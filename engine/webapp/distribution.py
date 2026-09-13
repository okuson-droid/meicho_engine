"""配布モード（D-074・案 B: 知人に配る Windows 実行ファイル）。

## 何をするか

配布版は「開発環境そのもの」ではなく、`scripts/make_dist.py` が allowlist で組み立てた
別のフォルダである。その中にマーカー `dist.json` を置き、**マーカーがあるときだけ**
アプリの振る舞いを次の 3 点で変える。

1. 記録（`results/human_games/`）の置き場を、マーカーの隣（＝実行ファイルの隣）にする。
   PyInstaller の onedir では `webapp/` はバンドル内（`_internal/`）に入るので、
   従来の「`webapp/../results`」だと利用者から見えない場所に書いてしまう。
2. 相手の一覧を `dist.json` の `opponents`（allowlist）で絞る。測定中の候補
   （`planner_vb3cps_lu50` 等）を配布版に出さないため。
3. 画面のタイトルと注意書き（非公式であること・権利表記）を `dist.json` から出す。
   画像が無いことは配布版の仕様なので、警告ではなく説明として出す（`server.config_payload`）。

## 守ること

- **マーカーが無ければ一手も変わらない。** `is_dist()` が False のとき、ここに書いた
  関数はすべて従来の値を返す。`tests/test_dist.py` が固定する。
- ルールにも AI にも触らない。ここは配布の**入れ物**の話であり、エンジンの真実源
  （rules_draft.md / cards/）とは無関係である。
- マーカーの探し方は 1 つ（`marker_path()`）。検査はここを差し替えて配布モードを入切する。

## PyInstaller での位置関係

```
MeichoSim/                 ← 配布フォルダ（実行ファイルの隣が「アプリの根」）
  MeichoSim.exe
  dist.json                ← マーカー（ここにある）
  results/human_games/     ← 記録（利用者が見つけられる場所）
  _internal/               ← バンドル（コード・モデル・デッキ。利用者は触らない）
    engine/meicho/ ... engine/results/models/ ...
```

`sys.frozen` のとき `app_root()` は実行ファイルの隣、それ以外は `engine/` の親
（`run_app.py` を置く場所）を返す。
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE = os.path.normpath(os.path.join(_HERE, ".."))

MARKER_NAME = "dist.json"

_INFO: dict | None = None      # 読み込み済みのマーカー（None = 未読 or 無し）。検査が差し替える


def app_root() -> str:
    """マーカーと記録を置く「アプリの根」。

    - PyInstaller で固めた実行ファイル: 実行ファイルの隣
    - ソースのまま（`run_app.py` から起動）: `engine/` の親
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.normpath(os.path.join(_ENGINE, ".."))


def marker_path() -> str:
    """マーカーの置き場。**ここが唯一の探し方**（検査はこの関数を差し替える）。"""
    return os.path.join(app_root(), MARKER_NAME)


def info() -> dict | None:
    """マーカーの中身。無ければ None。1 回読んだら覚える（対局中に振る舞いが揺れない）。"""
    global _INFO
    if _INFO is not None:
        return _INFO or None
    p = marker_path()
    if not os.path.isfile(p):
        _INFO = {}
        return None
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError(f"{p}: dist.json は辞書でなければならない")
    d.setdefault("name", "対決シミュレータ（非公式）")
    d.setdefault("notice", "")
    _INFO = d
    return d


def is_dist() -> bool:
    return info() is not None


def results_dir() -> str:
    """記録の置き場。配布モードではマーカーの隣の `results/`、それ以外は従来の `engine/results`。"""
    if is_dist():
        return os.path.join(os.path.dirname(marker_path()), "results")
    return os.path.join(_ENGINE, "results")


def opponent_allowlist() -> list | None:
    """配布版で選ばせる相手の登録名。None = 絞らない（従来どおり）。"""
    d = info()
    if d is None:
        return None
    ops = d.get("opponents")
    if ops is None:
        return None
    if not isinstance(ops, list) or not all(isinstance(x, str) for x in ops):
        raise ValueError("dist.json の opponents は登録名の配列でなければならない")
    return list(ops)


def opponent_labels() -> dict:
    """配布版で画面に出す相手の表示名（登録名 → 表示名）。無ければ空＝従来の表示名。

    従来の表示名は「現champion・Elo 1423・SD001専用」のような開発用の語で、
    知人には意味が通らない。登録名（記録に残る鍵）は変えず、表示名だけ差し替える。
    """
    d = info()
    if d is None:
        return {}
    labels = d.get("labels") or {}
    if not isinstance(labels, dict):
        raise ValueError("dist.json の labels は {登録名: 表示名} の辞書でなければならない")
    return dict(labels)


def public_info() -> dict | None:
    """画面に渡す分（`/api/config` の `dist`）。マーカーの中身をそのまま出さず、要る鍵だけ。"""
    d = info()
    if d is None:
        return None
    return {"name": d["name"], "notice": d["notice"],
            "version": d.get("version", ""), "credits": d.get("credits", "")}
