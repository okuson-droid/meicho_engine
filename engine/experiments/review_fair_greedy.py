"""レビュー用: 公正版貪欲（先読み時にデッキ順序も決定化する）の強さ測定。

review_nopeek_audit.py で発見した「貪欲の先読みが自分のデッキ順序
（＝未来のドロー）を参照している」問題への対処案と、その勝率影響の測定。

対処: 先読みに使う局面の複製で、両者のデッキ順序をエージェントの乱数で
シャッフルする（相手手札の標本抽出と同じ「決定化」の一部として扱う）。

結果 (2026-08-23): 公正版 0.637 ±0.054 (n=300) vs 元の 0.680 ±0.053 (n=300)。
差は信頼区間内であり、貪欲の優位はデッキ順序の覗き見によるものではない。
ただし探索を深くするほど（IS-MCTS等）この漏洩は拡大するため、修正して
本体に取り込むことを推奨する。
"""
import sys, os, json, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.engine import GameConfig, apply, legal_actions
from meicho.heuristic import HeuristicAgent
from meicho.greedy import GreedyAgent, evaluate
from meicho.runner import play_game
from meicho.state import Phase

DECK = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                   "decklists", "SD001.json"), encoding="utf-8"))
CONFIG = GameConfig(chara_decks=[DECK["chara_deck"]] * 2,
                    action_decks=[DECK["action_deck"]] * 2)
POOL = DECK["action_deck"]


class FairGreedy(GreedyAgent):
    """先読み時にデッキ順序も決定化する公正版。"""

    def _sample_opponent(self, s, pi):
        t = super()._sample_opponent(s, pi)
        self.rng.shuffle(t.players[pi].action_deck)
        self.rng.shuffle(t.players[1 - pi].action_deck)
        return t

    def act(self, s, pi):
        acts = legal_actions(s, pi)
        if len(acts) > 1 and s.phase in self.phases \
                and s.phase not in (Phase.SETUP_CHARA, Phase.MULLIGAN) \
                and s.phase != Phase.CLASH_SUBMIT:
            # 単独決定フェイズ: 決定化した1つの局面上で全候補を比較する
            t = s.clone()
            self.rng.shuffle(t.players[pi].action_deck)
            self.rng.shuffle(t.players[1 - pi].action_deck)
            return max(acts, key=lambda a: evaluate(
                self._settle(apply(t, {pi: a}), pi), pi, self.w))
        return super().act(s, pi)


def series(make_a, make_b, n, label):
    wins = decided = 0
    for seed in range(n):
        flip = seed % 2
        ags = ([make_b(seed * 2), make_a(seed * 2 + 1)] if flip
               else [make_a(seed * 2), make_b(seed * 2 + 1)])
        r = play_game(CONFIG, ags, seed=seed)
        if r["aborted"] or r["draw"]:
            continue
        decided += 1
        if r["winner"] == flip:
            wins += 1
    p = wins / decided
    ci = 1.96 * math.sqrt(p * (1 - p) / decided)
    print(f"{label}: {p:.3f} ±{ci:.3f} (n={decided})")


if __name__ == "__main__":
    series(lambda sd: FairGreedy(sd, opp_decklist=POOL),
           lambda sd: HeuristicAgent(sd), 300, "公正版貪欲 vs H_default")
    series(lambda sd: GreedyAgent(sd, opp_decklist=POOL),
           lambda sd: HeuristicAgent(sd), 300, "元の貪欲   vs H_default")
