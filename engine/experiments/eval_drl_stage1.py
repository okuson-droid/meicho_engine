"""DRL 段階 1 の検証 3 本（`HANDOFF_20260826_DRL.md` §2-3・D-057）。

学習した π（方策）と V（価値）が、実際の対局で何をもたらすかを測る。
**測るのは勝率であって、当てる精度ではない**（D-038）。

3 本の中身:

1. **π 単体** — 探索をまったくせず、ネットが出した点数がいちばん高い手をそのまま打つ。
   相手は H（ヒューリスティック）／貪欲／planner の 3 種。
   これは「教師（planner）の手を、探索なしでどこまで真似られたか」を対局で見る試験である。
2. **planner の葉 = V** — planner が「この先どうなりそうか」を採点する部分を、
   従来の手作りの評価関数から学習した V に差し替えたもの。相手は既定の planner。
3. **planner の相手モデル = π** — planner が「相手は対抗で何を出してくるか」を想像する部分を、
   従来の色履歴モデルから学習した π に差し替えたもの。相手は既定の planner。

判定は D-034 の門番に従う: **95% 信頼区間の下端が 0.5 を超えないかぎり champion 候補にしない。**
信頼区間とは「同じ条件で測り直したとき、だいたいこの範囲に収まる」という幅のことで、
幅が 0 をまたぐ（＝下端が 0.5 以下）なら「強いとは言い切れない」と読む。

使い方:
    python3 experiments/eval_drl_stage1.py --net results/models/drl_sd001_s1.json \
        --n 1200 --workers 2 --out results/drl/stage1_eval.json
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

import meicho_rs as rs                                                    # noqa: E402

from arena import load_deck, mirror_config                                # noqa: E402
from arena_rs import GREEDY, HEURISTIC, PLANNER, ensure_cards, series_rs  # noqa: E402


def POLICY(path: str, tau: float = 0.0) -> dict:
    return {"kind": "policy", "net": path, "tau": tau}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--net", required=True)
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=240700)
    ap.add_argument("--gap", type=int, default=1300, help="1 本ごとに進めるシードの幅（重ならないように）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=None, help="この語を含む名前の本だけ回す")
    args = ap.parse_args()

    ensure_cards()
    deck = load_deck(args.deck)
    config = mirror_config(deck)
    pool = deck["action_deck"]
    path = os.path.abspath(args.net)
    rs.net_forget(path)

    net = args.net                       # 記録には相対パスで残す（C-1 の教訓）
    runs = [
        ("1a. π 単体 vs H",                    POLICY(path),                       HEURISTIC()),
        ("1b. π 単体 vs 貪欲",                  POLICY(path),                       GREEDY(pool)),
        ("1c. π 単体 vs planner",              POLICY(path),                       PLANNER(pool)),
        ("2.  planner（葉 = V） vs planner",    PLANNER(pool, value_net=path),      PLANNER(pool)),
        ("3a. planner（相手 = π・根だけ） vs planner",
         PLANNER(pool, opp_policy_net=path, opp_policy_root_only=True),            PLANNER(pool)),
        ("3b. planner（相手 = π・葉の中も） vs planner",
         PLANNER(pool, opp_policy_net=path),                                       PLANNER(pool)),
    ]

    out = {"net": net, "deck": args.deck, "n": args.n, "seed0": args.seed0, "runs": []}
    seed = args.seed0
    for name, a, b in runs:
        if args.only and args.only not in name:
            seed += args.gap
            continue
        t0 = time.time()
        r = series_rs(a, b, args.n, config, workers=args.workers, seed0=seed)
        dt = time.time() - t0
        lo, hi = r.p - r.ci, r.p + r.ci
        verdict = "門番を越えた" if lo > 0.5 else "越えない"
        print(f"{name:44s} {r}  下端 {lo:.3f} / 上端 {hi:.3f}  → {verdict}   "
              f"[{seed}..{seed + args.n - 1}, {args.n / dt:.1f} 局/秒]", flush=True)
        out["runs"].append({"name": name, "seed0": seed, "wins": r.wins, "decided": r.decided,
                            "games": r.games, "p": r.p, "ci": r.ci, "lo": lo, "hi": hi,
                            "passes_gate": bool(lo > 0.5), "rate": args.n / dt})
        seed += args.gap

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"→ {args.out}")


if __name__ == "__main__":
    main()
