"""画面（M3）の検査。本物のブラウザ（Chromium）を、本物のマウスとタッチの入力で動かす。

計画書 8.2 の M3 の完了条件: 人対人で、マウスでもタッチでも 1 局打ち切れる。合法な対象が光り、できない操作に理由が出る。

Playwright が無い環境（マスターの PC など）では丸ごと skip になる。
"""
import asyncio

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("pytest_asyncio")
pytest.importorskip("playwright")

from aiohttp.test_utils import TestServer  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

from app import server as S  # noqa: E402
from app.tests.ui_driver import UiPlayer, create_room, join_room, sit_and_ready  # noqa: E402

pytestmark = pytest.mark.asyncio
PC = {"viewport": {"width": 1280, "height": 720}}
PHONE = {"viewport": {"width": 800, "height": 360}, "has_touch": True, "is_mobile": True}     # スマホの横持ち


class Rig:
    """サーバ 1 つとブラウザ 1 つ。ページで起きた JS のエラーを全部集める。"""

    def __init__(self, tmp_path, *, seed_source=None):
        """`seed_source`: 局のシードの出どころ。中身で結果が変わる検査は固定する（既定は毎回ちがうシード）。"""
        self.tmp_path, self.errors, self.seed_source = tmp_path, [], seed_source

    async def __aenter__(self):
        self.srv = TestServer(S.create_app(self.tmp_path / "data", seed_source=self.seed_source,
                                           flood_per_sec=None, cpu=True, cpu_delay=0))
        await self.srv.start_server()
        self.url = str(self.srv.make_url("")).rstrip("/")
        self.pw = await async_playwright().start()
        try:
            self.browser = await self.pw.chromium.launch()
        except Exception as e:                              # ブラウザ本体が入っていない
            await self.pw.stop()
            await self.srv.close()
            pytest.skip(f"chromium を起動できない: {e}")
        return self

    async def __aexit__(self, *exc):
        await self.browser.close()
        await self.pw.stop()
        await self.srv.close()

    async def page(self, tag: str, *, fx: str = "on", speed: float = 1, first_visit: bool = False, auto_pay: bool = False, **ctx):
        """`fx`: 演出の設定（"on"／"off"）。端末ごとの設定なので、ブラウザの保管場所に先に入れておく。
        `first_visit`: 初めて開いた端末として扱う（遊び方が自動で開く）。既定は「もう見た」にして、ほかの検査の邪魔をさせない。"""
        context = await self.browser.new_context(**ctx)
        await context.add_init_script(
            "try { localStorage.setItem('meichosim.settings', JSON.stringify({fx: '%s', speed: %s, volume: 0.3, muted: false, autoPay: %s})); } catch (e) {}"
            % (fx, speed, "true" if auto_pay else "false"))
        if not first_visit:
            await context.add_init_script("try { localStorage.setItem('meichosim.helpSeen', 'true'); } catch (e) {}")
        page = await context.new_page()
        page.set_default_timeout(10000)
        page.on("pageerror", lambda e: self.errors.append((tag, str(e))))
        page.on("console", lambda m: self.errors.append((tag, m.text)) if m.type == "error" else None)
        return page

    def room(self, rid):
        return self.srv.app[S.HUB].manager.rooms[rid]


async def test_full_game_with_mouse_and_touch(tmp_path):
    """マウスの人（PC）とタッチの人（スマホ横持ち）が、盤面の所作だけで 1 局を打ち切る。観戦者も最後まで見る。"""
    async with Rig(tmp_path) as rig:
        a, b, c = await rig.page("A", **PC), await rig.page("B", **PHONE), await rig.page("C", **PC)
        room = await create_room(a, rig.url, "マスター", "あいことば")
        await sit_and_ready(a, 0, "SD001")
        await join_room(b, rig.url, room, "知人", "あいことば")
        await sit_and_ready(b, 1, "SD02")
        await join_room(c, rig.url, room, "見学", "あいことば")
        for p in (a, b, c):
            await p.wait_for_selector("#board .midbar")
        pa, pb = UiPlayer(a, "mouse", 1), UiPlayer(b, "touch", 2)
        await asyncio.gather(pa.play(timeout=300), pb.play(timeout=300))

        r = rig.room(room)
        assert r.state == "finished" and r.game.result()["reason"] == "normal"
        # どちらの入力でも、ドラッグ・持ち上げて置く・直接クリック・宣言のボタンを実際に使った
        for who in (pa, pb):
            assert min(who.actions[k] for k in ("drag", "lift", "click", "button", "confirm", "skip")) > 0, who.actions
        # 観戦者: 結果まで届く。手札と操作の起点は 1 つも無い（R-SPEC-1・R-SPEC-3）
        await c.wait_for_selector(".modal .result")
        await c.click('.modal button[data-act="close"]')
        assert await c.locator('#board [data-role="hand"], #board .lit, #board [data-drop]').count() == 0
        assert await c.locator("#board .handrow .card.back").count() > 0
        # 勝ち負けの表示が食い違わない
        texts = [await p.inner_text(".modal .result .big") for p in (a, b)]
        assert sorted(texts) == ["勝ち", "負け"] or texts == ["引き分け", "引き分け"]
        assert not rig.errors, rig.errors[:5]


async def test_gestures_reasons_and_recovery(tmp_path):
    async with Rig(tmp_path) as rig:
        a, b = await rig.page("A", fx="off", **PC), await rig.page("B", fx="off", **PHONE)      # 所作だけを見るので、演出は切る
        room = await create_room(a, rig.url, "マスター", "pw")
        await a.select_option("#first", "seat0")                  # 席 1（マスター）が先攻
        await sit_and_ready(a, 0, "SD001")
        await join_room(b, rig.url, room, "知人", "pw")
        await sit_and_ready(b, 1, "SD001")
        await a.wait_for_selector('#board [data-role="tray"]')
        game = lambda: rig.room(room).game                        # noqa: E731
        pa, pb = UiPlayer(a, "mouse", 5), UiPlayer(b, "touch", 6)

        # --- 準備（R-ACT-1）: 3 枚置くまで「準備完了」は押せない。置けない場所で離しても何も起きない（R-PLAY-3）
        assert await a.locator('button[data-act="setup-ok"]').is_disabled()
        tray = await a.query_selector_all('#board [data-role="tray"]')
        await pa.drag(tray[0], await a.query_selector(".side.opp"))
        assert await a.locator('#board [data-role="tray"]').count() == 3 and len(game().applies) == 0
        for slot in (0, 1, 2):
            card = await a.query_selector('#board [data-role="tray"]')
            await pa.drag(card, await a.query_selector(f'.side.me [data-drop="slot{slot}"]'))
        assert await a.locator('#board [data-role="placed"]').count() == 3
        # 置き直せる: リーダーとバック 1 を入れ替える
        before = await a.inner_text('.side.me [data-drop="slot0"] .nm')
        await pa.drag(await a.query_selector('.side.me [data-drop="slot0"] [data-role="placed"]'), await a.query_selector('.side.me [data-drop="slot1"]'))
        assert await a.inner_text('.side.me [data-drop="slot1"] .nm') == before
        await a.click('button[data-act="setup-ok"]')
        # 相手の配置は、両者が揃うまで裏向き
        await a.wait_for_selector('#board .midbar .wait:not(.mine)')
        assert await a.locator(".side.opp [data-zone=slot] .card:not(.back)").count() == 0
        for slot in (0, 1, 2):                                    # タッチの人は「タップで持ち上げ → 枠をタップ」で置く（R-PLAY-6）
            await pb.tap(await b.query_selector('#board [data-role="tray"]'))
            assert await b.locator(".side.me .zone.drop-ok").count() == 3
            await pb.tap(await b.query_selector(f'.side.me [data-drop="slot{slot}"]'))
        await pb.tap(await b.query_selector('button[data-act="setup-ok"]'))

        # --- マリガン（R-ACT-2）: 印を付けると、ボタンの文が変わる
        await a.wait_for_selector('button[data-act="mulligan-ok"]')
        assert "このまま" in await a.inner_text('button[data-act="mulligan-ok"]')
        await pa.tap(await a.query_selector('#board [data-role="hand"]'))
        assert "引き直す（1 枚）" in await a.inner_text('button[data-act="mulligan-ok"]')
        await a.click('button[data-act="mulligan-ok"]')
        await b.wait_for_selector('button[data-act="mulligan-ok"]')
        await pb.tap(await b.query_selector('button[data-act="mulligan-ok"]'))

        # --- アクションフェイズ。先攻はマスター
        await a.wait_for_selector('button[data-act="legal"]')
        n = len(game().applies)
        # 相手番の人が手札を触ると、理由が出る（R-PLAY-4）。何も起きない
        await pb.tap(await b.query_selector('#board [data-role="hand"]'))
        assert "相手" in await b.inner_text("#layer-toast")
        assert await b.locator("#board .lit").count() == 0
        # 手札をトラッシュへドラッグ: いまは捨てる場面ではないので、光らず、置けず、何も起きない
        hand = await a.query_selector_all('#board [data-role="hand"]')
        await pa.drag(hand[0], await a.query_selector('.side.me [data-drop="trash"]'))
        assert len(game().applies) == n
        # 協奏エリアへドラッグ＝チャージ（R-ACT-3）。確認は挟まない
        await pa.drag(hand[0], await a.query_selector('.side.me [data-drop="concerto"]'))
        await a.wait_for_selector('.side.me [data-zone="concerto"] .card')
        assert len(game().applies) == n + 1
        # 2 回目のチャージはできない。理由はサーバが作った文
        await pa.tap(await a.query_selector('#board [data-role="hand"]'))
        assert "もうチャージした" in await a.inner_text("#layer-toast")
        # リーダーの切り替え（R-ACT-5）: バックをクリック → 確認 → やめる、なら何も起きない
        # （レベルアップもできるときは、先に「どちらにするか」を尋ねる・APP-026）
        async def open_switch():
            await pa.tap(await a.query_selector('.side.me [data-zone="slot"][data-slot="1"]'))
            await a.wait_for_selector('.modal button[data-act="cancel"], .modal button[data-act="slot-switch"]')
            if await a.query_selector('.modal button[data-act="slot-switch"]'):
                await a.click('.modal button[data-act="slot-switch"]')
                await a.wait_for_selector('.modal button[data-act="cancel"]')
        await open_switch()
        await a.click('.modal button[data-act="cancel"]')
        assert len(game().applies) == n + 1
        leader = await a.inner_text('.side.me [data-slot="0"] .nm')
        await open_switch()
        await a.click('.modal button[data-act="ok"]')
        await a.wait_for_function("(name) => document.querySelector('.side.me [data-slot=\"1\"] .nm')?.textContent === name", arg=leader)
        # キャラデッキは広げて見られる（R-PLAY-8）。相手のキャラデッキは見られない
        await pa.tap(await a.query_selector('.side.me [data-zone="charadeck"]'))
        assert await a.locator(".modal .grid .card").count() == 6
        await a.click('.modal button[data-act="close"]')
        await pa.tap(await a.query_selector('.side.opp [data-zone="charadeck"]'))
        assert await a.locator("#layer-modal .modal").count() == 0

        # --- 盤面で OS のメニューや文字選択が出ない（R-PLAY-10）
        assert await a.evaluate("getComputedStyle(document.getElementById('board')).userSelect") == "none"
        assert await a.evaluate("""() => { const e = new MouseEvent('contextmenu', {bubbles: true, cancelable: true});
            document.querySelector('#board .card').dispatchEvent(e); return e.defaultPrevented; }""")

        # --- 長押しで拡大（R-PLAY-7）。指を離すと消える。ドラッグにはならない
        card = await b.query_selector('#board [data-role="hand"]')
        box = await card.bounding_box()
        cdp = await b.context.new_cdp_session(b)
        pt = {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2}
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [pt]})
        await b.wait_for_selector("#layer-zoom.on .zoom h4")
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        assert await b.locator("#layer-zoom.on").count() == 0
        # ダイアログの中のカードも長押しで拡大する。離したときのクリックは捨てる（拡大を見るつもりで選ばない）。短いタップは届く
        await pb.tap(await b.query_selector('.side.me [data-zone="charadeck"]'))
        await b.wait_for_selector(".modal .grid .card")
        await b.evaluate("""() => { window.__clicks = 0; const c = document.querySelector('.modal .grid .card');
            c.addEventListener('click', () => { window.__clicks += 1; }); }""")
        box = await (await b.query_selector(".modal .grid .card")).bounding_box()
        pt = {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2}
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [pt]})
        await b.wait_for_selector("#layer-zoom.on .zoom h4")
        # 拡大はダイアログの暗幕より上に重なる（下だと薄く見える・APP-017 追記 1）
        assert await b.evaluate("""() => { const z = (id) => Number(getComputedStyle(document.getElementById(id)).zIndex);
            return z('layer-zoom') > z('layer-modal'); }""")
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        await b.wait_for_timeout(150)
        assert await b.locator("#layer-zoom.on").count() == 0 and await b.evaluate("window.__clicks") == 0
        assert await b.locator(".modal .grid").count() == 1               # ダイアログは開いたまま
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [pt]})
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        await b.wait_for_function("window.__clicks === 1")
        assert await b.locator("#layer-zoom.on").count() == 0
        await b.click('.modal button[data-act="close"]')

        # --- 読み込み直しても、席の鍵で同じ席に戻る（R-NET-3・R-NET-4）
        n_hand = await b.locator('#board [data-role="hand"]').count()
        await b.reload()
        await b.wait_for_selector('#board [data-role="hand"]')
        assert await b.locator('#board [data-role="hand"]').count() == n_hand
        # --- 相手が切断すると、経過時間つきで知らせる。負けにはしない（R-NET-2）
        await b.context.close()
        await a.wait_for_selector(".banner.opp")
        assert "切断中" in await a.inner_text(".banner.opp") and rig.room(room).state == "playing"
        # --- 予備の入口（R-PLAY-11）と投了（R-ACT-12）は、メニューの中にある
        await a.click('button[data-act="menu"]')
        await a.click('.modal button[data-act="list"]')
        assert await a.locator('.modal button[data-act="legal"]').count() == len(game().legal(0))
        await a.click('.modal button[data-act="close"]')
        await a.click('button[data-act="menu"]')
        await a.click('.modal button[data-act="resign"]')
        await a.click('.modal button[data-act="ok"]')
        await a.wait_for_selector(".modal .result .big.lose")
        assert not rig.errors, rig.errors[:5]


WATCH = """() => {
  window.__seen = {banners: [], ghosts: 0, litWhilePlaying: 0, pops: 0, srcPops: 0, leftovers: 0, sounds: []};
  // 鳴った音は累計で持つ（sfxPlayed は直近 50 個だけなので、長い局では早い音が押し出される・APP-015）
  const played = window.__meichosim.board.sfxPlayed, push = played.push.bind(played);
  played.push = (...xs) => { for (const x of xs) if (!window.__seen.sounds.includes(x)) window.__seen.sounds.push(x); return push(...xs); };
  new MutationObserver((muts) => { for (const m of muts) for (const n of m.addedNodes) {
    if (!n.classList) continue;
    if (n.classList.contains('fx-banner') || n.classList.contains('fx-verdict')) window.__seen.banners.push(n.textContent);
    if (n.classList.contains('fx-stage')) window.__seen.stages = (window.__seen.stages || 0) + 1;
    if (n.classList.contains('fx-skill')) window.__seen.skills = (window.__seen.skills || 0) + 1;
    if (n.classList.contains('fx-ghost')) window.__seen.ghosts += 1;
    if (n.classList.contains('fx-pop')) { window.__seen.pops += 1; if (n.querySelector('.fx-src')) window.__seen.srcPops += 1; }
  } }).observe(document.getElementById('layer-fx'), {childList: true, subtree: true});
  setInterval(() => { if (!document.querySelector('#board.playing') && document.getElementById('layer-fx').childElementCount) window.__seen.leftovers += 1; }, 25);
  setInterval(() => { if (document.querySelector('#board.playing') && document.querySelector('#board .lit, #board .drop-ok')) window.__seen.litWhilePlaying += 1; }, 25);
}"""


FX_SEED = 2847930805403082758         # 5 ターン目までにダメージと判定の勝ち負けが出る局（作業環境で確かめた）
# 固定しても、所作の間合いで打つ手が変わり中身が揺れることがある。止める条件でも中身を確かめる（APP-015）
FAR_ENOUGH = """(() => { const s = new Set(window.__seen.sounds);
  return (window.__meichosim.board.view || {}).turn_no >= 7 && s.has('damage') && (s.has('win') || s.has('lose')); })()"""


async def test_effects_play_in_order_block_input_and_respect_settings(tmp_path):
    """M4: 出来事が順に再生され、その間は入力が止まり、上限の時間を超えない。演出を切った画面では再生されず、ログには同じ出来事が出る。"""
    # 局の中身を固定する。シードが毎回ちがうと、7 ターンまでに一度もライフが動かない局が半分ほど出て、
    # 下の pops・damage の確かめが中身しだいで落ちていた（APP-015）。
    async with Rig(tmp_path, seed_source=lambda: FX_SEED) as rig:
        a = await rig.page("A", fx="on", speed=2.5, **PC)
        b = await rig.page("B", fx="on", speed=2.5, **PHONE)
        c = await rig.page("C", fx="off", **PC)                       # 観戦者は演出を切っている
        room = await create_room(a, rig.url, "マスター", "pw")
        await sit_and_ready(a, 0, "SD001")
        await join_room(b, rig.url, room, "知人", "pw")
        await join_room(c, rig.url, room, "見学", "pw")
        await sit_and_ready(b, 1, "SD02")
        for p in (a, b, c):
            await p.wait_for_selector("#board .midbar")
        for p in (a, b):
            await p.evaluate(WATCH)

        async def far_enough(page):                                 # 7 ターン目まで進み、ダメージと判定を少なくとも 1 回ずつ見た
            return await page.evaluate(FAR_ENOUGH)
        pa, pb = UiPlayer(a, "mouse", 3, skip=False), UiPlayer(b, "touch", 4, skip=False)       # 飛ばさずに最後まで見る
        await asyncio.gather(pa.play(timeout=300, until=far_enough), pb.play(timeout=300, until=far_enough))

        cap = await a.evaluate("parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fx-max'))")
        assert cap == 8000                                          # APP-024 で 6 → 8 秒
        for p in (a, b):
            stats = await p.evaluate("window.__meichosim.board.fx.stats")
            seen = await p.evaluate("window.__seen")
            sounds = set(seen["sounds"])
            assert stats["plays"] > 15 and stats["skips"] == 0, stats
            assert stats["maxMs"] <= cap + 700, stats                   # 1 回の再生は上限を超えない（R-FX-4）
            assert seen["litWhilePlaying"] == 0, seen                   # 再生中は触れるものが光らない＝入力が止まっている（R-FX-3）
            assert seen["ghosts"] > 10 and seen["pops"] > 0, seen
            assert seen["srcPops"] > 0, seen                            # ダメージの数字に出どころのカードの名前が添う（APP-016）
            assert seen["leftovers"] == 0, seen                         # 再生が終わったら、演出の層に何も残らない
            assert any(t.startswith("ターン") for t in seen["banners"]) and any("判定" in t for t in seen["banners"]), seen["banners"]
            assert seen.get("stages", 0) > 0, seen                      # 対抗は真ん中に並べて見せる（APP-022）
            assert seen.get("skills", 0) > 0, seen                      # 効果の解決ごとに「◯◯ の効果」の区切りが出る（APP-024）
            assert {"draw", "place", "clash", "turn", "damage"} <= sounds, sounds
            assert sounds & {"win", "lose"}
        # 演出を切った画面: 再生は 0 回。それでもログには出来事が順に出る（R-FX-7）
        assert (await c.evaluate("window.__meichosim.board.fx.stats"))["plays"] == 0
        await c.click('button[data-act="menu"]')
        await c.click('.modal button[data-act="log"]')
        lines = await c.locator(".logbox div").all_inner_texts()
        assert len(lines) > 20 and any("判定" in t for t in lines) and any("コストの支払い" in t or "チャージ" in t for t in lines)
        assert any("ライフ -" in t and "ダメージ）" in t for t in lines), [t for t in lines if "ライフ" in t]   # 出どころ（APP-016）
        # 設定はメニューから開けて、その場で効く。音の設定と演出の設定は別々（R-SND-2）
        await a.wait_for_selector("#board:not(.playing)")
        await a.click('button[data-act="menu"]')
        await a.click('.modal button[data-act="settings"]')
        await a.select_option("#set-fx", "off")
        await a.check("#set-mute")
        saved = await a.evaluate("JSON.parse(localStorage.getItem('meichosim.settings'))")
        assert saved["fx"] == "off" and saved["muted"] is True and saved["volume"] == 0.3
        assert not rig.errors, rig.errors[:5]


async def test_cpu_battle_from_the_home_screen(tmp_path):
    """M5: ホームから CPU 対戦を始め、同じ盤面で つよい（SD001 は現 champion）と 1 局打ち切り、そのまま再戦に入れる。"""
    async with Rig(tmp_path) as rig:
        a = await rig.page("A", fx="on", speed=2.5, **PC)
        await a.goto(rig.url + "/")
        await a.fill("#name", "マスター")
        assert await a.locator("#cpu-level option").all_inner_texts() == ["やさしい", "ふつう", "つよい"]
        await a.select_option("#cpu-deck", "SD001")
        await a.select_option("#cpu-level", "2")
        await a.select_option("#cpu-first", "cpu")
        await a.click("#cpu-start")
        await a.wait_for_selector("#board .midbar")                 # 席もデッキも選ばずに、そのまま盤面に入る
        room = a.url.split("room=")[1]
        r = rig.room(room)
        assert r.cpu and r.order == [1, 0] and r.cpu["agent"] == "planner_vc4cps_kheb_b75"
        assert "CPU（つよい）" in await a.inner_text(".side.opp .life .cap")
        me = UiPlayer(a, "mouse", 21)
        await me.play(timeout=300)
        assert r.state == "finished" and r.game.result()["reason"] == "normal"
        await a.click('.modal button[data-act="rematch"]')         # CPU はいつでも再戦に応じる
        await a.wait_for_function("window.__meichosim.room.state === 'playing' && window.__meichosim.room.games_played === 1")
        assert r.state == "playing" and len(r.finished) == 0 and r.games_played == 1
        assert not rig.errors, rig.errors[:5]


async def test_settings_show_version_history_and_update_trouble(tmp_path, monkeypatch):
    """設定画面でいまの版と更新の履歴を確かめられ、起動役が古いときは案内が出る（要件 R-UPD-8・R-UPD-9）。"""
    import json
    from app.core import release
    ver = tmp_path / "contents" / "versions" / "2026.09.21-7"
    (ver / "engine").mkdir(parents=True)
    m = {"version": "2026.09.21-7", "seq": 7, "built": "2026-09-21T10:00:00+09:00", "notes": "つよい CPU を交代",
         "rules_version": "v9.9", "history": [{"version": "2026.09.21-7", "built": "2026-09-21T10:00:00+09:00", "notes": "つよい CPU を交代"},
                                                {"version": "2026.09.20-6", "built": "2026-09-20T10:00:00+09:00", "notes": "カードを追加"}]}
    (ver / "release.json").write_text(json.dumps({"manifest": json.dumps(m, ensure_ascii=False), "sig": "00"}), encoding="utf-8")
    status = tmp_path / "last_update.json"
    status.write_text(json.dumps({"state": "launcher_outdated", "detail": "x", "to": "2026.09.22-8", "launcher_api": 1}), encoding="utf-8")
    monkeypatch.setattr(release, "ENGINE_DIR", ver / "engine")
    monkeypatch.setenv(release.STATUS_ENV, str(status))
    async with Rig(tmp_path) as rig:
        page = await rig.page("home")
        await page.goto(rig.url + "/")
        await page.wait_for_selector("#update-notice")
        assert "新しい起動役が必要" in await page.inner_text("#update-notice")
        assert "版 2026.09.21-7" in await page.inner_text("#home-version")
        await page.click("#home-settings")
        await page.wait_for_selector("#set-version details")
        text = await page.inner_text("#set-version")
        assert "版 2026.09.21-7" in text and "新しい起動役が必要" in text
        await page.click("#set-version summary")
        hist = await page.inner_text("#set-version .history")
        assert "つよい CPU を交代" in hist and "カードを追加" in hist and "2026.09.20-6" in hist
        assert rig.errors == []


def _png(rgb=(200, 60, 60), w=5, h=7) -> bytes:
    """小さな本物の PNG（ブラウザが絵として読めるもの）。公式の画像は検査にも使わない。"""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)   # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


async def test_local_card_images_show_on_the_board_and_stay_in_the_browser(tmp_path):
    """APP-013: 手元の画像を設定から読み込むと、盤面と拡大にその画像が出る。保管はこのブラウザの中だけで、読み込み直しても残る。
    画像はサーバへ 1 枚も送らない（要件 R-ASSET-1）。"""
    import json
    deck = json.loads((S.ENGINE_DIR / "decklists" / "SD001.json").read_text(encoding="utf-8"))
    ids = sorted(set(deck["chara_deck"] + deck["action_deck"]))
    files = [{"name": f"{cid}_カード.png", "mimeType": "image/png", "buffer": _png()} for cid in ids]
    files += [{"name": f"{ids[0]}_カード-R.png", "mimeType": "image/png", "buffer": _png((60, 60, 200))},     # 別版は別枠（盤面は通常の版）
              {"name": "メモ.txt", "mimeType": "text/plain", "buffer": b"x"},                                   # 名前の形が違うものは入れない
              {"name": "XX99-999_知らない番号.png", "mimeType": "image/png", "buffer": _png()}]                 # 番号がカードに無くても保管はする（一致には数えない）
    async with Rig(tmp_path) as rig:
        a = await rig.page("A", fx="off", **PC)
        sent = []
        a.on("request", lambda r: sent.append((r.method, r.url, len(r.post_data_buffer or b""))))
        await a.goto(rig.url + "/")
        await a.fill("#name", "マスター")
        await a.click("#home-settings")
        assert "未登録" in await a.inner_text("#set-art-status")
        assert await a.locator("#set-art-clear").is_hidden()
        await a.set_input_files("#set-art-files", files)
        await a.wait_for_function("document.querySelector('#set-art-status').textContent.includes('画像')")
        status = await a.inner_text("#set-art-status")
        assert f"画像 {len(ids) + 1} 種" in status and f"一致 {len(ids)} 種" in status, status
        await a.click('.modal button[data-act="close"]')

        await a.select_option("#cpu-deck", "SD001")
        await a.select_option("#cpu-level", "0")
        await a.click("#cpu-start")
        await a.wait_for_selector("#board .card.has-art img.art")
        srcs = await a.eval_on_selector_all("#board img.art", "els => els.map(e => e.src)")
        assert srcs and all(s.startswith("blob:") for s in srcs)                 # 手元の保管領域から出している。URL で取りに行っていない
        # 文字の要素は残っている（隠しているだけ）。裏向きのカードには画像が出ない
        assert await a.locator("#board .card.has-art .nm").count() == await a.locator("#board .card.has-art").count()
        assert await a.locator("#board .card.back img.art").count() == 0
        # 拡大にも画像が出る
        await a.locator('#board [data-role="tray"].has-art').last.hover()
        await a.wait_for_selector("#layer-zoom.on .zoom-art")
        # 読み込み直しても残る（IndexedDB）
        await a.reload()
        await a.wait_for_selector("#board .card.has-art img.art")

        # 画像はサーバへ送っていない: 送った本文はどれも小さく、画像の名前を含む要求も無い
        assert all(n < 4096 for _, _, n in sent), [x for x in sent if x[2] >= 4096]
        net = [u for _, u, _ in sent if not u.startswith("blob:")]           # blob: はブラウザの中の読み出しで、通信ではない
        assert net and all(u.startswith(rig.url) for u in net) and not [u for u in net if ".png" in u]

        # 消せる
        b = await a.context.new_page()
        await b.goto(rig.url + "/")
        await b.click("#home-settings")
        await b.click("#set-art-clear")
        await b.wait_for_function("document.querySelector('#set-art-status').textContent.includes('未登録')")
        await b.close()
        await a.reload()
        await a.wait_for_selector("#board .card:not(.back)")
        assert await a.locator("#board img.art").count() == 0
        assert not rig.errors, rig.errors[:5]


async def test_deck_maker_builds_a_deck_that_the_lobby_can_use(tmp_path):
    """APP-014: デッキメーカー（アーティファクト版と同じ仕様）でデッキを組み、ロビーでそのまま選んで席に着ける。
    カードの一覧はサーバから取り、画像と公式のテキストは手元から読んでこのブラウザにだけ保管する。"""
    import json
    sd001 = json.loads((S.ENGINE_DIR / "decklists" / "SD001.json").read_text(encoding="utf-8"))
    async with Rig(tmp_path) as rig:
        lobby = await rig.page("lobby", fx="off", **PC)
        sent = []
        lobby.on("request", lambda r: sent.append(r.url))
        room = await create_room(lobby, rig.url, "マスター", "pw")
        await lobby.click('button[data-act="sit"][data-seat="0"]')
        before = await lobby.locator("#deck-select option").all_inner_texts()

        dm = await lobby.context.new_page()
        dm.on("pageerror", lambda e: rig.errors.append(("deck", str(e))))
        dm.on("request", lambda r: sent.append(r.url))
        await dm.goto(rig.url + "/")
        await dm.click("#home-deck")                                   # ホームから入れる
        await dm.wait_for_url("**/deck")
        await dm.wait_for_selector(".tile")
        n = await dm.locator(".tile").count()
        assert n > 100 and f"カード {n} 種" in await dm.inner_text("#lbl-cards")
        assert await dm.locator("#f-attribute").is_hidden()             # 公式のデータを重ねるまで、属性の絞り込みは出さない

        # 組む: まず 1 枚だけ手で入れてみる → 構築ルールの検査が「キャラ 1 種類」を出す
        await dm.locator(".tile").first.hover()
        await dm.locator(".tile").first.locator(".tile-add button").last.click()
        assert "キャラが 1 種類" in await dm.inner_text("#checks")
        # 同梱の SD001 の JSON を読み込む → 新しいデッキとして入り、検査が全部通る
        await dm.set_input_files("#deck-import", files=[{"name": "SD001.json", "mimeType": "application/json",
                                                        "buffer": json.dumps({**sd001, "name": "わたしのSD001"}, ensure_ascii=False).encode()}])
        await dm.wait_for_function("document.querySelector('#deck-name').value === 'わたしのSD001'")
        assert await dm.locator("#checks .check.err, #checks .check.warn").count() == 0
        assert "15" in await dm.inner_text("#cnt-chara") and "40" in await dm.inner_text("#cnt-action")

        # 書き出す: ブラウザの普通のダウンロードで、decklists と同じ形の JSON
        async with dm.expect_download() as dl:
            await dm.click("#deck-export")
        path = await (await dl.value).path()
        out = json.loads(open(path, encoding="utf-8").read())
        assert out["name"] == "わたしのSD001" and sorted(out["chara_deck"]) == sorted(sd001["chara_deck"]) and sorted(out["action_deck"]) == sorted(sd001["action_deck"])

        # 画像: 盤面と同じ保管領域。タイルに出る
        cid = sd001["chara_deck"][0]
        await dm.set_input_files("#in-imgs", files=[{"name": f"{cid}_x.png", "mimeType": "image/png", "buffer": _png()}])
        await dm.wait_for_selector(".tile-art img")
        assert "画像 1/" in await dm.inner_text("#lbl-imgs")

        # 公式のデータ（手元のファイル）を重ねる → 属性の絞り込みが出て、詳細に「公式のテキスト」と出る
        official = [{"code": cid, "rarity": "3", "name": "x", "type": "キャラカード", "attribute": "テスト属性", "weapon": "-", "affiliation": "-",
                     "trait": "-", "effect": "テスト用の効果文", "set": "SD01"}]
        await dm.set_input_files("#in-cards", files=[{"name": "c.json", "mimeType": "application/json", "buffer": json.dumps(official, ensure_ascii=False).encode()}])
        await dm.wait_for_selector("#f-attribute .chip")
        await dm.fill("#f-q", "テスト用の効果文")
        await dm.wait_for_function("document.querySelectorAll('.tile').length === 1")
        await dm.locator(".tile").first.click()
        assert "公式のテキスト" in await dm.inner_text(".panel.detail")

        # ロビー（別のタブ）: 保存したデッキが選択肢に増え、選ぶとサーバが受け入れる
        await lobby.wait_for_function("[...document.querySelectorAll('#deck-select option')].some(o => o.textContent === 'わたしのSD001')")
        after = await lobby.locator("#deck-select option").all_inner_texts()
        assert len(after) > len(before)
        await lobby.select_option("#deck-select", label="わたしのSD001")
        await lobby.wait_for_selector("#ready:not([disabled])")
        r = rig.room(room)
        assert r.decks[0]["name"] == "わたしのSD001" and sorted(r.decks[0]["action_deck"]) == sorted(sd001["action_deck"])

        # 通信は自分のサーバだけ。公式のテキストと画像は送っていない
        net = [u for u in sent if not u.startswith(("blob:", "data:"))]
        assert all(u.startswith(rig.url) for u in net), [u for u in net if not u.startswith(rig.url)]
        assert not rig.errors, rig.errors[:5]


async def test_settings_name_zoom_pin_and_feed_consent(tmp_path):
    """設定の残り（要件 R-SET-1・R-SET-2・R-KIF-4）: 表示名を変えられる／カードの拡大を出したままにできる／棋譜の送信の同意は既定で「送らない」。"""
    async with Rig(tmp_path) as rig:
        a = await rig.page("A", fx="off", **PC)
        await a.goto(rig.url + "/")
        await a.fill("#name", "マスター")
        await a.click("#home-settings")
        # 棋譜の送信は既定で送らない。何を送るかと、いまは送り先が無いことが書いてある
        assert not await a.is_checked("#set-feed")
        note = await a.inner_text("#set-feed-note")
        assert "行動列" in note and "何も送られない" in note
        await a.check("#set-feed")
        # 表示名: 変えるとホームの入力欄にも映る。空にはできない
        await a.fill("#set-name", "オクソン")
        await a.press("#set-name", "Enter")
        await a.locator("#set-name").evaluate("e => e.dispatchEvent(new Event('change'))")
        await a.fill("#set-name", "  ")
        await a.locator("#set-name").evaluate("e => e.dispatchEvent(new Event('change'))")
        assert await a.input_value("#set-name") == "オクソン"
        saved = await a.evaluate("JSON.parse(localStorage.getItem('meichosim.settings'))")
        assert saved["feedConsent"] is True and saved["zoom"] == "hover"
        await a.click('.modal button[data-act="close"]')
        assert await a.input_value("#name") == "オクソン"
        assert await a.evaluate("JSON.parse(localStorage.getItem('meichosim.name'))") == "オクソン"

        # 盤面: 出したままにする設定では、カードから離れても拡大が残る。「触れている間だけ」に戻すと消える
        await a.select_option("#cpu-deck", "SD001")
        await a.select_option("#cpu-level", "0")
        await a.click("#cpu-start")
        await a.wait_for_selector('#board [data-role="tray"]')
        assert "オクソン" in await a.inner_text("#board")
        # 設定は対局中でも変えられる（R-SET-2）。検査の道具はページを開くたびに設定を入れ直すので、盤面に入ってから変える
        await a.click('button[data-act="menu"]')
        await a.click('.modal button[data-act="settings"]')
        await a.select_option("#set-zoom", "pin")
        await a.click('.modal button[data-act="close"]')
        await a.mouse.move(640, 5)
        await a.locator('#board [data-role="tray"]').last.hover()
        await a.wait_for_selector("#layer-zoom.on .zoom h4")
        await a.mouse.move(640, 5)                                   # カードの無いところ
        await a.mouse.move(1270, 715)
        await a.wait_for_timeout(400)
        assert await a.locator("#layer-zoom.on").count() == 1
        await a.click('button[data-act="menu"]')
        await a.click('.modal button[data-act="settings"]')
        await a.select_option("#set-zoom", "hover")
        assert await a.locator("#layer-zoom.on").count() == 0
        await a.click('.modal button[data-act="close"]')
        await a.locator('#board [data-role="tray"]').last.hover()
        await a.wait_for_selector("#layer-zoom.on .zoom h4")
        await a.mouse.move(640, 5)
        await a.mouse.move(1270, 715)
        await a.wait_for_function("!document.querySelector('#layer-zoom.on')")
        assert not rig.errors, rig.errors[:5]


async def test_help_opens_on_first_visit_and_labels_every_control(tmp_path):
    """遊び方（要件 R-HELP-1）: 初めて開いた端末では自動で開き、閉じたら次からは開かない。ホームとメニューから開き直せる。
    操作要素の名称（R-HELP-2）: ボタンには読める名前が、盤面のゾーンには名前の説明が付いている。"""
    async with Rig(tmp_path) as rig:
        a = await rig.page("A", fx="off", first_visit=True, **PC)
        await a.goto(rig.url + "/")
        await a.wait_for_selector("#help-body")
        assert "はじめに: 画面の見方" in await a.inner_text(".modal h3")
        await a.click('.modal button[data-act="help-next"]')
        assert "判定" in await a.inner_text("#help-body")
        await a.click('.modal button[data-act="help-next"]')
        assert "ドラッグ" in await a.inner_text("#help-body") and "公式サイト" in await a.inner_text("#help-rules")
        await a.click('.modal button[data-act="help-close"]')
        assert await a.locator("#layer-modal .modal").count() == 0
        await a.reload()
        await a.wait_for_selector("#home-help")
        await a.wait_for_timeout(200)
        assert await a.locator("#layer-modal .modal").count() == 0            # 2 回目は開かない
        await a.click("#home-help")
        assert "遊び方: 画面の見方" in await a.inner_text(".modal h3")
        await a.click('.modal button[data-act="help-next"]')
        await a.click('.modal button[data-act="help-prev"]')
        assert "画面の見方" in await a.inner_text(".modal h3")
        await a.mouse.click(5, 5)                                            # 外側で閉じられる
        # 招待リンクから初めて来た人にも開く。「あとで読む」で閉じられる
        b = await rig.page("B", fx="off", first_visit=True, **PHONE)
        await b.goto(rig.url + "/?room=abc")
        await b.wait_for_selector("#help-body")
        await b.click('.modal button[data-act="help-skip"]')
        assert await b.locator("#layer-modal .modal").count() == 0 and await b.locator("#join").count() == 1

        # 盤面: メニューから開ける。ボタンにはすべて名前があり、ゾーンには説明が付いている
        await a.fill("#name", "マスター")
        await a.select_option("#cpu-deck", "SD001")
        await a.select_option("#cpu-level", "0")
        await a.click("#cpu-start")
        await a.wait_for_selector('#board [data-role="tray"]')
        unnamed = await a.evaluate("""() => [...document.querySelectorAll('button, a.btn, select, input')]
            .filter((e) => e.offsetParent !== null)
            .filter((e) => !((e.getAttribute('aria-label') || e.textContent || '').trim() || e.closest('label') || e.labels?.length))
            .map((e) => e.outerHTML.slice(0, 80))""")
        assert unnamed == [], unnamed
        zones = await a.evaluate("[...document.querySelectorAll('#board [data-zone]')].map((z) => z.getAttribute('title') || '')")
        assert zones and all(zones), zones
        await a.click('button[data-act="menu"]')
        await a.click('.modal button[data-act="help"]')
        assert "遊び方" in await a.inner_text(".modal h3")
        assert not rig.errors, rig.errors[:5]


def _deck_code_oracle(deck: dict, version: int = 2) -> str:
    """デッキコード（版 2）を検査の側で独立に組む。画面側の encodeDeck と突き合わせるための控え（APP-018 追記 1）。"""
    from collections import Counter
    known = ["SD01", "SD02", "BP01"]
    bits: list = []

    def put(v, n):
        bits.extend(str((v >> k) & 1) for k in range(n - 1, -1, -1))

    def gamma(v):
        b = bin(v)[2:]
        bits.extend("0" * (len(b) - 1) + b)

    def part(lst, action):
        by: dict = {}
        for cid, n in Counter(lst).items():
            s, num = cid.rsplit("-", 1)
            by.setdefault(s, []).append((int(num), n, len(num)))
        gamma(len(by) + 1)
        for s in sorted(by):
            if s in known:
                gamma(known.index(s) + 2)
            else:
                import re
                letters, digits = re.fullmatch(r"([A-Z]{2,4})(\d{0,3})", s).groups()
                gamma(1); put(len(letters) - 2, 2)
                for ch in letters:
                    put(ord(ch) - 65, 5)
                put(len(digits), 2)
                if digits:
                    put(int(digits), 10)
            ents = sorted(by[s])
            if s not in known:
                put(ents[0][2] - 2, 2)
            gamma(len(ents))
            prev = -1
            for num, n, _ in ents:
                gamma(num - prev); prev = num
                if not action:
                    gamma(n)
                elif n <= 3:
                    put(n - 1, 2)
                else:
                    put(3, 2); gamma(n - 3)

    put(version, 4)
    part(deck["chara_deck"], False)
    part(deck["action_deck"], True)
    c = 0
    for ch in bits:
        top = ((c >> 7) & 1) ^ (ch == "1")
        c = ((c << 1) & 0xFF) ^ (0x07 if top else 0)
    put(c, 8)
    n = int("1" + "".join(bits), 2)
    alpha = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 62)
        out = alpha[r] + out
    return out


async def test_deck_code_round_trips_and_rejects_bad_input(tmp_path):
    """デッキコード（要件 R-CODE-1〜3・R-EXT-9・R-EXT-10・APP-018）: 1 行にでき、戻せる。中身は番号と枚数と版だけ。
    壊れた文字列・知らない番号・版違いは理由を示して拒む。デッキメーカーとロビーの読み込みの両方で使える。"""
    import json
    import random
    decks = {n: json.loads((S.ENGINE_DIR / "decklists" / f"{n}.json").read_text(encoding="utf-8")) for n in ("SD001", "SD02")}
    async with Rig(tmp_path) as rig:
        a = await rig.page("A", fx="off", **PC)
        await a.goto(rig.url + "/deck")
        await a.wait_for_selector(".tile")
        lib = "import('/static/js/deckcode.js')"
        for name, d in decks.items():
            code = await a.evaluate(f"async (d) => (await {lib}).encodeDeck(d)", d)
            assert code == _deck_code_oracle(d), (name, code)
            assert code.isascii() and code.isalnum() and len(code) <= 30, code        # 英数字だけ。同梱のデッキは 30 字以内
            shuffled = {k: random.Random(1).sample(v, len(v)) for k, v in d.items() if k in ("chara_deck", "action_deck")}
            assert await a.evaluate(f"async (d) => (await {lib}).encodeDeck(d)", shuffled) == code   # 並びが違っても同じコード
            back = await a.evaluate(f"async (c) => (await {lib}).decodeDeck(c)", code)
            assert sorted(back["chara_deck"]) == sorted(d["chara_deck"]) and sorted(back["action_deck"]) == sorted(d["action_deck"])
            folded = code[:30] + "\n  " + code[30:]                          # チャットで折り返されても読める
            assert (await a.evaluate(f"async (c) => (await {lib}).decodeDeck(c)", folded))["action_deck"] == back["action_deck"]
        # 表に無い新しい収録の接頭辞でも書けて読める（知らない番号かどうかの判定は、カードの一覧を渡したときだけ）
        odd = {"chara_deck": ["EX1-001"], "action_deck": ["EX1-002", "EX1-002", "QQ-0000", "BP01-060", "BP01-060", "BP01-060", "BP01-060", "BP01-060"]}
        c = await a.evaluate(f"async (d) => (await {lib}).encodeDeck(d)", odd)
        assert c == _deck_code_oracle(odd)
        back = await a.evaluate(f"async (c) => (await {lib}).decodeDeck(c)", c)
        assert sorted(back["chara_deck"]) == odd["chara_deck"] and sorted(back["action_deck"]) == sorted(odd["action_deck"])
        # 無作為に組んだデッキ 100 個: 戻せて、長さは 50 字以内
        from app.tests.conftest import random_deck
        rds = [random_deck(random.Random(i)) for i in range(100)]
        lens = await a.evaluate(f"""async (ds) => {{ const m = await {lib}; return ds.map((d) => {{ const c = m.encodeDeck(d); const b = m.decodeDeck(c);
            const same = (x, y) => JSON.stringify([...x].sort()) === JSON.stringify([...y].sort());
            return same(b.chara_deck, d.chara_deck) && same(b.action_deck, d.action_deck) ? c.length : -1; }}); }}""", rds)
        assert min(lens) > 0 and max(lens) <= 50, lens
        # 拒む: 理由の文が返る
        good = _deck_code_oracle(decks["SD001"])
        swapped = good[:5] + ("0" if good[5] != "0" else "1") + good[6:]
        bad = {"": "空", "abc-def": "使わない文字", "MS2:C/A": "知らない形式", "MS1:CBP01-018": "壊れている",
               "MS1:CBP01-0x8/A": "番号か枚数", "MS1:CBP01-018*0/A": "枚数が 0", swapped: "", good[:-3]: "",
               _deck_code_oracle(decks["SD001"], version=3): "新しい形式"}
        for text, why in bad.items():
            msg = await a.evaluate(f"""async (t) => {{ const m = await {lib}; try {{ m.decodeDeck(t); return null; }}
                catch (e) {{ return (e instanceof m.DeckCodeError ? 'DCE:' : 'OTHER:') + e.message; }} }}""", text)
            assert msg and msg.startswith("DCE:") and why in msg, (text, msg)
        # 1 字の書き間違いは検査の 8 ビットで見つかる（全部の位置を 1 字ずつ変えて、読めてしまったものが無い）
        missed = await a.evaluate(f"""async (c) => {{ const m = await {lib}; const B = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
            let n = 0; for (let i = 0; i < c.length; i++) {{ const t = c.slice(0, i) + B[(B.indexOf(c[i]) + 7) % 62] + c.slice(i + 1);
              try {{ m.decodeDeck(t); n++; }} catch (e) {{}} }} return n; }}""", good)
        assert missed == 0
        # 版 1（MS1:…）で出したコードも読める
        v1 = "MS1:CBP01-018/ASD01-007*2"
        assert await a.evaluate(f"async (c) => (await {lib}).decodeDeck(c)", v1) == {"chara_deck": ["BP01-018"], "action_deck": ["SD01-007", "SD01-007"]}
        chara, action = decks["SD001"]["chara_deck"][0], decks["SD001"]["action_deck"][0]
        kinds = "(c) => ({%r: 'chara', %r: 'action'})[c]" % (chara, action)
        for text, why in {_deck_code_oracle({"chara_deck": ["ZZ9-999"], "action_deck": []}): "知らないカード番号",
                          _deck_code_oracle({"chara_deck": [action], "action_deck": []}): "欄の違う"}.items():
            msg = await a.evaluate(f"""async (t) => {{ const m = await {lib}; try {{ m.decodeDeck(t, {kinds}); return null; }} catch (e) {{ return e.message; }} }}""", text)
            assert msg and why in msg, (text, msg)

        # デッキメーカー: コードから読む → 新しいデッキとして入り、検査が全部通る → コードを出すと同じ 1 行
        code = _deck_code_oracle(decks["SD02"])
        await a.click("#deck-code-in")
        await a.fill("#code-in", _deck_code_oracle({"chara_deck": ["ZZ9-999"], "action_deck": []}))
        await a.click("#code-load")
        assert "知らないカード番号" in await a.inner_text("#code-err")                 # 拒んだ理由が出て、デッキは増えない
        await a.fill("#code-in", code)
        await a.fill("#code-name", "もらったSD02")
        await a.click("#code-load")
        await a.wait_for_function("document.querySelector('#deck-name').value === 'もらったSD02'")
        assert await a.locator("#checks .check.err, #checks .check.warn").count() == 0
        await a.click("#deck-code")
        assert await a.input_value("#code-out") == code
        await a.click("#code-sheet .btn.ghost")

        # ロビーの「デッキを読み込む」にも貼れる。サーバが受け入れる
        room = await create_room(a, rig.url, "マスター", "pw")
        await a.click('button[data-act="sit"][data-seat="0"]')
        await a.click('button:has-text("デッキを読み込む")')
        await a.fill("#deck-json", "MS1:C/A" + "x")
        await a.click('.modal button:has-text("読み込んで使う")')
        assert "読めない" in await a.inner_text(".modal .err")
        await a.fill("#deck-json", _deck_code_oracle(decks["SD001"]))
        await a.click('.modal button:has-text("読み込んで使う")')
        await a.wait_for_selector("#ready:not([disabled])")
        r = rig.room(room)
        assert r.decks[0]["name"] == "コードから読んだデッキ" and sorted(r.decks[0]["action_deck"]) == sorted(decks["SD001"]["action_deck"])
        assert not rig.errors, rig.errors[:5]


async def test_replay_after_a_cpu_game_and_from_the_records(tmp_path):
    """リプレイ（R-REP-1〜3・APP-019）: 終局したら結果の画面から開ける。1 手送り・戻し・ターン単位・最初と最後・自動再生・視点の切り替え。
    全情報では相手の手札が表向き、公開情報のみでは自分の手札も伏せる。閉じると下の対局の画面が残っている。手元の記録の一覧からも開ける。"""
    import json
    async with Rig(tmp_path) as rig:
        a = await rig.page("A", fx="off", **PC)
        await a.goto(rig.url + "/")
        await a.fill("#name", "マスター")
        await a.select_option("#cpu-deck", "SD001")
        await a.select_option("#cpu-level", "0")
        await a.click("#cpu-start")
        await a.wait_for_selector("#board .midbar")
        await UiPlayer(a, "mouse", 31).play(timeout=300)
        await a.wait_for_selector('.modal button[data-act="replay"]')
        await a.click('.modal button[data-act="replay"]')
        await a.wait_for_selector("#layer-replay #board .midbar #replay-label")
        label = lambda: a.inner_text("#replay-label")                       # noqa: E731
        first = await label()
        n = int(first.split("/")[1].split("手")[0])
        assert first.startswith("0 / ") and n > 10
        assert await a.locator('#layer-replay [data-act="rp-prev"]').is_disabled()
        await a.click('#layer-replay [data-act="rp-next"]')
        assert (await label()).startswith("1 / ")
        await a.click('#layer-replay [data-act="rp-prev"]')
        assert (await label()).startswith("0 / ")
        await a.keyboard.press("ArrowRight")                                  # キーでも送れる
        assert (await label()).startswith("1 / ")
        await a.click('#layer-replay [data-act="rp-next-turn"]')
        await a.click('#layer-replay [data-act="rp-next-turn"]')
        t2 = await a.inner_text("#layer-replay .midbar .ph")
        assert "ターン" in t2
        await a.click('#layer-replay [data-act="rp-last"]')
        assert (await label()).startswith(f"{n} / ") and ("の勝ち" in await label() or "引き分け" in await label())
        assert await a.locator('#layer-replay [data-act="rp-next"]').is_disabled()
        # 視点: 途中の局面で、全情報なら相手の手札が表向き、公開情報のみなら自分の手札も伏せてある
        await a.click('#layer-replay [data-act="rp-first"]')
        for _ in range(3):
            await a.click('#layer-replay [data-act="rp-next-turn"]')
        pos = await label()
        await a.select_option("#replay-viewer", "full")
        await a.wait_for_function("document.querySelector('#replay-viewer').value === 'full' && !document.querySelector('#layer-replay .handrow .card.back')")
        assert await a.locator("#layer-replay .handrow.opp .card").count() > 0
        assert (await label()).split("｜")[0] == pos.split("｜")[0]              # 視点を替えても同じ手のまま
        await a.select_option("#replay-viewer", "spec")
        await a.wait_for_function("document.querySelector('#replay-viewer').value === 'spec' && document.querySelectorAll('#layer-replay .handrow.me .card.back').length > 0")
        assert await a.locator("#layer-replay .handrow.me .card:not(.back)").count() == 0
        # 自動再生で進み、止められる
        await a.click('#layer-replay [data-act="rp-auto"]')
        await a.wait_for_function(f"!document.querySelector('#replay-label').textContent.startsWith({json.dumps(pos.split(' ')[0] + ' ')})", timeout=10000)
        await a.click('#layer-replay [data-act="rp-auto"]')
        # 閉じると、下の対局の画面（部屋）がそのまま残っている
        await a.click('#layer-replay [data-act="rp-close"]')
        assert await a.locator("#layer-replay").count() == 0 and await a.locator("#app #board .midbar").count() == 1

        # 手元の記録の一覧からも開ける
        await a.goto(rig.url + "/")
        await a.click("#home-records")
        await a.wait_for_selector(".modal .record-row")
        assert await a.locator(".modal .record-row").count() == 1 and "CPU" in await a.inner_text(".modal .record-row")
        await a.click('.modal .record-row button[data-act="record-replay"]')
        await a.wait_for_selector("#layer-replay #replay-label")
        assert (await label()).startswith(f"0 / {n} ")
        assert await a.input_value("#replay-viewer") in ("0", "1")                # CPU 対戦は自分の席の視点で開く
        assert not rig.errors, rig.errors[:5]


FEEDBACK_WATCH = """() => {
  window.__fb = {calls: [], toasts: [], alert: 0, alertPrompt: '', areaCall: 0};
  new MutationObserver((muts) => { for (const m of muts) for (const n of m.addedNodes) {
    if (!n.classList) continue;
    if (n.classList.contains('fx-call')) window.__fb.calls.push(n.textContent);
    if (n.classList.contains('toast')) window.__fb.toasts.push(n.textContent);
  } }).observe(document.body, {childList: true, subtree: true});
  setInterval(() => {
    const bar = document.querySelector('#board .midbar.alert');
    if (bar) { window.__fb.alert += 1; window.__fb.alertPrompt = bar.querySelector('.prompt').textContent; }
    if (document.querySelector('#board .side.me .zone.area.call')) window.__fb.areaCall += 1;
  }, 25);
}"""


async def test_friend_feedback_order_clash_call_and_auto_pay(tmp_path):
    """知人との対戦の感想（APP-022）: 準備のうちから先攻後攻が分かる／対抗の提出が自分に来たことを強く知らせる／
    協奏エリアからの支払いを、対局画面のボタンで自動にできる（自動の人は支払いを自分で選ばない）。"""
    async with Rig(tmp_path, seed_source=lambda: FX_SEED) as rig:
        a = await rig.page("A", fx="on", speed=3, auto_pay=True, **PC)
        b = await rig.page("B", fx="on", speed=3, **PHONE)
        room = await create_room(a, rig.url, "マスター", "pw")
        await a.select_option("#first", "seat0")                  # 席 1（マスター）が先攻
        await sit_and_ready(a, 0, "SD001")
        await join_room(b, rig.url, room, "知人", "pw")
        for p in (a, b):
            await p.evaluate(FEEDBACK_WATCH)
        await sit_and_ready(b, 1, "SD02")
        await a.wait_for_selector('#board [data-role="tray"]')
        await b.wait_for_selector('#board [data-role="tray"]')

        # 1. 先攻後攻: 中央の帯・準備の案内・ライフの札・最初の知らせ
        assert "あなたは先攻" in await a.inner_text("#board .midbar .ph")
        assert "あなたは後攻" in await b.inner_text("#board .midbar .ph")
        assert "あなたは先攻" in await a.inner_text("#board .tray .hint")
        assert await a.inner_text(".side.me .order-chip") == "先攻" and await a.inner_text(".side.opp .order-chip") == "後攻"
        await a.wait_for_function("window.__fb.calls.some((t) => t.includes('あなたは先攻'))")
        await b.wait_for_function("window.__fb.calls.some((t) => t.includes('あなたは後攻'))")

        # 自動支払いのボタン: A は入、B は切。押すと切り替わる
        assert await a.inner_text('#board .midbar button[data-act="autopay"]') == "自動支払い 入"
        await b.click('#board .midbar button[data-act="autopay"]')
        assert await b.inner_text('#board .midbar button[data-act="autopay"]') == "自動支払い 入"
        await b.click('#board .midbar button[data-act="autopay"]')
        assert await b.inner_text('#board .midbar button[data-act="autopay"]') == "自動支払い 切"

        async def seen_enough(page):
            fb = await a.evaluate("window.__fb")
            return fb["alert"] > 0 and any("自動で支払った" in t for t in fb["toasts"])
        pa, pb = UiPlayer(a, "mouse", 7), UiPlayer(b, "touch", 8)
        await asyncio.gather(pa.play(timeout=300, until=seen_enough), pb.play(timeout=300, until=seen_enough))

        fa, fb = await a.evaluate("window.__fb"), await b.evaluate("window.__fb")
        # 2. 対抗の提出の知らせ: 帯が光り、文が出て、自分のアクションエリアが脈打ち、知らせと音が出る
        for f in (fa, fb):
            assert f["alert"] > 0 and f["areaCall"] > 0, f
            assert "対抗" in f["alertPrompt"] and any("対抗" in t for t in f["calls"]), f
        sounds = set(await a.evaluate("window.__meichosim.board.sfxPlayed"))
        assert "call" in sounds or fa["calls"], sounds
        # 4. 自動支払い: A は自動で払った。B（切）は自動で払っていない
        assert any("自動で支払った" in t for t in fa["toasts"]), fa["toasts"]
        assert not any("自動で支払った" in t for t in fb["toasts"]), fb["toasts"]
        assert not rig.errors, rig.errors[:5]


EFFECTS_WATCH = """() => {
  window.__eff = {panel: 0, now: 0, resolving: 0, bracket: 0, texts: [], nulls: 0};
  setInterval(() => {
    const p = document.querySelector('#board .midbar .effects');
    if (p) { window.__eff.panel += 1; if (window.__eff.texts.length < 20) window.__eff.texts.push(p.textContent); }
    if (document.querySelector('#board .midbar .effects .effrow.now')) window.__eff.now += 1;
    if (document.querySelector('#board .card.resolving')) window.__eff.resolving += 1;
    const pr = document.querySelector('#board .midbar .prompt');
    if (pr && pr.textContent.startsWith('【')) window.__eff.bracket += 1;
    const bar = document.querySelector('#board .midbar');
    if (bar && [...bar.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim() === 'null')) window.__eff.nulls += 1;
  }, 20);
}"""


async def test_effects_being_resolved_are_shown(tmp_path):
    """APP-023: 効果の解決中は、中央の帯の上に「解決中」と「待ち」の一覧が出て、解決中のカードが盤面で光り、
    自分の選択なら文の頭にカードの名前が付く。何も積まれていないときは一覧を出さない（帯に余計な文字も出ない）。"""
    async with Rig(tmp_path, seed_source=lambda: FX_SEED) as rig:
        a = await rig.page("A", fx="off", **PC)
        b = await rig.page("B", fx="off", **PHONE)
        room = await create_room(a, rig.url, "マスター", "pw")
        await sit_and_ready(a, 0, "SD001")
        await join_room(b, rig.url, room, "知人", "pw")
        await sit_and_ready(b, 1, "SD02")
        for p in (a, b):
            await p.wait_for_selector("#board .midbar")
            await p.evaluate(EFFECTS_WATCH)

        async def enough(page):
            ea, eb = await a.evaluate("window.__eff"), await b.evaluate("window.__eff")
            return all(e["now"] > 0 and e["resolving"] > 0 for e in (ea, eb)) and (ea["bracket"] + eb["bracket"]) > 0
        pa, pb = UiPlayer(a, "mouse", 11), UiPlayer(b, "touch", 12)
        await asyncio.gather(pa.play(timeout=300, until=enough), pb.play(timeout=300, until=enough))
        for p in (a, b):
            e = await p.evaluate("window.__eff")
            assert e["panel"] > 0 and e["now"] > 0 and e["resolving"] > 0, e
            assert any("解決中" in t for t in e["texts"]), e["texts"]
            assert e["nulls"] == 0, e
        assert not rig.errors, rig.errors[:5]



async def test_level_up_from_a_character_on_the_board(tmp_path):
    """APP-026: アクションフェイズに場のキャラを選ぶとレベルアップできる。バックでリーダーにもできるときは
    「レベルアップする／リーダーにする」を尋ね、レベルアップを選ぶとレベルアップ先を選ぶ（候補が 1 つなら確認だけ）。"""
    async with Rig(tmp_path, seed_source=lambda: FX_SEED) as rig:
        a = await rig.page("A", fx="off", **PC)
        b = await rig.page("B", fx="off", **PC)
        room = await create_room(a, rig.url, "マスター", "pw")
        await a.select_option("#first", "seat0")
        await sit_and_ready(a, 0, "SD001")
        await join_room(b, rig.url, room, "知人", "pw")
        await sit_and_ready(b, 1, "SD02")
        game = lambda: rig.room(room).game                        # noqa: E731

        def both_ok():                                            # A の番で、同じバックに「切り替え」と「レベルアップ」の両方がある
            g = game()
            if g is None or 0 not in g.awaiting() or g.state.phase.value != "action":
                return None
            acts = g.legal(0)
            for slot in (1, 2):
                if any(x["type"] == "switch" and x["back"] == slot for x in acts) and any(x["type"] == "levelup" and x["slot"] == slot for x in acts):
                    return slot
            return None

        async def ready(page):
            return both_ok() is not None
        async def settle():
            """自動の打ち手を止めた直後は、ダイアログが開いていたり演出の途中だったりする。閉じて、落ち着いてから条件を見直す"""
            for _ in range(40):
                await a.wait_for_timeout(100)
                btn = await a.query_selector('#layer-modal button[data-act="cancel"], #layer-modal button[data-act="close"]')
                if btn:
                    await btn.click()
                    continue
                if not await a.query_selector("#layer-modal .modal, #board.playing") and both_ok() is not None:
                    return both_ok()
            return None
        pa, pb = UiPlayer(a, "mouse", 21), UiPlayer(b, "mouse", 22)
        slot = None
        for _ in range(5):
            await asyncio.gather(pa.play(timeout=200, until=ready), pb.play(timeout=200, until=ready))
            slot = await settle()
            if slot is not None:
                break
        assert slot is not None
        await a.wait_for_selector(f'.side.me [data-zone="slot"][data-slot="{slot}"].lit')
        n = len(game().applies)
        cands = {x["card"] for x in game().legal(0) if x["type"] == "levelup" and x["slot"] == slot}

        # バックを選ぶ → 尋ねる → やめる、なら何も起きない
        await a.click(f'.side.me [data-zone="slot"][data-slot="{slot}"]')
        await a.wait_for_selector('.modal button[data-act="slot-levelup"]')
        assert await a.locator('.modal button[data-act="slot-switch"]').count() == 1
        await a.click('.modal button[data-act="close"]')
        assert len(game().applies) == n

        # レベルアップを選ぶ → 候補が 1 つなら確認、複数ならレベルアップ先を選んでから確認
        await a.click(f'.side.me [data-zone="slot"][data-slot="{slot}"]')
        await a.click('.modal button[data-act="slot-levelup"]')
        if len(cands) > 1:
            await a.wait_for_selector(".modal .grid [data-pick]")
            assert await a.locator(".modal .grid [data-pick]").count() == len(cands)
            await a.click(".modal .grid [data-pick]")
        await a.wait_for_selector('.modal button[data-act="ok"]')
        assert "重ねる" in await a.inner_text(".modal")
        await a.click('.modal button[data-act="ok"]')
        for _ in range(100):
            if len(game().applies) > n:
                break
            await a.wait_for_timeout(50)
        applied = game().applies[n]                               # 1 要素 = {席(文字列): 行動}
        assert applied["0"]["type"] == "levelup" and applied["0"]["slot"] == slot and applied["0"]["card"] in cands, applied
        assert not rig.errors, rig.errors[:5]
