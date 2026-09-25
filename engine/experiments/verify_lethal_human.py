"""対人の記録（`results/human_games/*.jsonl`）の対抗について、AI の合法手 × 相手の合法手の詰み表を出す。

各組み合わせを engine で適用し、対抗後の両者の決定を H（規則エージェント）の代打ちで**そのターンの終わりまで**進めて、
「AI の連撃で相手のライフが 0 になる（詰み）」か、そうでなければ両者の残りライフを表にする。
後知恵の判定（相手の実際の手を知っている）なので、AI に取れて当然の詰みではない。読み方は
`HUMAN_GAMES_20260903_NOTES.md` §2。

既定では**その局の最後の対抗**だけを見る。`--all-clashes` を付けると**その局のすべての対抗**を
順に見る（便 D 後半・D-5 の g001 診断で、負けが最後の 1 手ではなく組み立てにあるかを調べるため）。
最後の対抗の表は `--all-clashes` の有無で変わらない（`tests/test_lit_d2.py::T-D2-10` が固定する）。

使い方:
    python3 experiments/verify_lethal_human.py                         # 2026-09 の planner_vb3 との全局
    python3 experiments/verify_lethal_human.py --file results/human_games/2026-09.jsonl --opponent planner_vb3
    python3 experiments/verify_lethal_human.py --opponent planner_vc4cps --seed 130004 --all-clashes
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
from meicho.engine import apply, apply_owned, decision_players, legal_actions     # noqa: E402
from meicho.heuristic import HeuristicAgent                                       # noqa: E402
from meicho.state import Phase                                                    # noqa: E402
from webapp import record as wrec                                                 # noqa: E402


def lethal_after(s, ai: int, acts_both: dict):
    """両者の提出を適用し、以後の決定を H の代打ちでターン内だけ進める。(詰みか, 到達した局面)。"""
    turn0 = s.turn_no
    u = apply(s, acts_both)
    h = HeuristicAgent(1)
    for _ in range(40):
        if u.outcome is not None:
            break
        if u.turn_no != turn0 and u.phase != Phase.CHOICE:
            break
        need = decision_players(u)
        if not need:
            break
        u = apply_owned(u, {q: h.act(u, q) for q in need})
    return u.outcome == ai, u


def act_name(s, pi: int, a: dict) -> str:
    if a["type"] != "submit":
        return "pass"
    c = ACTION_CARDS[s.players[pi].hand[a["hand"]]]
    return f"{c.name}({c.color.name[0]} c{c.cost} s{c.speed})"


def clash_states(states):
    """その局の**すべての対抗**（両者が同時に提出する局面）をターン順に返す。"""
    return [s for s in states
            if s.phase == Phase.CLASH_SUBMIT and set(decision_players(s)) == {0, 1}]


def last_clash_state(states):
    clash = clash_states(states)
    return clash[-1] if clash else None


def walk_clashes(rec: dict, cfg) -> list:
    """再生しながら、**対抗の局面とそのとき実際に出された手**を組で集める。

    `webapp.record.replay` は局面しか返さないので、詰み表を「相手が実際に出した手の列」で
    読むために、同じ再生をここでもう一度なぞる（記録どおりに動かすだけなので結果は同じ）。
    """
    from meicho.engine import initial_state, outcome
    from webapp.record import ReplayAgent, is_legacy_stage1a
    # 段階1A より前の記録の補完は `webapp.record.replay` と**同じ判定**を通す（D-098）。
    legacy = is_legacy_stage1a(rec)
    agents = [ReplayAgent(rec["actions"], 0, legacy_stage1a=legacy),
              ReplayAgent(rec["actions"], 1, legacy_stage1a=legacy)]
    s = initial_state(cfg, rec["seed"])
    out, steps = [], 0
    while outcome(s) is None and s.turn_no <= 200:
        need = decision_players(s)
        if not need or all(agents[pi].exhausted for pi in need):
            break
        acts = {pi: agents[pi].act(s, pi) for pi in need}
        if s.phase == Phase.CLASH_SUBMIT and set(need) == {0, 1}:
            out.append((s, dict(acts)))
        s = apply(s, acts)
        steps += 1
        if steps > 20000:
            break
    return out


def clash_table(s, ai: int, hu: int) -> dict:
    """1 つの対抗の詰み表。表示に依らない形（検査から呼べるように）。

    `rows[i]["cells"][j]` は「AI が i 番目の手、相手が j 番目の手を出したとき」の結果で、
    詰みなら `{"lethal": True}`、そうでなければ残りライフ。
    `ai_has_lethal` は**その対抗のどこかに詰みの手があるか**（後知恵の判定）。
    """
    hu_legal, ai_legal = legal_actions(s, hu), legal_actions(s, ai)
    rows = []
    for a in ai_legal:
        cells = []
        for b in hu_legal:
            ok, u = lethal_after(s, ai, {ai: a, hu: b})
            cells.append({"lethal": bool(ok), "life_ai": u.players[ai].life,
                          "life_hu": u.players[hu].life})
        rows.append({"ai_act": act_name(s, ai, a), "cells": cells})
    from meicho.cards import CHARA_CARDS
    lv = lambda p: [CHARA_CARDS[sl.stack[-1]].level if sl.stack else None      # noqa: E731
                    for sl in p.slots]
    return {
        "turn": s.turn_no,
        "life_ai": s.players[ai].life, "life_hu": s.players[hu].life,
        "concerto_ai": len(s.players[ai].concerto),
        "concerto_hu": len(s.players[hu].concerto),
        # 場のキャラのレベル（[リーダー, バック1, バック2]。空きは null）と合計
        "levels_ai": lv(s.players[ai]), "levels_hu": lv(s.players[hu]),
        "level_sum_ai": sum(x for x in lv(s.players[ai]) if x is not None),
        "level_sum_hu": sum(x for x in lv(s.players[hu]) if x is not None),
        "hand_n_ai": len(s.players[ai].hand), "hand_n_hu": len(s.players[hu].hand),
        "hand_ai": [ACTION_CARDS[c].name for c in s.players[ai].hand],
        "hand_hu": [ACTION_CARDS[c].name for c in s.players[hu].hand],
        "hu_acts": [act_name(s, hu, b) for b in hu_legal],
        "rows": rows,
        "ai_has_lethal": any(c["lethal"] for r in rows for c in r["cells"]),
        # 「相手が実際に出した手に関係なく詰む」手があるか（＝取り逃してはならない詰み）
        "ai_has_forced_lethal": any(all(c["lethal"] for c in r["cells"]) for r in rows),
    }


def _index_of(acts: list, a) -> int | None:
    """合法手の並びの中で、実際に出された手が何番目かを返す（見つからなければ None）。"""
    for i, x in enumerate(acts):
        if x == a:
            return i
    return None


def annotate_actual(s, ai: int, hu: int, t: dict, actual: dict) -> dict:
    """詰み表に「実際に出された手」を書き込み、**取り逃した詰み**かどうかを判定する。

    T-14 に足す基準（`HUMAN_GAMES_20260903_NOTES.md` §2 と同じ）は
    **「相手が実際に出した手の列に詰みがあったのに、AI がその手を選ばなかった」**である。
    「どこかのマス目に詰みがある」ではない——相手の手が違えば詰まない手を
    取り逃したと呼ぶのは後知恵が過ぎる。
    """
    ai_legal, hu_legal = legal_actions(s, ai), legal_actions(s, hu)
    ia, ih = _index_of(ai_legal, actual.get(ai)), _index_of(hu_legal, actual.get(hu))
    t = dict(t)
    t["actual_ai"] = None if ia is None else t["rows"][ia]["ai_act"]
    t["actual_hu"] = None if ih is None else t["hu_acts"][ih]
    if ih is None:
        t["lethal_vs_actual"] = None
        t["ai_took_lethal"] = None
        t["missed_lethal"] = None
        return t
    col = [r["cells"][ih]["lethal"] for r in t["rows"]]
    t["lethal_vs_actual"] = [r["ai_act"] for r, ok in zip(t["rows"], col) if ok]
    t["ai_took_lethal"] = bool(ia is not None and col[ia])
    t["missed_lethal"] = bool(any(col) and ia is not None and not col[ia])
    return t


def tables_for_record(rec: dict, cfg, all_clashes: bool = False,
                      with_actual: bool = False) -> list:
    """1 局ぶんの詰み表（既定は最後の対抗だけ、`all_clashes` なら全部）。

    `with_actual=True` なら「実際に出された手」と取り逃しの判定も付ける。
    **付けない場合の表は従来とビット単位で同じ**（T-D2-10 が固定する）。
    """
    hu = rec["human_seat"]
    ai = 1 - hu
    if with_actual:
        pairs = walk_clashes(rec, cfg)
        if not pairs:
            return []
        if not all_clashes:
            pairs = pairs[-1:]
        return [annotate_actual(s, ai, hu, clash_table(s, ai, hu), acts)
                for s, acts in pairs]
    out = wrec.replay(rec, cfg, keep_states=True)
    sts = clash_states(out["states"])
    if not sts:
        return []
    if not all_clashes:
        sts = sts[-1:]
    return [clash_table(s, ai, hu) for s in sts]


def render_table(rec: dict, t: dict) -> str:
    L = [f"== {rec['game_id']} seed {rec['seed']} human_seat {rec['human_seat']}  "
         f"T{t['turn']} 対抗  life AI{t['life_ai']}/H{t['life_hu']} "
         f"conc AI{t['concerto_ai']}  AI hand {t['hand_ai']}",
         "   AI \\ H      " + "  ".join(f"{n:>22s}" for n in t["hu_acts"])]
    for r in t["rows"]:
        cells = ["詰み" if c["lethal"] else f"{c['life_ai']:>2d}/{c['life_hu']:<2d}"
                 for c in r["cells"]]
        L.append(f"   {r['ai_act']:18s} " + "  ".join(f"{c:>22s}" for c in cells))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(_HERE, "..", "results", "human_games", "2026-09.jsonl"))
    ap.add_argument("--opponent", default="planner_vb3")
    ap.add_argument("--seed", type=int, default=None, help="この局（記録の seed）だけを見る")
    ap.add_argument("--all-clashes", action="store_true",
                    help="その局のすべての対抗を見る（既定は最後の対抗だけ）")
    ap.add_argument("--with-actual", action="store_true",
                    help="実際に出された手を並べ、詰みの取り逃しを判定する")
    ap.add_argument("--json", default=None, help="詰み表を JSON でも書き出す")
    args = ap.parse_args(argv)
    deck = load_deck("SD001")
    cfg = mirror_config(deck)
    with open(args.file, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    recs = [r for r in recs if r["opponent"]["name"] == args.opponent]
    if args.seed is not None:
        recs = [r for r in recs if r.get("seed") == args.seed]
    dump = []
    for rec in recs:
        ts = tables_for_record(rec, cfg, all_clashes=args.all_clashes,
                              with_actual=args.with_actual)
        if not ts:
            print(f"== {rec['game_id']}: 対抗なし")
            continue
        for t in ts:
            print(render_table(rec, t))
            if args.with_actual:
                print(f"   実際: AI={t['actual_ai']} / 相手={t['actual_hu']}  "
                      f"相手の実手に対する詰みの手={t['lethal_vs_actual']}  "
                      f"取った={t['ai_took_lethal']}  **取り逃し={t['missed_lethal']}**")
        n_lethal = sum(1 for t in ts if t["ai_has_lethal"])
        if args.all_clashes:
            print(f"   → 対抗 {len(ts)} 回のうち、AI に詰みの手があったのは {n_lethal} 回"
                  f"（相手の手に関係なく詰む手があったのは "
                  f"{sum(1 for t in ts if t['ai_has_forced_lethal'])} 回）")
            if args.with_actual:
                print(f"   → **相手の実手に対して詰みがあったのは "
                      f"{sum(1 for t in ts if t['lethal_vs_actual'])} 回、"
                      f"そのうち取り逃したのは "
                      f"{sum(1 for t in ts if t['missed_lethal'])} 回**")
        dump.append({"game_id": rec["game_id"], "seed": rec.get("seed"),
                     "opponent": rec["opponent"]["name"],
                     "human_seat": rec["human_seat"], "tables": ts})
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(dump, f, ensure_ascii=False, indent=1)
        print(f"→ {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
