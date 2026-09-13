"""マスターの 2 局（2026-09-03・対 planner_vb3・2 連勝）の裏取り: 「本命の赤は対抗で出さず連撃まで温存する」
という打ち方を δ（発見ループの語彙 B・`reserve`／`forbid_in_clash`）で champion に重ね、champion 自身に当てる。

champion がこの δ 版に負け越すなら、マスターの勝ち方は 2 局の偶然ではなく**構造的な穴**である
（champion は「相手は対抗で一番強い札を出す」と想定して受けるため、安い札で対抗を取られて連撃で本命を叩き込まれる）。

使い方:
    python3 experiments/probe_human_recipe.py --n 600 --seed0 600000
帯は seed_bands.json に登録してから使う（D-028）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                    # noqa: E402
from arena_rs import PLANNER, ensure_cards, series_rs         # noqa: E402
from meicho.drlnet import resolve_model                       # noqa: E402
import champion as chmod                                      # noqa: E402

RECIPES = {
    "reserve_rekka": [{"kind": "reserve", "card": "燃える烈火"}],
    "forbid_rekka_in_clash": [{"kind": "forbid_in_clash", "card": "燃える烈火"}],
    "reserve_rekka_soumei": [{"kind": "reserve", "card": "燃える烈火"}, {"kind": "reserve", "card": "奏鳴"}],
    "reserve_big_reds": [{"kind": "reserve", "card": "燃える烈火"}, {"kind": "reserve", "card": "奏鳴"},
                         {"kind": "reserve", "card": "旋風"}],
}


def _resolve(kw: dict) -> dict:
    out = dict(kw)
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in out:
            out[key] = resolve_model(out[key])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", default=None)
    args = ap.parse_args(argv)
    ensure_cards()
    deck = load_deck(args.deck)
    config = mirror_config(deck)
    pool = deck["action_deck"]
    base = _resolve(chmod.CHAMPIONS[args.deck])
    champ = PLANNER(pool, **base)
    out = {"deck": args.deck, "n": args.n, "champion": chmod.CHAMPIONS[args.deck], "runs": []}
    seed = args.seed0
    for name, deltas in RECIPES.items():
        if args.only and name != args.only:
            continue
        chal = PLANNER(pool, **base, delta=deltas)
        t0 = time.time()
        r = series_rs(chal, champ, args.n, config, workers=args.workers, seed0=seed)
        dt = time.time() - t0
        row = {"name": name, "deltas": deltas, "seed0": seed, "n": args.n, "wins": r.wins,
               "decided": r.decided, "p": r.p, "ci": r.ci, "lo": r.p - r.ci, "hi": r.p + r.ci, "sec": dt}
        out["runs"].append(row)
        print(f"{name:24s} {r}  下端 {r.p - r.ci:.3f}  {dt:.0f}s  (seeds {seed}..{seed + args.n - 1})", flush=True)
        seed += args.n
        path = os.path.join(_HERE, "..", "results", "vb", "probe_human_recipe.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
