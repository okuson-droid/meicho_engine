"""学習価値関数エージェントのテスト（C-1 §4.1-2 / D-038）。

守るべき不変条件。

1. **学習時と推論時で同じ値が出ること**。`train_linear.py` は標準化した特徴の上で
   重みを当てるが、`LinearValue` は生の特徴の尺度に畳んで使う。畳み方を間違えると
   静かに別のモデルになる。
2. **終端の扱いを引き継ぐこと**（±WIN）。log-odds はせいぜい ±10 なので、
   終端の分岐を落とすと勝ちを勝ちと認識できなくなる。
3. **覗き見をしないこと**（D-026）。新エージェントは必ず実対局リプレイ監査にかける。
4. **決定的であること**（作業規約6 / D-006）。
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

import pytest

from arena import load_deck, mirror_config
from meicho import features as F
from meicho.audit import replay_audit
from meicho.engine import apply, decision_players, initial_state, observe, outcome
from meicho.greedy import WIN
from meicho.heuristic import HeuristicAgent
from meicho.runner import play_game
from meicho.state import Phase
from meicho.valuenet import LinearValue, ValueMCTSAgent, ValuePlannerAgent

MODEL = "c1_linear_v1.json"
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "results", "models",
                           MODEL)
needs_model = pytest.mark.skipif(
    not os.path.exists(_MODEL_PATH),
    reason="学習済みモデル未生成（python3 experiments/train_linear.py）")


def _deck():
    return load_deck("SD001")


def _states(seed=110000, cap=24):
    """実対局から (state, pi) を集める（アクションフェイズ）。"""
    deck = _deck()
    cfg = mirror_config(deck)
    a = ValuePlannerAgent(0, model=MODEL, opp_decklist=deck["action_deck"])
    b = HeuristicAgent(1)
    s, out = initial_state(cfg, seed), []
    while outcome(s) is None and s.turn_no <= 200 and len(out) < cap:
        if s.phase == Phase.ACTION:
            out += [(s, 0), (s, 1)]
        need = decision_players(s)
        s = apply(s, {pi: [a, b][pi].act(s, pi) for pi in need})
    return out


# --- 1. 学習時と推論時の一致 -----------------------------------------------

@needs_model
def test_inference_matches_the_saved_model():
    """畳んだ重みでの推論が、標準化して計算した値と一致すること。

    `LinearValue` は w/sd と b-Σw·mu/sd に畳んで内積1回で済ませている。
    ここが狂うと学習した重みが別のモデルとして動いてしまう。
    """
    d = json.load(open(_MODEL_PATH, encoding="utf-8"))
    w, mu, sd, cols = d["w"], d["mu"], d["sd"], d["cols"]
    inter = d.get("interactions", [])
    v = LinearValue(MODEL)
    for s, pi in _states(cap=12):
        x = F.from_state(s, pi)
        raw = [x[F.FEATURE_NAMES.index(c)] for c in cols]
        raw += [x[F.FEATURE_NAMES.index(a)] * x[F.FEATURE_NAMES.index(b)]
                for a, b in inter]
        want = w[-1] + sum(w[i] * (raw[i] - mu[i]) / sd[i] for i in range(len(raw)))
        assert v.logodds(x) == pytest.approx(want, abs=1e-9)


@needs_model
def test_model_feature_names_match_the_extractor():
    """モデルの特徴名が `meicho/features.py` と一致すること。

    特徴を足して学習し直さないまま使うと、重みが別の列に当たる。
    `LinearValue` は読み込み時に落ちるので、その保護が生きていることを確かめる。
    """
    d = json.load(open(_MODEL_PATH, encoding="utf-8"))
    assert list(d["feature_names"]) == list(F.FEATURE_NAMES)


# --- 2. 終端の扱い ---------------------------------------------------------

@needs_model
def test_terminal_states_dominate_every_learned_value():
    """終端は ±WIN を返し、非終端のどの値よりも大きい／小さいこと。"""
    deck = _deck()
    a = ValuePlannerAgent(0, model=MODEL, opp_decklist=deck["action_deck"])
    vals = [a._eval(s, pi) for s, pi in _states(cap=16)]
    assert vals, "非終端の局面が集まっていない"
    assert max(abs(v) for v in vals) < WIN / 10, "log-odds が大きすぎる（尺度の異常）"

    s, pi = _states(cap=2)[0]
    for outcome_value, expect in ((pi, WIN), (1 - pi, -WIN)):
        t = s.clone()
        t.outcome = outcome_value
        assert a._eval(t, pi) == expect
    t = s.clone()
    t.outcome = -1                      # DRAW
    assert a._eval(t, pi) == 0.0


@needs_model
def test_mcts_leaf_value_is_a_probability():
    """IS-MCTS 側の葉は [0,1]（UCB の有界報酬の前提）。"""
    deck = _deck()
    m = ValueMCTSAgent(0, model=MODEL, iterations=8,
                       opp_decklist=deck["action_deck"])
    for s, pi in _states(cap=10):
        v = m._leaf01(s, pi)
        assert 0.0 <= v <= 1.0
        assert math.isfinite(v)
    t = _states(cap=2)[0][0].clone()
    t.outcome = 0
    assert m._leaf01(t, 0) == 1.0 and m._leaf01(t, 1) == 0.0


# --- 3. 覗き見の禁止（D-026）-----------------------------------------------

@needs_model
def test_nopeek_audit_value_planner():
    """§4/§10: 学習価値関数を積んだ計画探索も隠蔽情報を使わないこと。

    引継ぎ書 §5「新エージェントは必ず audit.py の覗き見監査にかける」。
    """
    deck = _deck()["action_deck"]
    r = replay_audit(
        lambda sd: ValuePlannerAgent(sd, model=MODEL, opp_decklist=deck,
                                     plan_samples=2),
        lambda sd: HeuristicAgent(sd),
        mirror_config(_deck()), deck, n_games=2, variants=2, node_cap=60)
    assert r["checked"] >= 30, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"


@needs_model
def test_learned_value_is_invariant_to_hidden_information():
    """価値関数そのものが隠蔽情報に反応しないこと（監査の前段の直接検査）。"""
    import random as _r
    deck = _deck()["action_deck"]
    v = LinearValue(MODEL)
    for s, pi in _states(cap=8):
        base = v(s, pi)
        for trial in range(3):
            rng = _r.Random(trial)
            t = s.clone()
            n = min(len(t.players[1 - pi].hand), len(deck))
            t.players[1 - pi].hand = rng.sample(deck, n)
            rng.shuffle(t.players[0].action_deck)
            rng.shuffle(t.players[1].action_deck)
            assert v(t, pi) == pytest.approx(base, abs=1e-12)


# --- 4. 決定性 -------------------------------------------------------------

@needs_model
def test_value_planner_is_deterministic():
    """同じシードなら同じ対局になること（D-006 / 作業規約6）。"""
    deck = _deck()
    cfg = mirror_config(deck)

    def one():
        return play_game(cfg, [ValuePlannerAgent(0, model=MODEL,
                                                 opp_decklist=deck["action_deck"]),
                               HeuristicAgent(1)], seed=110001)
    a, b = one(), one()
    assert (a["winner"], a["turns"], a["life"]) == (b["winner"], b["turns"], b["life"])


@needs_model
def test_value_planner_differs_from_the_handwritten_evaluate():
    """学習価値関数が実際に手を変えていること（差し替えが効いていない事故の検出）。

    まったく同じ対局になるなら `_eval` の差し替えが効いていない。
    """
    from meicho.planner import PlannerAgent
    deck = _deck()
    cfg = mirror_config(deck)
    same = 0
    for seed in range(110002, 110008):
        base = play_game(cfg, [PlannerAgent(seed * 2,
                                            opp_decklist=deck["action_deck"]),
                               HeuristicAgent(seed * 2 + 1)], seed=seed)
        got = play_game(cfg, [ValuePlannerAgent(seed * 2, model=MODEL,
                                                opp_decklist=deck["action_deck"]),
                              HeuristicAgent(seed * 2 + 1)], seed=seed)
        same += (base["winner"], base["turns"]) == (got["winner"], got["turns"])
    assert same < 6, "全局が同一。_eval の差し替えが効いていない"
