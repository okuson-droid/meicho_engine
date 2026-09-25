"""段階1C-b（D-123）: 異種デッキの記録入口の検査。

1. 落とし穴の固定: `series` 系は奇数シードで A/B の席を入れ替えるがデッキは席に固定である。
   spec に固定の `opp_decklist` を持たせた**従来の回し方**では、異種デッキ戦の奇数シードで
   相手デッキ表が誤る（正しい表で 1 局ずつ回した参照と digest が食い違う）。
   `opp_from_seat=True` では全局が参照と一致する。
2. 挙動不変: ミラーでは `opp_from_seat` の有無で記録が**バイトまで同じ**。既定（False）は従来どおり。
3. `experiments/record_mix.py`: ミラーのブロックは `drl_record.py` と同じ呼び方の記録とバイトまで同じ。
   manifest の席別の決定数が記録の読み戻し（`drl_data.read_records`）と一致する。
4. 組み合わせ表の検査（champion を異種に使わない・教師以外が相手なら A 席だけ記録・帯の重なり・未登録帯）。

シードは台帳の 824000..824099（段階1C-b の煙試験・学習にも評価にも使用禁止）。
"""
from __future__ import annotations

import json

import pytest

rs = pytest.importorskip("meicho_rs")

from experiments.arena import load_deck, matchup_config, mirror_config          # noqa: E402
from experiments.arena_rs import GREEDY, PLANNER                               # noqa: E402
from meicho.cards_export import cards_json                                     # noqa: E402
from meicho.drl_data import read_records                                       # noqa: E402

SEED0 = 824000


@pytest.fixture(scope="module", autouse=True)
def _load_cards():
    rs.load_cards(cards_json())


def _decks():
    return load_deck("SD001"), load_deck("SD02")


def test_feature_tag_present():
    """入っている wheel が 1C-b を含む（古い wheel で検査が素通りしないように）。"""
    assert "opp_from_seat" in rs.features()


@pytest.mark.parametrize("kind", ["greedy", "planner"])
def test_heterogeneous_opp_decklist_follows_seat(kind):
    """異種デッキ戦で、各エージェントの相手デッキ表が**その局の相手の席のデッキ**になる。

    参照: 1 局ずつ、正しい相手デッキ表を手で入れた spec で回した digest。
    - 偶数シード: A が席 0（SD001）→ A の相手は席 1 の SD02、B の相手は SD001
    - 奇数シード: A が席 1（SD02）→ A の相手は SD001、B の相手は SD02
    """
    d0, d1 = _decks()
    cfg = matchup_config(d0, d1)
    p0, p1 = d0["action_deck"], d1["action_deck"]
    mk = GREEDY if kind == "greedy" else PLANNER
    n = 6
    ref = []
    for s in range(SEED0, SEED0 + n):
        if s % 2 == 0:
            sa, sb = mk(p1), mk(p0)
        else:
            sa, sb = mk(p0), mk(p1)
        ref.append(rs.series_digest(cfg.chara_decks, cfg.action_decks, sa, sb, s, 1, 1, 200)[0][4])
    # 従来の回し方（spec に固定の表・A は「相手は SD02」と思い込む）
    old = [r[4] for r in rs.series_digest(cfg.chara_decks, cfg.action_decks, mk(p1), mk(p0), SEED0, n, 1, 200)]
    # 1C-b（spec の表は何でもよい。ここではわざと自分のデッキを入れておく）
    new = [r[4] for r in rs.series_digest(cfg.chara_decks, cfg.action_decks, mk(p0), mk(p1), SEED0, n, 2, 200,
                                          opp_from_seat=True)]
    assert new == ref
    # 落とし穴そのもの: 偶数シードは一致し、奇数シードで食い違う局がある
    assert all(old[i] == ref[i] for i in range(0, n, 2))
    assert any(old[i] != ref[i] for i in range(1, n, 2)), "奇数シードで相手デッキ表の取り違えが再現しない"


def test_mirror_record_bytes_unchanged(tmp_path):
    """ミラーでは `opp_from_seat` の有無で記録がバイトまで同じ（相手の席のデッキ＝ spec の表）。"""
    d0, _ = _decks()
    cfg = mirror_config(d0)
    pool = d0["action_deck"]
    outs = []
    for flag in (False, True):
        _res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, GREEDY(pool), GREEDY(pool),
                                       SEED0 + 10, 4, str(tmp_path / f"m{int(flag)}"), 1, 200, True, True,
                                       opp_from_seat=flag)
        outs.append(b"".join(open(p, "rb").read() for p in files))
    assert outs[0] == outs[1] and len(outs[0]) > 16


def _run_mix(tmp_path, sch, workers=1):
    from experiments import record_mix
    p = tmp_path / "sch.json"
    p.write_text(json.dumps(sch, ensure_ascii=False), encoding="utf-8")
    return record_mix.main(["--schedule", str(p), "--out", str(tmp_path / "mix"), "--workers", str(workers)])


def test_record_mix_mirror_matches_drl_record(tmp_path):
    """ミラーのブロックは `drl_record.py` の呼び方（固定の表・opp_from_seat なし）とバイトまで同じ。"""
    from experiments import record_mix
    d0, _ = _decks()
    cfg = mirror_config(d0)
    pool = d0["action_deck"]
    seed0, n = SEED0 + 20, 3
    spec = PLANNER(pool, **record_mix.NETFREE)
    _res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, spec, spec, seed0, n,
                                   str(tmp_path / "ref"), 1, 200, True, True)
    ref = b"".join(open(p, "rb").read() for p in files)
    man = _run_mix(tmp_path, {"name": "t", "blocks": [
        {"deck_a": "SD001", "deck_b": "SD001", "seed0": seed0, "n": n}]})
    got = b"".join(open(p, "rb").read() for p in man["files"])
    assert got == ref
    assert man["opp_decklist_known"] is True and man["format"] == "MCDR v3"


def test_record_mix_manifest_counts(tmp_path):
    """異種デッキのブロックと H 相手のブロックで、manifest の数が記録と一致する（§5.4）。"""
    man = _run_mix(tmp_path, {"name": "t", "decks": {"SD02": {"lineage": "starter_b", "group": "SD02",
                                                              "split": "train"}},
                              "blocks": [
                                  {"deck_a": "SD001", "deck_b": "SD02", "seed0": SEED0 + 30, "n": 3,
                                   "p_planned": 0.4},
                                  {"deck_a": "SD02", "deck_b": "SD02", "seed0": SEED0 + 40, "n": 2,
                                   "opponent": "heuristic", "record": "a"}]}, workers=2)
    b0, b1 = man["blocks"]
    assert b0["games"] == {"a_seat0": 2, "a_seat1": 1}          # 824030, 824032 が偶数
    for b in (b0, b1):
        recs = read_records(b["files"])
        assert sum(b["decisions"].values()) == b["decisions_total"] == len(recs.seed)
        # 席ごと（席 0 = deck_a）
        seat0 = int((recs.pi == 0).sum())
        assert b["decisions"]["a_as_deck_a"] + b["decisions"]["b_as_deck_a"] == seat0
    # H 相手のブロックは A 席（教師）だけ記録されている
    assert b1["decisions"]["b_as_deck_a"] == b1["decisions"]["b_as_deck_b"] == 0
    assert b1["decisions_total"] > 0
    decks = man["decks"]
    assert set(decks) == {"SD001", "SD02"}
    assert decks["SD02"]["lineage"] == "starter_b" and decks["SD001"]["lineage"] is None
    assert len(decks["SD001"]["chara_trio"]) == 3 and len(decks["SD001"]["sha256"]) == 64
    # D-129 追記 1: `games` は**そのデッキが出た局数**（ミラーでも 1 局は 1）。席ごとの数は別の欄
    # （`seat_games` = 席 × 局・`seat_games_teacher` = そのうち教師が座った席）。
    # SD02 は異種 3 局＋H 相手のミラー 2 局 = 5 局。席はミラーで 2 つ埋まるので 3 + 2×2 = 7、
    # 教師の席は異種 3 ＋ミラーで A の 2（偶数シードで席 0・奇数で席 1）= 5。
    assert decks["SD02"]["games"] == 3 + 2 and decks["SD001"]["games"] == 3
    assert decks["SD02"]["seat_games"] == 3 + 2 * 2 and decks["SD001"]["seat_games"] == 3
    assert decks["SD02"]["seat_games_teacher"] == 3 + 2 and decks["SD001"]["seat_games_teacher"] == 3
    assert sum(d["games"] for d in decks.values()) >= sum(b["n"] for b in man["blocks"])
    assert man["games_by_opponent"] == {"teacher": 3, "heuristic": 2}
    assert b0["spec_a"]["kind"] == "planner" and b0["nets"] == {}


@pytest.mark.parametrize("block, msg", [
    ({"deck_a": "SD001", "deck_b": "SD02", "seed0": SEED0 + 50, "n": 1, "teacher": {"name": "champion"}},
     "SD001 のミラーだけ"),
    ({"deck_a": "SD001", "deck_b": "SD02", "seed0": SEED0 + 50, "n": 1, "opponent": "greedy", "record": "both"},
     "record を a に"),
    ({"deck_a": "SD001", "deck_b": "SD02", "seed0": 80000, "n": 1}, "評価専用"),
    ({"deck_a": "SD001", "deck_b": "SD02", "seed0": 99_000_000, "n": 1}, "未登録"),
])
def test_schedule_rejects(tmp_path, block, msg):
    with pytest.raises(SystemExit, match=msg):
        _run_mix(tmp_path, {"blocks": [block]})


def test_schedule_rejects_overlap(tmp_path):
    with pytest.raises(SystemExit, match="重なる"):
        _run_mix(tmp_path, {"blocks": [
            {"deck_a": "SD001", "deck_b": "SD02", "seed0": SEED0 + 60, "n": 5},
            {"deck_a": "SD02", "deck_b": "SD001", "seed0": SEED0 + 64, "n": 2}]})
