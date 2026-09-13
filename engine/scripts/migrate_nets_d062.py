# -*- coding: utf-8 -*-
"""D-062: AC-001 削除にともなう学習済みネットの移行（ENCODING_VERSION 2 → 3）。

## なぜ移行が要るか

`meicho/encode.py` は観測を「カード1種につき1つの枠」を並べた固定長の数列にする。
カードが1種消えると枠の数が変わり、**保存済みのネットの入力の形が合わなくなる**。
形が合わないまま読ませると、うまくいけば例外で落ちるが、最悪の場合は
別のカードの枠を読んでしまい、**黙って壊れた判断をする**。

## なぜ「値は変わらない」と言えるか

消した AC-001 はどのデッキリストにも入っていない。したがって

- 枚数ベクトルの AC-001 の枠は**常に 0**
- one-hot の AC-001 の枠も**常に 0**
- 行動符号のカード枠も AC-001 を指すことはない

入力が常に 0 の枠は、そこに掛かる重みが何であっても出力に寄与しない。
よって**その列を削るだけで、ネットの出力は完全に同じ**になる（数学的に厳密）。
この移行は「学習し直し」ではなく「使われていない列の切り落とし」である。

## 削る位置

旧: NA=35（AC-001 の添字は 0）/ NC=18 / N_SCALAR=62
- 観測 608 = 62 + 35×12 + 18×7 → 62 + 35b + 0（b=0..11）の12列を削る
- 行動 113 = 19 + 35 + 18 + 3 + 2 + 1 + 35 → 19+0 と 19+35+18+3+2+1+0=78 の2列を削る
- 方策の第1層の入力は [幹の出力 256 ⊕ 行動 113] なので 256 を足した位置を削る

使い方:
    python3 scripts/migrate_nets_d062.py results/models/drl_sd001_s1.json ...
    （--check だけ付けると、書き換えずに検算のみ行う）
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

OLD_NA, NEW_NA = 35, 34
NC = 18
N_SCALAR = 62
N_TYPES = 19
REMOVED = 0                      # AC-001 の旧添字
OLD_OBS = N_SCALAR + OLD_NA * 12 + NC * 7          # 608
NEW_OBS = N_SCALAR + NEW_NA * 12 + NC * 7          # 596
OLD_ACT = N_TYPES + OLD_NA + NC + 3 + 2 + 1 + OLD_NA   # 113
NEW_ACT = N_TYPES + NEW_NA + NC + 3 + 2 + 1 + NEW_NA   # 111

OBS_DROP = [N_SCALAR + OLD_NA * b + REMOVED for b in range(12)]
ACT_DROP = [N_TYPES + REMOVED,
            N_TYPES + OLD_NA + NC + 3 + 2 + 1 + REMOVED]


def _drop_cols(w: list, cols: list) -> list:
    a = np.asarray(w, dtype=np.float64)
    return np.delete(a, cols, axis=1).tolist()


def migrate(path: str, check_only: bool = False) -> None:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    if d["obs_dim"] == NEW_OBS and d["act_dim"] == NEW_ACT:
        print(f"  {os.path.basename(path)}: 既に移行済み（obs={NEW_OBS} act={NEW_ACT}）")
        return
    assert d["obs_dim"] == OLD_OBS, f"想定外の obs_dim: {d['obs_dim']}"
    assert d["act_dim"] == OLD_ACT, f"想定外の act_dim: {d['act_dim']}"
    assert d["encoding_version"] == 2, f"想定外の encoding_version: {d['encoding_version']}"

    hidden = len(d["trunk"][-1]["w"])
    old_trunk0 = np.asarray(d["trunk"][0]["w"], dtype=np.float64)
    old_pol0 = np.asarray(d["policy"][0]["w"], dtype=np.float64)
    assert old_trunk0.shape[1] == OLD_OBS, old_trunk0.shape
    assert old_pol0.shape[1] == hidden + OLD_ACT, (old_pol0.shape, hidden)

    new = json.loads(json.dumps(d))          # 深いコピー
    new["trunk"][0]["w"] = _drop_cols(d["trunk"][0]["w"], OBS_DROP)
    new["policy"][0]["w"] = _drop_cols(d["policy"][0]["w"],
                                       [hidden + c for c in ACT_DROP])
    new["obs_dim"] = NEW_OBS
    new["act_dim"] = NEW_ACT
    new["encoding_version"] = 3

    # --- 検算: 削った枠を 0 にした入力なら、出力が旧と（丸め誤差の範囲で）一致すること ---
    #
    # 実数の計算としては**完全に**一致する（削った列に掛かる入力が常に 0 だから）。
    # ただし実際は float32 で計算しており、列を減らすと足し算の順序が変わるため
    # 最後の桁に丸め誤差が出る。ここでは相対 1e-5 を上限として、
    # 「差が丸め誤差の大きさに収まっている」ことを確認する。
    # 判断（合法手の中でどれを選ぶか）が変わらないことは、この後の
    # `arena_rs.series_rs_digest` による前後比較で別途確認する。
    rng = np.random.RandomState(20260831)
    worst_h = worst_p = 0.0
    for trial in range(200):
        x_old = rng.randint(-8, 9, size=OLD_OBS).astype(np.float64)
        for c in OBS_DROP:
            x_old[c] = 0.0
        x_new = np.delete(x_old, OBS_DROP)
        h_old = _forward_trunk(d, x_old)
        h_new = _forward_trunk(new, x_new)
        worst_h = max(worst_h, _rel(h_old, h_new))
        assert worst_h < 1e-5, f"幹の出力が丸め誤差の範囲を超えた (trial={trial}, rel={worst_h:.3g})"

        a_old = rng.randint(0, 2, size=OLD_ACT).astype(np.float64)
        for c in ACT_DROP:
            a_old[c] = 0.0
        a_new = np.delete(a_old, ACT_DROP)
        worst_p = max(worst_p, _rel(_forward_policy(d, h_old, a_old),
                                    _forward_policy(new, h_new, a_new)))
        assert worst_p < 1e-5, f"方策の出力が丸め誤差の範囲を超えた (trial={trial}, rel={worst_p:.3g})"

    if check_only:
        print(f"  {os.path.basename(path)}: 検算のみ（書き換えなし・"
              f"幹の相対差 {worst_h:.2e} / 方策の相対差 {worst_p:.2e}）")
        return

    with open(path, "w", encoding="utf-8") as f:
        json.dump(new, f)
    print(f"  {os.path.basename(path)}: 移行完了 "
          f"obs {OLD_OBS}→{NEW_OBS} / act {OLD_ACT}→{NEW_ACT} / enc 2→3"
          f"（200 例で 幹 {worst_h:.2e} / 方策 {worst_p:.2e} の相対差＝丸め誤差の範囲）")


def _rel(a, b) -> float:
    """相対差（分母は値の大きさ。ゼロ近傍で暴れないよう 1.0 を下限に取る）。"""
    a = np.asarray(a, np.float64); b = np.asarray(b, np.float64)
    scale = np.maximum(np.maximum(np.abs(a), np.abs(b)), 1.0)
    return float(np.max(np.abs(a - b) / scale))


def _dense(layer):
    return (np.asarray(layer["w"], np.float32), np.asarray(layer["b"], np.float32))


def _forward_trunk(d, x):
    h = np.asarray(x, np.float32)
    for l in d["trunk"]:
        w, b = _dense(l)
        h = np.maximum(w @ h + b, 0.0).astype(np.float32)
    return h


def _forward_policy(d, h, a):
    v = np.concatenate([h, np.asarray(a, np.float32)])
    n = len(d["policy"])
    for i, l in enumerate(d["policy"]):
        w, b = _dense(l)
        v = (w @ v + b).astype(np.float32)
        if i + 1 < n:
            v = np.maximum(v, 0.0)
    return v


def main(argv: list) -> int:
    check = "--check" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 1
    print("D-062 ネット移行（AC-001 の列を落とす）")
    for p in paths:
        migrate(p, check_only=check)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
