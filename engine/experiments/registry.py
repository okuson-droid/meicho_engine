"""エージェント登録簿（C-4 / D-034）。

ガントレット定義（JSON）の `factory` 名を、pickle 可能な生成器に変換する。
`arena.series` はプロセス並列のため lambda を受け付けないので、
生成器は `Mk`（クラス＋kwargs を保持する呼び出し可能物）で表す。

登録名を増やすときはここに追加し、`tests/test_ladder.py` の登録テストに足す。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.agents import RandomAgent                      # noqa: E402
from meicho.greedy import GreedyAgent                      # noqa: E402
from meicho.heuristic import HeuristicAgent, Params        # noqa: E402
from meicho.mcts import MCTSAgent                          # noqa: E402
from meicho.planner import PlannerAgent                    # noqa: E402
from meicho.valuenet import ValueMCTSAgent, ValuePlannerAgent  # noqa: E402


class Mk:
    """pickle 可能なエージェント生成器。`Mk(cls, **kw)(seed) == cls(seed, **kw)`。"""

    def __init__(self, cls, **kw):
        self.cls, self.kw = cls, kw

    def __call__(self, seed: int):
        return self.cls(seed, **self.kw)

    def describe(self) -> str:
        """記録用の可読表現。kwargs は決定的な順序で並べる。"""
        def fmt(v):
            # デッキリストのような長い列は要約する（内容はガントレットの deck で決まる）
            return f"<list:{len(v)}>" if isinstance(v, list) and len(v) > 8 else repr(v)
        args = ", ".join(f"{k}={fmt(self.kw[k])}" for k in sorted(self.kw))
        return f"{self.cls.__name__}({args})"


# factory 名 → (クラス, 相手デッキ(opp_decklist)を要求するか)
FACTORIES = {
    "random":    (RandomAgent, False),
    "heuristic": (HeuristicAgent, False),
    "greedy":    (GreedyAgent, True),
    "planner":   (PlannerAgent, True),
    "mcts":      (MCTSAgent, True),
    # C-1 (D-038): 葉評価を学習価値関数に差し替えたもの。
    # 学習済みモデルは kwargs の `model`（`results/models/` 配下のファイル名）で渡す。
    # ガントレット JSON に書けるよう、絶対パスではなく名前で解決する。
    "planner_v":  (ValuePlannerAgent, True),
    "mcts_v":     (ValueMCTSAgent, True),
    # D-058: 相手モデルを学習した方策 π に差し替えた計画探索（現 SD001 champion）。
    # kwargs の `opp_policy_net` に `results/models/` 配下のファイル名を書く。
    # 中身の定義は `experiments/champion.py`（唯一の真実源）。
    "planner_pi": (PlannerAgent, True),
    # D-064: V の反復ブートストラップのループのエージェント（`VALUE_BOOTSTRAP_DESIGN.md` §4.3）。
    # kwargs の例（反復 2 の版をラダーに載せる場合）:
    #   {"extra_turns": 1, "value_net": "drl_sd001_vb2.json",
    #    "opp_policy_net": "drl_sd001_s1.json", "opp_policy_root_only": True}
    # 中身の定義は `experiments/vb.py`（唯一の真実源）。**絶対パス禁止**（C-1 の教訓）。
    #
    # D-065 便 1 で足したつまみも同じ kwargs としてそのまま通る（登録名は増やさない）:
    #   "policy_net"（代打ちを π に）／"policy_scope"（"all"|"proxy"|"fallback"）／
    #   "samples"（対抗の決定化の本数）／"choice_phases"／"solo_samples"／
    #   "align_leaves"（葉を次の自分のターン開始に揃える）／"tau"（対人用の確率化）。
    # どれも既定で無効なので、書かなければ従来どおりである。
    "planner_vb": (PlannerAgent, True),
}


def make(factory: str, kwargs: dict | None, pool: list | None) -> Mk:
    """登録名と JSON の kwargs から生成器を作る。

    - `params` が dict なら `heuristic.Params(**dict)` に変換する
      （摂動ヒューリスティック X1〜X3, π_det, π_mix を JSON で書けるように）。
    - 先読み系（greedy/planner/mcts）には相手デッキ `opp_decklist` を渡す。
    """
    if factory not in FACTORIES:
        raise KeyError(f"未登録の factory: {factory!r}（登録済: {sorted(FACTORIES)}）")
    cls, needs_pool = FACTORIES[factory]
    kw = dict(kwargs or {})
    if isinstance(kw.get("params"), dict):
        kw["params"] = Params(**kw["params"])
    if needs_pool:
        if pool is None:
            raise ValueError(f"{factory} には opp_decklist が必要")
        kw.setdefault("opp_decklist", pool)
    return Mk(cls, **kw)
