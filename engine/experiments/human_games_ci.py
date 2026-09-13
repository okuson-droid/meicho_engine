"""対人局の勝率を「区間」で読む道具（文献計画 便 D・D-1）。

## この道具の読み方

**問題**: 対人の記録はいま 4 局しかなく、AI は 0 勝である。これを「勝率 0%」と書くと
嘘になる。4 回コインを投げて 4 回とも裏が出ても、そのコインが「絶対に表が出ない」
とは言えないのと同じである。**少ない回数から言えるのは点ではなく範囲**である。

**この道具が出すもの**: 勝ち数 x と対局数 n から、勝率が入っていそうな範囲を 2 通りで出す。

- **Wilson 区間** … ふだん使う 95% 区間。n が小さくても 0 や 1 をはみ出さない
- **Clopper-Pearson 区間**（正確区間）… 二項分布から直に解く区間。**必ず Wilson より広い**。
  0 勝・全勝のような端では Wilson が狭すぎるので、**判断にはこちらを使う**

「95%」とは「同じ測り方を何度も繰り返したとき、その範囲が真の値を含む割合が 95%」
という意味である。1 回の測定について「95% の確率で正しい」と読むのは厳密には違うが、
実務上は「この範囲の外だとは考えにくい」と読んでよい。

**言えること／言えないこと**: n=4・0 勝なら「対マスター勝率は 0.602 を上回らない（95%）」
とは言える。しかし「どれくらい弱いか」は**まったく言えない**。0.05 でも 0.5 でも
この 4 局と矛盾しないからである。

**対人局は判定に使わない**（`REPORTING_RULES.md` §2.7）。判定は自己対戦の門番が行う。
対人局は「どの対抗で価値の見立てが崩れたか」を見る**診断**に使う。

## 使い方

    python3 experiments/human_games_ci.py
    python3 experiments/human_games_ci.py --json results/lit/d1_human_games_ci.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

Z = 1.96                       # 95%（両側 2.5% ずつ）
ALPHA_HALF = 0.025


# ------------------------------------------------------------------ 区間
def wilson(x: int, n: int, z: float = Z):
    """Wilson の 95% 区間 (lo, hi)。n=0 なら None。

    中心   (p̂ + z²/2n) / (1 + z²/n)
    半幅   z/(1 + z²/n) · √(p̂(1−p̂)/n + z²/4n²)
    """
    if n <= 0:
        return None
    p = x / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z / denom) * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)
    return (max(0.0, center - half), min(1.0, center + half))


def _binom_cdf_le(x: int, n: int, p: float) -> float:
    """P(X ≤ x) を素朴に足す（n は高々数千なので十分速い。scipy は使わない）。"""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if x >= n else 0.0
    # 対数で足すと桁落ちしない
    import math
    total = 0.0
    logp, logq = math.log(p), math.log1p(-p)
    lgam = math.lgamma
    for k in range(0, x + 1):
        lc = lgam(n + 1) - lgam(k + 1) - lgam(n - k + 1)
        total += math.exp(lc + k * logp + (n - k) * logq)
    return min(1.0, total)


def _bisect(f, lo: float, hi: float, target: float, iters: int = 200) -> float:
    """f が単調減少という前提で f(p) = target を二分法で解く。"""
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if f(mid) > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def clopper_pearson(x: int, n: int, alpha_half: float = ALPHA_HALF):
    """Clopper-Pearson（正確）95% 区間 (lo, hi)。n=0 なら None。

    上端 U は P(X ≤ x | U) = α/2 の解、下端 L は P(X ≥ x | L) = α/2 の解。
    端は閉じた形で置く（x=0 なら L=0・U = 1 − (α/2)^(1/n)、x=n はその鏡）。
    """
    if n <= 0:
        return None
    if x <= 0:
        return (0.0, 1.0 - alpha_half ** (1.0 / n))
    if x >= n:
        return (alpha_half ** (1.0 / n), 1.0)
    # 上端: P(X ≤ x | p) は p について単調減少
    hi = _bisect(lambda p: _binom_cdf_le(x, n, p), 0.0, 1.0, alpha_half)
    # 下端: P(X ≥ x | p) = 1 − P(X ≤ x−1 | p) は単調増加なので、符号を返して単調減少にする
    lo = _bisect(lambda p: 1.0 - (1.0 - _binom_cdf_le(x - 1, n, p)), 0.0, 1.0,
                 1.0 - alpha_half)
    return (lo, hi)


# ------------------------------------------------------------------ 集計
def _bucket(recs: list) -> dict:
    """勝敗が付いた局だけを数える。引き分け・投了・異常は分母から外す。"""
    n = wins = 0
    excluded = {"draw": 0, "aborted": 0, "error": 0, "resign": 0, "unfinished": 0}
    for r in recs:
        res = r.get("result") or {}
        reason = res.get("reason")
        if reason in ("error", "resign"):
            excluded[reason] += 1
            continue
        if res.get("draw"):
            excluded["draw"] += 1
            continue
        if res.get("aborted"):
            excluded["aborted"] += 1
            continue
        w = res.get("winner")
        if w not in ("ai", "human"):
            excluded["unfinished"] += 1
            continue
        n += 1
        wins += 1 if w == "ai" else 0
    out = {"n": n, "wins_ai": wins, "losses_ai": n - wins,
           "p": (wins / n) if n else None,
           "wilson": wilson(wins, n), "cp": clopper_pearson(wins, n),
           "excluded": excluded, "excluded_total": sum(excluded.values())}
    return out


def summarise(base_dir: str) -> dict:
    """`results/human_games/*.jsonl` を読み、全体／相手の版ごと／デッキごとに数える。"""
    from webapp import record as wrec
    recs = wrec.load_all(base_dir)
    by_opp: dict = {}
    by_deck: dict = {}
    for r in recs:
        by_opp.setdefault(r.get("opponent", {}).get("name", "?"), []).append(r)
        by_deck.setdefault(r.get("deck", "?"), []).append(r)
    overall = _bucket(recs)
    out = {
        "base_dir": os.path.abspath(base_dir),
        "games_total": len(recs),
        "overall": overall,
        "by_opponent": {k: _bucket(v) for k, v in sorted(by_opp.items())},
        "by_deck": {k: _bucket(v) for k, v in sorted(by_deck.items())},
        "opponents": sorted(by_opp),
        "mixed_opponents": len(by_opp) > 1,
    }
    return out


# ------------------------------------------------------------------ 表示
def _fmt(iv) -> str:
    return "  ―  " if iv is None else f"[{iv[0]:.3f}, {iv[1]:.3f}]"


def _row(name: str, b: dict) -> str:
    p = "  ―  " if b["p"] is None else f"{b['p']:.3f}"
    ex = f"  除外{b['excluded_total']}" if b["excluded_total"] else ""
    return (f"{name:<22}{b['n']:>5}{b['wins_ai']:>7}{p:>8}   "
            f"Wilson {_fmt(b['wilson'])}   CP {_fmt(b['cp'])}{ex}")


def render(out: dict) -> str:
    o = out["overall"]
    L = ["■ 対人局の勝率（AI から見た値）",
         "",
         "  n が小さい勝率は点で語れない。**範囲**で読むこと。",
         "  Wilson … ふだんの 95% 区間／CP（Clopper-Pearson）… 正確区間。端では必ず広い。",
         "  0 勝・全勝のような端では **CP を判断に使う**（Wilson は狭すぎる）。",
         "",
         f"{'区分':<22}{'n':>5}{'AI勝':>7}{'p̂':>8}   {'95% 区間'}",
         "-" * 92,
         _row("全体", o)]
    for k, b in out["by_opponent"].items():
        L.append(_row(f"  相手 {k}", b))
    if len(out["by_deck"]) > 1:
        for k, b in out["by_deck"].items():
            L.append(_row(f"  デッキ {k}", b))
    L.append("")
    if out["mixed_opponents"]:
        L.append("  ※ 相手の版が混在している（" + " / ".join(out["opponents"]) + "）。"
                 "版ごとに強さが違うので、**1 つの二項として扱うのは近似**である。")
    L.append("")
    if o["n"] == 0:
        L.append("言えること: 何も言えない（勝敗の付いた局が 0）")
    else:
        L.append(f"言えること: AI の対マスター勝率は **{o['cp'][1]:.3f} を上回らない**（95%・"
                 f"n={o['n']}・AI {o['wins_ai']} 勝）")
        L.append(f"言えないこと: **どれくらい弱いか**（下端は {o['cp'][0]:.3f} まで開いている）。"
                 "対人局は判定ではなく診断に使う（REPORTING_RULES.md §2.7）")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(_HERE, "..", "results"),
                    help="results ディレクトリ（この下の human_games/ を読む）")
    ap.add_argument("--json", default=None, help="集計を JSON でも書き出す")
    args = ap.parse_args(argv)

    out = summarise(args.results)
    print(render(out))
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"\n→ {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
