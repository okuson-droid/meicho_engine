"""高速 clone のプロトタイプ測定。

dataclass の __init__（既定値ファクトリの評価を含む）を迂回し、
`__new__` ＋属性直接代入で複製する clone に差し替えて速度を測る。
fingerprint が bench_speed.py と一致することで挙動不変を確認する。

結果 (2026-08-23, 本環境): 252 → 266 局/秒（約 +6%）。fingerprint 一致。
採用する場合は state.py の clone を書き換え、フィールド追加時に
clone の更新を忘れないよう「フィールド数の一致」をテストで担保すること。
"""
import sys, os, json, time, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.state import GameState, PlayerState, CharaSlot, _jcopy


def fast_pclone(self):
    q = PlayerState.__new__(PlayerState)
    q.life = self.life
    q.action_deck = self.action_deck[:]
    q.hand = self.hand[:]
    q.concerto = self.concerto[:]
    q.trash = self.trash[:]
    q.action_area = self.action_area[:]
    q.chara_deck = self.chara_deck[:]
    q.slots = [CharaSlot(stack=s.stack[:]) for s in self.slots]
    q.mulligan_done = self.mulligan_done
    q.charas_revealed = self.charas_revealed
    return q


def fast_sclone(self):
    q = GameState.__new__(GameState)
    q.seed = self.seed; q.rng_calls = self.rng_calls
    q.phase = self.phase; q.turn_no = self.turn_no; q.turn_player = self.turn_player
    q.players = [p.clone() for p in self.players]
    q.used_charge = self.used_charge; q.used_switch = self.used_switch
    q.used_levelup = self.used_levelup
    q.pending_submission = self.pending_submission[:]
    q.clash_cards = self.clash_cards[:]
    q.clash_winner = self.clash_winner
    q.rush_allowance = self.rush_allowance
    q.last_clash_winner = self.last_clash_winner
    q.last_clash_cards = self.last_clash_cards[:]
    q.leader_switch_forbidden = self.leader_switch_forbidden[:]
    q.rush_forbidden = self.rush_forbidden[:]
    q.pending_rush_forbidden = self.pending_rush_forbidden[:]
    q.red_cost_up = self.red_cost_up[:]
    q.pending_red_cost_up = self.pending_red_cost_up[:]
    q.pending_choices = _jcopy(self.pending_choices)
    q.pending_skills = [r[:] for r in self.pending_skills]
    q.pending_effect = _jcopy(self.pending_effect)
    q.pending_ctx = dict(self.pending_ctx)
    q.pending_shared_ctx = self.pending_shared_ctx
    q.choice_resume = _jcopy(self.choice_resume)
    q.phase_before_choice = self.phase_before_choice
    q.peeked_opp_hand = [None if h is None else h[:] for h in self.peeked_opp_hand]
    q.outcome = self.outcome
    return q


PlayerState.clone = fast_pclone
GameState.clone = fast_sclone

from meicho.engine import GameConfig
from meicho.heuristic import HeuristicAgent
from meicho.runner import play_game

DECK = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                   "decklists", "SD001.json"), encoding="utf-8"))
CONFIG = GameConfig(chara_decks=[DECK["chara_deck"]] * 2,
                    action_decks=[DECK["action_deck"]] * 2)

sig = []
for seed in range(50):
    r = play_game(CONFIG, [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)],
                  seed=seed)
    sig.append((r["winner"], r["turns"], tuple(r["life"])))
print("fingerprint =", hashlib.sha256(repr(sig).encode()).hexdigest()[:16],
      "(bench_speed.py と一致すること)")

t0 = time.time()
for seed in range(300):
    play_game(CONFIG, [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)], seed=seed)
print(f"ヒューリスティック同型: {300/(time.time()-t0):.0f} 局/秒")
