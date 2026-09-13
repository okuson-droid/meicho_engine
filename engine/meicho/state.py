"""ゲーム状態。rules_draft.md v0.10 §4（領域）・§10（実装メモ）に対応する。

設計方針:
- GameState は JSON 直列化可能（to_json / from_json）。
- 乱数は (seed, rng_calls) のペアから導出する決定的方式。Math.random 系の
  グローバル乱数は使用しない。シャッフル1回ごとに rng_calls を進める。
- applyは非破壊（copy を作ってから変更）。deepcopy より速い手書き clone を用意。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Phase(str, Enum):
    SETUP_CHARA = "setup_chara"        # §5-4 キャラ配置（両者同時・非公開）
    MULLIGAN = "mulligan"              # §5-5 マリガン（両者、各1回）
    ACTION = "action"                  # §6.3 アクションフェイズ（ターンプレイヤー）
    CLASH_SUBMIT = "clash_submit"      # §6.4(1) 対抗ステップ 裏向き同時提出
    CHOICE = "choice"                  # 効果解決中の選択待ち（D-015）
    RUSH = "rush"                      # §6.4(3) 連撃ステップ（勝者のみ）
    TURN_END_DISCARD = "turn_end_discard"  # §6.5 手札上限調整（ターンプレイヤー）
    GAME_OVER = "game_over"


HAND_LIMIT = 8          # §6.5
STARTING_LIFE = 20      # §1
MAX_LIFE = 20           # §1 回復効果はこの値を超えない（D-011）
OPENING_HAND = 5        # §5-5
DRAW_PER_TURN = 2       # §6.2
FIRST_TURN_DRAW = 1     # §6.2 先攻の最初のターン
RUSH_UNLIMITED = 10 ** 9  # 赤勝利時の「上限なし」(§6.4(2)-5) の内部表現
DRAW = -1               # outcome の引き分け表現（§9-5 / D-021）。0/1 は勝者のindex

# GameState.clash_counts の並び (B-3 / D-031)。cards.Color への依存を避けるため
# ここでは文字列値で引く（Color は str Enum なので Color.RED でもそのまま引ける）。
CLASH_COLOR_INDEX = {"red": 0, "green": 1, "blue": 2}
CLASH_PASS = 3
CLASH_SLOTS = 4


_SCALARS = (str, int, float, bool)


def _jcopy(x):
    """JSON相当の入れ子構造（dict/list/スカラ）の深いコピー。

    中断・再開用フィールド（pending_*）は小さな入れ子構造なので、
    copy.deepcopy より軽いこの関数で複製する。GameState.clone は
    探索のホットループから呼ばれるため、深さの浅い専用実装を置いている。

    B-2: 呼び出しの大半はスカラなので、先にスカラを弾く。
    """
    if x is None or type(x) in _SCALARS:
        return x
    if isinstance(x, dict):
        return {k: _jcopy(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jcopy(v) for v in x]
    return x


@dataclass
class CharaSlot:
    """キャラエリアの1枠。stack[-1] が最上段（現在レベル）。§6.3-3"""
    stack: list = field(default_factory=list)  # list[str] card_id

    def clone(self) -> "CharaSlot":
        # B-2: dataclass の __init__（既定値ファクトリの評価を含む）を迂回する。
        q = CharaSlot.__new__(CharaSlot)
        q.stack = self.stack[:]
        return q


@dataclass
class PlayerState:
    life: int = STARTING_LIFE
    action_deck: list = field(default_factory=list)   # 裏向き・非公開順序
    hand: list = field(default_factory=list)          # 非公開（アクションカードのみ）
    concerto: list = field(default_factory=list)      # §4-2 協奏エリア（公開）
    trash: list = field(default_factory=list)         # §4-6（公開）
    action_area: list = field(default_factory=list)   # §4-1（公開・左から順）
    chara_deck: list = field(default_factory=list)    # キャラデッキ（非公開）
    slots: list = field(default_factory=lambda: [CharaSlot(), CharaSlot(), CharaSlot()])
    # slots[0] = リーダーポジション, slots[1:2] = バックポジション (§4-4)
    mulligan_done: bool = False
    charas_revealed: bool = False   # §5-6 まで裏向き

    def clone(self) -> "PlayerState":
        # B-2: `__new__` ＋属性直接代入。dataclass の __init__ を通すより速い。
        # **フィールドを足したらここも足すこと。**
        # `test_clone_copies_every_field` が漏れを検出する。
        q = PlayerState.__new__(PlayerState)
        q.life = self.life
        q.action_deck = self.action_deck[:]
        q.hand = self.hand[:]
        q.concerto = self.concerto[:]
        q.trash = self.trash[:]
        q.action_area = self.action_area[:]
        q.chara_deck = self.chara_deck[:]
        q.slots = [s.clone() for s in self.slots]
        q.mulligan_done = self.mulligan_done
        q.charas_revealed = self.charas_revealed
        return q


@dataclass
class GameState:
    seed: int
    rng_calls: int = 0
    phase: Phase = Phase.SETUP_CHARA
    turn_no: int = 0                 # 1始まり。0 = 準備中
    turn_player: int = 0             # 先攻 = 0 とする（先攻決定は config で外部化）
    players: list = field(default_factory=list)  # list[PlayerState] len 2

    # ターン内フラグ (§6.3 各行動は1ターン1回)
    used_charge: bool = False
    used_switch: bool = False
    used_levelup: bool = False

    # 対抗フェイズの一時状態
    pending_submission: list = field(default_factory=lambda: [None, None])
    # 各プレイヤーの裏向き提出 card_id / "PASS" / None(未提出)
    clash_cards: list = field(default_factory=lambda: [None, None])  # 公開後
    clash_winner: Optional[int] = None
    rush_allowance: int = 0          # §6.4(2)-5 デフォルト0
    # 直近の対抗の記録（ターンをまたいで参照可能。分析・学習ログ用）
    last_clash_winner: Optional[int] = None
    last_clash_cards: list = field(default_factory=lambda: [None, None])

    # --- 対抗の履歴 (C-2 の解消 / B-3, D-031) --------------------------------
    # clash_counts[pi] = [赤, 緑, 青, パス] の累積回数。
    # 対抗ステップでは両者の提出が**公開**される (§6.4(1)-3) ので、
    # これは公開情報の集計であり、observe() でそのまま両者分を返してよい。
    #
    # 個々の対抗の列ではなく**十分統計量（回数）だけ**を持つ。理由は2つ:
    # (1) 「相手がこれまで対抗に出した色の経験分布」という当面の用途には
    #     回数で足りる。(2) GameState.clone は探索のホットループから呼ばれ、
    #     プロファイルで全体の約26%を占める。長さが対局とともに伸びる列を
    #     持たせるとここが劣化する。より豊かな履歴が必要になったら、
    #     そのとき用途と clone コストを見て拡張すること。
    clash_counts: list = field(
        default_factory=lambda: [[0, 0, 0, 0], [0, 0, 0, 0]])
    leader_switch_forbidden: list = field(default_factory=lambda: [False, False])
    # 「次のターン中、連撃できない」効果 (例: SD02-016 赤瞳凍土)。
    # rush_forbidden: 現在そのプレイヤーが連撃できないターン中か。
    # pending_rush_forbidden: そのプレイヤーの次の自分のターン開始時に rush_forbidden へ反映予定か。
    rush_forbidden: list = field(default_factory=lambda: [False, False])
    pending_rush_forbidden: list = field(default_factory=lambda: [False, False])
    # 「次のターン中、相手の赤色のカードのコスト+1」効果 (SD01-016 旋風)。
    # rush_forbidden と同じ「予約 → 次のターン開始時に発動」パターン（D-012関連）。
    red_cost_up: list = field(default_factory=lambda: [False, False])
    pending_red_cost_up: list = field(default_factory=lambda: [False, False])

    # --- 効果解決の中断・再開（D-015 / D-022）--------------------------------
    # 効果解決はスキル単位・オペコード単位で中断できる。プレイヤーの選択を要求する
    # 地点にぶつかると pending_choices に積んで Phase.CHOICE で制御を返し、
    # 選択が揃ったところで中断地点から再開する。すべて JSON 直列化可能な形で保持する。
    #
    # pending_choices: 選択の待ち行列。各要素 {"player": int, "kind": str, ...}
    # pending_skills:  未解決のスキル参照の待ち行列。各要素
    #                  [player, "chara"|"action", card_id, skill_index]
    # pending_effect:  解決中のスキルの残りオペコード
    #                  {"owner": int, "ops": [[op, params], ...]}
    # pending_ctx:     解決中のトリガーグループで共有する一時情報
    #                  （switched / bonus_damage）
    # pending_shared_ctx: True の場合、グループ内のスキル間で pending_ctx を共有する
    #                  （連撃で使用したカード自身のスキル群。_do_rush が使う）
    # choice_resume:   待ち行列が空になったときに再開する地点 {"kind": str, ...}
    pending_choices: list = field(default_factory=list)
    pending_skills: list = field(default_factory=list)
    pending_effect: Optional[dict] = None
    pending_ctx: dict = field(default_factory=dict)
    pending_shared_ctx: bool = False
    choice_resume: Optional[dict] = None
    # 選択待ちに入る直前のフェイズ。選択が片付いたら復帰する。
    phase_before_choice: Optional[Phase] = None

    # 「相手の手札を確認する」効果 (SD02-020 / SD01-020 スキャン) で見た内容の記録。
    # peeked_opp_hand[pi] = pi が覗いた時点の相手の手札のスナップショット (list[str]) / None。
    # observe() では現在の相手の手札との積集合を返すため、
    # 既に場に出た・捨てられたカードは自動的に落ちる（D-023）。
    peeked_opp_hand: list = field(default_factory=lambda: [None, None])

    # --- v0.12 / BP01 の状態欄（D-079 追記 3・便 K 段 K-2）------------------
    #
    # **すべて既定値で SD001/SD02 の対局が 1 手も変わらない**ことが条件である
    # （`tests/test_bp01.py` T-K-1）。BP01 のカードだけがこれらを読み書きする。
    # 足したら `clone` にも足すこと（`to_json` / `from_json` は dataclass 由来なので自動）。

    # 【優勢】(u2) の判定に使う。直前の 1 ターン（誰のターンでも）の対抗の結果。
    # `_begin_turn` で「今のターンの記録」を 1 ターンぶん繰り越す。
    last_turn_clash_winner: Optional[int] = None
    last_turn_clash_pass: list = field(default_factory=lambda: [False, False])
    # 「自分が受けるダメージ +N / −N」(u13)。ライフに入るダメージすべてに効く恒常修正。
    damage_taken_mod: list = field(default_factory=lambda: [0, 0])
    # 「各ターン、自分が最初に受けるダメージ」(u7) を済ませたか。
    first_damage_taken_this_turn: list = field(default_factory=lambda: [False, False])
    # 「このカードのスピードは N になる」(u10)。その対抗のあいだだけ有効な上書き。
    speed_override: list = field(default_factory=lambda: [None, None])
    # このターンに回復した回数（BP01-006「1ターン2回」）。
    heals_this_turn: list = field(default_factory=lambda: [0, 0])
    # このターンに使用したタグ・属性ごとの回数 (u7)。「最初に使用する〈タグ〉」の判定に使う。
    # 対抗と連撃を区別せず通しで数え、相手のターンでも数える。
    tag_uses_this_turn: list = field(default_factory=lambda: [{}, {}])
    # このターン直前に使用したカード（BP01-071「直前に使用したカードが＜滞空＞の場合」）。
    last_used_card: list = field(default_factory=lambda: [None, None])
    # このターン、そのプレイヤーがダメージを受けたか（BP01-012 が相手側を見る）。
    damaged_this_turn: list = field(default_factory=lambda: [False, False])
    # 各キャラ枠の最上段が置かれたターン番号（BP01-011「このターン以外に登場した場合」）。
    slot_entered_turn: list = field(
        default_factory=lambda: [[0, 0, 0], [0, 0, 0]])
    # BP01-057「終末ループ」で得た付与の残り枚数 (u19)。
    # 「このターン中、自分が次に使用する2枚の＜変奏スキル＞は
    # 『【連撃】カード1枚を引く。』を得る」——**連撃で使った札だけを数える**。
    # ターンをまたぐと消える（`_begin_turn` で 0 に戻す）。
    variation_rush_draw: list = field(default_factory=lambda: [0, 0])
    # 対抗フェイズ終了時に与える持ち越しダメージ（BP01-014 の付与スキル・K-4 で使う）。
    # 各要素 [与える側の player, 量]。
    deferred_clash_damage: list = field(default_factory=list)
    # 入れ子で誘発したスキルの割り込み待ち行列（`_queue_fire_nested`）。
    # `pending_skills` と同じ形だが、**解決中の効果を壊さない**ように別に持つ。
    pending_triggers: list = field(default_factory=list)

    # 決着: 勝者の player index (0/1) / DRAW(-1) 引き分け / None 未決着
    outcome: Optional[int] = None

    # --- 乱数 -------------------------------------------------------------
    def next_rng(self) -> random.Random:
        """決定的な乱数列。呼び出しごとに rng_calls を進める。"""
        r = random.Random(f"{self.seed}:{self.rng_calls}")
        self.rng_calls += 1
        return r

    # --- 複製・直列化 ------------------------------------------------------
    def clone(self) -> "GameState":
        """非破壊更新のための複製（作業規約2）。

        B-2: 探索のホットループでプロファイルの約3割を占めるため、
        dataclass の `__init__` を迂回して `__new__` ＋属性直接代入で作る。
        中断・再開用フィールド（pending_*）は空であることがほとんどなので、
        空なら `_jcopy` を呼ばずに定数を置く。

        **フィールドを足したらここも足すこと。**
        `test_clone_copies_every_field` が漏れを検出する。
        """
        s = GameState.__new__(GameState)
        s.seed = self.seed
        s.rng_calls = self.rng_calls
        s.phase = self.phase
        s.turn_no = self.turn_no
        s.turn_player = self.turn_player
        s.players = [p.clone() for p in self.players]
        s.used_charge = self.used_charge
        s.used_switch = self.used_switch
        s.used_levelup = self.used_levelup
        s.pending_submission = self.pending_submission[:]
        s.clash_cards = self.clash_cards[:]
        s.clash_winner = self.clash_winner
        s.rush_allowance = self.rush_allowance
        s.last_clash_winner = self.last_clash_winner
        s.last_clash_cards = self.last_clash_cards[:]
        s.clash_counts = [c[:] for c in self.clash_counts]
        s.leader_switch_forbidden = self.leader_switch_forbidden[:]
        s.rush_forbidden = self.rush_forbidden[:]
        s.pending_rush_forbidden = self.pending_rush_forbidden[:]
        s.red_cost_up = self.red_cost_up[:]
        s.pending_red_cost_up = self.pending_red_cost_up[:]
        s.pending_choices = _jcopy(self.pending_choices) if self.pending_choices else []
        s.pending_skills = [r[:] for r in self.pending_skills]
        s.pending_effect = (_jcopy(self.pending_effect)
                            if self.pending_effect is not None else None)
        s.pending_ctx = dict(self.pending_ctx) if self.pending_ctx else {}
        s.pending_shared_ctx = self.pending_shared_ctx
        s.choice_resume = (_jcopy(self.choice_resume)
                           if self.choice_resume is not None else None)
        s.phase_before_choice = self.phase_before_choice
        s.peeked_opp_hand = [None if h is None else h[:]
                             for h in self.peeked_opp_hand]
        # --- v0.12 / BP01（D-079 追記 3）---
        s.last_turn_clash_winner = self.last_turn_clash_winner
        s.last_turn_clash_pass = self.last_turn_clash_pass[:]
        s.damage_taken_mod = self.damage_taken_mod[:]
        s.first_damage_taken_this_turn = self.first_damage_taken_this_turn[:]
        s.speed_override = self.speed_override[:]
        s.heals_this_turn = self.heals_this_turn[:]
        # 中身が dict でない要素も素通しする。`test_clone_copies_every_field` は
        # 全フィールドに型を問わない値を差し込んで漏れを探すので、ここで型を
        # 決め打ちすると「漏れ」ではなく「例外」で落ちて原因が読めなくなる。
        s.tag_uses_this_turn = [dict(d) if type(d) is dict else d
                                for d in self.tag_uses_this_turn]
        s.last_used_card = self.last_used_card[:]
        s.damaged_this_turn = self.damaged_this_turn[:]
        s.slot_entered_turn = [t[:] for t in self.slot_entered_turn]
        s.variation_rush_draw = self.variation_rush_draw[:]
        s.deferred_clash_damage = ([d[:] for d in self.deferred_clash_damage]
                                   if self.deferred_clash_damage else [])
        s.pending_triggers = ([r[:] for r in self.pending_triggers]
                              if self.pending_triggers else [])
        s.outcome = self.outcome
        return s

    def to_json(self) -> str:
        d = asdict(self)
        d["phase"] = self.phase.value
        d["phase_before_choice"] = (None if self.phase_before_choice is None
                                    else self.phase_before_choice.value)
        return json.dumps(d, ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "GameState":
        d = json.loads(text)
        if d.get("phase_before_choice") is not None:
            d["phase_before_choice"] = Phase(d["phase_before_choice"])
        d["phase"] = Phase(d["phase"])
        players = []
        for pd in d["players"]:
            slots = [CharaSlot(stack=s["stack"]) for s in pd.pop("slots")]
            players.append(PlayerState(slots=slots, **pd))
        d["players"] = players
        return GameState(**d)
