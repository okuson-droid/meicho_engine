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

## 検査の組（D-125・2026-09-22）

全検査は PC で約 3 時間かかる。時間の 8 割は 20 本ほどの重い検査なので、組に分けて回す。
組の中身は `tests/test_sets.json`（`slow` と `pc_tests` は `scripts/make_test_sets.py` が作る）。

- **既定**（`python -m pytest tests`）: `slow` の検査は**飛ばす**（理由の行に「slow」と出る）
- `--run-slow`: 重い検査も回す。**作業環境ではクロエが毎便これで全検査を回す**（約 40 分）。
  AI の打ち方・champion の定義・発見ループを変えた便と、段階の区切りでは PC でもこれを使う
- `--pc`: **PC で回す組だけ**を集める（`pc_files` のファイル全部＋作業環境で資材が無くて回らなかった
  `pc_tests`）。この組の中の重い検査は飛ばさない（PC でしか回らないので）

飛ばす検査は、作業環境の `--run-slow` の全検査が毎便守る。「条件つきの skip は壊し方を素通りする」
（測定の作法）ので、**作業環境の全検査を省いた便では PC でも `--run-slow` を使う**こと。
"""
from __future__ import annotations

import os
import sys

import pytest

# 各検査モジュールが自分で入れているのと同じ経路（どこから pytest を呼んでも同じになるように）
# D-105: `scripts` をここに移した。以前は `test_bp01.py` の中の 4 か所と
# `test_cards_folder.py` / `test_dist.py` のモジュール頭に散っていて、4 か所のうち
# 1 か所が抜けていた。全検査では収集順のおかげで通り、そのファイルだけ名指しで
# 回すと落ちる、という見つけにくい形になっていた。**経路は 1 か所で持つ。**
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for p in (_ROOT, os.path.join(_ROOT, "experiments"), os.path.join(_ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from meicho.cards import ACTION_CARDS, CHARA_CARDS      # noqa: E402

import json as _json                                    # noqa: E402

_SETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_sets.json")


def _load_sets() -> dict:
    with open(_SETS_PATH, encoding="utf-8") as f:
        return _json.load(f)


def _key(item) -> str:
    """`test_x.py::名前`（パラメータの `[...]` は外す）。`scripts/make_test_sets.py` と同じ規則。"""
    return f"{os.path.basename(str(item.fspath))}::{item.name.split('[', 1)[0]}"


def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", default=False,
                     help="重い検査（tests/test_sets.json の slow）も回す（D-125）")
    parser.addoption("--pc", action="store_true", default=False,
                     help="マスターの PC で回す組だけを集める（pc_files と pc_tests・D-125）")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 1 件で 20 秒以上かかる検査（既定では飛ばす・--run-slow で回す）")


def pytest_collection_modifyitems(config, items):
    sets = _load_sets()
    slow = set(sets.get("slow", ()))
    if config.getoption("--pc"):
        files = set(sets.get("pc_files", ()))
        want = set(sets.get("pc_tests", ()))
        keep, drop = [], []
        for it in items:
            (keep if (os.path.basename(str(it.fspath)) in files or _key(it) in want) else drop).append(it)
        if drop:
            config.hook.pytest_deselected(items=drop)
            items[:] = keep
        return                                     # PC の組は重いものも飛ばさない
    if config.getoption("--run-slow"):
        return
    skip = pytest.mark.skip(reason="slow（重い検査・--run-slow で回す・D-125）")
    for it in items:
        if _key(it) in slow:
            it.add_marker(pytest.mark.slow)
            it.add_marker(skip)


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
