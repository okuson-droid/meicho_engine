"""E-5（D-183 追記 1）の準備の道具の検査: 教材の教師 `netfree_vb`（`netfree_v`＋束ねた対抗ゲーム `bundle_p=0.75`）。

`bundle_p` そのものは便 A 後半（D-082）で Rust・Python に入っており、`tests/test_lit_a2.py` が見る。
ここで見るのは、教材の道具（`record_mix`・`make_s2_schedule`）の教師の名前だけである。

E5-1 `make_s2_schedule.teacher_def("netfree_vb", value_net=…)` の教師の定義を `record_mix.teacher_spec` に通すと、
     NETFREE＋葉の V＋`bundle_p=0.75` の spec になる。これは測定の道具の席 `<V>+bundle_p=0.75`（E-2 の netfree_vb）と同じ
E5-2 既定の教師（`netfree`）と `netfree_v`・`netfree_vp` の定義と spec は従来のまま（`bundle_p` が入らない）。
     `record_mix.NETFREE` の辞書は変わっていない
E5-3 `netfree_vb` で葉の V が無いとき、指紋が違うとき、`tau` と同時に指定したときは止める
E5-4 教師 `netfree_vb` の spec で `series_digest` を回すと、`netfree_v` の spec と打ち方が変わる（口が繋がっている）

検査の対局は 990100..990199（kind=diag・D-183 追記 1 で登録）で回す。
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))
sys.path.insert(0, _HERE)

from test_d065 import CONFIG, POOL, _rand_net_path   # noqa: E402

SEED0 = 990100


def _mods():
    import eval_s3_h2h as H
    import make_s2_schedule as M
    import record_mix as R
    return H, M, R


# ------------------------------------------------------------------ E5-1
def test_netfree_vb_teacher_is_the_measured_seat(tmp_path):
    H, M, R = _mods()
    vnet = _rand_net_path(tmp_path, "e5a.json", seed=91)
    pool = list(POOL)
    t = M.teacher_def("netfree_vb", value_net=vnet)
    assert t["name"] == "netfree_vb" and t["value_net_sha16"] == H.sha16(vnet) and t["tau"] == 0.0
    spec = R.teacher_spec(t, pool, "a", "a")
    assert spec == dict(R.NETFREE, kind="planner", opp_decklist=pool, value_net=os.path.abspath(vnet), bundle_p=0.75)
    assert spec == H._spec(vnet + "+bundle_p=0.75", pool)
    assert R.NETFREE_VB_BUNDLE == 0.75


# ------------------------------------------------------------------ E5-2
def test_old_teachers_unchanged(tmp_path):
    H, M, R = _mods()
    vnet = _rand_net_path(tmp_path, "e5b.json", seed=92)
    pool = list(POOL)
    assert R.NETFREE == {"extra_turns": 1, "choice_phases": True, "solo_samples": 4, "known_hand": True,
                         "endgame_enum": 64, "draw_buckets": 1}
    assert M.teacher_def() == {"name": "netfree", "tau": 0.0}
    assert "bundle_p" not in R.teacher_spec({"name": "netfree"}, pool, "a", "a")
    tv = M.teacher_def("netfree_v", value_net=vnet)
    assert R.teacher_spec(tv, pool, "a", "a") == dict(R.NETFREE, kind="planner", opp_decklist=pool,
                                                     value_net=os.path.abspath(vnet))


# ------------------------------------------------------------------ E5-3
def test_netfree_vb_refusals(tmp_path):
    H, M, R = _mods()
    vnet = _rand_net_path(tmp_path, "e5c.json", seed=93)
    pool = list(POOL)
    t = M.teacher_def("netfree_vb", value_net=vnet)
    for bad in (lambda: M.teacher_def("netfree_vb"),
                lambda: M.teacher_def("netfree_vb", value_net=vnet, tau=0.006),
                lambda: R.teacher_spec({"name": "netfree_vb"}, pool, "a", "a"),
                lambda: R.teacher_spec(dict(t, value_net_sha16="0" * 16), pool, "a", "a"),
                lambda: R.teacher_spec(dict(t, tau=0.006), pool, "a", "a")):
        with pytest.raises(SystemExit):
            bad()


# ------------------------------------------------------------------ E5-4
@pytest.mark.slow
def test_netfree_vb_teacher_changes_play(tmp_path):
    rs = pytest.importorskip("meicho_rs")
    H, M, R = _mods()
    from arena_rs import PLANNER, ensure_cards
    ensure_cards()
    vnet = _rand_net_path(tmp_path, "e5d.json", seed=94)
    pool = list(POOL)
    opp = PLANNER(pool, **R.NETFREE)

    def dig(teacher):
        spec = R.teacher_spec(M.teacher_def(teacher, value_net=vnet), pool, "SD001", "SD001")
        return [r[4] for r in rs.series_digest(CONFIG.chara_decks, CONFIG.action_decks, spec, opp, SEED0, 4, 2, 200, True)]
    assert dig("netfree_vb") != dig("netfree_v")
