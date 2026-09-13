"""M6 の D1 — 学習の輪の反復に**循環**があるか（文献計画 便 M）。

## 何を見るか

価値の反復ブートストラップは V_1 → V_2 → V_3 → V_4' と世代を重ねている。
**k が k−1 に勝ち越している**ことは分かっている（V_4' 対 V_3 = 0.598・V_3 対 V_2 = 0.547）。
問題は「**k−2 が k に勝てるか**」である。勝てるなら三すくみ（循環）で、
「新しい世代が古い世代に負ける」場所があることになる。

循環があると、反復は「まっすぐ強くなる」のではなく「回っている」。
その場合、便 E の反復 7' には**磁石つき正則化**（新しい V を古い V から離れすぎないように
引き止める項）を入れて回転を止める必要がある（第 2 集 §5.9.2 の 6）。

## 規則（§0.3 (vi)。**回す前に決めてある**）

挑戦者＝**古い V**（k−2）、基準＝新しい V（k）。p は**挑戦者から見た**勝率。

- 95% 区間が 0.5 を**含むか上回る**（＝上端 ≥ 0.5）→ **循環あり**
- 上端が 0.5 を**下回る** → 循環なし

**2 世代のうち 1 つでも循環ありなら「循環あり」**として便 E 7' に磁石を入れる。

## 使い方

    # 対局は gate_sprt.py --mode fixed で回す（この道具は結果 JSON を読むだけ）
    python3 experiments/d1_cycle.py results/vb/d1_v2_vs_v4.json results/vb/d1_v1_vs_v3.json \
        --out results/vb/d1_cycle_verdict.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)


def cycle_verdict(wins: float, n: int) -> dict:
    """(挑戦者＝古い V の勝ち数, 決着局数) → 循環の有無。**純関数**（T-M-9 が固定する）。

    区間は ±1.96√(p(1−p)/n)（このプロジェクトの標準・作業規約 6）。
    """
    if not n:
        return {"n": 0, "p": None, "ci": None, "lo": None, "hi": None,
                "cycle": None, "reason": "決着局が 0"}
    p = wins / n
    ci = 1.96 * math.sqrt(p * (1 - p) / n)
    lo, hi = p - ci, p + ci
    cycle = hi >= 0.5
    return {"n": n, "wins": wins, "p": p, "ci": ci, "lo": lo, "hi": hi,
            "cycle": bool(cycle),
            "reason": ("95% 区間の上端が 0.5 以上（古い V が勝てる可能性が残る）"
                       if cycle else "95% 区間の上端が 0.5 未満（古い V は勝てない）")}


def read_run(path: str) -> dict:
    d = json.load(open(path, encoding="utf-8"))
    w = d.get("winrate") or {}
    v = cycle_verdict(float(w.get("wins", 0)), int(w.get("decided", 0)))
    return {"file": os.path.basename(path),
            "challenger_diff": d.get("challenger_diff"),
            "base_diff": d.get("base_diff"),
            "seed0": d.get("seed0"), "games": d.get("games"),
            "mode": d.get("mode"), "sec": d.get("sec"), "rate": d.get("rate"),
            "wilson": d.get("wilson"), **v}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="gate_sprt.py --mode fixed の結果 JSON")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    rows = [read_run(p) for p in args.runs]
    any_cycle = any(r["cycle"] for r in rows if r["cycle"] is not None)
    out = {"tool": "d1_cycle.py", "M": "M6 D1",
           "rule": ("挑戦者＝古い V（k−2）。95% 区間の上端 ≥ 0.5 なら循環あり。"
                    "2 世代のうち 1 つでも循環ありなら「循環あり」（§0.3 (vi)）"),
           "runs": rows,
           "cycle": bool(any_cycle),
           "magnet_needed": bool(any_cycle),
           "answer": ("循環あり → 便 E 反復 7' に磁石つき正則化を入れる"
                      if any_cycle else
                      "循環なし → 便 E 反復 7' に磁石は要らない")}
    print("■ M6 D1 反復の循環")
    print()
    for r in rows:
        print(f"  {r['file']}: 古い V から見た勝率 {r['p']:.3f} ±{r['ci']:.3f}"
              f"（n={r['n']}）／95% 区間 [{r['lo']:.3f}, {r['hi']:.3f}]"
              f" → {'**循環あり**' if r['cycle'] else '循環なし'}")
    print()
    print(f"  → **{out['answer']}**")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
