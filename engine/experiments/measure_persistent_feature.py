"""「カードから導出する特徴」が、プールに依らずに効くかを試す（D-047）。

rules_draft.md v0.10 準拠 / engine v0.1。
マスターの指摘（2026-08-25）:
「今後も定期的にカードプールは増えていく。
 それを見越したうえで、カードプールの増加に対応できる AI を計画する必要がある」。

## 何を確かめたいのか

D-046 で分かったのは、現行 22 特徴が**集計値**であること
（`level_me` は3枠のレベルの合計）。だから

- 漂泊者（女）Lv2（【ターン開始時】無条件で毎ターン1枚引く）
- 秧秧 Lv2（【対抗】【リーダー】赤で対抗したときだけ）

が同じ入力になり、価値の違い（0.555 対 0.500）を表現できない。

素朴な直し方は「漂泊者Lv2 なら +N」と書くことだが、
**それはプールが増えるたびに書き足す必要がある**。カード名を知識として埋め込む形は、
新セットが出るたびに陳腐化する。マスターの指摘はまさにここに当たる。

そこで別の形を試す。**定義は一般で、値はカードデータを読んで決まる特徴**である。

> いま自分の場で有効な**持続効果**（無条件・毎ターン誘発、または常在）の数

カード名は一つも出てこない。にもかかわらず漂泊者Lv2（【ターン開始時】・無条件）は
数えられ、秧秧Lv2（【対抗】・条件付き）は数えられない。
**新しいカードが増えても、書き足さずにそのまま数えられる。**

これが効くなら、「プール増加に対応できる AI」の作り方が一つ確かめられたことになる。

## 測り方

`PersistentAwarePlanner` は葉の採点に `w * (自分の持続効果数 − 相手の持続効果数)` を足す。
**変えたのはここだけ**で、探索も他の重みも触っていない。

比較は 3 つ。共通乱数（同じシード）で行う。

1. 対 通常の計画探索（SD001 同型）— 効くか
2. 対 通常の計画探索（**SD02 同型**）— **調整に使っていないプールでも効くか**
3. 挙動: 漂泊者Lv2 への到達が増えるか（D-045 の穴が塞がるか）

2 が本命である。SD001 でだけ効くなら、それは結局プール固有の知識でしかない。

実行: python3 experiments/measure_persistent_feature.py [n] [--workers 4]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from arena import load_deck, mirror_config, series                  # noqa: E402
from registry import Mk                                             # noqa: E402
from meicho.cards import Timing                                     # noqa: E402
from meicho.engine import _active_skills                            # noqa: E402
from meicho.heuristic import HeuristicAgent                         # noqa: E402
from meicho.planner import PlannerAgent                             # noqa: E402

SEED0 = 172000        # seed_bands.json に登録済み（D-047 の測定専用）

# 「持続効果」とみなすタイミング。毎ターン誘発するか、常に効いているもの。
PERSISTENT = (Timing.TURN_START, Timing.STATIC)
# 条件のうち「実質いつでも満たされる」とみなすキー。
# `is_turn_player` は自分のターンなら必ず真なので、毎ターン1回は必ず誘発する。
ALWAYS_KEYS = {"is_turn_player"}


def persistent_count(s, pi: int) -> int:
    """pi の場で有効な持続効果の数。**カード名を一つも知らずに数える。**

    数える条件は 3 つ。
      1. タイミングが【ターン開始時】または【常在】であること
      2. 条件が無いか、実質いつでも満たされるものだけであること
      3. 任意（「〜してもよい」）でないこと

    新しいカードが増えても、この関数は書き換えずにそのまま数えられる。
    そこが「カードから導出する特徴」の要点である。
    """
    n = 0
    for timing in PERSISTENT:
        for sk in _active_skills(s, pi, timing):
            if sk.optional:
                continue
            cond = sk.condition or {}
            if cond and not set(cond) <= ALWAYS_KEYS:
                continue
            n += 1
    return n


class PersistentAwarePlanner(PlannerAgent):
    """葉の採点に「持続効果の数の差」を足した計画探索。

    `w_persistent` は 1 個あたりの価値。`evaluate` の他の項と同じ尺度で、
    `w.life`（ライフ1点）を基準に読む。既定値は探索用の暫定値であり、
    本採用するなら A-3 の CEM で他の重みと**同時に**調整し直すこと
    （単軸で決めた値は誤導する・D-028）。
    """

    def __init__(self, seed, w_persistent: float = 3.0, **kw):
        super().__init__(seed, **kw)
        self.w_persistent = w_persistent

    def _eval(self, s, pi) -> float:
        v = super()._eval(s, pi)
        if s.outcome is not None:      # 終端は ±WIN のまま触らない
            return v
        return v + self.w_persistent * (persistent_count(s, pi)
                                        - persistent_count(s, 1 - pi))


def _run(deck_name: str, n: int, workers: int, w: float, seed0: int) -> None:
    d = load_deck(deck_name)
    cfg = mirror_config(d)
    pool = d["action_deck"]
    r = series(Mk(PersistentAwarePlanner, opp_decklist=pool, w_persistent=w),
               Mk(PlannerAgent, opp_decklist=pool), n, cfg, workers, seed0=seed0)
    h = series(Mk(PersistentAwarePlanner, opp_decklist=pool, w_persistent=w),
               Mk(HeuristicAgent), n, cfg, workers, seed0=seed0)
    print(f"  {deck_name:6s} 同型: vs 通常の計画探索 {r.wins}/{r.decided} = {r}"
          f"／下端 {r.p - r.ci:.4f}   （vs H {h}）")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    workers = 1
    if "--workers" in args:
        i = args.index("--workers")
        workers = int(args[i + 1])
        del args[i:i + 2]
    w = 3.0
    if "--w" in args:
        i = args.index("--w")
        w = float(args[i + 1])
        del args[i:i + 2]
    n = int(args[0]) if args else 300

    print(f"D-047 カードから導出する特徴「持続効果の数」（w={w}／n={n}）")
    print()
    print("■ 強さ")
    _run("SD001", n, workers, w, SEED0)
    _run("SD02", n, workers, w, SEED0 + 3000)     # 調整に使っていないプール
    print()
    print("■ 挙動: 漂泊者Lv2 への到達（対 H_default・40局・SD001）")
    from measure_rush_lv2 import _trace, _mk_h, POOL
    seeds = list(range(SEED0 + 6000, SEED0 + 6040))
    for label, mk in (
            ("通常の計画探索", lambda sd: PlannerAgent(sd, opp_decklist=POOL)),
            ("持続効果を見る", lambda sd: PersistentAwarePlanner(
                sd, opp_decklist=POOL, w_persistent=w))):
        t = _trace(mk, _mk_h, seeds)
        mt = "—" if t["mean_turn"] is None else f"{t['mean_turn']:.1f}"
        print(f"  {label:16s}: 到達 {t['reached']:2d}/{t['games']}"
              f"／到達ターン 平均 {mt:>5s}"
              f"／Lv2 が引かせた枚数 平均 {t['total_extra_draws_per_game']:.2f}")
    print()
    print("※ SD02 でも効くかどうかが本命である。SD001 でだけ効くなら、"
          "それはプール固有の知識でしかない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
