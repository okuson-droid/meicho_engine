"""ターン計画エージェント（レビュー 2026-08-23 §6 A-2）。

rules_draft.md v0.10 準拠。貪欲エージェント (greedy.py) の弱点だった
アクションフェイズを、**1手ではなくターン内の行動列を単位として**探索する。

## なぜ1手先読みでは足りなかったか

貪欲はアクションフェイズで対ヒューリスティック 0.338（最弱）だった。
原因は深さ不足そのものではなく、**採点の地点が悪い**ことである。
チャージを1手適用した直後の局面は「手札が1枚減った」だけで、
その協奏がこのターンの対抗で何を撃てるようにしたかが見えない。

## 利用する構造 (§6.3)

アクションフェイズは**相手が関与しない単独逐次決定**であり、
チャージ・切り替え・レベルアップは各1ターン1回に制限されている。
したがってターン内の行動列の空間は小さく（高々3行動の順列＋終端）、
**全列挙して「対抗を解決したあと」の局面で採点できる**。
これなら「チャージしてから対抗に入る」の合計価値が正しく見える。

## 探索の構造

- 節点 = アクションフェイズの局面。枝 = チャージ/切り替え/レベルアップ。
- 終端 = `to_clash`（対抗を固定方策で解決し、ターン終了まで進めて採点）
  または `end_turn`。
- 同一の結果局面に至る行動列は重複除去する（チャージとレベルアップの
  順序交換など、§6.3 の1回制限のもとでは多くが可換）。
- チャージ対象は card_utility の低い順に上位数枚へ限定する。
- 探索は毎決定ごとに再実行する（計画を保持しない）。使用済みフラグが
  立つぶん木は毎回小さくなるので、ターン全体の総コストは初回の約2倍に収まる。

## 決定化 (D-026) と分散の抑制

探索は必ず `_determinize` した局面の上で行う。1回の探索の中では
決定化を共有するので、候補間で「引く札」は共通であり比較は公正である。

**強さの大半はここから出た。** 対ヒューリスティック勝率の推移
（SD001同型・n=300・アクションフェイズのみ計画探索、他は既定構成）:

| 構成 | 勝率 |
|---|---|
| 1手貪欲（比較対象・GREEDY_NOTES.md） | 0.338 |
| 計画探索のみ | 0.490 ±0.057 |
| ＋共通乱数 (CRN) | 0.550 ±0.056 |

既定構成（対抗・連撃も含む）での決定化数 `plan_samples` の掃引（n=300）:
1→0.677, 2→0.710, 3→0.737, 4→**0.773 ±0.047**, 6→0.743。
4以上は頭打ちで、コストは線形に増える。既定を 4 とする。

分散抑制が効いた理由は、終端の対抗が固定方策の**混合戦略**で解決されるため、
枝ごとに乱数列が違うとその揺れがそのまま計画の優劣に化けていたからである。
同じ乱数の下で比べる（CRN）と、比較しているものが実際の計画の差になる。

## 地平の延長と葉の差し替え（D-064 / VALUE_BOOTSTRAP_DESIGN.md §4.1）

`extra_turns` と `value_net` は**どちらも既定で無効**であり、既定値のままなら
一手も挙動が変わらない（`tests/test_value_bootstrap.py::test_planner_defaults_unchanged`）。

- `extra_turns=1`: `_value_after_turn` の打ち切りを「自分のターンの終わり」から
  **「次に自分の手番が始まるところ」**まで延ばす（D-046 対策A）。旧
  `experiments/measure_horizon.py::LongHorizonPlanner` の実装をここへ移した。
- `value_net=<path>`: 葉の採点を学習した価値ネットに差し替える。返る値は勝率 [0,1]。
  **Rust 版 `agents.rs::Greedy::net_value` と同じ規約**であり、決着済みの局面は
  1.0 / 0.0 / 0.5 を返す（学習の教師と同じ尺度）。§3.2 の「終端が非終端を支配する」
  という要請は、[0,1] の尺度ではこの 1.0 / 0.0 が満たす。

## 既知の簡略化

- レベルアップの手札コスト（`Phase.CHOICE` の discard）は探索の枝にせず、
  ヒューリスティックの `card_utility` で自動選択する。選択肢化すると
  枝が手札枚数倍に増えるため。戦略的に意味を持つと判明した時点で見直す（D-004）。
- 終端の対抗は両者ともヒューリスティックで解決する。自分側は実戦では
  貪欲の決定化評価で選ぶため、`to_clash` の価値をやや過小評価する方向に偏る。
- `end_turn` は「対抗に出せる札が1枚もない」ときだけ終端候補に含める。
  出せる札があるのに対抗に進まないのは §6.4(2)-1-A のもとでほぼ常に損だが、
  これは枝刈りであって定理ではない。
"""
from __future__ import annotations

from .engine import (_usable_in_clash, apply, apply_owned,
                     decision_players, legal_actions, observe)
from .greedy import GreedyAgent, Weights, load_net
from .heuristic import HeuristicAgent, Params, card_utility
from .oppmodel import OpponentModel
from .cards import ACTION_CARDS
from .state import DRAW, Phase

# --- CEM で結合最適化した既定値（A-3, 2026-08-23）--------------------------
# experiments/optimize_cem.py: 8世代 × 個体12 × 各30局、相手プール
# {H_default, X1, X2}、シード帯 0..29 で探索。
# 検証は**未使用のシード帯 10000..** かつ**探索に使わなかった相手**で行い、
# 探索プール外にも転移することを確認済み（PLANNER_NOTES.md 参照）。
#
# 貪欲 (greedy.Weights) の既定と違う点が示唆的である:
#   - level 0.0 → 0.50: 1手先読みではレベルアップは「手札が減った」だけに見えたが、
#     ターン計画では消費と効果を同じ視野で見るので、正の重みが正しくなった。
#   - hand 0.5 → 1.13, concerto 0.8 → 1.03: 手札とコスト基盤の価値がともに上がった。
TUNED_WEIGHTS = Weights(life=1.0, concerto=1.034, hand=1.126, live_red=0.533,
                        level=0.498, resource=0.061)
TUNED_PARAMS = Params(own_color_weight=10.373, counter_weight=0.722,
                      scarce_penalty=0.255, concerto_target=4,
                      charge_min_hand=1, levelup_min_hand=4,
                      switch_min_gain=2, pay_min_concerto=2)


def _akey(a: dict) -> tuple:
    """行動を辞書キーにするための正規化。"""
    return tuple(sorted(a.items()))


class PlannerAgent(GreedyAgent):
    """アクションフェイズをターン計画探索で指し、対抗・連撃は貪欲に指す。"""

    def __init__(self, seed: int, weights: Weights = None,
                 opp_decklist: list = None, samples: int = 6,
                 rollout_depth: int = 24, phases: set = None,
                 charge_candidates: int = 3, leaf_budget: int = 220,
                 turn_rollout: int = 40, plan_samples: int = 4,
                 params: Params = None, tuned: bool = True,
                 use_history: bool = False, prior_strength: float = 8.0,
                 race_after: int = 99,
                 opp_policy_net: str = None, opp_policy_root_only: bool = False,
                 extra_turns: int = 0, value_net: str = None,
                 policy_net: str = None, policy_scope: str = "all",
                 choice_phases: bool = False, solo_samples: int = 1,
                 align_leaves: bool = False, align_rollout: int = 80,
                 align_stop: str = "my_turn", tau: float = 0.0,
                 opp_mix: float = 0.0, nash_delta: float = 0.0,
                 lethal_uniform: float = 0.0, known_hand: bool = False,
                 endgame_enum: int = 0, endgame_eval: int = 16,
                 endgame_conf: float = 0.6,
                 world_weight: float = 0.0, weight_temp: float = 2.0,
                 weight_floor: float = 0.2, weight_lookback: int = 3,
                 draw_buckets: int = 0, bundle_p: float = 0.0):
        # tuned=True で CEM 最適化済みの既定値を使う（A-3）。
        # 明示的に weights/params を渡した場合はそちらを優先する。
        if weights is None and tuned:
            weights = TUNED_WEIGHTS
        self._use_history, self._prior_strength = use_history, prior_strength
        super().__init__(seed, weights=weights, opp_decklist=opp_decklist,
                         use_history=use_history, prior_strength=prior_strength,
                         samples=samples, rollout_depth=rollout_depth,
                         phases=(phases if phases is not None else
                                 {Phase.ACTION, Phase.CLASH_SUBMIT, Phase.RUSH}),
                         opp_policy_net=opp_policy_net,
                         opp_policy_root_only=opp_policy_root_only,
                         policy_net=policy_net, policy_scope=policy_scope,
                         choice_phases=choice_phases, solo_samples=solo_samples,
                         align_leaves=align_leaves, align_rollout=align_rollout,
                         align_stop=align_stop, tau=tau, opp_mix=opp_mix,
                         nash_delta=nash_delta, lethal_uniform=lethal_uniform,
                         known_hand=known_hand,
                         endgame_enum=endgame_enum, endgame_eval=endgame_eval,
                         endgame_conf=endgame_conf, world_weight=world_weight,
                         weight_temp=weight_temp, weight_floor=weight_floor,
                         weight_lookback=weight_lookback,
                         draw_buckets=draw_buckets, bundle_p=bundle_p)
        # 便 A の判断①（D-071 裁定・便 E-0 で実装）: `lethal_uniform` は葉の採点が
        # **勝率の尺度**（決着済み = 1.0 / 0.0 / 0.5）であることに依存している。
        # 詰みの判定が `_score_clash(...) >= 1.0 − 1e-9` だからである。`value_net` が無い
        # 素の `evaluate`（±WIN = ±10000 の尺度）では 1.0 は詰みを意味しないので、
        # このつまみは**黙って別の意味で動いてしまう**。設計の穴なのでここで塞ぐ。
        # `GreedyAgent` は素の尺度の上で規則そのものを単体検査する土台として許す
        # （ただし champion 候補にもアプリの相手にもしない）。
        if lethal_uniform > 0.0 and value_net is None:
            raise ValueError(
                "lethal_uniform は value_net と組でしか使えない"
                "（詰みの判定が勝率の尺度 1.0 に依存しているため）")
        self.charge_candidates = charge_candidates   # チャージ対象の上位何枚を見るか
        self.leaf_budget = leaf_budget               # 1計画あたりの終端採点の上限
        self.turn_rollout = turn_rollout             # ターン終端までの最大手数
        self.plan_samples = plan_samples             # 決定化を何通り試すか
        # racing (B-2): この標本数を終えてから1手目の絞り込みを始める。
        # 大きいほど安全（絞らない）。plan_samples 以上で racing 無効。
        self.race_after = race_after
        # D-064: 地平の延長（0 = 従来どおり）と葉の採点の差し替え（None = 手作り evaluate）。
        self.extra_turns = extra_turns
        self.value_net = value_net
        if params is not None:
            self.fallback = HeuristicAgent(seed, params)
        elif tuned:
            self.fallback = HeuristicAgent(seed, TUNED_PARAMS)
        # fallback を差し替えたので、それを事前分布に使う相手モデルも作り直す
        self.opp_model = OpponentModel(self.fallback, prior_strength,
                                       enabled=use_history, seed=seed)

    # -- 本体 --------------------------------------------------------------
    def act(self, s, pi):
        # 段 C-2: 前の対抗の結果が公開されていれば履歴に積む。**ここにも要る**——
        # アクションフェイズは `_plan` に直行して `GreedyAgent.act` を通らないので、
        # 親クラスだけに置くと「アクションで決めた回」の履歴が落ちる（Rust と食い違う）。
        # 2 回呼ばれても 2 度は積まない（`_pending_clash` を取り出す形にしてある）。
        self._note_history(s, pi)
        acts = legal_actions(s, pi)
        assert acts, f"no legal actions for P{pi} in {s.phase}"
        if len(acts) == 1:
            return acts[0]
        if s.phase == Phase.ACTION and Phase.ACTION in self.phases:
            return self._plan(s, pi, acts)
        return super().act(s, pi)

    # -- ターン計画探索 ----------------------------------------------------
    def _plan(self, s, pi, acts) -> dict:
        """決定化 plan_samples 通りで探索し、1手目ごとの価値を平均して選ぶ。

        1つの決定化の中では「その1手目から到達できる最良の計画の値」を取り、
        決定化をまたいでその値を平均する（max-then-mean）。決定化ごとに
        引く札が変わるので、単一の決定化で当たり札を引いた計画に
        引きずられるのを防ぐ。
        """
        total, count, action_of = {}, {}, {}
        alive = None          # 生き残っている1手目（None = 全部）。B-2 の racing
        # 段 C-2（II-8・D-077）: 決定化をまたぐ平均を**加重平均**にする。
        # つまみ 0 なら重みはちょうど 1.0 なので、合計も件数も従来と同じ値になる
        # （`1.0 * x == x`・`0 + 1.0 == 1`）。
        ts, ws = self._worlds(s, pi, max(1, self.plan_samples))
        # 段 C-3（II-9・D-077 追記 3）: 列挙した本を使ったときだけ、
        # **本ごとの最良の 1 手目**に重みを載せて投票する（下の安全弁で使う）。
        enumerated = self._worlds_enumerated
        votes, vote_keys = {}, []
        for i, (t, w) in enumerate(zip(ts, ws)):
            leaves = []          # [(score, first_action)]
            self._budget = self.leaf_budget
            self._allowed = alive
            # 共通乱数 (common random numbers): 終端の対抗は固定方策の混合戦略で
            # 解決されるため、枝ごとに乱数列が違うとその揺れが計画の優劣に化ける。
            # 各終端の直前に同じ状態へ戻し、全計画を同一の乱数の下で比べる。
            self._crn = (self.fallback.rng.getstate(),
                         self.opp_model.rng.getstate())
            self._search(t, pi, None, 3, leaves, {self._sig(t)})
            best_here = {}       # この決定化での「1手目 → 到達できる最良値」
            for score, a in leaves:
                k = _akey(a)
                action_of[k] = a
                if k not in best_here or score > best_here[k]:
                    best_here[k] = score
            for k, v in best_here.items():
                total[k] = total.get(k, 0.0) + w * v
                count[k] = count.get(k, 0) + w
            if enumerated and best_here:
                # この本での最良の 1 手目（同点は先に出てきた方＝挿入順。Rust も同じ）
                bk = max(best_here, key=lambda k: best_here[k])
                if bk not in votes:
                    vote_keys.append(bk)
                votes[bk] = votes.get(bk, 0.0) + w
            if i + 1 >= self.race_after:
                alive = self._survivors(total, count, alive)
        if not action_of:    # 予算切れ等の保険。1手貪欲に落とす
            self._last_endgame = None
            return super()._solo(s, pi, acts)
        # 段 C-3 の投票と安全弁。**列挙した本を使ったときだけ**通る道である。
        # C = 勝った手の重みの割合。C ≥ `endgame_conf` ならその手、
        # そうでなければ従来どおり加重平均の最良手（＝安全弁）。
        # `tau > 0`（対人用の確率化）のときは投票を使わない——抽選の意味が変わるため。
        self._last_endgame = None
        if enumerated and votes:
            avg_key = max(total, key=lambda k: total[k] / count[k])
            tw = sum(votes.values())
            vk = max(vote_keys, key=lambda k: votes[k]) if tw > 0 else None
            conf = (votes[vk] / tw) if tw > 0 else 0.0
            used = bool(vk is not None and conf >= self.endgame_conf
                        and self.tau <= 0.0)
            self._last_endgame = {
                "enumerated": True, "worlds": len(ts), "C": conf, "used": used,
                "vote_move": action_of.get(vk), "avg_move": action_of[avg_key]}
            if used:
                return action_of[vk]
        if self.tau > 0.0:   # D-065 B-3: 対人用の確率化（既定 0 なら通らない）
            from .greedy import soft_pick
            keys = list(total)
            avg = [total[k] / count[k] for k in keys]
            return action_of[keys[soft_pick(avg, self.tau, self.rng)]]
        best = max(total, key=lambda k: total[k] / count[k])
        return action_of[best]

    def _survivors(self, total, count, alive):
        """B-2 racing: 次の決定化で展開する1手目を上位半分に絞る。

        決定化を重ねるほど候補を減らす。1手目ごとの価値は平均で比べるので、
        標本数が違っても比較は成立する（落とした候補は復活しない＝下位確定）。
        上位「半分」と広めに残すのは、1標本の揺れで真の最良を落とさないため。
        最低2つは残す。
        """
        keys = [k for k in total if alive is None or k in alive]
        if len(keys) <= 2:
            return set(keys)
        keys.sort(key=lambda k: total[k] / count[k], reverse=True)
        return set(keys[:max(2, (len(keys) + 1) // 2)])

    def _search(self, t, pi, first, depth, leaves, seen) -> None:
        acts = legal_actions(t, pi)
        types = {a["type"] for a in acts}
        # 1手目の絞り込み（racing）。根でだけ効かせる。
        top = first is None
        allowed = self._allowed

        # 終端: 対抗に進む（原則こちら）
        if "to_clash" in types and self._budget > 0 and not (
                top and allowed is not None
                and _akey({"type": "to_clash"}) not in allowed):
            self._budget -= 1
            leaves.append((self._value_after_turn(
                apply(t, {pi: {"type": "to_clash"}}), pi),
                first if first is not None else {"type": "to_clash"}))

        # 終端: ターンを終える（出せる札が1枚もないときだけ）
        p = t.players[pi]
        if "end_turn" in types and self._budget > 0 and not (
                top and allowed is not None
                and _akey({"type": "end_turn"}) not in allowed) and not any(
                _usable_in_clash(t, pi, ACTION_CARDS[cid]) for cid in p.hand):
            self._budget -= 1
            leaves.append((self._value_after_turn(
                apply(t, {pi: {"type": "end_turn"}}), pi),
                first if first is not None else {"type": "end_turn"}))

        if depth <= 0 or self._budget <= 0:
            return

        for a in self._branches(t, pi, acts):
            if top and allowed is not None and _akey(a) not in allowed:
                continue
            u = self._settle(apply(t, {pi: a}), pi)
            nxt = first if first is not None else a
            if u.outcome is not None or u.phase != Phase.ACTION:
                # ターン内で決着した／想定外の遷移。その場で採点して打ち切る
                if self._budget > 0:
                    self._budget -= 1
                    leaves.append((self._eval(u, pi), nxt))
                continue
            key = self._sig(u)
            if key in seen:       # 順序違いで同じ局面に着いた
                continue
            seen.add(key)
            self._search(u, pi, nxt, depth - 1, leaves, seen)

    def _branches(self, t, pi, acts) -> list:
        """展開する資源行動（§6.3-1/2/3）。重複と無価値な枝を落とす。"""
        p = t.players[pi]
        out = []

        # チャージ: 同じカードIDへの重複を潰し、手放して惜しくない順に上位数枚
        ch = {}
        for a in acts:
            if a["type"] == "charge":
                ch.setdefault(p.hand[a["hand"]], a)
        if ch:
            ranked = sorted(ch.items(),
                            key=lambda kv: card_utility(t, pi, kv[0],
                                                        self.fallback.p))
            out += [a for _, a in ranked[:self.charge_candidates]]

        out += [a for a in acts if a["type"] == "switch"]

        # レベルアップ: 同一スロットへの同一カードIDは1つに畳む
        lv = {}
        for a in acts:
            if a["type"] == "levelup":
                lv.setdefault((a["slot"], a["card"]), a)
        out += list(lv.values())
        return out

    def _value_after_turn(self, u, pi) -> float:
        """自分のターンが終わる（＝相手の手番が始まる）まで固定方策で進めて採点する。

        `_settle` と違い `CLASH_SUBMIT` で止まらない。ここが A-2 の本質で、
        「チャージしてから対抗に入った結果」まで見てから採点する。

        `extra_turns >= 1`（D-046 対策A・D-064 裁定 1）では打ち切りを
        **「次に自分の手番が始まるところ」**まで延ばす。相手のターンを通すぶん
        手数が増えるので、上限も `turn_rollout * (1 + extra_turns)` に増やす。
        分岐は Rust 版 `agents.rs::Planner::value_after_turn` と 1 対 1 に保つこと。
        """
        # 共通乱数（_plan 参照）。相手モデルも抽選を行うので必ず含めること。
        self.fallback.rng.setstate(self._crn[0])
        self.opp_model.rng.setstate(self._crn[1])
        if self.extra_turns == 0:
            turn0 = u.turn_no
            for _ in range(self.turn_rollout):
                if u.outcome is not None or u.phase == Phase.GAME_OVER:
                    break
                if u.turn_no != turn0 and u.phase != Phase.CHOICE:
                    break
                need = decision_players(u)
                if not need:
                    break
                u = apply_owned(u, {q: self._proxy_act(u, q, pi) for q in need})
        else:
            goal = u.turn_no + self.extra_turns + 1     # 自分の次のターン番号
            for _ in range(self.turn_rollout * (1 + self.extra_turns)):
                if u.outcome is not None or u.phase == Phase.GAME_OVER:
                    break
                if u.turn_no >= goal and u.phase != Phase.CHOICE:
                    break
                need = decision_players(u)
                if not need:
                    break
                u = apply_owned(u, {q: self._proxy_act(u, q, pi) for q in need})
        return self._eval(u, pi)

    def _eval(self, s, pi) -> float:
        """葉の採点。`value_net` があれば学習した価値ネット（勝率 [0,1]）。

        **Rust 版 `agents.rs::Greedy::net_value` と同じ規約**である:
        決着済みの局面は 1.0（勝ち）/ 0.0（負け）/ 0.5（引き分け）を返し、
        それ以外は `net.value_of(encode(observe(s, pi), pi))`。

        なぜ `greedy.WIN`（±10000）ではないのか: 葉の値の尺度が [0,1] になるので、
        1.0 と 0.0 がそのまま「どの非終端よりも良い／悪い」の役割を果たす
        （設計書 §3.2 が求めた「終端が支配する」性質はこれで満たされる）。
        逆に ±10000 を混ぜると、引き分けの扱いが Rust 版とずれて
        Python/Rust 一致テストが通らなくなる。**Python が真実源である以上、
        この規約を変えるなら Rust も同時に変えて再ビルドすること。**
        """
        if self.value_net is None:
            return super()._eval(s, pi)
        if s.outcome is not None:
            if s.outcome == DRAW:
                return 0.5
            return 1.0 if s.outcome == pi else 0.0
        import numpy as np
        from .encode import encode
        net = load_net(self.value_net)
        # v6（D-124）: 信念の要約は自分の想定デッキ表（`opp_decklist`）で作る（Rust の `net_value` と同じ）
        return float(net.value_of(np.asarray(encode(observe(s, pi), pi, self.opp_decklist), np.float32)))

    @staticmethod
    def _sig(u):
        """重複除去用の局面署名。アクションフェイズで区別すべき要素だけを含む。"""
        p0, p1 = u.players[0], u.players[1]
        return (u.phase, u.turn_no, u.used_charge, u.used_switch, u.used_levelup,
                p0.life, p1.life, len(p0.action_deck), len(p1.action_deck),
                tuple(sorted(p0.hand)), tuple(sorted(p0.concerto)),
                tuple(tuple(sl.stack) for sl in p0.slots),
                tuple(sorted(p1.hand)), tuple(sorted(p1.concerto)),
                tuple(tuple(sl.stack) for sl in p1.slots))
