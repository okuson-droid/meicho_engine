"""文献計画 便 M の検査（D-076）。

固定するもの:

1. カンニング版 planner が**相手の手札だけ**を真の手札にする（山札の並びは混ざる）（T-M-1）
2. `peek` を含む名前がどの登録簿にも無い（T-M-2。既存の T-L6 は動かさない）
3. 世界の数え方 W / H_w（T-M-3）と、`hand_known` を必ず含むこと（T-M-4）
4. 葉の相関は「全セルの**結果**が同じ」であって「詰みがあるか」ではない（T-M-5）
5. Elo 換算と便 C の分岐（T-M-6）
6. 帯 672000..675999 の登録と、670000 帯の文の訂正（T-M-7）
7. ラダー解析が**記録の欄**と**いまの champion** を分けて出し、数字は不変（T-M-8）
8. D1 の循環の規則が純関数であること（T-M-9）
9. 中盤の定義 ⌈T/2⌉ と D_t の端の扱い（T-M-10）

**わざと壊して落ちることを確かめた**（引継ぎ書 §4）:
`PeekPlanner._determinize` を素に戻す → T-M-1 が落ちる／W から `hand_known` の条件を
外す → T-M-4 が落ちる／相関の判定を「詰みが 1 つでもあるか」に変える → T-M-5 が落ちる。
"""
from __future__ import annotations

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from experiments.arena import load_deck, mirror_config                    # noqa: E402
from meicho.engine import apply, decision_players, initial_state          # noqa: E402
from meicho.planner import PlannerAgent                                   # noqa: E402
from meicho.state import Phase                                            # noqa: E402

SD001 = load_deck("SD001")
CONFIG = mirror_config(SD001)
POOL = SD001["action_deck"]
_HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(_HERE, "..", "results")
FIXTURES = os.path.join(_HERE, "fixtures")


def _state_with_opponent_hand(seed: int = 673900, steps: int = 30):
    """相手の手札が 2 枚以上ある局面まで、素の計画探索で進める（軽い相手で十分）。"""
    s = initial_state(CONFIG, seed)
    a = PlannerAgent(seed * 2, opp_decklist=POOL)
    b = PlannerAgent(seed * 2 + 1, opp_decklist=POOL)
    for _ in range(steps):
        if s.outcome is not None:
            break
        need = decision_players(s)
        if not need:
            break
        if 0 in need and len(s.players[1].hand) >= 2 and s.turn_no >= 2:
            return s
        s = apply(s, {q: (a if q == 0 else b).act(s, q) for q in sorted(need)})
    return s


# ===================================================== T-M-1
def test_peek_planner_uses_true_hand_only():
    """相手の手札は真の手札そのもの。**山札の並びは元と違いうる**（自分の山札も混ざる）。"""
    from peek_planner import PeekPlanner

    s = _state_with_opponent_hand()
    assert len(s.players[1].hand) >= 2, "相手の手札のある局面に届かなかった"

    ag = PeekPlanner(11, opp_decklist=POOL)
    opp_deck_differed = my_deck_differed = False
    for _ in range(10):
        t = ag._determinize(s, 0)
        # 相手の手札は真の手札（多重集合として一致。並びも保つ）
        assert t.players[1].hand == list(s.players[1].hand)
        # 相手の山札の中身は「未公開プール − 真の手札」の多重集合であること
        assert sorted(t.players[1].action_deck) == sorted(
            _rest_after_hand(ag, s, 0))
        if t.players[1].action_deck != s.players[1].action_deck:
            opp_deck_differed = True
        if t.players[0].action_deck != s.players[0].action_deck:
            my_deck_differed = True
    assert opp_deck_differed, "相手の山札の並びが 10 回とも元のままだった（混ぜていない）"
    assert my_deck_differed, "自分の山札の並びが 10 回とも元のままだった（混ぜていない）"

    # `_sample_opponent` も同じ扱い（直し忘れると天井が過小に出る・§7 の 3）
    u = ag._sample_opponent(s, 0)
    assert u.players[1].hand == list(s.players[1].hand)

    # 親（素の PlannerAgent）は真の手札を渡していない＝カンニングが効いている
    base = PlannerAgent(11, opp_decklist=POOL)
    same = sum(1 for _ in range(10)
               if sorted(base._determinize(s, 0).players[1].hand)
               == sorted(s.players[1].hand))
    assert same < 10, "親クラスでも毎回 真の手札になっている（カンニングを測れない）"


def _rest_after_hand(ag, s, pi):
    """`_unseen` から真の手札を 1 枚ずつ引いた残り（山札に入るはずの多重集合）。"""
    from peek_planner import _remove_multiset
    rest = _remove_multiset(sorted(ag._unseen(s, pi)), list(s.players[1 - pi].hand))
    return rest[:len(s.players[1 - pi].action_deck)]


# ===================================================== T-M-2
def test_peek_names_absent_from_registries():
    """`peek` を含む名前は `CHAMPIONS`・ガントレット・アプリ・登録簿・候補表のどこにも無い。"""
    import champion as chmod
    import registry
    from probe_d065 import CANDIDATES
    from webapp import agents as wagents

    def _has_peek(x) -> bool:
        return "peek" in json.dumps(x, ensure_ascii=False, default=str).lower()

    assert not _has_peek(chmod.CHAMPIONS)
    gdir = os.path.join(_HERE, "..", "experiments", "gauntlets")
    for name in sorted(os.listdir(gdir)):
        if name.endswith(".json"):
            with open(os.path.join(gdir, name), encoding="utf-8") as f:
                assert not _has_peek(json.load(f)), name
    assert not _has_peek(wagents.OPPONENTS)
    assert not _has_peek(sorted(registry.FACTORIES))
    assert not _has_peek(sorted(CANDIDATES)), "probe_d065.CANDIDATES に混ざっている"
    for deck in ("SD001", "SD02"):
        assert not _has_peek(wagents.available(deck))
    # champion の登録名にも入っていない
    assert "peek" not in (chmod.name_for("SD001") or "").lower()


# ===================================================== T-M-3
def test_world_count_on_small_pool():
    """区別できる**多重集合**の数と、多重度で重みづけたエントロピー。"""
    from diag_pimc import world_counts

    r = world_counts(["A", "A", "B"], 2)
    assert r["W"] == 2                                # {A,A} と {A,B}
    # 重み (C(2,2), C(2,1)·C(1,1)) = (1, 2) → H(1/3, 2/3)
    want = -(1 / 3) * math.log2(1 / 3) - (2 / 3) * math.log2(2 / 3)
    assert r["H_w"] == pytest.approx(want, abs=1e-12)

    r2 = world_counts(["A", "B", "C"], 2)
    assert r2["W"] == 3
    assert r2["H_w"] == pytest.approx(math.log2(3), abs=1e-12)

    # 端: 手札 0 枚なら 1 通り・エントロピー 0
    r3 = world_counts(["A", "B"], 0)
    assert r3["W"] == 1 and r3["H_w"] == pytest.approx(0.0, abs=1e-12)


# ===================================================== T-M-4
def test_world_count_respects_hand_known():
    """スキャンで見た札は**必ず含まれる**。それを外すと数が合わない。"""
    from diag_pimc import world_counts

    r = world_counts(["A", "A", "B"], 2, known=["B"])
    assert r["W"] == 1                                # {A,B} だけ
    assert r["H_w"] == pytest.approx(0.0, abs=1e-12)
    assert r["known_n"] == 1 and r["k"] == 1

    # 知らなければ 2 通り（T-M-3）。**hand_known を無視すると縮まない**
    assert world_counts(["A", "A", "B"], 2)["W"] == 2

    r2 = world_counts(["A", "A", "B", "C"], 3, known=["C"])
    assert r2["W"] == 2                               # {C,A,A} と {C,A,B}


# ===================================================== T-M-5
def test_leaf_correlation_on_constructed_tables():
    """相関は「全セルの**結果**が同じ」。詰みの有無と混同しない。"""
    from diag_pimc import correlated_from_grid

    assert correlated_from_grid([["ai", "ai"], ["ai", "ai"]])["correlated"] is True
    assert correlated_from_grid([["ai", "ai"], ["ai", "hu"]])["correlated"] is False
    # 「全セル詰みでない」でも結果が揃えば相関している
    assert correlated_from_grid([["none", "none"], ["none", "none"]])["correlated"] is True
    assert correlated_from_grid([["hu", "hu"], ["hu", "hu"]])["correlated"] is True
    # 詰みが 1 つあるだけでは相関ではない（**ここが混同しやすい**）
    g = [["ai", "hu"], ["none", "hu"]]
    assert correlated_from_grid(g)["correlated"] is False
    assert correlated_from_grid(g)["cells"] == 4
    assert correlated_from_grid([])["correlated"] is False


# ===================================================== T-M-6
def test_elo_conversion_and_branch():
    """Elo 換算と便 C の範囲の分岐（§0.3 (ii)）。**閾値は回す前に決めてある。**"""
    from peek_planner import branch_for, elo_from_p, p_from_elo

    assert elo_from_p(0.5) == pytest.approx(0.0, abs=1e-9)
    assert elo_from_p(0.529) == pytest.approx(20.2, abs=0.1)
    assert elo_from_p(0.571) == pytest.approx(49.7, abs=0.1)
    assert elo_from_p(0.4) == pytest.approx(-70.4, abs=0.1)
    assert p_from_elo(20.0) == pytest.approx(0.529, abs=1e-3)
    assert p_from_elo(50.0) == pytest.approx(0.571, abs=1e-3)

    b = branch_for(0.62, 0.60, 0.64)          # +85 Elo。区間はどの閾値もまたがない
    assert b["scope"] == "all" and b["boundary"] is False
    b = branch_for(0.55, 0.53, 0.57)          # +35 Elo
    assert b["scope"] == "ii7_ii8" and b["boundary"] is False
    b = branch_for(0.45, 0.43, 0.47)          # −35 Elo
    assert b["scope"] == "ii7_only" and b["boundary"] is False
    # 境界: 点推定は II-7・II-8 だが、区間が +50 をまたぐ
    b = branch_for(0.56, 0.54, 0.59)
    assert b["scope"] == "ii7_ii8" and b["boundary"] is True
    assert b["boundary_thresholds"] == [50.0]
    b = branch_for(0.53, 0.50, 0.60)
    assert b["scope"] == "ii7_ii8" and b["boundary_thresholds"] == [20.0, 50.0]


# ===================================================== T-M-7
def test_seed_bands_lit_m_registered():
    """帯 672000..675999 が台帳にあり、重なりが無い。670000 帯の文が実際どおり。"""
    path = os.path.join(_HERE, "..", "experiments", "seed_bands.json")
    d = json.load(open(path, encoding="utf-8"))
    bands = d["bands"]
    mine = [b for b in bands if b["start"] == 672000]
    assert len(mine) == 1, "便 M の帯が無い（または重複している）"
    assert mine[0]["end"] == 675999 and mine[0]["kind"] == "diag"
    # `next_free` は台帳全体で 1 つしかない「次に取れる番号」であり、**便が進むたびに
    # 前へ進む**。便 M の時点の値を `==` で固定すると、次の便が帯を登録した瞬間に
    # この検査が落ちる（実際に便 C の段 C-0 で落ちた）。固定したいのは
    # 「便 M の帯より先に進んでいること」なので `>=` で書く（他の便の検査も同じ形）。
    assert d["next_free"] >= 676000

    spans = sorted((b["start"], b["end"]) for b in bands)
    for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
        assert e0 < s1, f"帯が重なっている: {s0}..{e0} と {s1}..{e1}"

    old = [b for b in bands if b["start"] == 670000]
    assert len(old) == 1
    assert "2 本" in old[0]["purpose"], "670000 帯の文が直っていない（実際は 2 本）"
    assert "10 本" not in old[0]["purpose"]


# ===================================================== T-M-8
def _fake_record(champion_name: str) -> dict:
    """3 体の小さな記録。**記録の欄の champion** を引数で決める。"""
    agents = {"alpha": {}, "beta": {}, "gamma": {}}
    pairs = [{"a": "alpha", "b": "beta", "decided": 200, "wins_a": 130},
             {"a": "alpha", "b": "gamma", "decided": 200, "wins_a": 140},
             {"a": "beta", "b": "gamma", "decided": 200, "wins_a": 110}]
    return {"run_id": "fake", "gauntlet": "core5", "gauntlet_version": 0,
            "date": "2026-09-09T00:00:00+09:00", "deck": "SD001",
            "agents": agents, "pairs": pairs, "cycles": [],
            "ratings": {n: {"elo": 1000, "lo": 950, "hi": 1050} for n in agents},
            "champion": champion_name}


def test_ladder_analysis_champion_label_and_numbers_unchanged():
    """`record_champion`（記録の欄）と `champion`（いまの champion）が別に出る。数字は不変。"""
    from ladder_analysis import analyse

    rec = _fake_record("beta")
    out = analyse(rec, splits=3, iters=2000, restarts=2, champion_name="alpha")
    assert out["record_champion"] == "beta"
    assert out["champion"] == "alpha"
    assert out["champion_source"] == "argument"
    assert out["champion_in_support"] == ("alpha" in out["nash"]["support"])
    assert out["record_champion_in_support"] == ("beta" in out["nash"]["support"])
    assert out["champion_nA"] == pytest.approx(out["nash"]["nA"]["alpha"])
    assert out["record_champion_nA"] == pytest.approx(out["nash"]["nA"]["beta"])

    # 引数を渡さなければ従来どおり記録の欄を使う
    out2 = analyse(rec, splits=3, iters=2000, restarts=2)
    assert out2["champion"] == "beta" and out2["champion_source"] == "record"

    # ラダーに載っていない名前でも落ちない（v8 がこの形）
    out3 = analyse(rec, splits=3, iters=2000, restarts=2, champion_name="delta")
    assert out3["champion_in_ladder"] is False and out3["champion_nA"] is None

    # 実記録: v9 は現 champion で読み、数字は作り直し前と 1 つも変わらない
    new9 = json.load(open(os.path.join(RESULTS, "ladder_analysis_core5_v9.json"),
                          encoding="utf-8"))
    assert new9["champion"] == "planner_vc4cps"
    assert new9["champion_in_support"] is True
    assert new9["champion_nA"] == pytest.approx(0.0, abs=1e-6)
    assert new9["record_champion"] == "planner_vb3cps"
    assert new9["record_champion_in_support"] is False
    for v in ("v9", "v8"):
        old = json.load(open(os.path.join(
            FIXTURES, f"ladder_analysis_core5_{v}.before_d076.json"), encoding="utf-8"))
        new = json.load(open(os.path.join(
            RESULTS, f"ladder_analysis_core5_{v}.json"), encoding="utf-8"))
        for k in ("nash", "elo", "elo_vs_melo2", "cycles_by_tau", "seat_advantage",
                  "effective_diversity", "agents", "n_agents"):
            assert new[k] == old[k], f"{v} の {k} が変わっている"


# ===================================================== T-M-9
def test_cycle_rule_is_pure_function():
    """D1 の循環の規則（§0.3 (vi)）。**上端 ≥ 0.5 なら循環あり。**"""
    from d1_cycle import cycle_verdict

    v = cycle_verdict(300, 600)
    assert v["cycle"] is True and v["p"] == pytest.approx(0.5)
    v = cycle_verdict(250, 600)
    assert v["cycle"] is False and v["hi"] == pytest.approx(0.456, abs=0.001)
    v = cycle_verdict(285, 600)
    assert v["cycle"] is True and v["hi"] == pytest.approx(0.515, abs=0.001)
    assert cycle_verdict(0, 0)["cycle"] is None
    # 純関数（同じ入力で同じ出力・外を読まない）
    assert cycle_verdict(285, 600) == cycle_verdict(285, 600)


# ===================================================== T-M-10
def test_d_mid_definition():
    """中盤 = ⌈T/2⌉。W_0 = 1 なら D_t = 1（最初から確定）。"""
    from diag_pimc import d_from_w, mid_turn_of

    assert mid_turn_of(7) == 4
    assert mid_turn_of(8) == 4
    assert mid_turn_of(1) == 1
    assert mid_turn_of(12) == 6
    assert mid_turn_of(0) == 1

    assert d_from_w(5, 1) == 1.0            # W_0 = 1 → 定義により 1
    assert d_from_w(1, 100) == 1.0          # 完全に絞れた
    assert d_from_w(100, 100) == pytest.approx(0.0)
    assert d_from_w(10, 100) == pytest.approx(0.5)
