"""決定化の**被覆率**ハーネス（文献計画 便 C・II-7 (b)・段 C-0）。
**診断専用。打ち方は 1 ビットも変えない。**

## 何を測るか

計画探索は「相手の手札はこれだろう」という仮の世界を K 本作って（＝決定化）、
その平均で手を選ぶ。**本当の手札がその K 本の中に 1 本も入っていなければ、
どれだけ深く読んでもその読みは当たらない。** その入っている割合を測るのが本器である。

- **cov_hand** … その決定で作った K 本のうち、**真の相手手札（多重集合）と
  ぴったり一致した本があった**割合（決定ごとに 0/1 を数え、決定全体で平均）
- **cov_next** … 対抗の決定（両者が同時に提出する場面）に限り、
  **相手がその対抗で実際に出した札を含む本があった**割合
- **TSSR**（true state sampling rate ratio・真の世界を引く率の比）…
  K 本のうち真の手札に置かれた重みの合計 × W。
  W は「公開情報から見て区別できる相手の手札の数」（`diag_pimc.world_counts`）。
  **区別できる手札の上で一様に引けていれば 1.0 になる**ように作ってある
  （1/W の重みが W 本ぶん）。1 より大きければ「真の手札を引きやすい」、
  小さければ「引きにくい」。

  *注意*: 既定の `_determinize` は**区別できる手札の上で一様ではなく、
  物理的な配り方の上で一様**である（同じ札が複数枚あると、その型の手札は
  出やすい）。したがって 1.0 は「理想の一様」との比であって
  「現状が 1.0 のはず」という意味ではない。段どうしの**差**を読む。

**被覆率が上がったことを champion 交代の根拠にしてはならない**（引継ぎ書 §1・
第 2 集 §3.4.4 のカンニング逆説）。強さは門番と錨で測る。ここは
「なぜ効いたか／効かなかったか」を説明するための道具である。

## どうやって打ち方を変えずに測るか

対局そのものは**現 champion のミラー**（`diag_pimc.py` と同じ骨格）で回す。
被覆率は、その各決定で**別のエージェント（影）**に `_determinize` を K 回呼ばせて数える。
影は自分の乱数を持つので、**実際に打つエージェントの乱数は 1 回も消費しない**。
したがってこの器を通した対局は、素の champion ミラーと 1 手も変わらない。

影のつまみだけを段ごとに差し替える（`--known-hand` など）。対局は毎回同じなので、
**同じ 100 局・同じ決定の上で**段どうしの被覆率を比べられる。

## 使い方

    python3 experiments/coverage.py --n 100 --seed0 680400 --workers 2 \
        --budget-sec 480 --out results/lit/c_cov_baseline.json

    # 段 C-1 の候補（`known_hand` を使わせた版）を同じ 100 局で
    python3 experiments/coverage.py --n 100 --seed0 680400 --known-hand \
        --out results/lit/c_cov_kh.json

同じコマンドで再開する（`--resume` は要らない。`.games.jsonl` にある局は飛ばす）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                                  # noqa: E402
from diag_pimc import world_counts                                          # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,          # noqa: E402
                           observe, outcome)
from meicho.planner import PlannerAgent                                     # noqa: E402
from meicho.state import Phase                                             # noqa: E402
from peek_counter import resolved_kwargs                                    # noqa: E402

BAND = (680400, 680499)          # §5 の帯（被覆率ハーネス・全段で共有）
KS = (4, 6, 24)                  # K = 4（`plan_samples` の既定）／6（`samples`）／24
SHADOW_SEED_OFFSET = 900_000_000  # 影の乱数の種（実際に打つ側と絶対にぶつからない値）

DEFINITIONS = {
    "cov_hand": "K 本の決定化のうち、真の相手手札（多重集合）と一致した本が"
                "**1 本でもあった**決定の割合",
    "cov_next": "対抗の決定に限り、相手がその対抗で実際に出した札を含む本が"
                "1 本でもあった割合（相手がパスした対抗は分母から外す）",
    "tssr": "K 本のうち真の手札に置いた重みの合計 × W。"
            "区別できる手札の上で一様に引けていれば 1.0。"
            "既定の決定化は**配り方の上で**一様なので 1.0 とは限らない（段の差を読む）",
    "tssr_pooled": "Σ(真の手札に置いた重み) ÷ Σ(1/W)。決定ごとの TSSR と意味は同じだが"
                   "裾が重くない。**段どうしの比較はこちらを使う**。"
                   "等重みのときは K によらない値になる（1 本あたりの当たりやすさを測る量で、"
                   "K は本数＝予算だから）。K を増やして上がるのは cov_hand の方である",
    "W": "公開情報（＋つまみが使うなら hand_known）から見て区別できる相手手札の数",
    "known_n": "スキャンで見えていて今も相手の手札にある札の枚数",
    "note": "診断専用。影のエージェントが決定化するので、実際に打つ側の乱数は消費しない",
}


# ------------------------------------------------------- 1 決定ぶんの数え方
def coverage_of_decision(sampled_hands, true_hand, w: int,
                         next_card=None, weights=None) -> dict:
    """K 本の相手手札から被覆率を出す。**この関数だけで数え方が決まる**（T-C-14）。

    `sampled_hands` は K 本ぶんの「相手の手札（カード ID のリスト）」、
    `true_hand` は本当の相手の手札、`w` は区別できる手札の数 W、
    `next_card` はその対抗で相手が実際に出した札（無ければ None）、
    `weights` は本ごとの重み（None なら等重み。II-8 の重みをここに渡す）。

    重みは合計 1 に正規化してから使う（合計が 0 や負なら等重みに落とす）。
    """
    k = len(sampled_hands)
    if k == 0:
        return {"k": 0, "hit_hand": None, "hit_next": None,
                "w_true": None, "tssr": None}
    if weights is None:
        ws = [1.0 / k] * k
    else:
        if len(weights) != k:
            raise ValueError(f"重みの本数が合わない: {len(weights)} 対 {k}")
        tot = sum(weights)
        ws = [w_ / tot for w_ in weights] if tot > 0 else [1.0 / k] * k
    want = Counter(true_hand)
    w_true = 0.0
    hit = False
    for hand, wi in zip(sampled_hands, ws):
        if Counter(hand) == want:
            hit = True
            w_true += wi
    hit_next = None
    if next_card is not None:
        hit_next = any(next_card in hand for hand in sampled_hands)
    tssr = (w_true * w) if (w and w > 0) else None
    return {"k": k, "hit_hand": bool(hit), "hit_next": hit_next,
            "w_true": w_true, "tssr": tssr}


# ------------------------------------------------------------ 影の決定化
def _shadow_kwargs(kw: dict, knobs: dict) -> dict:
    """影のエージェントに渡す引数。champion の設定 ＋ 段のつまみ。

    葉の価値関数は決定化に関係しないので落とす（読み込みが重いだけ）。
    相手モデル π₀（`opp_policy_net`）は II-8 の重みで使うので残す。
    """
    out = {k: v for k, v in kw.items() if k != "value_net"}
    out.update({k: v for k, v in knobs.items() if v is not None})
    return out


def _sample_hands(shadow, s, pi: int, k: int) -> list:
    """影に K 本の決定化を作らせ、その中の**相手の手札**だけを返す。"""
    return [shadow._determinize(s, pi).players[1 - pi].hand for _ in range(k)]


def _weights_for(shadow, s, pi: int, hands: list):
    """本ごとの重み（II-8・段 C-2）。つまみ 0 なら None（＝等重み）。"""
    fn = getattr(shadow, "world_weights_for", None)
    if fn is None or not getattr(shadow, "world_weight", 0.0):
        return None
    return fn(s, pi, hands)


def _worlds_of(shadow, s, pi: int, k: int):
    """段 C-3: 影に「その決定で実際に使う本」を作らせる。

    返すのは `(手札の並び, 重み or None, 列挙だったか)`。
    `endgame_enum` が 0 のときは従来の道（`_determinize` を k 回）と**同じ手順**であり、
    段 C-0〜C-2 の記録は 1 ビットも変わらない。
    """
    if not getattr(shadow, "endgame_enum", 0):
        hands = _sample_hands(shadow, s, pi, k)
        return hands, _weights_for(shadow, s, pi, hands), False
    ts, ws = shadow._worlds(s, pi, k)
    hands = [t.players[1 - pi].hand for t in ts]
    if getattr(shadow, "_worlds_enumerated", False):
        return hands, list(ws), True
    return hands, (list(ws) if getattr(shadow, "world_weight", 0.0) else None), False


# ------------------------------------------------------------------ 1 局
def _one(args):
    """1 局回して、決定ごとの被覆率の行と局の要約を返す。"""
    deck, kw, knobs, seed, max_turns, ks = args
    d = load_deck(deck)
    config, pool = mirror_config(d), d["action_deck"]
    agents = [PlannerAgent(seed * 2, opp_decklist=pool, **kw),
              PlannerAgent(seed * 2 + 1, opp_decklist=pool, **kw)]
    # 影は席ごとに 1 体ずつ。種は実際に打つ側と絶対にぶつからない領域から取る。
    skw = _shadow_kwargs(kw, knobs)
    shadows = [PlannerAgent(SHADOW_SEED_OFFSET + seed * 2, opp_decklist=pool, **skw),
               PlannerAgent(SHADOW_SEED_OFFSET + seed * 2 + 1, opp_decklist=pool, **skw)]

    s = initial_state(config, seed)
    rows: list = []
    steps = 0
    while outcome(s) is None:
        if s.turn_no > max_turns:
            break
        need = decision_players(s)
        if not need:
            break
        acts = {pi: agents[pi].act(s, pi) for pi in need}
        is_clash = (s.phase == Phase.CLASH_SUBMIT and set(need) == {0, 1})
        for pi in sorted(need):
            # 段 C-2: 影は自分で `act` しないので、履歴の出し入れを**実際のエージェントと
            # 同じ順序で**代わりに呼ぶ（`act` の入口で積み、対抗の重みを取ったあとに控える）。
            # 履歴の中身は公開情報だけなので、これは覗き見にならない。
            if getattr(shadows[pi], "world_weight", 0.0) > 0.0:
                shadows[pi]._note_history(s, pi)
            opp = s.players[1 - pi]
            true_hand = list(opp.hand)
            unseen = agents[pi]._unseen(s, pi)
            known = observe(s, pi)["opp"]["hand_known"]
            wc = world_counts(unseen, len(true_hand), known)
            wc0 = world_counts(unseen, len(true_hand), ())
            next_card = None
            if is_clash:
                a = acts[1 - pi]
                if a.get("type") == "submit":
                    next_card = opp.hand[a["hand"]]
            row = {"seed": seed, "seat": pi, "turn": s.turn_no,
                   "phase": s.phase.name, "is_clash": bool(is_clash),
                   "n_hand": len(true_hand), "known_n": len(known),
                   "W": wc["W"], "W_nokwn": wc0["W"],
                   "next_known": next_card is not None, "K": {}}
            for k in ks:
                hands, ws, enum = _worlds_of(shadows[pi], s, pi, k)
                row["K"][str(k)] = coverage_of_decision(
                    hands, true_hand, wc["W"], next_card, ws)
                # 段 C-3: その決定で列挙に入ったか（入った本数も）。
                row["K"][str(k)]["enumerated"] = bool(enum)
            if is_clash and getattr(shadows[pi], "world_weight", 0.0) > 0.0:
                shadows[pi]._remember_clash(s, pi)
            rows.append(row)
        s = apply(s, acts)
        steps += 1

    o = outcome(s)
    summary = {"seed": seed, "T": s.turn_no, "steps": steps,
               "decisions": len(rows), "aborted": bool(o is None)}
    return rows, summary


def series(deck: str, kw: dict, knobs: dict, seeds: list, workers: int = 2,
           max_turns: int = 200, ks=KS) -> list:
    jobs = [(deck, kw, knobs, s, max_turns, tuple(ks)) for s in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_one, jobs, chunksize=1))
    return [_one(j) for j in jobs]


# ------------------------------------------------------------------ 集計
def _stats(xs: list) -> dict:
    if not xs:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    v = sorted(xs)
    n = len(v)
    med = v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])
    return {"n": n, "mean": sum(v) / n, "median": med, "min": v[0], "max": v[-1]}


def _rate(hits: int, n: int) -> dict:
    """割合と 95% Wilson 区間（§2.7）。"""
    if not n:
        return {"n": 0, "hits": 0, "rate": None, "lo": None, "hi": None}
    p, z = hits / n, 1.959963985
    den = 1.0 + z * z / n
    c = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {"n": n, "hits": hits, "rate": p,
            "lo": max(0.0, c - half), "hi": min(1.0, c + half)}


def aggregate(rows: list, summaries: list, ks=KS) -> dict:
    out = {"games": len(summaries), "decisions": len(rows),
           "definitions": DEFINITIONS, "K_list": list(ks),
           "by_K": {}}
    for k in ks:
        key = str(k)
        have = [r for r in rows if key in r["K"]]
        hh = [r for r in have if r["K"][key]["hit_hand"] is not None]
        nx = [r for r in have if r["K"][key]["hit_next"] is not None]
        ts = [r["K"][key]["tssr"] for r in have if r["K"][key]["tssr"] is not None]
        kn = [r for r in hh if r["known_n"] > 0]
        # TSSR は決定ごとに見ると裾が重い（当たったときだけ W 倍の値が立つ）。
        # 決定をまたいで比べるときは**プールした比**を使う:
        #   Σ(真の手札に置いた重み) ÷ Σ(1/W)   ＝ 一様に引いたときの期待値との比。
        # 分母が「一様ならこれだけ当たるはず」の総量なので、意味は各決定の TSSR と同じで
        # ありながら、まれな大当たりに引きずられない。
        wt = [r["K"][key]["w_true"] for r in have
              if r["K"][key]["w_true"] is not None and r["W"]]
        inv = [1.0 / r["W"] for r in have
               if r["K"][key]["w_true"] is not None and r["W"]]
        out["by_K"][key] = {
            "cov_hand": _rate(sum(1 for r in hh if r["K"][key]["hit_hand"]), len(hh)),
            "tssr_pooled": (sum(wt) / sum(inv)) if inv and sum(inv) > 0 else None,
            "cov_hand_known": _rate(sum(1 for r in kn if r["K"][key]["hit_hand"]),
                                    len(kn)),
            "cov_next": _rate(sum(1 for r in nx if r["K"][key]["hit_next"]), len(nx)),
            "tssr": _stats(ts),
            "w_true_mean": _stats([r["K"][key]["w_true"] for r in have
                                   if r["K"][key]["w_true"] is not None])["mean"],
            # 段 C-3: 列挙に入った決定の割合と、そこでの cov_hand（1.000 になるはず）
            "enum_rate": _rate(sum(1 for r in have
                                   if r["K"][key].get("enumerated")), len(have)),
            "cov_hand_enum": _rate(
                sum(1 for r in hh if r["K"][key].get("enumerated")
                    and r["K"][key]["hit_hand"]),
                sum(1 for r in hh if r["K"][key].get("enumerated"))),
        }
    out["W"] = _stats([r["W"] for r in rows])
    out["W_nokwn"] = _stats([r["W_nokwn"] for r in rows])
    out["known_rate"] = _rate(sum(1 for r in rows if r["known_n"] > 0), len(rows))
    out["clash_decisions"] = sum(1 for r in rows if r["is_clash"])
    out["games_aborted"] = sum(1 for s in summaries if s["aborted"])
    return out


def _fmt(x, d=3):
    return "―" if x is None else f"{x:.{d}f}"


def render(agg: dict, title: str = "") -> str:
    L = [f"■ 決定化の被覆率{('（' + title + '）') if title else ''}", "",
         f"  局数 {agg['games']}／決定 {agg['decisions']}"
         f"（うち対抗 {agg['clash_decisions']}・打ち切り {agg['games_aborted']}）",
         f"  スキャンで見た札がある決定 {_fmt(agg['known_rate']['rate'])}"
         f"／W 中央値 {agg['W']['median']}（hand_known 無視なら "
         f"{agg['W_nokwn']['median']}）", ""]
    for k in agg["K_list"]:
        b = agg["by_K"][str(k)]
        L += [f"  ── K = {k} 本 ──",
              f"    cov_hand（真の手札を含む）  {_fmt(b['cov_hand']['rate'])}"
              f" [{_fmt(b['cov_hand']['lo'])}, {_fmt(b['cov_hand']['hi'])}]"
              f"　※ 見えている札がある決定に限ると {_fmt(b['cov_hand_known']['rate'])}",
              f"    cov_next（次に出す札を含む）{_fmt(b['cov_next']['rate'])}"
              f" [{_fmt(b['cov_next']['lo'])}, {_fmt(b['cov_next']['hi'])}]"
              f"（n={b['cov_next']['n']}）",
              (f"    列挙に入った決定 {_fmt(b['enum_rate']['rate'])}"
               f"（n={b['enum_rate']['n']}）"
               f"／そこでの cov_hand {_fmt(b['cov_hand_enum']['rate'])}"
               f"（n={b['cov_hand_enum']['n']}）"
               if b.get("enum_rate", {}).get("hits") else
               "    列挙に入った決定 なし（段 C-3 のつまみが 0）"),
              f"    TSSR プール比 {_fmt(b.get('tssr_pooled'))}"
              f"（1.000 = 区別できる手札の上で一様に引けている。**段の比較はこれを見る**）"
              f"／決定ごとの平均 {_fmt(b['tssr']['mean'])}"
              f"（裾が重く n=100 局では揺れる）", ""]
    L += ["  読み方: cov_hand が 0 に近いなら、探索は**真の局面を一度も見ずに**手を選んでいる。",
          "  ただし被覆率が上がっても強くなるとは限らない（第 2 集 §3.4.4）。強さは門番と錨で測る。"]
    return "\n".join(L)


# ------------------------------------------------- 回帰 2 局面の診断（§3.0.3）
# 対人局の記録から取る局面。**T-14 は本便では関門ではなく診断である**（§0.3 (i)）。
# 見たいのは 1 つだけ:「その局面で、探索は真の相手手札を一度でも見ているか」。
REGRESSION_GAMES = os.path.join(_HERE, "..", "results", "human_games", "2026-09.jsonl")
REGRESSION_PICKS = (
    # (相手の名前, game_id, 取る対抗, 説明)
    ("planner_vb3", "g001", "last", "2026-09-03 の負け（詰みの烈火を持ちながらパス）"),
    ("planner_vb3", "g002", "last", "2026-09-03 の負け（青で受けた）"),
    ("planner_vc4cps", "g001", 3, "2026-09-08 の負け（序盤のテンポ負け）T3"),
    ("planner_vc4cps", "g001", 4, "2026-09-08 の負け（序盤のテンポ負け）T4"),
)


def regression_positions(path: str = None) -> list:
    """回帰局面を記録から再生して返す。

    返すのは [(tag, 局面, AI の席, エージェントのシード, 相手が実際に出した手, 説明)]。
    再生は `verify_lethal_human.walk_clashes` を**そのまま呼ぶ**（写して書き換えない。
    D-075 の教訓）。`walk_clashes` は対抗の局面と**そのとき実際に出された手**を組で返す。
    """
    from verify_lethal_human import walk_clashes
    path = path or REGRESSION_GAMES
    if not os.path.exists(path):
        return []
    recs = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    d = load_deck("SD001")
    cfg = mirror_config(d)
    out = []
    for opp_name, gid, pick, why in REGRESSION_PICKS:
        hit = [r for r in recs
               if r["opponent"]["name"] == opp_name and r["game_id"] == gid]
        if not hit:
            continue
        rec = hit[-1]
        clashes = walk_clashes(rec, cfg)
        if not clashes:
            continue
        if pick == "last":
            s, acts = clashes[-1]
        else:
            sel = [c for c in clashes if c[0].turn_no == pick]
            if not sel:
                continue
            s, acts = sel[0]
        ai = 1 - rec["human_seat"]
        tag = f"{opp_name}:{gid}:{'last' if pick == 'last' else 'T' + str(pick)}"
        # 段 C-2: その局面より**前の対抗**（同じ局の中）。相手モデルの重みは
        # 「相手が直近に何を出したか」で決まるので、履歴が無いと等重みに落ちてしまう。
        # ここで渡すのは公開情報だけ（局面と、相手が実際に出した手）である。
        prior = [(u, a[1 - ai]) for (u, a) in clashes if u.turn_no < s.turn_no]
        out.append((tag, s, ai, rec["opponent"].get("seed", 0), acts[1 - ai], why,
                    prior))
    return out


def _seed_history(shadow, ai: int, prior) -> None:
    """段 C-2: 同じ局のそれまでの対抗を、実際のエージェントと同じ形で履歴に積む。

    積むのは `_remember_clash` が作るのと**同じ 3 つ組**（公開局面・相手が出した札・
    そのときの相手の公開領域）である。**相手の手札も山札も入らない。**
    """
    if not getattr(shadow, "world_weight", 0.0):
        return
    shadow._opp_history = []
    for u, hu_a in prior[-max(1, shadow.weight_lookback):]:
        cid = (u.players[1 - ai].hand[hu_a["hand"]]
               if hu_a.get("type") == "submit" else None)
        shadow._opp_history.append((shadow._public_frame(u, ai), cid,
                                    shadow._opp_public_cards(u, ai)))


def run_regression(kw: dict, knobs: dict, ks=(6, 24), path: str = None,
                   reps: int = 20) -> dict:
    """回帰局面で「真の相手手札を決定化が捉えているか」を出す。

    **1 回引いて当たったかは運で決まる**（K=24・W=48 の局面でも当たらない引きはある）ので、
    独立な種で `reps` 回やり直し、**当たった回の割合**を出す。
    `hit_hand` は 1 回目の結果（従来どおりの 0/1）で、読みには割合の方を使う。
    """
    d = load_deck("SD001")
    pool = d["action_deck"]
    skw = _shadow_kwargs(kw, knobs)
    rows = []
    for tag, s, ai, seed, hu_act, why, prior in regression_positions(path):
        opp = s.players[1 - ai]
        true_hand = list(opp.hand)
        unseen = PlannerAgent(0, opp_decklist=pool, **skw)._unseen(s, ai)
        known = observe(s, ai)["opp"]["hand_known"]
        wc = world_counts(unseen, len(true_hand), known)
        wc0 = world_counts(unseen, len(true_hand), ())
        next_card = (opp.hand[hu_act["hand"]]
                     if hu_act.get("type") == "submit" else None)
        row = {"tag": tag, "why": why, "turn": int(s.turn_no), "ai_seat": int(ai),
               "n_hand": len(true_hand), "known_n": len(known),
               "W": wc["W"], "W_nokwn": wc0["W"], "prior_clashes": len(prior),
               "next_is_submit": next_card is not None, "K": {}}
        for k in ks:
            outs = []
            for r in range(max(1, reps)):
                shadow = PlannerAgent(SHADOW_SEED_OFFSET + seed + 1_000 * r,
                                      opp_decklist=pool, **skw)
                _seed_history(shadow, ai, prior)
                hands, ws, enum = _worlds_of(shadow, s, ai, k)
                outs.append({**coverage_of_decision(hands, true_hand, wc["W"],
                                                    next_card, ws),
                             "enumerated": bool(enum)})
            hit = [o for o in outs if o["hit_hand"] is not None]
            nx = [o for o in outs if o["hit_next"] is not None]
            row["K"][str(k)] = {
                **outs[0],
                "reps": len(outs),
                "hit_hand_rate": (sum(1 for o in hit if o["hit_hand"]) / len(hit))
                                 if hit else None,
                "hit_next_rate": (sum(1 for o in nx if o["hit_next"]) / len(nx))
                                 if nx else None,
                "tssr_mean": (sum(o["tssr"] for o in outs
                                  if o["tssr"] is not None) / len(outs))
                             if outs and outs[0]["tssr"] is not None else None,
            }
        rows.append(row)
    return {"positions": rows, "knobs": knobs, "K_list": list(ks),
            "reps": reps, "definitions": DEFINITIONS}


def render_regression(res: dict) -> str:
    L = ["■ 回帰 2 局面の診断（T-14 は本便では**関門ではなく診断**・§0.3 (i)）", ""]
    for r in res["positions"]:
        L.append(f"  {r['tag']}（{r['why']}）")
        L.append(f"    T{r['turn']}・相手の手札 {r['n_hand']} 枚"
                 f"／見えている札 {r['known_n']} 枚／W = {r['W']}"
                 f"（hand_known を無視した W = {r.get('W_nokwn')}"
                 "＝**いまの探索が実際に引いている広さ**）")
        for k in res["K_list"]:
            b = r["K"][str(k)]
            L.append(f"    K={k}: 真の手札を含む割合 "
                     + _fmt(b.get("hit_hand_rate"))
                     + f"（{b.get('reps', 1)} 回引き直して）"
                     + "／その対抗で相手が出した札を含む割合 "
                     + _fmt(b.get("hit_next_rate"))
                     + "／TSSR 平均 " + _fmt(b.get("tssr_mean")))
        L.append("")
    if not res["positions"]:
        L.append("  （対人の記録が無い環境）")
    return "\n".join(L)


# --------------------------------------------------------------------- CLI
def knobs_from_args(args) -> dict:
    """引数から段のつまみを組む。**設定しなかったつまみは渡さない**（既定のまま）。"""
    knobs: dict = {}
    if args.known_hand:
        knobs["known_hand"] = True
    if args.world_weight is not None:
        knobs["world_weight"] = float(args.world_weight)
        if args.weight_temp is not None:
            knobs["weight_temp"] = float(args.weight_temp)
        if args.weight_floor is not None:
            knobs["weight_floor"] = float(args.weight_floor)
    if args.endgame is not None:
        knobs["endgame_enum"] = int(args.endgame)
    if args.buckets:
        knobs["draw_buckets"] = 1
    return knobs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed0", type=int, default=BAND[0])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--chunk", type=int, default=5, help="1 塊の局数（中断の粒度）")
    ap.add_argument("--budget-sec", type=float, default=480.0)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--ks", default=",".join(str(k) for k in KS),
                    help="決定化の本数（カンマ区切り）")
    # --- 段のつまみ（影にだけ渡す。対局は常に現 champion ミラー） ------------
    ap.add_argument("--known-hand", action="store_true",
                    help="II-7 (a): スキャンで見た札を必ず相手の手札に入れる")
    ap.add_argument("--world-weight", type=float, default=None,
                    help="II-8: π₀ の到達確率で重み付け（0..1）")
    ap.add_argument("--weight-temp", type=float, default=None)
    ap.add_argument("--weight-floor", type=float, default=None)
    ap.add_argument("--endgame", type=int, default=None,
                    help="II-9: W がこの値以下なら整合世界を全列挙")
    ap.add_argument("--buckets", action="store_true",
                    help="ドロー結果のバケット化")
    ap.add_argument("--title", default="", help="表示用の一言（現 champion など）")
    ap.add_argument("--out", default=os.path.join(_HERE, "..", "results", "lit",
                                                  "c_cov_baseline.json"))
    ap.add_argument("--rows", default=None)
    ap.add_argument("--report", action="store_true", help="回さずに集計だけ出す")
    ap.add_argument("--mode", default="games", choices=("games", "regression"),
                    help="games = 自己対戦の被覆率／regression = 回帰局面の診断")
    args = ap.parse_args(argv)

    ks = tuple(int(x) for x in args.ks.split(",") if x.strip())
    kw = resolved_kwargs(args.deck)
    knobs = knobs_from_args(args)

    if args.mode == "regression":
        import provenance
        ks_r = tuple(k for k in ks if k >= 6) or ks
        res = run_regression(kw, knobs, ks_r)
        print(render_regression(res))
        res["provenance"] = provenance.block(
            kw, "python", None,
            extra={"tool": "coverage --mode regression", "stage": "lit_C",
                   "knobs": knobs, "host": provenance.host_name(),
                   "note": "対局を生まない（記録の再生のみ）。T-14 は診断"})
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f"\n→ {args.out}")
        return 0
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
                    sm = json.loads(line)
                    summaries.append(sm)
                    done.add(sm["seed"])
        with open(rows_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r["seed"] in done:
                        rows.append(r)
        print(f"  ※ 途中から再開（{len(summaries)}/{args.n} 局）", flush=True)

    # **由来は測定の開始時に書く**（§2.8 の V 凍結）。
    import provenance
    prov = provenance.block(
        kw, "python", (args.seed0, args.seed0 + args.n - 1),
        extra={"tool": "coverage", "stage": "lit_C", "knobs": knobs,
               "K_list": list(ks), "host": provenance.host_name(),
               "workers": int(args.workers),
               "note": "診断専用。影のエージェントが決定化するので打ち方は変わらない"})

    todo = [s for s in range(args.seed0, args.seed0 + args.n) if s not in done]
    if todo and not args.report:
        t0 = time.time()
        with open(rows_path, "a", encoding="utf-8") as fr, \
                open(sums_path, "a", encoding="utf-8") as fs:
            while todo and time.time() - t0 < args.budget_sec:
                block = todo[:args.chunk]
                todo = todo[args.chunk:]
                for rs, sm in series(args.deck, kw, knobs, block, args.workers,
                                     args.max_turns, ks):
                    for r in rs:
                        fr.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fs.write(json.dumps(sm, ensure_ascii=False) + "\n")
                    rows.extend(rs)
                    summaries.append(sm)
                fr.flush()
                fs.flush()
                a = aggregate(rows, summaries, ks)
                k0 = str(ks[0])
                print(f"  {len(summaries)}/{args.n} 局: K={k0} の cov_hand "
                      + _fmt(a["by_K"][k0]["cov_hand"]["rate"])
                      + f"　{time.time() - t0:.0f}s", flush=True)

    agg = aggregate(rows, summaries, ks)
    print()
    print(render(agg, args.title))
    out = {"agg": agg, "n_wanted": args.n, "seed0": args.seed0,
           "knobs": knobs, "K_list": list(ks),
           "rows_file": os.path.basename(rows_path),
           "games_file": os.path.basename(sums_path),
           "definitions": DEFINITIONS, "provenance": prov}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {args.out}")
    finished = len(summaries) >= args.n
    print("（完了）" if finished else "（途中。同じコマンドで続きから回る）")
    return 0 if finished or args.report else 3


if __name__ == "__main__":
    sys.exit(main())
