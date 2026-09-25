# -*- coding: utf-8 -*-
"""公式ルール再照合 A-1 / A-2 — ルールチェック（勝敗条件とデッキリフレッシュ）。

## 何を守るか

公式総合ルール 701 は、ルールチェックを**この順番で**実行すると定める。

- **701.1.1 勝敗条件のチェック**（先）— 701.1.1.1「・いずれかのプレイヤーのライフが 0 になった場合、
  そのプレイヤーは敗北します。・プレイヤーのアクションデッキエリア**および**トラッシュに
  カードが 1 枚もない場合、そのプレイヤーは敗北します。」双方同時なら引き分け（102.2）。
- **701.1.2 デッキリフレッシュチェック**（後）— 701.1.2.1「アクションデッキエリアにカードがない場合、
  トラッシュのすべてのカードを裏向きでアクションデッキエリアに移動し、その後、デッキをシャッフルします。」
  701.1.2.2 は処理の途中で空になった場合も中断してリフレッシュし、処理を再開すると定める。

**順番が大事である。**「デッキだけ空・トラッシュに在り」は敗北にならずリフレッシュされ、
**両方空**で初めて敗北する。

ルールチェックが走る場所は 2 つ。**700.1.1**（処理待ちチェックの先頭）と、
**903.1**「カードを引くとは、…手札に加え、その後、ルールチェックを実行することを指します」。

v0.12 までは (a) デッキ切れ敗北が無く（`_draw` が黙って戻る・D-025）、
(b) リフレッシュがドローの中でしか起きなかった（FAQ 33・46 が要求する解決後のリフレッシュが無い）。

準拠版: rules_draft **v0.14** ／ engine v0.1 ／ D-092（R-1・R-2）・D-095。
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
from meicho.state import DRAW, CharaSlot, GameState, Phase, PlayerState  # noqa: E402


def _state() -> GameState:
    s = GameState(seed=1)
    s.players = [PlayerState(), PlayerState()]
    s.turn_no = 3
    s.turn_player = 0
    s.phase = Phase.ACTION
    for pi in (0, 1):
        s.players[pi].slots[0] = CharaSlot(stack=["SD01-002"])
        s.players[pi].action_deck = ["SD01-007"] * 5
    return s


# --- A-1 勝敗条件（701.1.1.1）------------------------------------------------

def test_empty_deck_and_trash_loses_immediately():
    """701.1.1.1: アクションデッキエリア**および**トラッシュが空なら直ちに敗北。

    v0.12 までは `_draw` が黙って戻り、ライフが 0 になるまで対局が続いていた（D-025）。
    """
    s = _state()
    s.players[0].action_deck = []
    s.players[0].trash = []
    E._rule_check(s)
    assert s.outcome == 1, "空にしたのは P0 なので P1 の勝ち"
    assert s.phase == Phase.GAME_OVER


def test_empty_deck_but_trash_has_cards_does_not_lose():
    """701.1 の**順番**: 勝敗チェックが先だが、条件は「デッキ**および**トラッシュ」である。

    デッキだけ空でトラッシュに在るなら敗北にはならず、701.1.2 でリフレッシュされる。
    """
    s = _state()
    s.players[0].action_deck = []
    s.players[0].trash = ["SD01-007", "SD01-008"]
    E._rule_check(s)
    assert s.outcome is None, "トラッシュに在るのに敗北している"
    assert len(s.players[0].action_deck) == 2, "リフレッシュされていない"
    assert s.players[0].trash == [], "トラッシュが空になっていない"


def test_both_players_out_at_once_is_a_draw():
    """102.2: お互いが同時に敗北条件を満たしたら引き分け。"""
    s = _state()
    for pi in (0, 1):
        s.players[pi].action_deck = []
        s.players[pi].trash = []
    E._rule_check(s)
    assert s.outcome == DRAW
    assert s.phase == Phase.GAME_OVER


def test_life_zero_loses_in_the_same_check():
    """701.1.1.1 の 1 つめの条件。ライフ 0 も同じルールチェックで敗北する。"""
    s = _state()
    s.players[1].life = 0
    E._rule_check(s)
    assert s.outcome == 0


def test_drawing_the_last_card_does_not_lose_while_the_trash_has_cards():
    """903.1「引く」＝手札に加え、**その後ルールチェック**。

    最後の 1 枚を引いてデッキが空になっても、トラッシュに在ればリフレッシュされるだけである。
    """
    s = _state()
    s.players[0].action_deck = ["SD01-007"]
    s.players[0].trash = ["SD01-008", "SD01-009"]
    E._draw(s, 0, 1)
    assert s.outcome is None
    assert len(s.players[0].hand) == 1
    assert len(s.players[0].action_deck) == 2, "引いた後にリフレッシュされていない"


def test_drawing_from_an_empty_deck_with_an_empty_trash_loses():
    """引けないまま続行するのではなく、701.1.1.1 で敗北する。"""
    s = _state()
    s.players[0].action_deck = []
    s.players[0].trash = []
    E._draw(s, 0, 1)
    assert s.outcome == 1
    assert s.players[0].hand == []


# --- A-2 デッキリフレッシュ（701.1.2・FAQ 33・FAQ 46）------------------------

def test_reveal_n_take_matching_refreshes_after_it_resolves():
    """FAQ 33（`BP01-028` 今汐）: 「スキルの効果の処理が解決した後、アクションデッキに
    カードが 1 枚もない場合、デッキリフレッシュを行います。」

    デッキ 2 枚のときに「上から 5 枚を公開」を解決すると、公開できるのは 2 枚だけで
    デッキが空になる。その後リフレッシュされる（トラッシュには振り分けたカードが入っている）。
    """
    s = _state()
    s.players[0].action_deck = ["SD01-007", "SD01-008"]
    s.players[0].trash = []
    s.pending_effect = {"owner": 0, "card": "BP01-028", "card_kind": "chara", "ops": []}
    E._apply_op(s, 0, "reveal_n_take_matching", {"count": 5, "chara": "今汐"}, {})
    E._rule_check(s)
    assert s.outcome is None, "トラッシュに振り分けたカードが在るのに敗北している"
    assert len(s.players[0].action_deck) == 2, "解決後にリフレッシュされていない"
    assert s.players[0].trash == []


def test_search_deck_refreshes_when_the_card_is_not_there():
    """FAQ 46（`BP01-073` 遍く照らす神光）: 「自分のアクションデッキに「龍憑の天舞」が
    ないことを宣言し、デッキリフレッシュを行います。」

    ここでは「デッキが空になった」ではなく「探して見つからなかった」場合でも
    リフレッシュすると読める。**空でなければリフレッシュは起きない**（701.1.2.1 の条件はあくまで
    「アクションデッキエリアにカードがない場合」）ので、この検査はデッキが空のときを見る。
    """
    s = _state()
    s.players[0].action_deck = []
    s.players[0].trash = ["SD01-007", "SD01-008", "SD01-009"]
    s.pending_effect = {"owner": 0, "card": "BP01-073", "card_kind": "action", "ops": []}
    E._apply_op(s, 0, "search_deck", {"card_name": "龍憑の天舞"}, {})
    E._rule_check(s)
    assert s.outcome is None
    assert len(s.players[0].action_deck) == 3, "宣言のあとリフレッシュされていない"
    assert s.players[0].trash == []


def test_refresh_consumes_exactly_one_rng_call():
    """リフレッシュのシャッフルは乱数をちょうど 1 回使う（D-028 の決定性）。"""
    s = _state()
    s.players[0].action_deck = []
    s.players[0].trash = ["SD01-007", "SD01-008", "SD01-009"]
    before = s.rng_calls
    E._rule_check(s)
    assert s.rng_calls == before + 1, f"{before} → {s.rng_calls}"
