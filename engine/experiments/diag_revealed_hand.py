"""便 R の診断: 「公開して手札に入ったカード」を AI の知識に入れていない損はどれほどか（D-118 案）。

## 何を測るか

`observe` の `opp.hand_known` は、スキャン（`peek_opponent_hand`）と B-9 の手札公開で見たカードしか持たない。
`reveal_top_to_hand`・`reveal_n_take_matching`・`search_deck` で**公開してから手札に加えた**カードは、
両者に見えているのに `hand_known` に入らない（アプリの M1 仕様書 §10・送り箱 TE-10）。

この道具は**エンジンを一切変えずに**、外から理想の知識を追いかけて比べる:

- base: いまの `observe(s, pi)["opp"]["hand_known"]`
- aug : base と「公開して相手の手札に入ったカード（いまも手札にあるぶん）」の和（多重集合の max）
  —— 追いかけ方はエンジンと同じく「本当の手札との積」で忘れる。SD001/SD02 には手札から見えない所へ
  出る道（`opp_hand_random_to_deck_bottom`）が無いので、積で忘れても漏れは起きない（TE-10 は BP01 だけの話）

測る場面は pi の**対抗の提出**（`CLASH_SUBMIT` で pi が決定者）と、pi の決定全部。
各場面で、相手の手札としてありうる区別できる手札の数 W（`meicho.worlds.world_counts`・便 M と同じ数え方）を
base と aug の両方で数え、既知の枚数・W・重みつきエントロピー H_w（ビット）の差を集める。

エージェントの打ち方には触らない（トレースは読むだけ・D-114）。帯は `seed_bands.json` の 822000..822999。

実行: python experiments/diag_revealed_hand.py --deck SD001 --agent heuristic --seed0 822000 --n 400
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                       # noqa: E402
from registry import make                                        # noqa: E402
from meicho import trace                                         # noqa: E402
from meicho.engine import apply, decision_players, initial_state, observe, outcome  # noqa: E402
from meicho.state import Phase                                   # noqa: E402
from meicho.worlds import world_counts                           # noqa: E402


def _unseen(s, pi, decklist):
    """相手の手札にありうるカード（相手のデッキ表から公開領域を引いたもの）。greedy._unseen と同じ作り。"""
    opp = s.players[1 - pi]
    pool = Counter(decklist)
    for cid in opp.concerto + opp.trash + opp.action_area:
        if pool[cid] > 0:
            pool[cid] -= 1
    return list(pool.elements())


def play_one(config, deck, agent_name, seed):
    pool = deck["action_deck"]
    mk = make(agent_name, None, pool)
    agents = [mk(seed * 2 + k) for k in (0, 1)]
    s = initial_state(config, seed)
    # pub[pi] = pi が「公開されて相手の手札に入った」と知っているカード（多重集合）
    pub = [Counter(), Counter()]
    rows = []
    steps = 0
    while outcome(s) is None and s.turn_no <= 200:
        need = decision_players(s)
        if not need:
            break
        for pi in need:
            ob = observe(s, pi)
            h = ob["opp"]["hand_count"]
            base = Counter(ob["opp"]["hand_known_scan"])   # D-121: 診断した時点の hand_known（スキャン・B-9 のぶん）
            aug = base | pub[pi]
            if sum(aug.values()) == sum(base.values()):
                wb = wa = None
            else:
                pool_u = _unseen(s, pi, pool)
                wb = world_counts(pool_u, h, list(base.elements()))
                wa = world_counts(pool_u, h, list(aug.elements()))
            rows.append({
                "clash": s.phase == Phase.CLASH_SUBMIT, "turn": s.turn_no, "h": h,
                "base_n": sum(base.values()), "aug_n": sum(aug.values()),
                "W_base": None if wb is None else wb["W"], "W_aug": None if wa is None else wa["W"],
                "H_base": None if wb is None else wb["H_w"], "H_aug": None if wa is None else wa["H_w"],
                "incons": bool(wa and wa["inconsistent"]),
            })
        acts = {pi: agents[pi].act(s, pi) for pi in need}
        revealed = [[], []]

        def sink(kind, info, _s):
            if kind == "reveal" and info.get("zone") == "action_deck" and info.get("audience") == "all":
                revealed[info["owner"]] += list(info["cards"])

        before = [Counter(p.hand) for p in s.players]
        with trace.tracing(sink):
            s = apply(s, acts)
        steps += 1
        for o in (0, 1):
            after = Counter(s.players[o].hand)
            gained = Counter(revealed[o]) & (after - before[o])
            obs = 1 - o
            pub[obs] = (pub[obs] + gained) & after      # 本当の手札との積で忘れる（エンジンと同じ）
    return rows, steps


def summarize(rows):
    out = {}
    for label, sel in (("clash", [r for r in rows if r["clash"]]), ("all", rows)):
        n = len(sel)
        diff = [r for r in sel if r["aug_n"] > r["base_n"]]
        bits = [r["H_base"] - r["H_aug"] for r in diff if r["H_base"] is not None and r["H_aug"] is not None]
        ratio = sorted(r["W_base"] / r["W_aug"] for r in diff if r["W_aug"])
        out[label] = {
            "decisions": n,
            "with_extra": len(diff),
            "frac_with_extra": (len(diff) / n) if n else None,
            "mean_extra_cards": (sum(r["aug_n"] - r["base_n"] for r in diff) / len(diff)) if diff else 0,
            "mean_known_frac_base": (sum(r["base_n"] / r["h"] for r in sel if r["h"]) / n) if n else None,
            "mean_known_frac_aug": (sum(r["aug_n"] / r["h"] for r in sel if r["h"]) / n) if n else None,
            "mean_bits_saved_when_extra": (sum(bits) / len(bits)) if bits else None,
            "median_W_ratio_when_extra": ratio[len(ratio) // 2] if ratio else None,
            "inconsistent": sum(r["incons"] for r in sel),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--agent", default="heuristic")
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    deck = load_deck(a.deck)
    config = mirror_config(deck)
    all_rows, games_with_extra = [], 0
    for i in range(a.n):
        rows, _ = play_one(config, deck, a.agent, a.seed0 + i)
        games_with_extra += any(r["clash"] and r["aug_n"] > r["base_n"] for r in rows)
        all_rows += rows
    res = {"deck": a.deck, "agent": a.agent, "band": [a.seed0, a.seed0 + a.n - 1], "games": a.n,
           "games_with_extra_at_clash": games_with_extra, "summary": summarize(all_rows)}
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    print(txt)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(txt + "\n")


if __name__ == "__main__":
    main()
