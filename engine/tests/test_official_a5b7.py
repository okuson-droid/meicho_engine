# -*- coding: utf-8 -*-
"""公式ルール再照合 A-5 / B-7 — Lv.0 の枚数と、0 ダメージに削られたときの旗。

## A-5 各キャラの Lv.0 はちょうど 1 枚（公式 101.1.1.1）

公式 101.1.1.1 はキャラデッキに入れられる各キャラのレベル 0 のカードを
**ちょうど 1 枚**に限る。v0.15 までの `GameConfig.validate` は
「Lv.0 が **1 枚以上** あること」しか見ていなかった（D-092 の A-5）。

**現プールでは挙動は 1 手も変わらない**——Lv.0 は 9 名それぞれ 1 枚しか存在しないので、
2 枚入れようとしても同カード番号の重複が先に弾かれる。守っているのは
「同名の Lv.0 が 2 種類できたときに、準備の配置が暗黙にどちらかを選んでしまう」ことである。
`initial_state` の準備は `{名前: カード番号}` の辞書で Lv.0 を引くので、
同名が 2 枚あると**あとの 1 枚が黙って勝つ**。そこにも検査を置く。

## B-7 0 ダメージに削られたら「各ターン最初に受けるダメージ」の旗は消費しない（公式 901.2.1）

> 901.2.1 「0 ダメージを受ける」場合、そのプレイヤーはダメージを受けていないとして扱います。

`BP01-002`（ツバキ Lv2）の【リーダー】常在「各ターン、自分が最初に受けるダメージ −1」で
1 ダメージが 0 になったとき、v0.15 までの `_damage` は**旗を立ててから** 0 以下かを見て戻っていた。
公式では「受けていない」のだから旗は立たない。**次に来る本物のダメージが −1 を受ける**のが正しい。

準拠版: rules_draft **v0.17** ／ engine v0.1 ／ D-092（R-5・R-11）・D-100。
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
from meicho.cards import CHARA_CARDS, CharaCard                   # noqa: E402
from meicho.engine import GameConfig                              # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402


def _deck(name: str) -> dict:
    import json
    with open(os.path.join(_ROOT, "decklists", f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# A-5 Lv.0 はちょうど 1 枚
# ---------------------------------------------------------------------------

def test_the_shipped_pools_still_validate():
    """SD001・SD02・BP01 の仮デッキは従来どおり通る（挙動は変わらない）。"""
    for name in ("SD001", "SD02", "K_smoke_ANKO", "K_smoke_TSUBAKI", "K_smoke_SANGE"):
        d = _deck(name)
        GameConfig(chara_decks=[d["chara_deck"]] * 2,
                   action_decks=[d["action_deck"]] * 2).validate()


def test_every_lv0_name_is_unique_in_the_real_pool():
    """現プールには同名の Lv.0 が 2 枚無い＝A-5 は今日の対局を変えない。"""
    names = [c.name for c in CHARA_CARDS.values() if c.level == 0]
    assert len(names) == len(set(names))


def test_validate_rejects_a_second_lv0_of_the_same_name():
    """同名の Lv.0 が 2 種類あるキャラデッキは弾く（101.1.1.1）。"""
    CHARA_CARDS["TEST-C-DUP-LV0"] = CharaCard(
        card_id="TEST-C-DUP-LV0", name="ツバキ", level=0)
    d = _deck("K_smoke_TSUBAKI")
    # 15 枚上限（§3.1）に触れないよう、Lv.0 でない 1 枚と入れ替える。
    cd = [c for c in d["chara_deck"] if c != "BP01-004"] + ["TEST-C-DUP-LV0"]
    cfg = GameConfig(chara_decks=[cd, list(d["chara_deck"])],
                     action_decks=[d["action_deck"]] * 2)
    with pytest.raises(AssertionError, match="ちょうど1枚"):
        cfg.validate()


def test_setup_refuses_an_ambiguous_lv0():
    """準備の配置も、同名 Lv.0 が 2 枚あったら黙って片方を選ばない。"""
    CHARA_CARDS["TEST-C-DUP-LV0"] = CharaCard(
        card_id="TEST-C-DUP-LV0", name="ツバキ", level=0)
    d = _deck("K_smoke_TSUBAKI")
    s = GameState(seed=1, players=[PlayerState(), PlayerState()])
    s.phase = Phase.SETUP_CHARA
    for pi in (0, 1):
        s.players[pi].chara_deck = ([c for c in d["chara_deck"] if c != "BP01-004"]
                                    + ["TEST-C-DUP-LV0"])
        s.players[pi].action_deck = list(d["action_deck"])
    names = sorted({CHARA_CARDS[c].name for c in s.players[0].chara_deck
                    if CHARA_CARDS[c].level == 0})
    act = {"type": "setup", "leader": names[0],
           "backs": [n for n in names if n != names[0]]}
    with pytest.raises(AssertionError, match="Lv.0"):
        E.apply(s, {0: act, 1: act})


# ---------------------------------------------------------------------------
# B-7 0 ダメージと旗
# ---------------------------------------------------------------------------

def _tsubaki_lv2_leader(pi: int = 0) -> GameState:
    """pi のリーダーを `BP01-002`（ツバキ Lv2・「最初に受けるダメージ −1」）にする。"""
    s = GameState(seed=1, players=[PlayerState(), PlayerState()])
    s.turn_no = 3
    s.turn_player = 1 - pi
    s.phase = Phase.ACTION
    s.players[pi].slots[0] = CharaSlot(
        stack=["BP01-005", "BP01-003", "BP01-002"])
    s.players[1 - pi].slots[0] = CharaSlot(stack=["SD01-002"])
    for q in (0, 1):
        s.players[q].action_deck = ["SD01-007"] * 10
    return s


def test_the_modifier_is_actually_on_the_board():
    """下ごしらえの確認: −1 の常在が効いている。"""
    s = _tsubaki_lv2_leader()
    assert E._first_damage_taken_mod(s, 0) == -1


def test_zero_damage_does_not_consume_the_flag():
    """1 ダメージが −1 で 0 になったら、旗は立たない（901.2.1・B-7）。"""
    s = _tsubaki_lv2_leader()
    E._damage(s, 0, 1)
    assert s.players[0].life == 20
    assert s.first_damage_taken_this_turn[0] is False
    assert s.damaged_this_turn[0] is False


def test_the_reduction_is_still_available_after_a_zero():
    """0 に削られたあと、**次の本物のダメージが −1 を受ける**。ここが直しの本体である。"""
    s = _tsubaki_lv2_leader()
    E._damage(s, 0, 1)            # 0 になる。旗は立たない。
    E._damage(s, 0, 3)            # −1 されて 2
    assert s.players[0].life == 18
    assert s.first_damage_taken_this_turn[0] is True


def test_real_damage_consumes_the_flag_once():
    """本物のダメージなら旗を立て、同じターンの 2 回目は軽減されない。"""
    s = _tsubaki_lv2_leader()
    E._damage(s, 0, 3)
    assert s.players[0].life == 18
    assert s.first_damage_taken_this_turn[0] is True
    E._damage(s, 0, 3)
    assert s.players[0].life == 15


def test_no_modifier_means_the_old_behaviour():
    """軽減を持たない席では従来どおり（SD001/SD02 はこちら）。"""
    s = _tsubaki_lv2_leader()
    E._damage(s, 1, 2)
    assert s.players[1].life == 18
    assert s.first_damage_taken_this_turn[1] is True


def test_zero_base_damage_never_touches_the_flag():
    """もともと 0 以下のダメージは、軽減の有無にかかわらず何もしない。"""
    s = _tsubaki_lv2_leader()
    E._damage(s, 0, 0)
    assert s.first_damage_taken_this_turn[0] is False
    assert s.players[0].life == 20
