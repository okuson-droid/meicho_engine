"""同じシードで取った 2 本の差を、対にして測り直す（対照実験の作法・D-039）。

勝率を別々に出して区間を並べると、差の確かさを過小評価する（同じ初期局面・同じ山札順を
共有しているぶんの相関を捨てるため）。局ごとに対にして「勝敗が入れ替わった数」から
差の区間を出すと、はるかに細かく見える。
"""
from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import champion                                                       # noqa: E402
from arena import load_deck, mirror_config                            # noqa: E402
from arena_rs import GREEDY, HEURISTIC, PLANNER, ensure_cards, series_rs_detail   # noqa: E402

DECK = "SD001"
NET = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "results/models/drl_sd001_s2r1.json")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 1200
W = int(sys.argv[3]) if len(sys.argv) > 3 else 2

ensure_cards()
deck = load_deck(DECK)
cfg = mirror_config(deck)
pool = deck["action_deck"]
champ = champion.spec(DECK, pool)
new = PLANNER(pool, opp_policy_net=NET, opp_policy_root_only=True)


def paired(label, opp, seed0):
    a = series_rs_detail(new, opp, N, cfg, W, seed0)
    b = series_rs_detail(champ, opp, N, cfg, W, seed0)
    both = [(x[0], y[0]) for x, y in zip(a, b) if x[0] is not None and y[0] is not None]
    n = len(both)
    win_only_new = sum(1 for x, y in both if x and not y)
    win_only_old = sum(1 for x, y in both if y and not x)
    d = (win_only_new - win_only_old) / n
    # 差の分散（対応のある比率の差）
    var = (win_only_new + win_only_old - (win_only_new - win_only_old) ** 2 / n) / (n * n)
    ci = 1.96 * math.sqrt(max(var, 0.0))
    same = n - win_only_new - win_only_old
    print(f"{label:12s} n={n}  新だけ勝ち {win_only_new:4d} / 現だけ勝ち {win_only_old:4d} / 同じ {same:4d}"
          f"  →  差 {d:+.4f} ±{ci:.4f}  [{d-ci:+.4f}, {d+ci:+.4f}]  "
          f"{'差がある' if abs(d) > ci else '差があるとは言い切れない'}")


print(f"新: {os.path.basename(NET)} / 現champion: {champion.describe(DECK)}   n={N}")
paired("vs H", HEURISTIC(), 302600)
paired("vs 貪欲", GREEDY(pool), 303900)
