"""A-1 の効果測定: 公正化した貪欲の対ヒューリスティック勝率。

レビュー 2026-08-23 §3.4 / §6 A-1。旧版（デッキ順序を覗いていた）の
0.680 ±0.053 (n=300) と同一シードで比較する。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import load_deck, mirror_config, series, report
from meicho.greedy import GreedyAgent
from meicho.heuristic import HeuristicAgent

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]


class _G:
    """pickle 可能なファクトリ（プロセス並列のため）。"""

    def __init__(self, **kw):
        self.kw = kw

    def __call__(self, seed):
        return GreedyAgent(seed, opp_decklist=POOL, **self.kw)


class _H:
    def __init__(self, **kw):
        self.kw = kw

    def __call__(self, seed):
        return HeuristicAgent(seed, **self.kw)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    report("公正化した貪欲 vs H_default",
           series(_G(), _H(), n, CONFIG, workers=w))
