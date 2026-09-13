"""カンニング版 planner — 「相手の手札が完全に分かったら最大どれだけ強くなるか」の天井
（文献計画 便 M・M4）。**測定専用。champion 候補にしない。学習の相手にもしない（D-026）。**

## この道具の読み方

**知りたいこと**: いまの AI が負けているぶんのうち、「相手の私的情報（手札）が読めない」
ことで失っている分はどれだけあるか。

いまの探索は、相手の手札を**公開情報から作った未公開プールから配り直して**（決定化して）
読む。もし相手の手札がそのまま見えたら、決定化の当てずっぽうは消える。その差が
**推論を完璧にしたときの天井**である（第 2 集 §3.5.4）。

天井が大きければ「相手の手札の推論を良くする投資」（硬い制約フィルタ・被覆率・重み付け・
終盤の全列挙＝便 C の II-7〜II-9）は報われる。小さければ、そこに手を入れても伸びしろが無い。

**カンニングするのは相手の手札だけである**（§0.3 (i)）。相手の山札の順も自分の山札の順も
**従来どおり混ぜる**——測りたいのは「推論の対象である私的情報」の効果であって、
山札順は誰にも推論できない偶然の隠れ情報だからである（第 2 集 §2.7.5 の区別）。

**マイナスに出ることもある**（カンニング逆説・第 2 集 §3.4）。決定化を 1 通りに固定すると
葉の価値の平均化が消え、V の較正が崩れて弱くなりうる。**どちらに出てもそれが答えである。**

## なぜ登録簿に載せないか（D-026 覗き見禁止）

このエージェントは伏せられた情報を見ている。ラダーやアプリの相手として混ざると、
「強い AI」を名乗る反則者が測定に紛れ込む。名前は `peek_` で始め、`CHAMPIONS`・
`gauntlets/*.json`・`webapp/agents.py`・`registry` のどこにも載せない。
検査 T-L6 / T-M-2 が「`peek` を含む名前がどの登録簿にも無いこと」を固定している。

## 使い方

    # P1 天井（カンニング版 対 champion・n=1,200）
    python3 experiments/peek_planner.py --opponent champion --n 1200 --seed0 672400 \
        --workers 2 --budget-sec 480 --out results/lit/m4_peek_planner.json
    # P0 対照（champion 同士・カンニングを切る）
    python3 experiments/peek_planner.py --peek off --n 300 --seed0 672000 \
        --out results/lit/m4_control_py.json
    # P2 錨（カンニング版 対 H）
    python3 experiments/peek_planner.py --opponent H --n 300 --seed0 675200 \
        --out results/lit/m4_peek_anchor_H.json

同じコマンドをもう一度打つと続きから回る（`--budget-sec` で塊に切る・D-068 の型）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import ci95, load_deck, mirror_config                           # noqa: E402
from meicho.heuristic import HeuristicAgent                                # noqa: E402
from meicho.planner import PlannerAgent                                    # noqa: E402
from meicho.runner import play_game                                        # noqa: E402
from peek_counter import resolved_kwargs                                   # noqa: E402

BAND = (672400, 673599)          # §5 の帯（診断。評価にも学習にも使わない）
NAME = "peek_planner"            # **登録簿には載せない**（T-L6 / T-M-2 が固定する）

# 分岐の閾値（§0.3 (ii)。**回す前に決めてある。結果を見てから動かさない**）
ELO_HI = 50.0                    # +50 Elo ↔ p = 0.5711
ELO_LO = 20.0                    # +20 Elo ↔ p = 0.5288


# ------------------------------------------------------------ Elo と分岐
def elo_from_p(p: float) -> float:
    """勝率 → Elo 差 Δ = 400·log₁₀(p/(1−p))（§0.3 (ii)）。0 と 1 は張り付かせない。"""
    q = min(1 - 1e-9, max(1e-9, float(p)))
    return 400.0 * math.log10(q / (1.0 - q))


def p_from_elo(d: float) -> float:
    """Elo 差 → 勝率（閾値の対応を確かめるための逆関数）。"""
    return 1.0 / (1.0 + 10.0 ** (-d / 400.0))


def branch_for(p: float, lo: float, hi: float) -> dict:
    """M4 の答え（便 C の範囲）。**判定は点推定で行い**、区間が閾値をまたげば「境界」と併記する。

    - +50 Elo 以上 → II-7・II-8・II-9・バケット化の**全部**
    - +20〜+50 Elo → II-7・II-8
    - +20 Elo 未満（マイナスを含む）→ **II-7 のみ**（II-7 はどの分岐でもやる）
    """
    d, dlo, dhi = elo_from_p(p), elo_from_p(lo), elo_from_p(hi)
    if d >= ELO_HI:
        scope = "all"
        text = "II-7・II-8・II-9・バケット化（全部）"
    elif d >= ELO_LO:
        scope = "ii7_ii8"
        text = "II-7・II-8"
    else:
        scope = "ii7_only"
        text = "II-7 のみ"
    boundary = [t for t in (ELO_LO, ELO_HI) if dlo < t < dhi]
    return {"elo": d, "elo_lo": dlo, "elo_hi": dhi,
            "scope": scope, "text": text,
            "boundary": bool(boundary),
            "boundary_thresholds": boundary,
            "thresholds": {"elo_lo": ELO_LO, "elo_hi": ELO_HI,
                           "p_at_elo_lo": p_from_elo(ELO_LO),
                           "p_at_elo_hi": p_from_elo(ELO_HI)}}


def wilson(x: float, n: int, z: float = 1.96):
    """Wilson の 95% 区間（`gate_sprt.wilson_interval` と同じ式）。"""
    if n <= 0:
        return None
    p = x / n
    z2 = z * z
    den = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / den
    return [max(0.0, center - half), min(1.0, center + half)]


# ------------------------------------------------------------ カンニング版
def _remove_multiset(pool: list, take: list) -> list:
    """多重集合の引き算。`pool` から `take` の各カードを 1 枚ずつ取り除いた残り。"""
    left = Counter(take)
    out = []
    for cid in pool:
        if left.get(cid, 0) > 0:
            left[cid] -= 1
        else:
            out.append(cid)
    return out


class PeekPlanner(PlannerAgent):
    """champion と同じ設定だが、**決定化のとき相手の手札だけ**を真の手札に固定する。

    親（`GreedyAgent._determinize`）との差はそこだけである:

    - 自分の山札 … 従来どおり `sorted` してからシャッフル（順序の漏洩は断つ）
    - 相手の手札 … **真の手札**（`s.players[1−pi].hand`）をそのまま入れる ← ここだけ違う
    - 相手の山札 … 未公開プールから真の手札を引いた残りを**シャッフル**して入れる

    `_sample_opponent` も同じ扱いに揃える（親の実装は現状どこからも呼ばれないが、
    「相手の手札をサンプルしている口」を 1 つだけ直して残りを直し忘れると天井が
    過小に出る。§7 の 3）。
    """

    def _determinize(self, s, pi):
        t = s.clone()
        me, opp = t.players[pi], t.players[1 - pi]

        deck = sorted(me.action_deck)          # 親と同じ（自分の山札順は隠蔽情報のまま）
        self.rng.shuffle(deck)
        me.action_deck = deck

        true_hand = list(s.players[1 - pi].hand)          # ← カンニングするのはここだけ
        pool = sorted(self._unseen(s, pi))
        rest = _remove_multiset(pool, true_hand)
        self.rng.shuffle(rest)                            # 相手の山札順は従来どおり混ぜる
        opp.hand = true_hand
        if len(rest) >= len(opp.action_deck):
            opp.action_deck = rest[:len(opp.action_deck)]
        else:
            d = sorted(opp.action_deck)
            self.rng.shuffle(d)
            opp.action_deck = d
        return t

    def _sample_opponent(self, s, pi):
        t = s.clone()
        t.players[1 - pi].hand = list(s.players[1 - pi].hand)
        return t


# ------------------------------------------------------------ 1 局
def _make(kind: str, kw: dict, pool: list, seed: int):
    if kind == "peek":
        return PeekPlanner(seed, opp_decklist=pool, **kw)
    if kind == "champion":
        return PlannerAgent(seed, opp_decklist=pool, **kw)
    if kind == "H":
        return HeuristicAgent(seed)
    raise SystemExit(f"未知の相手: {kind!r}")


def _one(args):
    """1 局。戻り値は (カンニング版から見た勝敗 | None, カンニング版の席, ターン数)。

    席はシードの偶奇（**偶数シードでカンニング版が席 0**）。`arena._one` と同じ
    「役を入れ替えれば席も入れ替わる」型なので、両席が同数になる。
    """
    deck, kw, opp_kind, a_kind, seed = args
    d = load_deck(deck)
    config, pool = mirror_config(d), d["action_deck"]
    a_seat = seed % 2                                  # 0 なら席 0、1 なら席 1
    agents = [None, None]
    agents[a_seat] = _make(a_kind, kw, pool, seed * 2)
    agents[1 - a_seat] = _make(opp_kind, kw, pool, seed * 2 + 1)
    r = play_game(config, agents, seed=seed)
    if r["aborted"] or r["draw"]:
        return (None, a_seat, r["turns"])
    return (1 if r["winner"] == a_seat else 0, a_seat, r["turns"])


def series_peek(deck: str, kw: dict, opp_kind: str, a_kind: str,
                seeds: list, workers: int = 2) -> list:
    jobs = [(deck, kw, opp_kind, a_kind, s) for s in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_one, jobs, chunksize=2))
    return [_one(j) for j in jobs]


# ------------------------------------------------------------ 集計と表示
def aggregate(rows: list, branch: bool = False) -> dict:
    dec = [r for r in rows if r["won"] is not None]
    n = len(dec)
    wins = sum(r["won"] for r in dec)
    out = {"games": len(rows), "n": n, "wins": wins,
           "p": (wins / n) if n else None,
           "ci": ci95(wins, n) if n else None,
           "wilson": wilson(wins, n) if n else None,
           "turns_mean": (sum(r["turns"] for r in rows) / len(rows)) if rows else None}
    if n:
        out["lo"], out["hi"] = out["p"] - out["ci"], out["p"] + out["ci"]
        out["elo"] = elo_from_p(out["p"])
        # **分岐は「カンニング版 対 champion」でだけ意味を持つ**。錨（対 H）や対照で
        # 出すと、便 C の範囲を H への勝率から決めたように読めてしまう。
        out["branch"] = (branch_for(out["p"], out["lo"], out["hi"])
                         if branch else None)
    for seat in (0, 1):
        d2 = [r for r in dec if r["seat"] == seat]
        w2 = sum(r["won"] for r in d2)
        out[f"seat{seat}"] = {"n": len(d2), "wins": w2,
                              "p": (w2 / len(d2)) if d2 else None,
                              "ci": ci95(w2, len(d2)) if d2 else None}
    return out


def render(agg: dict, label: str, peek: bool) -> str:
    if not agg["n"]:
        return "勝敗の付いた局が 0"
    p, ci = agg["p"], agg["ci"]
    who = "カンニング版" if peek else "A 側（champion）"
    L = [f"■ M4 {label}",
         "",
         f"  {who} から見た勝率: {p:.3f} ±{ci:.3f}"
         f"（{agg['wins']}/{agg['n']}／除外 {agg['games'] - agg['n']}）",
         f"  95% 区間 [{agg['lo']:.3f}, {agg['hi']:.3f}]"
         f"／Wilson [{agg['wilson'][0]:.3f}, {agg['wilson'][1]:.3f}]",
         f"  席 0 {agg['seat0']['p']:.3f}（n={agg['seat0']['n']}）／"
         f"席 1 {agg['seat1']['p']:.3f}（n={agg['seat1']['n']}）／"
         f"平均ターン {agg['turns_mean']:.1f}"]
    if peek and agg.get("branch"):
        b = agg["branch"]
        L += ["",
              f"  Elo 換算 **{b['elo']:+.1f}**（区間の両端 {b['elo_lo']:+.1f} / "
              f"{b['elo_hi']:+.1f}）",
              f"  → **便 C の範囲 = {b['text']}**"
              + ("　※ **境界**（区間が "
                 + " と ".join(f"{t:+.0f}" for t in b["boundary_thresholds"])
                 + " をまたぐ）。判定は点推定で行う（§0.3 (ii)）" if b["boundary"] else ""),
              "",
              "  読み方: これは**天井**であって、実装できる強さではない。"
              "相手の手札の推論を良くする投資（II-7〜II-9）の伸びしろの上限である。"]
    elif peek:
        L += ["", f"  Elo 換算 {agg['elo']:+.1f}",
              "", "  読み方: **錨**。champion 対 H の既知値と並べて、カンニング版が"
                  "「別の弱さ」を持ち込んでいないことを見る。**便 C の分岐はここからは決めない。**"]
    else:
        L += ["", "  読み方: **配線の対照**。0.5 を含んでいれば Python 側の席の割り当てと"
                  "乱数の配り方が偏っていない。"]
    return "\n".join(L)


# ------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--opponent", default="champion", choices=("champion", "H"),
                    help="相手役。champion（既定）か H（錨）")
    ap.add_argument("--peek", default="on", choices=("on", "off"),
                    help="off なら A 側もただの champion（P0 の対照）")
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--seed0", type=int, default=BAND[0])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--chunk", type=int, default=50, help="1 塊の局数（中断の粒度）")
    ap.add_argument("--budget-sec", type=float, default=480.0,
                    help="この秒数を越えたら塊の切れ目で止まる。同じコマンドで再開")
    ap.add_argument("--out", default=os.path.join(_HERE, "..", "results", "lit",
                                                  "m4_peek_planner.json"))
    ap.add_argument("--rows", default=None, help="1 行 1 局の JSONL（既定は --out の .jsonl）")
    ap.add_argument("--report", action="store_true", help="回さずに集計だけ出す")
    args = ap.parse_args(argv)

    peek = args.peek == "on"
    a_kind = "peek" if peek else "champion"
    # 天井（＝便 C の分岐を決める測定）は「カンニング版 対 champion」だけ
    is_ceiling = peek and args.opponent == "champion"
    kw = resolved_kwargs(args.deck)
    rows_path = args.rows or (os.path.splitext(args.out)[0] + ".jsonl")
    os.makedirs(os.path.dirname(os.path.abspath(rows_path)), exist_ok=True)

    # 再開の鍵。**`peek` の有無と相手役を含める**（P0 と P1 と P2 を混ぜない・§7 の 11）
    key = {"deck": args.deck, "peek": peek, "opponent": args.opponent,
           "seed0": args.seed0}
    rows: list = []
    done: set = set()
    if os.path.exists(rows_path):
        with open(rows_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("_key") is not None and r["_key"] != key:
                    raise SystemExit(
                        f"途中経過 {rows_path} は**別の条件**のものである。\n"
                        f"  貯まっている　　　: {json.dumps(r['_key'], ensure_ascii=False)}\n"
                        f"  いま回そうとしている: {json.dumps(key, ensure_ascii=False)}\n"
                        "足し込むと混ざった数が出る。別の --rows を指すこと。")
                rows.append(r)
                done.add(r["seed"])
        print(f"  ※ 途中から再開（{len(rows)}/{args.n} 局）", flush=True)

    label = (f"{'カンニング版' if peek else 'champion'} 対 "
             f"{'champion' if args.opponent == 'champion' else 'H'}")
    todo = [s for s in range(args.seed0, args.seed0 + args.n) if s not in done]
    if todo and not args.report:
        t0 = time.time()
        with open(rows_path, "a", encoding="utf-8") as fh:
            while todo and time.time() - t0 < args.budget_sec:
                block = todo[:args.chunk]
                todo = todo[args.chunk:]
                got = series_peek(args.deck, kw, args.opponent, a_kind,
                                  block, args.workers)
                for seed, (w, seat, turns) in zip(block, got):
                    r = {"seed": seed, "seat_peek": seat, "won": w, "turns": turns,
                         "_key": key}
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    rows.append({**r, "seat": seat})
                fh.flush()
                a = aggregate([{**x, "seat": x["seat_peek"]} for x in rows], branch=is_ceiling)
                print(f"  {len(rows)}/{args.n} 局: {label} = "
                      f"{a['p']:.3f} ±{a['ci']:.3f}（途中の数）  "
                      f"{time.time() - t0:.0f}s", flush=True)

    agg = aggregate([{**x, "seat": x["seat_peek"]} for x in rows], branch=is_ceiling)
    print()
    print(render(agg, label, peek))
    import provenance
    out = {"agg": agg, "n_wanted": args.n, "seed0": args.seed0,
           "rows_file": os.path.basename(rows_path),
           "peek": peek, "opponent": args.opponent, "label": label,
           "is_ceiling": is_ceiling,
           "definitions": {
               "peek_scope": "相手の手札だけ（山札順は従来どおり混ぜる。§0.3 (i)）",
               "elo": "Δ = 400·log10(p/(1−p))（§0.3 (ii)）",
               "branch": "点推定で判定。区間が閾値をまたぐときは境界と併記",
               "seat": "偶数シードでカンニング版が席 0"},
           "provenance": provenance.block(
               kw, "python", (args.seed0, args.seed0 + args.n - 1),
               extra={"tool": "peek_planner", "M": "M4",
                      "peek": peek, "opponent": args.opponent,
                      "host": provenance.host_name(), "workers": int(args.workers),
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
