"""選択フェイズで「規則（H）の手」と「探索（V）の手」がどれだけ違うかを数える（D-065 便 2 の下見）。

## なぜ先にこれを回すのか

D-065 の候補 a1 は「選択フェイズ（レベルアップの捨て札・支払うか受けるか・任意効果・
公開枚数・切り替え先・解決順）と手札上限の捨て札も、探索の担当にする」というものである。
**もし探索が規則とまったく同じ手しか選ばないなら、a1 は強さを 1 ミリも動かせない。**
その場合、門番（1,200 局の直接対決）を回すのは時間の無駄である。だから先に
「違う手を選ぶ割合」を数える。数分で終わる。

## 何を測るか

現 champion（`experiments/champion.py` の定義）と H を対局させ、champion 側の
**選択フェイズの決定ごとに** 2 つの手を並べる。

1. **H の手**: いま champion が実際に選んでいる手（選択フェイズは規則に委ねている）
2. **V の手**: `choice_phases=True, solo_samples=N` を足した版が同じ局面で選ぶ手

対局そのものは 1 の手で進む（2 は覗くだけで、盤面には影響しない）。
したがってこの道具は**champion の実際の対局における選択の分布**を見ている。

種類（`kind`）ごとに「違う手を選んだ割合」を出す。**全種類で 0 なら a1 は効きようがない。**

## 使い方

    python3 experiments/diag_choice_agreement.py --n 100 --seed0 470000

帯 470000..470199 は `seed_bands.json` に「診断」として登録済みである（強さは読まない）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                    # noqa: E402
from arena_rs import ensure_cards                             # noqa: E402
from meicho.drlnet import resolve_model                       # noqa: E402
import champion as chmod                                      # noqa: E402

import meicho_rs as rs                                        # noqa: E402


def _resolve(kw: dict) -> dict:
    """モデルの名前を実ファイルのパスに直す（Rust 側はファイル配置を知らない）。"""
    out = dict(kw)
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in out:
            out[key] = resolve_model(out[key])
    return out


def _kind_of(state_json: dict) -> str:
    """決定の種類。選択フェイズは待ち行列の先頭の kind（と理由）で分ける。"""
    if state_json["phase"] == "turn_end_discard":
        return "turn_end_discard"
    ch = state_json.get("pending_choices") or []
    if not ch:
        return "?"
    k = ch[0].get("kind", "?")
    r = ch[0].get("reason")
    return f"{k}/{r}" if r else k


def run(deck_name: str, n: int, seed0: int, solo_samples: int, max_turns: int = 200) -> dict:
    ensure_cards()
    deck = load_deck(deck_name)
    config = mirror_config(deck)
    pool = deck["action_deck"]
    base = _resolve(chmod.kwargs_for(deck_name))
    probe_kw = dict(base, choice_phases=True, solo_samples=solo_samples)

    total = Counter()          # 種類 → 決定数
    differ = Counter()         # 種類 → 違う手を選んだ数
    all_decisions = 0          # champion 側の全決定（合法手 2 つ以上）
    examples: list = []
    t0 = time.time()
    for i in range(n):
        seed = seed0 + i
        flip = seed % 2 == 1                      # `arena` と同じ約束で先攻後攻を入れ替える
        me = 1 if flip else 0                     # champion の席
        ags = [None, None]
        ags[me] = rs.PlannerAgent(seed * 2 + me, opp_decklist=pool, **base)
        ags[1 - me] = rs.HeuristicAgent(seed * 2 + (1 - me))
        probe = rs.PlannerAgent(seed * 2 + me, opp_decklist=pool, **probe_kw)
        s = rs.initial_state(config.chara_decks, config.action_decks, seed)
        for _ in range(20000):
            if rs.outcome(s) is not None:
                break
            need = rs.decision_players(s)
            if not need:
                break
            sj = json.loads(s.to_json())
            if sj["turn_no"] > max_turns:
                break
            acts = {}
            for pi in need:
                a = ags[pi].act(s, pi)
                acts[pi] = a
                if pi != me or len(rs.legal_actions(s, pi)) < 2:
                    continue
                all_decisions += 1
                if sj["phase"] not in ("choice", "turn_end_discard"):
                    continue
                kind = _kind_of(sj)
                b = probe.act(s, pi)
                total[kind] += 1
                if a != b:
                    differ[kind] += 1
                    if len(examples) < 12:
                        examples.append({"seed": seed, "turn": sj["turn_no"], "kind": kind,
                                         "h": a, "v": b})
            s = rs.apply(s, acts)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{n} 局  ({time.time() - t0:.0f}s)", flush=True)

    rows = []
    for kind in sorted(total, key=lambda k: -total[k]):
        rows.append({"kind": kind, "n": total[kind], "differ": differ[kind],
                     "ratio": differ[kind] / total[kind]})
    n_choice = sum(total.values())
    return {"deck": deck_name, "n_games": n, "seed0": seed0, "solo_samples": solo_samples,
            "champion": chmod.kwargs_for(deck_name),
            "decisions_total": all_decisions, "decisions_choice": n_choice,
            "choice_share": (n_choice / all_decisions) if all_decisions else 0.0,
            "differ_total": sum(differ.values()),
            "differ_ratio": (sum(differ.values()) / n_choice) if n_choice else 0.0,
            "rows": rows, "examples": examples, "sec": time.time() - t0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed0", type=int, default=470000)
    ap.add_argument("--solo-samples", type=int, default=4)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    out = run(args.deck, args.n, args.seed0, args.solo_samples)
    print(f"\nchampion 側の決定 {out['decisions_total']} 件のうち、"
          f"選択フェイズ・手札上限は {out['decisions_choice']} 件"
          f"（{out['choice_share'] * 100:.1f}%）")
    print(f"そのうち V が H と違う手を選んだのは {out['differ_total']} 件"
          f"（{out['differ_ratio'] * 100:.1f}%）\n")
    print(f"{'種類':<28}{'決定数':>7}{'違う手':>8}{'割合':>8}")
    for r in out["rows"]:
        print(f"{r['kind']:<28}{r['n']:>7}{r['differ']:>8}{r['ratio'] * 100:>7.1f}%")
    path = args.out or os.path.join(_HERE, "..", "results", "vb", "diag_choice_agreement.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {path}  ({out['sec']:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
