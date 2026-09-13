"""レビュー用: 覗き見監査（引継ぎ書 §7.4 への回答）。

既存テストは単一局面×5差し替えのみ。本監査は実対局のリプレイ中、
プレイヤー0の**すべての実決定ノード**（合法手2以上）で隠蔽情報
（相手の手札の中身・両者のデッキ順序）を差し替え、選択が不変かを検査する。

エージェントは状態（乱数列）を持つため、各差し替え試行の前に
乱数状態を復元して比較の同一条件を保つ。
"""
import sys, os, json, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.engine import GameConfig, apply, decision_players, initial_state, outcome, legal_actions
from meicho.heuristic import HeuristicAgent
from meicho.greedy import GreedyAgent
from meicho.state import Phase

DECK = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                   "decklists", "SD001.json"), encoding="utf-8"))
CONFIG = GameConfig(chara_decks=[DECK["chara_deck"]] * 2,
                    action_decks=[DECK["action_deck"]] * 2)
POOL = DECK["action_deck"]


def scramble(s, rng, opp_hand=True, own_deck=True, opp_deck=True):
    """プレイヤー0から見た隠蔽情報だけを差し替えた状態を返す。

    フラグで差し替え対象を絞り、違反の原因を切り分けられる。
    """
    t = s.clone()
    if opp_hand:
        t.players[1].hand = rng.sample(POOL, len(t.players[1].hand))
    if own_deck:
        rng.shuffle(t.players[0].action_deck)
    if opp_deck:
        rng.shuffle(t.players[1].action_deck)
    return t


def rng_states(agent):
    sts = [("rng", agent.rng.getstate())]
    if hasattr(agent, "fallback"):
        sts.append(("fallback", agent.fallback.rng.getstate()))
    return sts


def restore(agent, sts):
    for name, st in sts:
        (agent.rng if name == "rng" else agent.fallback.rng).setstate(st)


def audit(make_a0, n_games, variants, label, node_cap=10**9, **scr):
    checked = violations = 0
    vio_examples = []
    for seed in range(n_games):
        agents = [make_a0(seed * 2), HeuristicAgent(seed * 2 + 1)]
        s = initial_state(CONFIG, seed)
        srng = random.Random(seed + 999)
        while outcome(s) is None and s.turn_no <= 200:
            need = decision_players(s)
            actions = {}
            for pi in need:
                if pi == 0 and len(legal_actions(s, 0)) > 1 and checked < node_cap:
                    sts = rng_states(agents[0])
                    base = agents[0].act(s, 0)
                    for _ in range(variants):
                        restore(agents[0], sts)
                        alt = agents[0].act(scramble(s, srng, **scr), 0)
                        if alt != base:
                            violations += 1
                            if len(vio_examples) < 3:
                                vio_examples.append((seed, s.turn_no,
                                                     s.phase.value, base, alt))
                            break
                    restore(agents[0], sts)
                    checked += 1
                    actions[0] = agents[0].act(s, 0)
                else:
                    actions[pi] = agents[pi].act(s, pi)
            s = apply(s, actions)
    print(f"{label}: 決定ノード {checked} / 違反 {violations}")
    for v in vio_examples:
        print("   例:", v)


G = lambda sd: GreedyAgent(sd, opp_decklist=POOL)
audit(lambda sd: HeuristicAgent(sd), 40, 3, "ヒューリスティック（40局・全フェイズ）")
audit(G, 6, 2, "貪欲: 全差し替え             ", node_cap=400)
# 違反の原因の切り分け（結果 2026-08-23: 自分のデッキ順序が原因）
audit(G, 6, 2, "貪欲: 相手手札のみ           ", node_cap=400,
      own_deck=False, opp_deck=False)
audit(G, 6, 2, "貪欲: 自分のデッキ順序のみ   ", node_cap=400,
      opp_hand=False, opp_deck=False)
audit(G, 6, 2, "貪欲: 相手のデッキ順序のみ   ", node_cap=400,
      opp_hand=False, own_deck=False)
