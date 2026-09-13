# -*- coding: utf-8 -*-
"""便 K 段 K-5 — 公式が遅れて掲載した 2 枚（`BP01-057` / `BP01-062`）の機構。

便 K を閉じた時点で残っていたのはこの 2 枚の効果だけだった（T-K-10 が
`xfail(strict=True)` で見張っていた）。3 つの語彙を足して実装した:

- `grant_rush_draw_to_variation_skills` — これから使う N 枚への付与（u19）。
- `cost_mod` — 常在のコスト修正・下限 0（u20）。
- `levelup_by_effect` の `level` パラメータ — レベルを指定して探す（u21）。

**この 3 つはどれも「既定では誰も使わない」形にしてある**ので、
2 枚をデッキに入れない限り対局は 1 手も変わらない（T-K5-8）。

準拠版: rules_draft **v0.12** ／ engine v0.1。裁定は u19〜u21（2026-09-12・マスター）。
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
for _p in (_ROOT, os.path.join(_ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from meicho import engine as E                                     # noqa: E402
from meicho.cards import ACTION_CARDS, CHARA_CARDS, Skill, Timing  # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402


def _state(**kw) -> GameState:
    s = GameState(seed=1)
    s.players = [PlayerState(), PlayerState()]
    s.turn_no = 3
    s.turn_player = 0
    s.phase = Phase.ACTION
    for pi in (0, 1):
        s.players[pi].action_deck = ["SD01-007"] * 10
        s.players[pi].slots[0] = CharaSlot(stack=["SD01-001"])
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _put(s, pi, si, cid):
    s.players[pi].slots[si] = CharaSlot(stack=[cid])


def _run(s: GameState) -> GameState:
    E._pump(s)
    for _ in range(60):
        if not s.pending_choices:
            break
        pi = s.pending_choices[0]["player"]
        acts = E.legal_actions(s, pi)
        pick = next((a for a in acts if a["type"] == "use"), acts[0])
        s = E.apply(s, {pi: pick})
    return s


# --- BP01-057 終末ループ（u19）----------------------------------------------

def test_grant_counts_only_variation_skills_used_in_rush():
    """T-K5-1: 付与を消費するのは**連撃で使った＜変奏スキル＞**だけ（u19）。

    「次に使用する2枚」を連撃の札だけで数えるのは、このカード自身が対抗の札であり、
    同じターンにもう一度対抗が起きないからである（マスター裁定 2026-09-12）。
    """
    variation = next(c for c in ACTION_CARDS.values() if "変奏スキル" in c.tags)
    plain = next(c for c in ACTION_CARDS.values() if "変奏スキル" not in c.tags)

    # ＜変奏スキル＞: 1 枚引いて残りが 1 減る。
    # **`_after_rush_skills` の直後に見ること。** この関数は連撃を続けられなければ
    # そのままターンを畳みにいき、`_begin_turn` が残り枚数を 0 に戻す（u19）。
    # `_run` まで進めてから数えると「減った」と「ターンが終わった」が区別できない。
    s = _state(phase=Phase.RUSH, variation_rush_draw=[2, 0], rush_allowance=1)
    s.players[0].action_area = [variation.card_id]
    n0 = len(s.players[0].hand)
    E._after_rush_skills(s, 0, variation.card_id)
    assert len(s.players[0].hand) == n0 + 1, "＜変奏スキル＞で引けていない"
    assert s.variation_rush_draw[0] == 1, "残り枚数が減っていない"

    # ＜変奏スキル＞でない札: 何も起きない。
    s = _state(phase=Phase.RUSH, variation_rush_draw=[2, 0], rush_allowance=1)
    s.players[0].action_area = [plain.card_id]
    n0 = len(s.players[0].hand)
    E._after_rush_skills(s, 0, plain.card_id)
    assert len(s.players[0].hand) == n0, "＜変奏スキル＞でない札で引いている"
    assert s.variation_rush_draw[0] == 2, "残り枚数が減っている"

    # 残り 0 なら引かない。
    s = _state(phase=Phase.RUSH, variation_rush_draw=[0, 0], rush_allowance=1)
    s.players[0].action_area = [variation.card_id]
    n0 = len(s.players[0].hand)
    E._after_rush_skills(s, 0, variation.card_id)
    assert len(s.players[0].hand) == n0, "残り 0 なのに引いている"


def test_grant_is_cumulative_and_dies_at_end_of_turn():
    """T-K5-2: 同じターンに複数回誘発したら**加算**、ターンをまたぐと消える（u19）。

    加算にしたのは「追撃N」の累積規則（§6.4(2)-5・D-012）に合わせたからで、
    上書きではない。
    """
    s = _state()
    E._apply_op(s, 0, "grant_rush_draw_to_variation_skills", {"count": 2}, {})
    E._apply_op(s, 0, "grant_rush_draw_to_variation_skills", {"count": 2}, {})
    assert s.variation_rush_draw == [4, 0], "上書きになっている"

    _put(s, 0, 0, "SD01-001")
    _put(s, 1, 0, "SD01-001")
    E._begin_turn(s)
    assert s.variation_rush_draw == [0, 0], "ターンをまたいで残っている"


def test_bp01_057_clash_skill_grants_two_and_judge_heals_and_pursues():
    """T-K5-3: カード定義がその 2 つの効果を持っていること。

    【対抗】で 2 枚ぶんの付与、【判定】で勝利時にライフ 1 回復と追撃 8。
    追撃は加算（§6.4(2)-5）なので `rush_allowance` に足される。
    """
    card = ACTION_CARDS["BP01-057"]
    assert card.leader_skill is True, "【リーダースキル】の使用条件が落ちている"

    clash = [sk for sk in card.skills if sk.timing == Timing.CLASH]
    assert len(clash) == 1
    assert clash[0].effect == (("grant_rush_draw_to_variation_skills", {"count": 2}),)

    s = _state(clash_winner=0, rush_allowance=0)
    s.players[0].life = 10
    judge = [sk for sk in card.skills if sk.timing == Timing.JUDGE]
    assert len(judge) == 1
    assert E._skill_condition_met(s, 0, judge[0], {}) is True
    E._run_effects(s, 0, judge[0].effect)
    assert s.players[0].life == 11, "ライフが回復していない"
    assert s.rush_allowance == 8, "追撃 8 が入っていない"

    # 敗北側では誘発しない。
    s = _state(clash_winner=1)
    assert E._skill_condition_met(s, 0, judge[0], {}) is False


# --- BP01-062 黒メェ大暴走（u20・u21）---------------------------------------

def test_cost_mod_discounts_only_while_dominant_and_never_below_zero():
    """T-K5-4: 【優勢】のコスト-1 は**常在の割引・下限 0**（u20）。

    使用条件の判定にも支払いにも効くよう、`_effective_cost` の中で読む。
    """
    card = ACTION_CARDS["BP01-062"]
    s = _state(turn_no=2, last_turn_clash_winner=None)
    assert E._is_dominant(s, 0) is False
    assert E._effective_cost(s, 0, card) == 2, "優勢でないのに割り引かれている"

    s = _state(turn_no=2, last_turn_clash_winner=0)
    assert E._is_dominant(s, 0) is True
    assert E._effective_cost(s, 0, card) == 1, "優勢なのに割り引かれていない"
    assert E._effective_cost(s, 1, card) == 2, "相手まで割り引かれている"

    # 下限 0: 素のコストより大きな割引でも負にならない。
    fake = card.__class__(
        "T-K5-ZERO", "下限の検査", card.color, cost=1, speed=1, damage=0,
        skills=(Skill(Timing.STATIC, (("cost_mod", {"delta": -5}),),
                      condition={"dominant": True}),),
    )
    ACTION_CARDS[fake.card_id] = fake
    E._ACTION_TIMING_IDX.pop((fake.card_id, Timing.STATIC), None)
    try:
        assert E._effective_cost(s, 0, fake) == 0, "コストが負になっている"
    finally:
        del ACTION_CARDS[fake.card_id]
        E._ACTION_TIMING_IDX.pop((fake.card_id, Timing.STATIC), None)


def test_cost_mod_stacks_with_the_red_cost_up_of_senpuu():
    """T-K5-5: SD01-016「旋風」の +1 と同じ関数の中で足し合わさること。

    片方だけを別の場所で読むと「払えないのに使える」がすぐ出る。
    """
    card = ACTION_CARDS["BP01-062"]          # 赤
    s = _state(turn_no=2, last_turn_clash_winner=0, red_cost_up=[True, False])
    assert E._effective_cost(s, 0, card) == 2, "2 ＋1 −1 になっていない"


def test_levelup_with_an_explicit_level_places_level2_even_on_a_level2():
    """T-K5-6: レベルを指定して置く（u21）。**同レベルの上にも置ける**（§6.3-3）。

    「この処理はレベルアップとしても扱う」ので【登場】【レベルアップ】が誘発する。
    レベル 2 の「アンコ」が複数あればキャラデッキの先頭から（決定的）。
    """
    lv2 = [cid for cid, c in CHARA_CARDS.items()
           if c.name == "アンコ" and c.level == 2]
    assert len(lv2) >= 2, "レベル 2 の「アンコ」が 2 枚以上ある前提が崩れている"

    s = _state()
    _put(s, 0, 0, lv2[0])                     # すでにレベル 2
    s.players[0].chara_deck = list(lv2[1:])
    E._apply_op(s, 0, "levelup_by_effect", {"name": "アンコ", "level": 2}, {})
    assert s.players[0].slots[0].stack == [lv2[0], lv2[1]], \
        "レベル 2 の上にレベル 2 を置けていない"
    assert lv2[1] not in s.players[0].chara_deck, "キャラデッキから抜けていない"
    assert s.slot_entered_turn[0][0] == s.turn_no, "登場のターン番号が更新されていない"

    # 指定したレベルが無ければ何も起きない。
    s = _state()
    _put(s, 0, 0, lv2[0])
    s.players[0].chara_deck = []
    E._apply_op(s, 0, "levelup_by_effect", {"name": "アンコ", "level": 2}, {})
    assert s.players[0].slots[0].stack == [lv2[0]], "無いのに置かれている"


def test_levelup_without_a_level_is_unchanged():
    """T-K5-7: `level` を渡さない従来の呼び方が 1 文字も変わっていないこと。

    既存カード（BP01-011 ほか）はこちらを使う。挙動が動くと便 K の測定が嘘になる。
    """
    lv1 = next(cid for cid, c in CHARA_CARDS.items()
               if c.name == "アンコ" and c.level == 1)
    lv2 = [cid for cid, c in CHARA_CARDS.items()
           if c.name == "アンコ" and c.level == 2]
    s = _state()
    _put(s, 0, 0, lv1)
    s.players[0].chara_deck = list(lv2)
    E._apply_op(s, 0, "levelup_by_effect", {"name": "アンコ"}, {})
    assert s.players[0].slots[0].stack == [lv1, lv2[0]], "次のレベルが置かれていない"


def test_bp01_062_switches_the_leader_after_placing():
    """T-K5-8: 置いたあとリーダーを「アンコ」に切り替えること。

    切り替えが禁じられているターンは `switch_leader_to` が何もしない（§7 の延長）。
    """
    card = ACTION_CARDS["BP01-062"]
    clash = [sk for sk in card.skills if sk.timing == Timing.CLASH]
    assert len(clash) == 1
    assert clash[0].effect == (
        ("levelup_by_effect", {"name": "アンコ", "level": 2}),
        ("switch_leader_to", {"name": "アンコ"}),
    )

    lv2 = next(cid for cid, c in CHARA_CARDS.items()
               if c.name == "アンコ" and c.level == 2)
    s = _state()
    _put(s, 0, 0, "SD01-001")                 # リーダーは別キャラ
    _put(s, 0, 1, lv2)                        # バックに「アンコ」
    E._run_effects(s, 0, (("switch_leader_to", {"name": "アンコ"}),))
    assert CHARA_CARDS[s.players[0].slots[0].stack[-1]].name == "アンコ"


# --- 既定では誰も使わない ----------------------------------------------------

def test_the_two_cards_are_in_no_decklist_so_games_are_unchanged():
    """T-K5-9: 新しい語彙 3 つを、既存のどのカードも使っていないこと。

    ここが崩れると「足しただけで対局が変わる」ので、fingerprint の一致では
    原因が読めない失敗になる。**語彙の側から数えて 0 を確かめる**。
    """
    new_ops = {"cost_mod", "grant_rush_draw_to_variation_skills"}
    users = {}
    for cid, c in list(ACTION_CARDS.items()) + list(CHARA_CARDS.items()):
        for sk in c.skills:
            hit = sorted({op for op, _ in sk.effect} & new_ops)
            if op_level := [1 for op, prm in sk.effect
                            if op.startswith("levelup_by_effect") and "level" in prm]:
                hit = hit + ["levelup_by_effect(level=)"] * len(op_level)
            if hit:
                users.setdefault(cid, []).extend(hit)
    assert set(users) == {"BP01-057", "BP01-062"}, \
        f"新しい語彙を使っているカードが 2 枚以外にある: {sorted(users)}"
