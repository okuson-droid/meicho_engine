"""相手の手札としてありうる世界の**数え上げと列挙**（文献計画 便 C 段 C-3・D-077 追記 3）。

## なぜここに移したか

W（区別できる相手の手札の数）の数え方は、もともと診断の道具
`experiments/diag_pimc.py` の中にあった（便 M）。段 C-3（II-9 終盤の全列挙）では
**探索の本体**が同じ数え方を使う。写して 2 か所に置くと、片方だけ直したときに
「診断が言う W」と「探索が使う W」が黙ってずれる（D-075 の `TracingPlanner` の教訓）。
そこで**数える関数はここ 1 か所に置き、`diag_pimc.py` はここを呼ぶ**。

数字が変わっていないことは `tests/test_lit_c.py::test_worlds_module_matches_diag_pimc` が
便 M の記録（`results/lit/m5m1_pimc.jsonl`）と突き合わせて固定する。

## 何を数えるか

相手の手札は**多重集合**である（同じ札が 2 枚あってもその 2 枚は区別しない）。
公開情報から作った未公開の候補 `pool` と、手札の枚数 `n_hand`、
そして「必ず含まれると分かっている札」`known`（スキャンで見て今も手札にある札・D-023）から、

- **W** … ありうる区別できる手札が何通りあるか
- **H_w** … 多重度で重みづけた分布のエントロピー（bit）
- **列挙** … その手札を全部並べる（重み＝その型になる**物理的な配り方**の数）

を出す。重みは Π_i C(c_i, a_i)——「その種類の札が c_i 枚あるうち a_i 枚を持つ組み合わせ」の積である。
配りが一様なら、手札 h の確率はこの重みに比例する。

**列挙は W が小さいときにしか使えない。** 段 C-3 は W ≤ 64 の決定に限って使う
（便 M の実測で決定の 14.3%・終盤に集中する）。
"""
from __future__ import annotations

import math
from collections import Counter
from math import comb


def remove_multiset(pool: list, take) -> list:
    """多重集合の引き算。`pool` から `take` の各カードを 1 枚ずつ取り除いた残り。

    並びは `pool` のまま（取り除いたものが抜けるだけ）。
    """
    left = Counter(take)
    out = []
    for cid in pool:
        if left.get(cid, 0) > 0:
            left[cid] -= 1
        else:
            out.append(cid)
    return out


def world_counts(pool, n_hand: int, known=()) -> dict:
    """相手の手札としてありうる**区別できる多重集合**の数 W と、重みつきエントロピー H_w。

    数え上げは種類ごとの生成関数 ∏(1 + x + … + x^{c_i}) の x^k の係数で、
    同じ DP で Σw と Σ w·ln w を持ち回ってエントロピーも一度に出す。

    **この関数の中身は便 M（`diag_pimc.py`）から 1 行も変えずに移したものである。**
    """
    pool = list(pool)
    known = list(known)
    left = remove_multiset(pool, known)
    k = n_hand - len(known)
    if k < 0 or k > len(left):
        # 情報が食い違う（起きないはずだが、起きたら黙って 0 にしない）
        return {"W": 0, "H_w": None, "k": k, "pool_size": len(pool),
                "known_n": len(known), "inconsistent": True}
    S = [0.0] * (k + 1)          # Σ 重み
    T = [0.0] * (k + 1)          # Σ 重み·ln(重み)
    W = [0] * (k + 1)            # 区別できる多重集合の数
    S[0], W[0] = 1.0, 1
    for c in sorted(Counter(left).values()):
        nS, nT, nW = [0.0] * (k + 1), [0.0] * (k + 1), [0] * (k + 1)
        for j in range(k + 1):
            if W[j] == 0:
                continue
            for a in range(0, min(c, k - j) + 1):
                v = float(comb(c, a))
                nS[j + a] += S[j] * v
                nT[j + a] += v * T[j] + S[j] * v * math.log(v)
                nW[j + a] += W[j]
        S, T, W = nS, nT, nW
    tot = S[k]
    h = None if tot <= 0 else (math.log(tot) - T[k] / tot) / math.log(2.0)
    if h is not None and abs(h) < 1e-12:
        h = 0.0
    return {"W": W[k], "H_w": h, "k": k, "pool_size": len(pool),
            "known_n": len(known), "inconsistent": False}


def enumerate_hands(pool, n_hand: int, known=(), limit: int = None) -> list:
    """ありうる相手の手札を**全部**並べる（段 C-3・II-9）。

    返すのは `[(手札, 重み), ...]`。手札は `known` を含む**並べ替え済み**のリストで、
    重みは「その型になる物理的な配り方の数」（`world_counts` の重みと同じ定義）。
    並びは **重みの大きい順、同点は手札の並び順**——`limit` で上から切っても
    同じシードなら同じ集合になるように、**完全に決定的**にしてある。

    `limit` を渡すと上位 `limit` 本だけ返す（§0.3 (vi) の `endgame_eval`）。
    W ≤ limit なら**取りこぼしが無い＝厳密**である。

    数え上げ（`world_counts`）と同じ規則で作ってあることは
    `tests/test_lit_c.py::test_endgame_enumeration_is_exhaustive` が固定する
    （列挙した本数が W と一致し、重みの合計が数え上げの Σ 重みと一致する）。
    """
    pool = list(pool)
    known = list(known)
    left = remove_multiset(pool, known)
    k = n_hand - len(known)
    if k < 0 or k > len(left):
        return []
    kinds = sorted(Counter(left).items())          # (card_id, 枚数) を id 順に
    out: list = []

    def walk(i: int, rest: int, taken: list, weight: float) -> None:
        if rest == 0:
            hand = sorted(known + [c for c, a in taken for _ in range(a)])
            out.append((hand, weight))
            return
        if i >= len(kinds):
            return
        cid, cnt = kinds[i]
        # 残りの札で足りるかを先に見る（枝を無駄に伸ばさない）
        if sum(c for _, c in kinds[i:]) < rest:
            return
        for a in range(min(cnt, rest), -1, -1):
            walk(i + 1, rest - a, taken + ([(cid, a)] if a else []),
                 weight * comb(cnt, a))

    walk(0, k, [], 1.0)
    # 重みの大きい順・同点は手札の並び順（**完全に決定的**）
    out.sort(key=lambda t: (-t[1], t[0]))
    return out if limit is None else out[:max(0, int(limit))]


def d_from_w(w: int, w0: int) -> float:
    """D_t = 1 − log W_t / log W_0。W_0 = 1（最初から確定）なら 1 と定義する。"""
    if not w0 or w0 <= 1:
        return 1.0
    if w <= 0:
        return 1.0
    return 1.0 - math.log(w) / math.log(w0)
