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
