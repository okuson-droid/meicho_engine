"""自動発見ループ（`experiments/discovery.py`・D-050 / D-053）のテスト。

勝率そのものは固定しない（測定は台帳が持つ）。固定するのは**前提**である:
- 生成器がカード名をコードに持たず、デッキのデータから候補を作ること
- `Intervention` が D-045 の診断用エージェント（`RushWandererLv2` 等）と同じ手を選ぶこと
- 「禁じる」型が計画探索の木の中まで効くこと／絞った結果が空なら絞らないこと
- 発火回数が数えられること
- 台帳の 1 行が必要な項目（シード帯・n・勝率・区間・判定）を持つこと
- **温存（reserve）が「対抗で出さない」と別の規則であること**（D-052 で見つかった重複の再発防止）
- **選別が「挙動が変わったか」で行われること**（手の記録のハッシュが champion と全局一致したら測らない）
- **シード帯が 1 つも重ならず、第 1・2 巡のシードが過去の記録と変わらないこと**
"""
from __future__ import annotations

import json

import pytest

rs = pytest.importorskip("meicho_rs")

from experiments import discovery as dsc                              # noqa: E402
from experiments.arena import load_deck, mirror_config                # noqa: E402
from experiments.arena_rs import (HEURISTIC, PLANNER, ensure_cards,    # noqa: E402
                                  series_rs_detail, series_rs_digest)
from experiments.measure_rush_lv2 import LateWandererLv2, RushWandererLv2  # noqa: E402
from meicho.cards import CHARA_CARDS                                  # noqa: E402
from meicho.engine import apply, decision_players, initial_state, outcome  # noqa: E402
from meicho.heuristic import HeuristicAgent                           # noqa: E402

SD001 = load_deck("SD001")
SD02 = load_deck("SD02")


@pytest.fixture(scope="module", autouse=True)
def _cards():
    ensure_cards()


def test_generators_are_data_driven():
    a1 = dsc.gen_A(SD001)
    a2 = dsc.gen_A(SD02)
    n1 = {CHARA_CARDS[c].name for c in SD001["chara_deck"]}
    n2 = {CHARA_CARDS[c].name for c in SD02["chara_deck"]}
    assert {d["name"] for d in a1} == n1 and {d["name"] for d in a2} == n2
    assert n1 != n2                                   # デッキが違えば候補も違う
    assert len(a1) == 3 * (2 * 4 + 1)                  # 3 体 × (2 レベル × (急ぐ3 + 禁じる1) + リーダー固定)
    for d in a1 + dsc.gen_B(SD001) + dsc.gen_C(SD001):
        assert dsc.label(d)                            # 人が読める一文が付く


def _lockstep_delta(delta, py_agent_cls, seed):
    """δ つき Rust 挑戦者と Python の診断用エージェントが毎手同じ手を選ぶ。"""
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    py = initial_state(cfg, seed)
    rss = rs.initial_state(cfg.chara_decks, cfg.action_decks, seed)
    py_ag = [py_agent_cls(seed * 2, opp_decklist=pool), HeuristicAgent(seed * 2 + 1)]
    # Rust 側は series の中でしか挑戦者を作れないので、ここでは 1 局を series_rs_detail で回し
    # 勝敗・ターン・手数が Python 版の 1 局と一致することで代用する
    steps = 0
    while outcome(py) is None and py.turn_no <= 200:
        need = decision_players(py)
        if not need:
            break
        acts = {pi: py_ag[pi].act(py, pi) for pi in need}
        py = apply(py, acts)
        rss = rs.apply(rss, acts)
        steps += 1
    out = series_rs_detail(PLANNER(pool, delta=delta), HEURISTIC(), 1, cfg, 1, seed0=seed)
    a_won, turns, rs_steps, fired = out[0]
    # series は seed の偶奇で席を入れ替えるので、偶数シードだけ Python 版と同じ席順になる
    assert seed % 2 == 0
    py_won = (outcome(py) == 0)
    assert (a_won, turns, rs_steps) == (py_won, py.turn_no, steps), (delta, seed)
    return fired


@pytest.mark.parametrize("seed", [0, 2, 4, 6])
def test_rush_chara_equals_rush_wanderer_lv2(seed):
    fired = _lockstep_delta({"kind": "rush_chara", "name": "漂泊者（女）", "goal": 2, "from_turn": 1},
                            RushWandererLv2, seed)
    assert fired >= 1


@pytest.mark.parametrize("seed", [0, 2, 4])
def test_rush_chara_from_turn_7_equals_late_wanderer(seed):
    _lockstep_delta({"kind": "rush_chara", "name": "漂泊者（女）", "goal": 2, "from_turn": 7},
                    LateWandererLv2, seed)


def test_forbid_levelup_never_reaches_level_and_fires():
    """禁じる型: 対局を通じてそのレベルに一度も上がらない（計画探索の木の中でも禁じられる）。"""
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    from experiments.measure_rush_lv2 import _top_level
    fired = 0
    for seed in range(6):
        ch = rs.Challenger(seed * 2, [{"kind": "forbid_levelup", "name": "漂泊者（女）", "level": 1}], opp_decklist=pool)
        h = rs.HeuristicAgent(seed * 2 + 1)
        s = rs.initial_state(cfg.chara_decks, cfg.action_decks, seed)
        while rs.outcome(s) is None and s.turn_no <= 200:
            need = rs.decision_players(s)
            if not need:
                break
            acts = {pi: (ch.act(s, pi) if pi == 0 else h.act(s, pi)) for pi in need}
            s = rs.apply(s, acts)
            st = json.loads(s.to_json())
            for stack in (sl["stack"] for sl in st["players"][0]["slots"]):
                if stack and CHARA_CARDS[stack[-1]].name == "漂泊者（女）":
                    assert CHARA_CARDS[stack[-1]].level == 0, (seed, stack)
        fired += ch.fired
    assert fired > 0
    del _top_level


def test_challenger_without_delta_equals_planner():
    """δ が空の挑戦者は champion そのもの（同じ手を選ぶ）。"""
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    for seed in range(3):
        ch = rs.Challenger(seed * 2, [], opp_decklist=pool)
        pl = rs.PlannerAgent(seed * 2, opp_decklist=pool)
        h = rs.HeuristicAgent(seed * 2 + 1)
        s = rs.initial_state(cfg.chara_decks, cfg.action_decks, seed)
        while rs.outcome(s) is None and s.turn_no <= 200:
            need = rs.decision_players(s)
            if not need:
                break
            acts = {}
            for pi in need:
                if pi == 0:
                    a, b = ch.act(s, 0), pl.act(s, 0)
                    assert a == b
                    acts[0] = a
                else:
                    acts[1] = h.act(s, 1)
            s = rs.apply(s, acts)
        assert ch.fired == 0


def test_restriction_never_empties_legal_actions():
    """絞った結果が空になる δ（例: 対抗で唯一の札を禁じる）でも対局は完走する。"""
    cfg = mirror_config(SD02)
    pool = SD02["action_deck"]
    name = next(iter({CHARA_CARDS[c].name for c in SD02["chara_deck"]}))
    deltas = [{"kind": "forbid_levelup", "name": name, "level": 1},
              {"kind": "never_free_rush"}, {"kind": "no_pass_if_behind", "margin": 0}]
    out = series_rs_detail(PLANNER(pool, delta=deltas), PLANNER(pool), 6, cfg, 2, seed0=190000)
    assert len(out) == 6 and all(r[1] > 0 for r in out)


def test_stacked_deltas_fire_and_run():
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    deltas = [{"kind": "rush_chara", "name": "漂泊者（女）", "goal": 2, "from_turn": 1},
              {"kind": "always_free_rush"}]
    out = series_rs_detail(PLANNER(pool, delta=deltas), HEURISTIC(), 10, cfg, 2, seed0=180000)
    assert sum(x[3] for x in out) >= 10


def test_ledger_row_has_seeds_and_intervals(tmp_path, monkeypatch):
    """台帳の 1 行に、再現に要るもの（帯・n・勝率・区間・判定）が全部ある。局数は小さくしてよい。

    **局数は意図的に小さい**（D-065 便 2 で champion が約 5 倍遅くなったため）。
    ここが固定するのは台帳の行の**中身**であって強さではないので、局数を減らしても意味は失われない。
    """
    monkeypatch.setattr(dsc, "LEDGER_DIR", str(tmp_path))
    loop = dsc.Loop("SD001", workers=2, screen_n=20, confirm_n=20, behav_n=4, quiet=True)
    rows = loop.run([{"kind": "rush_chara", "name": "漂泊者（女）", "goal": 2, "from_turn": 1}], max_folds=1)
    assert rows and rows[0]["verdict"] in ("accepted", "screen_fail", "confirm_fail", "no_change")
    lines = [json.loads(x) for x in open(loop.ledger_path, encoding="utf-8")]
    r = lines[0]
    for k in ("delta", "label", "behaviour", "verdict", "deck", "round", "champion_deltas", "time"):
        assert k in r
    assert r["behaviour"]["n"] == 4 and "changed_games" in r["behaviour"]
    if "screen" in r:
        assert {"seed0", "n", "decided", "wins", "p", "ci", "lb"} <= set(r["screen"])
    text = dsc.report(rows, "SD001", loop.champion_deltas)
    assert "発見ループ SD001" in text


# ---------------------------------------------------------------------------
# D-053 裁定 1: 温存（reserve）は「対抗で出さない」と別の規則である
# ---------------------------------------------------------------------------

CHAMP = [{"kind": "rush_chara", "name": "漂泊者（女）", "goal": 2, "from_turn": 1}]


def _digests(delta_list, n=20, seed0=210000):
    """挑戦者（champion + δ）を champion に当てたときの、各局の手の記録のハッシュ。"""
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    a = PLANNER(pool, delta=list(CHAMP) + list(delta_list)) if delta_list else PLANNER(pool, delta=list(CHAMP))
    out = series_rs_digest(a, PLANNER(pool, delta=list(CHAMP)), n, cfg, 2, seed0=seed0)
    return [r[4] for r in out]


def _rushable_card() -> str:
    """champion が実際に連撃で使うカードを 1 枚選ぶ（温存の後半が発火する相手）。"""
    for nm in sorted({dsc.ACTION_CARDS[c].name for c in SD001["action_deck"]}):
        if _digests([{"kind": "forbid_in_rush", "card": nm}]) != _digests([]):
            return nm
    raise AssertionError("連撃で使われるカードが 1 枚も無い")


def test_reserve_is_not_the_same_rule_as_forbid_in_clash():
    """D-052 で見つかった重複の再発防止。温存は対抗禁止と別の挙動を持つ。"""
    card = _rushable_card()
    forbid = _digests([{"kind": "forbid_in_clash", "card": card}])
    reserve = _digests([{"kind": "reserve", "card": card}])
    assert forbid != reserve, card


def test_reserve_forbids_clash_and_forces_rush():
    """温存 = 対抗では出さない（禁じる型）＋ 連撃で使えるなら必ず使う（強いる型）。"""
    cfg = mirror_config(SD001)
    pool = SD001["action_deck"]
    card = _rushable_card()
    submitted = rushed = forced = 0
    for seed in range(210000, 210040, 2):          # 偶数シード = 挑戦者が席 0（series と同じ約束）
        ch = rs.Challenger(seed * 2, list(CHAMP) + [{"kind": "reserve", "card": card}], opp_decklist=pool)
        opp = rs.PlannerAgent(seed * 2 + 1, opp_decklist=pool)
        s = rs.initial_state(cfg.chara_decks, cfg.action_decks, seed)
        while rs.outcome(s) is None and s.turn_no <= 200:
            need = rs.decision_players(s)
            if not need:
                break
            acts = {}
            for pi in need:
                if pi == 0:
                    hand = [dsc.ACTION_CARDS[c].name for c in s.hand(0)]   # hand() は card_id を返す
                    legal = rs.legal_actions(s, 0)
                    a = ch.act(s, 0)
                    if a["type"] == "submit":
                        assert hand[a["hand"]] != card                    # 対抗では出さない
                        submitted += 1
                    if a["type"] == "rush" and hand[a["hand"]] == card:
                        rushed += 1
                    # 連撃でそのカードが使えるなら必ずそれを選ぶ
                    if any(x["type"] == "rush" and hand[x["hand"]] == card for x in legal):
                        assert a["type"] == "rush" and hand[a["hand"]] == card, (seed, a)
                        forced += 1
                    acts[0] = a
                else:
                    acts[pi] = opp.act(s, pi)
            s = rs.apply(s, acts)
    assert forced > 0 and rushed > 0, (forced, rushed, submitted)


# ---------------------------------------------------------------------------
# D-053 裁定 2: 選別は「挙動が変わったか」で行う
# ---------------------------------------------------------------------------

def test_digest_is_stable_and_detects_a_changed_move():
    """同じ相手・同じシードなら digest は毎回同じ。手が変われば digest も変わる。"""
    assert _digests([]) == _digests([])                                   # 決定的
    changed = _digests([{"kind": "rush_chara", "name": "熾霞", "goal": 1, "from_turn": 1}])
    assert changed != _digests([])                                        # 実際に効く δ は変わる
    # champion が既に達成している目標を重ねても手は変わらない（δ が空回りする例）
    same = _digests([{"kind": "rush_chara", "name": "漂泊者（女）", "goal": 2, "from_turn": 7}])
    assert same == _digests([])


def test_behaviour_stage_rejects_a_delta_that_changes_nothing(tmp_path, monkeypatch):
    """champion が一度も連撃で使わないカードを連撃で禁じても、手は 1 つも変わらない → 測らない。

    **局数は意図的に小さい**（D-065 便 2 で champion が約 5 倍遅くなったため）。ここが固定するのは
    「挙動が 1 局も変わらない δ は測定に進まない」という**短絡そのもの**であって、
    どのカードが無効かではない。探索と本判定が同じ局数を見ている限り、結論は変わらない。
    """
    monkeypatch.setattr(dsc, "LEDGER_DIR", str(tmp_path))
    loop = dsc.Loop("SD001", workers=2, screen_n=20, confirm_n=20, behav_n=20, quiet=True)
    loop.champion_deltas = list(CHAMP)
    noop = None
    for nm in sorted({dsc.ACTION_CARDS[c].name for c in SD001["action_deck"]}):
        d = {"kind": "forbid_in_rush", "card": nm}
        if loop.behaviour(d, 1)["changed_games"] == 0:
            noop = d
            break
    assert noop is not None, "無効な候補が 1 つも無い（デッキが変わった？）"
    rec = loop.evaluate(noop, 1)
    assert rec["verdict"] == "no_change" and "screen" not in rec


def test_behaviour_stage_lets_a_real_delta_through(tmp_path, monkeypatch):
    monkeypatch.setattr(dsc, "LEDGER_DIR", str(tmp_path))
    # 局数は小さめ（champion が重いため）。「本物の δ は 1 局以上変える」を見るには足りる。
    loop = dsc.Loop("SD001", workers=2, screen_n=20, confirm_n=20, behav_n=20, quiet=True)
    loop.champion_deltas = list(CHAMP)
    b = loop.behaviour({"kind": "rush_chara", "name": "熾霞", "goal": 1, "from_turn": 1}, 1)
    assert b["changed_games"] > 0 and b["first_changed_seed"] is not None


# ---------------------------------------------------------------------------
# D-053 裁定 3: シード帯は 2 巡で 1 帯。過去の巡のシードは変わらない
# ---------------------------------------------------------------------------

def test_band_layout_is_unchanged_for_rounds_1_and_2():
    """第 1・2 巡のシードは D-051/D-052 の記録と同じでなければならない（測り直しを避けるため）。"""
    loop = dsc.Loop("SD001", workers=1, quiet=True)
    assert loop.band("screen", 1) == 181000 and loop.band("screen", 2) == 181300
    assert loop.band("confirm", 1) == 183000 and loop.band("confirm", 2) == 184200
    assert loop.band("reconfirm", 1) == 186000 and loop.band("reconfirm", 2) == 187200
    l2 = dsc.Loop("SD02", workers=1, quiet=True)
    assert l2.band("screen", 1) == 191000 and l2.band("confirm", 1) == 193000
    assert l2.band("reconfirm", 1) == 196000            # SD02 第 1 巡で実際に使った帯


def test_band_ranges_never_overlap():
    """全デッキ・全巡・全段階のシード区間が 1 つも重ならない（D-052 欠陥 C の再発防止）。"""
    used = []
    for deck in dsc.BANDS:
        loop = dsc.Loop(deck, workers=1, quiet=True)
        for rnd in range(1, loop.max_rounds + 1):
            for stage, n in (("behaviour", dsc.BEHAV_N), ("screen", dsc.SCREEN_N),
                             ("confirm", dsc.CONFIRM_N), ("reconfirm", dsc.CONFIRM_N)):
                s0 = loop.band(stage, rnd)
                used.append((s0, s0 + n - 1, deck, rnd, stage))
    used.sort()
    for (a0, a1, *ai), (b0, b1, *bi) in zip(used, used[1:]):
        assert a1 < b0, (ai, (a0, a1), bi, (b0, b1))


def test_band_beyond_the_sequence_is_rejected():
    loop = dsc.Loop("SD001", workers=1, quiet=True)
    assert loop.max_rounds == len(dsc.BANDS["SD001"]) * dsc.ROUNDS_PER_BAND
    with pytest.raises(AssertionError):
        loop.band("screen", loop.max_rounds + 1)


def test_bands_are_registered_in_seed_bands_json():
    """`BANDS` の帯が全部 seed_bands.json に登録されている（D-028 の規約）。"""
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "experiments", "seed_bands.json")
    reg = json.load(open(p, encoding="utf-8"))["bands"]
    for deck, bases in dsc.BANDS.items():
        for base in bases:
            assert any(b["start"] <= base and base + 9999 <= b["end"] for b in reg), (deck, base)
