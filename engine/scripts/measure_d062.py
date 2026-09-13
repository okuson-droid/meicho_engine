# -*- coding: utf-8 -*-
"""D-062: 秧秧Lv2の条件訂正が対局に与える影響の測定。

## 何を測るか

1. **ゲームそのもの**（AI に依存しない層）: SD001 のミラー戦をランダム行動で回し、
   先攻勝率・引き分け数・平均ターン数を出す。既存のスモークと同じ物差しである。
2. **その札が実際に働く頻度**: 秧秧Lv2 の「コスト1を払うか、ダメージ3を受けるか」の
   選択が、1局あたり何回・何割の局で発生したか。
   訂正の前後でこれがどう変わるかを見れば、**そもそもこの札がゲームに触っている量**が分かる。

## 測り方の作法（`measurement_discipline`）

- 訂正の前後で**同じシードを使い**、局ごとに対にして比べる。
- 勝率には対局数と 95% 信頼区間（±1.96√(p(1-p)/n)）を併記する。
- 引き分けは勝敗のどちらにも数えない（作業規約6 / D-021）。

使い方（2つの木で別々に走らせ、出力の JSON を突き合わせる）:
    python3 scripts/measure_d062.py --n 1000 --out before.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from meicho.agents import RandomAgent                      # noqa: E402
from meicho.engine import GameConfig, apply, decision_players, initial_state, outcome  # noqa: E402
from meicho.state import DRAW                              # noqa: E402


def play_and_count(config, agents, seed, max_turns=200) -> dict:
    """1局回して、結果と『秧秧Lv2の選択が出た回数』を返す。"""
    s = initial_state(config, seed)
    steps = fires = 0
    while outcome(s) is None:
        if s.turn_no > max_turns:
            return {"winner": None, "turns": s.turn_no, "aborted": True,
                    "draw": False, "steps": steps, "fires": fires}
        for ch in s.pending_choices:
            if ch.get("kind") == "pay_or_damage":
                fires += 1
        need = decision_players(s)
        actions = {pi: agents[pi].act(s, pi) for pi in need}
        s = apply(s, actions)
        steps += 1
    r = outcome(s)
    return {"winner": None if r == DRAW else r, "turns": s.turn_no, "aborted": False,
            "draw": r == DRAW, "steps": steps, "fires": fires,
            "life": [s.players[0].life, s.players[1].life]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed0", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    path = os.path.join(HERE, "..", "decklists", f"{args.deck}.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    config = GameConfig(chara_decks=[d["chara_deck"]] * 2,
                        action_decks=[d["action_deck"]] * 2)
    config.validate()

    per_game = []
    for i in range(args.n):
        seed = args.seed0 + i
        agents = [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)]
        per_game.append(play_and_count(config, agents, seed))

    decided = [g for g in per_game if not g["aborted"] and not g["draw"]]
    first = sum(1 for g in decided if g["winner"] == 0)
    n = len(decided)
    p = first / n if n else float("nan")
    ci = 1.96 * math.sqrt(p * (1 - p) / n) if n else float("nan")
    fires = [g["fires"] for g in per_game]
    turns = [g["turns"] for g in per_game if not g["aborted"]]

    res = {
        "deck": args.deck, "games": args.n, "seed0": args.seed0,
        "aborted": sum(1 for g in per_game if g["aborted"]),
        "draws": sum(1 for g in per_game if g["draw"]),
        "decided": n,
        "first_win_rate": p, "ci95": ci,
        "avg_turns": (sum(turns) / len(turns)) if turns else float("nan"),
        "yangyang_lv2_fires_total": sum(fires),
        "yangyang_lv2_fires_per_game": sum(fires) / args.n,
        "games_with_any_fire": sum(1 for x in fires if x),
        # 局ごとの対比較に使う生データ
        "winners": [g["winner"] for g in per_game],
        "draw_flags": [g["draw"] for g in per_game],
        "fires": fires,
        "turns_per_game": [g["turns"] for g in per_game],
    }
    js = json.dumps(res, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(js)
    print(f"{args.deck} {args.n}局 seed {args.seed0}..{args.seed0+args.n-1}")
    print(f"  打ち切り={res['aborted']} 引き分け={res['draws']} 平均ターン={res['avg_turns']:.1f}")
    print(f"  先攻勝率={p:.3f} ±{ci:.3f} (n={n}, 引き分けを除く)")
    print(f"  秧秧Lv2の選択: 合計 {res['yangyang_lv2_fires_total']} 回 / "
          f"1局あたり {res['yangyang_lv2_fires_per_game']:.2f} 回 / "
          f"発生した局 {res['games_with_any_fire']}/{args.n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
