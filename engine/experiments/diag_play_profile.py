"""「打ち方の近さ」の診断（設計書 `DECK_SIMILARITY_DESIGN.md` §8・D-130）。

    python3 experiments/diag_play_profile.py run --seed0 826000 --n 200 --out results/decksim/play_profile_v1.json
    python3 experiments/diag_play_profile.py report --in results/decksim/play_profile_v1.json

構成の近さ（decksim・層 1〜3）は「デッキに何が入っているか」しか見ない。ここでは同じネット無しの教師
（`record_mix.NETFREE`）に各デッキを持たせて固定の相手群（H・貪欲・素 planner）と打たせ、
**実際にどう打ったか**のプロフィールを比べる。候補を選ぶ物差しにはしない（§8）。
「構成は遠いのに打ち方が近い」組があれば、閾値（`th-1-provisional`）を**次の候補集合から**見直す材料にする。

## 回し方（候補を見る前に固定した・D-130）

- 教師は A 席、相手（H／貪欲／素 planner）は B 席。**相手のデッキは全デッキ共通の SD001**
  （相手のデッキまで候補と一緒に動くと、打ち方の差が相手のせいか分からなくなるため）
- `series` は奇数シードで A/B の席を入れ替え、デッキは席に固定なので、教師が候補デッキを持つのは
  **偶数シードの局だけ**である。数えるのはその局だけ（奇数シードは教師が SD001 を持つので捨てる）。
  記録は教師の席だけ（`record_a=True`・`opp_from_seat=True`）
- 同じシード帯をすべての（デッキ, 相手）に使う（共通の乱数で比べる）

## プロフィール（1 デッキ = 1 本のベクトル）

教師の**記録された決定**（選択肢が 1 つしかない場面は記録されない）から:

- `act` 行動の種類の割合: charge・switch・levelup・to_clash・end_turn・submit・pass・rush（8）
- `color` 対抗で出した札（submit）の色の割合: 赤・緑・青（3）
- `cost` 対抗で出した札のコスト帯の割合: 0-1・2・3・4+（4）
- `win` 相手ごとの勝率: H・貪欲・素 planner（3）
- `tempo` 局の長さ・教師が初めて与えたダメージのターン・初めて受けたダメージのターン（3・どれも局の平均÷10）。
  ダメージは記録の観測のライフ（自分 `obs[0]`・相手 `obs[1]`）が局の最初の記録より減った最初の決定のターンで見る
  （決定の無い時点で起きたダメージは次の決定で気づく）。一度も無ければ局の最後のターン＋1 を入れる

24 デッキで各特徴を z 化（分散 0 の特徴は落とす）し、距離はユークリッド距離÷√次元数。

## 旗の規則（候補を見る前に固定・D-130）

異なるグループ（`env_v1.json` の `decks_block[].group`）の組で、距離が
**同じグループの組の距離の中央値**より小さいものに旗を立てる。同じグループの組には立てない。
あわせて「同じデッキを偶数シードの半分ずつ（シード ≡ 0 と ≡ 2 mod 4）に分けた距離」の中央値を
**測り直しのぶれ**として出す（これより小さい差は読めない）。
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import shutil
import statistics
import sys
import time
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                                    # noqa: E402

from arena import load_deck, matchup_config                               # noqa: E402
from arena_rs import GREEDY, HEURISTIC, PLANNER, ensure_cards             # noqa: E402
from drl_record import check_record_band                                  # noqa: E402
from record_mix import NETFREE                                            # noqa: E402
from meicho.buckets import _COLOR_IX, cost_band                           # noqa: E402
from meicho.cards import ACTION_CARDS                                     # noqa: E402
from meicho.drl_data import read_records                                  # noqa: E402
from meicho.encode import ACTION_IDS, ACTION_TYPES                        # noqa: E402

TOOL_VERSION = "playprof-1"
OPPONENTS = ("heuristic", "greedy", "planner")
ACT_KINDS = ("charge", "switch", "levelup", "to_clash", "end_turn", "submit", "pass", "rush")
DEFAULT_ENV = os.path.join(_HERE, "..", "results", "decksim", "env_v1.json")


def _opp_spec(kind: str, pool: list) -> dict:
    return {"heuristic": HEURISTIC, "greedy": lambda: GREEDY(pool), "planner": lambda: PLANNER(pool)}[kind]()


def run_deck(deck: str, opp_deck: str, opponents, *, n: int, seed0: int, workers: int, tmp: str) -> dict:
    """1 デッキぶんを回して生の数を返す（プロフィールは `profile` で作る）。"""
    check_record_band(seed0)
    check_record_band(seed0 + n - 1)
    ensure_cards()
    d, o = load_deck(deck), load_deck(opp_deck)
    cfg = matchup_config(d, o)          # 席 0 = 候補デッキ・席 1 = 共通の相手デッキ
    cfg.validate()
    out = {"deck": deck, "opp_deck": opp_deck, "n": n, "seed0": seed0, "by_opponent": {}}
    os.makedirs(tmp, exist_ok=True)
    for kind in opponents:
        prefix = os.path.join(tmp, f"{deck.replace('/', '_')}_{kind}")
        spec_a = PLANNER(o["action_deck"], **NETFREE)
        spec_b = _opp_spec(kind, d["action_deck"])
        res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, spec_a, spec_b, seed0, n,
                                      prefix, workers, 200, True, False, opp_from_seat=True)
        used = [s for s in range(seed0, seed0 + n) if s % 2 == 0]
        results = [[seed0 + i, r[0], int(r[1])] for i, r in enumerate(res) if (seed0 + i) % 2 == 0]
        rec = read_records(files)
        keep = [i for i in range(rec.n) if int(rec.seed[i]) % 2 == 0]
        act, color, cost = Counter(), [0, 0, 0], [0, 0, 0, 0]
        per_game = {s: {"act": [0] * len(ACT_KINDS), "color": [0, 0, 0], "cost": [0, 0, 0, 0]} for s in used}
        pis = Counter(str(int(rec.pi[i])) for i in keep)
        first_deal, first_take, start = {}, {}, {}
        for i in keep:
            s, t = int(rec.seed[i]), int(rec.turn[i])
            ob = rec.obs[i]
            if s not in start:
                start[s] = (int(ob[0]), int(ob[1]))
            if s not in first_take and int(ob[0]) < start[s][0]:
                first_take[s] = t
            if s not in first_deal and int(ob[1]) < start[s][1]:
                first_deal[s] = t
            code = rec.actions_of(i)[int(rec.chosen[i])]
            typ = ACTION_TYPES[int(code[0])]
            if typ in ACT_KINDS:
                act[typ] += 1
                per_game[s]["act"][ACT_KINDS.index(typ)] += 1
            if typ == "submit" and int(code[1]) >= 0:
                c = ACTION_CARDS[ACTION_IDS[int(code[1])]]
                color[_COLOR_IX[c.color]] += 1
                cost[cost_band(c.cost)] += 1
                per_game[s]["color"][_COLOR_IX[c.color]] += 1
                per_game[s]["cost"][cost_band(c.cost)] += 1
        turns = {r[0]: r[2] for r in results}
        out["by_opponent"][kind] = {
            "seeds_used": used, "games": len(used), "results": results,
            "decisions": len(keep), "records_pi": dict(pis),
            "act_counts": {k: act[k] for k in ACT_KINDS}, "color_counts": color, "cost_counts": cost,
            "first_deal": [first_deal.get(s, turns[s] + 1) for s in used],
            "first_take": [first_take.get(s, turns[s] + 1) for s in used],
            "per_game": [per_game[s] for s in used],
        }
        for p in files:
            os.remove(p)
    return out


def _shares(counts):
    tot = sum(counts)
    return [c / tot for c in counts] if tot else [0.0] * len(counts)


def profile(raw: dict, seed_filter=None) -> dict:
    """生の数 → プロフィール。`seed_filter` を渡すとその局だけで作り直す（ぶれの見積もり用。全特徴を局ごとの数から作る）。"""
    act, color, cost = Counter(), [0, 0, 0], [0, 0, 0, 0]
    win, turns, deal, take = [], [], [], []
    for kind in OPPONENTS:
        b = raw["by_opponent"].get(kind)
        if b is None:
            win.append(0.0)
            continue
        idx = [j for j, s in enumerate(b["seeds_used"]) if seed_filter is None or seed_filter(s)]
        res = [b["results"][j] for j in idx]
        dec = [r[1] for r in res if r[1] is not None]
        win.append(sum(dec) / len(dec) if dec else 0.0)
        turns += [r[2] for r in res]
        deal += [b["first_deal"][j] for j in idx]
        take += [b["first_take"][j] for j in idx]
        for j in idx:
            g = b["per_game"][j]
            for k, v in zip(ACT_KINDS, g["act"]):
                act[k] += v
            color = [a + c for a, c in zip(color, g["color"])]
            cost = [a + c for a, c in zip(cost, g["cost"])]
    m = (lambda xs: sum(xs) / len(xs) / 10 if xs else 0.0)
    return {"act": _shares([act[k] for k in ACT_KINDS]), "color": _shares(color), "cost": _shares(cost),
            "win": win, "tempo": [m(turns), m(deal), m(take)]}


def _flat(p: dict) -> list:
    return p["act"] + p["color"] + p["cost"] + p["win"] + p["tempo"]


def zscore(vecs: dict) -> dict:
    names = sorted(vecs)
    dim = len(vecs[names[0]])
    keep, mu, sd = [], [], []
    for k in range(dim):
        col = [vecs[n][k] for n in names]
        s = statistics.pstdev(col)
        if s > 1e-12:
            keep.append(k)
            mu.append(statistics.fmean(col))
            sd.append(s)
    return {n: [(vecs[n][k] - m) / s for k, m, s in zip(keep, mu, sd)] for n in names}, keep, mu, sd


def dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)) if a else 0.0


def flag_pairs(vec: dict, group: dict) -> dict:
    names = sorted(vec)
    within, cross = [], []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            d = dist(vec[a], vec[b])
            (within if group[a] == group[b] else cross).append({"pair": [a, b], "d": d})
    med = statistics.median([x["d"] for x in within]) if within else None
    flagged = sorted([x for x in cross if med is not None and x["d"] < med], key=lambda x: x["d"])
    return {"within_median": med, "within": within, "cross": cross, "flagged": flagged}


def report(raw_all: dict, env: dict) -> dict:
    decks = sorted(raw_all["decks"])
    group = {d: env["decks_block"][d.split("/", 1)[1]]["group"] for d in decks}
    split = {d: env["decks_block"][d.split("/", 1)[1]]["split"] for d in decks}
    prof = {d: profile(raw_all["decks"][d]) for d in decks}
    z, keep, mu, sd = zscore({d: _flat(prof[d]) for d in decks})
    fp = flag_pairs(z, group)
    # 測り直しのぶれ: 偶数シードを ≡0 / ≡2 (mod 4) に分けた 2 本の距離（同じ z の尺度で）
    half = []
    for d in decks:
        va = _flat(profile(raw_all["decks"][d], lambda s: s % 4 == 0))
        vb = _flat(profile(raw_all["decks"][d], lambda s: s % 4 == 2))
        za = [(va[k] - m) / s for k, m, s in zip(keep, mu, sd)]
        zb = [(vb[k] - m) / s for k, m, s in zip(keep, mu, sd)]
        half.append({"deck": d, "d": dist(za, zb)})
    return {"version": TOOL_VERSION, "decks": decks, "group": group, "split": split, "profile": prof,
            "features_kept": keep, "within_median": fp["within_median"],
            "half_split_median": statistics.median([h["d"] for h in half]), "half_split": half,
            "flagged": fp["flagged"], "within": fp["within"], "cross": fp["cross"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--env", default=DEFAULT_ENV)
    r.add_argument("--opp-deck", default="SD001")
    r.add_argument("--n", type=int, default=200)
    r.add_argument("--seed0", type=int, required=True)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--out", required=True)
    r.add_argument("--only", nargs="*", default=None)
    r.add_argument("--budget-sec", type=float, default=450.0, help="この秒数を超えたら次のデッキに入らずに止める（再開可能）")
    q = sub.add_parser("report")
    q.add_argument("--env", default=DEFAULT_ENV)
    q.add_argument("--in", dest="inp", required=True)
    q.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    with open(args.env, encoding="utf-8") as f:
        env = json.load(f)
    if args.cmd == "run":
        allowed = sorted(f"env/{k}" for k in env["decks_block"])
        todo = args.only or allowed
        data = {"version": TOOL_VERSION, "decision": "D-130", "opp_deck": args.opp_deck, "n": args.n,
                "seed0": args.seed0, "teacher": dict(NETFREE), "opponents": list(OPPONENTS), "decks": {}}
        if os.path.exists(args.out):
            with open(args.out, encoding="utf-8") as f:
                data = json.load(f)
            assert (data["n"], data["seed0"], data["opp_deck"]) == (args.n, args.seed0, args.opp_deck), \
                "既存の結果と条件が違う（別の --out にすること）"
        t0 = time.time()
        tmp = os.path.join(os.path.dirname(os.path.abspath(args.out)), "_playprof_tmp")
        for deck in todo:
            if deck in data["decks"]:
                continue
            if time.time() - t0 > args.budget_sec:
                print(f"予算 {args.budget_sec} 秒を超えたので止める（続きは同じコマンドで再開）")
                break
            t = time.time()
            data["decks"][deck] = run_deck(deck, args.opp_deck, OPPONENTS, n=args.n, seed0=args.seed0,
                                           workers=args.workers, tmp=tmp)
            data["decks"][deck]["seconds"] = round(time.time() - t, 1)
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            print(f"{deck}: {data['decks'][deck]['seconds']} 秒（{len(data['decks'])}/{len(todo)}）", flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
        return data
    with open(args.inp, encoding="utf-8") as f:
        raw = json.load(f)
    rep = report(raw, env)
    out = args.out or args.inp.replace(".json", "_report.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps({"within_median": rep["within_median"], "half_split_median": rep["half_split_median"],
                      "flagged": len(rep["flagged"]), "cross": len(rep["cross"])}, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    main()
