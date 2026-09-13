"""「自分の方策としての π」が反復で伸びたかを、相手モデルの用途と切り離して測る（D-060 の材料）。

## 何を知りたいか

段階 2 反復 1（D-059）では、学習した π を **相手モデル**（＝計画探索の中で「相手は対抗で何を出すか」を
埋める部品）として使い、現 champion 専用に尖ったという結果になった。

だがそれは **π の使い道の話**であって、**π そのものが強くなったかどうか**は別の問いである。
AlphaZero 型の反復（自分の方策を反復して強くする）に見込みがあるかを判断するには、
π を**探索なしの単体のプレイヤー**として走らせて、新旧を直接比べればよい。

- **π₀ 単体 vs π₁ 単体** — 方策そのものが強くなったか。
- **対 H / 対 貪欲**（新旧を**同じシード**で） — 伸びが相手によらないか、それとも
  相手モデルのときと同じように「強い相手に特化」しているか。

判定は勝率だけで行う（D-038）。± は 95% 信頼区間（同じ条件で測り直したら収まる幅）。

使い方:
    python3 experiments/measure_policy_iteration.py --n 1200 --workers 2 --seed0 320000 \
        --out results/drl/policy_iteration.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                                    # noqa: E402

import champion                                                          # noqa: E402
from arena import load_deck, mirror_config                               # noqa: E402
from arena_rs import (GREEDY, HEURISTIC, PLANNER, ensure_cards,           # noqa: E402
                      series_rs, series_rs_detail)

OLD = "drl_sd001_s1.json"     # 段階 1 の π（現 champion が相手モデルとして積んでいるもの）
NEW = "drl_sd001_s2r1.json"   # 段階 2 反復 1 の π


def POLICY(path: str, tau: float = 0.0) -> dict:
    """探索を一切しない、ネットの点数だけで打つプレイヤー。"""
    return {"kind": "policy", "net": path, "tau": tau}


def paired(a_spec, b_spec, opp, n, cfg, workers, seed0, label):
    """同じシードで 2 本取り、局ごとに対にして差を出す（D-039 の作法）。"""
    a = series_rs_detail(a_spec, opp, n, cfg, workers, seed0)
    b = series_rs_detail(b_spec, opp, n, cfg, workers, seed0)
    both = [(x[0], y[0]) for x, y in zip(a, b) if x[0] is not None and y[0] is not None]
    m = len(both)
    only_a = sum(1 for x, y in both if x and not y)
    only_b = sum(1 for x, y in both if y and not x)
    pa = sum(1 for x, _ in both if x) / m
    pb = sum(1 for _, y in both if y) / m
    d = (only_a - only_b) / m
    var = (only_a + only_b - (only_a - only_b) ** 2 / m) / (m * m)
    ci = 1.96 * math.sqrt(max(var, 0.0))
    print(f"  {label:22s} 新 {pa:.3f} / 旧 {pb:.3f}   差 {d:+.4f} ±{ci:.4f}"
          f"  [{d-ci:+.4f}, {d+ci:+.4f}]  {'差がある' if abs(d) > ci else '言い切れない'}"
          f"   [{seed0}..{seed0+n-1}]", flush=True)
    return {"label": label, "seed0": seed0, "n": m, "p_new": pa, "p_old": pb,
            "diff": d, "ci": ci, "significant": bool(abs(d) > ci)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=320000)
    ap.add_argument("--gap", type=int, default=1300)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ensure_cards()
    deck = load_deck(args.deck)
    cfg = mirror_config(deck)
    pool = deck["action_deck"]
    from meicho.drlnet import resolve_model
    old, new = resolve_model(OLD), resolve_model(NEW)
    for p in (old, new):
        rs.net_forget(p)

    out = {"deck": args.deck, "n": args.n, "old": OLD, "new": NEW, "direct": None, "paired": [], "vs_champion": None}
    s = args.seed0

    print("■ 方策そのものの直接対決（どちらも探索なし・ネットの点数だけで打つ）")
    t0 = time.time()
    r = series_rs(POLICY(new), POLICY(old), args.n, cfg, workers=args.workers, seed0=s)
    lo = r.p - r.ci
    print(f"  π₁ 単体 vs π₀ 単体   {r}  下端 {lo:.3f} / 上端 {r.p + r.ci:.3f}"
          f"   [{s}..{s+args.n-1}, {args.n/(time.time()-t0):.0f} 局/秒]")
    out["direct"] = {"seed0": s, "p": r.p, "ci": r.ci, "lo": lo, "wins": r.wins, "decided": r.decided}
    s += args.gap

    print()
    print("■ 相手を変えたとき（新旧を同じシードで取り、局ごとに対にした差）")
    for label, opp in (("単体 vs H", HEURISTIC()),
                       ("単体 vs 貪欲", GREEDY(pool)),
                       ("単体 vs 計画探索", PLANNER(pool))):
        out["paired"].append(paired(POLICY(new), POLICY(old), opp, args.n, cfg, args.workers, s, label))
        s += args.gap

    print()
    print("■ 参考: 単体で現 champion に当てると（探索のある相手との差）")
    for name, net in (("π₁ 単体", new), ("π₀ 単体", old)):
        r = series_rs(POLICY(net), champion.spec(args.deck, pool), args.n, cfg, workers=args.workers, seed0=s)
        print(f"  {name} vs champion   {r}   [{s}..{s+args.n-1}]")
        out.setdefault("vs_champion_runs", []).append({"name": name, "seed0": s, "p": r.p, "ci": r.ci})
        s += args.gap

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
