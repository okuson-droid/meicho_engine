"""配布と自動更新（M5 後半・要件 R-UPD-1〜9、APP-010）の検査。

起動役（`app/mslauncher`）は標準ライブラリだけで動くので、ここの検査の大半は aiohttp が無くても回る。
起動の検査では、中身の代わりに「`/api/health` に答えるだけの小さなサーバ」を版フォルダに置く
（起動役が見るのは、子プロセスが立ち上がって応答するかどうかだけである）。
"""
import json
import os
import shutil
import socket
import sys
import urllib.request
import zlib
from pathlib import Path

import pytest

from app.mslauncher import LAUNCHER_API, ed25519, updater
from app.mslauncher import main as L
from app.mslauncher import manifest as M

SECRET = bytes(range(32))
PUBLIC = ed25519.public_key(SECRET)

FAKE_SERVER = '''
import argparse, json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
MARK = {mark!r}
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({{"ok": True, "rooms": 0, "mark": MARK, "status": os.environ.get("MEICHOSIM_STATUS")}}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--data"); ap.add_argument("--host"); ap.add_argument("--port", type=int); ap.add_argument("--cpu")
    a = ap.parse_args(argv)
    os.makedirs(a.data, exist_ok=True)
    HTTPServer((a.host, a.port), H).serve_forever()
'''


def make_release(feed_dir: Path, seq: int, files: dict, *, secret=SECRET, version=None, **extra) -> dict:
    """検査用の公開。`files` は {相対パス: 中身の bytes}。"""
    import hashlib
    (feed_dir / "files").mkdir(parents=True, exist_ok=True)
    meta = {}
    for rel, data in files.items():
        sha = hashlib.sha256(data).hexdigest()
        (feed_dir / "files" / f"{sha}.z").write_bytes(zlib.compress(data))
        meta[rel] = {"sha256": sha, "size": len(data)}
    m = {"format": 1, "version": version or f"t-{seq}", "seq": seq, "built": "x", "notes": f"n{seq}",
         "history": [], "launcher_api_min": 1, "files": meta, **extra}
    (feed_dir / "latest.json").write_bytes(M.seal(m, secret))
    return m


def contents(mark: str, broken: bool = False) -> dict:
    server = "raise RuntimeError('壊れた版')\n" if broken else FAKE_SERVER.format(mark=mark)
    return {"engine/app/__init__.py": b"", "engine/app/server.py": server.encode("utf-8"),
            "engine/big.json": json.dumps({"w": list(range(2000))}).encode()}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---- 署名 -------------------------------------------------------------------------------------------------------

RFC8032 = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


@pytest.mark.parametrize("sk,pk,msg,sig", RFC8032)
def test_ed25519_matches_rfc8032(sk, pk, msg, sig):
    sk, pk, msg, sig = (bytes.fromhex(x) for x in (sk, pk, msg, sig))
    assert ed25519.public_key(sk) == pk and ed25519.sign(sk, msg) == sig
    assert ed25519.verify(pk, msg, sig)
    assert not ed25519.verify(pk, msg + b"!", sig)
    assert not ed25519.verify(pk, msg, sig[:-1] + bytes([sig[-1] ^ 1]))
    assert not ed25519.verify(pk, msg, b"") and not ed25519.verify(b"\xff" * 32, msg, sig)     # 形の崩れた入力は例外にしない


def test_ed25519_agrees_with_a_second_implementation():
    crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    for i in range(8):
        sk, msg = os.urandom(32), os.urandom(i * 53)
        key = crypto.Ed25519PrivateKey.from_private_bytes(sk)
        assert ed25519.sign(sk, msg) == key.sign(msg)
        key.public_key().verify(ed25519.sign(sk, msg), msg)


# ---- 目録 -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rel", ["../x.py", "/abs.py", "a/../../x", "C:/x.py", "a\\b.py", "a//b", "a/./b", "", "a/", "con:1", "a/b. "])
def test_manifest_rejects_paths_that_escape_the_version_folder(rel):
    assert not M.safe_rel(rel)
    with pytest.raises(M.BadManifest):
        M.check({"format": 1, "version": "v", "seq": 1, "files": {rel: {"sha256": "0" * 64, "size": 0}}})


def test_manifest_rejects_case_colliding_paths():
    f = {"sha256": "0" * 64, "size": 0}
    with pytest.raises(M.BadManifest):
        M.check({"format": 1, "version": "v", "seq": 1, "files": {"a/B.py": f, "a/b.py": f}})


def test_envelope_signature_covers_every_byte(tmp_path):
    make_release(tmp_path, 1, {"engine/a.py": b"x"})
    raw = (tmp_path / "latest.json").read_bytes()
    m, _text, _sig = M.open_envelope(raw, PUBLIC)
    assert m["seq"] == 1
    env = json.loads(raw)
    env["manifest"] = env["manifest"].replace('"seq": 1', '"seq": 9')
    with pytest.raises(M.BadManifest):
        M.open_envelope(json.dumps(env).encode(), PUBLIC)
    with pytest.raises(M.BadManifest):
        M.open_envelope(raw, ed25519.public_key(b"\x01" * 32))          # 別人の鍵
    with pytest.raises(M.BadManifest):
        M.open_envelope(b"not json", PUBLIC)


# ---- 取り込み ---------------------------------------------------------------------------------------------------

class CountingFeed(updater.Feed):
    fetched: list = []

    def get(self, name, limit, timeout):
        CountingFeed.fetched.append(name)
        return super().get(name, limit, timeout)


@pytest.fixture
def counting(monkeypatch):
    CountingFeed.fetched = []
    monkeypatch.setattr(updater, "Feed", CountingFeed)
    return CountingFeed


def test_install_then_update_fetches_only_changed_files(tmp_path, counting):
    feed, root = tmp_path / "feed", tmp_path / "root"
    (root / "data").mkdir(parents=True)
    (root / "data" / "games.jsonl").write_text("棋譜", encoding="utf-8")
    make_release(feed, 1, contents("one"))
    st = updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    assert st["state"] == "updated" and st["to"] == "t-1"
    store = updater.Store(str(root))
    assert store.current() == {"version": "t-1", "seq": 1, "previous": None}
    assert store.check_installed("t-1", PUBLIC) == []
    assert len(counting.fetched) == 1 + 3

    counting.fetched.clear()
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)["state"] == "latest"       # 変わっていなければ何も取らない
    assert counting.fetched == ["latest.json"]

    counting.fetched.clear()
    make_release(feed, 2, contents("two"))                                                      # server.py だけが変わる
    st = updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    assert st["state"] == "updated" and (st["from"], st["to"]) == ("t-1", "t-2")
    assert len(counting.fetched) == 2, "変わったファイルだけを取る（R-UPD-2）"
    assert store.current()["previous"] == {"version": "t-1", "seq": 1}
    assert sorted(os.listdir(store.versions)) == ["t-1", "t-2"]

    make_release(feed, 3, contents("three"))
    updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    assert sorted(os.listdir(store.versions)) == ["t-2", "t-3"], "一つ前だけを残す（R-UPD-5）"
    assert (root / "data" / "games.jsonl").read_text(encoding="utf-8") == "棋譜", "利用者のデータに触らない（R-UPD-6）"
    assert not os.path.exists(store.staging)


def installed(tmp_path):
    feed, root = tmp_path / "feed", tmp_path / "root"
    make_release(feed, 5, contents("base"))
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)["state"] == "updated"
    return feed, root, updater.Store(str(root))


def test_tampered_file_is_not_adopted(tmp_path):
    feed, root, store = installed(tmp_path)
    m = make_release(feed, 6, contents("evil"))
    sha = m["files"]["engine/app/server.py"]["sha256"]
    (feed / "files" / f"{sha}.z").write_bytes(zlib.compress(b"x" * m["files"]["engine/app/server.py"]["size"]))   # 大きさは同じ、中身が違う
    st = updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    assert st["state"] == "failed" and store.current()["version"] == "t-5"
    assert os.listdir(store.versions) == ["t-5"] and not os.path.exists(store.staging)


def test_wrongly_signed_update_is_not_adopted(tmp_path):
    feed, root, store = installed(tmp_path)
    make_release(feed, 6, contents("evil"), secret=b"\x07" * 32)
    st = updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    assert st["state"] == "failed" and "署名" in st["detail"] and store.current()["version"] == "t-5"


def test_correctly_signed_old_release_cannot_downgrade(tmp_path):
    feed, root, store = installed(tmp_path)
    make_release(feed, 4, contents("old"))
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)["state"] == "latest"
    assert store.current()["version"] == "t-5"


def test_oversized_blob_is_refused(tmp_path):
    """目録の大きさを超えて膨らむ圧縮データは、展開しきる前に捨てる。"""
    feed, root, store = installed(tmp_path)
    m = make_release(feed, 6, dict(contents("bomb"), **{"engine/new.json": b"[1]"}))
    sha = m["files"]["engine/new.json"]["sha256"]
    (feed / "files" / f"{sha}.z").write_bytes(zlib.compress(b"\0" * 50_000_000))
    st = updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    assert st["state"] == "failed" and store.current()["version"] == "t-5"


@pytest.mark.parametrize("where", ["missing-folder", "http://127.0.0.1:9/feed"])
def test_unreachable_feed_starts_the_local_version(tmp_path, where, monkeypatch):
    _feed, root, store = installed(tmp_path)
    monkeypatch.setattr(updater, "CHECK_TIMEOUT", 1)
    st = updater.update(str(root), where if where.startswith("http") else str(tmp_path / where), PUBLIC, LAUNCHER_API)
    assert st["state"] == "offline" and store.current()["version"] == "t-5"
    assert updater.update(str(root), None, PUBLIC, LAUNCHER_API)["state"] == "no_feed"


def test_release_that_needs_a_newer_launcher_is_announced_not_adopted(tmp_path):
    feed, root, store = installed(tmp_path)
    make_release(feed, 6, contents("future"), launcher_api_min=LAUNCHER_API + 1)
    st = updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    assert st["state"] == "launcher_outdated" and st["to"] == "t-6" and store.current()["version"] == "t-5"


def test_feed_can_move_and_falls_back_to_the_builtin_one(tmp_path):
    feed, root, store = installed(tmp_path)
    new_feed = tmp_path / "feed2"
    make_release(feed, 6, contents("moving"), feed=str(new_feed))
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)["state"] == "updated"
    assert store.feed_hint() == str(new_feed)
    make_release(feed, 7, contents("old place"))
    make_release(new_feed, 8, contents("new place"))
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)["to"] == "t-8"              # 教わった更新元を先に見る
    shutil.rmtree(new_feed)
    make_release(feed, 9, contents("back"))
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)["to"] == "t-9"              # 消えていたら元の更新元へ


# ---- 更新元の合言葉（APP-011） ----------------------------------------------------------------------------------

class KeyedFeedServer:
    """合言葉が合わない要求に 404 を返す、検査用の更新元。届いたヘッダを控える。`redirect_to` があれば全部そこへ回す。"""

    def __init__(self, folder, key, redirect_to=None):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        outer = self
        self.seen = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append((self.path, self.headers.get("X-MeichoSim-Key")))
                if redirect_to:
                    self.send_response(302)
                    self.send_header("Location", redirect_to + self.path)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                target = Path(folder) / self.path.lstrip("/")
                if self.headers.get("X-MeichoSim-Key") != key or not target.is_file():
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


KEY = "k" * 32


def test_feed_key_opens_a_guarded_feed_and_a_wrong_key_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "CHECK_TIMEOUT", 3)
    feed, root = tmp_path / "feed", tmp_path / "root"
    make_release(feed, 1, contents("guarded"))
    srv = KeyedFeedServer(feed, KEY)
    try:
        for bad in (None, "x" * 32):
            st = updater.update(str(root), srv.url, PUBLIC, LAUNCHER_API, feed_key=bad)
            assert st["state"] == "offline", "合言葉が無い・違うときは、届かないのと同じ扱いで手元の版のまま起動する"
            assert updater.Store(str(root)).current() is None
        st = updater.update(str(root), srv.url, PUBLIC, LAUNCHER_API, feed_key=KEY)
        assert st["state"] == "updated" and st["to"] == "t-1"
        assert all(k == KEY for _p, k in srv.seen[-4:]), "latest.json にも files/ にも合言葉を付ける"
    finally:
        srv.close()


def test_feed_key_is_not_forwarded_to_another_host_on_redirect(tmp_path, monkeypatch):
    """置き場が別のホストへ回しても、合言葉はそちらへ渡さない（urllib は放っておくとヘッダをそのまま持っていく）。"""
    monkeypatch.setattr(updater, "CHECK_TIMEOUT", 3)
    feed = tmp_path / "feed"
    make_release(feed, 1, contents("elsewhere"))
    other = KeyedFeedServer(feed, KEY)
    front = KeyedFeedServer(feed, KEY, redirect_to=other.url)
    try:
        st = updater.update(str(tmp_path / "root"), front.url, PUBLIC, LAUNCHER_API, feed_key=KEY)
        assert front.seen and front.seen[0][1] == KEY
        assert other.seen and all(k is None for _p, k in other.seen), "回された先には合言葉が届いていない"
        assert st["state"] == "offline"
    finally:
        front.close()
        other.close()


@pytest.mark.parametrize("url,key,sent", [
    ("https://example.invalid/feed", KEY, True),
    ("http://example.invalid/feed", KEY, False),          # 平文の http では送らない（途中で読まれる）
    ("http://127.0.0.1:1/feed", KEY, True),               # 自分の PC の中だけは別（検査と手元の試し）
    ("https://example.invalid/feed", "bad key\r\nX-Evil: 1", False),   # launcher.json に変な字があっても、ヘッダを壊さない
    ("https://example.invalid/feed", "short", False),
    ("https://example.invalid/feed", None, False),
    ("https://example.invalid/feed", 12345, False),
])
def test_feed_key_is_sent_only_where_it_is_safe(url, key, sent):
    assert (updater.Feed(url, key).key is not None) == sent


def test_folder_feed_ignores_the_key(tmp_path):
    feed, root = tmp_path / "feed", tmp_path / "root"
    make_release(feed, 1, contents("folder"))
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API, feed_key=KEY)["state"] == "updated"


# ---- 起動と巻き戻し ---------------------------------------------------------------------------------------------

def ask(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
        return json.loads(r.read())


def stop(child):
    if child is not None:
        child.kill()
        child.wait(10)


def test_launcher_starts_contents_from_the_version_folder(tmp_path):
    _feed, root, store = installed(tmp_path)
    port = free_port()
    child, cur, rolled = L.start(str(root), store, PUBLIC, port, str(root / "st.json"))
    try:
        assert cur["version"] == "t-5" and rolled is None
        got = ask(port)
        assert got["mark"] == "base", "開発ツリーの app ではなく、版フォルダの app.server が動いている"
        assert got["status"] == str(root / "st.json")
        assert (root / "data").is_dir()
    finally:
        stop(child)


def test_broken_new_version_rolls_back_and_is_not_fetched_again(tmp_path, monkeypatch):
    feed, root, store = installed(tmp_path)
    make_release(feed, 6, contents("bad", broken=True))
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)["state"] == "updated"
    port = free_port()
    child, cur, rolled = L.start(str(root), store, PUBLIC, port, str(root / "st.json"))
    try:
        assert rolled == "t-6" and cur["version"] == "t-5" and ask(port)["mark"] == "base"
    finally:
        stop(child)
    assert store.bad() == [6] and store.current()["version"] == "t-5"
    st = updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    assert st["state"] == "failed" and store.current()["version"] == "t-5", "起動に失敗した版を取り込み直さない"
    make_release(feed, 7, contents("fixed"))
    assert updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)["to"] == "t-7"


def test_corrupted_installation_is_detected_before_running(tmp_path):
    feed, root, store = installed(tmp_path)
    make_release(feed, 6, contents("six"))
    updater.update(str(root), str(feed), PUBLIC, LAUNCHER_API)
    target = Path(store.ver_dir("t-6")) / "engine" / "app" / "server.py"
    target.write_text(target.read_text(encoding="utf-8").replace("'six'", "'hacked'"), encoding="utf-8")
    assert store.check_installed("t-6", PUBLIC) == ["engine/app/server.py"]
    port = free_port()
    child, cur, rolled = L.start(str(root), store, PUBLIC, port, str(root / "st.json"))
    try:
        assert rolled == "t-6" and ask(port)["mark"] == "base", "書き換えられた版は動かさず、一つ前へ戻す"
    finally:
        stop(child)


def test_launcher_does_not_import_the_contents():
    """起動役が中身を import すると、固めた実行ファイルに中身が焼き込まれて更新が効かなくなる。"""
    import ast
    pkg = Path(L.__file__).parent
    for p in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for n in names:
                top = n.split(".")[0]
                assert top in sys.stdlib_module_names, f"{p.name} が標準ライブラリ以外を import している: {n}"


# ---- 公開の道具 -------------------------------------------------------------------------------------------------

@pytest.fixture
def publish(tmp_path, monkeypatch):
    engine = Path(__file__).resolve().parents[2]
    if not (engine / "scripts" / "make_dist.py").is_file():
        pytest.skip("scripts/make_dist.py が無い")
    from app.release import publish as P
    parent = tmp_path / "launcher_parent"
    shutil.copytree(engine / "app" / "mslauncher", parent / "mslauncher", ignore=shutil.ignore_patterns("__pycache__", "pubkey.txt"))
    monkeypatch.setattr(P, "LAUNCHER_PARENT", parent)
    monkeypatch.setattr(P, "KEY_DIR", tmp_path / "keys")
    return P


def test_assemble_takes_only_the_allowlist_and_passes_the_scan(publish, tmp_path):
    tree = tmp_path / "tree"
    files = publish.assemble(tree)
    assert "app/server.py" in files and "app/core/game.py" in files and "app/static/index.html" in files
    assert "meicho/engine.py" in files and any(f.startswith("results/models/") for f in files)
    for f in files:
        assert not f.startswith(("app/tests/", "app/release/", "app/mslauncher/")) and not f.endswith(".md"), f
    assert publish.scan(tree) == []
    (tree / "engine" / "app" / "static" / "card.png").write_bytes(b"\x89PNG")
    (tree / "engine" / "rules_draft.md").write_text("内部文書", encoding="utf-8")
    problems = publish.scan(tree)
    assert any("card.png" in p for p in problems) and any("rules_draft" in p for p in problems), "走査を通らない中身は公開できない（R-UPD-7）"


def test_release_command_end_to_end(publish, tmp_path, capsys):
    pytest.importorskip("aiohttp")
    feed = tmp_path / "feed"
    assert publish.main(["init", "--feed-dir", str(feed)]) == 0
    assert publish.main(["release", "--notes", "一回目"]) == 0
    public = M.parse_public(publish.pubkey_path().read_text(encoding="utf-8"))
    m1, _t, _s = M.open_envelope((feed / "latest.json").read_bytes(), public)
    assert m1["seq"] == 1 and m1["notes"] == "一回目" and m1["rules_version"].startswith("v")
    assert "OK" in capsys.readouterr().out
    assert publish.main(["release", "--notes", "変更なし", "--no-smoke"]) == 0
    assert M.open_envelope((feed / "latest.json").read_bytes(), public)[0]["seq"] == 1, "中身が同じなら公開しない"
    assert publish.main(["release", "--notes", "二回目", "--no-smoke", "--force"]) == 0
    m2, _t, _s = M.open_envelope((feed / "latest.json").read_bytes(), public)
    assert m2["seq"] == 2 and [h["notes"] for h in m2["history"]] == ["二回目", "一回目"]

    root = tmp_path / "root"                                   # 公開したものを、起動役の手順で取り込める
    assert updater.update(str(root), str(feed), public, LAUNCHER_API)["state"] == "updated"
    assert updater.Store(str(root)).check_installed(m2["version"], public) == []


def test_release_refuses_a_key_that_does_not_match_the_launcher(publish, tmp_path):
    assert publish.main(["init", "--feed-dir", str(tmp_path / "feed")]) == 0
    (publish.KEY_DIR / "signing_key.txt").write_text(("11" * 32) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        publish.main(["release", "--notes", "x", "--no-smoke"])


def test_init_remembers_a_feed_key_and_the_launcher_config_carries_it(publish, tmp_path, capsys):
    assert publish.main(["init", "--feed-dir", str(tmp_path / "feed"), "--feed-key", "new"]) == 0
    key = publish.load_config()["feed_key"]
    assert updater.Feed("https://example.invalid/f", key).key == key, "道具が作った合言葉は、起動役が送れる形をしている"
    assert publish.launcher_config("https://example.invalid/f", publish.load_config()) == \
        {"feed": "https://example.invalid/f", "launcher_api": LAUNCHER_API, "feed_key": key}
    assert "feed_key" not in publish.launcher_config("https://example.invalid/f", {})
    assert publish.main(["init", "--feed-key", "短い"]) == 1 and publish.load_config()["feed_key"] == key
    capsys.readouterr()
    publish.launcher_config("http://example.invalid/f", publish.load_config())
    assert "https ではない" in capsys.readouterr().out


def test_clearing_the_launcher_out_folder_survives_a_stubborn_windows_folder(publish, tmp_path, monkeypatch):
    """Windows では、消した直後のフォルダを別のプログラム（ウイルス対策・検索の索引・開いたままのエクスプローラー）が
    つかんでいて rmdir が「アクセスが拒否されました」になることがある（2026-09-22 にマスターの PC で起きた）。
    少し待ってやり直す。だめでも**目印を最後まで残す**（目印が先に消えると、次の実行が「--out が空でない」で進めなくなる）。"""
    out = tmp_path / "out"
    (out / "src" / "mslauncher").mkdir(parents=True)
    (out / "src" / "mslauncher" / "main.py").write_text("x", encoding="utf-8")
    (out / "dist").mkdir()
    mark = out / ".meichosim_launcher_out"
    mark.write_text("m", encoding="utf-8")
    monkeypatch.setattr(publish, "RMTREE_WAIT", 0.01)
    real, calls = os.rmdir, {"n": 0}

    def flaky(path, *a, **k):
        if str(path).endswith("mslauncher") and calls["n"] < 2:
            calls["n"] += 1
            raise PermissionError(5, "アクセスが拒否されました。", str(path))
        return real(path, *a, **k)
    monkeypatch.setattr(os, "rmdir", flaky)
    publish.clear_out(out, mark)
    assert calls["n"] == 2 and sorted(p.name for p in out.iterdir()) == [mark.name], "2 回はじかれても、待ってやり直して消しきる"

    (out / "src" / "mslauncher").mkdir(parents=True)
    monkeypatch.setattr(os, "rmdir", lambda path, *a, **k: (_ for _ in ()).throw(PermissionError(5, "拒否", str(path))))
    with pytest.raises(SystemExit) as e:
        publish.clear_out(out, mark)
    assert "mslauncher" in str(e.value) and mark.exists(), "消せなかったときは、どこが消せないかを言い、目印は残す"


def test_launcher_out_is_recognised_without_the_mark_only_by_its_own_names(publish, tmp_path):
    out = tmp_path / "out"
    (out / "src").mkdir(parents=True)
    (out / "work").mkdir()
    (out / "MeichoSim_launcher1_2026.09.21-2.zip").write_bytes(b"z")
    assert publish.looks_like_launcher_out(out)
    (out / "大事な書類.txt").write_text("x", encoding="utf-8")
    assert not publish.looks_like_launcher_out(out), "知らない名前が 1 つでもあれば、消さない"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not publish.looks_like_launcher_out(empty)

