"""試作（`meicho/` は触らない）: 対抗の決定を「相手の合法手の表」で評価する PlannerAgent。

champion の `_clash` は決定化（相手の手札の仮置き）ごとに相手の提出を **π₀ の最尤 1 手**に決める。
本試作は `PlannerAgent` を継承して `_clash` だけ差し替え、相手の提出の扱い（opp_mode）を変えて比べる:

    argmax  : 現行（決定化ごとに π₀ の最尤 1 手）
    soft    : 決定化ごとに相手の合法手を π₀ の softmax(opp_tau) で重みづけ
    uniform : 決定化ごとに相手の合法手を等重み
    mix     : 0.5·argmax ＋ 0.5·等重み
    minimax : 決定化ごとに相手の合法手の最悪値
    nash    : 決定化ごとに AI×相手の行列ゲームを regret matching（400 反復）で解き、相手の均衡戦略に対する期待値
    regret    : 決定化ごとに**最大後悔**（「あとから見て、いちばん損をした量」）を計算し、それが最小の手を選ぶ
                （第 2 集 §4.8・Savage のミニマックス後悔）。相手の確率を仮定しないのが利点である
    softfloor : 相手の分布に**下駄**を履かせる。`(1−ε)·softmax(π₀/τ) ＋ ε·一様`。
                ε=0 なら soft τ=1 そのもの、ε=1 なら uniform そのもの。**その間を連続で動かせる**

`regret` と `softfloor` は文献計画 便 D（A-下見）で足したもので、対局はしていない
（回帰 2 局面での選択だけを見る）。**champion の定義ではない。**

読み方と結果は `HUMAN_GAMES_20260903_NOTES.md` §6。**champion の定義ではない**（採用は D-065 A-8 の測定で決める）。

使い方:
    python3 experiments/proto_matrix_clash.py pos                    # 対人 2 局の決定的な対抗で各 mode の選択を出す
    python3 experiments/proto_matrix_clash.py uniform 400 604000     # mode vs champion（Python 同士・ミラー）
帯は seed_bands.json に登録してから使う（D-028）。
"""
from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import numpy as np                                                                # noqa: E402

from arena import load_deck, mirror_config, series                                # noqa: E402
from meicho.drlnet import resolve_model                                           # noqa: E402
from meicho.encode import action_code, encode                                     # noqa: E402
from meicho.engine import apply, legal_actions, observe                           # noqa: E402
from meicho.greedy import load_net                                                # noqa: E402
from meicho.planner import PlannerAgent                                           # noqa: E402
from verify_lethal_human import act_name, last_clash_state                        # noqa: E402
import champion as chmod                                                          # noqa: E402

_DECK = load_deck("SD001")
CFG, POOL = mirror_config(_DECK), _DECK["action_deck"]


def resolved_kwargs() -> dict:
    kw = dict(chmod.kwargs_for("SD001"))
    for k in ("value_net", "opp_policy_net", "policy_net"):
        if k in kw:
            kw[k] = resolve_model(kw[k])
    return kw


def max_regret(m) -> list:
    """行ごとの**最大後悔**を返す（行 = 自分・列 = 相手）。

    後悔とは「相手がその手を出すと分かっていたら取れたはずの点数」と
    「実際に自分の手が取る点数」の差である。列 j の最良は `max_i m[i][j]` なので、
    行 i の後悔は `max_j (colbest_j − m[i][j])`。これが**小さい**手は
    「どの相手の手が来ても、後から悔やむ量が小さい」手である。

    確率の仮定を置かないのが利点で、相手モデル π₀ が偏っていても効かない
    （2026-09-03 の負けは π₀ が安い赤・緑にほぼ 0 を与えたことが原因だった）。
    """
    M = np.asarray(m, np.float64)
    colbest = M.max(axis=0)
    return [float(v) for v in (colbest[None, :] - M).max(axis=1)]


def softfloor_weights(scores, eps: float, tau: float = 1.0) -> list:
    """相手の分布に下駄を履かせる: `(1−ε)·softmax(scores/τ) ＋ ε·一様`。

    ε=0 なら soft τ=1 そのもの、ε=1 なら uniform そのもの。**その間が連続**なので、
    「uniform は回帰局面を直すが錨が悪化する」（A-8）の中間点を探せる。
    """
    sc = np.asarray(scores, np.float64)
    p = np.exp((sc - sc.max()) / tau)
    p /= p.sum()
    n = len(sc)
    return [float((1.0 - eps) * p[i] + eps / n) for i in range(n)]


class MatrixPlanner(PlannerAgent):
    def __init__(self, seed, opp_mode="argmax", opp_tau=1.0, min_w=0.02,
                 eps=0.3, **kw):
        super().__init__(seed, **kw)
        self.opp_mode, self.opp_tau, self.min_w = opp_mode, opp_tau, min_w
        self.eps = eps                 # softfloor の下駄の大きさ
        self.last_totals = None

    def _opp_dist(self, t, q):
        """仮置き t での相手 q の提出の分布 [(手, 重み)]。"""
        acts = legal_actions(t, q)
        if len(acts) == 1 or self.opp_mode == "argmax":
            return [(self._opp_act(t, q, True), 1.0)]
        if self.opp_mode == "uniform":
            return [(a, 1.0 / len(acts)) for a in acts]
        if self.opp_mode in ("minimax", "nash", "regret"):
            return [(a, None) for a in acts]
        ob = observe(t, q)
        net = load_net(self.opp_policy_net)
        x = np.asarray(encode(ob, q), np.float32)
        sc = np.asarray(net.policy_scores(x, [action_code(ob, a) for a in acts]), np.float64)
        p = np.exp((sc - sc.max()) / self.opp_tau)
        p /= p.sum()
        if self.opp_mode == "mix":
            p = np.full(len(acts), 0.5 / len(acts))
            p[int(np.argmax(sc))] += 0.5
        if self.opp_mode == "softfloor":
            # **下駄を履かせた分布は間引かない。** 間引くと ε で足した重みが消え、
            # 「安い赤・緑の列が評価から落ちる」という直したい病気がそのまま残る。
            return [(a, w) for a, w in zip(acts, softfloor_weights(sc, self.eps, self.opp_tau))]
        return [(a, float(w)) for a, w in zip(acts, p) if w >= self.min_w]

    @staticmethod
    def _nash_col(M, iters: int = 400):
        """行列ゲーム（行=AI が最大化・列=相手が最小化）の regret matching。列側の平均戦略を返す。"""
        M = np.asarray(M, np.float64)
        m, k = M.shape
        rr, rc, sc = np.zeros(m), np.zeros(k), np.zeros(k)
        for _ in range(iters):
            pr = np.maximum(rr, 0)
            pr = pr / pr.sum() if pr.sum() > 0 else np.full(m, 1.0 / m)
            pc = np.maximum(rc, 0)
            pc = pc / pc.sum() if pc.sum() > 0 else np.full(k, 1.0 / k)
            u_r, u_c = M @ pc, pr @ M
            v = pr @ u_r
            rr += u_r - v
            rc += v - u_c
            sc += pc
        return sc / iters

    def _clash(self, s, pi, acts):
        totals = [0.0] * len(acts)
        for _ in range(self.samples):
            t = self._determinize(s, pi)
            dist = self._opp_dist(t, 1 - pi)
            if self.opp_mode == "nash":
                cols = [b for b, _ in dist]
                M = [[self._eval(self._settle(apply(t, {pi: a, 1 - pi: b}), pi), pi) for b in cols] for a in acts]
                pc = self._nash_col(M)
                for i in range(len(acts)):
                    totals[i] += float(np.dot(M[i], pc))
            elif self.opp_mode == "regret":
                cols = [b for b, _ in dist]
                M = [[self._eval(self._settle(apply(t, {pi: a, 1 - pi: b}), pi), pi) for b in cols] for a in acts]
                # 最大後悔が**小さい**ほど良いので、符号を反転して足す
                # （`totals` は「大きいほど良い」で揃えてある）
                for i, r in enumerate(max_regret(M)):
                    totals[i] -= r
            elif self.opp_mode == "minimax":
                for i, a in enumerate(acts):
                    totals[i] += min(self._eval(self._settle(apply(t, {pi: a, 1 - pi: b}), pi), pi) for b, _ in dist)
            else:
                wsum = sum(w for _, w in dist)
                for b, w in dist:
                    for i, a in enumerate(acts):
                        totals[i] += (w / wsum) * self._eval(self._settle(apply(t, {pi: a, 1 - pi: b}), pi), pi)
        self.last_totals = [x / self.samples for x in totals]
        best = max(range(len(acts)), key=lambda i: totals[i])
        return acts[best]


def make_champ(seed):
    return PlannerAgent(seed, opp_decklist=POOL, **resolved_kwargs())


def _make(mode, tau, eps=0.3):
    def f(seed):
        return MatrixPlanner(seed, opp_mode=mode, opp_tau=tau, eps=eps,
                             opp_decklist=POOL, **resolved_kwargs())
    return f


# ProcessPoolExecutor に渡すためモジュール直下の関数にする
def make_soft(seed): return _make("soft", 1.0)(seed)          # noqa: E704
def make_soft2(seed): return _make("soft", 2.0)(seed)         # noqa: E704
def make_uniform(seed): return _make("uniform", 1.0)(seed)    # noqa: E704
def make_minimax(seed): return _make("minimax", 1.0)(seed)    # noqa: E704
def make_mix(seed): return _make("mix", 1.0)(seed)            # noqa: E704
def make_nash(seed): return _make("nash", 1.0)(seed)          # noqa: E704
def make_regret(seed): return _make("regret", 1.0)(seed)     # noqa: E704
def make_softfloor3(seed): return _make("softfloor", 1.0, 0.3)(seed)  # noqa: E704
def make_softfloor6(seed): return _make("softfloor", 1.0, 0.6)(seed)  # noqa: E704


MAKERS = {"soft": make_soft, "soft2": make_soft2, "uniform": make_uniform,
          "minimax": make_minimax, "mix": make_mix, "nash": make_nash,
          "regret": make_regret, "softfloor3": make_softfloor3,
          "softfloor6": make_softfloor6}
# **既存 7 モードの並びを変えない**（表の列がずれると過去の報告と突き合わせられない）。
# 3 つ目の要素は softfloor の ε。他のモードでは使わない。
MODES = [("argmax", 1.0, None), ("soft", 1.0, None), ("soft", 2.0, None),
         ("uniform", 1.0, None), ("mix", 1.0, None), ("minimax", 1.0, None),
         ("nash", 1.0, None),
         ("regret", 1.0, None), ("softfloor", 1.0, 0.3), ("softfloor", 1.0, 0.6)]


def positions(path: str, opponent: str = "planner_vb3") -> list:
    """回帰 2 局面（対人でマスターが勝った局の最後の対抗）での各モードの選択を出す。"""
    out_rows: list = []
    from webapp import record as wrec
    with open(path, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    base = chmod.kwargs_for("SD001")
    for rec in [r for r in recs if r["opponent"]["name"] == opponent]:
        out = wrec.replay(rec, CFG, keep_states=True)
        hu = rec["human_seat"]
        ai = 1 - hu
        s = last_clash_state(out["states"])
        if s is None:
            continue
        # 真の局面で π₀ が相手（人間）の合法手に与える確率（AI は本当は知らない値）
        acts = legal_actions(s, hu)
        ob = observe(s, hu)
        net = load_net(resolve_model(base["opp_policy_net"]))
        x = np.asarray(encode(ob, hu), np.float32)
        sc = np.asarray(net.policy_scores(x, [action_code(ob, a) for a in acts]), np.float64)
        p = np.exp(sc - sc.max())
        p /= p.sum()
        print(f"== {rec['game_id']} T{s.turn_no}: 真の手札での π₀(softmax τ=1) = "
              + ", ".join(f"{act_name(s, hu, a)} {w:.2f}" for a, w in zip(acts, p)))
        legal = legal_actions(s, ai)
        rows = []
        for mode, tau, eps in MODES:
            ag = MatrixPlanner(rec["opponent"]["seed"], opp_mode=mode, opp_tau=tau,
                               eps=(0.3 if eps is None else eps),
                               opp_decklist=POOL, **resolved_kwargs())
            a = ag.act(s, ai)
            ranked = sorted(zip(ag.last_totals, [act_name(s, ai, b) for b in legal]), reverse=True)
            label = f"{mode}" + ("" if eps is None else f"(ε={eps})")
            print(f"   {label:16s} τ={tau:.0f}: 選ぶ={act_name(s, ai, a):26s} "
                  + "  ".join(f"{n} {v:.3f}" for v, n in ranked))
            rows.append({"game_id": rec["game_id"], "turn": s.turn_no, "mode": mode,
                         "tau": tau, "eps": eps, "chosen": act_name(s, ai, a),
                         "totals": {n: v for v, n in ranked}})
        out_rows.extend(rows)
    return out_rows


def compare_rules(rows_path: str, rules=("argmax", "regret", "uniform"),
                  limit: int = 100) -> dict:
    """M2 で採った局面（`m2_clash_mix_rate.jsonl`）の先頭 `limit` 件で、
    `regret` の選択が現行 `argmax` と**どれだけ違うか**を数える（対局はしない）。

    「回帰 2 局面は直るが、普段の対抗をどれだけ変えるか」の目安である。
    たくさん変えるなら、便 A では錨（第三者との勝率）を丁寧に見る必要がある。

    M2 の JSONL には得点表そのものは残していない（大きすぎる）ので、ここでは
    **M2 と同じ帯・同じ局面を取り直して**比べる。取り直しは決定的なので同じ局面になる。
    """
    import clash_mix_rate as m2
    from meicho.engine import decision_players, initial_state, outcome
    from meicho.state import Phase as _Phase

    kw = resolved_kwargs()
    counts = {r: 0 for r in rules}
    agree = {r: 0 for r in rules}
    n = 0
    seeds = sorted({json.loads(line)["seed"]
                    for line in open(rows_path, encoding="utf-8") if line.strip()})
    for seed in seeds:
        if n >= limit:
            break
        a = PlannerAgent(seed * 2, opp_decklist=POOL, **kw)
        b = PlannerAgent(seed * 2 + 1, opp_decklist=POOL, **kw)
        st = initial_state(CFG, seed)
        for _ in range(2000):
            if n >= limit or outcome(st) is not None:
                break
            need = decision_players(st)
            if not need:
                break
            if st.phase == _Phase.CLASH_SUBMIT:
                for q in sorted(need):
                    if n >= limit or len(legal_actions(st, q)) < 2:
                        continue
                    agent = a if q == 0 else b
                    for m, am in m2.clash_matrices(agent, st, q):
                        if n >= limit:
                            break
                        picks = {}
                        picks["argmax"] = am
                        r = max_regret(m)
                        picks["regret"] = min(range(len(r)), key=lambda i: r[i])
                        u = [sum(row) / len(row) for row in m]
                        picks["uniform"] = max(range(len(u)), key=lambda i: u[i])
                        for rule in rules:
                            counts[rule] += 1
                            if picks[rule] == picks["argmax"]:
                                agree[rule] += 1
                        n += 1
            st = apply(st, {q: (a if q == 0 else b).act(st, q) for q in sorted(need)})
    return {"n": n,
            "agree_with_argmax": {r: (agree[r] / counts[r]) if counts[r] else None
                                  for r in rules},
            "differ_from_argmax": {r: (1 - agree[r] / counts[r]) if counts[r] else None
                                   for r in rules}}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "pos":
        rows = positions(os.path.join(_HERE, "..", "results", "human_games",
                                      "2026-09.jsonl"))
        out = os.path.join(_HERE, "..", "results", "lit", "a_scout_positions.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"\n→ {out}")
        return 0
    if argv[0] == "compare-rules":
        # 使い方: compare-rules [JSONL] [件数]
        rows_path = argv[1] if len(argv) > 1 else os.path.join(
            _HERE, "..", "results", "lit", "m2_clash_mix_rate.jsonl")
        limit = int(argv[2]) if len(argv) > 2 else 100
        res = compare_rules(rows_path, limit=limit)
        print(f"M2 の局面 {res['n']} 件（決定化 1 本 = 1 件）での選択の一致")
        for rule, p in res["agree_with_argmax"].items():
            print(f"  {rule:8s}: argmax と一致 {p:.3f}／違う {1 - p:.3f}")
        out = os.path.join(_HERE, "..", "results", "lit", "a_scout_compare_rules.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f"→ {out}")
        return 0
    mode, n, seed0 = argv[0], int(argv[1]), int(argv[2])
    t0 = time.time()
    r = series(MAKERS[mode], make_champ, n, CFG, workers=2, seed0=seed0)
    print(f"{mode} vs champion(Python) n={n} seed0={seed0}: {r}  下端 {r.p - r.ci:.3f}  "
          f"(seeds {seed0}..{seed0 + n - 1})  {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
