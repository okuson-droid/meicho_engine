"""中身の煙テスト（要件 R-UPD-7・R-UPD-8）。公開の前と、固めた実行ファイルの確認に使う。

サーバを空きポートで立て、画面・版・CPU 対戦の選択肢が返ることを確かめ、すべての段の AI を作れることを確かめてから、各デッキの一番軽い段の CPU と
1 局ずつ最後まで打つ（打つ側は `app/bot.py` の無作為の打ち手）。記録が再生照合を通ることも見る。
**ここが落ちる中身は公開しない**（`app/release/publish.py`）。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path


async def _run(data: Path) -> list:
    import aiohttp
    from aiohttp import web

    from . import server as S
    from .bot import Bot

    problems = []
    runner = web.AppRunner(S.create_app(data, cpu=True, cpu_delay=0, flood_per_sec=None))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url + "/") as r:
                if r.status != 200 or "<html" not in (await r.text()).lower():
                    problems.append("画面が返らない")
            async with s.get(url + "/api/version") as r:
                ver = await r.json()
            async with s.get(url + "/api/cpu") as r:
                cpu = await r.json()
            print(f"版: {ver.get('version')}  ルール {ver.get('rules_version')}  通信の版 {ver.get('protocol')}")
            if not cpu.get("enabled") or not cpu.get("decks"):
                problems.append("CPU 対戦の選択肢が無い")
            for deck, levels in cpu.get("decks", {}).items():
                print(f"  {deck}: {[x['label'] for x in levels]}")
            # 段の設定が指す AI が実在し、モデルのファイルが揃っているか（要件 R-EXT-7）。作れれば足りる
            from .core import cpu as cpu_mod
            for deck, opts in cpu_mod.options().items():
                for o in opts:
                    try:
                        cpu_mod.build(o["agent"], cpu_mod.load_deck(deck), 1)
                    except Exception as e:                      # noqa: BLE001
                        problems.append(f"{deck} の「{o['label']}」（{o['agent']}）を作れない: {e}")
            for deck in cpu.get("decks", {}):
                async with s.post(url + "/api/cpu", json={"deck": deck, "level": 0, "first": "random"}) as r:
                    body = await r.json()
                bot = Bot(url, body["room"], body["pass"], "selfcheck", seed=1)
                await bot.enter()
                res = await bot.play(timeout=300)
                await bot.close()
                print(f"  1 局（{deck}・やさしい）: {res.get('reason')}  勝者 {res.get('winner')}")
                if res.get("reason") != "normal" or bot.errors:
                    problems.append(f"{deck} の対局が正常に終わらない: {bot.errors[:2]}")
        recs = [json.loads(x) for p in (data / "games").glob("*.jsonl") for x in p.read_text(encoding="utf-8").splitlines()]
        if len(recs) != len(cpu.get("decks", {})) or not all(r.get("verified") for r in recs):
            problems.append("記録が再生照合を通らない")
    finally:
        await runner.cleanup()
    return problems


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):             # Windows の端末（cp932）で表せない字があっても、表示のせいで止まらない
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    with tempfile.TemporaryDirectory() as tmp:
        problems = asyncio.run(_run(Path(tmp)))
    for p in problems:
        print(f"NG: {p}")
    print("OK" if not problems else "NG")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
