# -*- coding: utf-8 -*-
"""便 K 段 K-3 — 【優勢】と＜音骸＞がちゃんと効くこと。

`tests/test_bp01.py` が「足しても壊れない」、`test_bp01_k2.py` が「K-2 の機構が効く」、
ここが「K-3 の機構が効く」を守る。

**乱数を使うオペコードが初めて出る段**である。`(seed, rng_calls)` からだけ引くこと、
**Rust と消費回数まで揃う**ことをここで固定する（作業規約 2・引継ぎ書 §3.3）。

準拠版: rules_draft **v0.12** ／ engine v0.1 ／ D-079 追記 5。
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
from meicho.cards import ACTION_CARDS, ONKAI_TAG                  # noqa: E402
from meicho.state import CharaSlot, GameState, Phase, PlayerState  # noqa: E402

# ＜音骸＞の 5 セット。強化（コスト 0）と妨害（コスト 1・【優勢】）の 2 枚組。
ONKAI_SETS = [
    ("山を轟かせる崩火", "焦熱", "BP01-034", "BP01-035"),
    ("夜にこびり付く白霜", "凝縮", "BP01-036", "BP01-037"),
    ("谷を突き抜ける長風", "気動", "BP01-038", "BP01-039"),
    ("二度と輝かない沈日", "消滅", "BP01-040", "BP01-041"),
    ("闇を取り払う浮星", "回折", "BP01-042", "BP01-043"),
]


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
    for _ in range(40):
        if not s.pending_choices:
            break
        pi = s.pending_choices[0]["player"]
        acts = E.legal_actions(s, pi)
        pick = next((a for a in acts if a["type"] == "use"), acts[0])
        s = E.apply(s, {pi: pick})
    return s


# --- ＜音骸＞の枠 ----------------------------------------------------------

def test_the_ten_onkai_are_common_cards_with_a_set_tag_and_an_attribute():
    """＜音骸＞10 枚が「共通カード（専用キャラ無し）」で、セット名と属性のタグを持つこと。

    BP01 で初めて出た専用キャラを持たないカードである（rules §3.2-5）。
    ここが崩れると u6 の「2 種類以上の＜セット名＞」が数えられない。
    """
    onkai = sorted(c for c in ACTION_CARDS if ONKAI_TAG in ACTION_CARDS[c].tags)
    assert len(onkai) == 10, onkai
    for setname, attr, a, b in ONKAI_SETS:
        for cid in (a, b):
            c = ACTION_CARDS[cid]
            assert c.dedicated_to is None, f"{cid} が専用キャラを持っている"
            assert setname in c.tags and attr in c.tags, (cid, c.tags)


def test_only_one_onkai_can_sit_in_the_action_area():
    """＜音骸＞は自分のアクションエリアに 1 枚まで。2 枚目は**使用できない** (u5)。

    「置いてからトラッシュ」ではなく合法手から外す、が裁定である。
    相手のアクションエリアの音骸は自分の制限に関わらない。
    """
    s = _state(phase=Phase.CLASH_SUBMIT)
    s.players[0].hand = ["BP01-034", "BP01-036"]
    s.players[0].concerto = ["SD01-007"] * 3
    assert E._usable_in_clash(s, 0, ACTION_CARDS["BP01-034"]) is True

    s.players[0].action_area = ["BP01-036"]
    assert E._usable_in_clash(s, 0, ACTION_CARDS["BP01-034"]) is False, "2 枚目が使える"
    # 音骸でないカードは影響を受けない
    assert E._usable_in_clash(s, 0, ACTION_CARDS["SD01-007"]) is True
    # 相手の盤面は関係しない
    t = _state(phase=Phase.CLASH_SUBMIT)
    t.players[1].action_area = ["BP01-036"]
    t.players[0].concerto = ["SD01-007"] * 3
    assert E._usable_in_clash(t, 0, ACTION_CARDS["BP01-034"]) is True


def test_onkai_restriction_removes_the_card_from_legal_actions():
    """合法手そのものから消えること（`_usable_in_clash` を通る道が 2 つあるので両方見る）。"""
    s = _state(phase=Phase.CLASH_SUBMIT)
    s.players[0].hand = ["BP01-034"]
    s.players[0].concerto = ["SD01-007"] * 3
    s.players[0].action_area = ["BP01-036"]
    assert not any(a["type"] == "submit" for a in E.legal_actions(s, 0))


# --- 協奏エリアの強化（u6・u7）---------------------------------------------

def test_concerto_set_buff_needs_two_distinct_names_and_only_the_first_use():
    """「このカードを含む 2 種類以上の＜セット名＞」で、各ターン最初の 1 枚だけ (u6・u7)。

    `BP01-034` 信号機モドキ。**協奏エリアに置かれたカード**に載る常在型なので、
    盤面の走査（`_active_skill_refs`）では見つからない。ここが効いていなければ、
    ダメージ計算が協奏エリアを見ていない。
    """
    setname, attr, buffer_, harm = ONKAI_SETS[0]
    victim = ACTION_CARDS[harm]                    # 同じセット＝属性タグを持つ
    assert attr in victim.tags

    # 1 種類だけ → 効かない
    s = _state()
    s.players[0].concerto = [buffer_]
    assert E._card_damage_bonus(s, 0, victim, in_rush=False) == 0

    # 同じカードを 2 枚（カード名の異なり数は 1）→ 効かない
    t = _state()
    t.players[0].concerto = [buffer_, buffer_]
    assert E._card_damage_bonus(t, 0, victim, in_rush=False) == 0, \
        "「種類」をカード名の異なり数で数えていない"

    # 2 種類 → 効く
    u = _state()
    u.players[0].concerto = [buffer_, harm]
    assert E._card_damage_bonus(u, 0, victim, in_rush=False) == 1

    # そのターンに既に＜属性＞を使っていれば効かない (u7)
    E._note_card_use(u, 0, harm)
    assert E._card_damage_bonus(u, 0, victim, in_rush=False) == 0

    # 属性が違うカードには乗らない
    v = _state()
    v.players[0].concerto = [buffer_, harm]
    assert E._card_damage_bonus(v, 0, ACTION_CARDS["SD01-017"], in_rush=False) == 0


def test_concerto_set_buff_does_not_leak_across_sets():
    """5 セットが互いに独立であること（セット名も属性も別なので混ざらない）。"""
    for i, (setname, attr, buffer_, harm) in enumerate(ONKAI_SETS):
        other = ONKAI_SETS[(i + 1) % len(ONKAI_SETS)]
        s = _state()
        s.players[0].concerto = [buffer_, harm]
        # 別セットの妨害カードには乗らない
        assert E._card_damage_bonus(s, 0, ACTION_CARDS[other[3]], in_rush=False) == 0, \
            f"{setname} の強化が {other[0]} に漏れている"


# --- 【優勢】 ---------------------------------------------------------------

def test_dominant_gates_every_harm_effect():
    """【優勢】でなければ妨害 5 種は 1 つも誘発しないこと (u2)。"""
    from meicho.cards import Timing
    for _, _, _, harm in ONKAI_SETS:
        sk = ACTION_CARDS[harm].skills[0]
        assert sk.timing is Timing.ON_DAMAGE_DEALT
        assert sk.condition == {"dominant": True}, (harm, sk.condition)
        s = _state(turn_no=2, last_turn_clash_winner=1)   # 相手が勝った＝自分は優勢でない
        assert E._skill_condition_met(s, 0, sk, {}) is False
        t = _state(turn_no=2, last_turn_clash_winner=0)
        assert E._skill_condition_met(t, 0, sk, {}) is True


def test_harm_effects_do_what_the_text_says():
    """妨害 5 種がそれぞれ正しい領域を動かすこと。**枚数と行き先**を見る。"""
    # (1) ランダム捨て札: 手札 4 枚につき 1 枚。端数は切り捨て (u9)
    s = _state()
    s.players[1].hand = ["SD01-007"] * 9          # 9 // 4 = 2 枚
    E._apply_op(s, 0, "opp_discard_random", {"per": 4}, {})
    assert len(s.players[1].hand) == 7 and len(s.players[1].trash) == 2
    t = _state()
    t.players[1].hand = ["SD01-007"] * 3          # 3 // 4 = 0 枚
    E._apply_op(t, 0, "opp_discard_random", {"per": 4}, {})
    assert len(t.players[1].hand) == 3, "端数を切り上げている"

    # (2) 協奏エリアからトラッシュ
    u = _state()
    u.players[1].concerto = ["SD01-007", "SD01-009"]
    E._apply_op(u, 0, "opp_concerto_to_trash", {"count": 1}, {})
    assert len(u.players[1].concerto) == 1 and u.players[1].trash == ["SD01-007"]

    # (3) 手札からランダムにデッキの下へ
    v = _state()
    v.players[1].hand = ["SD01-009"]
    n0 = len(v.players[1].action_deck)
    E._apply_op(v, 0, "opp_hand_random_to_deck_bottom", {"count": 1}, {})
    assert v.players[1].hand == [] and v.players[1].action_deck[-1] == "SD01-009"
    assert len(v.players[1].action_deck) == n0 + 1

    # (4) デッキの上から 3 枚トラッシュ。**山が尽きても再構成しない**
    w = _state()
    w.players[1].action_deck = ["SD01-007", "SD01-009"]
    E._apply_op(w, 0, "mill_opponent_deck_top", {"count": 3}, {})
    assert w.players[1].action_deck == [] and len(w.players[1].trash) == 2

    # (5) トラッシュから 2 枚までデッキの下へ
    x = _state()
    x.players[1].trash = ["SD01-007", "SD01-009", "SD01-010"]
    E._apply_op(x, 0, "opp_trash_to_deck_bottom", {"count": 2}, {})
    assert len(x.players[1].trash) == 1
    assert x.players[1].action_deck[-2:] == ["SD01-007", "SD01-009"]


def test_speed_override_card_needs_both_dominant_and_the_leader():
    """`BP01-059` は【優勢】とリーダー「アンコ」の**両方**が要る。"""
    sk = ACTION_CARDS["BP01-059"].skills[0]
    s = _state(turn_no=2, last_turn_clash_winner=0)
    s.players[0].slots[0] = CharaSlot(stack=["BP01-015"])      # リーダーがアンコ
    assert E._skill_condition_met(s, 0, sk, {}) is True
    s.players[0].slots[0] = CharaSlot(stack=["SD01-001"])      # リーダーが違う
    assert E._skill_condition_met(s, 0, sk, {}) is False
    t = _state(turn_no=2, last_turn_clash_winner=1)            # 優勢でない
    t.players[0].slots[0] = CharaSlot(stack=["BP01-015"])
    assert E._skill_condition_met(t, 0, sk, {}) is False


# --- 乱数 -------------------------------------------------------------------

@pytest.mark.parametrize("op,prm,hand", [
    ("opp_discard_random", {"per": 4}, 9),
    ("opp_discard_random", {"per": 4}, 3),
    ("opp_hand_random_to_deck_bottom", {"count": 1}, 5),
])
def test_random_ops_consume_a_predictable_number_of_rng_calls(op, prm, hand):
    """乱数は `(seed, rng_calls)` からだけ引き、**消費回数が読めること**。

    Rust と一致させるには回数まで揃っている必要がある（作業規約 2）。
    ここで固定するのは「1 枚動かすごとに 1 回」という規則である。
    """
    s = _state()
    s.players[1].hand = ["SD01-007"] * hand
    before = s.rng_calls
    moved_before = len(s.players[1].hand)
    E._apply_op(s, 0, op, dict(prm), {})
    moved = moved_before - len(s.players[1].hand)
    assert s.rng_calls - before == moved, "動かした枚数と乱数の消費回数が合わない"


def test_random_ops_are_reproducible_from_the_seed():
    """同じ `(seed, rng_calls)` なら同じ結果になること（決定性・D-006）。"""
    def run(seed):
        s = _state()
        s.seed = seed
        s.players[1].hand = ["a", "b", "c", "d", "e", "f", "g", "h"]
        E._apply_op(s, 0, "opp_discard_random", {"per": 4}, {})
        return list(s.players[1].hand), list(s.players[1].trash)

    assert run(7) == run(7)
    # 種が違えば（ほぼ確実に）違う結果になる。同じなら乱数を引いていない疑い。
    assert any(run(7) != run(k) for k in (8, 9, 10, 11)), "種を変えても結果が変わらない"


# --- Python / Rust の毎手一致（BP01 のデッキで）--------------------------------

@pytest.mark.parametrize("deck", ["K_smoke_ANKO", "K_smoke_TSUBAKI", "K_smoke_SANGE"])
@pytest.mark.parametrize("seed", list(range(40)))
def test_rust_matches_python_on_a_bp01_deck(seed, deck):
    """BP01 の仮デッキで、Python と Rust が**毎手・全欄一致**すること。

    `test_rust_engine.py` の毎手一致は SD001/SD02 の対局を回すので、BP01 のカードを
    1 度も踏まない——K-2・K-3 で足した機構は**あちらでは 1 行も実行されない**。
    ここが K-3 までの Python/Rust 一致の唯一の門番である。

    仮デッキは＜音骸＞10 種と【優勢】のカードを厚く積んであるので、
    乱数を使うオペコード（相手手札のランダムな捨て札・デッキ下送り）も踏む。
    **乱数の消費回数がずれれば `rng_calls` の不一致で落ちる。**

    仮デッキは**測定には使わない**（引継ぎ書 §3.6）。
    """
    rs = pytest.importorskip("meicho_rs")
    import json as _json

    from meicho.cards import ACTION_CARDS as _A, CHARA_CARDS as _C
    from meicho.cards_export import cards_json
    from meicho.engine import (GameConfig, apply, decision_players, initial_state,
                               legal_actions, observe, outcome)
    from meicho.agents import RandomAgent

    n = rs.load_cards(cards_json())
    assert n == len(_C) + len(_A)

    with open(os.path.join(_ROOT, "decklists", deck + ".json"), encoding="utf-8") as f:
        d = _json.load(f)
    config = GameConfig(chara_decks=[d["chara_deck"]] * 2,
                        action_decks=[d["action_deck"]] * 2)
    config.validate()

    def norm(x):
        return _json.loads(_json.dumps(x, ensure_ascii=False))

    py = initial_state(config, seed)
    rss = rs.initial_state(config.chara_decks, config.action_decks, seed)
    agents = [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)]
    steps = 0
    while outcome(py) is None and py.turn_no <= 200:
        assert norm(_json.loads(py.to_json())) == _json.loads(rss.to_json()), \
            f"state mismatch deck={deck} seed={seed} step={steps}"
        need = decision_players(py)
        assert list(need) == list(rs.decision_players(rss)), f"decision_players deck={deck} seed={seed} step={steps}"
        for pi in (0, 1):
            assert norm(legal_actions(py, pi)) == rs.legal_actions(rss, pi), \
                f"legal_actions P{pi} deck={deck} seed={seed} step={steps}"
        acts = {pi: agents[pi].act(py, pi) for pi in need}
        py = apply(py, acts)
        rss = rs.apply(rss, {pi: norm(a) for pi, a in acts.items()})
        steps += 1
    assert norm(_json.loads(py.to_json())) == _json.loads(rss.to_json()), "最終局面が違う"
    assert outcome(py) == rs.outcome(rss)
    assert steps > 20, f"対局が短すぎて何も踏んでいない（steps={steps}）"


def test_zone_choice_on_an_opponent_zone_carries_no_match_params():
    """B-8: 相手の領域を動かす zone_card の `match_params` が Python と Rust で一致すること。

    Python (`_queue_zone_choice` の呼び分け・`engine.py`) は **相手の領域**を動かす 2 つの op
    (`opp_concerto_to_trash` / `opp_trash_to_deck_bottom`) に `match_params` を渡さない。
    絞り込みを持つのは**自分のトラッシュから拾う** 2 つ (`trash_to_hand` / `trash_to_concerto`) だけである。

    Rust は 4 つを 1 本の分岐で扱っていて、つねに op の params を `match_params` に入れていた。
    `count` は絞り込みの鍵ではないので選択肢は変わらないが、**状態の JSON が食い違う**ので
    毎手一致が落ちる（2026-09-17・D-093 で発見。シード 5 の 22 手目）。

    ここは症状を名指しする検査である。上の毎手一致だけでも落ちるが、
    落ちたときに「どの欄が、なぜ」を読み取れるようにこちらを置く。
    **将来 `opp_trash_to_deck_bottom` に `tag` 等の絞り込みが付いたカードが来ると本物の挙動差になる**
    ので、そのときはこの検査を「Python と同じ絞り込みを渡す」側へ書き換えること。
    """
    rs = pytest.importorskip("meicho_rs")
    import json as _json

    from meicho.cards_export import cards_json
    from meicho.engine import (GameConfig, apply, decision_players, initial_state,
                               legal_actions, outcome)
    from meicho.agents import RandomAgent

    rs.load_cards(cards_json())
    with open(os.path.join(_ROOT, "decklists", "K_smoke_ANKO.json"), encoding="utf-8") as f:
        d = _json.load(f)
    config = GameConfig(chara_decks=[d["chara_deck"]] * 2,
                        action_decks=[d["action_deck"]] * 2)

    def norm(x):
        return _json.loads(_json.dumps(x, ensure_ascii=False))

    # シード 5 は `BP01-043`「哀切の凶鳥」の `opp_trash_to_deck_bottom {count: 2}` を踏む。
    seed = 5
    py = initial_state(config, seed)
    rss = rs.initial_state(config.chara_decks, config.action_decks, seed)
    agents = [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)]
    seen = 0
    while outcome(py) is None and py.turn_no <= 200:
        a = norm(_json.loads(py.to_json()))
        b = _json.loads(rss.to_json())
        for pc_py, pc_rs in zip(a.get("pending_choices") or [], b.get("pending_choices") or []):
            if pc_py.get("kind") != "zone_card":
                continue
            seen += 1
            mp_py, mp_rs = pc_py["match_params"], pc_rs["match_params"]
            assert mp_py == mp_rs, (
                "zone_card の match_params が食い違う（B-8）: "
                f"Python={mp_py} / Rust={mp_rs} / destination={pc_py['destination']}")
        need = decision_players(py)
        acts = {pi: agents[pi].act(py, pi) for pi in need}
        py = apply(py, acts)
        rss = rs.apply(rss, {pi: norm(a2) for pi, a2 in acts.items()})
    assert seen > 0, "zone_card の選択を 1 度も踏んでいない＝この検査は何も守っていない"


def test_pay_cost_return_self_to_hand_records_paid_like_python():
    """B-8 の 2 件目: 「支払いはもう済んだ」印の欄名が Python と Rust で一致すること。

    `BP01-069` 羽乱舞・回避の `pay_cost_return_self_to_hand` (u11) は、支払いの選択を
    先に済ませたことを **Python が `prm["paid"] = True`** で覚える（`engine.py`）。
    Rust は既存の `chosen` を流用して `chosen: 1` と書いていたので、`pending_effect` の
    params が食い違って毎手一致が落ちていた（2026-09-17・`K_smoke_TSUBAKI` のシード 37・39 ほか）。
    `chosen` はドロー枚数などにも使う欄なので流用は解けない。Rust に `paid` を足して直した。

    **1 件目（`match_params`）とは別の欄・別の原因である。**`K_smoke_ANKO` だけを回していた
    ころは踏まなかった——だから上の毎手一致は仮デッキ 3 種すべてを回すようにした。
    """
    rs = pytest.importorskip("meicho_rs")
    import json as _json

    from meicho.cards_export import cards_json
    from meicho.engine import (GameConfig, apply, decision_players, initial_state,
                               outcome)
    from meicho.agents import RandomAgent

    rs.load_cards(cards_json())
    with open(os.path.join(_ROOT, "decklists", "K_smoke_TSUBAKI.json"), encoding="utf-8") as f:
        d = _json.load(f)
    config = GameConfig(chara_decks=[d["chara_deck"]] * 2,
                        action_decks=[d["action_deck"]] * 2)

    def norm(x):
        return _json.loads(_json.dumps(x, ensure_ascii=False))

    # 踏むシードは実装の変更で動く（D-094 で誘発範囲を直したときに 37・39 が外れた）。
    # **固定のシードに頼らず、踏むまで探す。**踏まなければ最後の assert で落ちる。
    seen = 0
    for seed in range(40):
        if seen:
            break
        py = initial_state(config, seed)
        rss = rs.initial_state(config.chara_decks, config.action_decks, seed)
        agents = [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)]
        while outcome(py) is None and py.turn_no <= 200:
            a = norm(_json.loads(py.to_json()))
            b = _json.loads(rss.to_json())
            pe_py, pe_rs = a.get("pending_effect"), b.get("pending_effect")
            if pe_py and pe_rs and pe_py.get("ops") and pe_rs.get("ops"):
                op_py, prm_py = pe_py["ops"][0]
                op_rs, prm_rs = pe_rs["ops"][0]
                if op_py == "pay_cost_return_self_to_hand":
                    seen += 1
                    assert prm_py == prm_rs, (
                        "pay_cost_return_self_to_hand の params が食い違う（B-8 の 2 件目）: "
                        f"Python={prm_py} / Rust={prm_rs}")
            need = decision_players(py)
            acts = {pi: agents[pi].act(py, pi) for pi in need}
            py = apply(py, acts)
            rss = rs.apply(rss, {pi: norm(a2) for pi, a2 in acts.items()})
    assert seen > 0, "pay_cost_return_self_to_hand を 1 度も踏んでいない＝この検査は何も守っていない"


def test_the_smoke_deck_actually_exercises_the_new_machinery():
    """仮デッキの対局が＜音骸＞と乱数オペコードを**実際に踏んでいる**こと。

    踏んでいない検査は通っても何も守らない。ここは上の毎手一致の「効き目」の確認である。
    """
    import json as _json

    from meicho.engine import (GameConfig, apply, decision_players, initial_state,
                               legal_actions, outcome)
    from meicho.agents import RandomAgent

    with open(os.path.join(_ROOT, "decklists", "K_smoke_ANKO.json"), encoding="utf-8") as f:
        d = _json.load(f)
    config = GameConfig(chara_decks=[d["chara_deck"]] * 2,
                        action_decks=[d["action_deck"]] * 2)
    onkai_used = 0
    blocked = 0
    rng_used = 0
    for seed in range(8):
        s = initial_state(config, seed)
        agents = [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)]
        before_rng = s.rng_calls
        while outcome(s) is None and s.turn_no <= 200:
            for pi in (0, 1):
                area = s.players[pi].action_area
                if any(ONKAI_TAG in ACTION_CARDS[c].tags for c in area):
                    onkai_used += 1
                    # 音骸が場にある間、手札の別の音骸は合法手から外れているはず
                    if any(ONKAI_TAG in ACTION_CARDS[c].tags for c in s.players[pi].hand):
                        subs = {a.get("hand") for a in legal_actions(s, pi)
                                if a["type"] in ("submit", "rush")}
                        if not any(ONKAI_TAG in ACTION_CARDS[s.players[pi].hand[i]].tags
                                   for i in subs if i is not None):
                            blocked += 1
            need = decision_players(s)
            s = apply(s, {pi: agents[pi].act(s, pi) for pi in need})
        rng_used += s.rng_calls - before_rng
    assert onkai_used > 0, "＜音骸＞が 1 度もアクションエリアに出ていない"
    assert blocked > 0, "2 枚目を止める場面が 1 度も起きていない（u5 を踏んでいない）"
    assert rng_used > 0
