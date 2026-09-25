"""更新の目録（マニフェスト）と署名の検証（要件 R-UPD-4）。標準ライブラリだけ。

## 形

更新元に置くのは 2 種類だけである。

    latest.json          {"manifest": "<目録の JSON 文字列>", "sig": "<署名 64 バイトの 16 進>"}
    files/<sha256>.z     ファイルの中身（zlib で圧縮）。名前は圧縮前の中身の sha256

目録と署名を 1 つのファイルに入れるのは、置き場がただの静的ファイル置き場でも、
「目録だけ新しく署名は古い」という半端な瞬間を作らないためである。
署名は**目録の文字列そのもの（UTF-8 のバイト列）**にかける。JSON を組み直して比べることはしない。

    目録 = {"format": 1, "version": "2026.09.21-3", "seq": 3, "built": "...",
            "launcher_api_min": 1, "protocol": 1, "rules_version": "v0.9", "cards_version": "…",
            "notes": "この版の変更点", "history": [{"version", "seq", "built", "notes"}, …],
            "feed": "（任意）次回から見に行く更新元", "files": {"engine/app/server.py": {"sha256": …, "size": …}, …}}

- `seq` は公開のたびに 1 増える整数。**今より大きい seq しか取り込まない**ので、
  正しく署名された古い目録を送りつけて版を戻す攻撃が通らない。
- ファイルの道筋は相対・`/` 区切りで、`..` や絶対の道筋、ドライブ名を含むものは目録ごと捨てる。
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from . import ed25519

FORMAT = 1
MAX_MANIFEST_BYTES = 2_000_000
MAX_FILE_BYTES = 200_000_000
MAX_FILES = 5000
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SEG_RE = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]+$")


class BadManifest(Exception):
    """目録か署名が受け取れない。取り込みをやめて手元の版で起動する（R-UPD-3）。"""


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(rel: str) -> bool:
    """目録の道筋として受け取れるか。版フォルダの外へ書かせない。"""
    if not isinstance(rel, str) or not rel or len(rel) > 300 or rel.startswith("/") or rel.endswith("/"):
        return False
    segs = rel.split("/")
    return all(s not in ("", ".", "..") and _SEG_RE.match(s) and not s.endswith((" ", ".")) for s in segs)


def check(m: dict) -> dict:
    """目録の形を確かめる。おかしければ BadManifest。"""
    if not isinstance(m, dict) or m.get("format") != FORMAT:
        raise BadManifest("目録の形式が違う")
    if not isinstance(m.get("version"), str) or not _VERSION_RE.match(m["version"]):
        raise BadManifest("版の名前が受け取れない")
    if not isinstance(m.get("seq"), int) or isinstance(m["seq"], bool) or m["seq"] < 1:
        raise BadManifest("seq が受け取れない")
    if not isinstance(m.get("launcher_api_min", 1), int):
        raise BadManifest("launcher_api_min が受け取れない")
    files = m.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise BadManifest("ファイルの一覧が受け取れない")
    seen = set()
    for rel, meta in files.items():
        if not safe_rel(rel):
            raise BadManifest(f"道筋が受け取れない: {rel!r}")
        low = rel.lower()                      # Windows は大文字小文字を区別しない。重なる道筋は拒む
        if low in seen:
            raise BadManifest(f"道筋が重なっている: {rel!r}")
        seen.add(low)
        if (not isinstance(meta, dict) or not isinstance(meta.get("sha256"), str) or not _SHA_RE.match(meta["sha256"])
                or not isinstance(meta.get("size"), int) or not 0 <= meta["size"] <= MAX_FILE_BYTES):
            raise BadManifest(f"ファイルの記載が受け取れない: {rel!r}")
    return m


def open_envelope(raw: bytes, public: bytes) -> tuple:
    """`latest.json` の中身から、署名を確かめた目録を取り出す。返り値は (目録, 目録の文字列, 署名の16進)。"""
    if len(raw) > MAX_MANIFEST_BYTES:
        raise BadManifest("目録が大きすぎる")
    try:
        env = json.loads(raw.decode("utf-8"))
        text, sig_hex = env["manifest"], env["sig"]
        sig = bytes.fromhex(sig_hex)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
        raise BadManifest(f"latest.json が読めない: {e}") from None
    if not isinstance(text, str):
        raise BadManifest("latest.json が読めない")
    if not ed25519.verify(public, text.encode("utf-8"), sig):
        raise BadManifest("署名が合わない")
    try:
        m = json.loads(text)
    except ValueError as e:
        raise BadManifest(f"目録が読めない: {e}") from None
    return check(m), text, sig_hex


def seal(m: dict, secret: bytes) -> bytes:
    """目録に署名して `latest.json` の中身を作る（公開の道具が使う）。"""
    check(m)
    text = json.dumps(m, ensure_ascii=False, sort_keys=True, indent=1)
    sig = ed25519.sign(secret, text.encode("utf-8"))
    return json.dumps({"manifest": text, "sig": sig.hex()}, ensure_ascii=False).encode("utf-8")


def verify_tree(ver_dir: str, m: dict) -> list:
    """版フォルダが目録どおりか。合わないものを返す（空なら合格）。目録に無いファイルは数えない
    （`__pycache__` は実行すれば増える）が、**目録にあるものは 1 バイトも違ってはならない**。"""
    bad = []
    for rel, meta in m["files"].items():
        p = os.path.join(ver_dir, *rel.split("/"))
        try:
            if os.path.getsize(p) != meta["size"] or sha256_file(p) != meta["sha256"]:
                bad.append(rel)
        except OSError:
            bad.append(rel)
    return bad


def parse_public(text: str) -> bytes:
    """公開鍵ファイル（16 進 64 桁。`#` の行は注釈）を読む。"""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key = bytes.fromhex(line)
            if len(key) != 32:
                break
            return key
    raise ValueError("公開鍵が読めない")
