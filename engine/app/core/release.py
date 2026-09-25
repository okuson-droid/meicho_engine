"""いま動いている版と更新の状態（要件 R-UPD-8・R-UPD-9）。設定画面に出すために読むだけ。

配布版では、中身は `contents/versions/<版>/engine/` にあり、その隣の `release.json` が署名つきの目録である。
署名の検証は起動役の仕事で（`app/mslauncher`）、ここでは**表示のために読むだけ**である。
開発ツリーには `release.json` が無いので、そのときは「開発版」と答える。

更新の結果（更新した・届かなかった・一つ前に戻した・新しい起動役が必要）は、起動役が
環境変数 `MEICHOSIM_STATUS` で教えたファイルに書く。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

ENGINE_DIR = Path(__file__).resolve().parents[2]
STATUS_ENV = "MEICHOSIM_STATUS"
_KEYS = ("version", "seq", "built", "notes", "rules_version", "cards_version", "launcher_api_min")


def manifest(engine_dir: Optional[Path] = None) -> Optional[dict]:
    engine_dir = engine_dir or ENGINE_DIR
    try:
        with open(engine_dir.parent / "release.json", encoding="utf-8") as f:
            m = json.loads(json.load(f)["manifest"])
        return m if isinstance(m, dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def info(engine_dir: Optional[Path] = None) -> dict:
    """`/api/version` の中身。"""
    m = manifest(engine_dir)
    out = {"dist": m is not None, "version": "開発版", "history": [], "update": None}
    if m:
        out.update({k: m.get(k) for k in _KEYS})
        out["history"] = [h for h in m.get("history", []) if isinstance(h, dict)][:30]
    path = os.environ.get(STATUS_ENV)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            if isinstance(st, dict):
                out["update"] = {k: st.get(k) for k in ("state", "detail", "checked", "from", "to", "launcher_api")}
        except (OSError, ValueError):
            pass
    return out
