"""塊に割る道具（`experiments/plan_chunks.py`・D-142 追記 1 の 4）と `eval_s2_repr.py report` の直しの検査。

C-1 D-141 で使った割り振り（`results/drl/s3_it1_rec/{train,val}_chunks.json`）を、同じ見込み秒数で作り直すと
    バイト単位で同じになる（作業領域にあった道具を移しても割り振りが変わらない）
C-2 塊の小ブロックは親ブロックのシードを連続して過不足なく覆い、局数は偶数、1 塊の見込み秒数は予算以下
C-3 塊の組み合わせ表（`chunk_schedule`）は、D-141 の各 manifest に入っている組み合わせ表と同じ
C-4 `report` は、足し継ぎの途中（ブロックの局数が n に届いていない）の候補を落とさずに飛ばす
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import eval_s2_repr as R                                               # noqa: E402
import plan_chunks as P                                                # noqa: E402

REC = os.path.join(ROOT, "results", "drl", "s3_it1_rec")
SCHED = {x: os.path.join(ROOT, "results", "drl", f"s3_it1_{x}_schedule.json") for x in ("train", "val")}


@pytest.mark.parametrize("x", ["train", "val"])
def test_rebuild_matches_d141(tmp_path, x):
    """C-1: D-141 の割り振りとバイト単位で同じ。"""
    # `source` 欄は engine/ からの相対パスの文字列なので、cwd に依らないよう道具の関数を直接呼ぶ（D-105）
    with open(SCHED[x], encoding="utf-8") as f:
        sch = json.load(f)
    got = json.dumps(P.plan(sch, 420.0, f"results/drl/s3_it1_{x}_schedule.json"), ensure_ascii=False, indent=1)
    with open(os.path.join(REC, f"{x}_chunks.json"), "rb") as f:
        ref = f.read()
    assert got.encode("utf-8") == ref


@pytest.mark.parametrize("x", ["train", "val"])
def test_chunks_cover_blocks(x):
    """C-2: 親ブロックのシードを連続して過不足なく覆う・偶数・予算以下。"""
    with open(SCHED[x], encoding="utf-8") as f:
        sch = json.load(f)
    plan = P.plan(sch, 420.0)
    seen = {}
    for ch in plan["chunks"]:
        assert sum(b["n"] * P.COST[b["kind"]] for b in ch) <= 420.0 + 1e-9
        for b in ch:
            assert b["n"] % 2 == 0 and b["n"] >= 2
            seen.setdefault(b["parent"], []).append((b["seed0"], b["n"]))
    assert sorted(seen) == list(range(len(sch["blocks"])))
    for i, parts in seen.items():
        blk, s = sch["blocks"][i], sch["blocks"][i]["seed0"]
        for s0, n in parts:
            assert s0 == s
            s += n
        assert s == blk["seed0"] + blk["n"]


def test_budget_too_small_is_rejected():
    """C-2: 予算が 2 局ぶんに満たなければ、止まらずに落とす（前は無限ループ）。"""
    with open(SCHED["val"], encoding="utf-8") as f:
        sch = json.load(f)
    with pytest.raises(SystemExit, match="予算"):
        P.plan(sch, 20.0)


def test_cli_plan_writes_same_bytes(tmp_path, monkeypatch):
    """C-1: CLI の `plan` も同じバイトを書く（改行は LF 固定・engine/ から打つ前提の相対パス）。"""
    monkeypatch.chdir(ROOT)
    out = tmp_path / "c.json"
    P.main(["plan", "--schedule", "results/drl/s3_it1_val_schedule.json", "--out", str(out), "--budget-sec", "420"])
    with open(os.path.join(REC, "val_chunks.json"), "rb") as f:
        assert out.read_bytes() == f.read()


@pytest.mark.parametrize("x, k", [("train", 0), ("train", 77), ("train", 140), ("val", 0), ("val", 15)])
def test_chunk_schedule_matches_manifest(x, k):
    """C-3: 塊の組み合わせ表は D-141 の manifest に入っているものと同じ。"""
    with open(SCHED[x], encoding="utf-8") as f:
        src = json.load(f)
    with open(os.path.join(REC, f"{x}_chunks.json"), encoding="utf-8") as f:
        chunks = json.load(f)["chunks"]
    with open(os.path.join(REC, f"{x}.c{k:03d}.manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    got = P.chunk_schedule(src, chunks, k, f"results/drl/s3_it1_{x}_schedule.json")
    assert json.loads(json.dumps(got, ensure_ascii=False)) == man["schedule"]


def test_report_skips_incomplete_arm(tmp_path):
    """C-4: 足し継ぎの途中の候補は飛ばし、揃った候補だけで報告する（前は IndexError で落ちた）。"""
    decks = R.tune_decks()
    n = 4
    res = {}
    for a, b in R.blocks(decks):
        res[f"full|{a}|{b}"] = [[1.0, 10]] * n
        res[f"half|{a}|{b}"] = [[0.0, 10]] * (n if a != b else n // 2)      # ミラーだけ半分
    data = {"version": R.TOOL_VERSION, "decision": "D-132", "decks": decks, "n": n, "seed0": 841900,
            "opponent": "planner", "arms": {"full": {"path": None, "sha": None}, "half": {"path": None, "sha": None}},
            "results": res}
    p = tmp_path / "e.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    out = R.main(["report", "--in", str(p), "--new", "full", "--old", "half"])
    assert set(out["scores"]) == {"full"} and out["compare"] == {}
    assert out["incomplete"] == {"half": 4}
