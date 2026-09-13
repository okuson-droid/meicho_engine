"""配布版の組み立て（D-074・案 B: 知人に配る Windows 実行ファイル）。

## 何をするか

開発ツリーから **allowlist に載っているものだけ**を `build/dist_src/` に写し、
配布モードのマーカー `dist.json`・起動口 `run_app.py`・説明書・PyInstaller の設定を置く。
続けて、権利物（実カード画像・公式カード文の転記・マスターの棋譜・内部文書）が
入っていないことを機械で検査し、最後に煙テスト（AI 同士 1 局＋サーバ応答）を回す。

    python3 scripts/make_dist.py --smoke            # 組み立て → 検査 → 煙テスト
    python3 scripts/make_dist.py --smoke --zip      # さらに zip に固める（案 A 用）
    python3 scripts/make_dist.py --smoke --exe      # 案 B: PyInstaller で実行ファイル → その煙テスト → 配る zip
    （実行ファイルは**配る OS で**作る。Windows 向けはマスターの Windows PC で回す。
      手順は HANDOFF_20260909_DIST.md。Linux の作業環境で --exe を回すと Linux 版ができる）

## 守ること

- **手で選ばない。** 入れるものは `ALLOW` に列挙し、それ以外は構造的に入らない。
  配り直すたびに同じ検査が走る。
- **権利物は名前で弾く。** 画像の拡張子・`cards_structured`・`human_games`・`.jsonl`・
  内部文書（`*.md`・`decisions.md`・`rules_draft*`）は、どこにあっても失敗にする。
- **公式文の転記の印 `■【` が 1 か所でもあれば失敗**にする（`cards_structured` の書式）。
  短い引用（`カードテキスト「…」`）は失敗にせず警告として数え、報告に載せる。
- ルールにも AI にも触らない。配るモデルは `experiments/champion.py` から引く（一元化・D-058）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(_HERE, ".."))
TEMPLATES = os.path.join(_HERE, "dist_templates")

sys.path.insert(0, ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "experiments"))

# 入れるもの（engine/ からの相対パスの glob）。**ここに無いものは入らない。**
ALLOW = (
    "meicho/*.py",
    "webapp/*.py",
    "webapp/static/*",
    "experiments/registry.py",
    "experiments/champion.py",
    "experiments/arena.py",
    "decklists/*.json",
)

# どこにあっても失敗にするもの（組み立て結果の走査に使う）
FORBIDDEN_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".jsonl", ".bin", ".pyd", ".whl")
FORBIDDEN_NAME_PATTERNS = ("cards_structured*", "decisions.md", "rules_draft*", "*.md", "HANDOFF_*", "*_NOTES*")
FORBIDDEN_DIRS = ("human_games", "tests", "cards", "__pycache__", "rust", "datasets", "records")
OFFICIAL_TEXT_MARK = re.compile("■【")            # cards_structured の書式（公式文の転記の印）
QUOTE_MARK = re.compile("カードテキスト「")          # 短い引用（警告にとどめる）
TEXT_EXT = (".py", ".js", ".html", ".css", ".json", ".txt", ".spec", ".csv")


# 子プロセスの日本語出力を Windows の cp932 に左右されずに受け取る
_UTF8 = {"encoding": "utf-8", "errors": "replace",
         "env": dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")}


def champion_models() -> list:
    """配るモデル = champion の定義が指すファイル（全プール）。手で列挙しない。"""
    from champion import CHAMPIONS
    out = []
    for kw in CHAMPIONS.values():
        for key in ("value_net", "opp_policy_net", "policy_net"):
            if kw.get(key) and kw[key] not in out:
                out.append(kw[key])
    return out


def default_dist_info(name: str = "対決シミュレータ（非公式）", version: str | None = None,
                      author: str = "") -> dict:
    """`dist.json` の既定。相手の allowlist は「候補」「遅い旧 champion」を外す。"""
    from webapp import agents
    ops = [k for k, v in agents.OPPONENTS.items()
           if not any(w in v["label"] for w in ("候補", "不採用", "未測定", "倍遅い"))]
    if agents.DEFAULT_OPPONENT not in ops:
        ops.insert(0, agents.DEFAULT_OPPONENT)
    # 表示名: 開発用の語（champion・Elo・SD001専用）を知人向けに言い換える。登録名は変えない
    labels = {
        agents.DEFAULT_OPPONENT: "最強 AI（先読み＋学習した評価）",
        "planner_vb3cps": "強い AI（先読み＋学習した評価・一つ前の版）",
        "planner_vb3": "強い AI（先読み＋学習した評価・旧版）",
        "planner_pi": "先読み AI（相手モデル入り）",
        "planner_lh": "先読み AI（長い地平）",
        "planner": "先読み AI（学習なし）",
        "mcts160": "モンテカルロ木探索 AI",
        "greedy": "1 手読み AI",
        "heuristic": "ルール AI（弱い）",
        "random": "ランダム",
    }
    return {
        "name": name,
        "version": version or _dt.date.today().isoformat(),
        "notice": ("非公式のファンツールです。UCP・KURO GAMES とは関係がなく、承認も受けていません。"
                   "無償・個人利用のみ。再配布はしないでください。"),
        "credits": "『鳴潮』© KURO GAMES ALL RIGHTS RESERVED. 『鳴潮：対決』は株式会社 UCP の製品です。",
        "opponents": ops,
        "labels": {k: v for k, v in labels.items() if k in ops},
        "author": author,
        "built": _dt.datetime.now().isoformat(timespec="seconds"),
    }


def _matches_allow(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in ALLOW)


def assemble(engine_dir: str, out_dir: str, models: list, dist_info: dict) -> list:
    """allowlist で `out_dir` を組み立てる。返り値は写したファイルの絶対パス。"""
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    dst_engine = os.path.join(out_dir, "engine")
    copied = []

    for root, dirs, files in os.walk(engine_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, engine_dir).replace(os.sep, "/")
            if not _matches_allow(rel):
                continue
            dst = os.path.join(dst_engine, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(dst)

    # モデルは champion の定義から（.meta.json は学習条件の記録なので配らない）
    for m in models:
        src = os.path.join(engine_dir, "results", "models", m)
        if not os.path.isfile(src):
            raise FileNotFoundError(f"配るモデルが無い: {src}")
        dst = os.path.join(dst_engine, "results", "models", m)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)

    # 起動口・PyInstaller 設定・マーカー・説明書
    for t in ("run_app.py", "MeichoSim.spec"):
        shutil.copy2(os.path.join(TEMPLATES, t), os.path.join(out_dir, t))
        copied.append(os.path.join(out_dir, t))
    marker = os.path.join(out_dir, "dist.json")
    with open(marker, "w", encoding="utf-8") as fp:
        json.dump(dist_info, fp, ensure_ascii=False, indent=1)
    copied.append(marker)
    with open(os.path.join(TEMPLATES, "README_配布.txt"), encoding="utf-8") as fp:
        readme = fp.read()
    readme = readme.format(name=dist_info.get("name", ""), version=dist_info.get("version", ""),
                           author=dist_info.get("author", ""), built=dist_info.get("built", ""))
    rp = os.path.join(out_dir, "README_配布.txt")
    with open(rp, "w", encoding="utf-8") as fp:
        fp.write(readme)
    copied.append(rp)
    return copied


# 固めた実行ファイルのフォルダ（`_internal/` に numpy 等が入る）を走査するときに許すもの
_BINARY_OK_EXT = (".pyd", ".so", ".dll", ".whl", ".bin")
_BINARY_OK_NAMES = ("*.md",)          # 同梱ライブラリの LICENSE.md 等


def verify(out_dir: str, binary_ok: bool = False) -> list:
    """組み立て結果を走査し、権利物・内部文書・公式文の転記があれば問題として返す。空なら合格。

    `binary_ok=True` は固めた実行ファイルのフォルダ用: 同梱ライブラリの `.pyd`/`.so`/`.dll` と
    ライブラリ付属の `*.md` は許す。**画像・棋譜・転記・内部文書の禁止は変わらない。**
    """
    problems = []
    for root, dirs, files in os.walk(out_dir):
        for d in list(dirs):
            if d in FORBIDDEN_DIRS:
                problems.append(f"禁止フォルダ: {os.path.relpath(os.path.join(root, d), out_dir)}")
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, out_dir).replace(os.sep, "/")
            low = f.lower()
            if low.endswith(FORBIDDEN_EXT) and not (binary_ok and low.endswith(_BINARY_OK_EXT)):
                problems.append(f"禁止の拡張子: {rel}")
            if any(fnmatch.fnmatch(f, pat) for pat in FORBIDDEN_NAME_PATTERNS
                   if not (binary_ok and pat in _BINARY_OK_NAMES)):
                problems.append(f"禁止の名前: {rel}")
            if low.endswith(TEXT_EXT):
                try:
                    with open(p, encoding="utf-8") as fp:
                        text = fp.read()
                except UnicodeDecodeError:
                    problems.append(f"UTF-8 で読めないテキスト: {rel}")
                    continue
                if OFFICIAL_TEXT_MARK.search(text):
                    problems.append(f"公式カード文の転記の印（■【）: {rel}")
    return problems


def warnings(out_dir: str) -> list:
    """失敗にはしないが報告に載せるもの（短い引用など）。"""
    out = []
    for root, _dirs, files in os.walk(out_dir):
        for f in files:
            if not f.lower().endswith(TEXT_EXT):
                continue
            p = os.path.join(root, f)
            with open(p, encoding="utf-8", errors="replace") as fp:
                for i, line in enumerate(fp, 1):
                    if QUOTE_MARK.search(line):
                        out.append(f"{os.path.relpath(p, out_dir)}:{i}: カード文の短い引用 → {line.strip()[:60]}")
    return out


def manifest(out_dir: str) -> str:
    """入っているものの一覧（sha256 つき）。配布物と一緒に残す。"""
    lines = []
    total = 0
    for root, _dirs, files in os.walk(out_dir):
        for f in sorted(files):
            if f == "MANIFEST.txt":
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, out_dir).replace(os.sep, "/")
            with open(p, "rb") as fp:
                h = hashlib.sha256(fp.read()).hexdigest()[:16]
            n = os.path.getsize(p)
            total += n
            lines.append(f"{h}  {n:>9}  {rel}")
    lines.sort(key=lambda s: s.split("  ", 2)[2])
    text = "\n".join(lines) + f"\n\n合計 {len(lines)} ファイル / {total:,} バイト\n"
    with open(os.path.join(out_dir, "MANIFEST.txt"), "w", encoding="utf-8") as fp:
        fp.write(text)
    return text


def smoke(out_dir: str) -> int:
    """組み立てたフォルダの `run_app.py --selfcheck` を別プロセスで回す。"""
    r = subprocess.run([sys.executable, os.path.join(out_dir, "run_app.py"), "--selfcheck"],
                       cwd=out_dir, capture_output=True, text=True, timeout=600, **_UTF8)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def build_exe(out_dir: str) -> str:
    """組み立てフォルダの中で PyInstaller を回し、実行ファイルの隣にマーカーと説明書を置く。

    返り値は配るフォルダ（`<out_dir>/dist/MeichoSim`）。**マーカー `dist.json` は
    `_internal/` ではなく実行ファイルの隣**に要る（`webapp/distribution.py` の `app_root`）。
    """
    spec = os.path.join(out_dir, "MeichoSim.spec")
    r = subprocess.run([sys.executable, "-m", "PyInstaller", spec, "--noconfirm", "--log-level", "WARN"],
                       cwd=out_dir, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"PyInstaller が失敗した（終了コード {r.returncode}）")
    app = os.path.join(out_dir, "dist", "MeichoSim")
    for f in ("dist.json", "README_配布.txt", "MANIFEST.txt"):
        shutil.copy2(os.path.join(out_dir, f), os.path.join(app, f))
    return app


def smoke_exe(app_dir: str) -> int:
    """固めた実行ファイルの `--selfcheck`。"""
    exe = os.path.join(app_dir, "MeichoSim.exe" if os.name == "nt" else "MeichoSim")
    r = subprocess.run([exe, "--selfcheck"], cwd=app_dir, capture_output=True, text=True, timeout=600, **_UTF8)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def make_zip(out_dir: str, zip_path: str) -> str:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(out_dir):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.join(os.path.basename(out_dir), os.path.relpath(p, out_dir)))
    return zip_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ENGINE, "build", "dist_src"))
    ap.add_argument("--name", default="対決シミュレータ（非公式）")
    ap.add_argument("--version", default=None, help="既定は今日の日付")
    ap.add_argument("--author", default="")
    ap.add_argument("--smoke", action="store_true", help="組み立て後に煙テストを回す")
    ap.add_argument("--zip", action="store_true", help="組み立てフォルダを zip にも固める（案 A 用）")
    ap.add_argument("--exe", action="store_true",
                    help="PyInstaller で実行ファイルにし（案 B）、その --selfcheck と zip まで行う")
    a = ap.parse_args(argv)

    info = default_dist_info(a.name, a.version, a.author)
    models = champion_models()
    print(f"組み立て先: {a.out}")
    print(f"配るモデル: {models}")
    print(f"相手の allowlist: {info['opponents']}")
    files = assemble(ENGINE, a.out, models, info)
    print(f"写したファイル: {len(files)}")

    problems = verify(a.out)
    for w in warnings(a.out):
        print(f"警告: {w}")
    if problems:
        for p in problems:
            print(f"NG: {p}")
        print("組み立てを失敗にした（権利物または内部文書が入っている）。配らないこと。")
        return 1
    print("検査: 合格（画像・公式文の転記・棋譜・内部文書は入っていない）")
    text = manifest(a.out)
    print(text.splitlines()[-1])

    if a.smoke:
        rc = smoke(a.out)
        if rc != 0:
            print("煙テスト: NG")
            return rc
        print("煙テスト: OK")
    if a.zip:
        zp = make_zip(a.out, a.out.rstrip(os.sep) + ".zip")
        print(f"zip: {zp}")
    if a.exe:
        app = build_exe(a.out)
        print(f"実行ファイル: {app}")
        rc = smoke_exe(app)
        if rc != 0:
            print("実行ファイルの煙テスト: NG")
            return rc
        print("実行ファイルの煙テスト: OK")
        # 煙テストが作った __pycache__ と記録を消してから、固めたフォルダをもう一度検査して zip にする
        for root, dirs, _files in os.walk(app):
            for d in list(dirs):
                if d == "__pycache__":
                    shutil.rmtree(os.path.join(root, d))
                    dirs.remove(d)
        if os.path.isdir(os.path.join(app, "results")):
            shutil.rmtree(os.path.join(app, "results"))
        problems = verify(app, binary_ok=True)
        if problems:
            for p in problems:
                print(f"NG: {p}")
            print("固めたフォルダに権利物または内部文書が入っている。配らないこと。")
            return 1
        print("固めたフォルダの検査: 合格（画像・公式文の転記・棋譜・内部文書は入っていない）")
        zp = make_zip(app, os.path.join(a.out, "dist", f"MeichoSim_{info['version']}.zip"))
        print(f"配る zip: {zp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
