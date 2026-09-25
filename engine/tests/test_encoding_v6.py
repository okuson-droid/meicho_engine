"""段階1C-c（D-124）: 符号化 v6 の検査。

1. 形: v6 は v5 の列を動かさず、末尾に信念の要約（N_BELIEF）と統一した hand_known（NA）を足しただけ。
   デッキ表の想定を渡しても渡さなくても、先頭 OBS_DIM_V5 は同じ。
2. Python↔Rust: 実対局の毎手・両席で、デッキ表の想定あり／なしの両方で一致する
   （BP01-039 で知識を忘れる道を通る K_smoke を含む）。
3. 信念の要約の正しさ: W が小さい局面で、`worlds.enumerate_hands` の全列挙と
   W・確定の旗・色／コスト帯の上下限（ちょうど最小・最大）が一致する。
4. 覗き見の禁止（D-026）: 相手の**知らない**手札と山札を入れ替えても符号化が変わらない。
5. ネットの移行: 移行したネットに v6 の入力を与えた出力は、元のネットに v5 の入力を与えた出力と一致する。
"""
from __future__ import annotations

import json
import os
import random
from collections import Counter

import numpy as np
import pytest

rs = pytest.importorskip("meicho_rs")

from experiments.arena import load_deck, matchup_config, mirror_config          # noqa: E402
from meicho import encode as E                                                 # noqa: E402
from meicho.agents import RandomAgent                                          # noqa: E402
from meicho.buckets import _COLOR_IX, cost_band                                # noqa: E402
from meicho.cards import ACTION_CARDS                                          # noqa: E402
from meicho.cards_export import cards_json                                     # noqa: E402
from meicho.engine import apply, decision_players, initial_state, observe, outcome  # noqa: E402
from meicho.heuristic import HeuristicAgent                                    # noqa: E402
from meicho.worlds import enumerate_hands                                      # noqa: E402

SD001, SD02 = load_deck("SD001"), load_deck("SD02")
ANKO, SANGE = load_deck("K_smoke_ANKO"), load_deck("K_smoke_SANGE")


@pytest.fixture(scope="module", autouse=True)
def _load_cards():
    rs.load_cards(cards_json())


def _states(config, seed, kind="heuristic", max_steps=3000):
    """Python と Rust を並べて進め、毎手 (py, rss) を返す。"""
    config.validate()
    ag = ([RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)] if kind == "random"
          else [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)])
    py = initial_state(config, seed)
    rss = rs.initial_state(config.chara_decks, config.action_decks, seed)
    for _ in range(max_steps):
        need = decision_players(py)
        yield py, rss
        if outcome(py) is not None or not need or py.turn_no > 200:
            return
        acts = {pi: ag[pi].act(py, pi) for pi in need}
        py = apply(py, acts)
        rss = rs.apply(rss, acts)


def test_version_and_shape():
    assert E.ENCODING_VERSION == 6
    assert E.OBS_DIM == E.OBS_DIM_V5 + E.N_BELIEF + E.NA
    assert rs.encoding_info() == (6, E.OBS_DIM, E.ACT_DIM)
    assert "encoding_v6" in rs.features()


def test_v5_prefix_does_not_depend_on_the_decklist():
    """先頭の v5 部分はデッキ表の想定に依らない（＝移行したネットの出力が変わらない根拠）。"""
    cfg = matchup_config(SD001, SD02)
    n = 0
    for py, _ in _states(cfg, 7):
        for pi in (0, 1):
            ob = observe(py, pi)
            a = E.encode(ob, pi)
            b = E.encode(ob, pi, cfg.action_decks[1 - pi])
            assert a[:E.OBS_DIM_V5] == b[:E.OBS_DIM_V5]
            assert a[E.OBS_DIM_V5] == 0 and b[E.OBS_DIM_V5] == 1      # 「デッキ表を渡されたか」
            tail = b[E.OBS_DIM_V5 + E.N_BELIEF:]
            assert tail == E._counts(ob["opp"]["hand_known"], E.A_INDEX, E.NA)
            n += 1
    assert n > 50


@pytest.mark.parametrize("cfg_name,seed,kind", [
    ("SD001", 1, "random"), ("SD001", 2, "heuristic"), ("SD02", 3, "heuristic"),
    ("SD001-SD02", 4, "random"), ("SD001-SD02", 5, "heuristic"), ("ANKO-SANGE", 6, "heuristic"),
])
def test_python_rust_match_with_and_without_decklist(cfg_name, seed, kind):
    cfg = {"SD001": mirror_config(SD001), "SD02": mirror_config(SD02),
           "SD001-SD02": matchup_config(SD001, SD02),
           "ANKO-SANGE": matchup_config(ANKO, SANGE)}[cfg_name]
    n = nz = 0
    for py, rss in _states(cfg, seed, kind):
        for pi in (0, 1):
            ob = observe(py, pi)
            deck = cfg.action_decks[1 - pi]
            assert E.encode(ob, pi) == list(rs.encode_obs(rss, pi))
            e_py = E.encode(ob, pi, deck)
            assert e_py == list(rs.encode_obs(rss, pi, deck)), f"{cfg_name} seed={seed} P{pi} turn={py.turn_no}"
            n += 1
            nz += any(e_py[E.OBS_DIM_V5 + 6:E.OBS_DIM_V5 + E.N_BELIEF])
    assert n > 50 and nz > 0


def _exact(ob, deck):
    """全列挙から W・色／コスト帯の最小最大を出す（小さい局面だけ）。"""
    opp = ob["opp"]
    pool = Counter(deck)
    for cid in list(opp["concerto"]) + list(opp["trash"]) + list(opp["action_area"]):
        if pool[cid] > 0:
            pool[cid] -= 1
    pool_list = [c for c in sorted(pool) for _ in range(pool[c])]
    hands = enumerate_hands(pool_list, opp["hand_count"], list(opp["hand_known"]))
    col = [[_COLOR_IX[ACTION_CARDS[c].color] for c in h] for h, _ in hands]
    band = [[cost_band(ACTION_CARDS[c].cost) for c in h] for h, _ in hands]
    out = []
    for g in range(3):
        xs = [x.count(g) for x in col]
        out += [min(xs), max(xs)]
    for g in range(4):
        xs = [x.count(g) for x in band]
        out += [min(xs), max(xs)]
    return len(hands), out


def test_belief_matches_full_enumeration():
    """W が小さい局面で、W と上下限が全列挙とちょうど一致する（上下限は緩いだけでなく厳密）。"""
    checked = 0
    for cfg, seed in ((mirror_config(SD001), 21), (matchup_config(SD001, SD02), 22),
                      (matchup_config(ANKO, SANGE), 23), (mirror_config(SD02), 24)):
        for py, _ in _states(cfg, seed):
            for pi in (0, 1):
                ob = observe(py, pi)
                deck = cfg.action_decks[1 - pi]
                v = E._belief(ob, deck)
                if v[4] or v[3] > 2 * 11:           # 食い違い、または W > 2^11 は数え上げが重いので飛ばす
                    continue
                w, bounds = _exact(ob, deck)
                assert v[3] == ((w * w).bit_length() - 1)
                assert v[5] == (1 if w == 1 else 0)
                assert v[6:20] == bounds, (seed, pi, py.turn_no)
                checked += 1
    assert checked > 30


def test_belief_is_blind_to_hidden_cards():
    """相手の知らない手札と山札を入れ替えても、v6 の列（信念・統一した既知）は変わらない。"""
    cfg = matchup_config(SD001, SD02)
    rng = random.Random(5)
    n = 0
    for py, _ in _states(cfg, 31):
        if py.turn_no < 3:
            continue
        for pi in (0, 1):
            ob = observe(py, pi)
            base = E.encode(ob, pi, cfg.action_decks[1 - pi])
            t = py.clone()
            opp = t.players[1 - pi]
            # 知らない手札 1 枚を山札の札と入れ替え、山札を混ぜる
            unknown_ix = []
            kc = Counter(ob["opp"]["hand_known"])
            for i, c in enumerate(opp.hand):
                if kc[c] > 0:
                    kc[c] -= 1
                else:
                    unknown_ix.append(i)
            if unknown_ix and opp.action_deck:
                i = unknown_ix[0]
                opp.hand[i], opp.action_deck[0] = opp.action_deck[0], opp.hand[i]
            rng.shuffle(opp.action_deck)
            assert E.encode(observe(t, pi), pi, cfg.action_decks[1 - pi]) == base
            n += 1
        if n > 40:
            break
    assert n > 10


def test_migrated_nets_are_output_identical():
    """移行したネット（v6）と原本（v5・`*.json.enc5.bak.json`）の出力が一致する。"""
    from meicho.drlnet import Net
    root = os.path.join(os.path.dirname(__file__), "..", "results", "models")
    pairs = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if name.endswith(".enc5.bak.json"):
            pairs.append((os.path.join(root, name[:-len(".enc5.bak.json")]), os.path.join(root, name)))
    if not pairs:
        pytest.skip("移行したネットが無い環境")
    cfg = matchup_config(SD001, SD02)
    obs = [(observe(py, pi), pi) for k, (py, _) in enumerate(_states(cfg, 41)) if k % 7 == 0 for pi in (0, 1)][:40]
    for new_p, old_p in pairs:
        with open(old_p, encoding="utf-8") as f:
            old_raw = json.load(f)
        if old_raw.get("encoding_version") != 5:
            continue
        new, old = Net.load(new_p), _load_v5(old_p)
        for ob, pi in obs:
            x6 = np.asarray(E.encode(ob, pi, cfg.action_decks[1 - pi]), np.float32)
            x5 = x6[:E.OBS_DIM_V5]
            assert np.array_equal(new.trunk_out(x6), old.trunk_out(x5)), os.path.basename(new_p)


def _load_v5(path):
    """v5 のネットを寸法検査なしで読む（`Net.load` は現行の OBS_DIM を要求するため）。"""
    from meicho.drlnet import Net
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    net = Net.__new__(Net)
    net.trunk = [(np.asarray(l["w"], np.float32), np.asarray(l["b"], np.float32)) for l in d["trunk"]]
    return net
