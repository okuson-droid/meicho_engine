"""ローカル HTTP サーバ（APP_DESIGN.md §0.3・段階1）。

標準ライブラリのみ（プロジェクト方針「依存なし、テストのみ pytest」）。
**127.0.0.1 にのみ結び付け、外部には公開しない。**

## API（すべて JSON）

| メソッド | 経路 | 用途 |
|---|---|---|
| GET  | `/api/config`   | 選べる相手の一覧など |
| POST | `/api/new`      | 新しい対局を始める |
| GET  | `/api/state`    | 盤面と合法手（**observe だけから作る**） |
| POST | `/api/play`     | 合法手の**添字**を送る |
| POST | `/api/flag`     | 「気になる」印 |
| POST | `/api/resign`   | 投了 |
| POST | `/api/finish`   | 記録を保存して終了 |
| GET  | `/card/<ID>.png`| カード画像（UI_DESIGN.md §4.2） |

**全情報を返す API は段階1 では作らない**（レビューは段階2）。
作るときは §5.7 の安全装置（進行中の対局には応答しない）を必ず入れること。

起動: `python3 -m webapp.server [--port 8765] [--no-browser]`
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from webapp import agents, distribution, images, record            # noqa: E402
from webapp.session import IllegalMove, Session, StaleView         # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(_HERE, "static")


def results_dir() -> str:
    """記録の置き場。配布モード（D-074）では実行ファイルの隣、それ以外は従来の `engine/results`。

    モジュール定数にしないのは、配布モードの入切（検査・マーカー）に追従させるため。
    """
    return distribution.results_dir()


def config_payload(app: "App") -> dict:
    """`/api/config` の中身。画面の開始画面はこれだけで組み立てる。

    配布モード（D-074）では `dist`（名前・注意書き）を足し、画像の欠けを
    「仕様として無い」（`intentionally_absent`）と印を付ける。画面はそれを見て、
    警告ではなく説明を出す。マーカーが無ければ従来の応答と同じ鍵しか出ない。
    """
    im = images.status()
    payload = {
        # 相手はデッキごとに変わる（π はプール専用・D-058）
        "opponents": [{"key": k, "label": v["label"]}
                      for k, v in agents.available(app.deck_name).items()],
        "default": agents.default_for(app.deck_name),
        "deck": app.deck_name,
        "decks": list(DECKS),
        "next_seed": app.next_seed,
        "history": app.tally(),
        # 画像が引けなかったカードは**黙って落とさない**（§7.3）
        "images": im,
    }
    dist = distribution.public_info()
    if dist is not None:
        payload["dist"] = dist
        payload["images"] = dict(im, intentionally_absent=True)
    return payload

# シード帯 130000..139999 は seed_bands.json に登録して使う（§8.3 / D-028）。
SEED0 = 130000
SEED_END = 139999


# 選べるデッキ。**カードプールが増えたらここに足すだけで済むようにする**
# （D-047: プール固有の知識をコードに埋めない）。
DECKS = ("SD001", "SD02")


class App:
    """サーバ全体の状態。対局は同時に 1 つだけ持つ（1 人用）。

    デッキは**対局ごとに選べる**（D-048）。人間の基準値はデッキごとに別物なので、
    どのデッキで取った記録かを混ぜてはならない。記録の `deck` に必ず残る。
    """

    def __init__(self, deck_name: str = "SD001"):
        self.session: Session | None = None
        self.games_played = 0
        self.history: list = []          # この起動での勝敗（表示用）
        self.set_deck(deck_name)
        self.next_seed = self._resume_seed()

    def set_deck(self, deck_name: str) -> None:
        from arena import load_deck, mirror_config
        if deck_name not in DECKS:
            raise KeyError(f"未登録のデッキ: {deck_name!r}（登録済: {list(DECKS)}）")
        self.deck_name = deck_name
        self.deck = load_deck(deck_name)
        self.config = mirror_config(self.deck)
        self.pool = self.deck["action_deck"]

    def _resume_seed(self) -> int:
        """既に使ったシードの続きから取る（帯の重複を避ける）。"""
        used = [r["seed"] for r in record.load_all(results_dir())
                if SEED0 <= r.get("seed", -1) <= SEED_END]
        return (max(used) + 1) if used else SEED0

    def new_game(self, opponent: str, show_ai_thinking: bool = False,
                 deck_name: str = None) -> Session:
        if deck_name and deck_name != self.deck_name:
            self.set_deck(deck_name)
        if self.next_seed > SEED_END:
            raise RuntimeError("シード帯 130000..139999 を使い切った。台帳を更新すること")
        seed = self.next_seed
        self.next_seed += 1
        # 席は自動で交互に入れ替える（先攻有利の相殺・§8.3）
        human_seat = self.games_played % 2
        ai_seed = seed * 2 + (1 - human_seat)
        ai = agents.build(opponent, self.pool, ai_seed, deck_name=self.deck_name)
        self.games_played += 1
        self.session = Session(
            game_id=f"g{self.games_played:03d}", config=self.config,
            pool=self.pool, seed=seed, human_seat=human_seat,
            opponent_name=opponent, ai=ai, ai_seed=ai_seed,
            deck_name=self.deck_name, show_ai_thinking=show_ai_thinking)
        return self.session

    def finish(self) -> dict:
        """記録を保存し、その場で再生して一致を確かめる（§6.2）。"""
        s = self.session
        if s is None:
            raise RuntimeError("対局がない")
        rec = record.to_record(s)
        path = record.save(rec, results_dir())
        verified, problem = True, None
        try:
            record.verify(rec, self.config)
        except Exception as e:
            verified, problem = False, f"{type(e).__name__}: {e}"
        res = s.result() or {}
        self.history.append({"game_id": s.game_id, "winner": res.get("winner"),
                             "opponent": s.opponent_name, "turns": res.get("turns")})
        self.session = None
        return {"saved": path, "verified": verified, "problem": problem,
                "result": res, "history": self.tally()}

    def tally(self) -> dict:
        """この起動での戦績（信頼区間つき）。"""
        import math
        dec = [h for h in self.history if h["winner"] in ("human", "ai")]
        n = len(dec)
        w = sum(1 for h in dec if h["winner"] == "human")
        if not n:
            return {"n": 0, "wins": 0, "games": len(self.history)}
        p = w / n
        ci = 1.96 * math.sqrt(p * (1 - p) / n)
        return {"n": n, "wins": w, "rate": round(p, 3), "ci": round(ci, 3),
                "games": len(self.history)}


APP: App | None = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- 送受信 ------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str,
              cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # API と画面は毎回作り直す。**カード画像だけは恒久キャッシュ**にする
        # （内容が変わらないので、1手ごとに 18MB 読み直させない・UI_DESIGN.md §4.2）。
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode() or "{}")

    def log_message(self, fmt, *args):        # 既定のアクセスログは出さない
        pass

    # -- 経路 --------------------------------------------------------------
    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                return self._static("index.html", "text/html; charset=utf-8")
            if self.path == "/app.js":
                return self._static("app.js", "application/javascript; charset=utf-8")
            if self.path == "/style.css":
                return self._static("style.css", "text/css; charset=utf-8")
            if self.path.startswith(images.URL_PREFIX):
                return self._card_image(self.path)
            if self.path == "/api/config":
                return self._json(config_payload(APP))
            if self.path == "/api/state":
                if APP.session is None:
                    return self._json({"no_game": True, "history": APP.tally()})
                return self._json(APP.session.snapshot())
            self._json({"error": "not found"}, 404)
        except Exception:
            self._fail()

    def do_POST(self):
        try:
            b = self._body()
            if self.path == "/api/new":
                s = APP.new_game(b.get("opponent")
                                 or agents.default_for(b.get("deck") or APP.deck_name),
                                 bool(b.get("show_ai_thinking")),
                                 deck_name=b.get("deck"))
                return self._json(s.snapshot())
            if APP.session is None:
                return self._json({"error": "対局がありません"}, 400)
            if self.path == "/api/play":
                try:
                    APP.session.play(int(b["index"]), int(b["ply"]))
                except StaleView as e:
                    return self._json({"error": str(e), "stale": True}, 409)
                except IllegalMove as e:
                    return self._json({"error": str(e)}, 400)
                return self._json(APP.session.snapshot())
            if self.path == "/api/flag":
                APP.session.flag(str(b.get("note") or ""))
                return self._json(APP.session.snapshot())
            if self.path == "/api/resign":
                APP.session.resign()
                return self._json(APP.session.snapshot())
            if self.path == "/api/finish":
                return self._json(APP.finish())
            self._json({"error": "not found"}, 404)
        except Exception:
            self._fail()

    def _card_image(self, path: str) -> None:
        """カード画像。**経路からファイルパスを組み立てない**（§4.2）。

        ID の書式を検査し、索引の辞書から引くだけなので、
        フォルダ横断（`../` 等）の危険が構造的に無い。
        """
        cid = images.id_from_url_path(path)
        src = images.path_for(cid) if cid else None
        if not src or not os.path.isfile(src):
            # 画面はテキスト表示に落ちる（§P3）。ここで落ちてはならない。
            return self._json({"error": f"画像がない: {cid}"}, 404)
        ext = os.path.splitext(src)[1].lower()
        ctype = {".png": "image/png", ".jpg": "image/jpeg",
                 ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext, "image/png")
        with open(src, "rb") as f:
            self._send(200, f.read(), ctype,
                       cache="public, max-age=31536000, immutable")

    def _static(self, name: str, ctype: str) -> None:
        path = os.path.join(STATIC, name)
        if not os.path.isfile(path):
            return self._json({"error": f"missing {name}"}, 404)
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def _fail(self) -> None:
        """例外は握りつぶさず、画面にそのまま出す（§1.3）。"""
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        self._json({"error": "サーバで例外が発生しました", "traceback": tb}, 500)


def main(argv: list | None = None) -> None:
    global APP
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)

    APP = App()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}"
    dist = distribution.public_info()
    if dist is None:
        print(f"鳴潮：対決 検証アプリ（段階1）")
    else:
        # 配布モード（D-074）: 名前と注意書きはマーカーから。公式名を名乗らない
        print(f"{dist['name']}" + (f"  v{dist['version']}" if dist.get("version") else ""))
        if dist.get("notice"):
            print(f"  {dist['notice']}")
        print(f"  記録の置き場: {os.path.normpath(results_dir())}")
    print(f"  デッキ {APP.deck_name} 同型 / 次のシード {APP.next_seed}")
    print(f"  ブラウザで開く: {url}")
    print(f"  終了: Ctrl-C（このウィンドウを閉じても止まる）")
    if not a.no_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました")


if __name__ == "__main__":
    main()
