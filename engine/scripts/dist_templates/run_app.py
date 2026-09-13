"""配布版の起動口（D-074）。

ソースのまま `python run_app.py` でも、PyInstaller で固めた実行ファイルでも、
この 1 本が入口である。やることは 3 つだけ。

1. `engine/` と `engine/experiments/` を import 経路に足す
   （固めたときは PyInstaller が `pathex` で同じことをするので何もしない）。
2. `--selfcheck` なら、AI 同士で 1 局打ち、サーバの設定応答を確かめて終わる
   （組み立て直後の煙テスト。`scripts/make_dist.py --smoke` が呼ぶ）。
3. それ以外は対人アプリのサーバ（`webapp.server.main`）を起動する。

ルールも AI も持たない。**ここを変えても対局は変わらない。**
"""
from __future__ import annotations

import os
import sys


def _setup_path() -> str:
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS                       # PyInstaller のバンドル
    else:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine")
    for p in (base, os.path.join(base, "experiments")):
        if p not in sys.path:
            sys.path.insert(0, p)
    return base


def selfcheck() -> int:
    """煙テスト。champion（Python 版）対 H を 1 局、次にサーバの設定応答。落ちたら 1。"""
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    from arena import load_deck, mirror_config
    from meicho.runner import play_game
    from webapp import agents, distribution, server

    info = distribution.info()
    print(f"配布モード: {'あり' if info else 'なし'}"
          + (f"（{info['name']}）" if info else ""))

    deck = load_deck("SD001")
    cfg = mirror_config(deck)
    pool = deck["action_deck"]
    name = agents.default_for("SD001")
    a = agents.build(name, pool, 1, deck_name="SD001")
    from registry import make
    h = make("heuristic", {}, pool)(2)
    r = play_game(cfg, [a, h], 990001)
    print(f"1 局: {name} 対 heuristic  勝者 {r.get('winner')}  ターン {r.get('turns')}")
    if r.get("aborted"):
        print("NG: 対局が打ち切られた")
        return 1

    server.APP = server.App("SD001")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=10) as f:
            c = json.loads(f.read().decode("utf-8"))
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as f:
            html = f.read().decode("utf-8")
    finally:
        srv.shutdown()
        srv.server_close()
    ok = True
    if info and "dist" not in c:
        print("NG: 配布モードなのに /api/config に dist が無い")
        ok = False
    if info and not c.get("images", {}).get("intentionally_absent"):
        print("NG: 配布モードなのに画像の欠けが「仕様」と印されていない")
        ok = False
    if "<html" not in html.lower():
        print("NG: 画面が返らない")
        ok = False
    print(f"相手の一覧: {[o['key'] for o in c['opponents']]}  既定 {c['default']}")
    print(f"記録の置き場: {os.path.normpath(server.results_dir())}")
    print("OK" if ok else "NG")
    return 0 if ok else 1


def main() -> None:
    _setup_path()
    argv = sys.argv[1:]
    if "--selfcheck" in argv:
        sys.exit(selfcheck())
    from webapp.server import main as serve
    serve(argv)


if __name__ == "__main__":
    main()
