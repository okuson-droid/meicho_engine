"""カードデータモデル。

rules_draft.md v0.11 §2（カード種別）・§7（タイミング語彙）に対応する。

**正本は `cards/` フォルダ**（実カード画像と `cards_structured.csv`）である。
このファイルは正本を実装の形に写したものであり、食い違ったら正本が正しい。
`scripts/reconcile_cards.py` が両者を突き合わせ、`tests/test_cards_folder.py` が
食い違ったらテストを落とす。カードを足す・直すときは **先に `cards/` を直す**。

D-062 (2026-08-31) で次を行った。
- カード番号を仮ID（`SD001-T##` / `AC-00#` など）から**公式番号に統一**した。
  旧IDとの対応表は decisions.md D-062 にある。
- 秧秧Lv2 の発動条件を「自分が赤で対抗」→「**相手が**赤で対抗」に訂正した。
- 「躍動する炎」に属性タグ「焦熱」を補った。
- 実在しない仮カード `AC-001`「音の形・空中攻撃」を削除した。
- この時点で `unverified` の残りは無い。

登録済みは SD01（漂泊者（女）・秧秧・熾霞）と SD02（漂泊者（男）・散華・今汐）の
52枚。`cards/` にはさらに13枚（BP01 のツバキ・アンコ・既存キャラの別Lv1・
「黒メェと白メェ」）があり、これらは【登場】【レベルアップ】など新しい機構を伴うため
別作業として後で入れる。

キャラカードのタグは 所属勢力 / 属性 / 武器種 の3系統（D-013）。
漂泊者（男・女）は所属タグ「瑝瓏」を持たない。
タグは 所属 → 属性 → 武器種 の順に正規化して記述する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Color(str, Enum):
    RED = "red"      # 攻撃
    BLUE = "blue"    # 防御
    GREEN = "green"  # 探索

    def beats(self, other: "Color") -> bool:
        """3すくみ (rules §2.2): 赤>緑, 緑>青, 青>赤"""
        return (self, other) in {
            (Color.RED, Color.GREEN),
            (Color.GREEN, Color.BLUE),
            (Color.BLUE, Color.RED),
        }


class Timing(str, Enum):
    """スキルが誘発する場面（rules_draft.md §7）。

    D-079 追記 3（便 K 段 K-2・2026-09-10）で BP01 のために 7 種を足した。
    **既存 6 種の値は変えていない**（保存済みのカード JSON と Rust の突き合わせが
    文字列で行われるため）。新しい 7 種は SD001/SD02 のカードには 1 つも付かないので、
    足しただけでは対局は変わらない（`tests/test_bp01.py` T-K-1）。
    """

    CLASH = "clash"          # 【対抗】 対抗でカードが使用されたとき (§6.4(1)-4)
    JUDGE = "judge"          # 【判定】 勝敗確定時のみ。引き分けでは誘発しない (§6.4(2)-2)
    RUSH = "rush"            # 【連撃】 連撃で使用されたとき (§6.4(3)-1)
    TURN_END = "turn_end"    # 【各ターン終了時】 (§6.5)
    TURN_START = "turn_start"  # 【ターン開始時】 (§6.1)
    STATIC = "static"        # 常在型（例: SD02-005 今汐Lv2 / SD01-005 熾霞Lv2）

    # --- v0.12 / BP01（D-079 追記 3）------------------------------------
    # 【登場】キャラエリアの最上段に置かれたとき。準備 (§5-4) では誘発しない (u1)。
    ENTER = "enter"
    # 【レベルアップ】レベルアップで上に置かれたとき。行動でも効果でも誘発する (u3)。
    LEVELUP = "levelup"
    # 【切り替え】リーダーの切り替えが実際に行われたとき (§7 の「切り替えされた場合」と同じ判定)。
    SWITCHED = "switched"
    # 【自分の対抗フェイズ開始時】ターンプレイヤーのときだけ（is_turn_player 条件を併記する）。
    CLASH_PHASE_START = "clash_phase_start"
    # 【各対抗フェイズ終了時】両プレイヤーで誘発する。
    CLASH_PHASE_END = "clash_phase_end"
    # 自分のライフが回復した時（BP01-006 ショアキーパーLv2。回数制限は条件で書く）。
    ON_HEAL = "on_heal"
    # 相手にダメージを与えた時（BP01-060 と ＜音骸＞の【優勢】5 枚）。
    ON_DAMAGE_DEALT = "on_damage_dealt"


# 盤面の「場面」として発火する（＝カード 1 枚の使用に紐づかない）タイミング。
# アクションエリアに置かれたカードのスキルも拾う必要がある（例: BP01-069 羽乱舞・回避の
# 【各対抗フェイズ終了時】は、そのカードがアクションエリアに在るときに効く）。
#
# **`ON_DAMAGE_DEALT` はここに入れない**（u18・マスター裁定 2026-09-10）。
# 「相手にダメージを与えた時」は**そのカード自身が与えたときだけ**誘発する。
# K-2 の最初の実装はここに入れていたが、それは「連撃で使ったカードは対抗カードではないので
# 盤面の走査では拾えない」という**実装の都合**を、ルールの範囲の話にすり替えていた。
# 与えたカードが分かっている場面ではその 1 枚の索引を直に引けばよく、
# 範囲を広げる必要は無い（`engine._queue_fire_on_card`）。
AREA_TIMINGS = frozenset({Timing.CLASH_PHASE_START, Timing.CLASH_PHASE_END})

# ＜音骸＞のタグ（rules_draft.md v0.12 §7・u5）。**自分のアクションエリアに 1 枚まで**という
# 使用条件がこのタグに紐づく。BP01 で初めて出た「専用キャラを持たない共通カード」でもある。
ONKAI_TAG = "音骸"

# 効果の解決の途中で発火しうるタイミング（入れ子）。`_queue_fire` は待ち行列を
# 置き換えてしまうので、これらは `_queue_fire_nested` で**割り込ませる**。
NESTED_TIMINGS = frozenset({Timing.ENTER, Timing.LEVELUP, Timing.SWITCHED,
                            Timing.ON_HEAL, Timing.ON_DAMAGE_DEALT})


@dataclass(frozen=True)
class Skill:
    """スキル1個。

    condition: 誘発条件。使うキーは効果解決器 (engine._skill_condition_met) が解釈する。
      - self_result: "win" | "lose"   … 判定での自分の勝敗
      - self_color / opp_color: Color … 対抗カードの色
      - self_action_area_count_gte: int … 自分のアクションエリア枚数が閾値以上か (§4-1)
      - is_turn_player: bool … 自分がターンプレイヤーか。カードテキストの
        「自分のターン開始時」等を表す。条件を書かない場合、TURN_START/TURN_END は
        両プレイヤーで誘発する（=「各ターン〜」）。(D-014)
    effect: 効果オペコード列。engine._step_effect / _apply_op が解釈する。
      オペコードのパラメータ `up_to: True` は「N枚まで」を意味し、
      実際の枚数をプレイヤーが選ぶ（A-2 / D-022）。
    leader_only: 【リーダー】前置（リーダーポジションでのみ有効, §2.1）
    optional: 「〜してもよい」。実行するかどうかをプレイヤーが選ぶ（A-1 / D-022）
    unverified: カードテキスト判読不能につき仮実装
    """

    timing: Timing
    effect: tuple  # tuple of (op, params) タプル。frozen のため tuple 固定
    condition: Optional[dict] = None
    leader_only: bool = False
    optional: bool = False
    unverified: bool = False


@dataclass(frozen=True)
class CharaCard:
    card_id: str      # 例 "BP01-021"
    name: str         # 同名 = 同キャラ (§3.1)
    level: int
    tags: tuple = ()
    skills: tuple = ()  # tuple[Skill, ...]


@dataclass(frozen=True)
class ActionCard:
    card_id: str
    name: str
    color: Color
    cost: int
    speed: int
    damage: int
    tags: tuple = ()
    skills: tuple = ()
    # 専用キャラ名 (§2.2「専用キャラ名」欄・§3.2 rule3)。
    # デッキ構築時、このキャラがキャラデッキに含まれていないと採用できない、という
    # 構築時の制約のみを表す。使用時にこのキャラがリーダーである必要はない。
    dedicated_to: Optional[str] = None
    # 「リーダースキル」使用条件 (rules_draft.md 133行目 / §6.4 使用条件II)。
    # True の場合のみ、自分のリーダーが dedicated_to と同名でないと使用できない。
    # D-009: 旧 leader_lock フィールドは「専用キャラ」と「リーダースキル使用条件」を
    # 混同していたため2フィールドに分離した（マスター指摘, 2026-08-20）。
    leader_skill: bool = False
    unverified_fields: tuple = ()      # 判読できなかった属性名


# ---------------------------------------------------------------------------
# カード登録簿
# ---------------------------------------------------------------------------

CHARA_CARDS: dict[str, CharaCard] = {}
ACTION_CARDS: dict[str, ActionCard] = {}


def _chara(c: CharaCard) -> CharaCard:
    CHARA_CARDS[c.card_id] = c
    return c


def _action(c: ActionCard) -> ActionCard:
    ACTION_CARDS[c.card_id] = c
    return c


# --- キャラ: 漂泊者（男） ---------------------------------------------------
# 2026-08-20: Lv0(BP01-021)とLv2(SD02-001)のスキルが登録時に入れ替わっていたことが
# 判明し、マスター確認のうえ訂正（散華・今汐も同型の誤りがあった）。
_chara(CharaCard(
    "BP01-021", "漂泊者（男）", level=0, tags=("回折", "迅刀"),
    skills=(Skill(
        Timing.CLASH,
        (("reveal_top_to_hand", {"count": 2, "up_to": True}),),
        condition={"self_color": Color.GREEN},
        leader_only=True,
    ),),
))
_chara(CharaCard(
    "SD02-002", "漂泊者（男）", level=1, tags=("回折", "迅刀"),
    skills=(Skill(
        Timing.JUDGE,
        (("reveal_top_to_hand", {"count": 1}),),
        condition={"self_result": "lose", "self_color": Color.GREEN, "opp_color": Color.RED},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    "SD02-001", "漂泊者（男）", level=2, tags=("回折", "迅刀"),
    skills=(Skill(Timing.TURN_END, (("draw", {"count": 1}),), leader_only=True),),
))

# --- キャラ: 散華 -----------------------------------------------------------
_chara(CharaCard(
    "BP01-033", "散華", level=0, tags=("瑝瓏", "凝縮", "迅刀"),
    skills=(Skill(
        Timing.CLASH,
        (("top_to_concerto", {"count": 1}),),
        condition={"self_color": Color.BLUE},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    "SD02-004", "散華", level=1, tags=("瑝瓏", "凝縮", "迅刀"),
    skills=(Skill(
        Timing.JUDGE,
        (("reveal_top_to_hand", {"count": 1}),),
        condition={"self_result": "lose", "self_color": Color.BLUE, "opp_color": Color.GREEN},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    "SD02-003", "散華", level=2, tags=("瑝瓏", "凝縮", "迅刀"),
    skills=(Skill(Timing.TURN_END, (("top_to_concerto", {"count": 1}),), leader_only=True),),
))

# --- キャラ: 今汐 -----------------------------------------------------------
_chara(CharaCard(
    "BP01-030", "今汐", level=0, tags=("瑝瓏", "回折", "長刃"),
    skills=(Skill(
        Timing.CLASH,
        (("damage_opponent", {"amount": 1}),),
        condition={"self_color": Color.RED},
        leader_only=True,
    ),),
))
_chara(CharaCard(
    "SD02-006", "今汐", level=1, tags=("瑝瓏", "回折", "長刃"),
    skills=(Skill(
        Timing.JUDGE,
        (("reveal_top_to_hand", {"count": 1}),),
        condition={"self_result": "lose", "self_color": Color.RED, "opp_color": Color.BLUE},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    "SD02-005", "今汐", level=2, tags=("瑝瓏", "回折", "長刃"),
    skills=(Skill(Timing.STATIC, (("rush_damage_buff", {"amount": 1}),), leader_only=True),),
))

# ---------------------------------------------------------------------------
# アクションカード
# ---------------------------------------------------------------------------

# --- 漂泊者（男） 専用 --------------------------------------------------------
# D-062 (2026-08-31): 旧 "AC-001"「音の形・空中攻撃」をここから削除した。
# 写真が判読できなかった時期の仮カードで、cards/ の実カード画像65枚のどこにも
# 該当がなく、SD02 のアクションは SD02-007〜023 の17種で連番が埋まっていて
# 入る余地もない。どのデッキリストにも入っていなかったため対戦結果に影響はない。
# 実物が見つかった場合はここに公式番号で登録し直すこと。
_action(ActionCard(
    "SD02-017", "音の形・通常攻撃", Color.RED, cost=0, speed=8, damage=1,
    tags=("基本攻撃", "通常攻撃", "回折"),
    dedicated_to="漂泊者（男）",
))
_action(ActionCard(
    "SD02-019", "轟音", Color.RED, cost=0, speed=0, damage=0,
    tags=("変奏スキル",),
    dedicated_to="漂泊者（男）",
    skills=(Skill(
        Timing.RUSH,
        (("switch_leader", {}), ("draw_if_switched", {"name": "漂泊者（男）", "count": 1})),
    ),),
))
_action(ActionCard(
    "SD02-022", "音の刃", Color.RED, cost=1, speed=13, damage=3,
    tags=("共鳴スキル", "回折"),
    dedicated_to="漂泊者（男）", leader_skill=True,
))
_action(ActionCard(
    "SD02-023", "奏鳴", Color.RED, cost=2, speed=13, damage=5,
    tags=("共鳴解放", "回折"),
    dedicated_to="漂泊者（男）", leader_skill=True,
))
_action(ActionCard(
    "SD02-018", "音の形・回避", Color.BLUE, cost=0, speed=0, damage=0,
    tags=("回避",),
    dedicated_to="漂泊者（男）",
    skills=(Skill(
        Timing.JUDGE,
        (("draw", {"count": 1}), ("discard_self", {"count": 1})),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "SD02-020", "スキャン", Color.GREEN, cost=0, speed=5, damage=0,
    tags=("探索モジュール",),
    dedicated_to="漂泊者（男）",
    skills=(Skill(
        Timing.JUDGE,
        (("draw", {"count": 1}), ("peek_opponent_hand", {})),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "SD02-021", "鉤縄", Color.GREEN, cost=1, speed=8, damage=0,
    tags=("探索モジュール", "滞空"),
    dedicated_to="漂泊者（男）",
    skills=(Skill(
        Timing.JUDGE,
        (("draw", {"count": 1}), ("pursuit", {"count": 2})),
        condition={"self_result": "win"},
    ),),
))

# --- 散華 専用 ----------------------------------------------------------------
_action(ActionCard(
    "SD02-012", "冷徹な光・通常攻撃", Color.RED, cost=0, speed=8, damage=1,
    tags=("基本攻撃", "通常攻撃", "凝縮"),
    dedicated_to="散華",
))
_action(ActionCard(
    "SD02-014", "凛然浄化", Color.RED, cost=0, speed=0, damage=0,
    tags=("変奏スキル",),
    dedicated_to="散華",
    skills=(Skill(
        Timing.RUSH,
        (("switch_leader", {}), ("top_to_concerto_if_switched", {"name": "散華", "count": 1})),
    ),),
))
_action(ActionCard(
    "SD02-015", "永劫新雪", Color.RED, cost=1, speed=9, damage=3,
    tags=("共鳴スキル", "凝縮"),
    dedicated_to="散華", leader_skill=True,
    skills=(Skill(
        Timing.JUDGE, (("top_to_concerto", {"count": 2}),),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "SD02-016", "赤瞳凍土", Color.RED, cost=2, speed=13, damage=4,
    tags=("共鳴解放", "凝縮"),
    dedicated_to="散華", leader_skill=True,
    skills=(Skill(
        Timing.JUDGE, (("forbid_rush_next_turn", {}),),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "SD02-013", "冷徹な光・回避", Color.BLUE, cost=0, speed=0, damage=0,
    tags=("回避",),
    dedicated_to="散華",
    skills=(Skill(
        Timing.JUDGE, (("pursuit", {"count": 2}),),
        condition={"self_result": "win"},
    ),),
))

# --- 今汐 専用 ----------------------------------------------------------------
_action(ActionCard(
    "SD02-007", "寒風散らす光・通常攻撃", Color.RED, cost=0, speed=7, damage=1,
    tags=("基本攻撃", "通常攻撃", "回折"),
    dedicated_to="今汐",
))
_action(ActionCard(
    "SD02-009", "蟠龍の輝き", Color.RED, cost=0, speed=0, damage=0,
    tags=("変奏スキル", "回折"),
    dedicated_to="今汐",
    skills=(Skill(
        Timing.RUSH,
        (("switch_leader", {}), ("self_damage_buff_if_switched", {"name": "今汐", "amount": 2})),
    ),),
))
_action(ActionCard(
    "SD02-011", "邪を潰す歳月の重さ", Color.RED, cost=3, speed=13, damage=5,
    tags=("共鳴解放", "回折"),
    dedicated_to="今汐", leader_skill=True,
    skills=(Skill(
        Timing.RUSH, (("self_damage_buff", {"amount": 3}),),
        condition={"self_action_area_count_gte": 3},
    ),),
))
_action(ActionCard(
    "SD02-008", "寒風散らす光・回避反撃", Color.BLUE, cost=0, speed=0, damage=3,
    tags=("回避反撃", "回折"),
    dedicated_to="今汐",
))
_action(ActionCard(
    "SD02-010", "龍憑の天舞", Color.GREEN, cost=1, speed=13, damage=0,
    tags=("共鳴回路",),
    dedicated_to="今汐", leader_skill=True,
    skills=(
        Skill(Timing.CLASH, (("forbid_leader_switch_this_turn", {}),)),
        Skill(Timing.JUDGE, (("draw", {"count": 3}), ("pursuit", {"count": 8})),
              condition={"self_result": "win"}),
    ),
))


# ===========================================================================
# SD001（スターターデッキ: 漂泊者（女）・秧秧・熾霞）
# 2026-08-21 マスターより公式確定テキストで受領・反映。
# カード番号が未確認のため、アクションカードは SD001-T##、キャラカードは
# SD001-C## の仮IDを付与している（D-008）。
#
# 注意: 「漂泊者（男）」と「漂泊者（女）」は別キャラである（マスター確認済み）。
# 同名カードでも専用キャラが異なれば別カードとして別IDで登録し、SD02側とマージしない。
# ===========================================================================

# --- キャラ: 漂泊者（女） ---------------------------------------------------
# Lv0/Lv2の入れ替わり（SD02で発生した登録ミス）がないことを確認済み:
# Lv0=【対抗】色条件付き / Lv1=【判定】敗北時 / Lv2=常時系 の並びで整合する。
_chara(CharaCard(
    "BP01-018", "漂泊者（女）", level=0, tags=("回折", "迅刀"),
    skills=(Skill(
        Timing.CLASH,
        (("reveal_top_to_hand", {"count": 2, "up_to": True}),),
        condition={"self_color": Color.GREEN},
        leader_only=True,
    ),),
))
_chara(CharaCard(
    "SD01-002", "漂泊者（女）", level=1, tags=("回折", "迅刀"),
    skills=(Skill(
        Timing.JUDGE,
        (("reveal_top_to_hand", {"count": 1}),),
        condition={"self_result": "lose", "self_color": Color.GREEN,
                   "opp_color": Color.RED},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    # 「【自分の】ターン開始時」。男版 SD02-001 の「【各】ターン終了時」と異なり、
    # 自分がターンプレイヤーのターンでのみ誘発する (D-014)。
    # また本プロジェクト初の leader_only=False のキャラスキルであり、
    # 後衛ポジションにいても誘発する。
    "SD01-001", "漂泊者（女）", level=2, tags=("回折", "迅刀"),
    skills=(Skill(
        Timing.TURN_START,
        (("draw", {"count": 1}),),
        condition={"is_turn_player": True},
        leader_only=False,
    ),),
))

# --- キャラ: 秧秧 -----------------------------------------------------------
_chara(CharaCard(
    "BP01-024", "秧秧", level=0, tags=("瑝瓏", "気動", "迅刀"),
    skills=(Skill(
        Timing.CLASH,
        (("top_to_concerto", {"count": 1}),),
        condition={"self_color": Color.BLUE},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    "SD01-004", "秧秧", level=1, tags=("瑝瓏", "気動", "迅刀"),
    skills=(Skill(
        Timing.JUDGE,
        (("reveal_top_to_hand", {"count": 1}),),
        condition={"self_result": "lose", "self_color": Color.BLUE,
                   "opp_color": Color.GREEN},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    # 相手に「コスト1を支払う / 支払わずダメージ3を受ける」を選ばせる。
    # 本プロジェクト初の「相手に選択を要求する効果」であり、
    # 効果解決を中断して相手の決定を待つ仕組みを導入した (D-015)。
    # Lv2で【対抗】タイミングを使う初の例でもある。
    #
    # D-062 (2026-08-31): 条件は **opp_color**（相手が赤で対抗したとき）である。
    # カードテキスト「【対抗】相手が赤色のカードで対抗した場合」。
    # 従来は self_color=RED で登録されており、相手の赤を咎めるカウンターが
    # 自分の赤を後押しする追加打点に化けていた。実カード画像で確認して訂正。
    # 条件で opp_color を使う初の【対抗】スキルでもある
    # （両者の提出は _resolve_clash で出そろってから CLASH が誘発するため成立する）。
    "SD01-003", "秧秧", level=2, tags=("瑝瓏", "気動", "迅刀"),
    skills=(Skill(
        Timing.CLASH,
        (("opponent_pay_or_damage", {"cost": 1, "amount": 3}),),
        condition={"opp_color": Color.RED},
        leader_only=True,
    ),),
))

# --- キャラ: 熾霞 -----------------------------------------------------------
_chara(CharaCard(
    "BP01-027", "熾霞", level=0, tags=("瑝瓏", "焦熱", "拳銃"),
    skills=(Skill(
        Timing.CLASH,
        (("damage_opponent", {"amount": 1}),),
        condition={"self_color": Color.RED},
        leader_only=True,
    ),),
))
_chara(CharaCard(
    "SD01-006", "熾霞", level=1, tags=("瑝瓏", "焦熱", "拳銃"),
    skills=(Skill(
        Timing.JUDGE,
        (("reveal_top_to_hand", {"count": 1}),),
        condition={"self_result": "lose", "self_color": Color.RED,
                   "opp_color": Color.BLUE},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    # 常在型。カードテキストに【連撃】の限定がないため、対抗・連撃の両方の
    # ダメージに加算される（今汐Lv2 SD02-005 は【連撃】限定である点が異なる）。
    # 対象は「リーダースキルを持つ熾霞専用カード」= SD01-010 / SD01-011。
    "SD01-005", "熾霞", level=2, tags=("瑝瓏", "焦熱", "拳銃"),
    skills=(Skill(
        Timing.STATIC,
        (("dedicated_leader_card_damage_buff", {"name": "熾霞", "amount": 3}),),
        leader_only=False,
    ),),
))

# --- SD001 アクションカード: 漂泊者（女） 専用 --------------------------------
_action(ActionCard(
    # SD02-017（男版）と数値・タグが完全一致するが、専用キャラが異なる別カード。
    "SD01-017", "音の形・通常攻撃", Color.RED, cost=0, speed=8, damage=1,
    tags=("基本攻撃", "通常攻撃", "回折"),
    dedicated_to="漂泊者（女）",
))
_action(ActionCard(
    "SD01-019", "轟音", Color.RED, cost=0, speed=0, damage=0,
    tags=("変奏スキル",),
    dedicated_to="漂泊者（女）",
    skills=(Skill(
        Timing.RUSH,
        (("switch_leader", {}),
         ("draw_if_switched", {"name": "漂泊者（女）", "count": 1})),
    ),),
))
_action(ActionCard(
    # 男版 SD02-022 は 赤/1/13/3。女版はスピード16・ダメージ1（マスター確認済み・記載どおり）。
    "SD01-022", "音の刃", Color.RED, cost=1, speed=16, damage=1,
    tags=("共鳴スキル", "回折"),
    dedicated_to="漂泊者（女）", leader_skill=True,
))
_action(ActionCard(
    "SD01-023", "奏鳴", Color.RED, cost=3, speed=14, damage=5,
    tags=("共鳴解放", "回折"),
    dedicated_to="漂泊者（女）", leader_skill=True,
    skills=(Skill(
        Timing.JUDGE, (("heal_self", {"amount": 5}),),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "SD01-018", "音の形・回避", Color.BLUE, cost=0, speed=0, damage=0,
    tags=("回避",),
    dedicated_to="漂泊者（女）",
    skills=(Skill(
        Timing.JUDGE,
        (("draw", {"count": 1}), ("discard_self", {"count": 1})),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "SD01-020", "スキャン", Color.GREEN, cost=0, speed=5, damage=0,
    tags=("探索モジュール",),
    dedicated_to="漂泊者（女）",
    skills=(Skill(
        Timing.JUDGE,
        (("draw", {"count": 1}), ("peek_opponent_hand", {})),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "SD01-021", "鉤縄", Color.GREEN, cost=1, speed=8, damage=0,
    tags=("探索モジュール", "滞空"),
    dedicated_to="漂泊者（女）",
    skills=(Skill(
        Timing.JUDGE,
        (("draw", {"count": 1}), ("pursuit", {"count": 2})),
        condition={"self_result": "win"},
    ),),
))

# --- SD001 アクションカード: 秧秧 専用 ----------------------------------------
_action(ActionCard(
    "SD01-012", "羽の刃・通常攻撃", Color.RED, cost=0, speed=8, damage=1,
    tags=("基本攻撃", "通常攻撃", "気動"),
    dedicated_to="秧秧",
))
_action(ActionCard(
    "SD01-014", "息継ぎ", Color.RED, cost=0, speed=0, damage=0,
    tags=("変奏スキル",),
    dedicated_to="秧秧",
    skills=(Skill(
        Timing.RUSH,
        (("switch_leader", {}),
         ("top_to_concerto_if_switched", {"name": "秧秧", "count": 1})),
    ),),
))
_action(ActionCard(
    "SD01-016", "旋風", Color.RED, cost=2, speed=13, damage=4,
    tags=("共鳴解放", "気動"),
    dedicated_to="秧秧", leader_skill=True,
    skills=(Skill(
        Timing.JUDGE, (("raise_opponent_red_cost_next_turn", {}),),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "SD01-013", "羽の刃・回避", Color.BLUE, cost=0, speed=0, damage=0,
    tags=("回避",),
    dedicated_to="秧秧",
    skills=(Skill(
        Timing.JUDGE, (("pursuit", {"count": 2}),),
        condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    # 緑でありながら「探索モジュール」を持たない初のカード。タグ「移動」は初出。
    "SD01-015", "ジャンプ", Color.GREEN, cost=0, speed=7, damage=0,
    tags=("移動", "滞空"),
    dedicated_to="秧秧",
    skills=(Skill(
        Timing.JUDGE,
        (("draw", {"count": 1}), ("pursuit", {"count": 1})),
        condition={"self_result": "win"},
    ),),
))

# --- SD001 アクションカード: 熾霞 専用 ----------------------------------------
_action(ActionCard(
    "SD01-007", "ババン・通常攻撃", Color.RED, cost=0, speed=6, damage=1,
    tags=("基本攻撃", "通常攻撃", "焦熱"),
    dedicated_to="熾霞",
))
_action(ActionCard(
    # D-062 (2026-08-31): 属性タグ「焦熱」の記入漏れを補った（実カード画像で確認）。
    # 対応する SD02 側「蟠龍の輝き」は最初から ("変奏スキル", "回折") で正しい。
    "SD01-009", "躍動する炎", Color.RED, cost=0, speed=0, damage=0,
    tags=("変奏スキル", "焦熱"),
    dedicated_to="熾霞",
    skills=(Skill(
        Timing.RUSH,
        (("switch_leader", {}),
         ("self_damage_buff_if_switched", {"name": "熾霞", "amount": 2})),
    ),),
))
_action(ActionCard(
    # 判定で青に敗北した場合、このカードをアクションエリアから手札に戻せる。
    # 本プロジェクト初の「アクションエリアからカードを取り除く」効果。
    "SD01-010", "燃える闘志", Color.RED, cost=1, speed=8, damage=2,
    tags=("共鳴スキル", "焦熱"),
    dedicated_to="熾霞", leader_skill=True,
    skills=(Skill(
        Timing.JUDGE, (("return_clash_card_to_hand", {}),),
        condition={"self_result": "lose", "self_color": Color.RED,
                   "opp_color": Color.BLUE},
        optional=True,
    ),),
))
_action(ActionCard(
    # ダメージ7は現時点の最大値。熾霞Lv2の常在効果で+3される対象。
    "SD01-011", "燃える烈火", Color.RED, cost=3, speed=12, damage=7,
    tags=("共鳴解放", "焦熱"),
    dedicated_to="熾霞", leader_skill=True,
))
_action(ActionCard(
    "SD01-008", "ババン・回避反撃", Color.BLUE, cost=0, speed=0, damage=3,
    tags=("回避反撃", "焦熱"),
    dedicated_to="熾霞",
))


# ---------------------------------------------------------------------------
# BP01（第 1 弾ブースター）— 便 K 段 K-1（D-079 追記 2・2026-09-10）
# ---------------------------------------------------------------------------
#
# 68 番号すべてを**ここで一度に**登録する（D-079 判断 1）。段ごとに登録すると
# `encode.NA` / `NC` が段ごとに変わり、`ENCODING_VERSION` の上げ直しとネットの移行が
# 4 回必要になるためである。効果（`skills`）は段ごとに埋める:
#   K-1 … 既存の語彙で書ける 15 番号（バニラ 4・【判定】勝利でドロー等 11）
#   K-2 … 新しいタイミングと状態欄が要る 20 番号
#   K-3 … 【優勢】と＜音骸＞の 12 番号
#   K-4 … それ以外の新機構 21 番号
# まだ埋めていない番号は `skills=()` の枠で、`# TODO(K-n)` を添えてある。
# 枠であっても色・コスト・スピード・ダメージ・タグ・専用キャラ・【リーダースキル】は
# 正本どおりに入れる（`reconcile_cards.py` が突き合わせる）。
#
# **並びは末尾追記**である（D-079 判断・`tests/test_bp01.py` T-K-2）。既存 52 枚の添字を
# 動かさないため、カード番号順に並べ替えてはいけない。
#
# 機構の台帳は `cards/BP01_MECHANICS.md`、条文案は `rules_draft_v0.12_proposal.md`。

# --- BP01 キャラカード 27 -----------------------------------------------------
_chara(CharaCard(
    "BP01-001", "ツバキ", level=2, tags=('ブラックショア', '消滅', '迅刀'),
    skills=(
        # 「【レベルアップ】このカードをキャラデッキに戻す。」(u4)
        Skill(Timing.LEVELUP, (("return_to_chara_deck", {}),), unverified=True),
        # 「【リーダー】自分が受けるダメージ+1。自分の【ツバキ】の赤色のカードのダメージ+1。」(u13)
        Skill(Timing.STATIC,
              (("damage_taken_mod", {"amount": 1}),
               ("name_color_damage_buff", {"name": "ツバキ", "color": "red", "amount": 1})),
              leader_only=True, unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-002", "ツバキ", level=2, tags=('ブラックショア', '消滅', '迅刀'),
    skills=(
        Skill(Timing.LEVELUP, (("return_to_chara_deck", {}),), unverified=True),
        # 「【リーダー】各ターン、自分が最初に受けるダメージ−1。」(u7)
        Skill(Timing.STATIC, (("first_damage_taken_mod", {"amount": -1}),),
              leader_only=True, unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-003", "ツバキ", level=1, tags=('ブラックショア', '消滅', '迅刀'),
    skills=(
        # 「【登場】/【レベルアップ】トラッシュから＜通常攻撃＞1枚を手札に加えてもよい。」(u1)
        Skill(Timing.ENTER, (("trash_to_hand", {"tag": "通常攻撃", "count": 1}),),
              optional=True, unverified=True),
        Skill(Timing.LEVELUP, (("trash_to_hand", {"tag": "通常攻撃", "count": 1}),),
              optional=True, unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-004", "ツバキ", level=1, tags=('ブラックショア', '消滅', '迅刀'),
    skills=(Skill(
        Timing.JUDGE,
        (("reveal_top_to_hand", {"count": 1}),),
        condition={"self_result": "lose", "self_color": Color.RED, "opp_color": Color.BLUE},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    "BP01-005", "ツバキ", level=0, tags=('ブラックショア', '消滅', '迅刀'),
    skills=(Skill(
        # 「【リーダー】【判定】自分が勝利した場合、トラッシュから＜通常攻撃＞1枚を手札に加えてもよい。」
        Timing.JUDGE,
        (("trash_to_hand", {"tag": "通常攻撃", "count": 1}),),
        condition={"self_result": "win"},
        leader_only=True, optional=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-006", "ショアキーパー", level=2, tags=('ブラックショア', '回折', '増幅器'),
    skills=(Skill(
        # 「1ターン2回、自分のライフが回復した時、カード1枚を引いてもよい。」
        # 回数は状態欄 heals_this_turn で数える。_heal が誘発させる。
        Timing.ON_HEAL,
        (("draw", {"count": 1}),),
        condition={"heals_this_turn_lt": 3},
        optional=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-007", "ショアキーパー", level=2, tags=('ブラックショア', '回折', '増幅器'),
    skills=(Skill(
        # 「【リーダー】【自分の対抗フェイズ開始時】自分の手札が4枚以下の場合、5枚になるまでカードを引く。」
        Timing.CLASH_PHASE_START,
        (("draw_to", {"count": 5}),),
        condition={"is_turn_player": True, "hand_size_lte": 4},
        leader_only=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-008", "ショアキーパー", level=1, tags=('ブラックショア', '回折', '増幅器'),
    skills=(Skill(
        # 「【切り替え】カード1枚を引いてもよい。そうした場合、自分の手札1枚を捨てる。」
        # 「そうした場合」＝引いたなら必ず捨てる。任意なのは全体（optional）。
        Timing.SWITCHED,
        (("draw", {"count": 1}), ("discard_self", {"count": 1})),
        optional=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-009", "ショアキーパー", level=1, tags=('ブラックショア', '回折', '増幅器'),
    skills=(
        # 「【登場】/【レベルアップ】トラッシュから＜変奏スキル＞1枚を手札に加えてもよい。」(u1)
        Skill(Timing.ENTER, (("trash_to_hand", {"tag": "変奏スキル", "count": 1}),),
              optional=True, unverified=True),
        Skill(Timing.LEVELUP, (("trash_to_hand", {"tag": "変奏スキル", "count": 1}),),
              optional=True, unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-010", "ショアキーパー", level=0, tags=('ブラックショア', '回折', '増幅器'),
    skills=(
        Skill(
            Timing.CLASH,
            (("reveal_top_to_hand", {"count": 1}),),
            condition={"self_color": Color.GREEN},
            leader_only=True, optional=True,
        ),
        Skill(
            Timing.JUDGE,
            (("heal_self", {"amount": 1}),),
            condition={"self_result": "win", "self_color": Color.GREEN},
            leader_only=True,
        ),
    ),
))
_chara(CharaCard(
    "BP01-011", "アンコ", level=2, tags=('ブラックショア', '焦熱', '増幅器'),
    skills=(
        # 「このカードはカード効果でのみレベルアップできる。」(u3)
        # 「自分の【アンコ】の赤色のカードのダメージ+1。」
        Skill(Timing.STATIC,
              (("levelup_by_effect_only", {}),
               ("name_color_damage_buff", {"name": "アンコ", "color": "red", "amount": 1})),
              unverified=True),
        # 「【自分のターン終了時】このカードがこのターン以外に登場した場合、
        #   このカードをキャラデッキに戻す。」(u4)
        Skill(Timing.TURN_END, (("return_to_chara_deck", {}),),
              condition={"is_turn_player": True, "entered_turn_is_not_current": True},
              unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-012", "アンコ", level=2, tags=('ブラックショア', '焦熱', '増幅器'),
    skills=(Skill(
        # 「【リーダー】【各ターン終了時】このターン中、相手がダメージを受けた場合、
        #   トラッシュから【アンコ】のカード1枚を手札に加えてもよい。」
        Timing.TURN_END,
        (("trash_to_hand", {"chara": "アンコ", "count": 1}),),
        condition={"opp_damaged_this_turn": True},
        leader_only=True, optional=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-013", "アンコ", level=1, tags=('ブラックショア', '焦熱', '増幅器'),
    skills=(
        # 「【登場】/【レベルアップ】トラッシュから【アンコ】の赤色のカード1枚を手札に加えてもよい。」(u1)
        Skill(Timing.ENTER,
              (("trash_to_hand", {"chara": "アンコ", "color": "red", "count": 1}),),
              optional=True, unverified=True),
        Skill(Timing.LEVELUP,
              (("trash_to_hand", {"chara": "アンコ", "color": "red", "count": 1}),),
              optional=True, unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-014", "アンコ", level=1, tags=('ブラックショア', '焦熱', '増幅器'),
    skills=(Skill(
        # 「【リーダー】自分の【アンコ】の＜重撃＞と＜共鳴回路＞は
        #   『【判定】自分がこのカードで赤色のカードに敗北した場合、
        #     このターンの対抗フェイズの終了時に、相手にこのカードのダメージを与える。』を得る。」
        # 付与は今汐Lv2 と同じ常在型の型。判定ステップが読む（`_collect_granted_deferred_damage`）。
        Timing.STATIC,
        (("grant_deferred_damage_on_loss",
          {"chara": "アンコ", "tag": "重撃", "set_tag": "共鳴回路"}),),
        leader_only=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-015", "アンコ", level=0, tags=('ブラックショア', '焦熱', '増幅器'),
    skills=(Skill(
        # 「【リーダー】各ターン、自分が最初に使用した【アンコ】の＜基本攻撃＞のダメージ+2。」(u7)
        Timing.STATIC,
        (("first_use_damage_buff",
          {"name": "アンコ", "tag": "基本攻撃", "amount": 2}),),
        leader_only=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-016", "漂泊者（女）", level=2, tags=('回折', '迅刀'),
    skills=(Skill(
        # 「【リーダー】【判定】自分が緑色のカードで青色のカードに勝利し、
        #   かつ自分の手札が7枚以下の場合、8枚になるまでカードを引く。」
        Timing.JUDGE,
        (("draw_to", {"count": 8}),),
        condition={"self_result": "win", "self_color": Color.GREEN,
                   "opp_color": Color.BLUE, "hand_size_lte": 7},
        leader_only=True,
    ),),
))
_chara(CharaCard(
    "BP01-017", "漂泊者（女）", level=1, tags=('回折', '迅刀'),
    skills=(
        # 「【登場】/【レベルアップ】自分のデッキの上から1枚を公開し、手札に加えてもよい。」
        # 並記は**別の場面**を指す (u1) ので、スキルを 2 つに分ける。
        Skill(Timing.ENTER, (("reveal_top_to_hand", {"count": 1}),),
              optional=True, unverified=True),
        Skill(Timing.LEVELUP, (("reveal_top_to_hand", {"count": 1}),),
              optional=True, unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-019", "漂泊者（男）", level=2, tags=('回折', '迅刀'),
    skills=(Skill(
        Timing.JUDGE,
        (("pursuit", {"count": 3}),),
        condition={"self_result": "win", "self_color": Color.GREEN},
        leader_only=True,
    ),),
))
_chara(CharaCard(
    "BP01-020", "漂泊者（男）", level=1, tags=('回折', '迅刀'),
    skills=(
        # 「【登場】/【レベルアップ】自分のデッキの上から1枚を公開し、手札に加えてもよい。」
        Skill(Timing.ENTER, (("reveal_top_to_hand", {"count": 1}),),
              optional=True, unverified=True),
        Skill(Timing.LEVELUP, (("reveal_top_to_hand", {"count": 1}),),
              optional=True, unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-022", "秧秧", level=2, tags=('瑝瓏', '気動', '迅刀'),
    skills=(Skill(
        # 「【自分のターン終了時】自分の手札1枚を捨ててもよい。
        #   そうした場合、自分のリーダーを「秧秧」に切り替える。」(u14)
        Timing.TURN_END,
        (("discard_self", {"count": 1}), ("switch_leader_to", {"name": "秧秧"})),
        condition={"is_turn_player": True},
        optional=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-023", "秧秧", level=1, tags=('瑝瓏', '気動', '迅刀'),
    skills=(
        # 「【登場】/【レベルアップ】自分のデッキの上から1枚を協奏エリアに置く。」（強制）
        Skill(Timing.ENTER, (("top_to_concerto", {"count": 1}),), unverified=True),
        Skill(Timing.LEVELUP, (("top_to_concerto", {"count": 1}),), unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-025", "熾霞", level=2, tags=('瑝瓏', '焦熱', '拳銃'),
    skills=(Skill(
        # 「【リーダー】【各対抗フェイズ終了時】自分のアクションエリアに＜基本攻撃＞が
        #   2枚以上ある場合、相手にダメージ3を与える。」
        Timing.CLASH_PHASE_END,
        (("damage_opponent", {"amount": 3}),),
        condition={"action_area_tag_count_gte": ("基本攻撃", 2)},
        leader_only=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-026", "熾霞", level=1, tags=('瑝瓏', '焦熱', '拳銃'),
    skills=(
        # 「【登場】/【レベルアップ】トラッシュから＜基本攻撃＞1枚を手札に加えてもよい。」(u1)
        Skill(Timing.ENTER, (("trash_to_hand", {"tag": "基本攻撃", "count": 1}),),
              optional=True, unverified=True),
        Skill(Timing.LEVELUP, (("trash_to_hand", {"tag": "基本攻撃", "count": 1}),),
              optional=True, unverified=True),
    ),
))
_chara(CharaCard(
    "BP01-028", "今汐", level=2, tags=('瑝瓏', '回折', '長刃'),
    skills=(Skill(
        # 「【リーダー】【判定】自分が自分のターン中に勝利した場合、
        #   自分のデッキの上から5枚を公開してもよい。
        #   その中から全ての【今汐】のカードを手札に加え、残りをトラッシュに置く。」
        Timing.JUDGE,
        (("reveal_n_take_matching", {"count": 5, "chara": "今汐"}),),
        condition={"self_result": "win", "is_turn_player": True},
        leader_only=True, optional=True, unverified=True,
    ),),
))
_chara(CharaCard(
    "BP01-029", "今汐", level=1, tags=('瑝瓏', '回折', '長刃'),
    skills=(Skill(
        Timing.JUDGE,
        (("damage_opponent", {"amount": 2}),),
        condition={"self_result": "win", "self_color": Color.RED},
        leader_only=True,
    ),),
))
_chara(CharaCard(
    "BP01-031", "散華", level=2, tags=('瑝瓏', '凝縮', '迅刀'),
    skills=(Skill(
        Timing.JUDGE,
        (("switch_leader", {}), ("pursuit", {"count": 3})),
        condition={"self_result": "win", "self_color": Color.BLUE},
        leader_only=True, optional=True,
    ),),
))
_chara(CharaCard(
    "BP01-032", "散華", level=1, tags=('瑝瓏', '凝縮', '迅刀'),
    skills=(
        # 「【登場】/【レベルアップ】トラッシュからカード1枚を協奏エリアに置いてもよい。」(u1)
        Skill(Timing.ENTER, (("trash_to_concerto", {"count": 1}),),
              optional=True, unverified=True),
        Skill(Timing.LEVELUP, (("trash_to_concerto", {"count": 1}),),
              optional=True, unverified=True),
    ),
))

# --- BP01 アクションカード 41 -------------------------------------------------
_action(ActionCard(
    "BP01-034", "信号機モドキ", Color.RED, cost=0, speed=5, damage=1,
    tags=('音骸', '山を轟かせる崩火', '焦熱'),
    dedicated_to=None,
    skills=(Skill(
        # 「自分の協奏エリアにこのカードを含む、2種類以上の＜山を轟かせる崩火＞がある場合、
        #   各ターンに自分が最初に使用する＜焦熱＞のダメージ+1。」(u6・u7)
        # **協奏エリアに置かれたこのカード**に載る常在型なので、ダメージ計算側が
        # 協奏エリアを走査して読む（`_card_damage_bonus`）。
        Timing.STATIC,
        (("concerto_set_first_use_buff",
          {"set_tag": "山を轟かせる崩火", "tag": "焦熱", "count": 2, "amount": 1}),),
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-035", "燎原の炎騎", Color.RED, cost=1, speed=5, damage=2,
    tags=('音骸', '山を轟かせる崩火', '焦熱'),
    dedicated_to=None,
    skills=(Skill(
        # 【優勢】相手にダメージを与えた時、相手の手札4枚につき、ランダムに手札1枚を捨てさせる（端数切り捨て・u9）。
        # 【優勢】は条件 `dominant`（u2）。誘発は**このカード自身が与えたときだけ**（u18）。
        Timing.ON_DAMAGE_DEALT,
        (("opp_discard_random", {"per": 4}),),
        condition={"dominant": True},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-036", "グルッポ", Color.RED, cost=0, speed=5, damage=1,
    tags=('音骸', '夜にこびり付く白霜', '凝縮'),
    dedicated_to=None,
    skills=(Skill(
        # 「自分の協奏エリアにこのカードを含む、2種類以上の＜夜にこびり付く白霜＞がある場合、
        #   各ターンに自分が最初に使用する＜凝縮＞のダメージ+1。」(u6・u7)
        # **協奏エリアに置かれたこのカード**に載る常在型なので、ダメージ計算側が
        # 協奏エリアを走査して読む（`_card_damage_bonus`）。
        Timing.STATIC,
        (("concerto_set_first_use_buff",
          {"set_tag": "夜にこびり付く白霜", "tag": "凝縮", "count": 2, "amount": 1}),),
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-037", "輝き蛍の軍勢", Color.RED, cost=1, speed=5, damage=2,
    tags=('音骸', '夜にこびり付く白霜', '凝縮'),
    dedicated_to=None,
    skills=(Skill(
        # 【優勢】相手にダメージを与えた時、相手の協奏エリアから1枚をトラッシュに置く（選ぶ側は効果のオーナー・u8）。
        # 【優勢】は条件 `dominant`（u2）。誘発は**このカード自身が与えたときだけ**（u18）。
        Timing.ON_DAMAGE_DEALT,
        (("opp_concerto_to_trash", {"count": 1}),),
        condition={"dominant": True},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-038", "ジュルッポ", Color.RED, cost=0, speed=5, damage=1,
    tags=('音骸', '谷を突き抜ける長風', '気動'),
    dedicated_to=None,
    skills=(Skill(
        # 「自分の協奏エリアにこのカードを含む、2種類以上の＜谷を突き抜ける長風＞がある場合、
        #   各ターンに自分が最初に使用する＜気動＞のダメージ+1。」(u6・u7)
        # **協奏エリアに置かれたこのカード**に載る常在型なので、ダメージ計算側が
        # 協奏エリアを走査して読む（`_card_damage_bonus`）。
        Timing.STATIC,
        (("concerto_set_first_use_buff",
          {"set_tag": "谷を突き抜ける長風", "tag": "気動", "count": 2, "amount": 1}),),
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-039", "飛廉の大猿", Color.RED, cost=1, speed=5, damage=2,
    tags=('音骸', '谷を突き抜ける長風', '気動'),
    dedicated_to=None,
    skills=(Skill(
        # 【優勢】相手にダメージを与えた時、相手の手札からランダム1枚をデッキの下に置く。
        # 【優勢】は条件 `dominant`（u2）。誘発は**このカード自身が与えたときだけ**（u18）。
        Timing.ON_DAMAGE_DEALT,
        (("opp_hand_random_to_deck_bottom", {"count": 1}),),
        condition={"dominant": True},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-040", "トゲバラタケ", Color.RED, cost=0, speed=5, damage=1,
    tags=('音骸', '二度と輝かない沈日', '消滅'),
    dedicated_to=None,
    skills=(Skill(
        # 「自分の協奏エリアにこのカードを含む、2種類以上の＜二度と輝かない沈日＞がある場合、
        #   各ターンに自分が最初に使用する＜消滅＞のダメージ+1。」(u6・u7)
        # **協奏エリアに置かれたこのカード**に載る常在型なので、ダメージ計算側が
        # 協奏エリアを走査して読む（`_card_damage_bonus`）。
        Timing.STATIC,
        (("concerto_set_first_use_buff",
          {"set_tag": "二度と輝かない沈日", "tag": "消滅", "count": 2, "amount": 1}),),
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-041", "無冠者", Color.RED, cost=1, speed=5, damage=2,
    tags=('音骸', '二度と輝かない沈日', '消滅'),
    dedicated_to=None,
    skills=(Skill(
        # 【優勢】相手にダメージを与えた時、相手のデッキの上から3枚をトラッシュに置く。
        # 【優勢】は条件 `dominant`（u2）。誘発は**このカード自身が与えたときだけ**（u18）。
        Timing.ON_DAMAGE_DEALT,
        (("mill_opponent_deck_top", {"count": 3}),),
        condition={"dominant": True},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-042", "遊弋蝶", Color.RED, cost=0, speed=5, damage=1,
    tags=('音骸', '闇を取り払う浮星', '回折'),
    dedicated_to=None,
    skills=(Skill(
        # 「自分の協奏エリアにこのカードを含む、2種類以上の＜闇を取り払う浮星＞がある場合、
        #   各ターンに自分が最初に使用する＜回折＞のダメージ+1。」(u6・u7)
        # **協奏エリアに置かれたこのカード**に載る常在型なので、ダメージ計算側が
        # 協奏エリアを走査して読む（`_card_damage_bonus`）。
        Timing.STATIC,
        (("concerto_set_first_use_buff",
          {"set_tag": "闇を取り払う浮星", "tag": "回折", "count": 2, "amount": 1}),),
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-043", "哀切の凶鳥", Color.RED, cost=1, speed=5, damage=2,
    tags=('音骸', '闇を取り払う浮星', '回折'),
    dedicated_to=None,
    skills=(Skill(
        # 【優勢】相手にダメージを与えた時、相手のトラッシュから2枚までを相手のデッキの下に置く（選ぶ側は効果のオーナー・u8）。
        # 【優勢】は条件 `dominant`（u2）。誘発は**このカード自身が与えたときだけ**（u18）。
        Timing.ON_DAMAGE_DEALT,
        (("opp_trash_to_deck_bottom", {"count": 2}),),
        condition={"dominant": True},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-044", "品種改良·通常攻撃", Color.RED, cost=0, speed=8, damage=1,
    tags=('基本攻撃', '通常攻撃', '消滅'),
    dedicated_to='ツバキ',
))
_action(ActionCard(
    "BP01-045", "品種改良·回避反撃", Color.BLUE, cost=0, speed=0, damage=3,
    tags=('回避', '消滅'),
    dedicated_to='ツバキ',
))
_action(ActionCard(
    "BP01-046", "八千春秋", Color.RED, cost=0, speed=0, damage=0,
    tags=('変奏スキル',),
    dedicated_to='ツバキ',
    skills=(Skill(
        # 「【連撃】自分のリーダーを切り替える。「ツバキ」がリーダーに切り替えされた場合、
        #   自分の「ツバキ」をレベルアップする。」(u3)
        Timing.RUSH,
        (("switch_leader", {}),
         ("levelup_by_effect_if_switched", {"name": "ツバキ"})),
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-047", "品種改良·重撃", Color.RED, cost=0, speed=6, damage=1,
    tags=('基本攻撃', '重撃', '消滅'),
    dedicated_to='ツバキ',
    skills=(Skill(
        Timing.JUDGE, (("draw", {"count": 1}),), condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "BP01-048", "咲き誇る赤い椿", Color.RED, cost=1, speed=14, damage=1,
    tags=('共鳴スキル', '消滅'),
    dedicated_to='ツバキ', leader_skill=True,
    skills=(Skill(
        # 「【リーダースキル】【対抗】自分の「ツバキ」をレベルアップする。」(u3)
        Timing.CLASH, (("levelup_by_effect", {"name": "ツバキ"}),), unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-050", "蔓の舞", Color.RED, cost=0, speed=6, damage=1,
    tags=('通常攻撃', '消滅'),
    dedicated_to='ツバキ',
    skills=(Skill(
        # 「【連撃】自分のアクションエリアに＜通常攻撃＞が2枚以上ある場合、このカードのダメージ+1。」
        Timing.RUSH,
        (("self_damage_buff", {"amount": 1}),),
        condition={"action_area_tag_count_gte": ("通常攻撃", 2)},
    ),),
))
_action(ActionCard(
    "BP01-051", "輪舞", Color.RED, cost=0, speed=6, damage=1,
    tags=('通常攻撃', '消滅'),
    dedicated_to='ツバキ',
    skills=(Skill(
        Timing.JUDGE, (("draw", {"count": 1}),), condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "BP01-052", "真源演算·通常攻撃", Color.RED, cost=0, speed=5, damage=1,
    tags=('基本攻撃', '通常攻撃', '回折'),
    dedicated_to='ショアキーパー',
))
_action(ActionCard(
    "BP01-053", "真源演算·回避", Color.BLUE, cost=0, speed=0, damage=0,
    tags=('回避',),
    dedicated_to='ショアキーパー',
    skills=(Skill(
        Timing.JUDGE, (("heal_self", {"amount": 1}),), condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "BP01-054", "啓発", Color.RED, cost=0, speed=0, damage=0,
    tags=('変奏スキル',),
    dedicated_to='ショアキーパー',
    skills=(Skill(
        # 「【連撃】自分のリーダーを切り替える。「ショアキーパー」が切り替えされた場合、自分のライフ1を回復する。」
        Timing.RUSH,
        (("switch_leader", {}),
         ("heal_if_switched", {"name": "ショアキーパー", "amount": 1})),
    ),),
))
_action(ActionCard(
    "BP01-055", "真源演算·重撃", Color.RED, cost=0, speed=3, damage=1,
    tags=('基本攻撃', '重撃', '回折'),
    dedicated_to='ショアキーパー',
    skills=(Skill(
        # 「自分のライフが相手より多い場合、このカードのダメージ+1。」
        # タイミング語を持たない常在型で、**このカード自身**にだけ効く。
        Timing.STATIC,
        (("own_card_damage_buff", {"amount": 1}),),
        condition={"life_greater_than_opponent": True},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-056", "カオス理論", Color.RED, cost=1, speed=11, damage=1,
    tags=('共鳴スキル', '回折'),
    dedicated_to='ショアキーパー', leader_skill=True,
    skills=(Skill(
        # 「【リーダースキル】【判定】自分が勝利した場合、自分の「ショアキーパー」をレベルアップする。」(u3)
        Timing.JUDGE,
        (("levelup_by_effect", {"name": "ショアキーパー"}),),
        condition={"self_result": "win"}, unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-058", "超制限", Color.GREEN, cost=0, speed=5, damage=0,
    tags=(),
    dedicated_to='ショアキーパー',
    skills=(
        # 「【判定】自分が勝利した場合、カード2枚を引く。」
        Skill(Timing.JUDGE, (("draw", {"count": 2}),),
              condition={"self_result": "win"}),
        # 「【優勢】【判定】自分が敗北し、かつ自分のリーダーが「ショアキーパー」の場合、
        #   このターン中、相手は連撃できない。」(u12: 即時に立てる)
        Skill(Timing.JUDGE, (("forbid_rush_opponent_now", {}),),
              condition={"dominant": True, "self_result": "lose",
                         "leader_name_is": "ショアキーパー"},
              unverified=True),
    ),
))
_action(ActionCard(
    "BP01-059", "メェ、出撃·通常攻撃", Color.RED, cost=0, speed=5, damage=1,
    tags=('基本攻撃', '通常攻撃', '焦熱'),
    dedicated_to='アンコ',
    skills=(Skill(
        # 「【優勢】【対抗】自分のリーダーが「アンコ」の場合、このカードのスピードは10になる。」
        # 【対抗】は判定より前に解決されるので、上書きは同じ対抗の判定に間に合う (u10)。
        Timing.CLASH,
        (("speed_override", {"speed": 10}),),
        condition={"dominant": True, "leader_name_is": "アンコ"},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-060", "メェ、出撃·重撃", Color.RED, cost=0, speed=3, damage=1,
    tags=('基本攻撃', '重撃', '焦熱'),
    dedicated_to='アンコ',
    skills=(Skill(
        # 「相手にダメージを与えた時、自分のリーダーが「アンコ」の場合、カード1枚を引く。」(u18)
        Timing.ON_DAMAGE_DEALT,
        (("draw", {"count": 1}),),
        condition={"leader_name_is": "アンコ"},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-061", "黒メェと白メェ", Color.RED, cost=0, speed=0, damage=3,
    tags=('共鳴回路', '共鳴解放', '焦熱'),
    dedicated_to='アンコ', leader_skill=True,
    skills=(Skill(
        # 「【対抗】/【連撃】このターン中、自分は連撃できない。」(u12: 即時に立てる)
        Timing.CLASH, (("forbid_rush_self_now", {}),), unverified=True,
    ), Skill(
        Timing.RUSH, (("forbid_rush_self_now", {}),), unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-063", "メェ、助けて", Color.RED, cost=0, speed=0, damage=0,
    tags=('変奏スキル',),
    dedicated_to='アンコ',
    skills=(Skill(
        # 「【連撃】自分のリーダーを切り替える。「アンコ」が切り替えされた場合、
        #   トラッシュから＜変奏スキル＞以外の【アンコ】の赤色のカード1枚を手札に加える。」（強制）
        Timing.RUSH,
        (("switch_leader", {}),
         ("trash_to_hand_if_switched",
          {"name": "アンコ", "chara": "アンコ", "color": "red",
           "exclude_tag": "変奏スキル", "count": 1})),
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-064", "メェ、出撃·回避反撃", Color.BLUE, cost=0, speed=0, damage=3,
    tags=('回避反撃', '焦熱'),
    dedicated_to='アンコ',
))
_action(ActionCard(
    "BP01-065", "音の形·重撃", Color.RED, cost=0, speed=6, damage=1,
    tags=('基本攻撃', '重撃'),
    dedicated_to='漂泊者（女）',
    skills=(Skill(
        # 「【連撃】自分の手札1枚を捨ててもよい。そうした場合、このカードのダメージ+1。」
        Timing.RUSH,
        (("discard_self", {"count": 1}),
         ("self_damage_buff_if_discarded", {"amount": 1})),
        optional=True,
    ),),
))
_action(ActionCard(
    "BP01-066", "音の形·空中攻撃", Color.RED, cost=0, speed=6, damage=1,
    tags=('基本攻撃', '空中攻撃'),
    dedicated_to='漂泊者（女）',
    skills=(Skill(
        Timing.JUDGE, (("draw", {"count": 1}),), condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "BP01-067", "音の形·重撃", Color.RED, cost=0, speed=6, damage=1,
    tags=('基本攻撃', '重撃'),
    dedicated_to='漂泊者（男）',
    skills=(Skill(
        # 「【連撃】自分の手札1枚を捨ててもよい。そうした場合、このカードのダメージ+1。」
        Timing.RUSH,
        (("discard_self", {"count": 1}),
         ("self_damage_buff_if_discarded", {"amount": 1})),
        optional=True,
    ),),
))
_action(ActionCard(
    "BP01-068", "音の形·空中攻撃", Color.RED, cost=0, speed=6, damage=1,
    tags=('基本攻撃', '空中攻撃'),
    dedicated_to='漂泊者（男）',
    skills=(Skill(
        Timing.JUDGE, (("draw", {"count": 1}),), condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "BP01-069", "羽乱舞·回避", Color.BLUE, cost=0, speed=0, damage=0,
    tags=('回避', '滞空'),
    dedicated_to='秧秧',
    skills=(
        # 「【判定】自分が勝利した場合、【追撃1】。」
        Skill(Timing.JUDGE, (("pursuit", {"count": 1}),),
              condition={"self_result": "win"}),
        # 「【各対抗フェイズ終了時】自分のリーダーが「秧秧」の場合、
        #   コスト1を支払ってこのカードを手札に加えてもよい。」(u11)
        Skill(Timing.CLASH_PHASE_END,
              (("pay_cost_return_self_to_hand", {"cost": 1}),),
              condition={"leader_name_is": "秧秧"},
              optional=True, unverified=True),
    ),
))
_action(ActionCard(
    "BP01-070", "流風", Color.RED, cost=1, speed=14, damage=2,
    tags=('共鳴スキル', '気動'),
    dedicated_to='秧秧', leader_skill=True,
    skills=(Skill(
        # 「【リーダースキル】【判定】自分が勝利した場合、トラッシュから青色のカード1枚を手札に加える。」（強制）
        Timing.JUDGE,
        (("trash_to_hand", {"color": "blue", "count": 1}),),
        condition={"self_result": "win"}, unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-071", "音を乗せる軽羽", Color.RED, cost=0, speed=6, damage=1,
    tags=('空中攻撃', '気動'),
    dedicated_to='秧秧',
    skills=(Skill(
        # 「【連撃】このターン中、自分が直前に使用したカードが＜滞空＞の場合、
        #   自分のデッキの上から1枚を協奏エリアに置く。」
        # 「直前に使用した」は自分自身を含まない。`_note_card_use` は連撃の
        # ダメージ計算のあとに呼ばれるので、ここではまだ前のカードが入っている。
        Timing.RUSH,
        (("top_to_concerto", {"count": 1}),),
        condition={"last_used_card_has_tag": "滞空"},
        unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-072", "ドカンカン制圧", Color.RED, cost=1, speed=12, damage=2,
    tags=('共鳴回路', '焦熱'),
    dedicated_to='熾霞', leader_skill=True,
    skills=(Skill(
        # 「【リーダースキル】【優勢】【対抗】トラッシュから＜基本攻撃＞か＜共鳴解放＞1枚を手札に加える。」
        Timing.CLASH,
        (("trash_to_hand", {"tag": "基本攻撃|共鳴解放", "count": 1}),),
        condition={"dominant": True}, unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-073", "遍く照らす神光", Color.RED, cost=1, speed=13, damage=1,
    tags=('共鳴スキル', '回折'),
    dedicated_to='今汐', leader_skill=True,
    skills=(Skill(
        # 「【リーダースキル】【判定】自分が勝利した場合、自分のデッキから「龍憑の天舞」1枚を
        #   手札に加える。その後、デッキをシャッフルする。」
        # **該当が無くてもシャッフルする**（u15）＝乱数をちょうど 1 回消費する。
        Timing.JUDGE,
        (("search_deck", {"card_name": "龍憑の天舞"}),),
        condition={"self_result": "win"}, unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-074", "天幕を突き破る驚龍", Color.RED, cost=1, speed=11, damage=0,
    tags=('共鳴回路', '共鳴スキル', '回折'),
    dedicated_to='今汐', leader_skill=True,
    skills=(Skill(
        # 「【連撃】自分のアクションエリアのカード1枚につき、このカードのダメージ+1。」
        Timing.RUSH,
        (("self_damage_buff_per_action_area", {"amount": 1}),),
    ), Skill(
        # 「【対抗】/【連撃】このターン中、自分は連撃できない。」(u12)
        Timing.CLASH, (("forbid_rush_self_now", {}),), unverified=True,
    ), Skill(
        Timing.RUSH, (("forbid_rush_self_now", {}),), unverified=True,
    ),),
))
_action(ActionCard(
    "BP01-075", "寒風散らす光·重撃", Color.RED, cost=0, speed=5, damage=1,
    tags=('基本攻撃', '重撃', '回折'),
    dedicated_to='今汐',
    skills=(Skill(
        Timing.JUDGE, (("draw", {"count": 1}),), condition={"self_result": "win"},
    ),),
))
_action(ActionCard(
    "BP01-076", "凛然穿撃", Color.BLUE, cost=1, speed=0, damage=0,
    tags=('回避',),
    dedicated_to='散華',
    skills=(
        # 「【対抗】自分のリーダーを「散華」に切り替えてもよい。」(u14)
        Skill(Timing.CLASH, (("switch_leader_to", {"name": "散華"}),),
              optional=True, unverified=True),
        # 「【判定】自分が勝利し、かつ自分のリーダーが「散華」の場合、自分の「散華」をレベルアップする。」(u3)
        Skill(Timing.JUDGE, (("levelup_by_effect", {"name": "散華"}),),
              condition={"self_result": "win", "leader_name_is": "散華"},
              unverified=True),
    ),
))
_action(ActionCard(
    "BP01-077", "氷砕", Color.RED, cost=1, speed=11, damage=2,
    tags=('共鳴回路', '共鳴スキル', '凝縮'),
    dedicated_to='散華', leader_skill=True,
    skills=(Skill(
        # 「【判定】自分が勝利し、かつ自分の協奏エリアに【散華】のカードがある場合、
        #   自分のリーダーを切り替えてもよい。」
        Timing.JUDGE,
        (("switch_leader", {}),),
        condition={"self_result": "win", "concerto_has_chara_card": "散華"},
        optional=True, unverified=True,
    ),),
))

# --- 公式が未掲載の 3 番号（unverified の枠）-----------------------------------
#
# 取得漏れではない（公式の商品詳細が言うアクション 50 種と、取得できた 47 種の差が 3 で合う・D-078）。
#
# **2026-09-12 に公式サイトへ掲載され、3 枚とも取得した**（`cards/cards_official_20260912_add3.json`）。
# 数値・色・タグ・専用キャラは正本に入れて実値に差し替えてある。添字は K-1 で確保した位置のまま
# 動いていないので `ENCODING_VERSION` は 4 のままでよい（これが枠を先に取っておいた狙いである）。
#
# **3 枚とも完成している**（2026-09-13・段 K-5）。`BP01-049` は効果欄そのものが無い＝バニラ。
# 残る 2 枚のために語彙を 3 つ足した:
#   - `BP01-057`「このターン中、自分が次に使用する2枚の＜変奏スキル＞は『【連撃】カード1枚を引く。』を得る」
#     → `grant_rush_draw_to_variation_skills`。数えは `GameState.variation_rush_draw`。
#   - `BP01-062`「【優勢】このカードのコスト-1」→ 常在型の `cost_mod`（`_effective_cost` が読む）。
#     （`raise_opponent_red_cost_next_turn` は相手の赤コストを上げる別物で、流用はしていない。）
#   - `BP01-062`「自分のキャラデッキからレベル2の「アンコ」1枚を…上に置く」
#     → `levelup_by_effect` に任意の `level` を足した（省略時は従来どおり次のレベル）。
# **3 つとも既定では誰も使わない**ので、この 2 枚を入れない限り対局は 1 手も変わらない
# （`tests/test_bp01_k5.py` T-K5-9 と、SD001/SD02 の digest 一致で確かめた）。
# 挙動の検査は `tests/test_bp01_k5.py`。2 枚はスモークデッキにも入れた（K_smoke_ANKO）。
# 読み方は 2026-09-12 にマスターが裁定済み（u19〜u21・`rules_draft.md` §9-6 の表）:
#   - u19: 「次に使用する2枚の＜変奏スキル＞」は**連撃で使った札だけ**を数える
#     （このカード自身が対抗の札なので、同じターンの対抗はもう起きない）。ターン終了で消える。
#   - u20: 「【優勢】このカードのコスト-1」は**常在の割引・下限 0**。
#   - u21: レベル 2 の「アンコ」が複数あれば**左端から自動**。
#     **すでにレベル 2 でもレベルアップできる**（§6.3-3。同レベルも上に置ける）。
# 検査 `tests/test_bp01.py` の T-K-10 は `xfail(strict=True)` で置いてあり、実装した時点で
# 設計どおり「予想外に通った」で落ちたので旗を外した（T-K-4 と同じやり方）。
_action(ActionCard(
    "BP01-049", "花の余燼", Color.RED, cost=2, speed=13, damage=5,
    tags=('共鳴解放', '消滅'),
    dedicated_to='ツバキ',
    # 効果欄そのものが無いカード（カード画像にテキスト枠が無い）。バニラで完成している。
    unverified_fields=("color",),
))
_action(ActionCard(
    "BP01-057", "終末ループ", Color.GREEN, cost=1, speed=11, damage=0,
    tags=('共鳴解放',),
    dedicated_to='ショアキーパー', leader_skill=True,
    # 効果の要旨（**公式文はここに転記しない**。正本は cards/cards_structured.json・D-083 追記 4）:
    #   リーダースキル。対抗で、このターンに自分が次に使う＜変奏スキル＞2 枚に
    #   常在の付与を行い、判定の勝利時にライフ回復と追撃を足す。
    skills=(
        # u19: 「次に使用する2枚の＜変奏スキル＞」は**連撃で使った札だけ**を数える
        # （このカード自身が対抗の札なので、同じターンの対抗はもう起きない）。
        # ターン終了で消える。
        Skill(Timing.CLASH,
              (("grant_rush_draw_to_variation_skills", {"count": 2}),),
              unverified=True),
        # 【判定】自分が勝利した場合、ライフ1回復 ＋ 追撃8 (§6.4(2)-5)。
        Skill(Timing.JUDGE,
              (("heal_self", {"amount": 1}), ("pursuit", {"count": 8})),
              condition={"self_result": "win"},
              unverified=True),
    ),
    # 効果文の出所は公式サイト（2026-09-12 取得）なので `skills` の旗は外す。
    # 残る不確かさは**我々の読み**であり、それは各 Skill の `unverified=True`（u19〜u21）が担う。
    unverified_fields=("color",),
))
_action(ActionCard(
    "BP01-062", "黒メェ大暴走", Color.RED, cost=2, speed=11, damage=3,
    tags=('共鳴解放', '焦熱'),
    dedicated_to='アンコ',
    # 効果の要旨（**公式文はここに転記しない**。正本は cards/cards_structured.json・D-083 追記 4）:
    #   優勢のときコストが下がる。対抗で、キャラデッキのレベル 2 の専用キャラを
    #   自分のキャラエリアに重ねて置き（レベルアップとしても扱う）、リーダーを切り替える。
    skills=(
        # u20: 「【優勢】このカードのコスト-1」は**常在の割引・下限 0**。
        # `_effective_cost` が読む（使用可否の判定にも支払いにも効く）。
        Skill(Timing.STATIC,
              (("cost_mod", {"delta": -1}),),
              condition={"dominant": True},
              unverified=True),
        # u21: レベル 2 の「アンコ」が複数あれば左端から自動。**すでにレベル 2 でも
        # レベルアップできる**（§6.3-3。同レベルも上に置ける）。
        # 「この処理はレベルアップとしても扱う」＝【登場】【レベルアップ】が誘発する。
        Skill(Timing.CLASH,
              (("levelup_by_effect", {"name": "アンコ", "level": 2}),
               ("switch_leader_to", {"name": "アンコ"})),
              unverified=True),
    ),
    # 同上（u20・u21）。`color` だけはカード画像の帯から読んだ値なので旗が残る。
    unverified_fields=("color",),
))
