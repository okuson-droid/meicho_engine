"""エージェント比較の定点観測（レビュー 2026-08-23 §6 A-1 / A-2 の効果測定）。

すべて SD001 同型・固定シード 0..n-1・先攻後攻は seed の偶奇で入替。
使い方: python3 experiments/measure_agents.py [n] [workers]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import load_deck, mirror_config, series, report
from meicho.greedy import GreedyAgent
from meicho.heuristic import HeuristicAgent, Params
from meicho.planner import PlannerAgent
from meicho.state import Phase

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]


class Mk:
    """pickle 可能なエージェント生成器（プロセス並列のため）。"""

    def __init__(self, cls, **kw):
        self.cls, self.kw = cls, kw

    def __call__(self, seed):
        return self.cls(seed, **self.kw)


H = Mk(HeuristicAgent)
G = Mk(GreedyAgent, opp_decklist=POOL)
P = Mk(PlannerAgent, opp_decklist=POOL)                      # A-2 + A-3（既定）
P_RAW = Mk(PlannerAgent, opp_decklist=POOL, tuned=False)     # A-2 のみ（手調整の重み）
# アクションフェイズだけを計画探索にした版（A-2 単体の寄与を見る）
P_ACT = Mk(PlannerAgent, opp_decklist=POOL, phases={Phase.ACTION}, tuned=False)

# 第三の相手（レビュー §3.1 と同じ摂動ヒューリスティック）。in-sample を避ける。
X1 = Mk(HeuristicAgent, params=Params(concerto_target=3, levelup_min_hand=4))
X2 = Mk(HeuristicAgent, params=Params(own_color_weight=3.0, scarce_penalty=0.7,
                                      switch_min_gain=1))
X3 = Mk(HeuristicAgent, params=Params(counter_weight=6.0, own_color_weight=1.5))

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    print(f"--- 対 H_default (n={n}) ---")
    report("貪欲(公正化)             ", series(G, H, n, CONFIG, w))
    report("計画探索(アクションのみ・手調整)", series(P_ACT, H, n, CONFIG, w))
    report("計画探索(A-2のみ・手調整) ", series(P_RAW, H, n, CONFIG, w))
    report("計画探索(A-2+A-3・既定)   ", series(P, H, n, CONFIG, w))
    print(f"--- 第三の相手への転移 (n={n}) ---")
    for name, X in (("X1", X1), ("X2", X2), ("X3", X3)):
        report(f"計画探索 vs {name}       ", series(P, X, n, CONFIG, w))
        report(f"  対照 H_default vs {name}", series(H, X, n, CONFIG, w))
    print(f"--- 直接対決 (n={n}) ---")
    report("計画探索 vs 貪欲          ", series(P, G, n, CONFIG, w))
    report("計画探索(A-3後) vs (A-3前)", series(P, P_RAW, n, CONFIG, w))
