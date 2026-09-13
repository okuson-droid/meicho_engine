# -*- coding: utf-8 -*-
"""`cards/` フォルダ（正本）と `meicho/cards.py` が食い違わないことを固定する（D-062）。

2026-08-31 の突き合わせで engine 側に2件・CSV 側に2件の誤りが見つかった。
**同じ誤りを二度作らないための門番**である。カードを足す・直すときは、
先に `cards/cards_structured.csv` を正しくしてから実装を合わせること。

`cards/` が無い環境（エンジンだけ切り出した場合など）では skip する。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import reconcile_cards  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.path.exists(reconcile_cards.CSV_PATH),
    reason=f"cards/cards_structured.csv が無い ({reconcile_cards.CSV_PATH})")


def test_engine_cards_match_cards_folder():
    """数値・色・タグ・専用キャラ・レベルが cards/ と一致すること。

    効果テキストは機械比較できない（CSV は日本語文・engine はオペコード列）ので
    ここでは見ない。効果の確認は人がカード画像と突き合わせる。
    """
    problems = reconcile_cards.check(quiet=True)
    assert not problems, "cards/ と cards.py が食い違っている:\n  " + "\n  ".join(problems)


def test_every_engine_card_id_is_an_official_number():
    """engine の card_id が、すべて cards/ の code 欄に実在する番号であること。

    仮ID（`SD001-T01` や `AC-003` のような、実カードに存在しない番号）が
    紛れ込むと、また同じ突き合わせ作業が必要になる。
    """
    from meicho.cards import ACTION_CARDS, CHARA_CARDS
    codes = set(reconcile_cards.load_cards_csv())
    # 公式が未掲載の枠は正本 CSV に載せない（D-079 判断 2）。仮IDではなく、
    # 公式の連番のうち中身だけが未公開の番号なので、ここでは別扱いにする。
    codes |= reconcile_cards.unlisted_codes()
    bad = [cid for cid in list(ACTION_CARDS) + list(CHARA_CARDS)
           if not cid.startswith("TEST-") and cid not in codes]
    assert not bad, f"cards/ に存在しない番号で登録されている: {sorted(bad)}"


def test_decklists_use_official_numbers():
    """デッキリストのカード番号も、すべて実在する番号であること。"""
    import json
    codes = set(reconcile_cards.load_cards_csv())
    root = os.path.join(os.path.dirname(__file__), "..")
    for name in ("SD001", "SD02"):
        with open(os.path.join(root, "decklists", f"{name}.json"), encoding="utf-8") as f:
            d = json.load(f)
        bad = sorted({c for c in d["chara_deck"] + d["action_deck"] if c not in codes})
        assert not bad, f"decklists/{name}.json に実在しない番号: {bad}"


def test_no_card_in_the_folder_is_left_unregistered():
    """`cards/` の番号がすべて `cards.py` に入っていること。

    2026-09-10 の便 K で段階的に減らしてきた期待値が、段 K-1 で**空になった**
    （D-079 追記 2。68 番号＋未掲載の 3 枠を一度に登録した）。
    以後ここが空でなくなったら、`cards/` に新しい番号が入ったのに実装が
    追いついていない、という取りこぼしである。

    経緯: 13 枚（D-062）→ 68 番号（K-0・正本が 65→120 番号に増えたため）→ 0（K-1）。
    """
    from meicho.cards import ACTION_CARDS, CHARA_CARDS
    src = reconcile_cards.load_cards_csv()
    known = set(ACTION_CARDS) | set(CHARA_CARDS)
    missing = sorted(c for c in src if c not in known)
    assert missing == [], f"cards/ にあって engine に無い番号: {missing}"


def test_nothing_is_excluded_from_the_reconcile_any_more():
    """突き合わせから外している番号が無いこと。

    2026-09-10 の時点では公式未掲載の 3 番号（`BP01-049` `BP01-057` `BP01-062`）を
    正本 CSV に載せず、engine 側にだけ添字確保の枠を置いていた（D-079 判断 2）。
    **2026-09-12 に 3 枚とも掲載されて正本に入った**ので、この非対称は解消した。
    以後 `cards/BP01_UNLISTED.json` の `codes` が空でなくなったら、
    公式に新しい欠番が出たということなので、経緯を書いてから足すこと。

    なお `BP01-057` と `BP01-062` は**効果がまだ入っていない**が、それは別の話である
    （数値・色・タグ・専用キャラは正本と一致している。効果の穴は
    `tests/test_bp01.py` の T-K-10 が xfail(strict) で見張っている）。
    """
    from meicho.cards import ACTION_CARDS
    src = set(reconcile_cards.load_cards_csv())
    assert reconcile_cards.unlisted_codes() == set(), \
        "突き合わせから外している番号がある（増えたなら理由を書くこと）"
    for cid in ("BP01-049", "BP01-057", "BP01-062"):
        assert cid in ACTION_CARDS, f"{cid} が登録簿に無い"
        assert cid in src, f"{cid} が正本 CSV に無い"
