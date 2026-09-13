"""段 C-3（II-9）の投票がどれだけ効いているかの診断（文献計画 便 C）。

## 何を見るか

段 C-3 の候補は、ありうる相手の手札が `endgame_enum` 通り以下の決定で、
決定化 K 本の代わりに**整合する手札を全列挙**して使う。そのうえで
`_plan`（アクションフェイズ）の 1 手目だけは**投票**でも決める:

- 本ごとに「その本での最良の 1 手目」を採り、本の重み（多重度）を載せて足す
- **信頼度 C = 勝った手の重みの割合**
- C ≥ `endgame_conf` ならその手、そうでなければ従来どおり**加重平均の最良手**

強さの測定（錨・門番）は「勝ったか」しか答えないので、**この道が実際に何回通り、
何回手を変えたか**を別に数える。これが分からないと、門番の結果が
「投票が効かなかった」のか「そもそも投票が発動していない」のかを区別できない。

**この道具は診断であって、打ち方は候補そのものである**（候補のミラー戦をそのまま回す）。

## 使い方

    python3 experiments/diag_endgame.py --n 20 --seed0 692700 --workers 2 \
        --out results/lit/c3_vote_diag.json

数字の定義:

- `plan_decisions` … アクションフェイズで計画探索に入った決定の数
- `enumerated` … そのうち列挙に入った決定（W ≤ `endgame_enum`）
- `C_mean` / `C_median` … 信頼度 C
- `conf_pass` … C ≥ `endgame_conf` だった割合（＝投票の手を採った割合）
- `differs` … 投票の手と加重平均の手が**違った**割合（列挙に入った決定のうち）
- `changed` … 実際に手が変わった割合（＝ C ≥ しきい値 **かつ** 手が違った）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, ".."), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from arena import load_deck, mirror_config                                # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,        # noqa: E402
                           legal_actions, outcome)
from meicho.planner import PlannerAgent                                   # noqa: E402
from meicho.state import Phase                                            # noqa: E402
from peek_counter import resolved_kwargs                                  # noqa: E402

BAND = (692700, 692719)          # §5 段 C-3 の予備帯（診断・強さは読まない）
KNOBS = {"known_hand": True, "endgame_enum": 64}


def _one(args):
    deck, kw, seed, max_turns = args
    d = load_deck(deck)
    config, pool = mirror_config(d), d["action_deck"]
    agents = [PlannerAgent(seed * 2, opp_decklist=pool, **kw),
              PlannerAgent(seed * 2 + 1, opp_decklist=pool, **kw)]
    s = initial_state(config, seed)
    rows: list = []
    steps = 0
    while outcome(s) is None and s.turn_no <= max_turns:
        need = decision_players(s)
        if not need:
            break
        acts = {}
        for pi in sorted(need):
            # 計画探索に**実際に入る**決定だけを数える（合法手が 1 つなら即決）
            was_plan = (s.phase == Phase.ACTION
                        and Phase.ACTION in agents[pi].phases
                        and len(legal_actions(s, pi)) > 1)
            agents[pi]._last_endgame = None
            acts[pi] = agents[pi].act(s, pi)
            info = agents[pi]._last_endgame
            if not was_plan:
                continue
            row = {"seed": seed, "seat": pi, "turn": s.turn_no,
                   "enumerated": bool(info),
                   "worlds": (info or {}).get("worlds"),
                   "C": (info or {}).get("C"),
                   "used": bool((info or {}).get("used")),
                   "differs": (None if not info else
                               (info["vote_move"] != info["avg_move"]))}
            rows.append(row)
        s = apply(s, acts)
        steps += 1
    return rows, {"seed": seed, "T": s.turn_no, "steps": steps,
                  "aborted": bool(outcome(s) is None)}


def _stats(xs):
    if not xs:
        return {"n": 0, "mean": None, "median": None}
    v = sorted(xs)
    n = len(v)
    med = v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])
    return {"n": n, "mean": sum(v) / n, "median": med}


def aggregate(rows: list, games: list) -> dict:
    en = [r for r in rows if r["enumerated"]]
    dif = [r for r in en if r["differs"]]
    return {"games": len(games), "plan_decisions": len(rows),
            "enumerated": len(en),
            "enum_rate": (len(en) / len(rows)) if rows else None,
            "worlds": _stats([r["worlds"] for r in en if r["worlds"]]),
            "C": _stats([r["C"] for r in en if r["C"] is not None]),
            "conf_pass": (sum(1 for r in en if r["used"]) / len(en)) if en else None,
            "differs": (len(dif) / len(en)) if en else None,
            "changed": (sum(1 for r in en if r["used"] and r["differs"]) / len(en))
                       if en else None}


def render(agg: dict) -> str:
    def f(x, d=3):
        return "―" if x is None else f"{x:.{d}f}"
    return "\n".join([
        "■ 段 C-3 の投票の診断", "",
        f"  局数 {agg['games']}／計画探索の決定 {agg['plan_decisions']}",
        f"  列挙に入った決定 {agg['enumerated']}（{f(agg['enum_rate'])}）"
        f"／使った本の数 中央値 {agg['worlds']['median']}",
        f"  信頼度 C 平均 {f(agg['C']['mean'])}／中央値 {f(agg['C']['median'])}",
        f"  C がしきい値を越えた割合 {f(agg['conf_pass'])}",
        f"  投票の手と加重平均の手が違った割合 {f(agg['differs'])}",
        f"  **実際に手が変わった割合 {f(agg['changed'])}**", "",
        "  読み方: 「実際に手が変わった割合」が 0 に近ければ、投票は発動していても"
        "決定を動かしていない（＝門番の結果は投票の良し悪しをほとんど測っていない）。"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed0", type=int, default=BAND[0])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--out", default=os.path.join(_HERE, "..", "results", "lit",
                                                  "c3_vote_diag.json"))
    args = ap.parse_args(argv)

    kw = {**resolved_kwargs(args.deck), **KNOBS}
    rows_path = os.path.splitext(args.out)[0] + ".jsonl"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    jobs = [(args.deck, kw, sd, args.max_turns)
            for sd in range(args.seed0, args.seed0 + args.n)]
    t0 = time.time()
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            got = list(ex.map(_one, jobs, chunksize=1))
    else:
        got = [_one(j) for j in jobs]
    rows = [r for rs, _ in got for r in rs]
    games = [g for _, g in got]
    with open(rows_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    agg = aggregate(rows, games)
    print(render(agg))
    import provenance
    out = {"agg": agg, "knobs": KNOBS, "seed0": args.seed0, "n": args.n,
           "rows_file": os.path.basename(rows_path),
           "sec": round(time.time() - t0, 1),
           "games": games,
           "provenance": provenance.block(
               kw, "python", (args.seed0, args.seed0 + args.n - 1),
               extra={"tool": "diag_endgame", "host": provenance.host_name(),
                      "workers": int(args.workers),
                      "note": "診断。打ち方は段 C-3 の候補そのもの"})}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
