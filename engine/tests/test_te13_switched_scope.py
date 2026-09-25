# -*- coding: utf-8 -*-
"""TE-13 — 【切り替え】は**切り替えられたキャラ**だけが誘発する（D-134・rules v0.19 §7）。

## 何を守るか

公式総合ルール 603.1.2.1.1「キャラを切り替えた後、**切り替わったキャラカード**の【切り替え】スキルが誘発します」、
906.2「切り替えによって位置が変更されたキャラは、『切り替えられたキャラ』と呼びます」、
913.9.1「このアイコンを持つスキルは、**このスキルを持つキャラカードが切り替えられた時**に誘発します」。

切り替えは常にリーダーとバック 1 体の入れ替えなので、誘発するのは**入れ替わった 2 枠**だけである。
v0.18 までの実装は `_queue_fire_nested(s, Timing.SWITCHED, [owner])` で**その席の全キャラ枠**を拾っており、
入れ替えに関わっていないもう 1 体のバックの【切り替え】まで誘発していた
（アプリの持ち場からの報告 TE-13・2026-09-24。マスターが知人との対戦で見つけた）。

重なりの下のカードは従来どおり拾う——キャラカードは重ねて置かれたすべてのカードのスキルを持ち
（rules_draft §6.3-3）、枠ごと位置が変わるので「切り替えられたキャラ」に含まれる。
【登場】のような「一番上だけ」の限定（公式 603.1.2.2.1・908）は【切り替え】の条文には無い。

## 作り方

`tests/test_bp01_k2.py` と同じく盤面を直に組む。`BP01-008` ショアキーパー Lv1
「【切り替え】カード1枚を引いてもよい。そうした場合、自分の手札1枚を捨てる。」が
現行プールで【切り替え】を持つ唯一のカードである（検査で固定する）。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
for _p in (_ROOT, os.path.join(_ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from meicho import engine as E                                   # noqa: E402
from meicho.cards import ACTION_CARDS, CHARA_CARDS, Timing       # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402

SHOREKEEPER_LV1 = "BP01-008"


def _state(**kw) -> GameState:
    s = GameState(seed=1)
    s.players = [PlayerState(), PlayerState()]
    s.turn_no = 3
    s.turn_player = 0
    s.phase = Phase.ACTION
    for pi in (0, 1):
        s.players[pi].action_deck = ["SD01-007"] * 10
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _put(s: GameState, pi: int, slot: int, *chara_ids: str) -> None:
    s.players[pi].slots[slot] = CharaSlot(stack=list(chara_ids))


def _board(sk_slot: int) -> GameState:
    """P0: リーダー BP01-018・バック 1 BP01-024・バック 2 BP01-018 のうち、`sk_slot` だけ BP01-008。"""
    s = _state()
    ids = ["BP01-018", "BP01-024", "BP01-018"]
    ids[sk_slot] = SHOREKEEPER_LV1
    for si, cid in enumerate(ids):
        _put(s, 0, si, cid)
    _put(s, 1, 0, "SD01-001")
    return s


def _switched_refs(s: GameState) -> list:
    return [r for r in s.pending_triggers if E._deref_skill(r).timing == Timing.SWITCHED]


def _switched_choices(s: GameState) -> list:
    return [c for c in s.pending_choices if c.get("card") == SHOREKEEPER_LV1]


def test_shorekeeper_lv1_is_the_only_switched_card():
    """【切り替え】を持つのは現行プールで `BP01-008` だけ。増えたらこのファイルの前提を見直す。"""
    chara = sorted(c for c, card in CHARA_CARDS.items()
                   for sk in card.skills if sk.timing == Timing.SWITCHED)
    action = sorted(c for c, card in ACTION_CARDS.items()
                    for sk in card.skills if sk.timing == Timing.SWITCHED)
    assert chara == [SHOREKEEPER_LV1]
    assert action == []


# --- 行動としての切り替え（§6.3-2・公式 603.1.2.1）-------------------------------

def test_action_switch_does_not_fire_the_uninvolved_back():
    """TE-13 の再現そのもの。リーダーとバック 1 を入れ替えても、バック 2 の【切り替え】は誘発しない。"""
    s = _board(sk_slot=2)
    s = E.apply(s, {0: {"type": "switch", "back": 1}})
    assert [st.stack for st in s.players[0].slots] == [["BP01-024"], ["BP01-018"], [SHOREKEEPER_LV1]]
    assert not _switched_choices(s), s.pending_choices
    assert not _switched_refs(s)


@pytest.mark.parametrize("sk_slot,back", [(1, 1), (0, 1), (2, 2), (0, 2)])
def test_action_switch_fires_both_directions(sk_slot, back):
    """入れ替わった側なら、バック→リーダーでもリーダー→バックでも誘発する（§7・D-024 と同じ読み）。"""
    s = _board(sk_slot=sk_slot)
    s = E.apply(s, {0: {"type": "switch", "back": back}})
    assert len(_switched_choices(s)) == 1, s.pending_choices


def test_action_switch_fires_a_buried_card_in_a_moved_slot():
    """重なりの下にある `BP01-008` も、その枠が入れ替わったなら誘発する（§6.3-3・枠ごと動く）。"""
    s = _state()
    _put(s, 0, 0, "BP01-018")
    _put(s, 0, 1, SHOREKEEPER_LV1, "BP01-007")        # Lv1 の上に Lv2
    _put(s, 0, 2, "BP01-024")
    _put(s, 1, 0, "SD01-001")
    s = E.apply(s, {0: {"type": "switch", "back": 1}})
    assert len(_switched_choices(s)) == 1, s.pending_choices


def test_action_switch_does_not_fire_a_buried_card_in_the_uninvolved_slot():
    s = _state()
    _put(s, 0, 0, "BP01-018")
    _put(s, 0, 1, "BP01-024")
    _put(s, 0, 2, SHOREKEEPER_LV1, "BP01-007")
    _put(s, 1, 0, "SD01-001")
    s = E.apply(s, {0: {"type": "switch", "back": 1}})
    assert not _switched_choices(s), s.pending_choices


def test_action_switch_never_fires_the_opponents_card():
    """相手のキャラは位置が変わらない＝誘発しない（v0.18 でもそうだったことの固定）。"""
    s = _board(sk_slot=2)
    _put(s, 1, 0, SHOREKEEPER_LV1)
    _put(s, 1, 1, "BP01-018")
    s = E.apply(s, {0: {"type": "switch", "back": 1}})
    assert not _switched_choices(s), s.pending_choices


# --- 効果による切り替え（switch_leader・switch_leader_to）-----------------------

@pytest.mark.parametrize("sk_slot,expect", [(2, 0), (1, 1), (0, 1)])
def test_effect_switch_leader_fires_only_the_moved_pair(sk_slot, expect):
    s = _board(sk_slot=sk_slot)
    E._apply_op(s, 0, "switch_leader", {"back": 1}, {})
    assert len(_switched_refs(s)) == expect, s.pending_triggers


@pytest.mark.parametrize("sk_slot,expect", [(2, 0), (1, 1), (0, 1)])
def test_named_switch_fires_only_the_moved_pair(sk_slot, expect):
    """名指しの切り替え（u14）。名前で選ばれたバック 1 だけがリーダーと入れ替わる。"""
    s = _board(sk_slot=sk_slot)
    name = CHARA_CARDS[s.players[0].slots[1].stack[-1]].name
    E._apply_op(s, 0, "switch_leader_to", {"name": name}, {})
    assert len(_switched_refs(s)) == expect, s.pending_triggers


def test_no_switch_no_trigger_even_for_the_moved_candidates():
    """切り替え禁止中の効果は何も動かさない＝誘発しない（§7・v0.12 の条文の固定）。"""
    s = _board(sk_slot=1)
    s.leader_switch_forbidden = [True, False]
    E._apply_op(s, 0, "switch_leader", {"back": 1}, {})
    assert not _switched_refs(s)


# --- Python / Rust の毎手一致（ショアキーパーのデッキで）--------------------------

_SK_DECKS = ["ENV_SANGE_SK_TSUBAKI", "ENV_YANG_SK_ANKO"]


def _load_env(name: str) -> dict:
    with open(os.path.join(_ROOT, "decklists", "env", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("deck", _SK_DECKS)
@pytest.mark.parametrize("seed", list(range(12)))
def test_rust_matches_python_with_shorekeeper(seed, deck):
    """`BP01-008` を積んだ環境デッキ（SK 系）で、Python と Rust が毎手・全欄一致すること。

    `test_bp01_k3.py` の毎手一致は仮デッキ 3 種で、ショアキーパーを積んでいない＝【切り替え】を踏まない。
    ここが【切り替え】の Python/Rust 一致の門番である。踏んだ回数は下の検査で数える。
    """
    rs = pytest.importorskip("meicho_rs")
    if "te13_switched_scope" not in rs.features():
        pytest.skip("meicho_rs が TE-13 の直しより前のビルド（再ビルド待ち）")
    from meicho.agents import RandomAgent
    from meicho.cards_export import cards_json
    from meicho.engine import (GameConfig, apply, decision_players, initial_state,
                               legal_actions, outcome)

    rs.load_cards(cards_json())
    d = _load_env(deck)
    config = GameConfig(chara_decks=[d["chara_deck"]] * 2, action_decks=[d["action_deck"]] * 2)
    config.validate()

    def norm(x):
        return json.loads(json.dumps(x, ensure_ascii=False))

    py = initial_state(config, seed)
    rss = rs.initial_state(config.chara_decks, config.action_decks, seed)
    agents = [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)]
    steps = 0
    while outcome(py) is None and py.turn_no <= 200:
        assert norm(json.loads(py.to_json())) == json.loads(rss.to_json()), \
            f"state mismatch deck={deck} seed={seed} step={steps}"
        need = decision_players(py)
        assert list(need) == list(rs.decision_players(rss))
        for pi in (0, 1):
            assert norm(legal_actions(py, pi)) == rs.legal_actions(rss, pi), \
                f"legal_actions P{pi} deck={deck} seed={seed} step={steps}"
        acts = {pi: agents[pi].act(py, pi) for pi in need}
        py = apply(py, acts)
        rss = rs.apply(rss, {pi: norm(a) for pi, a in acts.items()})
        steps += 1
    assert norm(json.loads(py.to_json())) == json.loads(rss.to_json())
    assert outcome(py) == rs.outcome(rss)


def test_the_parity_games_actually_hit_the_case():
    """上の毎手一致が、**入れ替えに関わらないバックに `BP01-008` が居る切り替え**を実際に踏むこと。

    踏まない毎手一致は、直した箇所を 1 度も通らずに通ってしまう。
    """
    from meicho.agents import RandomAgent
    from meicho.engine import GameConfig, apply, decision_players, initial_state, outcome

    hit_uninvolved = hit_involved = 0
    for deck in _SK_DECKS:
        d = _load_env(deck)
        config = GameConfig(chara_decks=[d["chara_deck"]] * 2, action_decks=[d["action_deck"]] * 2)
        for seed in range(12):
            py = initial_state(config, seed)
            agents = [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)]
            while outcome(py) is None and py.turn_no <= 200:
                need = decision_players(py)
                acts = {pi: agents[pi].act(py, pi) for pi in need}
                if py.phase == Phase.ACTION and py.turn_player in acts \
                        and acts[py.turn_player]["type"] == "switch":
                    b = acts[py.turn_player]["back"]
                    other = 3 - b
                    slots = py.players[py.turn_player].slots
                    if SHOREKEEPER_LV1 in slots[other].stack:
                        hit_uninvolved += 1
                    if SHOREKEEPER_LV1 in slots[0].stack or SHOREKEEPER_LV1 in slots[b].stack:
                        hit_involved += 1
                py = apply(py, acts)
    assert hit_uninvolved > 0, "関わらないバックに BP01-008 が居る切り替えを 1 度も踏んでいない"
    assert hit_involved > 0, "BP01-008 が入れ替わる切り替えを 1 度も踏んでいない"
