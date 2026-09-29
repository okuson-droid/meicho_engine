"""段階3 反復 1 の診断の机上の集計（D-144 追記 3・比較書 `GENERALIST_STAGE3_DIAG_COMPARE_20260929.md` §4 の 1）。

    python3 experiments/diag_s3_desk.py --work <伸ばす置き場> --out results/drl/s3_diag_desk.json

対局は回さない。手元の記録（`results/drl/s3_it1_rec/*.xz`）・学習の記録（`results/models/*.meta.json`）・
選択の評価の局ごとの結果（`results/drl/s3_it1_select.json`）だけを読む。**判定に使うのは 2-a と 3-a の規則だけ**で、
ほかは読むための材料である（比較書 §4 の 1: 各項目の判定はその項目の事前の規則だけ）。

出すもの（名前は比較書と各版の節）:

- `coverage`（Cowork 版 1-0）: 検証の記録の決定数をデッキ別・組み合わせの種類別・フェイズ別に数え、局の長さ（ターン）と
  席 0 の勝率を出す
- `fit`（CC 版 §2.1・Cowork 版 2-a）: V_0 と V_1（部品 3 本と束ねたもの）の検証 v_logloss を層ごとに。層は
  フェイズ・ターン帯（≤3／4〜6／7 以上）・自分のデッキ・SK 系のデッキが絡むか・組み合わせの種類。各層の基準は
  「その層の平均勝率を常に言う」ときの対数損失
- `rule_2a`（Cowork 版 2-a の規則）: V_0 も V_1 も基準からの改善が 0.01 未満で、決定数の 10% 以上を占める層があるか
- `teacher`（Cowork 版 3-a・CC 版 §2.2）: 教師（探索値の最大を S5 の較正で勝率に直したもの）と V_0（束ねたもの）の
  対数損失と上乗せ u = L(V_0) − L(教師)。**較正は `s3v1_id_s0.meta.json` の a・b・c をそのまま当てる**（検証の記録で
  合わせ直さない）。規則: u < 0.002 → 「教師が V_0 に情報を足していない」。あわせて層別の u と 10 分位の較正図と、
  順位だけの物差し（AUC・判定には使わない）
- `columns_zero`（CC 版 §4 (i)）: 信念の要約（20 列）・`hand_known`（78 列）・その両方を 0 にしたときの v_logloss の悪化
- `calib`（`--calib`・CC 版 (ii)）: 探索値の較正の効きを、全体と番兵を除いた部分で（段階2 の教師と反復 1 の教師を同じ物差しで比べる）
- `select`（CC 版 §2.3）: 選択の評価の局を、候補のデッキ・席・ターン数（3 等分）ごとに「V_1 だけ勝った／V_0 だけ勝った」で数える

束ねた V は部品のロジットの平均の sigmoid として計算する（`ensemble_net.py` の `mean_logit` と同じ値・検査 M-4）。
"""
from __future__ import annotations

import argparse
import glob
import json
import lzma
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, _HERE)

from meicho.drl_data import read_records                          # noqa: E402
from meicho.drlnet import Net                                     # noqa: E402

TOOL_VERSION = "s3desk-1"
REC_DIR = os.path.join(ROOT, "results", "drl", "s3_it1_rec")
MODELS = os.path.join(ROOT, "results", "models")
PHASE_NAMES = ("setup", "mulligan", "action", "clash", "choice", "rush", "discard", "over")
# 符号化 v6 の末尾（D-124）: v5 の 1,825 列のあとに信念の要約 20 列、そのあとに hand_known 78 列
BELIEF_COLS = (1825, 1845)
HAND_KNOWN_COLS = (1845, 1923)
RULE_2A = {"gain": 0.01, "share": 0.10}
RULE_3A = 0.002
EPS = 1e-7


# ------------------------------------------------------------------ 記録
def extract(split: str, work: str, chunks=None) -> list:
    """`split`（val / train）の xz を `work` に伸ばし、伸ばしたファイルのパスを返す（あれば伸ばし直さない）。"""
    os.makedirs(work, exist_ok=True)
    out = []
    for src in sorted(glob.glob(os.path.join(REC_DIR, f"{split}.c*.xz"))):
        c = int(os.path.basename(src).split(".")[1][1:])
        if chunks is not None and c not in chunks:
            continue
        dst = os.path.join(work, os.path.basename(src)[:-3])
        if not os.path.exists(dst):
            with lzma.open(src) as f, open(dst + ".part", "wb") as g:
                g.write(f.read())
            os.replace(dst + ".part", dst)
        out.append(dst)
    return out


def manifests(split: str, chunks=None) -> list:
    out = []
    for p in sorted(glob.glob(os.path.join(REC_DIR, f"{split}.c*.manifest.json"))):
        c = int(os.path.basename(p).split(".")[1][1:])
        if chunks is None or c in chunks:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def block_table(mans: list) -> list:
    """manifest の小ブロックを (seed0, n, deck_a, deck_b, kind) に。kind は mirror / cross / anchor。"""
    rows = []
    for m in mans:
        for b in m["blocks"]:
            kind = "anchor" if b.get("opponent", "teacher") != "teacher" else ("mirror" if b["mirror"] else "cross")
            rows.append((int(b["seed0"]), int(b["n"]), b["deck_a"], b["deck_b"], kind))
    return sorted(rows)


def is_sk(deck: str) -> bool:
    return "_SK_" in deck


def tags(recs, table: list) -> dict:
    """決定ごとの属性。デッキは席で決まる（席 0 = deck_a・`series` はデッキを席に固定する）。"""
    starts = np.array([r[0] for r in table])
    k = np.searchsorted(starts, recs.seed, side="right") - 1
    if (k < 0).any():
        raise SystemExit("組み合わせ表に無いシードの決定がある")
    ends = np.array([r[0] + r[1] for r in table])
    if (recs.seed >= ends[k]).any():
        raise SystemExit("組み合わせ表に無いシードの決定がある")
    da = np.array([table[i][2] for i in k])
    db = np.array([table[i][3] for i in k])
    own = np.where(recs.pi == 0, da, db)
    opp = np.where(recs.pi == 0, db, da)
    turn = recs.turn.astype(int)
    tband = np.where(turn <= 3, "t<=3", np.where(turn <= 6, "t4-6", "t7+"))
    return {"block": k, "own": own, "opp": opp, "kind": np.array([table[i][4] for i in k]),
            "sk": np.array(["sk" if is_sk(a) or is_sk(b) else "no_sk" for a, b in zip(own, opp)]),
            "phase": np.array([PHASE_NAMES[p] for p in recs.phase]), "tband": tband}


# ------------------------------------------------------------------ ネット
def net_logit(net: Net, obs: np.ndarray, bs: int = 8192) -> np.ndarray:
    """`Net.value_of` のロジットを一括で（f32・Rust と同じ順序）。"""
    out = np.zeros(len(obs), np.float32)
    w, b = net.value
    for s in range(0, len(obs), bs):
        h = obs[s:s + bs].astype(np.float32)
        for tw, tb in net.trunk:
            h = np.maximum(h @ tw.T + tb, 0.0).astype(np.float32)
        out[s:s + bs] = (h @ w.T + b)[:, 0]
    return out


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, np.float64)))


def logloss(p, z) -> float:
    p = np.clip(np.asarray(p, np.float64), EPS, 1 - EPS)
    z = np.asarray(z, np.float64)
    return float(-(z * np.log(p) + (1 - z) * np.log(1 - p)).mean())


def base_logloss(z) -> float:
    return logloss(np.full(len(z), np.mean(z)), z)


# ------------------------------------------------------------------ 集計
def coverage(recs, tg: dict) -> dict:
    out = {"n": int(recs.n)}
    for key in ("own", "kind", "phase", "sk"):
        vals, cnt = np.unique(tg[key], return_counts=True)
        out[f"by_{key}"] = {str(v): int(c) for v, c in zip(vals, cnt)}
    games = {}
    for s, t, pi, z in zip(recs.seed, recs.turn, recs.pi, recs.z):
        g = games.setdefault(int(s), {"turns": 0, "z0": None})
        g["turns"] = max(g["turns"], int(t))
        if pi == 0 and np.isfinite(z):
            g["z0"] = float(z)
    turns = np.array([g["turns"] for g in games.values()])
    z0 = np.array([g["z0"] for g in games.values() if g["z0"] is not None])
    out["games"] = len(games)
    out["turns"] = {"mean": float(turns.mean()), "p10": float(np.percentile(turns, 10)),
                    "p50": float(np.percentile(turns, 50)), "p90": float(np.percentile(turns, 90))}
    # 錨は片側だけ記録するので、教師が席 1 に座った錨の局は席 0 の決定が無く、ここに入らない
    out["seat0_win"] = {"n": int(len(z0)), "rate": float(z0.mean()) if len(z0) else None}
    return out


def fit_slices(z: np.ndarray, preds: dict, tg: dict, keys=("phase", "tband", "own", "sk", "kind")) -> dict:
    out = {"all": {"n": int(len(z)), "base": base_logloss(z),
                   **{k: logloss(p, z) for k, p in preds.items()}}}
    for key in keys:
        for v in sorted(set(tg[key].tolist())):
            m = tg[key] == v
            out[f"{key}={v}"] = {"n": int(m.sum()), "share": float(m.mean()), "base": base_logloss(z[m]),
                                 **{k: logloss(p[m], z[m]) for k, p in preds.items()}}
    return out


def rule_2a(slices: dict, a: str = "V0", b: str = "V1") -> dict:
    """Cowork 版 2-a: 両方の V が基準から 0.01 未満しか良くならず、決定数の 10% 以上を占める層。"""
    hit = [k for k, s in slices.items() if k != "all" and s["share"] >= RULE_2A["share"]
           and s["base"] - s[a] < RULE_2A["gain"] and s["base"] - s[b] < RULE_2A["gain"]]
    return {"rule": f"両方の改善 < {RULE_2A['gain']} かつ 占有 ≥ {RULE_2A['share']:.0%}", "slices": hit,
            "verdict": "情報欠落の疑いがある層がある（2-b へ）" if hit else "説明できない（項目 3 へ）"}


def apply_calib(v: np.ndarray, calib: dict) -> np.ndarray:
    """層別でない較正（`drl_train.apply_calibration` の全体の較正と同じ式・形 `linear`／`logit` を読む・検査 M-5b・F-4）。

    `drl_train` は torch を読み込むので、torch の無い PC でもこの道具が動くよう式だけをここに置く。
    """
    if calib.get("form", "linear") == "logit":
        w = np.clip(v, 0.001, 0.999)                  # drl_train.LOGIT_CLIP と同じ
        u = np.log(w / (1 - w))
    else:
        u = np.clip(v, -calib["c"], calib["c"]) / calib["c"]
    return 1.0 / (1.0 + np.exp(-(calib["a"] * u + calib["b"])))


def auc(p, z) -> float:
    """順位だけの物差し（勝った決定の予測が負けた決定より高い割合・同順位は半分）。判定には使わない。"""
    p = np.asarray(p, np.float64)
    z = np.asarray(z) > 0.5
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    ps = p[order]
    i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    n1, n0 = int(z.sum()), int((~z).sum())
    return float((ranks[z].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def teacher_p(recs, calib: dict) -> np.ndarray:
    """探索値の最大（`--vtarget max`）を S5 の較正で勝率に。探索していない決定は NaN。"""
    v = np.full(recs.n, np.nan, np.float32)
    for i in range(recs.n):
        sc = recs.scores_of(i)
        fin = np.isfinite(sc)
        if fin.any():
            v[i] = sc[fin].max()
    return apply_calib(v, calib)


def teacher_uplift(z, p_v0, p_t, tg: dict) -> dict:
    ok = np.isfinite(p_t)
    out = {"n": int(ok.sum()), "L_V0": logloss(p_v0[ok], z[ok]), "L_teacher": logloss(p_t[ok], z[ok]),
           "base": base_logloss(z[ok])}
    out["u"] = out["L_V0"] - out["L_teacher"]
    # 順位だけの物差し（添える・判定には使わない）: 較正の形（上位の頭打ち）と、探索値の情報の有無を読み分ける
    out["auc"] = {"V0": auc(p_v0[ok], z[ok]), "teacher": auc(p_t[ok], z[ok])}
    out["rule"] = f"u < {RULE_3A}"
    out["verdict"] = ("教師が V_0 に情報を足していない（項目 3 で説明できる・止めて相談）" if out["u"] < RULE_3A
                      else "説明できない（項目 4 へ）")
    out["by"] = {}
    for key in ("phase", "tband"):
        for v in sorted(set(tg[key][ok].tolist())):
            m = ok & (tg[key] == v)
            out["by"][f"{key}={v}"] = {"n": int(m.sum()), "u": logloss(p_v0[m], z[m]) - logloss(p_t[m], z[m])}
    q = np.quantile(p_t[ok], np.linspace(0, 1, 11))
    k = np.clip(np.searchsorted(q, p_t[ok], side="right") - 1, 0, 9)
    out["deciles"] = [{"pred": float(p_t[ok][k == j].mean()), "actual": float(z[ok][k == j].mean()),
                       "n": int((k == j).sum())} for j in range(10) if (k == j).any()]
    return out


def columns_zero(nets: dict, obs: np.ndarray, z: np.ndarray) -> dict:
    """列を 0 にしたときの v_logloss の悪化（束ねた V・正なら悪化）。学び直さずに当てるだけ。"""
    base = {name: logloss(sigmoid(np.mean([net_logit(n, obs) for n in parts], 0)), z) for name, parts in nets.items()}
    out = {}
    for label, (lo, hi) in (("belief", BELIEF_COLS), ("hand_known", HAND_KNOWN_COLS),
                            ("both", (BELIEF_COLS[0], HAND_KNOWN_COLS[1]))):
        x = obs.copy()
        x[:, lo:hi] = 0
        out[label] = {name: logloss(sigmoid(np.mean([net_logit(n, x) for n in parts], 0)), z) - base[name]
                      for name, parts in nets.items()}
    return out


def select_breakdown(sel: dict, new: str = "v1", old: str = "v_ens3") -> dict:
    from eval_s2_repr import blocks, cand_deck
    rows = []
    for a, b in blocks(sel["decks"]):
        rn, ro = sel["results"][f"{new}|{a}|{b}"], sel["results"][f"{old}|{a}|{b}"]
        for i in range(sel["n"]):
            deck, seat = cand_deck(a, b, sel["seed0"] + i)
            rows.append((deck, seat, rn[i][0] - ro[i][0], (rn[i][1] + ro[i][1]) / 2))
    # 結果の 2 列目は `rs.series` の返すターン数（手数ではない）
    turns = np.array([r[3] for r in rows])
    cut = np.percentile(turns, [100 / 3, 200 / 3])
    out = {"n": len(rows), "turns_cut": [float(c) for c in cut], "by": {}}

    def add(key, sub):
        d = np.array([r[2] for r in sub])
        out["by"][key] = {"n": len(sub), "diff": float(d.mean()), "new_only": int((d > 0).sum()),
                          "old_only": int((d < 0).sum())}
    for deck in sorted({r[0] for r in rows}):
        add(f"deck={deck}", [r for r in rows if r[0] == deck])
    for seat in (0, 1):
        add(f"seat={seat}", [r for r in rows if r[1] == seat])
    bins = np.digitize(turns, cut, right=True)            # 0: ≤ 1/3 点・1: ≤ 2/3 点・2: それより長い
    for j, lab in enumerate(("short", "mid", "long")):
        add(f"turns={lab}", [r for r, k in zip(rows, bins) if k == j])
    return out


def calib_effect(files: list) -> dict:
    """CC 版 (ii)・Cowork 版 3-a の添えるもの: 探索値の較正の効き（基準 − 較正後の対数損失）を、全体と番兵を除いた部分で。

    較正は学習と同じ作り方（`--vtarget max`・`--calib-scale bulk`・`drl_train.calibrate_vsearch`）で、
    その記録自身に当てる。番兵は |v| ≥ `drl_train.BULK_CUT`（100）。段階2 の教師（手作り評価の葉・番兵 17.5%）と
    反復 1 の教師（葉が V・番兵 0%）を、番兵を除いた同じ物差しで比べるためのもの（比較書 §4 の 1）。
    torch を使う（`drl_train` の較正の関数をそのまま呼ぶ）。
    """
    import drl_train as T
    b = T.Batcher(read_records(files), vtarget="max")
    v, z = b.vsearch.astype(np.float64), b.z.astype(np.float64)
    ok = np.isfinite(v)
    sent = ok & (np.abs(v) >= T.BULK_CUT)

    def one(m):
        c = T.calibrate_vsearch(v[m], z[m], scale="bulk")
        return {k: c[k] for k in ("n", "a", "b", "c", "logloss", "base", "spread", "sentinel_frac")} | \
            {"gain": c["base"] - c["logloss"]}
    return {"n_decisions": int(b.n), "n_search": int(ok.sum()), "n_sentinel": int(sent.sum()),
            "all": one(ok), "non_sentinel": one(ok & ~sent)}


# ------------------------------------------------------------------ 項目 3 の直し方の門（D-148）
RULE_T0 = {"u": 0.002, "e_na": 0.05, "gain_na": 0.002, "u_lin_check": 0.0002}
RULE_TB = {"u": 0.002, "gain": 0.002}
ISO_CLIP = 1e-4


def fit_iso(v: np.ndarray, z: np.ndarray) -> dict:
    """単調回帰（PAV）。どんな単調な較正の形でも出せる最良の当てはまり（判定に使わない上限・設計書 §4.1）。"""
    order = np.argsort(v, kind="mergesort")
    xs, inv = np.unique(v[order], return_inverse=True)
    w = np.bincount(inv).astype(float)
    y = np.bincount(inv, weights=z[order]) / w
    blocks = []                                  # [値, 重み, 区間の先頭の添字]
    for i in range(len(xs)):
        blocks.append([y[i], w[i], i])
        while len(blocks) > 1 and blocks[-2][0] >= blocks[-1][0]:
            b2 = blocks.pop()
            b1 = blocks[-1]
            b1[0] = (b1[0] * b1[1] + b2[0] * b2[1]) / (b1[1] + b2[1])
            b1[1] += b2[1]
    fitted = np.empty(len(xs))
    starts = [b[2] for b in blocks] + [len(xs)]
    for k, b in enumerate(blocks):
        fitted[starts[k]:starts[k + 1]] = b[0]
    return {"form": "iso", "x": xs, "p": np.clip(fitted, ISO_CLIP, 1 - ISO_CLIP)}


def apply_iso(v: np.ndarray, iso: dict) -> np.ndarray:
    """学習の記録で合わせた階段を当てる（最小値より下は最初の段）。"""
    k = np.clip(np.searchsorted(iso["x"], v, side="right") - 1, 0, len(iso["x"]) - 1)
    return iso["p"][k]


def fit_form(v, z, form: str) -> dict:
    if form == "iso":
        return fit_iso(v, z)
    import drl_train as T
    return T.calibrate_vsearch(v, z, scale="bulk", form=form)


def apply_form(v, calib: dict) -> np.ndarray:
    return apply_iso(v, calib) if calib.get("form") == "iso" else apply_calib(v, calib)


def deciles(p, z) -> list:
    q = np.quantile(p, np.linspace(0, 1, 11))
    k = np.clip(np.searchsorted(q, p, side="right") - 1, 0, 9)
    return [{"pred": float(p[k == j].mean()), "actual": float(z[k == j].mean()), "n": int((k == j).sum())}
            for j in range(10) if (k == j).any()]


def calib_summary(c: dict) -> dict:
    if c.get("form") == "iso":
        return {"form": "iso", "steps": int(len(np.unique(c["p"])))}
    return {k: c[k] for k in ("a", "b", "c", "logloss", "base", "spread") if k in c} | {"form": c.get("form", "linear")}


def batch_tagged(files: list, mans: list, vtarget: str = "max"):
    """記録を `Batcher` に通し（学習と同じ教師の値）、決定の属性を同じ並び（z が有限の決定だけ）で返す。"""
    import drl_train as T
    recs = read_records(files)
    keep = ~np.isnan(recs.z)
    tg = {k: v[keep] for k, v in tags(recs, block_table(mans)).items()}
    b = T.Batcher(recs, vtarget=vtarget)
    seed = recs.seed[keep]
    return b, tg, seed


def t0(train_files, train_mans, val_files, val_mans, u_3a: float | None = None) -> dict:
    """門 T-0（(a) の門・設計書 §4.1）。較正は学習の記録で合わせ、検証の記録に当てるだけ。"""
    tr, tg_tr, _ = batch_tagged(train_files, train_mans)
    va, tg_va, _ = batch_tagged(val_files, val_mans)
    parts = load_parts("s2v_id")
    p_v0 = sigmoid(np.mean([net_logit(n, va.obs) for n in parts], 0))
    ok_tr, ok_va = np.isfinite(tr.vsearch), np.isfinite(va.vsearch)
    z_tr, z_va = tr.z.astype(np.float64), va.z.astype(np.float64)
    out = {"n_train": int(ok_tr.sum()), "n_val": int(ok_va.sum()), "forms": {}}
    L_v0 = logloss(p_v0[ok_va], z_va[ok_va])
    preds = {}
    for form in ("linear", "logit", "iso"):
        c = fit_form(tr.vsearch[ok_tr].astype(np.float64), z_tr[ok_tr], form)
        p = apply_form(va.vsearch[ok_va].astype(np.float64), c)
        preds[form] = p
        by = {}
        for key in ("kind", "phase", "tband"):
            for v in sorted(set(tg_va[key][ok_va].tolist())):
                m = tg_va[key][ok_va] == v
                by[f"{key}={v}"] = {"n": int(m.sum()),
                                    "u": logloss(p_v0[ok_va][m], z_va[ok_va][m]) - logloss(p[m], z_va[ok_va][m])}
        out["forms"][form] = {"calib": calib_summary(c), "L": logloss(p, z_va[ok_va]), "u": L_v0 - logloss(p, z_va[ok_va]),
                              "auc": auc(p, z_va[ok_va]), "spread": float(np.percentile(p, 75) - np.percentile(p, 25)),
                              "deciles": deciles(p, z_va[ok_va]),
                              "deciles_by_kind": {k: deciles(p[tg_va["kind"][ok_va] == k], z_va[ok_va][tg_va["kind"][ok_va] == k])
                                                  for k in sorted(set(tg_va["kind"][ok_va].tolist()))},
                              "by": by}
    out["L_V0"], out["auc_V0"] = L_v0, auc(p_v0[ok_va], z_va[ok_va])
    # 錨を除いた集合（学習・検証の両方から除き、合わせ直す）
    na_tr, na_va = ok_tr & (tg_tr["kind"] != "anchor"), ok_va & (tg_va["kind"] != "anchor")
    L_v0_na = logloss(p_v0[na_va], z_va[na_va])
    na = {"n_train": int(na_tr.sum()), "n_val": int(na_va.sum())}
    for form in ("linear", "logit"):
        c = fit_form(tr.vsearch[na_tr].astype(np.float64), z_tr[na_tr], form)
        p = apply_form(va.vsearch[na_va].astype(np.float64), c)
        na[form] = {"calib": calib_summary(c), "u": L_v0_na - logloss(p, z_va[na_va]), "deciles": deciles(p, z_va[na_va])}
    top = na["linear"]["deciles"][-1]
    na["e_na"] = top["actual"] - top["pred"]
    out["no_anchor"] = na
    u_lin, u_logit, u_iso = (out["forms"][f]["u"] for f in ("linear", "logit", "iso"))
    rule1 = na["e_na"] >= RULE_T0["e_na"] and na["logit"]["u"] - na["linear"]["u"] >= RULE_T0["gain_na"]
    out["check"] = {"u_lin": u_lin, "u_3a": u_3a,
                    "ok": u_3a is None or abs(u_lin - u_3a) < RULE_T0["u_lin_check"]}
    if not out["check"]["ok"]:
        verdict = "止める（u_lin が 3-a の値を再現しない・配線を疑う）"
    elif u_logit >= RULE_T0["u"] and rule1:
        verdict = "(a) を腕にする（規則 2）"
    elif u_logit >= RULE_T0["u"]:
        verdict = "(a) は回さず相談（u_logit は越えたが錨を除くと形の説明が立たない・規則 2）"
    elif u_iso >= RULE_T0["u"]:
        verdict = "(a) は回さず相談（ロジット型より良い単調な形がある・規則 3）"
    else:
        verdict = "(a) は回さない（u_logit < 0.002）。上限 u_iso も 0.002 未満＝較正の形では項目 3 は直らない（規則 3）"
    out["rules"] = {"rule1_shape_explains": bool(rule1), "u_logit": u_logit, "u_iso": u_iso, "verdict": verdict,
                    "thresholds": RULE_T0}
    return out


RECORD_KEYS = ("seed", "step", "turn", "pi", "phase", "n_acts", "chosen")


def record_order(recs) -> np.ndarray:
    return np.lexsort((recs.step, recs.pi, recs.seed))


def compare_retake(orig, retake) -> dict:
    """取り直した記録が元の記録と、fresh 以外で全件一致するか（設計書 §4.2 の止める規則）。"""
    out = {"n_orig": int(orig.n), "n_retake": int(retake.n), "mismatch": {}}
    if orig.n != retake.n:
        out["mismatch"]["n"] = abs(orig.n - retake.n)
        out["same"] = False
        return out
    a, b = record_order(orig), record_order(retake)
    for k in RECORD_KEYS:
        out["mismatch"][k] = int((getattr(orig, k)[a] != getattr(retake, k)[b]).sum())
    out["mismatch"]["z"] = int((~((orig.z[a] == retake.z[b]) | (np.isnan(orig.z[a]) & np.isnan(retake.z[b])))).sum())
    out["mismatch"]["obs"] = int((orig.obs[a] != retake.obs[b]).any(1).sum())
    bad_act = bad_sc = 0
    for i, j in zip(a, b):
        if not np.array_equal(orig.actions_of(i), retake.actions_of(j)):
            bad_act += 1
        if not np.array_equal(orig.scores_of(i), retake.scores_of(j), equal_nan=True):
            bad_sc += 1
    out["mismatch"]["actions"], out["mismatch"]["scores"] = bad_act, bad_sc
    out["fresh_finite"] = {"orig": int(np.isfinite(orig.fresh).sum()), "retake": int(np.isfinite(retake.fresh).sum())}
    out["same"] = not any(out["mismatch"].values())
    return out


def split_calib(v, z, seed, ok) -> np.ndarray:
    """局のシードの対 (2m, 2m+1) を m の偶奇で 2 つに分け、片方で合わせてもう片方に当てる（2 通り）。"""
    half = (seed // 2) % 2
    p = np.full(len(v), np.nan)
    for h in (0, 1):
        fit, use = ok & (half == h), ok & (half != h)
        c = fit_form(v[fit], z[fit], "linear")
        p[use] = apply_form(v[use], c)
    return p


def tb(orig_files, retake_files, val_mans) -> dict:
    """門 T-b（(b) の門・設計書 §4.2）。"""
    cmp = compare_retake(read_records(orig_files), read_records(retake_files))
    out = {"compare": cmp}
    if not cmp["same"]:
        out["rules"] = {"verdict": "止める（取り直した記録が元の記録と一致しない＝打ち方が変わった）"}
        return out
    bm, tg, seed = batch_tagged(retake_files, val_mans, "max")
    bf, _, _ = batch_tagged(retake_files, val_mans, "fresh_am")
    parts = load_parts("s2v_id")
    p_v0 = sigmoid(np.mean([net_logit(n, bm.obs) for n in parts], 0))
    z = bm.z.astype(np.float64)
    ok = np.isfinite(bm.vsearch) & np.isfinite(bf.vsearch)
    p_max = split_calib(bm.vsearch.astype(np.float64), z, seed, ok)
    p_fr = split_calib(bf.vsearch.astype(np.float64), z, seed, ok)
    L_v0 = logloss(p_v0[ok], z[ok])
    u_max2, u_fresh = L_v0 - logloss(p_max[ok], z[ok]), L_v0 - logloss(p_fr[ok], z[ok])
    out.update({"n": int(ok.sum()), "L_V0": L_v0, "u_max2": u_max2, "u_fresh": u_fresh,
                "auc": {"V0": auc(p_v0[ok], z[ok]), "max": auc(p_max[ok], z[ok]), "fresh_am": auc(p_fr[ok], z[ok])},
                "n_fresh_used": int(bf.n_fresh_used), "n_nonargmax": int(bf.n_nonargmax),
                "nonargmax_rate": float(bf.n_nonargmax / max(1, bf.n))})
    # root − fresh（argmax を選び fresh が有限の決定＝fresh_am が fresh を使った決定・候補の数別）
    import drl_train as T
    rr = read_records(retake_files)
    keep = np.nonzero(~np.isnan(rr.z))[0]
    used = np.array([np.isfinite(rr.fresh[i]) and T.is_argmax(rr.scores_of(i), int(rr.chosen[i])) for i in keep])
    diff = (bm.vsearch - bf.vsearch).astype(np.float64)
    na = rr.n_acts[keep]
    out["root_minus_fresh"] = {}
    for lab, m in (("all", na > 0), ("2", na == 2), ("3", na == 3), ("4-8", (na >= 4) & (na <= 8)), ("9+", na >= 9)):
        mm = ok & used & m
        out["root_minus_fresh"][lab] = {"n": int(mm.sum()), "mean": float(diff[mm].mean()) if mm.any() else None}
    if u_max2 >= RULE_TB["u"]:
        verdict = "どの腕も回さず止めて相談（u_max2 ≥ 0.002＝3-a の判定が較正の合わせ方で変わる）"
    elif u_fresh >= RULE_TB["u"] and u_fresh - u_max2 >= RULE_TB["gain"]:
        verdict = "(b) を腕にする"
    else:
        verdict = "(b) は回さない"
    out["rules"] = {"verdict": verdict, "thresholds": RULE_TB}
    return out


def load_parts(stem: str) -> list:
    return [Net.load(os.path.join(MODELS, f"{stem}_s{k}.json")) for k in range(3)]


def run(args) -> dict:
    files = extract("val", args.work)
    recs = read_records(files)
    ok = ~np.isnan(recs.z)
    table = block_table(manifests("val"))
    tg_all = tags(recs, table)
    tg = {k: v[ok] for k, v in tg_all.items()}
    z = recs.z[ok].astype(np.float64)
    obs = recs.obs[ok]
    nets = {"V0": load_parts("s2v_id"), "V1": load_parts("s3v1_id")}
    logit = {f"{name}_s{k}": net_logit(n, obs) for name, parts in nets.items() for k, n in enumerate(parts)}
    preds = {k: sigmoid(v) for k, v in logit.items()}
    for name in nets:
        preds[name] = sigmoid(np.mean([logit[f"{name}_s{k}"] for k in range(3)], 0))
    with open(os.path.join(MODELS, "s3v1_id_s0.meta.json"), encoding="utf-8") as f:
        calib = json.load(f)["calibration"]
    p_t = teacher_p(recs, calib)[ok]
    slices = fit_slices(z, preds, tg)
    out = {"version": TOOL_VERSION, "decision": "D-144 追記 3", "n_decisions": int(ok.sum()),
           "calibration_from": "results/models/s3v1_id_s0.meta.json",
           "coverage": coverage(recs, tg_all), "fit": slices, "rule_2a": rule_2a(slices),
           "teacher": teacher_uplift(z, preds["V0"], p_t, tg),
           "columns_zero": columns_zero(nets, obs, z)}
    with open(os.path.join(ROOT, "results", "drl", "s3_it1_select.json"), encoding="utf-8") as f:
        out["select"] = select_breakdown(json.load(f))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=None, help="記録を伸ばす置き場（git の外）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--calib", action="append", default=None,
                    help="名前=記録の接頭辞（カンマ区切りで複数）。付けると較正の効き（calib_effect）だけを出す")
    ap.add_argument("--t0", action="store_true", help="門 T-0（(a) の門・D-148 §4.1）を回す（--work に記録を伸ばす）")
    ap.add_argument("--tb", default=None, help="門 T-b（(b) の門・D-148 §4.2）。取り直した検証の記録の接頭辞（カンマ区切り）")
    args = ap.parse_args(argv)
    if args.t0 or args.tb:
        if not args.work:
            raise SystemExit("--work が要る")
        out = {"version": TOOL_VERSION, "decision": "D-148"}
        if args.t0:
            prev = os.path.join(ROOT, "results", "drl", "s3_diag_desk.json")
            u_3a = json.load(open(prev, encoding="utf-8"))["teacher"]["u"] if os.path.exists(prev) else None
            out["t0"] = t0(extract("train", args.work), manifests("train"), extract("val", args.work),
                           manifests("val"), u_3a)
        if args.tb:
            from drl_train import files_of
            out["tb"] = tb(extract("val", args.work), files_of(args.tb), manifests("val"))
        print(json.dumps({k: out[k]["rules"] for k in ("t0", "tb") if k in out}, ensure_ascii=False, indent=1))
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
        return out
    if args.calib:
        from drl_train import files_of
        out = {"version": TOOL_VERSION, "decision": "D-145 追記 1", "calib": {}}
        for spec in args.calib:
            name, _, prefix = spec.partition("=")
            out["calib"][name] = calib_effect(files_of(prefix))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
        return out
    if not args.work:
        raise SystemExit("--work が要る（--calib を付けないとき）")
    out = run(args)
    print(json.dumps({k: out[k] for k in ("n_decisions", "rule_2a")} |
                     {"teacher": {k: out["teacher"][k] for k in ("L_V0", "L_teacher", "u", "verdict")}},
                     ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    main()
