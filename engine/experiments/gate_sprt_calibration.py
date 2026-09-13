"""逐次検定 GSPRT が本当に約束どおりの誤り率で止まるかを確かめる（D-075 の宿題）。

## なぜこれが要るか

`experiments/gate_sprt.py` は「α = 0.025（互角なのに合格させてしまう確率の上限）／
β = 0.10（p₁ = 0.55 の強さがあるのに落としてしまう確率の上限）」を**約束として掲げている**。
しかし便 D（後半）の検算では、この約束を確かめられなかった。**対照（同じ AI どうし）が
この設計では退化する**からである——ペアの 2 局は文字どおり同じ 1 局になり、
ペア得点は必ずちょうど 0.5、ばらつきは 0 になる。ばらつきが 0 の対照は
「40 回に 1 回は間違って合格する」という形の確認に使えない。

そこでこの道具は 2 段構えで確かめる。

1. **形を実測する**（対局あり）。**互角だが別物の 2 体**——`planner_vb3cp` と
   `planner_vb3cps`（ラダー v9 で Elo 同点 1474、直接対決 0.513 ±0.057。違いは
   先読みの代打ちに使う π だけ）——を当てて、**ペア得点の度数の形**を数える。
2. **止め方だけを何万回もやり直す**（対局なし）。1 で測った形から、
   **平均をちょうど 0.5 にした分布**（＝本当に互角のときの形）と
   **平均をちょうど 0.55 にした分布**（＝ちょうど p₁ の強さがあるときの形）を作り、
   そこからペア得点を引いては逐次検定を最後まで回す、を何万回も繰り返す。
   合格した割合が実際の α、不合格になった割合が実際の β である。

**なぜ 2 段に分けるのか**: 実物の対局で α を測ろうとすると、40 回に 1 回の出来事を
数えるために逐次検定を何百本も回すことになり、1 本 10 分としても何日もかかる。
**形さえ実測できれば、止め方の性質は計算で確かめられる。**
形は対局から取るので「机上の仮定」ではない。

## 「平均をちょうど 0.5 にした分布」の作り方（2 通り。両方出す）

- **左右対称化**（既定・こちらを本命とする）: q(x) = (f(x) + f(1−x)) / 2。
  本当に互角な 2 体なら、ペア得点の分布は 0.5 を中心に**左右対称**でなければならない
  （2 連勝と 2 連敗が同じ確率で起きる）。対称化は**その性質を素直に課す**やり方で、
  平均は自動的にちょうど 0.5 になる。
- **傾け（指数傾斜）**: `gate_sprt.mle_with_mean(f, 0.5)`。検定そのものが使っているのと
  **同じ変換**で平均を 0.5 に合わせる。対称性は課さない。

2 つの答えが近ければ、「形の作り方」に結論が依存していないことの確認になる。

## 使い方

    # 1. 形を実測する（600 局。`planner_vb3cp` は代打ちに大きいネットを使うので約 1 時間）
    python3 experiments/gate_sprt_calibration.py measure --seed0 670000 --pairs 300 \
        --workers 2 --out results/vb/gsprt_calib_shape.json

    # 2. 止め方を何万回もやり直す（対局なし・約 20 分）
    #    あわせて「1 勝 1 敗の割合」を振った走査も出す（形の測り方のぶれに対する頑健さ）
    python3 experiments/gate_sprt_calibration.py simulate \
        --shape results/vb/gsprt_calib_shape.json --runs 30000 --sweep-runs 20000 \
        --out results/vb/gsprt_calib_sim.json

    # 3. 実物の逐次検定で追試する（対局あり・答え合わせ）
    python3 experiments/gate_sprt_calibration.py replicate --seed0 670400 --runs 4 \
        --span 250 --workers 2 --out results/vb/gsprt_calib_replicate.json

**母数は `gate_sprt.py` の定数をそのまま使う**（この道具からは変えられない）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import sys
import time
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import gate_sprt as G                                              # noqa: E402

JST = timezone(timedelta(hours=9))

# 互角だが別物の 2 体（現 champion への差分で書く）。
# `planner_vb3cp`  = 葉 V_3 ＋ 代打ち π が V_3 と同じネット
# `planner_vb3cps` = 葉 V_3 ＋ 代打ち π が蒸留した小さい版
# ラダー v9 で Elo は同点（1474 [1452, 1499]）、直接対決 154/300 = 0.513 ±0.057。
PAIR_A = {"value_net": "drl_sd001_vb3.json", "policy_net": "drl_sd001_vb3.json"}
PAIR_B = {"value_net": "drl_sd001_vb3.json", "policy_net": "pi_small64_e10.json"}
PAIR_NAMES = ("planner_vb3cp", "planner_vb3cps")


# ====================================================================== 形
def measure(seed0: int, pairs: int, workers: int, chunk: int = 20) -> dict:
    """互角だが別物の 2 体を当て、ペア得点の度数を数える（対局あり）。"""
    from arena import load_deck, mirror_config
    from arena_rs import ensure_cards
    ensure_cards()
    deck = load_deck("SD001")
    cfg = mirror_config(deck)
    # `build_specs(deck, pool, 挑戦者の差分, 基準の差分)` は (基準, 挑戦者) を返す。
    # 挑戦者 = `planner_vb3cps`（PAIR_B）、基準 = `planner_vb3cp`（PAIR_A）。
    base, chal = G.build_specs("SD001", deck["action_deck"], PAIR_B, PAIR_A)
    counts = [0] * 5
    wins = decided = 0
    t0 = time.time()
    done = 0
    while done < pairs:
        m = min(chunk, pairs - done)
        blk = G.pair_block(chal, base, cfg, seed0 + done, m, workers)
        for r in blk:
            counts[G.Gsprt.bucket(r["score"])] += 1
            wins += r["s_a"] + r["s_b"]
            decided += 2 - r["undecided"]
        done += m
        print(f"  … {done:>4}/{pairs} ペア（{2 * done} 局）  度数 {counts}", flush=True)
    n = sum(counts)
    mean = sum(c * x for c, x in zip(counts, G.PAIR_SCORES)) / n
    return {"pairs": n, "games": 2 * n, "counts": counts, "mean_pair_score": mean,
            "wins": wins, "decided": decided,
            "winrate": wins / decided if decided else None,
            "wilson": G.wilson_interval(wins, decided),
            "seed0": seed0, "workers": workers, "sec": round(time.time() - t0, 1),
            "pair": {"challenger": PAIR_NAMES[1], "base": PAIR_NAMES[0],
                     "challenger_diff": PAIR_B, "base_diff": PAIR_A}}


def symmetrised(counts) -> list:
    """左右対称化: q(x) = (f(x) + f(1−x)) / 2。平均は必ずちょうど 0.5 になる。"""
    n = float(sum(counts))
    f = [c / n for c in counts]
    return [(f[k] + f[len(f) - 1 - k]) / 2.0 for k in range(len(f))]


def tilted(counts, p: float) -> list:
    """指数傾斜で平均をちょうど p に合わせる（検定が内部で使うのと同じ変換）。"""
    n = float(sum(counts))
    f = G.regularize([c / n for c in counts])
    return G.mle_with_mean(f, p)


def _mean(q) -> float:
    return sum(a * x for a, x in zip(q, G.PAIR_SCORES))


# ====================================================================== 止め方の再現
def simulate(q, runs: int, seed: int = 0) -> dict:
    """分布 q からペア得点を引いて逐次検定を最後まで回す、を `runs` 回。

    **判定は 20 ペア（40 局）ごとの塊の切れ目でだけ行う**（実物と同じ）。
    戻り値は合格・不合格・上限それぞれの割合と、使った局数の分布。
    """
    rng = random.Random(seed)
    cum, acc = [], 0.0
    for w in q:
        acc += w
        cum.append(acc)
    cum[-1] = 1.0
    xs = G.PAIR_SCORES
    max_pairs = G.MAX_GAMES // 2
    tally = {"pass": 0, "fail": 0, "cap": 0}
    games = {"pass": [], "fail": [], "cap": []}
    for _ in range(runs):
        counts = [0] * 5
        v = "continue"
        done = 0
        while v == "continue":
            for _ in range(G.CHUNK_PAIRS):
                u = rng.random()
                k = 0
                while u > cum[k]:
                    k += 1
                counts[k] += 1
            done += G.CHUNK_PAIRS
            llr = G.llr_from_counts(counts)
            if llr >= G.A_BOUND:
                v = "pass"
            elif llr <= G.B_BOUND:
                v = "fail"
            elif 2 * done >= G.MAX_GAMES:
                v = "cap"
        tally[v] += 1
        games[v].append(2 * done)
    allg = sorted(g for lst in games.values() for g in lst)
    def q_(p):
        return allg[min(len(allg) - 1, int(p * len(allg)))] if allg else None
    out = {"runs": runs, "seed": seed,
           "q": list(q), "mean_of_q": _mean(q),
           "rates": {k: tally[k] / runs for k in tally},
           "counts": tally,
           "games_mean": sum(allg) / len(allg) if allg else None,
           "games_median": q_(0.5), "games_p90": q_(0.9), "games_max": allg[-1] if allg else None,
           "xs": list(xs)}
    for k in tally:
        out[f"games_mean_{k}"] = (sum(games[k]) / len(games[k])) if games[k] else None
    return out


def wilson(x: int, n: int):
    return G.wilson_interval(x, n)


def split_shape(split: float) -> list:
    """1 勝 1 敗（ペア得点 0.5）の割合が `split` の、左右対称な三項分布。

    実測ではペア得点 0.25 と 0.75 は**引き分けが要るので必ず 0** になる。
    したがって互角のときの形は「1 勝 1 敗が何割か」という数 1 つで決まる。
    形を 300 ペアから測ると 1 勝 1 敗の割合は ±0.056 ほどぶれるので、
    **その幅を丸ごと走査して、答えが幅の中で変わらないことを見る**のがこの関数の役目である。
    """
    if not 0.0 <= split <= 1.0:
        raise ValueError(f"split は 0..1（受け取った値 {split}）")
    side = (1.0 - split) / 2.0
    return [side, 0.0, split, 0.0, side]


def sweep(splits, runs: int, seed: int = 0) -> list:
    """1 勝 1 敗の割合を振って、実際の α と β がどう動くかを見る。"""
    out = []
    for s in splits:
        q0 = split_shape(s)
        q1 = G.mle_with_mean(G.regularize(q0), G.P1)
        r0 = simulate(q0, runs, seed=seed)
        r1 = simulate(q1, runs, seed=seed + 1)
        out.append({"split": s, "alpha": r0["rates"]["pass"], "beta": r1["rates"]["fail"],
                    "cap_null": r0["rates"]["cap"], "cap_alt": r1["rates"]["cap"],
                    "games_mean_null": r0["games_mean"], "games_mean_alt": r1["games_mean"],
                    "runs": runs})
    return out


# ====================================================================== 実物の追試
def replicate(seed0: int, runs: int, workers: int, span: int = 100) -> dict:
    """互角の 2 体で**実物の逐次検定**を `runs` 本回す（1 本あたり最大 `span` ペア）。

    シミュレーションの答え合わせである。上限を 100 ペア（200 局）に切ってあるので
    「上限で止まった」が多く出るが、**合格側で止まった本数**が実際の誤合格率の目安になる。
    """
    from arena import load_deck, mirror_config
    from arena_rs import ensure_cards
    ensure_cards()
    deck = load_deck("SD001")
    cfg = mirror_config(deck)
    base, chal = G.build_specs("SD001", deck["action_deck"], PAIR_B, PAIR_A)
    rows = []
    t0 = time.time()
    for i in range(runs):
        s0 = seed0 + i * span
        g = G.Gsprt()
        done, v = 0, "continue"
        while v == "continue" and done < span:
            m = min(G.CHUNK_PAIRS, span - done)
            for r in G.pair_block(chal, base, cfg, s0 + done, m, workers):
                g.add(r["score"])
            done += m
            v = g.verdict()
            if v == "cap":                        # 本当の上限ではなく span で切れただけ
                v = "continue"
        row = {"run": i, "seed0": s0, "verdict": v if v != "continue" else "span_limit",
               "pairs": g.pairs, "games": g.games, "llr": g.llr,
               "mean_pair_score": g.mean_score, "counts": list(g.counts)}
        rows.append(row)
        print(f"  本 {i + 1}/{runs}: {row['verdict']}  {row['games']} 局  "
              f"LLR {row['llr']:+.3f}  ペア平均 {row['mean_pair_score']:.4f}", flush=True)
    n_pass = sum(1 for r in rows if r["verdict"] == "pass")
    n_fail = sum(1 for r in rows if r["verdict"] == "fail")
    return {"runs": runs, "span_pairs": span, "seed0": seed0, "rows": rows,
            "n_pass": n_pass, "n_fail": n_fail,
            "n_span_limit": sum(1 for r in rows if r["verdict"] == "span_limit"),
            "pass_rate": n_pass / runs, "pass_wilson": wilson(n_pass, runs),
            "sec": round(time.time() - t0, 1)}


# ====================================================================== 本体
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("measure", help="ペア得点の形を実測する（対局あり）")
    m.add_argument("--seed0", type=int, required=True)
    m.add_argument("--pairs", type=int, default=300)
    m.add_argument("--workers", type=int, default=2)
    m.add_argument("--out", required=True)

    s = sub.add_parser("simulate", help="止め方を何万回もやり直す（対局なし）")
    s.add_argument("--shape", required=True, help="measure が書いた JSON")
    s.add_argument("--runs", type=int, default=30000)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--sweep-runs", type=int, default=20000,
                   help="1 勝 1 敗の割合を振る走査の 1 点あたりの本数（0 で走査しない）")
    s.add_argument("--out", required=True)

    r = sub.add_parser("replicate", help="実物の逐次検定で追試する（対局あり）")
    r.add_argument("--seed0", type=int, required=True)
    r.add_argument("--runs", type=int, default=10)
    r.add_argument("--span", type=int, default=100, help="1 本あたりの上限ペア数")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--out", required=True)

    args = ap.parse_args(argv)
    params = G.Gsprt().params()
    stamp = {"tool": "gate_sprt_calibration.py", "params": params,
             "when": datetime.now(JST).isoformat(timespec="seconds"),
             "platform": platform.platform()}

    if args.cmd == "measure":
        print("■ ペア得点の形を実測する（互角だが別物の 2 体）")
        print(f"  挑戦者 {PAIR_NAMES[1]} 対 基準 {PAIR_NAMES[0]}／帯 {args.seed0}..")
        out = {**stamp, **measure(args.seed0, args.pairs, args.workers)}
        print()
        print(f"→ {out['pairs']} ペア（{out['games']} 局）  度数 "
              f"{dict(zip(G.PAIR_SCORES, out['counts']))}")
        print(f"   ペア得点の平均 {out['mean_pair_score']:.4f}／"
              f"1 勝 1 敗の割合 {out['counts'][2] / out['pairs']:.3f}")
        print(f"   ふつうの勝率 {out['winrate']:.4f}  Wilson "
              f"[{out['wilson'][0]:.3f}, {out['wilson'][1]:.3f}]（n={out['decided']}）")

    elif args.cmd == "simulate":
        shape = json.load(open(args.shape, encoding="utf-8"))
        counts = shape["counts"]
        qs = {
            "null_symmetrised": symmetrised(counts),
            "null_tilted": tilted(counts, G.P0),
            "alt_symmetrised_tilted": G.mle_with_mean(
                G.regularize(symmetrised(counts)), G.P1),
            "alt_tilted": tilted(counts, G.P1),
            "observed": [c / sum(counts) for c in counts],
        }
        out = {**stamp, "shape_file": os.path.basename(args.shape),
               "shape_counts": counts, "runs": args.runs, "results": {}}
        print("■ 止め方だけを何度もやり直す（対局なし）")
        print(f"  形の出どころ: {os.path.basename(args.shape)}  度数 {counts}")
        print(f"  母数: α={params['alpha']} β={params['beta']} p₀={params['p0']} "
              f"p₁={params['p1']} 上限={params['max_games']}局")
        print()
        for name, q in qs.items():
            res = simulate(q, args.runs, seed=args.seed)
            out["results"][name] = res
            rt = res["rates"]
            print(f"  {name:<24} 平均 {res['mean_of_q']:.4f}  "
                  f"合格 {rt['pass']:.4f} / 不合格 {rt['fail']:.4f} / 上限 {rt['cap']:.4f}  "
                  f"局数 平均 {res['games_mean']:.0f}・中央 {res['games_median']}・"
                  f"9 割 {res['games_p90']}")
        if args.sweep_runs > 0:
            splits = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
            print()
            print("  1 勝 1 敗の割合を振ったとき（形の測り方のぶれに対する頑健さ）:")
            sw = sweep(splits, args.sweep_runs, seed=args.seed)
            out["sweep"] = sw
            for row in sw:
                print(f"    1 勝 1 敗 {row['split']:.2f} → 実際の α {row['alpha']:.4f} / "
                      f"実際の β {row['beta']:.4f}  平均局数 互角 {row['games_mean_null']:.0f}・"
                      f"p₁ {row['games_mean_alt']:.0f}")
        a_sym = out["results"]["null_symmetrised"]["rates"]["pass"]
        b_sym = out["results"]["alt_symmetrised_tilted"]["rates"]["fail"]
        print()
        print(f"→ **実際の α（互角なのに合格した割合）= {a_sym:.4f}**"
              f"（約束は {params['alpha']} 以下）"
              f"  {'✓ 守られている' if a_sym <= params['alpha'] else '**破れている**'}")
        print(f"→ **実際の β（p₁ の強さがあるのに落とした割合）= {b_sym:.4f}**"
              f"（約束は {params['beta']} 以下）"
              f"  {'✓ 守られている' if b_sym <= params['beta'] else '**破れている**'}")
        out["alpha_actual"] = a_sym
        out["beta_actual"] = b_sym
        out["alpha_ok"] = bool(a_sym <= params["alpha"])
        out["beta_ok"] = bool(b_sym <= params["beta"])

    else:
        print("■ 実物の逐次検定で追試する（互角だが別物の 2 体）")
        out = {**stamp, **replicate(args.seed0, args.runs, args.workers, args.span)}
        print()
        print(f"→ {out['runs']} 本中 合格 {out['n_pass']} 本／不合格 {out['n_fail']} 本／"
              f"上限（{out['span_pairs']} ペア）まで未決 {out['n_span_limit']} 本")
        w = out["pass_wilson"]
        print(f"   合格した割合 {out['pass_rate']:.3f}  Wilson [{w[0]:.3f}, {w[1]:.3f}]"
              f"（n={out['runs']}・**本数が少ないので幅は広い**）")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
