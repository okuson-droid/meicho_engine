"""E-1（D-177・`GENERALIST_WALL_READING_20261020.md` §7）の道具 `value_views` の検査。

`value_views=2` は葉を両視点の平均 (V(自分) + 1 − V(相手)) / 2 で採点する。相手の視点の信念の要約は
`own_decklist`（相手から見た相手＝自分のデッキ表）で作り、無ければミラーとみなして `opp_decklist` を使う。

VV-1 Python の `PlannerAgent._eval`: 既定（1）は自分の視点の V そのもの、2 は手で組んだ両視点の平均と一致する。
     `own_decklist` を渡せば相手の視点にはそれが、渡さなければ `opp_decklist` が使われる
VV-2 1 と 2 以外・`value_net` なしの 2 は止める（Python・Rust のクラス・spec の 3 つの口）
VV-3 Python 版と Rust 版が毎手同じ手を選ぶ（`own_decklist` なし・あり）
VV-4 `series` 系と同じ道で席に着けたとき、両視点の採点に渡すデッキ表は「自分の視点に相手の席の行動デッキ・
     相手の視点に自分の席の行動デッキ」（両席・偶奇のシード）。オフなら None
VV-5 spec の既定（鍵なし）と `value_views=1` は打ち方がバイトで同じ（`series_digest`）。2 は打ち方が変わる
VV-6 `eval_s3_h2h`・`eval_s2_repr` の席の末尾 `+views=2` が spec の `value_views=2` になり、指紋の末尾に付く。
     付けない席は従来の spec・指紋のまま。葉の V の無い席に付けると止める

検査の対局は 986300..986399（kind=diag・D-177 で登録）で回す。
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))
sys.path.insert(0, _HERE)

from test_d065 import CONFIG, POOL, _match_py_rust, _rand_net_path, _rs_has_d065   # noqa: E402

SEED0 = 986300


def _rs_has_views():
    rs = _rs_has_d065()
    if "value_views" not in rs.features():
        pytest.skip("wheel が E-1（value_views）より古い")
    return rs


def _other_pool():
    """SD001 と違う行動デッキ（`own_decklist` が実際に読まれているかを見分けるため）。"""
    from arena import load_deck
    import eval_s2_repr as E
    return load_deck(E.tune_decks()[0])["action_deck"]


def _mid_state(seed=SEED0, steps=12):
    """H どうしで数手進めた、決着していない局面。"""
    from meicho.engine import apply, decision_players, initial_state
    from meicho.heuristic import HeuristicAgent
    a, b = HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)
    s = initial_state(CONFIG, seed)
    for _ in range(steps):
        need = decision_players(s)
        if s.outcome is not None or not need:
            break
        s = apply(s, {q: (a if q == 0 else b).act(s, q) for q in sorted(need)})
    assert s.outcome is None
    return s


# ------------------------------------------------------------------ VV-1
def test_python_eval_by_hand(tmp_path):
    from meicho.encode import encode
    from meicho.engine import observe
    from meicho.greedy import load_net
    from meicho.planner import PlannerAgent
    vnet = _rand_net_path(tmp_path, "vv1.json", seed=61)
    net = load_net(vnet)
    other = _other_pool()
    s = _mid_state()

    def v(q, deck):
        return float(net.value_of(np.asarray(encode(observe(s, q), q, deck), np.float32)))

    for pi in (0, 1):
        one = PlannerAgent(0, opp_decklist=POOL, value_net=vnet)._eval(s, pi)
        assert one == v(pi, POOL)
        mirror = PlannerAgent(0, opp_decklist=POOL, value_net=vnet, value_views=2)._eval(s, pi)
        assert mirror == 0.5 * (v(pi, POOL) + 1.0 - v(1 - pi, POOL))
        own = PlannerAgent(0, opp_decklist=POOL, value_net=vnet, value_views=2, own_decklist=other)._eval(s, pi)
        assert own == 0.5 * (v(pi, POOL) + 1.0 - v(1 - pi, other))
        assert own != mirror, "own_decklist が相手の視点に効いていない"


# ------------------------------------------------------------------ VV-2
def test_refusals(tmp_path):
    from meicho.planner import PlannerAgent
    vnet = _rand_net_path(tmp_path, "vv2.json", seed=62)
    for kw in (dict(value_views=2), dict(value_views=3, value_net=vnet), dict(value_views=0, value_net=vnet)):
        with pytest.raises(ValueError):
            PlannerAgent(0, opp_decklist=POOL, **kw)
    rs = _rs_has_views()
    from arena_rs import PLANNER
    for kw in (dict(value_views=2), dict(value_views=3, value_net=vnet), dict(value_views=0, value_net=vnet)):
        with pytest.raises(ValueError):
            rs.PlannerAgent(0, opp_decklist=POOL, **kw)
        with pytest.raises(ValueError):
            rs.series_digest(CONFIG.chara_decks, CONFIG.action_decks, PLANNER(POOL, **kw), PLANNER(POOL),
                             SEED0, 1, 1, 200, True)


# ------------------------------------------------------------------ VV-3
def test_python_matches_rust_mirror(tmp_path):
    rs = _rs_has_views()
    vnet = _rand_net_path(tmp_path, "vv3a.json", seed=63)
    _match_py_rust(rs, dict(opp_decklist=POOL, extra_turns=1, value_net=vnet, value_views=2),
                   seed=SEED0 + 10, max_steps=40)


@pytest.mark.slow
def test_python_matches_rust_own_deck(tmp_path):
    rs = _rs_has_views()
    vnet = _rand_net_path(tmp_path, "vv3b.json", seed=64)
    _match_py_rust(rs, dict(opp_decklist=POOL, extra_turns=1, value_net=vnet, value_views=2,
                            own_decklist=_other_pool(), choice_phases=True, solo_samples=4),
                   seed=SEED0 + 11, max_steps=40)


# ------------------------------------------------------------------ VV-4
def test_decks_by_seat(tmp_path):
    rs = _rs_has_views()
    from arena import load_deck
    from arena_rs import PLANNER
    import eval_s2_repr as E
    da, db = (load_deck(k) for k in E.tune_decks()[:2])
    ad = [da["action_deck"], db["action_deck"]]
    vnet = _rand_net_path(tmp_path, "vv4.json", seed=65)
    on = PLANNER(db["action_deck"], value_net=vnet, value_views=2)
    off = PLANNER(db["action_deck"], value_net=vnet)
    for seed in (SEED0 + 20, SEED0 + 21):
        a_seat = seed % 2                                    # 奇数シードで A が席 1 に入れ替わる
        for seat in (0, 1):
            got = rs.value_views_decks(ad, on, off, seed, seat)
            if seat != a_seat:
                assert got is None, (seed, seat)
                continue
            mine, theirs = got
            assert sorted(mine) == sorted(ad[1 - seat]), (seed, seat)      # 自分の視点 = 相手の席の行動デッキ
            assert sorted(theirs) == sorted(ad[seat]), (seed, seat)        # 相手の視点 = 自分の席の行動デッキ


# ------------------------------------------------------------------ VV-5
@pytest.mark.slow
def test_spec_off_unchanged_on_changes_play(tmp_path):
    rs = _rs_has_views()
    from arena_rs import PLANNER
    from record_mix import NETFREE
    vnet = _rand_net_path(tmp_path, "vv5.json", seed=66)
    opp = PLANNER(POOL, **NETFREE)

    def dig(**kw):
        spec = PLANNER(POOL, **NETFREE, value_net=vnet, **kw)
        return [r[4] for r in rs.series_digest(CONFIG.chara_decks, CONFIG.action_decks, spec, opp,
                                               SEED0 + 30, 4, 2, 200, True)]
    base = dig()
    assert dig(value_views=1) == base
    assert dig(value_views=2) != base


# ------------------------------------------------------------------ VV-6
def test_side_syntax(tmp_path):
    import eval_s2_repr as E
    import eval_s3_h2h as H
    vnet = _rand_net_path(tmp_path, "vv6.json", seed=67)
    pool = list(POOL)
    assert "value_views" not in H._spec(vnet, pool)
    assert "value_views" not in E._arm_spec("v", vnet, pool)
    on = H._spec(vnet + E.VIEWS_SUFFIX, pool)
    assert on == dict(H._spec(vnet, pool), value_views=2)
    assert E._arm_spec("v", vnet + E.VIEWS_SUFFIX, pool) == dict(E._arm_spec("v", vnet, pool), value_views=2)
    assert H.side_sha(vnet + E.VIEWS_SUFFIX) == H.side_sha(vnet) + "+views=2"
    assert E.arm_sha(vnet + E.VIEWS_SUFFIX) == E.arm_sha(vnet) + "+views=2"
    for bad in ("netfree+views=2", "netfree_b+views=2"):
        with pytest.raises(SystemExit):
            H._spec(bad, pool)
    with pytest.raises(SystemExit):
        E._arm_spec("v", "+views=2", pool)
