"""レビュー検証スクリプト（2026-08-23 レビューセッション）。

目的:
  (1) 引継ぎ書 §4.4 の勝率を独立に再現する（小規模 n）
  (2) 引継ぎ書 §7.1「貪欲の重みが対ヒューリスティックで過適合している疑い」を
      第三の相手（パラメータを変えたヒューリスティック）への転移で検証する。

転移の測り方:
  貪欲の非担当フェイズは既定ヒューリスティックに委譲しているため、
  「貪欲 vs X」の勝率単体では貪欲の寄与が分からない。
  対照として「既定ヒューリスティック vs X」を測り、その差分を貪欲の寄与とする。

シードは 0..N-1 を決定的に使用（decisions.md D-006 規約）。
"""
import sys, os, json, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.engine import GameConfig
from meicho.agents import RandomAgent
from meicho.heuristic import HeuristicAgent, Params
from meicho.greedy import GreedyAgent
from meicho.runner import play_game

DECK = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                   "decklists", "SD001.json"), encoding="utf-8"))
CONFIG = GameConfig(chara_decks=[DECK["chara_deck"]] * 2,
                    action_decks=[DECK["action_deck"]] * 2)
CONFIG.validate()
ACTION = DECK["action_deck"]


def series(make_a, make_b, n, label):
    """n局（先攻後攻を入れ替えた両方向）で A の勝率を測る。"""
    wins = decided = 0
    for seed in range(n):
        if seed % 2 == 0:
            agents = [make_a(seed * 2), make_b(seed * 2 + 1)]
            a_idx = 0
        else:
            agents = [make_b(seed * 2), make_a(seed * 2 + 1)]
            a_idx = 1
        r = play_game(CONFIG, agents, seed=seed)
        if r["aborted"] or r["draw"]:
            continue
        decided += 1
        if r["winner"] == a_idx:
            wins += 1
    p = wins / decided
    ci = 1.96 * math.sqrt(p * (1 - p) / decided)
    print(f"{label}: {p:.3f} ±{ci:.3f} (n={decided})")
    return p, ci


H = lambda params: (lambda seed: HeuristicAgent(seed, params))
G = lambda seed: GreedyAgent(seed, opp_decklist=ACTION)

print("== (1) 引継ぎ書 §4.4 の再現（小規模） ==")
series(H(Params()), (lambda s: RandomAgent(s)), 400, "H_default vs Random   ")
series(G, H(Params()), 300, "Greedy    vs H_default")

print()
print("== (2) §7.1 転移検証: 第三の相手 X に対する 貪欲 と 対照(既定H) ==")
THIRD = {
    "X1 concerto=3,lvup=4     ": Params(concerto_target=3, levelup_min_hand=4),
    "X2 own=3,scarce=.7,sw=1  ": Params(own_color_weight=3.0,
                                        scarce_penalty=0.7, switch_min_gain=1),
    "X3 counter=6(踏み型)      ": Params(counter_weight=6.0, own_color_weight=1.5),
}
for name, params in THIRD.items():
    pg, cg = series(G, H(params), 300, f"Greedy    vs {name}")
    ph, ch = series(H(Params()), H(params), 1000, f"H_default vs {name}")
    print(f"  → 貪欲の寄与(差分): {pg - ph:+.3f}")
    print()
