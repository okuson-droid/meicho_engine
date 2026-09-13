"""貪欲エージェント（1手先読み＋評価関数）。

rules_draft.md v0.10 準拠。各合法手を実際に `apply` して、
結果の局面を評価関数で採点し、最大のものを選ぶ。

## ヒューリスティックとの違い

規則を書き下すのではなく、**評価関数ひとつで全フェイズをカバーする**。
評価関数はフェーズ4でそのまま再利用できる（MCTSのロールアウト方策・価値の初期値）。

## 同時手番の扱い（このゲーム固有の難所）

対抗ステップ (§6.4(1)) は同時提出のため、「自分の手を指した結果の局面」が
**相手の手を仮定しないと定義できない**。本実装は決定化（determinization）で扱う:

1. 相手の手札を**未公開のカードから標本抽出**する（相手の手札は覗かない）
2. 標本ごとに相手の行動をヒューリスティック方策で決める
3. 標本を平均して各手の価値とする

相手のデッキリストは既知として扱う（スターターデッキは公開情報であり、
実戦でも相手のデッキは分かっている場合が多い）。未指定なら自分と同じと仮定する。

## 覗かない制約

評価関数は次の情報しか参照しない。
- 自分: すべて（手札・デッキ枚数・協奏・トラッシュ・キャラ）
- 相手: ライフ・**手札枚数**・協奏・トラッシュ・アクションエリア・キャラ・デッキ枚数

ただし評価関数が覗かないだけでは不十分である（レビュー 2026-08-23 §3.4）。
**先読みの過程**（`apply` / `_settle`）はドロー効果を実際のデッキ順序で解決するため、
素朴に実装すると「次に引く札を知った上で」手を比較してしまう。デッキ順序は
どちらのプレイヤーにとっても隠蔽情報である (§4 / §10) から、これは覗き見にあたる。

対処 (D-026): 先読みに入る前に必ず `_determinize` を通し、
**相手の手札の標本抽出と両者のデッキ順序のシャッフルを同時に行う**。
単独決定フェイズでは1つの決定化局面を作り、その上で全候補を比較する
（候補間で「引く札」が共通になるため、比較は公正なまま）。

`test_greedy_does_not_peek_at_opponent_hand` と、実対局リプレイ上の
`test_nopeek_audit.py`（全実決定ノードで隠蔽情報を差し替え）で担保している。

## D-065 便 1 のつまみ（すべて既定で無効・挙動不変）

「V は伸びたのに、V を使う側（探索）が追いついていなかった」という診断
（`STRENGTH_REVIEW_20260902.md`）への手当てである。既定値では一手も変わらない
（`tests/test_d065.py::test_defaults_unchanged_d065`）。

| 引数 | 何をするか | 狙い |
|---|---|---|
| `policy_net` / `policy_scope` | 先読み中の代打ち（と担当外フェイズの実際の手）を学習した方策 π にする | 輪の不動点は代打ちの質で決まる（A-5'） |
| `choice_phases` / `solo_samples` | 選択フェイズと手札上限の捨て札も探索の担当にし、決定化を複数本にする | 決定の約 27% が H の規則のままだった（A-1） |
| `align_leaves` / `align_rollout` | 対抗・連撃・選択の葉を「次に自分がターンプレイヤーになるターン」まで進めてから採点する | 葉を V の学習分布の中に置く（A-2） |
| `tau` | 根の手を softmax(値/tau) で抽選する | 対人アプリの手の多様性（B-3） |

Rust 側（`rust/src/agents.rs`）には `reeval_samples`（選んだ手を別の決定化で
取り直す・記録形式 v3 の `fresh`）もあるが、**Python には口を作っていない**
（記録は Rust でしか取らないため）。したがって `reeval_samples > 0` の記録は
乱数の並びが変わり、Python 版では毎手再現できない（D-065 便 1 の報告参照）。
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass

from .cards import ACTION_CARDS, CHARA_CARDS, Color
from .buckets import stratify_top
from .engine import apply, apply_owned, decision_players, legal_actions, observe
from .heuristic import HeuristicAgent, Params, live_reds
from .oppmodel import OpponentModel
from .state import DRAW, Phase
from .worlds import enumerate_hands, world_counts

WIN = 10_000.0

# --- 相手モデルを学習した方策に差し替える口（D-057 / D-058） ----------------
# Rust 側 `agents.rs` の `opp_policy_net` / `opp_policy_root_only` と同じもの。
# **Python が真実源**であり、`tests/test_drl.py` が「同じネット・同じシードで
# 両者が同じ手を選ぶ」ことを固定する。
# ネットはパスをキーに 1 回だけ読む（Rust の `net::load` の cache と同じ約束）。
_NET_CACHE: dict = {}


def load_net(path: str):
    """モデル JSON を読む（プロセス内でパスごとに 1 回だけ）。

    名前だけなら `results/models/` から探す（`drlnet.resolve_model`）。
    """
    net = _NET_CACHE.get(path)
    if net is None:
        from .drlnet import Net, resolve_model
        net = _NET_CACHE[path] = Net.load(resolve_model(path))
    return net


def forget_net(path: str) -> None:
    """同じパスを上書きしたときに読み直させる（`meicho_rs.net_forget` と対）。"""
    _NET_CACHE.pop(path, None)


# 代打ち π を効かせる範囲（D-065 A-5'・`D065_IMPLEMENTATION_PLAN.md` §2.2）
# `proxy_lite` は速度の手当て（§9-4 (a)）: 代打ちのうち**相手のアクションフェイズと
# 自分の対抗の提出だけ**を π にし、残り（自分の連撃・選択・手札上限、相手の連撃・選択など）は
# H に戻す。π を読む回数が減るぶん速い。
POLICY_SCOPES = ("all", "proxy", "fallback", "proxy_lite")
# 葉の整列の止め方（D-065 A-2 と §2.4 の別解）
ALIGN_STOPS = ("my_turn", "turn_end")
# A-9: regret matching の反復回数（試作 `experiments/proto_matrix_clash.py` と同じ 400）。
# つまみにはしない。Rust の写しも同じ定数を使う。
NASH_ITERS = 400
# 便 A（D-071）: 「その手で相手のライフを 0 にできた」と見なす葉の値のしきい値。
# `value_net` の規約（決着済み = 1.0 / 0.0 / 0.5）に合わせた `1.0 - 1e-9` である。
# Rust の写しも同じ定数を使う。つまみにはしない。
LETHAL_EPS = 1e-9


def nash_col(matrix, iters: int = NASH_ITERS) -> list:
    """行列ゲームを regret matching で解き、**列側（相手）の平均戦略**を返す。

    行 = 自分（最大化）・列 = 相手（最小化）。乱数を一切引かない決定的な手続きである。
    足す順序まで Rust の写しと揃える（浮動小数の丸めを一致させるため）。
    """
    m = len(matrix)
    k = len(matrix[0]) if m else 0
    if m == 0 or k == 0:
        return []
    if k == 1:
        return [1.0]
    rr = [0.0] * m          # 行側の累積後悔
    rc = [0.0] * k          # 列側の累積後悔
    sc = [0.0] * k          # 列側の戦略の累積（平均戦略の分子）
    for _ in range(iters):
        pos = [x if x > 0.0 else 0.0 for x in rr]
        tot = sum(pos)
        pr = [x / tot for x in pos] if tot > 0.0 else [1.0 / m] * m
        pos = [x if x > 0.0 else 0.0 for x in rc]
        tot = sum(pos)
        pc = [x / tot for x in pos] if tot > 0.0 else [1.0 / k] * k
        u_r = [sum(matrix[i][j] * pc[j] for j in range(k)) for i in range(m)]
        u_c = [sum(pr[i] * matrix[i][j] for i in range(m)) for j in range(k)]
        v = sum(pr[i] * u_r[i] for i in range(m))
        for i in range(m):
            rr[i] += u_r[i] - v
        for j in range(k):
            rc[j] += v - u_c[j]
            sc[j] += pc[j]
    return [x / iters for x in sc]


def soft_pick(values, tau: float, rng) -> int:
    """softmax(値/tau) で 1 つ選ぶ。`tau <= 0` なら最大（同点は最初）。

    Rust 版 `agents.rs::soft_pick` の写しである（D-065 §2.6）。**Python が真実源**だが、
    この関数だけは Rust に先にあったものを持ち込んだので、両者の一致を
    `tests/test_d065.py::test_tau_python_matches_rust` が固定する。

    乱数は「tau > 0 かつ候補が 2 つ以上」のときだけ `rng.random()` を 1 回消費する。
    したがって `tau=0`（既定）では一切消費せず、既定の挙動は変わらない。
    """
    if len(values) <= 1:
        return 0
    if tau <= 0.0:
        return max(range(len(values)), key=lambda i: values[i])
    m = max(values)
    ws = [math.exp((v - m) / tau) for v in values]
    tot = sum(ws)
    r = rng.random() * tot
    acc = 0.0
    for i, w in enumerate(ws):
        acc += w
        if r <= acc:
            return i
    return len(values) - 1


def _act_display_name(s, pi: int, a: dict) -> str:
    """記録に残す手の表示名（D-7）。提出はカード名、それ以外は行動の種別。

    `tests/test_d065.py::_submitted_name` と**同じ規則**である。ここは記録の
    見出しにしか使わないので、打ち方には一切影響しない。
    """
    if a.get("type") != "submit":
        return str(a.get("type"))
    try:
        return ACTION_CARDS[s.players[pi].hand[a["hand"]]].name
    except Exception:                                   # noqa: BLE001
        return "submit"


@dataclass
class Weights:
    """評価関数の重み。自己対戦で調整する。"""

    life: float = 1.0        # ライフ差（勝利条件そのもの）
    concerto: float = 0.8    # 協奏エリア差（コストを払えることが土台）
    hand: float = 0.5        # 手札枚数差
    live_red: float = 0.4    # 使用可能な赤の枚数（自分のみ。相手は覗けない）
    # レベル差は 0.0 が最適だった（1.0 だと対ヒューリスティック 0.250、0.0 で 0.505）。
    # レベルアップの手札コストと釣り合わず、悪いタイミングで上げてしまうため。
    level: float = 0.0       # キャラの合計レベル差
    resource: float = 0.05   # デッキ+トラッシュの残量差


def _levels(p) -> int:
    return sum(CHARA_CARDS[sl.stack[-1]].level for sl in p.slots if sl.stack)


def evaluate(s, pi: int, w: Weights) -> float:
    """局面を pi の視点で採点する。相手の手札の**中身**は参照しない。"""
    if s.outcome is not None:
        if s.outcome == DRAW:
            return 0.0
        return WIN if s.outcome == pi else -WIN
    me, opp = s.players[pi], s.players[1 - pi]
    v = w.life * (me.life - opp.life)
    v += w.concerto * (len(me.concerto) - len(opp.concerto))
    v += w.hand * (len(me.hand) - len(opp.hand))
    v += w.live_red * live_reds(s, pi)
    v += w.level * (_levels(me) - _levels(opp))
    v += w.resource * ((len(me.action_deck) + len(me.trash))
                       - (len(opp.action_deck) + len(opp.trash)))
    return v


class GreedyAgent:
    """1手先読み＋評価関数。同時手番は決定化で扱う。"""

    def __init__(self, seed: int, weights: Weights = None,
                 opp_decklist: list = None, samples: int = 6,
                 rollout_depth: int = 24, phases: set = None,
                 use_history: bool = False, prior_strength: float = 8.0,
                 opp_policy_net: str = None, opp_policy_root_only: bool = False,
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
        # phases: 貪欲に判断するフェイズ。それ以外はヒューリスティックに委ねる。
        # 既定は対抗＋連撃。フェイズ別の切り分け（GREEDY_NOTES.md）で、
        # 貪欲は対抗ステップで強く（0.675）、アクションフェイズで弱い（0.338）ためである。
        self.phases = phases if phases is not None else {
            Phase.CLASH_SUBMIT, Phase.RUSH}
        # D-065 A-1: 選択フェイズ（レベルアップの捨て札・支払うか受けるか・任意効果・
        # 公開枚数・切り替え先）と手札上限の捨て札も探索の担当にする。
        # マリガンとリーダー選択は対象外のまま（`act` の除外は残す）。
        self.choice_phases = choice_phases
        if choice_phases:
            self.phases = set(self.phases) | {Phase.CHOICE,
                                              Phase.TURN_END_DISCARD}
        self.rng = random.Random(seed)
        self.w = weights or Weights()
        self.opp_decklist = opp_decklist
        self.samples = samples
        self.rollout_depth = rollout_depth
        # 準備段階と、非担当フェイズはヒューリスティックに委ねる
        self.fallback = HeuristicAgent(seed, Params())
        # 相手の行動モデル (B-3 / D-031)。観測が無いうちは fallback に縮退する。
        self.opp_model = OpponentModel(self.fallback, prior_strength,
                                       enabled=use_history, seed=seed)
        # 相手モデルを学習した方策に差し替える (D-057/058)。None なら従来どおり。
        self.opp_policy_net = opp_policy_net
        self.opp_policy_root_only = opp_policy_root_only
        # --- D-065 便 1 のつまみ（すべて既定で無効・§1-1） -------------------
        # A-5': 代打ちを π にする。`policy_scope` はその範囲。
        #   "all"      : 探索の中の代打ちと、担当外フェイズの実際の手の両方（Rust の従来どおり）
        #   "proxy"    : 代打ちだけ（担当外フェイズの実際の手は H のまま）
        #   "fallback" : 担当外フェイズの実際の手だけ（代打ちは H／相手モデルのまま）
        if policy_scope not in POLICY_SCOPES:
            raise ValueError(f"unknown policy_scope {policy_scope!r}"
                             f"（{list(POLICY_SCOPES)} のいずれか）")
        self.policy_net = policy_net
        self.policy_scope = policy_scope
        # A-1: `_solo` の決定化を何本の平均にするか（1 = 従来どおり）
        self.solo_samples = solo_samples
        # A-2: 対抗・連撃・選択の葉を「次に自分がターンプレイヤーになるターン」まで揃える
        self.align_leaves = align_leaves
        self.align_rollout = align_rollout
        # 葉をどこまで運ぶか。"my_turn" は次に自分がターンプレイヤーになるターン（A-2 の本案）、
        # "turn_end" は**いま進行中のターンが終わるところ**まで（§2.4 の別解＝計画探索の
        # `to_clash` の葉と同じ地点）。相手のターンに入らないぶん、H で想像する距離が短い。
        if align_stop not in ALIGN_STOPS:
            raise ValueError(f"unknown align_stop {align_stop!r}"
                             f"（{list(ALIGN_STOPS)} のいずれか）")
        self.align_stop = align_stop
        # B-3: 根の手を softmax(値/tau) で抽選する温度（0 なら最良手・既定）
        self.tau = tau
        # A-8（D-065 §12・`HUMAN_GAMES_20260903_NOTES.md`）: 対抗の相手モデルを広げる。
        # 0 なら従来どおり「決定化ごとに π₀ の最尤 1 手」だけを見る。0 より大きいと
        # 「(1−opp_mix)·最尤 ＋ opp_mix·相手の合法手の等重み」で期待値を取る。
        # なぜ要るか: π₀ は自己対戦から学んだので「安い赤や緑を対抗に出す」列にほぼ 0 を与える。
        # マスターはその外側の手（燃える闘志・鉤縄）で 2 局とも勝った。列が評価に無ければ、
        # どれだけ探索を深くしてもその負けは見えない。
        if not 0.0 <= opp_mix <= 1.0:
            raise ValueError(f"opp_mix は 0..1（受け取った値 {opp_mix}）")
        self.opp_mix = opp_mix
        # A-9（`D065_NOTES.md` の A-9・D-065 §12 の続き）: 均衡を土台にした「δ 制限つきの搾取」。
        # 0 なら従来どおり（挙動不変）。0 より大きいと対抗の決定で
        #   (1) 決定化ごとに 自分×相手 の行列を作り、regret matching で
        #       **相手の均衡戦略**を解き、その期待値（＝均衡値）を合計する
        #   (2) 均衡値が最大から `nash_delta` 以内の手を候補にし、
        #       その中で**相手の合法手が等重み（＝うっかりする相手）**での
        #       期待値が最大の手を選ぶ
        # なぜこの形か: 均衡だけでは搾取しない（相手が最尤外の手を撃っても罰しない）。
        # opp_mix のように全部を等重みで見ると搾取が無制限になり、均衡どおり動く相手に負ける。
        # δ は「均衡から最大どれだけ譲るか」の上限そのものである。
        if nash_delta < 0.0:
            raise ValueError(f"nash_delta は 0 以上（受け取った値 {nash_delta}）")
        if nash_delta > 0.0 and opp_mix > 0.0:
            raise ValueError("nash_delta と opp_mix は同時に使えない"
                             "（相手モデルの決め方が二重になるため）")
        if nash_delta > 0.0 and tau > 0.0:
            raise ValueError("nash_delta と tau は同時に使えない"
                             "（候補の絞り込みと抽選が二重になるため）")
        self.nash_delta = nash_delta
        # 文献計画 便 A（前半）・D-071: 「詰みが見えるときだけ、相手を等重みに見る」。
        # 0（既定）なら 1 ビットも変わらない。0 より大きいと、対抗の決定化ごとに
        # 自分×相手の行列を全部埋め、
        #   lethal_frac[i] = 「手 i が相手のどの列に対しても詰みになった列の割合」の平均
        # を作り、`max_i lethal_frac[i] >= lethal_uniform` のときだけ
        # **相手の合法手を等重み**で見た期待値（= opp_mix=1.0 と同じ値）で選ぶ。
        # そうでない対抗は従来どおり π₀ の最尤 1 手で選ぶ。
        #
        # なぜこの形か: 2026-09-03 の 2 局は「詰みの烈火を持ちながら π₀ が
        # 『相手は必ず青で受ける』と読んだ」ことで落ちた。`opp_mix=1.0` はこれを直すが、
        # **普段の対抗の 4 回に 1 回**を変えてしまう（便 D M2 の実測 0.25）。
        # 広げる場面を「詰みが取れる可能性のある対抗」だけに絞るのが本つまみである。
        #
        # **注意（値の尺度）**: 詰みの判定は `_score_clash` の値が
        # `1.0 - 1e-9` 以上かで行う。これは `value_net` があるとき（= champion）の規約
        # 「決着済みの局面は 1.0 / 0.0 / 0.5」に依存している。`value_net` が無い素の
        # `evaluate`（±WIN = ±10000 の尺度）では 1.0 は詰みを意味しないので、
        # このつまみは `value_net` を持つ設定でだけ意味を持つ（`LIT_NOTES.md` 便 A の判断①）。
        if not 0.0 <= lethal_uniform <= 1.0:
            raise ValueError(f"lethal_uniform は 0..1（受け取った値 {lethal_uniform}）")
        if lethal_uniform > 0.0 and opp_mix > 0.0:
            raise ValueError("lethal_uniform と opp_mix は同時に使えない"
                             "（相手モデルの決め方が二重になるため）")
        if lethal_uniform > 0.0 and nash_delta > 0.0:
            raise ValueError("lethal_uniform と nash_delta は同時に使えない"
                             "（相手モデルの決め方が二重になるため）")
        self.lethal_uniform = lethal_uniform
        # 文献計画 便 C 段 C-1（II-7 (a)・D-077）: **スキャンで見た札を決定化に必ず入れる。**
        # 0（既定）なら 1 ビットも変わらない。
        #
        # なぜ要るか: 「スキャン」でこちらが見た相手の手札は**公開情報ではないが、こちらは
        # 正当に知っている情報**である（`observe` が `opp.hand_known` として返す。D-023）。
        # ところが決定化はこれを使っておらず、**見えている札を含まない手札を大量に仮定していた**。
        # 便 M の実測では決定の 29.2% にスキャンの情報があり、そこで候補は 8〜20 分の 1 に縮む。
        # 便 C 段 C-0 の実測では、6 枚見えていて整合する手札が 48 通りしかない局面で、
        # 探索は 12,696 通りから 24 本引いて一度も真の手札に当たっていなかった。
        #
        # **覗き見ではない**（D-026）: 使うのは `observe(s, pi)["opp"]["hand_known"]` だけで、
        # `s.peeked_opp_hand` や相手の真の手札には触れない。`hand_known` は
        # 「覗いた時点のスナップショット ∩ いまの相手の手札」であり、手札から出るルートは
        # すべて公開情報なので、積を取っても見ていない情報は漏れない（`engine.observe` の註）。
        self.known_hand = bool(known_hand)
        # 文献計画 便 C 段 C-2（II-8・D-077）: **決定化に「もっともらしさ」の重みを付ける。**
        # 0（既定）なら 1 ビットも変わらない（重みが全部ちょうど 1.0 になる道を通る）。
        #
        # なぜ要るか: 段 C-1 で「引き方は公平になった」（TSSR プール比 0.449 → 1.019）。
        # しかし公平とは「ありうる手札を平等に扱う」ことであって、**相手が実際に持ちやすい手札を
        # 当てにいく**こととは違う。段 C-0 の実測では、相手がその対抗で出す札は K=24 の候補に
        # 0.996 の割合で入っていた——札を思いつけないのではなく、**思いついた上で
        # 「相手はそれを出さない」と重みを置いていない**のが読み違いの正体である。
        #
        # 何をするか: 相手が**直近の対抗で実際に出した札**を思い出し、決定化 w ごとに
        # 「w が仮定する手札を持っていたら、相手モデル π₀ はその札を出しただろうか」を
        # 確率で測る。出しそうな世界には重く、出しそうにない世界には軽く。
        #   η(w) = Π_t p_{T,ε}(c_t | 手札_w^t)      L = 直近 `weight_lookback` 回まで
        #   p_{T,ε} = (1−ε)·softmax(π₀ のロジット / T) + ε/|合法手|
        #   最終の重み = (1−u)·η の正規化 ＋ u·(1/K)      u = 1 − world_weight
        #
        # **消去ではなく重み付けである**（§7 の 4）。floor ε と一様分 u があるので
        # どの世界の重みも 0 にならない——「相手はこの札を持っていたら必ずこう出す」という
        # 価値判断で世界を消すことは、硬い制約フィルタ（II-7）とは別物であり、やらない。
        if not 0.0 <= world_weight <= 1.0:
            raise ValueError(f"world_weight は 0..1（受け取った値 {world_weight}）")
        if weight_temp <= 0.0:
            raise ValueError(f"weight_temp は 0 より大きい（受け取った値 {weight_temp}）")
        if not 0.0 <= weight_floor <= 1.0:
            raise ValueError(f"weight_floor は 0..1（受け取った値 {weight_floor}）")
        if weight_lookback < 0:
            raise ValueError(f"weight_lookback は 0 以上（受け取った値 {weight_lookback}）")
        if world_weight > 0.0 and opp_policy_net is None:
            # π₀ が無ければ「出しそうか」を測る物差しが無い。黙って等重みに落ちると
            # 「重みを付けたのに効かない」測定になるので、ここで塞ぐ（便 A の判断①と同じ形）。
            raise ValueError(
                "world_weight は opp_policy_net と組でしか使えない"
                "（重みが π₀ の到達確率だから）")
        self.world_weight = float(world_weight)
        self.weight_temp = float(weight_temp)
        self.weight_floor = float(weight_floor)
        self.weight_lookback = int(weight_lookback)
        # 相手の対抗提出の履歴 [(公開局面, 出した札 or None, そのときの相手の公開領域)]。
        # **相手の手札も山札も入らない**（T-C-7 が固定する）。
        self._opp_history: list = []
        self._pending_clash = None     # 自分が提出した時点の公開局面（結果待ち）
        # 文献計画 便 C 段 C-3（II-9・D-077 追記 3）: **終盤は決定化をやめて全部数える。**
        # 0（既定）なら 1 ビットも変わらない（列挙の枝に入らない）。
        #
        # なぜ要るか: 決定化は「ありうる手札から K 本引く」近似である。終盤は
        # ありうる手札の数 W そのものが小さくなる（便 M の実測で決定の 14.3% が W ≤ 64）。
        # そこまで小さいなら**引かずに全部見た方が速くて正確**であり、標本の揺れも消える。
        #
        # 何をするか: 決定の入口で W を数え（`hand_known` 込み）、W ≤ `endgame_enum` なら
        # 決定化 K 本の代わりに**整合する手札を全列挙**して重み＝多重度（物理的な配り方の数）で
        # 使う。本数が多すぎるときは重みの大きい順に `endgame_eval` 本まで（W ≤ eval なら厳密）。
        # `_plan` の 1 手目だけは**投票**でも決める: 本ごとの最良の 1 手目に重みを載せ、
        # 勝った手の重みの割合を信頼度 C とする。C ≥ `endgame_conf` ならその手、
        # C < `endgame_conf` なら従来どおり加重平均の最良手に戻す（安全弁）。
        if endgame_enum < 0:
            raise ValueError(f"endgame_enum は 0 以上（受け取った値 {endgame_enum}）")
        if endgame_eval < 1:
            raise ValueError(f"endgame_eval は 1 以上（受け取った値 {endgame_eval}）")
        if not 0.0 <= endgame_conf <= 1.5:
            raise ValueError(f"endgame_conf は 0..1.5（受け取った値 {endgame_conf}）")
        if endgame_enum > 0 and opp_decklist is None:
            # 列挙は「相手のデッキリストが分かっている」ことに全面的に寄りかかる（§7 の 14）。
            # 知らないまま「自分と同じデッキ」を仮定して数え上げると、相手のデッキが違うとき
            # **真の手札を 1 本も含まない**世界だけを見て確信する。黙って落とさずここで塞ぐ。
            raise ValueError(
                "endgame_enum は opp_decklist と組でしか使えない"
                "（列挙が相手のデッキリストに寄りかかっているため）")
        self.endgame_enum = int(endgame_enum)
        self.endgame_eval = int(endgame_eval)
        self.endgame_conf = float(endgame_conf)
        # 文献計画 便 C 段 C-4（D-077 追記 4）: **ドロー結果のバケット化。**
        # 0（既定）なら `stratify_top` を呼ばないので、乱数の消費順も並びも従来と同一である。
        #
        # 何をするか: 決定化 K 本の山札の**上位 3 枚**を「コスト帯 × 色」の層で散らす
        # （`meicho/buckets.py`）。自分の山札にも相手の山札にも同じ扱いをする。
        #
        # なぜ要るか: K 本を一様に混ぜると、K 本の「次に引く札」が偶然かたよる。
        # 段 C-1・C-3 で直したのは「相手の手札の集合」の側であって、
        # **自分と相手がこれから引く札の幅**はまだ一様な引き直しに任せたままだった。
        if int(draw_buckets) < 0:
            raise ValueError(f"draw_buckets は 0 以上（受け取った値 {draw_buckets}）")
        self.draw_buckets = int(draw_buckets)
        # 文献計画 便 A 後半（A-2・D-082）: **束ねた対抗ゲームを解いて提出分布を決める。**
        # 0（既定）なら 1 ビットも変わらない。
        #
        # 従来は決定化 K 本の**それぞれ**で相手の最尤 1 手を当てて期待値を取っていた。
        # これは「K 本それぞれで別の手を出してよい」という思い込み（strategy fusion）で、
        # 9/3 の 2 敗の形そのものである。A-2 は x（提出分布）を K 本に共通に置いて
        #
        #     max_x Σ_k w_k · min_{y_k} xᵀ A_k y_k
        #
        # を解き（`meicho/bundle.py`）、**平均戦略の最大**の手を出す。
        #
        # `bundle_p` は「現行の評価」と「最悪想定」の混ぜ方である:
        #
        #     A_k[i][j] = p · （π₀ の最尤 1 手 j₀ に対する値）＋ (1−p) · （相手の手 j に対する値）
        #
        # **p = 1.0 は行列の全列が同値**になるので、現行と一手・一点まで同じに落ちる
        # （`tests/test_lit_a2.py::T-A2-2`）。そのとき列は 1 本しか採点しない——
        # **採点の回数と乱数の消費まで既定の道と揃える**ためである。
        # **p = 0（純粋な最悪想定）は候補にしない**: A-9 の δ=0 で
        # 「相手を強く見積もりすぎて詰みを逃す」が実測されている（計画書 §3.1）。
        if not 0.0 <= bundle_p <= 1.0:
            raise ValueError(f"bundle_p は 0..1（受け取った値 {bundle_p}）")
        for _name, _v in (("lethal_uniform", lethal_uniform), ("opp_mix", opp_mix),
                          ("nash_delta", nash_delta), ("tau", tau)):
            if bundle_p > 0.0 and _v > 0.0:
                raise ValueError(f"bundle_p と {_name} は同時に使えない"
                                 "（対抗の集約規則が二重になり、何が効いたか言えなくなるため）")
        self.bundle_p = float(bundle_p)
        self._worlds_enumerated = False   # 直前の `_worlds` が列挙だったか
        self._endgame_uses = 0            # 列挙に入った決定の数（検査と診断用）
        self._last_endgame = None         # 直前の `_plan` の投票の記録（打ち方には効かない）
        # D-7（文献計画 便 D）: 直前の対抗で見比べた候補と点数。**打ち方には一切効かない。**
        # 対人アプリが記録に残し、便 F（相手の型）で「AI が何を迷って何を選んだか」と
        # 「マスターが実際に何を出したか」を突き合わせる材料にする。
        self.last_clash = None

    # -- ネットの方策で 1 手選ぶ（D-065 §2.2） ----------------------------
    def _policy_pick(self, net, s, q, tau: float = 0.0, rng=None) -> dict:
        """ネットの方策で手を選ぶ。`tau=0` なら最良手（同点は最初）で乱数を消費しない。

        Rust の `Greedy::policy_pick` と同じ（`soft_pick` まで含めて同じ順序で引く）。
        """
        acts = legal_actions(s, q)
        if len(acts) == 1:
            return acts[0]
        import numpy as np
        from .encode import action_code, encode
        ob = observe(s, q)
        x = np.asarray(encode(ob, q), np.float32)
        scores = [float(v) for v in
                  net.policy_scores(x, [action_code(ob, a) for a in acts])]
        return acts[soft_pick(scores, tau, rng if rng is not None else self.rng)]

    # -- 相手モデル（学習した方策で差し替えうる） -------------------------
    def _opp_act(self, s, q, allow_net: bool = True) -> dict:
        """相手の手を決める。`opp_policy_net` があれば**対抗の提出だけ**ネットの方策。

        相手モデルが働くのは対抗の提出だけ（`OpponentModel.act` 自身がそれ以外を
        固定方策に落とす）なので、差し替わるのもそこだけである。
        `allow_net=False`（`opp_policy_root_only` のときの葉のロールアウト）では読まない。
        同点は最初の手を選ぶ（Rust の `soft_pick(tau=0)` と同じ）。乱数は消費しない。
        """
        if allow_net and self.opp_policy_net is not None and s.phase == Phase.CLASH_SUBMIT:
            # 抽選の乱数は fallback（共通乱数の対象）。tau=0 なので実際には消費しない。
            return self._policy_pick(load_net(self.opp_policy_net), s, q,
                                     0.0, self.fallback.rng)
        return self.opp_model.act(s, q)

    # -- 相手の手札の標本抽出 ---------------------------------------------
    def _unseen(self, s, pi) -> list:
        """相手の手札にありうるカードの候補（公開情報のみから構成する）。"""
        opp = s.players[1 - pi]
        me = s.players[pi]
        deck = self.opp_decklist
        if deck is None:      # 未指定なら自分と同じデッキと仮定する
            deck = (me.action_deck + me.hand + me.concerto
                    + me.trash + me.action_area)
        pool = Counter(deck)
        for cid in opp.concerto + opp.trash + opp.action_area:   # 公開領域
            if pool[cid] > 0:
                pool[cid] -= 1
        out = []
        for cid, n in pool.items():
            out += [cid] * n
        return out

    def _known_in_hand(self, s, pi) -> list:
        """`known_hand` が立っているとき、相手の手札に必ず入れる札（多重集合）。

        **`observe` の返す欄だけを見る**（D-026 の覗き見禁止）。つまみが 0 なら空を返すので、
        呼ぶ側は「空なら従来どおり」と書ける。
        """
        if not self.known_hand:
            return []
        return list(observe(s, pi)["opp"]["hand_known"])

    @staticmethod
    def _minus_multiset(pool: list, take: list) -> list:
        """多重集合の引き算。`pool` の並びは保ったまま `take` を 1 枚ずつ取り除く。

        `take` に `pool` へ無い札があれば **黙って無視せず落とす**——それは
        「見えている札が未公開の候補に入っていない」という食い違いで、
        起きるとしたら `_unseen` か `hand_known` のどちらかが壊れている（§3.1）。
        """
        left = Counter(take)
        out = []
        for cid in pool:
            if left.get(cid, 0) > 0:
                left[cid] -= 1
            else:
                out.append(cid)
        if any(v > 0 for v in left.values()):
            missing = sorted(c for c, v in left.items() if v > 0)
            raise ValueError(
                f"hand_known の札が未公開の候補に無い: {missing}"
                "（_unseen か observe の hand_known が壊れている）")
        return out

    # -- 段 C-2: 相手の対抗提出の履歴（公開情報だけ） ----------------------
    def _public_frame(self, s, pi):
        """相手の手札と山札の**中身を落とした**局面の写し（履歴に積む器）。

        残すのは公開情報だけである（§10）:
        - 相手の手札は**空**にする。重みを測るときに「その世界が仮定する手札」を入れ直す
        - 相手の山札は**枚数だけ**残す（枚数は公開情報）。中身は同じ札で埋める——
          π₀ の入力に入るのは `deck_count` だけなので、中身は答えに効かない
        - 自分の側は触らない（自分の情報は自分のものである）

        **相手の真の手札も山札の並びも、この写しには入らない**（T-C-7 が固定する）。
        """
        t = s.clone()
        opp = t.players[1 - pi]
        n_deck = len(opp.action_deck)
        filler = self._deck_filler(s, pi)
        opp.hand = []
        opp.action_deck = [filler] * n_deck if filler is not None else []
        return t

    def _deck_filler(self, s, pi):
        """山札の枚数合わせに使う札（中身は答えに効かない・並びは決定的）。"""
        deck = self.opp_decklist
        if deck is None:
            me = s.players[pi]
            deck = (me.action_deck + me.hand + me.concerto
                    + me.trash + me.action_area)
        return sorted(deck)[0] if deck else None

    @staticmethod
    def _opp_public_cards(s, pi):
        """相手が手札から出し終えた札（公開領域）の多重集合。"""
        opp = s.players[1 - pi]
        return Counter(opp.concerto + opp.trash + opp.action_area)

    def _note_history(self, s, pi) -> None:
        """`act` の入口で呼ぶ。**前回の対抗の結果**が公開されていれば履歴に積む。

        相手が何を出したかは `observe` の `last_clash_cards`（公開情報・§6.4(1)-3）から取る。
        **相手の手札を覗いて調べるのではない。**
        """
        if self.world_weight <= 0.0 or self._pending_clash is None:
            return
        if s.phase == Phase.CLASH_SUBMIT:
            return                       # まだ解決していない（同じ対抗の中）
        frame, before = self._pending_clash
        self._pending_clash = None
        cid = observe(s, pi)["last_clash_cards"][1]     # 相手が出した札（None = パス）
        self._opp_history.append((frame, cid, before))
        if self.weight_lookback >= 0:
            del self._opp_history[:max(0, len(self._opp_history) - self.weight_lookback)]

    def _remember_clash(self, s, pi) -> None:
        """自分が対抗で提出する時点の公開局面を控える（結果は次の `act` で確定する）。"""
        if self.world_weight <= 0.0:
            return
        self._pending_clash = (self._public_frame(s, pi),
                               self._opp_public_cards(s, pi))

    # -- 段 C-2: 決定化の重み（II-8） --------------------------------------
    def _reach_prob(self, frame, pi, hand, cid) -> float:
        """「相手がその手札を持っていたら、π₀ は `cid` を出しただろうか」の確率。

        `p_{T,ε} = (1−ε)·softmax(ロジット / T) + ε/|合法手|`。
        `cid` が None ならパスの確率。同じ札が 2 枚あるときは**その札を出す合法手すべての和**
        （事象は「その札を出した」であって「その番号の札を出した」ではない）。
        """
        import numpy as np
        from .encode import action_code, encode
        q = 1 - pi
        u = frame.clone()
        u.players[q].hand = list(hand)
        acts = legal_actions(u, q)
        if not acts:
            return 1.0
        ob = observe(u, q)
        net = load_net(self.opp_policy_net)
        x = np.asarray(encode(ob, q), np.float32)
        scores = [float(v) for v in
                  net.policy_scores(x, [action_code(ob, a) for a in acts])]
        T = self.weight_temp
        mx = max(v / T for v in scores)
        ex = [math.exp(v / T - mx) for v in scores]
        tot = sum(ex)
        eps = self.weight_floor
        n = len(acts)
        p = 0.0
        for a, e in zip(acts, ex):
            hit = (a["type"] == "pass" if cid is None
                   else (a["type"] == "submit" and u.players[q].hand[a["hand"]] == cid))
            if hit:
                p += (1.0 - eps) * (e / tot) + eps / n
        return p

    def world_weights_for(self, s, pi, hands) -> list:
        """決定化 K 本の重み（合計 1）。**つまみ 0 のときは呼ばない。**

        `hands` は本ごとの「相手の手札」。履歴が空なら等重みになる（＝挙動不変）。
        """
        k = len(hands)
        if k == 0:
            return []
        u = 1.0 - self.world_weight          # 一様分の温存率
        if not self._opp_history:
            return [1.0 / k] * k
        now_public = self._opp_public_cards(s, pi)
        etas = []
        for hand in hands:
            eta = 1.0
            for frame, cid, before in self._opp_history:
                # 手札_w^t ＝「w が仮定するいまの手札」＋「t 以降に相手が手札から出した札」。
                # **上限の近似**である（t より後に引いた札も「t に持っていた」と扱う。§7 の 6）。
                since = now_public - before
                seq = list(hand) + [c for c, n in sorted(since.items()) for _ in range(n)]
                eta *= self._reach_prob(frame, pi, seq, cid)
            etas.append(eta)
        tot = sum(etas)
        if tot <= 0.0:
            return [1.0 / k] * k
        return [(1.0 - u) * (e / tot) + u / k for e in etas]

    def _worlds(self, s, pi, n: int):
        """決定化 n 本と、その重み（つまみ 0 なら**ちょうど 1.0 が n 個**）。

        **重みが 1.0 のとき掛け算は値を変えない**（IEEE754 で `1.0 * x == x`）ので、
        つまみ 0 の道は一手一点まで従来と同じである。
        乱数の消費順も変わらない——`_determinize` が引くのは `self.rng` だけ、
        採点が引くのは `fallback.rng` と `opp_model.rng` で、**別の流れ**だからである。
        """
        # 段 C-3（II-9）: W が小さければ引かずに全部数える。つまみ 0 なら通らない。
        self._worlds_enumerated = False
        if self.endgame_enum > 0:
            got = self._enumerated_worlds(s, pi, n)
            if got is not None:
                self._worlds_enumerated = True
                self._endgame_uses += 1
                return got
        # 段 C-4: つまみ 0 のときは**呼び出し方も従来のまま**にする。
        # `_determinize` を差し替えた検査用の子クラス（`test_lit_a.py` の `_StubClash` など）が
        # 引数 2 つのままでも動くようにするためで、既定の道の安全側でもある。
        ts = ([self._determinize(s, pi, j) for j in range(n)] if self.draw_buckets
              else [self._determinize(s, pi) for _ in range(n)])
        if self.world_weight <= 0.0:
            return ts, [1.0] * n
        ws = self.world_weights_for(s, pi, [t.players[1 - pi].hand for t in ts])
        # 重みは合計 1 に正規化してあるので、合計が n だった従来と桁を揃える
        # （`_pick` は合計で比べるだけなので順序には効かないが、`last_clash.totals` を
        # 「1 本あたり」に直す割り算と辻褄を合わせる）。
        return ts, [w * n for w in ws]

    def _enumerated_worlds(self, s, pi, n: int):
        """W ≤ `endgame_enum` なら列挙した世界と重みを返す。そうでなければ `None`。

        重みは多重度（その手札になる**物理的な配り方**の数）を正規化して合計 n に揃える。
        合計を n に揃えるのは、下流（`_clash` の `totals` を `samples` で割る所）の
        目盛りを決定化 n 本のときと同じに保つためである。

        `world_weight` も立っているときは、多重度に到達確率の重みを**掛ける**
        （どちらも「その世界のもっともらしさ」なので積が素直である）。候補
        `planner_vc4cps_khe` では `world_weight` は 0 なのでこの枝は通らない。
        """
        pool = self._unseen(s, pi)
        known = self._known_in_hand(s, pi)
        n_hand = len(s.players[1 - pi].hand)
        wc = world_counts(pool, n_hand, known)
        if wc["inconsistent"] or wc["W"] <= 0 or wc["W"] > self.endgame_enum:
            return None
        hands = enumerate_hands(pool, n_hand, known, limit=self.endgame_eval)
        if not hands:
            return None
        ts = ([self._determinize_with_hand(s, pi, h, j)
               for j, (h, _) in enumerate(hands)] if self.draw_buckets
              else [self._determinize_with_hand(s, pi, h) for h, _ in hands])
        ws = [w for _, w in hands]
        if self.world_weight > 0.0:
            extra = self.world_weights_for(s, pi, [h for h, _ in hands])
            ws = [a * b for a, b in zip(ws, extra)]
        tot = sum(ws)
        k = len(ts)
        if tot <= 0.0:
            return ts, [float(n) / k] * k
        return ts, [w / tot * n for w in ws]

    def _determinize_with_hand(self, s, pi, hand, world_ix: int = 0):
        """相手の手札を**指定した多重集合に固定**して決定化する（段 C-3）。

        `_determinize` との違いは「手札を引くかどうか」だけで、
        自分のデッキを混ぜる手順も相手の山札の作り方も同じである。
        乱数は `shuffle` を `_determinize` と同じ回数だけ引く。

        `world_ix` は段 C-4 のバケット化に使う「何本目か」である（つまみ 0 なら無視）。
        """
        t = s.clone()
        me, opp = t.players[pi], t.players[1 - pi]

        deck = sorted(me.action_deck)
        self.rng.shuffle(deck)
        self._stratify(deck, world_ix)
        me.action_deck = deck

        pool = sorted(self._unseen(s, pi))
        rest = self._minus_multiset(pool, list(hand))
        self.rng.shuffle(rest)
        opp.hand = list(hand)
        if len(rest) >= len(opp.action_deck):
            opp.action_deck = rest[:len(opp.action_deck)]
        else:
            d = sorted(opp.action_deck)
            self.rng.shuffle(d)
            opp.action_deck = d
        self._stratify(opp.action_deck, world_ix)
        return t

    def _stratify(self, deck: list, world_ix: int) -> None:
        """段 C-4: `draw_buckets` が立っているときだけ山札の上位を層別に並べ替える。

        つまみ 0 のときは**呼ぶだけで何もしない**（乱数も引かない）ので、
        既定の道は 1 ビットも変わらない。
        """
        if self.draw_buckets:
            stratify_top(deck, world_ix, self.rng)

    def _sample_opponent(self, s, pi):
        """相手の手札を差し替えた局面を返す（枚数は公開情報 §10）。"""
        t = s.clone()
        pool = self._unseen(s, pi)
        known = self._known_in_hand(s, pi)
        if known:
            # 段 C-1: 見えている札は必ず入れ、残りだけを候補から引く。
            rest = self._minus_multiset(pool, known)
            k = min(len(s.players[1 - pi].hand), len(known) + len(rest)) - len(known)
            t.players[1 - pi].hand = list(known) + (
                self.rng.sample(rest, k) if k > 0 else [])
            return t
        n = min(len(s.players[1 - pi].hand), len(pool))
        t.players[1 - pi].hand = self.rng.sample(pool, n) if n else []
        return t

    def _determinize(self, s, pi, world_ix: int = 0):
        """先読み用の局面を作る（D-026）。

        隠蔽情報をすべてエージェントの乱数で置き換える:
        - 自分のデッキ順序 → 中身は既知なので**正規化してから**シャッフル
        - 相手の手札とデッキ → 未公開カードをまとめて混ぜ、手札枚数分を配り直す

        デッキ順序を混ぜないと、先読み中のドローが実際の山札順で解決され、
        「次に引く札を知った上で」手を比較することになる（レビュー §3.4）。

        **正規化（sorted）が必須である。** `shuffle` は入力の並びに依存するため、
        実際の順序をそのまま混ぜると出力もまた実際の順序の関数になり、
        漏洩が消えない（同じ乱数状態でも元の並びが違えば結果が違う）。
        """
        t = s.clone()
        me, opp = t.players[pi], t.players[1 - pi]

        deck = sorted(me.action_deck)          # 中身は自分の情報。順序だけが隠蔽情報
        self.rng.shuffle(deck)
        # 段 C-4（D-077 追記 4）: つまみが立っているときだけ上位 3 枚を層別に散らす。
        self._stratify(deck, world_ix)
        me.action_deck = deck

        pool = sorted(self._unseen(s, pi))     # 相手の手札＋デッキ（公開情報から構成）
        # 段 C-1（II-7 (a)・D-077）: `known_hand` が立っているときは、
        # **スキャンで見えている札を候補から抜いてから混ぜ、必ず相手の手札に戻す。**
        # 乱数の消費は `shuffle` 1 回のままで、つまみ 0 のときは 1 ビットも変わらない
        # （`known` が空なら `_minus_multiset` は `pool` をそのまま返す）。
        known = sorted(self._known_in_hand(s, pi))
        if known:
            pool = self._minus_multiset(pool, known)
        self.rng.shuffle(pool)
        n_hand = min(len(opp.hand), len(known) + len(pool))
        n_draw = n_hand - len(known)
        # 見えている札を先頭に置く。並びは `sorted` で決まるので決定的である
        # （手札の並びは合法手の番号を決めるので、揺れると同じシードで手が変わる）。
        opp.hand = list(known) + pool[:max(0, n_draw)]
        rest = pool[max(0, n_draw):]
        if len(rest) >= len(opp.action_deck):
            opp.action_deck = rest[:len(opp.action_deck)]
        else:
            # 相手のデッキリストが未指定で候補が足りない場合。
            # 中身は推定できないが、順序の漏洩だけは同じ手順で断つ。
            d = sorted(opp.action_deck)
            self.rng.shuffle(d)
            opp.action_deck = d
        self._stratify(opp.action_deck, world_ix)
        return t

    # -- 葉の評価（差し替え口） ---------------------------------------------
    def _eval(self, s, pi) -> float:
        """葉の局面を pi 視点で採点する。**学習価値関数はここを差し替える**（C-1）。

        greedy / planner / mcts の採点はすべてこのメソッドを通る。
        既定は手書きの `evaluate` ＋ A-3 で調整した重み。
        差し替える側は終端の扱い（±WIN）を必ず引き継ぐこと。
        """
        return evaluate(s, pi, self.w)

    # -- 先読み中の代役 -----------------------------------------------------
    def _proxy_act(self, s, q, me):
        """先読み中に q の行動を決める。自分は固定方策、相手は相手モデル。

        `policy_net`（D-065 A-5'）があれば、代打ちを π の最良手に差し替える。
        **分岐の順序は Rust の `proxy_act` と同じでなければならない**
        （opp_policy_net → policy_net → 従来。違うと毎手一致が崩れる・§9-1）。
        """
        # 1. 相手の対抗の提出は opp_policy_net が優先（root_only でないとき）— D-057
        if q != me and s.phase == Phase.CLASH_SUBMIT and not self.opp_policy_root_only \
                and self.opp_policy_net is not None:
            return self._opp_act(s, q, True)
        # 2. 代打ちの π（D-065 A-5'）。proxy_lite は範囲をさらに絞る（§9-4 (a)）
        if self.policy_net is not None and (
                self.policy_scope in ("all", "proxy")
                or (self.policy_scope == "proxy_lite"
                    and self._lite_target(s, q, me))):
            return self._policy_pick(load_net(self.policy_net), s, q,
                                     0.0, self.fallback.rng)
        # 3. 従来どおり
        if q == me:
            return self.fallback.act(s, q)
        return self._opp_act(s, q, not self.opp_policy_root_only)

    @staticmethod
    def _lite_target(s, q, me) -> bool:
        """`proxy_lite` で π を使う代打ちか（相手のアクションフェイズ／自分の対抗の提出）。

        この 2 つに絞る理由: 探索の中で**相手の手がいちばん効く**のは相手のアクション
        フェイズであり、**自分の手がいちばん効く**のは対抗の提出だからである。
        残りは H に戻すので、π を読む回数が大きく減る（＝速い）。
        """
        return ((q != me and s.phase == Phase.ACTION)
                or (q == me and s.phase == Phase.CLASH_SUBMIT))

    def _fallback_act(self, s, pi):
        """担当外フェイズ（と準備段階）の**実際の**手。`policy_net` があれば π（D-065 A-5'）。

        Rust の `fallback_act` と同じく、抽選は `self.rng`・温度は `self.tau` である
        （代打ちの `tau=0` とは別。ここは実際に指す手なので確率化の対象になる）。
        """
        if self.policy_net is not None and self.policy_scope in ("all", "fallback"):
            return self._policy_pick(load_net(self.policy_net), s, pi,
                                     self.tau, self.rng)
        return self.fallback.act(s, pi)

    # -- 葉の整列（D-065 A-2・§2.4） ---------------------------------------
    def _goal_turn(self, s, pi) -> int:
        """`align_leaves` の目標ターン。**決定した局面**から決める。

        自分のターン中の決定なら次の自分のターン（+2）、相手のターン中なら +1。
        相手のターン中の対抗はもともと自分のターン開始で止まるので、+1 は
        「1 手も進めない＝従来と同じ葉」を意味する。

        `align_stop="turn_end"`（§2.4 の別解）では常に +1 である。つまり
        「いま進行中のターンが終わるところ」までしか運ばない。自分のアクションフェイズ中の
        選択（レベルアップの捨て札など）の葉が、計画探索の `to_clash` の葉と同じ地点になる。
        対抗・連撃の決定では `_settle` がすでにそこで止まっているので、**従来と同じ葉**になる。
        """
        if self.align_stop == "turn_end":
            return s.turn_no + 1
        return s.turn_no + (2 if s.turn_player == pi else 1)

    def _value_to_my_turn(self, u, pi, goal) -> float:
        """turn_no が goal 以上の最初の非 CHOICE 局面まで固定方策で進めて採点する（D-065 A-2）。

        `planner._value_after_turn`（extra_turns=1）と同じ打ち切りである。狙いは
        **葉を学習分布の中に置く**こと——V が学んだのは「自分のターンの開始（ACTION）」
        の局面だけであり、対抗や連撃の直後の局面は学習分布の外にある（レビュー §2.2）。
        """
        for _ in range(self.align_rollout):
            if u.outcome is not None or u.phase == Phase.GAME_OVER:
                break
            if u.turn_no >= goal and u.phase != Phase.CHOICE:
                break
            need = decision_players(u)
            if not need:
                break
            u = apply_owned(u, {q: self._proxy_act(u, q, pi) for q in need})
        return self._eval(u, pi)

    def _save_crn(self):
        """共通乱数の保存（`align_leaves` のときだけ）。

        葉まで進める距離が伸びるほど、固定方策の乱数の揺れが候補の優劣に化ける
        （`planner._plan` の CRN と同じ理由）。**False のときに戻すと既定の挙動が
        変わる**ので、必ず `align_leaves` のときだけにすること。
        """
        if not self.align_leaves:
            return None
        return (self.fallback.rng.getstate(), self.opp_model.rng.getstate())

    def _restore_crn(self, crn) -> None:
        if crn is None:
            return
        self.fallback.rng.setstate(crn[0])
        self.opp_model.rng.setstate(crn[1])

    # -- 局面を安定点まで進める -------------------------------------------
    def _settle(self, s, pi):
        """選択待ち・連撃を固定方策で解決し、採点できる局面まで進める。

        **前提: s は呼び出し側が専有している**（`apply(...)` の戻り値を直接渡すこと）。
        その前提のもとで `apply_owned` を使い、1手ごとの clone を省く（B-2）。
        """
        turn0 = s.turn_no
        for _ in range(self.rollout_depth):
            if s.outcome is not None:
                break
            if s.phase in (Phase.ACTION, Phase.CLASH_SUBMIT, Phase.GAME_OVER):
                break
            if s.turn_no != turn0 and s.phase != Phase.CHOICE:
                break
            need = decision_players(s)
            if not need:
                break
            s = apply_owned(s, {q: self._proxy_act(s, q, pi) for q in need})
        return s

    # -- 本体 --------------------------------------------------------------
    def act(self, s, pi):
        # 段 C-2: 前回の対抗の結果（公開情報）が出ていれば履歴に積む。
        # **つまみ 0 なら何もしない。**
        self._note_history(s, pi)
        acts = legal_actions(s, pi)
        assert acts, f"no legal actions for P{pi} in {s.phase}"
        if len(acts) == 1:
            return acts[0]
        # 担当外のフェイズと準備段階は規則に委ねる
        if s.phase not in self.phases or s.phase in (Phase.SETUP_CHARA,
                                                     Phase.MULLIGAN):
            return self._fallback_act(s, pi)
        if s.phase == Phase.CLASH_SUBMIT:
            return self._clash(s, pi, acts)
        return self._solo(s, pi, acts)

    def _pick(self, acts, totals, n: int) -> dict:
        """合計で最良を選ぶ（同点は最初）。`tau > 0` のときだけ平均で抽選する。

        合計と平均は同じ順序なので `tau=0` の結果は割り算の有無に依らないが、
        **割り算の丸めで同点が生まれる**ことがあるので既定の道では割らない
        （Rust の `clash` と同じ形。§2.3）。
        """
        if self.tau > 0.0:
            m = max(1, n)
            return acts[soft_pick([v / m for v in totals], self.tau, self.rng)]
        return acts[max(range(len(acts)), key=lambda i: totals[i])]

    def _solo(self, s, pi, acts) -> dict:
        """自分だけが決定するフェイズ（アクション・連撃・選択・手札上限）。

        D-026: 決定化した**1つの**局面の上で全候補を比較する。候補ごとに
        決定化し直すと、引く札の当たり外れが候補の優劣に化けてしまう。

        D-065 A-1: `solo_samples > 1` なら決定化を複数本引き、合計で比べる
        （`_clash` と同じ形）。1 本のときは従来と一手も変わらない。
        """
        goal = self._goal_turn(s, pi) if self.align_leaves else None
        n = max(1, self.solo_samples)
        totals = [0.0] * len(acts)
        ts, ws = self._worlds(s, pi, n)          # 段 C-2: つまみ 0 なら重みは 1.0
        for t, w in zip(ts, ws):
            crn = self._save_crn()
            for i, a in enumerate(acts):
                self._restore_crn(crn)
                totals[i] += w * self._score_solo(t, pi, a, goal)
        return self._pick(acts, totals, n)

    def _score_solo(self, t, pi, a, goal=None) -> float:
        """決定化済みの局面 t の上で1手を採点する。"""
        u = self._settle(apply(t, {pi: a}), pi)
        if self.align_leaves:
            return self._value_to_my_turn(u, pi, goal)
        return self._eval(u, pi)

    def _score_clash(self, t, pi, a, b, goal) -> float:
        """決定化 t の上で「自分が a・相手が b」を提出した結果を採点する。"""
        nxt = self._settle(apply(t, {pi: a, 1 - pi: b}), pi)
        return (self._value_to_my_turn(nxt, pi, goal)
                if self.align_leaves else self._eval(nxt, pi))

    def _opp_mix_dist(self, t, q, opp_act) -> list:
        """相手の提出の分布（A-8）。`(1−opp_mix)·最尤 ＋ opp_mix·合法手の等重み`。

        重みの合計で割って正規化する（試作 `experiments/proto_matrix_clash.py` の `mix` と同じ）。
        列の順序は `legal_actions` の順そのままで、Rust 版もこの順で足す（浮動小数の丸めまで揃える）。
        """
        opp_acts = legal_actions(t, q)
        if len(opp_acts) <= 1:
            return [(opp_acts[0] if opp_acts else opp_act, 1.0)]
        k = -1
        for i, b in enumerate(opp_acts):
            if b == opp_act:
                k = i
                break
        m = self.opp_mix
        ws = [m / len(opp_acts) + ((1.0 - m) if i == k else 0.0)
              for i in range(len(opp_acts))]
        tot = sum(ws)
        return [(b, w / tot) for b, w in zip(opp_acts, ws)]

    def _clash(self, s, pi, acts) -> dict:
        """§6.4(1) 対抗提出。相手の手札を標本抽出して期待値を取る。

        `opp_mix > 0`（A-8）では、決定化ごとに**相手の合法手の表**まで広げて期待値を取る。
        費用は「相手の合法手の数」倍（5〜8 倍）だが、対抗は決定の 1〜2 割である。
        """
        goal = self._goal_turn(s, pi) if self.align_leaves else None
        totals = [0.0] * len(acts)
        alts = [0.0] * len(acts)      # A-9 の第 2 基準（等重み相手での期待値）
        # 便 A: 詰みの割合（`lethal_uniform > 0` のときだけ埋まる）
        lethal = [0.0] * len(acts)
        uni = [0.0] * len(acts)       # 等重み相手での期待値（切り替え先の合計）
        bundle_mats = []              # A-2: 世界ごとの点数表
        bundle_ws = []                # A-2: その重み
        ts, ws = self._worlds(s, pi, self.samples)    # 段 C-2: つまみ 0 なら重みは 1.0
        self._remember_clash(s, pi)   # 段 C-2: この対抗の公開局面を控える
        for t, w in zip(ts, ws):
            crn = self._save_crn()
            opp_act = self._opp_act(t, 1 - pi, True)
            if self.lethal_uniform > 0.0:      # 便 A: 詰みが見えるときだけ等重み
                cols = legal_actions(t, 1 - pi) or [opp_act]
                m = [[0.0] * len(cols) for _ in acts]
                # 列の順序・足す順序は A-9 の経路と**同じ**（Rust の写しと丸めまで揃える）
                for j, b in enumerate(cols):
                    for i, a in enumerate(acts):
                        self._restore_crn(crn)
                        m[i][j] = self._score_clash(t, pi, a, b, goal)
                k = len(cols)
                j0 = -1
                for j, b in enumerate(cols):
                    if b == opp_act:
                        j0 = j
                        break
                if j0 < 0:
                    # opp_act が列に無い（起きない想定の保険）。π₀ の列だけ別に採点する。
                    for i, a in enumerate(acts):
                        self._restore_crn(crn)
                        totals[i] += w * self._score_clash(t, pi, a, opp_act, goal)
                for i in range(len(acts)):
                    lethal[i] += w * sum(1 for j in range(k)
                                         if m[i][j] >= 1.0 - LETHAL_EPS) / k
                    uni[i] += w * sum(m[i][j] for j in range(k)) / k
                    if j0 >= 0:
                        totals[i] += w * m[i][j0]
            elif self.nash_delta > 0.0:        # A-9: 均衡値 ＋ δ 以内での搾取
                cols = legal_actions(t, 1 - pi) or [opp_act]
                m = [[0.0] * len(cols) for _ in acts]
                for j, b in enumerate(cols):
                    for i, a in enumerate(acts):
                        self._restore_crn(crn)
                        m[i][j] = self._score_clash(t, pi, a, b, goal)
                pc = nash_col(m)
                k = len(cols)
                for i in range(len(acts)):
                    totals[i] += w * sum(m[i][j] * pc[j] for j in range(k))
                    alts[i] += w * sum(m[i][j] for j in range(k)) / k
            elif self.bundle_p > 0.0:          # A-2: 束ねた対抗ゲーム（便 A 後半）
                if self.bundle_p >= 1.0:
                    # 全列が同値になるので π₀ の列だけ採点する。**採点の呼び出しも
                    # 乱数の消費も既定の道と 1 回も違わない**（T-A2-2）。
                    col = []
                    for i, a in enumerate(acts):
                        self._restore_crn(crn)
                        col.append(self._score_clash(t, pi, a, opp_act, goal))
                    bundle_mats.append([[c] for c in col])
                    base = col
                else:
                    cols = legal_actions(t, 1 - pi) or [opp_act]
                    # 列の順序・足す順序は A-9 / 便 A の経路と**同じ**
                    # （Rust の写しと丸めまで揃えるため）。
                    m = [[0.0] * len(cols) for _ in acts]
                    for j, b in enumerate(cols):
                        for i, a in enumerate(acts):
                            self._restore_crn(crn)
                            m[i][j] = self._score_clash(t, pi, a, b, goal)
                    j0 = -1
                    for j, b in enumerate(cols):
                        if b == opp_act:
                            j0 = j
                            break
                    if j0 >= 0:
                        base = [m[i][j0] for i in range(len(acts))]
                    else:
                        # π₀ の手が列に無い（起きない想定の保険）。別に採点する。
                        base = []
                        for i, a in enumerate(acts):
                            self._restore_crn(crn)
                            base.append(self._score_clash(t, pi, a, opp_act, goal))
                    q = self.bundle_p
                    bundle_mats.append(
                        [[q * base[i] + (1.0 - q) * m[i][j] for j in range(len(cols))]
                         for i in range(len(acts))])
                bundle_ws.append(w)
                # `totals` の意味は従来のまま（π₀ に対する期待値）。混ぜた行列の
                # **π₀ の列は p に依らず m[i][j0] そのもの**なので、p=1 で自動的に一致する。
                for i in range(len(acts)):
                    totals[i] += w * base[i]
            elif self.opp_mix <= 0.0:          # 従来の道（既定・挙動不変）
                for i, a in enumerate(acts):
                    self._restore_crn(crn)
                    totals[i] += w * self._score_clash(t, pi, a, opp_act, goal)
            else:                              # A-8: 相手の合法手の表で期待値を取る
                for b, wb in self._opp_mix_dist(t, 1 - pi, opp_act):
                    for i, a in enumerate(acts):
                        self._restore_crn(crn)
                        totals[i] += w * wb * self._score_clash(t, pi, a, b, goal)
        rule = None
        if self.lethal_uniform > 0.0:
            n = max(1, self.samples)
            frac = [x / n for x in lethal]
            rule = "uniform" if max(frac) >= self.lethal_uniform else "pi0"
            if rule == "uniform":
                totals = uni
        bundle_x = None
        if self.bundle_p > 0.0:
            # A-2: 束ねたゲームを解き、**平均戦略**の最大の手を出す。
            # 同点は最初（`_pick` と同じ約束・引継ぎ書 §7-1）。
            from .bundle import solve_bundled
            bundle_x = solve_bundled(bundle_mats, bundle_ws)
            chosen = acts[max(range(len(acts)), key=lambda i: bundle_x[i])]
        elif self.nash_delta > 0.0:
            chosen = self._pick_safe(acts, totals, alts, self.samples)
        else:
            chosen = self._pick(acts, totals, self.samples)
        # D-7: 見比べた候補と点数を残す（記録用。**戻り値も乱数の消費も変わらない**）。
        # 点数は決定化 `samples` 本の合計なので、本数で割って 1 本あたりに直す。
        self.last_clash = {
            "acts": [_act_display_name(s, pi, a) for a in acts],
            "totals": [t / max(1, self.samples) for t in totals],
            # `_pick` は `acts` の要素そのものを返すので、同値の手が 2 つあっても
            # **同一性**で引けば取り違えない（`list.index` は最初の同値を返してしまう）。
            "chosen": next(i for i, a in enumerate(acts) if a is chosen),
        }
        if bundle_x is not None:
            # A-2: 解いた提出分布と最悪想定の値。**打ち方には効かない記録である**
            # （手は上で決まっている）。既定（p=0）ではこの 2 つの鍵は付かない。
            from .bundle import bundled_value
            self.last_clash["bundle_x"] = bundle_x
            self.last_clash["bundle_val"] = bundled_value(bundle_mats, bundle_ws,
                                                          bundle_x)
        if rule is not None:
            # 便 A: どちらの規則で選んだか／各手の詰みの割合。
            # **既定（θ=0）ではこの 2 つの鍵は付かない**ので、記録の形は変わらない。
            self.last_clash["rule"] = rule
            self.last_clash["lethal_frac"] = frac
        return chosen

    def _pick_safe(self, acts, nash_totals, alt_totals, n: int) -> dict:
        """A-9 の選び方: 均衡値が最大から δ 以内の手のうち、等重み相手での期待値が最大。

        `nash_totals`・`alt_totals` は標本 n 本の**合計**なので、しきい値も n 倍する。
        同点は最初（`_pick` と同じ約束）。
        """
        best = max(nash_totals)
        thr = best - self.nash_delta * max(1, n) - 1e-12
        cand = [i for i in range(len(acts)) if nash_totals[i] >= thr]
        return acts[max(cand, key=lambda i: alt_totals[i])]
