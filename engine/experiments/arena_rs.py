"""Rust 版エンジンで対局列を回す（`arena.series` の高速版・D-049）。

`arena.series` と同じ約束（シードの偶奇で先攻後攻を入れ替える／エージェントの乱数は
先攻が `seed*2`・後攻が `seed*2+1`／引き分け・打ち切りは分母から除く）で、
対局は Rust 内で完結する。`tests/test_rust_agents.py` が Python 版と結果が一致することを固定している。

使い方:

    from experiments.arena_rs import series_rs, PLANNER, HEURISTIC
    r = series_rs(PLANNER(pool), HEURISTIC(), n=600, config=CONFIG, workers=4, seed0=180000)
    print(r)          # 0.883 ±0.026 (n=600) — arena.Result と同じ

エージェントの仕様（`spec`）は dict で、`kind` が種別:
    {"kind": "random"}
    {"kind": "heuristic", "params": {...}}                       # heuristic.Params の項目名
    {"kind": "greedy", "opp_decklist": [...], "weights": {...}, "params": {...}, "samples": 6}
    {"kind": "planner", "opp_decklist": [...], "tuned": True, "plan_samples": 4,
     "race_after": 99, "extra_turns": 0, ...}                    # planner.PlannerAgent の引数名
`extra_turns=1` は D-046 対策A（`LongHorizonPlanner`）に相当する。
`"delta": {...}` を planner に付けると**挑戦者**（champion ＋ δ・発見ループ）になる。δ の種類は
`experiments/discovery.py` の生成器を参照（rush_chara / forbid_levelup / fix_leader / prefer_in_clash /
forbid_in_clash / forbid_in_rush / reserve / always_free_rush / never_free_rush / charge_if_concerto_empty /
levelup_if_hand / no_pass_if_behind / no_switch_until）。

注意:
- Rust 版に無いエージェント（IS-MCTS・学習価値関数 `planner_v` 等）はここでは回せない。
  それらは従来どおり `arena.series` を使う。
- `meicho_rs` が無い環境では ImportError になる。ビルド手順は `RUST_PORT_NOTES.md`。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                   # noqa: E402

from arena import Result                                 # noqa: E402
from meicho.cards_export import cards_json               # noqa: E402
from meicho.engine import GameConfig                     # noqa: E402

_LOADED = False


def ensure_cards() -> None:
    """カード表を Rust 側に渡す（プロセスごとに1回）。真実源は cards.py のまま。"""
    global _LOADED
    if not _LOADED:
        rs.load_cards(cards_json())
        _LOADED = True


# --- 仕様の短縮記法 ----------------------------------------------------------
def RANDOM() -> dict:
    return {"kind": "random"}


def HEURISTIC(params: dict = None) -> dict:
    return {"kind": "heuristic", "params": params}


def GREEDY(opp_decklist: list = None, **kw) -> dict:
    return {"kind": "greedy", "opp_decklist": opp_decklist, **kw}


def PLANNER(opp_decklist: list = None, **kw) -> dict:
    return {"kind": "planner", "opp_decklist": opp_decklist, **kw}


def series_rs(spec_a: dict, spec_b: dict, n: int, config: GameConfig,
              workers: int = 1, seed0: int = 0, max_turns: int = 200) -> Result:
    """A vs B を n 局。戻り値は A から見た勝率（`arena.Result`）。"""
    ensure_cards()
    config.validate()
    out = rs.series(config.chara_decks, config.action_decks, spec_a, spec_b,
                    seed0, n, workers, max_turns)
    decided = [r[0] for r in out if r[0] is not None]
    return Result(sum(1 for w in decided if w), len(decided), n)


def series_rs_detail(spec_a: dict, spec_b: dict, n: int, config: GameConfig,
                     workers: int = 1, seed0: int = 0, max_turns: int = 200) -> list:
    """各局の (a_won | None, turns, steps, fired_a) をシード順に返す（挙動の診断用）。

    `fired_a` は A が挑戦者（`delta` つきの planner）のとき、δ が手に関与した回数。"""
    ensure_cards()
    config.validate()
    return rs.series(config.chara_decks, config.action_decks, spec_a, spec_b,
                     seed0, n, workers, max_turns)


def series_rs_digest(spec_a: dict, spec_b: dict, n: int, config: GameConfig,
                     workers: int = 1, seed0: int = 0, max_turns: int = 200) -> list:
    """各局の (a_won | None, turns, steps, fired_a, digest) を返す（D-053）。

    `digest` は**その局の全決定（誰が・何を選んだか）を畳み込んだハッシュ**。
    同じシード帯・同じ相手で回した 2 つの列の digest が全局一致したら、
    その 2 者は毎手同じ手を選んだ＝**挙動が同じ**である。
    勝敗・ターン数・手数の一致は挙動の一致を意味しないので、選別にはこちらを使う。"""
    ensure_cards()
    config.validate()
    return rs.series_digest(config.chara_decks, config.action_decks, spec_a, spec_b,
                            seed0, n, workers, max_turns)


def gauntlet_rs(spec_a: dict, opponents: dict, n: int, config: GameConfig,
                workers: int = 1, seed0: int = 0) -> dict:
    """固定の相手プールに対する総当たり（`arena.gauntlet` と同じ形）。"""
    per = {name: series_rs(spec_a, spec, n, config, workers, seed0)
           for name, spec in opponents.items()}
    mean = sum(r.p for r in per.values()) / len(per)
    return {"mean": mean, "per": per}
