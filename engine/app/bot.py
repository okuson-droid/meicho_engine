"""画面なしの自動クライアント。合法手から決定的な乱数で選んで送るだけである。

用途は 2 つ。M2 のテスト（2 体で 1 局を WebSocket 越しに打ち切る）と、画面ができたあとの手動確認の相手役。
**強さは無い。**CPU 対戦の AI（M5）とは別物である。

例: `python -m app.bot --url http://127.0.0.1:8765 --room <部屋ID> --pass <合言葉> --deck decklists/SD001.json`
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from typing import Optional

import aiohttp

from .core import protocol as P


class Bot:
    def __init__(self, base_url: str, room: str, passphrase: str, name: str, *, deck: Optional[dict] = None,
                 seat: Optional[int] = None, seed: int = 0, key: Optional[str] = None,
                 delay: float = 0.0):
        self.base_url, self.room, self.passphrase, self.name = base_url.rstrip("/"), room, passphrase, name
        self.deck, self.seat, self.key = deck, seat, key
        self.delay = delay              # 1 手ごとの間（秒）。本番のサーバは連投を切るので、手動確認では 0 にしない
        self.rnd = random.Random(seed)
        self.member: Optional[str] = None
        self.room_info: Optional[dict] = None
        self.view: Optional[dict] = None
        self.inbox: list = []           # 受け取った全メッセージ（テストの検査用）
        self.errors: list = []
        self.answered = -1              # 返答済みの決定の番号
        self.ws = None
        self._session = None

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self.ws = await self._session.ws_connect(self.base_url + "/ws")
        await self.send({"t": P.C_HELLO, "v": P.PROTOCOL_VERSION, "room": self.room,
                         "name": self.name, "pass": self.passphrase, "key": self.key})

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self._session is not None:
            await self._session.close()
        self.ws = self._session = None

    async def send(self, msg: dict) -> None:
        await self.ws.send_str(json.dumps(msg))

    async def recv(self, timeout: float = 10.0) -> Optional[dict]:
        m = await self.ws.receive(timeout=timeout)
        if m.type != aiohttp.WSMsgType.TEXT:
            return None
        msg = json.loads(m.data)
        self.inbox.append(msg)
        t = msg["t"]
        if t == P.S_WELCOME:
            self.member, self.key, self.room_info = msg["member"], msg["key"], msg["room"]
        elif t == P.S_ROOM:
            self.room_info = msg["room"]
        elif t == P.S_VIEW:
            self.view = msg["view"]
        elif t == P.S_ERROR:
            self.errors.append(msg)
        return msg

    async def wait_for(self, pred, timeout: float = 10.0) -> dict:
        while True:
            msg = await self.recv(timeout)
            if msg is None:
                raise ConnectionError("closed")
            if pred(msg):
                return msg

    async def enter(self) -> None:
        """入室して、席に着き、デッキを出し、準備完了にする。"""
        await self.connect()
        await self.wait_for(lambda m: m["t"] == P.S_WELCOME)
        if self.seat is not None and self.deck is not None:
            await self.send({"t": P.C_SIT, "seat": self.seat})
            await self.send({"t": P.C_DECK, "deck": self.deck})
            await self.send({"t": P.C_READY, "on": True})

    def my_turn(self) -> bool:
        v = self.view
        return bool(v) and v.get("viewer") in (0, 1) and v["viewer"] in v["awaiting"] \
            and v["token"] != self.answered and v["outcome"] is None

    async def act_once(self) -> bool:
        if not self.my_turn():
            return False
        v = self.view
        self.answered = v["token"]
        if self.delay:
            await asyncio.sleep(self.delay)
        await self.send({"t": P.C_ACT, "token": v["token"], "index": self.rnd.randrange(len(v["legal"]))})
        return True

    async def play(self, *, stop=None, timeout: float = 20.0) -> Optional[dict]:
        """終局まで打つ。終局したら結果を返す。`stop(self)` が真になったら、打たずに `None` を返す。

        2 体を並べて途中で止めるときは、**両方に同じ条件**（例: `view["applies"] >= 15`）を渡すこと。
        同じ `view` が両方に届くので、片方だけが止まって相手を待たせることが無い。
        """
        while True:
            if self.room_info and self.room_info["state"] == "finished":
                return self.room_info["result"]
            if stop is not None and stop(self):
                return None
            await self.act_once()
            if await self.recv(timeout) is None:
                raise ConnectionError("closed")


async def _main(a) -> None:
    with open(a.deck, encoding="utf-8") as f:
        deck = json.load(f)
    bot = Bot(a.url, a.room, a.passphrase, a.name, deck=deck, seat=a.seat, seed=a.seed, delay=a.delay)
    await bot.enter()
    print(await bot.play(timeout=3600.0))
    await bot.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--room", required=True)
    ap.add_argument("--pass", dest="passphrase", required=True)
    ap.add_argument("--deck", required=True)
    ap.add_argument("--name", default="bot")
    ap.add_argument("--seat", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.3, help="1 手ごとの間（秒）")
    asyncio.run(_main(ap.parse_args()))
