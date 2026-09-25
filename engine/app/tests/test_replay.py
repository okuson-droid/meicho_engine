"""リプレイ（`app/core/replay.py`・要件 R-REP-1〜3・APP-019）の検査。

リプレイの手の列は「その席・観戦者が対局中に見ていたものと一字一句同じ」でなければならない（見直しで別の対局を見せない）。
全情報は終局した対局にだけ出す。手元の記録の一覧とリプレイは、手元で起動したときだけ使える。
"""
import asyncio
import json
import random

import pytest

from app.core import replay
from app.core.game import Game
from app.core.protocol import AppError
from app.core.views import FULL, SPECTATOR, card_ids_in

VIEWERS = (0, 1, SPECTATOR)


def play_and_watch(g: Game, rnd: random.Random, *, resign_at=None):
    """無作為に打ちながら、apply のたびに各相手が受け取った盤面と出来事を控える（対局中の画面が見たもの）。"""
    seen = {v: [{"view": g.public_view(v), "events": []}] for v in VIEWERS}
    n = 0
    while not g.over:
        if resign_at is not None and len(g.applies) >= resign_at:
            g.resign(0)
            break
        p = rnd.choice(g.awaiting())
        before = len(g.applies)
        out = g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))
        if len(g.applies) > before:                      # apply が起きた（提出だけなら出来事は「置いた」だけ）
            for v in VIEWERS:
                seen[v].append({"view": g.public_view(v), "events": out[v]})
        n += 1
        assert n < 5000
    return seen


def strip(view: dict) -> dict:
    """リプレイだけが足す欄（入力が無いことを示す空の欄）を除いて比べる。"""
    return {k: x for k, x in view.items() if k not in ("awaiting", "submitted", "applies", "legal", "labels", "hints", "token")}


def test_replay_shows_exactly_what_each_seat_and_spectator_saw(sd001, sd02):
    """席 0・席 1・観戦者のリプレイは、対局中にその相手へ届いた盤面と出来事と同じ（R-REP-1・R-REP-2）。"""
    for seed in range(6):
        g = Game([sd001, sd02], seed)
        seen = play_and_watch(g, random.Random(seed))
        frames = replay.build(g.dump(), g.result())
        for v in VIEWERS:
            assert len(frames[v]) == len(seen[v]) == len(g.applies) + 1
            for k, (f, s) in enumerate(zip(frames[v], seen[v])):
                assert strip(f["view"]) == strip(s["view"]), (seed, v, k)
                assert f["events"] == s["events"], (seed, v, k)
                assert f["view"]["legal"] == [] and f["view"]["applies"] == k
        assert frames[FULL][-1]["view"]["outcome"] == g.state.outcome


def test_full_view_opens_both_hands_and_nothing_else(sd001, sd02):
    """全情報は両者の手札とキャラデッキまで見せる。山札の並びは観測に無いので出さない（R-REP-2）。"""
    g = Game([sd001, sd02], 7)
    play_and_watch(g, random.Random(7))
    frames = replay.build(g.dump(), g.result())
    for k in (1, len(frames[FULL]) // 2, len(frames[FULL]) - 1):
        v = frames[FULL][k]["view"]
        assert v["viewer"] == FULL
        assert all(pl["hand"] is not None and pl["chara_deck"] is not None for pl in v["players"])
        assert all("deck" not in pl for pl in v["players"])           # 山札は枚数だけ
    last = frames[FULL][-1]["view"]["players"]
    assert [sorted(p["hand"]) for p in last] == [sorted(p.hand) for p in g.state.players]
    # 観戦のリプレイには手札の番号が出ない（全情報と違う）
    for f in frames[SPECTATOR]:
        assert all(pl["hand"] is None for pl in f["view"]["players"])


def test_resigned_game_ends_with_a_resign_step(sd001, sd02):
    g = Game([sd001, sd02], 3)
    play_and_watch(g, random.Random(3), resign_at=12)
    frames = replay.build(g.dump(), g.result())
    assert len(frames[0]) == len(g.applies) + 2
    last = frames[0][-1]
    assert last["events"] == [{"t": "game_over", "outcome": 1, "reason": "resign"}]
    assert last["view"]["outcome"] == 1 and last["view"]["resigned"] == 0


def test_unfinished_and_broken_records_are_refused(sd001, sd02):
    """終局していない対局は再生しない＝全情報を開かない（R-REP-3）。記録と局面が合わなければ理由つきで断る。"""
    g = Game([sd001, sd02], 5)
    rnd = random.Random(5)
    for _ in range(30):
        p = rnd.choice(g.awaiting())
        g.submit(p, g.tokens[p], rnd.randrange(len(g.legal(p))))
    with pytest.raises(AppError) as e:
        replay.build(g.dump())
    assert e.value.code == "not_finished"
    g2 = Game([sd001, sd02], 5)
    play_and_watch(g2, random.Random(5))
    d = g2.dump()
    bad = json.loads(json.dumps(d))
    bad["applies"][3] = {"0": {"type": "no_such_action"}}
    with pytest.raises(AppError) as e:
        replay.build(bad)
    assert e.value.code == "bad_record" and "4 手目" in e.value.msg
    with pytest.raises(AppError) as e:                       # 結果の照合
        replay.build(d, {**g2.result(), "winner": 1 - g2.result()["winner"]} if g2.result()["winner"] is not None else {"winner": 0, "reason": "normal"})
    assert e.value.code == "bad_record"


pytest.importorskip("aiohttp")
pytest.importorskip("pytest_asyncio")

import aiohttp  # noqa: E402

from app.bot import Bot  # noqa: E402
from app.core import protocol as P  # noqa: E402
from app.tests.test_server import PASS, boot, new_room, pair  # noqa: E402


@pytest.mark.asyncio
async def test_room_replay_only_after_the_game_and_for_everyone_in_the_room(tmp_path, sd001, sd02):
    """部屋のリプレイは終局したあとだけ。部屋の全員（観戦者も）が 4 つの視点のどれでも受け取れる。
    記録の一覧とリプレイの口は、手元で起動したときだけ（外へ出したサーバでは 404）。"""
    srv, url = await boot(tmp_path)                          # cpu=False ＝外へ出す形の起動
    try:
        room = await new_room(url)
        a, b = await pair(url, room, sd001, sd02)
        c = Bot(url, room, PASS, "C")
        await c.enter()
        # 対局中はリプレイを出さない
        await asyncio.sleep(0.2)
        await c.send({"t": P.C_REPLAY, "viewer": "full"})
        err = await c.wait_for(lambda m: m["t"] == P.S_ERROR)
        assert err["code"] == "not_finished"
        await asyncio.gather(a.play(), b.play(), c.play())
        for bot, viewer in ((c, "full"), (a, 0), (b, "spec")):
            await bot.send({"t": P.C_REPLAY, "viewer": viewer})
            msg = await bot.wait_for(lambda m: m["t"] == P.S_REPLAY, timeout=20)
            assert msg["viewer"] == viewer and msg["names"] and msg["result"]["reason"] == "normal"
            assert len(msg["frames"]) > 10 and msg["frames"][0]["events"] == []
        async with aiohttp.ClientSession() as s:
            async with s.get(url + "/api/records") as r:
                assert r.status == 404 and (await r.json())["code"] == "local_only"
            async with s.post(url + "/api/records/replay", json={"id": "2026-09:1", "viewer": 0}) as r:
                assert r.status == 404
        for x in (a, b, c):
            await x.close()
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_local_records_list_and_replay(tmp_path, sd001, sd02):
    """手元起動では、終局した対局が一覧に出て、リプレイを取れる。版の違う記録は理由つきで再生しない。"""
    srv, url = await boot(tmp_path, cpu=True, cpu_delay=0)
    try:
        room = await new_room(url)
        a, b = await pair(url, room, sd001, sd02)
        res, _ = await asyncio.gather(a.play(), b.play())
        async with aiohttp.ClientSession() as s:
            async with s.get(url + "/api/records") as r:
                body = await r.json()
            assert body["ok"] and len(body["records"]) == 1
            rec = body["records"][0]
            assert rec["problem"] is None and rec["result"] == res and sorted(rec["names"]) == ["A", "B"]
            async with s.post(url + "/api/records/replay", json={"id": rec["id"], "viewer": "full"}) as r:
                rp = await r.json()
            assert rp["ok"] and rp["viewer"] == "full" and rp["result"] == res
            assert all(pl["hand"] is not None for pl in rp["frames"][-1]["view"]["players"])
            async with s.post(url + "/api/records/replay", json={"id": rec["id"].split(":")[0] + ":999", "viewer": 0}) as r:
                assert r.status == 400 and (await r.json())["code"] == "no_record"
            # 版が違う記録（ルールの版を書き換えた）は、一覧に理由が出て、再生は断る
            path = next((tmp_path / "data" / "games").glob("*.jsonl"))
            line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            line["rules_version"] = "v0.1"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            async with s.get(url + "/api/records") as r:
                recs = (await r.json())["records"]
            assert "ルールの版が違う" in recs[0]["problem"]
            async with s.post(url + "/api/records/replay", json={"id": recs[0]["id"], "viewer": 0}) as r:
                assert r.status == 400 and (await r.json())["code"] == "old_record"
        for x in (a, b):
            await x.close()
    finally:
        await srv.close()


def test_replay_messages_carry_no_hidden_cards_for_a_seat(sd001, sd02):
    """席の視点のリプレイに、その席が対局中に見られなかったカード番号は出ない（全情報以外）。"""
    from app.core.views import visible_cards
    g = Game([sd001, sd02], 11)
    play_and_watch(g, random.Random(11))
    frames = replay.build(g.dump(), g.result())
    for v in VIEWERS:
        ever = set()
        for f in frames[v]:
            ever |= visible_cards(f["view"])
            assert card_ids_in(f["events"]) <= ever | visible_cards(f["view"]), v
