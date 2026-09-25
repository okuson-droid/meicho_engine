"""段階3 の土台の V（V_id 乱数 3 本のアンサンブル）を幅 3 倍の 1 本に組み直す道具の検査（D-132 追記 5・D-133）。

道具は `experiments/ensemble_net.py`。Rust の `value_net` はネット 1 本しか受けないので、K 本を 1 本の
全結合ネットに組み直して既存の JSON 形式で書き出す（Rust も符号化も変えない）。

守らせる条項:

N-1 値が正確: 組み直したネットの価値 = K 本のロジットの平均の sigmoid（numpy の参照実装・1e-5 以内）
N-2 Rust でも同じ: `meicho_rs.net_eval` で読めて、K 本を別々に Rust で通したロジットの平均の sigmoid と一致する
N-3 形: 第 1 層は K·H × OBS_DIM、第 2 層以降は K·H × K·H のブロック対角（ブロックの外は厳密に 0）、
    方策の頭は空、符号化の版と次元は元のまま
N-4 形の合わない K 本（幹の深さ・幅・符号化の版が違う）は組まずに落とす
N-5 わざと壊す側: ブロック対角の外に値を入れる／1/K を掛け忘れる、と N-1 の一致が崩れる（検査が効いていることの確認）
N-6 K=1 は元のネットと価値が一致する（方策の頭だけ落ちる）
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

import ensemble_net as EN                                               # noqa: E402
from meicho.drlnet import Net, random_net                               # noqa: E402
from meicho.encode import OBS_DIM                                       # noqa: E402


def _logit(net: Net, x) -> float:
    h = net.trunk_out(x)
    w, b = net.value
    return float((w @ h + b)[0])


def _mean_logit_value(nets, x) -> float:
    z = float(np.mean([_logit(n, x) for n in nets]))
    return 1.0 / (1.0 + np.exp(-z))


def _members(k=3, hidden=16):
    return [random_net(seed=10 + i, hidden=hidden) for i in range(k)]


def _inputs(n=40, seed=0):
    r = np.random.RandomState(seed)
    return [r.randint(0, 4, size=OBS_DIM).astype(np.float32) for _ in range(n)]


def test_value_is_mean_logit():
    """N-1: 組み直したネットの価値は K 本のロジットの平均の sigmoid。"""
    nets = _members()
    ens = EN.combine(nets)
    for x in _inputs():
        assert abs(ens.value_of(x) - _mean_logit_value(nets, x)) < 1e-5
    # 勝率の平均とは一般に一致しない（推しは「ロジットの平均」・D-132 追記 5）
    gaps = [abs(ens.value_of(x) - np.mean([n.value_of(x) for n in nets])) for x in _inputs()]
    assert max(gaps) > 0


def test_shape():
    """N-3: 形・ブロック対角・方策の頭なし・版と次元はそのまま。"""
    nets = _members(k=3, hidden=16)
    ens = EN.combine(nets)
    assert ens.trunk[0][0].shape == (48, OBS_DIM)
    w2 = ens.trunk[1][0]
    assert w2.shape == (48, 48)
    mask = np.zeros((48, 48), bool)
    for i in range(3):
        mask[16 * i:16 * (i + 1), 16 * i:16 * (i + 1)] = True
    assert np.all(w2[~mask] == 0.0)
    for i, n in enumerate(nets):
        assert np.array_equal(w2[16 * i:16 * (i + 1), 16 * i:16 * (i + 1)], n.trunk[1][0])
        assert np.array_equal(ens.trunk[0][0][16 * i:16 * (i + 1)], n.trunk[0][0])
    assert ens.value[0].shape == (1, 48)
    assert ens.policy == []
    d = ens.to_dict()
    assert d["hidden"] == 48 and d["policy"] == []
    assert (d["obs_dim"], d["act_dim"], d["encoding_version"]) == (nets[0].obs_dim, nets[0].act_dim,
                                                                   nets[0].encoding_version)


def test_refuses_mismatched_members():
    """N-4: 幹の深さ・幅・符号化の版が違う K 本は組まない。"""
    a = random_net(seed=1, hidden=16)
    b = random_net(seed=2, hidden=8)
    with pytest.raises(ValueError):
        EN.combine([a, b])
    c = random_net(seed=3, hidden=16)
    c.trunk = c.trunk[:1]
    c.value = (np.ones((1, 16), np.float32), np.zeros(1, np.float32))
    with pytest.raises(ValueError):
        EN.combine([a, c])
    d = random_net(seed=4, hidden=16)
    d.encoding_version = a.encoding_version - 1
    with pytest.raises(ValueError):
        EN.combine([a, d])
    e = random_net(seed=5, hidden=16)
    e.value = None
    with pytest.raises(ValueError):
        EN.combine([a, e])
    with pytest.raises(ValueError):
        EN.combine([])


def test_breaks_are_detected():
    """N-5: ブロック対角の外に値を入れる／1/K を掛け忘れると N-1 の一致が崩れる。"""
    nets = _members()
    xs = _inputs(20)
    ens = EN.combine(nets)
    w2 = ens.trunk[1][0].copy()
    w2[0, 20] = 0.5                                                      # ブロックの外
    broken = Net([ens.trunk[0], (w2, ens.trunk[1][1])], ens.value, [], ens.obs_dim, ens.act_dim,
                 ens.encoding_version)
    assert max(abs(broken.value_of(x) - _mean_logit_value(nets, x)) for x in xs) > 1e-4
    w, b = ens.value
    no_div = Net(ens.trunk, (w * 3.0, b * 3.0), [], ens.obs_dim, ens.act_dim, ens.encoding_version)
    assert max(abs(no_div.value_of(x) - _mean_logit_value(nets, x)) for x in xs) > 1e-4


def test_single_member_is_identity():
    """N-6: K=1 は元のネットと価値が一致する。"""
    n = random_net(seed=7, hidden=16)
    ens = EN.combine([n])
    for x in _inputs(10):
        assert abs(ens.value_of(x) - n.value_of(x)) < 1e-6


def test_rust_reads_the_ensemble(tmp_path):
    """N-2: Rust が組み直したネットを読み、K 本を別々に通したロジットの平均の sigmoid と一致する。"""
    rs = pytest.importorskip("meicho_rs")
    from arena import load_deck, matchup_config
    from arena_rs import ensure_cards
    from meicho.agents import RandomAgent
    ensure_cards()
    nets = _members(k=3, hidden=24)
    paths = []
    for i, n in enumerate(nets):
        p = str(tmp_path / f"m{i}.json")
        n.save(p)
        rs.net_forget(p)
        paths.append(p)
    ens_path = str(tmp_path / "ens.json")
    EN.combine(nets).save(ens_path)
    rs.net_forget(ens_path)
    da, db = load_deck("SD001"), load_deck("SD02")
    cfg = matchup_config(da, db)
    cfg.validate()
    s = rs.initial_state(cfg.chara_decks, cfg.action_decks, 843999)
    ag = [RandomAgent(1), RandomAgent(2)]
    from meicho.engine import initial_state
    py = initial_state(cfg, 843999)
    from meicho.engine import apply, decision_players, outcome
    checked = 0
    for _ in range(80):
        need = decision_players(py)
        if not need or outcome(py) is not None:
            break
        for pi in need:
            opp = (db if pi == 0 else da)["action_deck"]
            v_ens, sc = rs.net_eval(ens_path, s, pi, opp)
            assert sc == []                                              # 方策の頭なし
            z = []
            for p in paths:
                v, _ = rs.net_eval(p, s, pi, opp)
                z.append(np.log(v / (1.0 - v)))
            ref = 1.0 / (1.0 + np.exp(-np.mean(z)))
            assert abs(v_ens - ref) < 1e-4
            checked += 1
        actions = {pi: ag[pi].act(py, pi) for pi in need}
        py = apply(py, actions)
        s = rs.apply(s, actions)
    assert checked > 50
