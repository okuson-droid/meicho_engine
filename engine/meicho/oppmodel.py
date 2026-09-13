"""相手モデル（レビュー 2026-08-23 §6 B-3）。

> **【測定結果 2026-08-23: 既定はオフ (`use_history=False`)】**
> このモデルは**予測精度は上げたが、勝率を動かさなかった**（D-032）。
> 事前分布と最も違う相手 X3 に対して色の的中率は 0.326 → **0.389** に改善したが、
> **自分の手が変わったのは対抗ノードの 7.6% だけ**で、勝率は信頼区間内に留まった。
> 事前分布が正しい相手（H_default）では逆に的中率が 0.492 → 0.441 に落ちる。
> 事前強度 k を下げて履歴に強く寄せるほど悪化する（k=2 で 0.807 < 基準 0.830）。
>
> 機構と `GameState.clash_counts` は残してある。カードプールが増える
> （発売 2026-09-12 以降）と対抗の利得構造が変わりうるので、そのときに再測定する。
> 詳細と考察は `B3_NOTES.md`。


## 何が問題だったか

貪欲・計画探索は対抗ステップを決定化して評価するが、そこで**相手の行動を
既定ヒューリスティックで決め打ち**していた。相手が別の色方策を持っていても
モデルは「自色を8割で出す既定H」のまま動くので、見積もりが系統的にずれる。
人間相手（§8-3）ではこの前提はまず成り立たない。

## 何をするか

対抗で提出された色は**両者に公開される**（§6.4(1)-3）。その累積回数を
`GameState.clash_counts` に持たせた（D-031）ので、これを相手の色方策の
経験分布として使う。

    採用確率 w = n / (n + k)      n = 相手のこれまでの提出回数, k = 事前の強さ

- 確率 w で**経験分布**から色を抽選し、その色の中から最大打点を選ぶ
- 確率 1-w で従来どおり**固定ヒューリスティック**に委ねる

序盤（n=0）は w=0 なので**従来と完全に同じ挙動に縮退する**。観測が貯まるほど
経験分布に寄る。k はその移行の速さで、既定 8（対抗は1局に15〜30回起きるので、
中盤で経験分布が優勢になる）。

## なぜ「色だけ」を経験分布にするか

固定ヒューリスティックの良いところは、**標本抽出した手札に条件づけて**
行動を選ぶ点である（持っていない色は出せない）。経験分布はその条件づけを
持たない。そこで色の**選好**だけを経験分布から取り、
「その色の中でどのカードを出すか」は標本抽出した手札から決める、
という二段構えにして両方の利点を残している。

## 乱数は**自前で持つ**（重要・PLANNER_NOTES.md の分散抑制と対）

このモデルは抽選を行うので、探索の枝ごとに違う乱数を引くと、その揺れが
計画の優劣に化ける。計画探索は終端の直前に固定方策の乱数状態を同じ点へ
戻して比較条件を揃えている（共通乱数, CRN）が、モデルがエージェント本体の
乱数を使うとこの仕組みの外に出てしまう。実測でも、本体の乱数を共有した
初版は既定Hや自色確定の相手に対して **−0.007〜−0.037** と悪化した。

そこでモデルは専用の `random.Random` を持ち、CRN のスナップショット対象に
含める（`PlannerAgent._plan` / `_value_after_turn`）。

## 覗き見について

参照するのは `clash_counts`（公開情報の集計）と、決定化で差し替えた後の
相手の手札だけである。`test_nopeek_audit_*` がそのまま担保になる。
"""
from __future__ import annotations

import random

from .cards import ACTION_CARDS
from .engine import legal_actions
from .state import CLASH_COLOR_INDEX, Phase


class OpponentModel:
    """対抗の色を経験分布と固定方策の混合で予測する相手モデル。"""

    def __init__(self, fallback, prior_strength: float = 8.0,
                 enabled: bool = True, seed: int = 0):
        self.fallback = fallback          # 事前分布としての固定方策
        self.k = prior_strength           # 経験分布に移る速さ（大きいほど慎重）
        self.enabled = enabled            # False で従来どおりの固定方策のみ
        self.rng = random.Random(seed)    # 専用の乱数（CRN の対象に含めること）

    def act(self, s, opp: int, rng=None):
        """相手 opp の行動を1つ返す。rng 省略時は自前の乱数を使う。"""
        rng = rng or self.rng
        if not self.enabled or s.phase != Phase.CLASH_SUBMIT:
            return self.fallback.act(s, opp)

        acts = legal_actions(s, opp)
        sub = [a for a in acts if a["type"] == "submit"]
        if len(acts) <= 1 or not sub:
            return self.fallback.act(s, opp)

        counts = s.clash_counts[opp]
        n = counts[0] + counts[1] + counts[2]       # パスは色の分布に数えない
        if n <= 0 or rng.random() >= n / (n + self.k):
            return self.fallback.act(s, opp)        # 観測不足 → 事前分布

        # 提出可能な色に限って経験分布から抽選する
        bycol = {}
        for a in sub:
            bycol.setdefault(ACTION_CARDS[s.players[opp].hand[a["hand"]]].color,
                             []).append(a)
        weights = [(c, counts[CLASH_COLOR_INDEX[c.value]]) for c in bycol]
        total = sum(w for _c, w in weights)
        if total <= 0:
            # 観測した色を1枚も持っていない標本。手札の条件づけを優先する
            return self.fallback.act(s, opp)
        r = rng.random() * total
        acc = 0.0
        col = weights[-1][0]
        for c, w in weights:
            acc += w
            if r <= acc:
                col = c
                break
        return max(bycol[col],
                   key=lambda a: (ACTION_CARDS[s.players[opp].hand[a["hand"]]].damage,
                                  ACTION_CARDS[s.players[opp].hand[a["hand"]]].speed))
