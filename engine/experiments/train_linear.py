"""C-1 §4.1-2 線形／ロジスティック回帰で CEM の到達点を超えるか（D-038）。

rules_draft.md v0.10 準拠 / engine v0.1。データは D-037（`c1_v1`）。

## 何を比べるか

引継ぎ書 §4.1-2 の問い「CEM の到達点を超えるか。超えないなら特徴が足りない証拠」に
答えるには、**現行 `evaluate` を予測器として同じ土俵に載せる**必要がある。

現行 `evaluate` は `TUNED_WEIGHTS`（A-3 の CEM で結合最適化した6重み）による
特徴の線形結合である。その素点は勝敗確率ではないので、
**尺度と切片の2つだけを train で当てて** `p = σ(a·score + b)` に較正する。
重みは CEM のまま動かさない。これが「CEM の到達点」の予測器としての姿である。

比べる相手:

| 名前 | 自由度 | 意味 |
|---|---|---|
| `const` | 0 | 常に 0.5。下限の基準 |
| `cem_calibrated` | 2 | **CEM の6重みを固定**し尺度と切片だけ当てる ← 超えるべき相手 |
| `logit6` | 7 | 同じ6特徴で重みも当て直す。「CEM の重みは予測として最適か」 |
| `logit22` | 23 | 22特徴（D-037）。「特徴を増やすと予測は良くなるか」 |
| `logit22x` | 23+ | 22特徴＋主要な交互作用。「非線形性は本当に要るか」の安価な先行検査 |

## 統計の作法（作業規約6）

**行は独立ではない。** 同一対局から採った局面は強く相関し、さらに同一ターンの
2行は互いに鏡像でラベルが相補である。したがって素の n=8434 で信頼区間を作ると
狭すぎる。**対局を単位にしたブートストラップ**（対局ごと復元抽出、B=1000、固定シード）
で、モデル間の logloss 差の 95% 区間を出す。

正則化の強さ λ は **train の内部で対局単位に分けた交差検証**で選ぶ。
valid を見て選ぶと valid が in-sample になる（D-028 の精神）。

## 学習の実装

ロジスティック回帰は IRLS（Newton 法）で解く。23 パラメータなので
1回の反復が 23×23 の連立方程式であり、8 反復で収束する。
勾配降下と違って学習率も反復数も選ばなくてよく、**完全に決定的**である。

実行: python3 experiments/train_linear.py
"""
from __future__ import annotations

import gzip
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np                                              # noqa: E402

from meicho import features as F                                # noqa: E402
from meicho.version import ENGINE_VERSION, RULES_VERSION         # noqa: E402  D-117
import gendata                                                  # noqa: E402
from meicho.planner import TUNED_WEIGHTS                        # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(_HERE, "..", "results", "datasets")
MODELS = os.path.join(_HERE, "..", "results", "models")

BOOT = 1000          # ブートストラップの反復数
BOOT_SEED = 20260824
CV_FOLDS = 5


# ------------------------------------------------------------------ 読み込み
def load(split: str):
    """(X, y, game_id) を返す。game_id は対局単位のブートストラップに使う。"""
    X, y, g = [], [], []
    path = os.path.join(DATA, f"c1_v1_{split}.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            X.append(F.from_obs(r["obs"]))
            y.append(r["z"])
            g.append(r["seed"])          # シード = 対局の識別子
    return np.array(X), np.array(y), np.array(g)


# ------------------------------------------------------ 現行 evaluate の再現
def _idx(name):
    return F.FEATURE_NAMES.index(name)


def cem_score(X):
    """`greedy.evaluate` + `TUNED_WEIGHTS` を特徴行列から再現する。

    現行の6項はすべて 22 特徴の線形結合で書ける（`resource` は
    デッキとトラッシュの差の和）。よってこれは**新しいモデルではなく、
    現行評価関数そのもの**である。値が一致することを
    `test_cem_score_matches_evaluate` で確かめている。
    """
    w = TUNED_WEIGHTS
    return (w.life * X[:, _idx("life_diff")]
            + w.concerto * X[:, _idx("concerto_diff")]
            + w.hand * X[:, _idx("hand_diff")]
            + w.live_red * X[:, _idx("live_reds")]
            + w.level * X[:, _idx("level_diff")]
            + w.resource * ((X[:, _idx("deck_me")] + X[:, _idx("trash_me")])
                            - (X[:, _idx("deck_opp")] + X[:, _idx("trash_opp")])))


SIX = ("life_diff", "concerto_diff", "hand_diff", "live_reds", "level_diff")

# 交互作用の候補（引継ぎ書 §1 の仮説「ライフ差の価値は協奏の枚数に依存する」ほか）。
# 全対を入れると 231 項になり本題（特徴が足りているか）がぼやけるので、
# 動機のある組み合わせだけを見る。
INTERACTIONS = (
    ("life_diff", "concerto_me"),      # 優勢の価値は土台の厚さで変わるか
    ("life_diff", "turn_no"),          # 終盤ほどライフ差が効くか
    ("hand_diff", "concerto_me"),      # 手札の価値はコストを払えるかで変わるか
    ("live_reds", "concerto_me"),      # 赤の使用条件は協奏枚数そのもの
    ("life_diff", "life_me"),          # 絶対値との相互作用（残ライフの少なさ）
)


# ------------------------------------------------------------------ 学習
def _design(X, cols=None, inter=()):
    """設計行列を作る（選んだ列＋交互作用＋定数項）。"""
    parts = [X[:, [_idx(c) for c in cols]]] if cols else [X]
    for a, b in inter:
        parts.append((X[:, _idx(a)] * X[:, _idx(b)])[:, None])
    Z = np.hstack(parts)
    return Z


def _standardise(Z, mu=None, sd=None):
    if mu is None:
        mu, sd = Z.mean(0), Z.std(0)
        sd = np.where(sd > 1e-12, sd, 1.0)
    return (Z - mu) / sd, mu, sd


def irls(Z, y, lam, iters=25, tol=1e-10):
    """L2 正則化ロジスティック回帰を Newton 法で解く（定数項は正則化しない）。

    学習率も反復数も選ばなくてよく、完全に決定的である。
    """
    n, d = Z.shape
    A = np.hstack([Z, np.ones((n, 1))])
    w = np.zeros(d + 1)
    pen = np.ones(d + 1) * lam
    pen[-1] = 0.0                        # 定数項は罰しない
    for _ in range(iters):
        eta = A @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        W = np.clip(p * (1 - p), 1e-9, None)
        grad = A.T @ (y - p) - pen * w
        H = (A * W[:, None]).T @ A + np.diag(pen)
        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            # 特徴が線形従属だと λ=0 でヘッセ行列が特異になる（下の注記参照）。
            # 最小ノルム解に落として続行する。
            step = np.linalg.lstsq(H, grad, rcond=None)[0]
        w = w + step
        if np.max(np.abs(step)) < tol:
            break
    return w


def predict(Z, w):
    A = np.hstack([Z, np.ones((len(Z), 1))])
    return 1.0 / (1.0 + np.exp(-np.clip(A @ w, -30, 30)))


def logloss(p, y):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ------------------------------------------------------------------ λ の選択
def choose_lambda(Ztr, ytr, gtr, grid):
    """train の内部で**対局単位に**分けた交差検証で λ を選ぶ。

    行単位で分けると、同一対局の相関で楽観的になる（同じターンの鏡像行が
    train と検証の両方に入りうる）。
    """
    games = np.unique(gtr)
    fold = {g: i % CV_FOLDS for i, g in enumerate(sorted(games))}
    fid = np.array([fold[g] for g in gtr])
    out = {}
    for lam in grid:
        tot = 0.0
        for k in range(CV_FOLDS):
            tr, va = fid != k, fid == k
            Zs, mu, sd = _standardise(Ztr[tr])
            w = irls(Zs, ytr[tr], lam)
            tot += logloss(predict((Ztr[va] - mu) / sd, w), ytr[va]).mean()
        out[lam] = tot / CV_FOLDS
    best = min(out, key=out.get)
    return best, out


# ------------------------------------------------------------------ 評価
class Model:
    def __init__(self, name, p_tr, p_va):
        self.name, self.p_tr, self.p_va = name, p_tr, p_va


def boot_ci(loss_a, loss_b, games, b=BOOT, seed=BOOT_SEED):
    """対局単位のブートストラップで logloss 差 (a-b) の 95% 区間を出す。

    行は独立ではない（同一対局の局面は相関し、同一ターンの2行は鏡像である）。
    対局ごと復元抽出することでその構造を壊さずに区間を作る。
    """
    uniq, inv = np.unique(games, return_inverse=True)
    # 対局ごとの合計と件数を先に畳んでおく（毎回の抽出を O(対局数) にする）
    sa = np.bincount(inv, weights=loss_a, minlength=len(uniq))
    sb = np.bincount(inv, weights=loss_b, minlength=len(uniq))
    cnt = np.bincount(inv, minlength=len(uniq)).astype(float)
    rng = np.random.default_rng(seed)
    diffs = np.empty(b)
    for i in range(b):
        pick = rng.integers(0, len(uniq), len(uniq))
        n = cnt[pick].sum()
        diffs[i] = (sa[pick].sum() - sb[pick].sum()) / n
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


def main():
    t0 = time.perf_counter()
    print("== C-1 §4.1-2 線形／ロジスティック回帰 ==")
    man = json.load(open(os.path.join(DATA, "c1_v1_train.manifest.json"),
                         encoding="utf-8"))
    assert man["def_hash"] == gendata.def_hash(gendata.load_def("c1_v1")), \
        "データセットの定義が変わっている。作り直すこと"
    Xtr, ytr, gtr = load("train")
    Xva, yva, gva = load("valid")
    print(f"train {Xtr.shape} / {len(np.unique(gtr))} 局  "
          f"valid {Xva.shape} / {len(np.unique(gva))} 局")
    rank = np.linalg.matrix_rank(np.hstack([Xtr, np.ones((len(Xtr), 1))]))
    print(f"設計行列の階数: {rank} / {Xtr.shape[1] + 1} 列"
          f"（差分と素の値が線形従属。線形モデルの自由度は実質 {rank}）")
    print(f"データ def_hash {man['def_hash']} / 帯 train {man['seed_band']}..\n")

    models, saved = [], {}

    # --- 0. 常に 0.5 -------------------------------------------------------
    models.append(Model("const", np.full(len(ytr), 0.5), np.full(len(yva), 0.5)))

    # --- 1. CEM を較正しただけのもの（超えるべき相手）----------------------
    str_tr, str_va = cem_score(Xtr)[:, None], cem_score(Xva)[:, None]
    Zs, mu, sd = _standardise(str_tr)
    w_cem = irls(Zs, ytr, lam=0.0)
    models.append(Model("cem_calibrated", predict(Zs, w_cem),
                        predict((str_va - mu) / sd, w_cem)))
    print(f"cem_calibrated: p = σ({w_cem[0] / sd[0]:.4f}·evaluate + "
          f"{w_cem[1] - w_cem[0] * mu[0] / sd[0]:.4f})")

    # --- 2〜4. ロジスティック回帰 ------------------------------------------
    # **λ=0 は使わない。** 22特徴には厳密な線形従属が含まれるためである
    # （life_diff = life_me - life_opp、concerto_gap = concerto_me - 4 など）。
    # 差分と素の値を両方持たせたのは意図どおりだが、**線形モデルにとっては
    # 素の値は差分の情報を1ビットも増やさない**。効くとすれば交互作用を通してのみ。
    # これは §4.1-3（MLP）に進むかどうかの判断に直結する事実である。
    grid = [0.1, 1.0, 10.0, 100.0, 1000.0]
    specs = [("logit6", SIX + ("turn_no",), ()),
             ("logit22", None, ()),
             ("logit22x", None, INTERACTIONS)]
    for name, cols, inter in specs:
        Ztr, Zva = _design(Xtr, cols, inter), _design(Xva, cols, inter)
        lam, curve = choose_lambda(Ztr, ytr, gtr, grid)
        Zs, mu, sd = _standardise(Ztr)
        w = irls(Zs, ytr, lam)
        models.append(Model(name, predict(Zs, w), predict((Zva - mu) / sd, w)))
        print(f"{name}: λ={lam:g} (CV: " +
              " ".join(f"{k:g}={v:.4f}" for k, v in curve.items()) + ")")
        saved[name] = {"w": w.tolist(), "mu": mu.tolist(), "sd": sd.tolist(),
                       "lam": lam, "cols": list(cols) if cols else
                       list(F.FEATURE_NAMES),
                       "interactions": [list(p) for p in inter]}

    # --- 結果 --------------------------------------------------------------
    print("\n== 予測性能（logloss は低いほど良い） ==")
    print(f"{'モデル':<16}{'train ll':>10}{'valid ll':>10}{'valid acc':>11}"
          f"   vs cem_calibrated の差 [95%]")
    base = next(m for m in models if m.name == "cem_calibrated")
    lbase = logloss(base.p_va, yva)
    rows = []
    for m in models:
        lva = logloss(m.p_va, yva)
        acc = ((m.p_va > 0.5) == (yva > 0.5)).mean()
        if m.name == "cem_calibrated":
            tail = "—（基準）"
        else:
            lo, hi = boot_ci(lva, lbase, gva)
            d = lva.mean() - lbase.mean()
            sig = "有意" if hi < 0 or lo > 0 else "有意でない"
            tail = f"{d:+.4f} [{lo:+.4f}, {hi:+.4f}] {sig}"
        print(f"{m.name:<16}{logloss(m.p_tr, ytr).mean():>10.4f}"
              f"{lva.mean():>10.4f}{acc:>11.4f}   {tail}")
        rows.append({"name": m.name, "train_logloss": float(logloss(m.p_tr, ytr).mean()),
                     "valid_logloss": float(lva.mean()), "valid_acc": float(acc)})

    # --- 追加の対比: 交互作用は本当に要るか（§4.1-3 に進むかの判断材料）-----
    print("\n== 追加の対比（logloss 差・対局単位ブートストラップ 95%）==")
    def cmp(a, b):
        ma = next(m for m in models if m.name == a)
        mb = next(m for m in models if m.name == b)
        la, lb = logloss(ma.p_va, yva), logloss(mb.p_va, yva)
        lo, hi = boot_ci(la, lb, gva)
        d = la.mean() - lb.mean()
        sig = "有意" if hi < 0 or lo > 0 else "**有意でない**"
        print(f"  {a} − {b}: {d:+.4f} [{lo:+.4f}, {hi:+.4f}] {sig}")
        return d, lo, hi
    cmp("logit22", "logit6")
    inter_gain = cmp("logit22x", "logit22")

    # --- 採用モデルの係数 --------------------------------------------------
    best = "logit22"
    d = saved[best]
    print(f"\n== {best} の係数（標準化後・絶対値順）==")
    order = np.argsort(-np.abs(np.array(d["w"][:-1])))
    for i in order:
        print(f"  {d['cols'][i]:<18}{d['w'][i]:+.4f}")

    os.makedirs(MODELS, exist_ok=True)
    # 全変種を保存する。**予測での優劣が強さでの優劣に翻訳されるとは限らない**ので、
    # 強さの測定は複数の変種で行えるようにしておく（D-038 の診断はここから出た）。
    for nm, dd in saved.items():
        with open(os.path.join(MODELS, f"c1_{nm}.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"kind": "logistic", "model": nm,
                       "feature_names": list(F.FEATURE_NAMES),
                       "cols": dd["cols"], "interactions": dd["interactions"],
                       "w": dd["w"], "mu": dd["mu"], "sd": dd["sd"],
                       "lam": dd["lam"], "dataset": "c1_v1",
                       "def_hash": man["def_hash"], "rules_version": RULES_VERSION,
                       "engine_version": ENGINE_VERSION}, f,
                      ensure_ascii=False, indent=2)
    out = os.path.join(MODELS, "c1_linear_v1.json")
    payload = {
        "kind": "logistic", "model": best,
        "feature_names": list(F.FEATURE_NAMES),
        "cols": d["cols"], "interactions": d["interactions"],
        "w": d["w"], "mu": d["mu"], "sd": d["sd"], "lam": d["lam"],
        "dataset": "c1_v1", "def_hash": man["def_hash"],
        "rules_version": RULES_VERSION, "engine_version": ENGINE_VERSION,   # D-117
        "boot_seed": BOOT_SEED, "cv_folds": CV_FOLDS,
        "metrics": rows,
        "interaction_gain_vs_logit22": {"delta": inter_gain[0],
                                        "ci95": [inter_gain[1], inter_gain[2]]},
        "note": ("出力は勝率の log-odds。planner は argmax にしか使わないので "
                 "単調変換で足りる。MCTS は [0,1] が要るので σ を通すこと。"),
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nモデルを保存: {out}")
    print(f"所要 {time.perf_counter() - t0:.1f} 秒")
    return payload


if __name__ == "__main__":
    main()
