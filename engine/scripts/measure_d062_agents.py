# -*- coding: utf-8 -*-
"""D-062: 秧秧Lv2の訂正が「AI 同士の力関係」を動かすかの測定。

`measure_d062.py` はランダム行動でゲームそのものを測る。こちらは**強さの差がある
2者**を当てて、札の性質が変わったことで力関係が動くかを見る。

対戦は SD001 のミラー（両者とも同じデッキ）。したがって秧秧Lv2 は両者が使える。
それでも力関係が動きうるのは、**この札をうまく使えるかどうかが腕の差になる**ためである。

組み合わせ:
  - champion（計画探索＋相手モデル=π）vs H（ヒューリスティック）
  - champion vs 貪欲

作法（`measurement_discipline`）: 訂正の前後で同じシード帯・同じ相手を使い、
勝率には対局数と 95% 信頼区間を併記する。座席は 1 局ごとに入れ替わる
（`rust/src/lib.rs::run_series` がシードの偶奇で入れ替える）ので先攻の有利は相殺される。

使い方（2つの木で別々に走らせ、出力の JSON を突き合わせる）:
    python3 scripts/measure_d062_agents.py --n 600 --seed0 330100 --out before.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "experiments"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed0", type=int, default=330100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from meicho import GameConfig
    import champion
    from arena_rs import series_rs_detail

    with open(os.path.join(HERE, "..", "decklists", f"{args.deck}.json"), encoding="utf-8") as f:
        d = json.load(f)
    pool = d["action_deck"]
    config = GameConfig(chara_decks=[list(d["chara_deck"])] * 2,
                        action_decks=[list(pool)] * 2)
    champ = champion.spec(args.deck, pool)
    opponents = {
        "H": {"kind": "heuristic"},
        "greedy": {"kind": "greedy", "pool": pool},
    }

    res = {"deck": args.deck, "n": args.n, "seed0": args.seed0,
           "champion": champion.describe(args.deck), "matchups": {}}
    off = 0
    for name, spec_b in opponents.items():
        out = series_rs_detail(champ, spec_b, args.n, config,
                               workers=args.workers, seed0=args.seed0 + off)
        off += args.n
        decided = [r[0] for r in out if r[0] is not None]
        n = len(decided)
        wins = sum(1 for w in decided if w)
        p = wins / n if n else float("nan")
        ci = 1.96 * math.sqrt(p * (1 - p) / n) if n else float("nan")
        res["matchups"][name] = {
            "seed0": args.seed0 + off - args.n, "games": args.n, "decided": n,
            "wins": wins, "win_rate": p, "ci95": ci,
            "per_game": [r[0] for r in out],
            "turns": [r[1] for r in out],
        }
        print(f"  champion vs {name}: 勝率 {p:.3f} ±{ci:.3f} (n={n}, 引き分け・打ち切り {args.n - n} 局を除く)")

    js = json.dumps(res, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(js)
    return 0


if __name__ == "__main__":
    sys.exit(main())
