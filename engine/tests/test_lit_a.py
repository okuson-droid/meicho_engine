"""文献計画 便 A（前半）の検査。`HANDOFF_20260907_LIT_A.md` §5 の T-A1〜T-A9。

固定するのは**結論（強くなるか）ではなく前提**である。強さは §4 の測定が出す。
ここで守るのは 5 つ。

1. **既定値では一手も変わらない**（`lethal_uniform=0.0` なら 1 ビットも動かない）
2. **Python が真実源、Rust はその写し**（D-049・作業規約 1）。新しいつまみは毎手一致で固定する
3. **切り替えの規則そのもの**（`lethal_frac` の作り方と θ の境界）を、葉の採点から切り離して固定する
4. **取り直し（`reeval`）が根と同じ規則を使う**（規則が違うと `fresh` の意味が壊れる）
5. **アプリの既定を変えていない**（候補は選べるだけ）

`meicho_rs` が無い環境、または**入っている Rust が便 A より古い**環境では、
Rust を要する検査だけ理由つきで skip する（マスターの PC は交代の直前まで古い wheel のまま）。
**skip は「通った」ではない。** 便 A の完了判定は、新しい wheel を入れた作業環境で skip 0 である。
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
from meicho.drlnet import random_net, resolve_model                       # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,        # noqa: E402
                           legal_actions, outcome)
from meicho.greedy import GreedyAgent                                     # noqa: E402
from meicho.planner import PlannerAgent                                   # noqa: E402
from meicho.state import Phase                                            # noqa: E402

SD001 = load_deck("SD001")
CONFIG = mirror_config(SD001)
POOL = SD001["action_deck"]
HUMAN_GAMES = os.path.join(os.path.dirname(__file__), "..", "results",
                           "human_games", "2026-09.jsonl")
# 検査で対局を回すときの帯（便 A の共通帯の予備区画 655100..655999）。**強さは読まない。**
SEED0 = 655100


def _rs_has_lit_a():
    """入っている Rust が便 A のつまみを知っているか。知らなければ skip（§5 冒頭）。"""
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()                                   # 先にカード表を渡す
    if "lethal_uniform" not in rs.features():
        pytest.skip("Rust が便 A より古い（未再ビルド）。"
                    "作業環境では §1 の自前ビルド、マスターの PC では §7.3 のあとに通る")
    return rs


def _champion_kwargs() -> dict:
    """**便 A 当時の champion（`planner_vb3cps`・葉 V_3）** の kwargs。

    便 E-0 で champion が `planner_vc4cps` に替わったので、ここを `champion.py` から
    動的に読むと「便 A の測定が何の上で取られたか」が後から変わってしまう。
    便 A の検査は便 A の土俵に固定する（`test_champion_vc4.py` が唯一の定義）。
    """
    from tests.test_champion_vc4 import OLD_CHAMPION_KWARGS, resolved_kwargs
    return resolved_kwargs(OLD_CHAMPION_KWARGS)


def _submitted_name(s, pi, a) -> str:
    from meicho.cards import ACTION_CARDS
    if a["type"] != "submit":
        return a["type"]
    return ACTION_CARDS[s.players[pi].hand[a["hand"]]].name


def _human_clash_positions():
    """対人 2 局（g001/g002）の**負けを決めた対抗**の局面を記録から再生して返す。

    `tests/test_d065.py::_human_clash_positions` と同じ手順である（同じ 2 局面を指す）。
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


# --------------------------------------------------------- T-A1 挙動不変
def test_defaults_unchanged_lit_a():
    """`lethal_uniform=0.0`（既定）では一手も変わらない。

    見るのは 2 つ。
    1. `bench_agents.py` の fingerprint 3 種（素の H・貪欲・計画探索）
    2. **便 A 当時の champion（`planner_vb3cps`）**の fingerprint `7251a931d252a57a`
       （手順は `test_lit_d.py` と同じ。**spec を明示して固定する**——`champion.py` を
       動的に読むと、便 E-0 の交代でこの検査が「新 champion の固定」に化けるため）

    ここが動いたら**止める**——過去に取ったすべての勝率が比較できなくなる。
    旧値 `f82625f68bb79a2d` は作り方が失われているので基準に使わない（便 D の判断②）。
    """
    pytest.importorskip("meicho_rs")
    import hashlib

    from experiments import bench_agents
    from experiments.arena_rs import ensure_cards, series_rs_digest
    ensure_cards()

    assert bench_agents.fingerprint("H", 50) == "773a71c15c5bc16e"
    assert bench_agents.fingerprint("G", 20) == "677f28cc3b6995ee"
    assert bench_agents.fingerprint("P", 10) == "6e39c2aa4b35d876"

    from tests.test_champion_vc4 import (OLD_CHAMPION_FINGERPRINT,
                                         OLD_CHAMPION_KWARGS, resolved_kwargs)
    sp = {"kind": "planner", "opp_decklist": POOL, **resolved_kwargs(OLD_CHAMPION_KWARGS)}
    out = series_rs_digest(sp, sp, 10, CONFIG, workers=2, seed0=471500)
    fp = hashlib.sha256(repr([r[4] for r in out]).encode()).hexdigest()[:16]
    assert fp == OLD_CHAMPION_FINGERPRINT, (
        "便 A 当時の champion の挙動が変わった。便 A のつまみは既定で無効なので、"
        "ここが動いたら**止めて**原因を調べること")


def test_lethal_uniform_default_is_zero():
    """`PlannerAgent` / `GreedyAgent` の既定値が 0.0（＝無効）であること。"""
    from meicho.greedy import GreedyAgent
    assert PlannerAgent(0).lethal_uniform == 0.0
    assert GreedyAgent(0).lethal_uniform == 0.0
    # 既定では記録に新しい鍵が付かない（記録の形が変わらない・`test_lit_d.py` の T-D7）
    ag = PlannerAgent(0, opp_decklist=POOL)
    s = initial_state(CONFIG, SEED0)
    steps = 0
    while outcome(s) is None and steps < 60:
        need = decision_players(s)
        if not need:
            break
        if s.phase == Phase.CLASH_SUBMIT and 0 in need and len(legal_actions(s, 0)) > 1:
            ag.last_clash = None
            ag.act(s, 0)
            if ag.last_clash is not None:
                assert set(ag.last_clash) == {"acts", "totals", "chosen"}, \
                    "既定なのに便 A の鍵（rule / lethal_frac）が付いている"
                break
        s = apply(s, {q: _quick_act(s, q) for q in need})
        steps += 1


def _quick_act(s, q):
    """検査を早く回すための当たり障りのない手（規則ベース）。"""
    from meicho.heuristic import HeuristicAgent
    return HeuristicAgent(q).act(s, q)


# --------------------------------------------------- T-A2 Python と Rust の一致
def test_lethal_uniform_python_matches_rust(tmp_path):
    """`lethal_uniform=0.5` で Python 版と Rust 版が**毎手一致**する。

    列の順序・足す順序・`1.0 − 1e-9` の比較・`k` で割る位置がずれていれば、
    どこかの手で必ず食い違う（A-8 の写しと同じ規律・§9）。
    """
    rs = _rs_has_lit_a()
    vnet = str(tmp_path / "lu_v.json")
    pnet = str(tmp_path / "lu_p.json")
    random_net(seed=81, hidden=24).save(vnet)
    random_net(seed=82, hidden=24).save(pnet)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              opp_policy_net=pnet, opp_policy_root_only=True, lethal_uniform=0.5)
    _match_40(rs, kw, SEED0 + 1)
    # **切り替わる側の道も比べる。** 上の設定（学習した V を模した乱数ネット）は葉の値が
    # ほぼ (0,1) に収まるので `pi0` の道しか通らない。素の評価関数（±WIN の尺度）なら
    # しきい値 1.0 を越える葉が普通に出るので、`uniform` の道が通る
    # （尺度の話は `greedy.py` の `lethal_uniform` の注意書き・便 A の判断①）。
    #
    # **便 E-0（D-071 裁定・判断① の実装）で土台を `GreedyAgent` に移した。**
    # `PlannerAgent` は `value_net` 無しの `lethal_uniform` を拒むようになったが、
    # `uniform` の道は素の尺度でしか通らない。切り替え規則そのものは `GreedyAgent` に
    # あるので、ここを貪欲どうしで比べても**同じ規則の同じ道**を毎手照合できる。
    from meicho.greedy import GreedyAgent
    seen = _match_40(rs, dict(opp_decklist=POOL, lethal_uniform=0.5), SEED0 + 2,
                     collect_rules=True, py_cls=GreedyAgent, rs_cls=rs.GreedyAgent)
    assert "uniform" in seen, f"uniform の道を 1 度も比べていない（{seen}）"


def _match_40(rs, kw, seed, collect_rules=False, py_cls=None, rs_cls=None):
    """Python 版と Rust 版が毎手同じ手を選ぶこと（`test_d065._match_py_rust` の型）。"""
    py_cls = py_cls or PlannerAgent
    rs_cls = rs_cls or rs.PlannerAgent
    py_agents = [py_cls(0, **kw), py_cls(1, **kw)]
    rs_agents = [rs_cls(0, **kw), rs_cls(1, **kw)]
    py = initial_state(CONFIG, seed)
    rss = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, seed)
    steps, seen = 0, set()
    while outcome(py) is None and steps < 40:
        assert json.loads(py.to_json()) == json.loads(rss.to_json()), f"state step={steps}"
        need = decision_players(py)
        if not need:
            break
        acts = {}
        for pi in need:
            py_agents[pi].last_clash = None
            a_py = py_agents[pi].act(py, pi)
            a_rs = rs_agents[pi].act(rss, pi)
            assert a_py == a_rs, f"step {steps} P{pi}: python {a_py} != rust {a_rs}"
            # 規則そのものも一致していること（同じ手でも別の規則で選んでいたら写しが違う）
            py_rule = (py_agents[pi].last_clash or {}).get("rule")
            assert py_rule == rs_agents[pi].last_clash_rule, (
                f"step {steps} P{pi}: 規則が違う（python {py_rule} / "
                f"rust {rs_agents[pi].last_clash_rule}）")
            if py_rule:
                seen.add(py_rule)
                # **点数まで**一致していること。同じ手を選んでいても、割る位置が違えば
                # 点数がずれる（`/k` の落としなどはここでしか捕まらない）。
                # 完全一致にはしない——ネットの推論だけは Python(numpy) と Rust(f32) で
                # 最後の桁が揺れるためである（打ち方に効かない大きさ。実測 1e-8 台）。
                assert py_agents[pi].last_clash["totals"] == pytest.approx(
                    rs_agents[pi].last_scores, rel=1e-6, abs=1e-9), (
                    f"step {steps} P{pi}: 点数が違う（python "
                    f"{py_agents[pi].last_clash['totals']} / rust "
                    f"{rs_agents[pi].last_scores}）")
            acts[pi] = a_py
        py = apply(py, acts)
        rss = rs.apply(rss, acts)
        steps += 1
    assert steps >= 20, f"比べた手数が少なすぎる（{steps}）"
    return seen if collect_rules else steps


# ------------------------------------------------- T-A3 回帰局面（T-14）
@pytest.mark.skipif(not os.path.exists(HUMAN_GAMES), reason="対人の記録が無い環境")
def test_lethal_uniform_fixes_the_human_positions():
    """`lu50`・`lu30` が g001・g002 の両方で「燃える烈火」を選ぶ。既定は当時のまま。

    2026-09-03 の 2 局は、どちらも**詰みの烈火を持っていたのにパス／青で受けた**負けだった。
    原因は対抗の相手モデルが「π₀ の最尤 1 手」だけを見ることである。
    **θ をこの検査に合わせて動かしてはならない**——候補は先に 0.5 と 0.3 に固定してある。
    """
    kw = _champion_kwargs()
    want_old = {"g001": "pass", "g002": "音の形・回避"}
    pos = _human_clash_positions()
    assert len(pos) >= 2, f"回帰局面が足りない: {[p[0] for p in pos]}"
    for gid, s, ai, seed in pos:
        old = PlannerAgent(seed, opp_decklist=POOL, **kw).act(s, ai)
        assert _submitted_name(s, ai, old) == want_old[gid], \
            f"{gid}: 既定の挙動が変わった（{_submitted_name(s, ai, old)}）"
        for theta in (0.5, 0.3):
            ag = PlannerAgent(seed, opp_decklist=POOL, lethal_uniform=theta, **kw)
            new = ag.act(s, ai)
            assert _submitted_name(s, ai, new) == "燃える烈火", \
                (f"{gid}: θ={theta} でも烈火を選ばない（{_submitted_name(s, ai, new)}・"
                 f"lethal_frac={ag.last_clash.get('lethal_frac')}）")
            assert ag.last_clash["rule"] == "uniform", \
                f"{gid}: θ={theta} で切り替わっていない（rule={ag.last_clash['rule']}）"


# ------------------------------------------------- T-A4 使えない組み合わせ
def test_lethal_uniform_rejects_bad_combinations(tmp_path):
    """`opp_mix` / `nash_delta` との併用と、範囲外の θ は `ValueError`。

    混ぜると「相手モデルをどう決めたか」が二重になり、何を測っているか分からなくなる。

    併用と範囲の検査は**規則の定義元である `GreedyAgent`** で行う。便 E-0（判断①）で
    `PlannerAgent` は `value_net` 無しの `lethal_uniform` を拒むようになったので、
    そちらで書くと「どの理由で落ちたか」が分からなくなるためである。
    `PlannerAgent` 側は `value_net` を積んだ構成で、同じ組み合わせを弾くことを確かめる。
    """
    from meicho.greedy import GreedyAgent
    vnet = str(tmp_path / "t_a4_v.json")
    random_net(seed=93, hidden=16).save(vnet)

    with pytest.raises(ValueError):
        GreedyAgent(0, lethal_uniform=0.5, opp_mix=0.5)
    with pytest.raises(ValueError):
        GreedyAgent(0, lethal_uniform=0.5, nash_delta=0.06)
    with pytest.raises(ValueError):
        GreedyAgent(0, lethal_uniform=-0.1)
    with pytest.raises(ValueError):
        GreedyAgent(0, lethal_uniform=1.5)
    # 端は使える（0.0 = 無効・1.0 = 「どの列でも詰み」のときだけ切り替える）
    assert GreedyAgent(0, lethal_uniform=1.0).lethal_uniform == 1.0

    # `PlannerAgent` にも転送されていること（`value_net` を積んだ構成で）
    with pytest.raises(ValueError):
        PlannerAgent(0, value_net=vnet, lethal_uniform=0.5, opp_mix=0.5)
    with pytest.raises(ValueError):
        PlannerAgent(0, value_net=vnet, lethal_uniform=1.5)
    assert PlannerAgent(0, value_net=vnet, lethal_uniform=1.0).lethal_uniform == 1.0
    # `tau` との併用は可（抽選は `_pick` の中で従来どおり）
    assert PlannerAgent(0, value_net=vnet, lethal_uniform=0.5, tau=0.3).tau == 0.3
    # 判断①（D-071 裁定・便 E-0）: `value_net` 無し × `lethal_uniform > 0` は `ValueError`。
    # 4 つの置き場所（Python / Rust のクラスと spec）は `test_champion_vc4.py::T-C2`。
    with pytest.raises(ValueError, match="value_net"):
        PlannerAgent(0, lethal_uniform=0.5)


# ------------------------------ T-A5 詰みの割合と切り替えの規則（葉から切り離す）
class _StubClash(GreedyAgent):
    """`_score_clash` を差し替えて、**行列を検査が決める**版。

    こうすると「葉の採点が正しいか」と「切り替えの規則が正しいか」を分けて調べられる。
    `_determinize` は恒等（決定化の乱数を挟まない）、相手の最尤手は `cols[-1]` に固定する。

    **土台は `GreedyAgent`**（便 E-0・判断①）。切り替えの規則・`_clash`・`_determinize`・
    `_opp_act`・`_score_clash` はすべて `GreedyAgent` にあるので、調べている中身は変わらない。
    `PlannerAgent` は `value_net` 無しの `lethal_uniform` を拒むようになったが、
    この検査は `_score_clash` ごと差し替えるので葉の採点そのものを持たない——
    そこに `value_net` を積むのは「積んだふり」であり、意図を曇らせる。
    """

    def __init__(self, *a, table=None, cols=None, acts=None, **kw):
        super().__init__(*a, **kw)
        self._table, self._cols, self._acts = table, cols, acts

    def _determinize(self, s, pi):
        return s

    def _opp_act(self, s, q, allow_net=True):
        return self._cols[-1]

    def _score_clash(self, t, pi, a, b, goal):
        i = next(k for k, x in enumerate(self._acts) if x == a)
        j = next(k for k, x in enumerate(self._cols) if x == b)
        return self._table[i][j]


def _stub_position():
    """対抗フェイズで、自分に 2 手以上・相手に 2 列以上ある局面を 1 つ拾う。"""
    from meicho.heuristic import HeuristicAgent
    for seed in range(SEED0 + 10, SEED0 + 60):
        s = initial_state(CONFIG, seed)
        steps = 0
        while outcome(s) is None and steps < 200:
            need = decision_players(s)
            if not need:
                break
            if (s.phase == Phase.CLASH_SUBMIT and 0 in need and 1 in need
                    and len(legal_actions(s, 0)) >= 2 and len(legal_actions(s, 1)) >= 2):
                return s
            s = apply(s, {q: HeuristicAgent(q).act(s, q) for q in need})
            steps += 1
    pytest.skip("対抗の局面が見つからなかった")


def test_lethal_frac_and_switch_rule():
    """`lethal_frac` の作り方と θ の境界（`>=` で切り替わること）を固定する。

    表は検査が決める:
      行 0 … 前半の列で詰み（1.0）・後半は 0.0 → `lethal_frac` は ceil(k/2)/k（0.5 以上）
      行 1 … どの列も 0.4（詰み無し）→ `lethal_frac` は 0.0
    相手の最尤手は**最後の列**に固定してあるので、
      π₀ の値: 行 0 = 0.0 ／ 行 1 = 0.4  → pi0 で選ぶと**行 1**
      等重みの値: 行 0 = ceil(k/2)/k ≥ 0.5 ／ 行 1 = 0.4 → uniform で選ぶと**行 0**
    つまり「どちらの規則で選んだか」が選ぶ手そのもので分かる。
    """
    s = _stub_position()
    acts, cols = legal_actions(s, 0), legal_actions(s, 1)
    k, n_lethal = len(cols), math.ceil(len(cols) / 2)
    table = [[1.0 if j < n_lethal else 0.0 for j in range(k)]] + \
            [[0.4] * k for _ in acts[1:]]
    frac0 = n_lethal / k
    assert frac0 >= 0.5

    def make(theta):
        return _StubClash(0, opp_decklist=POOL, samples=3, lethal_uniform=theta,
                          table=table, cols=cols, acts=acts)

    # θ = frac0（境界）→ `>=` なので uniform 側
    ag = make(frac0)
    a = ag.act(s, 0)
    assert ag.last_clash["rule"] == "uniform", "境界（θ == lethal_frac）で切り替わっていない"
    assert a == acts[0], "uniform なのに等重みで最良の手を選んでいない"
    assert ag.last_clash["lethal_frac"] == pytest.approx([frac0] + [0.0] * (len(acts) - 1))

    # θ = frac0 + 1e-6（わずかに上）→ pi0 側
    ag = make(frac0 + 1e-6)
    a = ag.act(s, 0)
    assert ag.last_clash["rule"] == "pi0", "しきい値を越えたのに uniform のまま"
    assert a == acts[1], "pi0 なのに π₀ の列で最良の手を選んでいない"

    # 詰みが 1 つも無い表なら、θ をいくら下げても（0 より大きい限り）pi0
    ag = _StubClash(0, opp_decklist=POOL, samples=3, lethal_uniform=1e-9,
                    table=[[0.4] * k for _ in acts], cols=cols, acts=acts)
    ag.act(s, 0)
    assert ag.last_clash["rule"] == "pi0"
    assert ag.last_clash["lethal_frac"] == pytest.approx([0.0] * len(acts))


def test_lethal_threshold_is_exactly_one_minus_eps():
    """しきい値は `1.0 − 1e-9`。**それをわずかに下回る値は詰みと数えない。**"""
    from meicho.greedy import LETHAL_EPS
    assert LETHAL_EPS == 1e-9
    s = _stub_position()
    acts, cols = legal_actions(s, 0), legal_actions(s, 1)
    k = len(cols)
    just_below = 1.0 - 1e-8         # しきい値を下回る
    ag = _StubClash(0, opp_decklist=POOL, samples=1, lethal_uniform=1e-9,
                    table=[[just_below] * k for _ in acts], cols=cols, acts=acts)
    ag.act(s, 0)
    assert ag.last_clash["lethal_frac"] == pytest.approx([0.0] * len(acts)), \
        "1.0 − 1e-8 を詰みと数えている（しきい値が緩い）"
    ag = _StubClash(0, opp_decklist=POOL, samples=1, lethal_uniform=1e-9,
                    table=[[1.0 - 1e-10] * k for _ in acts], cols=cols, acts=acts)
    ag.act(s, 0)
    assert ag.last_clash["lethal_frac"] == pytest.approx([1.0] * len(acts)), \
        "1.0 − 1e-10 を詰みと数えていない（しきい値が厳しい）"


# ------------------------------------------- T-A6 取り直しが同じ規則を使う
def test_reeval_uses_the_same_rule():
    """`reeval_samples>0` のとき、取り直しは**根で選んだ規則**で 1 手を測る。

    取り直しは 1 手だけを別の決定化で測るので、そこで規則を決め直すと
    「詰みが見える／見えない」が根と食い違い、`fresh`（二重推定）の意味が壊れる。
    取り直しは Rust にしかない（`greedy.py` 冒頭）ので、この検査も Rust 版で行う。
    """
    rs = _rs_has_lit_a()
    kw = dict(_champion_kwargs())
    kw.pop("opp_policy_root_only", None)
    ag0 = rs.PlannerAgent(0, opp_decklist=POOL, reeval_samples=2,
                          lethal_uniform=0.3, opp_policy_root_only=True, **kw)
    ag1 = rs.PlannerAgent(1, opp_decklist=POOL, reeval_samples=2,
                          lethal_uniform=0.3, opp_policy_root_only=True, **kw)
    agents = [ag0, ag1]
    seen_uniform = seen_pi0 = 0
    for seed in range(SEED0 + 200, SEED0 + 206):
        s = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, seed)
        steps = 0
        while rs.outcome(s) is None and steps < 200:
            need = rs.decision_players(s)
            if not need:
                break
            acts = {q: agents[q].act(s, q) for q in need}
            for q in need:
                r = agents[q].last_clash_rule
                if r is not None:
                    assert agents[q].last_reeval_rule == r, (
                        f"取り直しが別の規則を使っている（根 {r} / 取り直し "
                        f"{agents[q].last_reeval_rule}）")
                    if r == "uniform":
                        seen_uniform += 1
                    else:
                        seen_pi0 += 1
            s = rs.apply(s, acts)
            steps += 1
        if seen_uniform and seen_pi0:
            break
    assert seen_pi0 > 0, "pi0 の対抗が 1 度も出ていない（検査になっていない）"
    assert seen_uniform > 0, "uniform に切り替わった対抗が 1 度も出ていない（つまみが効いていない）"


# ------------------------------------------ T-A7 アプリの登録（既定は不変）
def test_webapp_candidates_registered_default_unchanged():
    """候補が `build` でき、`DEFAULT_OPPONENT` が**現 champion と一致**していること。

    便 E-0 までは名前（`planner_vb3cps`）を直書きしていたが、交代のたびに落ちるので
    「既定の相手の中身が `champion.py` と一致する」という**不変条件のほう**を見る形にした。
    名前の一致は `tests/test_drl.py::test_champion_definition_is_consistent_everywhere`。
    """
    import champion as chmod
    from webapp import agents as wagents
    assert wagents.default_for("SD001") == wagents.DEFAULT_OPPONENT
    assert wagents.OPPONENTS[wagents.DEFAULT_OPPONENT]["kwargs"] == chmod.kwargs_for("SD001"), \
        "アプリの既定の相手が champion.py の定義と食い違っている"
    avail = wagents.available("SD001")
    for name in ("planner_vb3cps_lu50", "planner_vb3cps_m100"):
        assert name in avail, f"{name} が選べる相手に無い"
    a = wagents.build("planner_vb3cps_lu50", POOL, 1)
    assert a.lethal_uniform == 0.5 and a.opp_mix == 0.0
    b = wagents.build("planner_vb3cps_m100", POOL, 1)
    assert b.opp_mix == 1.0 and b.lethal_uniform == 0.0
    # 候補は「**便 A 当時の champion**（`planner_vb3cps`）＋ 差分 1 つ」であること
    # （他のつまみを一緒に動かしていない）。便 E-0 で champion は替わったが、
    # 便 A の候補が何への差分だったかは変わらない。
    champ = wagents.OPPONENTS["planner_vb3cps"]["kwargs"]
    for name, key in (("planner_vb3cps_lu50", "lethal_uniform"),
                      ("planner_vb3cps_m100", "opp_mix")):
        kw = dict(wagents.OPPONENTS[name]["kwargs"])
        assert kw.pop(key) is not None
        assert kw == champ, f"{name} が champion から {key} 以外も変えている"


# -------------------------------- T-A8 診断の道具が --cand を受け取る
def test_scan_and_peek_accept_cand():
    """`scan_missed_lethal` と `peek_counter` の `--cand null` が champion と同一。"""
    import peek_counter
    import scan_missed_lethal
    from probe_d065 import CANDIDATES
    assert scan_missed_lethal.kwargs_for_cand() == scan_missed_lethal.kwargs_for_cand("null")
    assert peek_counter.resolved_kwargs("SD001") == peek_counter.resolved_kwargs("SD001", "null")
    for cand, key, val in (("lu50", "lethal_uniform", 0.5),
                           ("lu30", "lethal_uniform", 0.3),
                           ("m100b", "opp_mix", 1.0)):
        assert CANDIDATES[cand] == {key: val}, f"{cand} の差分が 1 つでない"
        assert scan_missed_lethal.kwargs_for_cand(cand)[key] == val
        assert peek_counter.resolved_kwargs("SD001", cand)[key] == val
    with pytest.raises(SystemExit):
        scan_missed_lethal.kwargs_for_cand("そんな候補は無い")


def test_seed_bands_lit_a_registered():
    """§6 の帯が台帳にあり、`next_free` が 660000 まで進んでいる。重なりが無い。"""
    path = os.path.join(os.path.dirname(__file__), "..", "experiments", "seed_bands.json")
    with open(path, encoding="utf-8") as f:
        led = json.load(f)
    have = {(b["start"], b["end"]) for b in led["bands"]}
    for w in [(652000, 655999), (656000, 658999), (659000, 659299), (659300, 659999)]:
        assert w in have, f"帯 {w} が台帳に無い"
    assert led["next_free"] >= 660000
    ordered = sorted((b["start"], b["end"]) for b in led["bands"])
    for (s0, e0), (s1, e1) in zip(ordered, ordered[1:]):
        assert e0 < s1 or (s0, e0) == (s1, e1), f"帯が重なっている: {(s0, e0)} と {(s1, e1)}"


# ------------------------------------------------ T-A9 wheel の見分け
def test_features_lists_lethal_uniform():
    """`meicho_rs.features()` に `"lethal_uniform"` がある（新旧 wheel の見分け）。

    引数の有無だけでは見分けられないことがあるので、札を 1 行足してある（D-065 便 4 の型）。
    """
    rs = pytest.importorskip("meicho_rs")
    feats = rs.features()
    assert "d065_bin1" in feats, "そもそも便 1 より古い wheel"
    if "lethal_uniform" not in feats:
        pytest.skip("Rust が便 A より古い（未再ビルド）。§7.3 の再ビルドのあとに通る")
    assert "lethal_uniform" in feats
