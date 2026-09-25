"""PIMC の曖昧さ解消率（M5）と三性質（M1）— champion ミラーの自己対戦から測る
（文献計画 便 M）。**診断専用。打ち方は 1 ビットも変えない。**

## 何を測るか

### M5 disambiguation（曖昧さ解消率）

AI が決定するとき、相手の手札として**ありうる区別できる手札**が何通りあるかを
公開情報だけから数える。これを W_t と書く（Furtak & Buro・第 2 集 §2.7.4〜2.7.5）。

- H_t = log₂ W_t … 相手の手札の曖昧さ（bit）
- **D_t = 1 − log W_t / log W_0** … 局の最初（W_0）からどれだけ絞れたか（解消率）
- r_t = 1 − W_t / W_prev … 前回の自分の決定からの縮み

**中盤（その局の総ターン数 T の ⌈T/2⌉ ターン目、その席の最初の決定）の D_t の中央値が
0.3 を超えるか**で、便 B（IIMC＝葉を多値にする）の優先度を決める。0.3 は Furtak & Buro
の値である。**この定義は回す前に固定してあり、結果を見てから動かさない**（§0.3 (iv)）。

W の数え方（§0.3 (iii)）:

- プール … `GreedyAgent._unseen(s, pi)` と**同じ手順**（相手のデッキリストから
  公開領域＝協奏・トラッシュ・アクションエリアを引いた未公開の多重集合）
- **スキャンで見て今も手札に残っている札**（`observe(s, pi)["opp"]["hand_known"]`）を
  必ず含む多重集合だけを数える
- H_w … 多重度で重みづけた分布のエントロピー（配りが一様なら手札 h の確率 ∝ 多重度）
- **相手のキャラの伏せ札は数えない**（本便の対象は手札）

**注意（§6 (4) の気づいた点）**: 探索側（`_unseen` / `_determinize`）は `hand_known` を
**使っていない**。つまりスキャンの情報を探索が捨てている。したがってここで数える W は
**探索が実際に使っている情報量よりも少なく**見積もった値である。比較できるよう
`hand_known` を無視した W（`W_nokwn`）も併記する。

### M1 PIMC の三性質（第 1 集 §1.3.3 の翻訳）

- **lc（葉の相関 leaf correlation）** … 決着した最後の対抗について、後知恵（真の手札）で
  詰み表を作り、**全セルの勝敗結果が同じ**である割合。「詰みがあったか」ではない
  （詰みがあっても相手の応手で結果が変わるなら相関していない）
- **bias** … 相関している表のうち席 0 が勝つ割合（ターンプレイヤーが勝つ割合も併記）
- **df（disambiguation factor）** … M5 の r_t と兼用

lc が低いなら「決定化の本数を増やす」投資（便 C の II-7 の 6 → 24〜40）は効きが薄い、
と読む（第 1 集 §1.3.6）。

## 使い方

    python3 experiments/diag_pimc.py --n 200 --seed0 673600 --workers 2 \
        --budget-sec 480 --out results/lit/m5m1_pimc.json

同じコマンドで再開する。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                                  # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,          # noqa: E402
                           legal_actions, observe, outcome)
from meicho.planner import PlannerAgent                                     # noqa: E402
from meicho.state import DRAW, Phase                                        # noqa: E402
from meicho.worlds import d_from_w, remove_multiset, world_counts          # noqa: E402,F401
from peek_counter import resolved_kwargs                                    # noqa: E402
from verify_lethal_human import clash_table, lethal_after                   # noqa: E402

BAND = (673600, 673799)          # §5 の帯（診断。評価にも学習にも使わない）
D_MID_THRESHOLD = 0.3            # 便 B の分岐（Furtak & Buro・§0.3 (iv)）
TURN_CURVE_MAX = 12              # ターン別の曲線を出す範囲（T1〜T12）

DEFINITIONS = {
    "W": "相手の手札としてありうる**区別できる多重集合**の数（hand_known を必ず含む）",
    "W_nokwn": "同じだが hand_known を無視した数（探索側が使っている情報量に相当）",
    "H_w": "多重度で重みづけた分布のエントロピー（bit）",
    "D_t": "1 − log W_t / log W_0（W_0 = 1 なら 1 と定義する。§0.3 (iv) の字義どおり、"
           "W_0 = その席の**最初の決定**の W）",
    "D_amb_t": "同じ式だが W_0 を「相手の手札が配られた後の最初の決定の W」にしたもの。"
               "**字義どおりの D_t は退化する**——その席の最初の決定は配る前の"
               "キャラ配置（SETUP_CHARA・相手の手札 0 枚）で、そこでは W_0 = 1 に"
               "なるため、定義により D_t は必ず 1 になる。構造上そうなるので、"
               "読みはこちらを使う（§6 の判断が要る点 (1)）",
    "r_t": "1 − W_t / W_prev（同じ席の前回の決定から）",
    "mid_turn": "⌈T/2⌉（T = その局の総ターン数）",
    "D_mid": "mid_turn における、その席の**最初の決定**の D_t",
    "threshold": f"D_mid の中央値が {D_MID_THRESHOLD} を超えるかで便 B の優先度を決める",
    "lc": "決着した最後の対抗の後知恵の詰み表で、**全セルの勝敗結果が同じ**割合"
          "（分母 = 対抗で決着した局）",
    "bias": "相関している表のうち席 0 が勝つ割合",
    "decided_by": "clash = 最後の対抗と同じターンで決着した局／other = それ以外",
}


# ------------------------------------------------------------ 世界の数え方
# `_remove_multiset` / `world_counts` / `d_from_w` は **`meicho/worlds.py` に移した**
# （段 C-3・D-077 追記 3）。段 C-3 の終盤全列挙では**探索の本体**が同じ数え方を使うので、
# 写しを 2 か所に置くと「診断が言う W」と「探索が使う W」が黙ってずれる。
# ここは呼ぶだけにしてある。名前は昔のまま残す（本ファイル内の呼び出しを変えないため）。
# 数字が変わっていないことは
# `tests/test_lit_c.py::test_worlds_module_matches_diag_pimc` が便 M の記録と突き合わせる。
_remove_multiset = remove_multiset


def mid_turn_of(total_turns: int) -> int:
    """中盤のターン番号 = ⌈T/2⌉（§0.3 (iv)）。"""
    return max(1, math.ceil(total_turns / 2))


# ------------------------------------------------------------ 葉の相関（M1 lc）
def outcome_grid(s, ai: int, hu: int) -> list:
    """後知恵（真の手札）の詰み表の各セルの**勝敗結果**（"ai" / "hu" / "draw" / "none"）。

    `verify_lethal_human.lethal_after` を**そのまま呼ぶ**（D-075 の `TracingPlanner` の
    教訓。表は真の手札と engine の `apply` だけで解決するので探索器は関係ない）。
    """
    ai_legal, hu_legal = legal_actions(s, ai), legal_actions(s, hu)
    grid = []
    for a in ai_legal:
        row = []
        for b in hu_legal:
            _, u = lethal_after(s, ai, {ai: a, hu: b})
            o = u.outcome
            row.append("none" if o is None else
                       ("draw" if o == DRAW else ("ai" if o == ai else "hu")))
        grid.append(row)
    return grid


def correlated_from_grid(grid) -> dict:
    """勝敗結果の表（"ai" / "hu" / "draw" / "none" のマス目）が**相関している葉**か。

    定義は「**全セルの勝敗結果が同じ**」（§0.3 (v)）。**「詰みがあったか」ではない**
    （§7 の 7）——詰みが 1 つあっても、相手の応手で結果が変わるなら相関していない。
    逆に「どのマス目も未決着」でも、結果が揃っていれば相関している。
    """
    flat = [g for row in grid for g in row]
    same = bool(flat) and len(set(flat)) == 1
    return {"correlated": same, "result": flat[0] if same else None,
            "cells": len(flat), "rows": len(grid),
            "cols": len(grid[0]) if grid else 0}


def leaf_correlation(s, ai: int, hu: int) -> dict:
    """1 つの対抗が「相関している葉」か。**全セルの勝敗結果が同じ**なら相関（§0.3 (v)）。

    「詰みがあったか」ではない（§7 の 7）。表そのものは `clash_table` を呼んで作り、
    `lethal` 欄と `outcome_grid` の答えが食い違わないことをその場で確かめる。
    """
    t = clash_table(s, ai, hu)
    grid = outcome_grid(s, ai, hu)
    for r, row in zip(t["rows"], grid):
        for c, g in zip(r["cells"], row):
            if bool(c["lethal"]) != (g == "ai"):
                raise AssertionError("clash_table の lethal と outcome_grid が食い違う")
    return {**correlated_from_grid(grid),
            "ai_has_lethal": bool(t["ai_has_lethal"]),
            "turn": int(t["turn"])}


# ------------------------------------------------------------ 1 局
def _one(args):
    """1 局回して、決定ごとの行と局の要約を返す。**打ち方は素の champion ミラーと同じ。**

    W の計算は `agent._unseen` を呼ぶだけで乱数を消費しないので、
    この関数の対局は「ふつうの champion ミラー」と 1 手も変わらない。
    """
    deck, kw, seed, max_turns = args
    d = load_deck(deck)
    config, pool = mirror_config(d), d["action_deck"]
    agents = [PlannerAgent(seed * 2, opp_decklist=pool, **kw),
              PlannerAgent(seed * 2 + 1, opp_decklist=pool, **kw)]

    s = initial_state(config, seed)
    rows: list = []
    w0 = {}          # 席 → その局の最初の決定の W（§0.3 (iv) の字義どおり）
    w0a = {}         # 席 → 相手に手札が配られてからの最初の決定の W（退化を避けた版）
    wprev = {}       # 席 → 前回の決定の W
    last_clash = None
    steps = 0
    while outcome(s) is None:
        if s.turn_no > max_turns:
            break
        need = decision_players(s)
        if not need:
            break
        for pi in sorted(need):
            unseen = agents[pi]._unseen(s, pi)
            known = observe(s, pi)["opp"]["hand_known_scan"]   # D-121: 便 M の定義（スキャン・B-9 のぶん）のまま
            n_hand = len(s.players[1 - pi].hand)
            wc = world_counts(unseen, n_hand, known)
            wc0 = world_counts(unseen, n_hand, ())
            w0.setdefault(pi, wc["W"])
            if n_hand > 0:
                w0a.setdefault(pi, wc["W"])
            row = {"seed": seed, "seat": pi, "turn": s.turn_no,
                   "phase": s.phase.name,
                   "W": wc["W"], "H_w": wc["H_w"],
                   "W_nokwn": wc0["W"], "H_w_nokwn": wc0["H_w"],
                   "n_hand": n_hand, "pool_size": wc["pool_size"],
                   "known_n": wc["known_n"],
                   "W0": w0[pi], "W0_amb": w0a.get(pi),
                   "D": d_from_w(wc["W"], w0[pi]),
                   "D_amb": (None if pi not in w0a
                             else d_from_w(wc["W"], w0a[pi])),
                   "r": (None if pi not in wprev or not wprev[pi]
                         else 1.0 - wc["W"] / wprev[pi])}
            rows.append(row)
            wprev[pi] = wc["W"]
        if s.phase == Phase.CLASH_SUBMIT and set(need) == {0, 1}:
            last_clash = s
        acts = {pi: agents[pi].act(s, pi) for pi in need}
        s = apply(s, acts)
        steps += 1

    o = outcome(s)
    aborted = o is None
    total_turns = s.turn_no
    mid = mid_turn_of(total_turns)
    decided_by = "other"
    lc = None
    if (not aborted and o != DRAW and last_clash is not None
            and last_clash.turn_no == total_turns):
        decided_by = "clash"
        lc = leaf_correlation(last_clash, 0, 1)
        lc["turn_player"] = int(last_clash.turn_player)
        lc["winner"] = int(o)

    d_mid, d_mid_amb = {}, {}
    for pi in (0, 1):
        cand = [r for r in rows if r["seat"] == pi and r["turn"] == mid]
        d_mid[pi] = cand[0]["D"] if cand else None
        d_mid_amb[pi] = cand[0]["D_amb"] if cand else None

    summary = {"seed": seed, "T": total_turns, "steps": steps,
               "winner": (None if aborted or o == DRAW else int(o)),
               "draw": bool(o == DRAW), "aborted": bool(aborted),
               "decided_by": decided_by, "mid_turn": mid,
               "D_mid": {"0": d_mid[0], "1": d_mid[1]},
               "D_mid_amb": {"0": d_mid_amb[0], "1": d_mid_amb[1]},
               "W0": {"0": w0.get(0), "1": w0.get(1)},
               "W0_amb": {"0": w0a.get(0), "1": w0a.get(1)},
               "seat0_won": (None if aborted or o == DRAW else int(o == 0)),
               "lc": lc}
    return rows, summary


def series(deck: str, kw: dict, seeds: list, workers: int = 2,
           max_turns: int = 200) -> list:
    jobs = [(deck, kw, s, max_turns) for s in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_one, jobs, chunksize=1))
    return [_one(j) for j in jobs]


# ------------------------------------------------------------ 集計
def _quantiles(xs: list) -> dict:
    if not xs:
        return {"n": 0, "median": None, "q1": None, "q3": None,
                "min": None, "max": None}
    v = sorted(xs)

    def q(f):
        if len(v) == 1:
            return v[0]
        i = f * (len(v) - 1)
        lo, hi = int(math.floor(i)), int(math.ceil(i))
        return v[lo] + (v[hi] - v[lo]) * (i - lo)
    return {"n": len(v), "median": q(0.5), "q1": q(0.25), "q3": q(0.75),
            "min": v[0], "max": v[-1]}


def aggregate(rows: list, summaries: list) -> dict:
    out = {"games": len(summaries), "decisions": len(rows),
           "definitions": DEFINITIONS,
           "threshold": D_MID_THRESHOLD}

    # --- M5: D_mid（字義どおりの D と、退化を避けた D_amb の両方） -----------
    for key, field in (("D_mid", "D_mid"), ("D_mid_amb", "D_mid_amb")):
        dm = {"0": [], "1": [], "both": []}
        for s in summaries:
            for seat in ("0", "1"):
                x = (s.get(field) or {}).get(seat)
                if x is not None:
                    dm[seat].append(x)
                    dm["both"].append(x)
        out[key] = {k: {**_quantiles(v),
                        "gt_threshold": (sum(1 for x in v if x > D_MID_THRESHOLD) / len(v))
                        if v else None}
                    for k, v in dm.items()}
        out[key + "_answer"] = (None if not dm["both"] else
                                ("above" if _quantiles(dm["both"])["median"] > D_MID_THRESHOLD
                                 else "at_or_below"))
    # 読みに使うのは退化していない方（§6 の判断が要る点 (1)）
    out["answer_used"] = "D_mid_amb"
    out["D_mid_degenerate"] = bool(out["D_mid"]["both"]["min"] == 1.0
                                   and out["D_mid"]["both"]["max"] == 1.0) \
        if out["D_mid"]["both"]["n"] else None

    # --- ターン別の D_t の曲線 ---------------------------------------------
    for key, field in (("D_by_turn", "D"), ("D_amb_by_turn", "D_amb")):
        curve = {}
        for t in range(1, TURN_CURVE_MAX + 1):
            v = [r[field] for r in rows if r["turn"] == t and r.get(field) is not None]
            curve[str(t)] = {**_quantiles(v)}
        out[key] = curve

    # --- H_t と W の分布 ----------------------------------------------------
    out["W"] = _quantiles([r["W"] for r in rows])
    out["W_nokwn"] = _quantiles([r["W_nokwn"] for r in rows])
    out["H_w"] = _quantiles([r["H_w"] for r in rows if r["H_w"] is not None])
    out["known_used"] = {
        "decisions_with_known": sum(1 for r in rows if r["known_n"] > 0),
        "rate": (sum(1 for r in rows if r["known_n"] > 0) / len(rows)) if rows else None,
        "mean_W_ratio": (sum(r["W"] / r["W_nokwn"] for r in rows if r["W_nokwn"])
                         / max(1, sum(1 for r in rows if r["W_nokwn"]))),
    }
    out["W0"] = _quantiles([s["W0"][k] for s in summaries for k in ("0", "1")
                            if s["W0"][k] is not None])
    out["W0_amb"] = _quantiles([(s.get("W0_amb") or {}).get(k) for s in summaries
                                for k in ("0", "1")
                                if (s.get("W0_amb") or {}).get(k) is not None])

    # --- df（r_t） ---------------------------------------------------------
    rs = [r["r"] for r in rows if r["r"] is not None]
    out["r"] = {**_quantiles(rs),
                "mean": (sum(rs) / len(rs)) if rs else None}

    # --- M1: lc / bias -----------------------------------------------------
    clash = [s for s in summaries if s["decided_by"] == "clash"]
    corr = [s for s in clash if s["lc"] and s["lc"]["correlated"]]
    out["lc"] = {"n_decided_by_clash": len(clash),
                 "n_correlated": len(corr),
                 "lc": (len(corr) / len(clash)) if clash else None,
                 "n_decided_by_other": len(summaries) - len(clash),
                 "table_cells": _quantiles([s["lc"]["cells"] for s in clash if s["lc"]])}
    seat0 = [s for s in corr if s["seat0_won"] == 1]
    tp = [s for s in corr if s["winner"] == s["lc"]["turn_player"]]
    out["bias"] = {"n": len(corr),
                   "seat0_wins": len(seat0),
                   "p_seat0": (len(seat0) / len(corr)) if corr else None,
                   "turn_player_wins": len(tp),
                   "p_turn_player": (len(tp) / len(corr)) if corr else None}
    out["games_aborted"] = sum(1 for s in summaries if s["aborted"])
    out["games_draw"] = sum(1 for s in summaries if s["draw"])
    return out


def _fmt(x, d=3):
    return "―" if x is None else f"{x:.{d}f}"


def render(agg: dict) -> str:
    lit = agg["D_mid"]["both"]
    dm = agg["D_mid_amb"]["both"]
    L = ["■ M5 曖昧さ解消率 ／ M1 PIMC の三性質（champion ミラー）",
         "",
         f"  局数 {agg['games']}／決定 {agg['decisions']}"
         f"（引き分け {agg['games_draw']}・打ち切り {agg['games_aborted']}）",
         "",
         "── M5 disambiguation ──",
         f"  【字義どおりの定義】中盤の D_t: 中央値 {_fmt(lit['median'])}"
         f"（四分位 {_fmt(lit['q1'])} / {_fmt(lit['q3'])}・n={lit['n']}）"
         + ("　※ **退化している**（その席の最初の決定は配る前のキャラ配置で "
            "W_0 = 1。定義により D_t は必ず 1 になる）"
            if agg.get("D_mid_degenerate") else ""),
         f"  【読みに使う定義】W_0 を「配られた後の最初の決定」にした D_t: 中央値 "
         f"**{_fmt(dm['median'])}**"
         f"（四分位 {_fmt(dm['q1'])} / {_fmt(dm['q3'])}・n={dm['n']}）",
         f"  0.3 を超える局の割合: {_fmt(dm['gt_threshold'])}",
         f"  席別の中央値: 席 0 {_fmt(agg['D_mid_amb']['0']['median'])}"
         f" ／ 席 1 {_fmt(agg['D_mid_amb']['1']['median'])}",
         f"  → **便 B の優先度 = "
         + ("上げる（0.3 超え）" if agg["D_mid_amb_answer"] == "above"
            else "上げない（0.3 以下）") + "**",
         "",
         f"  W（区別できる手札の数）中央値 {agg['W']['median']}"
         f"（最小 {agg['W']['min']} / 最大 {agg['W']['max']}）"
         f"／配られた直後の W_0 中央値 {agg['W0_amb']['median']}"
         f"（字義どおりの W_0 中央値 {agg['W0']['median']}）",
         f"  H_w 中央値 "
         + ("―" if agg["H_w"]["median"] is None else f"{agg['H_w']['median']:.3f} bit"),
         f"  スキャンで見た札がある決定 {agg['known_used']['rate']:.3f}"
         f"／W が hand_known で縮む比 {agg['known_used']['mean_W_ratio']:.3f}"
         "（1.000 なら探索が捨てている情報は無い）",
         f"  r_t（前回の決定からの縮み）平均 "
         + ("―" if agg["r"]["mean"] is None else f"{agg['r']['mean']:+.3f}"),
         "",
         "── M1 三性質 ──",
         f"  lc（葉の相関）= "
         + ("―" if agg["lc"]["lc"] is None else
            f"**{agg['lc']['lc']:.3f}**（{agg['lc']['n_correlated']}"
            f"/{agg['lc']['n_decided_by_clash']}）")
         + f"　対抗以外で決着した局 {agg['lc']['n_decided_by_other']}",
         f"  bias（相関している表のうち席 0 が勝つ割合）= "
         + ("―" if agg["bias"]["p_seat0"] is None else
            f"{agg['bias']['p_seat0']:.3f}（{agg['bias']['seat0_wins']}"
            f"/{agg['bias']['n']}）")
         + "　ターンプレイヤーが勝つ割合 "
         + ("―" if agg["bias"]["p_turn_player"] is None
            else f"{agg['bias']['p_turn_player']:.3f}"),
         f"  df = r_t と兼用（上）",
         "",
         "  読み方: lc が低いほど「最後の一手で結果がひっくり返る」＝決定化の本数を",
         "  増やす投資（便 C の II-7 の 6 → 24〜40）は効きが薄い（第 1 集 §1.3.6）。"]
    return "\n".join(L)


# ------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed0", type=int, default=BAND[0])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--chunk", type=int, default=10, help="1 塊の局数（中断の粒度）")
    ap.add_argument("--budget-sec", type=float, default=480.0)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--out", default=os.path.join(_HERE, "..", "results", "lit",
                                                  "m5m1_pimc.json"))
    ap.add_argument("--rows", default=None, help="1 行 1 決定の JSONL（既定は --out の .jsonl）")
    ap.add_argument("--report", action="store_true", help="回さずに集計だけ出す")
    args = ap.parse_args(argv)

    kw = resolved_kwargs(args.deck)
    rows_path = args.rows or (os.path.splitext(args.out)[0] + ".jsonl")
    sums_path = os.path.splitext(args.out)[0] + ".games.jsonl"
    os.makedirs(os.path.dirname(os.path.abspath(rows_path)), exist_ok=True)

    rows: list = []
    summaries: list = []
    done: set = set()
    if os.path.exists(sums_path):
        with open(sums_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    s = json.loads(line)
                    summaries.append(s)
                    done.add(s["seed"])
        with open(rows_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r["seed"] in done:
                        rows.append(r)
        print(f"  ※ 途中から再開（{len(summaries)}/{args.n} 局）", flush=True)

    todo = [s for s in range(args.seed0, args.seed0 + args.n) if s not in done]
    if todo and not args.report:
        t0 = time.time()
        with open(rows_path, "a", encoding="utf-8") as fr, \
                open(sums_path, "a", encoding="utf-8") as fs:
            while todo and time.time() - t0 < args.budget_sec:
                block = todo[:args.chunk]
                todo = todo[args.chunk:]
                for rs, sm in series(args.deck, kw, block, args.workers,
                                     args.max_turns):
                    for r in rs:
                        fr.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fs.write(json.dumps(sm, ensure_ascii=False) + "\n")
                    rows.extend(rs)
                    summaries.append(sm)
                fr.flush()
                fs.flush()
                a = aggregate(rows, summaries)
                med = a["D_mid_amb"]["both"]["median"]
                print(f"  {len(summaries)}/{args.n} 局: 中盤 D_t の中央値 "
                      + ("―" if med is None else f"{med:.3f}")
                      + f"／lc "
                      + ("―" if a["lc"]["lc"] is None else f"{a['lc']['lc']:.3f}")
                      + f"　{time.time() - t0:.0f}s", flush=True)

    agg = aggregate(rows, summaries)
    print()
    print(render(agg))
    import provenance
    out = {"agg": agg, "n_wanted": args.n, "seed0": args.seed0,
           "rows_file": os.path.basename(rows_path),
           "games_file": os.path.basename(sums_path),
           # 局ごとの要約は JSON にも入れる（引継ぎ書 §0.4 の 3）。
           # 決定ごとの行（18,000 件級）は `.jsonl` の側にだけ置く。
           "games": sorted(summaries, key=lambda x: x["seed"]),
           "definitions": DEFINITIONS,
           "provenance": provenance.block(
               kw, "python", (args.seed0, args.seed0 + args.n - 1),
               extra={"tool": "diag_pimc", "M": "M5/M1",
                      "host": provenance.host_name(), "workers": int(args.workers),
                      "note": "診断専用。打ち方は変えていない（W の計算は乱数を消費しない）"})}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {args.out}")
    finished = len(summaries) >= args.n
    print("（完了）" if finished else "（途中。同じコマンドで続きから回る）")
    return 0 if finished or args.report else 3


if __name__ == "__main__":
    sys.exit(main())
