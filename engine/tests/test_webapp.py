"""対人検証アプリの検査（APP_DESIGN.md §7・段階1）。

アプリはルールを持たないので、ここで検査するのは「ルールの正しさ」ではなく
**アプリがエンジンを正しく仲介しているか**である。守るべき不変条件は 3 つ。

1. **記録した対局を再生すると同じ結果になる**（記録の完全性・エンジンの決定性・
   アプリがエンジンを迂回していないことが同時に保証される。§6.2）
2. **公平性**: AI は人間の提出を見ていない。画面に隠蔽情報が乗らない（§2.2 / §2.3）
3. **入力の健全性**: 合法手以外を送れない。詰まらない（§7.3）
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

import pytest

from arena import load_deck, mirror_config
from meicho.state import Phase
from webapp import agents, record
from webapp.session import IllegalMove, Session, StaleView

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]
SEED0 = 130000        # seed_bands.json に登録済み（アプリ専用帯）


def make_session(seed=SEED0, human_seat=0, opponent="heuristic", ai_seed=None):
    ai_seed = seed * 2 + (1 - human_seat) if ai_seed is None else ai_seed
    return Session(f"t{seed}", CONFIG, POOL, seed, human_seat, opponent,
                   agents.build(opponent, POOL, ai_seed), ai_seed)


def drive(sess, rng_seed=7, stop_phase=None, max_moves=4000):
    """疑似「人間」で対局を進める。stop_phase が来たらそこで止める。"""
    rng = random.Random(rng_seed)
    for _ in range(max_moves):
        if sess.finished:
            return sess
        acts = sess.legal()
        if not acts:
            raise AssertionError(f"入力待ちでないのに止まった: {sess.state.phase}")
        if stop_phase is not None and sess.state.phase == stop_phase:
            return sess
        sess.play(rng.randrange(len(acts)), sess.ply)
    raise AssertionError("対局が終わらない")


# --- 1. 記録と再生 ---------------------------------------------------------

def test_recorded_game_replays_to_the_same_result():
    """§6.2: 記録した対局を再生すると勝敗・ターン数・ライフが一致すること。

    ここが通れば、記録に漏れがないこと・エンジンが決定的であること・
    アプリがエンジンを迂回していないことが同時に保証される。
    """
    for i, opp in enumerate(("heuristic", "planner")):
        s = drive(make_session(SEED0 + i, i % 2, opp))
        assert not s.error, s.error
        rec = record.to_record(s)
        got = record.verify(rec, CONFIG)          # 食い違えば例外
        assert got["turns"] == s.result()["turns"]


def test_replay_detects_a_broken_record():
    """記録が壊れていれば、黙って通らずに失敗すること。"""
    s = drive(make_session(SEED0 + 5))
    rec = record.to_record(s)
    rec["actions"] = rec["actions"][:-4]          # 末尾を削って壊す
    with pytest.raises(record.RecordMismatch):
        record.verify(rec, CONFIG)


def test_record_is_json_serialisable_and_has_what_replay_needs():
    s = drive(make_session(SEED0 + 6), max_moves=40, stop_phase=None) \
        if False else drive(make_session(SEED0 + 6))
    rec = record.to_record(s)
    json.dumps(rec, ensure_ascii=False)
    assert set(rec) >= {"seed", "human_seat", "actions", "result",
                        "rules_version", "engine_version", "deck"}
    for row in rec["actions"]:
        assert set(row) >= {"ply", "turn", "phase", "by", "seat", "action"}


# --- 2. 公平性 -------------------------------------------------------------

def test_ai_choice_does_not_depend_on_the_human_submission():
    """§2.3: 同時提出で、AI の手が人間の提出内容に左右されないこと。

    同一のシードで 2 つの対局を対抗ステップまで同じ手順で進め、
    そこで**人間だけ違う手**を出す。AI の提出が変われば、
    AI が人間の手を覗いている（＝同時提出が壊れている）。
    """
    checked = 0
    for i in range(6):
        seed = SEED0 + 100 + i
        a = drive(make_session(seed, 0, "planner"), stop_phase=Phase.CLASH_SUBMIT)
        if a.finished or len(a.legal()) < 2:
            continue
        b = drive(make_session(seed, 0, "planner"), stop_phase=Phase.CLASH_SUBMIT)
        ply = a.ply
        a.play(0, a.ply)
        b.play(1, b.ply)                       # 人間だけ別の手
        ai_a = [r for r in a.actions if r["ply"] >= ply and r["by"] == "ai"]
        ai_b = [r for r in b.actions if r["ply"] >= ply and r["by"] == "ai"]
        assert ai_a and ai_b
        assert ai_a[0]["action"] == ai_b[0]["action"], (
            "AI の提出が人間の提出で変わった（同時提出が壊れている）")
        checked += 1
    assert checked >= 2, "対抗ステップでの比較が十分に行われていない"


def _public_ids(sess):
    """人間から見て公開されているカードIDの多重集合。"""
    st = sess.state
    me, opp = st.players[sess.human_seat], st.players[1 - sess.human_seat]
    out = list(me.hand) + list(me.concerto) + list(me.trash) + list(me.action_area)
    out += list(me.action_deck)                        # 自分のデッキの中身は既知
    out += list(opp.concerto) + list(opp.trash) + list(opp.action_area)
    return out


def test_snapshot_never_contains_hidden_information():
    """§2.2: 画面に送る内容に、相手の手札や山札の中身が現れないこと。"""
    for i in range(4):
        s = make_session(SEED0 + 200 + i, i % 2, "planner")
        rng = random.Random(11 + i)
        for _ in range(60):
            if s.finished:
                break
            snap = json.dumps(s.snapshot(), ensure_ascii=False)
            opp = s.state.players[1 - s.human_seat]
            public = _public_ids(s)
            for cid in set(opp.hand) | set(opp.action_deck):
                if cid in public:
                    continue                    # 同名のカードが公開領域にもある
                assert f'"{cid}"' not in snap, (
                    f"隠蔽情報 {cid} が画面に漏れている")
            acts = s.legal()
            if not acts:
                break
            s.play(rng.randrange(len(acts)), s.ply)


def test_ai_actions_are_logged_without_naming_face_down_cards():
    """対抗の提出は裏向き（§6.4(1)-1）。ログが解決前に名前を出さないこと。

    ログは「AI の行動は動詞だけ、カード名は公開領域から」という規則で作る。
    その規則が守られていることを、対抗提出の行に対して確かめる。
    """
    s = drive(make_session(SEED0 + 300, 0, "planner"))
    subs = [ln for ln in s.log if ln.startswith("CPU: 対抗カードを提出")]
    assert subs, "対抗の提出が1度も無い対局では検査にならない"
    for ln in subs:
        assert "SD001-" not in ln, f"裏向きの提出でカード名が出ている: {ln}"


# --- 3. 入力の健全性 -------------------------------------------------------

def test_illegal_index_is_rejected():
    s = make_session(SEED0 + 400)
    with pytest.raises(IllegalMove):
        s.play(999, s.ply)
    with pytest.raises(IllegalMove):
        s.play(-1, s.ply)


def test_stale_view_is_rejected():
    """二重送信よけ: 画面が古いまま送られた手は拒否されること。"""
    s = make_session(SEED0 + 401)
    with pytest.raises(StaleView):
        s.play(0, s.ply - 1)


def test_legal_order_is_stable():
    """§4.2: 画面の番号と適用される手がずれないこと。

    `snapshot` と `play` は同じ `legal()` を通る。順序が呼ぶたびに変わると
    「1 を押したのに別の手が指された」という取り返しのつかない事故になる。
    """
    s = make_session(SEED0 + 402)
    for _ in range(20):
        if s.finished:
            break
        a = [x["type"] for x in s.legal()]
        b = [x["type"] for x in s.legal()]
        snap = [x["label"] for x in s.snapshot()["legal"]]
        assert a == b
        assert len(snap) == len(a)
        if not a:
            break
        s.play(0, s.ply)


def test_human_always_has_a_legal_move_until_the_game_ends():
    """どの局面でも人間側に必ず 1 つ以上の合法手がある（詰まらない）。"""
    for i in range(3):
        s = drive(make_session(SEED0 + 500 + i, i % 2, "greedy"), rng_seed=3 + i)
        assert not s.error, s.error
        assert s.finished


def test_forced_moves_are_applied_automatically_and_recorded():
    """§4.2: 合法手が 1 つだけの場面は自動で通し、記録に残ること。"""
    found = False
    for i in range(4):
        s = drive(make_session(SEED0 + 600 + i, 0, "heuristic"), rng_seed=5 + i)
        auto = [r for r in s.actions if r["by"] == "human" and r["auto"]]
        if auto:
            found = True
            break
    assert found, "自動適用が一度も起きていない（検査が無効）"


def test_view_labels_every_legal_action():
    """すべての合法手に日本語の説明が付くこと（生の JSON を出さない）。"""
    for i in range(3):
        s = make_session(SEED0 + 700 + i, i % 2, "greedy")
        rng = random.Random(13 + i)
        for _ in range(50):
            if s.finished:
                break
            for a in s.snapshot()["legal"]:
                assert a["label"] and not a["label"].startswith("{"), a
            acts = s.legal()
            if not acts:
                break
            s.play(rng.randrange(len(acts)), s.ply)


# --- 4. エンジンへの渡し方 -------------------------------------------------

def test_actions_are_passed_to_the_engine_in_seat_order():
    """`apply` に渡す行動の辞書を、必ず席の昇順で組むこと。

    **エンジンは `actions` 辞書の挿入順に依存する**（`_apply_inner` が
    `actions.items()` を回すため、マリガン等のシャッフルが消費する乱数の順序が
    入れ替わる）。既存の呼び出し側はすべて席の昇順で組んでおり、
    アプリだけ「人間の手を先に入れる」順にしていたため、記録の再生が食い違った。

    この検査は**アプリ側の規律**を固定する。エンジン側の脆さは別途の課題である。
    """
    from meicho.engine import apply as _apply
    seen = []

    def spy(state, actions):
        seen.append(list(actions.keys()))
        return _apply(state, actions)

    import webapp.session as sess_mod
    orig, sess_mod.apply = sess_mod.apply, spy
    try:
        drive(make_session(SEED0 + 800, 1, "heuristic"), rng_seed=9)
    finally:
        sess_mod.apply = orig
    assert seen, "apply が一度も呼ばれていない"
    for keys in seen:
        assert keys == sorted(keys), f"席の昇順で渡していない: {keys}"


# --- 5. 表示（覚えていなくても分かること） -------------------------------

def test_every_skill_renders_as_japanese_not_as_opcodes():
    """全カードの全スキルが日本語になること。

    `view.skill_text` は**エンジンのオペコード列**を言い換える。未対応の
    オペコードが増えると生の `{'count': 1}` が画面に出てしまうので、
    そうなっていないことを全カードに対して確かめる。
    （＝新しい効果を実装したらこの検査が落ちて、訳を書けと言ってくる。）
    """
    from meicho.cards import ACTION_CARDS, CHARA_CARDS
    from webapp import view
    n = 0
    for table in (ACTION_CARDS, CHARA_CARDS):
        for cid, c in table.items():
            for sk in c.skills:
                t = view.skill_text(sk)
                assert t and "{" not in t and "'" not in t, (
                    f"{cid} のスキルが日本語になっていない: {t}")
                n += 1
    assert n > 20, "検査したスキルが少なすぎる"


def test_chara_overview_always_shows_the_whole_chara_deck():
    """§3.1: 自分のキャラデッキは自分にとって公開情報。

    `observe` の `chara_deck` は**まだ場に出していない残り**なので、
    レベルアップした分が消えて見える。画面用の一覧は
    「残り＋場に重なっている分」で、**常にキャラデッキ全体と一致**すること。
    """
    from webapp import view
    want = sorted(CONFIG.chara_decks[0])
    s = make_session(SEED0 + 900, 0, "planner")
    rng = random.Random(21)
    seen_on_field = False
    for _ in range(120):
        if s.finished:
            break
        b = s.snapshot()["board"]
        got = sorted(c["id"] for row in b["me"]["chara_overview"]
                     for c in row["levels"])
        assert got == want, "キャラデッキ一覧が全体と一致しない"
        if any(c["where"] != "キャラデッキ" for row in b["me"]["chara_overview"]
               for c in row["levels"]):
            seen_on_field = True
        acts = s.legal()
        if not acts:
            break
        s.play(rng.randrange(len(acts)), s.ply)
    assert seen_on_field, "場に出たキャラが1枚も無い（検査が無効）"


def test_mulligan_is_a_free_choice_of_which_cards_to_return():
    """§4.2: マリガンを「1枚ごとに入切する」画面にできること。

    画面はカードごとの入切だけを集め、**その組み合わせに一致する合法手**を
    探して送る。したがって「手札の任意の部分集合それぞれに、合法手が
    ちょうど 1 つ対応する」ことが前提になる。それをここで固定する。
    """
    s = make_session(SEED0 + 901)
    while s.state.phase != Phase.MULLIGAN and not s.finished:
        s.play(0, s.ply)
    acts = s.legal()
    assert acts and all(a["type"] == "mulligan" for a in acts)
    hand = len(s.state.players[s.human_seat].hand)
    assert len(acts) == 1 << hand, "部分集合が全部そろっていない"
    keys = [tuple(sorted(a["cards"])) for a in acts]
    assert len(set(keys)) == len(keys), "同じ組み合わせの合法手が重複している"
    for a in acts:
        assert all(0 <= i < hand for i in a["cards"])
    # 画面が添字を引けること（snapshot が生の行動を持っていること）
    legal = s.snapshot()["legal"]
    assert all("action" in x for x in legal)
    assert {tuple(sorted(x["action"]["cards"])) for x in legal} == set(keys)


def test_peeked_opponent_hand_reaches_the_screen():
    """スキャン等で確認した相手の手札が、画面用データに載ること。

    エンジンは覗いた内容を `observe` の `opp.hand_known` で返す（D-023）。
    **これは推測ではなく確定した情報**なので、出さないのは情報の取りこぼしである。
    実際、段階1 では `view.board` まで来ていたのに画面が描いていなかった。
    その取りこぼしを二度と起こさないための検査である。
    """
    from meicho.engine import observe
    found = False
    for i in range(12):
        s = make_session(SEED0 + 1000 + i, i % 2, "planner")
        rng = random.Random(31 + i)
        for _ in range(200):
            if s.finished:
                break
            ob = observe(s.state, s.human_seat)
            if ob["opp"]["hand_known"]:
                snap = s.snapshot()
                got = [c["id"] for c in snap["board"]["opp"]["hand_known"]]
                assert got == sorted(ob["opp"]["hand_known"]), (
                    "確認した相手の手札が画面用データに載っていない")
                found = True
                break
            acts = s.legal()
            if not acts:
                break
            s.play(rng.randrange(len(acts)), s.ply)
        if found:
            break
    assert found, "相手の手札を確認する効果が1度も起きていない（検査が無効）"


# --- 6. 対局後レビュー（全情報）-------------------------------------------

def test_review_reconstructs_every_recorded_decision():
    """§5: レビューが記録の全手を局面に対応づけられること。

    同時提出は 1 回の `apply` で 2 手ぶん進むので、単純に「1 手 = 1 局面」と
    数えるとずれる。ずれると「この手のときの盤面」が 1 つ手前になり、
    レビューでの指摘が的外れになる。ここが本質的な検査である。
    """
    from webapp import review
    s = drive(make_session(SEED0 + 950, 0, "planner"))
    assert not s.error, s.error
    rec = record.to_record(s)
    rv = review.build(rec, CONFIG)
    got = sum(len(st["decisions"]) for st in rv["steps"])
    assert got == len(rec["actions"]), (
        f"対応づけが合わない: レビュー {got} / 記録 {len(rec['actions'])}")
    # 記録された行動そのものが、同じ順で並んでいること
    flat = [d["action"] for st in rv["steps"] for d in st["decisions"]]
    assert flat == [r["action"] for r in rec["actions"]]


def test_review_sees_both_hands_but_only_from_a_record():
    """§5.7: レビューは**全情報**を持つ。だからこそ記録からしか作れない。

    ここでは「全情報が実際に入っていること」を確かめる。
    入っていなければレビューの意味が無い（対局中と同じ情報しか見えない）。
    対局中の画面に漏れていないことは
    `test_snapshot_never_contains_hidden_information` が別に担保する。
    """
    from webapp import review
    s = drive(make_session(SEED0 + 951, 1, "greedy"))
    rv = review.build(record.to_record(s), CONFIG)
    assert any(st["opp"]["hand"] for st in rv["steps"]), "相手の手札が入っていない"
    assert any(st["opp"]["deck_top"] for st in rv["steps"]), "山札の上が入っていない"
    # レビューは Session ではなく記録を受け取る（構造として進行中は作れない）
    with pytest.raises(Exception):
        review.build(s, CONFIG)


def test_review_output_is_readable_not_raw_json():
    from webapp import review
    s = drive(make_session(SEED0 + 952, 0, "heuristic"))
    rv = review.build(record.to_record(s), CONFIG)
    txt = review.to_text(rv)
    assert txt and all(not ln.startswith("{") for ln in txt)
    html = review.to_html(rv, {(1, "action", "human"): "テストの注記"})
    assert "<html" in html and "テストの注記" in html
    assert "{'type'" not in html, "生の行動辞書が HTML に出ている"


def test_both_decks_can_be_played_and_are_recorded(tmp_path):
    """D-048: デッキを選べること、そして**どのデッキの記録かが残る**こと。

    人間の基準値はデッキごとに別物である。SD001 の記録と SD02 の記録を
    混ぜて勝率を出したら、その数字は何も意味しない。
    `record.to_record` の `deck` と画面の `deck` が一致することを固定する。
    """
    from webapp.server import DECKS, App
    assert set(DECKS) >= {"SD001", "SD02"}
    for name in DECKS:
        app = App(name)
        s = app.new_game("heuristic", deck_name=name)
        rng = random.Random(17)
        for _ in range(4000):
            if s.finished:
                break
            acts = s.legal()
            if not acts:
                break
            s.play(rng.randrange(len(acts)), s.ply)
        assert s.finished and not s.error, s.error
        assert s.snapshot()["deck"] == name
        rec = record.to_record(s)
        assert rec["deck"] == name
        record.verify(rec, app.config)      # 食い違えば例外


def test_engine_is_independent_of_action_dict_order():
    """【D-050】同じ行動なら辞書の挿入順に関係なく同じ結果になること。

    D-040 で見つかった順序依存（`_apply_inner` が `actions.items()` の順でシャッフルの
    乱数を消費していた）を、席の昇順で処理する形に直した。Rust 版（D-049）と同じ規約。
    直す前の fingerprint 3 種（905073e2e202bd39 / 7cfceac12f2c070f / 1f5e2e218cc54acc）は不変。
    """
    from meicho.engine import apply, initial_state
    s = initial_state(CONFIG, SEED0 + 1)
    s = apply(s, {0: {"type": "setup", "leader": "漂泊者（女）"},
                  1: {"type": "setup", "leader": "熾霞"}})
    a0 = {"type": "mulligan", "cards": [4]}
    a1 = {"type": "mulligan", "cards": [0, 3]}
    x = apply(s, {0: a0, 1: a1})
    y = apply(s, {1: a1, 0: a0})
    assert x.rng_calls == y.rng_calls
    assert x.to_json() == y.to_json()
    # 準備段階（両者同時のキャラ配置）と対抗の提出でも同じ
    t = initial_state(CONFIG, SEED0 + 2)
    u = apply(t, {0: {"type": "setup", "leader": "秧秧"}, 1: {"type": "setup", "leader": "熾霞"}})
    v = apply(t, {1: {"type": "setup", "leader": "熾霞"}, 0: {"type": "setup", "leader": "秧秧"}})
    assert u.to_json() == v.to_json()


# --- ログの書き分け（D-063 v4） -------------------------------------------
# **同じ「トラッシュに置かれた」でも意味が違う。** 連撃や対抗では
# コストに払った札と使った札が同じトラッシュに並ぶので、読めなくなっていた。

from webapp.session import card_moves                              # noqa: E402


def _ob(hand=(), concerto=(), area=(), trash=(), hand_count=None):
    d = {"hand": list(hand), "concerto": list(concerto),
         "action_area": list(area), "trash": list(trash)}
    if hand_count is not None:
        d["hand_count"] = hand_count
    return d


def test_a_card_paid_as_cost_is_told_apart_from_a_card_that_was_used():
    """協奏エリアから減って→トラッシュ = コスト。場から減って→トラッシュ = 使用済み。"""
    b = {"me": _ob(hand=["A"], concerto=["C"], area=["U"], trash=[])}
    a = {"me": _ob(hand=["A"], concerto=[], area=[], trash=["C", "U"])}
    moves = dict(card_moves(b, a, "me"))
    assert "コストとして支払った" in moves["C"]
    assert "使い終わって" in moves["U"]


def test_a_card_discarded_from_hand_says_so():
    b = {"me": _ob(hand=["A", "B"], trash=[])}
    a = {"me": _ob(hand=["A"], trash=["B"])}
    assert "手札から捨てた" in dict(card_moves(b, a, "me"))["B"]


def test_playing_a_card_says_it_came_from_the_hand():
    b = {"me": _ob(hand=["A"], area=[])}
    a = {"me": _ob(hand=[], area=["A"])}
    assert "手札から場に出した" in dict(card_moves(b, a, "me"))["A"]


def test_a_card_put_into_concerto_from_the_deck_is_not_called_a_charge():
    """デッキの上から協奏エリアに置かれた札は、チャージではない（効果）。"""
    b = {"me": _ob(hand=["A"], concerto=[])}
    a = {"me": _ob(hand=["A"], concerto=["X"])}
    assert "デッキから協奏エリアへ" in dict(card_moves(b, a, "me"))["X"]


def test_the_opponent_hand_is_never_invented_as_a_source():
    """相手の手札は観測に写らない。**枚数が減っていなければ手札とは書かない。**"""
    b = {"opp": _ob(concerto=[], area=[], trash=[], hand_count=5)}
    a = {"opp": _ob(concerto=[], area=[], trash=["Z"], hand_count=5)}
    assert dict(card_moves(b, a, "opp"))["Z"] == "がトラッシュへ"
    # 枚数が減っていれば「手札から」と言ってよい（枚数は公開情報）
    a2 = {"opp": _ob(concerto=[], area=[], trash=["Z"], hand_count=4)}
    assert "手札から捨てた" in dict(card_moves(b, a2, "opp"))["Z"]


def test_a_real_game_shows_both_cost_and_used_lines():
    """実際の対局で、コストの支払いと使用済みの両方がログに出ること。"""
    sess = drive(make_session(), rng_seed=7)
    text = "\n".join(sess.log)
    assert "をコストとして支払った" in text
    assert "が使い終わってトラッシュへ" in text
    assert "を手札から捨てた" in text
    # 出どころを書かない古い形（どれがどれか分からない書き方）が残っていないこと
    assert "のトラッシュに " not in text
