"""文献計画 便 D（前半）の検査。`HANDOFF_20260907_LIT_D.md` §4 の T-L1〜T-L8。

この便は**測る道具を作る便**である。したがって固定するのは「強くなったか」ではなく、
道具が正しく数えているかと、**既定の挙動が 1 ビットも変わっていないこと**である。

守るもの:

1. 区間の計算が手計算と合う（T-L1）——n が小さい勝率を点推定で語らないための土台
2. 由来（provenance）が測定結果に必ず付き、同じモデルなら同じ sha256 になる（T-L2）
3. `--by-legal` を付けないときの `diag_optimism` の出力が**バイト単位で**従来と同じ（T-L3）
4. 対人記録に欄を 1 つ足しても再生が壊れず、古い記録も読める（T-L4）
5. 行列ゲームの解法（RM+）が既知の解と合い、**最終反復ではなく平均戦略**を返す（T-L5）
6. 透視カウンターが本当に透視しており、かつ**どの登録簿にも載っていない**（T-L6・D-026）
7. 試作の新しい選び方（`regret` / `softfloor`）が定義どおりに選ぶ（T-L7）
8. fingerprint が不変（T-L8）

`meicho_rs` が要る検査は、無い環境では理由つきで skip する。**skip は「通った」ではない。**
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from experiments.arena import load_deck, mirror_config                    # noqa: E402
from meicho.drlnet import random_net                                      # noqa: E402
from meicho.engine import legal_actions                                   # noqa: E402
from meicho.planner import PlannerAgent                                   # noqa: E402
from meicho.state import Phase                                            # noqa: E402

SD001 = load_deck("SD001")
CONFIG = mirror_config(SD001)
POOL = SD001["action_deck"]
HUMAN_GAMES = os.path.join(os.path.dirname(__file__), "..", "results", "human_games")


def _rand_net_path(tmp_path, name="lit_d.json", seed=101, hidden=24) -> str:
    net = random_net(seed=seed, hidden=hidden)
    path = str(tmp_path / name)
    net.save(path)
    return path


# ===================================================== T-L1 区間（D-1）
def test_wilson_and_clopper_pearson_known_values():
    """§3.1 の検算値。**小数第 3 位まで**手計算と一致すること。

    n=4・0 勝という「何も言えないように見える」データから、
    「勝率は 0.602 を上回らない」という**言えること**を取り出すのがこの道具の役目である。
    """
    from human_games_ci import clopper_pearson, wilson

    lo, hi = wilson(0, 4)
    assert round(lo, 3) == 0.000 and round(hi, 3) == 0.490
    lo, hi = clopper_pearson(0, 4)
    assert lo == 0.0 and round(hi, 3) == 0.602

    lo, hi = wilson(0, 10)
    assert round(lo, 3) == 0.000 and round(hi, 3) == 0.278
    lo, hi = clopper_pearson(0, 10)
    # 厳密値は 1 − 0.025^(1/10) = 0.3084971…。引継ぎ書 §3.1 の検算値は「0.309」だが、
    # これは 0.3085 を切り上げたもので、小数第 3 位に丸めると 0.308 である。
    # **式のほうが正しい**（`1 − 0.025^(1/n)` は閉じた形で確かめられる）ので、
    # ここは厳密値で固定し、食い違いは LIT_NOTES.md に残す。
    assert lo == 0.0 and abs(hi - (1.0 - 0.025 ** 0.1)) < 1e-12
    assert round(hi, 3) == 0.308

    lo, hi = wilson(4, 4)
    assert round(lo, 3) == 0.510 and round(hi, 3) == 1.000
    lo, hi = clopper_pearson(4, 4)
    assert round(lo, 3) == 0.398 and hi == 1.0

    lo, hi = wilson(50, 100)
    assert round(lo, 3) == 0.404 and round(hi, 3) == 0.596


def test_ci_symmetry_and_degenerate_n():
    """x=0 と x=n は鏡（片方を 1 から引くともう片方）。n=0 では落ちずに「なし」を返す。"""
    from human_games_ci import clopper_pearson, wilson

    for n in (1, 3, 7, 25):
        lo0, hi0 = wilson(0, n)
        lon, hin = wilson(n, n)
        assert abs(lo0 - (1.0 - hin)) < 1e-12
        assert abs(hi0 - (1.0 - lon)) < 1e-12
        clo0, chi0 = clopper_pearson(0, n)
        clon, chin = clopper_pearson(n, n)
        assert abs(chi0 - (1.0 - clon)) < 1e-9
        assert abs(clo0 - (1.0 - chin)) < 1e-9
    assert wilson(0, 0) is None
    assert clopper_pearson(0, 0) is None


def test_clopper_pearson_contains_wilson_at_the_tails():
    """0 勝・全勝では Clopper-Pearson のほうが**必ず広い**（だから判断に使う）。"""
    from human_games_ci import clopper_pearson, wilson
    for n in (2, 4, 10, 40):
        assert clopper_pearson(0, n)[1] > wilson(0, n)[1]
        assert clopper_pearson(n, n)[0] < wilson(n, n)[0]


# ------------------------------------------------- T-L1b 記録から数える
@pytest.mark.skipif(not os.path.isdir(HUMAN_GAMES), reason="対人の記録が無い環境")
def test_human_games_ci_reads_records():
    """記録を相手の版ごとに数え、混在の注意書きが出る。

    **局数は増えていくので固定しない**（便 D 後半で 4 局 → 8 局になった）。
    固定するのは (a) 相手ごとに分けて数えていること、(b) 混在の注意書き、
    (c) **もう増えない過去の版**の数字である。9/3 以前の `planner_vb3` の 2 局は
    アプリの相手が別の版に替わった以上もう増えないので、そこは値で固定してよい。
    """
    import human_games_ci as hgc

    out = hgc.summarise(os.path.join(os.path.dirname(__file__), "..", "results"))
    overall = out["overall"]
    by = out["by_opponent"]
    assert overall["n"] == sum(b["n"] for b in by.values())
    assert overall["wins_ai"] == sum(b["wins_ai"] for b in by.values())
    assert len(by) >= 3
    assert out["mixed_opponents"] is True
    # 過去の版（2026-09-03 の 2 局・AI 0 勝）はもう増えない
    vb3 = by["planner_vb3"]
    assert vb3["n"] == 2 and vb3["wins_ai"] == 0
    assert round(vb3["wilson"][1], 3) == 0.658
    assert round(vb3["cp"][1], 3) == 0.842
    text = hgc.render(out)
    assert "近似" in text                      # 混在の注意書き
    assert f"{overall['cp'][1]:.3f}" in text   # 上端が本文に出る


# ===================================================== T-L2 由来（D-2 / D-3）
def test_provenance_block_is_stable_and_complete(tmp_path):
    """同じファイルなら同じ sha256。3 つのモデルが揃う。engine の綴りは 2 択だけ。"""
    import provenance

    v = _rand_net_path(tmp_path, "v.json", seed=11)
    p = _rand_net_path(tmp_path, "p.json", seed=12)
    o = _rand_net_path(tmp_path, "o.json", seed=13)
    kw = {"extra_turns": 1, "value_net": v, "opp_policy_net": o, "policy_net": p}

    a = provenance.block(kw, "rust", (650000, 650199), label="test")
    b = provenance.block(kw, "rust", (650000, 650199), label="test")
    assert a["models"] == b["models"]
    assert set(a["models"]) == {"value_net", "opp_policy_net", "policy_net"}
    for m in a["models"].values():
        assert len(m["sha256"]) == 64 and int(m["sha256"], 16) >= 0
        assert m["bytes"] > 0
    # 中身が違えば sha256 も違う
    assert a["models"]["value_net"]["sha256"] != a["models"]["policy_net"]["sha256"]
    assert a["band"] == [650000, 650199]
    assert a["rules_version"] == "v0.11"
    # kwargs に**絶対パスを残さない**（環境をまたいで再現できなくなる・C-1 の教訓）。
    # 中身の同一性は sha256 が担うので、名前はファイル名だけでよい。
    assert a["kwargs"]["value_net"] == os.path.basename(v)
    assert a["models"]["value_net"]["file"] == os.path.basename(v)
    assert a["engine"] == "rust" and isinstance(a["rust_features"], list)
    assert provenance.block({}, "python", None)["rust_features"] is None
    with pytest.raises(ValueError):
        provenance.block({}, "cpython", None)


def test_provenance_labels_the_champion():
    """kwargs が champion と一致するときは、その名前が label に入る。"""
    import champion as chmod
    import provenance

    # 名前は直書きしない。**アプリの既定（＝現 champion の登録名）と一致すること**を見る
    # ——`provenance.py` の表示名の対応表を交代で直し忘れると、ここが落ちる（便 E-0）。
    from webapp import agents as wagents
    want = f"champion:{wagents.DEFAULT_OPPONENT}"
    blk = provenance.block(chmod.kwargs_for("SD001"), "rust", None)
    assert blk["label"] == want
    other = provenance.block({**chmod.kwargs_for("SD001"), "opp_mix": 1.0}, "rust", None)
    assert other["label"] != want


def test_provenance_tolerates_a_missing_model_file(tmp_path):
    """モデルが見つからないときも落ちない（**黙って捨てず、その旨を残す**）。"""
    import provenance
    blk = provenance.block({"value_net": str(tmp_path / "nope.json")}, "python", None)
    assert blk["models"]["value_net"]["sha256"] is None
    assert blk["models"]["value_net"].get("error")


def test_measurement_outputs_carry_provenance(tmp_path):
    """測定を組み立てる 4 本が `provenance` を持ち、既存のキーを落としていない。"""
    import champion as chmod
    import champion_challenge_vb as ccv
    import eval_vb
    import ladder as ladmod
    import probe_d065

    # eval_vb: 新旧それぞれの由来
    out = eval_vb.result_skeleton(deck="SD001", k=4, base=530000, null=False,
                                  label_new="新", label_old="前", new_net=None,
                                  old_net=None, loop=2, n=1200, anchor_n=600,
                                  new_kw={"value_net": "drl_sd001_vc4.json"},
                                  old_kw={"value_net": "drl_sd001_vb3.json"})
    for key in ("deck", "iter", "seed0", "null", "new", "old", "n", "anchor_n", "runs"):
        assert key in out, key
    assert "provenance_new" in out and "provenance_old" in out
    assert out["provenance_new"]["engine"] == "rust"

    # probe_d065 / champion_challenge_vb / ladder
    champ = chmod.kwargs_for("SD001")
    blk = probe_d065.provenance_for("a15", champ, {"opp_mix": 1.0}, 610000, 1200)
    assert set(blk) == {"cand", "base"}
    assert blk["cand"]["band"] == [610000, 611199]
    assert blk["cand"]["engine"] == "rust"
    assert blk["cand"]["models"]["value_net"]["sha256"] is not None
    from webapp import agents as wagents
    blk = ccv.provenance_for(champ, {**champ, "opp_mix": 1.0}, 550000, 1200)
    assert set(blk) == {"champion", "challenger"}
    assert blk["champion"]["label"] == f"champion:{wagents.DEFAULT_OPPONENT}"
    # D-072 判断 6: どの機械で・何並列で回したかが由来に入る
    assert blk["champion"]["extra"]["host"] and "workers" in blk["champion"]["extra"]
    g = ladmod.load_gauntlet("core5")
    blk = ladmod.provenance_for(g, "rust", 80000)
    assert set(blk) == set(g["agents"])
    for name, b in blk.items():
        assert b["engine"] == "rust" and b["band"] is not None


# ===================================================== T-L3 楽観の層別（D-6）
def _fake_records(n=4000, seed=7, n_acts=3, fresh_frac=0.5, opposite_strata=True,
                  legal_sizes=(1, 2, 3, 4, 6, 9)):
    """検査用の記録（`test_d065.py::_fake_records` の型）。

    ただし**決定ごとに「点数の付いた候補の数」を変える**——これが `--by-legal` の層である。
    番兵（-inf 相当の `-9.0` ではなく `NaN`）で「点数を付けなかった候補」を表す。
    """
    from meicho.drl_data import Records
    from meicho.encode import ACT_CODE_LEN, OBS_DIM
    rng = np.random.RandomState(seed)
    phase = np.where(rng.rand(n) < 0.5, 2, 3).astype(np.int8)
    turn = (rng.rand(n) < 0.5).astype(np.int8)
    obs = np.zeros((n, OBS_DIM), np.int8)
    obs[:, 0] = rng.randint(-100, 100, n)
    obs[:, 14] = turn
    v = rng.randn(n).astype(np.float32)
    sign = np.where(turn == 1, 1.0, -1.0) if opposite_strata else np.ones(n)
    p = 1.0 / (1.0 + np.exp(-3.0 * sign * v))
    z = (rng.rand(n) < p).astype(np.float32)
    n_legal = np.asarray([legal_sizes[i % len(legal_sizes)] for i in range(n)], np.int16)
    n_legal = np.minimum(n_legal, n_acts if n_acts >= max(legal_sizes) else n_acts)
    chosen = np.zeros(n, np.int16)
    scores = np.full(n * n_acts, np.nan, np.float32)
    for i in range(n):
        k = int(n_legal[i])
        s = np.full(n_acts, np.nan, np.float32)
        s[:k] = rng.randn(k).astype(np.float32) - 1.0
        s[0] = v[i]                            # 選んだ手が最大になるように置く
        chosen[i] = 0
        scores[i * n_acts:(i + 1) * n_acts] = s
    fresh = np.full(n, np.nan, np.float32)
    m = rng.rand(n) < fresh_frac
    fresh[m] = (v[m] - 0.5).astype(np.float32)
    off = np.arange(n + 1, dtype=np.int64) * n_acts
    acts = np.zeros((n * n_acts, ACT_CODE_LEN), np.int8)
    for j in range(n_acts):
        acts[j::n_acts, 0] = j % 5
        acts[j::n_acts, 1] = (j * 3) % 7
    return Records(n=n, seed=np.arange(n, dtype=np.int64), step=np.zeros(n, np.int32),
                   turn=np.zeros(n, np.int16), pi=np.zeros(n, np.int8), phase=phase,
                   n_acts=np.full(n, n_acts, np.int16), chosen=chosen, z=z, fresh=fresh,
                   obs=obs, act_off=off, acts_flat=acts, scores_flat=scores)


def test_diag_optimism_by_legal_partitions_the_decisions(monkeypatch):
    """層別の件数の合計が全体と一致し、**層は重ならない**。

    `diag_optimism` は `drl_train`（torch を要る）から較正の関数を借りているので、
    **torch が無い環境では skip する**（`test_d065._needs_torch` と同じ約束）。
    マスターの PC は学習を回さないので torch が無いのが正常であり、そこで**落ちる**のは
    検査の書き方が悪い。**skip は「通った」ではない**——作業環境では torch を入れて通す。
    """
    pytest.importorskip("torch")
    import experiments.diag_optimism as diag

    r = _fake_records(n=1200, seed=61, n_acts=9)
    monkeypatch.setattr(diag, "files_of", lambda *a, **k: ["dummy"])
    monkeypatch.setattr(diag, "read_records", lambda *a, **k: r)
    out = diag.collect("dummy", None, by_legal=True)
    rows = out["rows_by_legal"]
    total = out["rows"][0]["n"]
    assert sum(x["n"] for x in rows) == total
    keys = [x["key"] for x in rows]
    assert len(keys) == len(set(keys))
    # 「探索なし」（点数が 1 つ以下）の行が独立してあること
    assert any(x["key"] == "none" for x in rows)
    for x in rows:
        if x["key"] != "none":
            assert x["n_root"] == x["n"]        # 探索した決定は必ず root を持つ


def test_diag_optimism_default_output_is_byte_identical(monkeypatch):
    """`--by-legal` を**付けない**ときの JSON と表は、従来と 1 バイトも変わらない。

    torch が無い環境では skip（理由は上の検査と同じ）。
    """
    pytest.importorskip("torch")
    import experiments.diag_optimism as diag

    r = _fake_records(n=800, seed=63, n_acts=9)
    monkeypatch.setattr(diag, "files_of", lambda *a, **k: ["dummy"])
    monkeypatch.setattr(diag, "read_records", lambda *a, **k: r)
    out = diag.collect("dummy", None)
    assert "rows_by_legal" not in out           # 既定では**書かない**
    a = json.dumps(out, ensure_ascii=False, sort_keys=True).encode()

    out2 = diag.collect("dummy", None, by_legal=False)
    b = json.dumps(out2, ensure_ascii=False, sort_keys=True).encode()
    assert a == b
    # 表も同じ（`--by-legal` のときだけ追記される）
    assert diag.render(out) == diag.render(out2)
    assert "合法手" not in diag.render(out)
    assert "合法手" in diag.render(diag.collect("dummy", None, by_legal=True))


# ===================================================== T-L4 対人記録（D-7）
def _auto_play_one_game(opponent="planner", seed=130900, human_seat=0,
                        rng_seed=7, max_moves=4000):
    """アプリのセッションで 1 局を最後まで自動で打つ（`test_webapp.py::drive` の型）。

    人間側は疑似乱数で合法手を選ぶ。相手は既定で素の計画探索
    ——**対抗で 2 手以上を見比べる**（`ai_clash` が付く）ことが要るだけで、
    現 champion である必要は無い。速いほうを使う。
    """
    import random as _random

    from webapp import agents as wagents
    from webapp.session import Session

    ai_seed = seed * 2 + (1 - human_seat)
    sess = Session(f"lit_d{seed}", CONFIG, POOL, seed, human_seat, opponent,
                   wagents.build(opponent, POOL, ai_seed), ai_seed)
    rng = _random.Random(rng_seed)
    for _ in range(max_moves):
        if sess.finished or sess.error:
            break
        acts = sess.legal()
        if not acts:
            break
        sess.play(rng.randrange(len(acts)), sess.ply)
    assert not sess.error, sess.error
    assert sess.finished, "対局が終わらなかった"
    return sess


def test_record_carries_ai_clash_and_still_replays():
    """AI の対抗の行に `ai_clash` が残り、再生が `RecordMismatch` を出さない。"""
    from webapp import record as wrec
    sess = _auto_play_one_game()
    rec = wrec.to_record(sess)
    clash_rows = [r for r in rec["actions"]
                  if r["by"] == "ai" and r["phase"] == Phase.CLASH_SUBMIT.value]
    assert clash_rows, "AI の対抗の行が無い（局の選び方が悪い）"
    assert any("ai_clash" in r for r in clash_rows), "ai_clash が 1 行も残っていない"
    for r in clash_rows:
        c = r.get("ai_clash")
        if c is None:
            continue                      # 合法手 1 つの対抗は探索しない
        assert set(c) == {"acts", "totals", "chosen"}
        assert len(c["acts"]) == len(c["totals"]) >= 2
        assert 0 <= c["chosen"] < len(c["acts"])
        assert all(isinstance(x, float) for x in c["totals"])
    # 人間の行には付けない
    assert all("ai_clash" not in r for r in rec["actions"] if r["by"] == "human")
    wrec.verify(rec, sess.config)         # 一致しなければ RecordMismatch


def test_ai_clash_belongs_to_its_own_position():
    """`ai_clash` が**その行の局面のもの**であること（前の対抗の使い回しでないこと）。

    ここが要るのは、探索器が合法手 1 つの対抗では早く戻って `last_clash` を書かないからで、
    消し忘れると**別の局面の候補表が別の行に付く**。行としては読めるので、
    「付いているか」だけを見る検査は素通りしてしまう（実際に素通りした）。

    そこで記録をもう一度たどり直し、各 `ai_clash` について
    「候補の数がその局面の合法手の数と同じ」かつ「`chosen` が指す手が実際に打った手」
    であることを確かめる。使い回しならまず通らない。
    """
    from meicho.engine import apply, decision_players, initial_state, outcome
    from webapp import record as wrec

    # seed 130933 は **AI の対抗のうち 2 つが「合法手 1 つ」** になる局である。
    # そこで探索器は早く戻り `last_clash` を書かないので、消し忘れがあると
    # 前の対抗の候補表がその行に付く。**この局でないとその穴を突けない。**
    sess = _auto_play_one_game(seed=130933)
    rec = wrec.to_record(sess)
    clash_rows = [r for r in rec["actions"]
                  if r["by"] == "ai" and r["phase"] == Phase.CLASH_SUBMIT.value]
    assert any("ai_clash" not in r for r in clash_rows), (
        "この局には「合法手 1 つの対抗」が無い。消し忘れの穴を突けないので seed を選び直すこと")
    agents = [wrec.ReplayAgent(rec["actions"], 0), wrec.ReplayAgent(rec["actions"], 1)]
    st = initial_state(sess.config, rec["seed"])
    idx = 0
    checked = 0
    while outcome(st) is None and idx < len(rec["actions"]):
        need = decision_players(st)
        if not need or all(agents[pi].exhausted for pi in need):
            break
        acts = {pi: agents[pi].act(st, pi) for pi in need}
        for pi in sorted(acts):
            row = rec["actions"][idx]
            idx += 1
            c = row.get("ai_clash")
            if c is None:
                continue
            legal = legal_actions(st, row["seat"])
            assert len(c["acts"]) == len(legal), (
                f"ply {row['ply']}: 候補の数が合わない "
                f"（記録 {len(c['acts'])} ≠ 合法手 {len(legal)}）= 前の対抗の使い回し")
            assert legal[c["chosen"]] == row["action"], (
                f"ply {row['ply']}: chosen が実際に打った手を指していない")
            checked += 1
        st = apply(st, {pi: acts[pi] for pi in sorted(acts)})
    assert checked >= 1, "ai_clash の付いた行が 1 つも無かった"


def test_old_records_without_ai_clash_still_replay():
    """`ai_clash` を落とした古い形式の記録もそのまま読める（後方互換）。"""
    from webapp import record as wrec
    sess = _auto_play_one_game(seed=130901)
    rec = wrec.to_record(sess)
    old = dict(rec, actions=[{k: v for k, v in r.items() if k != "ai_clash"}
                             for r in rec["actions"]])
    assert wrec.verify(old, sess.config)["winner"] == rec["result"]["winner"]
    assert wrec.APP_VERSION == "1"        # 欄の追加は後方互換なので版は上げない


def test_last_clash_is_recorded_by_the_agent():
    """`greedy._clash` が `last_clash` を残す。**戻り値は変わらない。**"""
    from meicho.engine import initial_state, decision_players, apply
    import champion as chmod
    from meicho.drlnet import resolve_model
    kw = dict(chmod.kwargs_for("SD001"))
    for k in ("value_net", "opp_policy_net", "policy_net"):
        if k in kw:
            kw[k] = resolve_model(kw[k])
    a = PlannerAgent(651900, opp_decklist=POOL, **kw)
    b = PlannerAgent(651901, opp_decklist=POOL, **kw)
    s = initial_state(CONFIG, 651900)
    seen = False
    for _ in range(400):
        need = decision_players(s)
        if not need or s.outcome is not None:
            break
        if s.phase == Phase.CLASH_SUBMIT and len(legal_actions(s, 0)) >= 2:
            a.last_clash = None
            act = a.act(s, 0)
            c = a.last_clash
            assert c is not None
            assert len(c["acts"]) == len(c["totals"]) == len(legal_actions(s, 0))
            assert legal_actions(s, 0)[c["chosen"]] == act        # 記録は選んだ手を指す
            seen = True
            break
        s = apply(s, {q: (a if q == 0 else b).act(s, q) for q in sorted(need)})
    assert seen, "対抗の局面に届かなかった（seed を変えること）"


# ===================================================== T-L5 行列ゲームの解法（M2）
def test_rm_plus_matches_lp_on_small_games():
    """じゃんけん・鞍点つき 3×3・2×2 の混合で、**平均戦略**が既知の解と合う。"""
    from clash_mix_rate import solve_rmplus

    # (1) じゃんけん: 均衡は 1/3 ずつ・値 0
    rps = [[0.0, -1.0, 1.0], [1.0, 0.0, -1.0], [-1.0, 1.0, 0.0]]
    sol = solve_rmplus(rps, iters=4000)
    assert abs(sol["value"]) < 1e-3
    assert max(abs(x - 1 / 3) for x in sol["x"]) < 0.01
    assert max(abs(y - 1 / 3) for y in sol["y"]) < 0.01
    assert sol["exploitability"] < 1e-3
    assert sol["support_row"] == 3 and sol["support_col"] == 3

    # (2) 鞍点のある 3×3。行の最小値は [1, 2, 0] なので行 1 が最大最小（=2）、
    #     列の最大値は [5, 4, 2] なので列 2 が最小最大（=2）。両者が一致する
    #     ＝**純戦略の均衡**（行 1・列 2・値 2）。混ぜる必要が無い勝負である。
    saddle = [[3.0, 2.0, 1.0], [5.0, 4.0, 2.0], [4.0, 3.0, 0.0]]
    sol = solve_rmplus(saddle, iters=2000)
    assert abs(sol["value"] - 2.0) < 1e-3
    assert sol["x"][1] > 0.95 and sol["y"][2] > 0.95
    assert sol["support_row"] == 1 and sol["support_col"] == 1

    # (3) 2×2 の混合。均衡は行 (0.4, 0.6)・列 (0.4, 0.6)・値 0.2（手計算で確かめられる）
    two = [[2.0, -1.0], [-1.0, 1.0]]
    sol = solve_rmplus(two, iters=6000)
    assert abs(sol["value"] - 0.2) < 1e-3
    assert abs(sol["x"][0] - 0.4) < 0.01 and abs(sol["y"][0] - 0.4) < 0.01
    assert sol["support_row"] == 2 and sol["support_col"] == 2


def test_rm_plus_returns_the_average_not_the_last_iterate():
    """**最終反復ではなく平均戦略**を返していること。

    RM+ は「後悔の大きい手を次から多く出す」反復なので、**その時々の戦略は角
    （どれか 1 手に全振り）に寄る**。均衡になるのは全反復を通した平均のほうである。
    ここを取り違えると M2 の混合率がまるごと嘘になるので、わざと壊して落ちることを
    確かめてある（`x` の代わりに `last_x` を返すと下の 2 本とも落ちる）。
    """
    from clash_mix_rate import solve_rmplus
    two = [[2.0, -1.0], [-1.0, 1.0]]

    # 1 反復だけ回すと、次に出す戦略は**片方に全振り**。平均はまだ等重みである
    sol = solve_rmplus(two, iters=1, keep_last=True)
    assert max(sol["last_x"]) > 0.99
    assert max(sol["x"]) < 0.6

    # 十分回すと、平均は均衡 (0.4, 0.6) に寄るが、その時々の戦略は寄りきらない
    sol = solve_rmplus(two, iters=400, keep_last=True)
    assert abs(sol["x"][0] - 0.4) < 0.01
    assert abs(sol["last_x"][0] - 0.4) > 0.03


def test_clash_mix_rate_counts():
    """手作りの行列 3 つで、混合率・利得幅・一致率の数え方を固定する。"""
    from clash_mix_rate import summarise_matrix

    pure = summarise_matrix([[3.0, 2.0, 1.0], [5.0, 4.0, 2.0], [4.0, 3.0, 0.0]],
                            argmax_row=1, iters=2000)
    assert pure["mixed_row"] is False and pure["mixed_col"] is False
    assert pure["support_row"] == 1
    assert abs(pure["spread"] - 5.0) < 1e-9            # 最大 5 − 最小 0
    assert abs(pure["gain_over_pure"]) < 1e-3          # 混合で得していない
    assert pure["agrees_with_argmax"] is True          # 均衡の最良手 = 行 1 = argmax
    assert pure["converged"] is True

    mixed = summarise_matrix([[0.0, -1.0, 1.0], [1.0, 0.0, -1.0], [-1.0, 1.0, 0.0]],
                             argmax_row=0, iters=4000)
    assert mixed["mixed_row"] is True and mixed["mixed_col"] is True
    assert mixed["support_row"] == 3
    assert abs(mixed["spread"] - 2.0) < 1e-9
    # じゃんけんは最良の純戦略の保証値が −1、均衡値が 0。混合で 1 だけ得している
    assert abs(mixed["gain_over_pure"] - 1.0) < 1e-3

    # 未収束の扱い（1 反復だけ・許容差をほぼ 0 に）。**黙って収束扱いにしない。**
    hard = summarise_matrix([[2.0, -1.0], [-1.0, 1.0]],
                            argmax_row=0, iters=1, tol=1e-9, retry_iters=1)
    assert hard["converged"] is False
    assert hard["exploitability"] > 0.1


# ===================================================== T-L6 透視カウンター（M7）
def test_peek_counter_best_responds_and_is_not_registered():
    """`peek` を与えると真の最良応答を選ぶ。`peek=None` なら親クラスと同じ手。

    **透視が効いていること**（親と違う手を選ぶ例が少なくとも 1 つあること）まで
    確かめる。ここを緩めると「peek を渡し忘れていても通る」検査になり、
    M7 の数字が「champion 同士の対局」に化ける（§8 の転びやすいところ）。
    """
    from meicho.engine import apply, decision_players, initial_state
    from peek_counter import PeekCounter, resolved_kwargs

    kw = resolved_kwargs("SD001")
    s = initial_state(CONFIG, 651900)
    a = PlannerAgent(651900, opp_decklist=POOL, **kw)
    b = PlannerAgent(651901, opp_decklist=POOL, **kw)
    differed = False
    checked = 0
    positions = 0
    # **対抗の局面を 1 つ見て終わりにしない。** もとは最初の対抗で `break` していたが、
    # 便 C の champion 交代（D-081 追記 1）で探索器が変わると、その 1 局面では
    # たまたま透視しても同じ手になり、「透視が効いていない」と誤って落ちた。
    # 透視が配線されていることを見たいのだから、**差が出る局面が 1 つでもあればよい**。
    # 局面数に上限を置くのは重いからである（1 局面あたり探索が 3 回走る）。
    MAX_POSITIONS = 6
    for _ in range(400):
        need = decision_players(s)
        if not need or s.outcome is not None:
            break
        if (s.phase == Phase.CLASH_SUBMIT and len(legal_actions(s, 0)) >= 2
                and positions < MAX_POSITIONS):
            positions += 1
            my_acts = legal_actions(s, 0)
            # 透視しないときの手（親クラスと同じであること）
            base = PeekCounter(651900, opp_decklist=POOL, **kw)
            assert base.peek is None
            base_act = base.act(s, 0)
            assert base_act == PlannerAgent(651900, opp_decklist=POOL, **kw).act(s, 0)
            ref = PeekCounter(651900, opp_decklist=POOL, **kw)
            for b_act in legal_actions(s, 1)[:3]:      # 3 通りで足りる（重いので絞る）
                pc = PeekCounter(651900, opp_decklist=POOL, **kw)
                pc.peek = b_act
                got = pc.act(s, 0)
                # 透視した手は、**真の局面の上で**その相手の手に対する最良応答である
                goal = ref._goal_turn(s, 0) if ref.align_leaves else None
                crn = ref._save_crn()
                vals = []
                for x in my_acts:
                    ref._restore_crn(crn)
                    vals.append(ref._score_clash(s, 0, x, b_act, goal))
                assert got == my_acts[max(range(len(vals)), key=lambda i: vals[i])]
                if got != base_act:
                    differed = True
                checked += 1
            if differed:
                break
        s = apply(s, {q: (a if q == 0 else b).act(s, q) for q in sorted(need)})
    assert checked >= 2, "対抗の局面に届かなかった"
    assert differed, (f"{positions} 局面・{checked} 通り試して、どれも親クラスと同じ手だった"
                      "（透視が効いていない）")


def test_peek_counter_is_not_in_any_registry():
    """**測定専用**（D-026）。champion・ガントレット・アプリのどこにも載っていない。"""
    import champion as chmod
    import registry
    from webapp import agents as wagents

    def _has_peek(x) -> bool:
        return "peek" in json.dumps(x, ensure_ascii=False, default=str).lower()

    assert not _has_peek(chmod.CHAMPIONS)
    gdir = os.path.join(os.path.dirname(__file__), "..", "experiments", "gauntlets")
    for name in sorted(os.listdir(gdir)):
        if name.endswith(".json"):
            with open(os.path.join(gdir, name), encoding="utf-8") as f:
                assert not _has_peek(json.load(f)), name
    assert not _has_peek(wagents.OPPONENTS)
    assert not _has_peek(sorted(registry.FACTORIES))
    for deck in ("SD001", "SD02"):
        assert not _has_peek(wagents.available(deck))


def test_play_game_peek_equals_play_game_without_peek():
    """透視を切った `PeekCounter` 同士なら、専用ループと `runner.play_game` が完全一致。

    ここが落ちるのは、行動の辞書を**席の昇順**で組んでいないときである
    （乱数の消費順が変わる・`webapp/session.py` §2.3 と同じ理由）。

    **わざと軽い探索器（素の計画探索）で回す。** 確かめているのは進行の組み立てであって
    エージェントの中身ではないし、champion（Python 版で 1 局 10〜20 秒）で 20 局回すと
    この検査 1 本で 5 分を超える。
    """
    from meicho.runner import play_game
    from peek_counter import PeekCounter, play_game_peek

    def mk(seed):
        return PeekCounter(seed, opp_decklist=POOL)

    for seed in range(651900, 651920):
        ags = [mk(seed * 2), mk(seed * 2 + 1)]
        want = play_game(CONFIG, ags, seed=seed)
        ags2 = [mk(seed * 2), mk(seed * 2 + 1)]
        got = play_game_peek(CONFIG, ags2, seed=seed, peek_seat=None)
        assert (got["winner"], got["turns"], got["steps"]) == \
               (want["winner"], want["turns"], want["steps"]), f"seed={seed}"
        assert got["life"] == want["life"]


# ===================================================== T-L7 試作の新しい選び方（A-下見）
def test_proto_regret_and_softfloor_rules():
    """`regret` は最大後悔が最小の手を選ぶ。`softfloor` は ε の両端で既存モードに一致する。"""
    from proto_matrix_clash import max_regret, softfloor_weights

    # 行 = 自分・列 = 相手。列ごとの最良は [3, 5]。
    #   行 0 の後悔 = max(3-3, 5-1) = 4
    #   行 1 の後悔 = max(3-2, 5-5) = 1  ← 最小
    m = [[3.0, 1.0], [2.0, 5.0]]
    r = max_regret(m)
    assert abs(r[0] - 4.0) < 1e-12 and abs(r[1] - 1.0) < 1e-12
    assert min(range(len(r)), key=lambda i: r[i]) == 1

    # totals から R を引く形（本体と同じ符号）で選ぶと行 1 になる
    totals = [-r[i] for i in range(len(r))]
    assert max(range(len(totals)), key=lambda i: totals[i]) == 1

    # softfloor(ε=1) は一様、softfloor(ε=0) は softmax(τ=1) そのもの
    sc = np.array([2.0, 0.0, -1.0])
    w1 = softfloor_weights(sc, eps=1.0, tau=1.0)
    assert max(abs(x - 1 / 3) for x in w1) < 1e-9
    w0 = softfloor_weights(sc, eps=0.0, tau=1.0)
    soft = np.exp(sc - sc.max()); soft /= soft.sum()
    assert max(abs(a - b) for a, b in zip(w0, soft)) < 1e-9
    # 中間は必ず一様と softmax の内分
    w5 = softfloor_weights(sc, eps=0.5, tau=1.0)
    for i in range(3):
        assert abs(w5[i] - (0.5 * soft[i] + 0.5 / 3)) < 1e-9
    assert abs(sum(w5) - 1.0) < 1e-12


def test_proto_modes_are_registered_and_defaults_unchanged():
    """新しいモードが一覧に入り、既存モードの並びは変わっていない（表の列がずれない）。"""
    import proto_matrix_clash as proto
    names = [m for m, _, _ in proto.MODES]
    assert names[:7] == ["argmax", "soft", "soft", "uniform", "mix", "minimax", "nash"]
    assert "regret" in names and "softfloor" in names
    assert len(proto.MODES) == 10
    # softfloor は ε の 2 通り（0.3 / 0.6）
    assert sorted(e for m, _, e in proto.MODES if m == "softfloor") == [0.3, 0.6]
    # 並列実行用の作り手も揃っている（`MAKERS` は ProcessPoolExecutor に渡す）
    for k in ("regret", "softfloor3", "softfloor6"):
        assert k in proto.MAKERS


# ===================================================== T-L8 既定不変
def test_defaults_unchanged_lit_d():
    """`bench_agents.py` の fingerprint 3 種が不変（素の計画探索を測る）。"""
    import bench_agents
    assert bench_agents.fingerprint("H", 50) == "773a71c15c5bc16e"
    assert bench_agents.fingerprint("G", 20) == "677f28cc3b6995ee"
    assert bench_agents.fingerprint("P", 10) == "6e39c2aa4b35d876"


def test_champion_fingerprint_unchanged_lit_d():
    """**便 D 当時の champion**（`planner_vb3cps`）の fingerprint（帯 471500..471509・**手順つき**）。

    **なぜ手順を書くか**: `D065_NOTES.md` に残っていた `f82625f68bb79a2d` は、
    どう作った値かが**どこにも書かれていない**（便 D で再現できなかった）。
    値だけあって手順が無い基準は、次に誰かが「合わない」と気付いたとき
    「壊れたのか、作り方が違うのか」を区別できない。ここで手順ごと固定する。

    手順: Rust 版で champion 同士のミラー 10 局（seeds 471500..471509）を回し、
    各局の digest（その局の全決定を畳み込んだ値）の列を sha256 して先頭 16 桁。
    """
    pytest.importorskip("meicho_rs")
    import hashlib

    from experiments.arena_rs import ensure_cards, series_rs_digest
    from tests.test_champion_vc4 import (OLD_CHAMPION_FINGERPRINT,
                                         OLD_CHAMPION_KWARGS, resolved_kwargs)
    ensure_cards()
    # **便 D 当時の champion（`planner_vb3cps`）の spec を明示**して固定する。
    # `champion.py` を動的に読むと、便 E-0 の交代でこの検査の意味が
    # 「便 D 当時の挙動の固定」から「今の champion の固定」に化けてしまう。
    sp = {"kind": "planner", "opp_decklist": POOL,
          **resolved_kwargs(OLD_CHAMPION_KWARGS)}
    out = series_rs_digest(sp, sp, 10, CONFIG, workers=2, seed0=471500)
    fp = hashlib.sha256(repr([r[4] for r in out]).encode()).hexdigest()[:16]
    assert fp == OLD_CHAMPION_FINGERPRINT, (
        "便 D 当時の champion の挙動が変わった。便 D は探索器を 1 つも触っていないので、"
        "ここが動いたら**止めて**原因を調べること")


def test_seed_bands_lit_d_registered():
    """§5 の帯が台帳にあり、`next_free` が進んでいる。既存の帯と重ならない。"""
    path = os.path.join(os.path.dirname(__file__), "..", "experiments", "seed_bands.json")
    with open(path, encoding="utf-8") as f:
        led = json.load(f)
    bands = led["bands"]
    want = [(650000, 650199), (650200, 650399), (650400, 650999),
            (651000, 651599), (651600, 651999)]
    have = {(b["start"], b["end"]) for b in bands}
    for w in want:
        assert w in have, f"帯 {w} が台帳に無い"
    assert led["next_free"] >= 652000
    # 重なりが無いこと（台帳全体の不変条件）
    ordered = sorted((b["start"], b["end"]) for b in bands)
    for (s0, e0), (s1, _) in zip(ordered, ordered[1:]):
        assert e0 < s1 or (s0, e0) == (s1, _), f"帯が重なっている: {(s0, e0)} と {s1}"
