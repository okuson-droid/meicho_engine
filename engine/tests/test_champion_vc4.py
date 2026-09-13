"""便 E-0（champion 交代の判定・V_4'）の検査。`HANDOFF_20260908_VC4_CHAMPION.md` §5。

固定するのは**結論（V_4' が強いか）ではなく前提**である。強さは §4.1 と §4.4 の測定が出す。
ここで守るのは 5 つ。

1. **塊に割っても一括と同じ数が出る**（`--budget-sec` の再開が数を壊さないこと）
2. **`lethal_uniform` は `value_net` と組でしか使えない**（便 A の判断①・D-071 裁定）
3. **古い wheel では Rust を要する検査が理由つきで skip になる**（既にある仕組みの確認）
4. **旧 champion の fingerprint は spec を明示して固定し続ける**（交代しても消さない）
5. **帯が台帳にある**

T-C5〜T-C8 は交代したあとの状態を固定する。**交代を済ませたので条件つきの skip は外した**
（`_has_swapped()` で skip する形にしていたが、それだと「`champion.py` を旧に戻す」という
まさに捕まえたい壊し方のときに検査ごと消えてしまう。わざと壊す確認で分かった・§5 の教訓）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from experiments.arena import load_deck, mirror_config                    # noqa: E402
from meicho.drlnet import random_net                                      # noqa: E402
from meicho.greedy import GreedyAgent                                     # noqa: E402
from meicho.planner import PlannerAgent                                   # noqa: E402

SD001 = load_deck("SD001")
CONFIG = mirror_config(SD001)
POOL = SD001["action_deck"]
_HERE = os.path.dirname(os.path.abspath(__file__))

# 旧 champion（`planner_vb3cps`）の spec を**明示**して持つ。`champion.py` を動的に読むと
# 交代した瞬間に「旧 champion の固定」が「新 champion の固定」に化けてしまう（§10-5）。
OLD_CHAMPION_KWARGS = {"extra_turns": 1,
                       "value_net": "drl_sd001_vb3.json",
                       "opp_policy_net": "drl_sd001_s1.json",
                       "opp_policy_root_only": True,
                       "choice_phases": True,
                       "solo_samples": 4,
                       "policy_net": "pi_small64_e10.json",
                       "policy_scope": "proxy"}
OLD_CHAMPION_FINGERPRINT = "7251a931d252a57a"
# 交代したときの新 champion（葉だけ V_4' に差し替えたもの）。
NEW_CHAMPION_KWARGS = {**OLD_CHAMPION_KWARGS, "value_net": "drl_sd001_vc4.json"}
# §4.1 で実際に取った値を入れる（交代する場合。取るまでは None＝T-C5 は skip）。
NEW_CHAMPION_FINGERPRINT: str | None = "9b5ad48d2de6a7e0"
# 輪 2 で V_4' を葉に積む反復の番号（`vb.kwargs_for("SD001", 5, loop=2)`）。
LOOP2_ITERATION_FOR_VC4 = 5
# 便 C の階段が champion に足したつまみ（D-081 追記 1）。輪 2 の探索器（`vb.py`）には無い。
BIN_C_KNOBS = ("known_hand", "world_weight", "weight_temp", "endgame_enum", "draw_buckets")
# 便 A 後半が champion に足したつまみ（D-082 追記 2）。これも `vb.py` には無い。
# **便ごとに分けて持つ**——どの便で増えたずれかが後から分かるようにするためである。
BIN_A2_KNOBS = ("bundle_p",)
# `vb.py`（輪 2 の探索器）に無い、champion 側だけのつまみ。増えたらここに足す。
NOT_IN_LOOP2_KNOBS = BIN_C_KNOBS + BIN_A2_KNOBS


def _rs():
    """Rust が便 A 以降であること。古ければ理由つきで skip（§4.0-4）。"""
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()
    if "lethal_uniform" not in rs.features():
        pytest.skip("Rust が便 A より古い（未再ビルド）")
    return rs


def resolved_kwargs(kw: dict) -> dict:
    """モデル名を実ファイルのパスに直した kwargs（他の検査からも使う）。"""
    from meicho.drlnet import resolve_model
    out = dict(kw)
    for k in ("value_net", "opp_policy_net", "policy_net"):
        if k in out:
            out[k] = resolve_model(out[k])
    return out


_resolved = resolved_kwargs                     # 旧名（このファイル内で使っている）


def _fingerprint(kw: dict) -> str:
    """§1 の手順: Rust 版・同型ミラー 10 局・seeds 471500..471509・workers=2・
    各局の digest 列を `sha256(repr(digests))` して先頭 16 桁（便 D §8.2）。"""
    from experiments.arena_rs import ensure_cards, series_rs_digest
    ensure_cards()
    sp = {"kind": "planner", "opp_decklist": POOL, **_resolved(kw)}
    out = series_rs_digest(sp, sp, 10, CONFIG, workers=2, seed0=471500)
    return hashlib.sha256(repr([r[4] for r in out]).encode()).hexdigest()[:16]


# ------------------------------------------------- T-C1 中断と再開が数を壊さない
def test_challenge_budget_resume_matches_one_shot(tmp_path):
    """`champion_challenge_vb.py` を n=6 一括と 3+3 で回し、勝ち数・決着数・digest が一致。

    各局はシードだけで決まるので、塊に割っても同じ局を同じ順に回すことになる。
    ここが壊れると `--budget-sec` の再開が「取りこぼし」か「二重に数える」に化ける。
    条件の鍵が違う途中経過には**足し込まない**ことも合わせて見る。
    """
    _rs()
    import champion_challenge_vb as ccv

    diff = json.dumps({"value_net": "drl_sd001_vc4.json"})
    one = str(tmp_path / "one.json")
    part = str(tmp_path / "part.json")
    common = ["--deck", "SD001", "--seed0", "665400", "--n", "6", "--workers", "2",
              "--challenger-json", diff, "--skip-audit"]

    assert ccv.main(common + ["--out", one, "--chunk", "6"]) == 0
    assert ccv.main(common + ["--out", part, "--chunk", "3"]) == 0
    a = json.load(open(one, encoding="utf-8"))
    b = json.load(open(part, encoding="utf-8"))
    for ra, rb in zip(a["runs"], b["runs"]):
        assert (ra["wins"], ra["decided"], ra["n"], ra["seed0"]) == \
               (rb["wins"], rb["decided"], rb["n"], rb["seed0"]), \
            f"{ra['name']}: 塊に割ると数が変わる"
    assert a["digest_hash"] == b["digest_hash"]
    # 完走したら途中経過は残らない
    assert not os.path.exists(os.path.splitext(part)[0] + ".resume.json")

    # 条件が違う途中経過には足し込まない（帯を変えて途中経過だけ置いてみる）
    rp = str(tmp_path / "mismatch.resume.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"key": {"deck": "SD001", "vb": None, "challenger_diff": None,
                           "seed0": 1, "n": 6, "retest": False},
                   "slots": {}}, f)
    with pytest.raises(SystemExit):
        ccv.main(common + ["--out", str(tmp_path / "x.json"), "--resume", rp])


# ------------------------------------ T-C2 判断①（lethal_uniform は value_net と組）
def test_planner_lethal_uniform_requires_value_net(tmp_path):
    """`lethal_uniform > 0` かつ `value_net` 無しは `ValueError`（便 A の判断①・D-071 裁定）。

    塞ぐのは **4 か所**: Python の `PlannerAgent`、Rust の `PlannerAgent`（クラス）、
    Rust の spec（`series` / `series_record` が通る道）。`GreedyAgent` は**許す**——
    切り替え規則そのものを素の尺度の上で単体検査する土台だからである
    （ただし champion 候補にもアプリの相手にもしない）。

    理由: 詰みの判定は `_score_clash(...) >= 1.0 − 1e-9` であり、これは葉の採点が
    **勝率の尺度**（決着済み = 1.0 / 0.0 / 0.5）であることに依存している。
    素の `evaluate`（±WIN = ±10000）では 1.0 は詰みを意味しないので、黙って別の意味で動く。
    """
    rs = _rs()
    vnet = str(tmp_path / "v.json")
    random_net(seed=71, hidden=16).save(vnet)

    with pytest.raises(ValueError, match="value_net"):
        PlannerAgent(0, lethal_uniform=0.5)
    with pytest.raises(ValueError, match="value_net"):
        rs.PlannerAgent(0, lethal_uniform=0.5)
    with pytest.raises(ValueError, match="value_net"):
        rs.series(CONFIG.chara_decks, CONFIG.action_decks,
                  {"kind": "planner", "opp_decklist": POOL, "lethal_uniform": 0.5},
                  {"kind": "planner", "opp_decklist": POOL}, 665500, 1)

    # 組で渡せば通る。既定（0.0）はもちろん通る。
    assert PlannerAgent(0, value_net=vnet, lethal_uniform=0.5).lethal_uniform == 0.5
    assert PlannerAgent(0).lethal_uniform == 0.0
    # `GreedyAgent` は許す（Python も Rust も）
    assert GreedyAgent(0, lethal_uniform=0.5).lethal_uniform == 0.5
    assert rs.GreedyAgent(0, lethal_uniform=0.5) is not None


# --------------------------------------- T-C3 古い wheel では理由つきで skip になる
def test_rust_feature_tests_skip_on_old_wheel(monkeypatch):
    """`features()` に `lethal_uniform` が無いとき、便 A の Rust 検査が skip になる。

    マスターの PC の wheel は便 4 のままなので、この仕組みが効いていないと
    「PC で検査が落ちた」という報告になる（§10-10）。**仕組みの確認であって、
    新しい機能の検査ではない。**
    """
    rs = _rs()
    import tests.test_lit_a as lit_a

    monkeypatch.setattr(rs, "features", lambda: ["d065_bin1"])
    for fn in (lit_a._rs_has_lit_a, _rs):
        with pytest.raises(pytest.skip.Exception) as e:
            fn()
        assert "便 A より古い" in str(e.value)


# ------------------------------------------- T-C4 旧 champion の fingerprint
def test_old_champion_fingerprint_pinned():
    """旧 champion（`planner_vb3cps`）の spec を**明示**して `7251a931d252a57a`。

    `champion.py` を動的に読むと、交代した瞬間にこの検査は「新 champion の固定」に化ける。
    **交代しても旧 champion の値は固定し続ける**——過去の勝率を読み直すための基準だからである。
    """
    _rs()
    assert _fingerprint(OLD_CHAMPION_KWARGS) == OLD_CHAMPION_FINGERPRINT


# ----------------------------------------- T-C5 新 champion の fingerprint（交代時）
def test_new_champion_fingerprint():
    """新 champion（`planner_vc4cps`）の fingerprint。手順は旧と同じ（§1）。"""
    _rs()
    assert _fingerprint(NEW_CHAMPION_KWARGS) == NEW_CHAMPION_FINGERPRINT


# ------------------------------- T-C6 champion と輪 2 の反復番号の一致（交代時）
def test_champion_matches_loop2_iteration5():
    """champion と輪 2 の探索器の関係を固定する。

    もとは**完全一致**を見ていた（`champion.kwargs_for("SD001")
    == vb.kwargs_for("SD001", 5, loop=2)`）。便 C の交代（2026-09-11・D-081 追記 1）で
    champion に `known_hand` / `endgame_enum` / `draw_buckets` の 3 つが増え、
    **`vb.py` は変えていない**ので、完全一致はもう成り立たない。

    守りたかったものは「葉の価値関数と相手モデルと代打ちが輪 2 の反復と食い違わないこと」
    である。そこで検査を**「champion 側だけのつまみを外せば完全一致」**に読み替える。
    つまみの一覧は定数で書いてあるので、つまみが増えたらここも意識して足すことになる——
    **2026-09-13 の便 A 後半の交代（D-082 追記 2）で実際に `bundle_p` が 1 つ増えた。**
    便ごとに分けて持っているので、どの便で開いたずれかが後から分かる。

    **これは「ずれてよい」という意味ではない。** 次に輪 2 を回すときに探索器を揃えるかは
    未決で、`TASKS.md` の判断が要る点に載せてある（`champion.py` の冒頭にも書いた）。
    """
    import champion as chmod
    import vb as vbmod
    got = chmod.kwargs_for("SD001")
    assert {k: v for k, v in got.items() if k not in NOT_IN_LOOP2_KNOBS} == \
        vbmod.kwargs_for("SD001", LOOP2_ITERATION_FOR_VC4, loop=2)
    # いま実際にずれているのは便 C の 3 つ ＋ 便 A 後半の 1 つだけであること（増えたら気づく）。
    assert sorted(k for k in got if k in NOT_IN_LOOP2_KNOBS) == \
        ["bundle_p", "draw_buckets", "endgame_enum", "known_hand"]


# ------------------------------ T-C7 core5 の agents がラダー v9 の記録と食い違わない
def test_core5_v10_agents_match_ladder_v9_record():
    """**ラダー v9 に居た体は、いまの core5 でも 1 文字も変わっていない。**

    もとは「v10 は組が v9 と同一（だからラダーを測り直さない）」を固定する検査だった。
    v11（便 C の交代判定・D-077 追記 4/5）で候補 `planner_vc4cps_kheb` を**足した**ので、
    「完全に同じ」はもう成り立たない。しかし守りたかったものは失われていない——
    **v9 の結果を使い回してよいかどうか**は「v9 に居た体の定義が変わっていないか」で決まる。
    そこで検査を「同一」から**「v9 の組は現行の部分集合で、共通の体は完全一致」**に読み替える。
    足された体があること自体は許すが、**古い体が 1 文字でも変われば落ちる**（`ladder.load_reusable`
    の拾う条件と同じ線を、こちら側からも固定しておく）。
    """
    with open(os.path.join(_HERE, "..", "experiments", "gauntlets", "core5.json"),
              encoding="utf-8") as f:
        g = json.load(f)
    with open(os.path.join(_HERE, "..", "results", "ladder.json"), encoding="utf-8") as f:
        recs = json.load(f)
    # **v9 の記録を版で選ぶ。** もとは「最後の core5 の記録」を取っていたが、
    # 2026-09-11 に v11 を回したので最後は v11 になった（D-081 追記 1）。
    # この検査が見たいのは「v9 に居た体が変わっていないか」なので、v9 を名指しで取る。
    v9 = [r for r in recs if r["gauntlet"] == "core5" and r.get("gauntlet_version") == 9]
    assert v9, "ラダー v9 の記録が results/ladder.json に無い"
    rec = v9[-1]
    # 記録側には `repr`（表示用）が足してあるので、組の同一性は factory と kwargs で見る。
    got = {n: {"factory": a["factory"], "kwargs": a.get("kwargs") or {}}
           for n, a in rec["agents"].items()}
    want = {n: {"factory": a["factory"], "kwargs": a.get("kwargs") or {}}
            for n, a in g["agents"].items()}
    missing = sorted(set(got) - set(want))
    assert not missing, f"ラダー v9 に居た体が現行の core5 から消えている: {missing}"
    changed = sorted(n for n in got if got[n] != want[n])
    assert not changed, f"ラダー v9 に居た体の定義が変わっている（使い回せない）: {changed}"
    added = sorted(set(want) - set(got))
    # 足された体があるなら、その体が絡む組は**新しく回す**（使い回せない）。
    #
    # もとは `added == ["planner_vc4cps_kheb"]` と 1 体を名指ししていた（書いた時点では
    # v9 以降に足された体がそれ 1 つだったため）。2026-09-12 に便 A 後半の候補
    # `planner_vc4cps_kheb_b75` を v13 で足したので落ちた。**この検査の意図は
    # 上の docstring のとおり「足されること自体は許す／古い体が 1 文字でも変われば落ちる」**
    # なので、そこに読み替える（消さない・D-082）。足された体は
    # **v9 以降の champion 候補の系統（`planner_vc4cps_kheb` から派生した名前）だけ**に限る。
    assert "planner_vc4cps_kheb" in added, f"v9 以降の候補が足されていない: {added}"
    unknown = [n for n in added if not n.startswith("planner_vc4cps_kheb")]
    assert not unknown, f"覚えのない体が足されている: {unknown}"
    # v12 で champion 欄が候補に移った（D-081 追記 1・マスター裁定 2026-09-11）。
    # v13 は便 A 後半の候補を足しただけで champion 欄は据え置き、
    # **v14 で champion 欄がその候補に移った**（D-082 追記 2・マスター裁定 2026-09-13）。
    assert g["version"] >= 14 and g["champion"] == "planner_vc4cps_kheb_b75"


# ---------------------------------------- T-C8 アプリの既定が新 champion（交代時）
def test_webapp_default_is_new_champion():
    """アプリの既定が**いまの** champion で、歴代の champion が一覧から消えていない。

    便 A 後半の交代（D-082 追記 2・2026-09-13）で既定は `planner_vc4cps_kheb_b75` になった。
    **歴代の champion は一覧から消さない**（過去の対人局を同じ相手で再現できなくなるため・§8.2）。
    """
    from webapp import agents as wagents
    assert wagents.default_for("SD001") == "planner_vc4cps_kheb_b75"
    avail = wagents.available("SD001")
    for name in ("planner_vc4cps_kheb", "planner_vc4cps", "planner_vb3cps",
                 "planner_vb3cps_lu50", "planner_vb3cps_m100"):
        assert name in avail, f"{name}（歴代 champion と便 A の候補）が消えている"


# ------------------------------------------------- T-C9 T-14 の局面は spec 明示で固定
@pytest.mark.skipif(
    not os.path.exists(os.path.join(_HERE, "..", "results", "human_games",
                                    "2026-09.jsonl")),
    reason="対人の記録が無い環境")
def test_t14_positions_pinned_to_explicit_specs():
    """T-14 の 2 局面で**旧 champion の spec**が当時どおり pass／音の形・回避を選ぶ。

    `champion.kwargs_for` を動的に読む書き方だと、交代した瞬間に `want_old` が
    新 champion の選択と食い違って落ちる（§10-4）。**新 champion の選択に合わせて
    `want_old` を書き換えてはいけない**——それは「直った」ではない。
    新 champion が何を選ぶかは §4.3 の診断が記録する（合否にしない）。
    """
    import tests.test_lit_a as lit_a
    want_old = {"g001": "pass", "g002": "音の形・回避"}
    pos = lit_a._human_clash_positions()
    assert len(pos) >= 2, f"回帰局面が足りない: {[p[0] for p in pos]}"
    kw = _resolved(OLD_CHAMPION_KWARGS)
    for gid, s, ai, seed in pos:
        a = PlannerAgent(seed, opp_decklist=POOL, **kw).act(s, ai)
        assert lit_a._submitted_name(s, ai, a) == want_old[gid], \
            f"{gid}: 旧 champion の挙動が変わった（{lit_a._submitted_name(s, ai, a)}）"


# ------------------------------------------------------------- T-C10 帯の登録
def test_seed_bands_vc4_registered():
    """§6 の帯（660000..665999）が台帳にあり、重なりが無く、`next_free` が進んでいる。"""
    path = os.path.join(_HERE, "..", "experiments", "seed_bands.json")
    with open(path, encoding="utf-8") as f:
        led = json.load(f)
    have = {(b["start"], b["end"]) for b in led["bands"]}
    assert (660000, 665999) in have, "便 E-0 の帯が台帳に無い"
    assert led["next_free"] >= 666000
    ordered = sorted((b["start"], b["end"]) for b in led["bands"])
    for (s0, e0), (s1, e1) in zip(ordered, ordered[1:]):
        assert e0 < s1 or (s0, e0) == (s1, e1), f"帯が重なっている: {(s0, e0)} と {(s1, e1)}"
