"""C-1 §4.2 「evaluate の許容時間」の損益分岐を測る。

rules_draft.md v0.10 準拠 / engine v0.1。

## 何を答える道具か

学習価値関数は `greedy.evaluate` を置き換える。置き換えると1回あたりのコストが
上がるが、探索の予算（planner の `leaf_budget`、mcts の `iterations`）は
実時間で決まっているので、**質の向上が予算の減少に食われうる**。
本スクリプトは着手前にその境界を数値で出す。

出す量は3つ。

1. **呼び出し実態**: エージェント1局あたり `evaluate` が何回呼ばれ、
   その総時間が1局の何%を占めるか。
2. **単価**: 現行 `evaluate` と、学習価値関数の候補実装（線形／MLP を
   純Python・numpy・バッチ）の1回あたり時間。実局面の標本で測る。
3. **損益分岐**: 「evaluate の単価を c にしたとき局/秒がどうなるか」と、
   それが `leaf_budget` の何割の削減と等価か。

## 測り方の約束

- 速度計測は計数器を外した状態で行う（計数のオーバーヘッドを混ぜない）。
- 標本局面は実対局の `evaluate` 呼び出し地点から採る（合成局面では
  `live_reds` のループ長など分布が変わる）。
- 速度のみを測るので勝率の主張はしない。よってシード帯は fingerprint と
  同じ 0.. を用いる（D-028 の「調整・探索に使ってはならない」帯は 80000..）。

実行: python3 experiments/bench_evaluate.py [--quick]
"""
from __future__ import annotations

import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

try:                       # numpy は無くても純Python部分は動くようにする
    import numpy as np
except ImportError:        # 低スペック環境・素の CPython でも計測できること
    np = None

from meicho import features as c1_features                          # noqa: E402
from arena import load_deck, mirror_config                           # noqa: E402
from meicho import greedy, mcts as mcts_mod, planner as planner_mod  # noqa: E402
from meicho.cards import CHARA_CARDS, Color                          # noqa: E402
from meicho.greedy import GreedyAgent, evaluate as EVAL              # noqa: E402
from meicho.heuristic import HeuristicAgent, live_reds               # noqa: E402
from meicho.mcts import MCTSAgent                                    # noqa: E402
from meicho.planner import PlannerAgent, TUNED_WEIGHTS               # noqa: E402
from meicho.runner import play_game                                  # noqa: E402
from meicho.state import DRAW                                        # noqa: E402

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]

# evaluate を参照しているモジュール（from ... import evaluate で束縛済み）。
# 差し替えるときは全部を書き換えないと元の実装が呼ばれ続ける。
_BOUND = (greedy, planner_mod, mcts_mod)


def _rebind(fn):
    for m in _BOUND:
        m.evaluate = fn


def _pair(kind, seed, **kw):
    if kind == "H":
        return [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)]
    if kind == "G":
        return [GreedyAgent(seed * 2, opp_decklist=POOL, **kw),
                HeuristicAgent(seed * 2 + 1)]
    if kind == "P":
        return [PlannerAgent(seed * 2, opp_decklist=POOL, **kw),
                HeuristicAgent(seed * 2 + 1)]
    return [MCTSAgent(seed * 2, iterations=160, opp_decklist=POOL, **kw),
            HeuristicAgent(seed * 2 + 1)]


# ---------------------------------------------------------------- 1. 呼び出し実態
def count_and_time(kind, n, collect=0, **kw):
    """n 局を2回走らせ、(局/秒, evaluate 回数/局, 標本局面) を返す。

    1回目: 計数器つき（回数と標本の採取）。2回目: 素の実装（速度）。
    """
    box = [0]
    samples = []
    every = max(1, 53)           # 標本は素数間隔で間引く（周期との共鳴を避ける）

    def counting(s, pi, w):
        box[0] += 1
        if collect and box[0] % every == 0 and len(samples) < collect:
            samples.append((s.clone(), pi))
        return EVAL(s, pi, w)

    _rebind(counting)
    for seed in range(n):
        play_game(CONFIG, _pair(kind, seed, **kw), seed=seed)
    calls = box[0]

    _rebind(EVAL)
    t0 = time.perf_counter()
    for seed in range(n):
        play_game(CONFIG, _pair(kind, seed, **kw), seed=seed)
    dt = time.perf_counter() - t0
    return n / dt, calls / n, samples


# ---------------------------------------------------------------- 2. 候補の実装
# 特徴は `c1_features` を正本とする（D-036 で observe を拡張したのに合わせ、
# 叩き台をモジュールに昇格した）。ここでは速度計測のためだけに参照する。
N_FEAT = c1_features.N_FEAT
features = c1_features.from_state
_CONC_TARGET = c1_features.CONCERTO_TARGET


def _randn(rng, n, sc):
    return [rng.gauss(0.0, sc) for _ in range(n)]


class LinearVF:
    """線形モデル（純Python）。学習後もこの形なら現行とほぼ同速のはず。"""

    def __init__(self, seed=0):
        rng = random.Random(seed)
        self.w = _randn(rng, N_FEAT, 0.1)
        self.b = 0.0

    def __call__(self, s, pi, w=None):
        if s.outcome is not None:
            return 0.0 if s.outcome == DRAW else (
                greedy.WIN if s.outcome == pi else -greedy.WIN)
        x = features(s, pi)
        ww = self.w
        v = self.b
        for i in range(N_FEAT):
            v += ww[i] * x[i]
        return v


class MLPPure:
    """MLP(N_FEAT → h → h → 1) の純Python推論。"""

    def __init__(self, h=32, seed=0):
        rng = random.Random(seed)
        sc = 1.0 / math.sqrt(N_FEAT)
        self.W1 = [_randn(rng, N_FEAT, sc) for _ in range(h)]
        self.b1 = _randn(rng, h, sc)
        self.W2 = [_randn(rng, h, sc) for _ in range(h)]
        self.b2 = _randn(rng, h, sc)
        self.W3 = _randn(rng, h, sc)
        self.b3 = 0.0
        self.h = h

    def __call__(self, s, pi, w=None):
        if s.outcome is not None:
            return 0.0 if s.outcome == DRAW else (
                greedy.WIN if s.outcome == pi else -greedy.WIN)
        x = features(s, pi)
        tanh = math.tanh
        a1 = [tanh(b + sum(wi * xi for wi, xi in zip(row, x)))
              for row, b in zip(self.W1, self.b1)]
        a2 = [tanh(b + sum(wi * ai for wi, ai in zip(row, a1)))
              for row, b in zip(self.W2, self.b2)]
        return self.b3 + sum(wi * ai for wi, ai in zip(self.W3, a2))


class MLPNumpy:
    """同じ MLP を numpy で（1局面ずつ呼ぶ形）。"""

    def __init__(self, h=32, seed=0):
        assert np is not None, "numpy が無い環境では使えない"
        rng = random.Random(seed)
        sc = 1.0 / math.sqrt(N_FEAT)
        self.W1 = np.array([_randn(rng, h, sc) for _ in range(N_FEAT)])
        self.b1 = np.array(_randn(rng, h, sc))
        self.W2 = np.array([_randn(rng, h, sc) for _ in range(h)])
        self.b2 = np.array(_randn(rng, h, sc))
        self.W3 = np.array(_randn(rng, h, sc))
        self.b3 = 0.0

    def __call__(self, s, pi, w=None):
        if s.outcome is not None:
            return 0.0 if s.outcome == DRAW else (
                greedy.WIN if s.outcome == pi else -greedy.WIN)
        x = np.asarray(features(s, pi))
        a1 = np.tanh(x @ self.W1 + self.b1)
        a2 = np.tanh(a1 @ self.W2 + self.b2)
        return float(a2 @ self.W3 + self.b3)

    def batch(self, X):
        a1 = np.tanh(X @ self.W1 + self.b1)
        a2 = np.tanh(a1 @ self.W2 + self.b2)
        return a2 @ self.W3 + self.b3


def features_nolr(s, pi):
    """live_reds を抜いた特徴（`live_reds` が単価の何割かを見るため）。"""
    me, opp = s.players[pi], s.players[1 - pi]
    lv_me = sum(CHARA_CARDS[sl.stack[-1]].level for sl in me.slots if sl.stack)
    lv_op = sum(CHARA_CARDS[sl.stack[-1]].level for sl in opp.slots if sl.stack)
    cm, co = len(me.concerto), len(opp.concerto)
    hm, ho = len(me.hand), len(opp.hand)
    cc_me, cc_op = s.clash_counts[pi], s.clash_counts[1 - pi]
    return [
        me.life - opp.life, me.life, opp.life,
        cm - co, cm, co, float(cm - _CONC_TARGET),
        hm - ho, hm, ho, 0.0, 0.0,
        lv_me - lv_op, lv_me,
        len(me.action_deck), len(opp.action_deck),
        len(me.trash), len(opp.trash),
        float(s.turn_no),
        cc_me[0] - cc_op[0], cc_me[1] - cc_op[1], cc_me[3] - cc_op[3],
    ]


# ---------------------------------------------------------------- 3. 単価の計測
_SLICE = 0.25       # 1回の計測にかける目安秒数（速い実装ほど反復を増やす）


def _measure(body, n_per_rep):
    """body() を n_per_rep 回ぶんの単位として、目安時間まで反復し中央値を返す。"""
    t0 = time.perf_counter()
    body()
    one = time.perf_counter() - t0
    reps = max(1, int(_SLICE / max(one, 1e-6)))
    got = []
    for _ in range(3):
        t0 = time.perf_counter()
        for _ in range(reps):
            body()
        got.append((time.perf_counter() - t0) / (reps * n_per_rep) * 1e6)
    return sorted(got)[1]


def micro(fn, samples):
    def body():
        for s, pi in samples:
            fn(s, pi, TUNED_WEIGHTS)
    return _measure(body, len(samples))


def micro_feat(fn, samples):
    def body():
        for s, pi in samples:
            fn(s, pi)
    return _measure(body, len(samples))


def micro_batch(model, samples, bs):
    """特徴抽出は1件ずつ、行列積だけ bs 件まとめる形の単価。"""
    def body():
        buf = []
        for s, pi in samples:
            buf.append(features(s, pi))
            if len(buf) == bs:
                model.batch(np.asarray(buf))
                buf = []
        if buf:
            model.batch(np.asarray(buf))
    return _measure(body, len(samples))


# ---------------------------------------------------------------- 4. 損益分岐
def breakeven(rate, calls, c_now, c_new):
    """単価を c_now → c_new に変えたときの局/秒（線形モデル）。"""
    per_game = 1.0 / rate
    other = per_game - calls * c_now * 1e-6
    return 1.0 / (other + calls * c_new * 1e-6), other / per_game


class Padded:
    """挙動を変えずコストだけ足す差し替え（予測式の検証用）。

    候補モデルを実際に呼んで結果を捨て、値は現行 `evaluate` を返す。
    こうすると**選ぶ手が変わらない**ので fingerprint が一致し、
    観測された局/秒の低下は純粋に単価の増加ぶんになる。
    """

    def __init__(self, cost_fn):
        self.cost = cost_fn

    def __call__(self, s, pi, w):
        self.cost(s, pi, w)
        return EVAL(s, pi, w)


def timed_fp(kind, n, **kw):
    """1回のランで局/秒と fingerprint を同時に取る。"""
    import hashlib
    sig = []
    t0 = time.perf_counter()
    for seed in range(n):
        r = play_game(CONFIG, _pair(kind, seed, **kw), seed=seed)
        sig.append((r["winner"], r["turns"], tuple(r["life"])))
    dt = time.perf_counter() - t0
    return n / dt, hashlib.sha256(repr(sig).encode()).hexdigest()[:16]


def insitu(kind, rate, calls, c_now, samples, n, cands):
    """**実測**の損益分岐（挙動不変のコスト付加）。

    候補モデルを実対局の中で呼んで結果を捨て、値は現行 evaluate を返す。
    選ぶ手が変わらないので fingerprint が一致し、観測された低下は
    純粋に単価の増加ぶんになる。微小ベンチからの予測も並記して、
    予測式（1局 = その他 + 回数 × 単価）がどれだけ当たるかを見る。
    """
    base_rate, base_fp = timed_fp(kind, n)
    print(f"基準: {base_rate:.2f} 局/秒 (n={n}, fingerprint {base_fp})")
    print(f"{'付加した評価器':<32}{'実測':>7}{'低下':>8}{'実効単価':>10}"
          f"{'微小ベンチ':>10}{'予測':>7}  fp")
    for label, model in cands:
        c_micro = micro(model, samples)
        _rebind(Padded(model))
        obs, fp = timed_fp(kind, n)
        _rebind(EVAL)
        # 実効単価: 1局の増加時間 ÷ 呼び出し回数（これが本当のコスト）
        c_eff = (1 / obs - 1 / base_rate) / calls * 1e6
        pred, _ = breakeven(base_rate, calls, 0.0, c_micro)
        ok = "一致" if fp == base_fp else f"不一致({fp})"
        print(f"{label:<32}{obs:>7.2f}{(1 - obs / base_rate) * 100:>7.1f}%"
              f"{c_eff:>9.1f}µs{c_micro:>9.1f}µs{pred:>7.2f}  {ok}")


def knob_curve(n):
    """探索の予算つまみを削ったときの局/秒と evaluate 回数。

    「単価が上がったぶんを予算削減で払えるか」を判断する材料。
    予算が**実際には効いていない**つまみは、払う原資にならない。
    """
    print("\n== 6. 探索予算のつまみと速度（計画探索） ==")
    print(f"{'設定':<24}{'局/秒':>9}{'eval回/局':>12}")
    base = None
    for label, kw in (("既定 (budget220, ps4)", {}),
                      ("leaf_budget=110", {"leaf_budget": 110}),
                      ("leaf_budget=55", {"leaf_budget": 55}),
                      ("plan_samples=2", {"plan_samples": 2}),
                      ("plan_samples=1", {"plan_samples": 1})):
        rate, calls, _ = count_and_time("P", n, **kw)
        if base is None:
            base = calls
        print(f"{label:<24}{rate:>9.2f}{calls:>12.0f}"
              f"   (eval回 {calls / base * 100:>5.1f}%)")


def leaf_profile(n):
    """1決定化あたりの終端数の分布。`leaf_budget` が実際に効いているかを見る。

    §6 で leaf_budget を半分にしても evaluate 回数が変わらなかったので、
    予算は**上限として機能していない**という仮説を直接確かめる。
    """
    print("\n== 7. 1決定化あたりの終端数（leaf_budget=220 は効いているか） ==")
    counts = []
    orig = PlannerAgent._search

    def patched(self, t, pi, first, depth, leaves, seen):
        top = first is None
        if top:
            before = len(leaves)
        orig(self, t, pi, first, depth, leaves, seen)
        if top:
            counts.append(len(leaves) - before)

    PlannerAgent._search = patched
    for seed in range(n):
        play_game(CONFIG, _pair("P", seed), seed=seed)
    PlannerAgent._search = orig
    counts.sort()
    if not counts:
        print("（採取できず）")
        return
    q = lambda f: counts[min(len(counts) - 1, int(len(counts) * f))]   # noqa: E731
    print(f"決定化 {len(counts)} 回 / 終端数: 中央値 {q(0.5)}  "
          f"90%点 {q(0.9)}  99%点 {q(0.99)}  最大 {counts[-1]}")
    hit = sum(1 for c in counts if c >= 220)
    print(f"予算 220 に到達した決定化: {hit} 回 ({hit / len(counts) * 100:.2f}%)")


def main():
    quick = "--quick" in sys.argv
    print(f"処理系: {sys.implementation.name} {sys.version.split()[0]} / "
          f"numpy {np.__version__ if np is not None else 'なし'} / "
          f"CPU {os.cpu_count()}")
    print(f"デッキ SD001 同型・rules v0.10・シード帯 0..（速度のみ、勝率の主張なし）\n")

    plans = [("P", "計画探索 vs H", 6 if quick else 12),
             ("G", "貪欲 vs H", 15 if quick else 30),
             ("M", "IS-MCTS(160) vs H", 2 if quick else 4)]

    print("== 1. evaluate の呼び出し実態 ==")
    print(f"{'エージェント':<20}{'局/秒':>9}{'eval回/局':>12}{'eval/秒':>11}")
    stats, samples = {}, []
    for kind, label, n in plans:
        rate, calls, smp = count_and_time(kind, n, collect=(300 if kind == "P" else 0))
        stats[kind] = (label, rate, calls)
        samples += smp
        print(f"{label:<20}{rate:>9.2f}{calls:>12.0f}{rate * calls:>11.0f}")

    if not samples:
        print("標本が採れなかった")
        return
    print(f"\n標本局面 {len(samples)} 件（計画探索の実対局から間引き採取）")

    print("\n== 2. 1回あたりの単価（マイクロ秒・3回測って中央値） ==")
    c_now = micro(EVAL, samples)
    rows = [
        ("現行 evaluate（6項・純Python）", c_now, True),
        ("  └ 特徴抽出のみ 22項", micro_feat(features, samples), False),
        ("  └ 特徴抽出のみ 22項（live_reds 抜き）",
         micro_feat(features_nolr, samples), False),
        ("線形 22項（純Python）", micro(LinearVF(), samples), True),
        ("MLP 22-32-32-1（純Python）", micro(MLPPure(32), samples), True),
        ("MLP 22-64-64-1（純Python）", micro(MLPPure(64), samples), True),
    ]
    if np is not None:
        mlp_np = MLPNumpy()
        rows += [
            ("MLP 22-32-32-1（numpy 1件ずつ）", micro(mlp_np, samples), True),
            ("MLP 22-32-32-1（numpy 32件バッチ）",
             micro_batch(mlp_np, samples, 32), True),
            ("MLP 22-32-32-1（numpy 220件バッチ）",
             micro_batch(mlp_np, samples, 220), True),
        ]
    else:
        print("（numpy が無いので numpy 実装は測らない）")
    for label, c, show in rows:
        print(f"{label:<40}{c:>8.2f} µs" + (f"   ×{c / c_now:>5.1f}" if show else ""))

    print("\n== 3. 損益分岐（単価を上げたとき計画探索の局/秒がどうなるか） ==")
    label, rate, calls = stats["P"]
    _, frac_other = breakeven(rate, calls, c_now, c_now)
    print(f"計画探索: {rate:.2f} 局/秒 / evaluate {calls:.0f} 回/局 / "
          f"1局に占める evaluate は {(1 - frac_other) * 100:.1f}%")
    print(f"{'単価':>9}{'倍率':>7}{'局/秒':>9}{'低下':>8}")
    for c in (c_now, 2 * c_now, 5 * c_now, 10 * c_now, 20 * c_now,
              50 * c_now, 100 * c_now):
        r, _ = breakeven(rate, calls, c_now, c)
        print(f"{c:>7.1f}µs{c / c_now:>7.1f}{r:>9.2f}{(1 - r / rate) * 100:>7.1f}%")

    print("\n== 4. 参考: 他エージェント ==")
    for kind in ("G", "M"):
        label, rate_k, calls_k = stats[kind]
        _, fo = breakeven(rate_k, calls_k, c_now, c_now)
        r10, _ = breakeven(rate_k, calls_k, c_now, 10 * c_now)
        r100, _ = breakeven(rate_k, calls_k, c_now, 100 * c_now)
        print(f"{label:<20} {rate_k:>7.2f} 局/秒  eval {calls_k:>6.0f} 回/局  "
              f"eval {(1 - fo) * 100:>5.1f}%  ×10→{r10:>7.2f}  ×100→{r100:>6.2f}")

    print("\n== 5. 実測の損益分岐（挙動不変のコスト付加・計画探索） ==")
    cands = [("線形 22項（純Python）", LinearVF()),
             ("MLP 22-32-32-1（純Python）", MLPPure(32)),
             ("MLP 22-64-64-1（純Python）", MLPPure(64))]
    if np is not None:
        cands.append(("MLP 22-32-32-1（numpy 1件ずつ）", MLPNumpy(32)))
    insitu("P", rate, calls, c_now, samples, 5 if quick else 12, cands)

    knob_curve(5 if quick else 12)
    leaf_profile(5 if quick else 10)

    if "--mcts" in sys.argv:
        print("\n== 8. 実測の損益分岐（IS-MCTS(160)。B-1 が葉評価を弱点と診断した相手） ==")
        _, rate_m, calls_m = stats["M"]
        mc = [("線形 22項（純Python）", LinearVF()),
              ("MLP 22-32-32-1（純Python）", MLPPure(32))]
        if np is not None:
            mc.append(("MLP 22-32-32-1（numpy 1件ずつ）", MLPNumpy(32)))
        insitu("M", rate_m, calls_m, c_now, samples, 3 if quick else 6, mc)


if __name__ == "__main__":
    main()
