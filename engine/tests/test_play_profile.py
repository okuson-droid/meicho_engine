"""「打ち方の近さ」の診断（`experiments/diag_play_profile.py`・設計書 `DECK_SIMILARITY_DESIGN.md` §8・D-130）の検査。

守らせる条項:

P-1 教師がそのデッキを持った局だけを数える。相手の席には共通のデッキ（既定 SD001）を置くので、
    `series` の席の約束（奇数シードで A/B が入れ替わる）により**偶数シードの局だけ**が対象になる。
    教師の記録はすべて席 0（`pi == 0`）で、奇数シードの局の記録は 1 つも使わない。
P-2 割合の特徴（行動の種類・対抗で出した色・コスト帯）は、分母が 0 でなければ和が 1。
P-3 決定的（同じ引数なら結果の JSON はバイトまで同じ）。
P-4 旗の規則（**候補を見る前に固定**）: 異なるグループの組で、打ち方の距離が
    「同じグループの組の距離の中央値」より小さいものに旗を立てる。同じグループの組には立てない。
P-5 帯は台帳で確かめる（未登録・評価専用の帯では回さない）。

対局を回す検査のシードは台帳の 826000..826999（打ち方の近さの診断・学習にも評価にも使用禁止）の中。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

rs = pytest.importorskip("meicho_rs")

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import diag_play_profile as P                                          # noqa: E402

SEED0 = 826900      # 診断の帯の予備の端（本番は 826000..826199）


@pytest.fixture(scope="module", autouse=True)
def _cards():
    from arena_rs import ensure_cards
    ensure_cards()


@pytest.fixture(scope="module")
def one(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pp")
    return P.run_deck("env/ENV_SANGE_RF_ANKO", "SD001", ("heuristic",), n=6, seed0=SEED0, workers=2,
                      tmp=str(tmp))


def test_only_even_seeds_and_teacher_seat0(one):
    """P-1: 使った局は偶数シードだけ、記録は席 0 だけ。"""
    h = one["by_opponent"]["heuristic"]
    assert h["seeds_used"] == [s for s in range(SEED0, SEED0 + 6) if s % 2 == 0]
    assert h["records_pi"] == {"0": h["decisions"]}
    assert h["games"] == 3 and len(h["results"]) == 3


def test_shares_sum_to_one(one):
    """P-2: 割合の特徴は和が 1（分母が 0 のものは全部 0）。"""
    prof = P.profile(one)
    for key in ("act", "color", "cost"):
        s = sum(prof[key])
        assert s == 0 or abs(s - 1) < 1e-9, (key, prof[key])


def test_per_game_counts_add_up(one):
    """ぶれの見積もり（半分ずつに分けたプロフィール）のために、局ごとの数を持ち、その和が合計に一致する。"""
    h = one["by_opponent"]["heuristic"]
    assert len(h["per_game"]) == h["games"]
    assert [sum(g["act"][k] for g in h["per_game"]) for k in range(len(P.ACT_KINDS))] == \
        [h["act_counts"][k] for k in P.ACT_KINDS]
    assert [sum(g["color"][k] for g in h["per_game"]) for k in range(3)] == h["color_counts"]
    # 半分に絞ったプロフィールは、行動の割合も絞った局だけから作られる（全体のままではない）
    full = P.profile(one)
    part = P.profile(one, lambda s: s % 4 == 0)
    assert part["act"] != full["act"] or part["win"] != full["win"]


def test_deterministic(tmp_path):
    """P-3: 同じ引数なら結果はバイトまで同じ。"""
    a = P.run_deck("env/ENV_SANGE_RF_ANKO", "SD001", ("greedy",), n=4, seed0=SEED0 + 10, workers=2,
                   tmp=str(tmp_path / "a"))
    b = P.run_deck("env/ENV_SANGE_RF_ANKO", "SD001", ("greedy",), n=4, seed0=SEED0 + 10, workers=1,
                   tmp=str(tmp_path / "b"))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_flag_rule_on_synthetic_vectors():
    """P-4: 同グループの距離の中央値より近い異グループの組にだけ旗が立つ。"""
    vec = {"a1": [0.0, 0.0], "a2": [1.0, 0.0], "b1": [0.1, 0.0], "b2": [9.0, 9.0]}
    group = {"a1": 0, "a2": 0, "b1": 1, "b2": 1}
    out = P.flag_pairs(vec, group)
    # 同グループ: a1-a2 = 1.0, b1-b2 ≈ 12.6 → 中央値 ≈ 6.8。異グループで近いのは a1-b1(0.1)・a2-b1(0.9)
    flagged = {tuple(sorted(x["pair"])) for x in out["flagged"]}
    assert flagged == {("a1", "b1"), ("a2", "b1")}
    assert all(group[x["pair"][0]] != group[x["pair"][1]] for x in out["flagged"])


def test_flag_rule_breaks_if_same_group_allowed():
    """P-4 をわざと壊す側の確認: 同グループの組は距離が小さくても旗の対象外。"""
    vec = {"a1": [0.0], "a2": [0.0], "b1": [5.0], "b2": [5.0]}
    group = {"a1": 0, "a2": 0, "b1": 1, "b2": 1}
    out = P.flag_pairs(vec, group)
    assert out["flagged"] == []


def test_refuses_unregistered_band(tmp_path):
    """P-5: 未登録の帯では回さない。"""
    with pytest.raises(SystemExit):
        P.run_deck("env/ENV_SANGE_RF_ANKO", "SD001", ("heuristic",), n=2, seed0=99_000_000, workers=1,
                   tmp=str(tmp_path))
