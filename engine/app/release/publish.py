"""公開の道具（要件 R-UPD-7・R-UPD-8、APP-010）。マスターの PC で、`engine/` を作業フォルダにして使う。

    py -3.11 -m app.release.publish init --feed-dir C:\\meicho_dist\\feed --feed-url https://…   # 最初の 1 回。鍵を作り、置き場を覚える
    py -3.11 -m app.release.publish release --notes "変更点を 1 行で"                            # 中身の公開。毎回これ 1 つ
    py -3.11 -m app.release.publish launcher --out C:\\meicho_dist\\launcher                      # 起動役（実行ファイル）を作る。めったにやらない

## `release` がやること（1 回の操作で最後まで。どこかで落ちたら公開しない）

1. **組み立て**: allowlist に載っているものだけを作業フォルダに写す。エンジン側の一覧は `scripts/make_dist.py` の
   `ALLOW` と `champion_models()` を**そのまま読む**（写しを持たない・APP-002）。アプリ側の一覧はこのファイルの `APP_ALLOW`。
2. **走査**: `scripts/make_dist.py` の `verify` をかける（画像・公式文の転記・棋譜・内部文書。R-LAW-1）。
3. **署名**: 目録（全ファイルの sha256）を作り、マスターの秘密鍵で署名する。
4. **煙テスト**: 配布版と同じ置き方に並べ、**起動役の経路で**（署名の検証 → 目録との突き合わせ → 子プロセス）
   `app/selfcheck.py` を回す。
5. **配置**: 更新元のフォルダに、無い中身だけを `files/<sha256>.z` として足し、最後に `latest.json` を差し替える。
   `--after`（または init で覚えさせた命令）があれば、続けて実行する（置き場へのアップロード）。

## 更新元の合言葉（APP-011）

`init --feed-key new` で合言葉を作り、`~/.meichosim/publish.json` に覚える。`launcher` がそれを `launcher.json` の
`feed_key` に書き、起動役は要求ごとにヘッダ `X-MeichoSim-Key` で送る。置き場の側（`release/feed_host/`）には同じ値を
秘密の設定 `FEED_KEY` として入れる。**暗号的な守りではない**（起動役を持つ人は読める）。守るのは「URL だけが漏れたときに、
起動役を持たない人が中身を取れない」ことまでである。合言葉を替えるときは、置き場の `FEED_KEY` と、配った全員の
`launcher.json` を一緒に替える（`launcher.json` は実行ファイルの外にあるので、起動役を固め直さなくてよい）。

## 鍵

秘密鍵は `~/.meichosim/signing_key.txt`（**リポジトリの外・OneDrive の外**）。公開鍵は `app/mslauncher/pubkey.txt` で、
起動役に焼き込まれる。秘密鍵を失うと、配った起動役へ更新を届けられなくなる（起動役から配り直しになる）。
秘密鍵が漏れると、知人の PC で動くプログラムを他人が差し替えられる。どちらも台帳 APP-010 に書いた。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ENGINE = APP.parent
sys.path.insert(0, str(ENGINE / "scripts"))

from app.mslauncher import LAUNCHER_API, ed25519, updater  # noqa: E402
from app.mslauncher import manifest as M  # noqa: E402

KEY_DIR = Path.home() / ".meichosim"
LAUNCHER_PARENT = APP        # `mslauncher/` の親。検査は写しに差し替える（本物の pubkey.txt を書き換えない）
RMTREE_TRIES = 8             # Windows で消せないフォルダに当たったときのやり直しの回数
RMTREE_WAIT = 0.5            # その間隔（秒）
KEEP_MANIFESTS = 3           # 更新元に残す過去の目録の数。それより古い版だけが使う中身は消す

# アプリ側で配るもの（engine/ からの相対）。**ここに無いものは入らない。** 検査（tests）・台帳（*.md）・
# 公開の道具（release）・起動役（mslauncher。実行ファイルの側に入る）は入れない。
APP_ALLOW = ("app/__init__.py", "app/server.py", "app/bot.py", "app/selfcheck.py", "app/core/*.py", "app/static/**")

_UTF8 = {"encoding": "utf-8", "errors": "replace"}


def pubkey_path() -> Path:
    return LAUNCHER_PARENT / "mslauncher" / "pubkey.txt"


def _make_dist():
    import make_dist                      # エンジンの持ち場。読むだけ（LANES.md）
    return make_dist


def _app_allowed(rel: str) -> bool:
    for pat in APP_ALLOW:
        if pat.endswith("/**"):
            if rel.startswith(pat[:-2]):
                return True
        elif "/" in rel and fnmatch.fnmatch(rel.rsplit("/", 1)[1], pat.rsplit("/", 1)[1]) \
                and rel.rsplit("/", 1)[0] == pat.rsplit("/", 1)[0]:
            return True
    return False


def assemble(out: Path) -> list:
    """`out/engine/…` を組み立てる。返り値は写した相対パス。"""
    md = _make_dist()
    copied = []
    for root, dirs, files in os.walk(ENGINE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache", "build", "dist", ".git")]
        for f in files:
            src = Path(root) / f
            rel = src.relative_to(ENGINE).as_posix()
            if rel.startswith("app/"):
                ok = _app_allowed(rel)
            else:
                ok = md._matches_allow(rel)
            if ok:
                copied.append(rel)
    for m in md.champion_models():
        rel = f"results/models/{m}"
        if not (ENGINE / rel).is_file():
            raise FileNotFoundError(f"配るモデルが無い: {rel}")
        copied.append(rel)
    for rel in copied:
        dst = out / "engine" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ENGINE / rel, dst)
    return sorted(set(copied))


def scan(path: Path, binary_ok: bool = False) -> list:
    md = _make_dist()
    for w in md.warnings(str(path)) if not binary_ok else []:
        print(f"警告: {w}")
    return md.verify(str(path), binary_ok=binary_ok)


def load_secret() -> bytes:
    p = KEY_DIR / "signing_key.txt"
    if not p.is_file():
        raise SystemExit(f"秘密鍵が無い: {p}\n最初に `py -3.11 -m app.release.publish init …` を実行する。")
    secret = M.parse_public(p.read_text(encoding="utf-8"))          # 形は公開鍵と同じ（16 進 64 桁）
    if not pubkey_path().is_file() or M.parse_public(pubkey_path().read_text(encoding="utf-8")) != ed25519.public_key(secret):
        raise SystemExit("秘密鍵と app/mslauncher/pubkey.txt が対になっていない。配った起動役が持つ公開鍵と同じ鍵で署名しないと、更新は届かない。")
    return secret


def load_config() -> dict:
    return updater._read_json(str(KEY_DIR / "publish.json"), {}) or {}


def rmtree_patiently(path: Path) -> None:
    """フォルダを消す。Windows では、消した直後のファイルを別のプログラム（ウイルス対策・検索の索引・開いたままの
    エクスプローラーや cmd）がつかんでいて「アクセスが拒否されました」になることがあるので、少し待ってやり直す。
    読み取り専用の印が付いたファイルは、印を外して消す。"""
    def unlock(fn, p, _exc):
        os.chmod(p, 0o700)
        fn(p)
    last = None
    for _ in range(RMTREE_TRIES):
        try:
            shutil.rmtree(path, onerror=unlock)
            return
        except FileNotFoundError:
            return
        except OSError as e:
            last = e
            time.sleep(RMTREE_WAIT)
    raise SystemExit(f"消せない: {getattr(last, 'filename', None) or path}\n（{last}）\n"
                     "このフォルダを開いているエクスプローラーや黒い窓（cmd・MeichoSim.exe）を閉じてから、同じ行をもう一度打つ。")


def looks_like_launcher_out(out: Path) -> bool:
    """目印が無くても、中にあるのがこの道具の出力の名前だけなら、前回の出力とみなす。
    （目印を先に消してから途中で止まった古い版の後始末。2026-09-22 にマスターの PC で起きた）"""
    names = [p.name for p in out.iterdir()]
    return bool(names) and all(n in ("src", "work", "dist", ".meichosim_launcher_out")
                               or fnmatch.fnmatch(n, "MeichoSim_launcher*.zip") for n in names)


def clear_out(out: Path, mark: Path) -> None:
    """`launcher --out` の前回の出力を消す。**目印は消さない**——途中で消せないものに当たっても、
    次の実行が「この道具が作ったフォルダだ」と分かって続きから消せる。"""
    for p in sorted(out.iterdir()):
        if p == mark:
            continue
        if p.is_dir() and not p.is_symlink():
            rmtree_patiently(p)
        else:
            p.unlink()


def launcher_config(feed_url: str, cfg: dict) -> dict:
    """配る `launcher.json` の中身。合言葉は、覚えていて形が正しいときだけ入れる。"""
    out = {"feed": feed_url, "launcher_api": LAUNCHER_API}
    key = cfg.get("feed_key")
    if key:
        if not updater._KEY_OK.fullmatch(str(key)):
            raise SystemExit("覚えている合言葉の形がおかしい（英数字と - _ で 16〜128 字）。`init --feed-key new` で作り直す。")
        out["feed_key"] = key
        if feed_url and updater.Feed(feed_url, key).key is None and updater.Feed(feed_url).remote:
            print("注意: 更新元が https ではないので、起動役は合言葉を送らない（平文では送らない決まり）。")
    return out


def previous_manifest(feed_dir: Path, public: bytes):
    p = feed_dir / "latest.json"
    if not p.is_file():
        return None
    m, _t, _s = M.open_envelope(p.read_bytes(), public)
    return m


def build_manifest(tree: Path, prev, notes: str, version, launcher_api_min: int, feed_url) -> dict:
    from app.core import persist
    from app.core.protocol import PROTOCOL_VERSION
    seq = (prev["seq"] + 1) if prev else 1
    now = _dt.datetime.now().astimezone()
    version = version or f"{now:%Y.%m.%d}-{seq}"
    files = {}
    for p in sorted(tree.rglob("*")):
        if p.is_file():
            files[p.relative_to(tree).as_posix()] = {"sha256": M.sha256_file(str(p)), "size": p.stat().st_size}
    built = now.isoformat(timespec="seconds")
    history = [{"version": version, "seq": seq, "built": built, "notes": notes}] + list((prev or {}).get("history", []))
    m = {"format": M.FORMAT, "version": version, "seq": seq, "built": built, "notes": notes, "history": history[:30],
         "launcher_api_min": launcher_api_min, "protocol": PROTOCOL_VERSION,
         "rules_version": persist.rules_version(ENGINE), "cards_version": persist.cards_version(ENGINE), "files": files}
    if feed_url:
        m["feed"] = feed_url
    return M.check(m)


def smoke(tree: Path, envelope: bytes, m: dict, work: Path) -> int:
    """配布版と同じ置き方に並べ、起動役の経路で自己検査を回す。"""
    root = work / "smoke_root"
    ver = root / "contents" / "versions" / m["version"]
    shutil.copytree(tree, ver)
    (ver / "release.json").write_bytes(envelope)
    updater._write_json(str(root / "contents" / "current.json"), {"version": m["version"], "seq": m["seq"], "previous": None})
    boot = "import sys; sys.path.insert(0, sys.argv.pop(1)); from mslauncher.main import main; sys.exit(main())"
    r = subprocess.run([sys.executable, "-c", boot, str(LAUNCHER_PARENT), "--selfcheck"], cwd=root, timeout=1800,
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1"))
    return r.returncode


def place(tree: Path, envelope: bytes, m: dict, feed_dir: Path, public: bytes) -> int:
    """更新元のフォルダへ置く。`latest.json` の差し替えが最後（それまでは前の版が配られ続ける）。"""
    (feed_dir / "files").mkdir(parents=True, exist_ok=True)
    (feed_dir / "manifests").mkdir(exist_ok=True)
    added = 0
    for rel, meta in m["files"].items():
        dst = feed_dir / "files" / f"{meta['sha256']}.z"
        if not dst.exists():
            tmp = dst.with_suffix(".tmp")
            tmp.write_bytes(zlib.compress((tree / rel).read_bytes(), 9))
            os.replace(tmp, dst)
            added += 1
    (feed_dir / "manifests" / f"{m['seq']:06d}.json").write_bytes(envelope)
    tmp = feed_dir / "latest.json.tmp"
    tmp.write_bytes(envelope)
    os.replace(tmp, feed_dir / "latest.json")
    # 古い版だけが使っていた中身を消す（直近の目録が指すものは残す）
    kept = sorted((feed_dir / "manifests").glob("*.json"))[-KEEP_MANIFESTS:]
    alive = set()
    for p in kept:
        try:
            pm, _t, _s = M.open_envelope(p.read_bytes(), public)
            alive |= {meta["sha256"] for meta in pm["files"].values()}
        except M.BadManifest:
            pass
    for p in (feed_dir / "manifests").glob("*.json"):
        if p not in kept:
            p.unlink()
    for p in (feed_dir / "files").glob("*.z"):
        if p.stem not in alive:
            p.unlink()
    return added


def cmd_init(a) -> int:
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    kp = KEY_DIR / "signing_key.txt"
    if kp.exists():
        print(f"秘密鍵はすでにある（作り直さない）: {kp}")
        secret = M.parse_public(kp.read_text(encoding="utf-8"))
    else:
        secret = ed25519.new_secret()
        kp.write_text("# MeichoSim の更新に署名する秘密鍵。誰にも渡さない。リポジトリにも OneDrive にも置かない。\n"
                      + secret.hex() + "\n", encoding="utf-8")
        try:
            os.chmod(kp, 0o600)
        except OSError:
            pass
        print(f"秘密鍵を作った: {kp}")
    pub = ed25519.public_key(secret)
    if pubkey_path().is_file() and M.parse_public(pubkey_path().read_text(encoding="utf-8")) != pub:
        print("NG: app/mslauncher/pubkey.txt が別の鍵のものになっている。配った起動役がある場合、その鍵を使い続けること。")
        return 1
    pubkey_path().write_text("# MeichoSim の更新の署名を確かめる公開鍵（Ed25519）。秘密ではない。起動役に焼き込まれる。\n"
                      + pub.hex() + "\n", encoding="utf-8", newline="\n")
    cfg = load_config()
    for k in ("feed_dir", "feed_url", "after"):
        if getattr(a, k):
            cfg[k] = getattr(a, k)
    if a.feed_key:
        key = secrets.token_urlsafe(32) if a.feed_key == "new" else a.feed_key
        if not updater._KEY_OK.fullmatch(key):
            print("NG: 合言葉は英数字と - _ で 16〜128 字にする（`--feed-key new` なら道具が作る）。")
            return 1
        if cfg.get("feed_key") and cfg["feed_key"] != key:
            print("注意: 合言葉を替えた。置き場の FEED_KEY と、配った全員の launcher.json の feed_key も同じ値に替えること。")
        cfg["feed_key"] = key
    updater._write_json(str(KEY_DIR / "publish.json"), cfg)
    print(f"公開鍵: {pub.hex()}")
    print(f"覚えた設定: {json.dumps(cfg, ensure_ascii=False)}")
    if cfg.get("feed_key"):
        print("更新元の合言葉を覚えている。置き場の秘密の設定 FEED_KEY に同じ値を入れること（手順は release/feed_host/README.md）。")
    print("秘密鍵の控えを、PC の外（USB メモリなど）に 1 つ取っておくこと。")
    return 0


def cmd_release(a) -> int:
    cfg = load_config()
    feed_dir = Path(a.feed_dir or cfg.get("feed_dir") or "")
    if not str(feed_dir) or str(feed_dir) == ".":
        raise SystemExit("更新元のフォルダが決まっていない（--feed-dir か、init で覚えさせる）")
    secret = load_secret()
    public = ed25519.public_key(secret)
    prev = previous_manifest(feed_dir, public)
    with tempfile.TemporaryDirectory(prefix="meichosim_release_") as tmp:
        work = Path(tmp)
        tree = work / "tree"
        files = assemble(tree)
        print(f"[1/5] 組み立て: {len(files)} ファイル")
        problems = scan(tree)
        if problems:
            for p in problems:
                print(f"NG: {p}")
            print("走査を通らないので公開しない（権利物か内部文書が入っている）。")
            return 1
        print("[2/5] 走査: 合格（画像・公式文の転記・棋譜・内部文書は入っていない）")
        m = build_manifest(tree, prev, a.notes, a.version, a.launcher_api_min, a.feed_url_next)
        if prev and {k: v["sha256"] for k, v in prev["files"].items()} == {k: v["sha256"] for k, v in m["files"].items()} \
                and not a.force:
            print("前の版から中身が 1 バイトも変わっていないので公開しない（それでも出すなら --force）。")
            return 0
        envelope = M.seal(m, secret)
        print(f"[3/5] 署名: 版 {m['version']}（seq {m['seq']}）")
        if not a.no_smoke:
            if smoke(tree, envelope, m, work) != 0:
                print("煙テストが落ちたので公開しない。")
                return 1
        print("[4/5] 煙テスト: " + ("省略" if a.no_smoke else "OK"))
        added = place(tree, envelope, m, feed_dir, public)
        changed = [k for k, v in m["files"].items() if not prev or prev["files"].get(k, {}).get("sha256") != v["sha256"]]
        print(f"[5/5] 配置: {feed_dir}（新しい中身 {added} 個。前の版から変わったファイル {len(changed)} 個）")
    after = a.after or cfg.get("after")
    if after:
        print(f"続けて実行: {after}")
        r = subprocess.run(after, shell=True, cwd=feed_dir)
        if r.returncode != 0:
            print("NG: 置き場への送り出しが失敗した。更新元のフォルダは新しい版になっているので、送り出しだけやり直せばよい。")
            return r.returncode
    print(f"公開した: 版 {m['version']}")
    return 0


def cmd_launcher(a) -> int:
    cfg = load_config()
    feed_dir = Path(a.feed_dir or cfg.get("feed_dir") or "")
    feed_url = a.feed_url or cfg.get("feed_url") or ""
    secret = load_secret()
    public = ed25519.public_key(secret)
    if not (feed_dir / "latest.json").is_file():
        raise SystemExit("先に release で中身を 1 回公開する（起動役の zip には、その時点の中身を入れて配る）。")
    out = Path(a.out).resolve()
    mark = out / ".meichosim_launcher_out"
    if ENGINE in out.parents or out == ENGINE:
        raise SystemExit("--out はリポジトリの外（OneDrive の外）にする")
    if out.exists() and any(out.iterdir()):
        if not mark.exists() and not looks_like_launcher_out(out):      # 消してよいのは、この道具が前に作ったフォルダだけ
            raise SystemExit(f"--out が空でない: {out}\n空のフォルダか、まだ無いフォルダを指定する。")
        clear_out(out, mark)
    out.mkdir(parents=True, exist_ok=True)
    mark.write_text("publish.py launcher の出力先。次に同じ --out で実行すると、中身は消して作り直される。\n", encoding="utf-8")
    src = out / "src"
    shutil.copytree(LAUNCHER_PARENT / "mslauncher", src / "mslauncher", ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("run_launcher.py", "MeichoSimLauncher.spec"):
        shutil.copyfile(APP / "release" / f, src / f)
    r = subprocess.run([sys.executable, "-m", "PyInstaller", str(src / "MeichoSimLauncher.spec"), "--noconfirm",
                        "--log-level", "WARN", "--distpath", str(out / "dist"), "--workpath", str(out / "work")], cwd=src)
    if r.returncode != 0:
        print("NG: PyInstaller が失敗した")
        return 1
    app = out / "dist" / "MeichoSim"
    updater._write_json(str(app / "launcher.json"), launcher_config(feed_url, cfg))
    readme = (APP / "release" / "README_配布.txt").read_text(encoding="utf-8")
    (app / "README_配布.txt").write_text(readme.replace("{author}", a.author), encoding="utf-8", newline="\r\n")
    st = updater.update(str(app), str(feed_dir), public, LAUNCHER_API, print)        # 起動役と同じ手順で、最初の中身を入れる
    if st["state"] != "updated":
        print(f"NG: 最初の中身を入れられない: {st}")
        return 1
    exe = app / ("MeichoSim.exe" if os.name == "nt" else "MeichoSim")
    r = subprocess.run([str(exe), "--selfcheck"], cwd=app, timeout=1800,
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
    if r.returncode != 0:
        print("NG: 実行ファイルの煙テストが落ちた")
        return 1
    print("実行ファイルの煙テスト: OK")
    for root, dirs, _f in os.walk(app):
        for d in list(dirs):
            if d == "__pycache__" or (Path(root) == app and d == "data"):
                rmtree_patiently(Path(root) / d)
                dirs.remove(d)
    for junk in ("last_update.json",):
        (app / "contents" / junk).unlink(missing_ok=True)
    problems = scan(app, binary_ok=True)
    if problems:
        for p in problems:
            print(f"NG: {p}")
        print("固めたフォルダに権利物か内部文書が入っている。配らないこと。")
        return 1
    print("固めたフォルダの走査: 合格")
    cur = updater.Store(str(app)).current()
    zp = out / f"MeichoSim_launcher{LAUNCHER_API}_{re.sub(r'[^0-9A-Za-z._-]', '_', cur['version'])}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(app.rglob("*")):
            if p.is_file():
                z.write(p, Path("MeichoSim") / p.relative_to(app))
    print(f"配る zip: {zp}")
    if not feed_url:
        print("注意: 更新元の URL が空なので、この起動役は自動更新をしない（あとから launcher.json の feed に書けば効く）。")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MeichoSim の公開の道具")
    for stream in (sys.stdout, sys.stderr):             # Windows の端末（cp932）で表せない字があっても、表示のせいで止まらない
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="鍵を作り、更新元の置き場を覚える（最初の 1 回）")
    p.add_argument("--feed-dir")
    p.add_argument("--feed-url")
    p.add_argument("--after", help="release の最後に、更新元のフォルダで実行する命令（置き場へのアップロード）")
    p.add_argument("--feed-key", help="更新元の合言葉。`new` で道具が作る。launcher が launcher.json に書く（APP-011）")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("release", help="中身を公開する")
    p.add_argument("--notes", required=True, help="この版の変更点（設定画面の更新履歴に出る）")
    p.add_argument("--version", default=None, help="既定は 日付-seq")
    p.add_argument("--feed-dir")
    p.add_argument("--after")
    p.add_argument("--launcher-api-min", type=int, default=1,
                   help=f"この中身が求める起動役の版（今の起動役は {LAUNCHER_API}）。上げると、古い起動役は取り込まずに案内を出す")
    p.add_argument("--feed-url-next", default=None, help="更新元を引っ越すとき、次回から見に行く URL を知らせる")
    p.add_argument("--no-smoke", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_release)
    p = sub.add_parser("launcher", help="起動役（実行ファイル）を作って zip にする")
    p.add_argument("--out", required=True, help="作業と出力のフォルダ。**OneDrive の外**（例 C:\\meicho_dist\\launcher）。中身は消して作り直す")
    p.add_argument("--feed-dir")
    p.add_argument("--feed-url")
    p.add_argument("--author", default="")
    p.set_defaults(fn=cmd_launcher)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
