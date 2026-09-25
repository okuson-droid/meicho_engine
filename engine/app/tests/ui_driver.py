"""実ブラウザの自動プレイヤー（要件 R-NF・計画書 8.3「実ブラウザ・実ポインタ操作の自動テスト」）。

**DOM と本物のポインタ入力だけで打つ。**アプリの内部（JS の変数）には触らない。だから、これで 1 局を
打ち切れることが「人がマウスやタッチで 1 局を打ち切れる」ことの裏付けになる（M3 の完了条件）。

- `mode="mouse"`: マウスのドラッグ＆ドロップとクリック
- `mode="touch"`: タッチのタップ（持ち上げて置く）と、タッチのドラッグ（CDP で指の動きを送る）
"""
from __future__ import annotations

import asyncio
import random

LIT_CARDS = '#board .lit[data-role="hand"], #board .lit[data-role="concerto"], #board .lit[data-role="tray"], #board .lit[data-role="placed"]'
LIT_ZONES = '#board .side.me .zone.lit'
BUTTONS = '#board .midbar button[data-act="legal"]:not([disabled]), #board .midbar button[data-act="setup-ok"]:not([disabled]), #board .midbar button[data-act="mulligan-ok"]:not([disabled]), #board .midbar button[data-act="reopen"]'


class UiPlayer:
    def __init__(self, page, mode: str, seed: int, *, skip: bool = True):
        self.page, self.mode, self.rnd = page, mode, random.Random(seed)
        self.skip = skip                         # 演出の再生中に、タップで飛ばすか（False なら終わるまで待つ）
        self.cdp = None
        self.actions = {"drag": 0, "lift": 0, "click": 0, "button": 0, "pick": 0, "confirm": 0, "mark": 0, "skip": 0}

    # ---------------------------------------------------------------- 入力の下回り
    async def _center(self, el):
        box = await el.bounding_box()
        if not box:
            return None
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    async def tap(self, el) -> bool:
        pt = await self._center(el)
        if pt is None:
            return False
        if self.mode == "touch":
            await self.page.touchscreen.tap(*pt)
        else:
            await self.page.mouse.click(*pt)
        return True

    async def drag(self, src, dst) -> bool:
        a, b = await self._center(src), await self._center(dst)
        if a is None or b is None:
            return False
        steps = 6
        pts = [(a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps) for k in range(1, steps + 1)]
        if self.mode == "touch":
            if self.cdp is None:
                self.cdp = await self.page.context.new_cdp_session(self.page)
            send = self.cdp.send
            await send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": a[0], "y": a[1]}]})
            for x, y in pts:
                await send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
            await send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        else:
            await self.page.mouse.move(*a)
            await self.page.mouse.down()
            for x, y in pts:
                await self.page.mouse.move(x, y)
            await self.page.mouse.up()
        return True

    # ---------------------------------------------------------------- 1 手
    async def finished(self) -> bool:
        # 結果のダイアログか、閉じたあとに中央の帯へ出る「結果」ボタン
        return await self.page.query_selector('.modal .result, #board .midbar button[data-act="result"]') is not None

    async def step(self) -> bool:
        """できることを 1 つ行う。何もできなければ False。"""
        page, rnd = self.page, self.rnd
        playing = await page.query_selector("#board.playing .midbar .status")
        if playing:                              # 演出の再生中は入力が止まっている。盤面をタップして飛ばす（R-FX-4）
            if not self.skip:
                return False
            self.actions["skip"] += 1
            return await self.tap(playing)
        q = page.query_selector_all              # 要素の実体をつかむ。描き直しで消えたら、位置が取れずに False で抜ける
        if await page.query_selector("#layer-modal .modal .result"):
            return False
        if await page.query_selector("#layer-modal .modal"):
            ok = await q('#layer-modal button[data-act="ok"]')
            if ok:
                self.actions["confirm"] += 1
                return await self.tap(ok[0])
            picks = await q('#layer-modal [data-pick], #layer-modal button[data-act="legal"]')
            if picks:
                self.actions["pick"] += 1
                return await self.tap(rnd.choice(picks))
            close = await q('#layer-modal button[data-act="close"]')
            if close:
                return await self.tap(close[0])
            return False

        cards = await q(LIT_CARDS)
        zones = await q(LIT_ZONES)
        buttons = await q(BUTTONS)
        marking = bool(await q('#board .midbar button[data-act="mulligan-ok"]'))
        choices = []
        if cards:
            choices += ["card"] * 3
        if zones:
            choices += ["zone"]
        if buttons:
            choices += ["button"] * (1 if cards and not marking else 2)
        if not choices:
            return False
        kind = rnd.choice(choices)
        if kind == "button":
            self.actions["button"] += 1
            return await self.tap(rnd.choice(buttons))
        if kind == "zone":
            self.actions["click"] += 1
            return await self.tap(rnd.choice(zones))
        card = rnd.choice(cards)
        if marking:                                     # マリガン: タップで印を付ける
            self.actions["mark"] += 1
            return await self.tap(card)
        # 持ち上げて、置けるゾーンを見る（光るのは置けるゾーンだけ）
        if not await self.tap(card):
            return False
        drops = await q("#board .side.me .zone.drop-ok")
        if not drops:
            return True
        dst = rnd.choice(drops)
        if rnd.random() < 0.5:
            self.actions["lift"] += 1
            return await self.tap(dst)                  # タップで持ち上げ → 置き先をタップ（R-PLAY-6）
        role = await card.get_attribute("data-role")
        if role == "placed":                            # 置いたキャラは、もう一度タップすると枠から戻る
            self.actions["lift"] += 1
            return await self.tap(dst)
        await self.tap(card)                            # 下ろしてから、本物のドラッグで置く
        self.actions["drag"] += 1
        return await self.drag(card, dst)

    async def play(self, *, timeout: float = 600.0, idle: float = 0.03, until=None) -> None:
        """終局まで打つ。`until`（ページを受け取る非同期の関数）が真を返したら、そこで止まる。"""
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            if await self.finished() or (until is not None and await until(self.page)):
                return
            try:
                acted = await self.step()
            except Exception as e:                      # 描き直しで要素が消えた、など。次の周でやり直す
                if "Timeout" in type(e).__name__:
                    raise
                acted = False
            await asyncio.sleep(idle if acted else 0.08)
        state = await self.page.evaluate("""() => ({
            mid: document.querySelector('#board .midbar')?.innerText, lit: document.querySelectorAll('#board .lit').length,
            modal: document.querySelector('#layer-modal')?.innerText.slice(0, 300), toast: document.querySelector('#layer-toast')?.innerText,
            banner: document.querySelector('.banner')?.innerText, page: document.querySelector('#board') ? 'board' : document.body.innerText.slice(0, 200)})""")
        raise TimeoutError(f"UI player ({self.mode}) did not finish: {state} actions={self.actions}")


# ---------------------------------------------------------------- 入室までの手順（テストで共用）
async def create_room(page, url: str, name: str, passphrase: str) -> str:
    await page.goto(url + "/")
    await page.fill("#name", name)
    await page.fill("#pass", passphrase)
    await page.click("#create")
    await page.wait_for_url("**/?room=*")
    await page.wait_for_selector('button[data-act="sit"]')
    return page.url.split("room=")[1]


async def join_room(page, url: str, room: str, name: str, passphrase: str) -> None:
    await page.goto(f"{url}/?room={room}")
    await page.fill("#name", name)
    await page.fill("#pass", passphrase)
    await page.click("#join")
    await page.wait_for_selector("#invite, #board")


async def sit_and_ready(page, seat: int, deck: str) -> None:
    await page.click(f'button[data-act="sit"][data-seat="{seat}"]')
    await page.select_option("#deck-select", label=f"［同梱］{deck}")
    await page.wait_for_selector("#ready:not([disabled])")
    await page.click("#ready")
