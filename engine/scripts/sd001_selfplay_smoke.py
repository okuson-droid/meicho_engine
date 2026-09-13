"""SD001反映後の健全性チェック: 実デッキ(decklists/SD001.json)でランダム自己対戦を回す。

再現: python3 scripts/sd001_selfplay_smoke.py
（decisions.md D-006 規約: シードは 0..N-1 を決定的に使用。乱数はエージェント側のみ。）
"""
import sys, os, json, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.engine import GameConfig
from meicho.agents import RandomAgent
from meicho.runner import play_game

DECKLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "decklists", "SD001.json")

with open(DECKLIST_PATH, encoding="utf-8") as f:
    _d = json.load(f)

CHARA = _d["chara_deck"]
ACTION = _d["action_deck"]
assert len(CHARA) == 9 and len(ACTION) == 40

config = GameConfig(chara_decks=[CHARA, CHARA], action_decks=[ACTION, ACTION])
config.validate()

N = 1000
aborted = 0
draws = 0
first_wins = 0
turns = []
for seed in range(N):
    agents = [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)]
    result = play_game(config, agents, seed=seed)
    if result["aborted"]:
        aborted += 1
        print("ABORTED", seed, result)
        continue
    turns.append(result["turns"])
    if result["draw"]:
        # §9-5 / D-021: 進行不能状態による引き分け。勝敗のどちらにも数えない。
        draws += 1
        print("DRAW", seed, result)
    elif result["winner"] == 0:
        first_wins += 1

decided = len(turns) - draws
p = first_wins / decided if decided else float("nan")
ci = 1.96 * math.sqrt(p * (1 - p) / decided) if decided else float("nan")
print(f"games={N} aborted={aborted} draws={draws} "
      f"avg_turns={sum(turns)/len(turns):.1f} min={min(turns)} max={max(turns)}")
print(f"先攻勝率={p:.3f} ±{ci:.3f} (n={decided}, 引き分けを除く)")
