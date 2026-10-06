"""汎用 AI の壁を越える案（D-163・設計書 `GENERALIST_WALL_DESIGN_20261006.md`）の道具の検査。

腕 B（§3.2 B-0）:
WB-1 `next_turn_index`: 手で作った 2 局の記録で、s₁ の選び方が手計算と一致する（次の自分の手番の行動フェイズの最初・
     無ければその手番の最初・行動フェイズ以外と s₁ の無い記録は -1・相手の手番の記録は飛ばす）
WB-2 `next_turn_values`: s₁ の無い記録は決着の値（その局の z）、ある記録は s₁ の観測を束ねた V に通した値
WB-3 `--vtarget next_turn` の Batcher: 行動フェイズ以外の記録の目標は `--vtarget max` とバイトで同じ。行動フェイズの記録だけ
     0.3·z + 0.7·較正(v_next) に替わる
WB-4 既定（`--vtarget` を渡さない）は、口を足す前の `drl_train.py`（commit `fcb46e3`）とネットのバイト・meta が同じ
WB-5 `--vtarget next_turn` は `--next-net`・`--lam > 0` を要り、meta に `next_turn` の報告（s₁ の無い割合・較正・相関・
     十分位・τ の寄り道の数）が入る。`--next-net` だけを渡すと止める

検査の対局は 935000..935999（kind=diag・D-163 で登録）で回す。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

TARGET = "ENV_SANGE_RM_TSUBAKI"
SEED0 = 935900
PRE_COMMIT = "fcb46e3"                 # 腕 B の口を足す前


def T():
    pytest.importorskip("torch")
    import drl_train
    return drl_train


# ------------------------------------------------------------------ WB-1
def test_next_turn_index_by_hand():
    D = T()
    A, C, CH = D.ACTION_PHASE, D.PHASE_NAMES.index("clash"), D.PHASE_NAMES.index("choice")
    # (seed, pi, turn, step, phase, 自分の手番か)
    rows = [
        (1, 0, 1, 0, A, 1),    # 0: 席0 手番1 行動 → s₁ は席0 の次の自分の手番 3 の行動（#6）
        (1, 1, 1, 1, C, 0),    # 1: 席1 相手の手番での対抗（自分の手番ではない）
        (1, 1, 2, 2, CH, 1),   # 2: 席1 手番2 選択（行動より先）
        (1, 1, 2, 3, A, 1),    # 3: 席1 手番2 行動 → 席1 の次の自分の手番は無い → -1
        (1, 0, 2, 4, C, 0),    # 4: 席0 相手の手番の対抗（飛ばす）
        (1, 0, 3, 6, CH, 1),   # 5: 席0 手番3 選択
        (1, 0, 3, 7, A, 1),    # 6: 席0 手番3 行動（手番3 の行動フェイズの最初）
        (2, 0, 1, 0, A, 1),    # 7: 別の局・席0 手番1 行動 → 手番3 に行動が無い → その手番の最初（#9）
        (2, 0, 2, 1, C, 0),    # 8
        (2, 0, 3, 2, CH, 1),   # 9: 席0 手番3 選択だけ
        (2, 1, 2, 3, A, 1),    # 10: 席1 手番2 行動 → 無い → -1
    ]
    a = np.array(rows)
    got = D.next_turn_index(a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])
    want = np.full(len(rows), -1)
    want[0], want[7] = 6, 9
    want[6] = -1                                   # 席0 手番3 の行動のあとに自分の手番は無い
    assert got.tolist() == want.tolist()
    # 並びを崩しても同じ
    perm = np.random.RandomState(0).permutation(len(rows))
    g2 = D.next_turn_index(*(a[perm, k] for k in range(6)))
    inv = np.argsort(perm)
    assert [perm[x] if x >= 0 else -1 for x in g2[inv]] == want.tolist()


# ------------------------------------------------------------------ WB-2
def _tiny_net(seed=0):
    from meicho.drlnet import Net
    from meicho.encode import OBS_DIM
    r = np.random.RandomState(seed)
    return Net([(r.normal(0, 0.05, (8, OBS_DIM)).astype(np.float32), r.normal(0, 0.1, 8).astype(np.float32))],
               (r.normal(0, 0.3, (1, 8)).astype(np.float32), np.array([0.1], np.float32)), [])


def test_next_turn_values_terminal_and_net():
    D = T()
    from meicho.encode import OBS_DIM
    A, C = D.ACTION_PHASE, D.PHASE_NAMES.index("clash")
    seed = np.array([5, 5, 5, 5]); pi = np.array([0, 1, 0, 1]); turn = np.array([1, 2, 3, 4])
    step = np.arange(4); phase = np.array([A, A, A, C])
    r = np.random.RandomState(1)
    obs = r.randint(-3, 4, (4, OBS_DIM)).astype(np.int8)
    obs[:, D.TURN_FLAG_COL] = [1, 1, 1, 0]
    z = np.array([1.0, 0.0, 1.0, 0.0], np.float32)
    net = _tiny_net()
    v, n_term = D.next_turn_values(seed, pi, turn, step, phase, obs, z, net)
    assert n_term == 2                                         # 席1 手番2・席0 手番3 は s₁ が無い
    assert abs(v[0] - net.value_of(obs[2].astype(np.float32))) < 1e-5
    assert v[1] == 0.0 and v[2] == 1.0 and np.isnan(v[3])


# ------------------------------------------------------------------ 記録（WB-3〜5）
@pytest.fixture(scope="module")
def recs(tmp_path_factory):
    pytest.importorskip("meicho_rs")
    T()
    import record_mix
    d = tmp_path_factory.mktemp("wallrec")
    sch = {"name": "wb", "teacher": {"name": "netfree", "tau": 0.0},
           "blocks": [{"kind": "mirror", "deck_a": f"env/{TARGET}", "deck_b": f"env/{TARGET}",
                       "seed0": SEED0, "n": 48}]}
    p = d / "wb.json"
    p.write_text(json.dumps(sch), encoding="utf-8")
    man = record_mix.main(["--schedule", str(p), "--out", str(d / "wb"), "--workers", "4"])
    return man["files"][0].rsplit(".b0.", 1)[0], d


def _args(stem, out, **kw):
    a = dict(train=stem, valid=stem, out=out, init=None, epochs=1, bs=256, lr=1e-3, wd=0.0,
             hidden=16, depth=2, phead=8, wv=1.0, wp=1.0, lam=0.7, vtarget="max",
             calib_by="none", calib_scale="bulk", select="best_v", distil_from=None,
             card_profile=False, seed=0, threads=2, max_records=None, keep_pairs=None)
    a.update(kw)
    return argparse.Namespace(**a)


@pytest.mark.slow
def test_batcher_next_turn_changes_only_action_targets(recs):
    D = T()
    from meicho.drl_data import read_records
    stem, _ = recs
    r = read_records(D.files_of(stem))
    net = _tiny_net()
    bm = D.Batcher(r, vtarget="max")
    bn = D.Batcher(r, vtarget="next_turn", next_net=net)
    assert np.array_equal(bm.vsearch, bn.vsearch, equal_nan=True)   # 探索値と較正は従来のまま
    calib = D.calibrate_vsearch(bm.vsearch, bm.z, scale="bulk")
    okn = np.isfinite(bn.vnext)
    assert okn.sum() == (bn.phase == D.ACTION_PHASE).sum() > 0
    cn = D.calibrate_vsearch(bn.vnext[okn], bn.z[okn], scale="bulk", min_n=50)
    bm.set_lam(0.7, calib)
    bn.set_next(cn)
    bn.set_lam(0.7, calib)
    act = bn.phase == D.ACTION_PHASE
    assert bm.target[~act].tobytes() == bn.target[~act].tobytes()
    q = D._sigmoid_calib(bn.vnext[act], cn)
    assert np.allclose(bn.target[act], 0.3 * bn.z[act] + 0.7 * q, atol=1e-6)
    assert not np.allclose(bm.target[act], bn.target[act])


# ------------------------------------------------------------------ WB-4
@pytest.mark.slow
def test_default_matches_pre_arm_b_code(recs, tmp_path):
    import importlib.util
    import subprocess
    D = T()
    stem, _ = recs
    try:
        src = subprocess.run(["git", "show", f"{PRE_COMMIT}:engine/experiments/drl_train.py"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"git か commit {PRE_COMMIT} が無い")
    old_py = tmp_path / "drl_train_pre_b.py"
    old_py.write_bytes(src)
    spec = importlib.util.spec_from_file_location("drl_train_pre_b", old_py)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    outs = {}
    for tag, mod in (("old", old), ("new", D)):
        out = str(tmp_path / f"{tag}.json")
        mod.train(_args(stem, out))
        m = json.load(open(out.replace(".json", ".meta.json"), encoding="utf-8"))
        for row in m["log"]:
            row.pop("sec")
        outs[tag] = (open(out, "rb").read(), m)
    assert outs["old"][0] == outs["new"][0]
    assert outs["old"][1] == outs["new"][1]
    assert "next_turn" not in outs["new"][1]


# ------------------------------------------------------------------ WB-5
@pytest.mark.slow
def test_next_turn_train_meta_and_refusals(recs, tmp_path):
    D = T()
    stem, d = recs
    net_path = str(d / "tiny_next.json")
    _tiny_net().save(net_path)
    with pytest.raises(SystemExit):
        D.train(_args(stem, str(tmp_path / "a.json"), vtarget="next_turn"))              # --next-net が無い
    with pytest.raises(SystemExit):
        D.train(_args(stem, str(tmp_path / "b.json"), next_net=net_path))                # next_turn でない
    with pytest.raises(SystemExit):
        D.train(_args(stem, str(tmp_path / "c.json"), vtarget="next_turn", next_net=net_path, lam=0.0,
                      select="last"))
    out = str(tmp_path / "ok.json")
    D.train(_args(stem, out, vtarget="next_turn", next_net=net_path))
    m = json.load(open(out.replace(".json", ".meta.json"), encoding="utf-8"))
    info = m["next_turn"]
    assert info["n_action"] > 0 and 0 <= info["terminal_frac"] <= 1
    assert set(info["calib"]) >= {"a", "b", "c", "spread"} and len(info["deciles_q"]) == 11
    assert "n_nonargmax_action" in info and m["vtarget"] == "next_turn"
