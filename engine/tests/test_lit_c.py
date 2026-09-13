"""文献計画 便 C（決定化の中身）の検査（`HANDOFF_20260910_LIT_C.md` §4）。

段ごとに足していく。**段の本体より先に書く**のが規約である。

- 段 C-0: T-C-0（由来の host）・T-C-14（被覆率の数え方）・T-C-15（帯）・T-C-17（回帰局面）
- 段 C-1: T-C-1〜4（`known_hand`）
- 段 C-2: T-C-5〜8（π₀ の到達確率の重み）  ← まだ
- 段 C-3: T-C-9〜11（終盤の全列挙）        ← まだ
- 段 C-4: T-C-12〜13（バケット化）         ← まだ
- 段 C-3 で `meicho/worlds.py` に移すときの T-C-16 も同様

**既定の挙動は不変**であることが本便を通しての前提なので、
つまみを足す段では「つまみ 0 で一手一点まで同じ」を必ず先に書く。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, ".."), os.path.join(_HERE, "..", "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import coverage as cov                                            # noqa: E402
import provenance                                                 # noqa: E402


# ===================================================== T-C-0 由来の host
def test_host_name_accepts_cowork_and_rejects_typos(monkeypatch):
    """D-076 判断 5: クラウドの作業機 `cowork-2` を名乗れる。知らない名前は拒否する。"""
    assert "cowork-2" in provenance.HOSTS
    assert "workenv-2" in provenance.HOSTS
    monkeypatch.delenv("MEICHO_HOST", raising=False)
    assert provenance.host_name() == "workenv-2"          # 既定は据え置き
    monkeypatch.setenv("MEICHO_HOST", "cowork-2")
    assert provenance.host_name() == "cowork-2"
    monkeypatch.setenv("MEICHO_HOST", "cowork2")          # 打ち間違い
    with pytest.raises(ValueError):
        provenance.host_name()


# ===================================================== T-C-14 被覆率の数え方
def test_coverage_harness_counts_true_hand():
    """作り物の決定化で `cov_hand` / `cov_next` / TSSR を正しく数える。

    - 真の手札が全本に入っていれば重みは 1.0 → TSSR = W
    - 一様に W 本の別々の手札を引いていて 1 本だけ当たりなら TSSR = 1.0
    - 多重集合として一致を見る（並び順は関係ない）
    """
    true_hand = ["A", "B", "B"]
    # (1) 全本が真の手札 → 当たり・重み 1.0・TSSR = W
    r = cov.coverage_of_decision([["B", "A", "B"]] * 4, true_hand, w=10)
    assert r["hit_hand"] is True
    assert r["w_true"] == pytest.approx(1.0)
    assert r["tssr"] == pytest.approx(10.0)
    assert r["hit_next"] is None                      # next_card を渡していない

    # (2) 一様に 4 本引いて 1 本だけ当たり・W = 4 → TSSR = 1.0（一様の基準）
    r = cov.coverage_of_decision(
        [["A", "B", "B"], ["A", "A", "B"], ["B", "B", "C"], ["A", "B", "C"]],
        true_hand, w=4)
    assert r["hit_hand"] is True
    assert r["w_true"] == pytest.approx(0.25)
    assert r["tssr"] == pytest.approx(1.0)

    # (3) 1 本も当たらない
    r = cov.coverage_of_decision([["A", "A", "B"], ["B", "B", "C"]],
                                 true_hand, w=100)
    assert r["hit_hand"] is False
    assert r["w_true"] == pytest.approx(0.0)
    assert r["tssr"] == pytest.approx(0.0)

    # (4) cov_next は「その札を含む本があるか」だけ（手札の一致は要らない）
    r = cov.coverage_of_decision([["A", "A", "C"], ["C", "C", "C"]],
                                 true_hand, w=9, next_card="A")
    assert r["hit_hand"] is False and r["hit_next"] is True
    r = cov.coverage_of_decision([["C", "C", "C"]], true_hand, w=9, next_card="A")
    assert r["hit_next"] is False

    # (5) 重みつき（II-8 の道）。正規化してから真の手札の重みを合計する
    r = cov.coverage_of_decision(
        [["A", "B", "B"], ["A", "A", "B"], ["B", "B", "C"]],
        true_hand, w=3, weights=[3.0, 1.0, 2.0])
    assert r["w_true"] == pytest.approx(0.5)
    assert r["tssr"] == pytest.approx(1.5)
    # 重みが全部 0 なら等重みに落ちる（0 除算で落とさない）
    r = cov.coverage_of_decision([["A", "B", "B"], ["A", "A", "B"]],
                                 true_hand, w=2, weights=[0.0, 0.0])
    assert r["w_true"] == pytest.approx(0.5)
    # 本数が合わない重みは拒否する
    with pytest.raises(ValueError):
        cov.coverage_of_decision([["A", "B", "B"]], true_hand, w=2, weights=[1.0, 1.0])

    # (6) 1 本も引いていない決定は None（0 と区別する）
    r = cov.coverage_of_decision([], true_hand, w=5)
    assert r["hit_hand"] is None and r["tssr"] is None


def test_coverage_shadow_does_not_change_play():
    """被覆率ハーネスを通した対局が、素の champion ミラーと**一手も変わらない**。

    影のエージェントが自分の乱数で決定化するので、実際に打つ側の乱数は消費されない。
    ここでは同じシードの 1 局を `diag_pimc`（打ち方を変えない診断・既に固定済み）と
    突き合わせ、ターン数・手数・勝敗が一致することで確かめる。
    """
    import diag_pimc
    from peek_counter import resolved_kwargs
    kw = resolved_kwargs("SD001")
    seed = 680499                                   # §5 の被覆率ハーネスの帯の末尾
    _, mine = cov._one(("SD001", kw, {}, seed, 200, (4,)))
    _, theirs = diag_pimc._one(("SD001", kw, seed, 200))
    assert mine["T"] == theirs["T"], "ターン数が変わった＝影が乱数を食っている"
    assert mine["steps"] == theirs["steps"], "手数が変わった＝影が乱数を食っている"
    assert mine["aborted"] == theirs["aborted"]


# ===================================================== T-C-15 帯
def test_seed_bands_lit_c_registered():
    """帯 676000..705999 が台帳にあり、重なりが無い。`next_free` が 706000。"""
    path = os.path.join(_HERE, "..", "experiments", "seed_bands.json")
    d = json.load(open(path, encoding="utf-8"))
    bands = d["bands"]
    want = [(676000, 681999), (682000, 687999), (688000, 693999),
            (694000, 699999), (700000, 705999)]
    have = {(b["start"], b["end"]) for b in bands}
    for w in want:
        assert w in have, f"便 C の帯 {w} が台帳に無い"
    # **便 C が宣言した帯だけ**を見る。書いたときは 676000.. が台帳の末尾だったので
    # 「676000 以上はすべて validate」で書いてあったが、そのあと便 K のスモーク
    # （706000..708999・kind は `smoke`）と便 A 後半（709000..）が足された。
    # 検査の意図は「**便 C の帯が** validate で学習禁止と書いてある」ことなので、
    # そこに読み替える（消さない・便 A 後半 D-082）。
    by_span = {(b["start"], b["end"]): b for b in bands}
    for w in want:
        b = by_span[w]
        assert b["kind"] == "validate", f"{b['start']} が validate でない"
        assert "学習に使用禁止" in b["purpose"]
    assert d["next_free"] >= 706000
    spans = sorted((b["start"], b["end"]) for b in bands)
    for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
        assert e0 < s1, f"帯が重なっている: {s0}..{e0} と {s1}..{e1}"
    # 被覆率ハーネスの帯（全段で共有）が段 C-1 の帯の中に収まっている
    assert 676000 <= cov.BAND[0] and cov.BAND[1] <= 681999


# ===================================================== T-C-17 回帰局面
HUMAN_GAMES = os.path.join(_HERE, "..", "results", "human_games", "2026-09.jsonl")


@pytest.mark.skipif(not os.path.exists(HUMAN_GAMES), reason="対人の記録が無い環境")
def test_regression_positions_match_t14():
    """被覆率ハーネスが拾う回帰局面が、T-14 の 2 局面と**同じ局面**であること。

    `tests/test_d065.py::_human_clash_positions` は「負けを決めた対抗」を返す。
    こちらは `walk_clashes`（相手が実際に出した手も返す）から拾うので経路が違う。
    **経路が違うものが同じ答えを出すことを固定する**（写し間違いの検出）。
    """
    from tests.test_d065 import _human_clash_positions
    want = {gid: (s, ai) for gid, s, ai, _ in _human_clash_positions()}
    got = {tag.split(":")[1]: (s, ai)
           for tag, s, ai, _, _, _, _ in cov.regression_positions()
           if tag.startswith("planner_vb3:") and tag.endswith(":last")}
    assert set(got) == set(want), f"回帰局面の組が違う: {sorted(got)} 対 {sorted(want)}"
    for gid in want:
        s_w, ai_w = want[gid]
        s_g, ai_g = got[gid]
        assert ai_g == ai_w
        assert s_g.turn_no == s_w.turn_no
        assert s_g.players[1 - ai_g].hand == s_w.players[1 - ai_w].hand
        assert s_g.players[ai_g].hand == s_w.players[ai_w].hand


@pytest.mark.skipif(not os.path.exists(HUMAN_GAMES), reason="対人の記録が無い環境")
def test_regression_diagnostic_runs_and_is_deterministic():
    """回帰局面の診断が動き、同じ引数なら同じ答えを返す（決定的）。"""
    from peek_counter import resolved_kwargs
    kw = resolved_kwargs("SD001")
    a = cov.run_regression(kw, {}, ks=(6,))
    b = cov.run_regression(kw, {}, ks=(6,))
    assert len(a["positions"]) == 4, "回帰局面は 9/3 の 2 局面 ＋ 9/8 g001 の T3・T4"
    assert a["positions"] == b["positions"], "同じ引数で答えが揺れている"
    for r in a["positions"]:
        assert r["W"] <= r["W_nokwn"], "hand_known を使うと候補は増えないはず"


# ==================================================== 段 C-1（II-7 (a) known_hand）
import json                                                       # noqa: E402
import random                                                      # noqa: E402
from collections import Counter                                    # noqa: E402

from arena import load_deck, mirror_config                          # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,   # noqa: E402
                           legal_actions, observe, outcome)
from meicho.planner import PlannerAgent                             # noqa: E402
from meicho.state import Phase                                      # noqa: E402

SD001 = load_deck("SD001")
CONFIG = mirror_config(SD001)
POOL = SD001["action_deck"]


def _rs_has_known_hand():
    """入っている Rust が段 C-1 のつまみを知っているか。知らなければ skip。

    **skip は「通った」ではない**——作業環境では `rust/` を作り直せば 0 skip になる。
    """
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()
    if "known_hand" not in rs.features():
        pytest.skip("Rust が便 C 段 C-1 より古い（未再ビルド）。"
                    "作業環境なら engine/rust で maturin build --release")
    return rs


def _state_with_scan(seed0=680400, max_seeds=12, max_steps=400):
    """スキャンが解決して `hand_known` が空でなくなった局面を 1 つ返す。

    見つからなければ skip（カード表が変わって「スキャン」が無くなった環境）。
    """
    kw = {"opp_decklist": POOL}
    for seed in range(seed0, seed0 + max_seeds):
        agents = [PlannerAgent(seed * 2, **kw), PlannerAgent(seed * 2 + 1, **kw)]
        s = initial_state(CONFIG, seed)
        for _ in range(max_steps):
            if outcome(s) is not None:
                break
            need = decision_players(s)
            if not need:
                break
            for pi in need:
                if observe(s, pi)["opp"]["hand_known"]:
                    return s, pi, seed
            s = apply(s, {pi: agents[pi].act(s, pi) for pi in need})
    pytest.skip("スキャンが解決する局面が見つからない")


# ===================================================== T-C-1
def test_known_hand_forced_into_opponent_hand():
    """`known_hand=True` の決定化は、見えている札を**必ず**相手の手札に入れる。

    多重集合として含むこと（同じ札が 2 枚見えていれば 2 枚とも）。
    `hand_known` が空の局面では、同じ乱数状態から従来と同じ手札が出る。
    """
    s, pi, _ = _state_with_scan()
    known = observe(s, pi)["opp"]["hand_known"]
    assert known, "前提が壊れている（見えている札が無い）"
    ag = PlannerAgent(7, opp_decklist=POOL, known_hand=True)
    for _ in range(20):
        hand = Counter(ag._determinize(s, pi).players[1 - pi].hand)
        for cid, n in Counter(known).items():
            assert hand[cid] >= n, f"{cid} が {n} 枚入っていない（{hand[cid]} 枚）"
    # `_sample_opponent` も同じ扱い（直し忘れると天井が過小に出る・便 M §7 の 3 と同じ轍）
    for _ in range(20):
        hand = Counter(ag._sample_opponent(s, pi).players[1 - pi].hand)
        for cid, n in Counter(known).items():
            assert hand[cid] >= n, f"_sample_opponent で {cid} が入っていない"
    # 手札の枚数は公開情報なので変わらない
    assert (len(ag._determinize(s, pi).players[1 - pi].hand)
            == len(s.players[1 - pi].hand))

    # 見えていない局面（配った直後）では、同じ乱数状態から従来と同じ手札が出る
    s0 = initial_state(CONFIG, 680401)
    assert not observe(s0, 0)["opp"]["hand_known"]
    a = PlannerAgent(11, opp_decklist=POOL)
    b = PlannerAgent(11, opp_decklist=POOL, known_hand=True)
    assert (a._determinize(s0, 0).players[1].hand
            == b._determinize(s0, 0).players[1].hand)


# ===================================================== T-C-2
def test_known_hand_default_off_is_bitwise_identical():
    """つまみ 0 では、**スキャンのある局面でも**決定化の結果と乱数の消費が従来と同一。

    ここが崩れると同じシードの対局が変わり、過去に取った勝率が比較できなくなる。
    """
    s, pi, _ = _state_with_scan()
    assert observe(s, pi)["opp"]["hand_known"], "前提が壊れている"
    a = PlannerAgent(23, opp_decklist=POOL)                    # 既定
    b = PlannerAgent(23, opp_decklist=POOL, known_hand=False)  # 明示的に 0
    for _ in range(5):
        ta, tb = a._determinize(s, pi), b._determinize(s, pi)
        assert ta.players[1 - pi].hand == tb.players[1 - pi].hand
        assert ta.players[pi].action_deck == tb.players[pi].action_deck
        assert ta.players[1 - pi].action_deck == tb.players[1 - pi].action_deck
        # 乱数の消費が同じ（次に出る値が一致する）
        assert a.rng.random() == b.rng.random()

    # つまみ 1 でも**乱数の使い方の形は同じ**——`shuffle` を呼ぶ回数が変わらない
    # （自分のデッキで 1 回・相手のプールで 1 回）。
    # ※ `shuffle` が内側で引く乱数の**個数**は列の長さで変わる（Fisher–Yates）。
    #   つまみ 1 では見えている札を抜いたぶんプールが短いので、そこは一致しない。
    #   固定したいのは「余計な抽選を足していない」ことなので、呼び出し回数で見る。
    def count_shuffles(kw):
        ag = PlannerAgent(23, opp_decklist=POOL, **kw)
        n = [0]
        real = ag.rng.shuffle

        def counted(seq):
            n[0] += 1
            return real(seq)
        ag.rng.shuffle = counted
        ag._determinize(s, pi)
        return n[0]
    assert count_shuffles({}) == count_shuffles({"known_hand": True}) == 2, \
        "つまみ 1 で shuffle の呼び出し回数が変わった"

    # 1 局まるごと同じ手（つまみ 0 と既定）
    def play(kw, seed):
        ags = [PlannerAgent(seed * 2, opp_decklist=POOL, **kw),
               PlannerAgent(seed * 2 + 1, opp_decklist=POOL, **kw)]
        st, log = initial_state(CONFIG, seed), []
        while outcome(st) is None and st.turn_no <= 200:
            need = decision_players(st)
            if not need:
                break
            acts = {q: ags[q].act(st, q) for q in need}
            log.append(json.dumps(sorted(acts.items()), sort_keys=True,
                                  default=str))
            st = apply(st, acts)
        return log
    assert play({}, 680402) == play({"known_hand": False}, 680402)


# ===================================================== T-C-3
def test_known_hand_uses_observe_not_state():
    """探索側は `s.peeked_opp_hand` や相手の真の手札を読まず、`observe` の欄だけを見る。

    `observe` を差し替えた偽の局面で、決定化が**差し替えた側**に従うことで確かめる。
    """
    import meicho.greedy as G
    s, pi, _ = _state_with_scan()
    real = observe(s, pi)["opp"]["hand_known"]
    assert real

    # (1) `observe` が「何も見えていない」と言えば、決定化は素の振る舞いに戻る
    def blind(state, q):
        o = observe(state, q)
        if q == pi:
            o["opp"] = dict(o["opp"], hand_known=[])
        return o

    ag = PlannerAgent(31, opp_decklist=POOL, known_hand=True)
    base = PlannerAgent(31, opp_decklist=POOL)
    orig = G.observe
    try:
        G.observe = blind
        got = ag._determinize(s, pi).players[1 - pi].hand
    finally:
        G.observe = orig
    assert got == base._determinize(s, pi).players[1 - pi].hand, \
        "observe を差し替えたのに従っていない（真の手札か peeked を読んでいる）"

    # (2) `observe` が「別の札が見えている」と言えば、決定化はその札を入れる
    unseen = ag._unseen(s, pi)
    fake = [c for c in unseen if c not in real][:1]
    assert fake, "偽の札を作れない（プールが小さすぎる）"

    def lying(state, q):
        o = observe(state, q)
        if q == pi:
            o["opp"] = dict(o["opp"], hand_known=list(fake))
        return o

    ag2 = PlannerAgent(31, opp_decklist=POOL, known_hand=True)
    try:
        G.observe = lying
        hands = [ag2._determinize(s, pi).players[1 - pi].hand for _ in range(10)]
    finally:
        G.observe = orig
    assert all(fake[0] in h for h in hands), "偽の hand_known に従っていない"

    # (3) 覗き見監査（D-026）: 候補で違反 0
    from meicho.audit import replay_audit
    res = replay_audit(
        lambda sd: PlannerAgent(sd, opp_decklist=POOL, known_hand=True),
        lambda sd: PlannerAgent(sd, opp_decklist=POOL),
        CONFIG, POOL, n_games=2, variants=2, node_cap=40, seed0=703600)
    assert res["violations"] == 0, res["examples"]
    assert res["checked"] >= 20, res


# ===================================================== T-C-4
def test_rust_has_peeked_and_matches_python(tmp_path):
    """Rust の状態に `peeked_opp_hand` があり、`known_hand=True` で毎手一致（点数まで）。

    **引継ぎ書 §0.3 (x) の前提は誤りだった**——Rust の `GameState` には
    `peeked_opp_hand` が最初から在り、スキャンの効果で埋まり、JSON にも出ている。
    段 C-1 で足したのは決定化の分岐だけである。
    """
    rs = _rs_has_known_hand()
    s, pi, seed = _state_with_scan()
    # (1) 欄が在り、JSON に出ている
    rss = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, seed)
    assert "peeked_opp_hand" in json.loads(rss.to_json())

    # (2) 毎手一致（手と点数）。乱数ネットを積んで champion と同じ道を通す
    from tests.test_d065 import _rand_net_path
    vnet = _rand_net_path(tmp_path, "c1_v.json", seed=81)
    pnet = _rand_net_path(tmp_path, "c1_p.json", seed=82)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              opp_policy_net=pnet, opp_policy_root_only=True, known_hand=True)
    py_agents = [PlannerAgent(0, **kw), PlannerAgent(1, **kw)]
    rs_agents = [rs.PlannerAgent(0, **kw), rs.PlannerAgent(1, **kw)]
    # スキャンが解決する局まで進む種を選んである（680405 は 44 手目で `hand_known` が立つ）。
    py = initial_state(CONFIG, 680405)
    rsx = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, 680405)
    steps = seen_scan = 0
    while outcome(py) is None and steps < 70:
        assert json.loads(py.to_json()) == json.loads(rsx.to_json()), \
            f"局面が食い違った step={steps}"
        need = decision_players(py)
        if not need:
            break
        acts = {}
        for q in need:
            if observe(py, q)["opp"]["hand_known"]:
                seen_scan += 1
            py_agents[q].last_clash = None       # 前の対抗の記録を持ち越さない
            a_py = py_agents[q].act(py, q)
            a_rs = rs_agents[q].act(rsx, q)
            assert a_py == a_rs, f"step {steps} P{q}: python {a_py} != rust {a_rs}"
            lc = py_agents[q].last_clash
            if py.phase == Phase.CLASH_SUBMIT and lc and lc.get("totals"):
                got = list(rs_agents[q].last_scores)
                if got:
                    # 完全一致にはしない——ネットの推論だけは Python(numpy) と
                    # Rust(f32) で最後の桁が揺れる（便 A の T-A2 と同じ許容）。
                    assert lc["totals"] == pytest.approx(got, rel=1e-6, abs=1e-9), \
                        f"点数が違う step={steps} P{q}"
            acts[q] = a_py
        py = apply(py, acts)
        rsx = rs.apply(rsx, acts)
        steps += 1
    assert steps >= 20, f"比べた手数が少なすぎる（{steps}）"
    assert seen_scan > 0, "スキャンの情報がある決定を 1 つも通っていない（検査が空回り）"


def test_known_hand_rust_defaults_unchanged():
    """Rust 側もつまみ 0 で digest が不変（既定の挙動は 1 ビットも変わらない）。"""
    _rs_has_known_hand()
    from experiments.arena_rs import PLANNER, series_rs_digest
    from meicho.drl_data import BASELINE_DIGESTS_230000
    out = series_rs_digest(PLANNER(POOL), PLANNER(POOL), 6, CONFIG, workers=2,
                           seed0=230000)
    assert [r[4] for r in out] == BASELINE_DIGESTS_230000
    # 既定の引数が spec に漏れていないこと（`known_hand` を足しても spec は空のまま）
    assert PLANNER(POOL) == {"kind": "planner", "opp_decklist": POOL}
    assert PlannerAgent(0, opp_decklist=POOL).known_hand is False


# ============================================== 段 C-2（II-8 π₀ の到達確率の重み）
KHW = {"known_hand": True, "world_weight": 0.75}


def _rs_has_world_weight():
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()
    if "world_weight" not in rs.features():
        pytest.skip("Rust が便 C 段 C-2 より古い（未再ビルド）")
    return rs


# **便 C 以降に足されたつまみ。この一覧から外れたものが「便 C 以前の探索器」である。**
# 便 C の階段の 5 つに加え、**便 A 後半の `bundle_p`**（2026-09-13 の交代で champion が
# 持つようになった・D-082 追記 2）もここに入る。
# **次の便でつまみが増えたら、ここに足すこと。**足し忘れは `_pre_bin_c_kwargs` が捕まえる。
_BIN_C_KNOBS = ("known_hand", "world_weight", "weight_temp", "endgame_enum", "draw_buckets",
                "bundle_p")

# **便 C 以前の探索器（＝`planner_vc4cps`）の明示の固定。**
# 「現 champion から便 C 以降のつまみを引いたもの」は交代のたびに中身が変わりうるので、
# **引いた結果がこれと 1 文字も違わないこと**を毎回確かめる。
# ★この形にしたのは、2026-09-13 の交代で `bundle_p` が引き算から漏れ、
# `test_worlds_module_matches_diag_pimc` が「70 行目の phase が違う」で落ちたためである
# （便 M の記録を**別の探索器で**回し直していた）。**黙って土台が変わるほうが検査の失敗より怖い。**
_PRE_BIN_C_KWARGS = {"extra_turns": 1,
                     "value_net": "drl_sd001_vc4.json",
                     "opp_policy_net": "drl_sd001_s1.json",
                     "opp_policy_root_only": True,
                     "choice_phases": True,
                     "solo_samples": 4,
                     "policy_net": "pi_small64_e10.json",
                     "policy_scope": "proxy"}


def _pre_bin_c_kwargs() -> dict:
    """便 C 以前の探索器の kwargs（モデル名は実ファイルのパスに直したもの）。

    現 champion から `_BIN_C_KNOBS` を引き、**引いた結果が `_PRE_BIN_C_KWARGS` と
    完全に一致することを確かめてから**返す。一致しなければ、champion に新しいつまみが
    増えたのに一覧へ足していないということなので、**そこで止める**。
    """
    import champion as chmod
    from meicho.drlnet import resolve_model
    raw = {k: v for k, v in chmod.kwargs_for("SD001").items() if k not in _BIN_C_KNOBS}
    extra = sorted(set(raw) - set(_PRE_BIN_C_KWARGS))
    assert raw == _PRE_BIN_C_KWARGS, (
        "便 C 以前の探索器が復元できない。champion に増えたつまみを `_BIN_C_KNOBS` に"
        f"足し忘れていないか: 余分 {extra}／不足 {sorted(set(_PRE_BIN_C_KWARGS) - set(raw))}")
    return {k: (resolve_model(v) if k in ("value_net", "opp_policy_net", "policy_net") else v)
            for k, v in raw.items()}


def _champ_kw(**extra):
    """**便 C の階段の土台**（＝つまみを 1 つも入れていない探索器）の kwargs。

    もとは「現 champion の kwargs」をそのまま返していた。便 C の交代（2026-09-11・
    D-081 追記 1）で **champion 自身が `known_hand` / `endgame_enum` / `draw_buckets` を
    持つようになった**ので、そのままでは「つまみ 0 の既定」を測る検査が土台から壊れる
    （`test_*_default_off_is_bitwise_identical` が「既定でつまみが入っている」と言って落ちる）。

    そこで**便 C のつまみだけを外す**。外す対象を定数で列挙してあるのは、
    次に階段でつまみが増えたとき意識して足すためである。V や π₀ や代打ちは外さない
    ——土台は「そのときの champion の探索器から、便 C のつまみを抜いたもの」でよい。
    """
    return {**_pre_bin_c_kwargs(), "opp_decklist": POOL, **extra}


def _agent_with_history(seed=680420, max_steps=400, want_submit=False, **extra):
    """履歴がたまった状態のエージェントと、そのときの局面を返す。

    `want_submit=True` なら「相手が**札を出した**回」が履歴に入るまで進める
    （パスの回だけでは「その札を持つ世界」を作れず、比を見る検査ができない）。
    """
    kw = _champ_kw(**{**KHW, **extra})
    ags = [PlannerAgent(seed * 2, **kw), PlannerAgent(seed * 2 + 1, **kw)]
    s = initial_state(CONFIG, seed)
    for _ in range(max_steps):
        if outcome(s) is not None:
            break
        need = decision_players(s)
        if not need:
            break
        acts = {q: ags[q].act(s, q) for q in need}
        s = apply(s, acts)
        for q in (0, 1):
            h = ags[q]._opp_history
            if h and (not want_submit or any(c is not None for _, c, _ in h)):
                return ags[q], s, q
    pytest.skip("履歴がたまる局面が見つからない")


# ===================================================== T-C-5
def test_world_weight_never_zero():
    """floor ε と一様分 u により、**どの本の重みも 0 にならない**（消去ではなく重み付け）。

    下限は「一様分の取り分」u/K である（`_worlds` は合計を K に揃えて返すので u）。
    """
    ag, s, pi = _agent_with_history(want_submit=True)
    hit = [h for h in ag._opp_history if h[1] is not None]
    assert hit, "前提が壊れている（相手が札を出した回が無い）"
    cid = hit[-1][1]

    # 履歴を「相手が札を出した回」1 件に絞る。
    # **パスの回は別の意味を持つ**——相手が出せる札を持っている世界では「パスした」は
    # ありえないので η がちょうど 0 になり、全部の世界が 0 になると一様に落ちる
    # （下の `test_world_weight_falls_back_to_uniform` がその道を固定する）。
    ag._opp_history = hit[-1:]

    # **いちばん厳しい場合を手で作る**: 出した札を持っている世界と、持っていない世界。
    # 持っていない世界の η はちょうど 0 になるので、floor と一様分が無ければ重みも 0 になる。
    pool = sorted(set(ag._unseen(s, pi)))
    other = [c for c in pool if c != cid][:3]
    assert len(other) == 3
    hands = [[cid] + other[:2], list(other), [cid] + other[1:], list(other)]
    ws = ag.world_weights_for(s, pi, hands)
    k = len(hands)
    u = 1.0 - ag.world_weight
    assert abs(sum(ws) - 1.0) < 1e-9, "重みの合計が 1 でない"
    for w in ws:
        assert w >= u / k - 1e-12, f"重みが一様分の下限 u/K を下回った: {w}"
        assert w > 0.0, "重みが 0 になった（消去してしまっている）"
    assert max(ws) > min(ws) + 1e-9, "重みが全部同じ（π₀ が効いていない）"
    # 出した札を持つ世界の方が重い
    assert ws[0] > ws[1] and ws[2] > ws[3]

    # 実際の決定でも下限を割らない（`_worlds` は合計を本数に揃えて返す）
    _, ws2 = ag._worlds(s, pi, 6)
    assert abs(sum(ws2) - 6) < 1e-9
    for w in ws2:
        assert w >= u - 1e-12 and w > 0.0


# ===================================================== T-C-6
def test_world_weight_reach_probability_hand_made():
    """手で作った 2 つの世界で、η の比が p_{T,ε} の比に一致する。T→大 で一様に近づく。"""
    ag, s, pi = _agent_with_history(want_submit=True)
    hit = [h for h in ag._opp_history if h[1] is not None]
    assert hit, "前提が壊れている（相手が札を出した回が無い）"
    frame, cid, before = hit[-1]
    # 相手が出した札を含む世界と、含まない世界
    pool = sorted(set(ag._unseen(s, pi)))
    n_hand = 3
    other = [c for c in pool if c != cid][:n_hand]
    assert len(other) == n_hand
    hand_with = [cid] + other[:n_hand - 1]
    hand_without = other
    p_with = ag._reach_prob(frame, pi, hand_with, cid)
    p_without = ag._reach_prob(frame, pi, hand_without, cid)
    assert 0.0 < p_with <= 1.0
    # その札を持っていない世界では「その札を出した」確率はちょうど 0
    assert p_without == 0.0, "持っていない札を出せることになっている"

    # 温度を上げると一様に近づく（同じ手札・同じ札で比べる）
    hot = PlannerAgent(1, **_champ_kw(**KHW, weight_temp=1000.0))
    hot._opp_history = list(ag._opp_history)
    cold = PlannerAgent(1, **_champ_kw(**KHW, weight_temp=0.05))
    cold._opp_history = list(ag._opp_history)
    from meicho.engine import legal_actions
    u = frame.clone()
    u.players[1 - pi].hand = list(hand_with)
    n_acts = len(legal_actions(u, 1 - pi))
    if n_acts <= 1:
        pytest.skip("合法手が 1 つしかない（温度の効きが見えない）")
    p_hot = hot._reach_prob(frame, pi, hand_with, cid)
    p_cold = cold._reach_prob(frame, pi, hand_with, cid)
    assert abs(p_hot - 1.0 / n_acts) < 0.02, f"T→大 で一様に近づかない（{p_hot}）"
    assert abs(p_hot - 1.0 / n_acts) < abs(p_cold - 1.0 / n_acts)

    # floor: ε を 1.0 にすると完全に一様（π₀ を見ない）
    flat = PlannerAgent(1, **_champ_kw(**KHW, weight_floor=1.0))
    flat._opp_history = list(ag._opp_history)
    assert abs(flat._reach_prob(frame, pi, hand_with, cid) - 1.0 / n_acts) < 1e-9


# ===================================================== T-C-7
def test_world_weight_history_is_public_only():
    """履歴に積むのは**公開局面と提出札だけ**（相手の手札・山札の中身を含まない）。"""
    ag, s, pi = _agent_with_history()
    assert ag._opp_history
    for frame, cid, before in ag._opp_history:
        opp = frame.players[1 - pi]
        assert opp.hand == [], "履歴に相手の手札が残っている"
        # 山札は**枚数だけ**（中身は同じ札で埋めてある＝情報を持たない）
        assert len(set(opp.action_deck)) <= 1, "履歴に相手の山札の中身が残っている"
        assert cid is None or isinstance(cid, str)
        assert isinstance(before, Counter)
    # 積むのは「自分が対抗で決めた時点」だけで、件数は lookback で頭打ち
    assert len(ag._opp_history) <= ag.weight_lookback

    # 相手の真の手札を差し替えても履歴の中身は変わらない（＝真の手札を見ていない）
    t = s.clone()
    t.players[1 - pi].hand = list(reversed(t.players[1 - pi].hand))
    ag2, _, _ = _agent_with_history()
    assert [f.to_json() for f, _, _ in ag._opp_history] == \
           [f.to_json() for f, _, _ in ag2._opp_history]

    # 覗き見監査（D-026）: 候補で違反 0
    from meicho.audit import replay_audit
    res = replay_audit(
        lambda sd: PlannerAgent(sd, **_champ_kw(**KHW)),
        lambda sd: PlannerAgent(sd, **_champ_kw()),
        CONFIG, POOL, n_games=2, variants=2, node_cap=30, seed0=703620)
    assert res["violations"] == 0, res["examples"]
    assert res["checked"] >= 15, res


# ===================================================== T-C-8
def test_world_weight_default_off_is_bitwise_identical():
    """つまみ 0 で `_plan` / `_clash` / `_solo` の合計・選ぶ手・乱数消費が従来と同一。"""
    kw = _champ_kw()
    # (1) 重みはちょうど 1.0（掛け算が値を変えない）
    a = PlannerAgent(5, **kw)
    s = initial_state(CONFIG, 680421)
    _, ws = a._worlds(s, 0, 6)
    assert ws == [1.0] * 6, f"つまみ 0 で重みが 1.0 でない: {ws}"
    # 履歴も持たない（つまみ 0 では控えも取らない）
    b = PlannerAgent(5, **kw)
    b._remember_clash(s, 0)
    assert b._pending_clash is None and b._opp_history == []

    # (2) 1 局まるごと同じ手・同じ点数
    def play(extra, seed):
        ags = [PlannerAgent(seed * 2, **{**kw, **extra}),
               PlannerAgent(seed * 2 + 1, **{**kw, **extra})]
        st, log = initial_state(CONFIG, seed), []
        while outcome(st) is None and st.turn_no <= 200:
            need = decision_players(st)
            if not need:
                break
            acts = {}
            for q in need:
                ags[q].last_clash = None
                acts[q] = ags[q].act(st, q)
                lc = ags[q].last_clash
                log.append((q, json.dumps(acts[q], sort_keys=True),
                            None if not lc else [round(v, 12) for v in lc["totals"]]))
            st = apply(st, acts)
        return log
    assert play({}, 680422) == play({"world_weight": 0.0}, 680422)


def test_world_weight_requires_opp_policy_net():
    """π₀ が無い設定では `world_weight` を弾く（黙って等重みに落ちない）。"""
    with pytest.raises(ValueError):
        PlannerAgent(1, opp_decklist=POOL, world_weight=0.5)
    rs = _rs_has_world_weight()
    with pytest.raises(ValueError):
        rs.PlannerAgent(1, opp_decklist=POOL, world_weight=0.5)


def test_world_weight_python_matches_rust(tmp_path):
    """`known_hand` ＋ `world_weight` で Python と Rust が毎手一致（点数まで）。"""
    rs = _rs_has_world_weight()
    from tests.test_d065 import _rand_net_path
    vnet = _rand_net_path(tmp_path, "c2_v.json", seed=81)
    pnet = _rand_net_path(tmp_path, "c2_p.json", seed=82)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              opp_policy_net=pnet, opp_policy_root_only=True, **KHW)
    py_agents = [PlannerAgent(0, **kw), PlannerAgent(1, **kw)]
    rs_agents = [rs.PlannerAgent(0, **kw), rs.PlannerAgent(1, **kw)]
    py = initial_state(CONFIG, 680405)
    rsx = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, 680405)
    steps = with_hist = 0
    while outcome(py) is None and steps < 70:
        assert json.loads(py.to_json()) == json.loads(rsx.to_json()), \
            f"局面が食い違った step={steps}"
        need = decision_players(py)
        if not need:
            break
        acts = {}
        for q in need:
            if py_agents[q]._opp_history:
                with_hist += 1
            py_agents[q].last_clash = None
            a_py = py_agents[q].act(py, q)
            a_rs = rs_agents[q].act(rsx, q)
            assert a_py == a_rs, f"step {steps} P{q}: python {a_py} != rust {a_rs}"
            lc = py_agents[q].last_clash
            if py.phase == Phase.CLASH_SUBMIT and lc and lc.get("totals"):
                got = list(rs_agents[q].last_scores)
                if got:
                    assert lc["totals"] == pytest.approx(got, rel=1e-6, abs=1e-9), \
                        f"点数が違う step={steps} P{q}"
            acts[q] = a_py
        py = apply(py, acts)
        rsx = rs.apply(rsx, acts)
        steps += 1
    assert steps >= 20, f"比べた手数が少なすぎる（{steps}）"
    assert with_hist > 0, "履歴のある決定を 1 つも通っていない（検査が空回り）"


def test_world_weight_rust_defaults_unchanged():
    """Rust 側もつまみ 0 で digest が不変。"""
    _rs_has_world_weight()
    from experiments.arena_rs import PLANNER, series_rs_digest
    from meicho.drl_data import BASELINE_DIGESTS_230000
    out = series_rs_digest(PLANNER(POOL), PLANNER(POOL), 6, CONFIG, workers=2,
                           seed0=230000)
    assert [r[4] for r in out] == BASELINE_DIGESTS_230000
    assert PlannerAgent(0, opp_decklist=POOL).world_weight == 0.0


def test_world_weight_falls_back_to_uniform():
    """どの世界も「ありえない」と出たときは**等重みに落ちる**（0 除算で落ちない）。

    相手が**パスした**回は「出せる札を持っていなかった」という強い観測である。
    出せる札を持たせた世界ではパスの確率がちょうど 0 になるので、
    そういう世界しか無ければ η は全部 0 になる。そこで一様に戻す。
    """
    ag, s, pi = _agent_with_history(want_submit=True)
    passes = [h for h in ag._opp_history if h[1] is None]
    if not passes:
        pytest.skip("履歴にパスの回が無い")
    ag._opp_history = passes[-1:]
    pool = sorted(set(ag._unseen(s, pi)))[:3]
    ws = ag.world_weights_for(s, pi, [list(pool), list(pool)])
    assert ws == pytest.approx([0.5, 0.5]), f"等重みに落ちていない: {ws}"


# ============================================== 段 C-3（II-9 終盤の整合世界の全列挙）
KHE = {"known_hand": True, "endgame_enum": 64}


def _rs_has_endgame():
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()
    if "endgame_enum" not in rs.features():
        pytest.skip("Rust が便 C 段 C-3 より古い（未再ビルド）")
    return rs


def _state_where(pred, seed=688000, phase=Phase.ACTION, max_steps=400, what=""):
    """`pred(W)` を満たす決定まで**列挙を切った候補で**進めた局面を返す。

    進めるのは `endgame_enum=0`（段 C-1 の候補そのもの）なので、
    この関数自身が列挙の中身に影響しない。返すのは `(局面, 席, W)`。
    """
    from meicho.worlds import world_counts
    kw = _champ_kw(known_hand=True)
    ags = [PlannerAgent(seed * 2, **kw), PlannerAgent(seed * 2 + 1, **kw)]
    s = initial_state(CONFIG, seed)
    for _ in range(max_steps):
        if outcome(s) is not None:
            break
        need = decision_players(s)
        if not need:
            break
        for pi in sorted(need):
            if phase is not None and s.phase != phase:
                continue
            wc = world_counts(ags[pi]._unseen(s, pi),
                              len(s.players[1 - pi].hand),
                              observe(s, pi)["opp"]["hand_known"])
            if pred(wc["W"]):
                return s, pi, wc["W"]
        s = apply(s, {q: ags[q].act(s, q) for q in need})
    pytest.skip(f"{what or pred} を満たす {phase} の決定が見つからない（seed={seed}）")


def _small_w_state(seed=688000, phase=Phase.ACTION, cap=64, max_steps=400):
    """W（`hand_known` 込み）が 2..`cap` の決定まで進めた局面。"""
    return _state_where(lambda w: 1 < w <= cap, seed, phase, max_steps,
                        what=f"2 ≤ W ≤ {cap}")


# ===================================================== T-C-9
def test_endgame_enumeration_is_exhaustive():
    """列挙が**整合する手札を全部**出し、重みが多重度（物理的な配り方の数）である。

    - 本数は `world_counts` の W と一致する
    - 重みの合計は「その枚数の配り方の総数」＝ C(残り, k) と一致する
    - `known` は必ず全部の手札に入る
    - 実局面では**真の手札が必ず含まれる**（これが II-9 の前提）
    """
    from math import comb
    from meicho.worlds import enumerate_hands, world_counts

    # (1) 手で数えられる小さなプール
    pool = ["a", "a", "b", "c"]
    got = enumerate_hands(pool, 2)
    assert len(got) == world_counts(pool, 2)["W"] == 4
    assert sum(w for _, w in got) == comb(4, 2) == 6
    assert dict((tuple(h), w) for h, w in got) == {
        ("a", "a"): 1.0, ("a", "b"): 2.0, ("a", "c"): 2.0, ("b", "c"): 1.0}
    # 並びは重みの大きい順（同点は手札の並び順）＝ 切っても決定的
    assert [h for h, _ in got][:2] == [["a", "b"], ["a", "c"]]
    assert enumerate_hands(pool, 2, limit=2) == got[:2]

    # (2) 見えている札は必ず入る
    kn = enumerate_hands(pool, 2, known=["b"])
    assert len(kn) == world_counts(pool, 2, ["b"])["W"] == 2
    assert all("b" in h for h, _ in kn)
    assert sum(w for _, w in kn) == comb(3, 1) == 3

    # (3) 実局面: 真の手札が必ず含まれる（`hand_known` 込みで数えても）
    s, pi, w = _small_w_state()
    ag = PlannerAgent(3, **_champ_kw(**KHE))
    unseen = ag._unseen(s, pi)
    known = observe(s, pi)["opp"]["hand_known"]
    hands = enumerate_hands(unseen, len(s.players[1 - pi].hand), known)
    assert len(hands) == w
    true_hand = sorted(s.players[1 - pi].hand)      # 検査だけが見てよい（D-026）
    assert true_hand in [h for h, _ in hands], "真の手札が列挙に無い"
    # 2 回呼んでも同じ（乱数に依らない）
    assert hands == enumerate_hands(unseen, len(s.players[1 - pi].hand), known)


# ===================================================== T-C-10
def test_endgame_off_above_threshold():
    """W > N では従来と一手一点まで同じ。W ≤ N では列挙した本を使う。"""
    from collections import Counter as _C
    kw = _champ_kw(known_hand=True)

    # (1) つまみ 0 は 1 局まるごと同じ手・同じ点数
    def play(extra, seed):
        ags = [PlannerAgent(seed * 2, **{**kw, **extra}),
               PlannerAgent(seed * 2 + 1, **{**kw, **extra})]
        st, log = initial_state(CONFIG, seed), []
        while outcome(st) is None and st.turn_no <= 200:
            need = decision_players(st)
            if not need:
                break
            acts = {}
            for q in need:
                ags[q].last_clash = None
                acts[q] = ags[q].act(st, q)
                lc = ags[q].last_clash
                log.append((q, json.dumps(acts[q], sort_keys=True),
                            None if not lc else [round(v, 12) for v in lc["totals"]]))
            st = apply(st, acts)
        return log
    assert play({}, 688020) == play({"endgame_enum": 0}, 688020)

    # (2) W > N の局面では列挙に入らず、決定化も重みも従来のまま
    s0, q0, w0 = _state_where(lambda w: w > 64, seed=688021, phase=None,
                              what="W > 64")
    a_off = PlannerAgent(7, **kw)
    a_on = PlannerAgent(7, **_champ_kw(**KHE))
    ts_off, ws_off = a_off._worlds(s0, q0, 6)
    ts_on, ws_on = a_on._worlds(s0, q0, 6)
    assert a_on._worlds_enumerated is False
    assert ws_on == ws_off == [1.0] * 6
    assert [t.to_json() for t in ts_on] == [t.to_json() for t in ts_off]

    # (3) W ≤ N の局面では列挙した本を使う
    s, pi, w = _small_w_state()
    ag = PlannerAgent(9, **_champ_kw(**KHE))
    ts, ws = ag._worlds(s, pi, 6)
    assert ag._worlds_enumerated is True
    assert len(ts) == min(w, ag.endgame_eval)
    assert sum(ws) == pytest.approx(6.0), "重みの合計が本数に揃っていない"
    known = _C(observe(s, pi)["opp"]["hand_known"])
    unseen = _C(ag._unseen(s, pi))
    seen_hands = set()
    for t in ts:
        h = t.players[1 - pi].hand
        assert len(h) == len(s.players[1 - pi].hand), "手札の枚数が違う"
        assert tuple(sorted(h)) not in seen_hands, "同じ手札が 2 本ある"
        seen_hands.add(tuple(sorted(h)))
        c = _C(h)
        assert all(c[k] >= v for k, v in known.items()), "見えている札が入っていない"
        assert all(v <= unseen[k] for k, v in c.items()), "未公開に無い札が入っている"
    # 真の手札が本の中にある（W ≤ eval なら必ず）
    if w <= ag.endgame_eval:
        assert tuple(sorted(s.players[1 - pi].hand)) in seen_hands


# ===================================================== T-C-11
def test_endgame_confidence_fallback():
    """投票が割れる（C < 0.6）局面で**加重平均の手**に戻る。"""
    found = None
    for seed in (688000, 688001, 688008, 688011, 688002, 688003):
        try:
            s, pi, w = _small_w_state(seed=seed)
        except Exception:
            continue
        ag = PlannerAgent(11, **_champ_kw(**KHE, endgame_conf=0.0))
        acts = legal_actions(s, pi)
        if len(acts) < 2:
            continue
        a_vote = ag._plan(s, pi, acts)
        info = ag._last_endgame
        assert info is not None and info["enumerated"] is True
        assert 0.0 < info["C"] <= 1.0
        # 安全弁を絶対に通さない設定（C は 1.0 を超えられない）＝ 加重平均の道
        ag2 = PlannerAgent(11, **_champ_kw(**KHE, endgame_conf=1.5))
        a_avg = ag2._plan(s, pi, acts)
        assert ag2._last_endgame["used"] is False
        assert ag2._last_endgame["C"] == pytest.approx(info["C"])
        assert a_avg == ag2._last_endgame["avg_move"]
        assert a_vote == info["vote_move"]
        if info["C"] < 0.6 and info["vote_move"] != info["avg_move"]:
            found = (seed, info["C"])
            # しきい値 0.6 の候補は加重平均の側を返す
            ag3 = PlannerAgent(11, **_champ_kw(**KHE))
            assert ag3._plan(s, pi, acts) == info["avg_move"]
            assert ag3._last_endgame["used"] is False
            break
    if found is None:
        pytest.skip("投票が割れる（C < 0.6 かつ手が違う）局面が見つからない")


def test_endgame_python_matches_rust(tmp_path):
    """`known_hand` ＋ `endgame_enum` で Python と Rust が毎手一致（点数まで）。

    列挙に入る決定を必ず 1 回は通ることまで確かめる（＝空回りしていない）。
    """
    rs = _rs_has_endgame()
    from tests.test_d065 import _rand_net_path
    vnet = _rand_net_path(tmp_path, "c3_v.json", seed=83)
    pnet = _rand_net_path(tmp_path, "c3_p.json", seed=84)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              opp_policy_net=pnet, opp_policy_root_only=True, **KHE)
    py_agents = [PlannerAgent(0, **kw), PlannerAgent(1, **kw)]
    rs_agents = [rs.PlannerAgent(0, **kw), rs.PlannerAgent(1, **kw)]
    py = initial_state(CONFIG, 688030)
    rsx = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, 688030)
    steps = 0
    while outcome(py) is None and steps < 120:
        assert json.loads(py.to_json()) == json.loads(rsx.to_json()), \
            f"局面が食い違った step={steps}"
        need = decision_players(py)
        if not need:
            break
        acts = {}
        for q in need:
            py_agents[q].last_clash = None
            a_py = py_agents[q].act(py, q)
            a_rs = rs_agents[q].act(rsx, q)
            assert a_py == a_rs, f"step {steps} P{q}: python {a_py} != rust {a_rs}"
            lc = py_agents[q].last_clash
            if py.phase == Phase.CLASH_SUBMIT and lc and lc.get("totals"):
                got = list(rs_agents[q].last_scores)
                if got:
                    assert lc["totals"] == pytest.approx(got, rel=1e-6, abs=1e-9), \
                        f"点数が違う step={steps} P{q}"
            acts[q] = a_py
        py = apply(py, acts)
        rsx = rs.apply(rsx, acts)
        steps += 1
    assert steps >= 20, f"比べた手数が少なすぎる（{steps}）"
    used = sum(a._endgame_uses for a in py_agents)
    assert used > 0, "列挙に入る決定を 1 つも通っていない（検査が空回り）"


def test_endgame_rust_defaults_unchanged():
    """Rust 側もつまみ 0 で digest が不変。既定は列挙しない。"""
    _rs_has_endgame()
    from experiments.arena_rs import PLANNER, series_rs_digest
    from meicho.drl_data import BASELINE_DIGESTS_230000
    out = series_rs_digest(PLANNER(POOL), PLANNER(POOL), 6, CONFIG, workers=2,
                           seed0=230000)
    assert [r[4] for r in out] == BASELINE_DIGESTS_230000
    a = PlannerAgent(0, opp_decklist=POOL)
    assert (a.endgame_enum, a.endgame_eval, a.endgame_conf) == (0, 16, 0.6)


def test_endgame_requires_opp_decklist():
    """相手のデッキが分からない設定では列挙を弾く（§7 の 14）。"""
    with pytest.raises(ValueError):
        PlannerAgent(1, endgame_enum=64)
    rs = _rs_has_endgame()
    with pytest.raises(ValueError):
        rs.PlannerAgent(1, endgame_enum=64)


# ===================================================== T-C-16
def test_worlds_module_matches_diag_pimc():
    """`meicho/worlds.py` に移した W の数え方が便 M の記録と 1 行も違わない。

    記録（`results/lit/m5m1_pimc.jsonl`）の**先頭 200 行**は帯の頭の 2 局である。
    同じ 2 局を回し直し、W・W_nokwn・H_w（と H_w_nokwn）を突き合わせる。
    """
    path = os.path.join(_HERE, "..", "results", "lit", "m5m1_pimc.jsonl")
    if not os.path.exists(path):
        pytest.skip("便 M の記録が無い環境")
    import diag_pimc
    want = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                want.append(json.loads(line))
            if len(want) >= 200:
                break
    seeds = sorted({r["seed"] for r in want[:200]})[:2]
    # **記録を作った探索器で回し直す。** 便 M の記録は当時の champion（`planner_vc4cps`）の
    # 打ち方でできている。champion につまみが増えると**別の手を選び、別の局面を通り、
    # W も phase も変わる**（便 C の交代のときは 10 行目の W が 4636 と 4516 で食い違い、
    # 便 A 後半の交代のときは 70 行目の phase が CLASH_SUBMIT と ACTION で食い違った）。
    # **これは「W の数え方が変わった」のではなく「回している対局が変わった」**である。
    # `_pre_bin_c_kwargs()` が当時の探索器に戻し、戻せなければそこで止める。
    kw = _pre_bin_c_kwargs()
    got = []
    for sd in seeds:
        rows, _ = diag_pimc._one(("SD001", kw, sd, 200))
        got.extend(rows)
    keys = ("seed", "seat", "turn", "phase", "W", "W_nokwn", "H_w", "H_w_nokwn",
            "n_hand", "pool_size", "known_n")
    n = min(200, len(got))
    assert n >= 100, "回し直した行が少なすぎる"
    for i in range(n):
        for k in keys:
            assert got[i][k] == pytest.approx(want[i][k]) if isinstance(
                want[i][k], float) else got[i][k] == want[i][k], \
                f"{i} 行目の {k} が違う: {got[i][k]} != {want[i][k]}"


# ==================================================== 段 C-4（ドローのバケット化）
KHEB = {"known_hand": True, "endgame_enum": 64, "draw_buckets": 1}


def _rs_has_draw_buckets():
    """入っている Rust が段 C-4 のつまみを知っているか。知らなければ skip。"""
    rs = pytest.importorskip("meicho_rs")
    from experiments.arena_rs import ensure_cards
    ensure_cards()
    if "draw_buckets" not in rs.features():
        pytest.skip("Rust が便 C 段 C-4 より古い（未再ビルド）。"
                    "作業環境なら engine/rust で maturin build --release")
    return rs


# ===================================================== T-C-12
def test_draw_buckets_stratified_and_deterministic():
    """K 本の上位 3 枚のバケットが**層をなす**。同じ乱数状態なら同じ並び。

    層は「コスト帯 {0-1, 2, 3, 4+} × 色 {赤, 緑, 青}」の 12 通り（§0.3 (vii)）。
    層の割り当ては**乱数任せにしない**（乱数任せだとこの検査が落ちる＝わざと壊す先）。
    """
    from meicho.buckets import (N_BUCKETS, bucket_of, cost_band,
                                stratum_plan, strata_present)
    from meicho.cards import ACTION_CARDS, Color

    # (1) バケットの定義（コスト帯 × 色）が表のとおり
    assert N_BUCKETS == 12
    assert [cost_band(c) for c in (0, 1, 2, 3, 4, 7)] == [0, 0, 1, 2, 3, 3]
    for cid, card in ACTION_CARDS.items():
        b = bucket_of(cid)
        assert 0 <= b < N_BUCKETS
        assert b // 3 == cost_band(card.cost)
        assert b % 3 == {Color.RED: 0, Color.GREEN: 1, Color.BLUE: 2}[card.color]

    # (2) 割り当ては決定的で、K 本 × 上位 3 枚を層に散らす
    present = [1, 4, 5, 7]
    plan = [stratum_plan(present, j, 3) for j in range(6)]
    assert plan == [stratum_plan(present, j, 3) for j in range(6)], "決定的でない"
    flat = [b for row in plan for b in row]
    assert set(flat) == set(present), "使われない層がある"
    cnt = Counter(flat)
    assert max(cnt.values()) - min(cnt.values()) <= 1, "層への割り振りが偏っている"

    # (3) 実局面: つまみを立てると上位 3 枚のバケットの散らばりが**設計どおり**になる
    s, pi, _ = _small_w_state(phase=Phase.ACTION)
    ag = PlannerAgent(21, **_champ_kw(**KHEB))
    st = ag.rng.getstate()
    ts, _ = ag._worlds(s, pi, 6)
    decks = [t.players[pi].action_deck for t in ts]
    pres = strata_present(decks[0])
    assert len(pres) >= 2, "この局面ではデッキの層が 1 つしかない（検査にならない）"
    for j, deck in enumerate(decks):
        want = stratum_plan(pres, j, min(3, len(deck)))
        for r, b in enumerate(want):
            # その層の札が位置 r 以降に残っていたなら、必ずそれが置かれている
            if any(bucket_of(c) == b for c in deck[r:]):
                assert bucket_of(deck[r]) == b, \
                    f"{j} 本目の {r} 枚目が層 {b} でない"

    # (4) 同じ乱数状態なら 1 ビットも同じ
    ag.rng.setstate(st)
    ts2, _ = ag._worlds(s, pi, 6)
    assert [t.to_json() for t in ts2] == [t.to_json() for t in ts]

    # (5) 散らばりはつまみ 0 より**悪くならない**（上位 3 枚の層の種類数）
    base = PlannerAgent(21, **_champ_kw(**KHE))
    tb, _ = base._worlds(s, pi, 6)
    def spread(states):
        return len({bucket_of(c) for t in states
                    for c in t.players[pi].action_deck[:3]})
    assert spread(ts) >= spread(tb)


# ===================================================== T-C-13
def test_draw_buckets_default_off_is_bitwise_identical():
    """つまみ 0 で山札の並びと乱数の消費が従来と同一（1 局まるごと・手と点数）。"""
    kw = _champ_kw(**KHE)

    def play(extra, seed):
        ags = [PlannerAgent(seed * 2, **{**kw, **extra}),
               PlannerAgent(seed * 2 + 1, **{**kw, **extra})]
        st, log = initial_state(CONFIG, seed), []
        while outcome(st) is None and st.turn_no <= 200:
            need = decision_players(st)
            if not need:
                break
            acts = {}
            for q in need:
                ags[q].last_clash = None
                acts[q] = ags[q].act(st, q)
                lc = ags[q].last_clash
                log.append((q, json.dumps(acts[q], sort_keys=True),
                            None if not lc else [round(v, 12) for v in lc["totals"]]))
            st = apply(st, acts)
        return log

    assert play({}, 694020) == play({"draw_buckets": 0}, 694020)

    # 決定化 1 本ぶんも、乱数状態まで含めて同じ
    s, pi, _ = _small_w_state(phase=Phase.ACTION)
    a = PlannerAgent(23, **kw)
    b = PlannerAgent(23, **_champ_kw(**KHE, draw_buckets=0))
    ta, tb = a._determinize(s, pi), b._determinize(s, pi)
    assert ta.to_json() == tb.to_json()
    assert a.rng.getstate() == b.rng.getstate(), "乱数の消費が違う"

    # つまみ 1 は**並べ替えるだけ**——山札の中身（多重集合）も枚数も変わらない。
    # （乱数は 1 本の流れなので、つまみを立てると以降の引きはずれる。それは想定どおり
    #   で、既定不変の約束は「つまみ 0 のとき」にしかかからない。）
    c = PlannerAgent(23, **_champ_kw(**KHEB))
    tc = c._determinize(s, pi)
    assert sorted(tc.players[pi].action_deck) == sorted(ta.players[pi].action_deck)
    assert len(tc.players[1 - pi].hand) == len(ta.players[1 - pi].hand)
    assert len(tc.players[1 - pi].action_deck) == len(ta.players[1 - pi].action_deck)
    # 手札は未公開の候補から作られたままである（層別は山札にしか効かない）
    unseen = Counter(c._unseen(s, pi))
    assert all(v <= unseen[k] for k, v in Counter(tc.players[1 - pi].hand).items())


# ===================================================== T-C-12/13 の Rust 側
def test_draw_buckets_python_matches_rust(tmp_path):
    """`draw_buckets=1` で Python と Rust が**毎手一致**（手だけでなく点数まで）。"""
    rs = _rs_has_draw_buckets()
    from tests.test_d065 import _rand_net_path
    vnet = _rand_net_path(tmp_path, "c4_v.json", seed=85)
    pnet = _rand_net_path(tmp_path, "c4_p.json", seed=86)
    kw = dict(opp_decklist=POOL, extra_turns=1, value_net=vnet,
              opp_policy_net=pnet, opp_policy_root_only=True, **KHEB)
    py_agents = [PlannerAgent(0, **kw), PlannerAgent(1, **kw)]
    rs_agents = [rs.PlannerAgent(0, **kw), rs.PlannerAgent(1, **kw)]
    py = initial_state(CONFIG, 694030)
    rsx = rs.initial_state(CONFIG.chara_decks, CONFIG.action_decks, 694030)
    steps = 0
    while outcome(py) is None and steps < 120:
        assert json.loads(py.to_json()) == json.loads(rsx.to_json()), \
            f"局面が食い違った step={steps}"
        need = decision_players(py)
        if not need:
            break
        acts = {}
        for q in need:
            py_agents[q].last_clash = None
            a_py = py_agents[q].act(py, q)
            a_rs = rs_agents[q].act(rsx, q)
            assert a_py == a_rs, f"step {steps} P{q}: python {a_py} != rust {a_rs}"
            lc = py_agents[q].last_clash
            if py.phase == Phase.CLASH_SUBMIT and lc and lc.get("totals"):
                got = list(rs_agents[q].last_scores)
                if got:
                    assert lc["totals"] == pytest.approx(got, rel=1e-6, abs=1e-9), \
                        f"点数が違う step={steps} P{q}"
            acts[q] = a_py
        py = apply(py, acts)
        rsx = rs.apply(rsx, acts)
        steps += 1
    assert steps >= 20, f"比べた手数が少なすぎる（{steps}）"


def test_draw_buckets_rust_defaults_unchanged():
    """Rust 側もつまみ 0 が既定で、既定の挙動（digest）は不変。"""
    _rs_has_draw_buckets()
    from experiments.arena_rs import PLANNER, series_rs_digest
    from meicho.drl_data import BASELINE_DIGESTS_230000
    out = series_rs_digest(PLANNER(POOL), PLANNER(POOL), 6, CONFIG, workers=2,
                           seed0=230000)
    assert [r[4] for r in out] == BASELINE_DIGESTS_230000
    assert PlannerAgent(0, opp_decklist=POOL).draw_buckets == 0


# ======================================== champion 交代（D-081 追記 1・2026-09-11）
# 交代した新 champion。**中身を明示して書く**——`champion.py` を動的に読むと、
# 次に交代した瞬間この検査は「そのときの champion の固定」に化けてしまう
# （`tests/test_champion_vc4.py` の T-C4 と同じ流儀）。
KHEB_CHAMPION_KWARGS = {"extra_turns": 1,
                        "value_net": "drl_sd001_vc4.json",
                        "opp_policy_net": "drl_sd001_s1.json",
                        "opp_policy_root_only": True,
                        "choice_phases": True,
                        "solo_samples": 4,
                        "policy_net": "pi_small64_e10.json",
                        "policy_scope": "proxy",
                        "known_hand": True,
                        "endgame_enum": 64,
                        "draw_buckets": 1}
KHEB_CHAMPION_FINGERPRINT = "e82b796960e04c4a"
PREV_CHAMPION_FINGERPRINT = "9b5ad48d2de6a7e0"      # `planner_vc4cps`（一つ前）


def test_kheb_is_the_champion_now():
    """便 C の候補が今の champion の土台のままである（交代したこと自体の固定）。

    2026-09-11 の便 A 後半（D-082 追記 2）で champion は
    `planner_vc4cps_kheb_b75` に交代した。交代で足したのは `bundle_p` **ひとつだけ**
    であり、便 C が決めた 11 個の値は 1 文字も動いていない——ここで見るのはそれである。
    便 C の候補そのものの指紋は `test_kheb_champion_fingerprint` が見る。
    """
    import champion as chmod
    kw = chmod.kwargs_for("SD001")
    assert chmod.name_for("SD001") == "planner_vc4cps_kheb_b75"
    added = set(kw) - set(KHEB_CHAMPION_KWARGS)
    assert added == {"bundle_p"}, "便 C の土台に足されたつまみが `bundle_p` だけではない"
    assert {k: kw[k] for k in KHEB_CHAMPION_KWARGS} == KHEB_CHAMPION_KWARGS


def test_kheb_champion_fingerprint():
    """新 champion の fingerprint。手順は `tests/test_champion_vc4.py` §1 と同じ。

    一つ前の champion（`planner_vc4cps`）の指紋も**変わっていない**ことを合わせて見る
    ——交代で過去の測定の読み直しができなくなるのを防ぐためである。
    """
    _rs_has_draw_buckets()
    from tests.test_champion_vc4 import _fingerprint, NEW_CHAMPION_KWARGS
    assert _fingerprint(KHEB_CHAMPION_KWARGS) == KHEB_CHAMPION_FINGERPRINT
    assert _fingerprint(NEW_CHAMPION_KWARGS) == PREV_CHAMPION_FINGERPRINT


def test_champion_needs_opp_decklist_now():
    """`endgame_enum` を持つ champion は `opp_decklist` 無しでは作れない（起動時に落ちる）。

    これは不具合ではなく仕様である（`greedy.py` が組でしか使わせない）。
    `champion.kwargs_for` を**直に** `PlannerAgent` に渡す道具は `opp_decklist` を
    一緒に渡すこと。`registry.make` は先読み系に既定で入れるので通常は意識しなくてよい。
    """
    import champion as chmod
    kw = _resolve_models(chmod.kwargs_for("SD001"))
    with pytest.raises(ValueError):
        PlannerAgent(0, **kw)
    PlannerAgent(0, opp_decklist=POOL, **kw)        # 組で渡せば作れる


def _resolve_models(kw: dict) -> dict:
    from meicho.drlnet import resolve_model
    return {k: (resolve_model(v) if k in ("value_net", "opp_policy_net", "policy_net")
                else v) for k, v in kw.items()}
