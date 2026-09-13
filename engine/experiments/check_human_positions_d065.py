"""便 2 の候補（a1／a5／a15）が対人 2 局の決定的な対抗で何を選ぶかを見る（便 1 の新しい `meicho/` が要る）。

`HUMAN_GAMES_20260903_NOTES.md` §3 末尾。結果（2026-09-03）: 5 通りすべてで g001 T9 はパス、g002 T10 は音の形・回避——
便 2 のつまみは対抗の相手モデルに触れないので、champion を a15 に替えてもこの型の負けは残る。

使い方:
    python3 experiments/check_human_positions_d065.py
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                                        # noqa: E402
from meicho.drlnet import resolve_model                                           # noqa: E402
from meicho.planner import PlannerAgent                                           # noqa: E402
from verify_lethal_human import act_name, last_clash_state                        # noqa: E402
from webapp import record as wrec                                                 # noqa: E402
import champion as chmod                                                          # noqa: E402

A1 = {"choice_phases": True, "solo_samples": 4}
A5 = {"policy_net": "drl_sd001_vb3.json", "policy_scope": "proxy"}
VARIANTS = [("champion", {}), ("a1", A1), ("a5", A5), ("a15", {**A1, **A5}), ("a15+samples12", {**A1, **A5, "samples": 12})]


def _kw(extra: dict) -> dict:
    k = {**chmod.kwargs_for("SD001"), **extra}
    for key in ("value_net", "opp_policy_net", "policy_net"):
        if key in k:
            k[key] = resolve_model(k[key])
    return k


def main() -> int:
    deck = load_deck("SD001")
    cfg, pool = mirror_config(deck), deck["action_deck"]
    path = os.path.join(_HERE, "..", "results", "human_games", "2026-09.jsonl")
    with open(path, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    for rec in [r for r in recs if r["opponent"]["name"] == "planner_vb3"]:
        out = wrec.replay(rec, cfg, keep_states=True)
        ai = 1 - rec["human_seat"]
        s = last_clash_state(out["states"])
        for label, extra in VARIANTS:
            ag = PlannerAgent(rec["opponent"]["seed"], opp_decklist=pool, **_kw(extra))
            print(f"{rec['game_id']} T{s.turn_no} {label:16s} 選ぶ={act_name(s, ai, ag.act(s, ai))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
