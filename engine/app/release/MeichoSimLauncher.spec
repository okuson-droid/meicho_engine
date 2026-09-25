# -*- mode: python ; coding: utf-8 -*-
# 起動役の PyInstaller 設定（要件 R-UPD-1・APP-010）。`app/release/publish.py launcher` が作業フォルダに写して使う。
#
# 起動役に入れるのは **Python 本体・標準ライブラリの全部・numpy・aiohttp・`mslauncher`** だけである。
# 中身（meicho・app・webapp・experiments・モデル・デッキ）は入れない。実行ファイルの外の
# `contents/versions/<版>/` に素のファイルとして置かれ、更新で入れ替わる。
#
# - 中身は固めるときに解析されないので、中身が使う標準ライブラリを PyInstaller は自分では見つけられない。
#   だから**標準ライブラリを丸ごと入れる**。将来の中身が新しい標準モジュールを使っても、起動役を配り直さずに済む。
# - numpy と aiohttp も同じ理由で、下位のモジュールをすべて入れる。
# - onedir・console=True は従来の配布版（D-074）と同じ。ウィンドウを閉じればサーバが止まる。
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))

SKIP = {"tkinter", "turtle", "turtledemo", "idlelib", "test", "lib2to3", "ensurepip", "venv", "distutils",
        "pydoc_data", "antigravity", "this", "__phello__", "__hello__", "_tkinter", "msilib"}


def _exists(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


hidden = []
for name in sorted(sys.stdlib_module_names):
    if name in SKIP or name.startswith("_test") or name.startswith("_xx") or name.startswith("xx") or not _exists(name):
        continue
    hidden.append(name)
    spec = importlib.util.find_spec(name)
    if spec.submodule_search_locations:                      # パッケージなら下位も全部
        try:
            hidden += collect_submodules(name, filter=lambda n: ".test" not in n and ".idle" not in n)
        except Exception:
            pass

_drop = (".tests", ".testing", ".f2py", ".distutils", "._pyinstaller", ".conftest")
hidden += collect_submodules("numpy", filter=lambda n: not any(d in n for d in _drop))
hidden += collect_submodules("aiohttp", filter=lambda n: "pytest_plugin" not in n and "test_utils" not in n)
for dep in ("multidict", "yarl", "frozenlist", "aiosignal", "attr", "attrs", "propcache", "aiohappyeyeballs", "idna"):
    if _exists(dep):
        hidden += collect_submodules(dep)
hidden = sorted(set(hidden))

a = Analysis(
    [os.path.join(HERE, "run_launcher.py")],
    pathex=[HERE],
    binaries=[],
    datas=[(os.path.join(HERE, "mslauncher", "pubkey.txt"), "mslauncher")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "matplotlib", "scipy", "pandas", "PIL", "tkinter", "pytest", "app", "meicho", "webapp"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MeichoSim", debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MeichoSim")
