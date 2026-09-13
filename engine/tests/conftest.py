"""検査の下ごしらえ。**カード登録簿を検査のあいだ汚したままにしない。**

## なぜこれが要るのか（D-064 の実装中に見つかった潜在的な事故）

`tests/test_engine.py` は、効果解決器の分岐を突くために合成カード
（`TEST-A-*` / `TEST-C-*`）を `meicho.cards.ACTION_CARDS` / `CHARA_CARDS` に直接足す。
登録簿はモジュール大域の dict なので、**足したままだと後続の検査モジュールに残る**。

ここまでは無害だったが、次の 2 つが重なると壊れる。

1. 観測の符号化の長さ `OBS_DIM` は**カードの種類数から決まる**（`meicho/encode.py`）。
   Python 側は import 時に確定するが、Rust 側は `rs.load_cards(cards_json())` を
   呼んだ時点の登録簿から作り直される。
2. 検査モジュールのいくつか（`test_rust_engine.py` など）は自分で `rs.load_cards` を呼ぶ。

結果、`test_engine.py` の**あと**に Rust の表を読み直すと、Python が 596 次元・
Rust が 615 次元という食い違いが起き、価値ネットを積んだエージェントの
Python/Rust 一致検査が**検査の順番によって落ちる**。

実装の欠陥ではなく検査どうしの干渉なので、ここで断つ。1 つの検査が足した
合成カードは、その検査が終わったら消す。
"""
from __future__ import annotations

import os
import sys

import pytest

# 各検査モジュールが自分で入れているのと同じ経路（どこから pytest を呼んでも同じになるように）
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for p in (_ROOT, os.path.join(_ROOT, "experiments")):
    if p not in sys.path:
        sys.path.insert(0, p)

from meicho.cards import ACTION_CARDS, CHARA_CARDS      # noqa: E402


@pytest.fixture(autouse=True)
def _keep_card_registry_clean():
    """検査が足した合成カードを、その検査の終わりに取り除く。

    既存のカードの**中身**は触らない（差し替えたなら元に戻す）。
    """
    before_a = dict(ACTION_CARDS)
    before_c = dict(CHARA_CARDS)
    yield
    for reg, before in ((ACTION_CARDS, before_a), (CHARA_CARDS, before_c)):
        for cid in [c for c in reg if c not in before]:
            del reg[cid]
        for cid, card in before.items():
            if reg.get(cid) is not card:
                reg[cid] = card
