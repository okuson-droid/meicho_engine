# -*- coding: utf-8 -*-
"""D-062: cards_structured.csv / .json の修正（2026-08-31・実行済み）。

**このスクリプトは実行済みである。**再実行しても「すでに列が追加されている」で止まる。
記録として残してある（何をどう直したかが分かるように）。

1. 転記漏れ2件の補正（実カード画像で裏取り済み）
   - BP01-033 散華Lv0 :「協奏エリアに置く。」→「協奏エリアに置いてもよい。」
   - SD02-006 今汐Lv1 :「手札に加える。」→「手札に加えてもよい。」
2. 列 `dedicated_to`（専用キャラ）を末尾に追加する。
   既存15列の並びは変えない（位置で読む道具が壊れないようにするため）。
   キャラカードは "-"。アクションカードは engine の dedicated_to と
   BP01-061 の実カード画像（専用キャラ=アンコ）から埋める。

書式は原本に合わせる: UTF-8 BOM 付き・改行 CRLF・
引用符内の改行は LF のまま。
"""
import csv, io, json, os, sys

CARDS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cards"))
CSV_PATH = os.path.join(CARDS, "cards_structured.csv")
JSON_PATH = os.path.join(CARDS, "cards_structured.json")

# --- 1. 効果テキストの補正 -------------------------------------------------
EFFECT_FIX = {
    "BP01-033": (
        "■【リーダー】【対抗】自分が青色のカードで対抗した場合、自分のデッキの上から1枚を協奏エリアに置く。",
        "■【リーダー】【対抗】自分が青色のカードで対抗した場合、自分のデッキの上から1枚を協奏エリアに置いてもよい。",
    ),
    "SD02-006": (
        "■【リーダー】【判定】自分が赤色のカードで青色のカードに敗北した場合、自分のデッキの上から1枚を公開し、手札に加える。",
        "■【リーダー】【判定】自分が赤色のカードで青色のカードに敗北した場合、自分のデッキの上から1枚を公開し、手札に加えてもよい。",
    ),
}

# --- 2. 専用キャラ ---------------------------------------------------------
# 公式番号 → 専用キャラ名。SD01/SD02 の34枚は engine の dedicated_to と一致する。
# BP01-061 のみ実カード画像から読み取った（左上の枠に「アンコ」）。
DEDICATED = {
    # SD01（漂泊者（女）・秧秧・熾霞）
    "SD01-007": "熾霞",        "SD01-008": "熾霞",       "SD01-009": "熾霞",
    "SD01-010": "熾霞",        "SD01-011": "熾霞",
    "SD01-012": "秧秧",        "SD01-013": "秧秧",       "SD01-014": "秧秧",
    "SD01-015": "秧秧",        "SD01-016": "秧秧",
    "SD01-017": "漂泊者（女）", "SD01-018": "漂泊者（女）", "SD01-019": "漂泊者（女）",
    "SD01-020": "漂泊者（女）", "SD01-021": "漂泊者（女）", "SD01-022": "漂泊者（女）",
    "SD01-023": "漂泊者（女）",
    # SD02（漂泊者（男）・散華・今汐）
    "SD02-007": "今汐",        "SD02-008": "今汐",       "SD02-009": "今汐",
    "SD02-010": "今汐",        "SD02-011": "今汐",
    "SD02-012": "散華",        "SD02-013": "散華",       "SD02-014": "散華",
    "SD02-015": "散華",        "SD02-016": "散華",
    "SD02-017": "漂泊者（男）", "SD02-018": "漂泊者（男）", "SD02-019": "漂泊者（男）",
    "SD02-020": "漂泊者（男）", "SD02-021": "漂泊者（男）", "SD02-022": "漂泊者（男）",
    "SD02-023": "漂泊者（男）",
    # BP01
    "BP01-061": "アンコ",
}


def main() -> int:
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        cols = list(rdr.fieldnames)
        rows = list(rdr)

    assert cols[-1] == "set", cols
    assert "dedicated_to" not in cols, "すでに列が追加されている"

    applied = {"effect": 0, "dedicated": 0, "blank": 0}
    for r in rows:
        code = r["code"]
        if code in EFFECT_FIX:
            before, after = EFFECT_FIX[code]
            if r["effect"] == before:
                r["effect"] = after
                applied["effect"] += 1
            else:
                assert r["effect"] == after, f"{code}: 想定外の効果テキスト\n{r['effect']!r}"
        if r["type"] == "キャラカード":
            r["dedicated_to"] = "-"
            applied["blank"] += 1
        else:
            r["dedicated_to"] = DEDICATED[code]
            applied["dedicated"] += 1

    cols.append("dedicated_to")

    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\r\n")
    w.writeheader()
    w.writerows(rows)
    with open(CSV_PATH, "wb") as f:
        f.write("﻿".encode("utf-8"))
        f.write(buf.getvalue().encode("utf-8"))

    # JSON は原本と同じ体裁で書く: BOM なし・改行 LF・indent=2・rarity のみ int。
    def typed(r: dict) -> dict:
        out = {}
        for c in cols:
            out[c] = int(r[c]) if c == "rarity" else r[c]
        return out

    with open(JSON_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump([typed(r) for r in rows], f, ensure_ascii=False, indent=2)

    print(f"効果テキストの補正 {applied['effect']}件 / "
          f"専用キャラ記入 {applied['dedicated']}件 / キャラカード '-' {applied['blank']}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
