"""透視カウンター — champion の対抗が「読まれたときにどれだけ損をするか」を測る
（文献計画 便 D・M7）。**測定専用。champion 候補にしない。学習の相手にもしない（D-026）。**

## この道具の読み方

**知りたいこと**: いまの AI の対抗（お互いにカードを伏せて出す場面）は、相手に手を
読まれたときどれだけ搾取されるか。

じゃんけんで「いつもグーを出す人」は、読まれた瞬間に全敗する。読まれても大きく崩れない
打ち方を「被搾取が小さい」という。文献（第 2 集 §1.2）では相手に最適反撃させたときの
損失を Ex_d と書く。**この道具はその meicho 版である。**

**測り方**: 相手役として「AI の提出を**先に見てから**自分の手を決める」エージェントを置く。
これが透視カウンターである。champion 対 透視カウンターの勝率が

- 0.5 に近い → 読まれても崩れない（被搾取が小さい）
- 大きく 0.5 を下回る → 読まれると崩れる（被搾取が大きい）

**この数字だけでは良し悪しを決められない。** 透視カウンターは反則をしている相手なので、
負けるのが自然である。使い道は**比較**であって、絶対値ではない——便 A で対抗の作り方を
変えたとき、「錨（第三者との勝率）が悪化していない」に加えて「被搾取が増えていない」を
確かめるための基準値をここで取る。

**なぜ登録簿に載せないか（D-026 覗き見禁止）**: このエージェントは伏せられた情報を
見ている。ラダーやアプリの相手として混ざると、「強い AI」を名乗る反則者が測定に紛れ込む。
検査 T-L6 が「`peek` を含む名前がどの登録簿にも無いこと」を固定している。

## 使い方

    python3 experiments/peek_counter.py --n 600 --budget-sec 480
    （同じコマンドをもう一度打つと続きから回る）
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

import champion as chmod                                                    # noqa: E402
from arena import ci95, load_deck, mirror_config                            # noqa: E402
from meicho.drlnet import resolve_model                                     # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,          # noqa: E402
                           legal_actions, outcome)
from meicho.planner import PlannerAgent                                     # noqa: E402
from meicho.state import DRAW, Phase                                        # noqa: E402

BAND = (651000, 651599)          # §5 の帯（診断。評価にも学習にも使わない）
NAME = "peek_counter"            # **登録簿には載せない**（T-L6 が固定する）


def resolved_kwargs(deck: str = "SD001", cand: str = None) -> dict:
    """現 champion（＋候補の差分）の kwargs。モデル名は実ファイルのパスに直す。

    `cand` は `probe_d065.CANDIDATES` の候補名。省略すると現 champion そのもの。
    **透視カウンター側も同じ設定にする**——測りたいのは「その打ち方が読まれたときの損」で、
    相手役の強さを変えてしまうと候補どうしを同じ物差しで比べられない。
    """
    kw = dict(chmod.kwargs_for(deck))
    if cand:
        from probe_d065 import CANDIDATES
        if cand not in CANDIDATES:
            raise SystemExit(f"未登録の候補: {cand}（{sorted(CANDIDATES)}）")
        kw.update(CANDIDATES[cand])
    for k in ("value_net", "opp_policy_net", "policy_net"):
        if k in kw:
            kw[k] = resolve_model(kw[k])
    return kw


class PeekCounter(PlannerAgent):
    """champion と同じ設定だが、**対抗だけ**相手の提出を見てから決める。

    `peek` が None なら親クラスとまったく同じに振る舞う（透視しない）。
    `peek` に相手の提出が入っているときだけ、**決定化せず真の局面の上で**
    各手を採点し、最良の手を返す——つまり真の最良応答である。

    対抗以外の決定（アクション・連撃・選択）は champion と同じで、**透視しない**。
    測りたいのは「対抗が読まれたときの損」だけなので、それ以外で得をさせると
    数字の意味が混ざる。
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.peek = None
        self.peek_changed = 0        # 透視の結果、親と違う手を選んだ回数
        self.peek_total = 0          # 透視して決めた対抗の回数

    def _clash(self, s, pi, acts):
        if self.peek is None:
            return super()._clash(s, pi, acts)
        goal = self._goal_turn(s, pi) if self.align_leaves else None
        crn = self._save_crn()
        vals = []
        for a in acts:
            self._restore_crn(crn)
            vals.append(self._score_clash(s, pi, a, self.peek, goal))
        best = max(range(len(acts)), key=lambda i: vals[i])
        self.last_clash = {"acts": [str(a.get("type")) for a in acts],
                           "totals": list(vals), "chosen": best}
        self.peek_total += 1
        return acts[best]


def play_game_peek(config, agents: list, seed: int, peek_seat: int | None,
                   max_turns: int = 200) -> dict:
    """`meicho.runner.play_game` と同じだが、対抗だけ透視側に相手の手を渡す。

    **順序が要**: 対抗で両者が決める局面では、先に相手（champion）の手を取り、
    それを透視側の `peek` に入れてから透視側の手を取る。そのうえで
    **行動の辞書を席の昇順に組み直して** `apply` に渡す
    ——辞書の挿入順が違うと乱数の消費順が変わり、同じシードでも別の対局になる
    （`webapp/session.py` §2.3 と同じ理由）。`peek_seat=None` なら透視しない
    ＝`play_game` と 1 手も変わらない（検査 T-L6b がこれを固定する）。
    """
    s = initial_state(config, seed)
    steps = 0
    while outcome(s) is None:
        if s.turn_no > max_turns:
            return {"winner": None, "turns": s.turn_no, "aborted": True,
                    "draw": False, "steps": steps}
        need = decision_players(s)
        if (peek_seat is not None and s.phase == Phase.CLASH_SUBMIT
                and peek_seat in need and len(need) > 1):
            other = [q for q in need if q != peek_seat]
            acts = {q: agents[q].act(s, q) for q in other}      # 先に相手を決める
            ag = agents[peek_seat]
            base_act = None
            if getattr(ag, "peek", None) is None:
                # 透視しなかったときの手も取っておく（「透視で手を変えた割合」を数える）
                base_act = ag.act(s, peek_seat)
            ag.peek = acts[other[0]]
            acts[peek_seat] = ag.act(s, peek_seat)
            ag.peek = None
            if base_act is not None and base_act != acts[peek_seat]:
                ag.peek_changed += 1
        else:
            acts = {q: agents[q].act(s, q) for q in need}
        s = apply(s, {q: acts[q] for q in sorted(acts)})        # **席の昇順**
        steps += 1
    o = outcome(s)
    return {"winner": None if o == DRAW else o, "turns": s.turn_no,
            "aborted": False, "draw": o == DRAW, "steps": steps,
            "life": [s.players[0].life, s.players[1].life]}


# ------------------------------------------------------------ 1 局
def _one(args):
    """1 局。戻り値は (champion が勝ったか | None, 透視が手を変えた回数, 透視した回数)。"""
    deck, kw, seed = args
    d = load_deck(deck)
    config, pool = mirror_config(d), d["action_deck"]
    flip = seed % 2                       # 奇数シードで champion が後攻になる
    champ_seat = 1 if flip else 0
    peek_seat = 1 - champ_seat
    agents = [None, None]
    agents[champ_seat] = PlannerAgent(seed * 2, opp_decklist=pool, **kw)
    agents[peek_seat] = PeekCounter(seed * 2 + 1, opp_decklist=pool, **kw)
    r = play_game_peek(config, agents, seed, peek_seat)
    ag = agents[peek_seat]
    if r["aborted"] or r["draw"]:
        return (None, ag.peek_changed, ag.peek_total)
    return (1 if r["winner"] == champ_seat else 0, ag.peek_changed, ag.peek_total)


def series_peek(deck: str, kw: dict, seeds: list, workers: int = 2) -> list:
    jobs = [(deck, kw, s) for s in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_one, jobs, chunksize=2))
    return [_one(j) for j in jobs]


# ------------------------------------------------------------ 集計と表示
def aggregate(rows: list) -> dict:
    dec = [r["champ_won"] for r in rows if r["champ_won"] is not None]
    n = len(dec)
    wins = sum(dec)
    changed = sum(r["peek_changed"] for r in rows)
    total = sum(r["peek_total"] for r in rows)
    return {"games": len(rows), "n": n, "wins_champion": wins,
            "p": (wins / n) if n else None, "ci": ci95(wins, n) if n else None,
            "peek_clashes": total, "peek_changed": changed,
            "changed_rate": (changed / total) if total else None}


def render(agg: dict) -> str:
    if not agg["n"]:
        return "勝敗の付いた局が 0"
    p, ci = agg["p"], agg["ci"]
    L = ["■ M7 透視カウンター（champion の被搾取のベースライン）",
         "",
         "  透視カウンター = AI の提出を**先に見てから**自分の手を決める相手役。",
         "  反則をしている相手なので、champion が負け越すのが自然である。",
         "  使い道は**比較**であって絶対値ではない——便 A の候補を同じ物差しで並べるための基準値。",
         "",
         f"  champion から見た勝率: {p:.3f} ±{ci:.3f}"
         f"（n={agg['n']}／除外 {agg['games'] - agg['n']}）",
         f"  95% 区間 [{p - ci:.3f}, {p + ci:.3f}]",
         "",
         f"  透視した対抗 {agg['peek_clashes']} 回のうち、透視して**手を変えた**割合: "
         + ("―" if agg["changed_rate"] is None else f"{agg['changed_rate']:.3f}"
            f"（{agg['peek_changed']}/{agg['peek_clashes']}）"),
         "",
         "  読み方: 0.5 に近いほど「読まれても崩れない」。大きく下回るほど被搾取が大きい。",
         "  手を変えた割合が小さいなら、そもそも対抗で読み合いになっていない"
         "（＝どの相手の手にも同じ手が最良）ということである。"]
    return "\n".join(L)


# ------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed0", type=int, default=BAND[0])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--chunk", type=int, default=50, help="1 塊の局数（中断の粒度）")
    ap.add_argument("--budget-sec", type=float, default=480.0,
                    help="この秒数を越えたら塊の切れ目で止まる。同じコマンドで再開")
    ap.add_argument("--out", default=os.path.join(_HERE, "..", "results", "lit",
                                                  "m7_peek_baseline.json"))
    ap.add_argument("--rows", default=None, help="1 行 1 局の JSONL（既定は --out の .jsonl）")
    ap.add_argument("--cand", default=None,
                    help="probe_d065.CANDIDATES の候補名（省略時は現 champion）。"
                         "**同じ --seed0 で候補ごとに走らせて対にする**（便 A §4.4）")
    ap.add_argument("--report", action="store_true", help="回さずに集計だけ出す")
    args = ap.parse_args(argv)

    kw = resolved_kwargs(args.deck, args.cand)
    rows_path = args.rows or (os.path.splitext(args.out)[0] + ".jsonl")
    os.makedirs(os.path.dirname(os.path.abspath(rows_path)), exist_ok=True)

    rows: list = []
    done: set = set()
    if os.path.exists(rows_path):
        with open(rows_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    rows.append(r)
                    done.add(r["seed"])
        print(f"  ※ 途中から再開（{len(rows)}/{args.n} 局）", flush=True)

    todo = [s for s in range(args.seed0, args.seed0 + args.n) if s not in done]
    if todo and not args.report:
        t0 = time.time()
        with open(rows_path, "a", encoding="utf-8") as fh:
            while todo and time.time() - t0 < args.budget_sec:
                block = todo[:args.chunk]
                todo = todo[args.chunk:]
                got = series_peek(args.deck, kw, block, args.workers)
                for seed, (w, ch, tot) in zip(block, got):
                    r = {"seed": seed, "champ_won": w,
                         "peek_changed": ch, "peek_total": tot}
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    rows.append(r)
                fh.flush()
                a = aggregate(rows)
                print(f"  {len(rows)}/{args.n} 局: champion の勝率 "
                      f"{a['p']:.3f} ±{a['ci']:.3f}（途中の数）  "
                      f"{time.time() - t0:.0f}s", flush=True)

    agg = aggregate(rows)
    print()
    print(render(agg))
    import provenance
    out = {"agg": agg, "n_wanted": args.n, "seed0": args.seed0,
           "rows_file": os.path.basename(rows_path),
           "cand": args.cand or "champion",
           "provenance": provenance.block(
               kw, "python", (args.seed0, args.seed0 + args.n - 1),
               extra={"tool": "peek_counter", "M": "M7", "cand": args.cand or "champion",
                      "note": "測定専用。champion 候補にしない・学習の相手にしない（D-026）"})}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {args.out}")
    finished = len(rows) >= args.n
    print("（完了）" if finished else "（途中。同じコマンドで続きから回る）")
    return 0 if finished or args.report else 3


if __name__ == "__main__":
    sys.exit(main())
