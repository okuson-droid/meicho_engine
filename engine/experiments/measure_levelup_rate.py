"""「AI はレベルアップをしなさすぎるのではないか」を測る（D-043）。

rules_draft.md v0.10 準拠 / engine v0.1。
マスターの指摘（2026-08-25・対人対局 g001 のあと）:
「相手のプレイングで一番気になったのが、全然レベルアップをしないこと」。

## なぜ D-039 では見つからなかったのか（ここが要点）

D-039 は「レベルアップに価値があるか」を対照実験で調べ、**差は無い**と結論した。
しかし D-039 が試した対照は、いずれも**現状より下げる方向**だった。

| D-039 の対照 | 枝A | 枝B | 結果 |
|---|---|---|---|
| 対照1 | k回目のレベルアップを今やる | そのターンは待つ | −0.013 |
| 対照2 | 通常どおり | 一切やらない | −0.030 |
| 対照3（相手も計画探索） | 通常どおり | 一切やらない | +0.000 |

対照1 は**1回ぶんの前倒し**、対照2・3 は**現状からの削除**である。
**現状より多くレベルアップさせる方向は、一度も試していない。**

そして現状の頻度は低い。`diag_behaviour.py` の実測（planner vs H・40局）:

- レベルアップが選べたターンのうち実際にした割合 **31.7%**（83/262）
- 終局時のレベル合計（3体・最大6）の平均 **2.08**、40局での最大が 5

対する g001 のマスターは **6/6**（3体とも Lv2）で勝っている。
D-039 の §5-3 は「測っているのはこの AI にとっての価値であり、
より強い打ち手なら価値を引き出せるかもしれない」と自ら限界を書いていた。
**マスターの対局は、その限界の実例である。**

低い頻度から削っても差は出にくい。効果が「Lv2 まで積んで初めて出る」型なら、
1回の前倒しでも、元々2.08しかない分の削除でも、捉えられない。
**だから上げる方向を測る。**

## 測り方

`AlwaysLevelup`: アクションフェイズでレベルアップが合法なら必ず実行する
計画探索。**どのレベルアップを選ぶかは計画探索自身の評価に任せ、
「やるかどうか」だけを外から固定する。**

上限側の探り（upper-bound probe）である。「必ずやる」が最適だと主張するのではない。
知りたいのは**現状の 31.7% が低すぎるのかどうか**であり、
上げて良くなるなら低すぎ、悪くなるなら現状は的外れではない、と分かる。

3 つの測定:

1. **直接対決**: AlwaysLevelup vs 通常の計画探索。
2. **対 H_default**: 両者を同じシードで H に当て、勝率を比べる（共通乱数）。
3. **治療が効いているかの確認**: 終局時のレベル合計が実際に上がっていること。
   （効いていない治療で「差が無い」と言うのが D-039 の陥りかけた穴である。）

実行: python3 experiments/measure_levelup_rate.py [n] [--workers 2]
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from arena import ci95, load_deck, mirror_config, series          # noqa: E402
from registry import Mk                                            # noqa: E402
from meicho.cards import CHARA_CARDS                               # noqa: E402
from meicho.engine import apply, initial_state, outcome            # noqa: E402
from meicho.heuristic import HeuristicAgent                        # noqa: E402
from meicho.planner import PlannerAgent                            # noqa: E402

from meicho.runner import play_game                                # noqa: E402
from meicho.state import Phase                                     # noqa: E402

SEED0 = 150000        # seed_bands.json に登録済み（D-043 の測定専用）
DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]


class AlwaysLevelup(PlannerAgent):
    """レベルアップが合法なら必ずする計画探索（上限側の探り）。

    **「やるかどうか」だけを固定し、「どれをやるか」は計画探索に任せる。**
    合法手が 1 つしかない場面には介入しない（介入する余地が無い）。

    `act` を包むだけなので、探索の中身（`_branches` など）には触れていない。
    したがって「レベルアップを含む計画も普通に立てたうえで、
    最後に実行だけ強制する」形になる。
    """

    def act(self, s, pi):
        if s.phase != Phase.ACTION or s.turn_player != pi:
            return super().act(s, pi)
        from meicho.engine import legal_actions
        acts = legal_actions(s, pi)
        ups = [a for a in acts if a["type"] == "levelup"]
        if not ups or len(acts) == 1:
            return super().act(s, pi)
        if len(ups) == 1:
            return ups[0]
        # どれを重ねるかは自分の評価で決める（外から決めない）
        best, best_u = None, None
        for a in ups:
            u = self._settle(apply(s, {pi: a}), pi)
            v = self._eval(u, pi)
            if best_u is None or v > best_u:
                best, best_u = a, v
        return best


class AlwaysLevelupSmartDiscard(AlwaysLevelup):
    """必ずレベルアップし、**捨てる手札も自分で選ぶ**版（D-004 の影響を測る）。

    レベルアップは「そのカードのレベルと同数の手札を捨てる」を要求する（§6.3-3）。
    ところが計画探索は **捨てるカードの選択を探索していない**。
    `PlannerAgent.act` はアクションフェイズだけを計画し、選択フェイズは
    ヒューリスティックの既定に丸投げしている（D-004 の簡略化）。

    そこでここでは、捨てる 1 枚を 1 手先読みで選ぶ（捨てた直後の局面を
    自分の評価関数で採点し、最良のものを取る）。**レベルアップの是非ではなく、
    「払い方が下手なせいで高く付いているのか」を切り分けるための対照である。**
    """

    def act(self, s, pi):
        if s.phase == Phase.CHOICE:
            from meicho.engine import legal_actions
            acts = legal_actions(s, pi)
            ds = [a for a in acts if a["type"] == "discard"]
            if len(ds) > 1:
                best, best_v = None, None
                for a in ds:
                    v = self._eval(self._settle(apply(s, {pi: a}), pi), pi)
                    if best_v is None or v > best_v:
                        best, best_v = a, v
                return best
        return super().act(s, pi)


def _mk_always_smart(seed):
    return AlwaysLevelupSmartDiscard(seed, opp_decklist=POOL)


def _mk_always(seed):
    return AlwaysLevelup(seed, opp_decklist=POOL)


def _mk_planner(seed):
    return PlannerAgent(seed, opp_decklist=POOL)


def _mk_h(seed):
    return HeuristicAgent(seed)


# ------------------------------------------------------------------ 治療の確認
def _final_levels(agent_factory, opp_factory, seeds) -> dict:
    """終局時のレベル合計（席0のぶん）。**治療が効いているか**の確認用。"""
    tot, mx, ups = 0, 0, 0
    for seed in seeds:
        a, b = agent_factory(seed * 2), opp_factory(seed * 2 + 1)
        s = initial_state(CONFIG, seed)
        from meicho.engine import decision_players
        while outcome(s) is None and s.turn_no <= 200:
            need = decision_players(s)
            if not need:
                break
            acts = {}
            for pi in need:
                acts[pi] = (a if pi == 0 else b).act(s, pi)
                if pi == 0 and acts[pi].get("type") == "levelup":
                    ups += 1
            s = apply(s, {pi: acts[pi] for pi in sorted(acts)})
        lv = sum(0 if not sl.stack else CHARA_CARDS[sl.stack[-1]].level
                 for sl in s.players[0].slots)
        tot += lv
        mx = max(mx, lv)
    n = max(1, len(seeds))
    return {"mean_level_sum": tot / n, "max_level_sum": mx,
            "levelups_per_game": ups / n}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    workers = 1
    if "--workers" in args:
        i = args.index("--workers")
        workers = int(args[i + 1])
        del args[i:i + 2]
    n = int(args[0]) if args else 200

    print(f"D-043 レベルアップ頻度の上限側の探り（n={n}／シード帯 {SEED0}..）")
    print()

    print("■ 治療が効いているかの確認（先に見る。効いていない治療の"
          "「差が無い」は無意味である）")
    seeds = list(range(SEED0, SEED0 + min(n, 40)))
    base = _final_levels(_mk_planner, _mk_h, seeds)
    trt = _final_levels(_mk_always, _mk_h, seeds)
    print(f"  通常の計画探索  : レベル合計 平均 {base['mean_level_sum']:.2f}"
          f"／最大 {base['max_level_sum']}"
          f"／1局あたり {base['levelups_per_game']:.2f} 回")
    print(f"  AlwaysLevelup   : レベル合計 平均 {trt['mean_level_sum']:.2f}"
          f"／最大 {trt['max_level_sum']}"
          f"／1局あたり {trt['levelups_per_game']:.2f} 回")
    if trt["mean_level_sum"] <= base["mean_level_sum"] + 0.5:
        print("  ■ 治療が効いていない。以降の勝率差は解釈できない。")
    print()

    print("■ 測定1: 直接対決（AlwaysLevelup から見た勝率）")
    r = series(Mk(AlwaysLevelup, opp_decklist=POOL),
               Mk(PlannerAgent, opp_decklist=POOL),
               n, CONFIG, workers, seed0=SEED0)
    print(f"  {r.wins}/{r.decided} = {r}")
    print()

    print("■ 測定2: どちらも H_default に当てる（同じシード・共通乱数）")
    ra = series(Mk(PlannerAgent, opp_decklist=POOL), Mk(HeuristicAgent),
                n, CONFIG, workers, seed0=SEED0)
    rb = series(Mk(AlwaysLevelup, opp_decklist=POOL), Mk(HeuristicAgent),
                n, CONFIG, workers, seed0=SEED0)
    print(f"  通常の計画探索 vs H : {ra.wins}/{ra.decided} = {ra}")
    print(f"  AlwaysLevelup  vs H : {rb.wins}/{rb.decided} = {rb}")
    print(f"  差（Always − 通常）: {rb.p - ra.p:+.3f}")
    print()

    print("■ 測定3: 捨てる手札も自分で選ばせた場合（D-004 の簡略化の影響）")
    rc = series(Mk(AlwaysLevelupSmartDiscard, opp_decklist=POOL),
                Mk(HeuristicAgent), n, CONFIG, workers, seed0=SEED0)
    rd = series(Mk(AlwaysLevelupSmartDiscard, opp_decklist=POOL),
                Mk(PlannerAgent, opp_decklist=POOL),
                n, CONFIG, workers, seed0=SEED0)
    print(f"  Always+選んで捨てる vs H       : {rc.wins}/{rc.decided} = {rc}")
    print(f"  Always+選んで捨てる vs 計画探索 : {rd.wins}/{rd.decided} = {rd}")
    print(f"  捨て方を選ぶことの寄与（対H）  : {rc.p - rb.p:+.3f}")
    print()
    print("※ 区間は 95%。区間が重なる差を「差がある」と読まないこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
