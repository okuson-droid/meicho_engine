"""K 本の V を幅 K 倍の 1 本の全結合ネットに組み直す（段階3 の土台の V・D-132 追記 5・D-133）。

    python3 experiments/ensemble_net.py --out results/models/s2v_id_ens3.json \\
        results/models/s2v_id_s0.json results/models/s2v_id_s1.json results/models/s2v_id_s2.json

検査は `tests/test_ensemble_v.py`（N-1〜N-6）。

Rust の `value_net` はネット 1 本のパスしか受けない。そこで K 本（幹の深さと幅が同じもの）を:

- 幹の第 1 層: K 本の重みの行を縦に並べる（K·H × OBS_DIM）
- 幹の第 2 層以降: ブロック対角（K·H × K·H・ブロックの外は 0）
- 価値の頭: K 本の頭を横に並べ、重みと偏りに 1/K を掛ける
- 方策の頭: 空（葉にしか使わない。`rust/src/net.rs` は空なら方策なしとして読む）

と組むと、出力は **K 本のロジットの平均の sigmoid** になる（勝率の平均ではない・D-132 追記 5 の推し）。
Rust も符号化も変えない。費用は第 1 層が K 倍・第 2 層以降が K² 倍（ブロックの外の 0 も密に掛けるため）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from meicho.drlnet import Net                                           # noqa: E402

VERSION = "ensnet-1"


def _check(nets) -> None:
    if not nets:
        raise ValueError("ネットが 1 本も無い")
    a = nets[0]
    for n in nets:
        if n.value is None:
            raise ValueError("価値の頭の無いネットは束ねられない")
        if (n.obs_dim, n.act_dim, n.encoding_version) != (a.obs_dim, a.act_dim, a.encoding_version):
            raise ValueError("符号化の版または次元が違う")
        if len(n.trunk) != len(a.trunk):
            raise ValueError("幹の深さが違う")
        for (w, b), (wa, ba) in zip(n.trunk, a.trunk):
            if w.shape != wa.shape or b.shape != ba.shape:
                raise ValueError(f"幹の形が違う {w.shape} / {wa.shape}")
        if n.value[0].shape != a.value[0].shape:
            raise ValueError("価値の頭の形が違う")


def combine(nets) -> Net:
    """K 本を幅 K 倍の 1 本に組み直す（出力はロジットの平均の sigmoid）。"""
    _check(nets)
    k = len(nets)
    trunk = []
    for li in range(len(nets[0].trunk)):
        ws = [n.trunk[li][0] for n in nets]
        bs = [n.trunk[li][1] for n in nets]
        if li == 0:
            w = np.concatenate(ws, 0)
        else:
            o, i = ws[0].shape
            w = np.zeros((k * o, k * i), np.float32)
            for j, wj in enumerate(ws):
                w[j * o:(j + 1) * o, j * i:(j + 1) * i] = wj
        trunk.append((w.astype(np.float32), np.concatenate(bs).astype(np.float32)))
    vw = (np.concatenate([n.value[0] for n in nets], 1) / k).astype(np.float32)
    vb = (np.sum([n.value[1] for n in nets], 0) / k).astype(np.float32)
    a = nets[0]
    return Net(trunk, (vw, vb), [], a.obs_dim, a.act_dim, a.encoding_version)


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("nets", nargs="+")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    nets = [Net.load(p) for p in args.nets]
    ens = combine(nets)
    ens.save(args.out)
    meta = {"version": VERSION, "decision": "D-133", "combine": "mean_logit",
            "members": [{"path": os.path.relpath(p, os.path.dirname(os.path.abspath(args.out))),
                         "sha": _sha(p)} for p in args.nets],
            "hidden": int(ens.trunk[-1][0].shape[0]), "sha": _sha(args.out)}
    with open(args.out.replace(".json", ".meta.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
