"""B-3 の効果測定: 相手モデルの脱固定化（レビュー 2026-08-23 §6 B-3）。

仮説: 相手モデルを固定ヒューリスティックから「対抗で観測した色の経験分布との
混合」に替えると、**色方策が既定Hと違う相手**への見積もりが改善する。
既定Hが相手のときは事前分布が既に正しいので、改善しないはずである。
**この非対称な予測が当たるかどうか**が、機構が意図どおり働いた証拠になる。

同じシード帯で「履歴あり」と「履歴なし（従来）」を測り、差分を寄与とする。
シード帯 50000.. は本測定で初めて使う（A-3/A-4/A-5 のどれとも重ならない）。

使い方: python3 experiments/measure_oppmodel.py [n] [plan_samples] [workers]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import load_deck, mirror_config, series                   # noqa: E402
from meicho.greedy import GreedyAgent                                # noqa: E402
from meicho.heuristic import HeuristicAgent, Params                  # noqa: E402
from meicho.planner import PlannerAgent                              # noqa: E402

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]
SEED0 = 50000


class MkP:
    def __init__(self, use_history, plan_samples=4, prior_strength=8.0):
        self.kw = dict(use_history=use_history, plan_samples=plan_samples,
                       prior_strength=prior_strength)

    def __call__(self, seed):
        return PlannerAgent(seed, opp_decklist=POOL, **self.kw)


class MkH:
    def __init__(self, **kw):
        self.kw = kw

    def __call__(self, seed):
        return HeuristicAgent(seed, Params(**self.kw))


class MkG:
    def __call__(self, seed):
        return GreedyAgent(seed, opp_decklist=POOL, use_history=False)


# 色方策が既定Hからどれだけ離れているかで並べた相手プール
OPPONENTS = {
    "H_default (own=12・事前分布と一致)": MkH(),
    "π_det   (own=1000・自色確定)": MkH(own_color_weight=1000.0),
    "π_mix   (own=1.5・よく混ぜる)": MkH(own_color_weight=1.5),
    "X3      (counter=6・踏み型)": MkH(counter_weight=6.0, own_color_weight=1.5),
    "貪欲    (別クラスの相手)": MkG(),
}


def run(n, plan_samples, workers):
    on = MkP(True, plan_samples)
    off = MkP(False, plan_samples)
    print(f"計画探索の勝率（n={n}, plan_samples={plan_samples}, シード帯 {SEED0}..）\n")
    print("| 相手 | 履歴あり | 履歴なし（従来） | 差分 |")
    print("|---|---|---|---|")
    for name, opp in OPPONENTS.items():
        a = series(on, opp, n, CONFIG, workers, SEED0)
        b = series(off, opp, n, CONFIG, workers, SEED0)
        print(f"| {name} | {a} | {b} | {a.p - b.p:+.3f} |", flush=True)
    head = series(on, off, n, CONFIG, workers, SEED0)
    print(f"\n直接対決 履歴あり vs 履歴なし: {head}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    ps = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    run(n, ps, workers)
