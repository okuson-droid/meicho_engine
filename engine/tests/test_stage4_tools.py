"""段階4 便 4-A の道具の検査（D-154・設計書 `GENERALIST_STAGE4_DESIGN_20261001.md` §8）。

S4-1 `--target` の表に、調整デッキの残り 3 つと最終評価の 4 つが自分側にも相手側にも出ない。異種は D の席だけ記録
S4-2 `record: deck_a` の記録を読み戻すと、異種ブロックの決定はすべて D の席（席 0）。壊し方: `a` に戻すと
     奇数シードの局で席 1（相手デッキ）の決定が混ざる
S4-3 §4.3 の部分集合が 314 局（ミラー 120・異種 16 × 8・錨 3 × 22）で、席を入れ替えた組を割らない。
     塊に割った表（`parent`）でも同じ局になる。`drl_train --subset-frac` の meta に局数が入る
S4-4 既定の出力は従来どおり: `make_s2_schedule.py` は D-131 の表とバイト単位で同じ・`drl_train` の meta に
     新しい欄が入らない・`eval_s2_repr.py report`（課題 s2）の結果は従来の報告と同じ
S4-5 `--task s4` で全候補が同じシード列を使い、席が半々になる。違うシードで回った候補を同じ結果ファイルで
     比べようとすると落ちる。組を単位の対の差・局数の違う候補は共通の先頭の組だけで対にする
S4-6 `--pool-only SD001` の配分がミラー 80%・錨 20%（10,096 局）で、SD001 以外のデッキが出ない

検査の対局は 879900..879949（kind=diag・D-154 で登録）で回す。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import eval_s2_repr as E                                               # noqa: E402
import make_s2_schedule as M                                           # noqa: E402
from meicho.drl_data import read_records                               # noqa: E402

TARGET = "ENV_SANGE_RM_TSUBAKI"
PER_1000 = {"mirror": 400, "cross": 24, "anchor": 72}
SEED0 = 879900                        # 検査の帯（879900..879949・kind=diag・D-154）


@pytest.fixture(scope="module")
def env():
    with open(M.DEFAULT_ENV, encoding="utf-8") as f:
        return json.load(f)["decks_block"]


def _target(env, per=PER_1000, seed0=861000, band_end=862999):
    return M.build_target(env, target=TARGET, per=per, seed0=seed0, band_end=band_end, name="t",
                          purpose="stage4_finetune")


# ------------------------------------------------------------------ S4-1
def test_target_schedule_uses_only_target_and_train(env):
    sch = _target(env)
    train = {f"env/{k}" for k, v in env.items() if v["split"] == "train"}
    for b in sch["blocks"]:
        assert b["deck_a"] == f"env/{TARGET}"
        assert b["deck_b"] == f"env/{TARGET}" or b["deck_b"] in train
    forbidden = {f"env/{k}" for k, v in env.items() if v["split"] in ("tune", "final")} - {f"env/{TARGET}"}
    assert not forbidden & {d for b in sch["blocks"] for d in (b["deck_a"], b["deck_b"])}
    kinds = {}
    for b in sch["blocks"]:
        kinds.setdefault(b["kind"], []).append(b)
    assert [len(kinds[k]) for k in ("mirror", "cross", "anchor")] == [1, 16, 3]
    assert all(b["record"] == "deck_a" for b in kinds["cross"])
    assert kinds["mirror"][0]["record"] == "both"
    assert sorted(b["opponent"] for b in kinds["anchor"]) == ["greedy", "heuristic", "planner"]
    assert sch["n_total_actual"] == 1000 and sch["purpose"] == "stage4_finetune"
    val = _target(env, {"mirror": 80, "cross": 4, "anchor": 20}, 863000, 863999)
    assert val["n_total_actual"] == 204


@pytest.mark.parametrize("bad", ["ENV_SANGE_SK_ANKO", "ENV_SANGE_RF_ANKO", "NOPE"])
def test_target_refuses_final_train_or_unknown(env, bad):
    with pytest.raises(SystemExit):
        M.build_target(env, target=bad, per=PER_1000, seed0=861000, band_end=862999, name="t")


def test_per_block_must_be_even_and_complete():
    assert M.parse_per_block("mirror:400,cross:24,anchor:72", ("mirror", "cross", "anchor")) == PER_1000
    for bad in ("mirror:400,cross:23,anchor:72", "mirror:400,anchor:72", "mirror:0,cross:2,anchor:2"):
        with pytest.raises(SystemExit):
            M.parse_per_block(bad, ("mirror", "cross", "anchor"))


# ------------------------------------------------------------------ S4-2
@pytest.fixture(scope="module")
def deck_a_records(tmp_path_factory):
    rs = pytest.importorskip("meicho_rs")
    if "record_seats" not in rs.features():
        pytest.skip("入っている meicho_rs に record_seats が無い（再ビルドが要る）")
    import record_mix
    d = tmp_path_factory.mktemp("s4rec")
    out = {}
    for rec in ("deck_a", "a"):
        sch = {"name": rec, "teacher": {"name": "netfree", "tau": 0.0},
               "blocks": [{"kind": "cross", "deck_a": f"env/{TARGET}", "deck_b": "env/ENV_SANGE_RF_ANKO",
                           "seed0": SEED0, "n": 4, "record": rec}]}
        p = d / f"{rec}.json"
        p.write_text(json.dumps(sch), encoding="utf-8")
        man = record_mix.main(["--schedule", str(p), "--out", str(d / rec), "--workers", "2"])
        out[rec] = (man, read_records(man["files"]))
    return out


@pytest.mark.slow
def test_deck_a_records_only_seat0(deck_a_records):
    man, r = deck_a_records["deck_a"]
    assert r.n > 0 and (r.pi == 0).all()
    assert set(np.unique(r.seed).tolist()) == set(range(SEED0, SEED0 + 4))    # 偶奇どちらのシードも入る
    dec = man["blocks"][0]["decisions"]
    assert r.n == dec["a_as_deck_a"] + dec["b_as_deck_a"] and dec["a_as_deck_b"] == dec["b_as_deck_b"] == 0


@pytest.mark.slow
def test_agent_a_record_mixes_seats(deck_a_records):
    """壊し方: エージェント A の席（a）では、奇数シードの局で相手デッキの席（席 1）の決定が混ざる。"""
    _, r = deck_a_records["a"]
    assert (r.pi[r.seed % 2 == 1] == 1).all() and (r.pi[r.seed % 2 == 0] == 0).all()


@pytest.mark.slow
def test_deck_a_play_is_unchanged(deck_a_records):
    """記録する側を変えても対局は同じ（勝敗・digest）。"""
    ra = deck_a_records["deck_a"][0]["blocks"][0]
    rb = deck_a_records["a"][0]["blocks"][0]
    assert (ra["a_won"], ra["decided"], ra["mean_turns"]) == (rb["a_won"], rb["decided"], rb["mean_turns"])


def test_record_mix_refuses_deck_a_on_anchor():
    import record_mix
    sch = {"blocks": [{"deck_a": "SD001", "deck_b": "SD001", "seed0": SEED0, "n": 2, "opponent": "heuristic",
                       "record": "deck_a"}]}
    with pytest.raises(SystemExit):
        record_mix.check_schedule(sch)


# ------------------------------------------------------------------ S4-3
def _manifest(tmp_path, name, blocks):
    p = tmp_path / f"{name}.manifest.json"
    p.write_text(json.dumps({"schedule": {"blocks": blocks}}), encoding="utf-8")
    return str(tmp_path / name)


def test_subset_300_is_314_games_and_keeps_pairs(env, tmp_path):
    T = pytest.importorskip("drl_train")
    sch = _target(env)
    pre = _manifest(tmp_path, "full", sch["blocks"])
    keep = T.subset_seeds(pre, 0.3)
    assert len(keep) == 314
    by = {}
    for b in sch["blocks"]:
        got = [s for s in range(b["seed0"], b["seed0"] + b["n"]) if s in keep]
        by.setdefault(b["kind"], []).append(len(got))
        assert got == list(range(b["seed0"], b["seed0"] + len(got)))           # 先頭から・組を割らない
    assert by == {"mirror": [120], "cross": [8] * 16, "anchor": [22] * 3}
    assert all((s ^ 1) in keep for s in keep)
    # 塊に割った表（parent）でも同じ局
    import plan_chunks
    ch = plan_chunks.plan(sch, 60.0)
    pres = []
    for k in range(len(ch["chunks"])):
        sub = [dict(b) for b in ch["chunks"][k]]
        pres.append(_manifest(tmp_path, f"c{k}", sub))
    assert T.subset_seeds(",".join(pres), 0.3) == keep


def test_subset_counts_pairs_not_games(tmp_path):
    """壊し方: 局で数えると ミラー 400 局の 30% は 120 局で同じだが、24 局の異種では 7 局（組を割る）になる。"""
    T = pytest.importorskip("drl_train")
    pre = _manifest(tmp_path, "x", [{"seed0": 100, "n": 24}])
    keep = T.subset_seeds(pre, 0.3)
    assert len(keep) == 8 and round(0.3 * 24) == 7


@pytest.mark.slow
def test_train_subset_meta_and_default_has_no_new_keys(deck_a_records, tmp_path):
    T = pytest.importorskip("drl_train")
    man, r = deck_a_records["deck_a"]
    stem = man["files"][0].rsplit(".b0.", 1)[0]
    metas = {}
    for frac in (None, 0.5):
        out = str(tmp_path / f"v{frac}.json")
        args = argparse.Namespace(train=stem, valid=stem, out=out, init=None, epochs=1, bs=512, lr=1e-3, wd=0.0,
                                  hidden=16, depth=1, phead=8, wv=1.0, wp=1.0, lam=0.0, vtarget="max",
                                  calib_by="none", calib_scale="p90", select="last", distil_from=None,
                                  card_profile=False, seed=0, threads=2, max_records=None, keep_pairs=None,
                                  subset_frac=frac)
        T.train(args)
        metas[frac] = json.load(open(out.replace(".json", ".meta.json"), encoding="utf-8"))
    assert "subset_frac" not in metas[None] and "n_subset_games" not in metas[None]
    assert metas[0.5]["subset_frac"] == 0.5 and metas[0.5]["n_subset_games"] == 2
    keep = T.keep_seed_set(r, {SEED0, SEED0 + 1})
    assert metas[0.5]["n_train"] == int((~np.isnan(keep.z)).sum())
    assert metas[0.5]["n_valid"] == metas[None]["n_valid"]                     # 検証は絞らない


# ------------------------------------------------------------------ S4-4
def test_default_schedule_is_d131_bytes(env):
    path = os.path.join(ROOT, "results", "drl", "s2_v1_train_schedule.json")
    with open(path, encoding="utf-8") as f:
        old = json.load(f)
    g = old["generator"]
    sch = M.build(env, n_total=g["n_total_requested"], seed0=g["band"][0], band_end=g["band"][1],
                  only=g["only"], pilot_n=g["pilot_n"], name=old["name"])
    sch["generator"]["env"] = old["generator"]["env"]
    assert M.dumps(sch) == open(path, encoding="utf-8").read()


def test_s2_report_is_unchanged(tmp_path):
    src = os.path.join(ROOT, "results", "drl", "s3_it1_select.json")
    ref = os.path.join(ROOT, "results", "drl", "s3_it1_select_report.json")
    if not os.path.exists(ref):
        pytest.skip("従来の報告が無い")
    ref_d = json.load(open(ref, encoding="utf-8"))
    comp = list(ref_d["compare"])
    new, old = comp[0].split("-", 1)
    also = [c.replace("-", ":", 1) for c in comp[1:]]
    out = tmp_path / "r.json"
    E.report(argparse.Namespace(inp=src, new=new, old=old, also=also or None, out=str(out), level=0.95))
    assert out.read_text(encoding="utf-8") == open(ref, encoding="utf-8").read()


# ------------------------------------------------------------------ S4-5
def _fake_s4(n_by_arm: dict, seed0=878000):
    rng = np.random.RandomState(0)
    data = {"task": "s4", "target": f"env/{TARGET}", "opponents": list(E.S4_OPPONENTS), "seed0": seed0,
            "arms": {a: {"n": n} for a, n in n_by_arm.items()}, "results": {}}
    for a, n in n_by_arm.items():
        for o in E.S4_OPPONENTS:
            data["results"][f"{a}|{o}"] = [[float(rng.randint(0, 2)), 10] for _ in range(n)]
    return data


def test_s4_pairs_bootstrap_and_common_prefix():
    data = _fake_s4({"G": 400, "G0": 200})
    r = E.s4_paired(data, "G", "G0", n_boot=500)
    assert r["n_per_block"] == 200                                    # 共通の先頭 200 局だけ
    want = np.mean([np.mean([x[0] for x in data["results"][f"G|{o}"][:200]])
                    - np.mean([x[0] for x in data["results"][f"G0|{o}"][:200]]) for o in E.S4_OPPONENTS])
    assert r["diff"] == pytest.approx(want)
    assert r["lo"] <= r["diff"] <= r["hi"]
    same = E.s4_paired(data, "G", "G", n_boot=200)
    assert same["diff"] == same["lo"] == same["hi"] == 0


@pytest.mark.slow
def test_s4_run_same_seeds_and_refuses_other_seed(tmp_path):
    rs = pytest.importorskip("meicho_rs")
    del rs
    out = str(tmp_path / "e.json")
    base = ["run", "--task", "s4", "--target", "SD001", "--opponents", "heuristic", "--band-kind", "diag",
            "--workers", "2", "--out", out]
    E.main(base + ["--arm", "a", "--arm", "b", "--n", "4", "--seed0", str(SEED0 + 20)])
    data = json.load(open(out, encoding="utf-8"))
    assert data["results"]["a|heuristic"] == data["results"]["b|heuristic"]   # netfree どうし＝同じ局
    assert len(data["results"]["a|heuristic"]) == 4
    with pytest.raises(SystemExit):
        E.main(base + ["--arm", "c", "--n", "4", "--seed0", str(SEED0 + 30)])
    with pytest.raises(SystemExit):
        E.main(base[:-2] + ["--out", str(tmp_path / "f.json"), "--arm", "a", "--n", "3", "--seed0", str(SEED0 + 20)])


def test_s4_band_kind_is_checked():
    with pytest.raises(SystemExit):
        E.check_band_kind(878000, 400, "diag")                  # validate の帯を diag として使わない
    with pytest.raises(SystemExit):
        E.check_band_kind(861000, 400, "validate")              # 学習の帯では評価しない
    E.check_band_kind(878000, 400, "validate")
    E.check_band_kind(879000, 400, "diag")


# ------------------------------------------------------------------ S4-6
def test_pool_only_sd001():
    sch = M.build_pool_only("SD001", per={"mirror": 8080, "anchor": 672}, seed0=864000, band_end=875999, name="s")
    assert sch["n_total_actual"] == 10096
    assert {d for b in sch["blocks"] for d in (b["deck_a"], b["deck_b"])} == {"SD001"}
    mirror = sum(b["n"] for b in sch["blocks"] if b["kind"] == "mirror")
    assert mirror / sch["n_total_actual"] == pytest.approx(0.80, abs=0.001)
    assert sorted(b["opponent"] for b in sch["blocks"] if b["kind"] == "anchor") == ["greedy", "heuristic", "planner"]
    val = M.build_pool_only("SD001", per={"mirror": 872, "anchor": 72}, seed0=876000, band_end=877999, name="v")
    assert val["n_total_actual"] == 1088
    with pytest.raises(SystemExit):
        M.build_pool_only("NOPE", per={"mirror": 2, "anchor": 2}, seed0=864000, band_end=875999, name="x")
    # 表を deepcopy して record_mix の形の検査に通す
    import record_mix
    record_mix.check_schedule(copy.deepcopy(sch))
