"""CPU 対戦（M5）の検査。AI は「席に座る参加者の 1 種」で、対人戦と同じ経路を通る。

計画書 8.2 の M5 の完了条件のうち: 同じ画面（＝同じサーバと同じプロトコル）で champion と打てる／記録が `record.verify` で再生照合できる。
"""
import asyncio
import json

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("pytest_asyncio")

import aiohttp  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402

from app import server as S  # noqa: E402
from app.bot import Bot  # noqa: E402
from app.core import cpu as cpu_mod  # noqa: E402
from app.core import protocol as P  # noqa: E402
from app.core.game import make_config  # noqa: E402
from app.core.persist import legacy_view  # noqa: E402
from app.tests.test_server import allowed_ids, assert_no_leak, until  # noqa: E402

pytestmark = pytest.mark.asyncio

try:
    cpu_mod.options()
    from webapp import record as legacy_record
except Exception as e:                                      # 登録簿や学習済みモデルが無い環境
    pytest.skip(f"CPU 対戦の相手を読み込めない: {e}", allow_module_level=True)


async def boot(tmp_path, **kw):
    kw.setdefault("flood_per_sec", None)
    kw.setdefault("cpu", True)
    kw.setdefault("cpu_delay", 0)
    srv = TestServer(S.create_app(tmp_path / "data", **kw))
    await srv.start_server()
    return srv, str(srv.make_url("")).rstrip("/")


async def new_cpu(url, deck, level, first="random"):
    async with aiohttp.ClientSession() as s:
        async with s.post(url + "/api/cpu", json={"deck": deck, "level": level, "first": first}) as r:
            return r.status, await r.json()


def records(tmp_path):
    return [json.loads(x) for p in (tmp_path / "data" / "games").glob("*.jsonl")
            for x in p.read_text(encoding="utf-8").splitlines()]


async def test_tiers_follow_the_registry():
    """段の割り当ては登録簿の名前で、SD001 のつよいは登録簿の既定の相手（＝現 champion）を指す（要件 R-EXT-1）。"""
    from webapp import agents
    opts = cpu_mod.options()
    assert [o["label"] for o in opts["SD001"]] == ["やさしい", "ふつう", "つよい"]
    assert opts["SD001"][2]["agent"] == agents.DEFAULT_OPPONENT
    assert [o["agent"] for o in opts["SD02"]] == ["heuristic", "greedy", "planner_lh"]      # APP-005 追記 1（D-112）
    assert all(o["agent"] in agents.OPPONENTS for v in opts.values() for o in v)


@pytest.mark.parametrize("deck,level,first", [("SD02", 1, "me"), ("SD001", 2, "cpu")])
async def test_play_a_full_game_against_cpu(tmp_path, deck, level, first):
    srv, url = await boot(tmp_path)
    try:
        status, body = await new_cpu(url, deck, level, first)
        assert status == 200 and body["ok"]
        bot = Bot(url, body["room"], body["pass"], "マスター", seed=7)        # 席もデッキも指定しない: 入ればすぐ始まる
        await bot.enter()
        result = await bot.play(timeout=120)
        assert result["reason"] == "normal" and not bot.errors
        info = bot.room_info
        assert info["kind"] == "cpu" and info["cpu"] == {"level": level, "label": cpu_mod.LEVEL_JA[level], "deck": deck}
        assert info["seats"][1]["name"] == f"CPU（{cpu_mod.LEVEL_JA[level]}）" and info["seats"][1]["connected"]
        assert info["order"] == ([0, 1] if first == "me" else [1, 0])          # 先攻の指定が効いている

        rec, = records(tmp_path)
        opp = rec["opponent"]
        assert rec["kind"] == "cpu" and rec["verified"] is True
        assert opp["name"] == cpu_mod.resolve(deck, level) and opp["level"] == level and opp["deck"] == deck
        assert opp["seat"] == info["order"].index(1)
        assert 722000 <= rec["seed"] <= 741999 and 722000 <= opp["seed"] <= 741999 and rec["seed"] != opp["seed"]    # APP-008
        # 所要時間は席ごとに分けて測る（R-DATA-7）。AI の席の値は AI が考えた時間そのもの
        assert len(rec["times"]) == len(rec["applies"])
        assert all(set(t) == set(a) for t, a in zip(rec["times"], rec["applies"]))
        ai_ms = [t[str(opp["seat"])] for t in rec["times"] if str(opp["seat"]) in t]
        assert ai_ms and all(isinstance(x, int) and 0 <= x < 60000 for x in ai_ms)
        # 現行の `webapp/record.py` の verify で、そのまま再生照合できる（M5 の完了条件）
        old = legacy_view(rec)
        got = legacy_record.verify(old, make_config(rec["decks"]))
        assert got["turns"] == rec["result"]["turns"] and got["life"] == rec["result"]["life"]
        assert got["winner"] == ("human" if rec["result"]["winner"] == 1 - opp["seat"] else "ai")
        # 人間の席に、AI の手札や山札は届いていない（対人戦と同じ物差し・R-SEC-2）
        assert_no_leak(bot, allowed_ids(rec), 1 - opp["seat"], rec["seed"])
        await bot.close()
    finally:
        await srv.close()


async def test_rematch_restart_and_spectator(tmp_path):
    srv, url = await boot(tmp_path)
    _, body = await new_cpu(url, "SD02", 0)
    room, pw = body["room"], body["pass"]
    bot = Bot(url, room, pw, "マスター", seed=3)
    await bot.enter()
    await bot.play(timeout=120)
    # 再戦: CPU はいつでも応じる。新しい局は新しいシードで始まる
    await bot.send({"t": "rematch"})
    await bot.wait_for(lambda m: m["t"] == P.S_VIEW and m["view"]["applies"] == 0)
    bot.answered = -1
    watcher = Bot(url, room, pw, "見学")                                       # 合言葉を伝えれば観戦できる
    await watcher.enter()
    await watcher.wait_for(lambda m: m["t"] == P.S_VIEW)
    assert watcher.view["viewer"] == "spec"
    await bot.play(stop=until(12), timeout=60)
    hub = srv.app[S.HUB]
    seeds = (hub.manager.rooms[room].game.seed, hub.manager.rooms[room].ai_seed)
    key = bot.key
    await bot.close()
    await watcher.close()
    await srv.close()                                                          # サーバを落とす

    srv, url = await boot(tmp_path)                                            # 起こし直しても、続きから AI と打てる（R-NET-6）
    try:
        r = srv.app[S.HUB].manager.rooms[room]
        assert r.cpu and (r.game.seed, r.ai_seed) == seeds and r.members["cpu"].connected
        bot2 = Bot(url, room, "", "マスター", seed=4, key=key)
        await bot2.connect()
        await bot2.wait_for(lambda m: m["t"] == P.S_VIEW and m["full"])
        assert (await bot2.play(timeout=120))["reason"] == "normal"
        recs = records(tmp_path)
        assert len(recs) == 2 and all(x["verified"] for x in recs)
        assert len({x["seed"] for x in recs} | {x["opponent"]["seed"] for x in recs}) == 4      # シードは使い回さない
        await bot2.close()
    finally:
        await srv.close()


async def test_cpu_is_off_unless_launched_locally(tmp_path):
    srv, url = await boot(tmp_path, cpu=False)
    try:
        status, body = await new_cpu(url, "SD001", 0)
        assert status == 400 and body["code"] == "cpu_unavailable"
        async with aiohttp.ClientSession() as s:
            async with s.get(url + "/api/cpu") as r:
                assert (await r.json()) == {"enabled": False, "decks": {}}
            async with s.get(url + "/api/health") as r:
                assert (await r.json())["cpu"] is False
    finally:
        await srv.close()


async def test_bad_requests_and_room_limit(tmp_path):
    srv, url = await boot(tmp_path)
    try:
        for deck, level, first in (("SD999", 0, "random"), ("SD001", 3, "random"), ("SD001", True, "random"),
                                   ("SD001", "2", "random"), ("SD001", 0, "loser")):
            status, body = await new_cpu(url, deck, level, first)
            assert status == 400 and body["code"] == "bad_message", (deck, level, first)
        # CPU 対戦は 1 人で何度も作り直す。誰もいない部屋は古いものから閉じて、上限に引っかからないようにする
        ids = []
        for _ in range(P.MAX_ROOMS + 3):
            status, body = await new_cpu(url, "SD02", 0)
            assert status == 200, body
            ids.append(body["room"])
        hub = srv.app[S.HUB]
        assert len(hub.manager.rooms) == P.MAX_ROOMS and ids[-1] in hub.manager.rooms and ids[0] not in hub.manager.rooms
        assert not (tmp_path / "data" / "rooms" / f"{ids[0]}.json").exists()
        # 対人戦の部屋は、そのために閉じられない
        async with aiohttp.ClientSession() as s:
            async with s.get(url + "/api/cpu") as r:
                opts = await r.json()
        assert opts["enabled"] and set(opts["decks"]) == {"SD001", "SD02"}
        assert all("agent" not in o for v in opts["decks"].values() for o in v)      # 登録名は画面に出さない（表示は やさしい・ふつう・つよい）
    finally:
        await srv.close()
