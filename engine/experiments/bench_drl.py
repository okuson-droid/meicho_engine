"""DRL の差し替え口ごとの速度計測（`DRL_NOTES.md` §2 の表を再現・D-057）。

**強さは読まない。** ここで出るのは「1 秒あたり何局回せるか」だけである。
勝率は `series_rs` で別の帯を使って測る（D-034）。

使い方:

    python3 experiments/bench_drl.py --net results/models/drl_sd001_s1.json --n 20 --seed0 249000

`--net` を省くと、実運用と同じ寸法（幹の隠れ層 256）の**乱数ネット**を使う。
重みの中身は速度に影響しないので、学習前でも所要時間の見積もりになる。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                          # noqa: E402

from arena import load_deck, mirror_config                      # noqa: E402
from arena_rs import PLANNER, ensure_cards, series_rs           # noqa: E402
from meicho.drlnet import random_net                            # noqa: E402


def rate(spec_a, spec_b, n, config, workers, seed0):
    t0 = time.time()
    r = series_rs(spec_a, spec_b, n, config, workers=workers, seed0=seed0)
    dt = time.time() - t0
    return n / dt, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--net", default=None, help="モデル JSON。省略時は乱数ネット（寸法だけ実運用と同じ）")
    ap.add_argument("--hidden", type=int, default=256, help="乱数ネットの隠れ層の幅")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=249000)
    args = ap.parse_args()

    ensure_cards()
    deck = load_deck(args.deck)
    config = mirror_config(deck)
    pool = deck["action_deck"]

    path = args.net
    if path is None:
        path = os.path.join("/tmp", f"bench_net_h{args.hidden}.json")
        random_net(seed=0, hidden=args.hidden).save(path)
    rs.net_forget(path)

    cases = [
        ("planner 同型（基準）", PLANNER(pool)),
        ("planner（葉 = V ネット）", PLANNER(pool, value_net=path)),
        ("planner（代打ち = π ネット）", PLANNER(pool, policy_net=path)),
        ("planner（相手モデル = π・葉の中も・D-057）", PLANNER(pool, opp_policy_net=path)),
        ("planner（相手モデル = π・根だけ・D-057）",
         PLANNER(pool, opp_policy_net=path, opp_policy_root_only=True)),
        ("planner（葉 = V ＋ 相手モデル = π・根だけ）",
         PLANNER(pool, value_net=path, opp_policy_net=path, opp_policy_root_only=True)),
        ("π 単体（探索なし）", {"kind": "policy", "net": path, "tau": 0.0}),
    ]
    print(f"ネット: {path}  n={args.n}  workers={args.workers}  seed0={args.seed0}")
    print("（相手は常に planner 同型。勝率は n が小さいので読まないこと）")
    for label, spec in cases:
        sp, r = rate(spec, PLANNER(pool), args.n, config, args.workers, args.seed0)
        print(f"{label:44s} {sp:7.2f} 局/秒   （参考 {r}）")


if __name__ == "__main__":
    main()
