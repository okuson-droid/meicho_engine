"""E-3（D-181・`GENERALIST_E3_DESIGN_20261027.md` §4・付録 A）の道具の検査: 測定の席の末尾 `+hist=<k>`。

`use_history`・`prior_strength`（B-3 の履歴モデル・D-032）と `bundle_p`（D-082）は Rust・Python に既にある。
ここで見るのは、測定の道具（`eval_s3_h2h`・`eval_s2_repr`）の席の書き方と、2 つを同時に使ったときの Python と Rust の一致である。

E3-1 席の末尾 `+hist=8` が spec の `use_history=True`・`prior_strength=8.0` になり、指紋の末尾に `+hist=8` が付く。
     `+bundle_p=`・`+views=2` と並べると全部が spec に入り、書く順に依らず指紋は bundle_p → hist → views の順になる。
     付けない席・E-1 の `+views=2` だけ・E-2 の `+bundle_p=0.75` だけの席の spec と指紋は従来のまま
E3-2 値が 0 以下・数でないとき、同じつまみを 2 回書いたとき、葉の V の無い席（netfree・空の候補）に付けたときは止める
E3-3 `+bundle_p=0.75+hist=8` と同じ引数で、Python の `PlannerAgent` と Rust の `PlannerAgent` が毎手同じ手を選ぶ
     （`bundle_p` と `use_history` を同時に使った一致の検査はこれまで無かった・設計書 §4.1 (4)）
E3-4 `+bundle_p=0.75+hist=8` の spec で `series_digest` を回すと、`+bundle_p=0.75` だけの spec と打ち方が変わる（口が繋がっている）

検査の対局は 988600..988699（kind=diag・D-181 で登録）で回す。
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))
sys.path.insert(0, _HERE)

from test_d065 import CONFIG, POOL, _match_py_rust, _rand_net_path, _rs_has_d065   # noqa: E402

SEED0 = 988600


def _mods():
    import eval_s2_repr as E
    import eval_s3_h2h as H
    return E, H


# ------------------------------------------------------------------ E3-1
def test_hist_side_syntax(tmp_path):
    E, H = _mods()
    vnet = _rand_net_path(tmp_path, "e3a.json", seed=81)
    pool = list(POOL)
    base_h, base_e = H._spec(vnet, pool), E._arm_spec("v", vnet, pool)
    assert "use_history" not in base_h and "prior_strength" not in base_h
    hist = dict(use_history=True, prior_strength=8.0)
    assert H._spec(vnet + "+hist=8", pool) == dict(base_h, **hist)
    assert E._arm_spec("v", vnet + "+hist=8", pool) == dict(base_e, **hist)
    assert H.side_sha(vnet + "+hist=8") == H.side_sha(vnet) + "+hist=8"
    assert E.arm_sha(vnet + "+hist=8") == E.arm_sha(vnet) + "+hist=8"
    every = dict(base_h, bundle_p=0.75, value_views=2, **hist)
    for text in (vnet + "+bundle_p=0.75+hist=8+views=2", vnet + "+views=2+hist=8+bundle_p=0.75",
                 vnet + "+hist=8+bundle_p=0.75+views=2"):
        assert H._spec(text, pool) == every
        assert H.side_sha(text) == H.side_sha(vnet) + "+bundle_p=0.75+hist=8+views=2"
    assert H.side_sha(vnet + "+hist=2.5") == H.side_sha(vnet) + "+hist=2.5"
    # E-1・E-2 の席の指紋は、それぞれの結果ファイルに書かれた形のまま
    assert H.side_sha(vnet) == H.sha16(vnet)
    assert H.side_sha(vnet + "+views=2") == H.sha16(vnet) + "+views=2"
    assert H.side_sha(vnet + "+bundle_p=0.75") == H.sha16(vnet) + "+bundle_p=0.75"
    assert H._spec(vnet + "+bundle_p=0.75", pool) == dict(base_h, bundle_p=0.75)


# ------------------------------------------------------------------ E3-2
@pytest.mark.parametrize("bad", ["+hist=0", "+hist=-1", "+hist=abc", "+hist=8+hist=8",
                                 "+bundle_p=0.75+hist=8+bundle_p=0.5", "+views=2+views=2"])
def test_hist_bad_values(tmp_path, bad):
    E, H = _mods()
    vnet = _rand_net_path(tmp_path, "e3b.json", seed=82)
    with pytest.raises(SystemExit):
        H._spec(vnet + bad, list(POOL))
    with pytest.raises(SystemExit):
        E._arm_spec("v", vnet + bad, list(POOL))


def test_hist_needs_value_net():
    E, H = _mods()
    for side in ("netfree+hist=8", "netfree_b+hist=8"):
        with pytest.raises(SystemExit):
            H._spec(side, list(POOL))
    with pytest.raises(SystemExit):
        E._arm_spec("v", "+hist=8", list(POOL))


# ------------------------------------------------------------------ E3-3
@pytest.mark.slow
def test_bundle_and_history_python_matches_rust(tmp_path):
    rs = _rs_has_d065()
    vnet = _rand_net_path(tmp_path, "e3c.json", seed=83)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet, bundle_p=0.75,
              use_history=True, prior_strength=8.0)
    _match_py_rust(rs, kw, seed=SEED0 + 10, max_steps=60)


# ------------------------------------------------------------------ E3-4
@pytest.mark.slow
def test_hist_spec_changes_play(tmp_path):
    rs = pytest.importorskip("meicho_rs")
    from arena_rs import PLANNER, ensure_cards
    from record_mix import NETFREE
    ensure_cards()
    E, H = _mods()
    vnet = _rand_net_path(tmp_path, "e3d.json", seed=84)
    opp = PLANNER(POOL, **NETFREE)

    def dig(side):
        return [r[4] for r in rs.series_digest(CONFIG.chara_decks, CONFIG.action_decks, H._spec(side, list(POOL)), opp,
                                               SEED0 + 20, 6, 2, 200, True)]
    assert dig(vnet + "+bundle_p=0.75+hist=8") != dig(vnet + "+bundle_p=0.75")
