"""DRL の学習（段階 1 の模倣学習・段階 2 の専門家反復の学習部分）。`DRL_PLAN.md` §5・§6。

入力は `meicho_rs.series_record` が書いた記録（`meicho/drl_data.py` で読む）。
出力は Rust が読む JSON（`meicho/drlnet.py::Net.save`）。

学習するもの:
- 方策 π: 各決定で「記録した agent が選んだ手」を当てる（合法手の中の交差エントロピー）。
- 価値 V: 決定者から見た最終結果 z（勝 1 / 負 0）を当てる（二値交差エントロピー）。
  `--lam` > 0 なら、探索が採点した値を**勝率に直してから** (1-lam) z + lam p_search で混ぜる
  （段階 2・`DRL_PLAN.md` §6.1(b)）。

  どの探索値を使うかは `--vtarget` で決める（D-064 §3.3）。**既定は `max`**、すなわち
  その決定で探索が付けた値の**最大値**である。局面の価値とは「そこから最善を尽くしたときの
  価値」であり、また記録時は温度 τ で探索的な手も選ばせるので、`chosen`（実際に選んだ手の値・
  旧既定）だと**わざと選んだ悪手の値が教師に混ざる**。最大値なら τ に汚されない。

  `fresh`（D-065 便 3・レビュー A-3 (i)）は「選んだ手を**別の決定化で取り直した値**」を使う。
  最大値は「同じ決定化の中でいちばん良く見えた手」を選ぶので、決定化の揺れを最大で拾い、
  **本当の価値より高く見積もる**（レビュー §2.3 の実測で +0.17）。取り直した値はその偏りを
  持たない。記録が版 2（`fresh` が無い）の決定、および `reeval_samples=0` で取った記録では
  `fresh` は NaN なので、**そこは `max` で埋める**（過去の記録でもそのまま回る）。

  **なぜ「直してから」なのか（D-059）**: 記録に入る探索値は `greedy.evaluate` の
  重み付き和であって確率ではない。実測（SD001・下見 200 局）では範囲が -10000..10000、
  中央値 0.33 で、[0,1] に収まるのは全体の 10% にすぎない。素のまま z と混ぜると、
  「たまたま 0〜1 に落ちた決定だけが別の目標を持つ」というでたらめな教師になる。
  そこで 1 変数のロジスティック較正（`calibrate_vsearch`）で探索値 → 勝率に直し、
  較正の質（対数損失が基準値より下がるか）を出力・meta に記録してから混ぜる。
  較正が効いていない場合は `--lam` を使わないこと。

  **目盛りの選び方（`--calib-scale`・D-064 反復 1）**: 較正は `clip(v, ±c)/c` で目盛りを合わせる。
  従来（`p90`）の c は「|v| の 90% 点」で、これは**勝敗確定の番兵が 10% 以下**という前提に立つ。
  地平を延ばし（`extra_turns=1`）教師を最大値（`--vtarget max`）にすると番兵が 10% を超え、
  c が番兵に引きずられて**本体をまとめて 0 に潰す**。そうなると較正後の教師はほぼ定数になり、
  探索値の情報が伝わらない（実測: 教師 p の 25〜75% 分位が 0.498〜0.499）。
  その構成では `bulk`（番兵を除いた本体の 90% 点）を使う。出力の「教師 p の広がり」で判別できる。

使い方:
    python3 experiments/drl_train.py --train results/drl/sd001_s1_train.bin --valid results/drl/sd001_s1_valid.bin \
        --out results/models/drl_sd001_s1.json --epochs 6
記録ファイルは `<path>.<worker>` の分割で置かれているので、`--train` にはその接頭辞を渡す。
**`--train` はカンマ区切りで複数の接頭辞を受ける**（データ窓。D-064 §9「直近 N 反復ぶんを使う」）。
ただし**探索値の尺度が揃っている反復どうしだけ**を並べること（較正が 1 つの変換なので混ぜると壊れる）。
`--init` で既存モデルから続きを学ぶ（段階 2 の反復）。
`--select` で「どのエポックの版を保存するか」を選ぶ。既定は `last`（最後のエポック）だが、
段階 1 の実測では**価値 V は 1 エポック目が最良で以降悪化し、方策 π だけが伸びた**ので、
V を使う構成では `best_v`、π を使う構成では `best_p` を指定する（`HANDOFF_20260826_DRL2.md` §4-2）。

再現性: `--seed` で torch と numpy の乱数を固定する。CPU では決定的。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import torch                                                       # noqa: E402
import torch.nn as nn                                              # noqa: E402
import torch.nn.functional as F                                    # noqa: E402

from meicho.drl_data import Records, read_records                  # noqa: E402
from meicho.drlnet import Net                                      # noqa: E402
from meicho.encode import ACT_CODE_LEN, ACT_DIM, ACTION_TYPES, NA, NC, OBS_DIM   # noqa: E402

PHASE_NAMES = ("setup", "mulligan", "action", "clash", "choice", "rush", "discard", "over")
MAX_ACTS = 32


def files_of(prefix: str) -> list:
    """記録ファイルを集める。**カンマ区切りで複数の接頭辞を渡せる**（データ窓・D-064 §9）。

    設計書 §9 の「直近 N 反復ぶんだけを学習に使う」を、接頭辞を並べることで表す。
    **並べてよいのは探索値の尺度が揃っている反復どうしだけである**——較正は全データに
    1 つの変換を当てるので、尺度の違う記録を混ぜると教師が壊れる（D-064 第 5 便 §24）。
    葉が価値ネットになっている反復（探索値が [0,1]）どうしなら揃っている。
    """
    out: list = []
    for pre in [x.strip() for x in prefix.split(",") if x.strip()]:
        fs = sorted(glob.glob(pre + ".*"))
        fs = [f for f in fs if not f.endswith(".json")]
        if not fs:
            raise SystemExit(f"no record files for {pre}")
        out += fs
    if not out:
        raise SystemExit(f"no record files for {prefix}")
    # 同じファイルを 2 度読まない（接頭辞が入れ子だと起こりうる）
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


# ------------------------------------------------------------------ 探索値の較正
# 「番兵」とみなす大きさの下限（`greedy.WIN` = 10000 の 1%）。
# 探索値は決定化の平均なので、±10000 だけでなく ±5000・±2500 のような**部分的な番兵**も出る。
# 本体（勝敗が決まっていない局面の評価値）はこれよりずっと小さい。
BULK_CUT = 100.0


def calib_scale(v: np.ndarray, scale: str = "p90", bulk_cut: float = BULK_CUT) -> float:
    """較正の目盛り c を決める（D-064 反復 1 の裁定）。

    - `p90`（従来・D-059）: |v| の 90% 点。番兵が 10% 以下という前提のもとで正しい。
    - `bulk`: **番兵を除いた本体**の |v| の 90% 点。

    なぜ `bulk` が要るか（D-064 反復 1 の実測）: 地平を 1 往復延ばし（裁定 1）、教師を
    探索値の最大値にした（§3.3）ことで、**番兵が 10% よりずっと多く出るようになった**。
    実測では |v| の 90% 点が 5007 まで押し上げられ、本体（中央値 3.65）はその約 1/1000。
    `clip(v, ±5007)/5007` が本体をまとめて 0 の近くに潰し、較正後の教師は
    25〜75% 分位が 0.498〜0.499 の定数になっていた——探索値の情報が教師に伝わらない。

    葉が価値ネットの反復（探索値が [0,1] に収まる）では番兵が `bulk_cut` を超えないので、
    `bulk` と `p90` は同じ値になる。つまりこの指定に副作用は無い。
    """
    a = np.abs(v)
    if scale == "p90":
        pass
    elif scale == "bulk":
        m = a < bulk_cut
        if m.sum() >= 100:                 # 本体が数えられるときだけ絞る
            a = a[m]
    else:
        raise SystemExit(f"未対応の --calib-scale: {scale!r}")
    return max(float(np.percentile(a, 90)), 1e-6)


def calibrate_vsearch(v: np.ndarray, z: np.ndarray, steps: int = 400, seed: int = 0,
                      scale: str = "p90", min_n: int = 1000) -> dict:
    """探索値 v（無界の評価値）を勝率に直す 1 変数ロジスティック較正（D-059 / D-064）。

    p = sigmoid(a * clip(v, -c, c) / c + b)。c の決め方は `calib_scale`（`--calib-scale`）。
    a, b は勝敗 z への二値交差エントロピーを最小化して決める（決定的）。

    返り値には較正の質を入れる:
      `logloss` 較正後の対数損失／`base` 「常に平均勝率」と答えたときの対数損失。
      **`logloss` が `base` を下回らないなら、探索値は勝敗の情報を持っていない** ＝ λ を使わない。
    """
    ok = np.isfinite(v) & np.isfinite(z)
    v, z = v[ok].astype(np.float64), z[ok].astype(np.float64)
    if len(v) < min_n:
        raise SystemExit(f"較正に使える決定が少なすぎる（{len(v)} 件・下限 {min_n}）")
    c = calib_scale(v, scale)
    u = np.clip(v, -c, c) / c
    torch.manual_seed(seed)
    ut = torch.from_numpy(u).float()
    zt = torch.from_numpy(z).float()
    a = torch.zeros(1, requires_grad=True)
    b = torch.tensor([float(np.log(max(z.mean(), 1e-6) / max(1 - z.mean(), 1e-6)))], requires_grad=True)
    opt = torch.optim.LBFGS([a, b], max_iter=steps, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        loss = F.binary_cross_entropy_with_logits(a * ut + b, zt)
        loss.backward()
        return loss
    opt.step(closure)
    with torch.no_grad():
        ll = float(F.binary_cross_entropy_with_logits(a * ut + b, zt))
        p = torch.sigmoid(a * ut + b).numpy()
    p0 = float(z.mean())
    base = float(-(p0 * np.log(max(p0, 1e-9)) + (1 - p0) * np.log(max(1 - p0, 1e-9))))
    # `spread` は教師 p の**まん中半分**の広がり（75% 点 − 25% 点）。**ここが 0 に近いと、
    # 勝敗の決まっていない普通の局面で教師がほぼ定数＝探索値の情報が伝わっていない**
    # （D-064 反復 1 の失敗の指標。実測 0.001）。
    # `logloss < base` だけでは、番兵の 1 ビットだけで基準を下回れてしまい見抜けない。
    # 5%〜95% で測ると番兵の分だけ広く見えてしまうので、**四分位で測る**。
    return {"a": float(a.item()), "b": float(b.item()), "c": c, "n": int(len(v)),
            "scale": scale, "sentinel_frac": float((np.abs(v) >= BULK_CUT).mean()),
            "spread": float(np.percentile(p, 75) - np.percentile(p, 25)),
            "logloss": ll, "base": base, "useful": bool(ll < base - 1e-3)}


def _sigmoid_calib(v: np.ndarray, calib: dict) -> np.ndarray:
    u = np.clip(v, -calib["c"], calib["c"]) / calib["c"]
    return 1.0 / (1.0 + np.exp(-(calib["a"] * u + calib["b"])))


def apply_calibration(v: np.ndarray, calib: dict, strata: np.ndarray = None) -> np.ndarray:
    """較正を当てて勝率にする。v が NaN のところは NaN のまま。

    `calib` が層別（`calibrate_vsearch_strata` の返り値）で `strata` が渡されたときは、
    **決定ごとにその層の較正を当てる**。層別でない／`strata` が無いときは全体の較正を当てる
    ので、従来の呼び出し（`apply_calibration(v, calib)`）は一切変わらない。
    """
    if not calib.get("strata") or strata is None:
        return _sigmoid_calib(v, calib)
    out = _sigmoid_calib(v, calib)                 # まず全体の較正で埋める（層が薄いところの受け皿）
    for key, sub in calib["strata"].items():
        m = strata == int(key)
        if m.any():
            out[m] = _sigmoid_calib(v[m], sub)
    return out


# 観測ベクトルの何番目が「いま自分のターンか」の旗か（`meicho/encode.py` の scal の 15 番目）。
# **層の鍵はこの 1 ビットと phase の組**である。ここがずれると層が意味を失うので、
# `tests/test_d065.py::test_turn_flag_column_is_where_we_think_it_is` が実局面で固定している。
TURN_FLAG_COL = 14
N_PHASES = 8


def strata_of(phase: np.ndarray, obs: np.ndarray) -> np.ndarray:
    """層の鍵（phase × 自分のターンか）を 0..15 の整数にする（D-065 §4.1）。"""
    turn = (obs[:, TURN_FLAG_COL] != 0).astype(np.int64)
    return phase.astype(np.int64) * 2 + turn


LEAGUE_OFFSET = N_PHASES * 2          # リーグの局面を別の層にするときの下駄（D-067 案 A）


def stratum_name(key: int) -> str:
    if key >= LEAGUE_OFFSET:
        return "リーグ・" + stratum_name(key - LEAGUE_OFFSET)
    if not 0 <= key // 2 < len(PHASE_NAMES):
        return f"層{key}"                       # 想定外の鍵でも名前で落ちないように
    return f"{PHASE_NAMES[key // 2]}/{'自分' if key % 2 else '相手'}のターン"


def parse_seed_ranges(text: str | None) -> list:
    """`"487100-488099,488100-489099"` を [(487100, 488099), ...] にする。

    **なぜシードで指すのか**: リーグ（対 H・対貪欲）の局面は記録の塊で分かれており、
    その塊は manifest にもシード帯の台帳にも**シードの範囲**として書いてある。
    ファイル名の付け方に依存しないので、記録を取り直しても同じ指定が通る。
    """
    if not text:
        return []
    out = []
    for part in [x.strip() for x in text.split(",") if x.strip()]:
        if "-" not in part:
            raise SystemExit(f"シードの範囲は a-b の形で書くこと: {part!r}")
        a, b = part.split("-", 1)
        lo, hi = int(a), int(b)
        if lo > hi:
            raise SystemExit(f"シードの範囲が逆さま: {part!r}")
        out.append((lo, hi))
    return out


def in_ranges(seed: np.ndarray, ranges: list) -> np.ndarray:
    """`seed` の各要素がどれかの範囲に入っているか（両端を含む）。"""
    m = np.zeros(len(seed), bool)
    for lo, hi in ranges:
        m |= (seed >= lo) & (seed <= hi)
    return m


def calibrate_vsearch_strata(v: np.ndarray, z: np.ndarray, strata: np.ndarray,
                             steps: int = 400, seed: int = 0, scale: str = "p90",
                             min_n: int = 1000) -> dict:
    """層（phase × 自分のターンか）ごとに較正を取る（`--calib-by phase_turn`・D-065 §4.1）。

    なぜ層に分けるのか: 探索値 → 勝率の対応は**局面の種類でずれる**。たとえば対抗の最中に
    付いた +3 と、自分の行動フェイズで付いた +3 は、同じ数でも意味が違う。1 本の変換で
    まとめると、その差が「ただの誤差」として平らに均されてしまう。

    **決定が `min_n` 未満の層は全体の較正に落とす**（1 変数とはいえ、数十件から取った変換は
    その数十件に合わせただけの当てずっぽうになる）。落とした層は `fallback` に残す。

    返り値は `calibrate_vsearch` と同じ鍵（`a`/`b`/`c`/`logloss`/`base`/`spread`/`useful`）を
    **全体の較正の値と、層別を当てたあとの質**で埋めたうえに、`strata`・`fallback`・`by` を足す。
    そのため呼び出し側の印字・判定はそのまま動く。
    """
    ok = np.isfinite(v) & np.isfinite(z)
    overall = calibrate_vsearch(v, z, steps=steps, seed=seed, scale=scale, min_n=min_n)
    out = dict(overall)
    out["by"] = "phase_turn"
    out["overall"] = overall
    out["strata"] = {}
    out["fallback"] = []
    for key in sorted(set(int(k) for k in np.unique(strata[ok]))):
        m = ok & (strata == key)
        if int(m.sum()) >= min_n:
            sub = calibrate_vsearch(v[m], z[m], steps=steps, seed=seed, scale=scale, min_n=min_n)
            sub["name"] = stratum_name(key)
            out["strata"][str(key)] = sub
        else:
            out["fallback"].append({"key": key, "name": stratum_name(key), "n": int(m.sum())})
    # 層別を当てたあとの質を、全体と同じ物差しで測り直す（この値で `--lam` の可否を判断する）
    p = apply_calibration(v, out, strata)
    pv, zv = p[ok], z[ok].astype(np.float64)
    eps = 1e-9
    ll = float(-(zv * np.log(np.clip(pv, eps, 1)) + (1 - zv) * np.log(np.clip(1 - pv, eps, 1))).mean())
    out["logloss"] = ll
    out["base"] = overall["base"]
    out["spread"] = float(np.percentile(pv, 75) - np.percentile(pv, 25))
    out["useful"] = bool(ll < out["base"] - 1e-3)
    out["logloss_overall"] = overall["logloss"]
    return out


# ---------------------------------------------------------------------- データ
class Batcher:
    """記録を固定長の配列に詰め替える（行動は MAX_ACTS に詰めてマスク）。"""

    def __init__(self, recs: Records, lam: float = 0.0, calib: dict = None,
                 vtarget: str = "max", league_ranges: list = None):
        n = recs.n
        keep = ~np.isnan(recs.z)
        # リーグ（対 H・対貪欲）の局面かどうか。**シードで見分ける**（D-067）。
        self.league = (in_ranges(recs.seed[keep], league_ranges) if league_ranges
                       else np.zeros(int(keep.sum()), bool))
        self.obs = recs.obs[keep]
        self.z = recs.z[keep].astype(np.float32)
        self.chosen = recs.chosen[keep].astype(np.int64)
        self.phase = recs.phase[keep].astype(np.int64)
        self.n_acts = recs.n_acts[keep].astype(np.int64)
        idx = np.nonzero(keep)[0]
        m = len(idx)
        acts = np.full((m, MAX_ACTS, ACT_CODE_LEN), -1, np.int8)
        vsearch = np.full(m, np.nan, np.float32)
        if vtarget not in ("chosen", "max", "fresh"):
            raise SystemExit(f"未対応の --vtarget: {vtarget!r}")
        self.vtarget = vtarget
        # 層の鍵（phase × 自分のターンか）。`--calib-by phase_turn` のときだけ使う。
        self.stratum = strata_of(self.phase, self.obs)
        fresh = (recs.fresh[keep] if getattr(recs, "fresh", None) is not None
                 else np.full(m, np.nan, np.float32))
        self.n_fresh_used = 0
        for j, i in enumerate(idx):
            a = recs.actions_of(i)
            k = min(len(a), MAX_ACTS)
            acts[j, :k] = a[:k]
            sc = recs.scores_of(i)
            if vtarget == "fresh" and np.isfinite(fresh[j]):
                # 取り直した値があればそれを使う（決定化の揺れを最大で拾わない教師）
                vsearch[j] = fresh[j]
                self.n_fresh_used += 1
                continue
            if not len(sc):
                continue
            if vtarget in ("max", "fresh"):
                # `fresh` が NaN の決定（版 2 の記録・探索していない決定）はここに落ちる
                # 局面の価値 = 「そこから最善を尽くしたときの価値」（D-064 §3.3）。
                # 記録時は温度 τ で探索的な手も選ぶので、**選んだ手の値**を教師にすると
                # わざと選んだ悪手の値が教師に混ざる。最大値なら τ に汚されない。
                fin = np.isfinite(sc)
                if fin.any():
                    vsearch[j] = sc[fin].max()
            elif recs.chosen[i] < len(sc):
                vsearch[j] = sc[recs.chosen[i]]
        self.acts = acts
        self.n_acts = np.minimum(self.n_acts, MAX_ACTS)
        self.vsearch = vsearch
        self.n = m
        # V の損失にかける重み。案 B（`--league-mode drop`）ではリーグの局面を 0 にする。
        # **方策の頭（p）には使い続ける**——局面の多様性はそちらが引き受ける。
        self.vw = np.ones(m, np.float32)
        self.target = self.z.copy()
        self.set_lam(lam, calib)

    def set_lam(self, lam: float, calib: dict = None) -> None:
        """V の教師を (1-lam)·z + lam·p_search にする（段階 2）。探索値が無い決定は z のまま。

        `calib` は `calibrate_vsearch` の返り値。**lam > 0 なら必須**（D-059）。
        探索値は確率ではないので、較正せずに混ぜると教師がでたらめになる。
        """
        self.target = self.z.copy()
        if lam <= 0:
            return
        if not calib:
            raise SystemExit("--lam > 0 には探索値の較正が要る（探索値は確率ではない・D-059）")
        p = apply_calibration(self.vsearch, calib, self.stratum)
        ok = np.isfinite(p)
        self.target[ok] = ((1 - lam) * self.z[ok] + lam * p[ok]).astype(np.float32)

    def batch(self, ids):
        return (torch.from_numpy(self.obs[ids].astype(np.float32)),
                torch.from_numpy(self.acts[ids].astype(np.int64)),
                torch.from_numpy(self.n_acts[ids]),
                torch.from_numpy(self.chosen[ids]),
                torch.from_numpy(self.target[ids]),
                torch.from_numpy(self.z[ids]),
                torch.from_numpy(self.phase[ids]))


def expand_codes(codes: torch.Tensor) -> torch.Tensor:
    """[B, K, ACT_CODE_LEN] の符号 → [B, K, ACT_DIM]（`encode.expand_action` と同じ並び）。"""
    t, card, chara, slot, back, count = [codes[..., i] for i in range(6)]
    oh = lambda x, n: F.one_hot((x + 1).clamp(0, n), n + 1)[..., 1:].float()   # -1 → 全ゼロ
    mull = sum(oh(codes[..., 6 + k], NA) for k in range(5))                    # 捨て札の枚数ベクトル
    parts = [oh(t, len(ACTION_TYPES)), oh(card, NA), oh(chara, NC),
             oh(codes[..., 11], NC), oh(codes[..., 12], NC), oh(slot, 3),
             oh(back - 1, 2), (count.float() / 8.0).clamp(min=0.0).unsqueeze(-1), mull]
    v = torch.cat(parts, dim=-1)
    assert v.shape[-1] == ACT_DIM, (v.shape, ACT_DIM)
    return v


# ---------------------------------------------------------------------- モデル
class TwoHead(nn.Module):
    def __init__(self, hidden: int = 256, depth: int = 2, phead: int = 128, scale=None,
                 proj=None, proj_scale=None):
        super().__init__()
        # D-132: カードの効果表現の射影（`card_profile_proj.py`）。渡したときだけ第 1 層の入力に
        # `(x @ proj) / proj_scale` を足す。書き出しで第 1 層へ畳み込むので、Rust が読む形は変わらない。
        # 渡さなければ従来どおり（第 1 層の入力は OBS_DIM）。
        n_extra = 0
        if proj is None:
            self.proj = None
        else:
            self.register_buffer("proj", torch.as_tensor(proj, dtype=torch.float32))
            n_extra = self.proj.shape[1]
            self.register_buffer("proj_scale", torch.ones(n_extra) if proj_scale is None
                                 else torch.as_tensor(proj_scale, dtype=torch.float32))
            # 射影は疎（0/1 で非ゼロは約 1 万個）なので、掛け算は疎行列で行う（密だと 1 バッチ 7 GFLOP）
            self._proj_t = self.proj.t().contiguous().to_sparse_csr()
        layers, d = [], OBS_DIM + n_extra
        for _ in range(depth):
            layers += [nn.Linear(d, hidden), nn.ReLU()]
            d = hidden
        self.trunk = nn.Sequential(*layers)
        self.value = nn.Linear(hidden, 1)
        self.p1 = nn.Linear(hidden + ACT_DIM, phead)
        self.p2 = nn.Linear(phead, 1)
        # 入力のスケール（学習中は割る。書き出し時に第 1 層へ畳み込む）
        self.register_buffer("scale", torch.ones(OBS_DIM) if scale is None else torch.as_tensor(scale, dtype=torch.float32))

    def forward(self, obs, codes, n_acts):
        x = obs / self.scale
        if self.proj is not None:
            x = torch.cat([x, self.apply_proj(x) / self.proj_scale], -1)
        h = self.trunk(x)
        v = self.value(h).squeeze(-1)
        a = expand_codes(codes)                                  # [B,K,A]
        hk = h.unsqueeze(1).expand(-1, a.shape[1], -1)
        s = self.p2(F.relu(self.p1(torch.cat([hk, a], -1)))).squeeze(-1)   # [B,K]
        mask = torch.arange(a.shape[1]).unsqueeze(0) < n_acts.unsqueeze(1)
        s = s.masked_fill(~mask, -1e9)
        return v, s

    def apply_proj(self, x):
        """x @ proj を疎行列で計算する（値は密の掛け算と同じ・足し算の順だけが違う）。"""
        return (self._proj_t @ x.t()).t()

    def export(self) -> Net:
        """Rust が読む形。スケールは第 1 層の重みに畳み込む。"""
        lin = [m for m in self.trunk if isinstance(m, nn.Linear)]
        trunk = []
        for i, m in enumerate(lin):
            w = m.weight.detach().cpu().numpy().astype(np.float32)
            if i == 0:
                if self.proj is not None:
                    # D-132: 射影の列を畳み込む  W_id·x + W_pf·((x@M)/s) = (W_id + (W_pf/s)·Mᵀ)·x
                    pr = self.proj.detach().cpu().numpy().astype(np.float64)
                    ps = self.proj_scale.detach().cpu().numpy().astype(np.float64)
                    w64 = w.astype(np.float64)
                    w = (w64[:, :OBS_DIM] + (w64[:, OBS_DIM:] / ps[None, :]) @ pr.T).astype(np.float32)
                w = w / self.scale.detach().cpu().numpy()[None, :]
            trunk.append((w, m.bias.detach().cpu().numpy().astype(np.float32)))
        value = (self.value.weight.detach().cpu().numpy(), self.value.bias.detach().cpu().numpy())
        policy = [(self.p1.weight.detach().cpu().numpy(), self.p1.bias.detach().cpu().numpy()),
                  (self.p2.weight.detach().cpu().numpy(), self.p2.bias.detach().cpu().numpy())]
        return Net(trunk, value, policy)

    @staticmethod
    def from_net(net: Net, scale) -> "TwoHead":
        hidden = net.trunk[0][0].shape[0]
        depth = len(net.trunk)
        phead = net.policy[0][0].shape[0]
        m = TwoHead(hidden, depth, phead, scale)
        lin = [x for x in m.trunk if isinstance(x, nn.Linear)]
        with torch.no_grad():
            for i, (x, (w, b)) in enumerate(zip(lin, net.trunk)):
                w = torch.from_numpy(w.copy())
                if i == 0:
                    w = w * m.scale[None, :]
                x.weight.copy_(w); x.bias.copy_(torch.from_numpy(b.copy()))
            m.value.weight.copy_(torch.from_numpy(net.value[0].copy())); m.value.bias.copy_(torch.from_numpy(net.value[1].copy()))
            m.p1.weight.copy_(torch.from_numpy(net.policy[0][0].copy())); m.p1.bias.copy_(torch.from_numpy(net.policy[0][1].copy()))
            m.p2.weight.copy_(torch.from_numpy(net.policy[1][0].copy())); m.p2.bias.copy_(torch.from_numpy(net.policy[1][1].copy()))
        return m


# ------------------------------------------------------------------ 蒸留（π）
# D-065 便 4 の速度の手当て（計画書 §9-4 (b)・マスター裁定 2026-09-05）。
#
# なぜ要るのか: 代打ち π（`policy_scope="proxy"`）は探索の中で 1 決定ごとに呼ばれる。
# いまの π はネットの大きさが 幹 256・頭 128 で、これが**記録を 25 倍遅くしている**
# （実測・`D065_NOTES.md` 便 4 §5.1 §3）。同じように打つ小さいネットに置き換えれば、
# 強さを保ったまま速くなる。実測では 幹 64・頭 32 で 6.0 倍速い。
#
# 目的は**速さであって強化ではない**。だから生徒に求めるのは「先生と同じように打つこと」で、
# 「先生より良く打つこと」ではない。


def distil_loss(student_logits, teacher_logits, n_acts):
    """先生の手の選び方に生徒を合わせる損失（合法手の中の KL ダイバージェンス）。

    「KL ダイバージェンス」は 2 つの確率分布のずれを表す量で、**同じなら 0**、違うほど大きい。
    ここでは「合法手それぞれをどれくらい選びたいか」の分布どうしを比べている。

    **一番の手だけを当てにいかない**理由: 先生が「A が 0.5・B が 0.45・C が 0.05」と
    思っているとき、「A を選べ」とだけ教えると B と C の区別が伝わらない。分布ごと写せば
    「B もほぼ同じくらい良い」まで伝わるので、**少ない教材で似た打ち方になる**。

    合法手の外（固定長の枠の余り）は数えない。数えると、手の数が少ない決定ほど
    「無い手を選ばない練習」をさせられることになり、教材が歪む。
    """
    mask = torch.arange(student_logits.shape[1]).unsqueeze(0) < n_acts.unsqueeze(1)
    neg = torch.finfo(student_logits.dtype).min
    t = torch.where(mask, teacher_logits, torch.full_like(teacher_logits, neg))
    s = torch.where(mask, student_logits, torch.full_like(student_logits, neg))
    tp = F.softmax(t, dim=-1)
    return F.kl_div(F.log_softmax(s, dim=-1), tp, reduction="batchmean")


def check_distil_args(distil_from, wv: float, lam: float) -> None:
    """`--distil-from` は π だけを学ぶ口である（V は今までどおり大きい版を使う）。

    黙って V も一緒に学ぶと「何のための版か」が曖昧な版ができ、あとから読めなくなる。
    """
    if not distil_from:
        return
    if wv != 0.0:
        raise SystemExit("--distil-from は π だけを学ぶ口。--wv 0 を指定すること"
                         "（小さい版の V は使わない・葉に積むのは大きい版のまま）")
    if lam != 0.0:
        raise SystemExit("--distil-from と --lam は同時に使えない（--lam は V の教師の話）")


# ---------------------------------------------------------------------- 評価
@torch.no_grad()
def evaluate(model, data: Batcher, bs: int = 4096, teacher=None) -> dict:
    """`teacher` を渡すと「先生と同じ手を一番手に選んだ割合」も測る（蒸留の合否の目安）。"""
    model.eval()
    tot = {"n": 0, "v_logloss": 0.0, "v_acc": 0.0, "t_logloss": 0.0, "p_logloss": 0.0, "p_acc": 0.0}
    per_phase = {k: [0, 0] for k in range(8)}
    for s in range(0, data.n, bs):
        ids = np.arange(s, min(s + bs, data.n))
        obs, codes, n_acts, chosen, target, z, phase = data.batch(ids)
        v, sc = model(obs, codes, n_acts)
        p = torch.sigmoid(v)
        eps = 1e-6
        tot["v_logloss"] += float((-(z * torch.log(p + eps) + (1 - z) * torch.log(1 - p + eps))).sum())
        tot["v_acc"] += float(((p > 0.5).float() == z).float().sum())
        # `t_logloss` は**教師（target）に対する**外し具合（`--select target_v`・D-065 §4.1）。
        # `v_logloss` が「勝敗 z をどれだけ当てたか」なのに対し、こちらは
        # 「学習で狙っている当のもの（z と探索値の混合）をどれだけ当てたか」を測る。
        # `--lam 0` のときは target == z なので両者は一致する。
        tot["t_logloss"] += float((-(target * torch.log(p + eps)
                                     + (1 - target) * torch.log(1 - p + eps))).sum())
        lp = F.log_softmax(sc, -1)
        tot["p_logloss"] += float((-lp.gather(1, chosen.unsqueeze(1))).sum())
        hit = (sc.argmax(-1) == chosen)
        tot["p_acc"] += float(hit.float().sum())
        if teacher is not None:
            t_sc = teacher(obs, codes, n_acts)[1]
            tot["t_agree"] = tot.get("t_agree", 0.0) + float((sc.argmax(-1) == t_sc.argmax(-1)).float().sum())
        for k in range(8):
            m = phase == k
            per_phase[k][0] += int(hit[m].sum()); per_phase[k][1] += int(m.sum())
        tot["n"] += len(ids)
    n = max(1, tot["n"])
    out = {k: (v / n if k != "n" else v) for k, v in tot.items()}
    out["p_acc_by_phase"] = {PHASE_NAMES[k]: (c / t if t else None, t) for k, (c, t) in per_phase.items() if t}
    model.train()
    return out


class BestKeeper:
    """検証がいちばん良かったエポックの重みを控えておく（`--select`・D-059）。

    段階 1 の実測では **V は 1 エポック目が最良で以降悪化し、π だけが伸びた**。
    「最後のエポックを保存する」は π には正しく V には誤りなので、両方を控える。

    D-065 便 3 で 3 つ目（`t` = 教師そのものに対する損失・`--select target_v`）を足した。
    """

    #: `--select` の値 → 控えの鍵。**`split("_")` で作らないこと**——`target_v` が
    #: `"v"` に化けて `best_v` と区別できなくなる（この表が唯一の対応）。
    KEYS = {"best_v": "v", "best_p": "p", "target_v": "t"}
    METRICS = (("v", "v_logloss"), ("p", "p_logloss"), ("t", "t_logloss"))

    def __init__(self):
        import copy
        self._copy = copy.deepcopy
        self.best = {k: (float("inf"), None, 0) for k in ("v", "p", "t")}

    def offer(self, epoch: int, ev: dict, state) -> None:
        # 評価に無い指標は黙って飛ばす（`t_logloss` を足す前の呼び出しでも動くように）。
        # 実際の `evaluate` は 3 つとも返すので、本番で控えが空になることはない。
        for key, metric in self.METRICS:
            if metric in ev and ev[metric] < self.best[key][0]:
                self.best[key] = (ev[metric], self._copy(state), epoch)

    def pick(self, select: str):
        """(loss, state, epoch)。`select` は 'best_v' / 'best_p' / 'target_v'。"""
        return self.best[self.KEYS[select]]


def chance_accuracy(data: Batcher) -> float:
    """当てずっぽう（合法手から一様に選ぶ）の一致率の期待値。"""
    return float(np.mean(1.0 / data.n_acts))


# ---------------------------------------------------------------------- 学習
def train(args):
    torch.manual_seed(args.seed); np.random.seed(args.seed)
    torch.set_num_threads(args.threads)
    t0 = time.time()
    # 検査は簡素な args を組み立てて `train` を呼ぶ。新しい口を足したせいで
    # 既存の呼び出しが落ちないよう、既定（従来どおり）に落とす。
    args.league_seeds = getattr(args, "league_seeds", None)
    args.league_mode = getattr(args, "league_mode", "keep")
    lg = parse_seed_ranges(args.league_seeds)
    if lg and args.league_mode == "keep":
        raise SystemExit("--league-seeds を渡すなら --league-mode を drop か stratify にすること"
                         "（keep のままでは 1 ビットも挙動が変わらない）")
    if args.league_mode != "keep" and not lg:
        raise SystemExit(f"--league-mode {args.league_mode} には --league-seeds が要る")
    tr = Batcher(read_records(files_of(args.train), args.max_records),
                 vtarget=args.vtarget, league_ranges=lg)
    va = Batcher(read_records(files_of(args.valid), args.max_records),
                 vtarget=args.vtarget, league_ranges=lg)
    print(f"train {tr.n} decisions / valid {va.n} decisions  (read {time.time()-t0:.0f}s)  chance acc: "
          f"train {chance_accuracy(tr):.3f} valid {chance_accuracy(va):.3f}")

    # --- D-067: リーグ（対 H・対貪欲）の局面をどう扱うか -----------------------
    # 探索値には**相手が誰かが入っていない**ので、自己対戦とリーグを 1 本の較正曲線で
    # 同時に当てるのは構造的に無理である（自己対戦 +0.052／リーグ −0.263）。
    fit = np.ones(tr.n, bool)             # 較正を取るのに使う決定
    if args.league_mode != "keep":
        n_lg = int(tr.league.sum())
        if n_lg == 0:
            raise SystemExit(f"--league-seeds {args.league_seeds} に当たる決定が 1 件も無い。"
                             f"帯の指定が学習データと合っているか確かめること")
        print(f"  リーグの局面 {n_lg} 件（学習全体の {n_lg / tr.n:.1%}）→ --league-mode {args.league_mode}")
        if args.league_mode == "drop":
            # 案 B: V の損失から外す。較正もリーグ抜きで取る（物差しを 1 つにする）。
            fit = ~tr.league
            tr.vw[tr.league] = 0.0
            print(f"    V の教師からは外す（方策の頭には使い続ける）。"
                  f"V を学ぶ決定は {int(tr.vw.sum())} 件")
        else:
            # 案 A: 層に「リーグかどうか」を足す。集団ごとに別の較正が当たる。
            tr.stratum = tr.stratum + LEAGUE_OFFSET * tr.league.astype(np.int64)
            va.stratum = va.stratum + LEAGUE_OFFSET * va.league.astype(np.int64)
            print("    較正の層に「リーグかどうか」を足す（集団ごとに別の変換が当たる）")
    calib = None
    if args.lam > 0:
        # V を教師にブートストラップする構成では、保存する版は必ず「検証 v_logloss が
        # 最良のエポック」にする（段階 1 で V は 1 エポック目が最良で以降悪化した・D-064 §4.4）。
        if args.select not in ("best_v", "target_v"):
            raise SystemExit("--lam > 0（V をブートストラップする構成）では --select best_v か target_v を"
                             "指定すること（VALUE_BOOTSTRAP_DESIGN.md §4.4・D-065 §4.1）")
        # 較正は**反復ごとに、その反復の学習データから取り直す**（§3.3）。
        # 反復 1 の探索値は手作り評価の尺度（±10000 の番兵込み・無界）、
        # 反復 2 以降は葉が V なのでおおむね [0,1]＋番兵、と尺度が変わるからである。
        # `fit` は較正を取るのに使う決定（案 B ではリーグを外す）。
        if args.calib_by == "phase_turn":
            calib = calibrate_vsearch_strata(tr.vsearch[fit], tr.z[fit], tr.stratum[fit],
                                             seed=args.seed, scale=args.calib_scale)
        else:
            calib = calibrate_vsearch(tr.vsearch[fit], tr.z[fit], seed=args.seed,
                                      scale=args.calib_scale)
        print(f"探索値の較正[{calib['scale']}]: p = sigmoid({calib['a']:.3f}·clip(v,±{calib['c']:.3f})/{calib['c']:.3f} "
              f"+ {calib['b']:.3f})  n={calib['n']}  番兵の割合 {calib['sentinel_frac']:.3f}")
        if calib.get("strata") is not None:
            print(f"  層別[{calib['by']}]: {len(calib['strata'])} 層で取り、"
                  f"{len(calib['fallback'])} 層は決定が少なく全体の較正に落とした")
            for key, sub in sorted(calib["strata"].items(), key=lambda kv: -kv[1]["n"]):
                print(f"    {sub['name']:<22} n={sub['n']:>7}  対数損失 {sub['logloss']:.4f}"
                      f"（常に平均勝率なら {sub['base']:.4f}）  教師 p の広がり {sub['spread']:.3f}")
            for f in calib["fallback"]:
                print(f"    {f['name']:<22} n={f['n']:>7}  → 全体の較正を当てる")
            print(f"  層別にしたことで、全体 1 本の {calib['logloss_overall']:.4f} → "
                  f"{calib['logloss']:.4f}（下がっていれば層に分けた甲斐がある）")
        print(f"  較正後の対数損失 {calib['logloss']:.4f} vs 「常に平均勝率」{calib['base']:.4f} "
              f"→ {'探索値は勝敗の情報を持つ' if calib['useful'] else '**持たない。--lam は使わないこと**'}")
        print(f"  教師 p の広がり（75%点−25%点） {calib['spread']:.3f}"
              + ("  ← **ほぼ定数。目盛りが番兵に食われている（--calib-scale bulk を試すこと・D-064）**"
                 if calib["spread"] < 0.05 else ""))
        if not calib["useful"]:
            raise SystemExit("較正が基準を下回らない。--lam 0 で回すこと（D-059）")
        tr.set_lam(args.lam, calib)
        # 検証側にも**学習側の較正をそのまま当てる**（valid で取り直さない・D-065 §4.1）。
        # 取り直すと「検証データに合わせた変換」で採点することになり、版の選び方が甘くなる。
        # `v_logloss`（z に対する損失）は target を見ないので、この行で既存の指標は変わらない。
        va.set_lam(args.lam, calib)
    # 入力のスケール（各次元の絶対値の最大）。**まとめて float32 に変換しない**——
    # データ窓で数百万決定を読むと obs だけで数 GB になり、そこで落ちる（実測・D-064）。
    # 分割して同じ値を求める（結果は 1 回で求めたものと厳密に同じ）。
    _mx = np.zeros(tr.obs.shape[1], np.float32)
    for _s0 in range(0, tr.n, 200000):
        _mx = np.maximum(_mx, np.abs(tr.obs[_s0:_s0 + 200000].astype(np.float32)).max(0))
    scale = np.maximum(1.0, _mx)
    # D-132: カードの効果表現の射影（既定は使わない）。目盛りは入力と同じ作法（絶対値の最大・下限 1）。
    proj = proj_scale = proj_info = None
    if getattr(args, "card_profile", False):
        if args.init:
            raise SystemExit("--card-profile と --init は同時に使えない（書き出した重みから射影の成分は戻せない）")
        import card_profile_proj
        proj, proj_info = card_profile_proj.build_projection()
        _pm = np.zeros(proj.shape[1], np.float32)
        _pt = torch.from_numpy(proj).t().contiguous().to_sparse_csr()
        _sc = torch.from_numpy(scale.astype(np.float32))
        for _s0 in range(0, tr.n, 20000):                  # 小分けにする（密に掛けると 1 回で数 GB になり落ちた）
            _x = torch.from_numpy(tr.obs[_s0:_s0 + 20000].astype(np.float32)) / _sc
            _pm = np.maximum(_pm, (_pt @ _x.t()).t().abs().max(0).values.numpy())
        proj_scale = np.maximum(1.0, _pm)
        print(f"カードの効果表現の射影 {proj_info['version']}: 特徴 {proj_info['n_features']} 列"
              f"（アクション 15 塊 × {proj_info['vocab_action']}・キャラ 13 塊 × {proj_info['vocab_chara']}）")
    if args.init:
        model = TwoHead.from_net(Net.load(args.init), scale)
        print(f"init from {args.init}")
    else:
        model = TwoHead(args.hidden, args.depth, args.phead, scale, proj=proj, proj_scale=proj_scale)
    n_params = int(sum(p_.numel() for p_ in model.parameters()))
    print(f"学習する重みの数 {n_params:,}（書き出すネットは射影の有無によらず同じ形）")
    teacher = None
    if args.distil_from:
        # 先生は**学習しない**（重みを固定して、生徒の目標を出すだけ）。
        # 入力の目盛りは生徒と同じものを渡す（同じ obs を同じように見せるため）。
        teacher = TwoHead.from_net(Net.load(args.distil_from), scale)
        for prm in teacher.parameters():
            prm.requires_grad_(False)
        teacher.eval()
        print(f"蒸留: 先生 = {args.distil_from}（幹 {teacher.trunk[0].out_features}・"
              f"π 頭 {teacher.p1.out_features}） → 生徒 幹 {args.hidden}・π 頭 {args.phead}")
    opt = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.wd)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, args.epochs))
    rng = np.random.RandomState(args.seed)
    log = []
    keeper = BestKeeper()
    for ep in range(args.epochs):
        perm = rng.permutation(tr.n)
        t1 = time.time()
        acc_l = 0.0; cnt = 0
        for s in range(0, tr.n, args.bs):
            ids = perm[s:s + args.bs]
            obs, codes, n_acts, chosen, target, z, phase = tr.batch(ids)
            v, sc = model(obs, codes, n_acts)
            if args.league_mode == "drop":
                # **平均の分母も重みの合計にする**。0 埋めして全件で割ると、
                # 外した件数のぶんだけ V の勾配が縮んで「重みを下げた」のと同じになる。
                w = torch.from_numpy(tr.vw[ids])
                lv_each = F.binary_cross_entropy_with_logits(v, target, reduction="none")
                l_v = (lv_each * w).sum() / w.sum().clamp(min=1.0)
            else:
                l_v = F.binary_cross_entropy_with_logits(v, target)
            if teacher is not None:
                with torch.no_grad():
                    t_sc = teacher(obs, codes, n_acts)[1]
                l_p = distil_loss(sc, t_sc, n_acts)
            else:
                l_p = F.cross_entropy(sc, chosen)
            loss = args.wv * l_v + args.wp * l_p
            opt.zero_grad(); loss.backward(); opt.step()
            acc_l += float(loss.detach()) * len(ids); cnt += len(ids)
        sched.step()
        ev = evaluate(model, va, teacher=teacher)
        row = {"epoch": ep + 1, "train_loss": acc_l / cnt, "valid": ev, "sec": time.time() - t1}
        log.append(row)
        keeper.offer(ep + 1, ev, model.state_dict())
        print(f"ep {ep+1}: loss {acc_l/cnt:.4f} | valid v_logloss {ev['v_logloss']:.4f} v_acc {ev['v_acc']:.3f} "
              f"| t_logloss {ev['t_logloss']:.4f} | p_logloss {ev['p_logloss']:.4f} p_acc {ev['p_acc']:.3f} "
              + (f"| 先生と一致 {ev['t_agree']:.3f} " if "t_agree" in ev else "")
              + f"| {row['sec']:.0f}s")
        print("   by phase:", {k: f"{v[0]:.3f}({v[1]})" for k, v in ev["p_acc_by_phase"].items()})
    selected_epoch = args.epochs
    if args.select != "last":
        key = BestKeeper.KEYS[args.select]
        loss, sd, selected_epoch = keeper.pick(args.select)
        model.load_state_dict(sd)
        print(f"--select {args.select}: エポック {selected_epoch} の版を保存する"
              f"（検証 {key}_logloss {loss:.4f}・最後は {log[-1]['valid'][key + '_logloss']:.4f}）")
    net = model.export()
    net.save(args.out)
    # 検算: 書き出した重み（スケール畳み込み後）を numpy で評価しても同じ答えになる
    ids = np.arange(min(64, va.n))
    obs, codes, n_acts, chosen, target, z, phase = va.batch(ids)
    with torch.no_grad():
        v_t = torch.sigmoid(model(obs, codes, n_acts)[0]).numpy()
    v_n = np.array([net.value_of(va.obs[i].astype(np.float32)) for i in ids])
    assert np.abs(v_t - v_n).max() < 1e-4, "export mismatch"
    meta = {"train": args.train, "valid": args.valid, "epochs": args.epochs, "hidden": args.hidden, "depth": args.depth,
            "phead": args.phead, "lr": args.lr, "bs": args.bs, "seed": args.seed, "lam": args.lam, "init": args.init,
            "n_train": int(tr.n), "n_valid": int(va.n), "chance_acc_valid": chance_accuracy(va), "log": log,
            "select": args.select, "selected_epoch": selected_epoch, "calibration": calib,
            "league_mode": args.league_mode, "league_seeds": args.league_seeds,
            "n_league_train": int(tr.league.sum()), "n_v_train": int(tr.vw.sum()),
            "vtarget": args.vtarget, "calib_scale": args.calib_scale, "calib_by": args.calib_by,
            "distil_from": args.distil_from,
            "n_fresh_used": int(tr.n_fresh_used), "wd": args.wd, "wv": args.wv, "wp": args.wp,
            "card_profile": proj_info, "n_params_trained": n_params,
            "n_params_exported": int(sum(w.size + b.size for w, b in net.trunk) + net.value[0].size
                                     + net.value[1].size + sum(w.size + b.size for w, b in net.policy))}
    with open(args.out.replace(".json", ".meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"saved {args.out} ({time.time()-t0:.0f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True); ap.add_argument("--valid", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--init", default=None)
    ap.add_argument("--epochs", type=int, default=6); ap.add_argument("--bs", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3); ap.add_argument("--wd", type=float, default=0.0)
    ap.add_argument("--hidden", type=int, default=256); ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--phead", type=int, default=128)
    ap.add_argument("--wv", type=float, default=1.0); ap.add_argument("--wp", type=float, default=1.0)
    ap.add_argument("--lam", type=float, default=0.0)
    ap.add_argument("--vtarget", choices=["chosen", "max", "fresh"], default="max",
                    help="V の教師に使う探索値（既定 max）。max = その決定で探索が付けた値の最大値"
                         "＝「そこから最善を尽くしたときの価値」。chosen = 実際に選んだ手の値（旧既定）。"
                         "fresh = 選んだ手を別の決定化で取り直した値（楽観の偏りを持たない・"
                         "無いところは max で埋める・D-065 §4.1）")
    ap.add_argument("--calib-by", choices=["none", "phase_turn"], default="none",
                    help="較正を層ごとに取るか（既定 none = 全体で 1 本・従来どおり）。"
                         "phase_turn = phase × 自分のターンかの組ごとに取る。"
                         "決定が 1,000 件未満の層は全体の較正に落とす（D-065 §4.1）")
    ap.add_argument("--calib-scale", choices=["p90", "bulk"], default="p90",
                    help="較正の目盛り c の決め方（既定 p90 = 従来どおり |v| の 90% 点）。"
                         "bulk = 番兵を除いた本体の 90% 点。**番兵が 10%% を超える構成では bulk を使う**"
                         "（D-064 反復 1: p90 のままだと教師がほぼ定数になる）")
    ap.add_argument("--league-seeds", default=None,
                    help="リーグ（対 H・対貪欲）の局面のシードの範囲。`487100-489099` の形で、"
                         "カンマ区切りで複数可。manifest とシード帯の台帳に書いてある範囲を写す")
    ap.add_argument("--league-mode", choices=["keep", "drop", "stratify"], default="keep",
                    help="リーグの局面の扱い（既定 keep = 従来どおり混ぜる）。"
                         "drop = V の損失と較正から外す（方策の頭には使う・D-067 案 B）。"
                         "stratify = 較正の層に「リーグかどうか」を足す（D-067 案 A）。"
                         "**探索値には相手が誰かが入っていない**ので、自己対戦とリーグを "
                         "1 本の較正で当てるのは構造的に無理である（自己対戦 +0.052／リーグ −0.263）")
    ap.add_argument("--select", choices=["last", "best_v", "best_p", "target_v"], default="last",
                    help="保存する版（既定 last）。V を使うなら best_v・π を使うなら best_p。"
                         "target_v = 検証の**教師**（z と探索値の混合）に対する損失で選ぶ"
                         "（best_v は z に対する損失で選ぶ・D-065 §4.1）")
    ap.add_argument("--distil-from", default=None,
                    help="この版の π を**先生**として真似る（蒸留・D-065 便 4 の速度の手当て）。"
                         "--wv 0 と一緒に使う。生徒は --hidden / --phead で小さくする")
    ap.add_argument("--card-profile", action="store_true",
                    help="カードの効果表現の射影を第 1 層に足して学ぶ（D-132。書き出しで畳み込むので Rust の形は同じ）")
    ap.add_argument("--seed", type=int, default=0); ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--max-records", type=int, default=None)
    a = ap.parse_args()
    check_distil_args(a.distil_from, a.wv, a.lam)
    train(a)


if __name__ == "__main__":
    main()
