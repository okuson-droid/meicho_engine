#!/usr/bin/env python3
"""検査の組（`tests/test_sets.json`）を、作業環境の全検査の結果（JUnit XML）から作り直す（D-125）。

    python3 -m pytest tests -q -rfs --run-slow --junitxml=/tmp/junit.xml
    python3 scripts/make_test_sets.py /tmp/junit.xml

## 何を作るか

- `slow`: 1 件で **20 秒以上**かかった検査。既定では飛ばし、`--run-slow` のときだけ回す
- `pc_tests`: 作業環境で**資材が無くて**落ちた・飛んだ検査（`drl_sd001_vb3.json`・ラダーの記録・対人の記録・
  カード画像・`cards_structured.csv` など）。マスターの PC にはあるので、PC ではこれを回す（`--pc`）。
  torch が無くて飛んだものは PC にも torch が無いので入れない
- `pc_files`: 資材と関係なく**PC で回す意味がある**ファイル（手で決める・この道具は変えない）。
  Windows で作った Rust の部品の毎手一致・Windows の時計・移行したネット

**前提: 作業環境で落ちる検査は資材の無いものだけ**（それ以外で落ちていたら、先に直してからこの道具を打つ）。
落ちた検査は理由を見ずに `pc_tests` に入れるので、本物の失敗を混ぜるとそれが PC に回るだけで隠れはしないが、
作業環境で見落とすことになる。落ちた理由の一覧を最後に出すので、目で確かめること。
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET

SLOW_SEC = 20.0
_HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(_HERE, "..", "tests", "test_sets.json")


def key_of(tc) -> str:
    """`test_x.py::名前`（パラメータの `[...]` は外す）。conftest の `_key` と同じ規則。"""
    mod = tc.get("classname").split(".")[-1]
    name = tc.get("name").split("[", 1)[0]
    return f"{mod}.py::{name}"


def main(argv):
    if len(argv) != 2:
        raise SystemExit(__doc__)
    root = ET.parse(argv[1]).getroot()
    slow, pc, why = set(), set(), {}
    for tc in root.iter("testcase"):
        k = key_of(tc)
        if float(tc.get("time") or 0) >= SLOW_SEC:
            slow.add(k)
        for ch in tc:
            msg = (ch.get("message") or "").replace("\n", " ")[:120]
            if ch.tag in ("failure", "error"):
                pc.add(k); why[k] = "失敗: " + msg
            elif ch.tag == "skipped" and "torch" not in msg:
                pc.add(k); why[k] = "skip: " + msg
    with open(PATH, encoding="utf-8") as f:
        cur = json.load(f)
    cur["slow"] = sorted(slow)
    cur["pc_tests"] = sorted(pc)
    with open(PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"slow {len(slow)} 件 / pc_tests {len(pc)} 件 を書いた: {os.path.normpath(PATH)}")
    for k in sorted(why):
        print(f"  {k} — {why[k]}")


if __name__ == "__main__":
    main(sys.argv)
