"""サーバ（要件 R-NET・R-ROOM・R-NF-5・R-NF-11）。aiohttp で、静的ファイル・部屋を作る API・WebSocket を 1 つのポートで出す。

ここは**薄い**。ルールも部屋の進行も持たず、やることは 4 つだけである。

1. 受け取った JSON を `Room.handle` に渡す
2. 返ってきた `[(宛先, メッセージ)]` を、宛先の接続の送信待ち行列に**同期的に**積む（順序を保つため）
3. 1 通ごとに部屋を保存する（R-NET-6）。終局していたら記録を書く（R-DATA-1）
4. 失敗（`AppError`）を `error` として返す。想定外の例外でも接続 1 本が閉じるだけで、サーバは落ちない

起動: `python -m app.server --data <保存先> [--host 127.0.0.1] [--port 8765] [--allow-origin https://….trycloudflare.com]`（`engine/` の直下で）

外から届く形（トンネル・LAN）で出すときの守りは `origin_guard`（APP-012）。トンネルは 127.0.0.1 へつなぐので、
サーバは自分の外向きの名前を知らない。外向きの名前は `--allow-origin`（または環境変数 `MEICHOSIM_ALLOW_ORIGINS`）で受ける。
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from .core import cpu as cpu_mod
from .core import describe
from .core import protocol as P
from .core import release
from .core import replay as replay_mod
from .core.persist import ENGINE_DIR, SeedBand, Store, cards_version, make_record, record_problem, rules_version
from .core.protocol import AppError
from .core.room import CPU_ID, CPU_SEAT, FINISHED, PLAYING, Room, RoomManager

log = logging.getLogger("meichosim")

HELLO_TIMEOUT = 10.0        # 接続してから hello までの猶予（秒）
MAX_MSG = 64 * 1024         # 1 通の上限。デッキ 1 つで 2KB ほどなので十分
QUEUE_MAX = 256             # 送信待ちがこれを超えた接続は切る（読まない相手に付き合わない）
FLOOD_PER_SEC = 40          # 1 秒あたりの受信の上限
ROOM_TTL = 30 * 60          # 全員が切れてから部屋を閉じるまで（R-ROOM-10）。対局中の部屋は 24 時間
ROOM_TTL_PLAYING = 24 * 3600
ROOM_TTL_CPU = 5 * 60       # 誰もいない CPU 対戦の部屋（対局中でないもの）は早めに閉じる
ROOM_GRACE = 2 * 60         # 部屋が上限のとき、誰もいなくなってこれだけ経った部屋（対局中でないもの）は閉じて場所を空ける（APP-021）
ROOM_GRACE_PLAYING = ROOM_TTL   # 対局の途中で全員が切れた部屋は、30 分たつまで場所を空けるのに使わない
CPU_DELAY = 0.5             # AI が打つ前の間（秒）。一瞬で返ると、何が起きたか分かりにくい
STATIC_DIR = Path(__file__).resolve().parent / "static"
HUB = web.AppKey("hub", object)
ALLOWED = web.AppKey("allowed_origins", tuple)
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
ENV_ALLOW = "MEICHOSIM_ALLOW_ORIGINS"
UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


# -- 外から届く形の起動の守り（APP-012）
def normalize_origin(text) -> str:
    """`https://名前[:番号]` の形に揃える。道・問い合わせ・利用者名が付いたもの、http(s) 以外は ValueError。"""
    raw = str(text or "").strip()
    if raw.endswith("/"):
        raw = raw[:-1]
    try:
        u = urlsplit(raw)
        port = u.port
    except ValueError:
        raise ValueError(f"サイトの形が読めない: {text!r}") from None
    if u.scheme.lower() not in ("http", "https") or not u.hostname or u.path or u.query or u.fragment \
            or u.username is not None or u.password is not None:
        raise ValueError(f"許すサイトは https://名前 の形で書く（道や ? を付けない）: {text!r}")
    host = u.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{u.scheme.lower()}://{host}" + (f":{port}" if port is not None else "")


def parse_allow_origins(args=(), env=None) -> tuple:
    """起動の引数と環境変数（カンマ区切り）から、許すサイトの一覧を作る。重なりは除き、順は保つ。"""
    items = list(args or ()) + [x for x in str(env or "").split(",") if x.strip()]
    out: list = []
    for x in items:
        o = normalize_origin(x)
        if o not in out:
            out.append(o)
    return tuple(out)


def decide_cpu(mode: str, host: str, allow_origins) -> bool:
    """CPU 対戦を出すか（APP-009）。auto は「このPCの中からしか届かない起動」のときだけ。
    トンネルは 127.0.0.1 へつなぐので、許すサイトを書いた起動は外向きとみなす（APP-012）。"""
    if mode == "on":
        return True
    if mode == "off":
        return False
    return host in LOCAL_HOSTS and not allow_origins


def _split_host(value):
    """Host ヘッダ（`名前[:番号]`）を (名前, 元の文字列) に。読めなければ (None, …)。"""
    v = (value or "").strip().lower()
    try:
        return urlsplit("//" + v).hostname, v
    except ValueError:
        return None, v


def _is_ip(name) -> bool:
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def _host_ok(name, allowed: tuple) -> bool:
    """届いた名前を受けてよいか。IP の名前と localhost は付け替え（DNS rebinding）ができないので通す。"""
    if name is None:
        return False
    if name == "localhost" or _is_ip(name):
        return True
    return any(urlsplit(o).hostname == name for o in allowed)


def _origin_ok(origin: str, host_header: str, allowed: tuple) -> bool:
    """ブラウザが付けた Origin を受けてよいか。
    許すサイトに書いたもの、または手元・LAN の名前（IP・localhost）で開いた同じ場所（名前も番号も同じ）のページだけ。"""
    try:
        o = normalize_origin(origin)
    except ValueError:
        return False                    # "null"（ファイルから開いたページ・サンドボックス）など
    if o in allowed:
        return True
    u = urlsplit(o)
    if not (u.hostname == "localhost" or _is_ip(u.hostname)):
        return False
    return u.netloc == (host_header or "").strip().lower() and u.scheme == "http"


def _refuse(request: web.Request, code: str, what: str) -> web.Response:
    msg = (f"{what} このサーバに外から届く名前で入るなら、サーバを --allow-origin {what_origin(request)} を付けて起動し直してほしい"
           "（トンネルの URL は立てるたびに変わる）")
    log.warning("refused %s %s: %s (Host=%s Origin=%s)", request.method, request.path, code,
                request.headers.get("Host"), request.headers.get("Origin"))
    if request.path.startswith("/api/"):
        return web.json_response({"ok": False, "code": code, "msg": msg}, status=403,
                                 dumps=lambda o: json.dumps(o, ensure_ascii=False))
    return web.Response(status=403, text=msg, content_type="text/plain", charset="utf-8")


def what_origin(request: web.Request) -> str:
    """断ったとき、許すならどう書けばよいかの例。ブラウザの Origin があればそれ、無ければ Host から https で組む。"""
    origin = request.headers.get("Origin")
    try:
        return normalize_origin(origin)
    except ValueError:
        pass
    name, _ = _split_host(request.headers.get("Host"))
    return f"https://{name}" if name else "https://<トンネルの名前>"


@web.middleware
async def origin_guard(request: web.Request, handler):
    """外から届く形の起動の守り（APP-012・要件 R-SEC）。
    1. Host: 知らない名前で届いた要求は、読むだけでも断る（DNS の付け替えで、別のサイトのページから手元のサーバを読ませない）
    2. Origin: 部屋を作る・席に入る要求（WebSocket と、状態を変える HTTP）は、許したページからのものだけ受ける。
       Origin を付けないのはブラウザでない相手（起動役・自動クライアント）で、別のサイトのページからは操れないので通す"""
    allowed = request.app[ALLOWED]
    host = request.headers.get("Host")
    if host is not None:
        name, _ = _split_host(host)
        if not _host_ok(name, allowed):
            return _refuse(request, "bad_host", f"知らない名前（{host}）で届いたので断った。")
    origin = request.headers.get("Origin")
    if origin is not None and (request.method in UNSAFE_METHODS or request.path == "/ws") \
            and not _origin_ok(origin, host, allowed):
        return _refuse(request, "bad_origin", f"許していないページ（{origin}）からの要求なので断った。")
    return await handler(request)


class Conn:
    def __init__(self, ws):
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue()
        self.room_id = None
        self.member_id = None
        self.dead = False

    def push(self, msg: dict) -> None:
        if self.dead:
            return
        if self.queue.qsize() >= QUEUE_MAX:
            self.dead = True
            self.queue.put_nowait(None)
            return
        self.queue.put_nowait(msg)


class Hub:
    """部屋と接続の対応。送信・保存・掃除をまとめる。"""

    def __init__(self, store: Store, *, seed_source=None, clock=time.time, flood_per_sec=FLOOD_PER_SEC,
                 cpu: bool = False, cpu_delay: float = CPU_DELAY):
        self.store = store
        self.flood_per_sec = flood_per_sec
        self.cpu_enabled, self.cpu_delay = cpu, cpu_delay
        self.cpu_seeds = SeedBand(store.root / "cpu_seed.json")     # APP-008: 722000..741999
        self.cpu_agents: dict = {}      # room_id → (何局目か, エージェント)
        self.thinking: set = set()      # AI が考え中の部屋
        self.cpu_fails: dict = {}       # room_id → 続けて失敗した回数。空回りを止めるため
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="meichosim-ai")
        self.replay_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="meichosim-replay")   # AI の思考と取り合わない
        self.replay_cache: dict = {}    # (部屋, 何局目) または ("rec", 記録の番号) → 4 視点ぶんの手の列。新しい 4 件だけ持つ
        self.clock = clock
        self.manager = RoomManager(seed_source=seed_source)
        self.conns: dict = {}           # (room_id, member_id) → Conn
        self.empty_since: dict = {}     # room_id → 全員が切れた時刻
        for d in store.load_rooms():
            try:
                room = Room.load(d, seed_source=self.cpu_seeds if d.get("cpu") else seed_source)
            except Exception:           # 版が変わって当て直せない部屋は捨てずに、読み込まないだけにする
                log.exception("room %s could not be restored", d.get("id"))
                continue
            self.manager.rooms[room.id] = room
            self.empty_since[room.id] = self._restored_since(d, clock())

    # -- 送る
    def deliver(self, room: Room, out: list) -> None:
        for mid, msg in out:
            c = self.conns.get((room.id, mid))
            if c is not None:
                c.push(msg)

    def after_change(self, room: Room) -> None:
        while room.finished:
            fin = room.finished.pop(0)
            try:
                self.store.append_record(make_record(fin))
            except Exception:
                log.exception("record could not be saved (room %s)", room.id)
        if room.is_empty():
            self.empty_since.setdefault(room.id, self.clock())
        else:
            self.empty_since.pop(room.id, None)
        dump = room.dump()
        if room.id in self.empty_since:         # 起こし直しても「全員が切れた時刻」を数え直さない（APP-021）
            dump["empty_since"] = self.empty_since[room.id]
        self.store.save_room(dump)
        for rid in self.manager.closed:
            self.store.delete_room(rid)
            self.cpu_agents.pop(rid, None)
            self.empty_since.pop(rid, None)
        self.manager.closed.clear()
        self.kick_cpu(room)

    def _restored_since(self, d: dict, now: float) -> float:
        """保存から戻した部屋の「全員が切れた時刻」（APP-021）。

        起こし直した時点では誰もつながっていないので、どの部屋も空である。保存に時刻があればそれを使い、
        無ければ（APP-021 より前のファイル・人がいるまま落ちた部屋）ファイルの最後の保存時刻を使う。
        どちらも今より先なら今にする（時計の食い違いで部屋が居座らないように、ただし早く閉じすぎないように）。
        """
        t = d.get("empty_since")
        if not isinstance(t, (int, float)) or isinstance(t, bool):
            try:
                t = self.store._room_path(d["id"]).stat().st_mtime
            except (OSError, ValueError, KeyError, TypeError):
                t = now
        return min(float(t), now)

    def _close_room(self, rid: str) -> None:
        self.manager.close(rid)
        self.store.delete_room(rid)
        self.cpu_agents.pop(rid, None)
        self.empty_since.pop(rid, None)

    def make_room_space(self) -> None:
        """部屋が上限なら、誰もいない部屋を 1 つ閉じて場所を空ける（APP-021）。空けられなければ何もしない
        （そのあとの `create` が too_many_rooms で断る）。

        選ぶのは、誰もいなくなってから `ROOM_GRACE`（対局の途中なら `ROOM_GRACE_PLAYING`）以上たった部屋のうち、
        いちばん長く空いているもの。対局の途中の部屋より、対局していない部屋を先に閉じる。F5 や回線の瞬断で
        一瞬だけ空いた部屋は猶予の内なので閉じない。
        """
        if len(self.manager.rooms) < self.manager.max_rooms:
            return
        now, best = self.clock(), None
        for rid, since in self.empty_since.items():
            room = self.manager.rooms.get(rid)
            if room is None or not room.is_empty():
                continue
            playing = room.state == PLAYING
            if now - since < (ROOM_GRACE_PLAYING if playing else ROOM_GRACE):
                continue
            rank = (playing, since)             # 対局していない部屋が先、その中で古いものが先
            if best is None or rank < best[0]:
                best = (rank, rid)
        if best is not None:
            log.info("room %s closed to make space (rooms at the limit)", best[1])
            self._close_room(best[1])

    # -- AI の席（M5）。AI は「席に座る参加者の 1 種」で、人間と同じ `Room.handle` の道を通る
    def new_cpu_room(self, deck_name: str, level, first) -> tuple:
        if not self.cpu_enabled:
            raise AppError("cpu_unavailable", "CPU 対戦は、手元で起動したときだけ使える")
        if first not in ("random", "me", "cpu"):
            raise AppError("bad_message", "first の値が違う")
        agent = cpu_mod.resolve(deck_name, level)
        passphrase = secrets.token_urlsafe(12)              # 作った本人の画面にだけ返す。観戦させたい人には、これを伝える
        self.make_room_space()
        room = self.manager.create(passphrase, seed_source=self.cpu_seeds, cpu={
            "deck": cpu_mod.load_deck(deck_name), "level": level, "agent": agent,
            "label": cpu_mod.LEVEL_JA[level], "first": first})
        self.after_change(room)
        return room, passphrase

    def kick_cpu(self, room: Room) -> None:
        """AI の番なら考えさせる。**考えるのは `apply`（トレースの with）の外**である（TA-7 の注意）。"""
        if not room.cpu or room.state != PLAYING or room.id in self.thinking:
            return
        if self.cpu_fails.get(room.id, 0) >= 5:
            return                      # 同じ所で失敗し続けている。空回りさせず、人間の操作（投了など）を待つ
        if room.id not in self.manager.rooms or room.order.index(CPU_SEAT) not in room.game.awaiting():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:            # 起動時の読み込みなど、まだ動いていないとき。最初の接続で改めて呼ばれる
            return
        self.thinking.add(room.id)
        loop.create_task(self._cpu_move(room))

    def _agent(self, room: Room):
        tag, agent = self.cpu_agents.get(room.id, (None, None))
        if tag != (room.games_played, room.ai_seed):
            agent = cpu_mod.build(room.cpu["agent"], room.cpu["deck"], room.ai_seed)
            self.cpu_agents[room.id] = ((room.games_played, room.ai_seed), agent)
        return agent

    async def _cpu_move(self, room: Room) -> None:
        try:
            if self.cpu_delay:
                await asyncio.sleep(self.cpu_delay)
            game, g = room.game, room.order.index(CPU_SEAT)
            if room.state != PLAYING or g not in game.awaiting():
                return
            token, state, legal = game.tokens[g], game.state, game.legal(g)
            t0 = time.perf_counter()
            try:
                action = await asyncio.get_running_loop().run_in_executor(
                    self.pool, lambda: self._agent(room).act(state, g))
                index = legal.index(action)
            except Exception:           # AI が落ちても対局を止めない。合法手の先頭を打たせ、記録に印を残す
                log.exception("cpu agent failed in room %s", room.id)
                index = 0
                note = {"t": P.S_ERROR, "code": "cpu_error",
                        "msg": "CPU が考えるのに失敗したので、選べる手の先頭を打たせた（サーバの窓にエラーの内容が出ている）"}
                self.deliver(room, [(m.id, note) for m in room.members.values() if m.id != CPU_ID])
            ms = int((time.perf_counter() - t0) * 1000)
            if room.game is not game or room.state != PLAYING or game.tokens[g] != token:
                return                  # 考えている間に局面が変わった（投了・再戦など）。この答えは捨てる
            out = room.handle(CPU_ID, {"t": P.C_ACT, "token": token, "index": index, "ms": ms})
            self.deliver(room, out)
            self.cpu_fails.pop(room.id, None)
        except AppError as e:
            self.cpu_fails[room.id] = self.cpu_fails.get(room.id, 0) + 1
            log.warning("cpu move rejected in room %s: %s", room.id, e)
        except Exception:
            self.cpu_fails[room.id] = self.cpu_fails.get(room.id, 0) + 1
            log.exception("cpu move failed in room %s", room.id)
        finally:
            self.thinking.discard(room.id)
        if room.id in self.manager.rooms:
            self.after_change(room)     # 保存して、まだ AI の番なら続けて考えさせる

    # -- 入退室
    def attach(self, conn: Conn, hello: dict) -> None:
        if hello.get("v") != P.PROTOCOL_VERSION:
            raise AppError("version", "アプリの版が合わない。更新してほしい")     # R-UPD-10
        room = self.manager.get(hello.get("room"))
        member, out = room.join(hello.get("name"), hello.get("pass"), hello.get("key"))
        old = self.conns.get((room.id, member.id))
        if old is not None and old is not conn:        # 同じ鍵で別の画面から入り直した。古い方を閉じる
            old.push({"t": P.S_BYE, "code": "replaced"})
            old.push(None)
            old.member_id = None
        conn.room_id, conn.member_id = room.id, member.id
        self.conns[(room.id, member.id)] = conn
        self.deliver(room, out)
        self.after_change(room)

    def detach(self, conn: Conn) -> None:
        if conn.member_id is None:
            return
        key = (conn.room_id, conn.member_id)
        if self.conns.get(key) is conn:
            del self.conns[key]
            room = self.manager.rooms.get(conn.room_id)
            if room is not None:
                self.deliver(room, room.disconnect(conn.member_id, self.clock()))
                self.after_change(room)
        conn.member_id = None

    async def frames_for(self, key, dump: dict, result: dict) -> dict:
        """リプレイの手の列を作る（重いので別のスレッドで）。同じ局は作り直さない。"""
        if key not in self.replay_cache:
            frames = await asyncio.get_running_loop().run_in_executor(self.replay_pool, replay_mod.build, dump, result)
            self.replay_cache[key] = frames
            while len(self.replay_cache) > 4:
                self.replay_cache.pop(next(iter(self.replay_cache)))
        return self.replay_cache[key]

    async def send_replay(self, conn: Conn, msg: dict, ref=None) -> None:
        """部屋の最後の局のリプレイ（APP-019）。終局したあとだけ。部屋の全員（観戦者も）が、4 つの視点のどれでも見られる。"""
        try:
            room = self.manager.rooms.get(conn.room_id)
            if room is None:
                raise AppError("no_room", "部屋が閉じた")
            if room.state != FINISHED or room.game is None:
                raise AppError("not_finished", "リプレイは終局したあとに見られる")
            viewer = replay_mod.parse_viewer(msg.get("viewer", 0))
            frames = await self.frames_for((room.id, room.games_played), room.game.dump(), room.game.result())
            conn.push(replay_mod.message(frames, viewer, names=room.game_names(), result=room.game.result(),
                                         source={"room": room.id, "game": room.games_played}))
        except AppError as e:
            conn.push(_err(e, ref))

    def receive(self, conn: Conn, msg) -> None:
        room = self.manager.rooms.get(conn.room_id)
        if room is None:
            raise AppError("no_room", "部屋が閉じた")
        out = room.handle(conn.member_id, msg)
        self.deliver(room, out)
        self.after_change(room)

    # -- 掃除（R-ROOM-10）
    def sweep(self) -> list:
        now, closed = self.clock(), []
        for rid, since in list(self.empty_since.items()):
            room = self.manager.rooms.get(rid)
            if room is None:
                self.empty_since.pop(rid)
                continue
            ttl = ROOM_TTL_PLAYING if room.state == "playing" else (ROOM_TTL_CPU if room.cpu else ROOM_TTL)
            if room.is_empty() and now - since >= ttl:
                self._close_room(rid)
                closed.append(rid)
        return closed


def _err(e: AppError, ref=None) -> dict:
    d = {"t": P.S_ERROR, "code": e.code, "msg": e.msg}
    if ref is not None:
        d["ref"] = ref
    return d


async def _writer(conn: Conn) -> None:
    try:
        while True:
            msg = await conn.queue.get()
            if msg is None:
                break
            await conn.ws.send_str(json.dumps(msg, ensure_ascii=False, separators=(",", ":")))
    except (ConnectionError, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        conn.dead = True
        if not conn.ws.closed:
            await conn.ws.close()


def _parse(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        raise AppError("bad_message", "JSON として読めない") from None


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    hub: Hub = request.app[HUB]
    ws = web.WebSocketResponse(heartbeat=20.0, max_msg_size=MAX_MSG)
    await ws.prepare(request)
    conn = Conn(ws)
    writer = asyncio.ensure_future(_writer(conn))
    try:
        try:
            first = await ws.receive(timeout=HELLO_TIMEOUT)
            if first.type != WSMsgType.TEXT:
                raise AppError("bad_message", "最初は hello")
            hello = _parse(first.data)
            if not isinstance(hello, dict) or hello.get("t") != P.C_HELLO:
                raise AppError("bad_message", "最初は hello")
            hub.attach(conn, hello)
        except asyncio.TimeoutError:
            conn.push({"t": P.S_BYE, "code": "hello_timeout"})
            return ws
        except AppError as e:
            conn.push(_err(e))
            conn.push({"t": P.S_BYE, "code": e.code})
            return ws

        window, count = time.monotonic(), 0
        async for m in ws:
            if conn.dead or conn.member_id is None:
                break
            if m.type != WSMsgType.TEXT:
                continue
            now = time.monotonic()
            if now - window >= 1.0:
                window, count = now, 0
            count += 1
            if hub.flood_per_sec and count > hub.flood_per_sec:
                conn.push({"t": P.S_BYE, "code": "flood"})
                break
            ref = None
            try:
                msg = _parse(m.data)
                if isinstance(msg, dict):
                    ref = msg.get("ref") if isinstance(msg.get("ref"), (int, str)) else None
                if isinstance(msg, dict) and msg.get("t") == P.C_REPLAY:
                    asyncio.ensure_future(hub.send_replay(conn, msg, ref))
                    continue
                hub.receive(conn, msg)
            except AppError as e:
                for _, again in e.resync:
                    conn.push(again)
                conn.push(_err(e, ref))
            except Exception:           # ここに来たらバグ。状態は保存済みの版に任せ、この接続だけ閉じる
                log.exception("unexpected error in room %s", conn.room_id)
                conn.push({"t": P.S_BYE, "code": "server_error"})
                break
    finally:
        hub.detach(conn)
        conn.push(None)
        try:
            await asyncio.wait_for(writer, 5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            writer.cancel()
    return ws


async def create_room(request: web.Request) -> web.Response:
    hub: Hub = request.app[HUB]
    try:
        body = await request.json()
    except ValueError:
        body = None
    try:
        if not isinstance(body, dict):
            raise AppError("bad_message", "JSON の辞書を送ってほしい")
        hub.make_room_space()
        room = hub.manager.create(body.get("pass"))
    except AppError as e:
        return web.json_response({"ok": False, "code": e.code, "msg": e.msg}, status=400)
    hub.after_change(room)
    return web.json_response({"ok": True, "room": room.id})       # 合言葉はリンクに入れない（R-SEC-4）


async def health(request: web.Request) -> web.Response:
    hub: Hub = request.app[HUB]
    return web.json_response({"ok": True, "v": P.PROTOCOL_VERSION, "rooms": len(hub.manager.rooms), "cpu": hub.cpu_enabled})


async def version(request: web.Request) -> web.Response:
    """いまの版・更新の履歴・更新の結果（要件 R-UPD-8・R-UPD-9）。設定画面が読む。"""
    d = release.info()
    d["protocol"] = P.PROTOCOL_VERSION
    d["rules_version"], d["cards_version"] = rules_version(), cards_version()
    return web.json_response(d, dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def cpu_options(request: web.Request) -> web.Response:
    """CPU 対戦の選択肢（要件 R-CPU）。手元で起動したときだけ出る。"""
    hub: Hub = request.app[HUB]
    decks = cpu_mod.options() if hub.cpu_enabled else {}
    return web.json_response({"enabled": bool(decks), "decks": {d: [{"level": o["level"], "label": o["label"]} for o in v]
                                                                  for d, v in decks.items()}},
                             dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def create_cpu_room(request: web.Request) -> web.Response:
    hub: Hub = request.app[HUB]
    try:
        body = await request.json()
    except ValueError:
        body = None
    try:
        if not isinstance(body, dict):
            raise AppError("bad_message", "JSON の辞書を送ってほしい")
        room, passphrase = hub.new_cpu_room(body.get("deck"), body.get("level"), body.get("first", "random"))
    except AppError as e:
        return web.json_response({"ok": False, "code": e.code, "msg": e.msg}, status=400)
    return web.json_response({"ok": True, "room": room.id, "pass": passphrase})


def _local_only(hub: "Hub"):
    """手元で起動したときだけ使える口（記録の一覧とリプレイ）。外へ出したサーバでは、他人の対局の記録を見せない。"""
    if not hub.cpu_enabled:
        raise web.HTTPNotFound(text=json.dumps({"ok": False, "code": "local_only", "msg": "手元で起動したときだけ使える"}),
                               content_type="application/json")


async def records(request: web.Request) -> web.Response:
    """終局した対局の記録の一覧（新しい順）。手元起動のときだけ（APP-019）。"""
    hub: Hub = request.app[HUB]
    _local_only(hub)
    out = []
    for rid, rec in hub.store.list_records():
        res = rec.get("result") or {}
        out.append({"id": rid, "played_at": rec.get("played_at"), "kind": rec.get("kind"), "names": rec.get("names"),
                    "decks": [d.get("name", "") for d in rec.get("decks") or []], "result": res,
                    "opponent": (rec.get("opponent") or {}).get("name"), "cpu_seat": (rec.get("opponent") or {}).get("seat"),
                    "problem": record_problem(rec)})
    return web.json_response({"ok": True, "records": out}, dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def record_replay(request: web.Request) -> web.Response:
    """手元の記録 1 件のリプレイ（APP-019）。版が違う記録は理由を返して再生しない。"""
    hub: Hub = request.app[HUB]
    _local_only(hub)
    try:
        body = await request.json()
    except ValueError:
        body = None
    try:
        if not isinstance(body, dict):
            raise AppError("bad_message", "JSON の辞書を送ってほしい")
        viewer = replay_mod.parse_viewer(body.get("viewer", 0))
        rec = hub.store.get_record(body.get("id"))
        if rec is None:
            raise AppError("no_record", "その記録は無い")
        why = record_problem(rec)
        if why:
            raise AppError("old_record", why)
        dump = {"seed": rec["seed"], "decks": rec["decks"], "applies": rec["applies"], "resigned": rec.get("resigned")}
        frames = await hub.frames_for(("rec", body.get("id")), dump, rec.get("result"))
    except AppError as e:
        return web.json_response({"ok": False, "code": e.code, "msg": e.msg}, status=400)
    msg = replay_mod.message(frames, viewer, names=rec.get("names") or ["", ""], result=rec.get("result"),
                             source={"record": body.get("id")})
    return web.json_response({"ok": True, **msg}, dumps=lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")))


async def cards(request: web.Request) -> web.Response:
    """カードの表示データ。番号・名前・色・数値・オペコードの言い換え文だけで、公式テキストも画像も含まない（R-ASSET-1）。"""
    return web.json_response({"version": cards_version(), "rules": rules_version(), "cards": describe.card_db()},
                             dumps=lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")))


async def decks(request: web.Request) -> web.Response:
    """同梱のデッキリスト（カード番号と枚数だけ）。自作デッキは画面側がブラウザに保管する。"""
    out = []
    for path in sorted((ENGINE_DIR / "decklists").glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            out.append({"name": str(d.get("name") or path.stem), "chara_deck": list(d["chara_deck"]),
                        "action_deck": list(d["action_deck"])})
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("decklist %s could not be read", path.name)
    return web.json_response({"decks": out}, dumps=lambda o: json.dumps(o, ensure_ascii=False))


@web.middleware
async def no_cache(request: web.Request, handler):
    """画面のファイルは毎回確かめさせる。更新したのに古い画面が残る事故を避ける（R-UPD-10 の手前の備え）。"""
    resp = await handler(request)
    if request.path in ("/", "/deck") or request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


async def deck_page(request: web.Request) -> web.StreamResponse:
    """デッキメーカー（APP-014）。カードの画像も公式のテキストも持たない（遊ぶ人の手元から読む）。"""
    path = STATIC_DIR / "deck.html"
    if path.exists():
        return web.FileResponse(path)
    raise web.HTTPNotFound()


async def index(request: web.Request) -> web.StreamResponse:
    path = STATIC_DIR / "index.html"
    if path.exists():
        return web.FileResponse(path)
    return web.Response(text="MeichoSim (unofficial)", content_type="text/plain")


async def _sweeper(app: web.Application):
    async def loop():
        while True:
            await asyncio.sleep(60)
            try:
                app[HUB].sweep()
            except Exception:
                log.exception("sweep failed")
    task = asyncio.ensure_future(loop())
    yield
    task.cancel()


def create_app(data_dir, *, seed_source=None, clock=time.time, flood_per_sec=FLOOD_PER_SEC,
               cpu: bool = False, cpu_delay: float = CPU_DELAY, allow_origins=()) -> web.Application:
    app = web.Application(client_max_size=MAX_MSG, middlewares=[origin_guard, no_cache])
    app[ALLOWED] = parse_allow_origins(allow_origins)
    app[HUB] = Hub(Store(data_dir), seed_source=seed_source, clock=clock, flood_per_sec=flood_per_sec,
                   cpu=cpu, cpu_delay=cpu_delay)
    app.router.add_get("/", index)
    app.router.add_get("/deck", deck_page)
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/version", version)
    app.router.add_get("/api/cpu", cpu_options)
    app.router.add_post("/api/cpu", create_cpu_room)
    app.router.add_get("/api/cards", cards)
    app.router.add_get("/api/decks", decks)
    app.router.add_get("/api/records", records)
    app.router.add_post("/api/records/replay", record_replay)
    if STATIC_DIR.exists():
        app.router.add_static("/static/", STATIC_DIR)
    app.cleanup_ctx.append(_sweeper)
    return app


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="MeichoSim server (unofficial fan-made tool)")
    ap.add_argument("--data", required=True, help="保存先のフォルダ")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--cpu", choices=("auto", "on", "off"), default="auto",
                    help="CPU 対戦を出すか。auto は、このPCの中からしか届かない起動（127.0.0.1 で --allow-origin なし）のときだけ出す")
    ap.add_argument("--allow-origin", action="append", default=[], metavar="URL",
                    help=f"外から入るときのサイト（例: https://xxxx.trycloudflare.com）。何度でも書ける。環境変数 {ENV_ALLOW} にカンマ区切りでも書ける")
    a = ap.parse_args(argv)
    try:
        allow = parse_allow_origins(a.allow_origin, os.environ.get(ENV_ALLOW))
    except ValueError as e:
        ap.error(str(e))
    cpu = decide_cpu(a.cpu, a.host, allow)      # 要件: CPU 対戦は手元起動のときだけ。外へ出すサーバは AI を動かさない
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for o in allow:
        log.info("allow origin: %s", o)
    log.info("cpu: %s", "on" if cpu else "off")
    web.run_app(create_app(a.data, cpu=cpu, allow_origins=allow), host=a.host, port=a.port, access_log=None)


if __name__ == "__main__":
    main()
