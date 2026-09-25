"""段階2 の表現比較の評価（`experiments/eval_s2_repr.py`・D-132）の検査。

E-1 課題の組み方: 調整デッキ 4 つの順序つきの組 16 ブロック（ミラー 4＋異種 12）。候補がどのデッキも
    同じ局数・席 0 と席 1 を半分ずつ持つ（デッキと席の偏りが候補の差に化けない）
E-2 候補のデッキの読み方: 席 0＝deck_a なので、偶数シードは候補が deck_a・奇数シードは deck_b を持つ
E-3 対の差: 同じ（ブロック・シード）の局どうしで差を取り、デッキ内で局を再標本化してデッキを等重みで平均する
    （計画書 §7.3）。差が全部 0 なら区間も 0、片方が全勝なら差は正
E-4 学習・最終評価のデッキを課題に入れない（調整だけ）
E-5 帯は台帳で確かめる（評価の帯 kind=validate を使う・未登録は落とす）
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import eval_s2_repr as R                                               # noqa: E402


def test_blocks_are_balanced():
    """E-1・E-4: 16 ブロック・調整デッキだけ・候補はどのデッキも同じ局数で、席は半々。"""
    decks = R.tune_decks()
    assert len(decks) == 4
    env = R.load_env()
    assert all(env["decks_block"][d.split("/", 1)[1]]["split"] == "tune" for d in decks)
    bl = R.blocks(decks)
    assert len(bl) == 16 and len(set(bl)) == 16
    n = 300
    held = {d: [0, 0] for d in decks}                                 # [席 0, 席 1]
    for a, b in bl:
        for s in range(n):
            deck, seat = R.cand_deck(a, b, s)
            held[deck][seat] += 1
    assert all(v == [2 * n, 2 * n] for v in held.values()), held


def test_candidate_deck_by_parity():
    """E-2: 偶数シードは deck_a（席 0）、奇数シードは deck_b（席 1）。"""
    assert R.cand_deck("x", "y", 841000) == ("x", 0)
    assert R.cand_deck("x", "y", 841001) == ("y", 1)


def test_paired_bootstrap_zero_and_positive():
    """E-3: 同じ結果なら差も区間も 0。新が全部勝つなら差は正で下端も正。"""
    rng = np.random.RandomState(0)
    # デッキごとの局数をわざと変える（全体の平均とデッキ等重みの平均が食い違うように）
    games = [{"deck": d, "block": 0, "seed": s} for d, m in zip("ABCD", (50, 20, 20, 20)) for s in range(m)]
    base = [float(rng.rand() < 0.5) for _ in games]
    r0 = R.paired_diff(games, base, list(base), n_boot=500, seed=1)
    assert r0["diff"] == 0 and r0["lo"] == 0 and r0["hi"] == 0
    r1 = R.paired_diff(games, [1.0] * len(games), base, n_boot=500, seed=1)
    assert r1["diff"] > 0 and r1["lo"] > 0
    # デッキ等重み: 1 デッキだけ差があるとき、差はそのデッキの差の 1/4
    new = [1.0 if g["deck"] == "A" else b for g, b in zip(games, base)]
    r2 = R.paired_diff(games, new, base, n_boot=200, seed=1)
    a_gap = np.mean([1.0 - b for g, b in zip(games, base) if g["deck"] == "A"])
    assert abs(r2["diff"] - a_gap / 4) < 1e-12


def test_refuses_bad_band():
    """E-5: 未登録の帯・学習の帯では回さない。"""
    with pytest.raises(SystemExit):
        R.check_eval_band(99_000_000, 10)
    with pytest.raises(SystemExit):
        R.check_eval_band(827000, 10)                                  # 学習の帯（kind=train）
