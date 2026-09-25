# -*- coding: utf-8 -*-
"""公式ルール再照合 A-6 — 回復にライフの上限は無い。

## 何を直すか

v0.17 までの `_heal` は `min(MAX_LIFE, life + amount)` で **20 を上限にクリップ**していた。
根拠は **D-011（2026-08-21 のマスター裁定）**である。ただし D-011 自身が
「rules_draft.md v0.9 は開始ライフ 20 を書いていたが、**上限規定としての条文はなかった**」と
認めており、**公式総合ルールが出る前の、我々の側の補いだった**。

公式 101.6 は「自分のライフを **20 に設定します**」と定めるだけで、**これは開始ライフの規定**である。
回復の上限を定める条文は無い。**2026-09-15 にマスターが「回復上限なし」を確認済み**（D-092 の A-6・R-6）。

したがって **D-011 は覆る**。開始ライフは `STARTING_LIFE`（20）で、上限ではない。同じ値の旧名 `MAX_LIFE` は誤解を呼ぶので消した（D-107）。

## 何が動くか

**SD001 の対局が変わる。**回復するカードは `SD01-023`「奏鳴」（+5）・`BP01-053`（+1）・
`BP01-054`（+1）・`BP01-057`（+1）・`BP01-010`（+1）の 5 枚で、**`SD01-023` は SD001 に入っている**。
ライフ 20 から始まるので、序盤の回復はこれまでほぼ全部上限で削られていた。

準拠版: rules_draft **v0.18** ／ engine v0.1 ／ D-092（R-6）・D-104。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
for _p in (_ROOT, os.path.join(_ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from meicho import engine as E                                   # noqa: E402
from meicho.state import STARTING_LIFE, CharaSlot, GameState, Phase, PlayerState  # noqa: E402


def _state() -> GameState:
    s = GameState(seed=1, players=[PlayerState(), PlayerState()])
    s.turn_no = 3
    s.turn_player = 0
    s.phase = Phase.ACTION
    for pi in (0, 1):
        s.players[pi].action_deck = ["SD01-007"] * 10
        s.players[pi].slots[0] = CharaSlot(stack=["SD01-002"])
    return s


def test_max_life_is_the_starting_life_not_a_cap():
    """開始ライフは 20（公式 101.6）。**上限ではない**ので、旧名 `MAX_LIFE` は消した（D-107）。"""
    import meicho.state as st
    assert STARTING_LIFE == 20
    assert PlayerState().life == STARTING_LIFE
    assert not hasattr(st, "MAX_LIFE"), "上限を思わせる旧名が戻っている（D-107）"


def test_heal_goes_above_the_starting_life():
    """満タンから回復すると 20 を超える（D-011 を覆す）。"""
    s = _state()
    E._heal(s, 0, 5)
    assert s.players[0].life == 25


def test_heal_from_below_is_not_clipped_either():
    """途中からの回復も削られない。18 + 5 = 23。"""
    s = _state()
    s.players[0].life = 18
    E._heal(s, 0, 5)
    assert s.players[0].life == 23


def test_healing_at_full_life_now_counts_and_fires():
    """★満タンでの回復が**実際の回復になる**ので、【自分のライフが回復した時】が誘発する。

    v0.17 までは上限に張り付いていると 0 回復になり、`heals_this_turn` も進まなかった。
    """
    s = _state()
    assert s.players[0].life == 20
    E._heal(s, 0, 1)
    assert s.players[0].life == 21
    assert s.heals_this_turn[0] == 1


def test_zero_and_negative_heal_still_do_nothing():
    """0 以下の回復は従来どおり何も起こさない（誘発もしない）。"""
    s = _state()
    E._heal(s, 0, 0)
    assert s.players[0].life == 20
    assert s.heals_this_turn[0] == 0


def test_life_above_the_start_survives_the_encoding():
    """符号化のライフ欄は 20 を超えても削られない（R-6 の要確認事項の答え）。

    `_c` の範囲は ±127（i8）なので、20 を超えるライフはそのまま入る。
    **ただし学習済みネットはライフ 0〜20 で学んでいる**——範囲外にはならないが、
    分布の外ではある。これは検査ではなく `decisions.md` に残す事柄である。
    """
    from meicho.encode import OBS_DIM, encode
    s = _state()
    s.players[0].life = 25
    vec = encode(E.observe(s, 0), 0)
    assert len(vec) == OBS_DIM
    assert 25 in vec, "ライフ 25 が符号化に見当たらない（削られている）"


def test_the_damage_side_is_unchanged():
    """ダメージ側は触っていない（0 未満にはならず、0 で決着）。"""
    s = _state()
    s.players[0].life = 2
    E._damage(s, 0, 5)
    assert s.players[0].life == 0
    assert s.outcome == 1
