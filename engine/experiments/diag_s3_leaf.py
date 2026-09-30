"""段階3 項目 4（探索の分布）の 4-a で対局を回す部分（D-151・`GENERALIST_STAGE3_ITEM4_DESIGN_20260930.md` §3.1）。

    # 4-a-T: 反復 1 の検証の記録の組み合わせ表から、局のシードの対 (2m, 2m+1) で m mod M == R の局だけを抜いた表
    python3 experiments/diag_s3_leaf.py subset --schedule results/drl/s3_it1_val_schedule.json \
        --keep-pairs 5:0 --out results/drl/s3_item4_T_schedule.json
    #   → plan_chunks.py で塊に割り、record_mix.py --leaf-cap 8 で回す（打ち方は元の記録と同じ・全件照合する）

    # 4-a-E: 評価と同じ設定（候補 NETFREE＋葉 V_1 対 素 planner・τ = 0）で候補の席だけ記録し葉を書き出す
    python3 experiments/diag_s3_leaf.py e --value-net results/models/s3v1_id_ens3.json \
        --seed0 860000 --n 7 --out <置き場>/e --budget-sec 300

集計は `diag_s3_desk.py --leaf`（判定の規則もそちら）。この道具は判定をしない。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, _HERE)

TOOL_VERSION = "s3leaf-1"
LEAF_CAP = 8                                  # 設計書 §3.1: 1 決定あたり最大 8 個


def parse_keep_pairs(spec: str) -> tuple[int, int]:
    m, _, r = spec.partition(":")
    m, r = int(m), int(r)
    if m < 1 or not 0 <= r < m:
        raise SystemExit(f"--keep-pairs は M:R（M ≥ 1・0 ≤ R < M）: {spec}")
    return m, r


def subset(sch: dict, m: int, r: int) -> dict:
    """局のシードの対 (2k, 2k+1) で k mod m == r の局だけを、2 局ずつの小ブロックに割って残す。

    小ブロックは親ブロックの欄をそのまま持ち、`seed0`・`n` を差し替え、`parent` を足す（`plan_chunks.py` と同じ作法）。
    局はシードだけで決まるので、割っても記録は元と同じである（D-141 §3）。
    """
    out = copy.deepcopy(sch)
    blocks = []
    for i, b in enumerate(sch["blocks"]):
        lo, hi = int(b["seed0"]), int(b["seed0"]) + int(b["n"])
        if lo % 2 or hi % 2:
            raise SystemExit(f"blocks[{i}] のシード {lo}..{hi - 1} が対 (2k, 2k+1) で割り切れない")
        for s in range(lo, hi, 2):
            if (s // 2) % m == r:
                blocks.append(dict(b, seed0=s, n=2, parent=b.get("parent", i)))
    if not blocks:
        raise SystemExit("残る局が無い")
    out["blocks"] = blocks
    out["name"] = f"{sch.get('name')}.keep{m}_{r}"
    out["keep_pairs"] = {"m": m, "r": r, "source_name": sch.get("name")}
    return out


def check_diag_band(seed0: int, n: int) -> dict:
    """4-a-E は kind=diag の帯でだけ回す（学習にも強さの評価にも使わない帯・設計書 §7.1）。"""
    with open(os.path.join(_HERE, "seed_bands.json"), encoding="utf-8") as f:
        led = json.load(f)
    for s in (seed0, seed0 + n - 1):
        for b in led["bands"]:
            if b["start"] <= s <= b["end"]:
                if b.get("kind") != "diag":
                    raise SystemExit(f"帯 {b['start']}..{b['end']} は kind={b.get('kind')}。4-a-E は diag の帯でだけ回す")
                break
        else:
            raise SystemExit(f"シード {s} は seed_bands.json に未登録（D-028）")
    return {"seed0": seed0, "n": n}


def run_e(args) -> dict:
    """4-a-E。調整デッキ 16 ブロック × n 局・全ブロックで同じシード。ブロックごとに別の記録と葉のファイル。"""
    import meicho_rs as rs
    from arena import load_deck, matchup_config
    from arena_rs import PLANNER, ensure_cards
    from eval_s2_repr import blocks, load_env, tune_decks
    from record_mix import NETFREE
    check_diag_band(args.seed0, args.n)
    ensure_cards()
    if "leaf_dump" not in rs.features():
        raise SystemExit("入っている meicho_rs が古い（leaf_dump が無い）。再ビルドすること（D-151）")
    path = os.path.abspath(args.value_net)
    with open(path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()[:16]
    decks = tune_decks(load_env(args.env) if args.env else None)
    man_path = args.out + ".manifest.json"
    man = {"tool": "experiments/diag_s3_leaf.py e", "version": TOOL_VERSION, "decision": "D-151",
           "decks": decks, "seed0": args.seed0, "n": args.n, "leaf_cap": args.leaf_cap,
           "value_net": os.path.relpath(path, ROOT), "value_net_sha16": sha, "opponent": "planner",
           "blocks": []}
    if os.path.exists(man_path):
        with open(man_path, encoding="utf-8") as f:
            prev = json.load(f)
        for k in ("decks", "seed0", "n", "leaf_cap", "value_net_sha16"):
            if prev[k] != man[k]:
                raise SystemExit(f"条件が前回と違う（{k}）。別の --out に")
        man = prev
    done = {(b["deck_a"], b["deck_b"]) for b in man["blocks"]}
    t0 = time.time()
    for i, (a, b) in enumerate(blocks(decks)):
        if (a, b) in done:
            continue
        if time.time() - t0 > args.budget_sec:
            print(f"予算 {args.budget_sec} 秒を超えたので止める（続きは同じコマンドで再開）")
            break
        da, db_ = load_deck(a), load_deck(b)
        cfg = matchup_config(da, db_)
        cfg.validate()
        # 評価（eval_s2_repr.run）と同じ組: 候補は NETFREE＋葉の V・相手は素 planner・opp_from_seat=True
        spec_a = PLANNER(db_["action_deck"], **NETFREE, value_net=path)
        spec_b = PLANNER(da["action_deck"])
        t = time.time()
        res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, spec_a, spec_b, args.seed0, args.n,
                                      f"{args.out}.b{i}", args.workers, 200, True, False, opp_from_seat=True,
                                      leaf_dump=f"{args.out}.b{i}.leaf", leaf_cap=args.leaf_cap)
        man["blocks"].append({"i": i, "deck_a": a, "deck_b": b, "seed0": args.seed0, "n": args.n,
                              "files": files,
                              "leaf_files": [f"{args.out}.b{i}.leaf.{w}" for w in range(max(1, args.workers))],
                              "results": [[None if r[0] is None else bool(r[0]), int(r[1])] for r in res],
                              "seconds": time.time() - t})
        with open(man_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(man, f, ensure_ascii=False, indent=1)
        print(f"{a} 対 {b}: {time.time() - t:.0f} 秒", flush=True)
    return man


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("subset")
    s.add_argument("--schedule", required=True)
    s.add_argument("--keep-pairs", required=True, help="M:R（局のシードの対 (2k, 2k+1) で k mod M == R を残す）")
    s.add_argument("--out", required=True)
    e = sub.add_parser("e")
    e.add_argument("--value-net", required=True)
    e.add_argument("--env", default=None, help="既定は eval_s2_repr の DEFAULT_ENV（評価と同じ調整デッキ）")
    e.add_argument("--seed0", type=int, required=True)
    e.add_argument("--n", type=int, required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--workers", type=int, default=4)
    e.add_argument("--leaf-cap", type=int, default=LEAF_CAP)
    e.add_argument("--budget-sec", type=float, default=300.0)
    args = ap.parse_args(argv)
    if args.cmd == "subset":
        with open(args.schedule, encoding="utf-8") as f:
            sch = json.load(f)
        out = subset(sch, *parse_keep_pairs(args.keep_pairs))
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"{len(out['blocks'])} ブロック・{sum(b['n'] for b in out['blocks'])} 局 → {args.out}")
        return out
    return run_e(args)


if __name__ == "__main__":
    main()
