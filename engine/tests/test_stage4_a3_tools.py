"""段階4 便 4-A3 の道具の検査（D-158・設計書 `GENERALIST_STAGE4_GLEARN_DESIGN_20261003.md` §6）。

A3-1 `drl_train --freeze trunk` は `--init` が無いと止める（ランダムな幹を凍結しても意味が無い）
A3-2 `--freeze trunk` で学ぶと、学習の前後で幹の重みが 1 ビットも変わらず、価値の頭と方策の頭は変わる。
     書き出すネットの形は凍結の有無によらず同じ（葉の V として読める）。meta に `freeze` と学習した重みの数が入る。
     壊し方: 凍結を外すと幹が動く（同じ検査で落ちる）
A3-3 既定（`freeze` を付けない・`None`）では、口を足す前と同じ出力: `freeze` の属性が無い args と `None` で
     ネットのバイトと meta（所要時間の欄を除く）が同じで、meta に `freeze` の欄が入らない。さらに口を足す前の
     `drl_train.py`（commit `1d4faee`）を git から取り出して同じ引数で回し、ネットのバイトと meta が同じ
     （git か commit が無い環境では skip）
A3-4 `diag_s4_move.py`: 同じネットどうしで M = 0・違うネットで M > 0／部品の v_logloss が学習の記録
     （`.meta.json`）の選んだエポックの値と 1e-4 で一致／束ねた V はロジットの平均
A3-5 便の検証の記録（対象デッキの 204 局）が容器にあれば、決定数が 17,041（無ければ skip）

検査の対局は 889900..889903（kind=diag・D-158 で登録）で回す。
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
SEED0 = 889900                        # 検査の帯（889000..889999・kind=diag・D-158）
VAL_STEM_ENV = "MEICHO_S4_TARGET_VAL"  # 便の検証の記録の接頭辞（A3-5・無ければ既定の置き場を探す）


@pytest.fixture(scope="module")
def recs(tmp_path_factory):
    rs = pytest.importorskip("meicho_rs")
    pytest.importorskip("torch")
    import record_mix
    d = tmp_path_factory.mktemp("a3rec")
    sch = {"name": "a3", "teacher": {"name": "netfree", "tau": 0.0},
           "blocks": [{"kind": "mirror", "deck_a": f"env/{TARGET}", "deck_b": f"env/{TARGET}",
                       "seed0": SEED0, "n": 4}]}
    p = d / "a3.json"
    p.write_text(json.dumps(sch), encoding="utf-8")
    man = record_mix.main(["--schedule", str(p), "--out", str(d / "a3"), "--workers", "2"])
    stem = man["files"][0].rsplit(".b0.", 1)[0]
    return stem, d


def _args(stem, out, **kw):
    a = dict(train=stem, valid=stem, out=out, init=None, epochs=1, bs=256, lr=1e-3, wd=0.0,
             hidden=16, depth=2, phead=8, wv=1.0, wp=1.0, lam=0.0, vtarget="max",
             calib_by="none", calib_scale="p90", select="last", distil_from=None,
             card_profile=False, seed=0, threads=2, max_records=None, keep_pairs=None)
    a.update(kw)
    return argparse.Namespace(**a)


def _meta(out):
    with open(out.replace(".json", ".meta.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def init_net(recs):
    import drl_train as T
    stem, d = recs
    out = str(d / "init.json")
    T.train(_args(stem, out, epochs=2, seed=1))
    return out


# ------------------------------------------------------------------ A3-1
def test_freeze_requires_init(recs):
    import drl_train as T
    stem, d = recs
    with pytest.raises(SystemExit):
        T.train(_args(stem, str(d / "x.json"), freeze="trunk"))


# ------------------------------------------------------------------ A3-2
@pytest.mark.parametrize("freeze", ["trunk", None])
def test_freeze_keeps_trunk_bits_and_moves_heads(recs, init_net, freeze):
    import torch
    import drl_train as T
    from meicho.drlnet import Net
    stem, d = recs
    out = str(d / f"frz_{freeze}.json")
    model = T.train(_args(stem, out, init=init_net, freeze=freeze, lr=1e-2, epochs=2))
    ref = T.TwoHead.from_net(Net.load(init_net), model.scale)
    same_trunk = all(torch.equal(a, b) for a, b in zip(model.trunk.parameters(), ref.trunk.parameters()))
    heads = [(model.value, ref.value), (model.p1, ref.p1), (model.p2, ref.p2)]
    heads_moved = all(not torch.equal(a.weight, b.weight) for a, b in heads)
    assert heads_moved
    a_net, b_net = Net.load(out), Net.load(init_net)
    shape = lambda n: ([w.shape for w, _ in n.trunk], n.value[0].shape, [w.shape for w, _ in n.policy])
    assert shape(a_net) == shape(b_net)
    m = _meta(out)
    if freeze == "trunk":
        assert same_trunk                                        # 1 ビットも変わらない
        for (wa, ba), (wb, bb) in zip(a_net.trunk, b_net.trunk):  # 書き出しは目盛りの畳み込みの丸めだけ
            assert np.allclose(wa, wb, rtol=1e-5, atol=1e-7) and np.array_equal(ba, bb)
        n_heads = sum(p.numel() for mod in (model.value, model.p1, model.p2) for p in mod.parameters())
        assert m["freeze"] == "trunk" and m["n_params_trained"] == n_heads
    else:
        assert not same_trunk                                    # 壊し方: 凍結を外すと幹が動く
        assert "freeze" not in m


# ------------------------------------------------------------------ A3-3
def test_default_output_is_unchanged(recs, init_net):
    import drl_train as T
    stem, d = recs
    outs = {}
    for tag, kw in (("absent", {}), ("none", {"freeze": None})):
        out = str(d / f"def_{tag}.json")
        a = _args(stem, out, init=init_net, **kw)
        assert hasattr(a, "freeze") == (tag == "none")
        T.train(a)
        m = _meta(out)
        for row in m["log"]:
            row.pop("sec")
        outs[tag] = (open(out, "rb").read(), m)
    assert outs["absent"][0] == outs["none"][0]
    m0, m1 = outs["absent"][1], outs["none"][1]
    m0.pop("out", None); m1.pop("out", None)
    assert m0 == m1 and "freeze" not in m0
    full = sum(w.size + b.size for w, b in __import__("meicho.drlnet", fromlist=["Net"]).Net.load(init_net).trunk)
    assert m0["n_params_trained"] > full                         # 既定は幹も数える（従来どおり）


PRE_FREEZE_COMMIT = "1d4faee"          # `--freeze` の口を足す前（D-158 の台帳の commit）


def test_default_output_matches_pre_freeze_code(recs, init_net, tmp_path):
    """壊し方: 既定の経路（Adam に渡す重み・数え方・meta の欄）を変えると、旧版とバイトが合わなくなる。"""
    import importlib.util
    import subprocess
    import drl_train as T
    stem, d = recs
    try:
        src = subprocess.run(["git", "show", f"{PRE_FREEZE_COMMIT}:engine/experiments/drl_train.py"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"git か commit {PRE_FREEZE_COMMIT} が無い")
    old_py = tmp_path / "drl_train_pre_freeze.py"
    old_py.write_bytes(src)
    spec = importlib.util.spec_from_file_location("drl_train_pre_freeze", old_py)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    outs = {}
    for tag, mod in (("old", old), ("new", T)):
        for init in (None, init_net):
            out = str(tmp_path / f"{tag}_{init is not None}.json")
            mod.train(_args(stem, out, init=init, epochs=2, select="best_v", calib_scale="bulk"))
            m = _meta(out)
            for row in m["log"]:
                row.pop("sec")
            outs[(tag, init is not None)] = (open(out, "rb").read(), m)
    for k in (False, True):
        assert outs[("old", k)][0] == outs[("new", k)][0]
        assert outs[("old", k)][1] == outs[("new", k)][1]


# ------------------------------------------------------------------ A3-4
@pytest.fixture(scope="module")
def parts(recs):
    import drl_train as T
    stem, d = recs
    for k in range(3):
        T.train(_args(stem, str(d / f"tiny_s{k}.json"), seed=k, epochs=2))
    for k in range(3):
        T.train(_args(stem, str(d / f"tiny2_s{k}.json"), seed=10 + k, epochs=1))
    return stem, d


def test_move_zero_for_same_and_meta_match(parts):
    import diag_s4_move as D
    stem, d = parts
    res = D.run(stem, {"A": "tiny", "B": "tiny", "C": "tiny2"}, [("A", "B"), ("A", "C")], models=str(d))
    assert res["moves"]["A:B"]["ens"] == 0.0 and res["moves"]["A:B"]["parts"] == [0.0, 0.0, 0.0]
    assert min(res["moves"]["A:C"]["parts"]) > 0
    for q in res["nets"]["A"]["parts"] + res["nets"]["C"]["parts"]:
        assert q["meta_v_logloss"] is not None and abs(q["v_logloss"] - q["meta_v_logloss"]) < 1e-4
    assert res["nets"]["A"]["ens"]["v_logloss"] == res["nets"]["B"]["ens"]["v_logloss"]
    assert sum(v["n"] for v in res["nets"]["A"]["ens"]["by_phase"].values()) == res["n_valid"]


def test_ens_is_mean_logit(parts):
    import diag_s4_move as D
    from meicho.drl_data import read_records
    from meicho.drlnet import Net
    stem, d = parts
    res = D.run(stem, {"A": "tiny"}, [], models=str(d))
    r = read_records(D.files_of(stem))
    obs = r.obs.astype(np.float32)
    lg = np.mean([D.net_logit(Net.load(str(d / f"tiny_s{k}.json")), obs).astype(np.float64) for k in range(3)], 0)
    assert abs(D.logloss(D.sigmoid(lg), r.z) - res["nets"]["A"]["ens"]["v_logloss"]) < 1e-12
    import ensemble_net
    ens = ensemble_net.combine([Net.load(str(d / f"tiny_s{k}.json")) for k in range(3)])
    assert np.allclose(D.net_logit(ens, obs), lg, atol=1e-4)


# ------------------------------------------------------------------ A3-5
def _val_stem():
    s = os.environ.get(VAL_STEM_ENV)
    if s:
        return s
    import glob
    hits = glob.glob("/tmp/claude-*/**/s4/rec/target_val.c000.manifest.json", recursive=True)
    return hits[0].replace(".manifest.json", "") if hits else None


def test_target_valid_has_17041_decisions():
    stem = _val_stem()
    if stem is None:
        pytest.skip(f"便の検証の記録が無い（{VAL_STEM_ENV} で接頭辞を渡せる）")
    import diag_s4_move as D
    from meicho.drl_data import read_records
    assert read_records(D.files_of(stem)).n == 17041
