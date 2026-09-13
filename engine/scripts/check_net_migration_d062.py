# -*- coding: utf-8 -*-
"""D-062: ネット移行が「判断」を変えていないことの実測。

`scripts/migrate_nets_d062.py` は「使われていない列を切り落とすだけ」なので
実数の計算としては値が変わらない。ただし float32 の足し算の順序が変わるため
最後の桁に丸め誤差（相対 1e-6 前後）が出る。**その誤差で選ぶ手が変わらないか**を
ここで実際の対局で確かめる。

やり方（作法: 対照は同シード・差は局ごとに対にする）:
  同じシード帯で champion 同士を対局させ、1局ごとの digest（全手の系列のハッシュ）を
  取って、移行前後で突き合わせる。digest が1つでも違えば、どこかで手が変わっている。

使い方（2つのツリーで別々に走らせ、出力の JSON を突き合わせる）:
    python3 scripts/check_net_migration_d062.py --deck SD001 --n 30 --seed0 330000 --out before.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", "experiments"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=330000)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from meicho import GameConfig
    import champion
    from arena_rs import series_rs_digest

    path = os.path.join(_HERE, "..", "decklists", f"{args.deck}.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    pool = d["action_deck"]
    config = GameConfig(chara_decks=[list(d["chara_deck"])] * 2,
                        action_decks=[list(pool)] * 2)
    spec = champion.spec(args.deck, pool)
    out = series_rs_digest(spec, spec, args.n, config,
                           workers=args.workers, seed0=args.seed0)
    res = {
        "deck": args.deck, "n": args.n, "seed0": args.seed0,
        "champion": champion.describe(args.deck),
        "digests": [r[4] for r in out],
        "winners": [r[0] for r in out],
    }
    js = json.dumps(res, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(js)
    print(js)
    return 0


if __name__ == "__main__":
    sys.exit(main())
