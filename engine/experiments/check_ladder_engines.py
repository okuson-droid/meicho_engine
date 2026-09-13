"""ラダーを Rust 版で回してよいかを**実際に確かめる**（D-065 便 4・マスター裁定 2026-09-06）。

## この道具は何のためにあるか

ラダー（`experiments/ladder.py`）は Python 版のエージェントで回っていた。Rust 移植（D-049）より
前に作られたからである。Rust 版で回せば重い組で約 4 倍速いが、それが許されるのは
**両者が一手も違わないから**である。

一手一致は `tests/test_rust_agents.py` などで固定されている。しかし固定されているのは
**個々のエージェントの手**であって、「このガントレットの、この組の、この局数での勝敗の集計」ではない。
**信じるのではなく、この盤面で確かめてから使う。**

## 何を確かめるか

指定した組を **Python 版と Rust 版の両方で**回し、`wins` / `decided` が**完全に一致する**ことを見る。
勝率や信頼区間ではなく**生の数**で比べる（丸めで違いが隠れないように）。

    python3 experiments/check_ladder_engines.py core5 --n 40 --pairs 6

`--pairs` は確かめる組の数（重いものから選ぶ）。`--n` はその組で回す局数。
1 組でも食い違ったら**そこで止めて報告する**——ラダーを Rust 版で回してはならない。

なお `mcts` が絡む組は Rust 版が無いので、はじめから対象外である。
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

import ladder                                                   # noqa: E402
from arena import series                                        # noqa: E402
from arena_rs import ensure_cards, series_rs                    # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("gauntlet", nargs="?", default="core5")
    ap.add_argument("--n", type=int, default=40, help="1 組あたりの局数")
    ap.add_argument("--pairs", type=int, default=6, help="確かめる組の数（重いものから）")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=None, help="既定はそのラダーのシード帯")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    g = ladder.load_gauntlet(args.gauntlet)
    ensure_cards()
    config = ladder.build_config(g)
    mk = ladder.build_agents(g)
    rspec = ladder.build_rust_specs(g)
    seed0 = args.seed0 if args.seed0 is not None else g["seed_band"]
    names = [n for n in g["agents"] if rspec.get(n) is not None]

    # **重い組から確かめる**（軽い組は一致していても安心材料が薄い。
    # 探索が深く枝が多い組ほど、実装の違いが出るなら出る）。
    HEAVY_HINT = ("planner_vc4cps_kheb_b75", "planner_vc4cps_kheb", "planner_vc4cps",
                  "planner_vb3cps", "planner_vb3cp",
                  "planner_vb3", "planner_vb1",
                  "planner_lh", "planner_pi", "planner", "greedy", "H", "random")
    rank = {n: i for i, n in enumerate(HEAVY_HINT)}
    cand = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]
    cand.sort(key=lambda ab: (rank.get(ab[0], 99) + rank.get(ab[1], 99)))
    cand = cand[:args.pairs]

    print(f"■ ラダー {g['name']} を Rust 版で回してよいかの確認")
    print(f"  {len(cand)} 組 × {args.n} 局・シード {seed0}..{seed0 + args.n - 1}・workers={args.workers}")
    print(f"  比べるのは**生の数**（勝ち数と決着数）。1 つでも違えば Rust 版では回さない。\n")
    rows, ok_all = [], True
    for a, b in cand:
        t = time.time()
        rp = series(mk[a], mk[b], args.n, config, args.workers, seed0)
        t_py = time.time() - t
        t = time.time()
        rr = series_rs(rspec[a], rspec[b], args.n, config, args.workers, seed0)
        t_rs = time.time() - t
        ok = (rp.wins == rr.wins) and (rp.decided == rr.decided)
        ok_all &= ok
        rows.append({"a": a, "b": b, "n": args.n, "seed0": seed0,
                     "python": {"wins": rp.wins, "decided": rp.decided, "sec": round(t_py, 1)},
                     "rust": {"wins": rr.wins, "decided": rr.decided, "sec": round(t_rs, 1)},
                     "same": bool(ok)})
        mark = "一致" if ok else "**食い違い**"
        speed = f"{t_py / t_rs:.1f} 倍速い" if t_rs > 0 else "—"
        print(f"  {a:>14} vs {b:<14} python {rp.wins:>5}/{rp.decided:<4} "
              f"rust {rr.wins:>5}/{rr.decided:<4} {mark}   "
              f"（{t_py:.0f}s → {t_rs:.0f}s・{speed}）", flush=True)
        if not ok:
            print("\n  **止める。** 実装が食い違っている。ラダーを Rust 版で回してはならない。")
            break

    out = {"gauntlet": g["name"], "n": args.n, "seed0": seed0, "rows": rows, "all_same": bool(ok_all)}
    path = args.out or os.path.join(_HERE, "..", "results", f"ladder_engine_check_{g['name']}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n{'すべて一致した。Rust 版で回してよい。' if ok_all else '一致しなかった。'}"
          f"  → {os.path.normpath(path)}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
