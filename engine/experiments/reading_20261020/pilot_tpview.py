"""下見（判定には使わない）: 葉の採点を「手番側の視点」で取る版（tpview）対 従来の netfree_v。
同じ決定化・同じ V_0（部品 s0）。局の組 (2k, 2k+1) で席を入れ替え、A 席（tpview）の得点を数える。"""
import sys, os, json, time, math, numpy as np
ENG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, ENG); os.chdir(ENG)
from meicho.engine import initial_state, apply, decision_players, observe, GameConfig
from meicho.state import Phase, DRAW
from meicho.planner import PlannerAgent
from meicho.greedy import load_net
from meicho.encode import encode

deck = sys.argv[1]; n = int(sys.argv[2]); seed0 = int(sys.argv[3]); out = sys.argv[4]
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
mode = sys.argv[5] if len(sys.argv) > 5 else 'tp'   # tp = 手番側の視点 / avg = 両視点の平均
d = json.load(open(f'decklists/{deck}.json', encoding='utf-8'))
cfg = GameConfig(chara_decks=[d['chara_deck']] * 2, action_decks=[d['action_deck']] * 2)
NETFREE = dict(extra_turns=1, choice_phases=True, solo_samples=4, known_hand=True, endgame_enum=64, draw_buckets=1)


class TPView(PlannerAgent):
    """葉が相手の手番なら、相手の視点で V を取り 1 − V を返す（学習した種類の局面で採点する）。"""
    def _eval(self, s, pi):
        if self.value_net is None or s.outcome is not None:
            return super()._eval(s, pi)
        net = load_net(self.value_net)
        if mode == 'tp':
            q = s.turn_player
            v = float(net.value_of(np.asarray(encode(observe(s, q), q, self.opp_decklist), np.float32)))
            return v if q == pi else 1.0 - v
        v_me = float(net.value_of(np.asarray(encode(observe(s, pi), pi, self.opp_decklist), np.float32)))
        v_op = float(net.value_of(np.asarray(encode(observe(s, 1 - pi), 1 - pi, self.opp_decklist), np.float32)))
        return 0.5 * (v_me + 1.0 - v_op)


res = []
t0 = time.time()
for k in range(n):
    seed = seed0 + k
    a_seat = k % 2            # 組 (2k, 2k+1) で席を入れ替え
    ags = {}
    ags[a_seat] = TPView(seed=seed * 7 + 1, opp_decklist=d['action_deck'], value_net='s2v_id_s0', **NETFREE)
    ags[1 - a_seat] = PlannerAgent(seed=seed * 7 + 2, opp_decklist=d['action_deck'], value_net='s2v_id_s0', **NETFREE)
    s = initial_state(cfg, seed); steps = 0
    while s.outcome is None and steps < 400:
        need = decision_players(s)
        if not need:
            break
        s = apply(s, {q: ags[q].act(s, q) for q in need}); steps += 1
    score = 0.5 if s.outcome is None or s.outcome == DRAW else (1.0 if s.outcome == a_seat else 0.0)
    res.append({'seed': seed, 'a_seat': a_seat, 'outcome': s.outcome, 'turns': s.turn_no, 'score_a': score})
    if k % 10 == 9:
        m = np.mean([r['score_a'] for r in res])
        print(f'{k + 1} games, A score {m:.3f}, {time.time() - t0:.0f}s', flush=True)
        json.dump(res, open(out, 'w'))
json.dump(res, open(out, 'w'))
sc = np.array([r['score_a'] for r in res])
m = sc.mean(); se = 1.96 * math.sqrt(m * (1 - m) / len(sc))
print(f'FINAL n={len(sc)} A={m:.3f} [{m - se:.3f}, {m + se:.3f}]')
