# -*- coding: utf-8 -*-
"""公式ルール再照合 A-4 / B-4 — 誘発条件を判定する**時点**。

## 何を守るか

公式は誘発条件の判定を**誘発した時点**で行うと定める。

- **800.5.3**「誘発型スキルは、…**誘発条件を満たした時点で**自動的に誘発され、
  そのスキルの処理待ち回数が 1 増加します。」
- **800.4**「処理待ち状態に入った誘発型スキルは、**発生源から独立して扱われます**。
  そのため、発生源が元の領域から離れた場合でも、その効果は通常に解決されます。」
- **FAQ 47**（`BP01-076` 凛然穿撃）「【対抗】を持つ誘発型スキルは、…公開した時と**同時に誘発し、
  処理待ち状態に入ります**。**この時点では** BP01-033「散華」はバックポジションにいるため、
  BP01-033 の【リーダー】スキルは無効であり、**誘発しません**。」FAQ 48 も同型。

v0.14 までの実装は、積むときに `leader_only`（リーダー枠に居るか）**だけ**を見て、
スキルの `condition` は**解決の直前**にしか見ていなかった。ずれる方向が 2 つある。

- **A-4**: 誘発時に成立 → 解決時に不成立 で**落としてしまう**（800.4 違反）。
- **B-4**: 誘発時に不成立 → 解決時に成立 で**解決してしまう**（FAQ 47/48 違反）。

準拠版: rules_draft **v0.15** ／ engine v0.1 ／ D-092（R-4）・D-096。
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

from meicho import engine as E                                   # noqa: E402
from meicho.cards import Timing                                   # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402


def _state() -> GameState:
    s = GameState(seed=1)
    s.players = [PlayerState(), PlayerState()]
    s.turn_no = 3
    s.turn_player = 0
    s.phase = Phase.ACTION
    for pi in (0, 1):
        s.players[pi].action_deck = ["SD01-007"] * 10
        s.players[pi].trash = ["SD01-008"]
    return s


def _anko_board(s: GameState) -> None:
    """P0 のリーダーをアンコ Lv0、バックを別キャラにする。"""
    s.players[0].slots[0] = CharaSlot(stack=["BP01-015"])   # アンコ Lv0
    s.players[0].slots[1] = CharaSlot(stack=["BP01-005"])   # ツバキ Lv0
    s.players[1].slots[0] = CharaSlot(stack=["SD01-002"])


def _run(s: GameState) -> GameState:
    E._pump(s)
    for _ in range(40):
        if not s.pending_choices:
            break
        ch = s.pending_choices[0]
        pi = ch["player"]
        acts = E.legal_actions(s, pi)
        pick = next((a for a in acts if a["type"] == "use"), acts[0])
        s = E.apply(s, {pi: pick})
    return s


# --- A-4: 誘発時に成立していれば、解決時に崩れても解決される（800.4）--------

def test_a_queued_skill_still_resolves_after_its_condition_breaks():
    """800.4: 処理待ちに入ったスキルは、その後に条件が崩れても解決される。

    `BP01-060`「メェ、出撃·重撃」の【相手にダメージを与えた時】は
    条件「自分のリーダーが『アンコ』の場合」を持ち、効果はカードを 1 枚引くことである。

    ダメージを与えた時点でリーダーがアンコなら**その時点で誘発**する。
    そのあと（先に解決した別のスキルなどで）リーダーが変わっても、**引く効果は解決される**。
    v0.14 までは解決の直前に条件を見直して**落としていた**。
    """
    s = _state()
    _anko_board(s)
    s.players[0].action_area = ["BP01-060"]
    E._queue_fire_on_card(s, Timing.ON_DAMAGE_DEALT, 0, "action", "BP01-060")
    assert s.pending_triggers, "誘発時点で条件を満たしているのに積まれていない"

    # 解決の前にリーダーが変わる（切り替えが先に解決した、という想定）
    s.players[0].slots[0], s.players[0].slots[1] = s.players[0].slots[1], s.players[0].slots[0]
    assert E._leader_name(s, 0) != "アンコ"

    before = len(s.players[0].hand)
    s = _run(s)
    assert len(s.players[0].hand) == before + 1, "誘発済みのスキルが解決されていない（800.4 違反）"


# --- B-4: 誘発時に成立していなければ積まれない（FAQ 47/48・800.5.3）--------

def test_a_skill_whose_condition_is_unmet_at_trigger_time_is_not_queued():
    """FAQ 47/48・800.5.3: 判定は**誘発した時点**である。

    ダメージを与えた時点でリーダーがアンコでなければ、`BP01-060` は**誘発しない**。
    そのあとリーダーがアンコになっても解決されない。
    v0.14 までは積む時に条件を見ていなかったので、**あとから成立すると解決していた**。
    """
    s = _state()
    _anko_board(s)
    # リーダーをツバキにしてから誘発させる（条件を満たさない）
    s.players[0].slots[0], s.players[0].slots[1] = s.players[0].slots[1], s.players[0].slots[0]
    s.players[0].action_area = ["BP01-060"]
    E._queue_fire_on_card(s, Timing.ON_DAMAGE_DEALT, 0, "action", "BP01-060")
    assert s.pending_triggers == [], "誘発時点で条件を満たしていないのに積まれた"

    # そのあとリーダーがアンコに戻っても、もう誘発しない
    s.players[0].slots[0], s.players[0].slots[1] = s.players[0].slots[1], s.players[0].slots[0]
    before = len(s.players[0].hand)
    s = _run(s)
    assert len(s.players[0].hand) == before, "誘発していないスキルが解決された（FAQ 47/48 違反）"


def test_the_leader_only_prefix_is_still_judged_at_trigger_time():
    """FAQ 47 そのもの: 【リーダー】前置も**誘発した時点**で判定する。

    ここは v0.14 でも正しく動いていた（積む時に `leader_only` を見ていた）。
    条件の判定を誘発時点へ移したあとも壊れていないことを固定する。
    """
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005"])   # リーダーはツバキ
    s.players[0].slots[1] = CharaSlot(stack=["BP01-033"])   # 散華 Lv0（【リーダー】【対抗】）
    s.players[1].slots[0] = CharaSlot(stack=["SD01-002"])
    E._queue_fire_on_card(s, Timing.CLASH, 0, "chara", "BP01-033")
    assert s.pending_triggers == [], "バックに居る散華の【リーダー】スキルが誘発した"


# --- 条件の読み替え: 「このカード」を積む時点でも引けること -------------------

def test_entered_turn_condition_works_at_trigger_time():
    """`entered_turn_is_not_current`（`BP01-011` アンコ Lv2・u3）が誘発時点でも判定できること。

    この条件は「**このカード**がこのターン以外に登場した場合」で、v0.14 までは
    `pending_effect["card"]`（＝解決中のカード）から「このカード」を引いていた。
    **積む時点では `pending_effect` はまだそのスキルのものではない**ので、
    条件の判定を誘発時点へ移すにあたり、スキルの載っているカードを**明示的に渡す**形に直した。

    ここでは「このターンに登場した」ので条件を満たさず、誘発しないことを固定する。
    """
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-015", "BP01-013", "BP01-011"])
    s.players[1].slots[0] = CharaSlot(stack=["SD01-002"])
    s.slot_entered_turn[0][0] = s.turn_no           # このターンに登場した
    E._queue_fire_on_card(s, Timing.TURN_END, 0, "chara", "BP01-011")
    assert s.pending_triggers == [], "このターン登場なのに誘発した"

    # 前のターンに登場していれば誘発する
    s2 = _state()
    s2.players[0].slots[0] = CharaSlot(stack=["BP01-015", "BP01-013", "BP01-011"])
    s2.players[1].slots[0] = CharaSlot(stack=["SD01-002"])
    s2.slot_entered_turn[0][0] = s2.turn_no - 1
    E._queue_fire_on_card(s2, Timing.TURN_END, 0, "chara", "BP01-011")
    assert s2.pending_triggers, "前のターン登場なのに誘発しない"
