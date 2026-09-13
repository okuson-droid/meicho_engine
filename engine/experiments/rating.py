"""レーティング推定（C-4 / D-034）。純粋関数のみ。エンジンに依存しない。

- Bradley-Terry モデルの最尤推定（Hunter 2004 の MM アルゴリズム）。
  総当たりの勝敗行列を一括で扱うので、対局順にも局数の偏りにも依存しない。
- Elo 換算 `400·log10(γ)`。差しか決まらないので錨（anchor）で平行移動する。
- パラメトリック・ブートストラップによる 95% 区間（作業規約6）。
  乱数は固定シードの `random.Random` のみ（グローバル乱数禁止）。
- 非推移性（A>B>C>A）の検出。

入力の勝敗行列は `pairs: list[dict]` で、各要素は
`{"a": 名, "b": 名, "wins_a": int, "decided": int}`（a から見た勝数と有効局数）。
"""
from __future__ import annotations

import math
import random
from itertools import combinations


def bradley_terry(names: list, pairs: list, pseudo: float = 0.5,
                  iters: int = 2000, tol: float = 1e-10) -> dict:
    """各エージェントの強さ γ を返す（幾何平均 1 に正規化）。

    pseudo: 各ペアに加える仮想の勝ち・負け（各 pseudo 局）。
        全勝／全敗（完全分離）で推定が発散するのを防ぐ弱い事前分布。
    """
    idx = {n: i for i, n in enumerate(names)}
    k = len(names)
    wins = [0.0] * k                      # W_i: i の総勝数
    ngame = [[0.0] * k for _ in range(k)]  # n_ij: i と j の総局数
    for p in pairs:
        a, b = idx[p["a"]], idx[p["b"]]
        wa = p["wins_a"] + pseudo
        wb = (p["decided"] - p["wins_a"]) + pseudo
        wins[a] += wa
        wins[b] += wb
        ngame[a][b] += wa + wb
        ngame[b][a] += wa + wb
    g = [1.0] * k
    for _ in range(iters):
        new = []
        for i in range(k):
            denom = sum(ngame[i][j] / (g[i] + g[j]) for j in range(k) if ngame[i][j])
            new.append(wins[i] / denom if denom else g[i])
        # 幾何平均 1 に正規化（スケール不定性の固定）
        lg = sum(math.log(x) for x in new) / k
        new = [x / math.exp(lg) for x in new]
        delta = max(abs(a - b) for a, b in zip(new, g))
        g = new
        if delta < tol:
            break
    return dict(zip(names, g))


def to_elo(gamma: dict, anchor: str, anchor_elo: float = 1000.0) -> dict:
    """γ を Elo 尺度に換算し、anchor のレーティングが anchor_elo になるよう平行移動する。"""
    base = 400.0 * math.log10(gamma[anchor])
    return {n: anchor_elo + 400.0 * math.log10(g) - base for n, g in gamma.items()}


def bootstrap_elo(names: list, pairs: list, anchor: str, anchor_elo: float = 1000.0,
                  b: int = 1000, seed: int = 0, pseudo: float = 0.5) -> dict:
    """各ペアの勝数を二項分布で再標本化し、Elo の 2.5%〜97.5% 点を返す。

    戻り値: {名: {"elo": 点推定, "lo": 下限, "hi": 上限}}
    """
    rng = random.Random(seed)
    point = to_elo(bradley_terry(names, pairs, pseudo), anchor, anchor_elo)
    samples = {n: [] for n in names}
    for _ in range(b):
        res = []
        for p in pairs:
            n = p["decided"]
            q = p["wins_a"] / n if n else 0.5
            w = sum(1 for _ in range(n) if rng.random() < q)
            res.append({"a": p["a"], "b": p["b"], "wins_a": w, "decided": n})
        e = to_elo(bradley_terry(names, res, pseudo, iters=300, tol=1e-7),
                   anchor, anchor_elo)
        for nme in names:
            samples[nme].append(e[nme])
    out = {}
    for nme in names:
        s = sorted(samples[nme])
        lo = s[int(0.025 * (b - 1))]
        hi = s[int(0.975 * (b - 1))]
        out[nme] = {"elo": point[nme], "lo": lo, "hi": hi}
    return out


def ci95(wins: int, n: int) -> float:
    if n == 0:
        return float("nan")
    p = wins / n
    return 1.96 * math.sqrt(p * (1 - p) / n)


def significant_edges(pairs: list) -> set:
    """「x が y に有意に勝ち越す」（勝率の 95% 下限 > 0.5）有向辺 (x, y) の集合。"""
    edges = set()
    for p in pairs:
        n = p["decided"]
        if not n:
            continue
        pa = p["wins_a"] / n
        c = ci95(p["wins_a"], n)
        if pa - c > 0.5:
            edges.add((p["a"], p["b"]))
        elif (1 - pa) - c > 0.5:
            edges.add((p["b"], p["a"]))
    return edges


def find_cycles(names: list, pairs: list) -> list:
    """有意な勝ち越し関係に長さ 3 の閉路があれば列挙する（非推移性の検出）。"""
    e = significant_edges(pairs)
    cycles = []
    for x, y, z in combinations(names, 3):
        for a, b, c in ((x, y, z), (x, z, y)):
            if (a, b) in e and (b, c) in e and (c, a) in e:
                cycles.append([a, b, c])
    return cycles


def champion_candidates(pairs: list, champion: str) -> list:
    """現 champion との直接対決で 95% 下限 > 0.5 の挑戦者を返す（§6 の判定）。"""
    out = []
    for p in pairs:
        if champion not in (p["a"], p["b"]):
            continue
        n = p["decided"]
        if not n:
            continue
        if p["a"] == champion:
            chal, w = p["b"], n - p["wins_a"]
        else:
            chal, w = p["a"], p["wins_a"]
        pc = w / n
        if pc - ci95(w, n) > 0.5:
            out.append({"agent": chal, "p": pc, "ci": ci95(w, n), "n": n})
    return out
