"""champion（Python・`champion.kwargs_for`）の対抗の決定で「詰みが手札にあったのに取らなかった」回数を数える。

相手の実際の提出を後から知り、AI の各合法手についてターン内を H の代打ちで進めて判定する（後知恵）。
見逃しの内訳（ターン・出した手・相手の手・詰みだった手・ライフ・協奏）を局ごとに印字する。
読み方は `HUMAN_GAMES_20260903_NOTES.md` §5。

使い方:
    python3 experiments/scan_missed_lethal.py H 40 602400        # 対 H・40 局・シード 602400..
    python3 experiments/scan_missed_lethal.py mirror 30 603000   # champion 同士
    python3 experiments/scan_missed_lethal.py H 40 659300 lu50   # 候補（champion ＋ 差分）で測る
帯は seed_bands.json に登録してから使う（D-028）。偶数局は AI が先手、奇数局は後手。

第 4 引数（省略可）は `probe_d065.CANDIDATES` の候補名である。省略すると現 champion。
**測るのは AI 側だけ**で、ミラーの相手役も同じ設定になる（champion 対 champion / 候補 対 候補）。
比較は**同じシード**で候補ごとに走らせて行う（`HANDOFF_20260907_LIT_A.md` §4.2）。
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

from arena import load_deck, mirror_config                                        # noqa: E402
from meicho.cards import ACTION_CARDS                                             # noqa: E402
from meicho.engine import apply, decision_players, initial_state, legal_actions, outcome  # noqa: E402
from meicho.heuristic import HeuristicAgent                                       # noqa: E402
from meicho.planner import PlannerAgent                                           # noqa: E402
from meicho.state import Phase                                                    # noqa: E402
from verify_lethal_human import lethal_after                                      # noqa: E402
import champion as chmod                                                          # noqa: E402


def _card(s, pi, a):
    if a["type"] != "submit":
        return "pass"
    c = ACTION_CARDS[s.players[pi].hand[a["hand"]]]
    return f"{c.name}({c.color.name[0]}{c.cost})"


def kwargs_for_cand(cand: str = None) -> dict:
    """現 champion に候補の差分を重ねた kwargs（`--cand` 省略時は champion そのもの）。"""
    kw = dict(chmod.kwargs_for("SD001"))
    if cand:
        from probe_d065 import CANDIDATES
        if cand not in CANDIDATES:
            raise SystemExit(f"未登録の候補: {cand}（{sorted(CANDIDATES)}）")
        kw.update(CANDIDATES[cand])
    return kw


def run(seed: int, ai_seat: int, opp_kind: str, cfg, pool, cand: str = None) -> dict:
    kw = kwargs_for_cand(cand)
    ag = PlannerAgent(seed * 2 + ai_seat, opp_decklist=pool, **kw)
    if opp_kind == "H":
        op = HeuristicAgent(seed * 2 + 1 - ai_seat)
    else:
        op = PlannerAgent(seed * 2 + 1 - ai_seat, opp_decklist=pool, **kw)
    agents = [None, None]
    agents[ai_seat], agents[1 - ai_seat] = ag, op
    s = initial_state(cfg, seed)
    st = {"clash": 0, "lethal_avail": 0, "lethal_taken": 0, "missed": []}
    steps = 0
    while outcome(s) is None and steps < 600:
        need = decision_players(s)
        if not need:
            break
        acts = {pi: agents[pi].act(s, pi) for pi in need}
        if s.phase == Phase.CLASH_SUBMIT and ai_seat in need and (1 - ai_seat) in need:
            st["clash"] += 1
            my, other = acts[ai_seat], acts[1 - ai_seat]
            avail = [a for a in legal_actions(s, ai_seat)
                     if a["type"] == "submit" and lethal_after(s, ai_seat, {ai_seat: a, 1 - ai_seat: other})[0]]
            if avail:
                st["lethal_avail"] += 1
                if lethal_after(s, ai_seat, {ai_seat: my, 1 - ai_seat: other})[0]:
                    st["lethal_taken"] += 1
                else:
                    p, o = s.players[ai_seat], s.players[1 - ai_seat]
                    st["missed"].append((s.turn_no, _card(s, ai_seat, my), "opp:" + _card(s, 1 - ai_seat, other),
                                         "lethal:" + ",".join(_card(s, ai_seat, a) for a in avail),
                                         f"life me{p.life}/opp{o.life} conc{len(p.concerto)}"))
        s = apply(s, acts)
        steps += 1
    st["winner"], st["turns"] = outcome(s), s.turn_no
    return st


def main(argv=None) -> int:
    """`kind n seed0` に加えて `--cand`（候補名）・`--out`（JSONL・再開可）・`--budget-sec`。

    JSONL は 1 行 1 局なので、同じコマンドをもう一度打つと**終わった局を飛ばして続きから**回る。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["H", "mirror"])
    ap.add_argument("n", type=int)
    ap.add_argument("seed0", type=int)
    ap.add_argument("--cand", default=None,
                    help="probe_d065.CANDIDATES の候補名（省略時は現 champion）")
    ap.add_argument("--out", default=None, help="1 行 1 局の JSONL（再開に使う）")
    ap.add_argument("--budget-sec", type=float, default=None,
                    help="この秒数を越えたら局の切れ目で止まる。同じコマンドで再開")
    args = ap.parse_args(argv)
    kind, n, seed0, cand = args.kind, args.n, args.seed0, args.cand
    kwargs_for_cand(cand)                      # 未登録の候補名はここで落とす
    deck = load_deck("SD001")
    cfg, pool = mirror_config(deck), deck["action_deck"]

    rows: dict = {}
    if args.out and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    rows[r["seed"]] = r
        print(f"  ※ 途中から再開（{len(rows)}/{n} 局）", flush=True)

    t0 = time.time()
    fh = open(args.out, "a", encoding="utf-8") if args.out else None
    try:
        for g in range(n):
            seed, ai_seat = seed0 + g, g % 2
            if seed in rows:
                continue
            if args.budget_sec is not None and time.time() - t0 > args.budget_sec:
                break
            st = run(seed, ai_seat, kind, cfg, pool, cand)
            r = {"seed": seed, "ai_seat": ai_seat, "clash": st["clash"],
                 "lethal_avail": st["lethal_avail"], "lethal_taken": st["lethal_taken"],
                 "missed": st["missed"], "winner": st["winner"], "turns": st["turns"]}
            rows[seed] = r
            if fh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()
            if st["missed"]:
                print("  missed:", seed, st["missed"], "winner", st["winner"],
                      "ai_seat", ai_seat, flush=True)
    finally:
        if fh:
            fh.close()

    tot = {"games": 0, "clash": 0, "lethal_avail": 0, "lethal_taken": 0, "missed": 0, "wins": 0}
    for g in range(n):
        r = rows.get(seed0 + g)
        if r is None:
            continue
        tot["games"] += 1
        for k in ("clash", "lethal_avail", "lethal_taken"):
            tot[k] += r[k]
        tot["missed"] += len(r["missed"])
        tot["wins"] += int(r["winner"] == r["ai_seat"])
    taken = (tot["lethal_taken"] / tot["lethal_avail"]) if tot["lethal_avail"] else None
    tot["taken_rate"] = taken
    print(kind, f"cand={cand or 'champion'}", tot, f"{time.time() - t0:.0f}s", flush=True)
    return 0 if tot["games"] >= n else 3


if __name__ == "__main__":
    sys.exit(main())
