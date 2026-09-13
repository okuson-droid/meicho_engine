"""速度ベンチマーク＋処理系間の決定性チェック（標準ライブラリのみ）。

CPython と PyPy の両方で実行し、
  (1) 局/秒を比較する
  (2) fingerprint（勝者・ターン数・ライフの列のハッシュ）が一致することを確認する
      → 一致すれば「同シード同結果」が処理系をまたいで保たれている（D-001 の趣旨）。

実行: python3 experiments/bench_speed.py / pypy3 experiments/bench_speed.py
"""
import sys, os, json, time, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.engine import GameConfig
from meicho.heuristic import HeuristicAgent
from meicho.greedy import GreedyAgent
from meicho.runner import play_game

DECK = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                   "decklists", "SD001.json"), encoding="utf-8"))
CONFIG = GameConfig(chara_decks=[DECK["chara_deck"]] * 2,
                    action_decks=[DECK["action_deck"]] * 2)

print(f"処理系: {sys.implementation.name} {sys.version.split()[0]}")

# --- 決定性フィンガープリント（seeds 0..49, ヒューリスティック同型） ---
sig = []
for seed in range(50):
    r = play_game(CONFIG, [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)],
                  seed=seed)
    sig.append((r["winner"], r["turns"], tuple(r["life"])))
fp = hashlib.sha256(repr(sig).encode()).hexdigest()[:16]
print(f"fingerprint(H同型 seeds0-49) = {fp}")

# --- ウォームアップ（PyPy の JIT を温める。CPython では単なる追加試行） ---
for seed in range(100):
    play_game(CONFIG, [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)], seed=seed)

# --- ヒューリスティック速度 ---
t0 = time.time()
N = 300
for seed in range(N):
    play_game(CONFIG, [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)], seed=seed)
dt = time.time() - t0
print(f"ヒューリスティック同型: {N/dt:.0f} 局/秒")

# --- 貪欲速度 ---
t0 = time.time()
M = 20
for seed in range(M):
    play_game(CONFIG, [GreedyAgent(seed * 2, opp_decklist=DECK["action_deck"]),
                       HeuristicAgent(seed * 2 + 1)], seed=seed)
dt = time.time() - t0
print(f"貪欲 vs ヒューリスティック: {M/dt:.1f} 局/秒")
