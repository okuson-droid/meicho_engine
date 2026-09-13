"""探索の地平を延ばした計画探索の検査（D-046）。

固定するのは**結論（勝率）ではなく前提**である。

1. 地平が実際に延びていること（相手のターンを通ってから採点している）
2. 通常の計画探索と**挙動が変わる**こと（変わらなければ測定に意味が無い）
3. 覗き見をしていないこと（決定化の規約・D-026）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from measure_horizon import CONFIG, POOL, LongHorizonPlanner      # noqa: E402
from meicho.engine import (apply, decision_players,               # noqa: E402
                           initial_state, outcome)
from meicho.heuristic import HeuristicAgent                       # noqa: E402
from meicho.planner import PlannerAgent                           # noqa: E402
from meicho.state import Phase                                    # noqa: E402

SEED0 = 164000        # seed_bands.json に登録済み（D-046 の測定専用）


def _first_action_phase(seed, max_steps=400):
    """人手の要らない進行で、席0のアクションフェイズを1つ見つける。"""
    a, b = HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)
    s = initial_state(CONFIG, seed)
    for _ in range(max_steps):
        if outcome(s) is not None:
            return None
        need = decision_players(s)
        if not need:
            return None
        if s.phase == Phase.ACTION and s.turn_player == 0 and 0 in need:
            if len(__import__("meicho.engine", fromlist=["legal_actions"])
                   .legal_actions(s, 0)) > 1:
                return s
        s = apply(s, {pi: (a if pi == 0 else b).act(s, pi) for pi in sorted(need)})
    return None


def test_horizon_actually_extends_past_the_opponents_turn():
    """`_value_after_turn` が相手のターンを通ってから採点していること。

    採点した局面のターン番号を記録して確かめる。通常版は自分のターンで止まり、
    延長版はその先まで進む。ここが崩れたら「地平を延ばした」と言えない。
    """
    s = _first_action_phase(SEED0 + 300)
    assert s is not None, "検査に使えるアクションフェイズが見つからない"

    seen = {"plain": [], "long": []}

    def spy(agent, key):
        orig = agent._eval

        def wrapped(u, pi):
            seen[key].append(u.turn_no)
            return orig(u, pi)
        agent._eval = wrapped
        return agent

    plain = spy(PlannerAgent(SEED0 * 2, opp_decklist=POOL), "plain")
    long_ = spy(LongHorizonPlanner(SEED0 * 2, opp_decklist=POOL), "long")
    plain.act(s, 0)
    long_.act(s, 0)

    assert seen["plain"] and seen["long"]
    assert max(seen["long"]) > max(seen["plain"]), (
        f"地平が延びていない: 通常 {max(seen['plain'])} / "
        f"延長 {max(seen['long'])}")


def test_long_horizon_changes_the_chosen_move_somewhere():
    """通常版と違う手を選ぶ場面が実際にあること。

    どの局面でも同じ手を選ぶなら、勝率差は測定ノイズでしかありえない。
    """
    diff = 0
    for i in range(8):
        s = _first_action_phase(SEED0 + 400 + i)
        if s is None:
            continue
        seed = (SEED0 + 400 + i) * 2
        # **両方とも作りたての同一シード**で比べる（乱数の履歴を揃える）
        a = PlannerAgent(seed, opp_decklist=POOL)
        b = LongHorizonPlanner(seed, opp_decklist=POOL)
        if a.act(s, 0) != b.act(s, 0):
            diff += 1
    assert diff >= 1, "どの局面でも通常版と同じ手を選んでいる（変更が効いていない）"


def test_long_horizon_does_not_peek():
    """決定化の規約（D-026）を守っていること。**新エージェントは必ず監査する。**

    地平を延ばすということは、**相手のターンをこちらの想像で進める**ということである。
    そこで実際の相手の手札や山札の順序を覗いてしまえば、強くなって当然であり
    測定は無意味になる。ここが通らないかぎり D-046 の勝率は読めない。
    """
    from meicho.audit import replay_audit
    r = replay_audit(lambda sd: LongHorizonPlanner(sd, opp_decklist=POOL),
                     lambda sd: HeuristicAgent(sd),
                     CONFIG, POOL, n_games=3, variants=2, node_cap=120)
    assert r["checked"] >= 60, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"
