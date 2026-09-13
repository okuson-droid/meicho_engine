"""学習した価値関数を積んだエージェント（C-1 §4.1-2 / D-038）。

rules_draft.md v0.10 準拠 / engine v0.1。
モデルは `experiments/train_linear.py` が出力する JSON（`results/models/*.json`）。

## 何を差し替えているか

`GreedyAgent._eval`（葉の採点）だけである。探索の構造・決定化・共通乱数は
計画探索 (A-2) のまま。**したがって「葉の質が上がると強くなるか」を
単独で測れる**。B-1 (D-033) が IS-MCTS の弱点を葉評価と診断した仮説の検証でもある。

## 出力の尺度について（重要）

モデルは勝率の **log-odds** を返す。

- `PlannerAgent` は `_eval` の値を **argmax にしか使わない**ので、
  勝率の単調変換であれば尺度は自由である。log-odds をそのまま返す。
- `MCTSAgent` は UCB のために [0,1] が要る。手書き評価値は `tanh(v/8)` で
  潰していたが、log-odds なら **σ を通すだけで勝率そのものになる**。
  `_leaf01` をそう上書きする。尺度合わせの `eval_scale` は不要になる。

## 終端の扱い（引き継ぐこと）

`greedy.evaluate` は終端で ±`WIN`（10000）を返す。学習モデルの log-odds は
せいぜい ±10 なので、**終端の分岐を落とすと勝ちを勝ちと認識できなくなる**。
`_eval` の先頭で必ず終端を処理する。`test_valuenet_terminal_states_dominate`
がこれを押さえている。

## 覗き見について (D-026)

特徴は `meicho/features.from_state` のみを使う。これは
`from_obs`（観測だけから作る経路）と一致することがテストで担保されており、
隠蔽情報には触れない。エージェントとしての監査は
`test_nopeek_audit_value_planner` で実対局リプレイにかけている。
"""
from __future__ import annotations

import json
import math
import os

from . import features as F
from .greedy import WIN
from .mcts import MCTSAgent
from .planner import PlannerAgent
from .state import DRAW

# モデルのパス解決は `drlnet.resolve_model` を唯一の定義とする（D-058 で移した）。
from .drlnet import resolve_model                                  # noqa: E402,F401


class LinearValue:
    """ロジスティック回帰の価値関数。log-odds を返す。

    学習は標準化した特徴の上で行っているが、推論のたびに標準化するのは
    無駄なので、**重みを生の特徴の尺度に畳んでおく**
    （w_eff = w/sd, b_eff = b - Σ w·mu/sd）。1回の内積で済む。
    """

    __slots__ = ("w", "b", "idx", "inter", "name", "meta")

    def __init__(self, path: str):
        with open(resolve_model(path), encoding="utf-8") as f:
            d = json.load(f)
        assert d["kind"] == "logistic", f"未対応のモデル種別: {d['kind']}"
        assert list(d["feature_names"]) == list(F.FEATURE_NAMES), (
            "モデルの特徴名が meicho/features.py と一致しない。"
            "特徴を変えたらモデルを学習し直すこと")
        w, mu, sd = d["w"], d["mu"], d["sd"]
        n = len(w) - 1
        self.w = [w[i] / sd[i] for i in range(n)]
        self.b = w[n] - sum(w[i] * mu[i] / sd[i] for i in range(n))
        # 設計行列の並び: 選んだ列 → 交互作用の順（train_linear._design と対応）
        self.idx = [F.FEATURE_NAMES.index(c) for c in d["cols"]]
        self.inter = [(F.FEATURE_NAMES.index(a), F.FEATURE_NAMES.index(b))
                      for a, b in d.get("interactions", [])]
        assert len(self.idx) + len(self.inter) == n, "重みの本数が列と合わない"
        self.name = d.get("model", "linear")
        self.meta = {k: d.get(k) for k in ("dataset", "def_hash", "lam")}

    def logodds(self, x: list) -> float:
        w, v = self.w, self.b
        for k, i in enumerate(self.idx):
            v += w[k] * x[i]
        off = len(self.idx)
        for k, (a, b) in enumerate(self.inter):
            v += w[off + k] * x[a] * x[b]
        return v

    def __call__(self, s, pi) -> float:
        return self.logodds(F.from_state(s, pi))


class _ValueMixin:
    """`_eval` を学習モデルに差し替える混合クラス。"""

    def _init_value(self, model: str):
        self.value = LinearValue(model)
        self.model_path = model

    def _eval(self, s, pi) -> float:
        """終端は手書き評価と同じ ±WIN。それ以外は学習モデルの log-odds。"""
        if s.outcome is not None:
            if s.outcome == DRAW:
                return 0.0
            return WIN if s.outcome == pi else -WIN
        return self.value(s, pi)


class ValuePlannerAgent(_ValueMixin, PlannerAgent):
    """計画探索 (A-2) の葉評価だけを学習価値関数に差し替えたもの。

    重み `TUNED_WEIGHTS` は `_eval` を通らない経路（`heuristic` の
    `card_utility` 等）でなお使われるので、親の初期化はそのまま行う。
    """

    def __init__(self, seed: int, model: str = "c1_linear_v1.json", **kw):
        super().__init__(seed, **kw)
        self._init_value(model)


class ValueMCTSAgent(_ValueMixin, MCTSAgent):
    """IS-MCTS (B-1) の葉評価を学習価値関数に差し替えたもの。

    log-odds をそのまま σ に通せば勝率になるので、`tanh(v/eval_scale)` の
    尺度合わせは不要である（`eval_scale` は終端以外では使われなくなる）。
    """

    def __init__(self, seed: int, model: str = "c1_linear_v1.json", **kw):
        super().__init__(seed, **kw)
        self._init_value(model)

    def _leaf01(self, s, pi) -> float:
        if s.outcome is not None:
            if s.outcome == DRAW:
                return 0.5
            return 1.0 if s.outcome == pi else 0.0
        v = self.value(s, pi)
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, v))))
