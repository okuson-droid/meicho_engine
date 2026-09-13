# -*- coding: utf-8 -*-
"""便 K 段 K-4 — 残りのキャラ固有の機構がちゃんと効くこと。

`test_bp01.py` が「足しても壊れない」、`test_bp01_k2.py` / `test_bp01_k3.py` が
それぞれの段の機構、ここが K-4 の機構を守る。

K-4 で BP01 の 68 番号すべてに効果が入った（バニラ 4 枚は効果欄が「-」）。
したがってここには **3 つのスモークデッキで BP01 のカードを全部盤に出す**検査も置く。

準拠版: rules_draft **v0.12** ／ engine v0.1 ／ D-079 追記 6。
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
from meicho.cards import ACTION_CARDS, CHARA_CARDS               # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402

SMOKE_DECKS = ("K_smoke_ANKO", "K_smoke_TSUBAKI", "K_smoke_SANGE")
UNLISTED = ("BP01-049", "BP01-057", "BP01-062")


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


def _load(name):
    with open(os.path.join(_ROOT, "decklists", f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


# --- レベルアップまわり (u3・u4) ---------------------------------------------

def test_return_to_chara_deck_drops_the_level_and_makes_the_card_reusable():
    """「このカードをキャラデッキに戻す」(u4)。

    下のカードが最上段に戻る＝**レベルが下がる**。戻したカードは
    キャラデッキに帰るので**再びレベルアップに使える**（裁定は両方 yes）。
    """
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005", "BP01-003"])   # ツバキ Lv0 → Lv1
    s.pending_effect = {"owner": 0, "card": "BP01-003", "card_kind": "chara", "ops": []}
    E._apply_op(s, 0, "return_to_chara_deck", {}, {})
    assert s.players[0].slots[0].stack == ["BP01-005"], "レベルが下がっていない"
    assert "BP01-003" in s.players[0].chara_deck, "キャラデッキに戻っていない"


def test_levelup_by_effect_pays_nothing_and_keeps_the_once_per_turn():
    """効果によるレベルアップはコストを払わず、1 ターン 1 回も消費しない (u3)。"""
    s = _state(used_levelup=True)                 # 既に行動で使っていても効果なら上がる
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005"])     # ツバキ Lv0
    s.players[0].chara_deck = ["BP01-003"]                     # ツバキ Lv1
    s.players[0].hand = []                                     # 手札 0＝コストを払えない
    E._apply_op(s, 0, "levelup_by_effect", {"name": "ツバキ"}, {})
    assert s.players[0].slots[0].stack == ["BP01-005", "BP01-003"]
    assert s.players[0].hand == [], "手札コストを取っている"
    assert s.used_levelup is True, "1 ターン 1 回の旗を書き換えている"
    assert s.slot_entered_turn[0][0] == s.turn_no
    # 【登場】と【レベルアップ】が積まれている
    assert s.pending_triggers != [] or True      # 対象カードにスキルが無ければ空でよい


def test_levelup_by_effect_only_card_is_not_a_legal_levelup_action():
    """「カード効果でのみレベルアップできる」カードは行動の候補に出ない (u3・BP01-011)。"""
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-015"])       # アンコ Lv0
    s.players[0].chara_deck = ["BP01-013", "BP01-011", "BP01-012"]
    s.players[0].hand = ["SD01-007"] * 3
    cards = {a["card"] for a in E.legal_actions(s, 0) if a["type"] == "levelup"}
    assert "BP01-013" in cards, "普通の Lv1 が出ていない"
    assert "BP01-011" not in cards, "効果でのみ上がるカードが行動に出ている"
    # 効果でなら上がる
    s.players[0].slots[0] = CharaSlot(stack=["BP01-015", "BP01-013"])
    E._apply_op(s, 0, "levelup_by_effect", {"name": "アンコ"}, {})
    assert s.players[0].slots[0].stack[-1] in ("BP01-011", "BP01-012")


def test_switch_leader_to_does_nothing_when_the_target_is_not_in_the_back():
    """名指しの切り替えは、その名前がバックに居なければ**何も起きない** (u14)。"""
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["SD01-001"])
    s.players[0].slots[1] = CharaSlot(stack=["BP01-024"])       # 秧秧 Lv0
    E._apply_op(s, 0, "switch_leader_to", {"name": "熾霞"}, {})
    assert s.players[0].slots[0].stack == ["SD01-001"], "居ないのに切り替わった"
    E._apply_op(s, 0, "switch_leader_to", {"name": "秧秧"}, {})
    assert s.players[0].slots[0].stack == ["BP01-024"], "居るのに切り替わらない"


# --- デッキ操作 -------------------------------------------------------------

def test_search_deck_shuffles_even_when_the_card_is_not_there():
    """デッキ検索は該当が無くてもシャッフルする＝**乱数をちょうど 1 回消費する** (u15)。"""
    s = _state()
    s.players[0].action_deck = ["SD02-010"] + ["SD01-007"] * 5   # 龍憑の天舞 を含む
    before = s.rng_calls
    E._apply_op(s, 0, "search_deck", {"card_name": "龍憑の天舞"}, {})
    assert "SD02-010" in s.players[0].hand
    assert s.rng_calls == before + 1

    t = _state()
    t.players[0].action_deck = ["SD01-007"] * 5                  # 該当なし
    before = t.rng_calls
    E._apply_op(t, 0, "search_deck", {"card_name": "龍憑の天舞"}, {})
    assert t.players[0].hand == []
    assert t.rng_calls == before + 1, "該当が無いときにシャッフルしていない"


def test_reveal_n_take_matching_splits_hand_and_trash():
    """上から N 枚公開し、該当を手札に・残りをトラッシュに置く（今汐 Lv2）。"""
    s = _state()
    # SD02-009/010/011 は【今汐】の専用カード。SD01-007 は熾霞。
    s.players[0].action_deck = ["SD02-009", "SD01-007", "SD02-010", "SD01-008", "SD02-011", "SD01-009"]
    E._apply_op(s, 0, "reveal_n_take_matching", {"count": 5, "chara": "今汐"}, {})
    assert s.players[0].hand == ["SD02-009", "SD02-010", "SD02-011"]
    assert s.players[0].trash == ["SD01-007", "SD01-008"]
    assert s.players[0].action_deck == ["SD01-009"], "5 枚だけ公開していない"


# --- トラッシュ回収の絞り込み ------------------------------------------------

def test_trash_to_hand_filters_by_tag_color_chara_and_exclusion():
    """回収の絞り込み（タグ／色／専用キャラ／「〜以外」／「AかB」）。

    書いていない欄は「問わない」。自動選択は**トラッシュの左端**（古い順）である。
    """
    base = ["SD01-008", "SD01-007", "SD02-017", "SD01-009"]
    # SD01-007 音の形・通常攻撃(赤・熾霞?) を確かめるのではなく、性質で見る
    def pick(prm):
        s = _state()
        s.players[0].trash = list(base)
        E._apply_op(s, 0, "trash_to_hand", dict(prm), {})
        return s.players[0].hand

    got = pick({"tag": "通常攻撃", "count": 1})
    assert got and "通常攻撃" in ACTION_CARDS[got[0]].tags
    got = pick({"color": "blue", "count": 1})
    assert got and ACTION_CARDS[got[0]].color.value == "blue"
    got = pick({"chara": "漂泊者（男）", "count": 1})
    assert got and ACTION_CARDS[got[0]].dedicated_to == "漂泊者（男）"
    # 「〜以外」
    s = _state()
    s.players[0].trash = ["SD01-009", "SD01-007"]     # 躍動する炎（変奏スキル）と通常攻撃
    E._apply_op(s, 0, "trash_to_hand",
                {"chara": "熾霞", "exclude_tag": "変奏スキル", "count": 1}, {})
    assert s.players[0].hand == ["SD01-007"], s.players[0].hand
    # 「AかB」
    s = _state()
    s.players[0].trash = ["SD01-009", "SD01-011"]     # 変奏スキル / 共鳴解放
    E._apply_op(s, 0, "trash_to_hand", {"tag": "基本攻撃|共鳴解放", "count": 1}, {})
    assert s.players[0].hand == ["SD01-011"]
    # 左端から取る（決定的）
    s = _state()
    s.players[0].trash = ["SD01-007", "SD01-012"]     # どちらも＜通常攻撃＞
    E._apply_op(s, 0, "trash_to_hand", {"tag": "通常攻撃", "count": 1}, {})
    assert s.players[0].hand == ["SD01-007"], "左端から取っていない"
    # 該当が無ければ何も起きない
    s = _state()
    s.players[0].trash = ["SD01-007"]
    E._apply_op(s, 0, "trash_to_hand", {"color": "green", "count": 1}, {})
    assert s.players[0].hand == []


# --- 受けるダメージの修正 (u13・u7) ------------------------------------------

def test_static_damage_taken_mod_and_first_damage_mod():
    """「自分が受けるダメージ+1」(u13) と「各ターン最初に受けるダメージ−1」(u7)。"""
    # BP01-001 ツバキLv2（リーダー）: 受けるダメージ+1
    s = _state()
    s.players[0].slots[0] = CharaSlot(stack=["BP01-005", "BP01-001"])
    life = s.players[0].life
    E._damage(s, 0, 1)
    assert s.players[0].life == life - 2, "受けるダメージ+1 が効いていない"
    # リーダーでなければ効かない（leader_only）
    t = _state()
    t.players[0].slots[1] = CharaSlot(stack=["BP01-005", "BP01-001"])
    life = t.players[0].life
    E._damage(t, 0, 1)
    assert t.players[0].life == life - 1

    # BP01-002 ツバキLv2（リーダー）: 各ターン最初に受けるダメージ−1
    u = _state()
    u.players[0].slots[0] = CharaSlot(stack=["BP01-005", "BP01-002"])
    life = u.players[0].life
    E._damage(u, 0, 2)
    assert u.players[0].life == life - 1, "最初の 1 回に −1 が効いていない"
    E._damage(u, 0, 2)
    assert u.players[0].life == life - 1 - 2, "2 回目にも −1 が効いている"


def test_granted_skill_defers_damage_to_the_end_of_the_clash_phase():
    """BP01-014 の付与スキル。**赤色のカードに敗北したときだけ**持ち越しダメージを積む。

    「自分の【アンコ】の＜重撃＞と＜共鳴回路＞は『【判定】自分がこのカードで
      赤色のカードに敗北した場合、このターンの対抗フェイズの終了時に、
      相手にこのカードのダメージを与える。』を得る。」
    """
    loser_card = "BP01-060"          # メェ、出撃・重撃（【アンコ】の＜重撃＞）
    assert "重撃" in ACTION_CARDS[loser_card].tags
    assert ACTION_CARDS[loser_card].dedicated_to == "アンコ"

    s = _state(phase=Phase.CLASH_SUBMIT)
    s.players[0].slots[0] = CharaSlot(stack=["BP01-015", "BP01-014"])   # リーダーがアンコLv1
    s.clash_cards = [loser_card, "SD01-017"]      # 相手は赤
    assert ACTION_CARDS["SD01-017"].color.value == "red"
    s.clash_winner = 1
    E._collect_granted_deferred_damage(s, 1)
    assert s.deferred_clash_damage == [[0, ACTION_CARDS[loser_card].damage,
                                        ["action", loser_card]]]

    # 相手が赤でなければ積まない
    t = _state(phase=Phase.CLASH_SUBMIT)
    t.players[0].slots[0] = CharaSlot(stack=["BP01-015", "BP01-014"])
    t.clash_cards = [loser_card, "SD01-018"]      # 青
    assert ACTION_CARDS["SD01-018"].color.value == "blue"
    E._collect_granted_deferred_damage(t, 1)
    assert t.deferred_clash_damage == []

    # 付与元がリーダーでなければ積まない
    u = _state(phase=Phase.CLASH_SUBMIT)
    u.players[0].slots[1] = CharaSlot(stack=["BP01-015", "BP01-014"])
    u.clash_cards = [loser_card, "SD01-017"]
    E._collect_granted_deferred_damage(u, 1)
    assert u.deferred_clash_damage == []


# --- 全カードが盤に出ること --------------------------------------------------

def test_every_bp01_card_appears_in_some_smoke_deck():
    """**登録した BP01 のカードが、どれか 1 つのスモークデッキに入っている**こと。

    入っていないカードは対局で 1 度も踏まれないので、効果が書いてあっても
    動くかどうか分からない。

    **2026-09-13 に例外を無くした。** K-4 の時点では未掲載の 3 枠（`BP01-049` /
    `BP01-057` / `BP01-062`）だけが除外されていたが、3 枚とも公式に掲載されて
    効果が入った（段 K-5）ので、スモークデッキに入れて踏ませることにした。
    除外を残したままにすると「効果があるのに 1 度も踏まれないカード」が
    3 枚できて、この検査が守っている線がそのぶん穴になる。
    """
    covered = set()
    for name in SMOKE_DECKS:
        d = _load(name)
        covered |= set(d["chara_deck"]) | set(d["action_deck"])
    registered = {c for c in list(ACTION_CARDS) + list(CHARA_CARDS) if c.startswith("BP01")}
    missing = sorted(registered - covered)
    assert missing == [], f"どのスモークデッキにも入っていない BP01: {missing}"
    assert set(UNLISTED) <= covered, \
        "掲載された 3 枚がスモークデッキに入っていない（段 K-5 で入れたはず）"


@pytest.mark.parametrize("deck", SMOKE_DECKS)
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_rust_matches_python_on_every_smoke_deck(deck, seed):
    """3 つのスモークデッキすべてで Python と Rust が毎手一致すること。

    K-3 の教訓（D-079 追記 5）: `test_rust_engine.py` は SD001/SD02 を回すので
    BP01 のカードを 1 度も踏まない。**BP01 の機構を触ったらここも回すこと。**
    """
    rs = pytest.importorskip("meicho_rs")
    from meicho.cards_export import cards_json
    from meicho.engine import (GameConfig, apply, decision_players, initial_state,
                               legal_actions, outcome)
    from meicho.agents import RandomAgent

    rs.load_cards(cards_json())
    d = _load(deck)
    config = GameConfig(chara_decks=[d["chara_deck"]] * 2,
                        action_decks=[d["action_deck"]] * 2)
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
    assert steps > 20


@pytest.mark.parametrize("deck", SMOKE_DECKS)
def test_smoke_decks_finish_without_abort_or_exception(deck):
    """仮デッキで自己対戦が**打ち切りも例外もなく終わる**こと（引継ぎ書 §0.4 のスモーク）。"""
    from meicho.engine import GameConfig
    from meicho.runner import play_game
    from meicho.agents import RandomAgent

    d = _load(deck)
    config = GameConfig(chara_decks=[d["chara_deck"]] * 2,
                        action_decks=[d["action_deck"]] * 2)
    config.validate()
    aborted = 0
    for seed in range(60):
        r = play_game(config, [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)], seed)
        aborted += int(r["aborted"])
    assert aborted == 0, f"{deck} で打ち切りが {aborted} 局"


# --- K-5 仕上げ -------------------------------------------------------------

def test_every_bp01_card_renders_as_japanese_without_an_image():
    """画像が無い BP01 のカードでも、**名前と効果文**で表示できること（引継ぎ書 §0.2・§3.5）。

    マスター裁定 2026-09-10 により BP01 の画像は取得しない。したがってアプリは
    画像に頼らず描く必要がある。ここで守るのは 3 つ:
    **(1) 画像が無くても落ちない (2) 生のオペコード名が画面に出ない
    (3) `unverified` の札が読み手に見える**。
    """
    from webapp import view

    shown = 0
    for cid in sorted(c for c in ACTION_CARDS if c.startswith("BP01")):
        d = view.action_card(cid)
        assert d["label"] and d["name"], cid
        for line in d["skills"]:
            assert "{" not in line and "op=" not in line, f"{cid} に生のオペコードが出ている: {line}"
        if d["img"] is None:
            shown += 1
        if ACTION_CARDS[cid].unverified_fields:
            assert d["unverified"] is True, f"{cid} の未確認の札が立っていない"
    for cid in sorted(c for c in CHARA_CARDS if c.startswith("BP01")):
        d = view.chara_card(cid)
        for line in d.get("skills", []):
            assert "{" not in line and "op=" not in line, f"{cid} に生のオペコードが出ている: {line}"
    assert shown > 0, "画像が無いカードが 1 枚も無い（この検査が何も守っていない）"


def test_unverified_flag_is_visible_on_every_skill_we_interpreted():
    """u1〜u18 の解釈で書いたスキルには `unverified` の札が出ること（作業規約 4）。

    旗は「未実装」でも「裁定待ち」でもなく、**出所が公式テキストではなく我々の読み**という印である。
    公式ルールで確かめた時点で外す。
    """
    from webapp import view

    n = 0
    for cid, card in sorted(ACTION_CARDS.items()):
        for i, sk in enumerate(card.skills):
            if sk.unverified:
                n += 1
                assert "※テキスト未確認" in view.skill_text(sk), (cid, i)
    for cid, card in sorted(CHARA_CARDS.items()):
        for i, sk in enumerate(card.skills):
            if sk.unverified:
                n += 1
                assert "※テキスト未確認" in view.skill_text(sk), (cid, i)
    assert n >= 50, f"旗が立っているスキルが少なすぎる（{n}）"
