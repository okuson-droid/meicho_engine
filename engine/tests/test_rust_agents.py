"""Rust 版エージェント（`meicho_rs.HeuristicAgent / GreedyAgent / PlannerAgent`・D-049 R2/R3）の同一性テスト。

Python 版と Rust 版のエージェントを**同じ局面**に置き、**毎手の選択が一致する**ことを検証する。
乱数の消費列（混合戦略の抽選・決定化のシャッフル）まで一致しないと通らない。
同時に状態の JSON も毎手比較する（エンジンの同一性も再確認される）。
"""
from __future__ import annotations

import json

import pytest

rs = pytest.importorskip("meicho_rs")

from experiments.arena import load_deck, mirror_config      # noqa: E402
from experiments.measure_horizon import LongHorizonPlanner  # noqa: E402
from meicho.cards_export import cards_json                  # noqa: E402
from meicho.engine import apply, decision_players, initial_state, outcome  # noqa: E402
from meicho.greedy import GreedyAgent, Weights              # noqa: E402
from meicho.heuristic import HeuristicAgent, Params         # noqa: E402
from meicho.planner import PlannerAgent                     # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _load_cards():
    rs.load_cards(cards_json())


SD001 = load_deck("SD001")
SD02 = load_deck("SD02")


def _lockstep(config, seed, py_agents, rs_agents, max_steps=5000):
    """Python 版で進めながら、毎手 Rust 版エージェントにも同じ局面で手を選ばせて比べる。"""
    config.validate()
    py = initial_state(config, seed)
    rss = rs.initial_state(config.chara_decks, config.action_decks, seed)
    steps = 0
    while outcome(py) is None and py.turn_no <= 200:
        assert json.loads(py.to_json()) == json.loads(rss.to_json()), f"state seed={seed} step={steps}"
        need = decision_players(py)
        if not need:
            break
        actions = {}
        for pi in need:
            a_py = py_agents[pi].act(py, pi)
            a_rs = rs_agents[pi].act(rss, pi)
            assert json.loads(json.dumps(a_py)) == a_rs, \
                f"agent P{pi} chose differently: seed={seed} step={steps} phase={py.phase} py={a_py} rs={a_rs}"
            actions[pi] = a_py
        py = apply(py, actions)
        rss = rs.apply(rss, actions)
        steps += 1
        assert steps < max_steps
    assert outcome(py) == rs.outcome(rss)
    return steps


@pytest.mark.parametrize("seed", list(range(40)))
def test_heuristic_default_mirror(seed):
    cfg = mirror_config(SD001 if seed % 2 == 0 else SD02)
    _lockstep(cfg, seed,
              [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)],
              [rs.HeuristicAgent(seed * 2), rs.HeuristicAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(6)))
def test_heuristic_custom_params(seed):
    cfg = mirror_config(SD001)
    p = dict(concerto_target=3, levelup_min_hand=4, own_color_weight=3.0,
             scarce_penalty=0.7, switch_min_gain=1, counter_weight=6.0)
    _lockstep(cfg, seed,
              [HeuristicAgent(seed * 2, Params(**p)), HeuristicAgent(seed * 2 + 1)],
              [rs.HeuristicAgent(seed * 2, p), rs.HeuristicAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(12)))
def test_greedy_vs_heuristic(seed):
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    _lockstep(cfg, seed,
              [GreedyAgent(seed * 2, opp_decklist=pool), HeuristicAgent(seed * 2 + 1)],
              [rs.GreedyAgent(seed * 2, opp_decklist=pool), rs.HeuristicAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(6)))
def test_greedy_without_decklist_and_custom_weights(seed):
    """opp_decklist 未指定（自分のデッキから推定）と重みの指定。"""
    cfg = mirror_config(SD02)
    w = dict(life=1.0, concerto=1.2, hand=0.7, live_red=0.3, level=0.4, resource=0.02)
    _lockstep(cfg, seed,
              [GreedyAgent(seed * 2, weights=Weights(**w), samples=3), HeuristicAgent(seed * 2 + 1)],
              [rs.GreedyAgent(seed * 2, weights=w, samples=3), rs.HeuristicAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(6)))
def test_planner_vs_heuristic(seed):
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    _lockstep(cfg, seed,
              [PlannerAgent(seed * 2, opp_decklist=pool), HeuristicAgent(seed * 2 + 1)],
              [rs.PlannerAgent(seed * 2, opp_decklist=pool), rs.HeuristicAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(3)))
def test_planner_vs_planner(seed):
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    _lockstep(cfg, seed,
              [PlannerAgent(seed * 2, opp_decklist=pool), PlannerAgent(seed * 2 + 1, opp_decklist=pool)],
              [rs.PlannerAgent(seed * 2, opp_decklist=pool), rs.PlannerAgent(seed * 2 + 1, opp_decklist=pool)])


@pytest.mark.parametrize("seed", list(range(3)))
def test_planner_sd02_untuned_and_racing(seed):
    cfg = mirror_config(SD02)
    pool = SD02["action_deck"]
    _lockstep(cfg, seed,
              [PlannerAgent(seed * 2, opp_decklist=pool, tuned=False, plan_samples=3, race_after=2),
               HeuristicAgent(seed * 2 + 1)],
              [rs.PlannerAgent(seed * 2, opp_decklist=pool, tuned=False, plan_samples=3, race_after=2),
               rs.HeuristicAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(3)))
def test_long_horizon_planner(seed):
    """D-046 対策A（地平の延長）は `extra_turns=1`。"""
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    _lockstep(cfg, seed,
              [LongHorizonPlanner(seed * 2, opp_decklist=pool), HeuristicAgent(seed * 2 + 1)],
              [rs.PlannerAgent(seed * 2, opp_decklist=pool, extra_turns=1), rs.HeuristicAgent(seed * 2 + 1)])


def test_play_game_matches_python_runner():
    """Rust 内で完結する `play_game` が Python の `runner.play_game` と同じ結果を返す。"""
    from meicho.runner import play_game as py_play
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    for seed in range(4):
        r_py = py_play(cfg, [PlannerAgent(seed * 2, opp_decklist=pool), HeuristicAgent(seed * 2 + 1)], seed=seed)
        r_rs = rs.play_game(cfg.chara_decks, cfg.action_decks, seed,
                            rs.PlannerAgent(seed * 2, opp_decklist=pool), rs.HeuristicAgent(seed * 2 + 1))
        winner, turns, l0, l1, draw, aborted, steps = r_rs
        assert (r_py["winner"], r_py["turns"], r_py["life"], r_py["draw"], r_py["aborted"], r_py["steps"]) == \
            (winner, turns, [l0, l1], draw, aborted, steps), seed
