"""段階2 の組み合わせ表の生成器（`experiments/make_s2_schedule.py`・D-129）の検査。

生成器は `results/decksim/env_v1.json` の `decks_block`（24 デッキの lineage／group／split）から、
`experiments/record_mix.py` にそのまま渡せる組み合わせ表を作る。守らせる条項は次のとおり。

S-1 学習（split=train）のデッキだけを使う。調整・最終評価のデッキは**自分側にも相手側にも**出さない
    （計画書 `GENERALIST_AI_REVIEW_D086.md` §5.2「評価用デッキは学習対局の相手側にも出さない」）。
S-2 デッキ名は `env/<名前>`（`record_mix.deck_path` が `decklists/env/` を引く）。`decks` の鍵も同じ名前にし、
    lineage／group／split を manifest まで運ぶ（§5.4）。
S-3 配分はミラー 40%・異なる学習デッキ同士 40%・H／貪欲／素 planner 20%（§5.3 の出発点）。
    ブロックの局数は偶数（A/B が両方のデッキを半分ずつ持つ）。丸めの規則は `_even` の 1 か所。
S-4 H・貪欲・素 planner が相手のブロックは `record: "a"`（教師の席だけ記録・`VALUE_BOOTSTRAP_DESIGN.md` §6.3）。
S-5 シードは seed0 から隙間なく並べ、ブロック同士で重ならず、`--band-end` を越えない。
S-6 決定的（同じ引数なら出力はバイトまで同じ）。
S-7 `--only` は 1 デッキに関わるブロックだけに絞る（下見用）。学習でないデッキを指せば落ちる。
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import make_s2_schedule as M                                           # noqa: E402

ENV = os.path.join(ROOT, "results", "decksim", "env_v1.json")
SEED0, BAND_END = 900000, 999999        # 生成器の検査だけに使う数（対局は回さない。台帳の帯ではない）


@pytest.fixture(scope="module")
def env():
    with open(ENV, encoding="utf-8") as f:
        return json.load(f)


def _build(env, **kw):
    args = dict(n_total=10000, seed0=SEED0, band_end=BAND_END, only=None, pilot_n=None, name="t")
    args.update(kw)
    return M.build(env["decks_block"], **args)


def _names(sch):
    return {n for b in sch["blocks"] for n in (b["deck_a"], b["deck_b"])}


def test_only_train_decks_on_both_sides(env):
    """S-1: 調整・最終評価のデッキはどちらの席にも出ない。学習 16 はすべて出る。"""
    sch = _build(env)
    train = {f"env/{k}" for k, v in env["decks_block"].items() if v["split"] == "train"}
    assert len(train) == 16
    assert _names(sch) == train


def test_non_train_deck_is_dropped_even_if_marked_later(env):
    """S-1 をわざと壊す: 学習のデッキ 1 つを final に書き換えると、その名前はどこにも出なくなる。"""
    db = copy.deepcopy(env["decks_block"])
    victim = sorted(k for k, v in db.items() if v["split"] == "train")[0]
    db[victim]["split"] = "final"
    sch = M.build(db, n_total=10000, seed0=SEED0, band_end=BAND_END, only=None, pilot_n=None, name="t")
    assert f"env/{victim}" not in _names(sch)
    assert len(_names(sch)) == 15


def test_decks_meta_keys_match_block_names(env):
    """S-2: `decks` の鍵は `env/<名前>` で、lineage／group／split が env_v1 と一致する。"""
    sch = _build(env)
    assert set(sch["decks"]) == _names(sch)
    for name, meta in sch["decks"].items():
        src = env["decks_block"][name[len("env/"):]]
        assert meta == {"lineage": src["lineage"], "group": src["group"], "split": src["split"]}


def test_decks_exist_on_disk(env):
    """S-2: 名前は `record_mix.deck_path` で実在するファイルを指す。"""
    import record_mix
    for name in _names(_build(env)):
        assert os.path.exists(record_mix.deck_path(name)), name


def test_allocation_shares_and_even_blocks(env):
    """S-3: 各ブロックは偶数局。3 種の局数の割合は 40/40/20 から ±2 ポイント以内。"""
    sch = _build(env)
    tot = {"mirror": 0, "cross": 0, "anchor": 0}
    for b in sch["blocks"]:
        assert b["n"] >= 2 and b["n"] % 2 == 0, b
        tot[b["kind"]] += b["n"]
    n = sum(tot.values())
    assert n == sch["n_total_actual"]
    assert abs(tot["mirror"] / n - 0.4) <= 0.02
    assert abs(tot["cross"] / n - 0.4) <= 0.02
    assert abs(tot["anchor"] / n - 0.2) <= 0.02
    # 異なる学習デッキ同士は 16C2 = 120 組すべてが 1 回ずつ
    pairs = [(b["deck_a"], b["deck_b"]) for b in sch["blocks"] if b["kind"] == "cross"]
    assert len(pairs) == 120 == len(set(pairs))
    assert all(a < b for a, b in pairs)


def test_p_planned_sums_to_one(env):
    sch = _build(env)
    assert abs(sum(b["p_planned"] for b in sch["blocks"]) - 1.0) < 1e-9


def test_anchor_blocks_record_teacher_seat_only(env):
    """S-4: 相手が教師でないブロックは record=a、相手は heuristic/greedy/planner のどれか。"""
    sch = _build(env)
    anchors = [b for b in sch["blocks"] if b["kind"] == "anchor"]
    assert {b["opponent"] for b in anchors} == {"heuristic", "greedy", "planner"}
    assert all(b["record"] == "a" for b in anchors)
    for b in sch["blocks"]:
        if b["kind"] != "anchor":
            assert b.get("opponent", "teacher") == "teacher" and b["record"] == "both"


def test_seeds_contiguous_disjoint_and_within_band(env):
    """S-5: seed0 から隙間なく並び、重ならず、帯の終わりを越えない。"""
    sch = _build(env)
    s = SEED0
    for b in sch["blocks"]:
        assert b["seed0"] == s
        s += b["n"]
    assert s - 1 <= BAND_END


def test_band_overflow_is_refused(env):
    """S-5 をわざと壊す: 帯が足りなければ作らずに落ちる。"""
    with pytest.raises(SystemExit):
        _build(env, band_end=SEED0 + 999)


def test_deterministic_bytes(env):
    """S-6: 同じ引数なら出力はバイトまで同じ。"""
    a = M.dumps(_build(env))
    b = M.dumps(_build(env))
    assert a == b


def test_only_restricts_to_one_deck(env):
    """S-7: `--only` はその 1 デッキが出るブロックだけ。pilot_n は各ブロックの局数を上書きする。"""
    sch = _build(env, only="ENV_SANGE_RF_ANKO", pilot_n=2)
    me = "env/ENV_SANGE_RF_ANKO"
    assert sch["blocks"] and all(me in (b["deck_a"], b["deck_b"]) for b in sch["blocks"])
    kinds = [b["kind"] for b in sch["blocks"]]
    assert kinds.count("mirror") == 1 and kinds.count("cross") == 15 and kinds.count("anchor") == 3
    assert all(b["n"] == 2 for b in sch["blocks"])


@pytest.mark.parametrize("bad", ["ENV_SANGE_SK_CHIXIA", "ENV_SANGE_RF_TSUBAKI", "ENV_NOPE"])
def test_only_refuses_non_train(env, bad):
    """S-7 をわざと壊す: 最終評価・調整・存在しないデッキを `--only` に指すと落ちる。"""
    with pytest.raises(SystemExit):
        _build(env, only=bad, pilot_n=2)


def test_output_passes_record_mix_shape_check(env, monkeypatch):
    """出力は `record_mix.check_schedule` の形の検査を通る（帯の台帳の照会だけ差し替える）。"""
    import record_mix
    monkeypatch.setattr(record_mix, "check_record_band", lambda s: {})
    record_mix.check_schedule(_build(env))


def test_split_parts_cover_the_whole_schedule(env):
    """S-8（D-131）: 分けた組み合わせ表を並べると元の表に戻る（ブロック・シード・p_planned まで同じ）。"""
    sch = _build(env)
    parts = M.split(sch, 5)
    assert len(parts) == 5
    assert [b for p in parts for b in p["blocks"]] == sch["blocks"]
    assert all(p["decks"] == {d: sch["decks"][d] for d in sorted({x for b in p["blocks"]
                                                                   for x in (b["deck_a"], b["deck_b"])})}
               for p in parts)
    sizes = [sum(b["n"] for b in p["blocks"]) for p in parts]
    assert max(sizes) - min(sizes) <= max(b["n"] for b in sch["blocks"])      # 局数がほぼ均等
    assert [p["name"] for p in parts] == [f"t.p{i}of5" for i in range(5)]


def test_merge_manifests_sums_per_deck(tmp_path):
    """S-9（D-131）: manifest をまとめると、デッキ別の数は部分の和、ブロックは全部並ぶ。"""
    a = {"decks": {"x": {"sha256": "s", "games": 3, "seat_games": 4, "seat_games_teacher": 4,
                         "decisions_recorded": 10}},
         "games_by_opponent": {"teacher": 3}, "blocks": [{"i": 0, "n": 3}], "seconds": 1.0,
         "schedule_name": "t.p0of2", "schedule_sha256": "aa", "encoding_version": 6, "rules_version": "v0.18",
         "format": "MCDR v3"}
    b = {"decks": {"x": {"sha256": "s", "games": 2, "seat_games": 2, "seat_games_teacher": 1,
                         "decisions_recorded": 5},
                   "y": {"sha256": "t", "games": 2, "seat_games": 2, "seat_games_teacher": 1,
                         "decisions_recorded": 7}},
         "games_by_opponent": {"heuristic": 2}, "blocks": [{"i": 0, "n": 2}], "seconds": 2.0,
         "schedule_name": "t.p1of2", "schedule_sha256": "bb", "encoding_version": 6, "rules_version": "v0.18",
         "format": "MCDR v3"}
    paths = []
    for i, m in enumerate((a, b)):
        pth = tmp_path / f"m{i}.json"
        pth.write_text(json.dumps(m), encoding="utf-8")
        paths.append(str(pth))
    out = M.merge_manifests(paths)
    assert out["decks"]["x"]["games"] == 5 and out["decks"]["x"]["decisions_recorded"] == 15
    assert out["decks"]["x"]["seat_games_teacher"] == 5 and out["decks"]["y"]["games"] == 2
    assert out["games_by_opponent"] == {"teacher": 3, "heuristic": 2}
    assert out["games"] == 5 and len(out["parts"]) == 2


def test_merge_refuses_mixed_versions(tmp_path):
    """S-9 をわざと壊す: 符号化の版が違う manifest は混ぜない（DRL の決まり）。"""
    base = {"decks": {}, "games_by_opponent": {}, "blocks": [], "seconds": 0, "schedule_name": "n",
            "schedule_sha256": "x", "rules_version": "v0.18", "format": "MCDR v3"}
    paths = []
    for i, v in enumerate((6, 5)):
        pth = tmp_path / f"m{i}.json"
        pth.write_text(json.dumps(dict(base, encoding_version=v)), encoding="utf-8")
        paths.append(str(pth))
    with pytest.raises(SystemExit):
        M.merge_manifests(paths)
