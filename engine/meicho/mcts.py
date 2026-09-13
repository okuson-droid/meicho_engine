"""IS-MCTS（決定化UCT・同時手番は DUCT）— レビュー 2026-08-23 §6 B-1。

rules_draft.md v0.10 準拠。フェーズ4の中核。

## 部品はすでに揃っていた

- 決定化: `GreedyAgent._determinize`（D-026。隠蔽情報を乱数で置き換える）
- 進行: `engine.apply_owned`（B-2。専有 state を複製せず進める）
- ロールアウト方策: `HeuristicAgent`
- 葉の評価: `greedy.evaluate` ＋ A-3 で調整した重み
- 行動の絞り込み: `PlannerAgent._branches`（A-2）

本モジュールはそれらを木探索で束ねる。

## 同時手番の扱い: DUCT (Decoupled UCT)

対抗ステップ (§6.4(1)) は裏向き同時提出なので、手番を交互に積む普通のUCTでは
表現できない。DUCT は**各プレイヤーが独立に自分のUCBを回し**、
選ばれた行動の組を同時に適用する。実装が最小で、同時手番の近似として実用的である
（厳密なナッシュ均衡には収束しないが、CFR実験の教訓どおり
「部分ゲームを厳密に解く」ことより「フルゲームで測る」ことを優先する, D-032/C-2）。

## 木の同定（情報集合）

ノードは**根からの行動列**で同定する。決定化のたびに状態は変わるが、
行動列は観測可能な量なので、統計を決定化をまたいで共有できる。
これが IS-MCTS の「IS」の部分である。

## 分散抑制（PLANNER_NOTES.md と対）

このプロジェクトで繰り返し効いてきた対策をここでも入れる。

- **決定化は反復ごとに引き直す**（IS-MCTS の定義そのもの）
- **ロールアウトの乱数は反復ごとに固定点へ戻す**（共通乱数, CRN）。
  兄弟ノードの比較が乱数の揺れで決まるのを防ぐ。

## 覗き見について

探索はすべて `_determinize` を通した局面の上で行う。根の合法手は
実局面と同じ（隠蔽情報は相手の手札とデッキ順序だけなので、自分の合法手は不変）。
`tests/test_engine.py::test_nopeek_audit_mcts` で担保する。
"""
from __future__ import annotations

import math

from .engine import apply_owned, decision_players, legal_actions
from .planner import PlannerAgent, _akey
from .state import DRAW, Phase


def _squash(v: float, scale: float) -> float:
    """評価値を [0,1] に潰す。UCB は有界な報酬を前提とするため。"""
    return 0.5 + 0.5 * math.tanh(v / scale)


class _Node:
    """行動列で同定される情報集合ノード。統計はプレイヤーごとに持つ（DUCT）。"""

    __slots__ = ("children", "visits", "stats")

    def __init__(self):
        self.children = {}          # joint action key -> _Node
        self.visits = 0
        # stats[player][action_key] = [訪問回数, 報酬合計]
        self.stats = ({}, {})

    def select(self, q, acts, c, rng):
        """プレイヤー q の行動を UCB1 で選ぶ。未訪問があればそれを優先する。"""
        st = self.stats[q]
        untried = [a for a in acts if _akey(a) not in st]
        if untried:
            return untried[rng.randrange(len(untried))]
        total = sum(v[0] for v in st.values())
        logN = math.log(total + 1.0)
        best, best_v = None, -1e18
        for a in acts:
            n, s = st[_akey(a)]
            v = s / n + c * math.sqrt(logN / n)
            if v > best_v:
                best, best_v = a, v
        return best

    def update(self, q, key, reward):
        e = self.stats[q].get(key)
        if e is None:
            self.stats[q][key] = [1, reward]
        else:
            e[0] += 1
            e[1] += reward


class MCTSAgent(PlannerAgent):
    """決定化UCT。対抗の同時手番は DUCT で扱う。

    非担当フェイズ（選択・準備・手札上限）はヒューリスティックに委ねる点は
    貪欲・計画探索と同じ分担である。
    """

    def __init__(self, seed: int, iterations: int = 80, c_uct: float = 0.8,
                 rollout_turns: int = 2, max_depth: int = 24,
                 eval_scale: float = 8.0, opp_tree_phases: set = None,
                 mcts_phases: set = None, **kw):
        kw.setdefault("plan_samples", 1)     # 根の決定化は反復ごとに行う
        super().__init__(seed, **kw)
        self.iterations = iterations         # 1決定あたりのシミュレーション数
        self.c_uct = c_uct                   # 探索定数
        self.rollout_turns = rollout_turns   # ロールアウトで進めるターン数
        self.max_depth = max_depth           # 木の深さの上限（手数）
        self.eval_scale = eval_scale         # 評価値を [0,1] に潰す尺度
        # **相手の決定を木に入れるフェイズ**（B-1 の要点）。
        # 訪問数の少ないUCBノードは、調整済みヒューリスティックより
        # 相手モデルとして**劣る**。木に入れるのは同時手番でDUCTが必要な
        # 対抗ステップだけにし、それ以外の相手の手は固定方策で埋める。
        self.opp_tree_phases = ({Phase.CLASH_SUBMIT} if opp_tree_phases is None
                                else opp_tree_phases)
        # **木で指すフェイズ**。ここに入っていない担当フェイズは
        # 親クラス（計画探索 → 貪欲 → 規則）に委ねる。
        # 既定は担当フェイズすべて（＝素直な IS-MCTS）。
        # `mcts_phases={Phase.CLASH_SUBMIT}` にすると
        # 「アクションは計画探索・対抗は木」のハイブリッドになるが、
        # B-1 の測定では**素直な全部載せのほうが強かった**（B1_NOTES.md）。
        self.mcts_phases = set(self.phases) if mcts_phases is None \
            else mcts_phases

    # -- 葉の評価（差し替え口） ---------------------------------------------
    def _leaf01(self, s, pi) -> float:
        """葉を [0,1] に潰して返す。UCB は有界な報酬を前提とするため。

        既定は手書き評価値を `tanh` で潰す。**学習価値関数はここを差し替える**
        （C-1）。勝率を直接出すモデルなら潰す必要はなく、σ を通すだけでよい。
        """
        return _squash(self._eval(s, pi), self.eval_scale)

    # -- 木で扱う行動 ------------------------------------------------------
    def _tree_actions(self, s, q):
        """ノードで枝にする行動。木で扱わないなら None。

        アクションフェイズは A-2 の枝刈り（チャージ上位数枚・重複除去）を
        そのまま流用する。ここを絞らないと分岐が15前後になり、
        数十回の反復ではまったく探索しきれない。
        """
        if s.phase not in self.phases:
            return None
        acts = legal_actions(s, q)
        if len(acts) <= 1:
            return None
        if s.phase == Phase.ACTION:
            out = self._branches(s, q, acts)
            out += [a for a in acts if a["type"] in ("to_clash", "end_turn")]
            return out or acts
        return acts

    # -- 本体 --------------------------------------------------------------
    def act(self, s, pi):
        acts = legal_actions(s, pi)
        assert acts, f"no legal actions for P{pi} in {s.phase}"
        if len(acts) == 1:
            return acts[0]
        if s.phase not in self.mcts_phases:
            # 木に載せないフェイズは親（計画探索 → 貪欲 → 規則）に委ねる
            return super().act(s, pi)

        root = _Node()
        root_acts = self._tree_actions(s, pi) or acts
        crn = (self.fallback.rng.getstate(), self.opp_model.rng.getstate())
        for _ in range(self.iterations):
            t = self._determinize(s, pi)
            # 共通乱数: ロールアウトの揺れで兄弟の優劣が決まらないようにする
            self.fallback.rng.setstate(crn[0])
            self.opp_model.rng.setstate(crn[1])
            self._simulate(root, t, pi, root_acts)

        st = root.stats[pi]
        # 最終手は**訪問回数**で選ぶ（平均値より分散に強い定番の作法）
        best = max(root_acts, key=lambda a: st.get(_akey(a), (0, 0.0))[0])
        return best

    def _simulate(self, root, s, pi, root_acts) -> None:
        node, path, depth = root, [], 0
        while True:
            if s.outcome is not None:
                reward = (0.5 if s.outcome == DRAW
                          else (1.0 if s.outcome == pi else 0.0))
                break
            if depth >= self.max_depth:
                reward = self._leaf01(s, pi)
                break
            need = decision_players(s)
            if not need:
                reward = self._leaf01(s, pi)
                break

            actions, joint, tracked = {}, [], False
            for q in need:
                if q != pi and s.phase not in self.opp_tree_phases:
                    cand = None          # 相手の手は固定方策で埋める
                else:
                    cand = root_acts if (node is root and q == pi) \
                        else self._tree_actions(s, q)
                if cand is None:
                    # 木で扱わない決定は固定方策で埋める（選択・手札上限など）
                    actions[q] = self._proxy_act(s, q, pi)
                    continue
                tracked = True
                a = node.select(q, cand, self.c_uct, self.rng)
                actions[q] = a
                joint.append((q, _akey(a)))

            if not tracked:
                s = apply_owned(s, actions)
                depth += 1
                continue

            key = tuple(joint)
            child = node.children.get(key)
            s = apply_owned(s, actions)
            depth += 1
            path.append((node, joint))
            if child is None:
                node.children[key] = _Node()
                reward = self._rollout(s, pi)      # 展開したので葉評価へ
                break
            node = child

        for nd, joint in path:
            nd.visits += 1
            for q, k in joint:
                nd.update(q, k, reward if q == pi else 1.0 - reward)

    def _rollout(self, s, pi) -> float:
        """固定方策で数ターン進めてから評価する。

        最後まで回さないのは、1決定あたりの `apply` 回数を抑えるためである
        （SPEEDUP_NOTES.md の見積りどおり、ここが計算量を決める）。
        評価関数は A-3 で調整済みの重みをそのまま使う。
        """
        turn_end = s.turn_no + self.rollout_turns
        for _ in range(self.max_depth * 2):
            if s.outcome is not None:
                break
            if s.turn_no >= turn_end and s.phase != Phase.CHOICE:
                break
            need = decision_players(s)
            if not need:
                break
            s = apply_owned(s, {q: self._proxy_act(s, q, pi) for q in need})
        if s.outcome is not None:
            if s.outcome == DRAW:
                return 0.5
            return 1.0 if s.outcome == pi else 0.0
        return self._leaf01(s, pi)
