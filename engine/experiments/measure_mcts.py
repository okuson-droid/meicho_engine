"""B-1 の効果測定: IS-MCTS(DUCT)（レビュー 2026-08-23 §6 B-1）。

シード帯 70000.. は本測定で初めて使う（A-3/A-4/A-5/B-3 のどれとも重ならない）。

使い方: python3 experiments/measure_mcts.py [n] [workers] [iters...]
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import load_deck, mirror_config, series                   # noqa: E402
from meicho.heuristic import HeuristicAgent                          # noqa: E402
from meicho.mcts import MCTSAgent                                    # noqa: E402
from meicho.planner import PlannerAgent                              # noqa: E402
from meicho.runner import play_game                                  # noqa: E402

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]
SEED0 = 70000


class MkM:
    def __init__(self, **kw):
        self.kw = kw

    def __call__(self, seed):
        return MCTSAgent(seed, opp_decklist=POOL, **self.kw)


class MkP:
    def __call__(self, seed):
        return PlannerAgent(seed, opp_decklist=POOL)


class MkH:
    def __call__(self, seed):
        return HeuristicAgent(seed)


def speed(mk, n=4):
    t0 = time.time()
    for seed in range(n):
        play_game(CONFIG, [mk(seed * 2), HeuristicAgent(seed * 2 + 1)], seed=seed)
    return n / (time.time() - t0)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    iters = [int(x) for x in sys.argv[3:]] or [40, 80, 160]

    print(f"| 反復数 | vs H_default | vs 計画探索 | 速度(単プロセス) |")
    print("|---|---|---|---|")
    for it in iters:
        mk = MkM(iterations=it)
        a = series(mk, MkH(), n, CONFIG, w, SEED0)
        b = series(mk, MkP(), n, CONFIG, w, SEED0)
        sp = speed(mk)
        print(f"| {it} | {a} | {b} | {sp:.2f} 局/秒 |", flush=True)
