"""束ねた対抗ゲームのソルバ（文献計画 便 A 後半・A-2）。

## 何を解くのか

先読みは対抗の決定で**決定化 K 本**を引く。従来（そしていまの champion）は
**1 本ごとに**相手の最尤 1 手（π₀ の手）を当てて点を付け、K 本の期待値で比べていた。
これは「K 本それぞれで別の手を出してよい」ことになっていて、文献の言う
**strategy fusion**（決定化ごとに違う手を選べると思い込む誤り）そのものである
（`PAPER_NOTES_20260906_PART2.md` §2 の A-9 の読み直し）。

A-2 はここを直す。**AI の提出分布 x は K 本に共通**とし、相手は本ごとに最悪の応手を
選べるとして

    max_x  Σ_k w_k · min_{y_k} xᵀ A_k y_k

を解き、**平均戦略**から手を選ぶ。`A_k` は世界 k での（自分の手 i, 相手の手 j）の点数表、
`w_k` は `_worlds` が返す世界の重みである。行数（自分の合法手）は世界に依らず同じ、
列数（相手の合法手）は世界ごとに違ってよい。

## 解き方（交互更新の予測つき RM+・決定的）

自己対戦の後悔最小化をまわす。中身は 3 つの決まりごとでできている。

1. **RM+**（負の後悔を持ち越さない）。素の RM は `R ← R + r`、RM+ は `R ← max(0, R + r)`。
2. **交互更新**。1 反復の中で、まず自分の戦略を出し、それに対して相手を更新し、
   **更新後の相手**に対して自分を更新する。同時更新より収束がずっと速い（CFR+ と同じ形）。
3. **予測項**。戦略を作るとき、累積後悔に**直前の反復の瞬時後悔**を足した値で
   regret matching する（predictive RM+）。足した結果が負になりうるので、
   **正の部分を取ってから**正規化する——ここを忘れると分母に負が混ざり、
   反復数を増やしても可搾取度が上下に暴れる（実際に一度踏んだ）。

返すのは**平均戦略**（反復番号 t で重みを付けた線形平均）。
**その時々の戦略 `x_t` を返してはいけない**——RM+ の `x_t` は角（純戦略）に寄るので、
混ぜること自体を目的にした改良が台無しになる。ここを取り違えると全部が嘘になる。

実測（3×3 の非対称・厳密解 1.95 との可搾取度）: 反復 300 で **1.35e-4**、
1,000 で 1.22e-5、20,000 で 3.05e-8。じゃんけんは反復 300 で厳密に 1/3。

## 乱数を使わない

初期値は一様、反復数は固定、`rng` は受け取らない。つまみを立てた候補でも
**乱数の消費が増えない**ので、候補間の同シード比較が壊れない。

## Rust の写しと丸めを揃えるための約束（引継ぎ書 §1）

浮動小数は**足す順序で最後の桁が変わる**。平均戦略が 1e-12 ずれると、同点の手の
選ばれ方が変わって**手が割れる**。したがって次の走査順を Python と Rust で完全に揃える:

1. 相手側の `c[j]`（相手の手 j に対する値）は **i の昇順**に `x[i]·A_k[i][j]` を足す。
2. 自分側の `u[i]` は **k の昇順**に `w_k × (Σ_j A_k[i][j]·y_k[j])` を足す。
   内側の `Σ_j` は **j の昇順**。
3. 平均戦略の累積は **t の昇順**。

## 相手側の後悔に重み `w_k` を掛けないこと

`y_k` は世界 k の中だけで正規化されるので、その世界の後悔をすべて同じ正の定数で
スケールしても**戦略は 1 ビットも変わらない**。掛けないほうが `w_k` が小さいときの
桁落ちが無いので、掛けない。**これは近似ではない。**
"""
from __future__ import annotations

# 反復数の既定。計画書 §3.1 は 200〜400 を挙げているので中を取る。
# **定数で持ち、検査で固定する**（黙って変えると過去の測定と比較できなくなる）。
DEFAULT_ITERS = 300


def _strategy(regret: list, pred: list) -> list:
    """累積後悔 ＋ 予測項から次の戦略を作る。正の部分が無ければ一様。

    **正の部分を取ってから正規化する。** 予測項を足すと負になりうるので、
    ここを省くと分母に負が混ざって収束が壊れる。
    """
    n = len(regret)
    pos = [0.0] * n
    s = 0.0
    for i in range(n):
        v = regret[i] + pred[i]
        if v > 0.0:
            pos[i] = v
            s += v
    if s <= 0.0:
        u = 1.0 / n
        return [u] * n
    return [v / s for v in pos]


def solve_bundled(mats: list, weights: list, iters: int = DEFAULT_ITERS) -> list:
    """束ねた対抗ゲームを解き、**AI 側の平均戦略**を返す。

    mats: 世界ごとの点数表 `A_k[i][j]`（行 = 自分の手・列 = 相手の手）。
    weights: 世界の重み `w_k`（`_worlds` が返すものをそのまま）。
    iters: 反復数。既定 `DEFAULT_ITERS`。

    戻り値は長さ = 行数の確率ベクトル（合計 1）。**乱数は使わない。**
    """
    if not mats:
        raise ValueError("mats が空")
    if len(mats) != len(weights):
        raise ValueError(f"mats {len(mats)} 本と weights {len(weights)} 本が合わない")
    n = len(mats[0])
    if n == 0:
        raise ValueError("行（自分の手）が 0")
    for k, a in enumerate(mats):
        if len(a) != n:
            raise ValueError(f"世界 {k} の行数 {len(a)} が {n} と違う")
        if not a[0]:
            raise ValueError(f"世界 {k} の列（相手の手）が 0")
    if int(iters) < 1:
        raise ValueError(f"iters は 1 以上（受け取った値 {iters}）")
    iters = int(iters)

    ncols = [len(a[0]) for a in mats]
    kn = len(mats)
    rx = [0.0] * n                       # 自分の累積後悔（RM+ なので 0 以上）
    ry = [[0.0] * m for m in ncols]      # 相手の累積後悔（世界ごと）
    px = [0.0] * n                       # 直前の瞬時後悔（予測項）
    py = [[0.0] * m for m in ncols]
    xbar = [0.0] * n
    wsum = 0.0

    for t in range(1, iters + 1):
        x = _strategy(rx, px)

        # 1. 相手側を、いまの x に対して更新する（世界ごと・i の昇順）
        for k in range(kn):
            a = mats[k]
            m = ncols[k]
            c = [0.0] * m
            for i in range(n):
                xi = x[i]
                row = a[i]
                for j in range(m):
                    c[j] += xi * row[j]
            y = _strategy(ry[k], py[k])
            vk = 0.0
            for j in range(m):
                vk += c[j] * y[j]
            rk = ry[k]
            pk = py[k]
            for j in range(m):
                inst = vk - c[j]         # 相手は最小化するので符号が逆
                pk[j] = inst
                v = rk[j] + inst
                rk[j] = v if v > 0.0 else 0.0

        # 2. 更新後の相手に対して自分を更新する（k の昇順 → j の昇順）
        ys = [_strategy(ry[k], py[k]) for k in range(kn)]
        u = [0.0] * n
        for k in range(kn):
            a = mats[k]
            wk = weights[k]
            y = ys[k]
            m = ncols[k]
            for i in range(n):
                row = a[i]
                acc = 0.0
                for j in range(m):
                    acc += row[j] * y[j]
                u[i] += wk * acc
        v = 0.0
        for i in range(n):
            v += x[i] * u[i]
        for i in range(n):
            inst = u[i] - v
            px[i] = inst
            q = rx[i] + inst
            rx[i] = q if q > 0.0 else 0.0

        # 3. 平均戦略（線形平均・t の昇順）
        for i in range(n):
            xbar[i] += t * x[i]
        wsum += t

    return [q / wsum for q in xbar]


def bundled_value(mats: list, weights: list, x: list) -> float:
    """提出分布 `x` を固定したときの**最悪想定の値** Σ_k w_k · min_j (xᵀA_k)_j。

    診断と記録のための量である（**打ち方には効かない**）。
    可搾取度は「厳密解の値 − この値」で測る。
    """
    total = 0.0
    for k, a in enumerate(mats):
        m = len(a[0])
        c = [0.0] * m
        for i in range(len(a)):
            xi = x[i]
            row = a[i]
            for j in range(m):
                c[j] += xi * row[j]
        best = c[0]
        for j in range(1, m):
            if c[j] < best:
                best = c[j]
        total += weights[k] * best
    return total
