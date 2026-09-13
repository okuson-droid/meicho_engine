"""D-065 便 1（探索器のつまみ 5 つ）の検査。`D065_IMPLEMENTATION_PLAN.md` §8 の T-1〜T-8。

固定するのは**結論（強くなるか）ではなく前提**である。強さは便 2 の測定が出す。
ここで守るのは 4 つ。

1. **既定値では一手も変わらない**（新しい引数を足したせいで過去の測定が読めなくなる事故の予防）
2. **Python が真実源、Rust はその写し**（D-049・作業規約 1）。新しいつまみは毎手一致で固定する
3. **覗き見をしていない**（D-026）。`align_leaves` は相手のターンを想像で進める範囲を広げるので必須
4. **記録形式 v3 を足しても v2 が読める**（過去の記録を捨てない）

`meicho_rs` が無い環境、または**入っている Rust が便 1 より古い**環境では、
Rust を要する検査だけ理由つきで skip する（マスターの PC は便 2 の交代まで古い wheel のまま）。
**skip は「通った」ではない。** 便 1 の完了判定は、新しい wheel を入れた作業環境で skip 0 である。
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from experiments.arena import load_deck, mirror_config                    # noqa: E402
from meicho.drlnet import random_net                                      # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,        # noqa: E402
                           legal_actions, observe, outcome)
from meicho.heuristic import HeuristicAgent                               # noqa: E402
from meicho.planner import PlannerAgent                                   # noqa: E402
from meicho.state import Phase                                            # noqa: E402

SD001 = load_deck("SD001")
CONFIG = mirror_config(SD001)
POOL = SD001["action_deck"]
SEED0 = 471100        # 診断の帯の予備（D-065 §7・471100..471999 を検査用に登録した。強さは読まない）


def _rs_has_d065():
    """入っている Rust が便 1 のつまみを知っているか。知らなければ skip（§8 冒頭）。"""
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()                                  # 先にカード表を渡す（未呼び出しだとエラー）
    try:
        rs.PlannerAgent(0, policy_scope="all")      # 便 1 で足した引数。古い wheel では TypeError
    except TypeError:
        pytest.skip("Rust が D-065 便 1 より古い（未再ビルド）。"
                    "作業環境では計画書 §2.9、マスターの PC では §3.5 のあとに通る")
    return rs


def _rand_net_path(tmp_path, name="d065.json", seed=31, hidden=24) -> str:
    """検査用の乱数ネット。一致検査は重みの中身を問わない。"""
    net = random_net(seed=seed, hidden=hidden)
    path = str(tmp_path / name)
    net.save(path)
    from meicho.greedy import forget_net
    forget_net(path)
    try:
        import meicho_rs
        meicho_rs.net_forget(path)
    except ImportError:
        pass
    return path


def _first_phase(seed, phase, pi=0, max_steps=400):
    """人手の要らない進行で、`phase` かつ pi の合法手が 2 つ以上ある局面を 1 つ見つける。"""
    a, b = HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)
    s = initial_state(CONFIG, seed)
    for _ in range(max_steps):
        if outcome(s) is not None:
            return None
        need = decision_players(s)
        if not need:
            return None
        if s.phase == phase and pi in need and len(legal_actions(s, pi)) > 1:
            return s
        s = apply(s, {q: (a if q == 0 else b).act(s, q) for q in sorted(need)})
    return None


def _find(phase, pi=0, tries=40, seed0=SEED0):
    for i in range(tries):
        s = _first_phase(seed0 + i, phase, pi)
        if s is not None:
            return s, seed0 + i
    return None, None


def _match_py_rust(rs, kw, seed=230000, max_steps=60):
    """Python 版と Rust 版が毎手同じ手を選ぶこと（`test_vb_rust_matches_python` の型）。"""
    py_agents = [PlannerAgent(0, **kw), PlannerAgent(1, **kw)]
    rs_agents = [rs.PlannerAgent(0, **kw), rs.PlannerAgent(1, **kw)]
    py = initial_state(CONFIG, seed)
    rss = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, seed)
    steps = 0
    while outcome(py) is None and steps < max_steps:
        assert json.loads(py.to_json()) == json.loads(rss.to_json()), f"state step={steps}"
        need = decision_players(py)
        if not need:
            break
        acts = {}
        for pi in need:
            a_py = py_agents[pi].act(py, pi)
            a_rs = rs_agents[pi].act(rss, pi)
            assert a_py == a_rs, f"step {steps} P{pi}: python {a_py} != rust {a_rs}"
            acts[pi] = a_py
        py = apply(py, acts)
        rss = rs.apply(rss, acts)
        steps += 1
    assert steps >= 20, f"比べた手数が少なすぎる（{steps}）"
    return steps


# --------------------------------------------------------------- T-1 挙動不変

def _needs_torch():
    """**torch が無い環境では skip する。**

    学習側（`drl_train.py` とそれを読む道具）は torch を要る。マスターの PC は学習を回さないので
    入っていないのが正常であり、そこで**落ちる**のは検査の書き方が悪い。
    ただし **skip は「通った」ではない**——学習側の検査は、torch を入れた作業環境で
    **0 skip** になることが完了条件である。
    """
    return pytest.importorskip("torch")

def test_defaults_unchanged_d065():
    """新しい引数の既定値では一手も変わらない（計画書 §1-1）。

    基準は D-054 時点の wheel で取った実対局の digest
    （`meicho/drl_data.BASELINE_DIGESTS_230000`）。ここが動いたら**止める**——
    過去に取ったすべての勝率が比較できなくなる。
    """
    pytest.importorskip("meicho_rs")
    from experiments.arena_rs import PLANNER, ensure_cards, series_rs_digest
    from meicho.drl_data import BASELINE_DIGESTS_230000
    ensure_cards()
    out = series_rs_digest(PLANNER(POOL), PLANNER(POOL), 6, CONFIG, workers=2, seed0=230000)
    assert [r[4] for r in out] == BASELINE_DIGESTS_230000
    # 既定の引数が spec に漏れていないこと
    assert PLANNER(POOL) == {"kind": "planner", "opp_decklist": POOL}
    p = PlannerAgent(0, opp_decklist=POOL)
    assert p.policy_net is None
    assert p.policy_scope == "all"
    assert p.choice_phases is False
    assert p.solo_samples == 1
    assert p.align_leaves is False
    assert p.align_rollout == 80
    assert p.align_stop == "my_turn"
    assert p.opp_mix == 0.0
    assert p.nash_delta == 0.0
    assert p.tau == 0.0
    # 担当フェイズの既定は据え置き（選択フェイズは入らない）
    assert p.phases == {Phase.ACTION, Phase.CLASH_SUBMIT, Phase.RUSH}


# ------------------------------------------------- T-2 代打ち π（Python=Rust）
@pytest.mark.parametrize("scope", ["all", "proxy", "fallback", "proxy_lite"])
def test_policy_net_python_matches_rust(tmp_path, scope):
    """`policy_net`＋`policy_scope` の 3 値すべてで Python 版と Rust 版が毎手一致（§2.2）。

    分岐の**順序**（opp_policy_net → policy_net → 従来）が違うとここで落ちる（§9-1）。
    """
    rs = _rs_has_d065()
    pnet = _rand_net_path(tmp_path, f"pi_{scope}.json", seed=41)
    vnet = _rand_net_path(tmp_path, f"v_{scope}.json", seed=42)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              policy_net=pnet, policy_scope=scope)
    _match_py_rust(rs, kw, seed=230010, max_steps=40)


def test_policy_scope_selects_where_pi_acts(tmp_path):
    """`policy_scope` が代打ち（`_proxy_act`）と担当外の手（`_fallback_act`）を別々に切る（§2.2）。

    `proxy` では担当外フェイズの実際の手が H のまま、`fallback` では代打ちが H のままである。
    """
    pnet = _rand_net_path(tmp_path, "scope.json", seed=43)
    s, seed = _find(Phase.CHOICE)         # CHOICE は既定では担当外＝ fallback の道
    assert s is not None, "CHOICE の局面が見つからない"
    base = dict(opp_decklist=POOL)
    h_move = PlannerAgent(seed, **base).act(s, 0)
    for scope, same_as_h in (("all", False), ("fallback", False), ("proxy", True)):
        a = PlannerAgent(seed, policy_net=pnet, policy_scope=scope, **base).act(s, 0)
        if same_as_h:
            assert a == h_move, f"scope={scope} で担当外の手が π に変わっている"
    # 代打ち側: proxy と all は π、fallback は H（対抗の採点を通して手が変わりうる）
    c, cseed = _find(Phase.CLASH_SUBMIT)
    assert c is not None, "対抗の局面が見つからない"
    seen = {sc: PlannerAgent(cseed, policy_net=pnet, policy_scope=sc, **base)._proxy_act(
        c, 1, 0) for sc in ("all", "proxy", "fallback")}
    assert seen["all"] == seen["proxy"], "代打ちは all と proxy で同じはず"


# ---------------------------------------------- T-3 solo_samples=1 は従来と同じ
def test_solo_samples_1_is_identical():
    """`solo_samples=1` は従来の `_solo` と同じ手（同点処理込み・§2.3）。

    加えて `choice_phases=False` なら CHOICE は従来どおり fallback（H）の手である。
    """
    for phase in (Phase.RUSH, Phase.CHOICE, Phase.TURN_END_DISCARD):
        s, seed = _find(phase)
        if s is None:
            continue
        a = PlannerAgent(seed, opp_decklist=POOL).act(s, 0)
        b = PlannerAgent(seed, opp_decklist=POOL, solo_samples=1).act(s, 0)
        assert a == b, f"{phase} で solo_samples=1 が既定と違う手を選んだ"
    # CHOICE は担当外なので H の手そのもの（作りたての fallback は同じ乱数状態）
    s, seed = _find(Phase.CHOICE)
    assert s is not None
    got = PlannerAgent(seed, opp_decklist=POOL).act(s, 0)
    want = PlannerAgent(seed, opp_decklist=POOL).fallback.act(s, 0)
    assert got == want, "choice_phases=False なのに CHOICE が H の手でない"


# -------------------------------------------- T-4 選択フェイズを V で（一致＋発火）
def test_choice_phases_python_matches_rust(tmp_path):
    """`choice_phases=True, solo_samples=4` で Python 版と Rust 版が毎手一致（§2.3）。"""
    rs = _rs_has_d065()
    vnet = _rand_net_path(tmp_path, "cp.json", seed=44)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              choice_phases=True, solo_samples=4)
    _match_py_rust(rs, kw, seed=230020, max_steps=40)


def test_choice_phases_actually_searches(tmp_path):
    """`choice_phases=True` の CHOICE 決定で葉の採点（V）が呼ばれる（§2.3）。"""
    vnet = _rand_net_path(tmp_path, "cp2.json", seed=45)
    s, seed = _find(Phase.CHOICE)
    assert s is not None
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet)

    def count_eval(agent):
        n = {"n": 0}
        orig = agent._eval

        def wrapped(u, pi):
            n["n"] += 1
            return orig(u, pi)
        agent._eval = wrapped
        return n

    off = PlannerAgent(seed, **kw)
    n_off = count_eval(off)
    off.act(s, 0)
    on = PlannerAgent(seed, choice_phases=True, solo_samples=4, **kw)
    n_on = count_eval(on)
    on.act(s, 0)
    assert n_off["n"] == 0, "choice_phases=False なのに CHOICE で葉を採点している"
    assert n_on["n"] >= 4, f"choice_phases=True で葉の採点が少なすぎる（{n_on['n']}）"


# -------------------------------------------------------- T-5 葉の整列（A-2）
def test_align_leaves_stops_at_my_turn(tmp_path):
    """`align_leaves=True` の葉が「次に自分がターンプレイヤーになるターンの最初の
    非 CHOICE 局面」であること（§2.4）。`False` では従来どおり止まる。
    """
    vnet = _rand_net_path(tmp_path, "al.json", seed=46)
    s, seed = _find(Phase.CLASH_SUBMIT)
    assert s is not None
    goal = s.turn_no + (2 if s.turn_player == 0 else 1)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet)

    def leaves_of(agent):
        got = []
        orig = agent._eval

        def wrapped(u, pi):
            got.append((u.turn_no, u.phase, u.turn_player, u.outcome))
            return orig(u, pi)
        agent._eval = wrapped
        agent.act(s, 0)
        return got

    on = leaves_of(PlannerAgent(seed, align_leaves=True, **kw))
    off = leaves_of(PlannerAgent(seed, **kw))
    assert on and off
    for turn_no, phase, turn_player, oc in on:
        assert (oc is not None or phase == Phase.GAME_OVER
                or (turn_no >= goal and phase != Phase.CHOICE)), \
            f"整列した葉が止まる条件を満たしていない: {(turn_no, phase, turn_player, oc)}"
        if oc is None and phase != Phase.GAME_OVER:
            assert turn_player == 0, "自分のターン開始で止まっていない"
    assert max(t for t, _, _, _ in on) > max(t for t, _, _, _ in off), \
        "align_leaves=True で葉が先に進んでいない"


def test_align_leaves_python_matches_rust(tmp_path):
    """`align_leaves=True` で Python 版と Rust 版が毎手一致（§2.4・CRN の位置も含む）。"""
    rs = _rs_has_d065()
    vnet = _rand_net_path(tmp_path, "alrs.json", seed=47)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet, align_leaves=True)
    _match_py_rust(rs, kw, seed=230030, max_steps=40)


# ------------------------------------- T-2 補: spec 経由とクラス経由が同じであること
def test_spec_and_class_agree(tmp_path):
    """`series`（spec 経由）と `PlannerAgent`（クラス経由）が同じ対局になる（§2.7）。

    毎手一致の検査はクラス経由でしか回せないが、**測定と記録は spec 経由**である。
    ここが食い違うと「検査した AI と測った AI が別物」になる。
    """
    rs = _rs_has_d065()
    vnet = _rand_net_path(tmp_path, "sc_v.json", seed=53)
    pnet = _rand_net_path(tmp_path, "sc_p.json", seed=54)
    kn = dict(extra_turns=1, value_net=vnet, policy_net=pnet, policy_scope="proxy",
              choice_phases=True, solo_samples=2, align_leaves=True, samples=12)
    spec = {"kind": "planner", "opp_decklist": POOL, **kn}
    seed0, n = 471300, 4
    out = rs.series(CONFIG.chara_decks, CONFIG.action_decks, spec, spec, seed0, n, 1, 200)
    for i, r in enumerate(out):
        seed = seed0 + i
        # `run_series` と同じ約束: 席 0 の乱数は seed*2、席 1 は seed*2+1
        ags = [rs.PlannerAgent(seed * 2, opp_decklist=POOL, **kn),
               rs.PlannerAgent(seed * 2 + 1, opp_decklist=POOL, **kn)]
        s = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, seed)
        steps = 0
        while rs.outcome(s) is None and steps < 2000:
            need = rs.decision_players(s)
            if not need:
                break
            s = rs.apply(s, {pi: ags[pi].act(s, pi) for pi in need})
            steps += 1
        st = json.loads(s.to_json())
        winner, turns = rs.outcome(s), st["turn_no"]
        a_seat = 1 if seed % 2 == 1 else 0
        won = None if winner is None or winner < 0 else (winner == a_seat)
        assert (r[0], r[1]) == (won, turns), f"seed={seed}: spec {r[:2]} != class {(won, turns)}"


# ------------------ 追加: 速度の手当て（proxy_lite）と葉の整列の別解（turn_end）
def test_proxy_lite_narrows_where_pi_is_used(tmp_path):
    """`policy_scope="proxy_lite"` は代打ちのうち**相手の ACTION と自分の対抗**だけ π（§9-4 (a)）。

    速度の手当てである。効く場所を絞りすぎて「π をまったく使っていない」状態に
    なっていないことと、絞った場所以外は H に戻っていることを固定する。
    """
    pnet = _rand_net_path(tmp_path, "lite.json", seed=61)
    c, cseed = _find(Phase.CLASH_SUBMIT)
    assert c is not None
    base = dict(opp_decklist=POOL)
    lite = PlannerAgent(cseed, policy_net=pnet, policy_scope="proxy_lite", **base)
    full = PlannerAgent(cseed, policy_net=pnet, policy_scope="proxy", **base)
    plain = PlannerAgent(cseed, **base)
    # 自分の対抗の提出は π（proxy と同じ）
    assert lite._proxy_act(c, 0, 0) == full._proxy_act(c, 0, 0)
    # 相手の連撃・選択などは H に戻る（π を使う範囲の外）
    s, seed = _find(Phase.CHOICE)
    assert s is not None
    l2 = PlannerAgent(seed, policy_net=pnet, policy_scope="proxy_lite", **base)
    p2 = PlannerAgent(seed, **base)
    assert l2._proxy_act(s, 0, 1) == p2._proxy_act(s, 0, 1), "自分の選択の代打ちは H のはず"


def test_align_stop_turn_end_is_shorter(tmp_path):
    """`align_stop="turn_end"`（§2.4 の別解）は葉を**いま進行中のターンの終わり**で止める。

    自分のアクションフェイズ中の選択（レベルアップの捨て札など）の葉が、計画探索の
    `to_clash` の葉と同じ地点になる。対抗・連撃では `_settle` がすでにそこで止まっているので
    **従来と同じ葉**である（＝ここが本案 `my_turn` との違い）。
    """
    vnet = _rand_net_path(tmp_path, "turnend.json", seed=62)
    s, seed = _find(Phase.CHOICE)
    assert s is not None
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              choice_phases=True, solo_samples=2)

    def leaf_turns(agent):
        got = []
        orig = agent._eval

        def wrapped(u, pi):
            got.append(u.turn_no)
            return orig(u, pi)
        agent._eval = wrapped
        agent.act(s, 0)
        return got

    off = leaf_turns(PlannerAgent(seed, **kw))
    end = leaf_turns(PlannerAgent(seed, align_leaves=True, align_stop="turn_end", **kw))
    mine = leaf_turns(PlannerAgent(seed, align_leaves=True, **kw))
    assert max(off) <= max(end) <= max(mine), \
        f"別解の葉は本案より手前で止まるはず: {max(off)} / {max(end)} / {max(mine)}"
    assert max(end) > max(off), "turn_end で葉が進んでいない"
    # 対抗の決定では本案と違い、従来と同じ葉のまま
    c, cseed = _find(Phase.CLASH_SUBMIT)
    assert c is not None

    def clash_leaf_turns(agent):
        got = []
        orig = agent._eval

        def wrapped(u, pi):
            got.append(u.turn_no)
            return orig(u, pi)
        agent._eval = wrapped
        agent.act(c, 0)
        return got

    base_kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet)
    c_off = clash_leaf_turns(PlannerAgent(cseed, **base_kw))
    c_end = clash_leaf_turns(PlannerAgent(cseed, align_leaves=True,
                                          align_stop="turn_end", **base_kw))
    assert max(c_end) == max(c_off), "対抗の葉は別解では従来と同じはず"


def test_new_knobs_python_matches_rust(tmp_path):
    """`proxy_lite` と `align_stop="turn_end"` でも Python 版と Rust 版が毎手一致。"""
    rs = _rs_has_d065()
    vnet = _rand_net_path(tmp_path, "nk_v.json", seed=63)
    pnet = _rand_net_path(tmp_path, "nk_p.json", seed=64)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet, policy_net=pnet,
              policy_scope="proxy_lite", choice_phases=True, solo_samples=2,
              align_leaves=True, align_stop="turn_end")
    _match_py_rust(rs, kw, seed=230050, max_steps=40)


# ------------------------------- T-14 対人 2 局の回帰局面（A-8・計画書 §12.3）
HUMAN_GAMES = os.path.join(os.path.dirname(__file__), "..", "results",
                           "human_games", "2026-09.jsonl")


def _human_clash_positions():
    """対人 2 局（g001/g002）の**負けを決めた対抗**の局面を記録から再生して返す。

    返すのは [(game_id, 局面, AI の席, 記録にあるエージェントのシード)]。
    """
    from verify_lethal_human import last_clash_state
    from webapp import record as wrec
    with open(HUMAN_GAMES, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    out = []
    for rec in recs:
        if rec["opponent"]["name"] != "planner_vb3":
            continue
        st = wrec.replay(rec, CONFIG, keep_states=True)
        s = last_clash_state(st["states"])
        if s is not None:
            out.append((rec["game_id"], s, 1 - rec["human_seat"],
                        rec["opponent"].get("seed", 0)))
    return out


def _submitted_name(s, pi, a) -> str:
    from meicho.cards import ACTION_CARDS
    if a["type"] != "submit":
        return a["type"]
    return ACTION_CARDS[s.players[pi].hand[a["hand"]]].name


@pytest.mark.skipif(not os.path.exists(HUMAN_GAMES), reason="対人の記録が無い環境")
def test_opp_mix_fixes_the_human_positions():
    """A-8 の回帰局面（計画書 §12.3・`HUMAN_GAMES_20260903_NOTES.md`）。

    マスターが champion に勝った 2 局は、どちらも**詰みの烈火を持っていたのに
    パス／青で受けた**負けだった。原因は対抗の相手モデルが「π₀ の最尤 1 手」だけを
    見ることで、マスターが実際に出した安い赤・緑の列が評価から消えていたことである。

    ここで固定するのは 2 つ:
    1. `opp_mix=0`（既定）は**当時と同じ手**を選ぶ（旧挙動の固定。変わったら fingerprint も疑う）
    2. `opp_mix=1.0` は**両局面とも燃える烈火**を選ぶ（試作 `proto_matrix_clash.py` の uniform の再現）
    """
    # **旧 champion（`planner_vb3cps`・葉 V_3）の spec を明示**して固定する（便 E-0・§4.3）。
    # `champion.kwargs_for` を動的に読むと、交代した瞬間に `want_old` の意味が
    # 「当時の挙動」から「今の champion の挙動」に化ける。**新 champion に合わせて
    # `want_old` を書き換えてはいけない**——それは「直った」ではない。
    from tests.test_champion_vc4 import OLD_CHAMPION_KWARGS, resolved_kwargs
    kw = resolved_kwargs(OLD_CHAMPION_KWARGS)
    want_old = {"g001": "pass", "g002": "音の形・回避"}
    pos = _human_clash_positions()
    assert len(pos) >= 2, f"回帰局面が足りない: {[p[0] for p in pos]}"
    for gid, s, ai, seed in pos:
        old = PlannerAgent(seed, opp_decklist=POOL, **kw).act(s, ai)
        assert _submitted_name(s, ai, old) == want_old[gid], \
            f"{gid}: 既定の挙動が変わった（{_submitted_name(s, ai, old)}）"
        new = PlannerAgent(seed, opp_decklist=POOL, opp_mix=1.0, **kw).act(s, ai)
        assert _submitted_name(s, ai, new) == "燃える烈火", \
            f"{gid}: opp_mix=1.0 でも烈火を選ばない（{_submitted_name(s, ai, new)}）"


def test_opp_mix_python_matches_rust(tmp_path):
    """`opp_mix` でも Python 版と Rust 版が毎手一致（列の順序と足す順序まで同じであること）。"""
    rs = _rs_has_d065()
    vnet = _rand_net_path(tmp_path, "om_v.json", seed=71)
    pnet = _rand_net_path(tmp_path, "om_p.json", seed=72)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              opp_policy_net=pnet, opp_policy_root_only=True, opp_mix=0.5)
    _match_py_rust(rs, kw, seed=230060, max_steps=40)


# ------------------------------------------------------------ T-6 覗き見監査
def test_nopeek_audit_d065(tmp_path):
    """新しいつまみを全部入れた構成で隠蔽情報を参照していないこと（D-026）。

    `align_leaves` は**相手のターンを想像で進める範囲を広げる**。そこで実際の
    相手の手札や山札の順序を覗けば強くなって当然で、便 2 の測定は無意味になる。
    """
    from meicho.audit import replay_audit
    vnet = _rand_net_path(tmp_path, "audit_v.json", seed=48)
    pnet = _rand_net_path(tmp_path, "audit_p.json", seed=49)
    r = replay_audit(
        lambda sd: PlannerAgent(sd, opp_decklist=POOL, extra_turns=1, value_net=vnet,
                                policy_net=pnet, policy_scope="proxy",
                                choice_phases=True, solo_samples=2,
                                align_leaves=True, samples=12),
        lambda sd: HeuristicAgent(sd),
        CONFIG, POOL, n_games=2, variants=2, node_cap=120)
    assert r["checked"] >= 40, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"


# ------------------------------------------------------------------ T-7 tau
def test_tau_zero_consumes_no_randomness(tmp_path):
    """`tau=0` は抽選の乱数を消費しない（§2.6）。

    探索そのもの（`_determinize`）は当然 `self.rng` を使うので、ここで見るのは
    **抽選（`soft_pick`）が乱数を引かないこと**と、担当外フェイズの手を π で埋める
    経路（`_fallback_act`）が `tau=0` では乱数を消費しないことである。
    """
    import random
    from meicho.greedy import soft_pick
    rng = random.Random(7)
    st = rng.getstate()
    assert soft_pick([0.1, 0.9, 0.9], 0.0, rng) == 1, "tau=0 は最大（同点は最初）"
    assert rng.getstate() == st, "tau=0 で乱数を消費した"
    assert soft_pick([0.5], 0.3, rng) == 0 and rng.getstate() == st, "候補 1 つでは引かない"

    pnet = _rand_net_path(tmp_path, "tau0.json", seed=50)
    s, seed = _find(Phase.CHOICE)          # 担当外フェイズ＝ `_fallback_act` の道
    assert s is not None
    ag = PlannerAgent(seed, opp_decklist=POOL, policy_net=pnet, policy_scope="fallback")
    before = ag.rng.getstate()
    ag.act(s, 0)
    assert ag.rng.getstate() == before, "tau=0 の fallback で乱数を消費した"


def test_tau_python_matches_rust(tmp_path):
    """`tau=0.01` で Python 版と Rust 版が同じ手を選ぶ（§2.6）。

    両者の rng は同じ PyRandom の写しなので、**消費の順序が同じなら一致する**。
    一致しなければ消費の順序が違う。
    """
    rs = _rs_has_d065()
    vnet = _rand_net_path(tmp_path, "tau.json", seed=51)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet, tau=0.01)
    _match_py_rust(rs, kw, seed=230040, max_steps=40)


# --------------------------------------------------- T-8 記録形式 v3（fresh）
def _v2_bytes(obs_dim: int, acl: int) -> bytes:
    """版 2 の記録を手で作る（過去の記録が読めることの回帰検査用）。"""
    head = struct.pack("<4sIII", b"MCDR", 2, obs_dim, acl)
    rec = struct.pack("<qIHBBBBf", 12345, 3, 7, 1, 3, 2, 0, 1.0)
    rec += bytes(obs_dim) + bytes(2 * acl) + struct.pack("<2f", 0.4, 0.6)
    return head + rec


def test_record_v2_is_still_readable(tmp_path):
    """v3 を足しても**過去の v2 の記録が読める**（§2.5）。`fresh` は NaN で埋まる。"""
    from meicho.drl_data import read_records
    from meicho.encode import ACT_CODE_LEN, OBS_DIM
    p = tmp_path / "v2.bin"
    p.write_bytes(_v2_bytes(OBS_DIM, ACT_CODE_LEN))
    r = read_records([str(p)])
    assert r.n == 1 and r.z[0] == 1.0 and r.n_acts[0] == 2
    assert list(r.scores_of(0)) == [pytest.approx(0.4), pytest.approx(0.6)]
    assert math.isnan(float(r.fresh[0])), "v2 の fresh は NaN で埋めること"


@pytest.mark.parametrize("reeval", [0, 2])
def test_record_v3_fresh(tmp_path, reeval):
    """`series_record` の出力が v3 で `fresh` を持つ（§2.5）。

    `reeval_samples=0` なら NaN（探索は 1 回も増えない）。`>0` なら選んだ手を
    **別の決定化で取り直した値**が [0,1] に入る（葉が V なので勝率の尺度）。
    """
    rs = _rs_has_d065()
    from meicho.drl_data import read_records
    vnet = _rand_net_path(tmp_path, f"rec{reeval}.json", seed=52)
    spec = {"kind": "planner", "opp_decklist": POOL, "extra_turns": 1,
            "value_net": vnet, "reeval_samples": reeval}
    out = str(tmp_path / f"rec{reeval}")
    _res, files = rs.series_record(CONFIG.chara_decks, CONFIG.action_decks,
                                   spec, spec, 471200, 2, out, 1, 200, True, False)
    r = read_records(files)
    assert r.n > 10, f"記録が少なすぎる（{r.n}）"
    assert r.fresh.shape == (r.n,)
    # 探索した決定＝合法手のどれかに探索値が入っている決定
    # （計画探索は「1 手目として残った手」だけに値を付けるので、先頭の手が NaN でも
    #   探索していないとは限らない。ここを取り違えると検査が嘘をつく）
    searched = np.array([not np.isnan(r.scores_of(i)).all() for i in range(r.n)])
    fresh = r.fresh[searched]
    if reeval == 0:
        assert np.isnan(r.fresh).all(), "reeval_samples=0 なのに fresh が入っている"
    else:
        ok = fresh[~np.isnan(fresh)]
        assert ok.size > 0, "reeval_samples>0 なのに fresh が全部 NaN"
        assert ((ok >= 0.0) & (ok <= 1.0)).all(), f"fresh が [0,1] を外れた: {ok.min()}..{ok.max()}"
    # 探索していない決定は必ず NaN
    assert np.isnan(r.fresh[~searched]).all(), "探索していない決定に fresh が入っている"


# ------------------------------------------------------------ T-15 A-9 nash_delta
def test_nash_col_solves_known_matrices():
    """`nash_col` が既知の行列ゲームを解けること（乱数を引かない決定的な手続き）。

    A-9 の土台なので、ここが狂うと均衡値も候補の絞り込みも全部狂う。
    """
    from meicho.greedy import nash_col
    # 1. マッチングペニー（行=最大化・列=最小化）の均衡は列も 1/2 ずつ
    pc = nash_col([[1.0, -1.0], [-1.0, 1.0]])
    assert len(pc) == 2
    assert abs(pc[0] - 0.5) < 0.02, pc
    # 2. 列 0 が列 1 を支配する（相手は最小化するので小さい列を選ぶ）
    pc = nash_col([[0.0, 1.0], [0.0, 1.0]])
    assert pc[0] > 0.9, pc
    # 3. 列が 1 本しかなければ確率 1
    assert nash_col([[0.3], [0.7]]) == [1.0]
    # 4. 二度呼んでも同じ（乱数を引かない）
    m = [[0.2, 0.9, 0.4], [0.7, 0.1, 0.5], [0.3, 0.6, 0.8]]
    assert nash_col(m) == nash_col(m)


def test_nash_delta_defaults_off_and_rejects_bad_combinations():
    """既定 0 で挙動不変。二重に効く組み合わせは受け付けない（`D065_NOTES.md` A-9）。"""
    kw = dict(opp_decklist=POOL, extra_turns=1)
    assert PlannerAgent(1, **kw).nash_delta == 0.0
    with pytest.raises(ValueError):
        PlannerAgent(1, nash_delta=-0.1, **kw)
    with pytest.raises(ValueError):
        PlannerAgent(1, nash_delta=0.05, opp_mix=0.5, **kw)
    with pytest.raises(ValueError):
        PlannerAgent(1, nash_delta=0.05, tau=0.5, **kw)


def test_nash_delta_zero_matches_the_default_path():
    """`nash_delta=0` は既定の道と**一手も**変わらない（fingerprint を守る条件）。"""
    kw = dict(opp_decklist=POOL, extra_turns=1)
    for seed in (471400, 471401):
        a = PlannerAgent(seed, **kw)
        b = PlannerAgent(seed, nash_delta=0.0, **kw)
        s = initial_state(CONFIG, seed)
        for _ in range(60):
            if s.phase == Phase.GAME_OVER:
                break
            dp = decision_players(s)
            moves = {}
            for q in dp:
                x, y = a.act(s, q), b.act(s, q)
                assert x == y, f"seed {seed} で手が割れた: {x} / {y}"
                moves[q] = x
            s = apply(s, moves)


@pytest.mark.skipif(not os.path.exists(HUMAN_GAMES), reason="対人の記録が無い環境")
def test_nash_delta_fixes_the_human_positions():
    """A-9 の回帰局面（`D065_NOTES.md` A-9）。均衡だけでは直らず、δ を許すと直る。

    ここで固定するのは 3 つ:
    1. `nash_delta=0`（既定）は当時と同じ手（旧挙動の固定）
    2. **均衡そのもの（δ を極小にした状態）でも当時と同じ手**
       ——「均衡解なら勝てたはず」ではないことの証拠。搾取しないのが均衡だからである。
    3. `nash_delta=0.06` は両局面とも燃える烈火
    """
    # **旧 champion（`planner_vb3cps`・葉 V_3）の spec を明示**して固定する（便 E-0・§4.3）。
    # `champion.kwargs_for` を動的に読むと、交代した瞬間に `want_old` の意味が
    # 「当時の挙動」から「今の champion の挙動」に化ける。**新 champion に合わせて
    # `want_old` を書き換えてはいけない**——それは「直った」ではない。
    from tests.test_champion_vc4 import OLD_CHAMPION_KWARGS, resolved_kwargs
    kw = resolved_kwargs(OLD_CHAMPION_KWARGS)
    want_old = {"g001": "pass", "g002": "音の形・回避"}
    pos = _human_clash_positions()
    assert len(pos) >= 2, f"回帰局面が足りない: {[p[0] for p in pos]}"
    for gid, s, ai, seed in pos:
        old = PlannerAgent(seed, opp_decklist=POOL, **kw).act(s, ai)
        assert _submitted_name(s, ai, old) == want_old[gid], \
            f"{gid}: 既定の挙動が変わった（{_submitted_name(s, ai, old)}）"
        eq = PlannerAgent(seed, opp_decklist=POOL, nash_delta=1e-9, **kw).act(s, ai)
        assert _submitted_name(s, ai, eq) == want_old[gid], \
            f"{gid}: 均衡だけで手が変わった（{_submitted_name(s, ai, eq)}）"
        new = PlannerAgent(seed, opp_decklist=POOL, nash_delta=0.06, **kw).act(s, ai)
        assert _submitted_name(s, ai, new) == "燃える烈火", \
            f"{gid}: nash_delta=0.06 でも烈火を選ばない（{_submitted_name(s, ai, new)}）"


def test_nash_delta_python_matches_rust(tmp_path):
    """`nash_delta` でも Python 版と Rust 版が毎手一致（regret matching の足す順序まで同じであること）。

    行列の列の順序・`nash_col` の反復・候補の絞り込みとその同点処理のどれが食い違っても、
    ここで手が割れる。
    """
    rs = _rs_has_d065()
    vnet = _rand_net_path(tmp_path, "nd_v.json", seed=81)
    pnet = _rand_net_path(tmp_path, "nd_p.json", seed=82)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              opp_policy_net=pnet, opp_policy_root_only=True, nash_delta=0.06)
    _match_py_rust(rs, kw, seed=230070, max_steps=40)


def test_nash_delta_spec_and_class_agree(tmp_path):
    """spec 経由（測定・記録の道）とクラス経由（毎手一致検査の道）が同じ対局になる（§2.7）。"""
    rs = _rs_has_d065()
    from experiments.arena_rs import series_rs_digest
    vnet = _rand_net_path(tmp_path, "nd_spec.json", seed=83)
    spec = {"kind": "planner", "opp_decklist": POOL, "extra_turns": 1,
            "value_net": vnet, "nash_delta": 0.06}
    a = series_rs_digest(spec, spec, 2, CONFIG, workers=1, seed0=471310)
    b = series_rs_digest(spec, spec, 2, CONFIG, workers=1, seed0=471310)
    assert [r[4] for r in a] == [r[4] for r in b], "spec 経由が再現しない"
    # nash_delta を spec から外すと別の対局になる（＝鍵が効いている）
    plain = {k: v for k, v in spec.items() if k != "nash_delta"}
    c = series_rs_digest(plain, plain, 2, CONFIG, workers=1, seed0=471310)
    assert [r[4] for r in a] != [r[4] for r in c], "spec の nash_delta が効いていない"


# =========================================================== 便 3（学習側・Python だけ）
# T-16〜T-21。**Rust は一切触っていない**ので、ここは再ビルドの有無に関わらず全部走る。
#
# 固定するのは 便 1・便 2 と同じく**前提**である。「学習条件を変えると強くなるか」は
# 便 4 の門番が答えるものであって、検査が答えるものではない。ここで守るのは 4 つ。
#
# 1. **既定値では学習の中身が 1 ビットも変わらない**（新しい選択肢を足したせいで
#    過去の版が再現しなくなる事故の予防。便 1 の T-1 と同じ考え方）
# 2. `--vtarget fresh` は「取り直した値があればそれ・無ければ最大値」であること
# 3. `--calib-by phase_turn` は**層ごとに違う変換**を当て、薄い層は全体に落とすこと
# 4. `--select target_v` が `best_v` と**別物として**選ばれること
# 5. 記録の manifest に「作り直すコマンド」と「本当の版」が入ること（引継ぎ書 §2.1 の課題）


def _fake_records(n=4000, seed=7, n_acts=3, fresh_frac=0.5, opposite_strata=True):
    """検査用の記録を手で作る（対局は回さない）。

    `opposite_strata=True` のとき、**層によって探索値と勝敗の向きを逆にする**。
    全体 1 本の変換ではどちらの層にも合わせられないので、層別較正が効くかどうかを
    はっきり測れる（効かない実装なら対数損失が下がらない）。
    """
    from meicho.drl_data import Records
    from meicho.encode import ACT_CODE_LEN, OBS_DIM
    rng = np.random.RandomState(seed)
    phase = np.where(rng.rand(n) < 0.5, 2, 3).astype(np.int8)      # action / clash
    turn = (rng.rand(n) < 0.5).astype(np.int8)
    obs = np.zeros((n, OBS_DIM), np.int8)
    obs[:, 0] = rng.randint(-100, 100, n)      # 局面ごとに違いを持たせる（V が定数にならないように）
    obs[:, 14] = turn
    v = rng.randn(n).astype(np.float32)                             # 探索値（本体・番兵なし）
    sign = np.where(turn == 1, 1.0, -1.0) if opposite_strata else np.ones(n)
    p = 1.0 / (1.0 + np.exp(-3.0 * sign * v))
    z = (rng.rand(n) < p).astype(np.float32)
    chosen = rng.randint(0, n_acts, n).astype(np.int16)
    scores = np.zeros(n * n_acts, np.float32)
    for i in range(n):
        s = np.full(n_acts, -9.0, np.float32)
        s[chosen[i]] = v[i]                       # 選んだ手が最大になるように置く
        scores[i * n_acts:(i + 1) * n_acts] = s
    fresh = np.full(n, np.nan, np.float32)
    m = rng.rand(n) < fresh_frac
    fresh[m] = (v[m] - 0.5).astype(np.float32)    # 取り直すと **0.5 だけ低く出る**（＝楽観の分）
    off = np.arange(n + 1, dtype=np.int64) * n_acts
    # 行動の符号は**手ごとに違う値**にする。全部同じにすると、どの手も同じ入力になり
    # 方策の出力が一様になってしまう（π を見る検査が「常に一致」で素通りする）。
    acts = np.zeros((n * n_acts, ACT_CODE_LEN), np.int8)
    for j in range(n_acts):
        acts[j::n_acts, 0] = j % 5
        acts[j::n_acts, 1] = (j * 3) % 7
        acts[j::n_acts, 2] = (j * 5) % 3
    return Records(n=n, seed=np.arange(n, dtype=np.int64), step=np.zeros(n, np.int32),
                   turn=np.zeros(n, np.int16), pi=np.zeros(n, np.int8), phase=phase,
                   n_acts=np.full(n, n_acts, np.int16), chosen=chosen, z=z, fresh=fresh,
                   obs=obs, act_off=off,
                   acts_flat=acts, scores_flat=scores)


# ------------------------------------------------ T-16 既定不変（便 3 の T-1 にあたる）
def test_train_defaults_unchanged_d065_bin3():
    """新しい選択肢を足しても、**既定のまま作った教師は 1 ビットも変わらない**。

    `--vtarget max`（既定）で作った `vsearch` が「その決定の探索値の最大値」のままであること、
    `--lam 0`（既定）なら教師が勝敗 z そのままであること、
    `--calib-by none`（既定）の較正が層を一切見ないことを固定する。
    """
    _needs_torch()
    from experiments.drl_train import Batcher, apply_calibration, calibrate_vsearch
    r = _fake_records(n=2000, seed=11)
    b = Batcher(r)                                   # 既定 = vtarget max / lam 0
    assert b.vtarget == "max"
    exp = np.array([np.nanmax(r.scores_of(i)) for i in range(r.n)], np.float32)
    assert np.allclose(b.vsearch, exp), "既定の教師の作り方が変わっている"
    assert np.array_equal(b.target, b.z), "--lam 0 の教師は z そのままであること"
    # 全体 1 本の較正は、層を渡しても渡さなくても同じ答えを返す
    c = calibrate_vsearch(b.vsearch, b.z, min_n=100)
    assert "strata" not in c
    assert np.allclose(apply_calibration(b.vsearch, c),
                       apply_calibration(b.vsearch, c, b.stratum))


def test_turn_flag_column_is_where_we_think_it_is():
    """層の鍵に使う観測の 15 番目（添字 14）が本当に「いま自分のターンか」であること。

    ここがずれると層の意味が静かに壊れる（誤りが数字に出ない種類の事故）。
    **実際の局面を符号化して確かめる**。
    """
    _needs_torch()
    from experiments.drl_train import TURN_FLAG_COL
    from meicho.encode import encode
    s = initial_state(CONFIG, seed=SEED0 + 5)
    for _ in range(200):
        ds = decision_players(s)
        if not ds:
            break
        for pi in (0, 1):
            obs = encode(observe(s, pi), pi)
            assert obs[TURN_FLAG_COL] == (1 if s.turn_player == pi else 0), \
                f"添字 {TURN_FLAG_COL} は「自分のターンか」ではない"
        acts = {p: legal_actions(s, p) for p in ds}
        s = apply(s, {p: acts[p][0] for p in ds})
        if outcome(s) is not None:
            break


# ------------------------------------------------------------ T-17 --vtarget fresh
def test_vtarget_fresh_uses_fresh_and_falls_back_to_max():
    """取り直した値があればそれを使い、無ければ最大値で埋める（§4.1）。"""
    _needs_torch()
    from experiments.drl_train import Batcher
    r = _fake_records(n=1500, seed=13, fresh_frac=0.5)
    b = Batcher(r, vtarget="fresh")
    has = np.isfinite(r.fresh)
    assert 0 < has.sum() < r.n, "検査の材料が偏っている"
    assert np.allclose(b.vsearch[has], r.fresh[has]), "取り直した値を使っていない"
    mx = np.array([np.nanmax(r.scores_of(i)) for i in range(r.n)], np.float32)
    assert np.allclose(b.vsearch[~has], mx[~has]), "取り直した値が無いところは最大値で埋めること"
    assert b.n_fresh_used == int(has.sum())


def test_vtarget_fresh_on_v2_records_equals_max():
    """**版 2 の記録（`fresh` が無い）では `fresh` 指定が `max` と完全に同じになる。**

    過去の記録をそのまま回せることの保証である。
    """
    _needs_torch()
    from experiments.drl_train import Batcher
    r = _fake_records(n=800, seed=17, fresh_frac=0.0)     # v2 相当（fresh 全部 NaN）
    a = Batcher(r, vtarget="max")
    b = Batcher(r, vtarget="fresh")
    assert np.allclose(a.vsearch, b.vsearch, equal_nan=True)
    assert b.n_fresh_used == 0


# ------------------------------------------------------- T-18 --calib-by phase_turn
def test_calibration_by_strata_beats_one_curve_when_strata_differ():
    """層で探索値の意味が逆なら、層別較正は全体 1 本より**はっきり当たる**。

    「対数損失」= 予測の外し具合（低いほど良い。当てずっぽうで 0.693）。
    """
    _needs_torch()
    from experiments.drl_train import calibrate_vsearch, calibrate_vsearch_strata
    r = _fake_records(n=6000, seed=19, opposite_strata=True)
    from experiments.drl_train import Batcher
    b = Batcher(r)
    one = calibrate_vsearch(b.vsearch, b.z, min_n=100)
    many = calibrate_vsearch_strata(b.vsearch, b.z, b.stratum, min_n=100)
    assert many["by"] == "phase_turn"
    assert len(many["strata"]) == 4, f"層が 4 つ出るはず: {sorted(many['strata'])}"
    assert many["logloss"] < one["logloss"] - 0.05, \
        f"層別にした意味が出ていない（{many['logloss']:.4f} vs {one['logloss']:.4f}）"
    assert many["useful"]


def test_thin_strata_fall_back_to_the_overall_calibration():
    """決定が少ない層は全体の較正に落とす（数十件から取った変換を信じない）。"""
    _needs_torch()
    from experiments.drl_train import Batcher, apply_calibration, calibrate_vsearch_strata
    r = _fake_records(n=3000, seed=23)
    b = Batcher(r)
    st = b.stratum.copy()
    st[:20] = 99                      # 20 件だけの薄い層を作る
    c = calibrate_vsearch_strata(b.vsearch, b.z, st, min_n=100)
    assert "99" not in c["strata"], "薄い層から較正を取ってしまっている"
    assert any(f["key"] == 99 and f["n"] == 20 for f in c["fallback"])
    p = apply_calibration(b.vsearch, c, st)
    overall = apply_calibration(b.vsearch, c["overall"])
    assert np.allclose(p[:20], overall[:20]), "薄い層に全体の較正が当たっていない"


def test_strata_calibration_changes_the_teacher():
    """層別にすると教師（V の学習目標）が実際に変わること＝つまみが繋がっている。"""
    _needs_torch()
    from experiments.drl_train import Batcher, calibrate_vsearch, calibrate_vsearch_strata
    r = _fake_records(n=6000, seed=29, opposite_strata=True)
    b1, b2 = Batcher(r), Batcher(r)
    b1.set_lam(0.7, calibrate_vsearch(b1.vsearch, b1.z, min_n=100))
    b2.set_lam(0.7, calibrate_vsearch_strata(b2.vsearch, b2.z, b2.stratum, min_n=100))
    assert not np.allclose(b1.target, b2.target), "--calib-by が教師に効いていない"


# ------------------------------------------------------------- T-19 --select target_v
def test_target_v_is_a_different_key_from_best_v():
    """`target_v` が `best_v` に化けないこと。

    `select.split("_")[1]` で鍵を作ると `target_v` → `"v"` になり、
    **別物を指定したつもりで同じ版が保存される**。表で引くことで防ぐ。
    """
    _needs_torch()
    from experiments.drl_train import BestKeeper
    assert BestKeeper.KEYS["best_v"] == "v"
    assert BestKeeper.KEYS["target_v"] == "t"
    k = BestKeeper()
    k.offer(1, {"v_logloss": 0.60, "p_logloss": 0.9, "t_logloss": 0.50}, {"ep": 1})
    k.offer(2, {"v_logloss": 0.55, "p_logloss": 0.8, "t_logloss": 0.70}, {"ep": 2})
    assert k.pick("best_v")[2] == 2, "best_v は z に対する損失で選ぶ"
    assert k.pick("target_v")[2] == 1, "target_v は教師に対する損失で選ぶ"


def test_t_logloss_equals_v_logloss_when_lam_is_zero():
    """`--lam 0` では教師 = z なので、2 つの損失は一致する（別物を足しても既定は不変）。"""
    _needs_torch()
    import torch
    from experiments.drl_train import Batcher, TwoHead, evaluate
    r = _fake_records(n=600, seed=31)
    b = Batcher(r)
    torch.manual_seed(0)
    m = TwoHead(hidden=16, depth=1, phead=8)
    ev = evaluate(m, b)
    assert ev["t_logloss"] == pytest.approx(ev["v_logloss"], abs=1e-6)


def test_t_logloss_differs_when_lam_is_positive():
    """混合した教師を使うと、2 つの損失は別の数になる（＝ target_v が意味を持つ）。"""
    _needs_torch()
    import torch
    from experiments.drl_train import Batcher, TwoHead, calibrate_vsearch, evaluate
    r = _fake_records(n=3000, seed=37)
    b = Batcher(r)
    b.set_lam(0.7, calibrate_vsearch(b.vsearch, b.z, min_n=100))
    torch.manual_seed(0)
    m = TwoHead(hidden=16, depth=1, phead=8)
    ev = evaluate(m, b)
    assert abs(ev["t_logloss"] - ev["v_logloss"]) > 1e-3


# --------------------------------------------------------------- T-20 楽観の診断
def test_diag_optimism_measures_the_gap(tmp_path):
    """`diag_optimism` が層ごとに z・root・fresh を並べ、**楽観を対で測る**こと。

    材料の作り方から、`root − fresh` はどの層でも 0.5 になる（取り直すと 0.5 低く出る）。
    """
    _needs_torch()
    from experiments.diag_optimism import collect
    import experiments.diag_optimism as dg
    r = _fake_records(n=2000, seed=41, fresh_frac=0.6)
    # `collect` は記録を読み直すので、読み込みだけ差し替えて材料を渡す
    orig_read, orig_files = dg.read_records, dg.files_of
    dg.read_records = lambda paths, mx=None: r
    dg.files_of = lambda pre: ["dummy"]
    try:
        out = collect("dummy", None)
    finally:
        dg.read_records, dg.files_of = orig_read, orig_files
    assert out["rows"][0]["name"] == "全体" and out["rows"][0]["n"] == r.n
    assert len(out["rows"]) == 1 + 4, "全体 + 層 4 つの行が出るはず"
    assert sum(row["n"] for row in out["rows"][1:]) == r.n, "層の件数の合計が全体と合わない"
    for row in out["rows"]:
        assert row["root_minus_fresh"] == pytest.approx(0.5, abs=1e-5), \
            "楽観（root − fresh）を対で測れていない"
    assert "root−fr" in dg.render(out)


def test_diag_optimism_pairs_instead_of_subtracting_means():
    """差は**同じ決定で対にして**取ること（別々の平均を引き算しない）。"""
    _needs_torch()
    from experiments.diag_optimism import _diff, _mean
    a = np.array([1.0, 2.0, np.nan])
    b = np.array([0.0, np.nan, 5.0])
    assert _diff(a, b) == pytest.approx(1.0)          # 対になるのは 1 件目だけ
    assert _mean(a) == pytest.approx(1.5)


# ------------------------------------------- T-21 manifest（引継ぎ書 §2.1 の課題）
def test_manifest_records_the_real_format(tmp_path):
    """manifest の `format` を決め打ちにしない。**書けたファイルの版を読む**。"""
    from experiments.drl_record import record_format
    from meicho.encode import ACT_CODE_LEN, OBS_DIM
    v2 = tmp_path / "a.0"
    v2.write_bytes(_v2_bytes(OBS_DIM, ACT_CODE_LEN))
    v3 = tmp_path / "a.1"
    v3.write_bytes(struct.pack("<4sIII", b"MCDR", 3, OBS_DIM, ACT_CODE_LEN))
    assert record_format([str(v2)]) == "MCDR v2"
    assert record_format([str(v3)]) == "MCDR v3"
    assert record_format([str(v2), str(v3)]) == "MCDR v2/3"
    assert record_format([str(tmp_path / "nope")]) == "unknown"


def test_manifest_carries_a_regenerate_command():
    """記録は作り直せなければならない。**打ち直すコマンドが manifest に残ること**。

    D-064 の vb ループでは manifest を持ち帰っておらず、1.8 GB の記録が作り直せない形で
    失われた（引継ぎ書 §2.1）。`.bin` を捨ててよいのは、この 1 行があるからである。
    """
    from experiments.drl_record import regenerate_command
    cmd = regenerate_command(["drl_record.py", "--deck", "SD001", "--vb", "3",
                              "--seed0", "620000", "--n", "9650", "--out", "results/drl/vb3_train"])
    assert cmd.startswith("python3 experiments/drl_record.py ")
    for part in ("--deck SD001", "--vb 3", "--seed0 620000", "--n 9650",
                 "--out results/drl/vb3_train"):
        assert part in cmd, f"{part} が作り直しのコマンドに入っていない"


# ================================== 便 4 の下ごしらえ: 取り直しの乱数を分ける（案 C）
# T-22。マスター裁定 2026-09-04。**Rust を触る唯一の変更**。
#
# 何を直したか: 取り直し（`reeval_samples>0`）は「選んだ手を別の決定化で測り直す」処理だが、
# その別の決定化を**本編と同じ乱数の流れから引いて**いた。そのため同じシードでも
# 取り直しの有無で**対局そのものが変わって**しまい、
#   - manifest の `regenerate` を打っても同じ記録が作り直せない
#   - 取り直しの有無を同じシードで比べられない
# の 2 つが壊れていた。取り直し専用の乱数を 1 本足し、その間だけ差し替えて元に戻す。


def _rs_has_reeval_isolation():
    """入っている Rust が便 4 の修正を持っているか。無ければ skip（未再ビルド）。"""
    rs = _rs_has_d065()
    feats = getattr(rs, "features", None)
    if feats is None or "d065_reeval_isolated_rng" not in feats():
        pytest.skip("Rust が D-065 便 4（取り直し専用の乱数）より古い（未再ビルド）。"
                    "作業環境では maturin build、マスターの PC では計画書 §10 のあとに通る")
    return rs


@pytest.mark.parametrize("n_reeval", [1, 4, 7])
def test_reeval_does_not_disturb_the_main_game(tmp_path, n_reeval):
    """**取り直しの有無・本数によらず対局が変わらない**（案 C の目的そのもの）。

    取り直しは「記録に `fresh` を足す」だけの処理であって、打つ手を変えてはならない。
    変わってしまうと、同じシードで取り直しの有無を比べられず、manifest から作り直しても
    別の記録が出てくる。本数を 3 通り試すのは、**引いた乱数の量に依存しない**ことまで固定するため。

    `kind` は `planner` だけでよい。`Greedy` の取り直し（`solo` と `clash`）は
    **計画探索の中から呼ばれる**ので、この 1 本で 3 か所とも通る
    （なお spec の `kind: "greedy"` は `reeval_samples` も `value_net` も受け取らない。
    そちらで試しても何も起きないので、検査にすると空振りになる）。
    """
    _rs_has_reeval_isolation()
    from experiments.arena_rs import series_rs_digest
    vnet = _rand_net_path(tmp_path, "reeval_pl.json", seed=91)
    base = {"kind": "planner", "opp_decklist": POOL, "value_net": vnet, "extra_turns": 1}
    off = dict(base, reeval_samples=0)
    on = dict(base, reeval_samples=n_reeval)
    a = series_rs_digest(off, off, 3, CONFIG, workers=1, seed0=471400)
    b = series_rs_digest(on, on, 3, CONFIG, workers=1, seed0=471400)
    assert [r[4] for r in a] == [r[4] for r in b], \
        "取り直しが本編の乱数列を汚している（案 C が効いていない）"


def test_reeval_still_uses_fresh_determinizations(tmp_path):
    """**取り直しは本当に別の決定化を引いている**こと。

    前の検査（対局が変わらない）は、取り直しを「同じ決定化の使い回し」にしても通ってしまう。
    それでは楽観を持たない教師にならないので、ここで
    「`fresh` が根の探索値の最大とは別の数になる決定がある」ことを確かめる。
    """
    _rs_has_reeval_isolation()
    rs = pytest.importorskip("meicho_rs")
    from meicho.drl_data import read_records
    vnet = _rand_net_path(tmp_path, "reeval_fresh.json", seed=93)
    spec = {"kind": "planner", "opp_decklist": POOL, "extra_turns": 1,
            "value_net": vnet, "reeval_samples": 4}
    out = str(tmp_path / "reevalrec")
    _res, files = rs.series_record(CONFIG.chara_decks, CONFIG.action_decks,
                                   spec, spec, 471420, 3, out, 1, 200, True, False)
    r = read_records(files)
    diff = 0
    for i in range(r.n):
        f = float(r.fresh[i])
        sc = r.scores_of(i)
        if math.isnan(f) or not len(sc):
            continue
        fin = sc[np.isfinite(sc)]
        if fin.size and abs(f - float(fin.max())) > 1e-9:
            diff += 1
    assert diff >= 5, f"fresh が根の最大値と同じものばかり（別の決定化を引いていない）: {diff} 件"


def test_reeval_is_reproducible(tmp_path):
    """取り直しの値そのものも、同じシードなら毎回同じであること（専用の乱数も決定的）。"""
    _rs_has_reeval_isolation()
    rs = pytest.importorskip("meicho_rs")
    from meicho.drl_data import read_records
    vnet = _rand_net_path(tmp_path, "reeval_rep.json", seed=95)
    spec = {"kind": "planner", "opp_decklist": POOL, "extra_turns": 1,
            "value_net": vnet, "reeval_samples": 3}
    got = []
    for j in (0, 1):
        out = str(tmp_path / f"rep{j}")
        _res, files = rs.series_record(CONFIG.chara_decks, CONFIG.action_decks,
                                       spec, spec, 471440, 2, out, 1, 200, True, False)
        r = read_records(files)
        got.append([("nan" if math.isnan(float(v)) else round(float(v), 12)) for v in r.fresh])
    assert got[0] == got[1], "取り直しの値が再現しない（専用の乱数が決定的でない）"


def test_features_lists_what_this_wheel_has():
    """`meicho_rs.features()` が、この wheel に入っている修正の札を返すこと。

    検査が「入っている Rust が古いか」を**引数の有無ではなく札で**見分けられるようにする。
    つまみを増やさない修正（今回の案 C のような）は引数からは見分けられない。
    """
    rs = _rs_has_d065()
    feats = getattr(rs, "features", None)
    if feats is None:
        pytest.skip("Rust が features() を持たない（未再ビルド）")
    fs = feats()
    assert isinstance(fs, list) and all(isinstance(x, str) for x in fs)
    assert "d065_bin1" in fs


# ============================= 便 4 の速度の手当て: 代打ち π の蒸留（計画書 §9-4 (b)）
# T-23。マスター裁定 2026-09-05:「先に π を蒸留して速くする」「弱くなっていなければ採る」。
#
# 蒸留とは「大きいネット（先生）と**同じ手を選ぶ**小さいネット（生徒）を作る」こと。
# 代打ち π は探索の中で 1 決定ごとに呼ばれるので、ここが軽くなると全体が速くなる。
# 目的は速さであって強化ではない。だから生徒に求めるのは
# **「先生と同じように打つこと」**であって、「先生より良く打つこと」ではない。


def test_distil_target_is_the_teacher_not_the_recorded_move():
    """蒸留の目標は**先生の考え**であって、記録に残っている手ではない。

    従来の学習（模倣）は「記録した agent が選んだ手」を当てにいく。蒸留はそうではなく、
    **先生が合法手それぞれに付けた点数の分布**に生徒を合わせる。
    片方の手だけを見る（＝一番の手だけ真似る）より、
    「2 番目に良い手がどれくらい良いか」まで伝わるぶん、少ない教材で似せられる。
    """
    _needs_torch()
    import torch
    from experiments.drl_train import Batcher, TwoHead, distil_loss
    r = _fake_records(n=64, seed=51, n_acts=3)
    b = Batcher(r)
    torch.manual_seed(0)
    teacher = TwoHead(hidden=16, depth=1, phead=8)
    student = TwoHead(hidden=16, depth=1, phead=8)
    obs, codes, n_acts, chosen, target, z, phase = b.batch(np.arange(b.n))
    with torch.no_grad():
        t_logits = teacher(obs, codes, n_acts)[1]
    s_logits = student(obs, codes, n_acts)[1]
    loss = distil_loss(s_logits, t_logits, n_acts)
    assert loss.item() > 0
    # 先生と生徒が同じ出力なら損失は 0（合法手の外は数えない）
    same = distil_loss(t_logits, t_logits, n_acts)
    assert float(same) == pytest.approx(0.0, abs=1e-5), "同じ分布なのに損失が 0 でない"


def test_distil_ignores_illegal_actions():
    """合法手の外（詰め物の枠）は損失に混ぜないこと。

    行動は固定長の枠に詰めてあり、余った枠は「無い手」である。そこを数えると、
    **手の数が少ない決定ほど無い手を当てる練習をさせられる**ことになる。
    """
    _needs_torch()
    import torch
    from experiments.drl_train import distil_loss
    B, K = 4, 6
    n_acts = torch.tensor([2, 3, 6, 2])
    t = torch.zeros(B, K)
    s = torch.zeros(B, K)
    base = float(distil_loss(s, t, n_acts))
    # 合法手の**外**だけを大きく動かしても損失は変わらない
    s2 = s.clone()
    s2[0, 4] = 50.0
    s2[3, 5] = -50.0
    assert float(distil_loss(s2, t, n_acts)) == pytest.approx(base, abs=1e-6)
    # 合法手の**中**を動かせば損失は増える
    s3 = s.clone(); s3[0, 0] = 5.0
    assert float(distil_loss(s3, t, n_acts)) > base + 1e-3


def test_distil_makes_the_student_agree_with_the_teacher():
    """短い学習でも、生徒の一番手が先生の一番手に**近づく**こと（仕掛けが繋がっている）。"""
    _needs_torch()
    import torch
    import torch.nn.functional as F
    from experiments.drl_train import Batcher, TwoHead, distil_loss
    r = _fake_records(n=512, seed=53, n_acts=4)
    b = Batcher(r)
    torch.manual_seed(1)
    teacher = TwoHead(hidden=32, depth=1, phead=16)
    student = TwoHead(hidden=16, depth=1, phead=8)
    obs, codes, n_acts, chosen, target, z, phase = b.batch(np.arange(b.n))
    with torch.no_grad():
        t_logits = teacher(obs, codes, n_acts)[1]
        t_best = t_logits.argmax(-1)

    def agree():
        with torch.no_grad():
            return float((student(obs, codes, n_acts)[1].argmax(-1) == t_best).float().mean())
    before = agree()
    opt = torch.optim.Adam(student.parameters(), lr=3e-3)
    for _ in range(120):
        opt.zero_grad()
        distil_loss(student(obs, codes, n_acts)[1], t_logits, n_acts).backward()
        opt.step()
    after = agree()
    assert after > before + 0.05, f"蒸留で一致率が上がっていない（{before:.3f} → {after:.3f}）"


def test_distil_from_requires_wv_zero():
    """`--distil-from` は π だけを学ぶ口である。V も同時に学ぼうとしたら止める。

    小さいネットの V は使わない（葉に積むのは今までどおり大きい版）。
    黙って両方学ぶと「何のための版か」が曖昧な版ができる。
    """
    _needs_torch()
    from experiments.drl_train import check_distil_args
    with pytest.raises(SystemExit):
        check_distil_args(distil_from="x.json", wv=1.0, lam=0.0)
    with pytest.raises(SystemExit):
        check_distil_args(distil_from="x.json", wv=0.0, lam=0.7)   # λ は V の話なので同時に使わない
    check_distil_args(distil_from="x.json", wv=0.0, lam=0.0)       # これは通る
    check_distil_args(distil_from=None, wv=1.0, lam=0.7)           # 蒸留でないときは何も言わない
