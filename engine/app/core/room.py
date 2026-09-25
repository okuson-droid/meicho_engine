"""部屋（要件 R-ROOM-1〜10・R-NET-2〜7・R-SPEC-1〜4）。通信にも時計にも触らない純粋なロジック。

`Room` のメソッドは状態を進め、**送るべきメッセージの列 `[(宛先の member_id, メッセージ)]`** を返す。
実際に送るのは外側（`app/server.py`）の仕事である。こうしておくと、通信なしで全部テストできる。

席の番号は 2 種類ある。取り違えないこと。

- **部屋の席** `seat`（0／1）: 入室した人が座る椅子。再戦しても変わらない
- **対局の席** `gseat`（0／1）: エンジンのプレイヤー番号。0 が先攻。局ごとに `order` で対応づける
  （`order[gseat] = 部屋の席`）。`view` の中の席番号はすべて対局の席である
"""
from __future__ import annotations

import hashlib
import hmac
import random
import secrets
from typing import Callable, Optional

from . import protocol as P
from .game import Game, check_deck
from .protocol import AppError
from .views import SPECTATOR

LOBBY, CHOOSING, PLAYING, FINISHED = "lobby", "choosing_first", "playing", "finished"
CPU_ID = "cpu"            # CPU 対戦の相手の席に座る、通信を持たない参加者
CPU_SEAT = 1


def _hash_pass(salt: str, passphrase: str) -> str:
    return hashlib.sha256((salt + "\0" + passphrase).encode("utf-8")).hexdigest()


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Member:
    def __init__(self, mid: str, name: str, key_hash: str):
        self.id, self.name, self.key_hash = mid, name, key_hash   # 鍵そのものは持たない（R-SEC-4）
        self.seat: Optional[int] = None
        self.connected = True
        self.left_at: Optional[float] = None      # 切断した時刻（外側が入れる。表示用・R-NET-2）


class Room:
    def __init__(self, rid: str, passphrase: str, *, seed_source: Callable[[], int] = None,
                 salt: str = None, pass_hash: str = None, cpu: Optional[dict] = None):
        """`cpu` を渡すと CPU 対戦の部屋になる: `{deck: デッキ, level, agent: 登録名, label, first}`。

        AI は「席に座る参加者の 1 種」で、対人戦と同じ経路（`handle` に `act` を渡す）を通る（計画書 6 章）。
        考えるのは外側（`app/server.py`）の仕事で、ここは席・デッキ・準備完了・再戦を人間の代わりに済ませるだけである。
        """
        self.id = rid
        self.salt = salt or secrets.token_hex(8)
        self.pass_hash = pass_hash or _hash_pass(self.salt, passphrase)   # 平文は持たない（R-SEC-4）
        self.members: dict = {}
        self.owner: Optional[str] = None
        self.seats: list = [None, None]           # 部屋の席 → member_id
        self.decks: list = [None, None]           # 部屋の席 → デッキ
        self.ready = [False, False]
        self.first_mode = "random"
        self.state = LOBBY
        self.game: Optional[Game] = None
        self.order: Optional[list] = None         # 対局の席 → 部屋の席
        self.chooser: Optional[int] = None        # 先攻後攻を選ぶ人の「部屋の席」（first_mode="loser"）
        self.last_loser: Optional[int] = None     # 前の局の敗者の「部屋の席」
        self.rematch = [False, False]
        self.games_played = 0
        self.finished: list = []                  # まだ外側が保存していない終局の記録
        self._seed_source = seed_source or (lambda: secrets.randbits(62))
        self._n = 0
        self.cpu = dict(cpu) if cpu else None
        self.ai_seed: Optional[int] = None        # この局の AI のシード（記録に残す）
        if self.cpu:
            m = Member(CPU_ID, f"CPU（{self.cpu['label']}）", "")      # 鍵は空。どんな鍵とも一致しない
            self.members[CPU_ID] = m
            m.seat, self.seats[CPU_SEAT] = CPU_SEAT, CPU_ID
            self.decks[CPU_SEAT] = dict(self.cpu["deck"])
            self.ready[CPU_SEAT] = True
            self.first_mode = {"me": "seat0", "cpu": "seat1"}.get(self.cpu.get("first"), "random")

    @property
    def kind(self) -> str:
        return "cpu" if self.cpu else "pvp"

    # ------------------------------------------------------------------ 入退室
    def check_pass(self, passphrase) -> bool:
        return isinstance(passphrase, str) and \
            hmac.compare_digest(self.pass_hash, _hash_pass(self.salt, passphrase))

    def join(self, name, passphrase=None, key=None) -> tuple:
        """入室または再入室。戻り値は `(member, 送るメッセージの列)`。

        席に戻れるのは鍵を持つ接続だけである（R-NET-4）。鍵が合えば合言葉は問わない。
        """
        if isinstance(key, str) and key:
            kh = _hash_key(key)
            for m in self.members.values():
                if m.id != CPU_ID and hmac.compare_digest(m.key_hash, kh):
                    m.connected, m.left_at = True, None
                    return m, self._welcome(m, key) + self._room_to_all()
        if not self.check_pass(passphrase):
            raise AppError("bad_pass", "合言葉が違う")
        if not isinstance(name, str) or not name.strip():
            raise AppError("bad_name", "表示名を入れてほしい")
        name = name.strip()[:P.MAX_NAME]
        watchers = [m for m in self.members.values() if m.seat is None]
        if len(watchers) >= P.MAX_SPECTATORS + self.seats.count(None):
            raise AppError("room_full", "観戦者は 4 人まで")
        self._n += 1
        key = secrets.token_urlsafe(18)
        m = Member(f"m{self._n}", name, _hash_key(key))
        self.members[m.id] = m
        if self.owner is None:
            self.owner = m.id
        out = self._welcome(m, key) + self._room_to_all()
        if self.cpu and self.state == LOBBY and self.seats[1 - CPU_SEAT] is None:
            # CPU 対戦: 入ってきた人をそのまま席に着け、同じデッキを持たせ、準備完了にする（＝すぐ始まる）
            out += self._on_sit(m, {"seat": 1 - CPU_SEAT})
            out += self._on_deck(m, {"deck": self.cpu["deck"]})
            out += self._on_ready(m, {"on": True})
        return m, out

    def disconnect(self, mid: str, now: float = None) -> list:
        """接続が切れた。席に着いている人は席を保つ（R-NET-2・R-NET-7）。観戦者は部屋から外す。"""
        m = self.members.get(mid)
        if m is None:
            return []
        m.connected, m.left_at = False, now
        if m.seat is None:
            del self.members[mid]
            if self.owner == mid:
                self.owner = next(iter(self.members), None)
        return self._room_to_all()

    def is_empty(self) -> bool:
        return not any(m.connected for m in self.members.values() if m.id != CPU_ID)

    # ------------------------------------------------------------------ 受信の入口
    def handle(self, mid: str, msg) -> list:
        """1 通を処理する。失敗は `AppError`。**投げるときは状態を変えていない**（R-NF-11）。"""
        m = self.members.get(mid)
        if m is None:
            raise AppError("not_member", "入室していない")
        if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
            raise AppError("bad_message", "メッセージの形が違う")
        fn = self._HANDLERS.get(msg["t"])
        if fn is None:
            raise AppError("bad_message", f"知らない種類: {msg['t'][:20]}")
        return fn(self, m, msg)

    # ------------------------------------------------------------------ ロビー
    def _need_lobby(self):
        if self.state not in (LOBBY, FINISHED):
            raise AppError("in_game", "対局中は変えられない")

    def _on_sit(self, m, msg):
        self._need_lobby()
        seat = msg.get("seat")
        if seat not in (0, 1) or isinstance(seat, bool):
            raise AppError("bad_message", "席は 0 か 1")
        holder = self.members.get(self.seats[seat]) if self.seats[seat] else None
        if holder is not None and (holder.connected or holder is m):
            raise AppError("seat_taken", "その席は埋まっている")
        if holder is not None:              # 対局の外で切断したままの人の席は、譲ってよい
            self._clear_seat(seat)
            del self.members[holder.id]
            if self.owner == holder.id:
                self.owner = m.id
        if m.seat is not None:
            self._clear_seat(m.seat)
        self.seats[seat], m.seat = m.id, seat
        self._back_to_lobby()
        return self._room_to_all()

    def _on_stand(self, m, msg):
        self._need_lobby()
        if m.seat is None:
            raise AppError("not_seated", "席に着いていない")
        self._clear_seat(m.seat)
        m.seat = None
        self._back_to_lobby()
        return self._room_to_all()

    def _clear_seat(self, seat: int):
        self.seats[seat], self.decks[seat] = None, None
        self.ready[seat], self.rematch[seat] = False, False

    def _back_to_lobby(self):
        """終局後に席やデッキが動いたら、次の局の準備に戻る（R-ROOM-9）。"""
        if self.state == FINISHED:
            self.state, self.game, self.order = LOBBY, None, None
            self.ready, self.rematch = [False, False], [False, False]

    def _on_deck(self, m, msg):
        self._need_lobby()
        if m.seat is None:
            raise AppError("not_seated", "席に着いていない")
        deck = msg.get("deck")
        check_deck(deck)                                    # 通らなければ bad_deck（R-ROOM-5）
        name = deck.get("name")
        name = name.strip()[:40] if isinstance(name, str) else ""
        self._back_to_lobby()
        self.decks[m.seat] = {"name": name, "chara_deck": list(deck["chara_deck"]),
                              "action_deck": list(deck["action_deck"])}
        self.ready[m.seat] = False
        return self._room_to_all()

    def _on_settings(self, m, msg):
        self._need_lobby()
        if m.id != self.owner:
            raise AppError("not_owner", "設定を変えられるのは部屋主だけ")
        first = msg.get("first")
        if first not in P.FIRST_MODES:
            raise AppError("bad_message", "first の値が違う")
        self.first_mode = first
        return self._room_to_all()

    def _on_ready(self, m, msg):
        self._need_lobby()
        if m.seat is None:
            raise AppError("not_seated", "席に着いていない")
        on = msg.get("on", True)
        if not isinstance(on, bool):
            raise AppError("bad_message", "on は真偽値")
        if on and self.decks[m.seat] is None:
            raise AppError("no_deck", "先にデッキを選んでほしい")
        self._back_to_lobby()
        self.ready[m.seat] = on
        if all(self.ready) and None not in self.seats:
            return self._begin()
        return self._room_to_all()

    def _on_rematch(self, m, msg):
        """同じ席・同じデッキでもう 1 局（R-ROOM-9）。2 人とも押したら始まる。"""
        if self.state != FINISHED:
            raise AppError("not_finished", "まだ終局していない")
        if m.seat is None:
            raise AppError("not_seated", "席に着いていない")
        self.rematch[m.seat] = True
        if self.cpu:
            self.rematch[CPU_SEAT] = True              # CPU はいつでも再戦に応じる
        if all(self.rematch) and None not in self.seats and None not in self.decks:
            self.state = LOBBY
            return self._begin()
        return self._room_to_all()

    # ------------------------------------------------------------------ 対局の開始
    def _begin(self) -> list:
        self.ready, self.rematch = [False, False], [False, False]
        if self.cpu:
            self.ready[CPU_SEAT] = True
        mode = self.first_mode
        if mode == "loser" and self.last_loser is not None:
            self.state, self.chooser, self.game = CHOOSING, self.last_loser, None
            return self._room_to_all()
        seed = self._seed_source()
        if mode == "seat0":
            first = 0
        elif mode == "seat1":
            first = 1
        else:                       # random。敗者がいない（初戦・引き分け）ときの "loser" もここ
            first = random.Random(seed ^ 0x5EED).randrange(2)
        return self._start(first, seed)

    def _on_first(self, m, msg):
        if self.state != CHOOSING:
            raise AppError("not_choosing", "いまは先攻後攻を選ぶ場面ではない")
        if m.seat is None or m.seat != self.chooser:
            raise AppError("not_chooser", "選ぶのは前の局の敗者")
        choice = msg.get("choice")
        if choice not in ("me", "opp"):
            raise AppError("bad_message", "choice は me か opp")
        first = m.seat if choice == "me" else 1 - m.seat
        return self._start(first, self._seed_source())

    def _start(self, first_seat: int, seed: int) -> list:
        self.order = [first_seat, 1 - first_seat]
        self.game = Game([self.decks[s] for s in self.order], seed)
        self.state, self.chooser = PLAYING, None
        self.ai_seed = self._seed_source() if self.cpu else None
        return self._room_to_all() + self._views(None, full=True)

    # ------------------------------------------------------------------ 対局中
    def gseat_of(self, m: Member) -> Optional[int]:
        if self.order is None or m.seat is None:
            return None
        return self.order.index(m.seat)

    def _viewer_of(self, m: Member):
        g = self.gseat_of(m)
        return SPECTATOR if g is None else g

    def _on_act(self, m, msg):
        if self.state != PLAYING:
            raise AppError("not_playing", "対局中ではない")
        g = self.gseat_of(m)
        if g is None:
            raise AppError("not_seated", "観戦者は操作できない")      # R-SPEC-3
        try:
            events = self.game.submit(g, msg.get("token"), msg.get("index"),
                                      ms=msg.get("ms") if m.id == CPU_ID else None)
        except AppError as e:
            if e.code == "stale":
                # 古い画面からの操作。最新の全量を本人にだけ送り直してから、エラーを返させる（R-NET-5）
                e.resync = self._view_msgs(m, [], full=True)
            raise
        return self._after_game_step(events)

    def _on_resign(self, m, msg):
        if self.state != PLAYING:
            raise AppError("not_playing", "対局中ではない")
        g = self.gseat_of(m)
        if g is None:
            raise AppError("not_seated", "観戦者は操作できない")
        return self._after_game_step(self.game.resign(g))

    def _after_game_step(self, events: dict) -> list:
        out = self._views(events, full=False)
        if self.game.over:
            self._finish()
            out = self._room_to_all() + out
        return out

    def game_names(self) -> list:
        """いまの局の席 0・席 1 の表示名（記録と同じ並び）。"""
        return [self.members[self.seats[s]].name if self.seats[s] in self.members else "" for s in self.order]

    def _finish(self):
        res = self.game.result()
        self.state = FINISHED
        self.games_played += 1
        self.last_loser = None if res["winner"] is None else self.order[1 - res["winner"]]
        names = [self.members[self.seats[s]].name if self.seats[s] in self.members else ""
                 for s in self.order]
        fin = {"game": self.game.dump(), "result": res, "names": names, "kind": self.kind,
               "room_seats": list(self.order), "first_mode": self.first_mode}
        if self.cpu:
            fin["opponent"] = {"name": self.cpu["agent"], "level": self.cpu["level"], "seed": self.ai_seed,
                               "seat": self.order.index(CPU_SEAT), "deck": self.cpu["deck"]["name"]}
        self.finished.append(fin)

    def _on_ping(self, m, msg):
        return [(m.id, {"t": P.S_PONG})]

    _HANDLERS = {P.C_SIT: _on_sit, P.C_STAND: _on_stand, P.C_DECK: _on_deck,
                 P.C_READY: _on_ready, P.C_SETTINGS: _on_settings, P.C_FIRST: _on_first,
                 P.C_ACT: _on_act, P.C_RESIGN: _on_resign, P.C_REMATCH: _on_rematch,
                 P.C_PING: _on_ping}

    # ------------------------------------------------------------------ 送るものを作る
    def info(self) -> dict:
        """部屋の公開情報。**デッキの中身・シード・鍵は入れない**（R-ROOM-6・R-SEC-3）。"""
        seats = []
        for s in (0, 1):
            mid = self.seats[s]
            m = self.members.get(mid) if mid else None
            seats.append(None if m is None else {
                "member": m.id, "name": m.name, "connected": m.connected, "left_at": m.left_at,
                "deck_name": self.decks[s]["name"] if self.decks[s] else None,
                "has_deck": self.decks[s] is not None, "ready": self.ready[s],
                "rematch": self.rematch[s]})
        return {
            "id": self.id, "state": self.state, "owner": self.owner, "first": self.first_mode,
            "seats": seats,
            "spectators": [{"member": m.id, "name": m.name}
                           for m in self.members.values() if m.seat is None],
            "order": self.order, "chooser": self.chooser, "games_played": self.games_played,
            "kind": self.kind, "cpu": ({"level": self.cpu["level"], "label": self.cpu["label"],
                                        "deck": self.cpu["deck"]["name"]} if self.cpu else None),
            "result": self.game.result() if self.game and self.game.over else None,
        }

    def _welcome(self, m: Member, key: str) -> list:
        out = [(m.id, {"t": P.S_WELCOME, "v": P.PROTOCOL_VERSION, "member": m.id, "key": key,
                       "room": self.info()})]
        if self.game is not None:
            out += self._view_msgs(m, [], full=True)        # 全量を送り直す（R-NET-3・R-SPEC-2）
        return out

    def _room_to_all(self) -> list:
        info = self.info()
        return [(m.id, {"t": P.S_ROOM, "room": info}) for m in self.members.values() if m.connected]

    def _view_msgs(self, m: Member, events: list, *, full: bool) -> list:
        viewer = self._viewer_of(m)
        return [(m.id, {"t": P.S_VIEW, "view": self.game.view(viewer), "events": events,
                        "full": full})]

    def _views(self, events: Optional[dict], *, full: bool) -> list:
        out = []
        for m in self.members.values():
            if m.connected:
                ev = [] if events is None else events[self._viewer_of(m)]
                out += self._view_msgs(m, ev, full=full)
        return out

    # ------------------------------------------------------------------ 保存と復元
    def dump(self) -> dict:
        return {
            "id": self.id, "salt": self.salt, "pass_hash": self.pass_hash, "owner": self.owner,
            "members": [{"id": m.id, "name": m.name, "key_hash": m.key_hash, "seat": m.seat}
                        for m in self.members.values() if m.seat is not None],
            "seats": self.seats, "decks": self.decks, "ready": self.ready,
            "first_mode": self.first_mode, "state": self.state, "order": self.order,
            "chooser": self.chooser, "last_loser": self.last_loser, "rematch": self.rematch,
            "games_played": self.games_played, "n": self._n, "cpu": self.cpu, "ai_seed": self.ai_seed,
            "game": self.game.dump() if self.game else None,
        }

    @classmethod
    def load(cls, d: dict, *, seed_source=None) -> "Room":
        """再起動後の復元（R-NET-6）。席に着いていた人だけを「切断中」として戻す。"""
        r = cls(d["id"], "", seed_source=seed_source, salt=d["salt"], pass_hash=d["pass_hash"], cpu=d.get("cpu"))
        for md in d["members"]:
            if md["id"] == CPU_ID:
                continue                                # CPU の席は上で作り直してある（切断中にはならない）
            m = Member(md["id"], md["name"], md["key_hash"])
            m.seat, m.connected = md["seat"], False
            r.members[m.id] = m
        r.ai_seed = d.get("ai_seed")
        r.owner = d["owner"] if d["owner"] in r.members else next(iter(r.members), None)
        r.seats, r.decks, r.ready = list(d["seats"]), list(d["decks"]), list(d["ready"])
        r.first_mode, r.state, r.order = d["first_mode"], d["state"], d["order"]
        r.chooser, r.last_loser = d["chooser"], d["last_loser"]
        r.rematch, r.games_played, r._n = list(d["rematch"]), d["games_played"], d["n"]
        r.game = Game.load(d["game"]) if d["game"] else None
        return r


class RoomManager:
    def __init__(self, *, seed_source=None, max_rooms: int = P.MAX_ROOMS):
        self.rooms: dict = {}
        self.max_rooms = max_rooms
        self._seed_source = seed_source
        self.closed: list = []                  # 場所を空けるために閉じた部屋（外側が保存ファイルを消す）

    def create(self, passphrase, *, cpu: Optional[dict] = None, seed_source=None) -> Room:
        if not isinstance(passphrase, str) or not 1 <= len(passphrase) <= 64:
            raise AppError("bad_pass", "合言葉は 1〜64 文字")
        if len(self.rooms) >= self.max_rooms and cpu:
            # CPU 対戦は 1 人で何度も作り直す。誰もいない CPU 対戦の部屋があれば、古いものから閉じて場所を空ける
            for rid, r in list(self.rooms.items()):
                if r.cpu and r.is_empty():
                    self.closed.append(rid)
                    del self.rooms[rid]
                    break
        if len(self.rooms) >= self.max_rooms:
            raise AppError("too_many_rooms", "部屋の数が上限（R-NF-5）")
        rid = secrets.token_urlsafe(9)
        self.rooms[rid] = Room(rid, passphrase, seed_source=seed_source or self._seed_source, cpu=cpu)
        return self.rooms[rid]

    def get(self, rid) -> Room:
        r = self.rooms.get(rid) if isinstance(rid, str) else None
        if r is None:
            raise AppError("no_room", "部屋が無い（閉じたか、リンクが違う）")
        return r

    def close(self, rid: str) -> None:
        self.rooms.pop(rid, None)
