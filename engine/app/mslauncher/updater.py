"""中身の更新（要件 R-UPD-2〜6）。標準ライブラリだけ。

## 置き場（実行ファイルの隣を根とする）

    contents/current.json            {"version", "seq", "previous": {"version", "seq"} | null}
    contents/versions/<版>/          中身。`release.json`（署名つきの目録）と `engine/…`
    contents/staging/                取り込み中の作業場。起動のたびに空にする
    contents/bad.json                起動に失敗した版の seq。同じ版を取り込み直さない
    contents/feed.json               署名つきの目録が教えてくれた、次回からの更新元（任意）
    data/                            利用者のデータ。**更新はここに触らない**（R-UPD-6）

## 順序（R-UPD-5）

1. 更新元の `latest.json` を取り、署名を確かめる。seq が今より大きくなければ何もしない。
2. `staging/<版>/` に組み立てる。今の版に同じ中身（sha256）のファイルがあれば手元から写し、
   無いものだけを更新元から取る（R-UPD-2「変わったファイルだけ」）。
3. 組み上がったフォルダ全体を目録と突き合わせる。1 つでも合わなければ捨てる。
4. `versions/<版>/` へ名前を付け替え、`current.json` を差し替える。一つ前の版は残し、それより古い版を消す。

どの段で失敗しても `current.json` は変わらないので、手元の版でそのまま起動できる（R-UPD-3）。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zlib

from . import manifest as M

CHECK_TIMEOUT = 6          # 更新の有無を確かめる待ち時間（秒）。届かないなら早く諦めて起動する
FETCH_TIMEOUT = 60         # ファイル 1 つの待ち時間


KEY_HEADER = "X-MeichoSim-Key"
_KEY_OK = re.compile(r"[A-Za-z0-9_-]{16,128}")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


class _KeepKeyHome(urllib.request.HTTPRedirectHandler):
    """置き場が別のホストへ回したら、合言葉をそちらへ持っていかない（urllib は放っておくとヘッダをそのまま写す）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            a, b = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
            if (a.scheme, a.netloc.lower()) != (b.scheme, b.netloc.lower()):
                for h in list(new.headers):
                    if h.lower() == KEY_HEADER.lower():
                        del new.headers[h]
        return new


_OPENER = urllib.request.build_opener(_KeepKeyHome)


class Feed:
    """更新元。`https://…` か、フォルダの道筋（検査用・LAN や USB で配る場合）。

    `key` は更新元の合言葉（APP-011）。`launcher.json` の `feed_key` から来て、要求ごとにヘッダ `X-MeichoSim-Key` で送る。
    **暗号的な守りではない**（起動役を持つ人は読める）。守るのは「URL だけが漏れたときに、起動役を持たない人が
    中身を取れない」ことまでで、更新の正しさは引き続き署名が守る。送るのは https のときと、自分の PC の中
    （検査・手元の試し）だけ。形のおかしい合言葉は無いものとして扱う（ヘッダを壊させない）。
    """

    def __init__(self, url: str, key=None):
        self.url = url.strip()
        self.remote = self.url.lower().startswith(("http://", "https://"))
        self.key = None
        if self.remote and isinstance(key, str) and _KEY_OK.fullmatch(key):
            parts = urllib.parse.urlsplit(self.url)
            if parts.scheme.lower() == "https" or (parts.hostname or "").lower() in _LOOPBACK:
                self.key = key

    def get(self, name: str, limit: int, timeout: float) -> bytes:
        if self.remote:
            headers = {"User-Agent": "MeichoSim-launcher", "Cache-Control": "no-cache"}
            if self.key:
                headers[KEY_HEADER] = self.key
            req = urllib.request.Request(self.url.rstrip("/") + "/" + name, headers=headers)
            with _OPENER.open(req, timeout=timeout) as r:
                data = r.read(limit + 1)
        else:
            with open(os.path.join(self.url, *name.split("/")), "rb") as f:
                data = f.read(limit + 1)
        if len(data) > limit:
            raise M.BadManifest(f"{name} が大きすぎる")
        return data


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Store:
    """`contents/` の読み書き。版の切り替えは `current.json` の差し替え 1 回で起こる。"""

    def __init__(self, root: str):
        self.root = root
        self.dir = os.path.join(root, "contents")
        self.versions = os.path.join(self.dir, "versions")
        self.staging = os.path.join(self.dir, "staging")

    def current(self) -> dict | None:
        cur = _read_json(os.path.join(self.dir, "current.json"), None)
        if isinstance(cur, dict) and isinstance(cur.get("version"), str) and isinstance(cur.get("seq"), int):
            return cur
        return None

    def ver_dir(self, version: str) -> str:
        return os.path.join(self.versions, version)

    def bad(self) -> list:
        b = _read_json(os.path.join(self.dir, "bad.json"), [])
        return [x for x in b if isinstance(x, int)] if isinstance(b, list) else []

    def feed_hint(self) -> str | None:
        d = _read_json(os.path.join(self.dir, "feed.json"), None)
        return d.get("feed") if isinstance(d, dict) and isinstance(d.get("feed"), str) and d["feed"] else None

    def load_release(self, version: str, public: bytes) -> dict:
        """手元の版の目録を、署名を確かめて読む。"""
        with open(os.path.join(self.ver_dir(version), "release.json"), "rb") as f:
            m, _text, _sig = M.open_envelope(f.read(M.MAX_MANIFEST_BYTES + 1), public)
        if m["version"] != version:
            raise M.BadManifest("フォルダの名前と目録の版が違う")
        return m

    def check_installed(self, version: str, public: bytes) -> list:
        """手元の版が壊れていないか（署名と全ファイルのハッシュ）。問題の一覧を返す。"""
        try:
            m = self.load_release(version, public)
        except (OSError, M.BadManifest) as e:
            return [f"release.json: {e}"]
        return M.verify_tree(self.ver_dir(version), m)

    def switch(self, m: dict) -> None:
        cur = self.current()
        prev = {"version": cur["version"], "seq": cur["seq"]} if cur else None
        _write_json(os.path.join(self.dir, "current.json"), {"version": m["version"], "seq": m["seq"], "previous": prev})
        keep = {m["version"]} | ({prev["version"]} if prev else set())
        for name in os.listdir(self.versions):
            if name not in keep:
                shutil.rmtree(os.path.join(self.versions, name), ignore_errors=True)

    def rollback(self) -> dict | None:
        """今の版を「起動に失敗した版」と記録し、一つ前へ戻す。戻る先が無ければ None。"""
        cur = self.current()
        if not cur:
            return None
        _write_json(os.path.join(self.dir, "bad.json"), sorted(set(self.bad()) | {cur["seq"]}))
        prev = cur.get("previous")
        if not isinstance(prev, dict) or not os.path.isdir(self.ver_dir(str(prev.get("version")))):
            return None
        new = {"version": prev["version"], "seq": prev["seq"], "previous": None}
        _write_json(os.path.join(self.dir, "current.json"), new)
        return new


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _index_by_sha(store: Store, public: bytes) -> dict:
    """今の版のファイルを sha256 で引けるようにする（目録に載っていて、実物がそのとおりのものだけ）。"""
    cur = store.current()
    if not cur:
        return {}
    try:
        m = store.load_release(cur["version"], public)
    except (OSError, M.BadManifest):
        return {}
    base = store.ver_dir(cur["version"])
    return {meta["sha256"]: os.path.join(base, *rel.split("/")) for rel, meta in m["files"].items()}


def _fetch_blob(feed: Feed, sha: str, size: int) -> bytes:
    raw = feed.get(f"files/{sha}.z", size + 4096 + size // 100, FETCH_TIMEOUT)
    d = zlib.decompressobj()
    data = d.decompress(raw, size + 1)                  # 膨らみすぎる圧縮データを展開しきらない
    if len(data) != size or d.unconsumed_tail or not d.eof:
        raise M.BadManifest(f"大きさが目録と違う: {sha[:12]}")
    return data


def update(root: str, feed_url: str | None, public: bytes, launcher_api: int, say=lambda msg: None,
           feed_key: str | None = None) -> dict:
    """更新を確かめ、あれば取り込む。**例外を外へ出さない**（更新できないことを理由に遊べなくしない・R-UPD-3）。

    返り値は設定画面に出す状態: `state` は latest / updated / offline / failed / launcher_outdated / no_feed。
    `feed_key` は更新元の合言葉（`Feed` の説明を参照）。引っ越し先の更新元（署名つきの目録が教えたもの）にも同じ合言葉を送る。
    """
    store = Store(root)
    cur = store.current()
    status = {"state": "latest", "detail": "", "checked": _now(),
              "from": cur["version"] if cur else None, "to": None}
    shutil.rmtree(store.staging, ignore_errors=True)
    urls = [u for u in dict.fromkeys((store.feed_hint(), feed_url)) if u]     # 教わった更新元が消えていたら、起動役が持つ元の更新元へ
    if not urls:
        return dict(status, state="no_feed", detail="更新元が設定されていない")
    try:
        say("更新を確かめている…")
        feed = raw = why = None
        for u in urls:
            try:
                feed = Feed(u, feed_key)
                raw = feed.get("latest.json", M.MAX_MANIFEST_BYTES, CHECK_TIMEOUT)
                break
            except (OSError, urllib.error.URLError, ValueError) as e:
                why = type(e).__name__
        if raw is None:
            return dict(status, state="offline", detail=f"更新元に届かない（{why}）")
        m, _text, _sig = M.open_envelope(raw, public)
        if cur and m["seq"] <= cur["seq"]:
            return status
        if m["seq"] in store.bad():
            return dict(status, state="failed", to=m["version"],
                        detail="この版は前回の起動に失敗したので取り込まない。次の版を待つ")
        if m.get("launcher_api_min", 1) > launcher_api:
            return dict(status, state="launcher_outdated", to=m["version"],
                        detail="新しい版はこの起動役では動かない。新しい起動役が必要")

        have = _index_by_sha(store, public)
        stage = os.path.join(store.staging, m["version"])
        os.makedirs(stage)
        files = sorted(m["files"].items())
        need = [(rel, meta) for rel, meta in files if meta["sha256"] not in have]
        total = sum(meta["size"] for _rel, meta in need)
        say(f"新しい版 {m['version']} を取り込む（{len(need)} / {len(files)} ファイル、{total / 1e6:.1f} MB）")
        done = 0
        for rel, meta in files:
            dst = os.path.join(stage, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            src = have.get(meta["sha256"])
            if src:
                shutil.copyfile(src, dst)
                continue
            data = _fetch_blob(feed, meta["sha256"], meta["size"])
            with open(dst, "wb") as f:
                f.write(data)
            done += meta["size"]
            say(f"  {done * 100 // max(total, 1):3d}%  {rel}")
        with open(os.path.join(stage, "release.json"), "wb") as f:
            f.write(raw)
        wrong = M.verify_tree(stage, m)                 # 手元から写した分も含めて、全部を目録と突き合わせる
        if wrong:
            raise M.BadManifest(f"取り込んだファイルが目録と合わない: {wrong[:3]}")
        os.makedirs(store.versions, exist_ok=True)
        final = store.ver_dir(m["version"])
        shutil.rmtree(final, ignore_errors=True)
        os.replace(stage, final)
        store.switch(m)
        if isinstance(m.get("feed"), str) and m["feed"]:
            _write_json(os.path.join(store.dir, "feed.json"), {"feed": m["feed"]})
        say(f"版 {m['version']} に更新した")
        return dict(status, state="updated", to=m["version"])
    except M.BadManifest as e:
        return dict(status, state="failed", detail=str(e))
    except Exception as e:                              # noqa: BLE001  どんな失敗でも手元の版で起動する
        return dict(status, state="failed", detail=f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(store.staging, ignore_errors=True)
