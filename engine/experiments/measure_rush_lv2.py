"""漂泊者を最短で Lv2 にする方策を測る（D-045）。

rules_draft.md v0.10 準拠 / engine v0.1。
マスターの指摘（2026-08-25）:
「漂泊者Lv2 の効果はターン開始時に1枚引くというもので、
 はやく有効にすればするほど恩恵が大きい効果です」。

## なぜ D-043 の「必ずレベルアップ」では捉えられなかったのか

D-043 は `AlwaysLevelup`（レベルアップできるなら必ずする）を測り、
**通常より弱い**（対 H で 0.890 → 0.770）と結論した。
しかしあの方策は **3 体を無差別に上げる**。手札コストは §6.3-3 より
「重ねるカードのレベルと同じ枚数」なので、3 体とも Lv2 にすると
(1+2) × 3 = **9 枚**を捨てることになる。

対して漂泊者だけを Lv2 にするなら **1+2 = 3 枚**である。
そして得られるものは質が違う。

| カード | スキル | 型 |
|---|---|---|
| 漂泊者（女）Lv0 | 【対抗】【リーダー】緑で対抗したとき デッキの上2枚まで手札に | 条件付き・単発 |
| 漂泊者（女）Lv1 | 【判定】【リーダー】緑で赤に負けたとき 1枚（してもよい） | 条件付き・単発 |
| **漂泊者（女）Lv2** | **【ターン開始時】自分のターン: カードを1枚引く** | **無条件・毎ターン** |

**Lv2 だけ「毎ターン無条件」である。** しかも `leader_only=False` なので
**バックに置いたままでも働く**（実装で確認済み。本スクリプトの検査でも固定する）。
早く着けば着くほど、残りターン数ぶん得が積み上がる。

D-043 の `AlwaysLevelup` は、この「1 体を早く Lv2 に」と
「3 体を無差別に」を混ぜてしまっていた。**分離して測り直す。**

## 測り方

`RushWandererLv2`: アクションフェイズで、漂泊者がまだ Lv2 でなく、
漂泊者のレベルアップが合法なら、**到達できる一番高いレベル**を選んで実行する。
Lv2 に着いたら以降は通常の計画探索に戻る（他の 2 体には介入しない）。

比較（すべて共通乱数・同じシード帯）:

1. **直接対決**: RushWandererLv2 vs 通常の計画探索
2. **共通の相手**: 両者を同じシードで H_default に当てる
3. **効いていることの確認**: Lv2 到達ターンと、Lv2 が実際に引かせた枚数

実行: python3 experiments/measure_rush_lv2.py [n] [--workers 4]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from arena import ci95, load_deck, mirror_config, series          # noqa: E402
from registry import Mk                                           # noqa: E402
from meicho.cards import CHARA_CARDS                              # noqa: E402
from meicho.engine import (apply, decision_players,               # noqa: E402
                           initial_state, legal_actions, outcome)
from meicho.heuristic import HeuristicAgent                       # noqa: E402
from meicho.planner import PlannerAgent                           # noqa: E402
from meicho.state import Phase                                    # noqa: E402

SEED0 = 160000        # seed_bands.json に登録済み（D-045 の測定専用）
DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]
TARGET = "漂泊者（女）"
GOAL_LEVEL = 2


def _top_level(s, pi: int, name: str):
    """name のキャラが場にあるなら、その一番上のレベル。無ければ None。"""
    for sl in s.players[pi].slots:
        if sl.stack and CHARA_CARDS[sl.stack[-1]].name == name:
            return CHARA_CARDS[sl.stack[-1]].level
    return None


class RushWandererLv2(PlannerAgent):
    """漂泊者を最短で Lv2 にする計画探索。

    **介入するのは「漂泊者のレベルアップをするかどうか」だけ**である。
    Lv2 に着いたあとは何もしない（＝通常の計画探索そのもの）。
    他の 2 体のレベルアップにも介入しない。

    D-043 の `AlwaysLevelup` と違い、**払う手札は最大 3 枚**（Lv1 に 1 枚、
    Lv2 に 2 枚）で済む。狙いを 1 体に絞ることで、
    「早く着ける利益」と「無差別に上げる費用」を分離して測る。
    """

    target = TARGET
    goal = GOAL_LEVEL

    def act(self, s, pi):
        if s.phase != Phase.ACTION or s.turn_player != pi:
            return super().act(s, pi)
        lv = _top_level(s, pi, self.target)
        if lv is None or lv >= self.goal:
            return super().act(s, pi)
        acts = legal_actions(s, pi)
        if len(acts) == 1:
            return super().act(s, pi)
        ups = [a for a in acts
               if a["type"] == "levelup"
               and CHARA_CARDS[a["card"]].name == self.target]
        if not ups:
            return super().act(s, pi)
        # 到達できる一番高いレベルを選ぶ（§6.3-3: 同レベル or +1 が置ける）
        return max(ups, key=lambda a: CHARA_CARDS[a["card"]].level)


class RushWandererLv2Lead(RushWandererLv2):
    """さらに、開始時のリーダーを漂泊者に固定する版。

    Lv2 の引く効果は `leader_only=False` なのでリーダーである必要は無い。
    ただし Lv0・Lv1 のスキルは【リーダー】付きである。
    **リーダー選択が結果に効くかどうか**を切り分けるために別に測る。
    """

    def act(self, s, pi):
        if s.phase == Phase.SETUP_CHARA:
            acts = legal_actions(s, pi)
            for a in acts:
                if a.get("leader") == self.target:
                    return a
        return super().act(s, pi)


class LateWandererLv2(RushWandererLv2):
    """同じ Lv2 を作るが、**7ターン目まで着手しない**。

    **到達点は同じで、到達の早さだけが違う。**
    マスターの主張「はやく有効にすればするほど恩恵が大きい」が正しければ、
    この版では優位が消えるはずである。消えなければ、効いているのは
    「早さ」ではなく「Lv2 という到達点そのもの」だったことになる。
    """

    def act(self, s, pi):
        if s.phase == Phase.ACTION and s.turn_no < 7:
            return PlannerAgent.act(self, s, pi)
        return super().act(s, pi)


class RushChixiaLv2(RushWandererLv2):
    """対照: 熾霞を急ぐ。Lv2 は【常在】で熾霞の専用リーダーカードのダメージ+3。
    **持続効果ではあるが、対象のカードを持っていて初めて効く。**"""
    target = "熾霞"


class RushYangyangLv2(RushWandererLv2):
    """対照: 秧秧を急ぐ。Lv2 は【対抗】【リーダー】で赤で対抗したときだけ誘発する。
    **毎ターンでも無条件でもない。**"""
    target = "秧秧"


# ------------------------------------------------------------------ 診断
def _trace(mk_a, mk_b, seeds) -> dict:
    """治療が効いているかを見る。**勝率より先にこれを見ること。**

    - 漂泊者が Lv2 に到達したターン（到達しなければ None）
    - Lv2 の【ターン開始時】が実際に引かせた枚数
      （到達後に自分のターンが何回来たかを数える。§6.1 で毎ターン開始時に誘発する）
    """
    reach, never, extra, games = [], 0, [], 0
    for seed in seeds:
        a, b = mk_a(seed * 2), mk_b(seed * 2 + 1)
        s = initial_state(CONFIG, seed)
        got_at, draws, seen_turns = None, 0, set()
        while outcome(s) is None and s.turn_no <= 200:
            need = decision_players(s)
            if not need:
                break
            if (got_at is not None and s.turn_player == 0
                    and s.turn_no not in seen_turns):
                seen_turns.add(s.turn_no)
                draws += 1
            s = apply(s, {pi: (a if pi == 0 else b).act(s, pi)
                          for pi in sorted(need)})
            if got_at is None and _top_level(s, 0, TARGET) == GOAL_LEVEL:
                got_at = s.turn_no
        games += 1
        if got_at is None:
            never += 1
        else:
            reach.append(got_at)
            extra.append(draws)
    return {
        "games": games,
        "reached": len(reach),
        "never": never,
        "mean_turn": (sum(reach) / len(reach)) if reach else None,
        "mean_extra_draws": (sum(extra) / len(extra)) if extra else 0.0,
        "total_extra_draws_per_game": sum(extra) / max(1, games),
    }


def _mk_planner(seed):
    return PlannerAgent(seed, opp_decklist=POOL)


def _mk_rush(seed):
    return RushWandererLv2(seed, opp_decklist=POOL)


def _mk_rush_lead(seed):
    return RushWandererLv2Lead(seed, opp_decklist=POOL)


def _mk_h(seed):
    return HeuristicAgent(seed)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    workers = 1
    if "--workers" in args:
        i = args.index("--workers")
        workers = int(args[i + 1])
        del args[i:i + 2]
    n = int(args[0]) if args else 200

    print(f"D-045 漂泊者を最短で Lv2 にする（n={n}／シード帯 {SEED0}..）")
    print()
    print("■ まず治療が効いているかを見る（対 H_default・40局）")
    seeds = list(range(SEED0, SEED0 + min(n, 40)))
    for label, mk in (("通常の計画探索", _mk_planner),
                      ("漂泊者Lv2を急ぐ", _mk_rush),
                      ("同＋リーダー固定", _mk_rush_lead)):
        t = _trace(mk, _mk_h, seeds)
        mt = "—" if t["mean_turn"] is None else f"{t['mean_turn']:.1f}"
        print(f"  {label:16s}: Lv2 到達 {t['reached']}/{t['games']} 局"
              f"／到達ターン 平均 {mt}"
              f"／Lv2 が引かせた枚数 平均 {t['total_extra_draws_per_game']:.2f}")
    print()

    print("■ 測定1: 直接対決（漂泊者Lv2を急ぐ 側から見た勝率）")
    r1 = series(Mk(RushWandererLv2, opp_decklist=POOL),
                Mk(PlannerAgent, opp_decklist=POOL), n, CONFIG, workers,
                seed0=SEED0)
    r2 = series(Mk(RushWandererLv2Lead, opp_decklist=POOL),
                Mk(PlannerAgent, opp_decklist=POOL), n, CONFIG, workers,
                seed0=SEED0)
    print(f"  漂泊者Lv2を急ぐ   vs 計画探索: {r1.wins}/{r1.decided} = {r1}")
    print(f"  同＋リーダー固定  vs 計画探索: {r2.wins}/{r2.decided} = {r2}")
    print()

    print("■ 測定2: どちらも H_default に当てる（同じシード・共通乱数）")
    ra = series(Mk(PlannerAgent, opp_decklist=POOL), Mk(HeuristicAgent),
                n, CONFIG, workers, seed0=SEED0)
    rb = series(Mk(RushWandererLv2, opp_decklist=POOL), Mk(HeuristicAgent),
                n, CONFIG, workers, seed0=SEED0)
    rc = series(Mk(RushWandererLv2Lead, opp_decklist=POOL), Mk(HeuristicAgent),
                n, CONFIG, workers, seed0=SEED0)
    print(f"  通常の計画探索    vs H: {ra.wins}/{ra.decided} = {ra}")
    print(f"  漂泊者Lv2を急ぐ   vs H: {rb.wins}/{rb.decided} = {rb}")
    print(f"  同＋リーダー固定  vs H: {rc.wins}/{rc.decided} = {rc}")
    print(f"  差（急ぐ − 通常）: {rb.p - ra.p:+.3f}／"
          f"（急ぐ＋固定 − 通常）: {rc.p - ra.p:+.3f}")
    print()

    print("■ 測定3: 何が効いているのかの切り分け（すべて vs 通常の計画探索）")
    print("  ※ 探索と確認で**別のシード**を使う。一度の結果で結論しないため。")
    for label, cls, start, m in (
            ("早さ: 7ターン目から着手", LateWandererLv2, SEED0 + 1000, n),
            ("対象: 熾霞 Lv2 を急ぐ", RushChixiaLv2, SEED0 + 2000, n),
            ("対象: 秧秧 Lv2 を急ぐ", RushYangyangLv2, SEED0 + 2500, n)):
        rr = series(Mk(cls, opp_decklist=POOL),
                    Mk(PlannerAgent, opp_decklist=POOL), m, CONFIG, workers,
                    seed0=start)
        print(f"  {label:22s}: {rr.wins}/{rr.decided} = {rr}"
              f"／下端 {rr.p - rr.ci:.4f}")
    print()
    print("※ 区間は 95%。区間が重なる差を「差がある」と読まないこと。")
    print("※ 下端が 0.5 をわずかに超えただけの結果は、**別のシードで再現するまで"
          "信用しないこと**（本件では熾霞が n=300 で 0.560／下端 0.5038 だったが、"
          "n=600 の確認で 0.495 に戻った）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
