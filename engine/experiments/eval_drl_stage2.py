"""DRL 段階 2（専門家反復）の 1 反復ぶんの検証（`DRL_PLAN.md` §6.1(d)(e)・D-059）。

## この文書（と出力）の読み方

段階 2 の 1 反復は「現 champion どうしで対戦を記録する → その記録でネットを学習し直す →
新しいネットを積んだ AI が、現 champion に勝ち越すか測る」である。この道具は最後の
「測る」を担う。

出す数字は 4 種類ある。

1. **門番** — 新しい AI と現 champion を直接対決させた勝率。採否はこれだけで決める（D-034）。
   勝率のうしろの ± は 95% 信頼区間、つまり「同じ条件で測り直したらだいたいこの幅に収まる」幅である。
   **下端が 0.5 を超えたときだけ**「強くなった」と言ってよい。
2. **対照** — 現 champion どうしを同じ条件で当てた勝率。0.5 付近に出るのが正しい。
   ここがずれていたら測り方が壊れているので、1 の数字も信用しない。
3. **相手を変えた測定** — H（規則ベース）と貪欲に対する勝率を、新旧で**同じシード**で取る。
   D-058 で「相手モデルを π にする利得は、相手が強いほど大きい」と分かっているので、
   どの相手で得をして、どの相手で損をするかを毎回残す。
4. **カナリア** — 漂泊者（女）Lv2 への到達率と到達ターン（`measure_horizon.py` の型）。
   これは強さではなく**癖**の指標である。計画探索は「費用は今ターン・便益は次ターン以降」の
   手を取りこぼす癖があり（D-045/046）、価値ネットが勝敗から学べばこの癖は
   教えなくても直るはず、というのが計画の予言である（`DRL_PLAN.md` §0.3）。

使い方:
    python3 experiments/eval_drl_stage2.py --net results/models/drl_sd001_s2r1.json \
        --n 1200 --workers 2 --seed0 300000 --out results/drl/stage2_r1_eval.json
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

import meicho_rs as rs                                                    # noqa: E402

import champion                                                          # noqa: E402
from arena import load_deck, mirror_config                               # noqa: E402
from arena_rs import GREEDY, HEURISTIC, PLANNER, ensure_cards, series_rs  # noqa: E402


def NEW(pool: list, path: str) -> dict:
    """新しい π を積んだ AI。**champion と同じ形**（相手モデル = π・根だけ）で、中身だけ新しい。"""
    return PLANNER(pool, opp_policy_net=path, opp_policy_root_only=True)


def canary(deck: str, pool: str, net: str | None, seeds) -> dict:
    """漂泊者 Lv2 の到達率（Python 版・`measure_rush_lv2._trace`）。"""
    from measure_rush_lv2 import _trace
    from meicho.heuristic import HeuristicAgent
    from meicho.planner import PlannerAgent
    kw = dict(opp_decklist=pool)
    if net:
        kw.update(opp_policy_net=net, opp_policy_root_only=True)
    return _trace(lambda s: PlannerAgent(s, **kw), lambda s: HeuristicAgent(s), seeds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--net", required=True, help="新しい π（学習の出力）")
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=300000)
    ap.add_argument("--gap", type=int, default=1300, help="1 本ごとに進めるシードの幅（重ならないように）")
    ap.add_argument("--canary-seed0", type=int, default=306000)
    ap.add_argument("--canary-n", type=int, default=40)
    ap.add_argument("--skip-canary", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ensure_cards()
    deck = load_deck(args.deck)
    config = mirror_config(deck)
    pool = deck["action_deck"]
    path = os.path.abspath(args.net)
    rs.net_forget(path)                      # 同じパスを上書きした場合に備える（規約）

    champ = champion.spec(args.deck, pool)
    new = NEW(pool, path)
    print(f"現 champion: {champion.describe(args.deck)}")
    print(f"新しい版　 : 計画探索＋相手モデル=π（{os.path.basename(args.net)}・根だけ）")
    print()

    runs = [
        ("1.  門番: 新 vs 現champion",      new,           champ),
        ("2.  対照: 現champion vs 現champion", champ,      champ),
        ("3a. 新 vs H",                     new,           HEURISTIC()),
        ("3b. 現champion vs H",             champ,         HEURISTIC()),
        ("3c. 新 vs 貪欲",                  new,           GREEDY(pool)),
        ("3d. 現champion vs 貪欲",          champ,         GREEDY(pool)),
    ]
    # 3a と 3b（3c と 3d）は**同じシード**で取る。対照実験は同じシードで取り直すのが約束（D-039）。
    seeds = [args.seed0 + args.gap * i for i in range(4)]
    seed_of = {0: seeds[0], 1: seeds[1], 2: seeds[2], 3: seeds[2], 4: seeds[3], 5: seeds[3]}

    out = {"net": os.path.basename(args.net), "deck": args.deck, "n": args.n,
           "champion": champion.describe(args.deck), "runs": []}
    for i, (name, a, b) in enumerate(runs):
        seed = seed_of[i]
        t0 = time.time()
        r = series_rs(a, b, args.n, config, workers=args.workers, seed0=seed)
        dt = time.time() - t0
        lo, hi = r.p - r.ci, r.p + r.ci
        note = ""
        if i == 0:
            note = "  → " + ("**門番を越えた**" if lo > 0.5 else "越えない")
        print(f"{name:34s} {r}  下端 {lo:.3f} / 上端 {hi:.3f}"
              f"  [{seed}..{seed + args.n - 1}, {args.n / dt:.1f} 局/秒]{note}", flush=True)
        out["runs"].append({"name": name, "seed0": seed, "wins": r.wins, "decided": r.decided,
                            "games": r.games, "p": r.p, "ci": r.ci, "lo": lo, "hi": hi,
                            "passes_gate": bool(lo > 0.5), "rate": args.n / dt})

    if not args.skip_canary:
        print()
        print(f"■ カナリア: 漂泊者(女)Lv2 到達（対 H・{args.canary_n} 局・"
              f"シード {args.canary_seed0}..{args.canary_seed0 + args.canary_n - 1}）")
        cs = list(range(args.canary_seed0, args.canary_seed0 + args.canary_n))
        out["canary"] = {}
        for label, net in (("現champion", champion.kwargs_for(args.deck).get("opp_policy_net")),
                           ("新しい版", args.net)):
            from meicho.drlnet import resolve_model
            t = canary(args.deck, pool, resolve_model(net) if net else None, cs)
            mt = "—" if t["mean_turn"] is None else f"{t['mean_turn']:.1f}"
            print(f"  {label:10s}: 到達 {t['reached']:2d}/{t['games']}／到達ターン 平均 {mt:>5s}"
                  f"／Lv2 が引かせた枚数 平均 {t['total_extra_draws_per_game']:.2f}")
            out["canary"][label] = t
        print("  （比較: 素の計画探索 5/40・貪欲 28/40・H 28/40 — D-046）")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
