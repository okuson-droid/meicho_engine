"""C-4 恒久評価インフラのテスト（D-034）。ルール裁定ではなく計測基盤の検査。

作業規約6（勝率は n と 95%CI を伴う・シード記録で再現可能）と
D-028（探索と検証のシード帯分離）を機械的に担保する。
"""
import sys, os, json, math, random, copy
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

import pytest

import rating
import ladder
from registry import make, FACTORIES, Mk


# --- レーティング（純粋関数） ----------------------------------------------

def _synth(names, elos, n=400, seed=1):
    """真の Elo から Bradley-Terry に従う勝敗行列を合成する。"""
    rng = random.Random(seed)
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa = 1 / (1 + 10 ** ((elos[b] - elos[a]) / 400))
            w = sum(1 for _ in range(n) if rng.random() < pa)
            pairs.append({"a": a, "b": b, "wins_a": w, "decided": n})
    return pairs


def test_bt_recovers_known_strengths():
    names = ["w", "x", "y", "z"]
    true = {"w": 800, "x": 1000, "y": 1150, "z": 1400}
    est = rating.to_elo(rating.bradley_terry(names, _synth(names, true)), "x", 1000)
    assert sorted(names, key=est.get) == ["w", "x", "y", "z"]
    for n in names:                       # n=400 なら ±60 程度に収まる
        assert abs(est[n] - true[n]) < 60


def test_bt_handles_unequal_n():
    """局数が 10 倍違うペアが混在しても序列は崩れない（MCTS の n_cap を想定）。"""
    names = ["a", "b", "c"]
    true = {"a": 900, "b": 1000, "c": 1200}
    pairs = _synth(names, true, n=500)
    for p in pairs:                       # c を含むペアだけ 50 局に減らす
        if "c" in (p["a"], p["b"]):
            frac = p["wins_a"] / p["decided"]
            p["decided"] = 50
            p["wins_a"] = round(frac * 50)
    est = rating.to_elo(rating.bradley_terry(names, pairs), "b", 1000)
    assert est["a"] < est["b"] < est["c"]


def test_bt_separation_regularized():
    """全勝エージェントがいても発散せず有限値になる（仮想勝敗の効果）。"""
    names = ["r", "h"]
    est = rating.to_elo(rating.bradley_terry(names, [
        {"a": "h", "b": "r", "wins_a": 300, "decided": 300}]), "h", 1000)
    assert math.isfinite(est["r"]) and est["r"] < 1000


def test_bootstrap_deterministic_and_ordered():
    names = ["w", "x", "y"]
    pairs = _synth(names, {"w": 900, "x": 1000, "y": 1100})
    r1 = rating.bootstrap_elo(names, pairs, "x", b=200, seed=7)
    r2 = rating.bootstrap_elo(names, pairs, "x", b=200, seed=7)
    assert r1 == r2                                       # 同入力・同シードで同結果
    for n in names:
        assert r1[n]["lo"] <= r1[n]["elo"] <= r1[n]["hi"]
    assert r1["x"]["lo"] == r1["x"]["hi"] == 1000         # 錨は動かない


def test_cycle_detection():
    names = ["a", "b", "c"]
    cyc = [{"a": "a", "b": "b", "wins_a": 80, "decided": 100},
           {"a": "b", "b": "c", "wins_a": 80, "decided": 100},
           {"a": "c", "b": "a", "wins_a": 80, "decided": 100}]
    assert rating.find_cycles(names, cyc) == [["a", "b", "c"]]
    trans = [{"a": "a", "b": "b", "wins_a": 80, "decided": 100},
             {"a": "b", "b": "c", "wins_a": 80, "decided": 100},
             {"a": "a", "b": "c", "wins_a": 90, "decided": 100}]
    assert rating.find_cycles(names, trans) == []
    # 有意でない差（n が小さい）は辺にならない
    weak = [dict(p, decided=10, wins_a=6) for p in cyc]
    assert rating.find_cycles(names, weak) == []


def test_champion_rule():
    """直接対決の 95% 下限が 0.5 を上回るときだけ候補になる。"""
    ok = [{"a": "champ", "b": "chal", "wins_a": 120, "decided": 300}]     # chal 0.60 ±0.055
    assert [c["agent"] for c in rating.champion_candidates(ok, "champ")] == ["chal"]
    border = [{"a": "chal", "b": "champ", "wins_a": 160, "decided": 300}]  # 0.533 ±0.056
    assert rating.champion_candidates(border, "champ") == []
    small = [{"a": "chal", "b": "champ", "wins_a": 7, "decided": 10}]      # n 不足
    assert rating.champion_candidates(small, "champ") == []


# --- 定義・台帳 -------------------------------------------------------------

def test_seed_bands_no_overlap_and_ladder_registered():
    bands = ladder.load_seed_bands()
    bs = sorted(bands["bands"], key=lambda b: b["start"])
    for x, y in zip(bs, bs[1:]):
        assert x["end"] < y["start"], f"帯が重複: {x} / {y}"
    assert all(b["end"] < bands["next_free"] for b in bs)
    for name in ("core5", "full10"):
        g = ladder.load_gauntlet(name)
        assert ladder.check_seed_band(g["seed_band"], bands)["kind"] == "ladder"
    with pytest.raises(ValueError):       # 探索用の帯はラダーに使えない（D-028）
        ladder.check_seed_band(0, bands)
    with pytest.raises(ValueError):       # 未登録の帯は拒否
        ladder.check_seed_band(bands["next_free"], bands)


def test_gauntlet_hash_stable():
    g = ladder.load_gauntlet("core5")
    reordered = json.loads(json.dumps(dict(reversed(list(g.items())))))
    assert ladder.gauntlet_hash(g) == ladder.gauntlet_hash(reordered)
    changed = json.loads(json.dumps(g))
    changed["n_default"] += 1
    assert ladder.gauntlet_hash(g) != ladder.gauntlet_hash(changed)


def test_registry_builds_every_factory_and_gauntlet_agents():
    pool = ladder.load_deck("SD001")["action_deck"]
    for f in FACTORIES:
        mk = make(f, {}, pool)
        assert isinstance(mk, Mk) and mk(0) is not None
    for name in ("core5", "full10"):
        mks = ladder.build_agents(ladder.load_gauntlet(name))
        for mk in mks.values():
            assert mk(1) is not None
    assert make("heuristic", {"params": {"concerto_target": 3}}, None)(0).p.concerto_target == 3
    with pytest.raises(KeyError):
        make("nope", {}, pool)


def test_pair_n_uses_min_cap():
    g = ladder.load_gauntlet("core5")
    assert ladder.pair_n(g, "planner", "H") == 300
    assert ladder.pair_n(g, "mcts160", "H") == 100
    assert ladder.pair_n(g, "mcts160", "planner", 0.1) == 10


# --- 極小ガントレットの再現性 ------------------------------------------------

TINY = {
    "name": "tiny", "version": 1, "deck": "SD001", "mode": "mirror",
    "seed_band": 80000, "n_default": 6,
    "agents": {"random": {"factory": "random"}, "H": {"factory": "heuristic"},
               "H2": {"factory": "heuristic", "kwargs": {"params": {"concerto_target": 3}}}},
    "anchor": {"agent": "H", "elo": 1000}, "champion": "H",
}


def test_ladder_reproducible_across_workers(tmp_path):
    r1 = ladder.run_gauntlet(TINY, workers=1, verbose=False)
    r2 = ladder.run_gauntlet(TINY, workers=2, verbose=False)
    assert r1["pairs"] == r2["pairs"]                     # workers に依存しない
    assert r1["ratings"] == r2["ratings"]                 # ブートストラップも決定的
    assert r1["gauntlet_hash"] == r2["gauntlet_hash"]
    for p in r1["pairs"]:                                 # 作業規約6: n と CI を伴う
        assert p["seed0"] == 80000 and p["n"] == 6 and "ci" in p
    # 永続化: 追記され、md が描画できる
    path = tmp_path / "ladder.json"
    ladder.append_result(r1, str(path))
    ladder.append_result(r2, str(path))
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 2
    md = ladder.render_md(r1)
    assert "★champion" in md and "勝率行列" in md
    json.dumps(r1)                                        # JSON 直列化可能


# ============================ ラダーの中断・再開（D-065 便 4・2026-09-06）
# ラダーは 66 組・17,600 局あり、作業環境では一度に回しきれない
# （`bash` ツールの上限 600 秒／コンテナは 10 分の無操作で回収される）。
# **組み合わせごとに保存して、同じコマンドで続きから回せる**ようにする。
#
# 組ごとに独立に測れるのは、どの組も同じ `seed0` から始めるからである
# （`run_gauntlet` の中で組の順に依らない）。途中で止めても結果は変わらない。


def test_resume_skips_pairs_already_done(tmp_path):
    """途中まで保存してあれば、その組は**もう一度回さない**。"""
    path = str(tmp_path / "resume.json")
    # 予算 0 秒 = 1 組だけ回して戻る
    r = ladder.run_gauntlet(TINY, workers=1, verbose=False, resume_path=path, budget_sec=0.0)
    assert r is None, "途中なら None を返すこと（結果を確定させない）"
    st = json.loads(open(path, encoding="utf-8").read())
    assert len(st["pairs"]) == 1, f"1 組だけ回るはず: {len(st['pairs'])}"
    first = st["pairs"][0]

    # 続きから: 残りを回して完了する
    r = ladder.run_gauntlet(TINY, workers=1, verbose=False, resume_path=path)
    assert r is not None, "全部そろったら結果を返すこと"
    # 途中保存した組の中身が、そのまま最終結果に入っている（回し直していない）
    same = [p for p in r["pairs"] if p["a"] == first["a"] and p["b"] == first["b"]]
    assert len(same) == 1 and same[0] == first


def test_resume_result_equals_a_single_run(tmp_path):
    """**中断して再開した結果は、一度に回した結果と 1 ビットも変わらない。**

    ここが崩れると「途中で止めると別の答えが出る」ことになり、再開の意味が無くなる。
    """
    whole = ladder.run_gauntlet(TINY, workers=1, verbose=False)
    path = str(tmp_path / "r.json")
    while True:
        part = ladder.run_gauntlet(TINY, workers=1, verbose=False,
                                   resume_path=path, budget_sec=0.0)
        if part is not None:
            break
    assert part["pairs"] == whole["pairs"]
    assert part["ratings"] == whole["ratings"]
    assert part["champion_candidates"] == whole["champion_candidates"]


def test_resume_refuses_a_file_from_a_different_gauntlet(tmp_path):
    """**定義が違う途中経過に混ぜない。** 混ぜると別物の寄せ集めになる。"""
    path = str(tmp_path / "r.json")
    ladder.run_gauntlet(TINY, workers=1, verbose=False, resume_path=path, budget_sec=0.0)
    other = json.loads(json.dumps(TINY))
    other["n_default"] = TINY["n_default"] + 2        # 定義を変える → ハッシュが変わる
    with pytest.raises(SystemExit):
        ladder.run_gauntlet(other, workers=1, verbose=False, resume_path=path)
    # n_scale が違うのも混ぜない（組ごとの局数が変わるため）
    with pytest.raises(SystemExit):
        ladder.run_gauntlet(TINY, workers=1, verbose=False, resume_path=path, n_scale=0.5)


def test_resume_can_stop_in_the_middle_of_a_pair(tmp_path):
    """**1 組の途中でも止まれる**こと（D-065 便 4）。

    組によっては 300 局で 20 分かかる。組の切れ目でしか止まれないと、
    作業環境の上限（`bash` ツール 600 秒）に収まらない組が出てしまう。

    組を塊に割って足し合わせても答えが変わらないのは、`series` が
    **シードごとに独立な対局の合計**だからである（同じシードは同じ対局）。
    """
    whole = ladder.run_gauntlet(TINY, workers=1, verbose=False)
    path = str(tmp_path / "r.json")
    calls = 0
    while True:
        calls += 1
        assert calls < 200, "終わらない（塊の進み方が壊れている）"
        part = ladder.run_gauntlet(TINY, workers=1, verbose=False, resume_path=path,
                                   budget_sec=0.0, block=1)     # 1 局ずつで止める
        if part is not None:
            break
    assert part["pairs"] == whole["pairs"], "塊に割ると答えが変わっている"
    assert part["ratings"] == whole["ratings"]


def test_partial_pair_is_saved(tmp_path):
    """組の途中経過が保存され、そこから続くこと。"""
    path = str(tmp_path / "r.json")
    ladder.run_gauntlet(TINY, workers=1, verbose=False, resume_path=path,
                        budget_sec=0.0, block=1)
    st = json.loads(open(path, encoding="utf-8").read())
    # まだ 1 組も終わっていないが、途中の 1 局ぶんが残っている
    assert st["pairs"] == [] and st.get("partial"), st
    assert st["partial"]["games"] == 1


# ================== ラダーを Rust 版で回す（D-065 便 4・マスター裁定 2026-09-06）
# ラダーは Python 版のエージェントで回っていた（Rust 移植 D-049 より前に作られたため）。
# **実装は毎手一致で固定されている**ので、Rust 版で回しても出る数字は同じである。
# `mcts160` には Rust 版が無いので、その組だけ Python 版のままになる（`engine="auto"`）。


def test_rust_spec_covers_everything_except_mcts():
    """core5 の 11 体のうち、**mcts 以外は Rust 版の仕様に写せる**こと。"""
    g = ladder.load_gauntlet("core5")
    from arena import load_deck
    pool = load_deck(g["deck"])["action_deck"]
    for name, a in g["agents"].items():
        sp = ladder.rust_spec(a["factory"], a.get("kwargs"), pool)
        if a["factory"] == "mcts":
            assert sp is None, "mcts に Rust 版は無い（あると誤解させない）"
        else:
            assert sp is not None and "kind" in sp, f"{name} を写せていない"


def test_rust_spec_resolves_net_paths():
    """ネットの名前は**実ファイルのパスに直してから**渡すこと。

    Rust 側はファイルの置き場所を知らないので、名前のまま渡すと
    「そんなファイルは無い」と言って止まる。
    """
    g = ladder.load_gauntlet("core5")
    from arena import load_deck
    pool = load_deck(g["deck"])["action_deck"]
    sp = ladder.rust_spec("planner_vb", g["agents"]["planner_vb3cps"]["kwargs"], pool)
    for key in ("value_net", "opp_policy_net", "policy_net"):
        assert os.path.sep in sp[key], f"{key} が名前のまま: {sp[key]}"


def test_engine_choice_is_recorded_per_pair(tmp_path):
    """**どの実装で測った組か**を 1 組ずつ記録すること（あとから素性を追えるように）。"""
    r = ladder.run_gauntlet(TINY, workers=1, verbose=False, engine="python")
    assert all(p["engine"] == "python" for p in r["pairs"])


# --- 使い回し（便 C の交代判定・D-077 追記 5） --------------------------------
#
# 前の記録の組をそのまま使う。**同じシードは同じ対局**だから成り立つ仕掛けで、
# 前提が崩れると「別物の寄せ集め」になる。だから (1) 拾う条件を厳しく固定し、
# (2) 抜き取り検査で実際に回し直して突き合わせる——この 2 つを検査で固定する。

def _record(tmp_path, g, **kw):
    """`g` を 1 回回して `ladder.json` 相当のファイルに 1 件だけ書き、そのパスを返す。"""
    rec = ladder.run_gauntlet(g, workers=1, verbose=False, **kw)
    path = str(tmp_path / "ladder.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump([rec], f, ensure_ascii=False)
    return path, rec


def test_reuse_picks_up_only_identical_bodies(tmp_path):
    """拾うのは**体の定義が 1 文字も変わっていない組**だけ。"""
    path, rec = _record(tmp_path, TINY)
    n_pairs = len(rec["pairs"])
    assert n_pairs == 3

    ok, why = ladder.load_reusable(path, -1, TINY, 1.0, TINY["seed_band"])
    assert len(ok) == n_pairs and why["skipped"] == 0
    assert all(p["reused_from"] == rec["run_id"] for p in ok)
    assert ladder.load_reusable(path, rec["run_id"], TINY, 1.0,
                                TINY["seed_band"])[0] == ok          # run_id でも拾える

    # (a) kwargs が変わった体の組は拾わない（H2 の params を変える）
    g2 = copy.deepcopy(TINY)
    g2["agents"]["H2"]["kwargs"] = {"params": {"concerto_target": 4}}
    ok2, why2 = ladder.load_reusable(path, -1, g2, 1.0, TINY["seed_band"])
    assert [(p["a"], p["b"]) for p in ok2] == [("random", "H")]
    assert why2["skipped"] == 2 and "体の定義が違う（または居ない）" in why2["skipped_reasons"]

    # (b) 体が居なくなった組も拾わない
    g3 = copy.deepcopy(TINY)
    del g3["agents"]["H2"]
    ok3, _ = ladder.load_reusable(path, -1, g3, 1.0, TINY["seed_band"])
    assert [(p["a"], p["b"]) for p in ok3] == [("random", "H")]

    # (c) 局数・シード・デッキが違えば拾わない
    assert ladder.load_reusable(path, -1, TINY, 0.5, TINY["seed_band"])[0] == []
    assert ladder.load_reusable(path, -1, TINY, 1.0, TINY["seed_band"] + 1)[0] == []
    g4 = copy.deepcopy(TINY); g4["deck"] = "SD02"
    assert ladder.load_reusable(path, -1, g4, 1.0, TINY["seed_band"])[0] == []

    # (d) 新しい体を足したときは、**古い体どうしの組だけ**が拾える
    g5 = copy.deepcopy(TINY)
    g5["agents"]["H3"] = {"factory": "heuristic", "kwargs": {"params": {"concerto_target": 2}}}
    ok5, _ = ladder.load_reusable(path, -1, g5, 1.0, TINY["seed_band"])
    assert len(ok5) == 3                                   # H3 が絡む 3 組は新しく回す


def test_reuse_gives_the_same_answer_as_running_everything(tmp_path):
    """使い回した結果は、全部回し直した結果と**1 局も違わない**。"""
    path, _ = _record(tmp_path, TINY)
    whole = ladder.run_gauntlet(TINY, workers=1, verbose=False)
    reuse, meta = ladder.load_reusable(path, -1, TINY, 1.0, TINY["seed_band"])
    got = ladder.run_gauntlet(TINY, workers=1, verbose=False,
                              reuse=reuse, reuse_meta=meta)
    key = lambda r: sorted((p["a"], p["b"], p["wins_a"], p["decided"]) for p in r["pairs"])
    assert key(got) == key(whole)
    assert got["ratings"] == whole["ratings"]
    assert got["reused_pairs"] == 3
    assert got["reuse"]["run_id"] == meta["run_id"]


def test_reuse_verify_reruns_and_catches_a_changed_body(tmp_path):
    """抜き取り検査に指定した組は**回し直す**。記録と違えばそこで止まる。"""
    path, rec = _record(tmp_path, TINY)
    reuse, meta = ladder.load_reusable(path, -1, TINY, 1.0, TINY["seed_band"])

    # (1) 指定した組は使い回さず回し直し、一致すれば印がつく
    got = ladder.run_gauntlet(TINY, workers=1, verbose=False, reuse=reuse,
                              reuse_meta=meta, reuse_verify={("random", "H")})
    assert got["reused_pairs"] == 2                        # 3 組のうち 1 組は回し直した
    assert got["reuse_verified_pairs"] == ["random|H"]

    # (2) 記録を書き換えておくと（＝体が変わったのと同じ状況）そこで止まる
    bad = copy.deepcopy(reuse)
    for p in bad:
        if (p["a"], p["b"]) == ("random", "H"):
            p["wins_a"] = p["wins_a"] + 1 if p["wins_a"] < p["decided"] else 0
    with pytest.raises(SystemExit) as e:
        ladder.run_gauntlet(TINY, workers=1, verbose=False, reuse=bad,
                            reuse_meta=meta, reuse_verify={("random", "H")})
    assert "抜き取り検査が合わない" in str(e.value)


def test_reuse_from_requires_reuse_verify(tmp_path):
    """`--reuse-from` を抜き取り検査なしでは使わせない。"""
    with pytest.raises(SystemExit) as e:
        ladder.main(["core5", "--reuse-from", "-1"])
    assert "--reuse-verify" in str(e.value)
    with pytest.raises(SystemExit) as e:
        ladder.main(["core5", "--reuse-verify", "H|greedy"])
    assert "--reuse-from" in str(e.value)
