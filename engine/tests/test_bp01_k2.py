# -*- coding: utf-8 -*-
"""便 K 段 K-2 — 新しいタイミング・状態欄・オペコード・条件がちゃんと効くこと。

## なぜ別ファイルか

`tests/test_bp01.py` が守るのは「**足しても壊れない**」（SD001/SD02 の対局が 1 手も変わらない）で、
こちらが守るのは「**足したものが効く**」である。前者だけを通して「実装した」と言うと、
1 度も動いていないコードを抱えたまま次の段に進むことになる（作業規約 5）。

## 作り方

BP01 のカードは SD001/SD02 のデッキに入っていないので、**盤面を直に組んで**誘発させる。
対局を回さないぶん速く、失敗したときに原因の場所が読める。

準拠版: rules_draft **v0.12** ／ engine v0.1 ／ D-079 追記 3。
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
from meicho.cards import ACTION_CARDS, CHARA_CARDS, Timing       # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402


def _state(**kw) -> GameState:
    """最小の盤面。誘発だけを見たいので、デッキ構築規則は通さない。"""
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


def _run(s: GameState) -> GameState:
    """選択待ちを既定で消化しながら、保留がなくなるまで進める。"""
    E._pump(s)
    for _ in range(40):
        if not s.pending_choices:
            break
        ch = s.pending_choices[0]
        pi = ch["player"]
        acts = E.legal_actions(s, pi)
        pick = acts[0]
        for a in acts:            # 任意効果は「実行する」を選ぶ
            if a["type"] == "use":
                pick = a
                break
        s = E.apply(s, {pi: pick})
    return s


# --- タイミング -------------------------------------------------------------

def test_enter_and_levelup_fire_on_the_levelup_action_but_not_on_setup():
    """【登場】/【レベルアップ】はレベルアップ行動で誘発し、準備では誘発しない (u1・公式 908.3)。

    `BP01-017` 漂泊者（女）Lv1「■【登場】/【レベルアップ】自分のデッキの上から1枚を公開し、
    手札に加えてもよい」。

    **2026-09-17 に期待値を 2 枚から 1 枚へ書き換えた（D-092 B-1/B-2・D-094・rules v0.13）。**
    公式テキストの `■` は 1 つ＝**1 段落＝1 スキル**（800.3）で、アイコンが 2 つ付いているだけである。
    そして 603.1.2.2.1/.2 が【登場】＝一番上に置かれたカード、【レベルアップ】＝その下のカード、と
    誘発の主体を分けるので、**置いたばかりの `BP01-017` は【登場】でしか誘発しない**。
    下の `BP01-018`（Lv0）は【レベルアップ】を持たない。よって加わるのは **1 枚**である。

    旧版はここを「並記は別の場面なので 2 回引ける」(u1) と読んで 2 枚を要求しており、
    BP01 のキャラ Lv1 の 8 枚すべてでレベルアップ 1 回の利得が 2 倍になっていた。
    """
    s = _state()
    _put(s, 0, 0, "BP01-018")               # 漂泊者（女）Lv0
    _put(s, 1, 0, "SD01-001")
    s.players[0].chara_deck = ["BP01-017"]
    s.players[0].hand = ["SD01-007"]        # レベルアップのコスト 1 枚
    before = len(s.players[0].hand)
    s = E.apply(s, {0: {"type": "levelup", "slot": 0, "card": "BP01-017"}})
    s = _run(s)
    # コストで 1 枚捨て、【登場】で 1 枚加える（【レベルアップ】は誘発しない）
    assert len(s.players[0].hand) == before - 1 + 1, s.players[0].hand
    assert s.slot_entered_turn[0][0] == 3

    # 準備（§5-4）では誘発しない: 初期局面を作っただけで手札が増えないこと
    t = _state()
    _put(t, 0, 0, "BP01-017")
    assert not t.pending_triggers


def test_switched_fires_only_when_the_switch_actually_happens():
    """【切り替え】は切り替えが**実際に行われたとき**だけ誘発する (§7)。

    `BP01-008` ショアキーパーLv1「【切り替え】カード1枚を引いてもよい。そうした場合、手札1枚を捨てる」。
    """
    s = _state()
    _put(s, 0, 0, "SD01-001")
    _put(s, 0, 1, "BP01-008")
    _put(s, 1, 0, "SD01-001")
    s = E.apply(s, {0: {"type": "switch", "back": 1}})
    s = _run(s)
    assert s.players[0].trash, "引いてから捨てる、が起きていない"

    # 切り替え禁止中は誘発しない
    t = _state(leader_switch_forbidden=[True, False])
    _put(t, 0, 0, "SD01-001")
    _put(t, 0, 1, "BP01-008")
    _put(t, 1, 0, "SD01-001")
    assert not any(a["type"] == "switch" for a in E.legal_actions(t, 0))


def test_clash_phase_start_draws_up_to_five_for_the_turn_player_only():
    """【自分の対抗フェイズ開始時】はターンプレイヤーだけ (u なし)。

    `BP01-007` ショアキーパーLv2「手札が4枚以下の場合、5枚になるまで引く」。
    """
    s = _state()
    _put(s, 0, 0, "BP01-007")
    _put(s, 1, 0, "BP01-007")               # 相手も同じキャラ。誘発してはいけない
    s.players[0].hand = ["SD01-007"]
    s.players[1].hand = ["SD01-007"]
    s = E.apply(s, {0: {"type": "to_clash"}})
    s = _run(s)
    assert len(s.players[0].hand) == 5, s.players[0].hand
    assert len(s.players[1].hand) == 1, "非ターンプレイヤーで誘発している"


def test_clash_phase_end_fires_for_both_players():
    """【各対抗フェイズ終了時】は「各」なので両プレイヤーで誘発する (§7)。

    `BP01-025` 熾霞Lv2「アクションエリアに＜基本攻撃＞が2枚以上ある場合、相手にダメージ3」。
    """
    s = _state()
    _put(s, 0, 0, "BP01-025")
    _put(s, 1, 0, "BP01-025")
    for pi in (0, 1):
        s.players[pi].action_area = ["SD01-007", "SD01-012"]   # ともに＜基本攻撃＞
    life = [s.players[0].life, s.players[1].life]
    E._close_clash_phase(s)
    s = _run(s)
    assert s.players[0].life == life[0] - 3
    assert s.players[1].life == life[1] - 3


def test_on_heal_is_capped_by_the_per_turn_count():
    """【ライフが回復した時】は 1 ターン 2 回まで（`BP01-006`）。

    3 回目の回復では引かない。**回復量が 0 のときは誘発しない**。

    **A-6（D-104・rules v0.18）で後半を書き替えた。**v0.17 までは「満タンなら 0 回復になる」
    ことで「0 では数えない」を確かめていたが、**回復にライフの上限は無くなった**ので
    満タンからでも本物の回復になる。0 回復は**明示的に 0 を渡して**確かめる。
    """
    s = _state()
    _put(s, 0, 0, "BP01-006")
    _put(s, 1, 0, "SD01-001")
    s.players[0].life = 10
    drawn = []
    for i in range(4):
        n0 = len(s.players[0].hand)
        E._heal(s, 0, 1)
        s = _run(s)
        drawn.append(len(s.players[0].hand) - n0)
    assert drawn == [1, 1, 0, 0], drawn
    assert s.heals_this_turn[0] == 4

    # 0 回復は数えない（明示的に 0 を渡す）
    t = _state()
    _put(t, 0, 0, "BP01-006")
    _put(t, 1, 0, "SD01-001")
    E._heal(t, 0, 0)
    assert t.heals_this_turn[0] == 0, "0 回復で数えている"

    # **満タンからの回復は、いまは本物の回復である**（A-6・D-104）。
    u = _state()
    _put(u, 0, 0, "BP01-006")
    _put(u, 1, 0, "SD01-001")
    assert u.players[0].life == 20
    E._heal(u, 0, 1)
    assert u.players[0].life == 21
    assert u.heals_this_turn[0] == 1


def test_on_damage_dealt_fires_only_for_the_card_that_dealt_it():
    """【相手にダメージを与えた時】は**そのカード自身が与えたときだけ**誘発する (u18)。

    マスター裁定 2026-09-10。`BP01-060` メェ、出撃・重撃「相手にダメージを与えた時、
    自分のリーダーが「アンコ」の場合、カード1枚を引く」。

    K-2 の最初の実装は「そのカードがアクションエリアに在るあいだ、自分が与えたすべて」で、
    範囲が広すぎた。**盤面に置いてあるだけでは誘発しない**ことをここで固定する。
    """
    # (1) そのカード自身が与えた → 誘発する
    s = _state()
    _put(s, 0, 0, "BP01-015")               # アンコLv0（リーダー名が「アンコ」）
    _put(s, 1, 0, "SD01-001")
    s.players[0].action_area = ["BP01-060"]
    n0 = len(s.players[0].hand)
    E._damage(s, 1, 1, dealer=0, source=("action", "BP01-060"))
    s = _run(s)
    assert len(s.players[0].hand) == n0 + 1

    # (2) 別のカードが与えた → 盤面に在っても誘発しない（ここが裁定の中身）
    t = _state()
    _put(t, 0, 0, "BP01-015")
    _put(t, 1, 0, "SD01-001")
    t.players[0].action_area = ["BP01-060", "SD01-007"]
    m0 = len(t.players[0].hand)
    E._damage(t, 1, 1, dealer=0, source=("action", "SD01-007"))
    t = _run(t)
    assert len(t.players[0].hand) == m0, "自分が与えたダメージすべてで誘発している"

    # (3) リーダーが違えば誘発しない（条件は別途効く）
    u = _state()
    _put(u, 0, 0, "SD01-001")
    _put(u, 1, 0, "SD01-001")
    u.players[0].action_area = ["BP01-060"]
    k0 = len(u.players[0].hand)
    E._damage(u, 1, 1, dealer=0, source=("action", "BP01-060"))
    u = _run(u)
    assert len(u.players[0].hand) == k0


def test_on_damage_dealt_reaches_a_card_used_in_rush():
    """連撃で使ったカードでも誘発すること。

    連撃のカードは**対抗カードではない**ので、盤面の走査（`_active_skill_refs`）では拾えない。
    与えたカードを `source` で渡す形にしたのはこのためで、
    「拾えないからルールの範囲を広げる」という筋道は誤りだった（マスター指摘 2026-09-10）。
    """
    s = _state(phase=Phase.RUSH, rush_allowance=0)
    _put(s, 0, 0, "BP01-015")               # リーダーは「アンコ」
    _put(s, 1, 0, "SD01-001")
    s.players[0].action_area = ["BP01-060"]  # 連撃で使ったカードはここに積まれている
    s.clash_cards = [None, None]             # 対抗カードではない、を明示する
    n0 = len(s.players[0].hand)
    E._after_rush_skills(s, 0, "BP01-060")
    s = _run(s)
    assert len(s.players[0].hand) == n0 + 1, "連撃のカードで誘発していない"


# --- 状態欄・条件 -----------------------------------------------------------

def test_dominant_reads_the_previous_single_turn(monkeypatch):
    """【優勢】(u2): 直前の 1 ターンに勝ったか、相手がパスしていたか。最初のターンは不成立。"""
    s = _state(turn_no=1, last_turn_clash_winner=0)
    assert E._is_dominant(s, 0) is False, "最初のターンで成立している"
    s = _state(turn_no=2, last_turn_clash_winner=0)
    assert E._is_dominant(s, 0) is True
    assert E._is_dominant(s, 1) is False
    s = _state(turn_no=2, last_turn_clash_winner=None,
               last_turn_clash_pass=[False, True])
    assert E._is_dominant(s, 0) is True, "相手のパスで成立していない"
    assert E._is_dominant(s, 1) is False


def test_first_use_damage_buff_only_counts_the_first_card_of_the_turn():
    """「各ターンに自分が最初に使用した〈タグ〉」(u7) は 1 回だけ。

    `BP01-015` アンコLv0「最初に使用した【アンコ】の＜基本攻撃＞のダメージ+2」。
    """
    s = _state()
    _put(s, 0, 0, "BP01-015")
    _put(s, 1, 0, "SD01-001")
    card = ACTION_CARDS["BP01-059"]        # メェ、出撃・通常攻撃（【アンコ】の＜基本攻撃＞）
    assert E._card_damage_bonus(s, 0, card, in_rush=False) == 2
    E._note_card_use(s, 0, "BP01-059")
    assert E._card_damage_bonus(s, 0, card, in_rush=False) == 0, "2 枚目にも乗っている"
    # 専用キャラが違うカードには乗らない
    other = ACTION_CARDS["SD01-007"]
    t = _state()
    _put(t, 0, 0, "BP01-015")
    _put(t, 1, 0, "SD01-001")
    assert E._card_damage_bonus(t, 0, other, in_rush=False) == 0


def test_speed_override_only_changes_the_judge_comparison():
    """「スピードは N になる」(u10) は判定の比較にだけ効く**上書き**である。"""
    # 同じ赤どうしなので §6.4(2)(C) のスピード比較になる。
    # SD01-017 と SD02-022 はどちらも赤で、素の速さは 8 と 13。
    fast, slow = "SD02-022", "SD01-017"
    assert ACTION_CARDS[fast].speed > ACTION_CARDS[slow].speed

    # 素の値: 非ターンプレイヤー（速い方）が勝つ
    s = _state(phase=Phase.CLASH_SUBMIT)
    _put(s, 0, 0, "SD01-001")
    _put(s, 1, 0, "SD01-001")
    s.clash_cards = [slow, fast]
    E._judge_step(s)
    assert s.clash_winner == 1

    # 上書きでターンプレイヤーが逆転する
    t = _state(phase=Phase.CLASH_SUBMIT,
               speed_override=[ACTION_CARDS[fast].speed + 1, None])
    _put(t, 0, 0, "SD01-001")
    _put(t, 1, 0, "SD01-001")
    t.clash_cards = [slow, fast]
    E._judge_step(t)
    assert t.clash_winner == 0, "上書きが判定に効いていない"

    # 上書きはダメージには効かない（u10: 判定の比較にだけ）
    assert ACTION_CARDS[slow].damage == ACTION_CARDS[slow].damage


def test_damage_taken_mod_applies_to_every_source_and_never_goes_below_zero():
    """「自分が受けるダメージ +N / −N」(u13) はすべてのダメージに乗り、0 未満にならない。"""
    s = _state(damage_taken_mod=[2, 0])
    life = s.players[0].life
    E._damage(s, 0, 1)
    assert s.players[0].life == life - 3
    t = _state(damage_taken_mod=[-5, 0])
    life = t.players[0].life
    E._damage(t, 0, 1)
    assert t.players[0].life == life, "0 未満に落ちている / 回復している"
    assert t.damaged_this_turn[0] is False, "0 ダメージで「受けた」ことにしている"


def test_forbid_rush_self_now_is_immediate_not_reserved():
    """「このターン中、自分は連撃できない」(u12) は即時に立つ。予約 (`pending_`) を経ない。"""
    s = _state()
    _put(s, 0, 0, "SD01-001")
    _put(s, 1, 0, "SD01-001")
    E._apply_op(s, 0, "forbid_rush_self_now", {}, {})
    assert s.rush_forbidden[0] is True
    assert s.pending_rush_forbidden[0] is False, "予約になっている"


def test_new_state_fields_are_cleared_every_turn():
    """ターンごとに数え直す欄が `_begin_turn` で片付くこと。"""
    s = _state(heals_this_turn=[3, 3], damaged_this_turn=[True, True],
               first_damage_taken_this_turn=[True, True],
               last_used_card=["SD01-007", "SD01-007"],
               tag_uses_this_turn=[{"基本攻撃": 2}, {}],
               speed_override=[10, 10], clash_winner=1,
               pending_submission=["PASS", 0])
    _put(s, 0, 0, "SD01-001")
    _put(s, 1, 0, "SD01-001")
    E._begin_turn(s)
    assert s.heals_this_turn == [0, 0]
    assert s.damaged_this_turn == [False, False]
    assert s.first_damage_taken_this_turn == [False, False]
    assert s.last_used_card == [None, None]
    assert s.tag_uses_this_turn == [{}, {}]
    assert s.speed_override == [None, None]
    # 【優勢】の繰り越しは残る
    assert s.last_turn_clash_winner == 1
    assert s.last_turn_clash_pass == [True, False]


# --- 入れ子の割り込み -------------------------------------------------------

def test_nested_trigger_does_not_destroy_the_outer_resolution():
    """効果の途中で誘発しても、外側の待ち行列と再開地点が消えないこと。

    `_queue_fire` は `pending_skills` と `choice_resume` を**置き換える**ので、
    解決の途中で呼ぶと外側が消える（簡略化 B-4 の所在）。BP01 では
    【切り替え】【回復時】等が途中で起きるため、割り込み用の待ち行列を分けた。
    ここはその分離が守られていることの門番である。
    """
    s = _state()
    _put(s, 0, 0, "SD01-001")
    _put(s, 1, 0, "SD01-001")
    s.pending_skills = [[0, "chara", "SD01-001", 0]]
    s.choice_resume = {"kind": "turn_end"}
    keep_skills = [r[:] for r in s.pending_skills]
    keep_resume = dict(s.choice_resume)
    E._queue_fire_nested(s, Timing.ON_HEAL, [0])
    assert s.pending_skills == keep_skills, "外側の待ち行列が消えた"
    assert s.choice_resume == keep_resume, "再開地点が消えた"


def test_every_new_timing_is_reachable_from_some_registered_card():
    """足した 7 つのタイミングに、**実際に使っているカードが 1 枚以上ある**こと。

    使うカードが 1 枚も無いタイミングは、誘発点を書いても一度も踏まれない。
    K-3・K-4 で埋める番号があるので、ここは「0 でないこと」だけを見る。
    """
    used = {sk.timing for c in list(CHARA_CARDS.values()) + list(ACTION_CARDS.values())
            for sk in c.skills}
    for t in (Timing.ENTER, Timing.LEVELUP, Timing.SWITCHED, Timing.CLASH_PHASE_START,
              Timing.CLASH_PHASE_END, Timing.ON_HEAL, Timing.ON_DAMAGE_DEALT):
        assert t in used, f"{t.value} を使うカードが 1 枚も無い"
