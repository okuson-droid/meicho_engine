"""強さの候補の下見（コード変更なしで試せる spec だけ・2026-09-02）。

`STRENGTH_REVIEW_20260902.md` §3 の「零コード候補」を、現 champion（`planner_vb3`・
`experiments/champion.py` の定義）に**直接対決**で当てて測る。
シード帯は 430000..（`seed_bands.json` に登録済み）。**記録にも他の評価にも使っていない帯**。

候補は spec の差分だけで表す（`experiments/arena_rs.py` の PLANNER と同じ引数名）:
    proxy_pi      : policy_net=drl_sd001_vb3.json（探索の中の代打ちを H → 学習した方策 π に）
    wide          : plan_samples=8, samples=12（決定化の本数を倍に）
    tau           : tau=0.005（対抗・連撃・選択の根で僅差の手を混ぜる。対人用の確率化の**費用**を測る）

使い方:
    python3 experiments/probe_strength_candidates.py --cand proxy_pi --n 600 --seed0 430000
結果は results/vb/probe_<cand>.json。
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

CANDIDATES = {
    "proxy_pi": {"policy_net": "drl_sd001_vb3.json"},
    "proxy_pi_s1": {"policy_net": "drl_sd001_s1.json"},
    "wide": {"plan_samples": 8, "samples": 12},
    "wide_plan": {"plan_samples": 8},
    "wide_clash": {"samples": 12},
    "wide_clash24": {"samples": 24},
    "tau": {"tau": 0.005},
    "null": {},
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
    ap.add_argument("--cand", required=True, choices=sorted(CANDIDATES))
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    ensure_cards()
    deck = load_deck(args.deck)
    config = mirror_config(deck)
    pool = deck["action_deck"]
    base = _resolve(chmod.CHAMPIONS[args.deck])
    cand = _resolve({**chmod.CHAMPIONS[args.deck], **CANDIDATES[args.cand]})
    a = PLANNER(pool, **cand)
    b = PLANNER(pool, **base)
    print(f"候補 {args.cand}: {CANDIDATES[args.cand]}  vs 現champion  n={args.n} seed0={args.seed0}")
    t0 = time.time()
    r = series_rs(a, b, args.n, config, workers=args.workers, seed0=args.seed0)
    dt = time.time() - t0
    lo, hi = r.p - r.ci, r.p + r.ci
    print(f"  {r}  下端 {lo:.3f} / 上端 {hi:.3f}  {dt:.0f}s ({args.n / dt:.2f} 局/秒)")
    out = {"deck": args.deck, "cand": args.cand, "diff": CANDIDATES[args.cand], "n": args.n,
           "seed0": args.seed0, "wins": r.wins, "decided": r.decided, "p": r.p, "ci": r.ci,
           "lo": lo, "hi": hi, "sec": dt, "rate": args.n / dt,
           "champion": chmod.CHAMPIONS[args.deck]}
    path = args.out or os.path.join(_HERE, "..", "results", "vb", f"probe_{args.cand}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"  → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
