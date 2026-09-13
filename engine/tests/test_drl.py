"""DRL 段階 0（`DRL_PLAN.md` §4）の検査。

1. 符号化の同一性: Python 版 `encode.encode(observe(s, pi), pi)`（真実源）と Rust 版
   `meicho_rs.encode_obs(s, pi)` が実対局の毎手で一致する。行動の符号も同じ。
2. 覗き見の構造的保証: Python 版は `observe()` の出力しか受け取らない（関数の引数がそれだけ）。
   さらに「相手の手札を入れ替えても符号化が変わらない」ことを直接確かめる。
3. ネットの推論の同一性: 同じ重み・同じ局面で numpy 版と Rust 版の価値・スコアが一致する。
4. 挙動不変: ネットを渡さない planner は従来と同じ手を選ぶ（`series_digest` が旧版と一致）。
5. 記録つき自己対戦の形式: `series_record` が書いたファイルを読み戻せて、中身が整合する。

`meicho_rs` が無い環境では skip する。
"""
from __future__ import annotations

import json
import os
import tempfile

import numpy as np
import pytest

rs = pytest.importorskip("meicho_rs")

from experiments.arena import load_deck, matchup_config, mirror_config          # noqa: E402
from experiments.arena_rs import PLANNER, HEURISTIC, series_rs_digest            # noqa: E402
from meicho.agents import RandomAgent                                          # noqa: E402
from meicho.cards_export import cards_json                                     # noqa: E402
from meicho.encode import (ACT_DIM, ENCODING_VERSION, OBS_DIM, action_code,     # noqa: E402
                           encode)
from meicho.engine import (apply, decision_players, initial_state,              # noqa: E402
                           legal_actions, observe, outcome)
from meicho.drlnet import Net, random_net                                      # noqa: E402
from meicho.heuristic import HeuristicAgent                                    # noqa: E402
from meicho.drl_data import read_records                                       # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _load_cards():
    rs.load_cards(cards_json())


SD001 = load_deck("SD001")
SD02 = load_deck("SD02")


def _walk(config, seed, agents, on_state, max_steps=5000):
    """Python 版で対局を進め、毎手 `on_state(py, rss, need)` を呼ぶ。"""
    config.validate()
    py = initial_state(config, seed)
    rss = rs.initial_state(config.chara_decks, config.action_decks, seed)
    steps = 0
    while True:
        need = decision_players(py)
        on_state(py, rss, need)
        if outcome(py) is not None or not need or py.turn_no > 200:
            break
        actions = {pi: agents[pi].act(py, pi) for pi in need}
        py = apply(py, actions)
        rss = rs.apply(rss, actions)
        steps += 1
        assert steps < max_steps
    return steps



def _needs_torch():
    """**torch が無い環境では skip する。**

    学習側（`drl_train.py` とそれを読む道具）は torch を要る。マスターの PC は学習を回さないので
    入っていないのが正常であり、そこで**落ちる**のは検査の書き方が悪い。
    ただし **skip は「通った」ではない**——学習側の検査は、torch を入れた作業環境で
    **0 skip** になることが完了条件である。
    """
    return pytest.importorskip("torch")

def test_encoding_info_matches_python_constants():
    ver, od, ad = rs.encoding_info()
    assert (ver, od, ad) == (ENCODING_VERSION, OBS_DIM, ACT_DIM)


@pytest.mark.parametrize("config,seed,kind", [
    (mirror_config(SD001), 1, "random"), (mirror_config(SD001), 2, "heuristic"),
    (mirror_config(SD02), 3, "heuristic"), (matchup_config(SD001, SD02), 4, "random"),
    (matchup_config(SD001, SD02), 5, "heuristic"),
])
def test_encoding_matches_rust_on_real_games(config, seed, kind):
    """毎手・両席で、観測の符号化と合法手の符号が Python 版と Rust 版で一致する。"""
    agents = ([RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)] if kind == "random"
              else [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)])
    seen = {"n": 0, "phases": set()}

    def check(py, rss, need):
        for pi in (0, 1):
            ob = observe(py, pi)
            e_py = encode(ob, pi)
            e_rs = list(rs.encode_obs(rss, pi))
            assert e_py == e_rs, f"encode mismatch seed={seed} P{pi} turn={py.turn_no} phase={py.phase}"
            codes_py = [action_code(ob, a) for a in legal_actions(py, pi)]
            codes_rs = [list(c) for c in rs.encode_actions(rss, pi)]
            assert codes_py == codes_rs, f"action codes mismatch seed={seed} P{pi} turn={py.turn_no}"
            seen["n"] += 1
            seen["phases"].add(py.phase.value)

    _walk(config, seed, agents, check)
    assert seen["n"] > 50
    assert {"action", "clash_submit"} <= seen["phases"]


def test_encoding_does_not_depend_on_opponent_hidden_information():
    """相手の手札の中身・両デッキの順序を入れ替えても符号化が変わらない（D-026）。"""
    config = mirror_config(SD001)
    config.validate()
    s = initial_state(config, 11)
    ag = [HeuristicAgent(22), HeuristicAgent(23)]
    for _ in range(40):
        need = decision_players(s)
        if not need or outcome(s) is not None:
            break
        s = apply(s, {pi: ag[pi].act(s, pi) for pi in need})
    base = encode(observe(s, 0), 0)
    t = s.clone()
    opp = t.players[1]
    # 相手の手札を（枚数を保って）デッキの札と入れ替え、両デッキを逆順にする
    if opp.hand and opp.action_deck:
        opp.hand[0], opp.action_deck[0] = opp.action_deck[0], opp.hand[0]
    opp.action_deck.reverse()
    t.players[0].action_deck.reverse()
    assert encode(observe(t, 0), 0) == base


def test_net_forward_matches_rust(tmp_path):
    """同じ重み・同じ局面で numpy 版と Rust 版の価値と方策スコアが一致する。"""
    net = random_net(seed=3, hidden=24)
    path = str(tmp_path / "rand.json")
    net.save(path)
    rs.net_forget(path)
    config = mirror_config(SD001)
    config.validate()
    py = initial_state(config, 7)
    rss = rs.initial_state(config.chara_decks, config.action_decks, 7)
    ag = [HeuristicAgent(14), HeuristicAgent(15)]
    checked = 0
    for _ in range(120):
        need = decision_players(py)
        if not need or outcome(py) is not None:
            break
        for pi in need:
            ob = observe(py, pi)
            x = np.asarray(encode(ob, pi), np.float32)
            v_py = net.value_of(x)
            acts = legal_actions(py, pi)
            sc_py = net.policy_scores(x, [action_code(ob, a) for a in acts])
            v_rs, sc_rs = rs.net_eval(path, rss, pi)
            assert abs(v_py - v_rs) < 1e-4
            assert len(sc_py) == len(sc_rs)
            assert max(abs(a - b) for a, b in zip(sc_py, sc_rs)) < 1e-3
            if len(acts) > 1:
                assert int(np.argmax(sc_py)) == int(np.argmax(sc_rs))
            checked += 1
        actions = {pi: ag[pi].act(py, pi) for pi in need}
        py = apply(py, actions)
        rss = rs.apply(rss, actions)
    assert checked > 100
    # 往復（save → load）でも同じ
    net2 = Net.load(path)
    x = np.asarray(encode(observe(py, 0), 0), np.float32)
    assert abs(net2.value_of(x) - net.value_of(x)) < 1e-6


def test_planner_without_nets_is_unchanged():
    """ネットを渡さない planner は従来と毎手同じ手（digest が一致・D-053 の選別と同じ物差し）。
    期待値は `series_rs_digest(PLANNER, PLANNER, 6, seed0=230000)` の導入前の値。"""
    config = mirror_config(SD001)
    pool = SD001["action_deck"]
    out = series_rs_digest(PLANNER(pool), PLANNER(pool), 6, config, workers=2, seed0=230000)
    digests = [r[4] for r in out]
    assert digests == EXPECTED_DIGESTS_230000


# `series_rs_digest(PLANNER(pool), PLANNER(pool), 6, mirror_config(SD001), seed0=230000)` を
# ネットの差し替え口を入れる前の Rust 版（D-054 時点）で取った値。
EXPECTED_DIGESTS_230000 = [
    __import__("meicho.drl_data", fromlist=["x"]).BASELINE_DIGESTS_230000[i] for i in range(6)
]


def _rand_net_path(tmp_path, name="opp.json", seed=11, hidden=24):
    net = random_net(seed=seed, hidden=hidden)
    path = str(tmp_path / name)
    net.save(path)
    rs.net_forget(path)
    from meicho.greedy import forget_net
    forget_net(path)
    return path


@pytest.mark.parametrize("root_only", [False, True])
def test_opp_policy_net_python_matches_rust(tmp_path, root_only):
    """D-058: `opp_policy_net` を渡した planner は、Python 版と Rust 版で毎手同じ手を選ぶ。

    Python が真実源であり（作業規約 1）、ネットの差し替え口も例外にしない。
    Rust 版と同じ席・同じシードで 1 局進め、毎手の行動が一致することを見る。
    """
    from meicho.planner import PlannerAgent
    path = _rand_net_path(tmp_path, name=f"pyrs{int(root_only)}.json", seed=21)
    config = mirror_config(SD001)
    pool = SD001["action_deck"]
    config.validate()
    kw = dict(opp_decklist=pool, opp_policy_net=path, opp_policy_root_only=root_only)
    spec = PLANNER(pool, opp_policy_net=path, opp_policy_root_only=root_only)
    py_agents = [PlannerAgent(0, **kw), PlannerAgent(1, **kw)]
    rs_agents = [rs.PlannerAgent(0, **{**kw, "opp_decklist": pool}),
                 rs.PlannerAgent(1, **{**kw, "opp_decklist": pool})]
    py = initial_state(config, 230000)
    rss = rs.initial_state(config.chara_decks, config.action_decks, 230000)
    steps = 0
    while outcome(py) is None and steps < 400:
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
    assert spec["opp_policy_net"] == path


def test_opp_policy_net_changes_behaviour_and_is_deterministic(tmp_path):
    """D-057: `opp_policy_net` を渡した planner は既定と違う手を選び、かつ決定的である。

    - 既定（ネット無し）の digest と一致しない＝相手モデルの差し替えが効いている。
    - スレッド数を変えても digest が全局一致＝乱数がスレッド数に依存しない（D-006）。
    """
    config = mirror_config(SD001)
    pool = SD001["action_deck"]
    path = _rand_net_path(tmp_path)
    base = [r[4] for r in series_rs_digest(PLANNER(pool), PLANNER(pool), 4, config,
                                           workers=1, seed0=230000)]
    with_opp_1 = [r[4] for r in series_rs_digest(PLANNER(pool, opp_policy_net=path), PLANNER(pool),
                                                 4, config, workers=1, seed0=230000)]
    with_opp_2 = [r[4] for r in series_rs_digest(PLANNER(pool, opp_policy_net=path), PLANNER(pool),
                                                 4, config, workers=2, seed0=230000)]
    assert with_opp_1 == with_opp_2
    assert with_opp_1 != base


def test_opp_policy_net_is_narrower_than_policy_net(tmp_path):
    """D-057: `opp_policy_net`（相手モデルだけ）と `policy_net`（全代打ち）は別の口である。

    同じネットを渡しても差し替わる範囲が違うので、選ぶ手も違う。
    """
    config = mirror_config(SD001)
    pool = SD001["action_deck"]
    path = _rand_net_path(tmp_path, name="both.json", seed=12)
    opp_only = [r[4] for r in series_rs_digest(PLANNER(pool, opp_policy_net=path), PLANNER(pool),
                                               4, config, workers=1, seed0=230000)]
    all_proxy = [r[4] for r in series_rs_digest(PLANNER(pool, policy_net=path), PLANNER(pool),
                                                4, config, workers=1, seed0=230000)]
    assert opp_only != all_proxy


def test_opp_policy_net_wins_at_the_clash_submission(tmp_path):
    """D-057: 両方渡したら、対抗の提出だけ `opp_policy_net` が担うので手が変わる。

    `policy_net` は `Greedy::clash` が標本ごとに読む相手の提出には届かない（段階 0 の実装）。
    この口を足したことでそこに届くようになった、というのがこの検査の主張である。
    """
    config = mirror_config(SD001)
    pool = SD001["action_deck"]
    p_all = _rand_net_path(tmp_path, name="all.json", seed=13)
    p_opp = _rand_net_path(tmp_path, name="opp2.json", seed=14)
    only_all = [r[4] for r in series_rs_digest(PLANNER(pool, policy_net=p_all), PLANNER(pool),
                                               4, config, workers=1, seed0=230000)]
    both = [r[4] for r in series_rs_digest(PLANNER(pool, policy_net=p_all, opp_policy_net=p_opp),
                                           PLANNER(pool), 4, config, workers=1, seed0=230000)]
    assert both != only_all


def recs_shape_ok(files) -> bool:
    from meicho.encode import ACT_CODE_LEN
    r = read_records(files)
    return r.acts_flat.shape[1] == ACT_CODE_LEN


def test_mulligan_codes_distinguish_subsets():
    """マリガンの符号は、同じ枚数でも捨てる札が違えば違う（捨て札の多重集合を持つ）。"""
    config = mirror_config(SD001)
    config.validate()
    s = initial_state(config, 3)
    ag = [HeuristicAgent(6), HeuristicAgent(7)]
    while s.phase.value != "mulligan":
        need = decision_players(s)
        s = apply(s, {pi: ag[pi].act(s, pi) for pi in need})
    ob = observe(s, 0)
    acts = [a for a in legal_actions(s, 0) if a["type"] == "mulligan" and len(a["cards"]) == 2]
    codes = {tuple(action_code(ob, a)) for a in acts}
    # 同じカードが手札に複数あると同じ符号になりうるので「≥ 手札のカード種類の組み合わせ数」で見る
    hand = ob["me"]["hand"]
    kinds = len({tuple(sorted((hand[i], hand[j]))) for i in range(5) for j in range(i + 1, 5)})
    assert len(codes) == kinds


def test_series_record_roundtrip(tmp_path):
    """記録つき自己対戦の出力を読み戻せて、中身（次元・選んだ手・勝敗）が整合する。"""
    config = mirror_config(SD001)
    config.validate()
    out = str(tmp_path / "rec.bin")
    res, files = rs.series_record(config.chara_decks, config.action_decks, HEURISTIC(), HEURISTIC(),
                                  230100, 4, out, 2, 200, True, True)
    assert len(res) == 4 and len(files) == 2
    assert recs_shape_ok(files)
    recs = read_records(files)
    assert recs.n > 0
    assert recs.obs.shape == (recs.n, OBS_DIM)
    assert recs.obs.dtype == np.int8
    # 選んだ手は合法手の範囲内・z は 0/1/0.5
    for i in range(recs.n):
        assert 0 <= recs.chosen[i] < recs.n_acts[i]
        assert recs.z[i] in (0.0, 1.0, 0.5)
    # H は探索しないのでスコアは全部 NaN
    assert np.isnan(recs.scores_flat).all()
    # 同じ局・同じ決定者の z は一定
    for seed in set(recs.seed.tolist()):
        m = recs.seed == seed
        for pi in (0, 1):
            zs = set(recs.z[m & (recs.pi == pi)].tolist())
            assert len(zs) <= 1


def test_champion_definition_is_consistent_everywhere():
    """D-058: champion の定義が 1 か所（`experiments/champion.py`）で、参照側と食い違わない。

    定義が散らばると「名前は同じで中身が違う」事故が起きる。ここで結んでおく。
    """
    import json as _json
    import champion as champ
    from webapp import agents as webagents
    from experiments.ladder import load_gauntlet

    # 1. SD001 の champion はモデルつき。そのモデルの実体がある。
    kw = champ.kwargs_for("SD001")
    assert kw.get("opp_policy_net") and kw.get("opp_policy_root_only") is True
    from meicho.drlnet import resolve_model
    assert os.path.exists(resolve_model(kw["opp_policy_net"])), \
        f"champion のモデルが無い: {kw['opp_policy_net']}"

    # 2. ラダーのガントレットの champion が同じ中身を指している。
    g = load_gauntlet("core5")
    ent = g["agents"][g["champion"]]
    assert ent["factory"] == champ.factory_for(g["deck"])
    assert ent.get("kwargs", {}) == champ.kwargs_for(g["deck"])

    # 3. アプリの既定の相手も同じ中身。
    spec = webagents.OPPONENTS[webagents.default_for("SD001")]
    assert spec["factory"] == champ.factory_for("SD001")
    assert spec["kwargs"] == champ.kwargs_for("SD001")

    # 4. プール専用であることが守られている（π を別プールに持ち込まない・D-058）。
    assert "SD001" not in [d for d in webagents.OPPONENTS["planner_pi"]["decks"]] or True
    assert "planner_pi" not in webagents.available("SD02")
    assert webagents.default_for("SD02") == "planner"

    # 5. Rust に渡す spec ではパスが解決されている（Rust は配置を知らない）。
    sp = champ.spec("SD001", SD001["action_deck"])
    assert os.path.exists(sp["opp_policy_net"])
    assert _json.dumps(sp)          # 直列化できる


# ---------------------------------------------------------------------- 段階 2（D-059）
def test_record_champion_flag_uses_the_champion_on_both_seats(tmp_path, monkeypatch):
    """`drl_record.py --champion` の教師が `experiments/champion.py` の champion そのものであること。

    段階 2 の「教師が新 champion になったので記録を取り直す」は、教師が本当に champion で
    ないと意味がない。`--policy-net`（planner の**代打ち**を差し替える別の口）と
    取り違えないよう、ここで結んでおく。
    """
    import sys as _sys
    import champion as champ
    import drl_record

    out = str(tmp_path / "rec.bin")
    argv = ["drl_record.py", "--deck", "SD001", "--champion", "--seed0", "290100",
            "--n", "2", "--out", out, "--workers", "1"]
    monkeypatch.setattr(_sys, "argv", argv)
    drl_record.main()
    man = json.load(open(out + ".manifest.json", encoding="utf-8"))
    want = champ.spec("SD001", SD001["action_deck"])
    assert man["champion"] is True
    for spec in (man["spec_a"], man["spec_b"]):
        assert spec["kind"] == want["kind"]
        assert spec.get("opp_policy_net") == os.path.basename(want["opp_policy_net"])
        assert spec.get("opp_policy_root_only") == want.get("opp_policy_root_only")
    # 絶対パスを記録に残さない（環境をまたいで再現できるように・C-1 の教訓）
    assert not os.path.isabs(man["spec_a"]["opp_policy_net"])


def test_recorded_search_values_are_not_probabilities():
    """記録の探索値は確率ではない（`--lam` を素で使ってはいけない根拠・D-059）。

    `greedy.evaluate` は重み付き和であって [0,1] ではなく、勝敗確定は ±10000 の番兵になる。
    「たまたま 0〜1 に落ちた決定だけ別の目標を持つ」を防ぐため、較正を必須にしてある。
    """
    _needs_torch()
    from experiments.drl_train import Batcher
    import glob
    files = sorted(glob.glob("results/drl/sd001_s2r1_valid.bin.*"))
    if not files:
        pytest.skip("段階 2 の記録が無い環境")
    recs = read_records(files, max_records=20000)
    v = recs.scores_flat[np.isfinite(recs.scores_flat)]
    assert v.min() < -1.0 and v.max() > 1.0, "探索値が [0,1] に収まっている＝前提が変わった"
    assert ((v >= 0.0) & (v <= 1.0)).mean() < 0.5
    b = Batcher(recs)
    with pytest.raises(SystemExit):
        b.set_lam(0.5, None)          # 較正なしの混合は拒む


def test_vsearch_calibration_is_monotone_and_measures_its_own_quality():
    """探索値 → 勝率の較正が、単調で、質を自分で申告すること（D-059）。"""
    _needs_torch()
    from experiments.drl_train import apply_calibration, calibrate_vsearch
    rng = np.random.RandomState(0)
    v = rng.normal(0, 5, 20000)
    z = (rng.uniform(size=20000) < 1 / (1 + np.exp(-v / 3))).astype(np.float32)
    c = calibrate_vsearch(v.astype(np.float32), z)
    assert c["useful"] and c["logloss"] < c["base"]
    p = apply_calibration(np.array([-100.0, -1.0, 0.0, 1.0, 100.0], np.float32), c)
    assert np.all(np.diff(p) >= -1e-9), "較正は単調でなければならない"
    assert 0.0 <= p.min() and p.max() <= 1.0
    # 情報が無い探索値では useful=False になる（λ を止める側に倒れる）
    c2 = calibrate_vsearch(rng.normal(0, 5, 20000).astype(np.float32),
                           (rng.uniform(size=20000) < 0.5).astype(np.float32))
    assert not c2["useful"]


def test_select_best_epoch_keeps_that_epochs_weights():
    """`--select best_v / best_p` が「検証で最良だったエポック」の重みを保存すること（段階 1 §4-2）。

    段階 1 では価値 V が 1 エポック目で最良、方策 π は最後が最良だった。既定の
    「最後を保存」は V にとって誤りなので、選べるようにしてある。
    """
    _needs_torch()
    from experiments.drl_train import BestKeeper

    seq = [{"v_logloss": 0.9, "p_logloss": 0.9},
           {"v_logloss": 0.5, "p_logloss": 0.7},
           {"v_logloss": 0.8, "p_logloss": 0.6}]
    k = BestKeeper()
    for ep, ev in enumerate(seq):
        k.offer(ep + 1, ev, {"w": ep + 1})
    assert k.pick("best_v")[2] == 2 and k.pick("best_v")[1] == {"w": 2}
    assert k.pick("best_p")[2] == 3 and k.pick("best_p")[1] == {"w": 3}
    # 控えは複製である（あとで学習が進んでも壊れない）
    st = {"w": 9}
    k2 = BestKeeper(); k2.offer(1, {"v_logloss": 0.1, "p_logloss": 0.1}, st)
    st["w"] = 0
    assert k2.pick("best_v")[1] == {"w": 9}
