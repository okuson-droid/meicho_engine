"""A-3: 評価関数の重み × ヒューリスティックParams の結合最適化（CEM）。

レビュー 2026-08-23 §3.6 / §6 A-3。単軸の掃引は相互作用を見落として誤導するため
（引継ぎ書 §7.6）、交差エントロピー法 (CEM) で同時に探索する。

## in-sample 化を仕組みで防ぐ（§7.1 への恒久対策）

- **探索**: 相手プール = {H_default, X1, X2}、シード帯 = 0..N-1（固定）。
- **検証**: シード帯 = 10000.. （探索で一度も使っていない）かつ、
  **プールに入れていない相手** X3・貪欲・既定の計画探索と当てる。
  探索中にこの検証は一切見ない。

探索対象は計画探索エージェント (PlannerAgent)。評価関数の重みと、
非担当フェイズを預けているヒューリスティックのParamsを1本のベクトルにまとめ、
同時に動かす。

使い方:
    python3 experiments/optimize_cem.py [iters] [pop] [games] [workers]
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import gauntlet, load_deck, mirror_config, series          # noqa: E402
from meicho.greedy import GreedyAgent, Weights                        # noqa: E402
from meicho.heuristic import HeuristicAgent, Params                   # noqa: E402
from meicho.planner import PlannerAgent                               # noqa: E402

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]

# --- 探索空間 -------------------------------------------------------------
# (名前, 初期値, 探索の初期σ, 下限, 上限, 整数か)
SPACE = [
    # 評価関数の重み（life は尺度の基準なので固定し、他を相対値として動かす）
    ("w_concerto",       0.8, 0.5,  0.0, 4.0, False),
    ("w_hand",           0.5, 0.4,  0.0, 3.0, False),
    ("w_live_red",       0.4, 0.4,  0.0, 3.0, False),
    ("w_level",          0.0, 0.5, -1.0, 3.0, False),
    ("w_resource",      0.05, 0.2, -0.5, 1.0, False),
    # ヒューリスティック側（非担当フェイズと相手モデルを兼ねる）
    ("p_own_color",     12.0, 6.0,  0.0, 40.0, False),
    ("p_counter",        0.0, 3.0,  0.0, 15.0, False),
    ("p_scarce",        0.35, 0.3,  0.0, 1.0, False),
    ("p_concerto_tgt",   4.0, 1.5,  2.0, 8.0, True),
    ("p_charge_min",     2.0, 1.5,  0.0, 6.0, True),
    ("p_levelup_min",    5.0, 2.0,  0.0, 8.0, True),
    ("p_switch_gain",    2.0, 1.0,  1.0, 4.0, True),
    ("p_pay_concerto",   3.0, 1.5,  0.0, 8.0, True),
]
NAMES = [x[0] for x in SPACE]


def to_agent_kwargs(v: dict) -> dict:
    w = Weights(life=1.0, concerto=v["w_concerto"], hand=v["w_hand"],
                live_red=v["w_live_red"], level=v["w_level"],
                resource=v["w_resource"])
    p = Params(own_color_weight=v["p_own_color"], counter_weight=v["p_counter"],
               scarce_penalty=v["p_scarce"],
               concerto_target=int(v["p_concerto_tgt"]),
               charge_min_hand=int(v["p_charge_min"]),
               levelup_min_hand=int(v["p_levelup_min"]),
               switch_min_gain=int(v["p_switch_gain"]),
               pay_min_concerto=int(v["p_pay_concerto"]))
    return {"weights": w, "params": p}


class MkPlanner:
    """pickle 可能な生成器。Params は fallback に差し込む。"""

    def __init__(self, weights, params, plan_samples=2):
        self.weights, self.params, self.plan_samples = weights, params, plan_samples

    def __call__(self, seed):
        a = PlannerAgent(seed, weights=self.weights, opp_decklist=POOL,
                         plan_samples=self.plan_samples)
        a.fallback = HeuristicAgent(seed, self.params)
        return a


class MkH:
    def __init__(self, params=None):
        self.params = params

    def __call__(self, seed):
        return HeuristicAgent(seed, self.params)


class MkG:
    def __call__(self, seed):
        return GreedyAgent(seed, opp_decklist=POOL)


# --- 相手プール -----------------------------------------------------------
SEARCH_POOL = {
    "H_default": MkH(),
    "X1": MkH(Params(concerto_target=3, levelup_min_hand=4)),
    "X2": MkH(Params(own_color_weight=3.0, scarce_penalty=0.7, switch_min_gain=1)),
}
HOLDOUT_POOL = {                     # 探索中は一切見ない
    "X3(踏み型)": MkH(Params(counter_weight=6.0, own_color_weight=1.5)),
    "貪欲": MkG(),
    "計画探索(既定重み)": MkPlanner(Weights(), Params(), plan_samples=2),
}
SEARCH_SEED0 = 0
HOLDOUT_SEED0 = 10000


def evaluate_vector(v, games, workers, plan_samples=2, pool=None, seed0=None):
    mk = MkPlanner(**to_agent_kwargs(v), plan_samples=plan_samples)
    return gauntlet(mk, pool or SEARCH_POOL, games, CONFIG, workers,
                    SEARCH_SEED0 if seed0 is None else seed0)["mean"]


def cem(iters, pop, games, workers, seed=20260823, pool=None, seed0=None,
        quiet=False):
    """交差エントロピー法。pool を差し替えると別の目的関数に対して探索できる
    （A-5 の最適応答探索が同じ機構を使う）。"""
    rng = random.Random(seed)
    mu = {n: x[1] for n, x in zip(NAMES, SPACE)}
    sg = {n: x[2] for n, x in zip(NAMES, SPACE)}
    n_elite = max(2, pop // 4)
    history = []
    for it in range(iters):
        cands = []
        for _ in range(pop):
            v = {}
            for name, _init, _s, lo, hi, is_int in SPACE:
                x = rng.gauss(mu[name], sg[name])
                x = min(max(x, lo), hi)
                v[name] = round(x) if is_int else x
            cands.append(v)
        scored = [(evaluate_vector(v, games, workers, pool=pool, seed0=seed0), v)
                  for v in cands]
        scored.sort(key=lambda t: -t[0])
        elite = [v for _, v in scored[:n_elite]]
        for name, _i, _s, lo, hi, is_int in SPACE:
            vals = [e[name] for e in elite]
            m = sum(vals) / len(vals)
            var = sum((x - m) ** 2 for x in vals) / len(vals)
            mu[name] = m
            # σの下限を残して早すぎる収束を防ぐ（初期σの15%）
            sg[name] = max(var ** 0.5, 0.15 * dict(zip(NAMES, [x[2] for x in SPACE]))[name])
        best = scored[0]
        history.append({"iter": it, "best": best[0],
                        "mean_pop": sum(s for s, _ in scored) / len(scored),
                        "mu": dict(mu)})
        if not quiet:
            print(f"[iter {it}] best={best[0]:.3f} pop_mean="
                  f"{history[-1]['mean_pop']:.3f} mu_own_color={mu['p_own_color']:.1f} "
                  f"mu_concerto={mu['w_concerto']:.2f}", flush=True)
    return mu, history


if __name__ == "__main__":
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    pop = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    games = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 2

    mu, history = cem(iters, pop, games, workers)
    print("\n=== 探索結果（平均ベクトル）===")
    for n in NAMES:
        print(f"  {n:16s} {mu[n]:.3f}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "cem_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"mu": mu, "history": history,
                   "search": {"pool": list(SEARCH_POOL), "seed0": SEARCH_SEED0,
                              "games": games, "iters": iters, "pop": pop}},
                  f, ensure_ascii=False, indent=2)
    print(f"→ {out}")

    print("\n=== 検証（未使用シード帯 10000.. / 未使用の相手）===")
    tuned = MkPlanner(**to_agent_kwargs(mu), plan_samples=4)
    base = MkPlanner(Weights(), Params(), plan_samples=4)
    for name, opp in list(SEARCH_POOL.items()) + list(HOLDOUT_POOL.items()):
        tag = "探索プール" if name in SEARCH_POOL else "**未使用**"
        r_t = series(tuned, opp, 150, CONFIG, workers, HOLDOUT_SEED0)
        r_b = series(base, opp, 150, CONFIG, workers, HOLDOUT_SEED0)
        print(f"  vs {name:20s} [{tag}] 調整後 {r_t} / 既定 {r_b}")
