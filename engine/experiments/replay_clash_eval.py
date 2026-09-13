"""対人の記録の対抗で、champion（Python）の対抗の評価 `_clash` を再生して中身を出す。

決定化（相手の手札の仮置き）ごとに「π₀ が予測した相手の提出」と AI の各手の葉の V を印字し、
samples を変えたときの順位も出す。読み方は `HUMAN_GAMES_20260903_NOTES.md` §3。
エージェントのシードは記録の `opponent.seed` を使う（アプリと同じ仮置きになる保証はない。仮置きは乱数の消費順にも依る）。

既定では**その局の最後の対抗**だけを見る。`--all-clashes` を付けると**すべての対抗**を順に見て、
記録に残っている `ai_clash.totals`（アプリがそのとき実際に出した点数）と突き合わせる
（便 D 後半・D-5 の g001 診断）。**合わなければ記録側を正とし、差を書く**——
再生の決定化の乱数はアプリの乱数の消費順と同じとは限らないからである（§7 の 7）。

使い方:
    python3 experiments/replay_clash_eval.py
    python3 experiments/replay_clash_eval.py --opponent planner_vc4cps --seed 130004 --all-clashes
    python3 experiments/replay_clash_eval.py --opponent planner_vc4cps --seed 130007 \
        --all-clashes --override '{"lethal_uniform": 0.0}'
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                                        # noqa: E402
from meicho.cards import ACTION_CARDS                                             # noqa: E402
from meicho.drlnet import resolve_model                                           # noqa: E402
from meicho.engine import apply, legal_actions                                    # noqa: E402
from meicho.planner import PlannerAgent                                           # noqa: E402
from verify_lethal_human import act_name, clash_states, last_clash_state          # noqa: E402,F401
from webapp import record as wrec                                                 # noqa: E402
import champion as chmod                                                          # noqa: E402


class TracingPlanner(PlannerAgent):
    """`_clash` を写して、決定化ごとの予測と葉の値を残す。挙動は同じ。"""

    def _clash(self, s, pi, acts):
        self.trace = []
        totals = [0.0] * len(acts)
        for _ in range(self.samples):
            t = self._determinize(s, pi)
            opp_act = self._opp_act(t, 1 - pi, True)
            row = {"opp_hand": [ACTION_CARDS[c].name for c in t.players[1 - pi].hand],
                   "opp_pred": act_name(t, 1 - pi, opp_act), "vals": []}
            for i, a in enumerate(acts):
                v = self._eval(self._settle(apply(t, {pi: a, 1 - pi: opp_act}), pi), pi)
                totals[i] += v
                row["vals"].append(v)
            self.trace.append(row)
        self.totals = [x / self.samples for x in totals]
        best = max(range(len(acts)), key=lambda i: totals[i])
        return acts[best]


def resolved_kwargs(override: dict | None = None) -> dict:
    kw = dict(chmod.kwargs_for("SD001"))
    kw.update(override or {})
    for k in ("value_net", "opp_policy_net", "policy_net"):
        if isinstance(kw.get(k), str):
            kw[k] = resolve_model(kw[k])
    return kw


def recorded_clashes(rec: dict) -> list:
    """記録に残っている対抗の `ai_clash`（アプリがそのとき出した点数）をターン順に。"""
    return [{"turn": a.get("turn"), **a["ai_clash"]}
            for a in rec.get("actions", [])
            if a.get("by") == "ai" and isinstance(a.get("ai_clash"), dict)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(_HERE, "..", "results", "human_games", "2026-09.jsonl"))
    ap.add_argument("--opponent", default="planner_vb3")
    ap.add_argument("--seed", type=int, default=None, help="この局（記録の seed）だけを見る")
    ap.add_argument("--samples", type=int, nargs="+", default=[6, 12, 24])
    ap.add_argument("--all-clashes", action="store_true",
                    help="その局のすべての対抗を見る（既定は最後の対抗だけ）")
    ap.add_argument("--override", default=None,
                    help="champion の引数への差分（JSON）。例 '{\"lethal_uniform\": 0.0}'")
    ap.add_argument("--detail", action="store_true", help="決定化ごとの内訳も出す（samples の最初の値だけ）")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    override = json.loads(args.override) if args.override else None
    deck = load_deck("SD001")
    cfg, pool = mirror_config(deck), deck["action_deck"]
    with open(args.file, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    recs = [r for r in recs if r["opponent"]["name"] == args.opponent]
    if args.seed is not None:
        recs = [r for r in recs if r.get("seed") == args.seed]
    dump = []
    for rec in recs:
        out = wrec.replay(rec, cfg, keep_states=True)
        hu = rec["human_seat"]
        ai = 1 - hu
        sts = clash_states(out["states"])
        if not sts:
            continue
        if not args.all_clashes:
            sts = sts[-1:]
        recorded = recorded_clashes(rec)
        by_turn = {r["turn"]: r for r in recorded}
        for s in sts:
            legal = legal_actions(s, ai)
            for k, n in enumerate(args.samples):
                kw = resolved_kwargs(override)
                kw["samples"] = n
                ag = TracingPlanner(rec["opponent"]["seed"], opp_decklist=pool, **kw)
                chosen = ag.act(s, ai)
                preds = [r["opp_pred"] for r in ag.trace]
                print(f"== {rec['game_id']} seed {rec.get('seed')} T{s.turn_no} samples={n}"
                      f"  選ぶ={act_name(s, ai, chosen)}  予測した相手の提出: {preds}")
                for v, a in sorted(zip(ag.totals, legal), key=lambda x: -x[0]):
                    print(f"   {v:.3f}  {act_name(s, ai, a)}")
                rc = by_turn.get(s.turn_no)
                if rc and k == 0:
                    got = {act_name(s, ai, a): v for a, v in zip(legal, ag.totals)}
                    print(f"   記録（アプリ）: 選んだ={rc['acts'][rc['chosen']]}"
                          f"  点数={[round(x, 4) for x in rc['totals']]}")
                    diffs = []
                    for nm, rv in zip(rc["acts"], rc["totals"]):
                        cand = [gv for gn, gv in got.items() if gn.startswith(nm)]
                        if cand:
                            diffs.append(abs(cand[0] - rv))
                    if diffs:
                        print(f"   再生との最大差 {max(diffs):.4f}"
                              + ("（一致とみてよい）" if max(diffs) < 1e-6
                                 else "（**合わない。決定化の乱数が違う。記録側を正とする**）"))
                    dump.append({"game_id": rec["game_id"], "seed": rec.get("seed"),
                                 "turn": s.turn_no, "samples": n,
                                 "replay_choice": act_name(s, ai, chosen),
                                 "replay_totals": {k2: v2 for k2, v2 in got.items()},
                                 "recorded_choice": rc["acts"][rc["chosen"]],
                                 "recorded_totals": rc["totals"],
                                 "max_abs_diff": (max(diffs) if diffs else None)})
                if args.detail and k == 0:
                    for j, r in enumerate(ag.trace):
                        print(f"   --- 仮置き {j}: 相手の手札={r['opp_hand']} 予測={r['opp_pred']}")
                        for v, a in zip(r["vals"], legal):
                            print(f"        {act_name(s, ai, a):24s} V={v:.3f}")
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(dump, f, ensure_ascii=False, indent=1)
        print(f"→ {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
