"""サーバ（`app/server.py`）の検査。本物の WebSocket 越しに、画面なしの自動クライアントで打つ。

計画書 8.2 の M2 の完了条件:
  自動クライアント 2 体が WebSocket 越しに 1 局を打ち切る／切断・二重送信・順序入れ替わり・サーバ再起動の
  各テストが通る／相手の席に届くメッセージに非公開情報が含まれないことを機械的に検査する
"""
import asyncio
import json

import pytest

# エンジン側の環境に aiohttp が無くても、`engine/` 直下の pytest を壊さない（無ければこのファイルだけ skip）
pytest.importorskip("aiohttp")
pytest.importorskip("pytest_asyncio")

import aiohttp  # noqa: E402
from aiohttp.test_utils import TestServer

from app import server as S
from app.bot import Bot
from app.core import protocol as P
from app.core.views import SPECTATOR, card_ids_in, view_for
from app.core.game import make_config
from meicho import apply, initial_state

pytestmark = pytest.mark.asyncio
PASS = "あいことば"


class Seeds:
    def __init__(self, start=424242000):
        self.n = start

    def __call__(self):
        self.n += 1
        return self.n


async def boot(tmp_path, **kw):
    kw.setdefault("flood_per_sec", None)        # 自動クライアントは人間より桁違いに速いので、既定では切る
    srv = TestServer(S.create_app(tmp_path / "data", seed_source=Seeds(), **kw))
    await srv.start_server()
    return srv, str(srv.make_url("")).rstrip("/")


async def new_room(url, passphrase=PASS):
    async with aiohttp.ClientSession() as s:
        async with s.post(url + "/api/rooms", json={"pass": passphrase}) as r:
            body = await r.json()
    assert body["ok"], body
    return body["room"]


async def pair(url, room, sd001, sd02, **kw):
    a = Bot(url, room, PASS, "A", deck=sd001, seat=0, seed=1, **kw)
    b = Bot(url, room, PASS, "B", deck=sd02, seat=1, seed=2, **kw)
    await a.enter()
    await b.enter()
    return a, b


def until(n):
    """`apply` が n 回に達したら止まる条件。2 体に同じものを渡す。"""
    return lambda bot: bool(bot.view) and bot.view["applies"] >= n


def allowed_ids(rec) -> list:
    """記録を当て直し、`apply` の回ごと・相手ごとに「見えてよいカード番号」の集合を作る（検査の物差し）。

    見えてよいのは、その apply の間の各時点（エンジンのトレース点）でその相手の観測に写っていたものと、
    エンジンが「公開」と知らせて宛先にその相手が入っていたものだけである。画面へ送る側のコード（`Game`）は通さずに作る。
    """
    from meicho import trace
    viewers = (0, 1, SPECTATOR)
    s = initial_state(make_config(rec["decks"]), rec["seed"])
    out = [{v: card_ids_in(view_for(s, v)) for v in viewers}]
    public_ever: set = set()            # 全員に公開されたことのあるカード番号。そのあと「手札にあると知られているカード」として盤面に出てよい
    for row in rec["applies"]:
        acc = {v: set(public_ever) for v in viewers}

        def sink(kind, info, st, acc=acc):
            for v in viewers:
                acc[v] |= card_ids_in(view_for(st, v))
                if kind == "reveal" and info.get("audience") in ("all", v):
                    acc[v] |= set(info["cards"])
            if kind == "reveal" and info.get("audience") == "all":
                public_ever.update(info["cards"])

        with trace.tracing(sink):
            s = apply(s, {int(p): a for p, a in row.items()})
        for v in viewers:
            acc[v] |= card_ids_in(view_for(s, v))
        out.append(acc)
    return out


def assert_no_leak(bot, allowed, viewer, seed):
    """そのクライアントが受け取った**全メッセージ**を調べる（要件 R-SEC-2）。

    `view` に載っている `applies`（何回目の apply の後か）から、その回と 1 つ前の回にその相手へ見えてよかった
    カード番号を引き、メッセージ中のカード番号がその中に収まっていることを確かめる。
    """
    n = 0
    for msg in bot.inbox:
        text = json.dumps(msg)
        assert str(seed) not in text                           # R-SEC-3
        if msg["t"] != P.S_VIEW:
            assert not card_ids_in(msg), msg                   # 部屋の情報にカード番号は無い（R-ROOM-6）
            continue
        k = msg["view"]["applies"]
        ok = allowed[k][viewer] | (allowed[k - 1][viewer] if k > 0 else set())
        leaked = card_ids_in(msg) - ok
        assert not leaked, (viewer, k, leaked)
        n += 1
    assert n > 50


async def test_two_bots_finish_a_game_and_nothing_leaks(tmp_path, sd001, sd02):
    srv, url = await boot(tmp_path)
    try:
        room = await new_room(url)
        a, b = await pair(url, room, sd001, sd02)
        c = Bot(url, room, PASS, "C")                           # 観戦者
        await c.enter()
        ra, rb, rc = await asyncio.gather(a.play(), b.play(), c.play())
        assert ra == rb == rc and ra["reason"] == "normal"
        assert not a.errors and not b.errors and not c.errors

        recs = [json.loads(x) for p in (tmp_path / "data" / "games").glob("*.jsonl")
                for x in p.read_text(encoding="utf-8").splitlines()]
        assert len(recs) == 1
        rec = recs[0]
        assert rec["verified"] is True and rec["result"] == ra
        assert rec["rules_version"].startswith("v0.") and rec["kind"] == "pvp"
        assert sorted(rec["names"]) == ["A", "B"] and len(rec["decks"][0]["action_deck"]) == 40

        allowed = allowed_ids(rec)
        order = a.room_info["order"]                            # 対局の席 → 部屋の席
        assert_no_leak(a, allowed, order.index(0), rec["seed"])
        assert_no_leak(b, allowed, order.index(1), rec["seed"])
        assert_no_leak(c, allowed, SPECTATOR, rec["seed"])
        # 観戦者には手札も選択肢も合法手も届かない（R-SPEC-1）
        for msg in c.inbox:
            if msg["t"] == P.S_VIEW:
                v = msg["view"]
                assert v["viewer"] == "spec" and "legal" not in v and v["choice"] is None
                assert all(pl["hand"] is None for pl in v["players"])
        for x in (a, b, c):
            await x.close()
    finally:
        await srv.close()


async def test_disconnect_and_reconnect_with_key(tmp_path, sd001, sd02):
    srv, url = await boot(tmp_path)
    try:
        room = await new_room(url)
        a, b = await pair(url, room, sd001, sd02)
        await asyncio.gather(a.play(stop=until(15)), b.play(stop=until(15)))
        key, member = b.key, b.member
        await b.close()
        msg = await a.wait_for(lambda m: m["t"] == P.S_ROOM and
                               any(s and not s["connected"] for s in m["room"]["seats"]))
        assert msg["room"]["state"] == "playing"               # 自動で負けにしない（R-NET-2）

        # 表示名が同じでも、鍵が無ければ席には戻れない（R-NET-4）
        fake = Bot(url, room, PASS, "B")
        await fake.enter()
        await fake.wait_for(lambda m: m["t"] == P.S_VIEW)
        assert fake.member != member and fake.view["viewer"] == "spec"
        await fake.close()

        b2 = Bot(url, room, "", "B", seed=2, key=key)
        await b2.connect()
        w = await b2.wait_for(lambda m: m["t"] == P.S_WELCOME)
        assert w["member"] == member
        v = await b2.wait_for(lambda m: m["t"] == P.S_VIEW)
        assert v["full"] and v["events"] == [] and v["view"]["viewer"] in (0, 1)   # 全量の送り直し（R-NET-3）
        ra, rb = await asyncio.gather(a.play(), b2.play())
        assert ra == rb and ra is not None
        await a.close()
        await b2.close()
    finally:
        await srv.close()


async def test_duplicate_stale_and_garbage_do_not_move_the_game(tmp_path, sd001, sd02):
    srv, url = await boot(tmp_path)
    try:
        room = await new_room(url)
        a, b = await pair(url, room, sd001, sd02)
        await asyncio.gather(a.play(stop=until(10)), b.play(stop=until(10)))
        hub = srv.app[S.HUB]
        game = hub.manager.rooms[room].game

        async def settle(bot):
            await bot.send({"t": "ping", "ref": "sync"})
            await bot.wait_for(lambda m: m["t"] == P.S_PONG)

        await settle(a)
        await settle(b)
        mover = a if a.my_turn() else b
        assert mover.my_turn()
        tok, n_applies, n_held = mover.view["token"], len(game.applies), len(game.held)

        # 壊れた入力いろいろ。どれもエラーが返るだけで、対局は 1 手も進まない（R-NF-11）
        n_err = len(mover.errors)
        await mover.ws.send_str("{not json")
        await mover.ws.send_str(json.dumps([1, 2, 3]))
        await mover.ws.send_bytes(b"\x00\x01")
        for bad in ({"t": "act"}, {"t": "act", "token": tok, "index": 10 ** 9}, {"t": "act", "token": tok, "index": "0"},
                    {"t": "act", "token": tok - 1, "index": 0}, {"t": "act", "token": tok + 5, "index": 0},
                    {"t": "sit", "seat": 0}, {"t": "deck", "deck": sd001}, {"t": "zzz"}):
            await mover.send(bad)
        await settle(mover)
        assert len(mover.errors) - n_err == 10
        assert (len(game.applies), len(game.held)) == (n_applies, n_held)
        # 古い番号には、エラーの前に最新の全量が届く（R-NET-5「画面は最新の状態を取り直す」）
        i = next(k for k, m in enumerate(mover.inbox) if m["t"] == P.S_ERROR and m["code"] == "stale")
        assert mover.inbox[i - 1]["t"] == P.S_VIEW and mover.inbox[i - 1]["full"]

        # 二重送信: 同じ番号を 2 通続けて送る。通るのは 1 通だけ
        n_err = len(mover.errors)
        act = {"t": "act", "token": tok, "index": 0, "ref": 77}
        await mover.send(act)
        await mover.send(act)
        await settle(mover)
        errs = mover.errors[n_err:]
        assert len(errs) == 1 and errs[0]["code"] in ("stale", "not_awaited") and errs[0]["ref"] == 77
        assert len(game.applies) + len(game.held) == n_applies + n_held + 1
        mover.answered = tok

        ra, rb = await asyncio.gather(a.play(), b.play())
        assert ra == rb
        await a.close()
        await b.close()
    finally:
        await srv.close()


async def test_out_of_turn_act_is_rejected(tmp_path, sd001, sd02):
    """順序の入れ替わり: 手番でない席・対抗でまだ開いていない席からの提出は通らない（R-CLASH-1）。"""
    srv, url = await boot(tmp_path)
    try:
        room = await new_room(url)
        a, b = await pair(url, room, sd001, sd02)
        game = None
        for k in range(1, 400):
            await asyncio.gather(a.play(stop=until(k)), b.play(stop=until(k)))
            game = srv.app[S.HUB].manager.rooms[room].game
            if len(game.awaiting()) == 1 and not game.held:
                break
        waiting = game.awaiting()[0]
        idle = a if a.room_info["order"].index(0) != waiting else b
        n = len(game.applies)
        await idle.send({"t": "act", "token": game.tokens[1 - waiting], "index": 0})
        e = await idle.wait_for(lambda m: m["t"] == P.S_ERROR)
        assert e["code"] == "not_awaited" and len(game.applies) == n and not game.held
        await a.close()
        await b.close()
    finally:
        await srv.close()


async def test_server_restart_keeps_the_game(tmp_path, sd001, sd02):
    srv, url = await boot(tmp_path)
    room = await new_room(url)
    a, b = await pair(url, room, sd001, sd02)
    await asyncio.gather(a.play(stop=until(20)), b.play(stop=until(20)))
    await a.send({"t": "ping"})
    await a.wait_for(lambda m: m["t"] == P.S_PONG)
    before = srv.app[S.HUB].manager.rooms[room].game.dump()
    keys = (a.key, b.key)
    await a.close()
    await b.close()
    await srv.close()                                           # サーバを落とす

    srv, url = await boot(tmp_path)                             # 同じ保存先で起こし直す（R-NET-6）
    try:
        game = srv.app[S.HUB].manager.rooms[room].game
        assert game.dump()["applies"] == before["applies"] and game.dump()["seed"] == before["seed"]
        a2 = Bot(url, room, "", "A", seed=11, key=keys[0])
        b2 = Bot(url, room, "", "B", seed=12, key=keys[1])
        for x in (a2, b2):
            await x.connect()
            await x.wait_for(lambda m: m["t"] == P.S_VIEW and m["full"])
        ra, rb = await asyncio.gather(a2.play(), b2.play())
        assert ra == rb and ra is not None
        recs = [x for p in (tmp_path / "data" / "games").glob("*.jsonl")
                for x in p.read_text(encoding="utf-8").splitlines()]
        assert len(recs) == 1 and json.loads(recs[0])["verified"] is True
        assert len(json.loads(recs[0])["applies"]) > len(before["applies"])
        await a2.close()
        await b2.close()
    finally:
        await srv.close()


async def test_hello_gate(tmp_path):
    srv, url = await boot(tmp_path)
    try:
        room = await new_room(url)
        async with aiohttp.ClientSession() as s:
            for hello, code in (
                ({"t": "hello", "v": 999, "room": room, "name": "A", "pass": PASS}, "version"),
                ({"t": "hello", "v": P.PROTOCOL_VERSION, "room": "nope", "name": "A", "pass": PASS}, "no_room"),
                ({"t": "hello", "v": P.PROTOCOL_VERSION, "room": room, "name": "A", "pass": "x"}, "bad_pass"),
                ({"t": "hello", "v": P.PROTOCOL_VERSION, "room": room, "name": "  ", "pass": PASS}, "bad_name"),
                ({"t": "sit", "seat": 0}, "bad_message"),
            ):
                ws = await s.ws_connect(url + "/ws")
                await ws.send_str(json.dumps(hello))
                got = [json.loads((await ws.receive(timeout=5)).data) for _ in range(2)]
                assert got[0]["t"] == P.S_ERROR and got[0]["code"] == code
                assert got[1] == {"t": P.S_BYE, "code": code}
                assert (await ws.receive(timeout=5)).type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                                               aiohttp.WSMsgType.CLOSING)
            async with s.post(url + "/api/rooms", json={"pass": ""}) as r:
                assert r.status == 400
            async with s.post(url + "/api/rooms", data=b"garbage") as r:
                assert r.status == 400
            async with s.get(url + "/api/health") as r:
                assert (await r.json())["ok"]
            async with s.get(url + "/") as r:                   # プレビューに出るのはアプリ名と「非公式」だけ（R-ROOM-3）
                text = await r.text()
                assert "非公式" in text and not card_ids_in(text.split())
    finally:
        await srv.close()


async def test_same_key_from_second_screen_replaces_the_first(tmp_path, sd001):
    srv, url = await boot(tmp_path)
    try:
        room = await new_room(url)
        a = Bot(url, room, PASS, "A", deck=sd001, seat=0)
        await a.enter()
        await a.wait_for(lambda m: m["t"] == P.S_ROOM and m["room"]["seats"][0] and m["room"]["seats"][0]["ready"])
        a2 = Bot(url, room, "", "A", key=a.key)
        await a2.connect()
        await a2.wait_for(lambda m: m["t"] == P.S_WELCOME)
        bye = await a.wait_for(lambda m: m["t"] == P.S_BYE)
        assert bye["code"] == "replaced"
        info = srv.app[S.HUB].manager.rooms[room].info()
        assert info["seats"][0]["connected"] is True            # 古い接続が閉じても、席は切断扱いにならない
        await a.close()
        await asyncio.sleep(0.1)
        assert srv.app[S.HUB].manager.rooms[room].info()["seats"][0]["connected"] is True
        await a2.close()
    finally:
        await srv.close()


async def test_empty_rooms_are_swept(tmp_path):
    now = [1000.0]
    srv, url = await boot(tmp_path, clock=lambda: now[0])
    try:
        room = await new_room(url)
        hub = srv.app[S.HUB]
        path = tmp_path / "data" / "rooms" / f"{room}.json"
        assert path.exists() and hub.sweep() == []
        now[0] += S.ROOM_TTL - 1
        assert hub.sweep() == []
        now[0] += 2
        assert hub.sweep() == [room] and not path.exists()      # R-ROOM-10
        assert room not in hub.manager.rooms
    finally:
        await srv.close()


async def test_flood_closes_only_that_connection(tmp_path, sd001):
    srv, url = await boot(tmp_path, flood_per_sec=20)
    try:
        room = await new_room(url)
        a = Bot(url, room, PASS, "A")
        b = Bot(url, room, PASS, "B")
        await a.enter()
        await b.enter()
        for _ in range(60):
            await a.send({"t": "ping"})
        bye = await a.wait_for(lambda m: m["t"] == P.S_BYE)
        assert bye["code"] == "flood"
        await b.send({"t": "ping"})                              # 他の接続とサーバは無事
        await b.wait_for(lambda m: m["t"] == P.S_PONG)
        await a.close()
        await b.close()
    finally:
        await srv.close()


async def test_pages_carry_no_official_assets_and_say_unofficial(tmp_path):
    """配るファイルに画像が無く、外部の配信元に頼らず、「非公式」を名乗る（R-ASSET-1・R-ROOM-3・R-UI-3・R-UI-4）。"""
    srv, url = await boot(tmp_path)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url + "/") as r:
                html = await r.text()
                assert r.headers["Cache-Control"] == "no-cache"
            async with s.get(url + "/api/cards") as r:
                cards = await r.json()
            async with s.get(url + "/api/decks") as r:
                decks = (await r.json())["decks"]
            async with s.get(url + "/static/js/main.js") as r:
                assert r.status == 200
        assert "非公式" in html and "noindex" in html and "<img" not in html
        assert len(cards["cards"]) > 100 and cards["rules"].startswith("v0.")
        allowed = {"kind", "name", "color", "cost", "speed", "damage", "tags", "dedicated_to",
                   "leader_skill", "skills", "unverified", "level"}
        assert all(set(c) <= allowed for c in cards["cards"].values())
        assert {d["name"] for d in decks} >= {"SD001", "SD02"} and all(set(d) == {"name", "chara_deck", "action_deck"} for d in decks)
        files = [p for p in S.STATIC_DIR.rglob("*") if p.is_file()]
        assert not [p for p in files if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")]
        for p in files:
            if p.suffix in (".js", ".css", ".html"):
                text = p.read_text(encoding="utf-8")
                assert "http://" not in text and "https://" not in text, p
    finally:
        await srv.close()


async def test_version_endpoint_in_the_dev_tree(tmp_path):
    """開発ツリーには署名つきの目録が無いので「開発版」と答える。版の情報は画面の表示にだけ使う（要件 R-UPD-8）。"""
    import aiohttp
    srv = TestServer(S.create_app(tmp_path / "data", flood_per_sec=None))
    await srv.start_server()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(str(srv.make_url("/api/version"))) as r:
                d = await r.json()
        assert d["dist"] is False and d["version"] == "開発版" and d["update"] is None
        assert d["protocol"] == P.PROTOCOL_VERSION and d["rules_version"].startswith("v")
    finally:
        await srv.close()


# -- 外から届く形の起動の守り（APP-012）。トンネル越しでは、別のサイトのページから部屋を作られたり席に入られたりしないようにする

TUNNEL = "https://abc-def.trycloudflare.com"


async def _status(method, url, headers):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, url, headers=headers, json={"pass": PASS}) as r:
            return r.status


async def _ws_status(url, headers):
    """WebSocket の握手が通れば 101、断られたら HTTP の状態番号を返す。通ったら hello まで打って welcome を確かめる。"""
    async with aiohttp.ClientSession() as s:
        try:
            ws = await s.ws_connect(url.replace("http", "ws", 1) + "/ws", headers=headers)
        except aiohttp.WSServerHandshakeError as e:
            return e.status
        await ws.close()
        return 101


async def test_allow_origin_is_normalized_and_validated():
    assert S.normalize_origin("HTTPS://ABC-def.TryCloudflare.com/") == TUNNEL
    assert S.normalize_origin("http://192.168.1.5:8765") == "http://192.168.1.5:8765"
    for bad in ("abc.trycloudflare.com", "ftp://x.example", "https://x.example/room", "https://x.example?a=1",
                "https://", "https://user@x.example", "null", ""):
        with pytest.raises(ValueError):
            S.normalize_origin(bad)
    assert S.parse_allow_origins([TUNNEL], " https://b.example , ") == (TUNNEL, "https://b.example")
    assert S.parse_allow_origins([TUNNEL, TUNNEL + "/"], None) == (TUNNEL,)


async def test_cpu_is_on_only_for_a_purely_local_launch():
    """トンネルは 127.0.0.1 へつなぐので、`--host` だけでは外から届くかを判別できない。許すサイトを書いた起動は外向きとみなす。"""
    assert S.decide_cpu("auto", "127.0.0.1", ()) is True
    assert S.decide_cpu("auto", "localhost", ()) is True
    assert S.decide_cpu("auto", "127.0.0.1", (TUNNEL,)) is False
    assert S.decide_cpu("auto", "0.0.0.0", ()) is False
    assert S.decide_cpu("on", "127.0.0.1", (TUNNEL,)) is True
    assert S.decide_cpu("off", "127.0.0.1", ()) is False


async def test_local_page_and_plain_clients_pass(tmp_path):
    srv, url = await boot(tmp_path)
    try:
        port = srv.port
        same = {"Origin": f"http://127.0.0.1:{port}"}
        assert await _status("POST", url + "/api/rooms", same) == 200
        assert await _status("POST", url + "/api/rooms", {"Origin": f"http://localhost:{port}", "Host": f"localhost:{port}"}) == 200
        assert await _status("POST", url + "/api/rooms", {}) == 200          # 起動役・自動クライアント（ブラウザでない）は Origin を送らない
        assert await _ws_status(url, same) == 101
        assert await _ws_status(url, {}) == 101
    finally:
        await srv.close()


async def test_foreign_pages_are_refused(tmp_path):
    srv, url = await boot(tmp_path, cpu=True, cpu_delay=0)
    try:
        port = srv.port
        before = len(srv.app[S.HUB].manager.rooms)
        for origin in ("https://evil.example", f"http://localhost:{port + 1}", f"http://127.0.0.1:{port + 1}",
                       "null", TUNNEL, f"https://127.0.0.1:{port}"):
            h = {"Origin": origin}
            assert await _status("POST", url + "/api/rooms", h) == 403, origin
            assert await _status("POST", url + "/api/cpu", h) == 403, origin
            assert await _ws_status(url, h) == 403, origin
        assert len(srv.app[S.HUB].manager.rooms) == before           # 断った要求で部屋ができていない
        assert await _status("GET", url + "/api/health", {"Origin": "https://evil.example"}) == 200   # 読むだけの GET は Origin を見ない
    finally:
        await srv.close()


async def test_rebound_host_names_are_refused(tmp_path):
    """DNS の付け替え（rebinding）で、別のサイトの名前のまま手元のサーバに届いた要求は、読むだけでも断る。"""
    srv, url = await boot(tmp_path)
    try:
        for host in ("evil.example", f"evil.example:{srv.port}", "abc-def.trycloudflare.com"):
            assert await _status("GET", url + "/api/health", {"Host": host}) == 403, host
            assert await _status("GET", url + "/", {"Host": host}) == 403, host
        assert await _status("GET", url + "/api/health", {"Host": f"[::1]:{srv.port}"}) == 200
    finally:
        await srv.close()


async def test_tunnel_origin_passes_only_when_configured(tmp_path):
    srv, url = await boot(tmp_path, allow_origins=(TUNNEL,))
    try:
        h = {"Origin": TUNNEL, "Host": "abc-def.trycloudflare.com"}
        assert await _status("GET", url + "/api/health", {"Host": h["Host"]}) == 200
        assert await _status("POST", url + "/api/rooms", h) == 200
        assert await _ws_status(url, h) == 101
        # トンネルが Host を手元の名前に書き換えて渡してきても通る（Origin はブラウザが付けたまま届く）
        assert await _ws_status(url, {"Origin": TUNNEL, "Host": f"localhost:{srv.port}"}) == 101
        other = "https://zzz.trycloudflare.com"
        assert await _status("POST", url + "/api/rooms", {"Origin": other, "Host": "abc-def.trycloudflare.com"}) == 403
        assert await _ws_status(url, {"Origin": other, "Host": "zzz.trycloudflare.com"}) == 403
        assert await _status("GET", url + "/api/health", {"Host": "zzz.trycloudflare.com"}) == 403
        # 手元のブラウザからは今までどおり
        assert await _ws_status(url, {"Origin": f"http://127.0.0.1:{srv.port}"}) == 101
    finally:
        await srv.close()


async def test_lan_address_pages_pass_as_same_origin(tmp_path):
    """同じ LAN のスマホから `http://<PC の IP>:8765/` で開く使い方（README）は、設定なしで通る。IP の名前は付け替えができない。"""
    srv, url = await boot(tmp_path)
    try:
        host = "192.168.1.5:8765"
        assert await _status("GET", url + "/", {"Host": host}) == 200
        assert await _ws_status(url, {"Host": host, "Origin": f"http://{host}"}) == 101
        assert await _status("POST", url + "/api/rooms", {"Host": host, "Origin": f"http://{host}"}) == 200
        assert await _ws_status(url, {"Host": host, "Origin": "http://192.168.1.9:8765"}) == 403
        assert await _ws_status(url, {"Host": host, "Origin": "http://192.168.1.5:8766"}) == 403
    finally:
        await srv.close()


async def test_refusal_tells_how_to_allow(tmp_path):
    """断ったときの文に、許し方（起動の引数）を書く。トンネルを立てたのに付け忘れたとき、窓とブラウザで分かるように。"""
    srv, url = await boot(tmp_path)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url + "/", headers={"Host": "abc-def.trycloudflare.com"}) as r:
                text = await r.text()
            async with s.post(url + "/api/rooms", headers={"Origin": TUNNEL}, json={"pass": PASS}) as r:
                body = await r.json()
        assert "--allow-origin" in text and "https://abc-def.trycloudflare.com" in text
        assert body["ok"] is False and body["code"] == "bad_origin" and "--allow-origin" in body["msg"]
    finally:
        await srv.close()


# -- 部屋が残り続けて上限に当たる不具合（APP-021）
async def _post_room(url, passphrase=PASS):
    async with aiohttp.ClientSession() as s:
        async with s.post(url + "/api/rooms", json={"pass": passphrase}) as r:
            return r.status, await r.json()


async def test_restart_does_not_restart_the_empty_clock(tmp_path):
    """起こし直しても「全員が切れた時刻」を数え直さない。数え直すと、何度も立て直すあいだ部屋が居座る。"""
    now = [1000.0]
    srv, url = await boot(tmp_path, clock=lambda: now[0])
    room = await new_room(url)
    await srv.close()
    now[0] += S.ROOM_TTL - 10
    srv, url = await boot(tmp_path, clock=lambda: now[0])     # 同じ保存先で起こし直す
    try:
        hub = srv.app[S.HUB]
        assert room in hub.manager.rooms and hub.empty_since[room] == 1000.0
        assert hub.sweep() == []
        now[0] += 20
        assert hub.sweep() == [room]                             # 起こし直した時刻からではなく、最初に空いた時刻から 30 分
        assert not (tmp_path / "data" / "rooms" / f"{room}.json").exists()
    finally:
        await srv.close()


async def test_room_files_without_the_time_use_the_file_time(tmp_path):
    """APP-021 より前のファイル（時刻を持たない）は、最後に保存された時刻から数える。"""
    import os
    import time
    now = [time.time()]
    srv, url = await boot(tmp_path, clock=lambda: now[0])
    room = await new_room(url)
    await srv.close()
    path = tmp_path / "data" / "rooms" / f"{room}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    d.pop("empty_since")
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    old = now[0] - S.ROOM_TTL - 5
    os.utime(path, (old, old))
    srv, url = await boot(tmp_path, clock=lambda: now[0])
    try:
        hub = srv.app[S.HUB]
        assert abs(hub.empty_since[room] - old) < 1
        assert hub.sweep() == [room]
    finally:
        await srv.close()


async def test_a_full_house_makes_space_from_long_empty_rooms(tmp_path, sd001):
    """上限のとき、誰もいなくなって猶予を過ぎた部屋を 1 つ閉じて場所を空ける。人がいる部屋・猶予の内の部屋・
    30 分に満たない対局の途中の部屋は閉じない。対局していない部屋を先に、その中で古いものを先に閉じる。"""
    now = [1000.0]
    srv, url = await boot(tmp_path, clock=lambda: now[0])
    try:
        hub = srv.app[S.HUB]
        rooms = []
        for _ in range(P.MAX_ROOMS):
            rooms.append(await new_room(url))
            now[0] += 1
        occupied, playing, older, newer = rooms
        a = Bot(url, occupied, PASS, "A", deck=sd001, seat=0, seed=1)
        await a.enter()                                          # 人がいる部屋
        hub.manager.rooms[playing].state = S.PLAYING             # 対局の途中で全員が切れた部屋に見立てる

        status, body = await _post_room(url)                     # 猶予の内: どれも閉じない
        assert status == 400 and body["code"] == "too_many_rooms"
        assert set(hub.manager.rooms) == set(rooms)

        now[0] += S.ROOM_GRACE + 5
        status, body = await _post_room(url)                     # 対局していない部屋のうち、古い方が閉じる
        assert status == 200 and body["ok"]
        assert older not in hub.manager.rooms and not (tmp_path / "data" / "rooms" / f"{older}.json").exists()
        assert {occupied, playing, newer} <= set(hub.manager.rooms)

        now[0] += 5
        status, body = await _post_room(url)                     # 対局していない部屋の次
        assert status == 200 and newer not in hub.manager.rooms
        fresh = [r for r in hub.manager.rooms if r not in rooms]
        assert len(fresh) == 2

        status, body = await _post_room(url)                     # 残りは人がいる部屋・30 分に満たない対局中・作ったばかり
        assert status == 400 and body["code"] == "too_many_rooms"
        now[0] += S.ROOM_GRACE_PLAYING
        status, body = await _post_room(url)                     # 作ったばかりの部屋（対局していない）が先に猶予を過ぎている
        assert status == 200 and playing in hub.manager.rooms and occupied in hub.manager.rooms
        await a.close()
    finally:
        await srv.close()
