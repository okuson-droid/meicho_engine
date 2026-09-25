"""記録の読み込み（`meicho/drl_data.read_records`）を 2 回読みの形にした（D-132）ことの検査。

旧方式（`_read_records_listwise`・1 決定ずつ小さな配列を作って最後に積む）と、**すべての欄が 1 ビットも違わない**
ことを、実際に書いた記録（複数ファイル・異種デッキ）で確かめる。`max_records` で途中で止めた場合も同じ。
シードは台帳の 826900..826999（打ち方の近さの診断の検査枠・学習にも評価にも使用禁止）の中。
"""
from __future__ import annotations

import numpy as np
import pytest

rs = pytest.importorskip("meicho_rs")

from experiments.arena import load_deck, matchup_config                       # noqa: E402
from experiments.arena_rs import GREEDY, ensure_cards                          # noqa: E402
from meicho import drl_data as D                                               # noqa: E402

FIELDS = ("seed", "step", "turn", "pi", "phase", "n_acts", "chosen", "z", "fresh", "obs", "act_off",
          "acts_flat", "scores_flat")


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    ensure_cards()
    d0, d1 = load_deck("SD001"), load_deck("SD02")
    cfg = matchup_config(d0, d1)
    tmp = tmp_path_factory.mktemp("rd")
    _res, fs = rs.series_record(cfg.chara_decks, cfg.action_decks, GREEDY(d1["action_deck"]),
                                GREEDY(d0["action_deck"]), 826960, 6, str(tmp / "r"), 2, 200, True, True,
                                opp_from_seat=True)
    return fs


def _same(a, b):
    assert a.n == b.n
    for k in FIELDS:
        x, y = getattr(a, k), getattr(b, k)
        assert x.dtype == y.dtype and x.shape == y.shape, k
        assert np.array_equal(x, y, equal_nan=(x.dtype.kind == "f")), k


def test_two_pass_equals_listwise(files):
    assert len(files) >= 2
    _same(D.read_records(files), D._read_records_listwise(files))


@pytest.mark.parametrize("m", [1, 57, 10_000_000])
def test_two_pass_equals_listwise_with_max(files, m):
    _same(D.read_records(files, m), D._read_records_listwise(files, m))
