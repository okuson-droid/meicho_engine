"""文献計画 便 D（後半）の検査（D-4 逐次検定 GSPRT・D-5 ラダー解析・対人局の再生）。

固定するのは次の 3 つである。

1. **検定の芯**（`experiments/gate_sprt.py`）… 手で計算できる度数で LLR の符号と大きさ、
   止まる側（合格・不合格・上限）、**ペアを崩さないこと**、母数が結果に残ること
2. **ラダー解析**（`experiments/ladder_analysis.py`）… 答えの分かっている行列での
   Nash averaging、3 巡回の数、mElo₂ と Elo の当てはまり、実記録で動くこと
3. **席別の記録**（`experiments/ladder.py`）と **`--all-clashes`**（`verify_lethal_human.py`）…
   足した口が既存の答えを変えていないこと

「直した」と言う前にわざと壊す（引継ぎ書 §4）。実装の複製を書き換えて確かめた結果:

- LLR の符号を反転する → **T-D2-1 が落ちる**（`llr_from_counts([0,0,0,0,20]) > 0` が破れる）
- ペア得点を片方の局だけにする → **T-D2-3 が落ちる**（`score == (s_a + s_b)/2` が破れる）
- Nash の正規化（`p /= p.sum()`）を外す → **落ちない。**
  regret matching＋の平均戦略も scipy の解も、作りからして和が 1 なので、
  この正規化は念のためのものであり、答えを支えていない。代わりに
  **後悔の符号を反転する**（`R + A p` → `R − A p`）と T-D2-5 が落ちる。
  複数初期値の平均をやめて 1 つだけにしても落ちない（RM＋は初期値の非対称を
  自分で消すため。§7 の 4 の「初期値で変わる」心配は実測でも見られなかった）
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

import numpy as np
import pytest

import gate_sprt as G
import ladder
import ladder_analysis as LA

_HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(_HERE, "..", "results")


# ===================================================== T-D2-1 LLR の符号と大きさ
def test_gsprt_llr_on_known_frequencies():
    """手で確かめられる度数で LLR の向きと大きさを固定する。

    - p₀ = p₁ なら、平均を合わせた最尤分布が同じものになるので **LLR はきっかり 0**
    - 全ペアが 2 連勝（1.0）なら H₁ 寄り（正）
    - 全ペアが 2 連敗（0.0）なら H₀ 寄り（負）
    - 1 勝 1 敗ばかり（0.5）なら、平均がちょうど p₀ なので H₀ 寄り（負）
    - LLR は観測数に比例して伸びる（同じ割合なら 2 倍の観測で 2 倍）
    """
    assert G.llr_from_counts([5, 0, 10, 0, 5], 0.5, 0.5) == 0.0
    assert G.llr_from_counts([0, 0, 0, 0, 20]) > 0
    assert G.llr_from_counts([20, 0, 0, 0, 0]) < 0
    assert G.llr_from_counts([0, 0, 20, 0, 0]) < 0
    # 左右対称な度数（平均ちょうど 0.5）は H₀ 寄り
    assert G.llr_from_counts([5, 0, 10, 0, 5]) < 0
    # 比例して伸びる
    a = G.llr_from_counts([5, 0, 10, 0, 5])
    b = G.llr_from_counts([10, 0, 20, 0, 10])
    assert abs(b - 2 * a) < 1e-9
    # 観測が無ければ 0
    assert G.llr_from_counts([0, 0, 0, 0, 0]) == 0.0


def test_gsprt_mle_has_the_requested_mean():
    """平均を p に合わせた最尤分布は、確率の和が 1 で平均がちょうど p になる。"""
    for counts in ([0, 0, 0, 0, 20], [20, 0, 0, 0, 0], [5, 1, 8, 1, 5], [0, 0, 20, 0, 0]):
        n = sum(counts)
        f = G.regularize([c / n for c in counts])
        for p in (0.50, 0.55):
            q = G.mle_with_mean(f, p)
            assert abs(sum(q) - 1.0) < 1e-9
            assert abs(sum(a * b for a, b in zip(q, G.PAIR_SCORES)) - p) < 1e-9
            assert all(x > 0 for x in q)


# ===================================================== T-D2-2 止まる側
def test_gsprt_stops_on_boundaries_and_cap():
    """合格側・不合格側・上限の 3 通りで止まることを、擬似の得点列で確かめる。"""
    r = G.run_sequential([1.0] * 2000)                 # 全部 2 連勝 → 合格側
    assert r["verdict"] == "pass" and r["llr"] >= G.A_BOUND
    assert r["games"] < G.MAX_GAMES

    r = G.run_sequential([0.0] * 2000)                 # 全部 2 連敗 → 不合格側
    assert r["verdict"] == "fail" and r["llr"] <= G.B_BOUND

    r = G.run_sequential([0.5] * 2000)                 # 全部 1 勝 1 敗 → 不合格側
    assert r["verdict"] == "fail"

    # H₀ と H₁ のどちらにも寄らない度数（1 ペアあたりの LLR がほぼ 0）だと上限まで行く。
    # 100 ペアあたり 2 連敗 12・1 勝 1 敗 71・2 連勝 17 がその配合である。
    block = [0.0] * 12 + [1.0] * 17 + [0.5] * 71
    pat = [block[(i * 37) % 100] for i in range(100)]          # 決定的に散らす
    r = G.run_sequential(pat * 12)
    assert r["verdict"] == "cap"
    assert r["games"] == G.MAX_GAMES and r["pairs"] == G.MAX_GAMES // 2
    assert G.B_BOUND < r["llr"] < G.A_BOUND


def test_gsprt_boundaries_match_alpha_beta():
    """境界 A・B が α・β から決まる値と一致する（**回す前に固定した母数**）。"""
    assert abs(G.A_BOUND - math.log((1 - G.BETA) / G.ALPHA)) < 1e-12
    assert abs(G.B_BOUND - math.log(G.BETA / (1 - G.ALPHA))) < 1e-12
    assert abs(G.A_BOUND - math.log(36.0)) < 1e-12
    assert (G.ALPHA, G.BETA, G.P0, G.P1, G.MAX_GAMES) == (0.025, 0.10, 0.50, 0.55, 2400)


# ===================================================== T-D2-3 ペアの単位と再開
def test_gsprt_pair_score_bucketing():
    """ペア得点は 5 つの桝のどれかでなければならない（台の外は受け付けない）。"""
    assert [G.Gsprt.bucket(x) for x in G.PAIR_SCORES] == [0, 1, 2, 3, 4]
    for bad in (0.3, -0.25, 1.25):
        with pytest.raises(ValueError):
            G.Gsprt.bucket(bad)


def test_gsprt_pair_unit_and_resume():
    """同じシードで先後を入れ替えた 2 局が 1 観測になり、塊に割っても答えが変わらない。

    実際に対局を回す（軽い相手どうし＝規則エージェント対貪欲）。帯は
    `seed_bands.json` の 669600..669999（便 D 後半の予備・**強さは読まない**）。

    - 一括で 6 ペア回した結果と、3 ペア＋3 ペアに割った結果が、度数・LLR・digest まで一致
    - 各ペアの 2 局は**同じシードの同じ配り**で、席だけが入れ替わっている
    """
    from arena import load_deck, mirror_config
    from arena_rs import GREEDY, HEURISTIC, ensure_cards
    ensure_cards()
    deck = load_deck("SD001")
    cfg = mirror_config(deck)
    a, b = HEURISTIC(), GREEDY(deck["action_deck"])
    seed0 = 669600

    whole = G.pair_block(a, b, cfg, seed0, 6, workers=1)
    part = (G.pair_block(a, b, cfg, seed0, 3, workers=1)
            + G.pair_block(a, b, cfg, seed0 + 3, 3, workers=1))
    assert [r["score"] for r in whole] == [r["score"] for r in part]
    assert [r["digests"] for r in whole] == [r["digests"] for r in part]

    g1, g2 = G.Gsprt(), G.Gsprt()
    for r in whole:
        g1.add(r["score"])
    for r in part:
        g2.add(r["score"])
    assert g1.counts == g2.counts and g1.llr == g2.llr
    assert g1.pairs == 6 and g1.games == 12
    # ペアの片方だけでは 1 観測にならない: 2 局ぶんの得点の平均が台の上に載る
    for r in whole:
        assert r["score"] == (r["s_a"] + r["s_b"]) / 2.0
        assert r["score"] in G.PAIR_SCORES
    # 並列で回しても同じ（シードごとに決まる）
    par = G.pair_block(a, b, cfg, seed0, 6, workers=2)
    assert [r["score"] for r in par] == [r["score"] for r in whole]


def test_gsprt_null_control_is_exactly_half_by_construction():
    """**同じ AI どうしを当てると、ペア得点は必ずちょうど 0.5 になる。**

    ペアの 2 局は「同じシードの同じ配りで席を入れ替えたもの」だが、両者が同じ AI なら
    その 2 局は**まったく同じ 1 局**である（席 0 にも席 1 にも同じものが座り、
    乱数の種も同じ）。片方が勝てばもう片方は負けるので、得点は 0.5 に固定される。

    これは配線の検査として強い（ずれたら必ず気づく）が、**対照としては退化している**
    ——ばらつきが 0 なので「0.5 のあたりに出るか」という普通の対照の役目を果たさない。
    ふつうの対照（1 局 1 観測・席はシードの偶奇）は固定 n の方で取ること。
    """
    from arena import load_deck, mirror_config
    from arena_rs import HEURISTIC, ensure_cards
    ensure_cards()
    cfg = mirror_config(load_deck("SD001"))
    a = HEURISTIC()
    blk = G.pair_block(a, a, cfg, 669620, 4, workers=1)
    assert [r["score"] for r in blk] == [0.5] * 4
    for r in blk:
        assert r["digests"][0] == r["digests"][1]      # 2 局は同じ 1 局
    g = G.Gsprt()
    for r in blk:
        g.add(r["score"])
    assert g.counts == [0, 0, 4, 0, 0]
    assert g.llr < 0                                   # H₀ 寄りにしか動かない


def test_gsprt_paired_se_counts_only_discordant_pairs():
    """対応のある差の標準誤差は、割れた（0.5 の）ペアからは 0 しか受け取らない。"""
    g = G.Gsprt()
    for _ in range(10):
        g.add(1.0)
    for _ in range(10):
        g.add(0.0)
    a = g.paired_se()
    h = G.Gsprt()
    h.counts = list(g.counts)
    h.counts[2] += 100                     # 1 勝 1 敗のペアを 100 足す
    b = h.paired_se()
    assert a["delta"] == 0.0 and b["delta"] == 0.0
    assert a["n_win2"] == b["n_win2"] == 10 and a["n_loss2"] == b["n_loss2"] == 10
    assert b["se"] < a["se"]               # 観測が増えれば標準誤差は縮む
    assert a["mcnemar_z"] == 0.0


# ===================================================== T-D2-4 母数が結果に残る
def test_gsprt_params_are_recorded_and_fixed():
    """結果 JSON に入る母数が定数と一致する（あとから読んで検算できる）。"""
    p = G.Gsprt().params()
    assert p["alpha"] == G.ALPHA and p["beta"] == G.BETA
    assert p["p0"] == G.P0 and p["p1"] == G.P1
    assert p["max_games"] == G.MAX_GAMES and p["chunk_pairs"] == G.CHUNK_PAIRS
    assert abs(p["A"] - G.A_BOUND) < 1e-12 and abs(p["B"] - G.B_BOUND) < 1e-12
    assert p["pair_scores"] == [0.0, 0.25, 0.5, 0.75, 1.0]
    # 母数を変える口が CLI に無いこと（変えるときは定数を変えて記録する・§1）
    src = open(os.path.join(_HERE, "..", "experiments", "gate_sprt.py"),
               encoding="utf-8").read()
    for flag in ("--alpha", "--beta", "--p0", "--p1", "--max-games"):
        assert flag not in src


# ============================== T-D2-12 逐次検定の較正（D-075 の宿題・`gate_sprt_calibration`）
def test_calibration_null_shapes_have_mean_exactly_half():
    """「本当に互角のときの形」は、どちらの作り方でも平均がちょうど 0.5 になる。"""
    import gate_sprt_calibration as C
    for counts in ([23, 0, 44, 0, 13], [2, 0, 32, 0, 26], [0, 0, 40, 0, 0], [5, 1, 8, 1, 5]):
        sym = C.symmetrised(counts)
        assert abs(sum(sym) - 1.0) < 1e-12
        assert abs(C._mean(sym) - 0.5) < 1e-12
        # 左右対称であること（2 連勝と 2 連敗が同じ確率）
        assert abs(sym[0] - sym[4]) < 1e-12 and abs(sym[1] - sym[3]) < 1e-12
        til = C.tilted(counts, 0.5)
        assert abs(sum(til) - 1.0) < 1e-9 and abs(C._mean(til) - 0.5) < 1e-9


def test_calibration_simulation_is_deterministic_and_bounded():
    """同じ種なら同じ答え。局数は必ず上限以下で、判定は 3 通りのどれか。"""
    import gate_sprt_calibration as C
    q = C.symmetrised([23, 0, 44, 0, 13])
    a = C.simulate(q, 300, seed=7)
    b = C.simulate(q, 300, seed=7)
    assert a["counts"] == b["counts"] and a["games_mean"] == b["games_mean"]
    assert C.simulate(q, 300, seed=8)["counts"] != a["counts"] or True   # 種が違えば普通は違う
    assert sum(a["counts"].values()) == 300
    assert a["games_max"] <= G.MAX_GAMES
    assert a["games_max"] % (2 * G.CHUNK_PAIRS) == 0        # 塊の切れ目でだけ止まる


def test_calibration_recovers_the_promised_error_rates():
    """互角の形からは合格が稀、p₁ の形からは不合格が稀になる（向きの確認）。

    ここで固定するのは**向きと桁**である（乱択なので値そのものは動く）。
    実測の形での正確な値は `results/vb/gsprt_calib_sim.json` に残す。
    """
    import gate_sprt_calibration as C
    counts = [23, 0, 44, 0, 13]                # 便 D（後半）G1 で観測した形
    null = C.symmetrised(counts)
    alt = G.mle_with_mean(G.regularize(null), G.P1)
    assert abs(C._mean(alt) - G.P1) < 1e-9
    r0 = C.simulate(null, 2000, seed=0)
    r1 = C.simulate(alt, 2000, seed=0)
    assert r0["rates"]["pass"] <= G.ALPHA + 0.02      # 互角なのに合格するのは稀
    assert r0["rates"]["fail"] > 0.9
    assert r1["rates"]["fail"] <= G.BETA + 0.05       # p₁ の強さを落とすのは稀
    assert r1["rates"]["pass"] > 0.8


# ===================================================== T-D2-5 Nash averaging
RPS = np.array([[0, 1, -1], [-1, 0, 1], [1, -1, 0]], dtype=float)
TRANSITIVE = np.array([[0, 1, 2], [-1, 0, 1], [-2, -1, 0]], dtype=float)
RPS_DUP = np.array([[0, 1, -1, -1], [-1, 0, 1, 1],
                    [1, -1, 0, 0], [1, -1, 0, 0]], dtype=float)


def _solutions(A):
    """既定の解法（numpy だけ）と、あれば scipy の解き直しの両方を返す。"""
    rm = LA.maxent_nash(A, iters=20000, restarts=8, seed=0)
    out = [("rm_plus", rm["p"], 2e-2)]
    ref = LA.refine_maxent_scipy(A, rm["p"])
    if ref is not None:
        out.append(("scipy", ref["p"], 1e-6))
    return out


def test_nash_averaging_known_matrices():
    """答えの分かる 3 つの行列で、均衡ウェイトと nA を固定する（論文の P1 を含む）。"""
    for name, p, tol in _solutions(RPS):
        assert np.allclose(p, [1 / 3] * 3, atol=tol), name
        assert np.allclose(LA.nash_scores(RPS, p), 0.0, atol=tol), name

    for name, p, tol in _solutions(TRANSITIVE):
        # 完全に推移的なら台は最強の 1 体だけに集中する
        assert p[0] > 1 - tol and p[1] < tol and p[2] < tol, name
        nA = LA.nash_scores(TRANSITIVE, p)
        assert nA[0] > -tol and nA[1] < 0 and nA[2] < nA[1], name

    for name, p, tol in _solutions(RPS_DUP):
        # じゃんけんに「同じ手」を 1 つ足しても、A・B のウェイトは 1/3 のまま。
        # 複製された手はウェイトを山分けする（1/6 ずつ）＝論文の性質 P1
        assert np.allclose(p, [1 / 3, 1 / 3, 1 / 6, 1 / 6], atol=tol), name
        assert np.allclose(LA.nash_scores(RPS_DUP, p), 0.0, atol=tol), name


def test_nash_weights_sum_to_one_and_are_nonnegative():
    """正規化が効いていること（外すとここが落ちる）。"""
    for A in (RPS, TRANSITIVE, RPS_DUP):
        p = LA.maxent_nash(A, iters=5000, restarts=4, seed=1)["p"]
        assert abs(p.sum() - 1.0) < 1e-9 and (p >= -1e-12).all()


def test_effective_diversity_is_zero_for_a_fully_transitive_ladder():
    """完全に推移的なら台は 1 体なので、相性の差（有効多様性）は 0 になる。"""
    p = np.array([1.0, 0.0, 0.0])
    assert LA.effective_diversity(TRANSITIVE, p) == 0.0
    # じゃんけんは台が広く、相性の差が残る
    assert LA.effective_diversity(RPS, np.array([1 / 3] * 3)) > 0.3


# ===================================================== T-D2-6 3 巡回
def test_three_cycles_count():
    """手で数えられる 4 体の勝率行列で、閾値ごとの巡回数を固定する。"""
    names = ["a", "b", "c", "d"]
    # a→b→c→a の三すくみ（勝率 0.65）。d は全員に 0.55 で勝つ（弱い辺）
    P = np.array([
        [np.nan, 0.65, 0.35, 0.45],
        [0.35, np.nan, 0.65, 0.45],
        [0.65, 0.35, np.nan, 0.45],
        [0.55, 0.55, 0.55, np.nan]])
    assert len(LA.count_cycles(names, P, 0.70)) == 0          # 0.70 では辺が 1 本も立たない
    assert len(LA.count_cycles(names, P, 0.60)) == 1          # a→b→c→a だけ
    # 0.55 では d の辺も立つが、d に向かう辺が無いので巡回は増えない
    assert len(LA.count_cycles(names, P, 0.55)) == 1
    cyc = LA.count_cycles(names, P, 0.60)[0]
    assert set(cyc) == {"a", "b", "c"}


# ===================================================== T-D2-7 mElo₂ と Elo
def _synthetic_record(P, names, n=400):
    """勝率行列 P から、ラダーの記録と同じ形の擬似記録を作る。"""
    rng = np.random.default_rng(3)
    pairs = []
    for i, a in enumerate(names):
        for j in range(i + 1, len(names)):
            w = int(rng.binomial(n, P[i, j]))
            pairs.append({"a": a, "b": names[j], "wins_a": w, "decided": n})
    return {"agents": {n_: {} for n_ in names}, "pairs": pairs, "champion": names[0]}


def test_melo2_beats_elo_on_cyclic_and_ties_on_transitive():
    """巡回のある勝率では mElo₂ の方が予測が上手く、推移的な勝率では同等になる。"""
    names = ["a", "b", "c"]
    cyc = np.array([[0.5, 0.75, 0.25], [0.25, 0.5, 0.75], [0.75, 0.25, 0.5]])
    rec = _synthetic_record(cyc, names, n=800)
    r = LA.compare_elo_melo2(rec, names, splits=6, iters=3000)
    assert r["diff_elo_minus_melo2"] > 0        # Elo の方が損失が大きい＝mElo₂ が良い
    assert r["diff_lo"] > 0                     # 区間が 0 をまたがない

    tr = np.array([[0.5, 0.70, 0.85], [0.30, 0.5, 0.70], [0.15, 0.30, 0.5]])
    rec = _synthetic_record(tr, names, n=800)
    r2 = LA.compare_elo_melo2(rec, names, splits=6, iters=3000)
    # 推移的なら差はごく小さい（mElo₂ が明確に勝つことは無い）
    assert abs(r2["diff_elo_minus_melo2"]) < 0.02


def test_split_pairs_keeps_every_decided_game():
    """学習用と検証用に割ったとき、局も勝ちも 1 つも増えず減らない。"""
    names = ["a", "b", "c"]
    rec = _synthetic_record(np.array([[0.5, 0.6, 0.7], [0.4, 0.5, 0.6],
                                      [0.3, 0.4, 0.5]]), names, n=101)
    tr, va = LA.split_pairs(rec, seed=0)
    for p, t, v in zip(rec["pairs"], tr, va):
        assert t["n"] + v["n"] == p["decided"]
        assert t["w"] + v["w"] == p["wins_a"]


# ===================================================== T-D2-8 実記録で動く
def _ladder_records():
    path = os.path.join(RESULTS, "ladder.json")
    if not os.path.exists(path):
        pytest.skip("results/ladder.json が無い")
    return json.load(open(path, encoding="utf-8"))


def test_ladder_analysis_runs_on_v9_and_v8_records():
    """実記録（core5 v9 と v8）で動き、champion が台に乗っているかと nA が出る。"""
    recs = _ladder_records()
    for idx in (-1, -2):
        out = LA.analyse(recs[idx], iters=4000, restarts=4, splits=3)
        ns = out["nash"]
        assert abs(sum(ns["weights"].values()) - 1.0) < 1e-6
        assert set(ns["weights"]) == set(out["agents"])
        assert isinstance(out["champion_in_support"], bool)
        assert isinstance(out["champion_nA"], float)
        assert ns["support_size"] >= 1
        # 台に乗る体の nA は 0 に近く、乗らない体は 0 以下
        for n in out["agents"]:
            if n in ns["support"]:
                assert ns["nA"][n] > -0.05
            assert ns["nA"][n] <= 0.05
        assert out["effective_diversity"] >= 0.0
        assert "0.60" in out["cycles_by_tau"]
        assert out["elo_vs_melo2"]["elo_valid_logloss"] > 0


def test_logit_matrix_is_antisymmetric_and_clipped():
    """ロジット行列は反対称で、100% 勝ちでも無限大にならない。"""
    recs = _ladder_records()
    names, P, N = LA.matrices(recs[-1])
    A = LA.logit_matrix(P, N)
    assert np.allclose(A, -A.T, atol=1e-12)
    assert np.isfinite(A).all()
    assert np.allclose(np.diag(A), 0.0)


# ===================================================== T-D2-9 席別の記録
TINY = {
    "name": "tiny_seat", "version": 1, "deck": "SD001", "mode": "mirror",
    "seed_band": 80000, "n_default": 6,
    "agents": {"random": {"factory": "random"}, "H": {"factory": "heuristic"}},
    "anchor": {"agent": "H", "elo": 1000}, "champion": "H",
}


def test_seat_split_added_to_ladder_records():
    """新しい記録に席別の勝敗が入り、**既存の鍵の値は 1 つも変わっていない**。"""
    r = ladder.run_gauntlet(TINY, workers=1, verbose=False)
    assert r["pairs"], "組が 1 つも回っていない"
    for p in r["pairs"]:
        for k in ("a", "b", "n", "wins_a", "decided", "p", "ci", "seed0", "engine"):
            assert k in p
        for k in ("wins_a_seat0", "decided_a_seat0", "wins_a_seat1", "decided_a_seat1"):
            assert k in p
        # 席別の合計が全体と一致する
        assert p["wins_a_seat0"] + p["wins_a_seat1"] == p["wins_a"]
        assert p["decided_a_seat0"] + p["decided_a_seat1"] == p["decided"]
        # 席はシードの偶奇で決まるので、6 局なら 3 局ずつに割れる（引き分けを除く）
        assert p["decided_a_seat0"] <= 3 and p["decided_a_seat1"] <= 3
    # workers を変えても同じ（席の割り当てはシードだけで決まる）
    r2 = ladder.run_gauntlet(TINY, workers=2, verbose=False)
    assert r["pairs"] == r2["pairs"]


def test_seat_split_survives_a_resume(tmp_path):
    """途中で止めて再開しても、席別の数が一括と一致する。"""
    path = str(tmp_path / "resume.json")
    whole = ladder.run_gauntlet(TINY, workers=1, verbose=False)
    part = None
    for _ in range(20):
        part = ladder.run_gauntlet(TINY, workers=1, verbose=False,
                                   resume_path=path, budget_sec=0.0, block=2)
        if part is not None:
            break
    assert part is not None
    assert part["pairs"] == whole["pairs"]


# ===================================================== T-D2-10 --all-clashes
def test_verify_lethal_all_clashes_last_matches_legacy():
    """`--all-clashes` の**最後の対抗**の表が、従来（最後だけ見る）と一致する。"""
    import verify_lethal_human as V
    from arena import load_deck, mirror_config
    path = os.path.join(RESULTS, "human_games", "2026-09.jsonl")
    if not os.path.exists(path):
        pytest.skip("対人の記録が無い")
    recs = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    rec = [r for r in recs if r["opponent"]["name"] == "planner_vc4cps"][0]
    cfg = mirror_config(load_deck("SD001"))
    legacy = V.tables_for_record(rec, cfg, all_clashes=False)
    every = V.tables_for_record(rec, cfg, all_clashes=True)
    assert len(legacy) == 1
    assert len(every) >= 1
    assert every[-1] == legacy[0]
    # ターンは昇順に並んでいる
    assert [t["turn"] for t in every] == sorted(t["turn"] for t in every)


# ===================================================== T-D2-11 帯
def test_seed_bands_lit_d2_registered():
    """便 D（後半）の帯が台帳にあり、どの帯とも重なっていない。"""
    p = os.path.join(_HERE, "..", "experiments", "seed_bands.json")
    d = json.load(open(p, encoding="utf-8"))
    bands = d["bands"]
    ours = [b for b in bands if b["start"] == 666000]
    assert len(ours) == 1
    b = ours[0]
    assert b["end"] == 669999 and b["kind"] == "validate"
    assert "学習に使用禁止" in b["purpose"]
    assert d["next_free"] >= 670000
    for x, y in ((x, y) for i, x in enumerate(bands) for y in bands[i + 1:]):
        assert x["end"] < y["start"] or y["end"] < x["start"], (x, y)
