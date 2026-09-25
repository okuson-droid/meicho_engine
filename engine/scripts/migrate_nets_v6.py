#!/usr/bin/env python3
"""段階1C-c（D-124）: 符号化 v5 の学習済みネットを v6 へ無損失移行する。

v6 は v5 の観測の列を 1 つも動かさず、末尾に信念の要約（N_BELIEF=20）と統一した
`hand_known` の枚数ベクトル（NA）を足しただけである。したがって幹の第 1 層の重みに
**0 の列を末尾に足す**だけで、v6 の入力を与えたときの幹・価値・方策の出力は、
v5 の入力を与えたときと float64 で一致する（新しい列の値が何であっても 0 倍される）。
行動の符号化は変えていない（ACT_DIM は同じ）。

    python scripts/migrate_nets_v6.py results/models/*.json
    python scripts/migrate_nets_v6.py --check results/models/*.json    # 書かずに検算だけ

原本は `<名前>.json.enc5.bak.json` に残す（既にあれば上書きしない）。移行済みのものは飛ばす。
`*.bak.json` と `*.meta.json` は対象から外し、ネットでない JSON（`c1_*.json` など）は飛ばす。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil

import numpy as np

from meicho.encode import ACT_DIM, N_BELIEF, NA, OBS_DIM as NEW_OBS, OBS_DIM_V5 as OLD_OBS

OLD_VERSION, NEW_VERSION = 5, 6
assert NEW_OBS == OLD_OBS + N_BELIEF + NA


def dense(layer, x, relu=True):
    y = np.asarray(layer["w"], float) @ x + np.asarray(layer["b"], float)
    return np.maximum(y, 0) if relu else y


def trunk(net, x):
    for layer in net["trunk"]:
        x = dense(layer, x)
    return x


def head(layers, x):
    for layer in layers[:-1]:
        x = dense(layer, x)
    return dense(layers[-1], x, relu=False)


def migrate(path, check=False):
    with open(path, encoding="utf-8") as f:
        old = json.load(f)
    if not isinstance(old, dict) or "trunk" not in old or "encoding_version" not in old:
        print(f"{os.path.basename(path)}: skip（ネットではない）")
        return "skip"
    if old.get("encoding_version") == NEW_VERSION and old.get("obs_dim") == NEW_OBS:
        print(f"{os.path.basename(path)}: already v6")
        return "already"
    got = (old.get("encoding_version"), old.get("obs_dim"), old.get("act_dim"))
    assert got == (OLD_VERSION, OLD_OBS, ACT_DIM), f"{path}: v5 のネットではない {got}"
    new = json.loads(json.dumps(old))
    w = np.asarray(old["trunk"][0]["w"], dtype=np.float64)
    assert w.shape[1] == OLD_OBS, w.shape
    new["trunk"][0]["w"] = np.concatenate([w, np.zeros((w.shape[0], NEW_OBS - OLD_OBS))], axis=1).tolist()
    new.update(obs_dim=NEW_OBS, encoding_version=NEW_VERSION)
    # 検算: 新しい列に**でたらめな値**を入れても出力が変わらないこと（0 倍されること）を確かめる
    rng = np.random.RandomState(20260922)
    worst = 0.0
    for _ in range(100):
        xo = rng.randint(-8, 9, OLD_OBS).astype(float)
        xn = np.concatenate([xo, rng.randint(-8, 9, NEW_OBS - OLD_OBS).astype(float)])
        ho, hn = trunk(old, xo), trunk(new, xn)
        worst = max(worst, float(np.max(np.abs(ho - hn))))
        if old.get("value"):
            vals = old["value"] if isinstance(old["value"], list) else [old["value"]]
            valn = new["value"] if isinstance(new["value"], list) else [new["value"]]
            worst = max(worst, float(np.max(np.abs(head(vals, ho) - head(valn, hn)))))
        if old.get("policy"):
            a = rng.randint(0, 2, ACT_DIM).astype(float)
            worst = max(worst, float(np.max(np.abs(head(old["policy"], np.concatenate([ho, a]))
                                                   - head(new["policy"], np.concatenate([hn, a]))))))
    assert worst == 0.0, worst
    if not check:
        backup = path + ".enc5.bak.json"          # 前回（v4→v5）と同じ付け方: `<名前>.json.enc5.bak.json`
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(new, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{os.path.basename(path)}: {'checked' if check else 'migrated'} max_abs={worst:.3g}")
    return "checked" if check else "migrated"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+")
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    paths = []
    for pat in a.paths:
        paths.extend(glob.glob(pat) or [pat])
    paths = sorted(q for q in paths if not q.endswith(".bak.json") and not q.endswith(".meta.json"))
    bad = []
    for path in paths:
        try:
            migrate(path, a.check)
        except AssertionError as e:          # 1 本が想定外でも、残りの移行は続ける
            print(f"{os.path.basename(path)}: NG {e}")
            bad.append(path)
    if bad:
        raise SystemExit(f"移行できなかったもの {len(bad)} 本（上の NG の行）")


if __name__ == "__main__":
    main()
