# -*- coding: utf-8 -*-
"""`cards/` フォルダ（正本）と `meicho/cards.py`（実装）の突き合わせ（D-062）。

## 何のためにあるか

2026-08-31 の突き合わせで、engine 側に2件・CSV 側に2件の食い違いが見つかった。
同じことを二度やらないため、**機械で毎回確かめられる形**にしたものである。
`tests/test_cards_folder.py` がこれを呼び、食い違えばテストが落ちる。

## 何を比べるか

`cards/cards_structured.csv` を正として、engine の登録簿と次を比べる。

- カード番号（engine の card_id が CSV の code に存在すること）
- アクション: 色・コスト・スピード・ダメージ・特徴タグ・専用キャラ・【リーダースキル】
- キャラ: レベル・タグ（所属勢力／属性／武器種）

効果テキストは比べない。CSV は日本語文、engine はオペコード列で、機械的に
突き合わせられないからである（人が読んで確かめるしかない）。

## 比べないもの

- `rarity`（レアリティ）: 同じカードの絵柄違い。ゲーム性能に関係しない。
- CSV にあって engine に無いカード: 未登録として**数えて報告する**が、
  失敗にはしない（未登録は既知。D-062 の裁定で ID 統一より後に入れる）。

使い方:
    python3 scripts/reconcile_cards.py          # 人が読む形で出す
    python3 scripts/reconcile_cards.py --quiet  # 食い違いだけ出す
"""
from __future__ import annotations

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CARDS_DIR = os.path.normpath(os.path.join(ROOT, "..", "cards"))
CSV_PATH = os.path.join(CARDS_DIR, "cards_structured.csv")
# 公式が未掲載の番号（D-079 判断 2）。正本 CSV には載せず、ここで突き合わせから外す。
UNLISTED_PATH = os.path.join(CARDS_DIR, "BP01_UNLISTED.json")


def unlisted_codes() -> set:
    """公式が未掲載で、engine には `unverified` の枠だけを置いてある番号。

    正本 CSV に仮値を混ぜると「未掲載」と「確認済み」の区別が正本から消えるので、
    別ファイルに分けてある（D-079 判断 2・引継ぎ書 §0.3 (6) の画像の許容リストと同じ形）。
    ファイルが無い環境では空集合を返す（K-1 より前の状態）。
    """
    try:
        with open(UNLISTED_PATH, encoding="utf-8") as f:
            return set(json.load(f)["codes"])
    except OSError:
        return set()

COLOR_JA = {"赤": "red", "青": "blue", "緑": "green"}


def load_cards_csv(path: str = CSV_PATH) -> dict:
    """code → 行。レアリティ違いの重複行は1つに畳む（性能は同じ）。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        out.setdefault(r["code"], r)
    return out


def _num(v) -> int:
    return 0 if v in ("-", "", None) else int(v)


def check(quiet: bool = False) -> list:
    """食い違いの一覧（文字列）を返す。空なら一致。"""
    sys.path.insert(0, ROOT)
    from meicho.cards import ACTION_CARDS, CHARA_CARDS

    src = load_cards_csv()
    unlisted = unlisted_codes()
    problems = []

    # --- アクションカード ---
    for cid, a in ACTION_CARDS.items():
        if cid.startswith("TEST-"):          # テストが差し込むダミー
            continue
        if cid in unlisted:                  # 公式未掲載の枠（仮値・D-079 判断 2）
            if not a.unverified_fields:
                problems.append(f"{cid}: 未掲載の枠なのに unverified の旗が無い")
            continue
        r = src.get(cid)
        if r is None:
            problems.append(f"アクション {cid}「{a.name}」: cards/ に該当する番号が無い")
            continue
        if r["type"] != "アクションカード":
            problems.append(f"{cid}: cards/ では「{r['type']}」だがアクションとして登録されている")
            continue
        if r["name"] != a.name:
            problems.append(f"{cid}: 名前 cards/='{r['name']}' engine='{a.name}'")
        if COLOR_JA.get(r["color"]) != a.color.value:
            problems.append(f"{cid}「{a.name}」: 色 cards/='{r['color']}' engine='{a.color.value}'")
        for fld, ev in (("cost", a.cost), ("speed", a.speed), ("damage", a.damage)):
            if _num(r[fld]) != ev:
                problems.append(f"{cid}「{a.name}」: {fld} cards/={r[fld]} engine={ev}")
        tags = tuple(t for t in r["trait"].split("、") if t and t != "-")
        if tags != a.tags:
            problems.append(f"{cid}「{a.name}」: 特徴タグ cards/={tags} engine={a.tags}")
        want_ded = r.get("dedicated_to", "-")
        want_ded = None if want_ded in ("-", "") else want_ded
        if want_ded != a.dedicated_to:
            problems.append(f"{cid}「{a.name}」: 専用キャラ cards/={want_ded} engine={a.dedicated_to}")
        want_ls = "【リーダースキル】" in r["effect"]
        if want_ls != a.leader_skill:
            problems.append(f"{cid}「{a.name}」: リーダースキル指定 cards/={want_ls} engine={a.leader_skill}")

    # --- キャラカード ---
    for cid, c in CHARA_CARDS.items():
        r = src.get(cid)
        if r is None:
            problems.append(f"キャラ {cid}「{c.name}」: cards/ に該当する番号が無い")
            continue
        if r["type"] != "キャラカード":
            problems.append(f"{cid}: cards/ では「{r['type']}」だがキャラとして登録されている")
            continue
        if r["name"] != c.name:
            problems.append(f"{cid}: 名前 cards/='{r['name']}' engine='{c.name}'")
        if int(r["level"]) != c.level:
            problems.append(f"{cid}「{c.name}」: レベル cards/={r['level']} engine={c.level}")
        want = tuple(x for x in (r["affiliation"], r["attribute"], r["weapon"])
                     if x not in ("-", ""))
        if want != c.tags:
            problems.append(f"{cid}「{c.name}」: タグ cards/={want} engine={c.tags}")

    if not quiet:
        n_csv = len(src)
        n_eng = len(ACTION_CARDS) + len(CHARA_CARDS)
        missing = [code for code in src if code not in ACTION_CARDS and code not in CHARA_CARDS]
        print(f"cards/ = {n_csv} 種 / engine = {n_eng} 枚"
              f"（うち未掲載の枠 {len(unlisted)}）/ 未登録 = {len(missing)} 枚")
        if missing:
            print("  未登録（D-062 の裁定により ID 統一より後に入れる）:")
            for code in sorted(missing):
                print(f"    {code} {src[code]['name']}（{src[code]['type']}・{src[code]['set']}）")
        print(f"食い違い: {len(problems)} 件")
        for p in problems:
            print("  ★ " + p)
    return problems


if __name__ == "__main__":
    sys.exit(1 if check("--quiet" in sys.argv[1:]) else 0)
