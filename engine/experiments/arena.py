"""共通の対戦計測基盤（レビュー 2026-08-23 §6 C-4 の先取り）。

すべてのエージェント比較を同一の物差しで測るための土台。以後の実験は
自前で対戦ループを書かず、ここの `series` / `gauntlet` を使うこと。

不変条件（作業規約6 / D-006）:
- シードは 0..n-1 の決定的使用。乱数はエージェント生成時のシードのみに由来する。
- 先攻後攻を seed の偶奇で入れ替え、両方向を等しく含める。
- 勝率は必ず対戦数と95%信頼区間 ±1.96√(p(1-p)/n) を伴って返す。
- 引き分け・打ち切りは勝敗のどちらにも数えない（分母から除く）。
"""
from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.engine import GameConfig                       # noqa: E402
from meicho.runner import play_game                        # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_deck(name: str = "SD001") -> dict:
    with open(os.path.join(_HERE, "..", "decklists", f"{name}.json"),
              encoding="utf-8") as f:
        return json.load(f)


def mirror_config(deck: dict) -> GameConfig:
    """同一デッキの同型戦の設定。"""
    return GameConfig(chara_decks=[deck["chara_deck"]] * 2,
                      action_decks=[deck["action_deck"]] * 2)


def matchup_config(deck0: dict, deck1: dict) -> GameConfig:
    """異型戦の設定（席0が deck0、席1が deck1）。

    `series` は seed の偶奇で席を入れ替えるので、両エージェントは
    どちらのデッキも等しく持つ。デッキ強度の差は相殺され、
    測っているのはエージェント（規則）の差だけになる（レビュー §3.5）。
    """
    return GameConfig(chara_decks=[deck0["chara_deck"], deck1["chara_deck"]],
                      action_decks=[deck0["action_deck"], deck1["action_deck"]])


def ci95(wins: int, n: int) -> float:
    if n == 0:
        return float("nan")
    p = wins / n
    return 1.96 * math.sqrt(p * (1 - p) / n)


class Result:
    """勝率・対戦数・信頼区間をまとめて持つ。"""

    def __init__(self, wins: int, decided: int, games: int):
        self.wins, self.decided, self.games = wins, decided, games

    @property
    def p(self) -> float:
        return self.wins / self.decided if self.decided else float("nan")

    @property
    def ci(self) -> float:
        return ci95(self.wins, self.decided)

    def __str__(self) -> str:
        skipped = self.games - self.decided
        tail = f" / 除外{skipped}" if skipped else ""
        return f"{self.p:.3f} ±{self.ci:.3f} (n={self.decided}{tail})"


# --- 1試合 ---------------------------------------------------------------
# 並列実行のため、ワーカへはエージェントの「作り方」を渡す必要がある。
# ファクトリはトップレベル関数か、pickle 可能な呼び出し可能物であること。

def _one(args):
    make_a, make_b, config, seed = args
    flip = seed % 2                      # 奇数シードで A が後攻になる
    ags = ([make_b(seed * 2), make_a(seed * 2 + 1)] if flip
           else [make_a(seed * 2), make_b(seed * 2 + 1)])
    r = play_game(config, ags, seed=seed)
    if r["aborted"] or r["draw"]:
        return None
    return 1 if r["winner"] == flip else 0


def series(make_a, make_b, n: int, config: GameConfig,
           workers: int = 1, seed0: int = 0) -> Result:
    """A vs B を n 局。戻り値は A から見た勝率。

    workers>1 で対局単位のプロセス並列（レビュー §6 B-2(2)）。
    シードは分割されるだけなので結果は workers に依存しない。

    seed0: 使うシードの開始点。探索と検証で**別のシード帯**を使い、
        in-sample 評価を仕組みで防ぐために用いる（§7.1）。
    """
    jobs = [(make_a, make_b, config, seed) for seed in range(seed0, seed0 + n)]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            out = list(ex.map(_one, jobs, chunksize=4))
    else:
        out = [_one(j) for j in jobs]
    dec = [r for r in out if r is not None]
    return Result(sum(dec), len(dec), n)


def series_detail(make_a, make_b, n: int, config: GameConfig,
                  workers: int = 1, seed0: int = 0) -> list:
    """`series` と**まったく同じ対局**を回し、各局の結果をシード順の並びで返す。

    要素は 1（A の勝ち）／0（A の負け）／None（引き分け・打ち切り）。
    `series` は合計しか返さないので、**席（先攻・後攻）別に数えたいとき**に使う
    （席はシードの偶奇で決まる。偶数シードなら A が席 0）。集計の仕方が違うだけで、
    回す対局は 1 局も変わらない。
    """
    jobs = [(make_a, make_b, config, seed) for seed in range(seed0, seed0 + n)]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_one, jobs, chunksize=4))
    return [_one(j) for j in jobs]


def gauntlet(make_a, opponents: dict, n: int, config: GameConfig,
             workers: int = 1, seed0: int = 0) -> dict:
    """固定の相手プールに対する総当たり。平均勝率と内訳を返す。

    §7.1 の in-sample 化を防ぐため、探索の目的関数はこの平均を使い、
    相手プールとシードは探索中に固定する。検証は別のシード帯
    （seed0 を変える）と、プールに入れなかった相手で行う。
    """
    per = {name: series(make_a, mk, n, config, workers, seed0)
           for name, mk in opponents.items()}
    mean = sum(r.p for r in per.values()) / len(per)
    return {"mean": mean, "per": per}


def report(label: str, r: Result) -> None:
    print(f"{label}: {r}")
