"""便 A 後半（A-2 束ねたソルバ）— 回帰 4 局面で**何を選ぶか**を記録する道具。

## なぜ要るか

便 C は回帰 4 局面について**覆い率**（真の相手手札を決定化が捉えているか）だけを測り、
**選ぶ手が変わったかは記録していない**（`LIT_NOTES.md` §C-3）。
とくに 9/3 g002（青で受けた負け）は段 C-3 の `endgame_enum` で覆い率が 0.50 → 1.00 になり
「確実に読める側」に入ったが、**そこで何を出すかは未測定**である。

引継ぎ書 `HANDOFF_20260911_LIT_A2.md` §3.1 (a) の「便 C が残した空白」がここで、
**対局を 1 局も回さずに**埋まる。A2-2（§3.3）では同じ口に `bundle_p` を足して
基準と並べる。**関門ではなく診断**である（§0.3 (i)・便 C の §0.3 (i) と同じ扱い）。

## 局面の取り方

`coverage.regression_positions()` をそのまま呼ぶ（写して書き換えない・D-075 の教訓）。
`tests/test_lit_a.py::_human_clash_positions()` は 9/3 の 2 局面しか返さないので使わない
（9/8 の 2 局面を取りこぼす・引継ぎ書 §3.1 (a)）。

## エージェントの作り方

`PlannerAgent(seed, opp_decklist=pool, **champion.kwargs_for("SD001"))`。
`seed` は記録に残っている対局時の相手（＝AI）のシードで、
`tests/test_lit_a.py` が回帰局面を引くときと**同じ約束**である。

**`opp_decklist` は必ず一緒に渡すこと。** 新 champion は `endgame_enum` を持つので、
単独では起動時に `ValueError` になる（仕様・`tests/test_lit_c.py::T-C-19`）。
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import champion                                            # noqa: E402
from arena import load_deck                                # noqa: E402
from coverage import _seed_history, regression_positions   # noqa: E402
from meicho.planner import PlannerAgent                     # noqa: E402

# 候補名 → champion に足す引数。`base` は現 champion そのもの（基準点）。
CANDIDATES: dict = {
    "base": {},
    "b90": {"bundle_p": 0.9},
    "b75": {"bundle_p": 0.75},
    "b50": {"bundle_p": 0.5},
    # `bundle_p=1.0` は「現行と一手一点まで同じ」であることの基準点（T-A2-2）。
    # 候補ではないが、この口からも確かめられるようにしておく。
    "b100": {"bundle_p": 1.0},
}


def _act_name(s, ai: int, act: dict) -> str:
    """提出した札の名前（パスは "パス"）。表示用。"""
    if act.get("type") != "submit":
        return act.get("type", "?")
    from meicho.cards import ACTION_CARDS
    return ACTION_CARDS[s.players[ai].hand[act["hand"]]].name


def pick_at_positions(extra: dict, path: str = None) -> list:
    """回帰 4 局面それぞれで champion(+extra) が何を選ぶかと点数表を返す。

    **対局は 1 局も回さない。**決定的（乱数はエージェントのシードだけに由来する）。
    """
    d = load_deck("SD001")
    pool = d["action_deck"]
    kw = {**champion.kwargs_for("SD001"), **extra}
    rows = []
    for tag, s, ai, seed, hu_act, why, prior in regression_positions(path):
        ag = PlannerAgent(seed, opp_decklist=pool, **kw)
        _seed_history(ag, ai, prior)          # world_weight が無ければ何もしない
        act = ag.act(s, ai)
        lc = dict(ag.last_clash or {})
        rows.append({
            "tag": tag, "why": why, "turn": int(s.turn_no), "ai_seat": int(ai),
            "seed": int(seed),
            "chosen_name": _act_name(s, ai, act),
            "chosen_index": lc.get("chosen"),
            "acts": lc.get("acts"),
            "totals": lc.get("totals"),
            # 相手がそのとき実際に出した札（公開情報）。読みの材料。
            "human_played": (_act_name(s, 1 - ai, hu_act)
                             if hu_act.get("type") == "submit" else "パス"),
        })
    return rows


def run(names: list, path: str = None) -> dict:
    out = {"candidates": {}, "definitions": {
        "chosen_name": "その局面で AI が提出した札の名前（パスなら 'パス'）",
        "totals": "決定化 1 本あたりに直した各手の点数（`last_clash.totals`）",
        "acts": "点数表の並び（合法手の順）。`chosen_index` はこの並びの添字",
        "human_played": "そのときマスターが実際に出した札（記録・公開情報）",
    }}
    for name in names:
        if name not in CANDIDATES:
            raise ValueError(f"未登録の候補: {name}")
        out["candidates"][name] = pick_at_positions(CANDIDATES[name], path)
    return out


def render(res: dict) -> str:
    L = ["■ 回帰 4 局面で何を選ぶか（対局なし・**関門ではなく診断**）", ""]
    names = list(res["candidates"])
    tags = [r["tag"] for r in res["candidates"][names[0]]]
    for i, tag in enumerate(tags):
        r0 = res["candidates"][names[0]][i]
        L.append(f"  {tag}（{r0['why']}）")
        L.append(f"    T{r0['turn']}・AI は席 {r0['ai_seat']}・"
                 f"マスターの提出 {r0['human_played']}")
        for name in names:
            r = res["candidates"][name][i]
            ts = r["totals"] or []
            top = (f"{max(ts):.4f}" if ts else "-")
            L.append(f"      {name:5s} → {r['chosen_name']}（最良 {top}・"
                     f"手 {len(r['acts'] or [])} 通り）")
        base = res["candidates"][names[0]][i]["chosen_name"]
        diff = [n for n in names[1:]
                if res["candidates"][n][i]["chosen_name"] != base]
        L.append(f"      基準と違う手を選んだ候補: {diff if diff else 'なし'}")
        L.append("")
    return "\n".join(L)


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cands", default="base",
                    help="カンマ区切りの候補名（既定 base）")
    ap.add_argument("--out", default=None, help="書き出す JSON のパス")
    a = ap.parse_args(argv)
    names = [x.strip() for x in a.cands.split(",") if x.strip()]
    res = run(names)
    print(render(res))
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f"  → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
