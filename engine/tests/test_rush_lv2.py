"""漂泊者を最短で Lv2 にする方策の検査（D-045）。

ここで固定するのは**結論（勝率）ではなく前提**である。勝率は乱数を伴う測定なので
テストにはしない。テストにすべきなのは「その測定が成り立つための条件」であり、
それが崩れたら測定結果の意味が変わる、という類のものである。

1. 漂泊者 Lv2 のスキルが「無条件・毎ターン・リーダー限定でない」ままであること
   （カードデータを直したらこの前提が壊れる）
2. `RushWandererLv2` が実際に最短で Lv2 に着くこと（＝治療が効いていること）
3. Lv2 に着いたあとは通常の計画探索に戻ること（介入が漏れ続けていないこと）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from measure_rush_lv2 import (CONFIG, GOAL_LEVEL, POOL, TARGET,  # noqa: E402
                              RushWandererLv2, _top_level)
from meicho.cards import CHARA_CARDS                             # noqa: E402
from meicho.engine import (apply, decision_players,              # noqa: E402
                           initial_state, outcome)
from meicho.heuristic import HeuristicAgent                      # noqa: E402
from meicho.planner import PlannerAgent                          # noqa: E402

SEED0 = 160000        # seed_bands.json に登録済み（D-045 の測定専用）

# **D-045 の前提は「このカード」についての話である**（D-083 追記 4）。
# BP01 は SD のキャラ全員に Lv1 / Lv2 の**別版**を足したので、
# 「名前とレベル」ではカードが 1 枚に決まらなくなった
# （漂泊者（女）Lv2 は SD01-001 と BP01-016 の 2 枚。**効果はまったく違う**——
# BP01-016 は【判定】の条件付き・リーダー限定である）。
# したがって基準は**カード番号を明示の定数で直書きする**。
# 名前から引き直すと、プールが増えるたびに検査が黙って別のカードを見に行く。
TARGET_CARD_ID = "SD01-001"


def test_wanderer_lv2_is_an_unconditional_every_turn_draw():
    """D-045 の前提: 漂泊者 Lv2 が「無条件・毎ターン・リーダー不問」であること。

    この 3 つが揃っているから「早く着けるほど得」になる。
    カードデータを修正してどれかが崩れたら、D-045 の結論は再測定が要る。
    """
    from meicho.cards import Timing as T
    card = CHARA_CARDS[TARGET_CARD_ID]
    assert (card.name, card.level) == (TARGET, GOAL_LEVEL), (card.name, card.level)
    skills = card.skills
    assert len(skills) == 1
    sk = skills[0]
    assert sk.timing == T.TURN_START, "【ターン開始時】でなくなっている"
    assert sk.leader_only is False, "リーダー限定になっている（バックで効かない）"
    assert sk.optional is False, "任意になっている"
    # 条件は「自分のターンであること」だけ（＝毎ターン必ず誘発する）
    assert sk.condition == {"is_turn_player": True}, sk.condition
    assert sk.effect == (("draw", {"count": 1}),), sk.effect


def _run(agent, seed, max_turns=40, stop_at_goal=False):
    """agent を席0、H_default を席1 で対局させる。

    戻り値は (Lv2 到達ターン or None, そのときの局面)。
    `stop_at_goal=True` なら到達した時点で止める（到達直後の局面が欲しい場合）。
    """
    opp = HeuristicAgent(seed * 2 + 1)
    s = initial_state(CONFIG, seed)
    got = None
    while outcome(s) is None and s.turn_no <= max_turns:
        need = decision_players(s)
        if not need:
            break
        s = apply(s, {pi: (agent if pi == 0 else opp).act(s, pi)
                      for pi in sorted(need)})
        if got is None and _top_level(s, 0, TARGET) == GOAL_LEVEL:
            got = s.turn_no
            if stop_at_goal:
                return got, s
    return got, s


def test_rush_reaches_lv2_much_earlier_than_the_plain_planner():
    """治療が効いていること。**勝率より先にこれを見る。**

    効いていない治療で勝率差を語るのは無意味である（D-043 の教訓）。
    """
    rush, plain = [], []
    for i in range(6):
        seed = SEED0 + 500 + i
        got, _ = _run(RushWandererLv2(seed * 2, opp_decklist=POOL), seed)
        rush.append(got)
        got2, _ = _run(PlannerAgent(seed * 2, opp_decklist=POOL), seed)
        plain.append(got2)
    assert all(g is not None for g in rush), f"急ぐ版が到達しない: {rush}"
    assert max(rush) <= 5, f"最短ルートになっていない: {rush}"
    reached_plain = [g for g in plain if g is not None]
    assert len(reached_plain) < len(rush), (
        "通常の計画探索が同じだけ到達している（対照になっていない）")


def test_rush_stops_intervening_once_the_goal_is_reached():
    """Lv2 に着いたあとは通常の計画探索と同じ手を選ぶこと。

    介入が残り続けると、測っているものが「早く Lv2 にすること」ではなく
    「ずっとレベルアップを優先すること」に変わってしまう。
    """
    from meicho.state import Phase
    checked = 0
    for i in range(4):
        seed = SEED0 + 600 + i
        got, s = _run(RushWandererLv2(seed * 2, opp_decklist=POOL), seed,
                      stop_at_goal=True)
        if got is None:
            continue
        assert _top_level(s, 0, TARGET) == GOAL_LEVEL
        # 到達後のアクションフェイズまで、通常の計画探索で進める
        plain_drive = PlannerAgent(seed * 2, opp_decklist=POOL)
        opp = HeuristicAgent(seed * 2 + 1)
        t = s
        for _ in range(60):
            if outcome(t) is not None:
                break
            need = decision_players(t)
            if not need:
                break
            if t.phase == Phase.ACTION and t.turn_player == 0 and 0 in need:
                break
            t = apply(t, {pi: (plain_drive if pi == 0 else opp).act(t, pi)
                          for pi in sorted(need)})
        if outcome(t) is not None or t.phase != Phase.ACTION or t.turn_player != 0:
            continue
        # **両方とも作りたての同一シード**で比べる。使い回すと乱数の履歴が
        # 違ってしまい、介入の有無ではなく履歴の違いを見ることになる。
        a = RushWandererLv2(seed * 2, opp_decklist=POOL)
        b = PlannerAgent(seed * 2, opp_decklist=POOL)
        assert a.act(t, 0) == b.act(t, 0), "Lv2 到達後も介入している"
        checked += 1
    assert checked >= 1, "到達後のアクションフェイズを1度も検査できていない"


def test_name_and_level_no_longer_identify_a_card():
    """**名前とレベルではカードが 1 枚に決まらない**ことを、前提として固定する。

    BP01 が SD のキャラ全員に Lv1 / Lv2 の別版を足したためである（D-083 追記 4）。
    ここが 1 枚に戻ったら、それはカードデータのほうが壊れている
    （あるいは BP01 を外した）ということなので、検査で気づけるようにしておく。
    """
    same = [c for c in CHARA_CARDS.values()
            if c.name == TARGET and c.level == GOAL_LEVEL]
    assert len(same) == 2, [c.card_id for c in same]
    assert {c.card_id for c in same} == {"SD01-001", "BP01-016"}
