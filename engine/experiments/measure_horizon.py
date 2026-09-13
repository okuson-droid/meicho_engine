"""探索の地平を1ターン延ばすと何が起きるか（D-046）。

rules_draft.md v0.10 準拠 / engine v0.1。
マスターの問い（2026-08-25）:
「長期的な視点、大局的な視点を AI が持てていない。
 今後のプランですでにこの問題が解消される見込みはあるか？」

## 何を変えているか

`PlannerAgent._value_after_turn` は、候補手を打ったあと固定方策で進めて採点する。
その打ち切り条件が `if u.turn_no != turn0 and u.phase != Phase.CHOICE: break`、
すなわち **自分のターンの終わりまで**である。

`LongHorizonPlanner` はこれを **次に自分の手番が始まるところ**まで延ばす。
相手のターンを通してから採点するので、
【ターン開始時】の誘発が 1 回だけ地平の内側に入る。

変えたのはこの 1 メソッドだけである。特徴も重みも探索の枝も触っていない。

## なぜ「地平が短いこと」を疑ったのか（そして疑いだけでは足りなかった）

D-045 で、漂泊者（女）Lv2（【ターン開始時】無条件で1枚引く）を最短で作ると
現champion に勝ち越すと分かった。ところが計画探索は自分ではほとんどそこへ行かない。
費用（手札2枚）は地平の内側、便益（次のターン以降の毎ターン1枚）は外側だからである。

しかし**エージェント横断の観察は、この単純な説明と合わない**。

| エージェント | 先読みの深さ | 漂泊者Lv2 到達（対H・40局） | 到達ターン |
|---|---|---|---|
| 計画探索 | 実質1ターン | 3 / 40 | 7.7 |
| IS-MCTS(160) | ロールアウト2ターン | 12 / 40 | 10.8 |
| 貪欲 | 1手 | 28 / 40 | 4.9 |
| H_default | **先読み無し** | 28 / 40 | 4.4 |

**先読みが浅いほどよく到達している。** 規則ベースの H は「余裕があれば上げる」という
一行の規則に従うだけで、ほぼ最短で Lv2 を作る。

つまり問題は「地平が短くて便益が見えない」だけではない。
**評価が表現できないものを、探索が忠実に最適化しているのである。**
探索を強くするほど、評価の盲点が増幅される。
だからこそ「地平を延ばせば直る」は**推測ではなく測定で確かめる必要があった。**

実行: python3 experiments/measure_horizon.py [n] [--workers 4]
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from arena import load_deck, mirror_config, series                # noqa: E402
from registry import Mk                                           # noqa: E402
from meicho.heuristic import HeuristicAgent                       # noqa: E402
from meicho.planner import PlannerAgent                           # noqa: E402

SEED0 = 164000        # seed_bands.json に登録済み（D-046 の測定専用）
DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]


class LongHorizonPlanner(PlannerAgent):
    """葉の採点を「次に自分の手番が始まった時点」まで延ばした計画探索。

    `extra_turns=1` で相手のターンを 1 つ通す。**デッキに依存しない一般の変更**で
    あり、特定のカード名を知っている必要はない。

    費用は速度である（相手のターンぶん余計に `apply` を回す）。
    D-035 で「速度は C-1 の壁ではない」と実測してあるので、
    払う余地はある。実測値は `main()` が出す。

    **D-064 で実装は `PlannerAgent(extra_turns=...)` に移した**（設計書 §4.1）。
    ここに残るのは既存の呼び出し元・文献との対応をとるための別名だけである。
    重複実装を置かないこと（同じ打ち切り条件が 2 か所にあると必ず食い違う）。
    """

    def __init__(self, seed, extra_turns: int = 1, **kw):
        super().__init__(seed, extra_turns=extra_turns, **kw)


def _mk_long(seed):
    return LongHorizonPlanner(seed, opp_decklist=POOL)


def _mk_planner(seed):
    return PlannerAgent(seed, opp_decklist=POOL)


def _mk_h(seed):
    return HeuristicAgent(seed)


def speed(n: int = 40) -> dict:
    """1局あたりの所要時間。地平を延ばす費用はここに出る。"""
    out = {}
    for label, cls in (("planner", PlannerAgent),
                       ("long_horizon", LongHorizonPlanner)):
        t0 = time.time()
        series(Mk(cls, opp_decklist=POOL), Mk(HeuristicAgent), n, CONFIG, 1,
               seed0=SEED0 + 4000)
        d = time.time() - t0
        out[label] = n / d
    return out


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    workers = 1
    if "--workers" in args:
        i = args.index("--workers")
        workers = int(args[i + 1])
        del args[i:i + 2]
    n = int(args[0]) if args else 600

    print(f"D-046 探索の地平を1ターン延ばす（n={n}／シード帯 {SEED0}..）")
    print()
    print("■ 挙動が変わったか（対 H_default・40局）")
    from measure_rush_lv2 import _trace
    seeds = list(range(SEED0 + 1000, SEED0 + 1040))
    for label, mk in (("通常（1ターン）", _mk_planner),
                      ("地平を延ばす（2ターン）", _mk_long)):
        t = _trace(mk, _mk_h, seeds)
        mt = "—" if t["mean_turn"] is None else f"{t['mean_turn']:.1f}"
        print(f"  {label:22s}: 漂泊者Lv2 到達 {t['reached']:2d}/{t['games']}"
              f"／到達ターン 平均 {mt:>5s}"
              f"／Lv2 が引かせた枚数 平均 {t['total_extra_draws_per_game']:.2f}")
    print()

    print("■ 強さ（直接対決・地平を延ばした側から見た勝率）")
    r = series(Mk(LongHorizonPlanner, opp_decklist=POOL),
               Mk(PlannerAgent, opp_decklist=POOL), n, CONFIG, workers,
               seed0=SEED0 + 2600)
    print(f"  {r.wins}/{r.decided} = {r}／下端 {r.p - r.ci:.4f}")
    print()

    print("■ 速度の代償（40局・1プロセス）")
    sp = speed(40)
    print(f"  通常 {sp['planner']:.2f} 局/秒 → 延長 {sp['long_horizon']:.2f} 局/秒"
          f"（{sp['planner'] / sp['long_horizon']:.2f} 倍の時間）")
    print()
    print("※ D-045 の教訓: 下端が 0.5 をぎりぎり超えただけの結果は、"
          "別シードで再現するまで信用しないこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
