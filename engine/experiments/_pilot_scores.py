"""段階 2 の設計判断のための下見（使い捨て）。

現 champion を教師にした記録を少量取り、記録された「探索が採点した各合法手の値」の
分布を調べる。`drl_train.py --lam` は値が [0,1] に入っていることを前提にしているので、
実際にどうなっているかを確かめる。
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                     # noqa: E402

import champion                                            # noqa: E402
from arena import load_deck, mirror_config                 # noqa: E402
from arena_rs import ensure_cards                          # noqa: E402
from meicho.drl_data import read_records                   # noqa: E402

DECK = sys.argv[1] if len(sys.argv) > 1 else "SD001"
SEED0 = int(sys.argv[2]) if len(sys.argv) > 2 else 299000
N = int(sys.argv[3]) if len(sys.argv) > 3 else 200
TAU = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0

ensure_cards()
deck = load_deck(DECK)
pool = deck["action_deck"]
cfg = mirror_config(deck)
cfg.validate()

spec = champion.spec(DECK, pool)
if TAU:
    spec = dict(spec, tau=TAU)
print("teacher:", champion.describe(DECK), "tau=", TAU)

out = "/tmp/pilot.bin"
t = time.time()
res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, spec, spec,
                              SEED0, N, out, 2, 200, True, True)
dt = time.time() - t
print(f"{N} 局 {dt:.1f}s = {N/dt:.2f} 局/秒 (2 workers)")

r = read_records(files)
print("決定数", r.n, " 1 局あたり", r.n / N)
sc = r.scores_flat
fin = np.isfinite(sc)
print(f"探索値: 有限 {fin.mean():.3f} / NaN {1-fin.mean():.3f}")
v = sc[fin]
print(f"  範囲 [{v.min():.3f}, {v.max():.3f}]  平均 {v.mean():.3f}  中央 {np.median(v):.3f}  標準偏差 {v.std():.3f}")
qs = [0.1, 1, 5, 25, 50, 75, 95, 99, 99.9]
print("  分位:", {q: round(float(np.percentile(v, q)), 3) for q in qs})
print(f"  [0,1] に入る割合 {(0.0 <= v).mean() * (v <= 1.0).mean():.3f} → 実際 {((v >= 0) & (v <= 1)).mean():.3f}")

# 選んだ手の値と、その決定の中での順位
chosen_v, spread, nb = [], [], []
for i in range(r.n):
    s = r.scores_of(i)
    f = np.isfinite(s)
    if f.sum() < 2:
        continue
    w = s[f]
    chosen_v.append(s[r.chosen[i]] if np.isfinite(s[r.chosen[i]]) else np.nan)
    spread.append(w.max() - w.min())
    nb.append(len(w))
chosen_v = np.asarray(chosen_v, float)
spread = np.asarray(spread, float)
print(f"探索した決定 {len(spread)} 件（全 {r.n} 件の {len(spread)/r.n:.3f}）")
print(f"  1 決定内の最大-最小: 中央 {np.median(spread):.3f} / 平均 {spread.mean():.3f} / 90% 点 {np.percentile(spread,90):.3f}")
print(f"  選んだ手の値が最大か: {np.mean([1.0])}")
ok = np.isfinite(chosen_v)
print(f"  選んだ手の値が有限: {ok.mean():.3f}")

# フェイズ別
from drl_train import PHASE_NAMES                          # noqa: E402
for k in range(8):
    m = r.phase == k
    if not m.any():
        continue
    # そのフェイズの決定のうち、探索値が有限なものの割合
    fr = []
    for i in np.nonzero(m)[0][:5000]:
        fr.append(np.isfinite(r.scores_of(i)).mean())
    print(f"  {PHASE_NAMES[k]:9s} 決定 {int(m.sum()):7d}  探索値あり {np.mean(fr):.3f}")

for f in files:
    os.remove(f)
