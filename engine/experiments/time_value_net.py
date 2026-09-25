"""V の葉の費用の実測（D-133）。同じシード・同じ課題で、葉の V だけを替えて 1 局の時間を比べる。

    python3 experiments/time_value_net.py --arm s2=results/models/s2v_id_s2.json \
        --arm ens3=results/models/s2v_id_ens3.json --seed0 843000 --n 25 --out results/drl/s3_ens_cost_v1.json

課題は調整デッキ 4 つの対角ブロック（ミラー 4）の先頭 n 局。相手は素 planner。候補の探索器は
`eval_s2_repr` と同じ（`record_mix.NETFREE` ＋ `value_net`）。帯は diag（843000..843999）だけを受ける。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)


def main(argv=None):
    import meicho_rs as rs
    from arena import load_deck, matchup_config
    from arena_rs import PLANNER, ensure_cards
    from eval_s2_repr import _arm_spec, load_env, tune_decks
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True)
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not (843000 <= args.seed0 and args.seed0 + args.n - 1 <= 843998):
        raise SystemExit("帯 843000..843998（diag・D-133）の中で回すこと")
    ensure_cards()
    decks = tune_decks(load_env())
    data = {"version": "vcost-1", "decision": "D-133", "seed0": args.seed0, "n": args.n,
            "workers": args.workers, "host_cpus": os.cpu_count(), "arms": {}}
    if os.path.exists(args.out):
        data = json.load(open(args.out, encoding="utf-8"))
    for a in args.arm:
        name, _, path = a.partition("=")
        if name in data["arms"]:
            continue
        rec = {"path": path or None, "blocks": {}}
        for d in decks:
            da = load_deck(d)
            cfg = matchup_config(da, da)
            cfg.validate()
            t = time.time()
            res = rs.series(cfg.chara_decks, cfg.action_decks, _arm_spec(name, path or None, da["action_deck"]),
                            PLANNER(da["action_deck"]), args.seed0, args.n, args.workers, 200, True)
            rec["blocks"][d] = {"sec": time.time() - t,
                                "score": [(0.5 if r[0] is None else float(bool(r[0]))) for r in res]}
            print(name, d, f"{rec['blocks'][d]['sec']:.1f} 秒", flush=True)
        rec["sec_total"] = sum(b["sec"] for b in rec["blocks"].values())
        rec["sec_per_game"] = rec["sec_total"] / (args.n * len(decks))
        data["arms"][name] = rec
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False)
        print(name, f"1 局 {rec['sec_per_game']:.2f} 秒（壁時計・workers {args.workers}）", flush=True)


if __name__ == "__main__":
    main()
