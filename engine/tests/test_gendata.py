"""C-1 §4.1-1 学習データ生成のテスト（D-037）。

ルール裁定ではなくデータ生成基盤の検査。守るべき不変条件は3つある。

1. **採取は対局を変えない**（`observe` は純粋関数。記録したせいで別の対局に
   なっていたら、学習データは実戦の分布ではない）。
2. **保存物に隠蔽情報が含まれない**（D-026 を保存形式のレベルで担保する）。
3. **決定的である**（作業規約6。同じ定義・同じ帯なら同じデータになる）。
"""
import gzip
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

import pytest

import gendata
from arena import load_deck, mirror_config
from registry import make
from meicho.runner import play_game


def _mk(name="planner", kwargs=None):
    deck = load_deck("SD001")
    return make(name, kwargs, deck["action_deck"])


def _cfg():
    return mirror_config(load_deck("SD001"))


# --- 1. 採取が対局を変えないこと -------------------------------------------

def test_recording_does_not_change_the_game():
    """`_record_game` は `play_game` と同じ対局を再現すること。

    観測の採取は `observe`（純粋関数）を呼ぶだけで、状態にもエージェントの
    乱数にも触れない。ここが破れると学習データは実戦の分布からずれる。
    """
    cfg, seed = _cfg(), 90000
    mk_a, mk_b = _mk("planner"), _mk("heuristic")
    ref = play_game(cfg, [mk_a(seed * 2), mk_b(seed * 2 + 1)], seed=seed)
    got = gendata._record_game(
        cfg, [mk_a(seed * 2), mk_b(seed * 2 + 1)], seed, ["a", "b"])
    assert got["turns"] == ref["turns"]
    assert got["aborted"] == ref["aborted"]
    assert got["winner"] == ref["winner"]


# --- 2. 保存物に隠蔽情報が無いこと -----------------------------------------

def test_saved_rows_contain_no_hidden_information():
    """§4/§10・D-026: 相手の手札の中身とデッキ順序が保存物に現れないこと。

    `observe` を保存単位にしているので構造的に入りようがないが、
    保存形式を変えたときに気づけるよう機械で押さえる。
    """
    r = gendata._one((_mk("planner"), _mk("heuristic"), "planner", "H",
                      _cfg(), 90040))
    assert r["rows"], "1件も採れていない"
    for row in r["rows"]:
        opp = row["obs"]["opp"]
        # 相手の手札は枚数と「スキャンで見た分」だけ。中身の列は持たない
        assert "hand" not in opp
        assert set(opp) >= {"hand_count", "hand_known"}
        # デッキは順序を持たない（枚数のみ）。両者とも。
        assert "action_deck" not in opp and "action_deck" not in row["obs"]["me"]
        assert isinstance(opp["deck_count"], int)
        assert isinstance(row["obs"]["me"]["deck_count"], int)


def test_saved_rows_are_json_serialisable_and_labelled():
    """行が JSON 直列化可能で、ラベルと出所が揃っていること。"""
    r = gendata._one((_mk("planner"), _mk("heuristic"), "planner", "H",
                      _cfg(), 90041))
    for row in r["rows"]:
        assert set(row) >= {"turn_no", "seat", "agent", "obs", "z",
                            "turns_total", "seed", "matchup"}
        assert row["z"] in (0.0, 0.5, 1.0)
        assert row["seat"] in (0, 1)
        json.dumps(row)                      # 例外が出ないこと


def test_labels_are_zero_sum_within_a_game():
    """同一ターンの両者のラベルは足して 1.0（引き分けなら双方 0.5）。

    ラベルの視点が取り違えられていたら、ここで落ちる。
    """
    r = gendata._one((_mk("planner"), _mk("greedy"), "planner", "greedy",
                      _cfg(), 90060))
    by_turn = {}
    for row in r["rows"]:
        by_turn.setdefault(row["turn_no"], []).append(row)
    assert by_turn
    for turn, rows in by_turn.items():
        assert len(rows) == 2, f"ターン {turn} が両者ぶん揃っていない"
        assert {rows[0]["seat"], rows[1]["seat"]} == {0, 1}
        assert rows[0]["z"] + rows[1]["z"] == pytest.approx(1.0)


# --- 3. シード帯と割り当て -------------------------------------------------

def test_seed_assignment_is_disjoint_and_deterministic():
    """対戦組へのシード割り当てが重複せず、呼ぶたびに同じであること。"""
    d = gendata.load_def("c1_v1")
    p1, p2 = gendata.plan(d, "train"), gendata.plan(d, "train")
    assert p1 == p2
    used = set()
    for m in p1:
        rng = set(range(m["seed0"], m["seed0"] + m["games"]))
        assert not (used & rng), f"シードが重複している: {m}"
        used |= rng
    # train と valid は帯ごと分かれていること（D-028）
    tv = {s for m in gendata.plan(d, "valid")
          for s in range(m["seed0"], m["seed0"] + m["games"])}
    assert not (used & tv)


def test_ladder_band_is_refused_for_data_generation():
    """D-034: 評価専用帯（80000..）での生成は拒否されること。"""
    with pytest.raises(ValueError, match="評価専用"):
        gendata.check_band(80000)


def test_unregistered_band_is_refused():
    """D-028: 台帳に無い帯は拒否されること（先に seed_bands.json に追記する）。"""
    with pytest.raises(ValueError, match="未登録"):
        gendata.check_band(900000)


def test_declared_bands_are_registered():
    """定義が使う帯が台帳に登録済みであること。"""
    d = gendata.load_def("c1_v1")
    for split in d["splits"]:
        gendata.check_band(d["splits"][split]["seed_band"])


# --- 4. 生成物の決定性 -----------------------------------------------------

def _digest(rows):
    return hashlib.sha256(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True)
                for r in rows).encode()).hexdigest()[:16]


def test_generation_is_reproducible():
    """同じ定義・同じシードなら、まったく同じ行が出ること（作業規約6）。"""
    job = (_mk("planner"), _mk("heuristic"), "planner", "H", _cfg(), 90042)
    assert _digest(gendata._one(job)["rows"]) == _digest(gendata._one(job)["rows"])


@pytest.mark.skipif(
    not os.path.exists(os.path.join(os.path.dirname(__file__), "..", "results",
                                    "datasets", "c1_v1_train.manifest.json")),
    reason="データセット未生成")
def test_generated_dataset_matches_its_manifest():
    """出力済みデータセットが、マニフェストの申告と一致すること。"""
    base = os.path.join(os.path.dirname(__file__), "..", "results", "datasets")
    man = json.load(open(os.path.join(base, "c1_v1_train.manifest.json"),
                         encoding="utf-8"))
    assert man["def_hash"] == gendata.def_hash(gendata.load_def("c1_v1")), \
        "定義が変わっている。データセットを作り直すこと"
    n = z = 0
    with gzip.open(os.path.join(base, "c1_v1_train.jsonl.gz"), "rt",
                   encoding="utf-8") as f:
        for line in f:
            n += 1
            z += json.loads(line)["z"]
    assert n == man["rows"]
    # 両者ぶんを採っているので、ラベルの総和は件数の半分になる
    assert z == pytest.approx(n / 2)
