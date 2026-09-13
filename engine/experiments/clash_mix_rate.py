"""対抗の「混合率」と利得幅を測る（文献計画 便 D・M2）。

## この道具の読み方（専門知識は要らない）

**行列ゲーム**とは、じゃんけんのように「自分の手」と「相手の手」を同時に選び、
その組み合わせで得点が決まる勝負のことである。行が自分の手・列が相手の手の表
（＝行列）を作れば、その 1 マスが「自分が a・相手が b を出したときの自分の得点」である。

**混合戦略**とは「毎回どれか 1 つに決める」のではなく「グーを 1/3・チョキを 1/3…」
のように確率で混ぜて出すことである。じゃんけんは混ぜないと必ず読まれて負けるので、
**混合が必要な勝負**である。一方、将棋の 1 手のように「相手が何をしようとこれが最善」
という手があるなら、混ぜる必要は無い（**純戦略**でよい）。

**知りたいこと**: このゲームの対抗（お互いにカードを伏せて出す場面）は、
じゃんけん型（混ぜないと損）なのか、それとも純戦略で足りるのか。

- **混ぜないと損な局面が多い** → 便 A で「行列ゲームをきちんと解くソルバ（A-2）」を作る値打ちがある
- **ほとんど純戦略で足りる** → ソルバは作らない。労力を別のところに使う

計画書 §2 の分岐条件は「**混合率 5% 未満なら A-2 は作らない**」である。

## どうやって測るか

1. 現 champion 同士で自己対戦を回し、対抗の局面（合法手が 2 つ以上あるもの）を集める
2. 各局面で、champion と同じ決定化（相手の伏せ札の仮置き）を 6 本引く
3. 決定化 1 本ごとに「自分の合法手 × 相手の合法手」の得点表を作る
4. その表を **RM+（regret matching plus）** という反復法で解き、両者の均衡戦略を出す
5. 均衡戦略の中に「重みが 0.05 を超える手」が 2 つ以上あれば、その表は**混合**と数える

**RM+ の注意**: 反復法なので、最後の 1 回の戦略は角（純戦略）を行ったり来たりする。
均衡になるのは**全反復の平均**のほうである。ここを取り違えると混合率がまるごと嘘になるので、
検査 T-L5 で「平均を返していること」を固定してある。

**可搾取度**とは「相手に最善で反撃されたとき、均衡値からどれだけ損をするか」である。
0 に近いほど、出した戦略が均衡に近い。ここでは収束の判定に使う。

## 使い方

    python3 experiments/clash_mix_rate.py --n-positions 1000 --budget-sec 480
    （同じコマンドをもう一度打つと続きから回る）
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import champion as chmod                                                   # noqa: E402
from arena import load_deck, mirror_config                                 # noqa: E402
from human_games_ci import wilson                                          # noqa: E402
from meicho.drlnet import resolve_model                                    # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,         # noqa: E402
                           legal_actions, outcome)
from meicho.planner import PlannerAgent                                    # noqa: E402
from meicho.state import Phase                                             # noqa: E402

BAND = (650200, 650399)          # §5 の採取用の帯（診断。評価にも学習にも使わない）
SUPPORT_W = 0.05                 # 「台に入っている」とみなす重みのしきい値
TOL = 0.01                       # 可搾取度がこれを超えたら反復を延ばす
ITERS = 400
RETRY_ITERS = 1000


def resolved_kwargs(deck: str = "SD001") -> dict:
    kw = dict(chmod.kwargs_for(deck))
    for k in ("value_net", "opp_policy_net", "policy_net"):
        if k in kw:
            kw[k] = resolve_model(kw[k])
    return kw


# ------------------------------------------------------------ 行列ゲームを解く
def _rm_strategy(regret: list) -> list:
    """累積後悔（0 以上）を戦略に直す。全部 0 なら等重み。"""
    tot = sum(regret)
    n = len(regret)
    return [v / tot for v in regret] if tot > 0 else [1.0 / n] * n


def solve_rmplus(matrix, iters: int = ITERS, keep_last: bool = False) -> dict:
    """行列ゲームを RM+ で解き、**両者の平均戦略**と均衡値・可搾取度を返す。

    行 = 自分（最大化）・列 = 相手（最小化）。「後悔」とは「あの手を毎回出して
    いれば、いまより何点得していたか」であり、後悔の大きい手ほど次から多く出す
    ——それが regret matching である。**負の後悔を 0 に切り上げて持ち越さない**
    のが「plus」で、素の regret matching よりずっと速く収束する。

    ここでは 2 つの標準的な加速を入れている。どちらも解を変えるものではなく、
    **同じ均衡に速く着く**ための工夫である。

    - **交互更新**: 行を更新してから、その新しい行に対して列を更新する
      （同時に更新するより速い）
    - **線形平均**: 平均を取るとき、後の反復ほど重く数える（後のほうが均衡に近い）

    返り値:
      x, y            … 行側・列側の**平均戦略**（これが均衡の近似）
      value           … 平均戦略どうしの得点 xᵀ M y
      exploitability  … max_i (M y)_i − min_j (xᵀ M)_j。**相手に最善で反撃された
                        ときの損の大きさ**で、0 に近いほど均衡に近い
      last_x, last_y  … **最終反復の次に出す戦略**（`keep_last=True` のときだけ）。
                        これは均衡ではない——角に寄る。検査 T-L5 が取り違えを見る
    """
    m = [list(map(float, row)) for row in matrix]
    nr, nc = len(m), len(m[0])
    rr = [0.0] * nr              # 行側の累積後悔（plus なので常に 0 以上）
    rc = [0.0] * nc
    sx = [0.0] * nr              # 平均戦略のための重みつき累積
    sy = [0.0] * nc
    sw = 0.0
    pc = [1.0 / nc] * nc
    for t in range(1, max(1, iters) + 1):
        pr = _rm_strategy(rr)
        # 交互更新: いまの行に対して列が後悔を貯める
        uc = [sum(pr[i] * m[i][j] for i in range(nr)) for j in range(nc)]
        vc = sum(pc[j] * uc[j] for j in range(nc))
        rc = [max(0.0, rc[j] + (vc - uc[j])) for j in range(nc)]
        pc = _rm_strategy(rc)
        ur = [sum(m[i][j] * pc[j] for j in range(nc)) for i in range(nr)]
        vr = sum(pr[i] * ur[i] for i in range(nr))
        rr = [max(0.0, rr[i] + (ur[i] - vr)) for i in range(nr)]
        sw += t                                   # 線形平均（後の反復ほど重い）
        for i in range(nr):
            sx[i] += t * pr[i]
        for j in range(nc):
            sy[j] += t * pc[j]
    tx, ty = sw or 1.0, sw or 1.0
    x = [v / tx for v in sx]
    y = [v / ty for v in sy]
    my = [sum(m[i][j] * y[j] for j in range(nc)) for i in range(nr)]
    xm = [sum(x[i] * m[i][j] for i in range(nr)) for j in range(nc)]
    value = sum(x[i] * my[i] for i in range(nr))
    out = {"x": x, "y": y, "value": value,
           "exploitability": max(my) - min(xm),
           "support_row": sum(1 for v in x if v > SUPPORT_W),
           "support_col": sum(1 for v in y if v > SUPPORT_W)}
    if keep_last:
        # 「最終反復の次に出す戦略」。均衡ではない（角に寄る）ので、
        # これを返してしまう取り違えを T-L5 が見る。
        out["last_x"], out["last_y"] = _rm_strategy(rr), _rm_strategy(rc)
    return out


def summarise_matrix(matrix, argmax_row: int | None = None, iters: int = ITERS,
                     tol: float = TOL, retry_iters: int = RETRY_ITERS) -> dict:
    """1 つの得点表について、混合かどうか・利得幅・現行の選択との一致を数える。

    `argmax_row` は**現行の champion がこの決定化で選んだ手の添字**である
    （相手モデル = π₀ の最尤 1 手に対する最良手）。均衡の最良手と一致するかを見る。
    """
    sol = solve_rmplus(matrix, iters)
    converged = sol["exploitability"] <= tol
    if not converged:
        sol = solve_rmplus(matrix, retry_iters)
        converged = sol["exploitability"] <= tol
    flat = [v for row in matrix for v in row]
    # 混合で得している量 = 均衡値 − 最良の純戦略の保証値（max_i min_j m_ij）
    pure_floor = max(min(row) for row in matrix)
    eq_row = max(range(len(sol["x"])), key=lambda i: sol["x"][i])
    return {
        "rows": len(matrix), "cols": len(matrix[0]),
        "mixed_row": sol["support_row"] >= 2,
        "mixed_col": sol["support_col"] >= 2,
        "support_row": sol["support_row"], "support_col": sol["support_col"],
        "spread": max(flat) - min(flat),
        "value": sol["value"],
        "gain_over_pure": sol["value"] - pure_floor,
        "exploitability": sol["exploitability"],
        "converged": bool(converged),
        "eq_best_row": eq_row,
        "agrees_with_argmax": None if argmax_row is None else (eq_row == argmax_row),
    }


# ------------------------------------------------------------ 局面を採る
def clash_matrices(agent, s, pi: int):
    """1 つの対抗局面について、決定化 1 本ごとの (得点表, 現行の選択) を返す。

    組み立ては `diag_nash_delta.probe` と同じ（CRN を毎回復元してから採点する）。
    違うのは kwargs が**現 champion** であることと、**表をそのまま返す**ことである。
    """
    acts = legal_actions(s, pi)
    if len(acts) <= 1:
        return []
    goal = agent._goal_turn(s, pi) if agent.align_leaves else None
    out = []
    for _ in range(agent.samples):
        t = agent._determinize(s, pi)
        crn = agent._save_crn()
        opp_act = agent._opp_act(t, 1 - pi, True)
        cols = legal_actions(t, 1 - pi) or [opp_act]
        m = [[0.0] * len(cols) for _ in acts]
        for j, b in enumerate(cols):
            for i, a in enumerate(acts):
                agent._restore_crn(crn)
                m[i][j] = agent._score_clash(t, pi, a, b, goal)
        # 現行の選び方（相手モデル = π₀ の最尤 1 手）が、この決定化で選ぶ手
        k = cols.index(opp_act) if opp_act in cols else None
        argmax_row = (max(range(len(acts)), key=lambda i: m[i][k])
                      if k is not None else None)
        out.append((m, argmax_row))
    return out


def collect_positions(kw: dict, pool: list, config, seed0: int, seed_last: int,
                      want: int, on_row, budget: float, done_seeds: set,
                      verbose: bool = True) -> int:
    """champion 同士の自己対戦を回し、対抗の局面を `want` 件になるまで集める。

    局面は `(seed, ply)` で再現できるように記録し、**状態そのものは保持しない**
    （盤面を持ち回ると再現の真実源が 2 つになる）。1 局ごとに `on_row` を呼ぶ。
    """
    t0 = time.time()
    got = 0
    for seed in range(seed0, seed_last + 1):
        if got >= want or time.time() - t0 > budget:
            break
        if seed in done_seeds:
            continue
        a = PlannerAgent(seed * 2, opp_decklist=pool, **kw)
        b = PlannerAgent(seed * 2 + 1, opp_decklist=pool, **kw)
        s = initial_state(config, seed)
        ply = 0
        rows = []
        for _ in range(2000):
            if outcome(s) is not None:
                break
            need = decision_players(s)
            if not need:
                break
            if s.phase == Phase.CLASH_SUBMIT:
                for q in sorted(need):        # **両席から**採る
                    agent = a if q == 0 else b
                    for t_i, (m, am) in enumerate(clash_matrices(agent, s, q)):
                        r = summarise_matrix(m, am)
                        r.update({"seed": seed, "ply": ply, "seat": q, "det": t_i})
                        rows.append(r)
            s = apply(s, {q: (a if q == 0 else b).act(s, q) for q in sorted(need)})
            ply += 1
        on_row(seed, rows)
        got += len(rows)
        if verbose:
            print(f"  seed {seed}: 決定化 {len(rows)} 件（通算 {got}）", flush=True)
    return got


# ------------------------------------------------------------ 集計と表示
def aggregate(rows: list) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}

    def _rate(pred):
        k = sum(1 for r in rows if pred(r))
        lo, hi = wilson(k, n)
        return {"k": k, "p": k / n, "ci95": [lo, hi]}

    spreads = sorted(r["spread"] for r in rows)
    gains = sorted(r["gain_over_pure"] for r in rows)
    agree = [r for r in rows if r["agrees_with_argmax"] is not None]
    by_pos: dict = {}
    for r in rows:
        by_pos.setdefault((r["seed"], r["ply"], r["seat"]), []).append(r)
    all_pure = sum(1 for v in by_pos.values() if all(not x["mixed_row"] for x in v))
    return {
        "n": n,
        "n_positions": len(by_pos),
        "mix_rate_ai": _rate(lambda r: r["mixed_row"]),
        "mix_rate_opp": _rate(lambda r: r["mixed_col"]),
        "not_converged": _rate(lambda r: not r["converged"]),
        "spread_mean": sum(spreads) / n, "spread_median": spreads[n // 2],
        "gain_mean": sum(gains) / n, "gain_median": gains[n // 2],
        "agree_with_argmax": (
            {"k": sum(1 for r in agree if r["agrees_with_argmax"]),
             "n": len(agree),
             "p": (sum(1 for r in agree if r["agrees_with_argmax"]) / len(agree))
                  if agree else None}),
        "positions_all_pure": {"k": all_pure, "n": len(by_pos),
                               "p": all_pure / len(by_pos) if by_pos else None},
        # **「均衡が混合」と「混ぜないと損」は別物である。**
        # 手の点数が並んでいるだけ（どれを出しても同じ）なら、均衡は混合になるが
        # 混ぜる値打ちは無い。混合で得している量にしきい値を置いて数え直す。
        "mix_rate_by_gain": {str(thr): _rate(lambda r, t=thr: r["mixed_row"]
                                             and r["gain_over_pure"] > t)
                             for thr in (0.0, 0.005, 0.01, 0.02, 0.05)},
    }


def render(agg: dict) -> str:
    if not agg.get("n"):
        return "対抗の決定化が 1 件も取れなかった"
    a, o = agg["mix_rate_ai"], agg["mix_rate_opp"]
    L = ["■ M2 対抗の混合率と利得幅",
         "",
         f"  決定化 {agg['n']} 件（対抗の局面 {agg['n_positions']} 個・決定化 6 本ずつ）",
         "",
         "  「混合」= 均衡戦略の中に重み 0.05 を超える手が 2 つ以上ある表のこと。",
         "  混ぜないと損な局面が多いほど、行列ゲームを解くソルバ（A-2）の値打ちが上がる。",
         "",
         f"  AI 側の混合率　 : {a['p']:.3f}  95% 区間 [{a['ci95'][0]:.3f}, {a['ci95'][1]:.3f}]"
         f"（{a['k']}/{agg['n']}）",
         f"  相手側の混合率  : {o['p']:.3f}  95% 区間 [{o['ci95'][0]:.3f}, {o['ci95'][1]:.3f}]"
         f"（{o['k']}/{agg['n']}）",
         f"  6 本すべて純戦略だった局面: {agg['positions_all_pure']['p']:.3f}"
         f"（{agg['positions_all_pure']['k']}/{agg['positions_all_pure']['n']}）",
         "",
         f"  利得幅（表の最大 − 最小）: 平均 {agg['spread_mean']:.3f}／中央 {agg['spread_median']:.3f}",
         f"  混合で得している量（均衡値 − 最良の純戦略の保証値）: "
         f"平均 {agg['gain_mean']:.3f}／中央 {agg['gain_median']:.3f}",
         ""]
    if agg.get("mix_rate_by_gain"):
        L += ["  ただし「均衡が混合」と「混ぜないと損」は別物である。手の点数が並んでいる",
              "  だけなら均衡は混合になるが、混ぜる値打ちは無い。混合で得している量に",
              "  しきい値を置いて数え直すと:",
              ""]
        for thr, r in agg["mix_rate_by_gain"].items():
            L.append(f"    得している量 > {float(thr):.3f} の混合だけ数える: "
                     f"{r['p']:.3f}  95% 区間 [{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}]"
                     f"（{r['k']}/{agg['n']}）")
        L.append("")
    ag = agg["agree_with_argmax"]
    if ag["n"]:
        L.append(f"  均衡の最良手と現行（argmax-π₀）の選択が一致した割合: "
                 f"{ag['p']:.3f}（{ag['k']}/{ag['n']}）")
    nc = agg["not_converged"]
    L.append(f"  未収束（可搾取度 > {TOL} のまま）: {nc['p']:.3f}（{nc['k']}/{agg['n']}）")
    L.append("")
    if a["ci95"][1] < 0.05:
        verdict = ("**A-2（束ねたソルバ）は作らない**。AI 側の混合率の上端が 5% を下回る"
                   "＝混ぜないと損な局面はほとんど無い")
    elif a["ci95"][0] >= 0.05:
        verdict = ("**A-2 を作る**。AI 側の混合率の下端が 5% 以上"
                   "＝混ぜないと損な局面が確かにある")
    else:
        verdict = (f"**まだ読めない**。AI 側の混合率の区間 "
                   f"[{a['ci95'][0]:.3f}, {a['ci95'][1]:.3f}] が 5% をまたいでいる"
                   "。局面を増やすか、裁定を仰ぐ")
    L.append("分岐の結論: " + verdict)
    return "\n".join(L)


# ------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n-positions", type=int, default=1000,
                    help="集める決定化の件数（1 局面あたり 6 本）")
    ap.add_argument("--seed0", type=int, default=BAND[0])
    ap.add_argument("--seed-last", type=int, default=BAND[1])
    ap.add_argument("--budget-sec", type=float, default=480.0,
                    help="この秒数を越えたら局の切れ目で止まる。同じコマンドで再開")
    ap.add_argument("--out", default=os.path.join(_HERE, "..", "results", "lit",
                                                  "m2_clash_mix_rate.json"))
    ap.add_argument("--rows", default=None,
                    help="1 行 1 決定化の JSONL（既定は --out の .jsonl）")
    ap.add_argument("--report", action="store_true", help="回さずに集計だけ出す")
    args = ap.parse_args(argv)

    deck = load_deck(args.deck)
    config, pool = mirror_config(deck), deck["action_deck"]
    kw = resolved_kwargs(args.deck)
    rows_path = args.rows or (os.path.splitext(args.out)[0] + ".jsonl")
    os.makedirs(os.path.dirname(os.path.abspath(rows_path)), exist_ok=True)

    rows: list = []
    done_seeds: set = set()
    if os.path.exists(rows_path):
        with open(rows_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    rows.append(r)
                    done_seeds.add(r["seed"])
        print(f"  ※ 途中から再開（{len(rows)} 件・{len(done_seeds)} 局ぶん）", flush=True)

    if not args.report and len(rows) < args.n_positions:
        fh = open(rows_path, "a", encoding="utf-8")

        def on_row(seed, new_rows):
            for r in new_rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                rows.append(r)
            fh.flush()

        collect_positions(kw, pool, config, args.seed0, args.seed_last,
                          args.n_positions - len(rows), on_row,
                          args.budget_sec, done_seeds)
        fh.close()

    agg = aggregate(rows[:args.n_positions])
    print()
    print(render(agg))
    import provenance
    out = {"agg": agg, "n_wanted": args.n_positions,
           "seed0": args.seed0, "seed_last": args.seed_last,
           "rows_file": os.path.basename(rows_path),
           "provenance": provenance.block(kw, "python", (args.seed0, args.seed_last),
                                          extra={"tool": "clash_mix_rate", "M": "M2"})}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {args.out}")
    done = len(rows) >= args.n_positions
    print("（完了）" if done else "（途中。同じコマンドで続きから回る）")
    return 0 if done or args.report else 3


if __name__ == "__main__":
    sys.exit(main())
