"""記録の温度 τ の下見（D-064・設計書 §5.3-1）。**反復ごとにやり直すこと。**

## 何のための道具か

記録つき自己対戦では、AI にわざと「いちばん良いと思う手」以外も打たせる。そうしないと
**同じ局面ばかりが記録され、価値ネットに「行ったことのない場所の価値」を教えられない**からである。
その「わざと外す度合い」を決めるつまみが温度 τ である（τ=0 なら常に最良手）。

厄介なのは、**適切な τ が探索値の尺度によって変わる**ことである。反復 1 の探索値は手作り評価の
点数（無界・勝敗確定は ±10000）だが、反復 2 以降は葉が価値ネットになって値が [0,1] に収まる。
同じ τ でも「外れる割合」がまるで変わる。D-059 では尺度を見ずに τ を置いた結果、
実質的に温度 0（いつも最良手）になっていた。だから**反復ごとに下見をやり直す**。

## 出す数字

- **混合率** = 探索した決定のうち、**最良手以外を選んだ割合**。これが本命の指標である。
  設計書 §5.3-1 の目標は **10〜30%**。低すぎると多様性が出ず、高すぎると記録が
  「下手な打ち方」だらけになって教材の質が落ちる。
- 探索値の分布（範囲・分位）。較正（探索値 → 勝率の変換）が効くかの目安になる。

## 使い方

    python3 experiments/pilot_tau_vb.py --deck SD001 --vb 1 --seed0 340000 --n 200 \
        --taus 0,0.25,0.5,1,2,4 --workers 2

**同じシードを全部の τ に使う**（対にして比べるため。強さは読まないので評価帯は使わない）。
選んだ τ は記録の manifest に残る（`drl_record.py --tau`）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                     # noqa: E402

import vb as vbmod                                         # noqa: E402
from arena import load_deck, mirror_config                 # noqa: E402
from arena_rs import ensure_cards                          # noqa: E402
from drl_record import check_record_band                   # noqa: E402
from meicho.drl_data import read_records                   # noqa: E402


def mixing_rate(recs) -> dict:
    """探索した決定のうち「最良手以外を選んだ」割合と、探索値の分布。

    探索していない決定（探索値が全部 NaN）は数えない——そこは τ が働かないからである。
    """
    n_searched = n_mixed = 0
    for i in range(recs.n):
        sc = recs.scores_of(i)
        fin = np.isfinite(sc)
        if fin.sum() < 2:
            continue
        n_searched += 1
        c = int(recs.chosen[i])
        if c >= len(sc) or not fin[c]:
            n_mixed += 1                 # 探索の外の手を選んだ（起こらないはずだが数える）
            continue
        top = float(np.max(np.where(fin, sc, -np.inf)))
        # **値で比べる（添字で比べない）。** 記録の探索値は f32 に丸めてあるので、
        # f64 では僅差だった 2 手が記録の上では同点になりうる。同点の中でどれを選んだかは
        # 「最良手を外した」ではない。相対の許容差で判定する。
        if float(sc[c]) < top - 1e-6 * max(1.0, abs(top)):
            n_mixed += 1
    v = recs.scores_flat[np.isfinite(recs.scores_flat)]
    return {"decisions": int(recs.n), "searched": n_searched,
            "mixed": n_mixed, "rate": (n_mixed / n_searched) if n_searched else None,
            "v_min": float(v.min()) if len(v) else None,
            "v_max": float(v.max()) if len(v) else None,
            "v_p25": float(np.percentile(v, 25)) if len(v) else None,
            "v_p50": float(np.percentile(v, 50)) if len(v) else None,
            "v_p75": float(np.percentile(v, 75)) if len(v) else None,
            "v_in01": float(((v >= 0) & (v <= 1)).mean()) if len(v) else None}


def run_one(cfg, spec, seed0, n, workers, tau, tmpdir) -> dict:
    s = dict(spec)
    if tau:
        s["tau"] = tau
    out = os.path.join(tmpdir, f"pilot_tau{tau}.bin")
    for f in glob.glob(out + ".*"):
        os.remove(f)
    t0 = time.time()
    _, files = rs.series_record(cfg.chara_decks, cfg.action_decks, s, s,
                                seed0, n, out, workers, 200, True, True)
    dt = time.time() - t0
    m = mixing_rate(read_records(files))
    m["tau"] = tau
    m["rate_per_sec"] = n / dt if dt else None
    for f in files:
        os.remove(f)
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--vb", type=int, required=True, help="これから記録する反復の番号 k")
    ap.add_argument("--loop", type=int, default=1,
                    help="輪の番号（既定 1 = D-064 の輪。2 = D-065 便 4 の輪）")
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--taus", default="0,0.25,0.5,1,2,4")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--tmpdir", default="/tmp")
    ap.add_argument("--out", default=None, help="結果の JSON（既定 results/vb/pilot_tau<k>.json）")
    args = ap.parse_args(argv)

    check_record_band(args.seed0)          # 評価専用の帯で下見をしない
    ensure_cards()
    deck = load_deck(args.deck)
    pool = deck["action_deck"]
    cfg = mirror_config(deck)
    cfg.validate()
    # 下見も**記録と同じ探索器**で回す（τ の尺度は探索器で変わる）。
    spec = vbmod.spec(args.deck, pool, args.vb, loop=args.loop, recording=True)

    print(f"■ 温度 τ の下見（{vbmod.describe(args.deck, args.vb, args.loop)}）")
    print(f"  シード {args.seed0}..{args.seed0 + args.n - 1}（全部の τ で同じ）・各 {args.n} 局")
    print()
    print(f"{'τ':>6} {'混合率':>8} {'探索した決定':>12} {'探索値の範囲':>24} {'[0,1]内':>8} {'局/秒':>7}")
    rows = []
    for t in [float(x) for x in args.taus.split(",")]:
        m = run_one(cfg, spec, args.seed0, args.n, args.workers, t, args.tmpdir)
        rows.append(m)
        rng = f"[{m['v_min']:.2f}, {m['v_max']:.2f}]" if m["v_min"] is not None else "—"
        rate = f"{m['rate']:.3f}" if m["rate"] is not None else "—"
        print(f"{t:>6} {rate:>8} {m['searched']:>12} {rng:>24} "
              f"{m['v_in01']:>8.3f} {m['rate_per_sec']:>7.1f}", flush=True)

    ok = [r for r in rows if r["rate"] is not None and 0.10 <= r["rate"] <= 0.30]
    print()
    if ok:
        # 目標帯（10〜30%）の中で、まん中（20%）にいちばん近いものを推す
        pick = min(ok, key=lambda r: abs(r["rate"] - 0.20))
        print(f"→ 推し: τ = {pick['tau']}（混合率 {pick['rate']:.3f}）。"
              f"目標は 10〜30%（設計書 §5.3-1）")
    else:
        print("→ 目標の 10〜30% に入る τ が無い。--taus の範囲を広げて測り直すこと。"
              "**推測で τ を置いてはならない**（D-059 の失敗）")

    path = args.out or os.path.join(_HERE, "..", "results", "vb", (f"pilot_tau{args.vb}.json" if args.loop == 1
                                     else f"pilot_tau_l{args.loop}_{args.vb}.json"))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"deck": args.deck, "vb": args.vb, "loop": args.loop,
                   "seed0": args.seed0, "n": args.n,
                   "agent": vbmod.describe(args.deck, args.vb, args.loop), "rows": rows}, f,
                  ensure_ascii=False, indent=1)
    print(f"→ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
