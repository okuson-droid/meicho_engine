"""起動役の本体（要件 R-UPD-1〜9）。標準ライブラリだけ。

## 1 回の起動でやること

1. すでに MeichoSim が動いていれば、ブラウザを開いて終わる（ポートは固定なので 2 つは動かせない）。
2. 更新を確かめ、あれば取り込む（`updater.update`）。失敗しても先へ進む。
3. 今の版を目録と突き合わせ、**子プロセス**でサーバを起動する。
   `/api/health` が返れば成功。返らなければ子を止め、一つ前の版へ戻してもう一度起動する（R-UPD-5）。
4. ブラウザを開き、子が終わるまで待つ。このウィンドウを閉じればサーバも止まる。

## なぜ子プロセスか

- 新しい版が import の時点で落ちても、起動役は生きていて前の版へ戻せる。
- 起動役は `app`・`meicho`・`webapp` を import しないので、固めた実行ファイルに中身が焼き込まれない。
  子は同じ実行ファイルを `--child <版フォルダ>` で呼び直したもので、版フォルダを import 経路の先頭に足してから
  `app.server` を**名前の文字列で**読み込む。
"""
from __future__ import annotations

import importlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from . import LAUNCHER_API, PORT
from . import manifest as M
from . import updater

START_TIMEOUT = 60         # 子のサーバが応答するまで待つ秒数（遅い PC のウイルス対策ソフトの走査を見込む）
_HERE = os.path.dirname(os.path.abspath(__file__))


def app_root() -> str:
    """配布フォルダの根（`contents/`・`data/`・`launcher.json` がある場所）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.getcwd()


def load_public() -> bytes:
    """マスターの公開鍵。**起動役の側に持つ**（中身の側に置くと、更新で差し替えられてしまう）。"""
    with open(os.path.join(_HERE, "pubkey.txt"), encoding="utf-8") as f:
        return M.parse_public(f.read())


def say(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:                                   # noqa: BLE001  画面に出せないことで起動を止めない
        pass


def health(port: int, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            d = json.loads(r.read(65536).decode("utf-8"))
        return d if isinstance(d, dict) and d.get("ok") and "rooms" in d else None
    except Exception:                                   # noqa: BLE001
        return None


def port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 直前に終了したサーバの後始末（TIME_WAIT）を「使用中」と見誤らない。Windows の SO_REUSEADDR は
    # 使用中のポートにも bind できてしまう別物なので、そちらでは「独占で開けるか」を確かめる
    if os.name == "nt":
        s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
    else:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def child_command(ver_dir: str, extra: list) -> list:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--child", ver_dir] + extra
    # 固めていないとき（検査・公開前の煙テスト）も、子は最上位の `mslauncher` として動かす。
    # `app.mslauncher` として動かすと開発ツリーの `app` が先に読み込まれ、版フォルダの `app.server` に届かない。
    boot = "import sys; sys.path.insert(0, sys.argv.pop(1)); from mslauncher.main import main; sys.exit(main())"
    return [sys.executable, "-c", boot, os.path.dirname(_HERE), "--child", ver_dir] + extra


def run_child(ver_dir: str, argv: list) -> int:
    """子プロセスの中身。版フォルダを import 経路に足して、中身のサーバ（または自己検査）を動かす。"""
    engine = os.path.join(ver_dir, "engine")
    for p in (os.path.join(engine, "experiments"), engine):
        sys.path.insert(0, p)
    sys.dont_write_bytecode = True                      # 版フォルダに __pycache__ を増やさない（目録と突き合わせる対象を汚さない）
    if argv and argv[0] == "--selfcheck":
        return int(importlib.import_module("app.selfcheck").main(argv[1:]) or 0)
    importlib.import_module("app.server").main(argv)
    return 0


def start(root: str, store: updater.Store, public: bytes, port: int, status_path: str):
    """今の版を起動する。だめなら一つ前へ戻して起動する。返り値は (子プロセス, 版, 起動に失敗して戻した版の名前 | None)。"""
    rolled = None
    for _attempt in range(2):
        cur = store.current()
        if not cur:
            break
        ver_dir = store.ver_dir(cur["version"])
        wrong = store.check_installed(cur["version"], public)
        if wrong:
            say(f"版 {cur['version']} が壊れている（{wrong[0]} ほか {len(wrong) - 1} 件）")
        else:
            say(f"版 {cur['version']} を起動している…")
            env = dict(os.environ, MEICHOSIM_STATUS=status_path, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            child = subprocess.Popen(child_command(ver_dir, ["--data", os.path.join(root, "data"), "--host", "127.0.0.1",
                                                             "--port", str(port), "--cpu", "on"]), env=env, cwd=root)
            t0 = time.monotonic()
            while time.monotonic() - t0 < START_TIMEOUT and child.poll() is None:
                if health(port, 1.0):
                    return child, cur, rolled
                time.sleep(0.3)
            if child.poll() is None:
                child.kill()
                child.wait(10)
            say(f"版 {cur['version']} が起動しなかった")
        if rolled or not store.rollback():
            break
        rolled = cur["version"]
        say("一つ前の版に戻す")
    return None, None, rolled


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):             # Windows の端末（cp932）で表せない字があっても、表示のせいで止まらない
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if argv and argv[0] == "--child":
        return run_child(argv[1], argv[2:])

    root = app_root()
    no_browser = "--no-browser" in argv
    port = PORT
    if "--port" in argv:                                # 検査用。配る版では固定のまま使う（R-UPD-6）
        port = int(argv[argv.index("--port") + 1])
    cfg = updater._read_json(os.path.join(root, "launcher.json"), {}) or {}
    url = f"http://127.0.0.1:{port}/"
    public = load_public()
    store = updater.Store(root)

    if "--selfcheck" in argv:
        cur = store.current()
        if not cur or store.check_installed(cur["version"], public):
            say("NG: 中身が無いか、目録と合わない")
            return 1
        return subprocess.call(child_command(store.ver_dir(cur["version"]), ["--selfcheck"]),
                               env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"), cwd=root)

    say("MeichoSim（非公式のファンツール）")
    if health(port):
        say("すでに起動しているので、ブラウザを開く")
        if not no_browser:
            webbrowser.open(url)
        return 0
    if not port_free(port):
        say(f"ポート {port} を別のプログラムが使っているので起動できない。そのプログラムを終了してから、もう一度起動してほしい。")
        return 2

    status = updater.update(root, None if "--offline" in argv else cfg.get("feed"), public, LAUNCHER_API, say,
                            feed_key=cfg.get("feed_key"))
    if status["state"] in ("offline", "failed", "launcher_outdated"):
        say(f"更新しなかった: {status['detail']}（手元の版で起動する）")
    status_path = os.path.join(root, "contents", "last_update.json")
    status["launcher_api"] = LAUNCHER_API

    def write_status():
        try:
            updater._write_json(status_path, status)
        except OSError:
            pass
    write_status()

    child, cur, rolled = start(root, store, public, port, status_path)
    if rolled:
        status.update(state="rolled_back", detail=f"版 {rolled} は起動に失敗したので、一つ前の版に戻した")
        write_status()
    if child is None:
        say("起動できなかった。配布の zip を展開し直してほしい（data フォルダは残してよい。棋譜と設定が入っている）。")
        return 1
    say(f"起動した: {url}")
    say("このウィンドウを閉じると終了する。")
    if not no_browser:
        webbrowser.open(url)
    def stop(_sig, _frame):                             # 起動役を止められたら、子（サーバ）も止める
        raise KeyboardInterrupt
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        try:
            child.wait(10)
        except subprocess.TimeoutExpired:
            child.kill()
        return 0


if __name__ == "__main__":
    sys.exit(main())
