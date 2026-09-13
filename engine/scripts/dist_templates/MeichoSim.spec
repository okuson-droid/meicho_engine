# -*- mode: python ; coding: utf-8 -*-
# PyInstaller の設定（D-074・配布版）。`scripts/make_dist.py` が組み立てフォルダに置く。
#
# 使い方（組み立てフォルダの中で）:  pyinstaller MeichoSim.spec
#   → dist/MeichoSim/MeichoSim.exe と _internal/ ができる。
#
# 方針:
# - `meicho/`・`webapp/` は pathex で見つけさせ、PyZ に入れる（stdlib の依存も自動で拾われる）。
# - `experiments/`（registry・champion・arena）は **PyZ に入れず、data として `_internal/experiments/` に置く**。
#   これらは `__file__/..` を engine の根として decklists 等を探すので、PyZ に入れると
#   `_internal/arena.py` 扱いになり `_internal/../decklists` を見に行って落ちる（Linux で実測）。
#   `run_app.py` が `_internal/experiments` を sys.path に足すので、そこから素の .py として読まれる。
# - 見た目・デッキ・モデルも datas で `_internal/` の下に、**ソース時と同じ相対位置**で置く
#   （`webapp/images.py`・`meicho/drlnet.py` は `__file__` 相対でファイルを探す）。
# - onedir（1 フォルダ）にする。onefile は起動のたびに展開して遅く、記録の置き場も分かりにくい。
# - console=True。ウィンドウを閉じればサーバが止まる、という分かりやすさを優先する。
import os

HERE = os.path.dirname(os.path.abspath(SPEC))
ENGINE = os.path.join(HERE, "engine")

datas = [
    (os.path.join(ENGINE, "experiments"), "experiments"),
    (os.path.join(ENGINE, "webapp", "static"), os.path.join("webapp", "static")),
    (os.path.join(ENGINE, "decklists"), "decklists"),
    (os.path.join(ENGINE, "results", "models"), os.path.join("results", "models")),
]

hiddenimports = [
    # `experiments/*.py` は data として置くので静的解析されない。そこが使う stdlib をここで拾う
    "concurrent.futures", "multiprocessing", "json", "math", "random", "hashlib",
    # 実行時に sys.path 経由で読む名前（静的解析では見つからない）
    "webapp", "webapp.server", "webapp.agents", "webapp.session", "webapp.view",
    "webapp.record", "webapp.images", "webapp.distribution", "webapp.review",
    "meicho", "meicho.engine", "meicho.state", "meicho.cards", "meicho.cards_export",
    "meicho.greedy", "meicho.planner", "meicho.heuristic", "meicho.mcts",
    "meicho.valuenet", "meicho.drlnet", "meicho.encode", "meicho.features",
    "meicho.oppmodel", "meicho.agents", "meicho.runner", "meicho.audit",
    "meicho.drl_data",
    "numpy",
]

a = Analysis(
    [os.path.join(HERE, "run_app.py")],
    pathex=[ENGINE],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "matplotlib", "scipy", "pandas", "PIL", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MeichoSim",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MeichoSim",
)
