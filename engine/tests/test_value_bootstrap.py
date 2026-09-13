"""V の反復ブートストラップ（D-064）の検査。`VALUE_BOOTSTRAP_DESIGN.md` §8 の 10 件。

固定するのは**結論（強くなるか）ではなく前提**である。強さは測定（`eval_vb.py`）が出す。
ここで守るのは次の 5 つ。

1. 既定値では一手も変わらない（新しい引数を足したことで過去の測定が読めなくなる事故の予防）
2. 地平の延長が旧 `LongHorizonPlanner` と同じ打ち切りであること（移植の忠実さ）
3. 葉を価値ネットに差し替えても、終端の扱いが Python 版と Rust 版で一致すること
4. 覗き見をしていないこと（D-026。**新しいエージェントは必ず監査する**）
5. 教材と教師の作り方が設計どおりであること（席の固定・δ の語彙・探索値の最大値・較正）

`meicho_rs` が無い環境では、Rust を要する検査だけ skip する。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

import vb as vbmod                                                        # noqa: E402
from experiments.arena import load_deck, mirror_config                    # noqa: E402
from meicho.engine import (apply, apply_owned, decision_players,          # noqa: E402
                           initial_state, outcome)
from meicho.drlnet import random_net                                      # noqa: E402
from meicho.heuristic import HeuristicAgent                               # noqa: E402
from meicho.planner import PlannerAgent                                   # noqa: E402
from meicho.state import Phase                                            # noqa: E402

SD001 = load_deck("SD001")
CONFIG = mirror_config(SD001)
POOL = SD001["action_deck"]
SEED0 = 164000        # D-046 の測定専用帯（挙動の検査にだけ使う。強さは読まない）


def _rand_net_path(tmp_path, name="vb.json", seed=31, hidden=24) -> str:
    """検査用の乱数ネット。一致テストは重みの中身を問わない。"""
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


def _first_action_phase(seed, max_steps=400):
    """人手の要らない進行で、席0のアクションフェイズ（合法手 2 以上）を 1 つ見つける。"""
    from meicho.engine import legal_actions
    a, b = HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)
    s = initial_state(CONFIG, seed)
    for _ in range(max_steps):
        if outcome(s) is not None:
            return None
        need = decision_players(s)
        if not need:
            return None
        if s.phase == Phase.ACTION and s.turn_player == 0 and 0 in need \
                and len(legal_actions(s, 0)) > 1:
            return s
        s = apply(s, {pi: (a if pi == 0 else b).act(s, pi) for pi in sorted(need)})
    return None


# ------------------------------------------------------------------ 1. 挙動不変

def _needs_torch():
    """**torch が無い環境では skip する。**

    学習側（`drl_train.py` とそれを読む道具）は torch を要る。マスターの PC は学習を回さないので
    入っていないのが正常であり、そこで**落ちる**のは検査の書き方が悪い。
    ただし **skip は「通った」ではない**——学習側の検査は、torch を入れた作業環境で
    **0 skip** になることが完了条件である。
    """
    return pytest.importorskip("torch")

def test_planner_defaults_unchanged():
    """`extra_turns=0, value_net=None` の planner は一手も変わっていない（§4.1）。

    新しい引数を足したせいで既定の挙動が動くと、**過去に取ったすべての勝率が
    比較できなくなる**。基準は D-054 時点の wheel で取った実対局の digest
    （`meicho/drl_data.BASELINE_DIGESTS_230000`）。
    """
    pytest.importorskip("meicho_rs")
    from experiments.arena_rs import PLANNER, ensure_cards, series_rs_digest
    from meicho.drl_data import BASELINE_DIGESTS_230000
    ensure_cards()
    out = series_rs_digest(PLANNER(POOL), PLANNER(POOL), 6, CONFIG, workers=2, seed0=230000)
    assert [r[4] for r in out] == BASELINE_DIGESTS_230000
    # Python 版も同じ。既定の引数が spec に漏れていないことを合わせて見る。
    assert PLANNER(POOL) == {"kind": "planner", "opp_decklist": POOL}
    p = PlannerAgent(0, opp_decklist=POOL)
    assert (p.extra_turns, p.value_net) == (0, None)


# ------------------------------------------- 2. 地平の延長が旧実装と同じであること
class _OldLongHorizon(PlannerAgent):
    """D-064 以前の `measure_horizon.LongHorizonPlanner._value_after_turn` の**写し**。

    移植の忠実さを測るための基準なので、**この写しは書き換えないこと**。
    書き換えたくなったら、それは移植ではなく仕様変更である。
    """

    def __init__(self, seed, extra_turns: int = 1, **kw):
        super().__init__(seed, **kw)
        self._old_extra = extra_turns

    def _value_after_turn(self, u, pi) -> float:
        self.fallback.rng.setstate(self._crn[0])
        self.opp_model.rng.setstate(self._crn[1])
        goal = u.turn_no + self._old_extra + 1
        for _ in range(self.turn_rollout * (1 + self._old_extra)):
            if u.outcome is not None or u.phase == Phase.GAME_OVER:
                break
            if u.turn_no >= goal and u.phase != Phase.CHOICE:
                break
            need = decision_players(u)
            if not need:
                break
            u = apply_owned(u, {q: self._proxy_act(u, q, pi) for q in need})
        return self._eval(u, pi)


@pytest.mark.parametrize("extra", [1, 2])
def test_extra_turns_matches_long_horizon(extra):
    """`PlannerAgent(extra_turns=n)` が旧 `LongHorizonPlanner` と同じ手を選ぶ（§4.1）。"""
    checked = 0
    for i in range(8):
        s = _first_action_phase(SEED0 + 500 + i)
        if s is None:
            continue
        seed = (SEED0 + 500 + i) * 2
        # **両方とも作りたての同一シード**で比べる（乱数の履歴を揃える）
        new = PlannerAgent(seed, opp_decklist=POOL, extra_turns=extra)
        old = _OldLongHorizon(seed, extra_turns=extra, opp_decklist=POOL)
        assert new.act(s, 0) == old.act(s, 0), f"移植で手が変わった（seed={seed}）"
        checked += 1
    assert checked >= 4, f"比べられた局面が少なすぎる（{checked}）"


def test_extra_turns_actually_extends_past_the_opponents_turn():
    """採点する局面が実際に相手のターンの先まで進んでいること（§3.1 の要）。"""
    s = _first_action_phase(SEED0 + 300)
    assert s is not None
    seen = {"plain": [], "long": []}

    def spy(agent, key):
        orig = agent._eval

        def wrapped(u, pi):
            seen[key].append(u.turn_no)
            return orig(u, pi)
        agent._eval = wrapped
        return agent

    spy(PlannerAgent(SEED0 * 2, opp_decklist=POOL), "plain").act(s, 0)
    spy(PlannerAgent(SEED0 * 2, opp_decklist=POOL, extra_turns=1), "long").act(s, 0)
    assert max(seen["long"]) > max(seen["plain"])


# ------------------------------------------------------------ 3. 終端の扱い
def test_vb_terminal_states_dominate(tmp_path):
    """葉を価値ネットに差し替えても、終端が非終端を支配すること（§3.2）。

    尺度は勝率 [0,1] なので、支配する値は 1.0（勝ち）と 0.0（負け）である
    （手作り評価の ±WIN に当たるもの）。引き分けは 0.5。
    **Rust 版 `agents.rs::Greedy::net_value` と同じ規約**であり、ここを変えるなら
    Rust も同時に変えて再ビルドすること（Python が真実源・作業規約 1）。
    """
    path = _rand_net_path(tmp_path, "term.json")
    ag = PlannerAgent(0, opp_decklist=POOL, value_net=path)
    s = initial_state(CONFIG, 7)
    for _ in range(60):        # 非終端の局面をいくつか集める
        need = decision_players(s)
        if not need or outcome(s) is not None:
            break
        s = apply(s, {pi: HeuristicAgent(pi).act(s, pi) for pi in need})
    mid = ag._eval(s, 0)
    assert 0.0 <= mid <= 1.0, f"価値ネットの葉が [0,1] を外れた: {mid}"

    from meicho.state import DRAW
    for pi in (0, 1):
        t = s.clone(); t.outcome = 0
        assert ag._eval(t, pi) == (1.0 if pi == 0 else 0.0)
        t = s.clone(); t.outcome = DRAW
        assert ag._eval(t, pi) == 0.5
    # 勝ち ≥ どの非終端 ≥ 負け（支配していること）
    win = s.clone(); win.outcome = 0
    lose = s.clone(); lose.outcome = 1
    assert ag._eval(win, 0) >= mid >= ag._eval(lose, 0)


# --------------------------------------------------- 4. Python / Rust の一致
def test_vb_rust_matches_python(tmp_path):
    """`extra_turns=1` ＋ `value_net` の組み合わせで Python 版と Rust 版が毎手同じ手を選ぶ。

    D-049 の型。**Python が真実源**であり（作業規約 1）、地平と葉を同時に変えた
    構成も例外にしない。ここが通らないかぎり Rust 版で回した記録は読めない。
    """
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()
    path = _rand_net_path(tmp_path, "vbrs.json", seed=41)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=path)
    py_agents = [PlannerAgent(0, **kw), PlannerAgent(1, **kw)]
    rs_agents = [rs.PlannerAgent(0, **kw), rs.PlannerAgent(1, **kw)]
    py = initial_state(CONFIG, 230000)
    rss = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, 230000)
    steps = 0
    while outcome(py) is None and steps < 400:
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
    assert steps > 20, f"対局が短すぎる（{steps} 手）"


# ------------------------------------------------------------- 5. 覗き見監査
def test_nopeek_audit_planner_vb(tmp_path):
    """決定化の規約（D-026）を守っていること。**新しいエージェントは必ず監査する。**

    地平を延ばすということは**相手のターンをこちらの想像で進める**ということであり、
    そこで実際の相手の手札や山札の順序を覗けば強くなって当然で、測定は無意味になる。
    """
    from meicho.audit import replay_audit
    path = _rand_net_path(tmp_path, "audit.json", seed=51)
    r = replay_audit(
        lambda sd: PlannerAgent(sd, opp_decklist=POOL, extra_turns=1, value_net=path),
        lambda sd: HeuristicAgent(sd),
        CONFIG, POOL, n_games=3, variants=2, node_cap=120)
    assert r["checked"] >= 60, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"


# ------------------------------------------------- 6. 教師（探索値の最大値）
def _fake_records(scores: list, chosen: list, z: list):
    """`Batcher` に食わせられる最小の Records（obs も行動も中身は見ない）。"""
    from meicho.drl_data import Records
    from meicho.encode import ACT_CODE_LEN, OBS_DIM
    n = len(scores)
    na = np.asarray([len(s) for s in scores], np.int16)
    off = np.zeros(n + 1, np.int64)
    off[1:] = np.cumsum(na.astype(np.int64))
    return Records(
        n=n, seed=np.arange(n, dtype=np.int64), step=np.zeros(n, np.int32),
        turn=np.ones(n, np.int16), pi=np.zeros(n, np.int8), phase=np.full(n, 2, np.int8),
        n_acts=na, chosen=np.asarray(chosen, np.int16), z=np.asarray(z, np.float32),
        # `fresh`（二重推定・D-065 §2.5）は版 2 相当の NaN。教師の既定は従来どおり max。
        fresh=np.full(n, np.nan, np.float32),
        obs=np.zeros((n, OBS_DIM), np.int8), act_off=off,
        acts_flat=np.zeros((int(off[-1]), ACT_CODE_LEN), np.int8),
        scores_flat=np.concatenate([np.asarray(s, np.float32) for s in scores]))


def test_vtarget_max_ignores_exploration():
    """`--vtarget max` の教師が「どの手を選んだか」に依らないこと（§3.3）。

    記録では温度 τ で探索的な手も選ばせる。教師が「選んだ手の値」だと、
    **わざと選んだ悪手の値が教師に混ざる**。最大値なら τ に汚されない。
    """
    _needs_torch()
    from experiments.drl_train import Batcher
    scores = [[1.0, 5.0, -2.0], [0.0, 3.0], [7.0, 7.0, 7.0]]
    z = [1.0, 0.0, 1.0]
    best = Batcher(_fake_records(scores, [1, 1, 0], z), vtarget="max")
    worst = Batcher(_fake_records(scores, [2, 0, 2], z), vtarget="max")
    assert list(best.vsearch) == list(worst.vsearch) == [5.0, 3.0, 7.0]
    # 旧既定（chosen）は選んだ手に依存する——それがまさに直したかったこと
    a = Batcher(_fake_records(scores, [1, 1, 0], z), vtarget="chosen")
    b = Batcher(_fake_records(scores, [2, 0, 2], z), vtarget="chosen")
    assert list(a.vsearch) != list(b.vsearch)
    # 探索していない決定（全部 NaN）は NaN のまま＝教師は z になる
    nan = Batcher(_fake_records([[np.nan, np.nan]], [0], [1.0]), vtarget="max")
    assert np.isnan(nan.vsearch[0]) and nan.target[0] == 1.0


# --------------------------------------------------- 7. 教材のレシピ（席と δ）
def test_vb_record_specs(tmp_path):
    """`--vb` の spec・記録する席・δ の語彙が設計どおりであること（§4.5・§6）。"""
    import drl_record
    import discovery

    # (a) 反復 k のエージェントの定義は vb.py が唯一の真実源
    kw1 = vbmod.kwargs_for("SD001", 1)
    assert kw1 == {"extra_turns": 1, "opp_policy_net": "drl_sd001_s1.json",
                   "opp_policy_root_only": True}, "反復 1 は葉に V を積まない（§5.2）"
    kw2 = vbmod.kwargs_for("SD001", 2)
    assert kw2["value_net"] == "drl_sd001_vb1.json", "反復 k は V_{k-1} を積む"
    assert kw2["opp_policy_net"] == kw1["opp_policy_net"], "π₀ は据え置き（§3.6）"
    for k in (1, 2, 5):
        for key in ("opp_policy_net", "value_net"):
            v = vbmod.kwargs_for("SD001", k).get(key)
            assert v is None or not os.path.isabs(v), "絶対パス禁止（C-1 の教訓）"

    # (b) δ は発見ループの語彙の部分集合であり、「強いる」型だけ
    cands = vbmod.delta_candidates("SD001", "A")
    gen_a = {vbmod._key(d) for d in discovery.gen_A(SD001)}
    assert cands and {vbmod._key(d) for d in cands} <= gen_a, \
        "δ が発見ループの語彙 A からはみ出している（同じ gens で同じ挑戦者になること）"
    assert {d["kind"] for d in cands} <= {"rush_chara", "fix_leader"}, "「禁じる」型は使わない"
    # 持続効果を持つキャラだけ（SD001 なら漂泊者（女）Lv2 と熾霞 Lv2）
    assert {d["name"] for d in cands} == {"漂泊者（女）", "熾霞"}

    # (c) 挑戦者の spec の形が discovery の challenger と同じ（`delta` に δ の列）
    spec = vbmod.spec("SD001", POOL, 1, delta=[cands[0]])
    assert spec["kind"] == "planner" and spec["delta"] == [cands[0]]
    assert os.path.isabs(spec["opp_policy_net"]), "Rust に渡す spec ではパスを解決する"

    # (d) リーグ局・δ 局は A 席だけ記録する（§6.3 の Simpson の罠よけ）
    for argv in (["--spec-b", "heuristic"], ["--delta-gens", "A"]):
        sys_argv = ["drl_record.py", "--deck", "SD001", "--vb", "1", "--seed0", "340000",
                    "--n", "8", "--out", str(tmp_path / "x.bin"), "--workers", "1"] + argv
        old = sys.argv
        sys.argv = sys_argv
        try:
            with pytest.raises(SystemExit) as e:
                drl_record.main()
            assert "--record a" in str(e.value)
        finally:
            sys.argv = old

    # (e) 記録帯の検査: 評価専用の帯では記録できない
    assert drl_record.check_record_band(340000)["kind"] == "search"
    for bad in (80000, 390000):
        with pytest.raises(SystemExit):
            drl_record.check_record_band(bad)


def test_vb_record_delta_manifest(tmp_path):
    """δ 局の manifest に語彙と δ の一覧が残ること（§4.5。あとから除外できるように）。"""
    pytest.importorskip("meicho_rs")
    import drl_record
    out = str(tmp_path / "d.bin")
    old = sys.argv
    sys.argv = ["drl_record.py", "--deck", "SD001", "--vb", "1", "--seed0", "340000",
                "--n", "8", "--out", out, "--workers", "1", "--delta-gens", "A", "--record", "a"]
    try:
        drl_record.main()
    finally:
        sys.argv = old
    man = json.load(open(out + ".manifest.json", encoding="utf-8"))
    assert man["delta"] == "A" and man["vb"] == 1 and man["record"] == "a"
    blocks = man["delta_blocks"]
    assert len(blocks) == len(vbmod.delta_candidates("SD001", "A"))
    assert sum(b["n"] for b in blocks) == 8
    # 帯が重ならない（あとからシードだけで「どの δ の局か」を引ける）
    spans = sorted((b["seed0"], b["seed0"] + b["n"]) for b in blocks)
    assert all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))
    # 絶対パスを残さない
    assert not os.path.isabs(man["spec_a"]["opp_policy_net"])
    # 書いたファイルが全部読み戻せる（学習が `--train <out>` でまとめて読める形）
    _needs_torch()
    from experiments.drl_train import files_of
    from meicho.drl_data import read_records
    fs = files_of(out)
    assert set(fs) == set(man["files"]) and read_records(fs).n > 0


def test_files_of_accepts_a_data_window(tmp_path):
    """`--train` がカンマ区切りの複数接頭辞を受ける（データ窓・設計書 §9）。

    「直近 N 反復ぶんだけを学習に使う」を、接頭辞を並べることで表す。
    manifest（`.json`）は混ざらず、接頭辞が入れ子でも同じファイルを 2 度読まない。
    """
    _needs_torch()
    from experiments.drl_train import files_of
    a = tmp_path / "it2.bin"
    b = tmp_path / "it3.bin"
    for p in (a, b):
        (tmp_path / (p.name + ".0")).write_bytes(b"x")
        (tmp_path / (p.name + ".1")).write_bytes(b"x")
        (tmp_path / (p.name + ".manifest.json")).write_text("{}", encoding="utf-8")
    (tmp_path / "it3.bin.delta.g0.0").write_bytes(b"x")

    one = files_of(str(a))
    assert len(one) == 2 and all(not f.endswith(".json") for f in one)
    two = files_of(f"{a},{b}")
    assert len(two) == 5 and all(not f.endswith(".json") for f in two)
    assert set(one) < set(two)
    # 入れ子の接頭辞を並べても重複しない
    assert files_of(f"{b},{b}.delta") == files_of(str(b))
    with pytest.raises(SystemExit):
        files_of(str(tmp_path / "nope.bin"))


def test_split_seeds_is_a_partition():
    """δ ごとのシード帯が、重なりも隙間もなく n 局を覆うこと。"""
    from drl_record import split_seeds
    for n, k in ((750, 8), (16, 8), (10, 3), (8, 8)):
        parts = split_seeds(1000, n, k)
        assert len(parts) == k and sum(m for _, m in parts) == n
        s = 1000
        for s0, m in parts:
            assert s0 == s
            s += m


# --------------------------------------------------------- 8. 較正の取り直し
def test_calibration_recomputed_per_iteration():
    """反復 2 以降の探索値（[0,1] 主体＋番兵）でも較正が働き、質を自分で申告すること（§3.3）。

    反復 1 の探索値は手作り評価の尺度（無界・±10000 の番兵）だが、反復 2 では葉が V に
    なるので探索値はおおむね [0,1] に収まる。**尺度が変わる**ので較正は反復ごとに
    取り直す必要がある。ここでは「取り直せば新しい尺度でも効く」ことを固定する。
    """
    _needs_torch()
    from experiments.drl_train import apply_calibration, calibrate_vsearch
    rng = np.random.RandomState(1)
    n = 20000
    # 反復 2 以降を模した分布: [0,1] の勝率 ＋ 5% は勝敗確定の番兵（±10000）
    p = rng.uniform(size=n)
    v = p.copy()
    z = (rng.uniform(size=n) < p).astype(np.float32)
    sent = rng.uniform(size=n) < 0.05
    v[sent] = np.where(z[sent] > 0.5, 10000.0, -10000.0)
    c = calibrate_vsearch(v.astype(np.float32), z)
    assert c["useful"] and c["logloss"] < c["base"], "新しい尺度で較正が効かない"
    q = apply_calibration(np.array([-10000.0, 0.0, 0.5, 1.0, 10000.0], np.float32), c)
    assert np.all(np.diff(q) >= -1e-9) and 0.0 <= q.min() and q.max() <= 1.0
    # 反復 1 の尺度（無界）でも同じ関数が働く＝取り直しが可能である
    v1 = rng.normal(0, 5, n)
    z1 = (rng.uniform(size=n) < 1 / (1 + np.exp(-v1 / 3))).astype(np.float32)
    assert calibrate_vsearch(v1.astype(np.float32), z1)["useful"]

    # 番兵が多いときは目盛りを本体に合わせる（--calib-scale bulk・D-064 反復 1 の裁定）
    from experiments.drl_train import calib_scale
    n2 = 30000
    # D-064 反復 1 の記録を模した 3 層。**「部分的な番兵」があることが肝**である。
    #   本体 70%: 勝敗が決まっていない局面の評価値（尺度 5）。勝敗をよく予測する
    #   部分的な番兵 20%: 決定化 4 通りのうち一部で勝敗が決まった平均値（±5000）。予測は弱い
    #   完全な番兵 10%: 探索の中で勝敗が確定（±10000）。勝敗と 1 対 1
    kind = rng.randint(0, 10, n2)
    bulk = rng.normal(0, 5, n2)
    v2 = bulk.copy()
    pz = 1 / (1 + np.exp(-bulk / 3))
    part = kind >= 9                                   # 10%: 完全な番兵
    half = (kind >= 7) & (kind < 9)                    # 20%: 部分的な番兵
    sgn = np.where(rng.uniform(size=n2) < 0.5, 1.0, -1.0)
    v2[half] = 5000.0 * sgn[half]
    pz[half] = np.where(sgn[half] > 0, 0.65, 0.35)     # 部分的な番兵は「やや有利」でしかない
    v2[part] = 10000.0 * sgn[part]
    pz[part] = np.where(sgn[part] > 0, 0.999, 0.001)
    zb = (rng.uniform(size=n2) < pz).astype(np.float32)
    v2 = v2.astype(np.float32)

    c_p90 = calib_scale(v2, "p90")
    c_bulk = calib_scale(v2, "bulk")
    assert c_p90 > 1000.0, "番兵が 30% あれば |v| の 90% 点は番兵に食われる（これが直したい症状）"
    assert 1.0 < c_bulk < 100.0, f"本体の目盛りが本体の尺度になっていない: {c_bulk}"

    good = calibrate_vsearch(v2, zb, scale="bulk")
    bad = calibrate_vsearch(v2, zb, scale="p90")
    assert good["logloss"] < bad["logloss"], (
        f"目盛りを本体に合わせても情報量が増えない: bulk {good['logloss']:.4f} / p90 {bad['logloss']:.4f}")
    # 直した側は本体に広がりがある。壊れている側は本体がほぼ定数に潰れる
    pg = apply_calibration(np.asarray(bulk, np.float32), good)
    pb = apply_calibration(np.asarray(bulk, np.float32), bad)
    def spread(p):
        return float(np.percentile(p, 75) - np.percentile(p, 25))
    assert spread(pg) > 5 * spread(pb), \
        f"本体の広がり: 直した側 {spread(pg):.3f} / 現行 {spread(pb):.3f}"
    # 較正が自分で「教師がほぼ定数になっている」と申告すること（学習の出力で気づけるように）
    assert bad["spread"] < 0.05 < good["spread"], (
        f"較正が自分の壊れ具合を申告していない: p90 {bad['spread']:.4f} / bulk {good['spread']:.4f}")
    assert bad["scale"] == "p90" and good["scale"] == "bulk"
    assert 0.25 < bad["sentinel_frac"] < 0.35

    # 葉が価値ネットの反復（探索値が [0,1] に収まる）では両者が一致する＝この指定に副作用は無い
    v3 = rng.uniform(size=n2).astype(np.float32)
    assert abs(calib_scale(v3, "bulk") - calib_scale(v3, "p90")) < 1e-6

    # λ > 0 は best_v の指定を強制する（V が 1 エポック目最良で以降悪化する再発への備え・§4.4）
    import argparse
    import experiments.drl_train as dt
    args = argparse.Namespace(lam=0.7, select="last", seed=0, threads=1, train="x", valid="y",
                              max_records=None, vtarget="max", calib_scale="bulk")
    with pytest.raises(SystemExit) as e:
        dt.train(args)
    assert "best_v" in str(e.value) or "no record files" in str(e.value)


# ------------------------------------------------------ 9. eval_vb の空回し
def test_eval_vb_null_run(tmp_path):
    """同じ版どうしを当てると 0.5 付近に出る（配管の検査・§4.6-4）。

    ここがずれていたら測り方が壊れているので、門番の数字も信用してはならない。
    """
    pytest.importorskip("meicho_rs")
    import eval_vb
    out = str(tmp_path / "null.json")
    assert eval_vb.main(["--deck", "SD001", "--iter", "1", "--null", "--n", "60",
                         "--anchor-n", "20", "--skip-canary", "--workers", "2",
                         "--out", out]) == 0
    d = json.load(open(out, encoding="utf-8"))
    gate = d["runs"][0]
    assert gate["lo"] <= 0.5 <= gate["hi"], \
        f"同じ版どうしなのに 0.5 が信頼区間に入らない: {gate}"
    # 錨は新旧が同一なので差はぴったり 0（同じシード・同じ spec）
    for a in d["anchors"]:
        assert a["diff"] == 0.0, f"空回しなのに錨に差が出た: {a}"


# ------------------------------------------------------------ 10. シード帯
def test_seed_bands_registered():
    """§7.6 の帯が台帳に登録済みで、記録帯と評価帯が重ならないこと。"""
    import eval_vb
    path = os.path.join(os.path.dirname(__file__), "..", "experiments", "seed_bands.json")
    with open(path, encoding="utf-8") as f:
        led = json.load(f)

    def band_of(seed):
        for b in led["bands"]:
            if b["start"] <= seed <= b["end"]:
                return b
        return None

    # 記録: 反復 1〜5 = 34〜38 万台（各 10,000 幅）。学習に使える種別であること。
    for k in range(1, 6):
        s = 340000 + (k - 1) * 10000
        b = band_of(s)
        assert b is not None, f"反復 {k} の記録帯 {s} が未登録"
        assert b["kind"] not in ("ladder", "validate"), f"記録帯 {s} が評価専用になっている"
        assert band_of(s + 9999) is b

    # 評価: 反復ごとに 4,000 幅。記録帯と重ならず、評価専用として登録されていること。
    for k in range(1, 6):
        e = eval_vb.eval_band(k)
        assert e == 390000 + (k - 1) * 4000
        b = band_of(e)
        assert b is not None and b["kind"] == "validate", f"評価帯 {e} が validate でない"
        assert band_of(e + eval_vb.EVAL_BAND_WIDTH - 1) is b
        assert e >= 390000 > 389999, "評価帯が記録帯と重なっている"

    # 帯の中の内訳が重ならない（門番 1200／錨 600×3／カナリア 200）
    used = [(eval_vb.OFFSETS["gate"], 1200), (eval_vb.OFFSETS["anchor_planner"], 600),
            (eval_vb.OFFSETS["anchor_h"], 600), (eval_vb.OFFSETS["anchor_greedy"], 600),
            (eval_vb.OFFSETS["canary"], 200)]
    used.sort()
    for (o, n), (o2, _) in zip(used, used[1:]):
        assert o + n <= o2, f"帯の中の割り当てが重なっている: {used}"
    assert used[-1][0] + used[-1][1] <= eval_vb.SPARE < eval_vb.EVAL_BAND_WIDTH

    # 台帳全体として帯が重複していないこと（D-028）と next_free
    bands = sorted(led["bands"], key=lambda b: b["start"])
    for a, b in zip(bands, bands[1:]):
        assert a["end"] < b["start"], f"帯が重複している: {a['start']}.. と {b['start']}.."
    assert bands[-1]["end"] < led["next_free"], "next_free が登録済みの帯と重なっている"
    # 門番の境界の追試の帯（§7.1・D-059 の型）。**本測定の帯と重ならないこと。**
    retest = band_of(410000)
    assert retest is not None and retest["kind"] == "validate"
    for k in range(1, 6):
        assert not (retest["start"] <= eval_vb.eval_band(k) <= retest["end"]), \
            "追試の帯が本測定の評価帯と重なっている"
    # 反復 6 以降は勝手に伸ばさない（新規登録を促す）
    with pytest.raises(SystemExit):
        eval_vb.eval_band(6)


# ============================================= D-065 便 4: 輪の再始動（loop 2）
# 計画書 §5.1 の T-12。固定するのは 3 つ。
#
# 1. **loop 1 の定義が 1 文字も変わらない**（loop を足したせいで過去の反復が再現しなくなる事故の予防）
# 2. loop 2 の探索器が「**便 2 で採った組み合わせ**」であること
#    （計画書に書いてある字面には、便 2 で**却下された**つまみが混じっている。§5.1 の訂正）
# 3. 反復 4' の V_{k-1} が loop 1 の V_3 を指すこと（輪のつなぎ目）

# loop 1 の定義の「動かぬ証拠」。**この表を書き換えるときは、過去の反復が再現しなくなることを意味する。**
LOOP1_GOLDEN = {
    1: {"extra_turns": 1, "opp_policy_net": "drl_sd001_s1.json", "opp_policy_root_only": True},
    2: {"extra_turns": 1, "opp_policy_net": "drl_sd001_s1.json", "opp_policy_root_only": True,
        "value_net": "drl_sd001_vb1.json"},
    3: {"extra_turns": 1, "opp_policy_net": "drl_sd001_s1.json", "opp_policy_root_only": True,
        "value_net": "drl_sd001_vb2.json"},
    4: {"extra_turns": 1, "opp_policy_net": "drl_sd001_s1.json", "opp_policy_root_only": True,
        "value_net": "drl_sd001_vb3.json"},
    5: {"extra_turns": 1, "opp_policy_net": "drl_sd001_s1.json", "opp_policy_root_only": True,
        "value_net": "drl_sd001_vb4.json"},
}


def test_loop1_definition_is_untouched():
    """**loop 1 の反復 1〜5 の定義が 1 文字も変わっていない**（T-12）。

    `--loop` を足したせいで loop 1 の中身が動くと、D-064 の反復がすべて再現しなくなる。
    既定（`loop` を渡さない）と `loop=1` を明示したときが同じであることも見る。
    """
    import vb
    for k, want in LOOP1_GOLDEN.items():
        assert vb.kwargs_for("SD001", k) == want, f"loop 1 の反復 {k} の定義が変わっている"
        assert vb.kwargs_for("SD001", k, loop=1) == want
        assert vb.model_name("SD001", k) == f"drl_sd001_vb{k}.json"
        assert vb.model_name("SD001", k, loop=1) == f"drl_sd001_vb{k}.json"
    # 記録のときも loop 1 は何も足さない（loop 1 の記録は取り直しを使っていない）
    assert vb.kwargs_for("SD001", 2, recording=True) == LOOP1_GOLDEN[2]


def test_loop2_search_is_what_bin2_actually_adopted():
    """loop 2 の探索器は**便 2 で採った組み合わせ**（a1 ＋ a5）であること。

    **計画書 §5.1 の字面には従わない。** そこに書いてある `align_leaves: True` と `samples: 12` は
    計画書を書いた時点の予想であって、便 2 の測定で**どちらも却下された**
    （葉の整列 0.441〜0.511 で有害／決定化 12 本 0.489 で効かない）。
    §5.1 のコメント自身が「便 2 で採った組み合わせに合わせる」と書いているので、
    **字面ではなくコメントの意図に従う**。採ったのは a1（選択フェイズ＋solo 4 本）と
    a5（代打ちを π に・範囲は proxy）である。
    """
    import vb
    kw = vb.kwargs_for("SD001", 4, loop=2)
    assert kw["choice_phases"] is True and kw["solo_samples"] == 4, "a1 が入っていない"
    assert kw["policy_scope"] == "proxy", "a5 が入っていない"
    assert "align_leaves" not in kw, "却下された葉の整列が入っている（便 2 で有害と分かっている）"
    assert "samples" not in kw, "却下された決定化 12 本が入っている（便 2 で効かないと分かっている）"
    assert kw["extra_turns"] == 1
    assert kw["opp_policy_net"] == "drl_sd001_s1.json" and kw["opp_policy_root_only"] is True, \
        "相手モデル π₀ は据え置き（設計書 §3.6）"


def test_loop2_joins_onto_loop1_v3():
    """反復 4' の V_{k-1} は **loop 1 の V_3**（輪のつなぎ目・T-12）。"""
    import vb
    assert vb.model_name("SD001", 3, loop=2) == "drl_sd001_vb3.json", \
        "loop 2 の入口の 1 つ前は loop 1 の V_3 を指すこと"
    assert vb.model_name("SD001", 4, loop=2) == "drl_sd001_vc4.json"
    assert vb.model_name("SD001", 5, loop=2) == "drl_sd001_vc5.json"
    kw = vb.kwargs_for("SD001", 4, loop=2)
    assert kw["value_net"] == "drl_sd001_vb3.json"
    kw5 = vb.kwargs_for("SD001", 5, loop=2)
    assert kw5["value_net"] == "drl_sd001_vc4.json"


def test_loop2_proxy_pi_is_fixed_across_iterations():
    """輪 2 の**代打ち π は反復をまたいで固定**であること（2026-09-06 の裁定）。

    計画書 §5.1 は「反復 k の代打ちに V_{k-1} の π 頭を使う」（＝反復ごとに変わる）と
    書いていたが、2 つの理由でそうしない。

    1. **champion に揃えるため。** champion は蒸留した固定の π（`pi_small64_e10.json`）を
       代打ちに使う。輪の目的は「champion の探索器のための V を育てる」ことなので、
       輪の探索器が champion と違っては筋が通らない
    2. **探索器を反復間で動かさないため。** 代打ちが反復ごとに変わると、門番で見ている差が
       「V が良くなった差」なのか「探索器が変わった差」なのか区別できなくなる
       （計画書 §5.1 自身が注意している取り違えと同じもの）
    """
    import vb
    import champion as chmod
    pi = [vb.kwargs_for("SD001", k, loop=2)["policy_net"] for k in (4, 5, 6)]
    assert len(set(pi)) == 1, f"代打ち π が反復ごとに変わっている: {pi}"
    assert pi[0] == chmod.CHAMPIONS["SD001"]["policy_net"], \
        "輪 2 の代打ち π が champion のものと違う（輪と champion の探索器は揃えること）"
    assert vb.kwargs_for("SD001", 4, loop=2)["policy_scope"] == "proxy"


def test_reeval_is_only_for_recording():
    """取り直し（`reeval_samples`）は**記録のときだけ**付ける。

    案 C で「取り直しは対局を変えない」ようにしたので、評価に付けても結果は同じで**時間だけ損**する。
    だから探索器の定義には入れず、記録の口にだけ足す。
    """
    import vb
    rec = vb.kwargs_for("SD001", 4, loop=2, recording=True)
    ev = vb.kwargs_for("SD001", 4, loop=2)
    assert rec["reeval_samples"] == 4, "記録に取り直しが付いていない（fresh が取れない）"
    assert "reeval_samples" not in ev, "評価に取り直しが付いている（時間の無駄）"
    assert {k: v for k, v in rec.items() if k != "reeval_samples"} == ev, \
        "記録と評価で探索器が違う（取り直し以外は同じでなければならない）"


def test_loop2_describe_says_which_loop():
    """表示に loop が出ること（報告で loop 1 と取り違えないため）。"""
    import vb
    d1 = vb.describe("SD001", 4, loop=1)
    d2 = vb.describe("SD001", 4, loop=2)
    assert d1 != d2
    assert "vb3" in d2 and ("輪2" in d2 or "loop 2" in d2 or "第2の輪" in d2)


def test_unknown_loop_is_rejected():
    """知らない loop 番号は黙って 1 として動かさず、はっきり止める。"""
    import vb
    with pytest.raises((SystemExit, KeyError, AssertionError)):
        vb.kwargs_for("SD001", 4, loop=9)


def test_loop2_spec_resolves_both_nets():
    """spec 経由で `value_net` と `policy_net` の両方がパス解決されること。

    片方だけ解決し忘れると Rust 側が「そんなファイルは無い」と言って止まる。
    """
    import vb
    from arena import load_deck
    pool = load_deck("SD001")["action_deck"]
    sp = vb.spec("SD001", pool, 4, loop=2)
    for key in ("value_net", "policy_net", "opp_policy_net"):
        assert os.path.isabs(sp[key]) or os.path.exists(sp[key]), f"{key} が解決されていない: {sp[key]}"
    assert sp["policy_scope"] == "proxy" and sp["choice_phases"] is True


def test_every_spec_maker_resolves_the_proxy_pi():
    """**spec を作る口はいくつもある。**そのすべてで代打ちの π が解決されること。

    `vb.spec` だけを見ていて実際に落ちた（2026-09-07）。門番を回す `eval_vb.specs_for`
    は自前の `_resolve` を持っており、そこの鍵の一覧に `policy_net` が無かったため、
    Rust 側が生のファイル名 `pi_small64_e10.json` を開こうとして
    `No such file or directory` で止まった。**存在するファイルであること**まで見る
    （絶対パスかどうかでは、解決し忘れた相対名が作業場所によって通ってしまう）。
    """
    import vb
    import eval_vb
    from experiments.arena import load_deck
    pool = load_deck("SD001")["action_deck"]

    makers = {"vb.spec": [vb.spec("SD001", pool, 4, loop=2)]}
    new, old = eval_vb.specs_for("SD001", pool, 4, loop=2)
    makers["eval_vb.specs_for"] = [new, old]

    for who, specs in makers.items():
        for sp in specs:
            for key in ("value_net", "policy_net", "opp_policy_net"):
                assert key in sp, f"{who}: {key} が spec から落ちている"
                assert os.path.exists(sp[key]), \
                    f"{who}: {key} が解決されていない（そんなファイルは無い）: {sp[key]}"


def test_eval_vb_resume_matches_one_shot():
    """**塊に割っても、1 回で回したのと同じ数が出る**こと。

    1 局はシードだけで決まる約束（`arena.series` の取り決め）なので、n 局を
    シードの範囲で割っても各局は変わらない。これが崩れると、中断・再開した測定は
    「1 回で回した測定」と別物になり、比べてよい数ではなくなる。
    """
    from experiments.arena_rs import GREEDY, HEURISTIC, ensure_cards, series_rs
    ensure_cards()
    deck = load_deck("SD001")
    cfg, pool = mirror_config(deck), deck["action_deck"]
    a, b = GREEDY(pool), HEURISTIC()
    whole = series_rs(a, b, 60, cfg, workers=2, seed0=999000)
    w = d = 0
    for off in (0, 20, 40):
        r = series_rs(a, b, 20, cfg, workers=2, seed0=999000 + off)
        w, d = w + r.wins, d + r.decided
    assert (whole.wins, whole.decided) == (w, d)


def test_paired_from_counts_equals_paired_diff():
    """錨の対差を「数え上げ → 後から計算」に置き換えても、値が 1 ビットも変わらないこと。

    差 d は局ごとに −1 / 0 / +1 しか取らないので、4 つの数から平均も標準偏差も厳密に出せる。
    信頼区間まで一致することを見る（区間がずれたら採否の判定がずれる）。
    """
    import eval_vb as E
    from experiments.arena_rs import GREEDY, HEURISTIC, ensure_cards
    ensure_cards()
    deck = load_deck("SD001")
    cfg, pool = mirror_config(deck), deck["action_deck"]
    new, old, opp = GREEDY(pool, samples=6), GREEDY(pool, samples=3), HEURISTIC()

    ref = E.paired_diff(cfg, new, old, opp, 999100, 60, 2)
    acc = {"both_win": 0, "new_only": 0, "old_only": 0, "both_lose": 0}
    for off in (0, 20, 40):
        for key, v in E.paired_counts(cfg, new, old, opp, 999100 + off, 20, 2).items():
            acc[key] += v
    got = E.paired_from_counts(acc)

    assert ref["pairs"] == got["pairs"] > 0
    assert ref["new_only"] == got["new_only"] and ref["old_only"] == got["old_only"]
    for key in ("new_p", "old_p", "diff", "ci"):
        assert abs(ref[key] - got[key]) < 1e-12, (key, ref[key], got[key])
    assert ref["clearly_worse"] == got["clearly_worse"]


def _run_eval_vb(args: list, tmp_path, child_locale: str = None):
    """`eval_vb.py` を子プロセスで回して (returncode, 出力) を返す。

    **出力は必ず UTF-8 で受ける。** 既定のまま `text=True` にすると親は
    ロケールの符号化（日本語 Windows では cp932）で読もうとして、
    道具の UTF-8 の出力が文字化けする。`scripts/make_dist.py` の `_UTF8` と同じ手当てである。

    `child_locale` を渡すと、**子のロケールの符号化をそれに固定**する
    （cp932 を渡せば日本語 Windows と同じ状況を、どの環境でも作れる）。
    """
    import subprocess
    here = os.path.join(os.path.dirname(__file__), "..")
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    if child_locale:
        env["PYTHONIOENCODING"] = child_locale
    else:
        env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, os.path.join(here, "experiments", "eval_vb.py")] + args,
                       capture_output=True, text=True, cwd=here,
                       encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout + p.stderr)


def _stale_resume(tmp_path):
    """条件の違う途中経過を置いて、`--out` を返す。"""
    out = tmp_path / "x.json"
    res = tmp_path / "x.resume.json"
    res.write_text(json.dumps({"key": {"deck": "SD001", "iter": 99, "loop": 7},
                               "gate": {"n_done": 500, "wins": 400, "decided": 500}}),
                   encoding="utf-8")
    return out


def test_resume_refuses_a_different_measurement(tmp_path):
    """**条件が違う途中経過には足し込まない**こと（混ざった数を出さないため）。"""
    out = _stale_resume(tmp_path)
    rc, text = _run_eval_vb(["--deck", "SD001", "--iter", "1", "--null", "--n", "2",
                             "--out", str(out)], tmp_path)
    assert rc != 0, text
    assert "別の条件" in text


def test_report_survives_a_console_that_cannot_write_subscripts(tmp_path):
    """**報告の文字が書けない環境でも、道具は理由を言えること**（D-082 追記 1）。

    報告の文には `π₀` が入っていて、**`₀`（U+2080）は cp932 で書けない**。
    Python は標準出力がコンソールのときは Windows のコンソール API を直に叩くので
    日本語 Windows でも書けるが、**パイプやファイルに向けるとロケールの符号化を使う**。
    そのため「別の条件の途中経過には足し込まない」と**言う前に** `UnicodeEncodeError` で
    落ちていた——マスターの PC で実際に起きて、この検査が捕まえた形である。

    ここでは子の `PYTHONIOENCODING` を `cp932` に固定して、**どの環境からでも
    同じ状況を作って**確かめる。`eval_vb.main` が表示を UTF-8 に寄せていれば通る。
    """
    out = _stale_resume(tmp_path)
    rc, text = _run_eval_vb(["--deck", "SD001", "--iter", "1", "--null", "--n", "2",
                             "--out", str(out)], tmp_path, child_locale="cp932")
    assert "UnicodeEncodeError" not in text, \
        f"報告の途中で落ちている（表示の符号化が寄せられていない）:\n{text[-800:]}"
    assert rc != 0, text
    assert "別の条件" in text
    # 記録する文字列は変えていない＝ラベルに `π₀` が残っていること
    assert "π₀" in text, "ラベルを書き換えてしまっている（途中経過の鍵と結果が読めなくなる）"


def test_canary_chunks_merge_to_the_same_numbers():
    """カナリアも塊に割って足せること（平均は合計と件数から出し直す）。

    `merge_canary` が平均を「平均どうしの平均」で作ってしまうと、塊の大きさが
    そろわない最後の 1 塊で狂う。到達ターンの平均は**到達した局だけ**の平均、
    引かせた枚数は**全局**あたりの平均で、割る数が違うことも見る。
    """
    import eval_vb as E
    pool = load_deck("SD001")["action_deck"]
    whole = E.canary("SD001", pool, 1, list(range(393800, 393808)), 1)
    acc = {}
    for off in (0, 4):
        acc = E.merge_canary(acc, E.canary("SD001", pool, 1, list(range(393800 + off, 393804 + off)), 1))
    for key in ("games", "reached", "never", "mean_turn",
                "mean_extra_draws", "total_extra_draws_per_game"):
        a, b = whole[key], acc[key]
        assert a == b or abs(a - b) < 1e-9, (key, a, b)
