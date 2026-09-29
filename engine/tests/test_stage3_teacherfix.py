"""段階3 項目 3（教師の較正）の直し方の道具の検査（D-148・設計書 `GENERALIST_STAGE3_TEACHER_FIX_DESIGN_20260930.md` §7）。

F-1 `--calib-form` の既定（linear）は従来とバイト単位で同じ（S5 の較正 a・b・c と meta が一致・`form` 欄を足さない）
F-2 `logit` は勝率として較正済みの合成データで a ≈ 1・b ≈ 0 を返す
F-3 `logit` は |v| > 1 の探索値が 1 件でもあれば止める
F-4 `apply_calibration` は形を読む（形を取り違えると値が大きく変わる）
F-5 `is_argmax`: 有限の点数の最大と選んだ手の一致・同点は最初の手（Rust `argmax_by` と同じ）
F-6 `--vtarget fresh_am`: argmax の決定は fresh（有限なら）・それ以外は max・fresh が NaN なら max
F-7 `record_mix.py` の `reeval_samples`: 同じシードで 0 と 4 を取ると fresh 以外が全件一致し、fresh が NaN → 有限になる。
    manifest の教師の定義に `reeval_samples` が入る
F-8 `make_s2_schedule.py --reeval-samples`: 既定は欄を足さない（従来とバイト単位で同じ）・4 で欄が入る
F-9 `eval_s2_repr.py report --level`: 既定は既存の報告とバイト単位で同じ・0.983 で区間が広がる
F-10 `diag_s3_desk`: 単調回帰（PAV）が単調で重みつき平均を保つ／T-0 が端から端まで回り規則の欄を出す／
     取り直しの照合が一致を認め、1 か所の違いを見つける
"""
from __future__ import annotations

import hashlib
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
from meicho.drl_data import read_records                               # noqa: E402

MODELS = os.path.join(ROOT, "results", "models")
NET_REL = "results/models/s2v_id_s0.json"
REC_SEED0 = 860000                    # seed_bands.json の検査用（kind=diag・860000..860099）


def _T():
    pytest.importorskip("torch")
    import drl_train
    return drl_train


@pytest.fixture(scope="module")
def val_small(tmp_path_factory):
    chunks = {0, 13}
    return D.extract("val", str(tmp_path_factory.mktemp("rec")), chunks), D.manifests("val", chunks)


# ------------------------------------------------------------------ F-1〜F-4
@pytest.fixture(scope="module")
def it1_train(tmp_path_factory):
    return D.extract("train", str(tmp_path_factory.mktemp("train")))


def test_calib_default_matches_s5_meta(it1_train):
    """F-1: 既定の形で反復 1 の学習の記録に合わせると、S5 の meta の較正と同じ値になり、`form` 欄は足さない。"""
    T = _T()
    b = T.Batcher(read_records(it1_train), vtarget="max")
    got = T.calibrate_vsearch(b.vsearch, b.z, scale="bulk")
    ref = json.load(open(os.path.join(MODELS, "s3v1_id_s0.meta.json"), encoding="utf-8"))["calibration"]
    assert "form" not in got
    assert json.dumps(got, sort_keys=True) == json.dumps(ref, sort_keys=True)


def test_calib_logit_identity_on_calibrated_data():
    """F-2: 勝率として較正済みの値なら、ロジット型は恒等に近い（a ≈ 1・b ≈ 0）。"""
    T = _T()
    rng = np.random.RandomState(0)
    v = rng.uniform(0.05, 0.95, 200000)
    z = (rng.uniform(size=len(v)) < v).astype(float)
    c = T.calibrate_vsearch(v, z, scale="bulk", form="logit")
    assert c["form"] == "logit"
    assert abs(c["a"] - 1) < 0.05 and abs(c["b"]) < 0.05
    lin = T.calibrate_vsearch(v, z, scale="bulk")
    assert c["logloss"] < lin["logloss"]                  # 端を曲げられるぶん当てはまりが良い


def test_calib_logit_refuses_unbounded():
    """F-3: 手作り評価の探索値（|v| > 1）には使えない。"""
    T = _T()
    v = np.concatenate([np.linspace(0, 1, 2000), [3.5]])
    with pytest.raises(SystemExit, match="logit"):
        T.calibrate_vsearch(v, (v > 0.5).astype(float), form="logit")


def test_apply_calibration_reads_form():
    """F-4: 当てる関数が形を読む。logit の較正を linear として当てると値が大きく変わる。"""
    T = _T()
    calib = {"a": 1.0, "b": 0.0, "c": 0.9, "form": "logit"}
    v = np.array([0.02, 0.3, 0.7, 0.98])
    assert np.allclose(T.apply_calibration(v, calib), v, atol=1e-9)             # 恒等
    wrong = T.apply_calibration(v, {k: x for k, x in calib.items() if k != "form"})
    assert np.abs(wrong - v).max() > 0.1
    assert np.allclose(D.apply_calib(v, calib), T.apply_calibration(v, calib))   # 机上の道具も同じ式


# ------------------------------------------------------------------ F-5・F-6
def test_is_argmax_tie_first():
    T = _T()
    sc = np.array([1.0, 3.0, 3.0, np.nan], np.float32)
    assert T.is_argmax(sc, 1) and not T.is_argmax(sc, 2) and not T.is_argmax(sc, 0)
    assert not T.is_argmax(sc, 3)                                             # NaN の手は argmax ではない
    assert not T.is_argmax(np.array([np.nan, np.nan], np.float32), 0)


def test_vtarget_fresh_am(val_small):
    """F-6: argmax の決定は fresh・それ以外は max。fresh が NaN なら max（反復 1 の記録は fresh が全部 NaN）。"""
    T = _T()
    files, _ = val_small
    r = read_records(files)
    bm = T.Batcher(r, vtarget="max")
    b0 = T.Batcher(r, vtarget="fresh_am")
    assert np.array_equal(bm.vsearch, b0.vsearch, equal_nan=True) and b0.n_fresh_used == 0
    r.fresh[:] = 0.123                                                        # すべての決定に取り直しの値
    bf = T.Batcher(r, vtarget="fresh_am")
    keep = np.nonzero(~np.isnan(r.z))[0]
    am = np.array([T.is_argmax(r.scores_of(i), int(r.chosen[i])) for i in keep])
    searched = np.array([len(r.scores_of(i)) > 0 for i in keep])
    assert bf.n_nonargmax == int((~am & searched).sum()) > 0
    assert np.allclose(bf.vsearch[am], 0.123)
    assert np.array_equal(bf.vsearch[~am], bm.vsearch[~am], equal_nan=True)
    assert bf.n_fresh_used == int(am.sum())


# ------------------------------------------------------------------ F-7・F-8
def _sha16(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


@pytest.fixture(scope="module")
def reeval_pair(tmp_path_factory):
    pytest.importorskip("meicho_rs")
    import record_mix
    d = tmp_path_factory.mktemp("reeval")
    out = {}
    for k in (0, 4):
        teacher = {"name": "netfree_v", "tau": 0.006, "value_net": NET_REL,
                   "value_net_sha16": _sha16(os.path.join(ROOT, NET_REL))}
        if k:
            teacher["reeval_samples"] = k
        sch = {"name": f"t{k}", "teacher": teacher,
               "blocks": [{"deck_a": "SD001", "deck_b": "SD001", "seed0": REC_SEED0, "n": 2}]}
        p = d / f"s{k}.json"
        p.write_text(json.dumps(sch), encoding="utf-8")
        man = record_mix.main(["--schedule", str(p), "--out", str(d / f"r{k}"), "--workers", "2"])
        out[k] = (man, read_records(man["files"]))
    return out


@pytest.mark.slow
def test_reeval_keeps_play(reeval_pair):
    """F-7: 取り直しは打ち方を変えない（fresh 以外が全件一致）・fresh が NaN → 有限。"""
    (m0, r0), (m4, r4) = reeval_pair[0], reeval_pair[4]
    cmp = D.compare_retake(r0, r4)
    assert cmp["same"], cmp
    assert cmp["fresh_finite"]["orig"] == 0 and cmp["fresh_finite"]["retake"] > 0
    assert m4["schedule"]["teacher"]["reeval_samples"] == 4 and "reeval_samples" not in m0["schedule"]["teacher"]
    assert m4["blocks"][0]["spec_a"]["reeval_samples"] == 4


@pytest.mark.slow
def test_compare_retake_finds_a_difference(reeval_pair):
    """F-10: 照合は 1 か所の違い（選んだ手）を見つける。"""
    (_, r0), (_, r4) = reeval_pair[0], reeval_pair[4]
    r4.chosen[3] = (r4.chosen[3] + 1) % max(2, int(r4.n_acts[3]))
    cmp = D.compare_retake(r0, r4)
    assert not cmp["same"] and cmp["mismatch"]["chosen"] == 1


def test_schedule_reeval_flag(tmp_path):
    """F-8: 既定は欄を足さない・4 で欄が入る。"""
    import make_s2_schedule as M
    assert "reeval_samples" not in M.teacher_def("netfree_v", NET_REL, 0.006)
    t = M.teacher_def("netfree_v", NET_REL, 0.006, 4)
    assert t["reeval_samples"] == 4
    assert {k: v for k, v in t.items() if k != "reeval_samples"} == M.teacher_def("netfree_v", NET_REL, 0.006)


# ------------------------------------------------------------------ F-9
def test_report_level(tmp_path):
    import eval_s2_repr as R
    src = os.path.join(ROOT, "results", "drl", "s3_it1_select.json")
    ref = os.path.join(ROOT, "results", "drl", "s3_it1_select_report.json")
    a = R.main(["report", "--in", src, "--new", "v1", "--old", "v_ens3", "--out", str(tmp_path / "a.json")])
    assert (tmp_path / "a.json").read_bytes() == open(ref, "rb").read()
    b = R.main(["report", "--in", src, "--new", "v1", "--old", "v_ens3", "--out", str(tmp_path / "b.json"),
                "--level", "0.983"])
    ca, cb = a["compare"]["v1-v_ens3"], b["compare"]["v1-v_ens3"]
    assert cb["lo"] < ca["lo"] and cb["hi"] > ca["hi"] and cb["diff"] == ca["diff"]
    assert b["level"] == 0.983 and "level" not in a
    assert R.ci_percentiles(0.95) == [2.5, 97.5]


# ------------------------------------------------------------------ F-10
def test_iso_is_monotone_pav():
    v = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.5])
    z = np.array([0.0, 1.0, 0.0, 1.0, 1.0, 1.0])
    iso = D.fit_iso(v, z)
    assert np.all(np.diff(iso["p"]) >= 0)
    assert np.allclose(iso["p"], [0.0001, 0.5, 0.5, 0.9999, 0.9999][:len(iso["p"])])
    assert np.allclose(D.apply_iso(np.array([0.0, 0.25, 0.9]), iso), [0.0001, 0.5, 0.9999])


def test_t0_runs_and_reports_rules(val_small):
    """F-10: T-0 が端から端まで回り、3 つの形と錨を除いた集合と規則の欄を出す（配線の確認・小さい集合）。"""
    _T()
    files, mans = val_small
    out = D.t0(files, mans, files, mans, None)
    assert set(out["forms"]) == {"linear", "logit", "iso"}
    assert out["forms"]["logit"]["calib"]["form"] == "logit"
    assert "e_na" in out["no_anchor"] and out["no_anchor"]["n_val"] < out["n_val"]     # 塊 13 は錨を含む
    assert out["check"]["ok"] and out["rules"]["verdict"]
    # 合わせる集合と当てる集合が同じなら、単調回帰はどの単調な形より当てはまりが良い（上限の配線の確認）
    assert out["forms"]["iso"]["u"] >= out["forms"]["logit"]["u"] - 1e-4
    assert out["forms"]["iso"]["u"] >= out["forms"]["linear"]["u"] - 1e-4
