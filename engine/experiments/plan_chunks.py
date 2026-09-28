"""組み合わせ表を、1 回の実行が 10 分に収まる「塊」に割る（段階3・D-141・D-142 追記 1 の 4）。

    python3 experiments/plan_chunks.py plan --schedule results/drl/s3_it1_train_schedule.json \
        --out results/drl/s3_it1_rec/train_chunks.json --budget-sec 420
    python3 experiments/plan_chunks.py emit --schedule results/drl/s3_it1_train_schedule.json \
        --chunks results/drl/s3_it1_rec/train_chunks.json --k 0 --out /tmp/train.c000.schedule.json
    python3 experiments/record_mix.py --schedule /tmp/train.c000.schedule.json --out <置き場>/train.c000 --workers 4

`record_mix.py` はブロックを丸ごと回し、途中から再開できない。`make_s2_schedule.py --parts` はブロック単位で
分けるので、局数の多いブロック（ミラー 126 局など）は 1 つで 10 分を超える。そこでブロックを**シードの連続した
小ブロック**に割り、見込み秒数が予算に収まるように詰めて塊にする。局はシードだけで決まるので、割っても記録は
同じである（D-141 §3・Rust `run_series` は局ごとに席のエージェントを作り直す）。

- 見込み秒数は局の種類ごとの定数（`COST`・D-140 の実測・workers 4）。塊の実測はこれより短いことが多い
  （学習の表は 1 局 4.2 秒だった・D-141 §2）。予算は「10 分に余裕を持って収まる」目安であって、判定には使わない
- 小ブロックの局数は偶数（A/B が両方のデッキを半分ずつ持つ・`record_mix` の席の約束）
- 小ブロックは親ブロックの欄をそのまま持ち、`seed0`・`n` を差し替え、`parent`（親ブロックの番号）を足す
- `emit` が作る塊の組み合わせ表は、名前に `.c<3 桁>` を付け、`chunk`（番号と元の表）を持つ。D-141 の記録の
  manifest に入っている組み合わせ表と同じ形（検査 `tests/test_plan_chunks.py`）
"""
from __future__ import annotations

import argparse
import json
import sys

COST = {"mirror": 8.8, "cross": 15.5, "anchor": 9.9}   # D-140 の実測（秒/局・workers 4）


def plan(sch: dict, budget: float, src_path: str | None = None) -> dict:
    """ブロックをシードの連続した小ブロックに割り、見込み秒数が `budget` 以下の塊に詰める。"""
    chunks, cur, acc = [], [], 0.0
    for i, b in enumerate(sch["blocks"]):
        c = COST[b["kind"]]
        s, left = b["seed0"], b["n"]
        while left > 0:
            room = int((budget - acc) / c) // 2 * 2
            if room < 2:
                if not cur:
                    raise SystemExit(f"予算 {budget} 秒では {b['kind']} の 2 局（{2 * c} 秒）も入らない")
                chunks.append(cur)
                cur, acc = [], 0.0
                continue
            k = min(left, room)
            cur.append(dict(b, seed0=s, n=k, parent=i))
            acc += k * c
            s += k
            left -= k
    if cur:
        chunks.append(cur)
    return {"source": src_path, "budget_sec": budget, "cost_per_game": COST, "chunks": chunks}


def chunk_schedule(src: dict, chunks: list, k: int, src_path: str) -> dict:
    """塊 k の組み合わせ表（`record_mix.py --schedule` にそのまま渡せる）。"""
    ch = chunks[k]
    return {"name": f"{src['name']}.c{k:03d}", "teacher": src["teacher"], "generator": src["generator"],
            "n_total_actual": src["n_total_actual"], "chunk": {"index": k, "source": src_path},
            "decks": {d: src["decks"][d] for d in sorted({v for b in ch for v in (b["deck_a"], b["deck_b"])})},
            "blocks": ch}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--schedule", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--budget-sec", type=float, default=420.0)
    e = sub.add_parser("emit")
    e.add_argument("--schedule", required=True)
    e.add_argument("--chunks", required=True)
    e.add_argument("--k", type=int, required=True)
    e.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.schedule, encoding="utf-8") as f:
        src = json.load(f)
    if args.cmd == "plan":
        out = plan(src, args.budget_sec, args.schedule)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(len(out["chunks"]), "塊・", sum(b["n"] for c in out["chunks"] for b in c), "局")
        return out
    with open(args.chunks, encoding="utf-8") as f:
        chunks = json.load(f)["chunks"]
    out = chunk_schedule(src, chunks, args.k, args.schedule)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
