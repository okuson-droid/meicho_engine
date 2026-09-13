"""C-1 特徴抽出のテスト（D-035 / D-036）。

守るべき不変条件は3つ。

1. **2つの入口が一致すること**（`from_obs` と `from_state`）。片方だけ直すと
   学習時と推論時で別の特徴になり、学習した重みが探索で意味を失う。
2. **隠蔽情報を参照しないこと**（D-026）。学習でも覗き見は反則である。
3. **定数でないこと**。「覗かない」だけなら定数関数でも通ってしまう。
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

import pytest

from meicho import features as F
from arena import load_deck, mirror_config
from registry import make
from meicho.engine import (apply, decision_players, initial_state, observe,
                           outcome)
from meicho.state import Phase


def _states(seeds=(90000, 90001), phase=Phase.ACTION, cap=60):
    """実対局を回して、指定フェイズの (state, pi) を集める。

    合成局面ではなく実局面で比べる。`live_reds` のループ長や協奏の枚数など、
    実際に出る分布でしか踏まない場合分けがあるためである。
    """
    deck = load_deck("SD001")
    cfg = mirror_config(deck)
    mk_a = make("planner", None, deck["action_deck"])
    mk_b = make("heuristic", None, None)
    out = []
    for seed in seeds:
        agents = [mk_a(seed * 2), mk_b(seed * 2 + 1)]
        s = initial_state(cfg, seed)
        while outcome(s) is None and s.turn_no <= 200 and len(out) < cap:
            if s.phase == phase:
                out.append((s, 0))
                out.append((s, 1))
            need = decision_players(s)
            s = apply(s, {pi: agents[pi].act(s, pi) for pi in need})
    return out


# --- 1. 2つの入口の一致 ----------------------------------------------------

def test_from_obs_matches_from_state_on_real_games():
    """D-036: 観測からの抽出と状態からの抽出が完全に一致すること。

    ここが落ちたら、`observe` に足りない公開情報があるか、
    どちらか一方の実装だけを変えたかのどちらかである。
    """
    pairs = _states()
    assert len(pairs) >= 20, "比較する局面が少なすぎる"
    for s, pi in pairs:
        a = F.from_state(s, pi)
        b = F.from_obs(observe(s, pi))
        assert a == b, (f"turn {s.turn_no} P{pi} で不一致\n"
                        f"  state: {a}\n  obs  : {b}")


def test_from_obs_matches_from_state_when_red_cost_up_is_active():
    """旋風 (SD01-016) の継続効果が効いている局面でも一致すること。

    `red_cost_up` は実対局の約3%の局面でしか立たないので、
    上のテストだけでは踏み抜けない。ここで強制的に立てて比べる。
    """
    pairs = _states(seeds=(90002,), cap=20)
    assert pairs
    hit = 0
    for s, pi in pairs:
        t = s.clone()
        t.red_cost_up = [True, True]      # 両者に立てて写し違えも検出する
        assert F.from_state(t, pi) == F.from_obs(observe(t, pi))
        # 効果が実際に枚数を動かした局面が1つはあること（無効なテストの検出）
        if F.from_state(t, pi) != F.from_state(s, pi):
            hit += 1
    assert hit > 0, "red_cost_up が1件も特徴を動かしていない（テストが無効）"


# --- 2. 覗き見の禁止 -------------------------------------------------------

def test_features_do_not_peek_at_hidden_information():
    """D-026: 相手の手札の中身と両者のデッキ順序に不変であること。"""
    import random as _r
    deck = load_deck("SD001")["action_deck"]
    pairs = _states(seeds=(90003,), cap=12)
    assert pairs
    for s, pi in pairs:
        base = F.from_state(s, pi)
        for trial in range(3):
            rng = _r.Random(trial)
            t = s.clone()
            n = min(len(t.players[1 - pi].hand), len(deck))
            t.players[1 - pi].hand = rng.sample(deck, n)
            rng.shuffle(t.players[0].action_deck)
            rng.shuffle(t.players[1].action_deck)
            assert F.from_state(t, pi) == base, "隠蔽情報を参照している"


# --- 3. 形と非定数性 -------------------------------------------------------

def test_features_are_wellformed():
    """長さが FEATURE_NAMES と揃い、すべて有限の float であること。"""
    assert len(F.FEATURE_NAMES) == F.N_FEAT
    assert len(set(F.FEATURE_NAMES)) == F.N_FEAT, "特徴名が重複している"
    for s, pi in _states(seeds=(90004,), cap=8):
        x = F.from_state(s, pi)
        assert len(x) == F.N_FEAT
        assert all(isinstance(v, float) and math.isfinite(v) for v in x)


def test_features_respond_to_own_visible_resources():
    """自分の手札・ライフ・協奏の変化に反応すること（定数関数でないこと）。"""
    s, pi = _states(seeds=(90005,), cap=2)[0]
    base = F.from_state(s, pi)
    t = s.clone()
    t.players[pi].hand = t.players[pi].hand[:-1]
    assert F.from_state(t, pi) != base, "自分の手札の変化に反応していない"
    u = s.clone()
    u.players[pi].life -= 1
    assert F.from_state(u, pi) != base, "ライフの変化に反応していない"


def test_every_feature_varies_somewhere_in_real_play():
    """実対局のあいだに、どの特徴も一度は値が動くこと。

    常に定数の特徴は学習の役に立たず、抽出のコストだけ払うことになる。
    """
    pairs = _states(seeds=(90006, 90007), cap=80)
    cols = list(zip(*[F.from_state(s, pi) for s, pi in pairs]))
    dead = [F.FEATURE_NAMES[i] for i, c in enumerate(cols) if len(set(c)) == 1]
    assert not dead, f"実対局で一度も動かない特徴がある: {dead}"


@pytest.mark.parametrize("name", ["life_diff", "concerto_me", "live_reds"])
def test_named_features_are_present(name):
    """名前と並びの対応が保たれていること（並べ替えの事故を防ぐ）。"""
    assert name in F.FEATURE_NAMES
