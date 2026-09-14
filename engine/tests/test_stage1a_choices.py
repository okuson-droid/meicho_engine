# -*- coding: utf-8 -*-
"""段階1A — 自動選択を Python の合法手へ移したことの回帰検査（D-087）。"""

from meicho import engine as E
from meicho.state import CharaSlot, GameState, Phase, PlayerState


def _state() -> GameState:
    s = GameState(seed=1)
    s.players = [PlayerState(), PlayerState()]
    s.turn_no = 3
    s.turn_player = 0
    s.phase = Phase.ACTION
    for p in s.players:
        p.action_deck = ["SD01-007"] * 10
        p.slots[0] = CharaSlot(stack=["SD01-001"])
    return s


def _effect(s: GameState, op: str, prm: dict, owner: int = 0) -> GameState:
    s.pending_effect = {
        "owner": owner, "card": None, "card_kind": "action",
        "ops": [[op, dict(prm)]],
    }
    E._pump(s)
    return s


def _choose(s: GameState, **want) -> GameState:
    pi = s.pending_choices[0]["player"]
    act = next(a for a in E.legal_actions(s, pi)
               if all(a.get(k) == v for k, v in want.items()))
    return E.apply(s, {pi: act})


def test_setup_has_all_six_ordered_placements_and_old_form_keeps_name_order():
    s = _state()
    s.phase = Phase.SETUP_CHARA
    charas = ["BP01-005", "BP01-010", "BP01-015"]  # ツバキ／ショアキーパー／アンコ Lv0
    for p in s.players:
        p.slots = [CharaSlot(), CharaSlot(), CharaSlot()]
        p.chara_deck = list(charas)

    acts = E.legal_actions(s, 0)
    assert len(acts) == 6
    assert len({(a["leader"], *a["backs"]) for a in acts}) == 6

    # 新形式ではバック順を選べる。
    a0 = next(a for a in acts if a["leader"] == "アンコ"
              and a["backs"] == ["ツバキ", "ショアキーパー"])
    a1 = next(a for a in E.legal_actions(s, 1) if a["leader"] == "アンコ")
    u = E.apply(s, {0: a0, 1: a1})
    assert [E._leader_name(u, 0),
            E.CHARA_CARDS[u.players[0].slots[1].stack[-1]].name,
            E.CHARA_CARDS[u.players[0].slots[2].stack[-1]].name] == [
                "アンコ", "ツバキ", "ショアキーパー"]

    # 後方互換の旧形式は従来どおり名前順。
    v = E.apply(s, {0: {"type": "setup", "leader": "アンコ"},
                    1: {"type": "setup", "leader": "アンコ"}})
    assert [E.CHARA_CARDS[v.players[0].slots[i].stack[-1]].name for i in (1, 2)] \
        == sorted(["ショアキーパー", "ツバキ"])


def test_cost_payment_chooses_a_public_concerto_card_and_deduplicates_copies():
    s = _state()
    s.players[0].concerto = ["SD01-007", "SD01-007", "SD01-009"]
    assert E._queue_pay_cost(s, 0, 1)
    E._pump(s)
    acts = E.legal_actions(s, 0)
    assert [a["card"] for a in acts] == ["SD01-007", "SD01-009"]
    s = _choose(s, type="choose_card", card="SD01-009")
    assert s.players[0].concerto == ["SD01-007", "SD01-007"]
    assert s.players[0].trash == ["SD01-009"]


def test_opponent_concerto_target_is_chosen_by_effect_owner():
    s = _state()
    s.players[1].concerto = ["SD01-007", "SD01-009"]
    _effect(s, "opp_concerto_to_trash", {"count": 1})
    assert s.pending_choices[0]["player"] == 0
    s = _choose(s, type="choose_card", card="SD01-009")
    assert s.players[1].concerto == ["SD01-007"]
    assert s.players[1].trash == ["SD01-009"]


def test_opponent_trash_to_bottom_can_stop_at_zero_or_choose_order():
    base = _state()
    base.players[1].trash = ["SD01-007", "SD01-009", "SD01-014"]
    _effect(base, "opp_trash_to_deck_bottom", {"count": 2})
    stopped = _choose(base, type="stop")
    assert stopped.players[1].trash == ["SD01-007", "SD01-009", "SD01-014"]

    s = _state()
    s.players[1].trash = ["SD01-007", "SD01-009", "SD01-014"]
    _effect(s, "opp_trash_to_deck_bottom", {"count": 2})
    s = _choose(s, type="choose_card", card="SD01-014")
    s = _choose(s, type="choose_card", card="SD01-009")
    assert s.players[1].trash == ["SD01-007"]
    assert s.players[1].action_deck[-2:] == ["SD01-014", "SD01-009"]


def test_trash_recovery_respects_filter_and_destination():
    s = _state()
    s.players[0].trash = ["SD01-007", "SD01-009", "SD01-014"]
    _effect(s, "trash_to_hand", {"color": "red", "count": 1})
    acts = E.legal_actions(s, 0)
    assert all(E.ACTION_CARDS[a["card"]].color.value == "red" for a in acts)
    chosen = acts[-1]
    s = E.apply(s, {0: chosen})
    assert s.players[0].hand == [chosen["card"]]


def test_effect_levelup_offers_same_and_next_levels_and_named_level_limits_it():
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-014"])  # アンコ Lv1
    s.players[0].chara_deck = ["BP01-013", "BP01-011", "BP01-012"]
    _effect(s, "levelup_by_effect", {"name": "アンコ"})
    acts = E.legal_actions(s, 0)
    assert {E.CHARA_CARDS[a["card"]].level for a in acts} == {1, 2}
    s = _choose(s, type="choose_card", card="BP01-013")
    assert s.players[0].slots[0].stack[-1] == "BP01-013"

    t = _state()
    t.players[0].slots[0] = CharaSlot(stack=["BP01-014"])
    t.players[0].chara_deck = ["BP01-013", "BP01-011", "BP01-012"]
    _effect(t, "levelup_by_effect", {"name": "アンコ", "level": 2})
    assert {a["card"] for a in E.legal_actions(t, 0)} == {"BP01-011", "BP01-012"}


def test_conditional_wrappers_do_not_bypass_the_new_choices():
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005"])  # ツバキ Lv0
    s.players[0].chara_deck = ["BP01-003", "BP01-004"]
    s.pending_ctx = {"switched": ["ツバキ"]}
    s.pending_shared_ctx = True
    _effect(s, "levelup_by_effect_if_switched", {"name": "ツバキ"})
    assert s.pending_choices[0]["kind"] == "levelup_by_effect"
    assert {a["card"] for a in E.legal_actions(s, 0)} == {"BP01-003", "BP01-004"}

    t = _state()
    t.players[0].trash = ["SD01-007", "SD01-009"]
    t.pending_ctx = {"switched": ["ツバキ"]}
    t.pending_shared_ctx = True
    _effect(t, "trash_to_hand_if_switched", {"name": "ツバキ", "count": 1})
    assert t.pending_choices[0]["kind"] == "zone_card"


def test_pay_then_return_waits_for_the_chosen_concerto_card():
    s = _state()
    source = "BP01-069"
    s.players[0].action_area = [source]
    s.players[0].concerto = ["SD01-007", "SD01-009"]
    s.pending_effect = {
        "owner": 0, "card": source, "card_kind": "action",
        "ops": [["pay_cost_return_self_to_hand", {"cost": 1}]],
    }
    E._pump(s)
    assert s.pending_choices[0]["kind"] == "pay_cost_card"
    s = _choose(s, type="choose_card", card="SD01-009")
    assert source in s.players[0].hand and source not in s.players[0].action_area
    assert s.players[0].trash == ["SD01-009"]
