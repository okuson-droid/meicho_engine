"""進行（`app/core/game.py`）と視点（`app/core/views.py`）の検査。通信なし。"""
import json
import random

import pytest

from app.core.game import Game, check_deck
from app.core.protocol import AppError
from app.core.views import SPECTATOR, card_ids_in, view_for
from app.tests.conftest import random_deck
from meicho import decision_players
from meicho.state import Phase

VIEWERS = (0, 1, SPECTATOR)


def snapshot(g: Game) -> str:
    return json.dumps([g.dump(), g.tokens, sorted(g._open)], sort_keys=True)


def play_random(g: Game, rnd: random.Random, on_step=None, limit=5000):
    n = 0
    while not g.over:
        p = rnd.choice(g.awaiting())
        before = {v: card_ids_in(view_for(g.state, v)) for v in VIEWERS}
        events = g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))
        if on_step:
            on_step(g, before, events)
        n += 1
        assert n < limit
    return n


def test_clash_order_turn_player_first(sd001):
    """要件 R-CLASH-1〜3・公式 604.1.1: 非ターンプレイヤーの入力は、ターンプレイヤーが置くまで開かない。"""
    seen = 0
    for seed in range(8):
        g, rnd = Game([sd001, sd001], seed), random.Random(seed)
        while not g.over:
            if g.state.phase == Phase.CLASH_SUBMIT and set(decision_players(g.state)) == {0, 1} and not g.held:
                tp = g.state.turn_player
                assert g.awaiting() == [tp]
                with pytest.raises(AppError) as e:
                    g.submit(1 - tp, g.tokens[1 - tp], 0)
                assert e.value.code == "not_awaited"
                tok_before = g.tokens[1 - tp]
                ev = g.submit(tp, g.tokens[tp], rnd.randrange(len(g.legal(tp))))
                assert g.awaiting() == [1 - tp] and g.tokens[1 - tp] == tok_before + 1
                # 相手と観戦者に届くのは「置いた」という事実だけ。カード番号は無い
                for v in VIEWERS:
                    assert ev[v] and all(x["t"] in ("placed", "submitted") for x in ev[v])
                    assert not card_ids_in(ev[v])
                assert g.view(1 - tp)["submitted"] == [tp]
                seen += 1
                continue
            p = rnd.choice(g.awaiting())
            g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))
    assert seen > 50


def test_bad_input_never_changes_state(sd001, sd02):
    """要件 R-NET-5・R-NF-11: 古い番号・二重送信・範囲外・手番でない席は弾き、状態は 1 ビットも動かない。"""
    g, rnd = Game([sd001, sd02], 3), random.Random(3)
    checked = 0
    while not g.over and checked < 300:
        p = rnd.choice(g.awaiting())
        tok, snap = g.tokens[p], snapshot(g)
        bads = [(p, tok - 1, 0, "stale"), (p, tok + 1, 0, "stale"), (p, None, 0, "stale"),
                (p, tok, -1, "bad_index"), (p, tok, 10 ** 6, "bad_index"), (p, tok, True, "bad_index"),
                (p, tok, "0", "bad_index"), (p, tok, 1.0, "bad_index"), (p, tok, None, "bad_index"),
                (2, tok, 0, "not_seated"), ("spec", tok, 0, "not_seated"), (None, tok, 0, "not_seated")]
        if 1 - p not in g.awaiting():
            bads.append((1 - p, g.tokens[1 - p], 0, "not_awaited"))
        for seat, t, i, code in bads:
            with pytest.raises(AppError) as e:
                g.submit(seat, t, i)
            assert e.value.code == code
            assert snapshot(g) == snap
        g.submit(p, tok, rnd.randrange(len(g.legal(p))))
        snap = snapshot(g)
        with pytest.raises(AppError) as e:                   # 二重送信: 同じ番号は二度と通らない
            g.submit(p, tok, 0)
        assert e.value.code in ("stale", "not_awaited") and snapshot(g) == snap
        checked += 1
    assert checked == 300 or g.over


def test_no_hidden_card_reaches_other_viewers():
    """要件 R-SEC-1〜3・R-SPEC-1: 出来事に載るカード番号は、その相手の視点（前か後）に写っているものだけ。

    デッキはカードプール全体から無作為に組む（SD001・SD02・BP01 が混ざる・要件 R-EXT-12）。
    """
    stats = {"events": 0, "games": 0, "shows": 0, "private_shows": 0}

    def check(g, before, events):
        for v in VIEWERS:
            # その相手に見えてよいカード番号 = apply の間の各時点で、その相手の観測に写っていたもの。
            # それ以外で許されるのは、エンジンが「公開」と知らせ、宛先にその相手が入っているものだけ（APP-003）
            allowed = before[v] | card_ids_in(view_for(g.state, v))
            for frame in g.last_frames.get(v, []):
                allowed |= card_ids_in(frame)
            plain = [e for e in events[v] if e["t"] != "show"]
            shows = [e for e in events[v] if e["t"] == "show"]
            for e in shows:                                     # 公開されたカードは、そのあと「手札にあると知られている」としても出てくる
                allowed |= set(e["cards"])
            leaked = card_ids_in(plain) - allowed
            assert not leaked, (v, leaked)
            want = [r["cards"] for r in g.last_reveals if r["audience"] in ("all", v)] if shows or g.last_reveals else []
            assert [e["cards"] for e in shows] == want, (v, shows, g.last_reveals)
            stats["events"] += len(events[v])
            stats["shows"] += len(shows)
            stats["private_shows"] += sum(1 for r in g.last_reveals if r["audience"] != "all") if v == SPECTATOR else 0
        g.last_reveals = []
        sv = g.view(SPECTATOR)
        for pi, pl in enumerate(sv["players"]):
            assert pl["hand"] is None and pl["chara_deck"] is None
            # 観戦者に見える「相手の手札」は、全員に公開されて手札に入ったカードだけ。スキャンで片方だけが知ったカードは入らない（R-SPEC-1）
            assert pl["hand_known"] == sorted(g.public_known[pi].elements())
        assert sv["choice"] is None and "legal" not in sv and "token" not in sv
        for pi in (0, 1):
            opp = g.view(pi)["players"][1 - pi]
            assert opp["hand"] is None and opp["chara_deck"] is None

    for seed in range(40):
        rnd = random.Random(1000 + seed)
        g = Game([random_deck(rnd), random_deck(rnd)], seed)
        play_random(g, rnd, check)
        stats["games"] += 1
    assert stats["games"] == 40 and stats["events"] > 10000
    assert stats["shows"] > 0 and stats["private_shows"] > 0, stats      # 全員への公開も、片方の席だけへの公開（スキャン）も実際に起きた


def test_spectator_view_is_subset_of_both_seats(sd001, sd02):
    """観戦者に見えるカード番号は、両方の席に見えているものだけ（片方しか知らない情報は入らない）。"""
    def check(g, before, events):
        spec = card_ids_in(view_for(g.state, SPECTATOR))
        assert spec <= card_ids_in(view_for(g.state, 0)) & card_ids_in(view_for(g.state, 1))

    for seed in range(10):
        play_random(Game([sd001, sd02], seed), random.Random(seed), check)


def test_dump_load_roundtrip(sd001, sd02):
    """要件 R-NET-6・R-DATA-1: シード＋デッキ＋行動列から、提出の途中も含めて同じ状態に戻る。"""
    g, rnd = Game([sd02, sd001], 11), random.Random(11)
    n = 0
    while not g.over:
        p = rnd.choice(g.awaiting())
        g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))
        n += 1
        if n % 7 == 0 or g.held:
            g2 = Game.load(json.loads(json.dumps(g.dump())))
            assert g2.held == g.held and g2.awaiting() == g.awaiting()
            for v in VIEWERS:
                assert view_for(g2.state, v) == view_for(g.state, v)
            assert [g2.legal(p) for p in (0, 1)] == [g.legal(p) for p in (0, 1)]
    g2 = Game.load(json.loads(json.dumps(g.dump())))
    assert g2.result() == g.result()


def test_load_rejects_tampered_record(sd001):
    g, rnd = Game([sd001, sd001], 5), random.Random(5)
    for _ in range(30):
        p = rnd.choice(g.awaiting())
        g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))
    d = json.loads(json.dumps(g.dump()))
    d["applies"][10] = {"0": {"type": "no_such_action"}, "1": {"type": "no_such_action"}}
    with pytest.raises(AppError) as e:
        Game.load(d)
    assert e.value.code == "bad_record"


def test_resign(sd001):
    g = Game([sd001, sd001], 1)
    ev = g.resign(1)
    assert g.over and g.result() == {**g.result(), "winner": 0, "reason": "resign"}
    assert ev[SPECTATOR][0]["t"] == "game_over"
    with pytest.raises(AppError):
        g.submit(0, g.tokens[0], 0)
    g2 = Game.load(g.dump())
    assert g2.over and g2.result()["winner"] == 0


def test_check_deck(sd001):
    check_deck(sd001)
    for bad in (None, [], {}, {"chara_deck": "x", "action_deck": []},
                {**sd001, "action_deck": sd001["action_deck"][:39]},
                {**sd001, "action_deck": sd001["action_deck"][:39] + ["NOPE-999"]},
                {**sd001, "chara_deck": sd001["chara_deck"][:2]},
                {**sd001, "action_deck": [sd001["action_deck"][0]] * 40},
                {**sd001, "action_deck": sd001["action_deck"][:39] + [123]}):
        with pytest.raises(AppError) as e:
            check_deck(bad)
        assert e.value.code == "bad_deck"


def test_hints_and_labels(sd001, sd02):
    """要件 R-PLAY-4・R-PLAY-11: 理由は「合法手に無い所作」にだけ付く。ラベルは合法手と同じ数。観戦者には手札の理由が無い。"""
    seen = {"clash": 0, "rush": 0, "charge": 0, "wait": 0}
    for seed in range(12):
        g, rnd = Game([sd001, sd02], seed), random.Random(seed)
        while not g.over:
            for pi in (0, 1):
                v = g.view(pi)
                hints, legal = v["hints"], v["legal"]
                assert len(v["labels"]) == len(legal) and all(isinstance(x, str) and x for x in v["labels"])
                if pi not in g.awaiting():
                    assert hints["general"] and not hints["hand"] and not legal
                    seen["wait"] += 1
                    continue
                kinds = {a["type"] for a in legal}
                for key in ("charge", "switch", "levelup"):
                    if key in kinds:
                        assert hints[key] is None
                if v["phase"] == "action":
                    assert all((hints[k] is None) == (k in kinds) for k in ("charge", "switch", "levelup"))
                    seen["charge"] += hints["charge"] is not None
                if v["phase"] in ("clash_submit", "rush"):
                    ok = {a["hand"] for a in legal if a["type"] in ("submit", "rush")}
                    n = len(v["players"][pi]["hand"])
                    assert set(hints["hand"]) == set(range(n)) - ok
                    assert all(isinstance(t, str) and t for t in hints["hand"].values())
                    seen["clash" if v["phase"] == "clash_submit" else "rush"] += len(hints["hand"])
            sv = g.view(SPECTATOR)
            assert sv["hints"]["hand"] == {} and "labels" not in sv and "my_held" not in sv
            p = rnd.choice(g.awaiting())
            g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))
    assert all(n > 0 for n in seen.values()), seen


def test_events_come_in_the_order_they_happened(sd001, sd02):
    """要件 R-FX-1・R-CLASH-4: 出来事は、エンジンのトレース点（TA-7）ごとの差分をつないだもので、起きた順に並ぶ。"""
    from app.core.views import _choreograph

    # 1 つの差分の中の並べ替えは、順序だけを変える
    mixed = [{"t": "phase", "phase": "x"}, {"t": "life", "player": 0, "delta": -1, "value": 1}, {"t": "judge", "winner": 1},
             {"t": "move", "player": 0, "card": "A", "from": "concerto", "to": "trash"},
             {"t": "move", "player": 0, "card": "B", "from": "hand", "to": "action_area"}]
    out = _choreograph(list(mixed), {"turn_player": 0})
    assert [e["t"] for e in out] == ["move", "move", "judge", "life", "phase"] and out[0]["card"] == "B"
    assert sorted(map(str, out)) == sorted(map(str, mixed))

    seen = {"judge": 0, "turn_draw": 0, "cleanup": 0, "frames": 0}
    for seed in range(6):
        g, rnd = Game([sd001, sd02], seed), random.Random(seed)
        while not g.over:
            p = rnd.choice(g.awaiting())
            n = len(g.applies)
            ev = g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))[SPECTATOR]
            if len(g.applies) > n:
                seen["frames"] += len(g.last_frames[SPECTATOR]) > 2          # 解決の途中の盤面が取れている＝トレース点が効いている
            kinds = [e["t"] for e in ev]
            if "judge" in kinds:
                seen["judge"] += 1
                placed = [i for i, e in enumerate(ev) if e["t"] == "move" and e["to"] == "action_area"]
                assert all(i < kinds.index("judge") for i in placed)      # 公開が先、判定が後
            if "turn" in kinds:
                k = kinds.index("turn"); tp = ev[k]["player"]
                draws = [i for i, e in enumerate(ev) if e["t"] == "move" and e["player"] == tp and e["from"] == "deck" and e["to"] == "hand"]
                clean = [i for i, e in enumerate(ev) if e["t"] == "move" and e["from"] == "action_area"]
                assert all(i < k for i in clean)                          # 片付け → ターンの交代
                seen["turn_draw"] += any(i > k for i in draws)            # → 新しいターンのドロー（効果で先に引くこともある）
                seen["cleanup"] += bool(clean)
    assert all(n > 5 for n in seen.values()), seen


def test_publicly_revealed_cards_stay_face_up_in_hand():
    """デッキから公開して手札に加えたカードは、相手と観戦者に表向きで見え続ける（2026-09-21 マスターの指摘）。

    覚えているのは「全員に公開されて、そのまま手札に入ったカード」だけ。手札から出れば減り、どれが出たか見えない出方があれば全部忘れる。
    **本当の手札に無いカードを「ある」と見せることは一度も無い。**復元（サーバの再起動）のあとも同じ内容に戻る。
    """
    from collections import Counter
    seen = {"known": 0, "to_opp": 0, "to_spec": 0, "forgot": 0, "restored": 0}
    for seed in range(40):
        rnd = random.Random(5000 + seed)
        g = Game([random_deck(rnd), random_deck(rnd)], seed)
        n = 0
        while not g.over:
            p = rnd.choice(g.awaiting())
            had = [sum(k.values()) for k in g.public_known]
            ev = g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))
            n += 1
            for pi in (0, 1):
                known = g.public_known[pi]
                assert not known - Counter(g.state.players[pi].hand), (pi, known)      # 本当の手札の範囲を出ない
                if known:
                    seen["known"] += 1
                    cards = sorted(known.elements())
                    opp_known = g.view(1 - pi)["players"][pi]["hand_known"]
                    assert not Counter(cards) - Counter(opp_known)                       # 相手の席に表向きで見える
                    assert g.view(SPECTATOR)["players"][pi]["hand_known"] == cards       # 観戦者にも見える
                    assert g.view(pi)["players"][pi]["hand_known"] == []                 # 本人の視点は変わらない（自分の手札は元から見えている）
                seen["forgot"] += sum(known.values()) < had[pi]
                seen["to_opp"] += any(e["t"] == "known" and e["player"] == pi for e in ev[1 - pi])
                seen["to_spec"] += any(e["t"] == "known" and e["player"] == pi for e in ev[SPECTATOR])
                assert not any(e["t"] == "known" and e["player"] == pi for e in ev[pi])
            if n % 25 == 0 and any(g.public_known):
                g2 = Game.load(json.loads(json.dumps(g.dump())))
                assert g2.public_known == g.public_known
                seen["restored"] += 1
    assert all(v > 0 for v in seen.values()), seen


def test_damage_events_name_their_source_and_lethal_does_not_heal(sd001, sd02):
    """ダメージのライフの出来事には出どころのカードと量が付く（APP-016）。番号はその相手に写っているときだけ。
    とどめのダメージのあと、ライフを 0 に直すぶんが「回復」として出ない。"""
    from app.core.views import visible_cards
    tagged = lethal = 0
    for seed in range(12):
        g, rnd = Game([sd001, sd02], seed), random.Random(seed)

        def check(g, before, events):
            nonlocal tagged, lethal
            for v, evs in events.items():
                lives = [e for e in evs if e["t"] == "life"]
                for e in lives:
                    assert e["value"] >= 0, e                        # 負のライフを見せない
                    if e["delta"] < 0:
                        assert "src" in e and "amount" in e, e       # トレース点のあるエンジンでは必ず付く
                        assert e["amount"] >= -e["delta"], e
                        if e["src"] is not None:
                            tagged += 1
                            seen = set().union(*(visible_cards(f) for f in g.last_frames.get(v, [])))   # この apply の間に写っていたもの
                            assert e["src"] in seen, (v, e)
                if g.over and any(e["delta"] < 0 and e["value"] == 0 for e in lives):
                    lethal += 1
                    assert not any(e["delta"] > 0 and e["value"] == 0 for e in lives), lives
        play_random(g, rnd, check)
    assert tagged > 100 and lethal > 0, (tagged, lethal)


def test_damage_source_is_hidden_from_viewers_who_cannot_see_the_card(sd001, sd02):
    """出どころのカードが写っていない相手には、番号を渡さない（APP-016・APP-003）。"""
    g = Game([sd001, sd02], 1)
    prev = {v: view_for(g.state, v) for v in VIEWERS}
    seen_by_0 = sorted(visible_cards_of(prev[0]))
    hidden = next(c for c in sorted(g.state.players[1].action_deck) if c not in visible_cards_of(prev[0]))
    out = {v: [{"t": "life", "player": 0, "delta": -2, "value": 18}] for v in VIEWERS}
    Game._tag_damage(out, prev, {"player": 0, "amount": 2, "dealer": 1, "source": ["action", hidden]})
    assert out[0][0]["src"] is None and out[0][0]["amount"] == 2 and out[0][0]["dealer"] == 1
    assert seen_by_0                                                   # 見えているカードなら付く
    out = {v: [{"t": "life", "player": 0, "delta": -2, "value": 18}] for v in VIEWERS}
    Game._tag_damage(out, prev, {"player": 0, "amount": 2, "dealer": 1, "source": ["chara", seen_by_0[0]]})
    assert out[0][0]["src"] == seen_by_0[0]


def visible_cards_of(view):
    from app.core.views import visible_cards
    return visible_cards(view)


def test_effect_stack_shows_only_visible_cards_in_resolution_order():
    """APP-023: 効果の一覧（解決中・待ち）は、その視点に写っているカードだけ番号を出す。割り込みが外側より先に並ぶ。
    無作為なデッキ（BP01 が混ざる）の対局で、全視点・全手番について確かめる。"""
    from app.core.views import effect_stack, visible_cards
    seen = {"resolving": 0, "queue": 0, "hidden": 0}

    def check(g, before, events):
        s = g.state
        for v in VIEWERS:
            view = view_for(s, v)
            eff = view["effects"]
            vis = visible_cards({k: x for k, x in view.items() if k != "effects"})
            items = ([eff["resolving"]] if eff["resolving"] else []) + eff["queue"]
            for it in items:
                assert it["card"] is None or it["card"] in vis, (v, it)
                if it["card"] is None:
                    assert it["skill_index"] is None
                    seen["hidden"] += 1
            refs = list(s.pending_triggers) + list(s.pending_skills)
            assert [(it["player"], it["card"] or r[2]) for it, r in zip(eff["queue"], refs)] == [(r[0], r[2]) for r in refs]
            seen["resolving"] += 1 if eff["resolving"] else 0
            seen["queue"] += len(eff["queue"])

    for seed in range(12):
        rnd = random.Random(7000 + seed)
        g = Game([random_deck(rnd), random_deck(rnd)], seed)
        play_random(g, rnd, check)
    assert seen["resolving"] > 0 and seen["queue"] > 0, seen


def test_effect_stack_hides_cards_the_viewer_cannot_see():
    """手で作った局面: 見えているキャラのスキルは番号つき、どの視点にも写っていないカードは「伏せたカード」になる。"""
    from app.core.views import effect_stack
    g = Game([random_deck(random.Random(1)), random_deck(random.Random(2))], 5)
    s = g.state
    s.pending_triggers = [[0, "chara", "BP01-008", 0]]
    s.pending_skills = [[1, "action", "SD02-020", 0]]
    s.players[0].slots[2].stack = ["BP01-008"]
    for v in VIEWERS:
        eff = view_for(s, v)["effects"]
        vis_08 = "BP01-008" in card_ids_in({k: x for k, x in view_for(s, v).items() if k != "effects"})
        assert eff["queue"][0] == {"player": 0, "card": "BP01-008" if vis_08 else None, "skill_index": 0 if vis_08 else None}
        vis_20 = "SD02-020" in card_ids_in({k: x for k, x in view_for(s, v).items() if k != "effects"})
        assert eff["queue"][1] == {"player": 1, "card": "SD02-020" if vis_20 else None, "skill_index": 0 if vis_20 else None}


def test_each_skill_resolution_is_an_event_with_only_visible_cards():
    """APP-024: スキル 1 個の解決が始まるたびに `skill` の出来事が 1 つ出る（演出の区切りとログ）。
    カード番号はその相手の視点に写っているときだけ。ログの 1 行にもなる。"""
    from app.core.views import visible_cards
    seen = {"skill": 0, "hidden": 0}

    def check(g, before, events):
        for v in VIEWERS:
            frames = g.last_frames.get(v, [])
            vis = set().union(*(visible_cards(f) for f in frames)) if frames else set()
            for e in events[v]:
                if e["t"] != "skill":
                    continue
                seen["skill"] += 1
                assert e["player"] in (0, 1)
                assert e["card"] is None or e["card"] in vis, (v, e)
                seen["hidden"] += e["card"] is None

    for seed in range(8):
        rnd = random.Random(9100 + seed)
        g = Game([random_deck(rnd), random_deck(rnd)], seed)
        play_random(g, rnd, check)
    assert seen["skill"] > 50, seen
