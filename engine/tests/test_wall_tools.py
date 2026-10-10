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
WE-2 `--rule wall` の判定（下端 > 0 伸びた・上端 < 0 悪くなった・点推定 > 0 で 0 をまたげば境界・それ以外は伸びていない・
     `--retest` は下端 > 0 だけで伸びた）と、
     98.3% の区間が 95% より広いこと。`--rule s3` に `--level` を渡すと止める
WE-4 足し継ぎの追試（D-169）: 1 つの結果を前後半の 2 つに分けて `merge_runs` で合わせると、元の 1 つの報告と同じ。
     シードが重なる・組のネットが違う結果は止める。直接の得点（挑戦 − 0.5）を添える
WE-5 D-170 の直接の得点の判定（`report --direct`）: 判定の 4 つの言葉、前後半に分けて合わせても同じ、null の確かめ
WE-3 `eval_s2_repr run --opponent heuristic|greedy`（課題 s2 の錨）: 相手が記録に残り、別の相手で足し継ぐと止める。
     既定（planner）は口を足す前（commit `fcb46e3`）と同じ結果。`--task s4` に `--opponent` を渡すと止める

腕 A（§2.1・§2.2 A-0）の Rust の口 `policy_belief`:
WA-1 `series` 系と同じ道で席に着けたとき、π に渡すデッキ表は「q = 自分なら相手の席の行動デッキ、q ≠ 自分なら自分の席の
     行動デッキ」（両席・偶奇のシード）。記録の観測（その席の `opp_decklist`＝相手の席の行動デッキ・`opp_from_seat`）と同じ
     デッキ表になる。オフなら None
WA-2 `policy_belief` は `policy_net` と `opp_decklist` が無いと止める
WA-3 オフ（鍵なし・False）は打ち方がバイトで同じ（`series_digest`）。オンは打ち方が変わる（口が繋がっている）
WA-7 A-2 の門（`diag_s3_desk.py --a2`）: u と局を単位の区間（同じ予測なら 0・手計算と一致・区間は点を含む）、
     判定（u ≥ 0.002 で越える・下端 ≤ 0 なら弱い通過）、記録に通すと線形・logit・isotonic の u と AUC が出る
WA-6 π つき（`policy_belief` なし）の `series_record` の記録が、口を足す前の wheel（commit `7f36ffb` から作った）と
     バイトで同じ（その wheel で出した sha を固定・2 局・両席を記録）
WA-4 `drl_train --policy-target argmax`: π の答えは探索の点数が最大の手（同点は最初）・点数の無い決定は -100（除く）。
     検証の指標は答えのある決定だけで割る。学習が回り meta に除いた数が入る。既定は WB-4 が見る
WA-5 π を持つ打ち手の口: `record_mix` の教師 `netfree_vp`・`make_s2_schedule --teacher netfree_vp --policy-net`・
     `eval_s3_h2h` の席 `V+pi=π`・`eval_s2_repr --arm 名前=V+pi=π` が、どれも NETFREE＋葉 V＋代打ち π（proxy・
     policy_belief）の同じ spec になり、指紋に π が入る。π だけ・V なしの π は止める。π の候補で 2 局回る

腕 C（§4.2 C-0）:
WC-1 `aux_targets`: c1 は全フェイズの記録に引いた s₁ のライフ差 / 20（s₁ が無ければ NaN）、c2 は log(1 + 局の最後の手番 − いまの手番)
WC-2 補助の頭を足した網の書き出しは補助の頭を持たず、足す前と同じ形・同じ重みで、葉の値は同じ入力で学習中の網と一致する
WC-3 `--aux` の学習が回り、meta に補助の目標の要約が入り、書き出した網は `--aux` なしと同じ形。既定は WB-4 が見る

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
    assert H.verdict_wall(0.01, -0.01, 0.03, retest=True) == "伸びていない"       # 追試は追試だけで判定
    assert H.verdict_wall(0.02, 0.001, 0.04, retest=True) == "伸びた"
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
    with pytest.raises(SystemExit):
        H.report(data, ch, nl, retest=True)
    assert H.report(data, ch, nl, rule="wall", level=0.983, retest=True)["retest"] is True


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
        a_seat = seed % 2                                    # 奇数シードで A が席 1 に入れ替わる
        for seat in (0, 1):
            for q in (0, 1):
                # A（オン）と B（オフ）を別の指定にして、入れ替わりを見分ける
                got = rs.policy_belief_deck(ad, on, off, seed, seat, q)
                if seat != a_seat:
                    assert got is None, (seed, seat, q)
                    continue
                # 席 q の記録の観測は、その席の opp_decklist＝相手の席の行動デッキ ad[1 - q] で作られる
                # （opp_from_seat・D-123）。π に渡すデッキ表がそれと同じなら、同じ encode で観測も一致する
                assert sorted(got) == sorted(ad[1 - q]), (seed, seat, q)
                assert sorted(got) == sorted(ad[1 - seat] if q == seat else ad[seat])


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


# ------------------------------------------------------------------ WA-4
@pytest.mark.slow
def test_policy_target_argmax(recs, tmp_path):
    D = T()
    from meicho.drl_data import read_records
    stem, _ = recs
    r = read_records(D.files_of(stem))
    b0 = D.Batcher(r)
    b = D.Batcher(r, policy_target="argmax")
    keep = np.nonzero(~np.isnan(r.z))[0]
    n_ex = 0
    for j, i in enumerate(keep):
        sc = r.scores_of(i)
        fin = np.isfinite(sc) if len(sc) else np.zeros(0, bool)
        if not fin.any():
            assert b.chosen[j] == -100
            n_ex += 1
            continue
        want = int(np.nonzero(fin & (sc == sc[fin].max()))[0][0])
        assert b.chosen[j] == (want if want < D.MAX_ACTS else -100)
    assert b.n_policy_excluded >= n_ex > 0                    # 探索しない決定（H の落とし先）がある
    assert b.n_policy_changed == int(((b.chosen >= 0) & (b.chosen != b0.chosen)).sum()) > 0   # τ の寄り道
    with pytest.raises(SystemExit):
        D.Batcher(r, policy_target="best")
    out = str(tmp_path / "pa.json")
    D.train(_args(stem, out, policy_target="argmax", wv=0.0, lam=0.0, select="best_p", hidden=8, phead=4))
    m = json.load(open(out.replace(".json", ".meta.json"), encoding="utf-8"))
    assert m["policy_target"]["train_excluded"] == b.n_policy_excluded
    assert m["log"][-1]["valid"]["n_p"] == int((b.chosen >= 0).sum())


# ------------------------------------------------------------------ WA-5
V0 = os.path.join(ROOT, "results", "models", "s3v1_id_s0.json")      # 検査の葉の V（git にある網なら何でもよい）


def test_pi_player_specs_agree():
    T()
    import eval_s2_repr as E
    import eval_s3_h2h as H
    import make_s2_schedule as M
    import record_mix as R
    pool = ["x"]
    want = dict(R.NETFREE, kind="planner", opp_decklist=pool, value_net=os.path.abspath(V0),
                policy_net=os.path.abspath(PI_NET), policy_scope="proxy", policy_belief=True)
    t = M.teacher_def("netfree_vp", value_net=V0, policy_net=PI_NET, tau=0.006)
    assert t["policy_net_sha16"] == H.sha16(PI_NET) and t["value_net_sha16"] == H.sha16(V0)
    assert R.teacher_spec(t, pool, "a", "a") == dict(want, tau=0.006)
    assert H._spec(f"{V0}+pi={PI_NET}", pool) == want
    assert E._arm_spec("x", f"{V0}+pi={PI_NET}", pool) == want
    assert H.side_sha(f"{V0}+pi={PI_NET}") == E.arm_sha(f"{V0}+pi={PI_NET}") == f"{H.sha16(V0)}+pi={H.sha16(PI_NET)}"
    assert H.side_sha(V0) == E.arm_sha(V0) == H.sha16(V0)                 # π なしは従来どおり
    assert "policy_net" not in H._spec(V0, pool) and "policy_net" not in E._arm_spec("x", V0, pool)
    for bad in (lambda: M.teacher_def("netfree_vp", value_net=V0),
                lambda: M.teacher_def("netfree_v", value_net=V0, policy_net=PI_NET),
                lambda: R.teacher_spec({"name": "netfree_vp", "value_net": V0}, pool, "a", "a"),
                lambda: H.split_side(f"netfree+pi={PI_NET}"),
                lambda: E._arm_spec("x", f"+pi={PI_NET}", pool),
                lambda: R.teacher_spec(dict(t, policy_net_sha16="0" * 16), pool, "a", "a")):
        with pytest.raises(SystemExit):
            bad()


@pytest.mark.slow
def test_pi_arm_plays(tmp_path):
    pytest.importorskip("meicho_rs")
    import eval_s2_repr as E
    out = str(tmp_path / "pi.json")
    E.main(["run", "--task", "s4", "--target", TARGET, "--opponents", "heuristic", "--band-kind", "diag",
            "--workers", "2", "--out", out, "--arm", f"vp={V0}+pi={PI_NET}", "--n", "2", "--seed0", str(SEED0 + 90)])
    d = json.load(open(out, encoding="utf-8"))
    assert len(d["results"]["vp|heuristic"]) == 2
    assert d["arms"]["vp"]["sha"].endswith("+pi=" + E.arm_sha(PI_NET))


# ------------------------------------------------------------------ WA-6
REC_SHA_PRE_A = "b5b435dfff92de43"     # commit 7f36ffb の wheel で同じ記録を出したときの sha256 先頭 16 桁（2026-10-07）


@pytest.mark.slow
def test_record_with_pi_unchanged_from_pre_policy_belief(tmp_path):
    import hashlib
    rs = pytest.importorskip("meicho_rs")
    from arena import load_deck, matchup_config
    from arena_rs import PLANNER, ensure_cards
    from record_mix import NETFREE
    ensure_cards()
    da, db = load_deck(f"env/{TARGET}"), load_deck("env/ENV_YANG_RM_CHIXIA")       # どちらも最終評価ではない
    cfg = matchup_config(da, db)

    def sp(pool):
        return PLANNER(pool, **NETFREE, value_net=V0, policy_net=PI_NET, policy_scope="proxy")
    out = str(tmp_path / "r")
    rs.series_record(cfg.chara_decks, cfg.action_decks, sp(db["action_deck"]), sp(da["action_deck"]),
                     935970, 2, out, 2, 200, True, True, True)
    h = hashlib.sha256()
    for f in sorted(x for x in os.listdir(tmp_path) if x.startswith("r.")):
        h.update((tmp_path / f).read_bytes())
    assert h.hexdigest()[:16] == REC_SHA_PRE_A


# ------------------------------------------------------------------ WA-7
def test_a2_uplift_and_verdict():
    import diag_s3_desk as K
    r = np.random.RandomState(3)
    z = (r.rand(400) < 0.5).astype(float)
    game = np.repeat(np.arange(40), 10)
    p0 = np.clip(0.5 + 0.2 * (z - 0.5) + r.normal(0, 0.1, 400), 0.05, 0.95)
    same = K.uplift_ci(p0, p0, z, game, n_boot=500)
    assert same["u"] == same["lo"] == same["hi"] == 0 and same["n_games"] == 40
    pt = np.clip(p0 + 0.1 * (z - 0.5), 0.05, 0.95)                       # 勝敗に寄せた教師
    got = K.uplift_ci(p0, pt, z, game, n_boot=2000)
    want = float(np.mean(K._ll_each(p0, z) - K._ll_each(pt, z)))
    assert got["u"] == pytest.approx(want) and got["lo"] <= got["u"] <= got["hi"] and got["u"] > 0
    assert K.verdict_a2(0.001, -0.01).startswith("門を越えない")
    assert K.verdict_a2(0.003, -0.001) == "門を越える（弱い通過・区間の下端 ≤ 0）"
    assert K.verdict_a2(0.003, 0.001) == "門を越える"


@pytest.mark.slow
def test_a2_gate_on_records(recs):
    T()
    import diag_s3_desk as K
    import glob as G
    stem, d = recs
    from drl_train import files_of
    mans = [json.load(open(p, encoding="utf-8")) for p in sorted(G.glob(stem + "*.manifest.json"))]
    out = K.gate_a2(files_of(stem), mans)
    a = out["A"]
    assert set(a["forms"]) == {"linear", "logit", "iso"} and a["n_searched"] > 0
    assert "u" in a["forms"]["iso"]                       # 検査の記録は葉の V なし＝探索値が [−1, 1] の外で logit は飛ぶ
    assert out["u_A"] == a["forms"]["linear"]["u"] and out["verdict"] == K.verdict_a2(out["u_A"], out["lo"])
    assert out["lo"] <= out["u_A"] <= out["hi"]


# ------------------------------------------------------------------ WC-1〜3
def test_aux_targets_by_hand():
    D = T()
    from meicho.encode import OBS_DIM
    A, C = D.ACTION_PHASE, D.PHASE_NAMES.index("clash")
    # (seed, pi, turn, step, phase, 自分の手番か, 自分のライフ, 相手のライフ)
    rows = [(1, 0, 1, 0, A, 1, 20, 20), (1, 1, 1, 1, C, 0, 20, 20), (1, 1, 2, 2, A, 1, 18, 15),
            (1, 0, 2, 3, C, 0, 15, 18), (1, 0, 3, 4, A, 1, 12, 9), (2, 0, 1, 0, A, 1, 20, 20)]
    a = np.array(rows)
    obs = np.zeros((len(rows), OBS_DIM), np.int8)
    obs[:, D.TURN_FLAG_COL] = a[:, 5]
    obs[:, D.LIFE_COLS[0]], obs[:, D.LIFE_COLS[1]] = a[:, 6], a[:, 7]
    c1, c2 = D.aux_targets(a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], obs)
    # 席 0 の手番 1 と手番 2（相手の手番の対抗）の s₁ は席 0 の手番 3（#4: 12 − 9）。席 1 の手番 1 の対抗の s₁ は席 1 の手番 2（#2）
    assert np.allclose(c1[[0, 3]], 3 / 20) and np.isclose(c1[1], 3 / 20)
    assert np.isnan(c1[2]) and np.isnan(c1[4]) and np.isnan(c1[5])
    assert np.allclose(c2, np.log1p([2, 2, 1, 1, 0, 0]))


def test_aux_head_not_exported():
    T()
    import torch
    import drl_train as D
    from meicho.encode import OBS_DIM
    torch.manual_seed(0)
    m = D.TwoHead(hidden=16, depth=2, phead=8)
    before = m.export()
    m.add_aux()
    after = m.export()
    assert [w.tobytes() for w, b in after.trunk] == [w.tobytes() for w, b in before.trunk]
    assert after.value[0].tobytes() == before.value[0].tobytes() and len(after.policy) == len(before.policy)
    x = np.random.RandomState(1).randint(-3, 4, (5, OBS_DIM)).astype(np.float32)
    with torch.no_grad():
        h = m.trunk(torch.from_numpy(x) / m.scale)
        v = torch.sigmoid(m.value(h)).squeeze(-1).numpy()
    assert np.allclose([after.value_of(r) for r in x], v, atol=1e-5)


@pytest.mark.slow
def test_aux_train_meta(recs, tmp_path):
    D = T()
    from meicho.drlnet import Net
    stem, _ = recs
    o1, o2 = str(tmp_path / "plain.json"), str(tmp_path / "aux.json")
    D.train(_args(stem, o1))
    D.train(_args(stem, o2, aux=True))
    m = json.load(open(o2.replace(".json", ".meta.json"), encoding="utf-8"))
    assert m["aux"]["w"] == 0.25 and m["aux"]["n_c1"] > 0 and m["aux"]["exported"] is False
    a, b = Net.load(o1), Net.load(o2)
    assert [w.shape for w, _ in a.trunk] == [w.shape for w, _ in b.trunk] and a.value[0].shape == b.value[0].shape
    assert "aux" not in json.load(open(o1.replace(".json", ".meta.json"), encoding="utf-8"))


# ------------------------------------------------------------------ WE-4
def test_h2h_merge_runs_equals_single():
    import copy
    H = _h2h()
    data = json.load(open(os.path.join(ROOT, "results", "drl", "s3_diag_h2h.json"), encoding="utf-8"))
    n, h = data["n"], data["n"] // 2
    a, b = copy.deepcopy(data), copy.deepcopy(data)
    a["n"], b["n"], b["seed0"] = h, n - h, data["seed0"] + h
    for k in data["results"]:
        a["results"][k] = data["results"][k][:h]
        b["results"][k] = data["results"][k][h:]
    m = H.merge_runs([a, b], "ch", "null")
    want = H.report(data, "ch", "null", rule="wall", level=0.983)
    got = H.report(m, "ch", "null", rule="wall", level=0.983)
    assert got["main"] == want["main"] and got["by_deck"] == want["by_deck"] and got["raw"] == want["raw"]
    with pytest.raises(SystemExit):
        H.merge_runs([a, a], "ch", "null")                     # シードが重なる
    c = copy.deepcopy(b)
    c["pairs"]["ch"]["a"]["sha"] = "0" * 16
    with pytest.raises(SystemExit):
        H.merge_runs([a, c], "ch", "null")
    d = H.direct_score(m, "ch", level=0.95)
    assert d["lo"] <= d["diff"] <= d["hi"]


# ------------------------------------------------------------------ WE-5
def test_h2h_direct_report():
    import copy
    H = _h2h()
    assert H.verdict_direct(0.03, 0.001, 0.06) == "伸びた"
    assert H.verdict_direct(-0.03, -0.06, -0.001) == "悪くなった"
    assert H.verdict_direct(0.0, -0.02, 0.019).startswith("区別できない（+2% 以上")
    assert "否定できない" in H.verdict_direct(0.01, -0.01, 0.03)
    data = json.load(open(os.path.join(ROOT, "results", "drl", "s3_diag_h2h.json"), encoding="utf-8"))
    r = H.report_direct(data, "ch", 0.983, null_data=data, nl="null")
    d = H.direct_score(data, "ch", level=0.983)
    assert r["main"]["diff"] == d["diff"] and r["main"]["lo"] == d["lo"] and r["n_games"] == 16 * data["n"]
    assert "contains_half" in r["null"]
    h = data["n"] // 2
    a, b = copy.deepcopy(data), copy.deepcopy(data)
    a["n"], b["n"], b["seed0"] = h, data["n"] - h, data["seed0"] + h
    for k in data["results"]:
        a["results"][k], b["results"][k] = data["results"][k][:h], data["results"][k][h:]
    m = H.merge_runs([a, b], "ch", None)
    assert H.report_direct(m, "ch", 0.983)["main"]["diff"] == pytest.approx(r["main"]["diff"])
