"""AI の「怪しい挙動」の出現頻度を数える（対人検証アプリの指摘の裏取り・D-042）。

## これは何をする道具か

対人対局で「AI のこの手はおかしいのでは」と思ったとき、まず知りたいのは
**それが一度きりの偶然か、いつもやっていることか**である。
ここでは特定の型の手を数えるだけで、**良し悪しの判定はしない**。

良し悪しを決めるには、その手を禁じた AI と禁じない AI を同じシードで
戦わせて勝率を比べる必要がある（D-039 の対照実験）。頻度はその前段である。
頻度が 0 に近ければ、そもそも調べる価値がない。

## 数えている型

- `free_rush_declined`: **コスト0でダメージのある連撃**が選べたのに「連撃をやめる」を
  選んだ回数。払うものが無く、失うのは手札1枚だけの場面である。
- `no_charge_turn`: **協奏エリアが空**で、チャージが選べたのに、そのターン
  一度もチャージせずに対抗フェイズ／ターン終了へ進んだ回数。
  （協奏はコストの支払い元なので、空のまま進むと重いカードが使えない。）
- `levelup_*`: レベルアップが選べたターンのうち、実際にレベルアップした割合と、
  終局時に到達したレベルの合計（3体ぶん。SD001 なら最大 6 = 全員 Lv2）。

どちらも「必ず悪い」とは限らない。だから**数えるだけ**である。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from meicho.cards import ACTION_CARDS, CHARA_CARDS
from meicho.engine import (apply, decision_players, initial_state,
                           legal_actions, outcome)
from meicho.state import Phase

from arena import load_deck, mirror_config

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from webapp.agents import build as build_agent   # noqa: E402 （アプリと同一の相手）

BAND = (140000, 149999)          # seed_bands.json に登録済み（診断専用）


def check_band(seeds) -> None:
    lo, hi = BAND
    bad = [s for s in seeds if not (lo <= s <= hi)]
    if bad:
        raise SystemExit(f"診断帯 {lo}..{hi} の外のシードが混ざっている: {bad[:5]}")


def _free_rush_options(s, pi) -> list:
    """コスト0でダメージのある連撃の選択肢。"""
    out = []
    for a in legal_actions(s, pi):
        if a.get("type") != "rush":
            continue
        cid = s.players[pi].hand[a["hand"]]
        c = ACTION_CARDS[cid]
        if c.cost == 0 and c.damage > 0:
            out.append(cid)
    return out


def run(agent_name: str, opponent: str, seeds: list, deck: str = "SD001") -> dict:
    check_band(seeds)
    d = load_deck(deck)
    cfg = mirror_config(d)
    pool = d["action_deck"]

    tally = {
        "games": 0, "turns": 0,
        "rush_decisions": 0, "free_rush_available": 0, "free_rush_declined": 0,
        "free_rush_lethal_available": 0, "free_rush_lethal_declined": 0,
        "turns_as_turn_player": 0, "turns_with_empty_concerto": 0,
        "no_charge_turn": 0,
        "turns_levelup_possible": 0, "turns_levelup_taken": 0,
        "final_level_sum": 0, "final_level_max": 0,
    }
    for seed in seeds:
        agents = {0: build_agent(agent_name, pool, seed * 2),
                  1: build_agent(opponent, pool, seed * 2 + 1)}
        s = initial_state(cfg, seed)
        # 「このターン、まだチャージしていない」の追跡（測る側の席は 0 に固定）
        turn_seen, charged, empty_at_start = -1, False, False
        lv_possible, lv_taken = False, False
        while outcome(s) is None and s.turn_no <= 200:
            need = decision_players(s)
            if not need:
                break
            if s.turn_player == 0 and s.turn_no != turn_seen:
                if lv_possible:
                    tally["turns_levelup_possible"] += 1
                    if lv_taken:
                        tally["turns_levelup_taken"] += 1
                lv_possible = lv_taken = False
                turn_seen = s.turn_no
                charged = False
                empty_at_start = not s.players[0].concerto
                if s.phase == Phase.ACTION:
                    tally["turns_as_turn_player"] += 1
                    if empty_at_start:
                        tally["turns_with_empty_concerto"] += 1

            acts = {}
            for pi in need:
                a = agents[pi].act(s, pi)
                acts[pi] = a
                if pi != 0:
                    continue
                if a.get("type") == "charge":
                    charged = True
                if s.phase == Phase.ACTION and s.turn_player == 0:
                    # 「そのターン、レベルアップが一度でも選べたか / したか」
                    if any(x.get("type") == "levelup"
                           for x in legal_actions(s, 0)):
                        lv_possible = True
                    if a.get("type") == "levelup":
                        lv_taken = True
                if s.phase == Phase.RUSH:
                    tally["rush_decisions"] += 1
                    free = _free_rush_options(s, 0)
                    if free:
                        tally["free_rush_available"] += 1
                        best = max(ACTION_CARDS[c].damage for c in free)
                        lethal = best >= s.players[1].life
                        if lethal:
                            tally["free_rush_lethal_available"] += 1
                        if a.get("type") == "stop":
                            tally["free_rush_declined"] += 1
                            if lethal:
                                # **その場で勝てる手を見送った**。言い訳の余地が無い型。
                                tally["free_rush_lethal_declined"] += 1
                if (s.phase == Phase.ACTION and s.turn_player == 0
                        and a.get("type") in ("to_clash", "end_turn")
                        and empty_at_start and not charged):
                    # チャージが選べたのに一度もせずに進んだか
                    if any(x.get("type") == "charge"
                           for x in legal_actions(s, 0)):
                        tally["no_charge_turn"] += 1

            s = apply(s, {pi: acts[pi] for pi in sorted(acts)})
        if lv_possible:
            tally["turns_levelup_possible"] += 1
            if lv_taken:
                tally["turns_levelup_taken"] += 1
        # 終局時に到達したレベルの合計（3枠の一番上のレベルを足す）
        lv = sum(0 if not sl.stack else CHARA_CARDS[sl.stack[-1]].level
                 for sl in s.players[0].slots)
        tally["final_level_sum"] += lv
        tally["final_level_max"] = max(tally["final_level_max"], lv)
        tally["games"] += 1
        tally["turns"] += s.turn_no
    return tally


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="planner")
    ap.add_argument("--opponent", default="heuristic")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--start", type=int, default=BAND[0])
    a = ap.parse_args(argv)
    seeds = list(range(a.start, a.start + a.n))
    t = run(a.agent, a.opponent, seeds)
    print(json.dumps(t, ensure_ascii=False, indent=1))

    def pct(x, n):
        return "—" if not n else f"{100.0 * x / n:.1f}%"

    print()
    print(f"{a.agent} vs {a.opponent}／{t['games']} 局")
    print(f"連撃の判断 {t['rush_decisions']} 回のうち、"
          f"コスト0で damage>0 の連撃が選べた場面 {t['free_rush_available']} 回。"
          f"うち やめた {t['free_rush_declined']} 回 "
          f"({pct(t['free_rush_declined'], t['free_rush_available'])})")
    print(f"そのうち **その連撃で勝てた** 場面 {t['free_rush_lethal_available']} 回。"
          f"うち見送った {t['free_rush_lethal_declined']} 回 "
          f"({pct(t['free_rush_lethal_declined'], t['free_rush_lethal_available'])})")
    print(f"レベルアップが選べたターン {t['turns_levelup_possible']} 回のうち、"
          f"実際にした {t['turns_levelup_taken']} 回 "
          f"({pct(t['turns_levelup_taken'], t['turns_levelup_possible'])})")
    print(f"終局時のレベル合計（3体・最大6）: 平均 "
          f"{t['final_level_sum'] / max(1, t['games']):.2f}／最大 {t['final_level_max']}")
    print(f"協奏が空で始まった自分のターン {t['turns_with_empty_concerto']} 回のうち、"
          f"一度もチャージせずに進んだ {t['no_charge_turn']} 回 "
          f"({pct(t['no_charge_turn'], t['turns_with_empty_concerto'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
