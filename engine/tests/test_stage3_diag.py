"""段階3 反復 1 の診断の道具の検査（D-144 追記 3・比較書 §4・§7・Cowork 版 §12）。

K-1 `drl_train.keep_pairs`: シードの対 (2k, 2k+1) を割らない／補集合と合わせると元に戻る／決定ごとの行動と点数が元と同じ
K-2 `drl_train --keep-pairs`: 学習の記録だけを間引き、meta に間引く前後の数を残す（検証の記録は間引かない）
M-1 `diag_s3_desk.tags`: 決定のデッキは席で決まる（席 0 = deck_a）。manifest の席別の決定数と一致（ミラー・同士・錨）
M-2 `diag_s3_desk.fit_slices`: 層の決定数の合計が全体と一致
M-3 `diag_s3_desk.net_logit` は `Net.value_of` と同じ値
M-4 束ねた V を部品のロジットの平均で計算した値が `ensemble_net.combine` の値と同じ
M-5 3-a の教師は `s3v1_id_s0.meta.json` の較正をそのまま当てる（検証の記録で合わせ直さない）
M-6 2-a・3-a の規則の境目
M-7 検証の記録全体で、V_1 の部品 3 本の v_logloss が学習の記録（meta の選んだエポック）と一致
H-1 `eval_s3_h2h`: 同じシードは同じ局／足し継ぎは一度に回したのと同じ
H-2 挑戦に null と同じ V を渡すと d が全局 0
H-3 学習の帯（kind=train）では回さない
H-4 `report` は B 席の V が違う組・局数がそろっていない組を対にしない
H-5 ブロック等重みの対の差と区間

H-1・H-2 は対局 16 局（約 40 秒）を回す。`tests/test_sets.json` は作業環境か PC の全検査から `make_test_sets.py` で作り直す
（手で直さない・クラウドの結果では資材の違いで組がずれる）ので、次に作り直すまでは既定の組でも回る
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import diag_s3_desk as D                                               # noqa: E402
import drl_train as T                                                  # noqa: E402
import eval_s3_h2h as H                                                # noqa: E402
from meicho.drl_data import read_records                               # noqa: E402
from meicho.drlnet import Net                                          # noqa: E402

MODELS = os.path.join(ROOT, "results", "models")
SMALL_V = os.path.join(MODELS, "s2v_id_s0.json")
TEST_SEED0 = 859900                   # seed_bands.json の検査用（859900..859949）


@pytest.fixture(scope="module")
def val_small(tmp_path_factory):
    """検証の記録のうち、ミラー・同士・錨を含む塊 0・4・13 だけを伸ばす。"""
    chunks = {0, 4, 13}
    files = D.extract("val", str(tmp_path_factory.mktemp("rec")), chunks)
    return files, D.manifests("val", chunks)


# ------------------------------------------------------------------ K
def test_keep_pairs_partition(val_small):
    files, _ = val_small
    r = read_records(files)
    for mod in (2, 4):
        parts = [T.keep_pairs(r, mod, k) for k in range(mod)]
        assert sum(p.n for p in parts) == r.n
        assert sum(len(p.scores_flat) for p in parts) == len(r.scores_flat)
        for k, p in enumerate(parts):
            assert ((p.seed // 2) % mod == k).all()
            # 対を割らない: 残った局の相方（2k と 2k+1）も、元に決定があれば残っている
            kept = set(p.seed.tolist())
            for s in kept:
                mate = s ^ 1
                assert (mate in kept) or not (r.seed == mate).any()
    p = T.keep_pairs(r, 2, 0)
    idx = np.nonzero((r.seed // 2) % 2 == 0)[0]
    for j in (0, 1, len(idx) // 2, len(idx) - 1):
        i = idx[j]
        assert np.array_equal(p.actions_of(j), r.actions_of(i))
        assert np.array_equal(p.scores_of(j), r.scores_of(i), equal_nan=True)
        assert np.array_equal(p.obs[j], r.obs[i]) and p.chosen[j] == r.chosen[i]


def test_parse_keep_pairs():
    assert T.parse_keep_pairs(None) is None
    assert T.parse_keep_pairs("4:1") == (4, 1)
    for bad in ("1:0", "2:2", "2", "a:b", "3:-1"):
        with pytest.raises(SystemExit):
            T.parse_keep_pairs(bad)


def test_train_keep_pairs_meta(val_small, tmp_path):
    files, _ = val_small
    prefix = os.path.join(os.path.dirname(files[0]), "val.c000")
    out = str(tmp_path / "v.json")
    args = argparse.Namespace(train=prefix, valid=prefix, out=out, init=None, epochs=1, bs=512, lr=1e-3, wd=0.0,
                              hidden=16, depth=1, phead=8, wv=1.0, wp=1.0, lam=0.0, vtarget="max", calib_by="none",
                              calib_scale="p90", select="last", distil_from=None, card_profile=False, seed=0,
                              threads=2, max_records=None, keep_pairs="2:0")
    T.train(args)
    meta = json.load(open(out.replace(".json", ".meta.json"), encoding="utf-8"))
    r = read_records(T.files_of(prefix))
    keep = T.keep_pairs(r, 2, 0)
    assert meta["keep_pairs"] == "2:0" and meta["n_train_read"] == r.n
    assert meta["n_train"] == int((~np.isnan(keep.z)).sum())
    assert meta["n_valid"] == int((~np.isnan(r.z)).sum())            # 検証は間引かない


# ------------------------------------------------------------------ M
def test_tags_seat_deck_matches_manifest(val_small):
    files, mans = val_small
    r = read_records(files)
    tg = D.tags(r, D.block_table(mans))
    kinds = set()
    for m in mans:
        for b in m["blocks"]:
            sel = (r.seed >= b["seed0"]) & (r.seed < b["seed0"] + b["n"])
            dec = b["decisions"]
            assert int((sel & (r.pi == 0)).sum()) == dec["a_as_deck_a"] + dec["b_as_deck_a"]
            assert int((sel & (r.pi == 1)).sum()) == dec["a_as_deck_b"] + dec["b_as_deck_b"]
            assert (tg["own"][sel & (r.pi == 0)] == b["deck_a"]).all()
            assert (tg["opp"][sel & (r.pi == 0)] == b["deck_b"]).all()
            kinds |= set(tg["kind"][sel].tolist())
    assert kinds == {"mirror", "cross", "anchor"}


def test_fit_slices_counts(val_small):
    files, mans = val_small
    r = read_records(files)
    ok = ~np.isnan(r.z)
    tg = {k: v[ok] for k, v in D.tags(r, D.block_table(mans)).items()}
    z = r.z[ok].astype(float)
    s = D.fit_slices(z, {"c": np.full(len(z), 0.5)}, tg)
    for key in ("phase", "tband", "own", "sk", "kind"):
        assert sum(v["n"] for k, v in s.items() if k.startswith(key + "=")) == s["all"]["n"] == len(z)
    assert abs(s["all"]["c"] - np.log(2)) < 1e-9


def test_net_logit_matches_value_of(val_small):
    files, _ = val_small
    r = read_records(files)
    net = Net.load(SMALL_V)
    x = r.obs[:20]
    got = D.sigmoid(D.net_logit(net, x))
    ref = np.array([net.value_of(o.astype(np.float32)) for o in x])
    assert np.abs(got - ref).max() < 1e-5


def test_ensemble_mean_logit_matches_combine(val_small):
    from ensemble_net import combine
    files, _ = val_small
    x = read_records(files).obs[:30]
    parts = D.load_parts("s2v_id")
    ens = combine(parts)
    got = D.sigmoid(np.mean([D.net_logit(n, x) for n in parts], 0))
    ref = D.sigmoid(D.net_logit(ens, x))
    assert np.abs(got - ref).max() < 1e-5


def test_teacher_uses_meta_calibration(val_small):
    files, _ = val_small
    r = read_records(files)
    calib = json.load(open(os.path.join(MODELS, "s3v1_id_s0.meta.json"), encoding="utf-8"))["calibration"]
    p = D.teacher_p(r, calib)
    for i in (0, 7, r.n // 2):
        sc = r.scores_of(i)
        fin = np.isfinite(sc)
        if not fin.any():
            assert np.isnan(p[i])
            continue
        u = np.clip(sc[fin].max(), -calib["c"], calib["c"]) / calib["c"]
        assert abs(p[i] - 1 / (1 + np.exp(-(calib["a"] * u + calib["b"])))) < 1e-6


def test_rules_thresholds():
    sl = {"all": {"share": 1.0, "base": 0.69, "V0": 0.6, "V1": 0.6},
          "a=x": {"share": 0.10, "base": 0.69, "V0": 0.681, "V1": 0.6801},     # 両方 < 0.01・占有 10% → 当たる
          "a=y": {"share": 0.099, "base": 0.69, "V0": 0.69, "V1": 0.69},       # 占有が足りない
          "a=w": {"share": 0.5, "base": 0.69, "V0": 0.685, "V1": 0.679}}       # V1 は 0.011 改善 → 当たらない
    assert D.rule_2a(sl)["slices"] == ["a=x"]
    z = np.array([1.0, 0.0] * 50)
    tg = {"phase": np.array(["action"] * 100), "tband": np.array(["t4-6"] * 100)}
    p = np.full(100, 0.5)
    assert D.teacher_uplift(z, p, p, tg)["u"] == 0.0
    assert "足していない" in D.teacher_uplift(z, p, p, tg)["verdict"]


def test_full_val_matches_training_log(tmp_path_factory):
    """M-7: 検証の記録全体で、V_1 の部品の v_logloss が学習の記録と一致（配線の確認）。"""
    files = D.extract("val", str(tmp_path_factory.mktemp("full")))
    r = read_records(files)
    ok = ~np.isnan(r.z)
    for k in range(3):
        meta = json.load(open(os.path.join(MODELS, f"s3v1_id_s{k}.meta.json"), encoding="utf-8"))
        ref = meta["log"][meta["selected_epoch"] - 1]["valid"]["v_logloss"]
        net = Net.load(os.path.join(MODELS, f"s3v1_id_s{k}.json"))
        got = D.logloss(D.sigmoid(D.net_logit(net, r.obs[ok])), r.z[ok])
        assert abs(got - ref) < 2e-4, (k, got, ref)


# ------------------------------------------------------------------ H
def _h2h_args(out, n, pairs, seed0=TEST_SEED0):
    return SimpleNamespace(pair=pairs, n=n, seed0=seed0, out=str(out), workers=2, budget_sec=1e9,
                           env=H.DEFAULT_ENV)


@pytest.fixture(scope="module")
def h2h_runs(tmp_path_factory):
    d = tmp_path_factory.mktemp("h2h")
    decks = H.tune_decks()[:1]                        # ミラー 1 ブロックだけ
    pairs = [f"x={SMALL_V}:{SMALL_V}", f"y={SMALL_V}:{SMALL_V}"]
    one = H.run(_h2h_args(d / "one.json", 4, pairs), decks)
    H.run(_h2h_args(d / "ext.json", 2, pairs[:1]), decks)
    ext = H.run(_h2h_args(d / "ext.json", 4, pairs[:1]), decks)
    again = H.run(_h2h_args(d / "again.json", 4, pairs[:1]), decks)
    return one, ext, again


def test_h2h_deterministic_and_extension(h2h_runs):
    one, ext, again = h2h_runs
    key = [k for k in one["results"] if k.startswith("x|")][0]
    assert len(one["results"][key]) == 4
    assert one["results"][key] == ext["results"][key] == again["results"][key]


def test_h2h_identical_pairs_zero_diff(h2h_runs):
    one, _, _ = h2h_runs
    rep = H.report(one, "x", "y", n_boot=200)
    assert rep["main"]["diff"] == 0.0 and rep["main"]["lo"] == 0.0 and rep["main"]["hi"] == 0.0
    assert all(v["challenge_only"] == v["null_only"] == 0 for v in rep["by_deck"].values())


def test_h2h_rejects_train_band(tmp_path):
    with pytest.raises(SystemExit, match="kind=train"):
        H.run(_h2h_args(tmp_path / "t.json", 2, [f"x={SMALL_V}:{SMALL_V}"], seed0=845000), H.tune_decks()[:1])


def test_h2h_report_rejects_unpaired():
    decks = H.tune_decks()[:1]
    key = f"|{decks[0]}|{decks[0]}"
    base = {"decks": decks, "n": 2, "seed0": TEST_SEED0,
            "pairs": {"c": {"a": {"sha": "1"}, "b": {"sha": "0"}}, "n": {"a": {"sha": "0"}, "b": {"sha": "0"}}},
            "results": {"c" + key: [[1.0, 5], [0.0, 5]], "n" + key: [[0.0, 5], [0.0, 5]]}}
    assert H.report(base, "c", "n", n_boot=100)["main"]["diff"] == 0.5
    bad = json.loads(json.dumps(base))
    bad["pairs"]["n"]["b"]["sha"] = "9"
    with pytest.raises(SystemExit, match="B 席"):
        H.report(bad, "c", "n")
    short = json.loads(json.dumps(base))
    short["results"]["n" + key] = [[0.0, 5]]
    with pytest.raises(SystemExit, match="足し継ぎ"):
        H.report(short, "c", "n")


def test_paired_blocks_equal_weight():
    r = H.paired_blocks([[1.0] * 10, [0.0] * 90], n_boot=200)
    assert r["diff"] == 0.5 and r["lo"] == r["hi"] == 0.5          # 局数でなくブロックで等重み
    assert H.verdict(0.011).startswith("伸びていた") and H.verdict(-0.011).startswith("伸びていない")
    assert H.verdict(0.0).startswith("境界") and H.verdict(0.01).startswith("境界")
