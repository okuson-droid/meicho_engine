"""速度ベンチマーク＋決定性フィンガープリント（B-2）。

`bench_speed.py` の後継。最適化の対象が貪欲から**計画探索**に移ったので、
3エージェントぶんの速度と fingerprint をまとめて出す。

**fingerprint は挙動不変の受け入れテストである。** 速度だけを変える施策
（clone の高速化・処理系の変更など）は、必ずこのハッシュを一致させること。
挙動を変える施策（標本数・枝刈り）は一致しないので、勝率で別途確認する。

実行: python3 experiments/bench_agents.py [--profile]
"""
import hashlib
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import load_deck, mirror_config                            # noqa: E402
from meicho.greedy import GreedyAgent                                 # noqa: E402
from meicho.heuristic import HeuristicAgent                           # noqa: E402
from meicho.planner import PlannerAgent                               # noqa: E402
from meicho.runner import play_game                                   # noqa: E402

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]


def _pair(kind, seed):
    if kind == "H":
        return [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)]
    if kind == "G":
        return [GreedyAgent(seed * 2, opp_decklist=POOL),
                HeuristicAgent(seed * 2 + 1)]
    return [PlannerAgent(seed * 2, opp_decklist=POOL),
            HeuristicAgent(seed * 2 + 1)]


def fingerprint(kind, n):
    sig = []
    for seed in range(n):
        r = play_game(CONFIG, _pair(kind, seed), seed=seed)
        sig.append((r["winner"], r["turns"], tuple(r["life"])))
    return hashlib.sha256(repr(sig).encode()).hexdigest()[:16]


def speed(kind, n):
    t0 = time.time()
    for seed in range(n):
        play_game(CONFIG, _pair(kind, seed), seed=seed)
    return n / (time.time() - t0)


def main():
    print(f"処理系: {sys.implementation.name} {sys.version.split()[0]}")
    for kind, label, nfp, nsp in (("H", "ヒューリスティック同型", 50, 300),
                                  ("G", "貪欲 vs H          ", 20, 20),
                                  ("P", "計画探索 vs H      ", 10, 10)):
        fp = fingerprint(kind, nfp)
        sp = speed(kind, nsp)
        print(f"{label}: {sp:8.1f} 局/秒   fingerprint(seeds0-{nfp-1}) = {fp}")


def profile():
    import cProfile
    import pstats
    pr = cProfile.Profile()
    pr.enable()
    for seed in range(6):
        play_game(CONFIG, _pair("P", seed), seed=seed)
    pr.disable()
    st = pstats.Stats(pr)
    st.sort_stats("cumulative")
    print("\n=== 計画探索 6局 / 累積時間 上位 ===")
    st.print_stats(22)
    st.sort_stats("tottime")
    print("\n=== 自身の時間 上位 ===")
    st.print_stats(18)


if __name__ == "__main__":
    if "--profile" in sys.argv:
        profile()
    else:
        main()
