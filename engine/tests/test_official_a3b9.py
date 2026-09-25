# -*- coding: utf-8 -*-
"""公式ルール再照合 A-3 / B-9 — 処理待ちの解決順と、対抗で出せないときの手札公開。

## A-3 同時に誘発したスキルの解決順はプレイヤーが選ぶ（公式 700.1.2/.3・603.1.2.2.2）

公式 700.1.2 は「ターンプレイヤーは、自分の処理待ち状態のスキルを **1 つ選び**、
そのスキルの効果を解決します」と定め、700.1.3 が非ターンプレイヤーについて同じことを定める。
603.1.2.2.2 は「複数のカードに複数の【レベルアップ】スキルがある場合は、
**この時点ですべて誘発します**」と明記する。

v0.15 までの実装は、外側の待ち行列 `pending_skills` にだけ順序選択（A-7）を持ち、
効果の途中で誘発したものを積む**割り込みの待ち行列 `pending_triggers` は `pop(0)` の固定順**
だった。ツバキは【レベルアップ】を持つカードを 3 枚持ち（`BP01-003`・`BP01-001`・`BP01-002`）、
§6.3-3 が同レベルの重ね置きを認める（u21）ので、**下になった 2 枚が同時に誘発する**。
固定順で解くのは公式に反する。

## B-9 対抗で出せないターンプレイヤーは手札をすべて公開する（公式 604.1.1.2 後段）

> ターンプレイヤーの手札に使用条件を満たすアクションカードが存在せず、アクションエリアに
> カードを置くことができない場合、ターンプレイヤーは**自身の手札をすべて公開し**、
> 使用条件を満たすアクションカードが手札に存在しないことを非ターンプレイヤーに確認させます。

**公開の時点は 604.1.1.3（非ターンプレイヤーが置く）より前である。**条文の番号がその順序を定める。
実装では、ターンプレイヤーが出せないことは**手札から決まる**（そこに選択は無い）ので、
提出を集める前に公開して構わない——対抗ステップの同時手番の構造を壊さずに公式の順序を満たせる。

公開は `peeked_opp_hand`（スキャンで既にある仕組み）に流し込む。
`observe` は覗いた時点のスナップショットと現在の手札の積を返す（D-023）ので、
公開したあとに手札が動けば、知られたままになるのは残っているカードだけになる。

準拠版: rules_draft **v0.16** ／ engine v0.1 ／ D-092（R-3・R-13）・D-099。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
for _p in (_ROOT, os.path.join(_ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from meicho import engine as E                                   # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402


# ---------------------------------------------------------------------------
# 共通の下ごしらえ
# ---------------------------------------------------------------------------

def _state() -> GameState:
    s = GameState(seed=1)
    s.players = [PlayerState(), PlayerState()]
    s.turn_no = 3
    s.turn_player = 0
    s.phase = Phase.ACTION
    for pi in (0, 1):
        s.players[pi].action_deck = ["SD01-007"] * 10
        s.players[pi].slots[0] = CharaSlot(stack=["SD01-002"])
    return s


def _tsubaki_stack(s: GameState, pi: int = 0) -> None:
    """ツバキ Lv0/Lv1/Lv2 の上に、もう 1 枚の Lv2 を重ねた直後の形（u21・§6.3-3）。

    一番上（`BP01-002`）が「いま置かれたカード」、その下の `BP01-001`（Lv2）と
    `BP01-003`（Lv1）が**どちらも【レベルアップ】を持つ**。603.1.2.2.2 の場面である。
    """
    s.players[pi].slots[0] = CharaSlot(
        stack=["BP01-005", "BP01-003", "BP01-001", "BP01-002"])


# ---------------------------------------------------------------------------
# A-3 割り込みの待ち行列の解決順
# ---------------------------------------------------------------------------

def test_two_simultaneous_levelup_triggers_offer_an_order_choice():
    """下になったカード 2 枚の【レベルアップ】が同時に誘発したら順序を選ばせる（700.1.2）。"""
    s = _state()
    _tsubaki_stack(s)
    E._queue_levelup_triggers(s, 0, 0)
    # BP01-001（下・Lv2）と BP01-003（さらに下・Lv1）の 2 件が積まれている。
    assert len(s.pending_triggers) == 2
    E._pump(s)
    ch = s.pending_choices[0]
    assert ch["kind"] == "order"
    assert ch["player"] == 0
    assert ch["queue"] == "pending_triggers"
    assert {o["card"] for o in ch["options"]} == {"BP01-001", "BP01-003"}


def test_the_order_choice_resolves_the_chosen_one_first():
    """選んだほうが先に解決に入る。"""
    s = _state()
    _tsubaki_stack(s)
    E._queue_levelup_triggers(s, 0, 0)
    E._pump(s)
    ch = s.pending_choices[0]
    # BP01-003 の【レベルアップ】は「〜してもよい」なので、選ぶと use_optional が出る。
    idx = next(o["index"] for o in ch["options"] if o["card"] == "BP01-003")
    E._apply_choice(s, {0: {"type": "resolve", "index": idx}})
    E._pump(s)
    nxt = s.pending_choices[0]
    assert nxt["kind"] == "use_optional"
    assert nxt["card"] == "BP01-003"
    # 選ばなかったほうは待ち行列に残っている。
    assert [r[2] for r in s.pending_triggers] == ["BP01-001"]


def test_a_single_pending_trigger_is_not_asked():
    """1 件しか誘発していないときは選択を挟まない（従来どおり）。"""
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005", "BP01-003"])
    s.players[0].chara_deck = ["BP01-001"]
    E._queue_levelup_triggers(s, 0, 0)
    assert len(s.pending_triggers) == 1
    E._pump(s)
    assert all(c["kind"] != "order" for c in s.pending_choices)


def test_the_order_choice_groups_only_the_leading_player():
    """順序を選ぶのは先頭のプレイヤーのぶんだけ（700.1.2 → 700.1.3 の順）。"""
    s = _state()
    _tsubaki_stack(s)
    _tsubaki_stack(s, 1)
    E._queue_levelup_triggers(s, 1, 0)      # 先に非ターンプレイヤーぶんを積む
    E._queue_levelup_triggers(s, 0, 0)
    assert len(s.pending_triggers) == 4
    E._pump(s)
    ch = s.pending_choices[0]
    assert ch["kind"] == "order"
    assert ch["player"] == 1
    assert len(ch["options"]) == 2


def test_the_order_choice_reuses_the_existing_choice_kind():
    """符号化を動かさないために、既存の `order` を使い回す（新しい種類を足さない）。

    `CHOICE_KINDS` が増えると `ENCODING_VERSION` が上がり、学習済みネットが全部壊れる。
    A-3 は**決定の並び**を変えるだけで、**行動と観測の語彙は変えない**。
    """
    from meicho.encode import ACT_DIM, CHOICE_KINDS, ENCODING_VERSION, OBS_DIM, OBS_DIM_V5
    # D-124: 版は 1C-c（観測の末尾に信念の要約を足した）で 6 になった。A-3 が守る「選択の語彙」の部分
    # （v5 の形と行動の次元）は変わっていない
    assert ENCODING_VERSION == 6
    assert (OBS_DIM_V5, ACT_DIM) == (1825, 317) and OBS_DIM == 1923
    assert CHOICE_KINDS.count("order") == 1
    assert not any(k.startswith("order_") for k in CHOICE_KINDS)


def test_the_outer_queue_still_asks_the_same_way():
    """外側の待ち行列（A-7）の順序選択は従来どおり動く。"""
    s = _state()
    s.pending_skills = [[0, "chara", "BP01-001", 0], [0, "chara", "BP01-002", 0]]
    E._pump(s)
    ch = s.pending_choices[0]
    assert ch["kind"] == "order"
    assert ch["queue"] == "pending_skills"
    assert len(ch["options"]) == 2


# ---------------------------------------------------------------------------
# B-9 対抗で出せないターンプレイヤーの手札公開
# ---------------------------------------------------------------------------

def _clash(s: GameState) -> None:
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]


def test_turn_player_with_no_usable_card_reveals_the_whole_hand():
    """出せないターンプレイヤーの手札は、対抗の提出を集める前に相手へ公開される。"""
    s = _state()
    s.players[0].hand = ["SD01-016", "SD01-021"]
    s.players[0].concerto = []                     # 協奏が空なのでコストを払えない
    s.players[1].hand = ["SD01-007"]
    s.players[1].concerto = ["SD01-007"] * 3
    _clash(s)
    assert E.legal_actions(s, 0) == [{"type": "pass"}]
    E._pump(s)
    assert s.peeked_opp_hand[1] == ["SD01-016", "SD01-021"]
    assert E.observe(s, 1)["opp"]["hand_known"] == sorted(["SD01-016", "SD01-021"])


def test_the_reveal_happens_before_the_non_turn_player_submits():
    """公開の時点は 604.1.1.3 より前＝まだ誰も提出していない時点で見えている。"""
    s = _state()
    s.players[0].hand = ["SD01-016"]
    s.players[0].concerto = []
    s.players[1].hand = ["SD01-007"]
    s.players[1].concerto = ["SD01-007"] * 3
    _clash(s)
    E._pump(s)
    assert s.pending_submission == [None, None]     # まだ誰も出していない
    assert E.observe(s, 1)["opp"]["hand_known"] == ["SD01-016"]


def test_no_reveal_when_the_turn_player_can_submit():
    """出せるなら公開しない（公開は「置けない場合」の処理である）。"""
    s = _state()
    s.players[0].hand = ["SD01-007"]
    s.players[0].concerto = ["SD01-007"] * 3
    s.players[1].hand = ["SD01-007"]
    s.players[1].concerto = ["SD01-007"] * 3
    _clash(s)
    E._pump(s)
    assert s.peeked_opp_hand[1] is None
    assert E.observe(s, 1)["opp"]["hand_known"] == []


def test_no_reveal_for_the_non_turn_player():
    """非ターンプレイヤーは置かなくてよい（604.1.1.3）ので公開の対象ではない。"""
    s = _state()
    s.players[0].hand = ["SD01-007"]
    s.players[0].concerto = ["SD01-007"] * 3
    s.players[1].hand = ["SD01-016"]
    s.players[1].concerto = []                     # 非ターンプレイヤーが出せない
    _clash(s)
    E._pump(s)
    assert s.peeked_opp_hand[0] is None


def test_the_reveal_is_a_snapshot_intersected_with_the_current_hand():
    """公開後に手札が動けば、知られたままなのは残っているカードだけ（D-023 と同じ扱い）。"""
    s = _state()
    s.players[0].hand = ["SD01-016", "SD01-021"]
    s.players[0].concerto = []
    s.players[1].hand = []
    _clash(s)
    E._pump(s)
    assert E.observe(s, 1)["opp"]["hand_known"] == sorted(["SD01-016", "SD01-021"])
    s.players[0].hand.remove("SD01-016")
    assert E.observe(s, 1)["opp"]["hand_known"] == ["SD01-021"]


def test_the_reveal_never_loses_earlier_scan_knowledge():
    """先にスキャンで覗いていても、公開のほうが広いので情報は減らない。"""
    s = _state()
    s.players[0].hand = ["SD01-016", "SD01-021", "SD01-022"]
    s.players[0].concerto = []
    s.players[1].hand = []
    s.peeked_opp_hand[1] = ["SD01-016"]            # 先にスキャンで 1 枚だけ見ていた
    _clash(s)
    E._pump(s)
    known = E.observe(s, 1)["opp"]["hand_known"]
    assert known == sorted(["SD01-016", "SD01-021", "SD01-022"])
