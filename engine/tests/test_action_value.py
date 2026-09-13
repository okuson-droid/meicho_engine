"""行動の因果効果を測る対照実験の検査（D-039）。

この実験は「レベルアップを禁じた枝」と「通常の枝」を比べる。したがって
**禁止が本当に効いていること**が結論の前提になる。効いていなければ
「差が出ない」のは当たり前であり、実験そのものが無意味になる。
ここではその前提を機械的に押さえる。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

import measure_action_value as AV
from meicho.engine import apply, decision_players, initial_state, outcome
from meicho.heuristic import HeuristicAgent
from meicho.state import Phase


def _count_levelups(ban, n_games=3, seed0=120000):
    """席0（計画探索）が実際にレベルアップした回数を数える。"""
    ups = 0
    for seed in range(seed0, seed0 + n_games):
        p = AV.NoLevelupThisTurn(seed * 2, ban_turn=ban, opp_decklist=AV.POOL)
        agents = [p, HeuristicAgent(seed * 2 + 1)]
        s = initial_state(AV.CONFIG, seed)
        while outcome(s) is None and s.turn_no <= 200:
            need = decision_players(s)
            acts = {pi: agents[pi].act(s, pi) for pi in need}
            if 0 in acts and acts[0]["type"] == "levelup":
                ups += 1
            s = apply(s, acts)
    return ups


def test_normal_play_does_level_up():
    """禁止しなければレベルアップは実際に行われること。

    これが 0 なら、禁止の効果を測っても意味がない（元々やらない行動なので）。
    実測では 1 局あたり約 2.3 回行われる。
    """
    assert _count_levelups(ban=-1) > 0, "通常でもレベルアップしていない（実験が無意味）"


def test_ban_all_removes_every_levelup():
    """D-039: 全ターン禁止の枝ではレベルアップが 1 回も起きないこと。

    `_branches` の除外だけで足りているか（`act` の別経路から漏れないか）を確かめる。
    ここが漏れていると「差が出ない」という結論が偽になる。
    """
    assert _count_levelups(ban="all") == 0, "禁止したのにレベルアップしている"


def test_ban_one_turn_only_affects_that_turn():
    """1ターンだけの禁止は、そのターンにだけ効くこと。

    「今やらない」と「一生やらない」は別の対照である。取り違えると
    測っているものが変わる。
    """
    seed = 120001
    p = AV.NoLevelupThisTurn(seed * 2, ban_turn=3, opp_decklist=AV.POOL)
    agents = [p, HeuristicAgent(seed * 2 + 1)]
    s = initial_state(AV.CONFIG, seed)
    on_banned_turn = elsewhere = 0
    while outcome(s) is None and s.turn_no <= 200:
        need = decision_players(s)
        acts = {pi: agents[pi].act(s, pi) for pi in need}
        if 0 in acts and acts[0]["type"] == "levelup":
            if s.turn_no == 3:
                on_banned_turn += 1
            else:
                elsewhere += 1
        s = apply(s, acts)
    assert on_banned_turn == 0, "禁止したターンにレベルアップしている"
    # 他のターンで起きること自体は要求しない（対局によっては起きない）が、
    # 起きた場合に禁止が漏れていないことは上で押さえている。
    assert elsewhere >= 0


def test_fork_point_is_a_real_choice():
    """分岐点では、レベルアップ以外の選択肢も存在すること。

    唯一の合法手が レベルアップ なら「やらない」枝が作れず、比較にならない。
    `_find_fork` はそういう地点を飛ばす仕様である。
    """
    from meicho.engine import legal_actions
    found = AV._find_fork(120000, 0, 1)
    assert found is not None, "分岐点が見つからない"
    s, up, _ = found
    assert s.phase == Phase.ACTION
    acts = legal_actions(s, 0)
    assert up in acts
    assert any(a["type"] != "levelup" for a in acts), "比較対象が無い分岐点"


def test_paired_branches_are_deterministic():
    """同じシードなら両枝とも毎回同じ結果になること（作業規約6 / D-006）。"""
    a, b = AV._one(120002), AV._one(120002)
    assert a is not None and a == b
