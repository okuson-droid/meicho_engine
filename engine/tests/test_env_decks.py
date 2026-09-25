"""環境デッキ群 24 種（`decklists/env/`・D-128）の検査。

マスターが 2026-09-24 に出した構築規則をそのまま条項にする。

R-1 3 グループ（GA=秧秧・散華／GB=漂泊者（男）・漂泊者（女）・ショアキーパー／
    GC=アンコ・ツバキ・今汐・熾霞）から 1 人ずつ選ぶ。2×3×4 = 24 通りを全部作る。
R-2 色の枚数は 緑 6〜9・青 9〜11・赤 20 以上（合計 40）。
R-3 ＜音骸＞タグのカードを入れない。
R-4 【重撃】はアンコのカードだけ。【通常攻撃】はツバキのカードだけ。
R-5 アタッカーのグループ（GC）の赤は、他の 2 人のどちらよりも多い。
R-6 キャラカードは入れられるものを全部入れる（3 人 × 登録簿の全レベル = 15 枚）。

加えて、rules_draft.md §3.1・§3.2（`GameConfig.validate` と同じ条件）と、
生成器 `experiments/make_env_decks.py` の決定性（作り直すとバイト列が一致する）を見る。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
ENV_DIR = os.path.join(ROOT, "decklists", "env")

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from meicho.cards import ACTION_CARDS, CHARA_CARDS, ONKAI_TAG          # noqa: E402
from meicho.engine import GameConfig                                   # noqa: E402

import make_env_decks as M                                             # noqa: E402

GA = ("秧秧", "散華")
GB = ("漂泊者（男）", "漂泊者（女）", "ショアキーパー")
GC = ("アンコ", "ツバキ", "今汐", "熾霞")


def _load_all() -> dict:
    if not os.path.isdir(ENV_DIR):
        pytest.skip("decklists/env が無い")
    out = {}
    for fn in sorted(os.listdir(ENV_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(ENV_DIR, fn), "rb") as f:
                raw = f.read()
            out[fn[:-len(".json")]] = (json.loads(raw.decode("utf-8")), raw)
    return out


DECKS = _load_all()
NAMES = sorted(DECKS)


def _trio(deck) -> set:
    return {CHARA_CARDS[c].name for c in deck["chara_deck"]}


def _colors(deck) -> Counter:
    return Counter(ACTION_CARDS[c].color.value for c in deck["action_deck"])


def _red_by_chara(deck) -> Counter:
    return Counter(ACTION_CARDS[c].dedicated_to for c in deck["action_deck"]
                   if ACTION_CARDS[c].color.value == "red")


# ------------------------------------------------------------------ R-1
def test_all_24_combinations_exist():
    """R-1: 2×3×4 = 24 通りがちょうど 1 つずつある。"""
    assert len(DECKS) == 24, sorted(DECKS)
    trios = {frozenset(_trio(d)) for d, _ in DECKS.values()}
    want = {frozenset((a, b, c)) for a in GA for b in GB for c in GC}
    assert trios == want


def test_name_matches_the_trio():
    """名前の 3 つの符丁が中身の 3 人組と合う（`ENV_<GA>_<GB>_<GC>`）。"""
    for name, (deck, _) in DECKS.items():
        head, ga, gb, gc = name.split("_")
        assert head == "ENV"
        assert (ga, gb, gc) == (deck["groups"]["GA"], deck["groups"]["GB"], deck["groups"]["GC"])
        assert _trio(deck) == {M.CODE[ga], M.CODE[gb], M.CODE[gc]}
        assert M.CODE[ga] in GA and M.CODE[gb] in GB and M.CODE[gc] in GC
        assert deck["name"] == name


# ------------------------------------------------------------------ 合法性
@pytest.mark.parametrize("name", NAMES)
def test_legal(name):
    """rules §3.1・§3.2（`GameConfig.validate`）。"""
    deck = DECKS[name][0]
    GameConfig(chara_decks=[deck["chara_deck"]] * 2,
               action_decks=[deck["action_deck"]] * 2).validate()


@pytest.mark.parametrize("name", NAMES)
def test_only_dedicated_cards(name):
    """共通カードは 10 枚とも＜音骸＞なので、R-3 の結果として全部が専用札になる。"""
    deck = DECKS[name][0]
    trio = _trio(deck)
    for cid in set(deck["action_deck"]):
        ded = ACTION_CARDS[cid].dedicated_to
        assert ded is not None, f"{name}: {cid} は共通カード"
        assert ded in trio


# ------------------------------------------------------------------ R-2
@pytest.mark.parametrize("name", NAMES)
def test_color_balance(name):
    """R-2: 緑 6〜9・青 9〜11・赤 20 以上。"""
    c = _colors(DECKS[name][0])
    assert sum(c.values()) == 40
    assert 6 <= c["green"] <= 9, (name, dict(c))
    assert 9 <= c["blue"] <= 11, (name, dict(c))
    assert c["red"] >= 20, (name, dict(c))


# ------------------------------------------------------------------ R-3 / R-4
@pytest.mark.parametrize("name", NAMES)
def test_no_onkai(name):
    """R-3: ＜音骸＞を 1 枚も入れない。"""
    for cid in set(DECKS[name][0]["action_deck"]):
        assert ONKAI_TAG not in ACTION_CARDS[cid].tags, f"{name}: {cid}"


@pytest.mark.parametrize("name", NAMES)
def test_heavy_and_normal_attack_are_restricted(name):
    """R-4: 【重撃】はアンコだけ・【通常攻撃】はツバキだけ。"""
    for cid in set(DECKS[name][0]["action_deck"]):
        card = ACTION_CARDS[cid]
        if "重撃" in card.tags:
            assert card.dedicated_to == "アンコ", f"{name}: {cid} {card.name}"
        if "通常攻撃" in card.tags:
            assert card.dedicated_to == "ツバキ", f"{name}: {cid} {card.name}"


def test_anko_and_tsubaki_actually_keep_theirs():
    """R-4 の裏: アンコのデッキには【重撃】が、ツバキのデッキには【通常攻撃】が実際に入っている
    （「全部除いた」で条件を満たしてしまうのを防ぐ）。"""
    n_anko = n_tsubaki = 0
    for name, (deck, _) in DECKS.items():
        tags = Counter(t for cid in deck["action_deck"] for t in ACTION_CARDS[cid].tags)
        if "アンコ" in _trio(deck):
            assert tags["重撃"] > 0, name
            n_anko += 1
        if "ツバキ" in _trio(deck):
            assert tags["通常攻撃"] > 0, name
            n_tsubaki += 1
    assert n_anko == 6 and n_tsubaki == 6


# ------------------------------------------------------------------ R-5
@pytest.mark.parametrize("name", NAMES)
def test_attacker_has_the_most_red(name):
    """R-5: GC の赤が他の 2 人のどちらよりも多い。"""
    deck = DECKS[name][0]
    red = _red_by_chara(deck)
    atk = [n for n in _trio(deck) if n in GC]
    assert len(atk) == 1
    others = [n for n in _trio(deck) if n != atk[0]]
    for o in others:
        assert red[atk[0]] > red[o], (name, dict(red))


# ------------------------------------------------------------------ R-6
@pytest.mark.parametrize("name", NAMES)
def test_all_chara_cards_are_included(name):
    """R-6: 3 人分の登録簿のキャラカードを全部入れる（いまの登録簿では 15 枚）。"""
    deck = DECKS[name][0]
    trio = _trio(deck)
    want = {cid for cid, c in CHARA_CARDS.items() if c.name in trio}
    assert set(deck["chara_deck"]) == want
    assert len(deck["chara_deck"]) == len(want) == 15


# ------------------------------------------------------------------ 生成器
def test_generator_is_deterministic(tmp_path):
    """作り直すとバイト列まで一致する（乱数を使っていない）。"""
    out = str(tmp_path / "env")
    M.build_all(out)
    made = sorted(os.listdir(out))
    assert made == sorted(f"{n}.json" for n in NAMES)
    for n in NAMES:
        with open(os.path.join(out, f"{n}.json"), "rb") as f:
            assert f.read() == DECKS[n][1], n


def test_generator_runs_as_a_script(tmp_path):
    """CLI から回る（`--out`）。"""
    out = str(tmp_path / "env2")
    env = dict(os.environ, PYTHONPATH=os.path.abspath(ROOT))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "experiments", "make_env_decks.py"),
                        "--out", out], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert len(os.listdir(out)) == 24


def test_deck_similarity_accepts_them():
    """`deck_similarity.py::load_decks` が 24 個とも読める（名前が重ならない・合法）。"""
    from deck_similarity import load_decks
    decks, rejected = load_decks([ENV_DIR])
    assert rejected == {}
    assert len(decks) == 24
