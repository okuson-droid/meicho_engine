"""ラダーの記録を「順位表」より深く読む道具（文献計画 便 D 後半・D-5／第 2 集 §7.4.1・§7.5.5）。

## なぜ Elo だけでは足りないのか

ラダー（`results/ladder.json`）はいま **Elo** という 1 本の物差しで 13 体を並べている。
Elo は「強さは 1 つの数で表せる」という前提の上に立つ。じゃんけんのように
**A が B に勝ち、B が C に勝ち、C が A に勝つ**関係（*非推移性*）があると、
その前提は崩れる。1 位の体が「みんなに強い」のか「たまたま相性の良い相手が多かった」のか、
Elo の数字だけからは区別できない。

この道具は、同じ勝敗表から次の 6 つを出す。**対局は 1 局も回さない**（記録を読むだけ）。

1. **Nash averaging**（第 2 集 §7.5.5）… 「相手をどう混ぜて評価するのが公平か」を、
   ゲーム理論の均衡として決める。使用率でも一様でもなく、**均衡ウェイト**で評価する
2. **台（support）に乗っているか**… 均衡ウェイトが 0 でない体の集合を*台*という。
   台に乗る＝「誰かにとって本当に脅威である」。**champion が台に乗っていなければ、
   Elo 1 位でも「都合の良い相手にだけ強い」可能性がある**
3. **3 巡回の数**… じゃんけんの三すくみが何組あるか
4. **mElo₂ と Elo の当てはまり比べ**… 巡回成分を 2 次元ぶん足したモデル（mElo₂）が
   1 次元の Elo よりも**予測が上手いか**。上手ければ「強さは 1 本の物差しでは表せない」
5. **有効多様性**… 均衡ウェイトのもとで、体どうしの相性差がどれだけ残っているか
6. **先手の利**… 席（先攻／後攻）による勝率の偏り

## 用語（初出の説明・REPORTING_RULES §2.1）

- *ロジット* … 勝率 p を log(p/(1−p)) に直したもの。0.5 → 0、0.75 → +1.10、0.25 → −1.10。
  勝率を足し算のできる尺度に直す変換である（Elo の 400·log₁₀ と同じ族）
- *ゼロ和ゲーム* … 一方の得が他方の損とぴったり釣り合うゲーム。勝敗のロジットを
  利得にすると A_ij = −A_ji（*反対称*）になり、自動的にゼロ和になる
- *Nash 均衡* … 「相手の混ぜ方を知っても、自分の混ぜ方を変える気にならない」混ぜ方の組。
  対称なゼロ和ゲームでは値は必ず 0 で、均衡 p* は (A p*)_i ≤ 0 をすべての i で満たす
- *最大エントロピー Nash* … 均衡は 1 つとは限らない。均衡の中で**いちばん散らばった**
  ものを選ぶと一意に決まる（Balduzzi 2018 の選び方）。「同じ強さの体を差別しない」
  という意味であり、同じ体を 2 つ登録しても評価が変わらない性質（論文の P1）を持つ
- *対数損失* … 予測の外し具合。低いほど良い。当てずっぽう（いつも 0.5）なら 0.693

## 使い方

    python3 experiments/ladder_analysis.py                    # 最新（core5 v9）
    python3 experiments/ladder_analysis.py --index -2         # ひとつ前（v8）
    python3 experiments/ladder_analysis.py --index -1 --out-prefix results/ladder_analysis_core5_v9

`scipy` があれば最大エントロピー Nash を凸最適化で解き直して照合するが、**無くても動く**
（既定の解法は numpy だけで書いた regret matching＋の平均戦略である）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from itertools import combinations

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

JST = timezone(timedelta(hours=9))

TAUS = (0.55, 0.60, 0.70)          # 3 巡回を数えるときの辺の閾値
SUPPORT_TOL = 1e-3                 # 台に乗っていると見なす均衡ウェイトの下限


# ============================================================ 勝敗表 → 行列
def matrices(rec: dict):
    """記録 1 件から (names, P, N) を作る。

    P[i][j] … i が j に勝つ割合（対角は nan）／N[i][j] … その組の決着局数。
    """
    names = list(rec["agents"])
    idx = {n: i for i, n in enumerate(names)}
    k = len(names)
    P = np.full((k, k), np.nan)
    N = np.zeros((k, k))
    for p in rec["pairs"]:
        i, j = idx[p["a"]], idx[p["b"]]
        n = p["decided"]
        if not n:
            continue
        pa = p["wins_a"] / n
        P[i, j], P[j, i] = pa, 1.0 - pa
        N[i, j] = N[j, i] = n
    return names, P, N


def logit_matrix(P: np.ndarray, N: np.ndarray) -> np.ndarray:
    """反対称ロジット行列 A_ij = log(p_ij/(1−p_ij))。

    p が 0 や 1 ちょうどだとロジットが ±∞ になるので、**その組の局数から決まる幅**
    ε = 1/(2n) だけ内側に丸める（100% 勝ちを「1 − 1/(2n)」と読む。局数が多いほど
    端に近づけてよい、という素直な決め方である）。
    """
    k = P.shape[0]
    A = np.zeros((k, k))
    for i in range(k):
        for j in range(k):
            if i == j or not np.isfinite(P[i, j]):
                continue
            n = max(1.0, N[i, j])
            eps = 1.0 / (2.0 * n)
            p = min(1.0 - eps, max(eps, P[i, j]))
            A[i, j] = math.log(p / (1.0 - p))
    A = 0.5 * (A - A.T)                     # 数値誤差ぶんの非対称を落とす
    return A


# ============================================================ Nash averaging
def _rm_plus(A: np.ndarray, iters: int, r0: np.ndarray) -> np.ndarray:
    """対称ゼロ和ゲームの regret matching＋（線形平均）。平均戦略を返す。

    仕組み: 両者が同じ混ぜ方 p を使う。p での各手の利得は u = A p で、
    ゼロ和・対称なので平均利得は 0、したがって**後悔 r はそのまま u** である。
    後悔の累積 R を 0 で下から押さえながら足し、R を正規化したものを次の p にする。
    この平均戦略が Nash に収束することが知られている（CFR+ と同じ更新）。
    """
    k = A.shape[0]
    R = np.maximum(r0, 0.0).astype(float)
    acc = np.zeros(k)
    wsum = 0.0
    for t in range(1, iters + 1):
        s = R.sum()
        p = (R / s) if s > 0 else np.full(k, 1.0 / k)
        acc += t * p                         # 線形平均（新しいものを重く見る）
        wsum += t
        R = np.maximum(R + A @ p, 0.0)
    return acc / wsum


def maxent_nash(A: np.ndarray, iters: int = 20000, restarts: int = 8,
                seed: int = 0) -> dict:
    """最大エントロピー Nash の近似 p* と診断。

    手順（引継ぎ書 §3.2 (1) の推し）: 複数の初期値から regret matching＋を回し、
    得られた平均戦略を平均する。**均衡の集合は凸**なので、均衡どうしの平均は
    やはり均衡であり、平均を取るほど散らばった（＝エントロピーの高い）側に寄る。

    診断として、各初期値の解のばらつき（`spread`）と、最終解の *可搾取量*
    （exploitability。max_i (A p)_i。均衡なら 0）を返す（§7 の 4）。
    """
    k = A.shape[0]
    rng = np.random.default_rng(seed)
    sols = [_rm_plus(A, iters, np.zeros(k))]
    for _ in range(max(0, restarts - 1)):
        sols.append(_rm_plus(A, iters, rng.random(k)))
    S = np.array(sols)
    p = S.mean(axis=0)
    p = np.maximum(p, 0.0)
    p /= p.sum()
    spread = float(np.max(np.abs(S - p)))
    return {"p": p, "exploitability": float(np.max(A @ p)),
            "spread_across_restarts": spread, "iters": iters, "restarts": restarts,
            "entropy": float(-np.sum(p[p > 0] * np.log(p[p > 0]))),
            "solver": "rm_plus_multistart"}


def refine_maxent_scipy(A: np.ndarray, p0: np.ndarray, tol: float = 1e-9) -> dict | None:
    """scipy があれば、均衡の集合 {p ∈ Δ : A p ≤ 0} 上でエントロピーを最大化し直す。

    **照合用**である（既定の答えは `maxent_nash` の方）。scipy が無ければ None を返す。
    """
    try:
        from scipy.optimize import minimize
    except Exception:                                        # noqa: BLE001
        return None
    k = A.shape[0]

    def neg_entropy(p):
        q = np.clip(p, 1e-12, None)
        return float(np.sum(q * np.log(q)))

    cons = [{"type": "eq", "fun": lambda p: p.sum() - 1.0},
            {"type": "ineq", "fun": lambda p: -(A @ p) + tol}]
    res = minimize(neg_entropy, p0, method="SLSQP", bounds=[(0.0, 1.0)] * k,
                   constraints=cons, options={"maxiter": 500, "ftol": 1e-12})
    p = np.maximum(res.x, 0.0)
    if p.sum() <= 0:
        return None
    p /= p.sum()
    return {"p": p, "ok": bool(res.success), "message": str(res.message),
            "entropy": float(-np.sum(p[p > 0] * np.log(p[p > 0]))),
            "exploitability": float(np.max(A @ p)),
            "max_abs_diff_vs_rm": float(np.max(np.abs(p - p0)))}


def nash_scores(A: np.ndarray, p: np.ndarray) -> np.ndarray:
    """nA_i = (A p*)_i。**均衡ウェイトの相手に対する平均のロジット勝率**である。

    台に乗る体は 0、乗らない体は負になる（負であるほど「均衡の相手には勝てない」）。
    """
    return A @ p


def effective_diversity(A: np.ndarray, p: np.ndarray) -> float:
    """有効多様性 Σ_ij p_i p_j max(A_ij, 0)（第 2 集 §5.2.1）。

    均衡ウェイトで 2 体を引いたとき、**相性で得をする側の期待ロジット幅**である。
    0 なら全員が同じ順序で並ぶ（＝1 本の物差しで説明できる）。大きいほど
    「相手によって強さが入れ替わる」余地が残っている。
    """
    return float(p @ np.maximum(A, 0.0) @ p)


# ============================================================ 3 巡回
def count_cycles(names, P: np.ndarray, tau: float):
    """「i が j に勝率 τ 以上」を辺とし、長さ 3 の有向閉路を数える。"""
    k = len(names)
    E = np.zeros((k, k), dtype=bool)
    for i in range(k):
        for j in range(k):
            if i != j and np.isfinite(P[i, j]) and P[i, j] >= tau:
                E[i, j] = True
    cycles = []
    for x, y, z in combinations(range(k), 3):
        for a, b, c in ((x, y, z), (x, z, y)):
            if E[a, b] and E[b, c] and E[c, a]:
                cycles.append([names[a], names[b], names[c]])
    return cycles


# ============================================================ Elo / mElo₂
def split_pairs(rec: dict, seed: int = 0):
    """各組の決着局を**学習用と検証用に半々**に割る。

    記録には 1 局ごとの勝敗ではなく「n 局中 w 勝」しか残っていないので、
    n 個の玉（勝ちが w 個）を混ぜて半分に取り分ける形で割る（超幾何分布）。
    乱数は固定シードなので、同じ引数なら何度でも同じ割り方になる。
    """
    rng = np.random.default_rng(seed)
    tr, va = [], []
    for p in rec["pairs"]:
        n, w = int(p["decided"]), int(round(p["wins_a"]))
        if n <= 1:
            continue
        balls = np.array([1] * w + [0] * (n - w))
        rng.shuffle(balls)
        h = n // 2
        tr.append({"a": p["a"], "b": p["b"], "n": h, "w": int(balls[:h].sum())})
        va.append({"a": p["a"], "b": p["b"], "n": n - h, "w": int(balls[h:].sum())})
    return tr, va


def _logloss(rows, names, pred) -> float:
    idx = {n: i for i, n in enumerate(names)}
    tot = ll = 0.0
    for r in rows:
        i, j = idx[r["a"]], idx[r["b"]]
        q = min(1 - 1e-9, max(1e-9, pred(i, j)))
        ll += r["w"] * math.log(q) + (r["n"] - r["w"]) * math.log(1 - q)
        tot += r["n"]
    return -ll / tot if tot else float("nan")


def fit_elo(rows, names, lr: float = 0.05, iters: int = 4000):
    """1 次元 Elo（Bradley-Terry）を勾配降下で当てる。logit p_ij = r_i − r_j。"""
    idx = {n: i for i, n in enumerate(names)}
    k = len(names)
    r = np.zeros(k)
    I = np.array([idx[x["a"]] for x in rows])
    J = np.array([idx[x["b"]] for x in rows])
    W = np.array([x["w"] for x in rows], dtype=float)
    N = np.array([x["n"] for x in rows], dtype=float)
    for _ in range(iters):
        q = 1.0 / (1.0 + np.exp(-(r[I] - r[J])))
        g = (W - N * q)
        gr = np.zeros(k)
        np.add.at(gr, I, g)
        np.add.at(gr, J, -g)
        r += lr * gr / max(1.0, N.sum())
        r -= r.mean()
    return r


def fit_melo2(rows, names, lr: float = 0.05, iters: int = 4000, seed: int = 0):
    """mElo₂ = Elo ＋ 2 次元の巡回成分。logit p_ij = r_i − r_j + c_i1·c_j2 − c_i2·c_j1。

    2 番目の項は**反対称**なので、じゃんけんのような循環だけを表す。
    Elo（1 次元）では表せない相性を、いちばん小さい追加で拾う形である。
    """
    idx = {n: i for i, n in enumerate(names)}
    k = len(names)
    rng = np.random.default_rng(seed)
    r = np.zeros(k)
    C = 0.1 * rng.standard_normal((k, 2))
    I = np.array([idx[x["a"]] for x in rows])
    J = np.array([idx[x["b"]] for x in rows])
    W = np.array([x["w"] for x in rows], dtype=float)
    N = np.array([x["n"] for x in rows], dtype=float)
    scale = max(1.0, N.sum())
    for _ in range(iters):
        cyc = C[I, 0] * C[J, 1] - C[I, 1] * C[J, 0]
        q = 1.0 / (1.0 + np.exp(-(r[I] - r[J] + cyc)))
        g = (W - N * q)
        gr = np.zeros(k)
        np.add.at(gr, I, g)
        np.add.at(gr, J, -g)
        gC = np.zeros((k, 2))
        np.add.at(gC, I, np.stack([g * C[J, 1], -g * C[J, 0]], axis=1))
        np.add.at(gC, J, np.stack([-g * C[I, 1], g * C[I, 0]], axis=1))
        r += lr * gr / scale
        C += lr * gC / scale
        r -= r.mean()
    return r, C


def compare_elo_melo2(rec: dict, names, splits: int = 20, lr: float = 0.05,
                      iters: int = 4000) -> dict:
    """学習用で当て、**検証用**の対数損失で Elo と mElo₂ を比べる（過学習よけ・§7 の 5）。

    割り方の乱数を `splits` 回変えて、差の平均と 95% 区間（差の標準誤差の 1.96 倍）を出す。
    """
    d_elo, d_melo, diffs = [], [], []
    for s in range(splits):
        tr, va = split_pairs(rec, seed=s)
        r = fit_elo(tr, names, lr, iters)
        rm, C = fit_melo2(tr, names, lr, iters, seed=s)
        le = _logloss(va, names, lambda i, j: 1 / (1 + math.exp(-(r[i] - r[j]))))
        lm = _logloss(va, names, lambda i, j: 1 / (1 + math.exp(
            -(rm[i] - rm[j] + C[i, 0] * C[j, 1] - C[i, 1] * C[j, 0]))))
        d_elo.append(le)
        d_melo.append(lm)
        diffs.append(le - lm)
    d = np.array(diffs)
    se = float(d.std(ddof=1) / math.sqrt(len(d))) if len(d) > 1 else float("nan")
    return {"splits": splits, "lr": lr, "iters": iters,
            "elo_valid_logloss": float(np.mean(d_elo)),
            "melo2_valid_logloss": float(np.mean(d_melo)),
            "diff_elo_minus_melo2": float(d.mean()),
            "diff_se": se, "diff_lo": float(d.mean() - 1.96 * se),
            "diff_hi": float(d.mean() + 1.96 * se),
            "coinflip_logloss": math.log(2.0)}


# ============================================================ 先手の利
def seat_advantage(paths) -> dict:
    """席（先攻／後攻）による勝率の偏り。**席が分かる記録**からだけ出す。

    ラダーの組の記録には席別の勝敗が入っていない（本便で `ladder.py` に足したので、
    次にラダーを回したときから入る）。いまは `results/vb/d065_null_lit_a.json` の
    対照 1,200 局——同じ AI どうしの対戦——を使う。`gate` は各シードの
    「A から見た勝敗」の並びで、席は**シードの偶奇**（偶数なら A が席 0）である。
    """
    out = {"sources": [], "seat0_wins": 0, "decided": 0}
    for path in paths:
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))
        g = d.get("gate")
        if not isinstance(g, list) or not g:
            continue
        seed0 = int(d.get("seed0", 0))
        w = n = 0
        for i, v in enumerate(g):
            if v is None:
                continue
            a_seat = (seed0 + i) % 2          # 奇数シードなら A は席 1
            seat0_won = (v if a_seat == 0 else (not v))
            w += 1 if seat0_won else 0
            n += 1
        out["sources"].append({"file": os.path.basename(path), "seed0": seed0,
                               "n": n, "seat0_wins": w,
                               "base": d.get("base"), "cand": d.get("cand")})
        out["seat0_wins"] += w
        out["decided"] += n
    n, w = out["decided"], out["seat0_wins"]
    if n:
        p = w / n
        out["p_seat0"] = p
        out["ci"] = 1.96 * math.sqrt(p * (1 - p) / n)
        out["lo"], out["hi"] = p - out["ci"], p + out["ci"]
        # BayesElo の eloAdvantage 相当（先手であることの Elo 換算）
        pc = min(1 - 1e-9, max(1e-9, p))
        out["elo_advantage"] = 400.0 * math.log10(pc / (1 - pc))
    return out


# ============================================================ まとめ
def analyse(rec: dict, seed: int = 0, iters: int = 20000, restarts: int = 8,
            splits: int = 20, champion_name: str | None = None) -> dict:
    names, P, N = matrices(rec)
    A = logit_matrix(P, N)
    nash = maxent_nash(A, iters=iters, restarts=restarts, seed=seed)
    ref = refine_maxent_scipy(A, nash["p"])
    # 既定の解法（regret matching＋）は反復法なので 1e-3 くらいの誤差が残る。
    # scipy があれば凸最適化で解き直し、**均衡であること（可搾取量 ≈ 0）と
    # エントロピーが下がっていないこと**を確かめたうえで、そちらを報告値に採る。
    # scipy が無い環境では regret matching＋の答えをそのまま使う（結論は変わらない）。
    source = "rm_plus_multistart"
    p = nash["p"]
    if ref is not None and ref["exploitability"] <= 1e-6 \
            and ref["entropy"] >= nash["entropy"] - 1e-6:
        p, source = ref["p"], "scipy_maxent(refined from rm_plus)"
    nA = nash_scores(A, p)
    # 便 M（D-076）: **記録の欄の champion** と **いまの champion** を分ける。
    # 記録は交代前に回されていることがある（v9 の欄は `planner_vb3cps`）。D-034 の改訂で
    # 「Nash の台に乗り nA ≥ 0」を交代の条件にする以上、判定は**いまの champion**で行う。
    rec_champ = rec.get("champion")
    champ = champion_name if champion_name is not None else rec_champ
    support = [names[i] for i in range(len(names)) if p[i] > SUPPORT_TOL]
    cyc = {f"{t:.2f}": count_cycles(names, P, t) for t in TAUS}
    out = {
        "run_id": rec.get("run_id"), "gauntlet": rec.get("gauntlet"),
        "gauntlet_version": rec.get("gauntlet_version"), "date": rec.get("date"),
        "n_agents": len(names), "agents": names,
        "champion": champ,                 # いまの champion（--champion。既定は champion.py 由来）
        "record_champion": rec_champ,      # ラダーの記録の欄（回した当時の champion）
        "champion_source": ("argument" if champion_name is not None else "record"),
        "nash": {
            "weights": {n: float(x) for n, x in zip(names, p)},
            "support": support, "support_size": len(support),
            "support_tol": SUPPORT_TOL,
            "nA": {n: float(x) for n, x in zip(names, nA)},
            "exploitability": float(np.max(nA)),
            "spread_across_restarts": nash["spread_across_restarts"],
            "entropy": float(-np.sum(p[p > 0] * np.log(p[p > 0]))),
            "iters": nash["iters"],
            "restarts": nash["restarts"], "solver": source,
            "rm_weights": {n: float(x) for n, x in zip(names, nash["p"])},
            "rm_exploitability": nash["exploitability"],
            "rm_entropy": nash["entropy"],
        },
        "nash_refined_scipy": (None if ref is None else
                               {"weights": {n: float(x) for n, x in zip(names, ref["p"])},
                                "entropy": ref["entropy"],
                                "exploitability": ref["exploitability"],
                                "max_abs_diff_vs_rm": ref["max_abs_diff_vs_rm"],
                                "ok": ref["ok"], "message": ref["message"]}),
        "champion_in_support": bool(champ in support) if champ else None,
        "champion_nA": (float(nA[names.index(champ)]) if champ in names else None),
        "champion_in_ladder": bool(champ in names) if champ else None,
        "record_champion_in_support": bool(rec_champ in support) if rec_champ else None,
        "record_champion_nA": (float(nA[names.index(rec_champ)])
                               if rec_champ in names else None),
        "effective_diversity": effective_diversity(A, p),
        "effective_diversity_formula": "Σ_ij p*_i p*_j max(A_ij, 0)  (A_ij = logit p_ij)",
        "cycles_by_tau": {k: {"count": len(v), "cycles": v} for k, v in cyc.items()},
        "cycles_significant_rating_py": rec.get("cycles"),
        "elo_vs_melo2": compare_elo_melo2(rec, names, splits=splits),
        "elo": rec.get("ratings"),
        "analysed_at": datetime.now(JST).isoformat(timespec="seconds"),
    }
    return out


def render(out: dict, seat: dict | None) -> str:
    L = []
    v = out.get("gauntlet_version")
    L.append(f"# ラダー解析 {out.get('gauntlet')} v{v}（D-5・便 D 後半）")
    L.append("")
    L.append(f"対象: `{out.get('run_id')}`（{out.get('date','')[:19]}）／"
             f"{out['n_agents']} 体／champion = `{out.get('champion')}`"
             f"（{'--champion で指定' if out.get('champion_source') == 'argument' else '記録の欄'}）")
    if out.get("record_champion") != out.get("champion"):
        L.append("")
        L.append(f"※ **ラダーの記録の欄の champion は `{out.get('record_champion')}`** である"
                 "（この記録は交代前に回した）。以下の結論は**いまの champion**について書く。"
                 "記録の欄の体については §1 の表と `record_champion_*` を見ること。")
    L.append("")
    L.append("## 0. 結論（先に）")
    L.append("")
    ns = out["nash"]
    L.append(f"- **均衡ウェイトの台のサイズ = {ns['support_size']} 体**"
             f"（{', '.join('`' + s + '`' for s in ns['support'])}）")
    if out.get("champion") is None:
        L.append("- champion の名前が分からない（記録の欄も `--champion` も空）ので、"
                 "台に乗っているかは判定しない")
    elif not out.get("champion_in_ladder", out["champion_nA"] is not None):
        L.append(f"- **champion `{out.get('champion')}` はこのラダーに載っていない**"
                 "（この世代の顔ぶれに入っていないので、台に乗っているかは**この記録では判定できない**）")
    else:
        L.append(f"- **champion `{out.get('champion')}` は台に"
                 f"{'乗っている' if out['champion_in_support'] else '**乗っていない**'}**"
                 f"／nA = {out['champion_nA']:+.4f}"
                 f"（0 に近いほど「均衡の相手に互角以上」）")
    if out.get("record_champion") and out.get("record_champion") != out.get("champion"):
        rn = out.get("record_champion_nA")
        L.append(f"- 参考（記録の欄の champion `{out['record_champion']}`）: 台に"
                 f"{'乗っている' if out.get('record_champion_in_support') else '**乗っていない**'}"
                 + ("" if rn is None else f"／nA = {rn:+.4f}"))
    L.append(f"- **有効多様性 = {out['effective_diversity']:.4f}**"
             f"（0 なら 1 本の物差しで説明できる）")
    e = out["elo_vs_melo2"]
    # 「区間が 0 をまたがないか（差があると言えるか）」と「差が実用上どれだけ大きいか」は別。
    # 0.005 は当てずっぽう（0.693）と実測（≈0.48）の隔たりの約 2% にあたり、
    # ここを下回る差は「1 次元では表せない」と言うには小さすぎると見なす。
    if e["diff_lo"] > 0:
        better = ("mElo₂ の方が良い" if e["diff_elo_minus_melo2"] >= 0.005 else
                  "mElo₂ の方がわずかに良いが、差は実用上ほぼ無い"
                  "（0 をまたがないだけで、大きさは 0.005 未満）")
    elif e["diff_hi"] < 0:
        better = "Elo の方が良い"
    else:
        better = "差があるとは言い切れない（区間が 0 をまたぐ）"
    L.append(f"- **当てはまり: Elo {e['elo_valid_logloss']:.4f} 対 "
             f"mElo₂ {e['melo2_valid_logloss']:.4f}（検証用の対数損失。低いほど良い。"
             f"当てずっぽうは {e['coinflip_logloss']:.4f}）→ {better}"
             f"（差 {e['diff_elo_minus_melo2']:+.4f} "
             f"[{e['diff_lo']:+.4f}, {e['diff_hi']:+.4f}]）**")
    for t, c in out["cycles_by_tau"].items():
        L.append(f"- 3 巡回（勝率 {t} 以上を辺とする）: **{c['count']} 組**")
    if seat and seat.get("decided"):
        L.append(f"- **先手（席 0）の勝率 = {seat['p_seat0']:.3f} ±{seat['ci']:.3f}"
                 f"（n={seat['decided']}）／Elo 換算 {seat['elo_advantage']:+.1f}**")
    L.append("")
    L.append("## 1. Nash averaging（均衡ウェイト）")
    L.append("")
    L.append("「どの相手をどれだけ重く見て評価するか」を、勝敗のロジットを利得とする")
    L.append("対称ゼロ和ゲームの最大エントロピー Nash 均衡として決める。")
    L.append("ウェイトが 0 でない体の集合を**台**という。台に乗らない体は")
    L.append("「均衡の相手に対して勝ち越せない＝評価の物差しとして働かない」体である。")
    L.append("")
    L.append("| 体 | 均衡ウェイト p* | nA（均衡相手への平均ロジット） | Elo |")
    L.append("|---|---:|---:|---:|")
    elo = out.get("elo") or {}
    order = sorted(out["agents"], key=lambda n: -ns["weights"][n])
    for n in order:
        er = elo.get(n) or {}
        es = (f"{er['elo']:.0f} [{er['lo']:.0f}, {er['hi']:.0f}]"
              if er else "—")
        L.append(f"| `{n}` | {ns['weights'][n]:.4f} | {ns['nA'][n]:+.4f} | {es} |")
    L.append("")
    L.append(f"解法: {ns['solver']}（{ns['restarts']} 通りの初期値 × {ns['iters']} 反復の"
             f"平均戦略をさらに平均）。可搾取量 {ns['exploitability']:+.2e}"
             f"（0 なら均衡）、初期値によるばらつき {ns['spread_across_restarts']:.2e}。")
    r = out.get("nash_refined_scipy")
    if r:
        L.append(f"scipy による最大エントロピーの解き直し: エントロピー "
                 f"{r['entropy']:.4f}（既定の解は {ns['entropy']:.4f}）、"
                 f"ウェイトの最大差 {r['max_abs_diff_vs_rm']:.2e}、"
                 f"可搾取量 {r['exploitability']:+.2e}。")
    else:
        L.append("scipy が無いので照合は省略した（既定の解法だけで完結する）。")
    L.append("")
    if out["nash"]["support_size"] <= 2:
        L.append("**台が小さいことの読み方（注意）**: 台が 1〜2 体ということは、"
                 f"「この {out['n_agents']} 体の中では、強さが 1 本の順序で並んでいる」"
                 "という意味である。"
                 "ただしこのラダーの顔ぶれは **champion とその祖先**が大半で、"
                 "相性の噛み合い（じゃんけん）を作るために選ばれた体ではない。"
                 "したがって「このゲームに非推移性が無い」ではなく、"
                 f"**「いま並べている {out['n_agents']} 体の中には無い」**と読むのが正しい。")
        L.append("")
    L.append("## 2. 3 巡回（非推移性）")
    L.append("")
    L.append("「A が B に勝ち、B が C に勝ち、C が A に勝つ」組を数える。")
    L.append("辺の閾値 τ は「勝率 τ 以上なら勝ち越しと見なす」線である。")
    L.append("AlphaStar の論文は τ=0.7 を使うが、13 体級では厳しすぎるので 0.6 を主に見る。")
    L.append("")
    for t, c in out["cycles_by_tau"].items():
        L.append(f"- **τ = {t}: {c['count']} 組**"
                 + ("" if not c["cycles"] else
                    "　" + " ／ ".join("→".join(x) for x in c["cycles"][:6])
                    + ("　…" if len(c["cycles"]) > 6 else "")))
    sig = out.get("cycles_significant_rating_py")
    L.append("")
    L.append(f"参考: `rating.find_cycles`（閾値ではなく**勝率の 95% 下端 > 0.5** を辺とする"
             f"別定義）では {len(sig or [])} 組。定義が違うので数が合わなくてよい。")
    L.append("")
    L.append("## 3. Elo と mElo₂ の当てはまり")
    L.append("")
    L.append("各組の決着局を半々に割り、片方（学習用）でモデルを当て、")
    L.append("もう片方（検証用）でどれだけ当たったかを対数損失で測る。")
    L.append("学習用で比べると複雑なモデルが必ず勝ってしまうので、**検証用で比べる**。")
    L.append("")
    L.append(f"- Elo（1 次元）　　  検証用の対数損失 **{e['elo_valid_logloss']:.4f}**")
    L.append(f"- mElo₂（Elo＋2 次元の巡回成分） **{e['melo2_valid_logloss']:.4f}**")
    L.append(f"- 差（Elo − mElo₂）**{e['diff_elo_minus_melo2']:+.4f}** "
             f"[{e['diff_lo']:+.4f}, {e['diff_hi']:+.4f}]"
             f"（割り方を {e['splits']} 通り変えたときのばらつきから）")
    L.append(f"- 学習率 {e['lr']}／反復 {e['iters']}／当てずっぽうの対数損失 "
             f"{e['coinflip_logloss']:.4f}")
    L.append("")
    L.append(f"読み: **{better}**。")
    L.append("区間が 0 をまたがないことは「差がある」を意味するだけで、")
    L.append("「その差が判断を変えるほど大きい」は意味しない。両方を見ること。")
    L.append("")
    L.append("## 4. 有効多様性")
    L.append("")
    L.append(f"定義: `{out['effective_diversity_formula']}`（第 2 集 §5.2.1）。")
    L.append("均衡ウェイトで 2 体を引いたとき、相性で得をする側の期待ロジット幅である。")
    L.append(f"値 = **{out['effective_diversity']:.4f}**。")
    L.append("")
    if seat and seat.get("decided"):
        L.append("## 5. 先手の利")
        L.append("")
        L.append("ラダーの組の記録には席別の勝敗が無いので、**席が分かる対局**から出す。")
        for s in seat["sources"]:
            L.append(f"- `{s['file']}` 帯 {s['seed0']}.. n={s['n']}／席 0 の勝ち {s['seat0_wins']}")
        L.append(f"- 合計: 席 0（先攻）の勝率 **{seat['p_seat0']:.3f} ±{seat['ci']:.3f}**"
                 f"（95% 区間 [{seat['lo']:.3f}, {seat['hi']:.3f}]・n={seat['decided']}）")
        L.append(f"- Elo 換算の先手の利: **{seat['elo_advantage']:+.1f}**")
        L.append("")
    L.append(f"（解析日時 {out['analysed_at']}。対局は 1 局も回していない）")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ladder", default=os.path.join(_HERE, "..", "results", "ladder.json"))
    ap.add_argument("--index", type=int, default=-1, help="記録の何番目か（既定は最新）")
    ap.add_argument("--out-prefix", default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--iters", type=int, default=20000)
    ap.add_argument("--restarts", type=int, default=8)
    ap.add_argument("--splits", type=int, default=20)
    ap.add_argument("--null", nargs="*", default=None,
                    help="席の分かる対局の記録（先手の利。既定は d065_null_lit_a.json）")
    ap.add_argument("--champion", default=None,
                    help="判定に使う champion の名前（既定は `champion.py` の現 champion）。"
                         "`record` と書くとラダーの記録の欄をそのまま使う（旧来の挙動）")
    args = ap.parse_args(argv)

    recs = json.load(open(args.ladder, encoding="utf-8"))
    rec = recs[args.index]
    if args.champion == "record":
        champ_name = None
    elif args.champion:
        champ_name = args.champion
    else:
        import champion as chmod
        champ_name = chmod.name_for(rec.get("deck") or "SD001",
                                    gauntlet=rec.get("gauntlet") or "core5")
    out = analyse(rec, seed=args.seed, iters=args.iters, restarts=args.restarts,
                  splits=args.splits, champion_name=champ_name)
    nulls = args.null if args.null is not None else [
        os.path.join(_HERE, "..", "results", "vb", "d065_null_lit_a.json")]
    seat = seat_advantage(nulls)
    out["seat_advantage"] = seat

    prefix = args.out_prefix or os.path.join(
        _HERE, "..", "results",
        f"ladder_analysis_{rec.get('gauntlet')}_v{rec.get('gauntlet_version')}")
    os.makedirs(os.path.dirname(os.path.abspath(prefix)) or ".", exist_ok=True)
    with open(prefix + ".json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    md = render(out, seat)
    with open(prefix + ".md", "w", encoding="utf-8") as f:
        f.write(md + "\n")
    print(md)
    print()
    print(f"→ {prefix}.json / {prefix}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
