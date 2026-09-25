# -*- coding: utf-8 -*-
"""公式ルール再照合 B-1 / B-2 / B-3 — 【登場】と【レベルアップ】の誘発範囲。

## 何を守るか

公式総合ルール 603.1.2.2.1/.2 は、レベルアップの直後に誘発するものをこう分ける。

- **【登場】は「一番上に置かれたカード」だけ**（908.1 の「登場」＝キャラエリアの一番上に移動させる行動。
  908.2 で「下に移動した場合は登場にならない」、908.3 で準備の配置は登場にならない）。
- **【レベルアップ】は「その下に重ねて置かれたカード」だけ**。
  「複数のカードに複数の【レベルアップ】スキルがある場合は、この時点ですべて誘発します」。

v0.12 までの実装は、両方を**そのプレイヤーのキャラエリア全体**（全スロット・全重ねカード）で
列挙していた（B-3）。加えて `rules_draft.md` §7 の【レベルアップ】の定義が
「上に置かれたとき」と公式の逆だった（B-2）。その 2 つが重なって、
`■【登場】/【レベルアップ】…` と 1 段落に 2 つのアイコンを持つカード（BP01 のキャラ Lv1 の 8 枚）が
**1 回のレベルアップで 2 回解決していた**（B-1）。

**B-1 は B-2 と B-3 を直せば自動的に解ける。**1 枚のカードが「一番上」と「その下」に
同時になることはないので、誘発は必ず片方だけである（800.5.3.1 の重複抑制を実装する必要はない・R-9）。

準拠版: rules_draft **v0.13** ／ engine v0.1 ／ D-092（R-7・R-8）・D-094。
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
from meicho.cards import CHARA_CARDS, Timing                      # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402


def _state() -> GameState:
    s = GameState(seed=1)
    s.players = [PlayerState(), PlayerState()]
    s.turn_no = 3
    s.turn_player = 0
    s.phase = Phase.ACTION
    for pi in (0, 1):
        s.players[pi].action_deck = ["SD01-007"] * 10
    return s


def _queued(s: GameState) -> list:
    """割り込みの待ち行列に積まれた (カード番号, タイミング) を並べる。"""
    out = []
    for ref in s.pending_triggers:
        sk = E._deref_skill(ref)
        out.append((ref[2], sk.timing.name))
    return out


# --- B-2: 誘発の主体（上に置いたカード／その下のカード）---------------------

def test_enter_fires_only_for_the_card_just_placed_on_top():
    """603.1.2.2.1: 【登場】は一番上に置かれたカードだけ。

    ツバキ Lv0 → Lv1 (`BP01-003`・【登場】/【レベルアップ】) にレベルアップする。
    **【登場】が 1 回だけ**積まれ、【レベルアップ】は積まれない
    （`BP01-003` は一番上なので「その下」ではない）。下の `BP01-005` は【レベルアップ】を持たない。
    """
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005"])
    s.players[0].chara_deck = ["BP01-003"]
    s.players[0].hand = ["SD01-007"]
    s = E.apply(s, {0: {"type": "levelup", "slot": 0, "card": "BP01-003"}})
    assert _queued(s) == [("BP01-003", "ENTER")], _queued(s)


def test_levelup_fires_only_for_the_cards_underneath():
    """603.1.2.2.2: 【レベルアップ】は下に重ねて置かれたカードだけ。

    ツバキ Lv1 (`BP01-003`) の上に Lv2 (`BP01-001`) を置く。
    `BP01-001` は【登場】を持たないので 603.1.2.2.1 では何も誘発せず、
    **下になった `BP01-003` の【レベルアップ】だけ**が積まれる。
    v0.12 までは置いた `BP01-001` 自身の【レベルアップ】も積まれていた（B-2）。
    """
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005", "BP01-003"])
    s.players[0].chara_deck = ["BP01-001"]
    s.players[0].hand = ["SD01-007", "SD01-007"]
    s = E.apply(s, {0: {"type": "levelup", "slot": 0, "card": "BP01-001"}})
    assert _queued(s) == [("BP01-003", "LEVELUP")], _queued(s)


def test_all_the_levelup_skills_underneath_fire_at_once():
    """603.1.2.2.2 後段「複数のカードに複数の【レベルアップ】スキルがある場合は、この時点ですべて誘発します」。

    ツバキは【レベルアップ】を持つカードを 3 枚持つ（`BP01-003` Lv1 と `BP01-001`/`BP01-002` Lv2）。
    §6.3-3 は同レベルの重ね置きを認める（u21）ので、Lv2 の上にもう 1 枚 Lv2 を置くと
    **下になった 2 枚**の【レベルアップ】が同時に誘発する。

    **この局面は A-3（同時誘発の解決順を選べない）が現に効く場所でもある。**
    順序選択は A-3 の便で足すので、ここでは「2 件とも積まれること」だけを固定し、
    順番は上から下へ（置いたカードのすぐ下が先）という暫定の固定順を書き留める。
    """
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005", "BP01-003", "BP01-001"])
    s.players[0].chara_deck = ["BP01-002"]
    s.players[0].hand = ["SD01-007", "SD01-007"]
    s = E.apply(s, {0: {"type": "levelup", "slot": 0, "card": "BP01-002"}})
    assert _queued(s) == [("BP01-001", "LEVELUP"), ("BP01-003", "LEVELUP")], _queued(s)


# --- B-3: 誘発の範囲（別スロット・埋もれたカードは誘発しない）----------------

def test_a_chara_in_another_slot_does_not_fire():
    """B-3: ほかの枠のキャラの【登場】【レベルアップ】は誘発しない。

    枠 0 のツバキをレベルアップするとき、枠 1 のショアキーパー Lv1 (`BP01-009`・
    【登場】/【レベルアップ】) は**何も誘発しない**。v0.12 までは両方積まれていた。
    """
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005"])
    s.players[0].slots[1] = CharaSlot(stack=["BP01-010", "BP01-009"])
    s.players[0].chara_deck = ["BP01-003"]
    s.players[0].hand = ["SD01-007"]
    s = E.apply(s, {0: {"type": "levelup", "slot": 0, "card": "BP01-003"}})
    assert _queued(s) == [("BP01-003", "ENTER")], _queued(s)


def test_a_buried_card_does_not_fire_enter_again():
    """B-3: 一度埋もれたカードの【登場】は二度と誘発しない（908.2）。

    枠 0 が ツバキ Lv0/Lv1(`BP01-003`) の状態で Lv2 (`BP01-001`) を置く。
    `BP01-003` は**下になった**ので【登場】は誘発せず、【レベルアップ】だけが誘発する。
    """
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005", "BP01-003"])
    s.players[0].chara_deck = ["BP01-001"]
    s.players[0].hand = ["SD01-007", "SD01-007"]
    s = E.apply(s, {0: {"type": "levelup", "slot": 0, "card": "BP01-001"}})
    assert ("BP01-003", "ENTER") not in _queued(s), _queued(s)


# --- B-1: 1 段落 2 アイコンのカードは 1 回しか解決しない ---------------------

@pytest.mark.parametrize("cid", ["BP01-003", "BP01-009", "BP01-013", "BP01-017",
                                 "BP01-020", "BP01-023", "BP01-026", "BP01-032"])
def test_one_paragraph_two_icons_resolves_once_per_levelup(cid):
    """B-1: `■【登場】/【レベルアップ】…` は 1 段落＝1 スキル（800.3）なので解決は 1 回。

    該当は BP01 のキャラ Lv1 の **8 枚**である。実装は【登場】と【レベルアップ】を
    別スキルとして持っているが、**1 枚のカードが「一番上」と「その下」に同時になることはない**ので、
    1 回のレベルアップで誘発するのは必ず片方だけになる。
    800.5.3.1 の重複抑制を別に実装する必要はない（R-9）。
    """
    card = CHARA_CARDS[cid]
    timings = [sk.timing for sk in card.skills]
    assert Timing.ENTER in timings and Timing.LEVELUP in timings, "前提が崩れている"

    lv0 = next(c for c in CHARA_CARDS.values()
               if c.name == card.name and c.level == 0)
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=[lv0.card_id])
    s.players[0].chara_deck = [cid]
    s.players[0].hand = ["SD01-007"] * 3
    s = E.apply(s, {0: {"type": "levelup", "slot": 0, "card": cid}})
    fired = [t for (c, t) in _queued(s) if c == cid]
    assert fired == ["ENTER"], f"{cid}: {_queued(s)}"
