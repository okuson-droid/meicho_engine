"""E-2（D-179・`GENERALIST_WALL_READING_20261020.md` §7）の道具の検査: 測定の席の末尾 `+bundle_p=…`。

`bundle_p` そのもの（束ねた対抗ゲーム）は便 A 後半（D-082）で Rust・Python に入っており、`tests/test_lit_a2.py` が見る。
ここで見るのは、測定の道具（`eval_s3_h2h`・`eval_s2_repr`）の席の書き方だけである。

E2-1 席の末尾 `+bundle_p=0.75` が spec の `bundle_p=0.75` になり、指紋の末尾に `+bundle_p=0.75` が付く。
     `+views=2` と並べると両方が spec に入り、書く順に依らず指紋は bundle_p → views の順になる
E2-2 付けない席の spec と指紋は従来のまま。E-1 の `+views=2` だけの席の指紋も変わらない
E2-3 値が 0 以下・1 より大きい・数でないときと、葉の V の無い席（netfree・空の候補）に付けたときは止める
E2-4 `bundle_p=0.75` の spec で `series_digest` を回すと、付けない spec と打ち方が変わる（口が繋がっている）

検査の対局は 986300..986399（kind=diag・D-177 で登録）の 986350.. で回す。
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

from test_d065 import CONFIG, POOL, _rand_net_path   # noqa: E402

SEED0 = 986350


def _mods():
    import eval_s2_repr as E
    import eval_s3_h2h as H
    return E, H


# ------------------------------------------------------------------ E2-1・E2-2
def test_bundle_side_syntax(tmp_path):
    E, H = _mods()
    vnet = _rand_net_path(tmp_path, "e2a.json", seed=71)
    pool = list(POOL)
    base_h, base_e = H._spec(vnet, pool), E._arm_spec("v", vnet, pool)
    assert "bundle_p" not in base_h and "bundle_p" not in base_e
    assert H._spec(vnet + "+bundle_p=0.75", pool) == dict(base_h, bundle_p=0.75)
    assert E._arm_spec("v", vnet + "+bundle_p=0.75", pool) == dict(base_e, bundle_p=0.75)
    assert H.side_sha(vnet + "+bundle_p=0.75") == H.side_sha(vnet) + "+bundle_p=0.75"
    assert E.arm_sha(vnet + "+bundle_p=0.75") == E.arm_sha(vnet) + "+bundle_p=0.75"
    both = dict(base_h, bundle_p=0.75, value_views=2)
    for text in (vnet + "+bundle_p=0.75+views=2", vnet + "+views=2+bundle_p=0.75"):
        assert H._spec(text, pool) == both
        assert H.side_sha(text) == H.side_sha(vnet) + "+bundle_p=0.75+views=2"
    # E-1 の席（+views=2 だけ）の指紋は E-1 の結果ファイルに書かれた形のまま
    assert H.side_sha(vnet + "+views=2") == H.side_sha(vnet) + "+views=2"
    assert H.side_sha(vnet) == H.sha16(vnet)


# ------------------------------------------------------------------ E2-3
@pytest.mark.parametrize("bad", ["+bundle_p=0", "+bundle_p=1.5", "+bundle_p=-0.2", "+bundle_p=abc"])
def test_bundle_bad_values(tmp_path, bad):
    E, H = _mods()
    vnet = _rand_net_path(tmp_path, "e2b.json", seed=72)
    with pytest.raises(SystemExit):
        H._spec(vnet + bad, list(POOL))
    with pytest.raises(SystemExit):
        E._arm_spec("v", vnet + bad, list(POOL))


def test_bundle_needs_value_net():
    E, H = _mods()
    for side in ("netfree+bundle_p=0.75", "netfree_b+bundle_p=0.75"):
        with pytest.raises(SystemExit):
            H._spec(side, list(POOL))
    with pytest.raises(SystemExit):
        E._arm_spec("v", "+bundle_p=0.75", list(POOL))


# ------------------------------------------------------------------ E2-4
@pytest.mark.slow
def test_bundle_spec_changes_play(tmp_path):
    rs = pytest.importorskip("meicho_rs")
    from arena_rs import PLANNER, ensure_cards
    from record_mix import NETFREE
    ensure_cards()
    E, H = _mods()
    vnet = _rand_net_path(tmp_path, "e2c.json", seed=73)
    opp = PLANNER(POOL, **NETFREE)

    def dig(side):
        return [r[4] for r in rs.series_digest(CONFIG.chara_decks, CONFIG.action_decks, H._spec(side, list(POOL)), opp,
                                               SEED0, 4, 2, 200, True)]
    assert dig(vnet + "+bundle_p=0.75") != dig(vnet)
