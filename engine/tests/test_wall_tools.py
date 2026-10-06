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

評価の口（§5.1・§5.2）:
WE-1 `eval_s3_h2h report` の既定（`--rule s3`）は、口を足す前の報告（`results/drl/s3_diag_h2h_report.json`）と同じ
WE-2 `--rule wall` の判定（下端 > 0 伸びた・上端 < 0 悪くなった・点推定 > 0 で 0 をまたげば境界・それ以外は伸びていない）と、
     98.3% の区間が 95% より広いこと。`--rule s3` に `--level` を渡すと止める
WE-3 `eval_s2_repr run --opponent heuristic|greedy`（課題 s2 の錨）: 相手が記録に残り、別の相手で足し継ぐと止める。
     既定（planner）は口を足す前（commit `fcb46e3`）と同じ結果。`--task s4` に `--opponent` を渡すと止める

腕 A（§2.1・§2.2 A-0）の Rust の口 `policy_belief`:
WA-1 `series` 系と同じ道で席に着けたとき、π に渡すデッキ表は「q = 自分なら相手の席の行動デッキ、q ≠ 自分なら自分の席の
     行動デッキ」（両席・偶奇のシード）。記録の観測（その席の `opp_decklist`＝相手の席の行動デッキ・`opp_from_seat`）と同じ
     デッキ表になる。オフなら None
WA-2 `policy_belief` は `policy_net` と `opp_decklist` が無いと止める
WA-3 オフ（鍵なし・False）は打ち方がバイトで同じ（`series_digest`）。オンは打ち方が変わる（口が繋がっている）

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


# ------------------------------------------------------------------ WE-1・WE-2
def _h2h():
    import eval_s3_h2h
    return eval_s3_h2h


def test_h2h_default_report_unchanged():
    H = _h2h()
    base = os.path.join(ROOT, "results", "drl")
    data = json.load(open(os.path.join(base, "s3_diag_h2h.json"), encoding="utf-8"))
    want = json.load(open(os.path.join(base, "s3_diag_h2h_report.json"), encoding="utf-8"))
    got = H.report(data, want["challenge"], want["null"])
    assert json.loads(json.dumps(got)) == want


def test_h2h_wall_rule_and_level():
    H = _h2h()
    assert H.verdict_wall(0.02, 0.001, 0.04) == "伸びた"
    assert H.verdict_wall(-0.02, -0.04, -0.001) == "悪くなった"
    assert H.verdict_wall(0.01, -0.01, 0.03).startswith("境界")
    assert H.verdict_wall(0.0, -0.02, 0.02) == "伸びていない"
    assert H.verdict_wall(-0.005, -0.03, 0.02) == "伸びていない"
    data = json.load(open(os.path.join(ROOT, "results", "drl", "s3_diag_h2h.json"), encoding="utf-8"))
    ch, nl = "ch", "null"
    if ch not in data["pairs"]:
        ch, nl = sorted(data["pairs"])[:2]
    a = H.report(data, ch, nl)
    w95 = H.report(data, ch, nl, rule="wall", level=0.95)
    w983 = H.report(data, ch, nl, rule="wall", level=0.983)
    assert (w95["main"]["lo"], w95["main"]["hi"]) == (a["main"]["lo"], a["main"]["hi"])
    assert w983["main"]["lo"] < w95["main"]["lo"] and w983["main"]["hi"] > w95["main"]["hi"]
    assert w983["raw"] == a["raw"] and w983["level"] == 0.983 and w983["rule"] == "wall"
    with pytest.raises(SystemExit):
        H.report(data, ch, nl, level=0.983)


# ------------------------------------------------------------------ WE-3
@pytest.mark.slow
def test_s2_opponent_anchor(tmp_path, monkeypatch):
    pytest.importorskip("meicho_rs")
    import importlib.util
    import subprocess
    import eval_s2_repr as E
    monkeypatch.setattr(E, "check_eval_band", lambda s, n: None)        # 検査は diag の帯で回す
    out = str(tmp_path / "h.json")
    base = ["run", "--arm", "a", "--n", "1", "--seed0", str(SEED0 + 80), "--workers", "4"]
    E.main(base + ["--opponent", "heuristic", "--out", out])
    d = json.load(open(out, encoding="utf-8"))
    assert d["opponent"] == "heuristic" and all(len(v) == 1 for v in d["results"].values())
    with pytest.raises(AssertionError):
        E.main(base + ["--opponent", "greedy", "--out", out])          # 別の相手で足し継がない
    with pytest.raises(SystemExit):
        E.main(["run", "--task", "s4", "--target", TARGET, "--opponent", "heuristic", "--arm", "a", "--n", "1",
                "--seed0", str(SEED0 + 80), "--band-kind", "diag", "--out", str(tmp_path / "s4.json")])
    # 既定（planner）は口を足す前と同じ
    try:
        src = subprocess.run(["git", "show", f"{PRE_COMMIT}:engine/experiments/eval_s2_repr.py"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"git か commit {PRE_COMMIT} が無い")
    old_py = os.path.join(ROOT, "experiments", "_eval_s2_repr_pre_wall.py")
    try:
        with open(old_py, "wb") as f:
            f.write(src)
        spec = importlib.util.spec_from_file_location("_eval_s2_repr_pre_wall", old_py)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
    finally:
        os.remove(old_py)
    monkeypatch.setattr(old, "check_eval_band", lambda s, n: None)
    po, pn = str(tmp_path / "po.json"), str(tmp_path / "pn.json")
    old.main(base + ["--out", po])
    E.main(base + ["--out", pn])
    assert open(po, "rb").read() == open(pn, "rb").read()


# ------------------------------------------------------------------ WA-1〜3
PI_NET = os.path.join(ROOT, "results", "models", "s2v_id_s0.json")     # v6 で学んだ方策の頭を持つ網（検査の π）


def _two_decks():
    from arena import load_deck
    import eval_s2_repr as E
    a, b = E.tune_decks()[:2]
    return load_deck(a), load_deck(b)


def _pi_spec(pool, **kw):
    from arena_rs import PLANNER
    from record_mix import NETFREE
    return PLANNER(pool, **NETFREE, policy_net=PI_NET, policy_scope="proxy", **kw)


def test_policy_belief_deck_by_seat():
    rs = pytest.importorskip("meicho_rs")
    if "policy_belief" not in rs.features():
        pytest.skip("wheel が古い")
    from arena_rs import ensure_cards
    ensure_cards()
    da, db = _two_decks()
    ad = [da["action_deck"], db["action_deck"]]
    on, off = _pi_spec(db["action_deck"], policy_belief=True), _pi_spec(db["action_deck"])
    for seed in (10, 11):
        for seat in (0, 1):
            for q in (0, 1):
                want = ad[1 - seat] if q == seat else ad[seat]
                got = rs.policy_belief_deck(ad, on, on, seed, seat, q)
                assert sorted(got) == sorted(want), (seed, seat, q)
                assert rs.policy_belief_deck(ad, off, off, seed, seat, q) is None
    # q = 自分のときは、記録の観測が渡すデッキ表（その席の opp_decklist）と同じ
    for seat in (0, 1):
        assert sorted(rs.policy_belief_deck(ad, on, on, 10, seat, seat)) == sorted(ad[1 - seat])


def test_policy_belief_requires_net_and_pool():
    rs = pytest.importorskip("meicho_rs")
    if "policy_belief" not in rs.features():
        pytest.skip("wheel が古い")
    from arena_rs import ensure_cards
    ensure_cards()
    from arena_rs import PLANNER
    from record_mix import NETFREE
    da, db = _two_decks()
    ad = [da["action_deck"], db["action_deck"]]
    with pytest.raises(ValueError):
        rs.policy_belief_deck(ad, PLANNER(db["action_deck"], **NETFREE, policy_belief=True), _pi_spec(None), 0, 0, 0)
    with pytest.raises(ValueError):
        rs.policy_belief_deck(ad, PLANNER(None, **NETFREE, policy_net=PI_NET, policy_belief=True), _pi_spec(None),
                              0, 0, 0)


@pytest.mark.slow
def test_policy_belief_off_unchanged_on_changes_play():
    rs = pytest.importorskip("meicho_rs")
    if "policy_belief" not in rs.features():
        pytest.skip("wheel が古い")
    from arena_rs import ensure_cards
    ensure_cards()
    from arena import matchup_config
    from arena_rs import PLANNER
    da, db = _two_decks()
    cfg = matchup_config(da, db)
    opp = PLANNER(da["action_deck"])

    def dig(spec):
        return [r[4] for r in rs.series_digest(cfg.chara_decks, cfg.action_decks, spec, opp, SEED0 + 60, 2, 2, 200,
                                               True)]
    base = dig(_pi_spec(db["action_deck"]))
    assert dig(_pi_spec(db["action_deck"], policy_belief=False)) == base
    assert dig(_pi_spec(db["action_deck"], policy_belief=True)) != base
