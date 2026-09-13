# -*- coding: utf-8 -*-
"""`cards/` の画像と `meicho/cards.py`（実装）の突き合わせ（UI_DESIGN.md §7.1）。

## 何のためにあるか

対人検証アプリはカードを画像で並べる。画像が引けないカードは文字表示に落ちるが、
**落ちたことに気付けなければ意味が無い**ので、機械で毎回数えられる形にした。

`scripts/reconcile_cards.py` とは役割が違う。あちらは**カードの中身**（色・コスト・
タグ）を CSV と突き合わせる。こちらは**画像の在り処**だけを見る。

## 何を出すか

1. 実装にあるが画像が無いカード  → **これがあると画面に穴が開く**
2. 画像はあるが実装に無いカード  → 未登録カード（D-062 の残り）の進捗表になる
3. 索引に当たらなかった画像ファイル → 名前の先頭がカードIDでないもの

索引は**ファイル名の先頭のカードIDだけ**を見る（誤字・異体字・レベル欠落に強い）。
`-R` はパラレル（別イラスト・同じカード）なので、既定では非パラレルを採る。

使い方:
    python3 scripts/check_card_images.py          # 人が読む形で出す
    python3 scripts/check_card_images.py --quiet  # 問題だけ出す

終了コード: 1 の「画像が無い実装カード」があれば 1、無ければ 0。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.normpath(ROOT))

from meicho.cards import ACTION_CARDS, CHARA_CARDS      # noqa: E402
from webapp import images                               # noqa: E402


def _name_of(cid: str) -> str:
    c = ACTION_CARDS.get(cid) or CHARA_CARDS.get(cid)
    return c.name if c else "（実装に無い）"


def check(quiet: bool = False) -> list[str]:
    index = images.get_index()
    st = images.status()

    # 索引に当たらなかった画像ファイル
    stray = []
    if os.path.isdir(images.CARDS_DIR):
        for name in sorted(os.listdir(images.CARDS_DIR)):
            if os.path.splitext(name)[1].lower() not in images._EXT:
                continue
            if not images.ID_RE.match(name):
                stray.append(name)

    if not quiet:
        print(f"画像フォルダ: {images.CARDS_DIR}")
        print(f"索引 = {st['indexed']} 種 / 実装 = {st['implemented']} 枚")

        print(f"\n1. 画像が無い実装カード: {len(st['missing'])} 枚")
        for cid in st["missing"]:
            print(f"    ★ {cid}「{_name_of(cid)}」")

        print(f"\n2. 画像はあるが実装に無いカード（未登録）: {len(st['unused'])} 枚")
        for cid in st["unused"]:
            print(f"    {cid}  {os.path.basename(index[cid])}")

        print(f"\n3. 索引に当たらなかった画像ファイル: {len(stray)} 件")
        for name in stray:
            print(f"    {name}")

        # パラレルの採用状況（見落としやすいので数だけ出す）
        par = [cid for cid, p in index.items()
               if os.path.splitext(os.path.basename(p))[0].endswith("-R")]
        print(f"\nパラレル（-R）を採ったカード: {len(par)} 種"
              + (f" {par}" if par else "（非パラレルが全部そろっている）"))

    problems = [f"画像が無い: {cid}「{_name_of(cid)}」" for cid in st["missing"]]
    if quiet:
        for p in problems:
            print("★ " + p)
    return problems


if __name__ == "__main__":
    sys.exit(1 if check("--quiet" in sys.argv[1:]) else 0)
