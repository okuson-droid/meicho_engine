"""λ（教師に探索値をどれだけ混ぜるか）の 1 回だけの比較（D-064・設計書 §5.3-2）。

## 何を決める道具か

V の学習目標は `(1 − λ)·z ＋ λ·p_search` である。
- `z` は**その局の実際の勝敗**（勝ち 1 / 負け 0）。確かだが、1 局の結果なので雑音が多い。
- `p_search` は**探索がその局面に付けた点数を勝率に直したもの**。滑らかだが、
  自分の予測を自分で教師にするので、間違いが積み上がりうる。

λ が 0 なら勝敗だけ、1 なら探索値だけ。既定は 0.7（探索値を主に、勝敗で接地する）。
**反復 1 で 1 回だけ 3 本比べて決め、以降の反復は固定する**（設計書 §5.3-2）。

## 比べ方（強さで比べる。学習の指標では比べない）

同じ記録から学習した 3 本を、**同じシード**で素の計画探索に当てて勝率を比べ、
あわせてカナリア（漂泊者 Lv2 の到達率）を見る。学習の指標（対数損失）が良い版が
強いとは限らない——C-1 と段階 1 で 2 回そうなった（予測は良いのに強くならない）ので、
ここでは強さで選ぶ。

**3 本の信頼区間が重なって区別できなければ、既定の 0.7 を使う**（設計書 §5.3-2）。

使い方:
    python3 experiments/pick_lambda_vb.py --deck SD001 --vb 1 \
        --nets results/models/drl_sd001_vb1_lam05.json,...lam07.json,...lam10.json \
        --labels 0.5,0.7,1.0 --n 600 --workers 2
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

import eval_vb                                                           # noqa: E402
import vb as vbmod                                                       # noqa: E402
from arena import load_deck, mirror_config                               # noqa: E402
from arena_rs import PLANNER, ensure_cards, series_rs                    # noqa: E402


def agent_with_net(deck: str, pool: list, k: int, net_path: str, loop: int = 1) -> dict:
    """反復 k の記録から学んだ V を積んだ版（＝反復 k+1 のエージェント）の spec。"""
    kw = vbmod.kwargs_for(deck, k + 1, loop)
    kw["value_net"] = os.path.abspath(net_path)
    rs.net_forget(kw["value_net"])
    from meicho.drlnet import resolve_model
    kw["opp_policy_net"] = resolve_model(kw["opp_policy_net"])
    # 代打ちの π 頭も差し替えた版を指す（輪 2 では葉と同じファイルを読むため・vb.py の pi_proxy）
    if kw.get("policy_scope") == "proxy":
        kw["policy_net"] = kw["value_net"]
    return PLANNER(pool, **kw)


def canary_with_net(deck: str, pool: list, k: int, net_path: str, seeds, loop: int = 1) -> dict:
    from measure_rush_lv2 import _trace
    from meicho.heuristic import HeuristicAgent
    from meicho.planner import PlannerAgent
    kw = vbmod.kwargs_for(deck, k + 1, loop)
    kw["value_net"] = os.path.abspath(net_path)
    if kw.get("policy_scope") == "proxy":
        kw["policy_net"] = kw["value_net"]
    from meicho.greedy import forget_net
    forget_net(kw["value_net"])
    return _trace(lambda s: PlannerAgent(s, opp_decklist=pool, **kw),
                  lambda s: HeuristicAgent(s), seeds)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--vb", type=int, required=True, help="記録を取った反復の番号 k")
    ap.add_argument("--loop", type=int, default=1,
                    help="輪の番号（既定 1 = D-064 の輪。2 = D-065 便 4 の輪）")
    ap.add_argument("--nets", required=True, help="比べるモデルのパス（カンマ区切り）")
    ap.add_argument("--labels", default=None, help="表示用のラベル（カンマ区切り。既定はファイル名）")
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--canary-n", type=int, default=200)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--skip-canary", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    nets = [s.strip() for s in args.nets.split(",") if s.strip()]
    labels = [s.strip() for s in args.labels.split(",")] if args.labels \
        else [os.path.basename(p) for p in nets]
    assert len(nets) == len(labels)

    ensure_cards()
    deck = load_deck(args.deck)
    pool = deck["action_deck"]
    config = mirror_config(deck)
    base = eval_vb.eval_band(args.vb)
    seed = base + eval_vb.OFFSETS["anchor_planner"]     # 錨と同じシード（帯を増やさない・§7.6）
    cs0 = base + eval_vb.OFFSETS["canary"]

    print(f"■ λ の比較（反復 {args.vb} の記録から学んだ V・{args.deck}）")
    print(f"  対 素の計画探索・{args.n} 局・**全部の版に同じシード** {seed}..{seed + args.n - 1}")
    print()
    rows = []
    for label, path in zip(labels, nets):
        a = agent_with_net(args.deck, pool, args.vb, path, args.loop)
        t0 = time.time()
        r = series_rs(a, PLANNER(pool), args.n, config, workers=args.workers, seed0=seed)
        dt = time.time() - t0
        row = {"label": label, "net": os.path.basename(path), "p": r.p, "ci": r.ci,
               "lo": r.p - r.ci, "hi": r.p + r.ci, "wins": r.wins, "decided": r.decided,
               "rate": args.n / dt if dt else None}
        rows.append(row)
        print(f"  λ={label:>4}  vs 素planner {r}  下端 {row['lo']:.3f} / 上端 {row['hi']:.3f}"
              f"  [{args.n / dt:.1f} 局/秒]", flush=True)

    if not args.skip_canary:
        print()
        print(f"■ カナリア（対 H・{args.canary_n} 局・シード {cs0}..{cs0 + args.canary_n - 1}）")
        cs = list(range(cs0, cs0 + args.canary_n))
        for row, path in zip(rows, nets):
            t = canary_with_net(args.deck, pool, args.vb, path, cs, args.loop)
            mt = "—" if t["mean_turn"] is None else f"{t['mean_turn']:.1f}"
            row["canary"] = t
            print(f"  λ={row['label']:>4}  到達 {t['reached']:3d}/{t['games']}"
                  f"／到達ターン 平均 {mt:>5s}／Lv2 が引かせた枚数 平均 "
                  f"{t['total_extra_draws_per_game']:.2f}", flush=True)

    best = max(rows, key=lambda r: r["p"])
    overlap = [r for r in rows if r is not best and r["hi"] >= best["lo"]]
    print()
    if overlap:
        print("→ 3 本の信頼区間が重なっており、強さでは区別できない。"
              "**既定の λ=0.7 を使う**（設計書 §5.3-2）")
    else:
        print(f"→ λ={best['label']} が明確に上（下端 {best['lo']:.3f} が他の上端を超える）")

    path = args.out or os.path.join(_HERE, "..", "results", "vb", f"lambda{args.vb}.json")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"deck": args.deck, "vb": args.vb, "loop": args.loop, "seed0": seed, "n": args.n,
                   "rows": rows}, f, ensure_ascii=False, indent=1)
    print(f"→ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
