"""s3_it1_rec（段階3 反復 1 の記録・教師 netfree_v・葉 V_0）の机上の読み。
決定ごとの候補の点数の差（決め手の大きさ）と、V_0 の部品 3 本の食い違い（V の揺れ）を並べる。"""
import sys, os, json, glob
import numpy as np
ENG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, ENG); sys.path.insert(0, os.path.join(ENG, 'experiments'))
os.chdir(ENG)
from diag_s3_desk import extract, manifests, block_table, tags, net_logit, sigmoid, PHASE_NAMES
from meicho.drl_data import read_records
from meicho.drlnet import Net
from meicho.heuristic import LEADER_COLOR

split = sys.argv[1] if len(sys.argv) > 1 else 'val'
chunks = None
if len(sys.argv) > 2:
    chunks = set(int(c) for c in sys.argv[2].split(','))
work = os.path.join(ENG, 'results', 'reading_20261020')
files = extract(split, work, chunks)
recs = read_records(files)
mans = manifests(split, chunks)
table = block_table(mans)
tg = tags(recs, table)
n = recs.n
print(f'{split}: decisions {n}')

# H のリーダー（dedicated 最多・同点は legal_actions の順）→ 対抗の担当色の有無
from meicho.engine import initial_state, decision_players, GameConfig
from meicho.heuristic import HeuristicAgent
leader_known = {}
def deck_file(name):
    return os.path.join(ENG, 'decklists', name + '.json')
for dk in sorted(set(tg['own']) | set(tg['opp'])):
    d = json.load(open(deck_file(dk), encoding='utf-8'))
    cfg = GameConfig(chara_decks=[d['chara_deck']] * 2, action_decks=[d['action_deck']] * 2)
    s = initial_state(cfg, 1)
    a = HeuristicAgent(0).act(s, decision_players(s)[0])
    leader_known[dk] = (a['leader'], LEADER_COLOR.get(a['leader']) is not None)
own_known = np.array([leader_known[d][1] for d in tg['own']])
opp_known = np.array([leader_known[d][1] for d in tg['opp']])
print('decks:', {k: v for k, v in leader_known.items()})

# 候補の点数
best = np.full(n, np.nan); second = np.full(n, np.nan); nfin = np.zeros(n, int)
chosen_is_max = np.zeros(n, bool); chosen_score = np.full(n, np.nan)
pass_chosen = np.zeros(n, bool)
for i in range(n):
    sc = recs.scores_of(i)
    f = np.isfinite(sc)
    nfin[i] = f.sum()
    if nfin[i] >= 1:
        s = np.sort(sc[f])[::-1]
        best[i] = s[0]
        second[i] = s[1] if len(s) >= 2 else np.nan
        ch = int(recs.chosen[i])
        chosen_score[i] = sc[ch]
        chosen_is_max[i] = np.isfinite(sc[ch]) and sc[ch] >= s[0] - 1e-9
gap = best - second

# V_0 の部品 3 本
nets = [Net.load(os.path.join(ENG, 'results', 'models', f's2v_id_s{k}.json')) for k in range(3)]
logits = np.stack([net_logit(nt, recs.obs) for nt in nets])  # [3, n]
p_parts = sigmoid(logits)
p_ens = sigmoid(logits.mean(0))
p_std = p_parts.std(0)      # 部品の食い違い（確率の目盛り）
z = recs.z.astype(np.float64)
okz = np.isfinite(z)

def q(x, qs=(0.1, 0.25, 0.5, 0.75, 0.9)):
    x = x[np.isfinite(x)]
    return [round(float(np.quantile(x, v)), 4) for v in qs] if len(x) else None

out = {}
phase = tg['phase']
for ph in ('action', 'clash', 'choice', 'rush', 'discard'):
    m = (phase == ph) & (nfin >= 2)
    if m.sum() == 0:
        continue
    row = {'n': int(m.sum()), 'n_acts_median': float(np.median(recs.n_acts[m])),
           'gap_q': q(gap[m]), 'p_std_q': q(p_std[m]),
           'frac_gap_lt_0.01': float(np.mean(gap[m] < 0.01)),
           'frac_gap_lt_0.02': float(np.mean(gap[m] < 0.02)),
           'frac_gap_lt_pstd': float(np.mean(gap[m] < p_std[m])),
           'chosen_is_max': float(chosen_is_max[m].mean()),
           'root_minus_z': float(np.nanmean((best - z)[m & okz])),
           'root_minus_v0': float(np.nanmean((best - p_ens)[m])),
           'v0_minus_z': float(np.nanmean((p_ens - z)[m & okz]))}
    # 自分のリーダーに担当色があるか（H の対抗の色が偏るか）で分ける
    for lbl, mm in (('own_leader_color', m & own_known), ('own_leader_none', m & ~own_known)):
        if mm.sum():
            row[lbl] = {'n': int(mm.sum()), 'gap_median': float(np.nanmedian(gap[mm])),
                        'frac_gap_lt_0.02': float(np.mean(gap[mm] < 0.02)),
                        'frac_gap_lt_pstd': float(np.mean(gap[mm] < p_std[mm])),
                        'root_minus_z': float(np.nanmean((best - z)[mm & okz]))}
    out[ph] = row
# 対抗: パスが選ばれた割合と、候補数
m = (phase == 'clash')
out['clash_extra'] = {'n': int(m.sum()), 'n_acts_q': q(recs.n_acts[m].astype(float), (0.1, 0.5, 0.9)),
                      'n_single_candidate(nfin<2)': int((m & (nfin < 2)).sum())}
# 探索していない決定（点数が全部 NaN）の割合
out['unexplored_frac_by_phase'] = {ph: float(np.mean(nfin[phase == ph] == 0)) for ph in set(phase)}
# V_0 の当てはまり（参考）
def logloss(p, z):
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return float(-np.mean(z * np.log(p) + (1 - z) * np.log(1 - p)))
out['v0_logloss'] = logloss(p_ens[okz], z[okz])
out['v0_part_std_overall_q'] = q(p_std)
json.dump({'leader_known': {k: [v[0], v[1]] for k, v in leader_known.items()}, 'stats': out},
          open(os.path.join(work, f'analysis_{split}.json'), 'w'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
