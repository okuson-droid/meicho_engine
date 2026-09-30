"""段階3 項目 4（探索の分布）の道具の検査（D-151・設計書 `GENERALIST_STAGE3_ITEM4_DESIGN_20260930.md` §5.1・§5.3）。

L-1 葉の書き出しを渡さなければ `record_mix.py` の記録と manifest は従来の形（葉の欄を足さない）。
    渡しても記録はバイト単位で同じ（→ L-2）
L-2 毎手一致: 書き出しあり・なしで、`NETFREE`＋V と champion の両方について、選んだ手（digest）・勝敗・記録が全件一致
L-3 指紋: champion は `f4b80b25c35cfa77`（`check_champion_fingerprint.py`）。H・貪欲・素 planner の 3 種は既存の検査
    （`test_lit_a2.py::test_a2_defaults_unchanged` など）が固定している
L-4 書き出した根の入力が、同じ決定の記録の観測と一致する。信念の要約の 20 列が 0 でない（第 3 引数の渡し忘れで落ちる・D-124）
L-5 書き出した葉の入力を V に通し直すと、探索が使った値と一致（1e-5）
L-6 `leaf_cap` を変えても対局は変わらない。小さい上限で残した葉は大きい上限で残した葉の部分集合（抜き方が対局の乱数を使わない）
L-7 机上: 部品のばらつき（母標準偏差）と中央値の比が手計算と合う／重みつき中央値が `np.median` と同じ／
    再標本化の単位が局である（葉と根が同じ局から一緒に引かれる）／判定の規則の境目（下端 ≥ 1.5・上端 < 1.5・境界と追試）
L-8 `diag_s3_leaf.py subset`: 残した局の和が元の表と一致（M 通りの R で重ならず全部を覆う）・小ブロックは 2 局
L-9 4-b: 錨の相手別の決定数の和が 6,087・u_A が +0.0016（許容 0.0002）（検証の記録全体・torch が要る）

検査の対局は帯 860900..860949（kind=diag・D-151 で登録）で回す。
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import diag_s3_desk as D                                               # noqa: E402
import diag_s3_leaf as DL                                              # noqa: E402

ENS_REL = "results/models/s2v_id_ens3.json"
SEED0 = 860900                        # 検査の帯（860900..860949・kind=diag・D-151）


def _sha16(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


@pytest.fixture(scope="module")
def dumps(tmp_path_factory):
    """同じ局を葉の上限 0（書かない）・8・4 で記録する。"""
    rs = pytest.importorskip("meicho_rs")
    if "leaf_dump" not in rs.features():
        pytest.skip("入っている meicho_rs に leaf_dump が無い（再ビルドが要る）")
    import record_mix
    d = tmp_path_factory.mktemp("leaf")
    teacher = {"name": "netfree_v", "tau": 0.006, "value_net": ENS_REL,
               "value_net_sha16": _sha16(os.path.join(ROOT, ENS_REL))}
    out = {}
    for cap in (0, 8, 4):
        sch = {"name": f"l{cap}", "teacher": teacher,
               "blocks": [{"deck_a": "SD001", "deck_b": "SD001", "seed0": SEED0, "n": 2}]}
        p = d / f"s{cap}.json"
        p.write_text(json.dumps(sch), encoding="utf-8")
        argv = ["--schedule", str(p), "--out", str(d / f"r{cap}"), "--workers", "2"]
        if cap:
            argv += ["--leaf-cap", str(cap)]
        out[cap] = record_mix.main(argv)
    return out


def _bytes(files):
    return [open(p, "rb").read() for p in files]


# ------------------------------------------------------------------ L-1・L-2・L-6
@pytest.mark.slow
def test_default_manifest_has_no_leaf_keys(dumps):
    """L-1: 既定では manifest に葉の欄が無い（従来の形）。"""
    m0 = dumps[0]
    assert "leaf_cap" not in m0 and all("leaf_files" not in b for b in m0["blocks"])
    assert dumps[8]["leaf_cap"] == 8 and dumps[8]["blocks"][0]["leaf_files"]


@pytest.mark.slow
def test_leaf_dump_keeps_records(dumps):
    """L-2・L-6: 葉を書いても（上限を変えても）記録はバイト単位で同じ。"""
    ref = _bytes(dumps[0]["files"])
    for cap in (8, 4):
        assert _bytes(dumps[cap]["files"]) == ref


def _digest_pair(spec_a, spec_b, deck, n, leaf_dir=None):
    import meicho_rs as rs
    from arena import load_deck, matchup_config
    da = load_deck(deck)
    cfg = matchup_config(da, da)
    if leaf_dir is None:
        return rs.series_digest(cfg.chara_decks, cfg.action_decks, spec_a, spec_b, SEED0 + 10, n, 2, 200, True)
    res, _ = rs.series_record(cfg.chara_decks, cfg.action_decks, spec_a, spec_b, SEED0 + 10, n,
                              str(leaf_dir / "r"), 2, 200, True, True, opp_from_seat=True,
                              leaf_dump=str(leaf_dir / "l"), leaf_cap=8)
    return res


@pytest.mark.slow
@pytest.mark.parametrize("who", ["netfree_v", "champion"])
def test_play_unchanged_with_leaf_dump(who, tmp_path):
    """L-2: 書き出しあり・なしで digest（毎手の手）と勝敗が全件一致。champion にも葉がある（V を使う）。"""
    rs = pytest.importorskip("meicho_rs")
    if "leaf_dump" not in rs.features():
        pytest.skip("leaf_dump が無い")
    import champion
    from arena import load_deck
    from arena_rs import PLANNER, ensure_cards
    from record_mix import NETFREE
    ensure_cards()
    pool = load_deck("SD001")["action_deck"]
    spec = (PLANNER(pool, **NETFREE, value_net=os.path.join(ROOT, ENS_REL)) if who == "netfree_v"
            else champion.spec("SD001", pool))
    plain = _digest_pair(spec, spec, "SD001", 2)
    dumped = _digest_pair(spec, spec, "SD001", 2, tmp_path)
    assert [tuple(r) for r in plain] == [tuple(r) for r in dumped]
    lv = D.read_leaves(sorted(glob.glob(str(tmp_path / "l.*"))))
    assert len(lv["leaf"]["dec"]) > 0


@pytest.mark.slow
def test_champion_fingerprint():
    """L-3: champion の指紋が変わらない。"""
    pytest.importorskip("meicho_rs")
    import check_champion_fingerprint as C
    assert C.main() == 0


# ------------------------------------------------------------------ L-4・L-5・L-6
@pytest.mark.slow
def test_root_matches_record_and_belief_nonzero(dumps):
    """L-4"""
    from meicho.drl_data import read_records
    m = dumps[8]
    recs = read_records(m["files"])
    lv = D.read_leaves(m["blocks"][0]["leaf_files"])
    r = lv["root"]
    a = np.lexsort((recs.step, recs.pi, recs.seed))
    b = np.lexsort((r["step"], r["pi"], r["seed"]))
    assert recs.n == len(r["seed"]) > 0
    for k in ("seed", "pi", "step"):
        assert np.array_equal(getattr(recs, k)[a], r[k][b])
    assert np.array_equal(recs.obs[a], r["obs"][b])
    assert (r["obs"][:, D.BELIEF_COLS[0]:D.BELIEF_COLS[1]] != 0).any(1).mean() > 0.5


@pytest.mark.slow
def test_leaf_value_reproduces(dumps):
    """L-5: 葉の入力を V（束ねた V・部品のロジットの平均）に通し直すと、探索の使った値と 1e-5 以内。"""
    from meicho.drlnet import Net
    lv = D.read_leaves(dumps[8]["blocks"][0]["leaf_files"])
    lf = lv["leaf"]
    assert len(lf["dec"]) > 0
    ens = Net.load(os.path.join(ROOT, ENS_REL))
    assert np.abs(D.sigmoid(D.net_logit(ens, lf["obs"])) - lf["value"]).max() < 1e-5
    _, m = D.parts_spread(D.load_parts("s2v_id"), lf["obs"])
    assert np.abs(D.sigmoid(m) - lf["value"]).max() < 1e-5
    assert (lv["root"]["n_kept"] <= 8).all()
    assert (lv["root"]["n_kept"] == np.minimum(lv["root"]["n_calls"], 8)).all()


@pytest.mark.slow
def test_smaller_cap_is_subset(dumps):
    """L-6: 上限 4 で残した葉は上限 8 で残した葉の部分集合（同じ鍵の順で抜く・対局の乱数を使わない）。"""
    def keys(m):
        lv = D.read_leaves(m["blocks"][0]["leaf_files"])
        r, lf = lv["root"], lv["leaf"]
        return {(int(r["seed"][d]), int(r["step"][d]), int(r["pi"][d]), int(i)) for d, i in zip(lf["dec"], lf["idx"])}
    k4, k8 = keys(dumps[4]), keys(dumps[8])
    assert k4 and k4 < k8


# ------------------------------------------------------------------ L-7 机上
def test_wmedian_matches_numpy():
    rng = np.random.RandomState(1)
    for n in (1, 2, 5, 10):
        v = np.sort(rng.rand(n))
        w = rng.randint(0, 4, n)
        if w.sum() == 0:
            w[0] = 1
        assert D._wmedian_sorted(v, w) == pytest.approx(float(np.median(np.repeat(v, w))))


def test_spread_is_population_std():
    class Fake:
        def __init__(self, c):
            self.c = c
    lg = np.array([[0.0, 1.0], [1.0, 1.0], [2.0, 4.0]])         # 部品 3 本 × 局面 2
    orig = D.net_logit
    try:
        D.net_logit = lambda n, obs: lg[n.c]
        s, m = D.parts_spread([Fake(0), Fake(1), Fake(2)], np.zeros((2, 3)))
    finally:
        D.net_logit = orig
    assert s == pytest.approx([np.std([0, 1, 2]), np.std([1, 1, 4])])
    assert m == pytest.approx([1.0, 2.0])


def test_ratio_ci_resamples_games_together():
    """葉と根が同じ局の集合なら、局ごとに一緒に引く。局ごとに比が一定なら区間はその比に潰れる。"""
    games = np.repeat(np.arange(20), 5)
    root = np.tile(np.array([1.0, 2.0, 3.0, 4.0, 5.0]), 20)
    r = D.ratio_ci(root * 2.0, games, root, games, n_boot=500)
    assert r["ratio"] == pytest.approx(2.0) and r["lo"] == pytest.approx(2.0) and r["hi"] == pytest.approx(2.0)
    assert r["shared_games"]
    # 局で値が違えば区間は広がる（局の再標本化が効いている）
    root2 = root * (1 + games / 10.0)
    r2 = D.ratio_ci(root2 * 1.6, games, root, games, n_boot=500)
    assert r2["lo"] < r2["ratio"] < r2["hi"]
    # 葉の無い局があっても、局の集合を明示すれば一緒に引く（葉の側では重み 0 の局になるだけ）
    keep = games != 0
    g = np.unique(games)
    r3 = D.ratio_ci((root * 2.0)[keep], games[keep], root, games, n_boot=200, leaf_games=g, root_games=g)
    assert r3["shared_games"]


def test_verdict_edges():
    v = D.verdict_4a
    assert v({"lo": 1.5, "hi": 2.0, "ratio": 1.7}).startswith("説明できる")
    assert v({"lo": 1.2, "hi": 1.4999, "ratio": 1.3}).startswith("説明できない")
    assert v({"lo": 1.4, "hi": 1.6, "ratio": 1.45}).startswith("境界")
    assert "説明できる" in v({"lo": 1.4, "hi": 1.6, "ratio": 1.5}, retest=True)
    assert "説明できない" in v({"lo": 1.4, "hi": 1.6, "ratio": 1.49}, retest=True)


def test_read_leaves_roundtrip(tmp_path):
    """書式（Rust `write_leaves`）どおりに組んだバイト列を読む。"""
    od = 3
    buf = D.LEAF_FILE_HEAD.pack(b"MCLF", 1, od, 8)
    buf += D.LEAF_DEC.pack(7, 2, 3, 1, 2, 5, 2) + bytes([1, 2, 255])
    buf += D.LEAF_ITEM.pack(0, 4, 2, 1, 0.25) + bytes([9, 8, 7])
    buf += D.LEAF_ITEM.pack(3, 5, 2, 1, 0.75) + bytes([6, 5, 4])
    buf += D.LEAF_DEC.pack(8, 0, 1, 0, 1, 0, 0) + bytes([0, 0, 1])
    p = tmp_path / "x.leaf.0"
    p.write_bytes(buf)
    lv = D.read_leaves([str(p)])
    assert lv["root"]["seed"].tolist() == [7, 8] and lv["root"]["n_calls"].tolist() == [5, 0]
    assert lv["root"]["obs"][0].tolist() == [1, 2, -1]
    assert lv["leaf"]["dec"].tolist() == [0, 0] and lv["leaf"]["idx"].tolist() == [0, 3]
    assert lv["leaf"]["value"].tolist() == [0.25, 0.75] and lv["leaf"]["obs"][1].tolist() == [6, 5, 4]


# ------------------------------------------------------------------ L-8
def test_subset_partitions_pairs():
    sch = {"name": "x", "blocks": [{"kind": "mirror", "deck_a": "A", "deck_b": "A", "seed0": 100, "n": 12},
                                   {"kind": "anchor", "deck_a": "A", "deck_b": "B", "seed0": 112, "n": 8,
                                    "opponent": "heuristic", "record": "a"}]}
    seeds = []
    for r in range(5):
        out = DL.subset(sch, 5, r)
        assert all(b["n"] == 2 and b["seed0"] % 2 == 0 and (b["seed0"] // 2) % 5 == r for b in out["blocks"])
        assert out["keep_pairs"] == {"m": 5, "r": r, "source_name": "x"}
        seeds += [s for b in out["blocks"] for s in (b["seed0"], b["seed0"] + 1)]
        assert all(b["opponent"] == "heuristic" for b in out["blocks"] if b["kind"] == "anchor")
    assert sorted(seeds) == list(range(100, 120))
    with pytest.raises(SystemExit):
        DL.parse_keep_pairs("5:5")


def test_e_refuses_non_diag_band():
    with pytest.raises(SystemExit):
        DL.check_diag_band(841000, 7)          # validate の帯
    assert DL.check_diag_band(860000, 7)


# ------------------------------------------------------------------ L-9
@pytest.mark.slow
def test_anchor_split_counts_and_u_A(tmp_path_factory):
    pytest.importorskip("torch")
    with open(os.path.join(ROOT, "results", "drl", "s3_fix_t0.json"), encoding="utf-8") as f:
        t0 = json.load(f)["t0"]
    files = D.extract("val", str(tmp_path_factory.mktemp("val")))
    out = D.anchor_split(files, D.manifests("val"), t0)
    assert out["n_anchor"] == 6087
    assert sum(v["n"] for v in out["by_opponent"].values()) == 6087
    assert set(out["by_opponent"]) == {"heuristic", "greedy", "planner"}
    assert out["u_A"]["ok"], out["u_A"]
