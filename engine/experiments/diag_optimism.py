"""楽観の診断（D-065 便 3・§4.2／強さのレビュー §2.3）。

## この文書（と出力）の読み方

**知りたいこと**: 探索は「この局面から自分はどれくらい勝てるか」を数で答える。その数が
**実際の勝率より高い**なら、AI は自分を過大評価していることになる。過大評価した値をそのまま
次の版の教師にすると、間違いがそのまま受け継がれ、反復を重ねても強くならない。
この道具は**その過大評価（＝楽観）がどれだけあるかを、局面の種類ごとに測る**。

**測り方**: 記録（実際に対戦した局面の並び）を読み、各決定について次の 3 つを並べる。

- `z`  … その局が**実際にどうなったか**（勝ち 1 / 負け 0）。これが答えである
- `V`  … 価値ネットがその局面に付けた勝率の見立て
- `root` … その決定で**探索が付けた値の最大値**（＝「いちばん良く見えた手」の値）
- `fresh` … 選んだ手を**別の決定化で取り直した**値（記録が版 3 で `reeval_samples>0` のときだけ）

「決定化」とは、伏せられている相手の手札やデッキの並びを 1 通りに決めて読むこと。
探索は何通りか決めて読み、その平均を採る。`root` は**同じ決定化の中でいちばん良く見えた手**を
選ぶので、たまたま都合よく決まった読み筋を拾いやすい。これが楽観の出どころである。
`fresh` は選び終わってから別の決定化で測り直すので、その偏りを持たない。

**出力の見方**: 各行の `root - z` が楽観の大きさである。**正なら過大評価**。
反復を重ねるごとにこの値が 0 に近づいていれば、レビュー A-3 の手当てが効いている。
`V - z` は価値ネット自身のずれで、これは楽観というより単なる当たり外れである。

## 使い方

    python3 experiments/diag_optimism.py --records results/drl/vb3_train \\
        --net results/models/drl_sd001_vb3.json --out results/vb/diag_optimism_vb3.json

`--calib-from <meta.json>` を付けると、`root` と `fresh` に**その版の学習で使った較正**を
当ててから比べる（探索値が確率でないときに、`z` と同じ物差しに乗せるため）。
記録の葉が価値ネットの反復では探索値はもともと [0,1] なので、付けても付けなくてもよい。

**便 4 では毎反復、`eval_vb.py` のあとにこれを回して報告に貼る**（設計書 §5.2）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from experiments.drl_train import (PHASE_NAMES, apply_calibration,      # noqa: E402
                                   files_of, strata_of, stratum_name)
from meicho.drl_data import read_records                                # noqa: E402
from meicho.drlnet import Net                                           # noqa: E402


def _mean(x) -> float | None:
    x = np.asarray(x, np.float64)
    x = x[np.isfinite(x)]
    return float(x.mean()) if x.size else None


def _diff(a, b) -> float | None:
    """a と b を**同じ決定だけ**で対にして引く（別々の平均を引き算しない）。

    平均どうしを引くと、a が入っている決定と b が入っている決定が違うときに
    「別の集団どうしの比較」になってしまう。対にしてから引けばそれが起きない。
    """
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    m = np.isfinite(a) & np.isfinite(b)
    return float((a[m] - b[m]).mean()) if m.any() else None


LEGAL_BINS = ((2, 2, "合法手 2"), (3, 3, "合法手 3"), (4, 5, "合法手 4〜5"),
              (6, 8, "合法手 6〜8"), (9, 10 ** 9, "合法手 9 以上"))


def _legal_bin(k: int):
    """点数の付いた候補の数 k を層の鍵にする。1 以下は「探索なし」。"""
    if k <= 1:
        return "none", "探索なし（点数 1 つ以下）"
    for lo, hi, name in LEGAL_BINS:
        if lo <= k <= hi:
            return f"{lo}-{hi}", name
    return "none", "探索なし（点数 1 つ以下）"


def _diff_ci(a, b) -> list | None:
    """対にした差の 95% 区間の**半幅** [平均, 半幅]。決定 1 件ずつ対にして引く。

    半幅は `1.96 · 標準偏差 / √(対にした件数)`。区間が 0 をまたぐなら
    「差があるとは言い切れない」と読む（`REPORTING_RULES.md` §2.2）。
    """
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    m = np.isfinite(a) & np.isfinite(b)
    d = a[m] - b[m]
    if d.size < 2:
        return None
    return [float(d.mean()), float(1.96 * d.std(ddof=1) / np.sqrt(d.size))]


def collect(records: str, net_path: str | None, calib: dict | None = None,
            max_records: int | None = None, sample_v: int | None = None,
            by_legal: bool = False) -> dict:
    """記録を読み、層（phase × 自分のターンか）ごとに z・V・root・fresh を集計する。

    `by_legal=True` のときは**その決定で探索が点数を付けた候補の数**でも層を切り、
    `rows_by_legal` を**追加**する（D-6）。第 2 集 §6.4.2 の検定である
    ——合法手が多い層ほど `root − fresh` が大きいなら、楽観の主因は「勝者の呪い」
    （たくさんの候補から最大値を選ぶと、たまたま高く出た候補を拾いやすい）である。

    **既定（`by_legal=False`）の返り値は 1 バイトも変わらない。**
    """
    recs = read_records(files_of(records), max_records)
    keep = ~np.isnan(recs.z)
    idx = np.nonzero(keep)[0]
    z = recs.z[keep].astype(np.float64)
    strata = strata_of(recs.phase[keep], recs.obs[keep])

    # 根の最大値（探索していない決定は NaN）
    root = np.full(len(idx), np.nan, np.float64)
    n_scored = np.zeros(len(idx), np.int64)      # 点数の付いた候補の数（D-6 の層）
    for j, i in enumerate(idx):
        sc = recs.scores_of(i)
        if len(sc):
            fin = np.isfinite(sc)
            n_scored[j] = int(fin.sum())
            if fin.any():
                root[j] = sc[fin].max()
    fresh = recs.fresh[keep].astype(np.float64)
    if calib:
        root = apply_calibration(root, calib, strata)
        fresh = apply_calibration(fresh, calib, strata)

    # 価値ネットの見立て（重いので `--sample-v` で間引ける）
    v = np.full(len(idx), np.nan, np.float64)
    if net_path:
        net = Net.load(net_path)
        obs = recs.obs[keep]
        step = 1 if not sample_v or sample_v >= len(idx) else max(1, len(idx) // sample_v)
        for j in range(0, len(idx), step):
            v[j] = net.value_of(obs[j].astype(np.float32))

    def _summary(key, name, m) -> dict:
        return {
            "key": key, "name": name,
            "n": int(m.sum()),
            "mean_z": _mean(z[m]),
            "n_v": int(np.isfinite(v[m]).sum()), "mean_v": _mean(v[m]), "v_minus_z": _diff(v[m], z[m]),
            "n_root": int(np.isfinite(root[m]).sum()), "mean_root": _mean(root[m]),
            "root_minus_z": _diff(root[m], z[m]),
            "n_fresh": int(np.isfinite(fresh[m]).sum()), "mean_fresh": _mean(fresh[m]),
            "fresh_minus_z": _diff(fresh[m], z[m]),
            "root_minus_fresh": _diff(root[m], fresh[m]),
            # 層別の表は判断の材料になるので、**差には必ず 95% 区間を添える**
            # （n が層ごとに違うので、生の差だけを並べると誤読を招く）
            "root_minus_z_ci": _diff_ci(root[m], z[m]),
            "root_minus_fresh_ci": _diff_ci(root[m], fresh[m]),
        }

    rows = []
    for key in [None] + sorted(int(k) for k in np.unique(strata)):
        m = np.ones(len(idx), bool) if key is None else (strata == key)
        rows.append({
            "key": key, "name": "全体" if key is None else stratum_name(key),
            "n": int(m.sum()),
            "mean_z": _mean(z[m]),
            "n_v": int(np.isfinite(v[m]).sum()), "mean_v": _mean(v[m]), "v_minus_z": _diff(v[m], z[m]),
            "n_root": int(np.isfinite(root[m]).sum()), "mean_root": _mean(root[m]),
            "root_minus_z": _diff(root[m], z[m]),
            "n_fresh": int(np.isfinite(fresh[m]).sum()), "mean_fresh": _mean(fresh[m]),
            "fresh_minus_z": _diff(fresh[m], z[m]),
            # 同じ決定で root と fresh を対にした差。**楽観そのものの大きさ**である
            # （z を挟まないので、勝敗のばらつきに薄められない）
            "root_minus_fresh": _diff(root[m], fresh[m]),
        })
    out = {"records": records, "net": net_path, "n_decisions": int(len(idx)),
           "calibrated": bool(calib), "rows": rows,
           "phase_names": list(PHASE_NAMES)}
    if by_legal:
        # 層の並びは LEGAL_BINS の順（少ない手 → 多い手）で、最後に「探索なし」。
        order = [f"{lo}-{hi}" for lo, hi, _ in LEGAL_BINS] + ["none"]
        names = {f"{lo}-{hi}": nm for lo, hi, nm in LEGAL_BINS}
        names["none"] = "探索なし（点数 1 つ以下）"
        keys = np.asarray([_legal_bin(int(k))[0] for k in n_scored])
        out["rows_by_legal"] = [_summary(key, names[key], keys == key)
                                for key in order if (keys == key).any()]
    return out


def render(out: dict) -> str:
    """人が読む表。数はすべて「決定 1 つあたりの平均」である。"""
    lines = [f"記録 {out['records']}  決定 {out['n_decisions']} 件"
             + ("  （探索値は較正済み＝勝率の物差しに乗せてある）" if out["calibrated"] else ""),
             "",
             "  楽観 = root − z が正なら、探索は実際の勝率より高く見積もっている。",
             "  root−fresh は同じ決定を別の決定化で測り直した差で、**楽観そのもの**。",
             ""]
    head = (f"{'局面の種類':<24}{'件数':>8}{'z':>8}{'V':>8}{'V−z':>8}"
            f"{'root':>8}{'root−z':>9}{'fresh':>8}{'fr−z':>8}{'root−fr':>9}")
    lines.append(head)
    lines.append("-" * len(head))
    f = lambda x: "  ―  " if x is None else f"{x:.3f}"
    for r in out["rows"]:
        lines.append(f"{r['name']:<24}{r['n']:>8}{f(r['mean_z']):>8}{f(r['mean_v']):>8}"
                     f"{f(r['v_minus_z']):>8}{f(r['mean_root']):>8}{f(r['root_minus_z']):>9}"
                     f"{f(r['mean_fresh']):>8}{f(r['fresh_minus_z']):>8}{f(r['root_minus_fresh']):>9}")
    if out.get("rows_by_legal"):
        lines += ["", "",
                  "■ 合法手の数で切った層（D-6・第 2 集 §6.4.2 の検定）",
                  "",
                  "  「合法手」はここでは**その決定で探索が点数を付けた候補の数**である。",
                  "  候補が多いほど root−fresh が大きければ、楽観の主因は**勝者の呪い**",
                  "  （たくさんの候補から最大値を選ぶと、たまたま高く出た候補を拾う）。",
                  "  どの層でもほぼ一定なら、残る楽観は較正と strategy fusion の側にある。",
                  ""]
        lines.append(head)
        lines.append("-" * len(head))
        for r in out["rows_by_legal"]:
            lines.append(f"{r['name']:<24}{r['n']:>8}{f(r['mean_z']):>8}{f(r['mean_v']):>8}"
                         f"{f(r['v_minus_z']):>8}{f(r['mean_root']):>8}{f(r['root_minus_z']):>9}"
                         f"{f(r['mean_fresh']):>8}{f(r['fresh_minus_z']):>8}"
                         f"{f(r['root_minus_fresh']):>9}")
        lines += ["", "  root−fresh（楽観そのもの）の 95% 区間:"]
        for r in out["rows_by_legal"]:
            ci = r.get("root_minus_fresh_ci")
            if ci is None:
                lines.append(f"    {r['name']:<22} ―（対にできた決定が少なすぎる）")
                continue
            lo, hi = ci[0] - ci[1], ci[0] + ci[1]
            mark = "" if lo <= 0.0 <= hi else "  ← 0 をまたがない"
            lines.append(f"    {r['name']:<22} {ci[0]:+.4f} ±{ci[1]:.4f}"
                         f"  [{lo:+.4f}, {hi:+.4f}]{mark}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True, help="記録ファイルの接頭辞（カンマ区切りで複数可）")
    ap.add_argument("--net", default=None, help="価値ネット（省略すると V の列は空になる）")
    ap.add_argument("--calib-from", default=None,
                    help="この版の meta.json に入っている較正を探索値に当てる（勝率の物差しに乗せる）")
    ap.add_argument("--out", default=None, help="JSON の書き出し先")
    ap.add_argument("--max-records", type=int, default=None)
    ap.add_argument("--sample-v", type=int, default=None,
                    help="V を計算する決定の数（間引き。既定は全部）")
    ap.add_argument("--by-legal", action="store_true",
                    help="点数の付いた候補の数でも層を切る（D-6）。付けないときの出力は従来と同一")
    args = ap.parse_args()

    calib = None
    if args.calib_from:
        meta = json.load(open(args.calib_from, encoding="utf-8"))
        calib = meta.get("calibration")
        if not calib:
            raise SystemExit(f"{args.calib_from} に calibration が無い（--lam 0 で学習した版）")
    out = collect(args.records, args.net, calib, args.max_records, args.sample_v,
                  by_legal=args.by_legal)
    print(render(out))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"\nsaved {args.out}")


if __name__ == "__main__":
    main()
