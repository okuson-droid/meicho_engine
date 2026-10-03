"""段階4 便 4-A3 の段 0（机上・判定なし）: 追加学習で V はどれだけ動いたか（D-158・設計書 §4.1）。

    python3 experiments/diag_s4_move.py --valid <R>/target_val.c000 --models <M> \\
        --nets G0=s2v_id G1000=s4G1000 S0=s4S S1000=s4S1000 S3000=s4S3000 \\
        --moves G0:G1000 S0:S1000 --out results/drl/s4/a3_stage0.json

`--nets NAME=STEM` の STEM は部品 `STEM_s0`・`STEM_s1`・`STEM_s2` の共通部分。部品は `--models` の置き場、
無ければ `results/models` から読む。束ねた V は部品のロジットの平均の sigmoid として計算する
（`ensemble_net.py` で束ねたものと同じ値・`diag_s3_desk.py` と同じ作法）。

出すもの（検証の記録の全決定）:

- 検証 v_logloss（勝敗 z に対する対数損失）: 部品ごと・束ねたもの・フェイズ別（action・choice・clash・rush ほか）
- 学習の記録（`.meta.json`）の選んだエポックの検証 v_logloss（同じ検証の記録で学んだものだけ。照合用）
- 出力の動き M: `--moves A:B` ごとに、同じ決定で A と B のロジットの差の絶対値の平均。部品は同じ番号どうし、
  束ねたものは平均のロジットどうし
- 読み方の目安（判定ではない・設計書 §4.1）: L(G0) − L(G1000) < 0.002 かつ M(G) < M(S)/2 → H-a 寄り、
  L(G0) − L(G1000) ≥ 0.002 → H-b 寄り

検査は `tests/test_stage4_a3_tools.py`。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, _HERE)

from meicho.drl_data import read_records                          # noqa: E402
from meicho.drlnet import Net                                     # noqa: E402
from diag_s3_desk import PHASE_NAMES, logloss, net_logit, sigmoid  # noqa: E402

TOOL_VERSION = "s4move-1"
MODELS = os.path.join(ROOT, "results", "models")
META_DIRS = (os.path.join(ROOT, "results", "drl", "s4", "models"),)
K_PARTS = 3
RULE_DL = 0.002               # §4.1 の目安: 当てはまりが良くなったとみなす幅


def files_of(prefix: str) -> list:
    import drl_train
    return drl_train.files_of(prefix)


def part_paths(stem: str, models: str | None, k: int = K_PARTS) -> list:
    out = []
    for i in range(k):
        name = f"{stem}_s{i}.json"
        cands = ([os.path.join(models, name)] if models else []) + [os.path.join(MODELS, name)]
        hit = next((c for c in cands if os.path.exists(c)), None)
        if hit is None:
            raise SystemExit(f"部品が見つからない: {name}（{cands}）")
        out.append(hit)
    return out


def meta_v_logloss(path: str, valid: str, n_valid: int):
    """同じ検証の記録で学んだネットなら、選んだエポックの検証 v_logloss。違えば None。"""
    base = os.path.basename(path).replace(".json", ".meta.json")
    for d in (os.path.dirname(path),) + META_DIRS:
        mp = os.path.join(d, base)
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as f:
                m = json.load(f)
            same = (os.path.basename(str(m.get("valid", "")).rstrip("/")) == os.path.basename(valid.rstrip("/"))
                    and m.get("n_valid") == n_valid)
            if not same:
                return None
            ep = m.get("selected_epoch") or m["epochs"]
            return float(m["log"][ep - 1]["valid"]["v_logloss"])
    return None


def by_phase(p: np.ndarray, z: np.ndarray, phase: np.ndarray) -> dict:
    out = {}
    for k in np.unique(phase).tolist():
        m = phase == k
        out[PHASE_NAMES[k]] = {"n": int(m.sum()), "v_logloss": logloss(p[m], z[m])}
    return out


def move(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(np.asarray(a, np.float64) - np.asarray(b, np.float64)).mean())


def run(valid: str, nets: dict, moves: list, models: str | None = None) -> dict:
    recs = read_records(files_of(valid))
    obs = recs.obs.astype(np.float32)
    z = np.asarray(recs.z, np.float64)
    phase = np.asarray(recs.phase)
    logits, out_nets = {}, {}
    for name, stem in nets.items():
        paths = part_paths(stem, models)
        parts, pl = [], []
        for pth in paths:
            lg = net_logit(Net.load(pth), obs)
            pl.append(lg)
            p = sigmoid(lg)
            parts.append({"path": os.path.relpath(pth, ROOT) if pth.startswith(ROOT) else os.path.basename(pth),
                          "v_logloss": logloss(p, z), "meta_v_logloss": meta_v_logloss(pth, valid, recs.n),
                          "by_phase": by_phase(p, z, phase)})
        ens = np.mean(np.stack([x.astype(np.float64) for x in pl]), 0)
        pe = sigmoid(ens)
        logits[name] = (pl, ens)
        out_nets[name] = {"stem": stem, "parts": parts,
                          "parts_mean_v_logloss": float(np.mean([q["v_logloss"] for q in parts])),
                          "ens": {"v_logloss": logloss(pe, z), "by_phase": by_phase(pe, z, phase)}}
    out_moves = {}
    for a, b in moves:
        (pa, ea), (pb, eb) = logits[a], logits[b]
        out_moves[f"{a}:{b}"] = {"parts": [move(x, y) for x, y in zip(pa, pb)], "ens": move(ea, eb),
                                 "parts_mean": float(np.mean([move(x, y) for x, y in zip(pa, pb)]))}
    res = {"tool_version": TOOL_VERSION, "valid": valid, "n_valid": int(recs.n),
           "base_logloss": logloss(np.full(len(z), z.mean()), z), "nets": out_nets, "moves": out_moves}
    res["reading"] = reading(res)
    return res


def reading(res: dict):
    """§4.1 の読み方の目安（判定ではない）。G0・G1000・S0・S1000 が揃っているときだけ。"""
    n, mv = res["nets"], res["moves"]
    if not {"G0", "G1000"} <= set(n) or "G0:G1000" not in mv or "S0:S1000" not in mv:
        return None
    dl = n["G0"]["ens"]["v_logloss"] - n["G1000"]["ens"]["v_logloss"]
    mg, ms = mv["G0:G1000"]["ens"], mv["S0:S1000"]["ens"]
    if dl >= RULE_DL:
        lean = "H-b 寄り"
    elif mg < ms / 2:
        lean = "H-a 寄り"
    else:
        lean = "どちらとも言えない"
    return {"dL_G": dl, "M_G": mg, "M_S": ms, "M_ratio": mg / ms if ms else None, "lean": lean,
            "rule": f"dL_G >= {RULE_DL} → H-b 寄り／dL_G < {RULE_DL} かつ M_G < M_S/2 → H-a 寄り（判定ではない）"}


def parse_kv(items: list) -> dict:
    out = {}
    for it in items:
        k, _, v = it.partition("=")
        if not k or not v:
            raise SystemExit(f"--nets は NAME=STEM の形: {it}")
        out[k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--valid", required=True, help="検証の記録の接頭辞（drl_train の --valid と同じ）")
    ap.add_argument("--nets", nargs="+", required=True, help="NAME=STEM（部品は STEM_s0..s2）")
    ap.add_argument("--moves", nargs="*", default=[], help="A:B（出力の動き M を出す組）")
    ap.add_argument("--models", default=None, help="部品の置き場（無ければ results/models）")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    nets = parse_kv(a.nets)
    moves = [tuple(m.split(":", 1)) for m in a.moves]
    for x, y in moves:
        if x not in nets or y not in nets:
            raise SystemExit(f"--moves {x}:{y} の名前が --nets に無い")
    res = run(a.valid, nets, moves, a.models)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"n_valid {res['n_valid']}  base {res['base_logloss']:.4f}")
    for name, r in res["nets"].items():
        pv = " ".join(f"{q['v_logloss']:.4f}" + (f"(meta {q['meta_v_logloss']:.4f})" if q["meta_v_logloss"] is not None else "")
                      for q in r["parts"])
        print(f"{name:>8}: ens {r['ens']['v_logloss']:.4f} | parts {pv}")
    for k, m in res["moves"].items():
        print(f"M {k}: ens {m['ens']:.4f} | parts " + " ".join(f"{x:.4f}" for x in m["parts"]))
    if res["reading"]:
        print("reading:", res["reading"])
    return res


if __name__ == "__main__":
    main()
