"""自己対戦（netfree・葉 V_0 の部品 1 本）の局面を集め、V を「ターンプレイヤーの視点」と「相手の視点」の両方で当て、
z との当たり方と 2 視点の整合（V_me + V_opp ≈ 1 か）を V_0・V_1 で比べる。"""
import sys, os, json, time, numpy as np
from collections import defaultdict
ENG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, ENG); os.chdir(ENG)
from meicho.engine import initial_state, apply, decision_players, observe, GameConfig
from meicho.state import Phase
from meicho.planner import PlannerAgent
from meicho.greedy import load_net
from meicho.encode import encode

deck = sys.argv[1] if len(sys.argv) > 1 else 'env/ENV_SANGE_RM_TSUBAKI'
ngames = int(sys.argv[2]) if len(sys.argv) > 2 else 40
seed0 = int(sys.argv[3]) if len(sys.argv) > 3 else 9000
d = json.load(open(f'decklists/{deck}.json', encoding='utf-8'))
cfg = GameConfig(chara_decks=[d['chara_deck']] * 2, action_decks=[d['action_deck']] * 2)
NETFREE = dict(extra_turns=1, choice_phases=True, solo_samples=4, known_hand=True, endgame_enum=64, draw_buckets=1)
NETS = {'V0': [load_net(f's2v_id_s{k}') for k in range(3)], 'V1': [load_net(f's3v1_id_s{k}') for k in range(3)]}

def ens(nets, x):
    ls = []
    for n in nets:
        p = float(n.value_of(x)); p = min(max(p, 1e-6), 1 - 1e-6); ls.append(np.log(p / (1 - p)))
    return 1 / (1 + np.exp(-np.mean(ls)))

os.makedirs(os.path.join(ENG, 'results', 'reading_20261020'), exist_ok=True)
rows = []   # (phase, kind, V0_me, V0_opp, V1_me, V1_opp, z_turnplayer, turn)
t0 = time.time()
for g in range(ngames):
    ag = [PlannerAgent(seed=seed0 * 10 + g * 2 + k, opp_decklist=d['action_deck'], value_net='s2v_id_s0', **NETFREE) for k in (0, 1)]
    s = initial_state(cfg, seed0 + g); steps = 0; traj = []
    while s.outcome is None and steps < 400:
        need = decision_players(s)
        if not need:
            break
        if s.phase in (Phase.ACTION, Phase.CLASH_SUBMIT, Phase.RUSH, Phase.CHOICE):
            tp = s.turn_player
            xs = [np.asarray(encode(observe(s, q), q, d['action_deck']), np.float32) for q in (tp, 1 - tp)]
            traj.append((s.phase.name, tp, [ens(NETS[k], xs[0]) for k in ('V0', 'V1')], [ens(NETS[k], xs[1]) for k in ('V0', 'V1')], s.turn_no))
        s = apply(s, {q: ag[q].act(s, q) for q in need}); steps += 1
    for ph, tp, vme, vop, tn in traj:
        z = 0.5 if s.outcome is None or s.outcome == -1 else (1.0 if s.outcome == tp else 0.0)
        rows.append((ph, vme[0], vop[0], vme[1], vop[1], z, tn, g))
    if g % 10 == 9:
        print('game', g, f'{time.time() - t0:.0f}s', flush=True)

def ll(p, z):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(z * np.log(p) + (1 - z) * np.log(1 - p)))
out = {}
for ph in ('ACTION', 'CLASH_SUBMIT', 'RUSH', 'CHOICE'):
    a = np.array([r[1:7] for r in rows if r[0] == ph], float)
    if len(a) == 0:
        continue
    z = a[:, 4]
    res = {'n': len(a), 'z_turnplayer_mean': float(z.mean()), 'base_logloss': ll(np.full(len(z), z.mean()), z)}
    for k, (i_me, i_op) in (('V0', (0, 1)), ('V1', (2, 3))):
        vme, vop = a[:, i_me], a[:, i_op]
        res[k] = {'mean_me': float(vme.mean()), 'mean_opp': float(vop.mean()), 'sum_mean': float((vme + vop).mean()),
                  'sum_std': float((vme + vop).std()),
                  'logloss_me_view': ll(vme, z), 'logloss_opp_view(1-V)': ll(1 - vop, z),
                  'logloss_avg_views': ll((vme + 1 - vop) / 2, z),
                  'corr_me_vs_1-opp': float(np.corrcoef(vme, 1 - vop)[0, 1])}
    out[ph] = res
print(json.dumps(out, indent=1))
json.dump({'deck': deck, 'ngames': ngames, 'rows': rows, 'summary': out},
          open(os.path.join(ENG, 'results', 'reading_20261020', f'twoseat_{deck.split("/")[-1]}.json'), 'w'))
