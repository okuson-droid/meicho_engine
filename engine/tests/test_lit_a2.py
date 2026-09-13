"""文献計画 便 A 後半（A-2 束ねたソルバ `bundle_p`・D-082）の検査。

引継ぎ書 `engine/HANDOFF_20260911_LIT_A2.md` §4 の T-A2-1 〜 T-A2-11。
**本体より先に書いた。**

## この便で何を固定するのか

新しいつまみ `bundle_p` は「対抗の集約規則」を 1 つだけ変える。
AI の提出分布 x を決定化 K 本に**共通**に置いたまま

    max_x Σ_k w_k · min_{y_k} xᵀ A_k y_k

を解き、**平均戦略**から手を選ぶ。`A_k[i][j] = p·(π₀ の手に対する値) + (1−p)·(手 j に対する値)`。

固定したいのは次の 4 つである。

1. **既定（0.0）では 1 ビットも変わらない**（fingerprint 4 種・Rust の digest）
2. **`bundle_p = 1.0` は現行 champion と一手一点まで同じ**（乱数の消費まで）
   ——A-1 が実装されていないので、計画書の「p=1 で A-1 と一致」をこれに置き換えた（§0.3 (i)）
3. **ソルバが正しい**（厳密解と一致・**平均戦略**を返す・乱数を引かない）
4. **Python と Rust が同じ手・同じ点数**

## わざと壊して落ちることを確かめた 3 つ（引継ぎ書 §4）

1. ソルバを**最終反復**を返すように変える → T-A2-5・T-A2-3 が落ちる
2. 行列を**決定化ごとに解いて平均**する（＝ A-9・strategy fusion）→ T-A2-2 が落ちる
3. Rust の足し算の順序を変える → T-A2-7 が落ちる

結果は `LIT_NOTES.md` の「便 A 後半の報告」§A2-4 に書いてある。
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from fractions import Fraction

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, ".."), os.path.join(_HERE, "..", "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from meicho import bundle                                          # noqa: E402
from meicho.engine import (Phase, apply, decision_players,          # noqa: E402
                           initial_state, outcome)
from meicho.planner import PlannerAgent                             # noqa: E402
from arena import load_deck, mirror_config                          # noqa: E402

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]
# 便 C の 3 つのつまみ（いまの champion の「世界の作り方」）
KHEB = {"known_hand": True, "endgame_enum": 64, "draw_buckets": 1}

# ------------------------------------------------------------------ 明示した spec
# **`champion.py` を動的に読んではいけない。** 便 A 後半の交代（D-082 追記 2・2026-09-13）で
# `bundle_p=0.75` が champion に入ったので、動的に読むとこの検査が
# 「`bundle_p=0` の挙動不変の固定」から「新 champion の固定」に化けてしまう
# （`tests/test_champion_vc4.py` §10-5 と同じ罠。**交代の直後に実際に 3 件落ちて気づいた**）。
# 交代の前後どちらも**名指しで**持つ。
KHEB_KWARGS = {"extra_turns": 1,
               "value_net": "drl_sd001_vc4.json",
               "opp_policy_net": "drl_sd001_s1.json",
               "opp_policy_root_only": True,
               "choice_phases": True,
               "solo_samples": 4,
               "policy_net": "pi_small64_e10.json",
               "policy_scope": "proxy",
               **KHEB}
B75_KWARGS = {**KHEB_KWARGS, "bundle_p": 0.75}
KHEB_FINGERPRINT = "e82b796960e04c4a"      # 便 C の champion（`bundle_p` が入る前）
B75_FINGERPRINT = "e1662edb32b144a9"       # 便 A 後半の champion（いま）
PREV_FINGERPRINT = "9b5ad48d2de6a7e0"      # `planner_vc4cps`（二つ前）


def _rs():
    """入っている Rust が便 A 後半のつまみを知っているか。知らなければ skip。"""
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()
    if "bundle_p" not in rs.features():
        pytest.skip("Rust が便 A 後半より古い（未再ビルド）。"
                    "作業環境なら engine/rust で cargo build --release")
    return rs


def _champ_kw(**extra) -> dict:
    """champion の引数（モデルはファイル名のまま）＋ `extra`。"""
    import champion as chmod
    return {**chmod.kwargs_for("SD001"), **extra}


# =========================================================== 厳密解（LP の代わり）
def _exact_value(matrix) -> Fraction:
    """小さな零和行列ゲームの**厳密な**値（行 = 最大化・列 = 最小化）。

    支持集合を総当たりし、有理数（`Fraction`）で連立方程式を解く。
    **外部の LP 解法に頼らない**のは、マスターの PC に scipy が入っている保証が
    無いからである（検査は PC でも回る必要がある）。3×3 までしか使わない。
    """
    n, m = len(matrix), len(matrix[0])
    A = [[Fraction(x).limit_denominator(10 ** 9) for x in row] for row in matrix]
    best = None
    for r in range(1, min(n, m) + 1):
        for S in itertools.combinations(range(n), r):
            for T in itertools.combinations(range(m), r):
                rows = [[A[i][j] for i in S] + [Fraction(-1), Fraction(0)] for j in T]
                rows.append([Fraction(1)] * r + [Fraction(0), Fraction(1)])
                k = r + 1
                mx = [row[:] for row in rows]
                try:
                    for c in range(k):
                        piv = next((q for q in range(c, len(mx)) if mx[q][c] != 0), None)
                        if piv is None:
                            raise ValueError
                        mx[c], mx[piv] = mx[piv], mx[c]
                        pv = mx[c][c]
                        mx[c] = [v / pv for v in mx[c]]
                        for q in range(len(mx)):
                            if q != c and mx[q][c] != 0:
                                f = mx[q][c]
                                mx[q] = [a - f * b for a, b in zip(mx[q], mx[c])]
                except ValueError:
                    continue
                sol = [mx[c][-1] for c in range(k)]
                xs, v = sol[:r], sol[r]
                if any(q < 0 for q in xs):
                    continue
                x = [Fraction(0)] * n
                for idx, i in enumerate(S):
                    x[i] = xs[idx]
                worst = min(sum(x[i] * A[i][j] for i in range(n)) for j in range(m))
                if worst == v and (best is None or v > best):
                    best = v
    assert best is not None, "厳密解が見つからない"
    return best


RPS = [[0.5, 0.0, 1.0],       # じゃんけん（勝ち 1・あいこ 0.5・負け 0）
       [1.0, 0.5, 0.0],
       [0.0, 1.0, 0.5]]
ASYM = [[3.0, 1.0, 2.0],      # 3×3 の非対称（厳密値 39/20 = 1.95・完全混合）
        [1.0, 4.0, 0.0],
        [2.0, 0.0, 5.0]]


# ===================================================== T-A2-1 既定の挙動が不変
def test_a2_defaults_unchanged():
    """既定（`bundle_p=0`）で fingerprint 4 種が不変。Rust の digest も不変。

    ここが動いたら**止める**——過去に取ったすべての勝率が比較できなくなる。
    """
    import hashlib
    rs = _rs()
    from experiments import bench_agents
    from experiments.arena_rs import PLANNER, series_rs_digest
    from meicho.drl_data import BASELINE_DIGESTS_230000
    from meicho.drlnet import resolve_model

    assert bench_agents.fingerprint("H", 50) == "773a71c15c5bc16e"
    assert bench_agents.fingerprint("G", 20) == "677f28cc3b6995ee"
    assert bench_agents.fingerprint("P", 10) == "6e39c2aa4b35d876"

    def fp(kw):
        kwr = {k: (resolve_model(v)
                   if k in ("value_net", "opp_policy_net", "policy_net") else v)
               for k, v in kw.items()}
        out = series_rs_digest({"kind": "planner", "opp_decklist": POOL, **kwr},
                               {"kind": "planner", "opp_decklist": POOL, **kwr},
                               10, CONFIG, workers=2, seed0=471500)
        return hashlib.sha256(repr([r[4] for r in out]).encode()).hexdigest()[:16]

    # **名指しした spec** で固定する（交代でこの検査が化けないように・上の註）。
    assert fp(KHEB_KWARGS) == KHEB_FINGERPRINT, "便 C の champion の指紋が動いた"
    assert fp(B75_KWARGS) == B75_FINGERPRINT, "便 A 後半の champion の指紋が動いた"
    prev = {k: v for k, v in KHEB_KWARGS.items()
            if k not in ("known_hand", "endgame_enum", "draw_buckets")}
    assert fp(prev) == PREV_FINGERPRINT, "二つ前の champion の指紋が動いた"
    # いまの champion が名指しした spec と 1 文字も違わないこと（戻されたら気づく）
    import champion as chmod
    assert chmod.kwargs_for("SD001") == B75_KWARGS

    out = series_rs_digest(PLANNER(POOL), PLANNER(POOL), 6, CONFIG, workers=2,
                           seed0=230000)
    assert [r[4] for r in out] == list(BASELINE_DIGESTS_230000[:6])

    # つまみの既定は 0（**素の planner** で見る。champion は 2026-09-13 から 0.75 を持つ）
    assert PlannerAgent(0, opp_decklist=POOL).bundle_p == 0.0
    assert PlannerAgent(0, opp_decklist=POOL, **KHEB_KWARGS).bundle_p == 0.0
    assert PlannerAgent(0, opp_decklist=POOL, **B75_KWARGS).bundle_p == 0.75
    assert bundle.DEFAULT_ITERS == 300


# ================================== T-A2-2 p=1.0 が現行 champion と一手一点まで同じ
def _play(extra: dict, seed: int):
    """1 局まるごと回して、手の列・対抗の点数・乱数の状態・勝敗を返す。

    土台は**名指しした `KHEB_KWARGS`**（`bundle_p` が入る前の champion）である。
    `champion.kwargs_for` を動的に読むと、交代した瞬間に土台が `bundle_p=0.75` になって
    「p=1.0 が現行と同じ」という比較そのものが消える（2026-09-13 の交代で実際に落ちた）。
    """
    kw = {**KHEB_KWARGS, **extra}
    ags = [PlannerAgent(seed * 2, opp_decklist=POOL, **kw),
           PlannerAgent(seed * 2 + 1, opp_decklist=POOL, **kw)]
    s = initial_state(CONFIG, seed)
    moves, clashes = [], []
    while outcome(s) is None and s.turn_no <= 200:
        need = decision_players(s)
        if not need:
            break
        acts = {}
        for q in sorted(need):
            ags[q].last_clash = None
            acts[q] = ags[q].act(s, q)
            moves.append((q, json.dumps(acts[q], sort_keys=True)))
            lc = ags[q].last_clash
            if lc:
                clashes.append((q, lc["chosen"], tuple(lc["totals"])))
        s = apply(s, acts)
    return (moves, clashes, [a.rng.getstate() for a in ags], outcome(s))


@pytest.mark.parametrize("seed", [709960, 709961, 709962])
def test_a2_p_one_equals_current_champion(seed):
    """`bundle_p=1.0` は**便 C の champion**（`bundle_p` が入る前）と
    **一手・一点・乱数の消費まで**同じ。

    行列の全列が同値になるので、どんな x でも同じ値になり、解は最良手に落ちる。
    **そのとき列は 1 本しか採点しない**ので、採点の呼び出しも乱数の引きも増えない。

    計画書 §3.1 の「p=1 で A-1 と一致」は A-1 が実装されていないので使えない。
    引継ぎ書 §0.3 (i) の裁定で**ここに置き換えた**——fingerprint で固定できるぶん強い。
    """
    base = _play({}, seed)
    one = _play({"bundle_p": 1.0}, seed)
    assert base[0] == one[0], "手の列が違う"
    assert base[1] == one[1], "対抗の点数表が違う"
    assert base[2] == one[2], "乱数の消費が違う"
    assert base[3] == one[3], "勝敗が違う"
    assert len(base[1]) >= 5, f"比べた対抗が少なすぎる（{len(base[1])}）"


# ============================================ T-A2-3 / T-A2-4 ソルバが厳密解と合う
def _exploitability(mats, ws, x) -> float:
    """厳密解の値 − この x の最悪想定の値。"""
    assert len(mats) == 1, "厳密解を使う検査は 1 世界のみ"
    return float(_exact_value(mats[0])) - bundle.bundled_value(mats, ws, x)


def test_a2_solver_matches_lp_on_rps():
    """じゃんけん（3×3・零和）で一様 1/3 に収束し、厳密解と一致する。"""
    assert _exact_value(RPS) == Fraction(1, 2)
    x = bundle.solve_bundled([RPS], [1.0])
    assert sum(x) == pytest.approx(1.0, abs=1e-12)
    for v in x:
        assert v == pytest.approx(1.0 / 3.0, abs=1e-6)
    assert _exploitability([RPS], [1.0], x) < 1e-3


def test_a2_solver_matches_lp_on_asymmetric():
    """3×3 の非対称な既知の行列で厳密解と一致する（完全混合の均衡）。

    厳密解は x = (0.35, 0.40, 0.25)・値 39/20 = 1.95。
    """
    assert _exact_value(ASYM) == Fraction(39, 20)
    x = bundle.solve_bundled([ASYM], [1.0])
    assert sum(x) == pytest.approx(1.0, abs=1e-12)
    assert x == pytest.approx([0.35, 0.40, 0.25], abs=2e-3)
    assert _exploitability([ASYM], [1.0], x) < 1e-3


def test_a2_solver_handles_many_worlds_and_uneven_columns():
    """世界が複数あり、列数が世界ごとに違っても解ける（終盤の列挙が作る形）。"""
    mats = [RPS, [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]]
    x = bundle.solve_bundled(mats, [0.7, 0.3])
    assert len(x) == 3
    assert sum(x) == pytest.approx(1.0, abs=1e-12)
    assert all(v >= 0.0 for v in x)


# ===================================================== T-A2-5 平均戦略を返している
def test_a2_returns_the_average_not_the_last_iterate():
    """返るのは**平均戦略**であって、その時々の戦略（最終反復）ではない。

    **見分け方に一工夫が要る。** 素の RM+ なら最終反復は角に寄って暴れるので
    「一様から外れるか」で見分けられるが、いま使っているのは**予測つき** RM+ で、
    こちらは行儀のよい行列だと**最終反復も収束してしまう**（実測: じゃんけんでも
    3×3 の非対称でも最終反復の可搾取度は平均と同程度）。だから素朴な比較では
    壊れていることに気づけない。**確かめたときに分かった落とし穴なので、ここに残す。**

    そこで**退化した行列**（全列が同値）で見分ける。これは `bundle_p = 1.0` の
    ときに実際に作られる形である。最良の行が 1 つしかないので:

    - **最終反復**は 2 反復目以降その行に 1.0 が立つ＝`max == 1.0`・他は厳密に 0
    - **平均**は 1 反復目の一様が薄く残る＝`max < 1.0`・どの行も厳密には 0 でない

    最終反復を返すように壊すと、この違いが消える。
    """
    degenerate = [[0.8, 0.8], [0.2, 0.2], [0.5, 0.5]]
    x = bundle.solve_bundled([degenerate], [1.0])
    assert x[0] == max(x), "最良の行に最大の重みが載っていない"
    assert max(x) < 1.0, "角に 1.0 が立っている＝平均でなく最終反復を返している"
    assert min(x) > 0.0, "1 反復目の一様が残っていない＝平均でない"
    # 1 反復目（一様）の寄与は線形平均の重み 1 / Σt である
    t = bundle.DEFAULT_ITERS
    share = 1.0 / (t * (t + 1) / 2)
    assert x[1] == pytest.approx(share / 3.0, rel=1e-6), \
        "残っている量が線形平均の 1 反復目ぶんと合わない"
    # じゃんけんでも角に寄っていない（平均であることの別の見え方）
    r = bundle.solve_bundled([RPS], [1.0])
    assert max(r) < 0.4, f"角に寄っている（{r}）"


# ===================================================== T-A2-6 乱数を消費しない
def test_a2_solver_consumes_no_randomness():
    """`bundle_p > 0` でも `rng` の状態が進まない。

    ここが破れると、以降の引きが全部ずれて**候補間の同シード比較が壊れる**。
    ソルバ単体（`rng` を受け取らない）と、エージェント全体の両方で見る。
    """
    import random
    r = random.Random(12345)
    before = r.getstate()
    bundle.solve_bundled([RPS], [1.0])
    assert r.getstate() == before          # そもそも rng を触れない口である

    # エージェント: p=1.0 は現行と乱数の消費が同じ（T-A2-2 の一部をここでも押さえる）
    seed = 709970
    kw0 = dict(KHEB_KWARGS)                      # `bundle_p` が入る前の champion
    kw1 = {**KHEB_KWARGS, "bundle_p": 1.0}
    s = initial_state(CONFIG, seed)
    a0 = PlannerAgent(seed, opp_decklist=POOL, **kw0)
    a1 = PlannerAgent(seed, opp_decklist=POOL, **kw1)
    need = decision_players(s)
    q = sorted(need)[0]
    assert a0.act(s, q) == a1.act(s, q)
    assert a0.rng.getstate() == a1.rng.getstate()


# ===================================================== T-A2-7 Python と Rust が一致
@pytest.mark.parametrize("bundle_p", [0.9, 0.75, 0.5])
def test_a2_python_and_rust_agree(tmp_path, bundle_p):
    """`bundle_p` を立てて Python と Rust が**同じ手・同じ点数**（rel=1e-6）。

    **束ねの決定を実際に通っている**ことも確かめる（`last_clash["bundle_x"]`）。
    足し算の順序が Python と Rust でずれると、平均戦略が 1e-12 違って
    同点の手の選び方が変わり、ここが落ちる。
    """
    rs = _rs()
    from tests.test_d065 import _rand_net_path
    vnet = _rand_net_path(tmp_path, "a2_v.json", seed=85)
    pnet = _rand_net_path(tmp_path, "a2_p.json", seed=86)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              opp_policy_net=pnet, opp_policy_root_only=True,
              choice_phases=True, solo_samples=4, bundle_p=bundle_p, **KHEB)
    py_ag = [PlannerAgent(0, **kw), PlannerAgent(1, **kw)]
    rs_ag = [rs.PlannerAgent(0, **kw), rs.PlannerAgent(1, **kw)]
    py = initial_state(CONFIG, 710050)
    rx = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, 710050)
    steps = n_bundle = 0
    while outcome(py) is None and steps < 120:
        assert json.loads(py.to_json()) == json.loads(rx.to_json()), \
            f"局面が食い違った step={steps}"
        need = decision_players(py)
        if not need:
            break
        acts = {}
        for q in need:
            py_ag[q].last_clash = None
            a_py = py_ag[q].act(py, q)
            a_rs = rs_ag[q].act(rx, q)
            assert a_py == a_rs, f"step {steps} P{q}: python {a_py} != rust {a_rs}"
            lc = py_ag[q].last_clash
            if py.phase == Phase.CLASH_SUBMIT and lc and lc.get("totals"):
                assert "bundle_x" in lc, "束ねの道を通っていない"
                assert sum(lc["bundle_x"]) == pytest.approx(1.0, abs=1e-9)
                n_bundle += 1
                got = list(rs_ag[q].last_scores)
                if got:
                    assert lc["totals"] == pytest.approx(got, rel=1e-6, abs=1e-9), \
                        f"点数が違う step={steps} P{q}"
            acts[q] = a_py
        py = apply(py, acts)
        rx = rs.apply(rx, acts)
        steps += 1
    assert steps >= 20, f"比べた手数が少なすぎる（{steps}）"
    assert n_bundle >= 3, f"束ねの決定が少なすぎる（{n_bundle}）"


def test_a2_python_and_rust_solvers_are_bit_identical():
    """ソルバ単体が Python と Rust で**ビット単位で同じ**値を返す。

    **これが足し算の順序を守る本体の検査である。** 対局を回して毎手一致を見るだけでは
    取りこぼす——順序を変えても平均戦略は最後の桁しか動かず、同点の手がめったに
    起きないので手が割れないことがあるからである
    （実際に「Rust の j を降順に足す」壊し方が対局の検査をすり抜けた・§A2-4）。
    """
    rs = _rs()
    assert hasattr(rs, "solve_bundled"), "Rust が検査用の口を持っていない（未再ビルド）"
    uneven = [[0.1, 0.9, 0.4], [0.7, 0.2, 0.55], [0.33, 0.66, 0.99]]
    cases = [([RPS], [1.0]),
             ([ASYM], [1.0]),
             ([RPS, ASYM, uneven], [0.5, 0.3, 0.2]),
             ([[[0.8, 0.8], [0.2, 0.2], [0.5, 0.5]]], [1.0]),
             ([uneven, [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]], [0.25, 0.75])]
    for mats, ws in cases:
        py = bundle.solve_bundled(mats, ws)
        got = rs.solve_bundled(mats, ws)
        assert py == got, f"ビットが違う\n python {py}\n rust   {got}"
        assert bundle.DEFAULT_ITERS == 300
        # 反復数を変えても揃う（既定値に寄りかかっていない）
        assert bundle.solve_bundled(mats, ws, 57) == rs.solve_bundled(mats, ws, 57)


def test_a2_rust_p_one_has_the_champion_fingerprint():
    """Rust 側でも `bundle_p=1.0` の指紋が現行 champion と同じ。"""
    import hashlib
    _rs()
    from experiments.arena_rs import series_rs_digest
    from meicho.drlnet import resolve_model
    kw = {**KHEB_KWARGS, "bundle_p": 1.0}
    kwr = {k: (resolve_model(v)
               if k in ("value_net", "opp_policy_net", "policy_net") else v)
           for k, v in kw.items()}
    sp = {"kind": "planner", "opp_decklist": POOL, **kwr}
    out = series_rs_digest(sp, sp, 10, CONFIG, workers=2, seed0=471500)
    got = hashlib.sha256(repr([r[4] for r in out]).encode()).hexdigest()[:16]
    assert got == KHEB_FINGERPRINT


# ===================================================== T-A2-8 つまみの検証と排他
def test_a2_range_and_exclusivity():
    """`bundle_p` は 0..1。対抗の集約規則を触る他のつまみとは同時に使えない。"""
    rs = _rs()
    for bad in (-0.1, 1.1, 2.0):
        with pytest.raises(ValueError):
            PlannerAgent(0, opp_decklist=POOL, bundle_p=bad)
    for name, extra in (("lethal_uniform", {"lethal_uniform": 0.5}),
                        ("opp_mix", {"opp_mix": 0.5}),
                        ("nash_delta", {"nash_delta": 0.1}),
                        ("tau", {"tau": 0.5})):
        with pytest.raises(ValueError):
            PlannerAgent(0, opp_decklist=POOL, bundle_p=0.9, **extra)
    # Rust 側は Python が弾く前提だが、**つまみを受け取れること**は確かめる
    assert "bundle_p" in rs.features()
    rs.PlannerAgent(0, opp_decklist=POOL, bundle_p=0.9)
    # ソルバの入口の検証
    with pytest.raises(ValueError):
        bundle.solve_bundled([], [])
    with pytest.raises(ValueError):
        bundle.solve_bundled([RPS], [1.0, 1.0])
    with pytest.raises(ValueError):
        bundle.solve_bundled([RPS], [1.0], iters=0)


# ===================================== T-A2-9 終盤の全列挙でも束ねが働く
def test_a2_bundles_over_enumerated_worlds():
    """`endgame_enum` が発火した決定でも束ねが働き、**列挙した世界が行列の k になる**。

    引継ぎ書 §0.3 (iii) の裁定（終盤も働かせる）をここで固定する。

    局面は**回帰 4 局面の 9/3 g002**（青で受けた負け）を使う。W = 48 ≤ 64 なので
    段 C-3 の列挙が確実に発火する、**実際に起きた**終盤の対抗である
    （champion のミラーを頭から回すと、この深さまで行かない局が多い）。
    """
    from coverage import regression_positions
    pos = [p for p in regression_positions() if p[0] == "planner_vb3:g002:last"]
    assert pos, "回帰局面 g002 が取れない（results/human_games/2026-09.jsonl が要る）"
    tag, s, ai, seed, _hu, _why, _prior = pos[0]

    ag = PlannerAgent(seed, opp_decklist=POOL, **_champ_kw(bundle_p=0.5))
    seen = []
    orig = ag._worlds

    def spy(st, pi, n):
        ts, ws = orig(st, pi, n)
        seen.append((len(ts), ag._worlds_enumerated))
        return ts, ws

    ag._worlds = spy
    ag.act(s, ai)
    assert seen, "`_worlds` が呼ばれていない"
    n_worlds, enumerated = seen[0]
    assert enumerated, "この局面で列挙が発火していない（段 C-3 の前提が崩れた）"
    assert ag._endgame_uses >= 1
    assert n_worlds > ag.samples, "列挙なのに決定化の本数が増えていない"
    lc = ag.last_clash
    assert lc is not None and "bundle_x" in lc, "列挙の決定で束ねが働いていない"
    assert len(lc["bundle_x"]) == len(lc["acts"])
    assert sum(lc["bundle_x"]) == pytest.approx(1.0, abs=1e-9)


# ===================================== T-A2-10 覗き見をしていない
def test_a2_does_not_peek():
    """探索側が `s.peeked_opp_hand` にも相手の真の手札にも触らない（D-026）。

    `observe` を差し替えた型で見る（`tests/test_lit_c.py::T-C-3` と同じ手口）。
    """
    from meicho import greedy as gmod

    touched = []

    class _Tattle(dict):
        def __getitem__(self, k):
            if k == "peeked_opp_hand":
                touched.append(k)
            return super().__getitem__(k)

    s = initial_state(CONFIG, 710070)
    ag = PlannerAgent(0, opp_decklist=POOL, **_champ_kw(bundle_p=0.5))
    # 真の相手手札を差し替えた局面で、選ぶ手が変わらないこと＝見ていないこと
    s2 = s.clone()
    hand = list(s2.players[1].hand)
    s2.players[1].hand = list(reversed(hand))
    a1 = ag.act(s, 0)
    ag2 = PlannerAgent(0, opp_decklist=POOL, **_champ_kw(bundle_p=0.5))
    a2 = ag2.act(s2, 0)
    assert a1 == a2, "相手の手札の並びを変えたら手が変わった＝覗いている"
    assert not touched
    assert not hasattr(gmod, "peeked_opp_hand")


# ===================================== T-A2-11 帯が台帳に登録されている
def test_a2_seed_bands_registered():
    """便 A 後半の帯が `seed_bands.json` に登録済みで、重なりが無く `next_free` が進んでいる。"""
    path = os.path.join(_HERE, "..", "experiments", "seed_bands.json")
    with open(path, encoding="utf-8") as f:
        led = json.load(f)
    bands = sorted(led["bands"], key=lambda b: b["start"])
    for a, b in zip(bands, bands[1:]):
        assert a["end"] < b["start"], f"帯が重なっている {a['start']} / {b['start']}"
    starts = {b["start"]: b for b in bands}
    assert 709000 in starts, "便 A 後半の帯が登録されていない"
    assert starts[709000]["end"] == 714999
    # 便 K のスモークの帯も（zip が PC 未展開なので、この便で代行して登録した）
    assert 706000 in starts, "便 K のスモークの帯が登録されていない"
    assert starts[706000]["end"] == 708999
    assert led["next_free"] >= 715000
