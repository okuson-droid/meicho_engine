"""部屋（`app/core/room.py`）の検査。通信なし。"""
import json
import random

import pytest

from app.core import protocol as P
from app.core.protocol import AppError
from app.core.room import CHOOSING, FINISHED, LOBBY, PLAYING, Room, RoomManager
from app.core.views import card_ids_in


def seeds(start=987654321000):
    box = [start]

    def f():
        box[0] += 1
        return box[0]
    return f


def setup_room(sd001, sd02, first="random"):
    r = Room("r1", "himitsu", seed_source=seeds())
    a, _ = r.join("A", "himitsu")
    b, _ = r.join("B", "himitsu")
    r.handle(a.id, {"t": "settings", "first": first})
    r.handle(a.id, {"t": "sit", "seat": 0})
    r.handle(b.id, {"t": "sit", "seat": 1})
    r.handle(a.id, {"t": "deck", "deck": sd001})
    r.handle(b.id, {"t": "deck", "deck": sd02})
    return r, a, b


def start(r, a, b):
    r.handle(a.id, {"t": "ready", "on": True})
    return r.handle(b.id, {"t": "ready", "on": True})


def play_out(r, rnd, sink=None):
    by_seat = {m.seat: m for m in r.members.values() if m.seat is not None}
    while r.state == PLAYING:
        g = rnd.choice(r.game.awaiting())
        m = by_seat[r.order[g]]
        out = r.handle(m.id, {"t": "act", "token": r.game.tokens[g],
                              "index": rnd.randrange(len(r.game.legal(g)))})
        if sink:
            sink(out)


def test_join_needs_pass_and_key_restores_seat(sd001, sd02):
    r = Room("r1", "himitsu")
    for bad in ("x", "", None, 5):
        with pytest.raises(AppError) as e:
            r.join("A", bad)
        assert e.value.code == "bad_pass"
    a, out = r.join("A", "himitsu")
    key = out[0][1]["key"]
    assert out[0][1]["t"] == P.S_WELCOME and r.owner == a.id
    r.handle(a.id, {"t": "sit", "seat": 1})
    r.disconnect(a.id, 123.0)
    assert r.info()["seats"][1]["connected"] is False
    # 同じ表示名でも、鍵が無ければ別人（R-NET-4）
    a2, _ = r.join("A", "himitsu")
    assert a2.id != a.id and a2.seat is None
    # 鍵があれば合言葉なしで席に戻る
    a3, _ = r.join("whatever", None, key)
    assert a3 is a and a.seat == 1 and a.connected
    # 鍵も合言葉も違えば入れない
    with pytest.raises(AppError):
        r.join("A", None, "wrong-key")
    # 保存に鍵と合言葉の平文が残らない（R-SEC-4）
    blob = json.dumps(r.dump())
    assert key not in blob and "himitsu" not in blob


def test_lobby_rules(sd001, sd02):
    r, a, b = setup_room(sd001, sd02)
    c, _ = r.join("C", "himitsu")
    for mid, msg, code in [
        (c.id, {"t": "sit", "seat": 0}, "seat_taken"),
        (c.id, {"t": "deck", "deck": sd001}, "not_seated"),
        (c.id, {"t": "ready"}, "not_seated"),
        (b.id, {"t": "settings", "first": "seat1"}, "not_owner"),
        (a.id, {"t": "settings", "first": "coin"}, "bad_message"),
        (a.id, {"t": "sit", "seat": 2}, "bad_message"),
        (a.id, {"t": "nope"}, "bad_message"),
        (a.id, "hello", "bad_message"),
        (a.id, {"t": "act", "token": 1, "index": 0}, "not_playing"),
        ("ghost", {"t": "ping"}, "not_member"),
        (a.id, {"t": "deck", "deck": {**sd001, "action_deck": []}}, "bad_deck"),
    ]:
        before = json.dumps(r.dump(), sort_keys=True)
        with pytest.raises(AppError) as e:
            r.handle(mid, msg)
        assert e.value.code == code, msg
        assert json.dumps(r.dump(), sort_keys=True) == before
    # デッキを出していない席は準備完了にできない（R-ROOM-5）
    r.handle(a.id, {"t": "stand"})
    r.handle(a.id, {"t": "sit", "seat": 0})
    with pytest.raises(AppError) as e:
        r.handle(a.id, {"t": "ready", "on": True})
    assert e.value.code == "no_deck"


def test_room_info_never_contains_deck_contents_or_seed(sd001, sd02):
    """要件 R-ROOM-6・R-SEC-3。対局前・対局中・終局後のすべての `room` メッセージを調べる。"""
    r, a, b = setup_room(sd001, sd02)
    c, _ = r.join("C", "himitsu")
    msgs = []
    msgs += start(r, a, b)
    play_out(r, random.Random(1), msgs.extend)
    assert r.state == FINISHED
    seed = r.finished[0]["game"]["seed"]
    for _, m in msgs:
        if m["t"] == P.S_ROOM:
            assert not card_ids_in(m["room"])
        assert str(seed) not in json.dumps(m)
    assert r.info()["seats"][0]["deck_name"] == "SD001"


def test_first_player_modes(sd001, sd02):
    for mode, want in (("seat0", [0, 1]), ("seat1", [1, 0])):
        r, a, b = setup_room(sd001, sd02, mode)
        start(r, a, b)
        assert r.order == want
        # 対局の席 0 のデッキは、先攻になった部屋の席のデッキ
        assert r.game.decks[0]["name"] == ("SD001" if want[0] == 0 else "SD02")
    orders = set()
    for s in range(20):
        r = Room("r", "p", seed_source=seeds(s * 7 + 1))
        a, _ = r.join("A", "p")
        b, _ = r.join("B", "p")
        for m, seat, d in ((a, 0, sd001), (b, 1, sd02)):
            r.handle(m.id, {"t": "sit", "seat": seat})
            r.handle(m.id, {"t": "deck", "deck": d})
        start(r, a, b)
        orders.add(tuple(r.order))
    assert orders == {(0, 1), (1, 0)}


def test_loser_chooses_on_rematch(sd001, sd02):
    r, a, b = setup_room(sd001, sd02, "loser")
    start(r, a, b)                       # 初戦は敗者がいないのでランダム
    assert r.state == PLAYING
    g_b = r.gseat_of(b)
    r.handle(b.id, {"t": "resign"})
    assert r.state == FINISHED and r.last_loser == b.seat
    assert r.info()["result"]["winner"] == 1 - g_b
    r.handle(a.id, {"t": "rematch"})
    assert r.state == FINISHED
    r.handle(b.id, {"t": "rematch"})
    assert r.state == CHOOSING and r.chooser == b.seat
    with pytest.raises(AppError) as e:
        r.handle(a.id, {"t": "first", "choice": "me"})
    assert e.value.code == "not_chooser"
    r.handle(b.id, {"t": "first", "choice": "opp"})
    assert r.state == PLAYING and r.order == [a.seat, b.seat]
    assert len(r.finished) == 1 and r.games_played == 1


def test_spectators(sd001, sd02):
    r, a, b = setup_room(sd001, sd02)
    start(r, a, b)
    rnd = random.Random(2)
    for _ in range(25):
        g = rnd.choice(r.game.awaiting())
        m = a if r.gseat_of(a) == g else b
        r.handle(m.id, {"t": "act", "token": r.game.tokens[g], "index": rnd.randrange(len(r.game.legal(g)))})
    # 途中から入ると、その時点の公開状態の全量が届く（R-SPEC-2）
    c, out = r.join("C", "himitsu")
    views = [m for mid, m in out if mid == c.id and m["t"] == P.S_VIEW]
    assert len(views) == 1 and views[0]["full"] and views[0]["view"]["viewer"] == "spec"
    # 操作はできない（R-SPEC-3）。席にも着けない
    for msg, code in (({"t": "act", "token": 1, "index": 0}, "not_seated"),
                      ({"t": "resign"}, "not_seated"), ({"t": "sit", "seat": 0}, "in_game")):
        with pytest.raises(AppError) as e:
            r.handle(c.id, msg)
        assert e.value.code == code
    # 4 人まで（R-SPEC-4）
    for i in range(3):
        r.join(f"S{i}", "himitsu")
    with pytest.raises(AppError) as e:
        r.join("S9", "himitsu")
    assert e.value.code == "room_full"
    # 観戦者の出入りは対局を止めない
    applies = len(r.game.applies)
    r.disconnect(c.id)
    assert c.id not in r.members and r.state == PLAYING and len(r.game.applies) == applies


def test_disconnect_mid_game_keeps_seat_and_does_not_forfeit(sd001, sd02):
    r, a, b = setup_room(sd001, sd02)
    start(r, a, b)
    r.disconnect(b.id, 50.0)
    assert r.state == PLAYING and r.seats[1] == b.id              # R-NET-2・R-NET-7
    info = r.info()["seats"][1]
    assert info["connected"] is False and info["left_at"] == 50.0
    assert not r.is_empty()
    r.disconnect(a.id, 60.0)
    assert r.is_empty()


def test_stale_act_carries_resync(sd001, sd02):
    r, a, b = setup_room(sd001, sd02)
    start(r, a, b)
    g = r.game.awaiting()[0]
    m = a if r.gseat_of(a) == g else b
    with pytest.raises(AppError) as e:
        r.handle(m.id, {"t": "act", "token": 0, "index": 0})
    assert e.value.code == "stale"
    assert [x[1]["t"] for x in e.value.resync] == [P.S_VIEW] and e.value.resync[0][1]["full"]


def test_room_dump_load_mid_game(sd001, sd02):
    r, a, b = setup_room(sd001, sd02)
    start(r, a, b)
    rnd = random.Random(4)
    for _ in range(40):
        g = rnd.choice(r.game.awaiting())
        m = a if r.gseat_of(a) == g else b
        r.handle(m.id, {"t": "act", "token": r.game.tokens[g], "index": rnd.randrange(len(r.game.legal(g)))})
    r2 = Room.load(json.loads(json.dumps(r.dump())), seed_source=seeds())
    assert r2.state == PLAYING and r2.order == r.order and r2.is_empty()
    assert r2.game.view(0) == {**r.game.view(0), "token": r2.game.tokens[0]}
    assert r2.check_pass("himitsu") and not r2.check_pass("x")
    play_out(r, rnd)
    assert r.state == FINISHED


def test_manager_limits():
    mgr = RoomManager()
    for bad in (None, "", "x" * 65, 5):
        with pytest.raises(AppError):
            mgr.create(bad)
    rooms = [mgr.create("p") for _ in range(P.MAX_ROOMS)]
    with pytest.raises(AppError) as e:
        mgr.create("p")
    assert e.value.code == "too_many_rooms"
    assert len({r.id for r in rooms}) == P.MAX_ROOMS
    with pytest.raises(AppError):
        mgr.get("nope")
    mgr.close(rooms[0].id)
    mgr.create("p")


def test_review_mode_shares_one_position_and_anyone_can_take_over(sd001, sd02):
    """感想戦（R-REP-4・APP-029）: 終局したあとだけ始められ、部屋の全員に同じ位置が配られる。
    位置を動かせるのは操作する 1 人で、誰でも代われる。操作する人が抜けたら次の人へ渡り、次の局が始まったら終わる。"""
    from app.core import replay
    r, a, b = setup_room(sd001, sd02)
    c, _ = r.join("C", "himitsu")                                     # 観戦者も加われる
    start(r, a, b)
    with pytest.raises(AppError) as e:
        r.handle(c.id, {"t": "review", "op": "start"})
    assert e.value.code == "not_finished" and r.review is None
    play_out(r, random.Random(3))
    last = len(replay.build(r.game.dump(), r.game.result())["full"]) - 1    # リプレイの最後の位置と一致させる
    assert r._review_last() == last
    with pytest.raises(AppError) as e:
        r.handle(a.id, {"t": "review", "op": "move", "pos": 1})
    assert e.value.code == "no_review"

    out = r.handle(c.id, {"t": "review", "op": "start", "pos": 5})
    assert {mid for mid, _ in out} == {a.id, b.id, c.id}              # 部屋の全員へ
    rv = out[0][1]["room"]["review"]
    assert rv["driver"] == c.id and rv["pos"] == 5
    first_n = rv["n"]
    assert r.handle(a.id, {"t": "review", "op": "start"}) and r.review["driver"] == c.id    # 2 回目の start は加わるだけ
    with pytest.raises(AppError) as e:
        r.handle(a.id, {"t": "review", "op": "move", "pos": 6})
    assert e.value.code == "not_driver" and r.review["pos"] == 5      # 操作していない人は動かせない（状態は変わらない）
    for bad in (-1, last + 1, "3", True, None):
        with pytest.raises(AppError):
            r.handle(c.id, {"t": "review", "op": "move", "pos": bad})
    out = r.handle(c.id, {"t": "review", "op": "move", "pos": last})
    assert all(m["room"]["review"]["pos"] == last for _, m in out)
    assert r.handle(c.id, {"t": "review", "op": "move", "pos": last}) == []   # 同じ位置は配り直さない

    r.handle(a.id, {"t": "review", "op": "take"})                     # 誰でも代われる
    assert r.review["driver"] == a.id
    r.handle(a.id, {"t": "review", "op": "move", "pos": 2})
    with pytest.raises(AppError):
        r.handle(c.id, {"t": "review", "op": "move", "pos": 3})
    r.disconnect(a.id, 1.0)                                           # 操作する人が抜けたら、つながっている人へ
    assert r.review["driver"] in (b.id, c.id) and r.review["pos"] == 2
    with pytest.raises(AppError):
        r.handle(c.id, {"t": "review", "op": "nope"})
    r.handle(b.id, {"t": "review", "op": "stop"})
    assert r.review is None and r.info()["review"] is None
    r.handle(b.id, {"t": "review", "op": "start"})
    assert r.review["n"] != first_n and r.review["pos"] == 0          # 始め直すと別の感想戦（画面はまた開く）
    assert "review" not in json.dumps(r.dump())                      # 保存しない（再起動したら終わる）

    r.members[a.id].connected = True                                 # A がつなぎ直した（席は保たれている）
    r.handle(a.id, {"t": "rematch"})
    r.handle(b.id, {"t": "rematch"})                                  # 次の局が始まったら感想戦は終わる
    assert r.state in (PLAYING, CHOOSING) and r.review is None and r.info()["review"] is None


def test_live_flags_go_only_to_their_author_and_into_the_record(sd001, sd02):
    """対局中の「気になる」印（R-REP-5・APP-030）: 直前の手（いまの局面を作った手）に付く。返事は付けた本人にだけで、
    部屋の情報には載らない（相手に見せない）。観戦者も付けられる。保存と復元をまたぎ、終局で記録の材料に入り、次の局で空になる。"""
    r, a, b = setup_room(sd001, sd02)
    c, _ = r.join("C", "himitsu")
    with pytest.raises(AppError) as e:
        r.handle(a.id, {"t": "flag"})
    assert e.value.code == "not_playing"
    start(r, a, b)
    rnd = random.Random(4)
    by_seat = {m.seat: m for m in (a, b)}
    for _ in range(12):
        g = rnd.choice(r.game.awaiting())
        r.handle(by_seat[r.order[g]].id, {"t": "act", "token": r.game.tokens[g], "index": rnd.randrange(len(r.game.legal(g)))})
    out = r.handle(b.id, {"t": "flag"})
    assert [mid for mid, _ in out] == [b.id] and out[0][1]["t"] == P.S_FLAGGED
    f = out[0][1]["flag"]
    assert f == {"pos": len(r.game.applies), "turn": r.game.state.turn_no, "note": "", "by": "B",
                 "seat": r.gseat_of(b), "when": "live"}
    r.handle(c.id, {"t": "flag"})                                     # 観戦者は席なし
    assert r.flags[1]["by"] == "C" and r.flags[1]["seat"] is None
    assert "flags" not in r.info() and "flag" not in json.dumps(r.info())
    r2 = Room.load(json.loads(json.dumps(r.dump())))                  # 再起動をまたぐ
    assert r2.flags == r.flags
    play_out(r, rnd)
    fin = r.finished[-1]
    assert [x["by"] for x in fin["flags"]] == ["B", "C"]
    r.handle(a.id, {"t": "rematch"})
    r.handle(b.id, {"t": "rematch"})
    assert r.state in (PLAYING, CHOOSING) and r.flags == []
