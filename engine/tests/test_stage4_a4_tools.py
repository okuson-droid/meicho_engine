"""段階4 便 4-A4 の道具の検査（D-161・設計書 `GENERALIST_STAGE4_TEACHER_DESIGN_20261005.md` §6）。

A4-1 Rust `series_record(agents_follow_decks=True)`: A が常に deck_a を打つ。偶数シードの局は既定と同じ局、
     奇数シードの局は「デッキの並びを逆にした既定」の同じシードの局と同じ（digest・勝敗）。壊し方: 既定のままだと
     奇数シードの局が逆並びの局と一致しない（A が deck_b を打っている）
A4-2 `agents_follow_decks=False` を明示しても既定と記録のバイトが同じ。`record_seats` と同時に渡すと落ちる
A4-3 `record_mix`: 相手 `netfree` は葉の V なしの `NETFREE` そのもの。相手 `netfree` の異種のブロックは
     `agents_follow_decks: true` が無いと落ちる。付けたブロックの manifest は A（教師）の決定がすべて deck_a 側に数わる
A4-4 `make_s2_schedule --cross-opponent netfree`: 異種のブロックだけ相手が netfree・記録は a・`agents_follow_decks`。
     ミラーと錨は既定と同じ。既定（付けない）は従来の表とバイト単位で同じ
A4-5 `eval_s3_h2h`: `--target` はミラー 1 ブロック・最終評価のデッキは落とす。`netfree` の側は葉の V なし・指紋 None。
     `report --gate` は A 席の得点と組を単位の区間・「下端 > 0.5」

検査の対局は 897900..897999（kind=diag・D-161 で登録）で回す。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import make_s2_schedule as M                                           # noqa: E402

TARGET = "ENV_SANGE_RM_TSUBAKI"
OTHER = "ENV_SANGE_RF_ANKO"                    # 学習デッキ（異種の相手）
SEED0 = 897900                                 # 検査の帯（897000..897999・kind=diag・D-161）


@pytest.fixture(scope="module")
def env():
    with open(M.DEFAULT_ENV, encoding="utf-8") as f:
        return json.load(f)["decks_block"]


def _rs():
    rs = pytest.importorskip("meicho_rs")
    if "agents_follow_decks" not in rs.features():
        pytest.skip("入っている meicho_rs に agents_follow_decks が無い（再ビルドが要る）")
    from arena_rs import ensure_cards
    ensure_cards()
    return rs


def _cfg(a, b):
    from arena import load_deck, matchup_config
    da, db = load_deck(f"env/{a}"), load_deck(f"env/{b}")
    cfg = matchup_config(da, db)
    cfg.validate()
    return cfg, da, db


def _run(rs, tmp, a, b, seed0, n, tag, **kw):
    from arena_rs import GREEDY, HEURISTIC
    cfg, da, db = _cfg(a, b)
    res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, GREEDY(db["action_deck"]), HEURISTIC(),
                                  seed0, n, str(tmp / tag), 1, 200, True, False, True, **kw)
    return res, b"".join(open(f, "rb").read() for f in files)


# ------------------------------------------------------------------ A4-1・A4-2
def test_follow_decks_plays_deck_a_on_odd_seeds(tmp_path):
    rs = _rs()
    n = 4
    fol, _ = _run(rs, tmp_path, TARGET, OTHER, SEED0, n, "fol", agents_follow_decks=True)
    dflt, _ = _run(rs, tmp_path, TARGET, OTHER, SEED0, n, "def")
    rev, _ = _run(rs, tmp_path, OTHER, TARGET, SEED0, n, "rev")
    for k in range(n):
        if (SEED0 + k) % 2 == 0:
            assert fol[k] == dflt[k]                     # 偶数シード: A は席 0 = deck_a（既定と同じ局）
        else:
            assert fol[k] == rev[k]                      # 奇数シード: A は席 1 で deck_a（逆並びの既定と同じ局）
            assert dflt[k][4] != rev[k][4]               # 壊し方: 既定の奇数シードは A が deck_b を打つ別の局


def test_follow_false_is_default_bytes_and_refuses_record_seats(tmp_path):
    rs = _rs()
    r0, b0 = _run(rs, tmp_path, TARGET, OTHER, SEED0 + 10, 2, "a")
    r1, b1 = _run(rs, tmp_path, TARGET, OTHER, SEED0 + 10, 2, "b", agents_follow_decks=False)
    assert r0 == r1 and b0 == b1
    with pytest.raises(ValueError):
        _run(rs, tmp_path, TARGET, OTHER, SEED0 + 10, 2, "c", agents_follow_decks=True, record_seats=(True, False))


# ------------------------------------------------------------------ A4-3
def test_record_mix_netfree_opponent_spec():
    import record_mix as R
    sp = R.opponent_spec("netfree", {"name": "netfree_v", "value_net": "x"}, [], "a", "b")
    assert sp == R.PLANNER([], **R.NETFREE)
    assert "value_net" not in sp


def test_record_mix_refuses_netfree_cross_without_follow():
    import record_mix as R
    base = {"deck_a": f"env/{TARGET}", "deck_b": f"env/{OTHER}", "seed0": SEED0, "n": 2, "opponent": "netfree",
            "record": "a"}
    with pytest.raises(SystemExit):
        R.check_schedule({"blocks": [base]})
    R.check_schedule({"blocks": [dict(base, agents_follow_decks=True)]})
    with pytest.raises(SystemExit):                      # 教師どうし・ミラーには付けない
        R.check_schedule({"blocks": [{"deck_a": f"env/{TARGET}", "deck_b": f"env/{TARGET}", "seed0": SEED0, "n": 2,
                                      "agents_follow_decks": True}]})


@pytest.mark.slow
def test_record_mix_follow_block_counts_teacher_on_deck_a(tmp_path):
    _rs()
    import record_mix
    from meicho.drl_data import read_records
    sch = {"name": "a4", "teacher": {"name": "netfree", "tau": 0.0},
           "blocks": [{"kind": "cross", "deck_a": f"env/{TARGET}", "deck_b": f"env/{OTHER}", "seed0": SEED0 + 20,
                       "n": 2, "opponent": "netfree", "record": "a", "agents_follow_decks": True}]}
    p = tmp_path / "a4.json"
    p.write_text(json.dumps(sch), encoding="utf-8")
    man = record_mix.main(["--schedule", str(p), "--out", str(tmp_path / "a4"), "--workers", "1"])
    blk = man["blocks"][0]
    assert blk["agents_follow_decks"] is True and blk["opponent"] == "netfree"
    dec = blk["decisions"]
    r = read_records(man["files"])
    assert dec["a_as_deck_a"] == r.n > 0 and dec["a_as_deck_b"] == dec["b_as_deck_a"] == dec["b_as_deck_b"] == 0
    assert blk["games"]["a_as_deck_a"] == 2 and blk["games"]["a_as_deck_b"] == 0
    assert (r.pi == (r.seed % 2)).all()                 # 記録は教師（A）の席: 偶数シードは席 0・奇数は席 1


# ------------------------------------------------------------------ A4-4
def _target(env, **kw):
    return M.build_target(env, target=TARGET, per={"mirror": 4, "cross": 2, "anchor": 2}, seed0=SEED0,
                          band_end=SEED0 + 99, name="t", **kw)


def test_cross_opponent_netfree_schedule(env):
    a, b = _target(env), _target(env, cross_opponent="netfree")
    assert len(a["blocks"]) == len(b["blocks"])
    for x, y in zip(a["blocks"], b["blocks"]):
        if x["kind"] == "cross":
            assert y["opponent"] == "netfree" and y["record"] == "a" and y["agents_follow_decks"] is True
            assert {k: v for k, v in y.items() if k not in ("opponent", "record", "agents_follow_decks")} == \
                   {k: v for k, v in x.items() if k != "record"}
        else:
            assert x == y
    assert b["generator"]["cross_opponent"] == "netfree" and "cross_opponent" not in a["generator"]
    assert not any("agents_follow_decks" in x for x in a["blocks"])
    import record_mix
    record_mix.check_schedule(b)
    with pytest.raises(SystemExit):
        _target(env, cross_opponent="heuristic")


def test_default_target_schedule_is_unchanged(env):
    assert _target(env) == _target(env, cross_opponent="teacher")


# ------------------------------------------------------------------ A4-5
def test_h2h_target_and_netfree_side(env):
    import eval_s3_h2h as H
    assert H.target_decks(TARGET, {"decks_block": env}) == [f"env/{TARGET}"]
    final = next(k for k, v in env.items() if v.get("split") == "final")
    with pytest.raises(SystemExit):
        H.target_decks(final, {"decks_block": env})
    assert H.side_sha("netfree") is None
    sp = H._spec("netfree", [])
    assert "value_net" not in sp


def test_h2h_gate():
    import eval_s3_h2h as H
    res = [[1.0, 10], [1.0, 10], [0.0, 10], [1.0, 10]] * 25          # 100 局・得点 0.75
    data = {"decks": [f"env/{TARGET}"], "n": 100, "pairs": {"g": {"a": {}, "b": {}}},
            "results": {f"g|env/{TARGET}|env/{TARGET}": res}}
    out = H.gate(data, "g")
    assert abs(out["score"] - 0.75) < 1e-12 and out["lo"] > 0.5 and out["verdict"] == "門を越える"
    data["results"][f"g|env/{TARGET}|env/{TARGET}"] = [[0.5, 10]] * 100
    out = H.gate(data, "g")
    assert out["verdict"].startswith("門を越えない")
    data["results"][f"g|env/{TARGET}|env/{TARGET}"] = [[1.0, 10]] * 98
    with pytest.raises(SystemExit):
        H.gate(data, "g")
