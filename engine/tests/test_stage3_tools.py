"""段階3 反復 1 の道具（D-138・設計書 `GENERALIST_STAGE3_DESIGN.md` §3.1・§9）の検査。

T-1 既定の教師 `netfree` は従来どおり（spec が `PLANNER(pool, **NETFREE)` と同じ）
T-2 教師 `netfree_v`: `NETFREE` に `value_net` を足しただけ。パスは engine/ からの相対でも絶対でもよい。
    パスが無い・ファイルが無い・指紋（sha256 先頭 16 桁）が組み合わせ表と違う、はどれも回す前に落とす
T-3 manifest: `netfree_v` のブロックの「教師の定義」にネットの指紋が入る
T-4 「argmax 以外を選んだ決定の割合」（D-064 §6.2 の τ の下見の尺度）を manifest に書く。τ = 0 でも
    終盤の総当たりの投票（`vote_pick`）のぶんだけ 0 にならないが小さく、τ を大きくすれば増える
T-5 既定は 1 ビットも変わらない: D-129 の下見（`s2_pilot`）の TE-13 に関わらないブロックを打ち直すと、
    ブロックごとの決定数が当時の manifest と一致する（SK 系のデッキが絡むブロックは D-134 で変わるので除く）
T-6 `make_s2_schedule.py`: 既定の引数は D-131 の組み合わせ表とバイト単位で同じ。`--teacher netfree_v` は
    `--value-net` が要り、指紋を組み合わせ表に書く。`--merge` で教師の違う部分を混ぜると落ちる
T-7 `eval_s2_repr.py`: ブロックの局数を足し継いでも一度に回したのと同じ結果になる。別ファイルの結果を
    取り込む `--import` は、シード・デッキ・ネットの指紋のどれかが違えば落とす（前の反復と違うシードで
    回った候補と対にしない・§3.7）

シードは台帳の帯だけを使う: 記録は 824000..824099（段階1C-b の煙試験）、評価は 841900..841999
（D-132 の速度の下見・kind=validate）。T-5 は D-129 の下見の帯 825000.. をそのまま打ち直す。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys

import pytest

rs = pytest.importorskip("meicho_rs")

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from experiments import eval_s2_repr, make_s2_schedule, record_mix       # noqa: E402
from experiments.arena import load_deck                                 # noqa: E402
from experiments.arena_rs import PLANNER                                # noqa: E402
from meicho.cards_export import cards_json                              # noqa: E402

NET_REL = "results/models/s2v_id_s0.json"
NET_ABS = os.path.abspath(os.path.join(ROOT, NET_REL))
REC_SEED0 = 824060
EVAL_SEED0 = 841900


def _sha16(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


@pytest.fixture(scope="module", autouse=True)
def _load_cards():
    rs.load_cards(cards_json())


def _pool():
    return load_deck("SD001")["action_deck"]


def _run_mix(tmp_path, sch, name="mix"):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(sch, ensure_ascii=False), encoding="utf-8")
    return record_mix.main(["--schedule", str(p), "--out", str(tmp_path / name), "--workers", "2"])


# --- T-1・T-2 -------------------------------------------------------------------------------------

def test_netfree_default_unchanged():
    """T-1: 既定の教師の spec は従来の `PLANNER(pool, **NETFREE)` と同じ。"""
    pool = _pool()
    assert record_mix.teacher_spec({"name": "netfree", "tau": 0.0}, pool, "SD001", "SD001") \
        == PLANNER(pool, **record_mix.NETFREE)
    assert record_mix.teacher_spec({}, pool, "SD001", "SD001") == PLANNER(pool, **record_mix.NETFREE)


@pytest.mark.parametrize("path", [NET_REL, NET_ABS])
def test_netfree_v_is_netfree_plus_value_net(path):
    """T-2: `netfree_v` は `NETFREE` に葉の V を足しただけ（パスは絶対パスに直して渡す）。"""
    pool = _pool()
    got = record_mix.teacher_spec({"name": "netfree_v", "value_net": path, "tau": 0.5}, pool, "a", "b")
    assert got == PLANNER(pool, **record_mix.NETFREE, value_net=NET_ABS, tau=0.5)


@pytest.mark.parametrize("teacher, why", [
    ({"name": "netfree_v"}, "value_net"),
    ({"name": "netfree_v", "value_net": "results/models/__nothing__.json"}, "無い"),
    ({"name": "netfree_v", "value_net": NET_REL, "value_net_sha16": "0" * 16}, "指紋"),
])
def test_netfree_v_rejects_bad_net(teacher, why):
    """T-2: パスが無い・ファイルが無い・指紋が違う、は落とす。"""
    with pytest.raises(SystemExit, match=why):
        record_mix.teacher_spec(teacher, _pool(), "a", "b")


def test_schedule_check_catches_bad_net_before_running(tmp_path):
    """T-2: 教師の不備は組み合わせ表の検査で落ちる（1 局も回さない）。"""
    sch = {"name": "t", "teacher": {"name": "netfree_v", "value_net": NET_REL, "value_net_sha16": "0" * 16},
           "blocks": [{"deck_a": "SD001", "deck_b": "SD001", "seed0": REC_SEED0, "n": 2}]}
    with pytest.raises(SystemExit, match="指紋"):
        record_mix.check_schedule(sch)


# --- T-3・T-4 -------------------------------------------------------------------------------------

def test_manifest_has_net_fingerprint(tmp_path):
    """T-3: `netfree_v` のブロックの manifest に、葉の V の指紋が入る。"""
    sha = _sha16(NET_ABS)
    man = _run_mix(tmp_path, {"name": "t", "teacher": {"name": "netfree_v", "value_net": NET_REL,
                                                       "value_net_sha16": sha, "tau": 0.0},
                              "blocks": [{"deck_a": "SD001", "deck_b": "SD001", "seed0": REC_SEED0, "n": 2}]})
    b = man["blocks"][0]
    assert b["nets"] == {"s2v_id_s0.json": sha}
    assert b["teacher"]["name"] == "netfree_v" and b["teacher"]["value_net"] == NET_REL
    assert b["spec_a"].get("value_net") == "s2v_id_s0.json"          # strip_paths で名前だけ残る


def test_nonargmax_rate(tmp_path):
    """T-4: τ = 0 では argmax 以外は少なく（投票のぶんだけ）、τ を大きくすれば増える。"""
    out = {}
    for tau in (0.0, 5.0):
        man = _run_mix(tmp_path, {"name": "t", "teacher": {"name": "netfree", "tau": tau},
                                  "blocks": [{"deck_a": "SD001", "deck_b": "SD001",
                                              "seed0": REC_SEED0 + 10, "n": 2}]}, name=f"tau{tau}")
        st = man["blocks"][0]["nonargmax"]
        assert st["multi"] > 0 and 0 <= st["off"] <= st["multi"]
        assert st["rate"] == pytest.approx(st["off"] / st["multi"])
        out[tau] = st
        assert man["nonargmax"] == st                              # 1 ブロックなので全体＝そのブロック
    assert out[0.0]["rate"] < 0.05
    assert out[5.0]["off"] > out[0.0]["off"] + 5


# --- T-5 ------------------------------------------------------------------------------------------

def test_pilot_blocks_replay_decision_counts(tmp_path):
    """T-5: D-129 の下見を打ち直すと、TE-13 に関わらないブロックの決定数が当時と一致する。"""
    with open(os.path.join(ROOT, "results", "drl", "s2_pilot.manifest.json"), encoding="utf-8") as f:
        old = json.load(f)
    keep = [b for b in old["blocks"] if "_SK_" not in b["deck_a"] + b["deck_b"]]
    assert len(keep) == 15
    sch = copy.deepcopy(old["schedule"])
    sch["blocks"] = [sch["blocks"][b["i"]] for b in keep]
    man = _run_mix(tmp_path, sch, name="pilot")
    for new, ref in zip(man["blocks"], keep):
        assert (new["deck_a"], new["deck_b"], new["seed0"]) == (ref["deck_a"], ref["deck_b"], ref["seed0"])
        assert new["decisions"] == ref["decisions"], (ref["deck_a"], ref["deck_b"], ref["opponent"])


# --- T-6 ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("stem", ["s2_v1_train_schedule", "s2_v1_val_schedule"])
def test_schedule_default_bytes_match_d131(tmp_path, stem):
    """T-6: 既定の引数で作り直した組み合わせ表は D-131 のものとバイト単位で同じ。"""
    ref_path = os.path.join(ROOT, "results", "drl", f"{stem}.json")
    with open(ref_path, "rb") as f:
        ref = f.read()
    g = json.loads(ref)["generator"]
    out = tmp_path / "s.json"
    make_s2_schedule.main(["--n-total", str(g["n_total_requested"]), "--seed0", str(g["band"][0]),
                           "--band-end", str(g["band"][1]), "--name", json.loads(ref)["name"],
                           "--out", str(out)])
    assert out.read_bytes() == ref


def test_schedule_teacher_netfree_v(tmp_path):
    """T-6: `--teacher netfree_v` は葉の V のパス・指紋・τ を組み合わせ表の教師に書く。"""
    out = tmp_path / "s.json"
    sch = make_s2_schedule.main(["--n-total", "400", "--seed0", "900000", "--band-end", "999999",
                                 "--teacher", "netfree_v", "--value-net", NET_REL, "--tau", "0.3",
                                 "--out", str(out)])
    assert sch["teacher"] == {"name": "netfree_v", "tau": 0.3, "value_net": NET_REL,
                              "value_net_sha16": _sha16(NET_ABS)}
    assert json.loads(out.read_text(encoding="utf-8"))["teacher"] == sch["teacher"]


@pytest.mark.parametrize("args, why", [
    (["--teacher", "netfree_v"], "--value-net"),
    (["--value-net", NET_REL], "netfree_v"),
    (["--teacher", "netfree_v", "--value-net", "results/models/__nothing__.json"], "無い"),
])
def test_schedule_teacher_args_checked(tmp_path, args, why):
    with pytest.raises(SystemExit, match=why):
        make_s2_schedule.main(["--n-total", "400", "--seed0", "900000", "--band-end", "999999",
                               *args, "--out", str(tmp_path / "s.json")])


def _fake_manifest(tmp_path, name, teacher, nets):
    m = {"encoding_version": 6, "rules_version": "v0.19", "format": "MCDR v3", "schedule_name": name,
         "schedule_sha256": "x", "schedule": {"teacher": teacher}, "seconds": 1.0,
         "blocks": [{"n": 2, "nets": nets}], "games_by_opponent": {"teacher": 2},
         "decks": {"env/A": {"sha256": "s", "games": 2, "seat_games": 4, "seat_games_teacher": 4,
                             "decisions_recorded": 10}}}
    p = tmp_path / f"{name}.manifest.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return str(p)


def test_merge_rejects_mixed_teachers(tmp_path):
    """T-6: 教師（名前・τ・葉の V の指紋）の違う部分をまとめると落ちる。同じなら通る。"""
    t = {"name": "netfree_v", "tau": 0.3, "value_net": NET_REL, "value_net_sha16": "a" * 16}
    p0 = _fake_manifest(tmp_path, "p0", t, {"v.json": "a" * 16})
    p1 = _fake_manifest(tmp_path, "p1", t, {"v.json": "a" * 16})
    assert make_s2_schedule.merge_manifests([p0, p1])["games"] == 4
    p2 = _fake_manifest(tmp_path, "p2", dict(t, tau=0.0), {"v.json": "a" * 16})
    with pytest.raises(SystemExit, match="教師"):
        make_s2_schedule.merge_manifests([p0, p2])
    p3 = _fake_manifest(tmp_path, "p3", t, {"v.json": "b" * 16})
    with pytest.raises(SystemExit, match="教師"):
        make_s2_schedule.merge_manifests([p0, p3])


# --- T-7 ------------------------------------------------------------------------------------------

def _eval(out, n, *extra, seed0=EVAL_SEED0, arm="nf"):
    return eval_s2_repr.main(["run", "--arm", arm, "--n", str(n), "--seed0", str(seed0), "--workers", "2",
                              "--budget-sec", "1e9", "--out", str(out), *extra])


def test_eval_extend_equals_direct(tmp_path):
    """T-7: 2 局で回したあと 4 局に足し継いだ結果は、最初から 4 局で回したのと同じ。"""
    direct = _eval(tmp_path / "d.json", 4)
    part = _eval(tmp_path / "p.json", 2)
    assert part["n"] == 2
    grown = _eval(tmp_path / "p.json", 4)                   # 同じファイルの局数を増やす
    assert grown["n"] == 4 and grown["results"] == direct["results"]
    _eval(tmp_path / "q.json", 2)
    ext = _eval(tmp_path / "x.json", 4, "--import", f"{tmp_path / 'q.json'}:nf")    # 別ファイルから取り込む
    assert ext["n"] == 4 and ext["results"] == direct["results"]
    assert ext["imported"] == [{"from": str(tmp_path / "q.json"), "arm": "nf", "n": 2}]


def test_eval_import_rejects_mismatch(tmp_path):
    """T-7: 取り込み元のシード・ネットの指紋・局数（取り込み先より多い）が違えば落とす。"""
    _eval(tmp_path / "a.json", 2)
    with pytest.raises(SystemExit, match="シード"):
        _eval(tmp_path / "b.json", 2, "--import", f"{tmp_path / 'a.json'}:nf", seed0=EVAL_SEED0 + 10)
    with pytest.raises(SystemExit, match="指紋"):
        _eval(tmp_path / "c.json", 2, "--import", f"{tmp_path / 'a.json'}:nf", arm=f"nf={NET_REL}")
    _eval(tmp_path / "big.json", 4)
    with pytest.raises(SystemExit, match="局数"):
        _eval(tmp_path / "s.json", 2, "--import", f"{tmp_path / 'big.json'}:nf")
    with pytest.raises(SystemExit, match="候補"):
        _eval(tmp_path / "m.json", 2, "--import", f"{tmp_path / 'a.json'}:zz")
