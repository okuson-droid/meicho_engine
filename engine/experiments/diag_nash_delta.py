"""A-9 の診断: `nash_delta` の窓が実際にどれだけ広いかを数える。

δ = 0.06 が「均衡からわずかに譲る」なのか「実質的に絞り込んでいない」のかを見る。
自己対戦を進めながら対抗の局面を集め、各局面で

  - 合法手のうち **均衡値が最大から δ 以内**に入る手の割合（窓の広さ）
  - δ 規則が選ぶ手が **純均衡の最良手**と違う割合（＝搾取が発動した割合）
  - δ 規則が選ぶ手が **等重み相手での最良手**と一致する割合（＝実質 opp_mix=1.0 になっている割合）

を数える。帯は seed_bands.json に登録済みのものを使う（D-028）。

使い方: python3 experiments/diag_nash_delta.py [局数] [seed0] [delta ...]
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                                    # noqa: E402
from meicho.drlnet import resolve_model                                       # noqa: E402
from meicho.engine import apply, decision_players, initial_state, legal_actions, outcome  # noqa: E402
from meicho.greedy import nash_col                                            # noqa: E402
from meicho.planner import PlannerAgent                                       # noqa: E402
from meicho.state import Phase                                                # noqa: E402

_DECK = load_deck("SD001")
CFG, POOL = mirror_config(_DECK), _DECK["action_deck"]
A15 = {"choice_phases": True, "solo_samples": 4,
       "policy_net": "drl_sd001_vb3.json", "policy_scope": "proxy"}
CHAMP = {"extra_turns": 1, "value_net": "drl_sd001_vb3.json",
         "opp_policy_net": "drl_sd001_s1.json", "opp_policy_root_only": True}


def _kw() -> dict:
    kw = {**CHAMP, **A15}
    for k in ("opp_policy_net", "value_net", "policy_net"):
        kw[k] = resolve_model(kw[k])
    return kw


def probe(agent, s, pi, deltas):
    """1 つの対抗局面で、行列・均衡値・等重み値を 1 回だけ作って全 δ を評価する。"""
    acts = legal_actions(s, pi)
    if len(acts) <= 1:
        return None
    goal = agent._goal_turn(s, pi) if agent.align_leaves else None
    nash = [0.0] * len(acts)
    unif = [0.0] * len(acts)
    for _ in range(agent.samples):
        t = agent._determinize(s, pi)
        crn = agent._save_crn()
        cols = legal_actions(t, 1 - pi) or [agent._opp_act(t, 1 - pi, True)]
        m = [[0.0] * len(cols) for _ in acts]
        for j, b in enumerate(cols):
            for i, a in enumerate(acts):
                agent._restore_crn(crn)
                m[i][j] = agent._score_clash(t, pi, a, b, goal)
        pc = nash_col(m)
        k = len(cols)
        for i in range(len(acts)):
            nash[i] += sum(m[i][j] * pc[j] for j in range(k))
            unif[i] += sum(m[i][j] for j in range(k)) / k
    n = agent.samples
    nash = [v / n for v in nash]
    unif = [v / n for v in unif]
    eq = max(range(len(acts)), key=lambda i: nash[i])
    ub = max(range(len(acts)), key=lambda i: unif[i])
    spread = max(nash) - min(nash)
    out = {"k": len(acts), "spread": spread, "eq": eq, "ub": ub, "per": {}}
    for d in deltas:
        thr = max(nash) - d - 1e-12
        cand = [i for i in range(len(acts)) if nash[i] >= thr]
        pick = max(cand, key=lambda i: unif[i])
        out["per"][d] = (len(cand) / len(acts), pick != eq, pick == ub)
    return out


def main(games: int, seed0: int, deltas: list) -> None:
    kw = _kw()
    rows = []
    for g in range(games):
        seed = seed0 + g
        a = PlannerAgent(seed, opp_decklist=POOL, **kw)
        b = PlannerAgent(seed + 10_000, opp_decklist=POOL, **kw)
        s = initial_state(CFG, seed)
        for _ in range(400):
            if outcome(s) is not None:
                break
            need = decision_players(s)
            if not need:
                break
            if s.phase == Phase.CLASH_SUBMIT:
                for q in sorted(need):
                    r = probe(a if q == 0 else b, s, q, deltas)
                    if r is not None:
                        rows.append(r)
            s = apply(s, {q: (a if q == 0 else b).act(s, q) for q in sorted(need)})
        print(f"  {g + 1}/{games} 局（対抗の局面 {len(rows)}）", flush=True)
    if not rows:
        print("対抗の局面が取れなかった")
        return
    n = len(rows)
    print(f"\n対抗の局面 {n} 個・合法手の平均 {sum(r['k'] for r in rows) / n:.1f} 手")
    print(f"均衡値の幅（最大 − 最小）の平均 {sum(r['spread'] for r in rows) / n:.3f}"
          f"／中央 {sorted(r['spread'] for r in rows)[n // 2]:.3f}")
    print(f"純均衡の最良手と等重みの最良手が一致する割合 "
          f"{sum(1 for r in rows if r['eq'] == r['ub']) / n:.3f}")
    print("\n δ      窓に入る手の割合   均衡と違う手を選んだ割合   等重みの最良手と一致した割合")
    for d in deltas:
        w = sum(r["per"][d][0] for r in rows) / n
        ch = sum(1 for r in rows if r["per"][d][1]) / n
        equb = sum(1 for r in rows if r["per"][d][2]) / n
        print(f" {d:<6} {w:>14.3f} {ch:>24.3f} {equb:>28.3f}")


if __name__ == "__main__":
    g = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    s0 = int(sys.argv[2]) if len(sys.argv) > 2 else 471500
    ds = [float(x) for x in sys.argv[3:]] or [0.005, 0.01, 0.02, 0.03, 0.06, 0.10]
    main(g, s0, ds)
