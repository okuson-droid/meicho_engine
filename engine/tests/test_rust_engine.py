"""Rust 版エンジン（`meicho_rs`・D-049）と Python 版の同一性テスト。

受け入れ基準（D-049）: **全 apply 後の GameState の JSON が Python 版と完全一致**すること。
fingerprint（勝者・ターン数・ライフ）より厳しい。合わせて `decision_players` /
`legal_actions` / `observe` も毎手で突き合わせる。

`meicho_rs` が入っていない環境ではこのファイル全体を skip する
（Python 版だけで作業する場面を止めないため）。
"""
from __future__ import annotations

import json
import random

import pytest

rs = pytest.importorskip("meicho_rs")

from experiments.arena import load_deck, matchup_config, mirror_config  # noqa: E402
from meicho.agents import RandomAgent                                  # noqa: E402
from meicho.cards import ACTION_CARDS, CHARA_CARDS                     # noqa: E402
from meicho.cards_export import cards_dict, cards_json                 # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,      # noqa: E402
                           legal_actions, observe, outcome)
from meicho.greedy import GreedyAgent                                  # noqa: E402
from meicho.heuristic import HeuristicAgent                            # noqa: E402
from meicho.planner import PlannerAgent                                # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _load_cards():
    n = rs.load_cards(cards_json())
    assert n == len(CHARA_CARDS) + len(ACTION_CARDS)


def _norm(x):
    """JSON 相当の入れ子を比較用に正規化する（tuple→list）。"""
    return json.loads(json.dumps(x, ensure_ascii=False))


def _lockstep(config, seed, agents, max_steps=5000):
    """Python 版で対局を進め、同じ行動を Rust 版にも流して毎手比較する。

    戻り値は (steps, turns)。差があれば assert で落ちる。
    """
    config.validate()
    py = initial_state(config, seed)
    rss = rs.initial_state(config.chara_decks, config.action_decks, seed)
    steps = 0
    while True:
        assert _norm(json.loads(py.to_json())) == json.loads(rss.to_json()), \
            f"state mismatch seed={seed} step={steps}"
        need = decision_players(py)
        assert list(need) == list(rs.decision_players(rss)), f"decision_players seed={seed} step={steps}"
        for pi in (0, 1):
            assert _norm(legal_actions(py, pi)) == rs.legal_actions(rss, pi), \
                f"legal_actions P{pi} seed={seed} step={steps}"
            assert _norm(observe(py, pi)) == rs.observe(rss, pi), \
                f"observe P{pi} seed={seed} step={steps}"
        assert outcome(py) == rs.outcome(rss)
        if outcome(py) is not None or not need or py.turn_no > 200:
            break
        actions = {pi: agents[pi].act(py, pi) for pi in need}
        py = apply(py, actions)
        rss = rs.apply(rss, actions)
        steps += 1
        assert steps < max_steps
    return steps, py.turn_no


SD001 = load_deck("SD001")
SD02 = load_deck("SD02")


def test_cards_roundtrip_matches_cards_py():
    """書き出し（cards_export）の内容が cards.py と一致する。"""
    d = cards_dict()
    assert [c["card_id"] for c in d["chara"]] == list(CHARA_CARDS)
    assert [c["card_id"] for c in d["action"]] == list(ACTION_CARDS)
    for c in d["action"]:
        a = ACTION_CARDS[c["card_id"]]
        assert (c["color"], c["cost"], c["speed"], c["damage"]) == \
            (a.color.value, a.cost, a.speed, a.damage)


@pytest.mark.parametrize("seed", list(range(50)))
def test_random_agents_mirror_sd001(seed):
    cfg = mirror_config(SD001)
    steps, _ = _lockstep(cfg, seed, [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)])
    assert steps > 0


@pytest.mark.parametrize("seed", list(range(50, 80)))
def test_random_agents_mirror_sd02(seed):
    cfg = mirror_config(SD02)
    _lockstep(cfg, seed, [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(80, 100)))
def test_random_agents_matchup(seed):
    cfg = matchup_config(SD001, SD02) if seed % 2 == 0 else matchup_config(SD02, SD001)
    _lockstep(cfg, seed, [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(30)))
def test_heuristic_agents_sd001(seed):
    cfg = mirror_config(SD001)
    _lockstep(cfg, seed, [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(10)))
def test_greedy_vs_heuristic_sd001(seed):
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    _lockstep(cfg, seed, [GreedyAgent(seed * 2, opp_decklist=pool), HeuristicAgent(seed * 2 + 1)])


@pytest.mark.parametrize("seed", list(range(4)))
def test_planner_vs_heuristic_sd001(seed):
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    _lockstep(cfg, seed, [PlannerAgent(seed * 2, opp_decklist=pool), HeuristicAgent(seed * 2 + 1)])


def test_apply_is_order_independent_in_rust():
    """D-040 の順序依存は Rust 版には無い（席の昇順で処理する）。"""
    cfg = mirror_config(SD001)
    s = rs.initial_state(cfg.chara_decks, cfg.action_decks, 130001)
    a0 = rs.legal_actions(s, 0)[0]
    a1 = rs.legal_actions(s, 1)[1]
    x = rs.apply(s, {0: a0, 1: a1})
    y = rs.apply(s, {1: a1, 0: a0})
    assert x.to_json() == y.to_json()


def test_apply_owned_mutates_and_apply_does_not():
    cfg = mirror_config(SD001)
    s = rs.initial_state(cfg.chara_decks, cfg.action_decks, 3)
    before = s.to_json()
    acts = {pi: rs.legal_actions(s, pi)[0] for pi in rs.decision_players(s)}
    t = rs.apply(s, acts)
    assert s.to_json() == before and t.to_json() != before
    rs.apply_owned(s, acts)
    assert s.to_json() == t.to_json()


def test_rejects_missing_player_actions():
    cfg = mirror_config(SD001)
    s = rs.initial_state(cfg.chara_decks, cfg.action_decks, 3)
    with pytest.raises(ValueError):
        rs.apply(s, {0: rs.legal_actions(s, 0)[0]})
