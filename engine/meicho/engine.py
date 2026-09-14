"""鳴潮：対決 ルールエンジン中核。rules_draft.md v0.10 準拠。

API（すべて純粋関数。state を変更せず新しい state を返す）:
    initial_state(config, seed)        -> GameState
    decision_players(state)            -> list[int]   いま決定を求められているプレイヤー
    legal_actions(state, player)       -> list[dict]  そのプレイヤーの合法手
    apply(state, actions)              -> GameState   actions: {player: action}
    outcome(state)                     -> Optional[int]
    observe(state, player)             -> dict        情報集合（そのプレイヤーから見える情報）

同時手番の扱い (§10):
    対抗ステップ等では decision_players が [0, 1] を返す。apply は要求された
    全プレイヤー分の行動が揃って初めて解決を進める。

意図的な簡略化（decisions.md 参照）:
    - コスト支払い・レベルアップ時の手札捨ては左端から自動選択
    - 「〜してもよい」効果は常に実行
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .cards import (ACTION_CARDS, AREA_TIMINGS, CHARA_CARDS, ONKAI_TAG, ActionCard,
                    CharaCard, Color, Skill, Timing)
from .state import (
    CLASH_COLOR_INDEX, CLASH_PASS, DRAW, DRAW_PER_TURN, FIRST_TURN_DRAW,
    HAND_LIMIT, MAX_LIFE, OPENING_HAND, RUSH_UNLIMITED,
    CharaSlot, GameState, Phase, PlayerState,
)


@dataclass
class GameConfig:
    """デッキ構成。§3 の構築ルールを validate で検査する。"""
    chara_decks: list   # [player0: list[chara card_id], player1: ...]
    action_decks: list  # [player0: list[action card_id] (40枚), player1: ...]

    def validate(self) -> None:
        for pi in (0, 1):
            cd = self.chara_decks[pi]
            ad = self.action_decks[pi]
            charas = [CHARA_CARDS[c] for c in cd]
            names = {c.name for c in charas}
            # §3.1
            assert len(names) == 3, f"P{pi}: キャラは3種類ちょうど ({names})"
            assert 3 <= len(cd) <= 15, f"P{pi}: キャラデッキは3〜15枚"
            assert len(cd) == len(set(cd)), f"P{pi}: 同カード番号は1枚まで"
            for n in names:
                assert any(c.name == n and c.level == 0 for c in charas), \
                    f"P{pi}: {n} の Lv.0 が必要"
            # §3.2
            assert len(ad) == 40, f"P{pi}: アクションデッキは40枚ちょうど"
            for cid in set(ad):
                assert ad.count(cid) <= 3, f"P{pi}: {cid} は3枚まで"
                dedicated_to = ACTION_CARDS[cid].dedicated_to
                assert dedicated_to is None or dedicated_to in names, \
                    f"P{pi}: 専用カード {cid} に対応するキャラがいない"


# ---------------------------------------------------------------------------
# 初期化 (§5)
# ---------------------------------------------------------------------------

def initial_state(config: GameConfig, seed: int) -> GameState:
    config.validate()
    s = GameState(seed=seed, players=[PlayerState(), PlayerState()])
    for pi in (0, 1):
        p = s.players[pi]
        p.chara_deck = list(config.chara_decks[pi])
        p.action_deck = list(config.action_decks[pi])
        s.next_rng().shuffle(p.action_deck)  # §5-2
    s.phase = Phase.SETUP_CHARA
    return s


# ---------------------------------------------------------------------------
# 決定要求と合法手
# ---------------------------------------------------------------------------

def decision_players(s: GameState) -> list:
    if s.phase == Phase.SETUP_CHARA:
        return [pi for pi in (0, 1) if not s.players[pi].slots[0].stack]
    if s.phase == Phase.MULLIGAN:
        return [pi for pi in (0, 1) if not s.players[pi].mulligan_done]
    if s.phase == Phase.ACTION:
        return [s.turn_player]
    if s.phase == Phase.CLASH_SUBMIT:
        return [pi for pi in (0, 1) if s.pending_submission[pi] is None]
    if s.phase == Phase.CHOICE:
        # D-015: 効果解決中の選択。先頭の1件だけを順に処理する。
        return [s.pending_choices[0]["player"]] if s.pending_choices else []
    if s.phase == Phase.RUSH:
        return [s.clash_winner]
    if s.phase == Phase.TURN_END_DISCARD:
        return [s.turn_player]
    return []


def _effective_cost(s: GameState, pi: int, card: ActionCard) -> int:
    """カードの実効コスト (§6.4 使用条件I)。

    素のコストに、継続効果によるコスト修正を加えた値を返す。
    修正要因は 2 つ:
      - SD01-016「旋風」の「次のターン中、相手の赤色のカードのコスト+1」。
      - そのカード自身が持つ常在型の `cost_mod`（BP01-062「【優勢】このカードのコスト-1」・u20）。
        **常在の割引であり、下限は 0**（u20 のマスター裁定 2026-09-12）。

    コストを参照する箇所（使用可否判定・対抗の支払い・連撃の支払い）は
    必ずこの関数を経由すること。1箇所でも card.cost を直接読むと
    「払えないのに使える」等の不整合になる。

    `_action_timing_index` は (card_id, timing) で索引を持つので、常在型スキルを
    持たないカードでは空リストが返るだけで、対局中の費用はほぼ増えない。
    """
    cost = card.cost
    if s.red_cost_up[pi] and card.color == Color.RED:
        cost += 1
    for k in _action_timing_index(card.card_id, Timing.STATIC):
        sk = card.skills[k]
        if not any(op == "cost_mod" for op, _ in sk.effect):
            continue
        if not _skill_condition_met(s, pi, sk, {}):
            continue
        for op, prm in sk.effect:
            if op == "cost_mod":
                cost += prm["delta"]
    return max(0, cost)


def _usable_in_clash(s: GameState, pi: int, card: ActionCard) -> bool:
    """使用条件 I + II (§6.4)。

    使用条件II（追加条件）が課されるのは「リーダースキル」が明記されたカードのみ
    (rules_draft.md 133行目 / D-009)。単に専用キャラを持つだけのカードは、
    デッキ構築時の制約 (§3.2 rule3, GameConfig.validate) を満たしていれば
    リーダーが誰であっても使用できる。

    2026-08-20 修正: 旧実装は leader_lock (=専用キャラ名) を単純所持しているだけの
    カードにもリーダー一致を要求してしまっていた（D-009で発覚したバグ）。
    """
    if _effective_cost(s, pi, card) > len(s.players[pi].concerto):
        return False
    if card.leader_skill:
        leader = _leader_name(s, pi)
        if leader != card.dedicated_to:
            return False
    # v0.12 / BP01（D-079 追記 5・便 K 段 K-3）: ＜音骸＞は自分のアクションエリアに
    # **1 枚までしか存在できない**（u5）。2 枚目は**使用できない**（置いてからトラッシュ、ではない）。
    # §6.4 の使用条件と同じ場所に置く。対抗でも連撃でも同じく効く。
    if ONKAI_TAG in card.tags:
        if any(ONKAI_TAG in ACTION_CARDS[cid].tags
               for cid in s.players[pi].action_area):
            return False
    return True


def _levelup_by_effect_only(card: CharaCard) -> bool:
    """「このカードはカード効果でのみレベルアップできる」か (u3・BP01-011)。

    常在型に `levelup_by_effect_only` を書いたカードだけが True。
    カード定義は不変なので走査は安いが、`legal_actions` のホットループから呼ばれるので
    スキルが無いカードは即座に抜ける。
    """
    for sk in card.skills:
        if sk.timing is Timing.STATIC:
            for op, _prm in sk.effect:
                if op == "levelup_by_effect_only":
                    return True
    return False


def _trash_matches(card: ActionCard, prm: dict) -> bool:
    """トラッシュ回収の絞り込み（タグ／色／専用キャラ／「〜以外」）。

    書いていない欄は「問わない」。すべて満たしたものだけが対象になる。
    `tag` は「または」を `|` で繋げる（BP01-072 の「＜基本攻撃＞か＜共鳴解放＞」）。
    """
    if "tag" in prm and not any(t in card.tags for t in prm["tag"].split("|")):
        return False
    if "exclude_tag" in prm and prm["exclude_tag"] in card.tags:
        return False
    if "color" in prm and card.color.value != prm["color"]:
        return False
    if "chara" in prm and card.dedicated_to != prm["chara"]:
        return False
    if "card_name" in prm and card.name != prm["card_name"]:
        return False
    return True


def _static_damage_taken_mod(s: GameState, pi: int) -> int:
    """「自分が受けるダメージ +N / −N」(u13・BP01-001) の常在型ぶん。

    状態欄 `damage_taken_mod` は効果で立てる一時的な修正のために残してあり、
    こちらはキャラの常在スキルから毎回数える。該当カードが無ければ 0。
    """
    mod = 0
    for sk in _active_skills(s, pi, Timing.STATIC):
        for op, prm in sk.effect:
            if op == "damage_taken_mod":
                mod += prm["amount"]
    return mod


def _leader_name(s: GameState, pi: int) -> Optional[str]:
    stack = s.players[pi].slots[0].stack
    return CHARA_CARDS[stack[-1]].name if stack else None


def legal_actions(s: GameState, pi: int) -> list:
    p = s.players[pi]
    acts: list = []

    if s.phase == Phase.SETUP_CHARA and not p.slots[0].stack:
        lv0_names = sorted({CHARA_CARDS[c].name for c in p.chara_deck
                            if CHARA_CARDS[c].level == 0})
        # 準備では3枠すべての配置を選ぶ。従来はリーダー以外を名前順で
        # バック1・2へ自動配置していたが、後の切り替えはバック番号を区別する。
        acts = []
        for leader in lv0_names:
            backs = [n for n in lv0_names if n != leader]
            for order in (backs, list(reversed(backs))):
                acts.append({"type": "setup", "leader": leader, "backs": order})
        return acts

    if s.phase == Phase.MULLIGAN and not p.mulligan_done:
        # A-6 (§5-5): 戻す手札は任意の部分集合。初手5枚なら 2^5 = 32通り。
        n = len(p.hand)
        return [{"type": "mulligan",
                 "cards": [i for i in range(n) if mask >> i & 1]}
                for mask in range(1 << n)]

    if s.phase == Phase.ACTION and pi == s.turn_player:
        if not s.used_charge and p.hand:
            acts += [{"type": "charge", "hand": i} for i in range(len(p.hand))]
        if not s.used_switch and not s.leader_switch_forbidden[pi]:
            acts += [{"type": "switch", "back": b} for b in (1, 2)
                     if p.slots[b].stack]
        if not s.used_levelup:
            for si, slot in enumerate(p.slots):
                if not slot.stack:
                    continue
                top = CHARA_CARDS[slot.stack[-1]]
                for cid in p.chara_deck:
                    c = CHARA_CARDS[cid]
                    # v0.12 / BP01（u3・BP01-011 アンコLv2）: 「このカードはカード効果でのみ
                    # レベルアップできる」。行動としてのレベルアップの候補から外す。
                    if _levelup_by_effect_only(c):
                        continue
                    if (c.name == top.name and c.level in (top.level, top.level + 1)
                            and len(p.hand) >= c.level):  # §6.3-3 手札コスト
                        acts.append({"type": "levelup", "slot": si, "card": cid})
        acts.append({"type": "to_clash"})
        acts.append({"type": "end_turn"})
        return acts

    if s.phase == Phase.CLASH_SUBMIT and s.pending_submission[pi] is None:
        usable = [i for i, cid in enumerate(p.hand)
                  if _usable_in_clash(s, pi, ACTION_CARDS[cid])]
        acts = [{"type": "submit", "hand": i} for i in usable]
        # ターンプレイヤーは提出必須 (§6.4(1)-1)。出せるカードがない場合のみパス可。
        if pi != s.turn_player or not usable:
            acts.append({"type": "pass"})
        return acts

    if s.phase == Phase.CHOICE and s.pending_choices \
            and s.pending_choices[0]["player"] == pi:
        ch = s.pending_choices[0]
        kind = ch["kind"]
        if kind == "pay_or_damage":
            # 支払い不能な場合は選択自体を積まない（_apply_op 側で即ダメージ）ため、
            # ここに来た時点で必ず支払える。
            return [{"type": "pay"}, {"type": "decline"}]
        if kind == "switch_back":       # A-5: どちらのバックをリーダーにするか
            return [{"type": "choose_back", "back": b} for b in ch["options"]]
        if kind == "use_optional":      # A-1: 「〜してもよい」を使うか
            return [{"type": "use"}, {"type": "skip"}]
        if kind == "reveal_count":      # A-2: 「N枚まで」の枚数
            return [{"type": "choose_count", "count": n}
                    for n in range(ch["max"] + 1)]
        if kind in ("discard", "discard_for_effect"):   # A-3 / A-4: 捨てるカード
            return [{"type": "discard", "hand": i} for i in range(len(p.hand))]
        if kind == "order":             # A-7: どのスキルから解決するか
            return [{"type": "resolve", "index": o["index"]} for o in ch["options"]]
        if kind in ("pay_cost_card", "zone_card", "levelup_by_effect"):
            return [dict(o) for o in ch["options"]]
        raise ValueError(kind)

    if s.phase == Phase.RUSH and pi == s.clash_winner:
        acts = [{"type": "stop"}]
        if s.rush_allowance > 0 and not s.rush_forbidden[pi]:
            for i, cid in enumerate(p.hand):
                c = ACTION_CARDS[cid]
                if c.color == Color.RED and _usable_in_clash(s, pi, c):
                    acts.append({"type": "rush", "hand": i})
        return acts

    if s.phase == Phase.TURN_END_DISCARD and pi == s.turn_player:
        return [{"type": "discard", "hand": i} for i in range(len(p.hand))]

    return acts


# ---------------------------------------------------------------------------
# 効果解決
# ---------------------------------------------------------------------------

def _draw(s: GameState, pi: int, count: int) -> None:
    p = s.players[pi]
    for _ in range(count):
        if not p.action_deck:
            if not p.trash:
                return  # 引けない（裁定未確認だが実害なし）
            p.action_deck = list(p.trash)
            p.trash = []
            s.next_rng().shuffle(p.action_deck)  # §6.2 デッキ再構成
        p.hand.append(p.action_deck.pop(0))


def _damage(s: GameState, pi: int, amount: int, *,
            dealer: Optional[int] = None, source: Optional[tuple] = None) -> None:
    """pi のライフに直接ダメージ (§1)。0以下で即決着。

    v0.12 / BP01（D-079 追記 3）で 3 つ足した。**いずれも既定値では従来と同じ**である。

    - `damage_taken_mod[pi]`: 「自分が受けるダメージ +N / −N」(u13)。対抗・連撃・効果の
      すべてに乗り、0 未満にはならない。既定 0。
    - `first_damage_taken_this_turn[pi]`: 「各ターン、自分が最初に受けるダメージ」(u7) の記録。
    - `dealer` と `source`: 【相手にダメージを与えた時】(u18) を誘発させる。
      **`source` はそのダメージを与えた**カード**（`("action"|"chara", card_id)`）**で、
      誘発するのはそのカード自身のスキルだけである（u18 のマスター裁定 2026-09-10）。
      誘発は解決中の効果を壊さないよう**割り込み**で積む。
    """
    if amount <= 0:
        return
    amount += s.damage_taken_mod[pi] + _static_damage_taken_mod(s, pi)
    if not s.first_damage_taken_this_turn[pi]:
        amount += _first_damage_taken_mod(s, pi)
        s.first_damage_taken_this_turn[pi] = True
    if amount <= 0:
        return
    p = s.players[pi]
    p.life -= amount
    s.damaged_this_turn[pi] = True
    if p.life <= 0 and s.outcome is None:
        p.life = 0
        s.outcome = 1 - pi
        s.phase = Phase.GAME_OVER
        return
    if dealer is not None and source is not None:
        _queue_fire_on_card(s, Timing.ON_DAMAGE_DEALT, dealer, source[0], source[1])


def _heal(s: GameState, pi: int, amount: int) -> None:
    """pi のライフを回復する (D-011: 上限 MAX_LIFE)。

    実際に 1 以上回復したときだけ `heals_this_turn` を進め、
    【自分のライフが回復した時】(BP01-006) を誘発させる。
    0 回復（上限に張り付いている等）では誘発しない。
    """
    p = s.players[pi]
    before = p.life
    p.life = min(MAX_LIFE, p.life + amount)
    if p.life > before:
        s.heals_this_turn[pi] += 1
        _queue_fire_nested(s, Timing.ON_HEAL, [pi])


def _run_effects(s: GameState, owner: int, effects, ctx: Optional[dict] = None) -> None:
    """選択を伴わない効果列をその場で解決する簡易版（内部・テスト用）。

    プレイヤーの選択を要求しうるオペコードを含む効果は、`_step_effect` 経由で
    1オペコードずつ解決すること（D-022）。この関数はそれらのオペコードに
    到達した場合、選択を積まずに既定の挙動で処理する。
    """
    ctx = {} if ctx is None else ctx
    for op, prm in effects:
        if s.outcome is not None:
            return
        _apply_op(s, owner, op, dict(prm), ctx)


def _apply_op(s: GameState, owner: int, op: str, prm: dict, ctx: dict) -> None:
    """オペコード1個を適用する。選択の要否は呼び出し側 (_step_effect) が判断する。"""
    if True:
        p = s.players[owner]
        if op == "draw" or op == "reveal_top_to_hand":
            _draw(s, owner, prm["count"])
        elif op == "top_to_concerto":
            for _ in range(prm["count"]):
                if p.action_deck:
                    p.concerto.append(p.action_deck.pop(0))
        elif op == "damage_opponent":
            # v0.12: 効果によるダメージも「相手にダメージを与えた時」を誘発させる
            # （＜音骸＞の【優勢】5 枚と BP01-060）。既定では誰も拾わない。
            src = None
            if s.pending_effect is not None and s.pending_effect.get("card"):
                src = (s.pending_effect.get("card_kind", "action"),
                       s.pending_effect["card"])
            _damage(s, 1 - owner, prm["amount"], dealer=owner, source=src)
        elif op == "pursuit":  # 追撃N (§7)
            # D-012: 追撃は複数回発動した場合に加算される（上書きではない）。
            # マスター裁定 2026-08-21。旧実装は max() による上書きだった。
            s.rush_allowance += prm["count"]
        elif op == "forbid_leader_switch_this_turn":
            s.leader_switch_forbidden[owner] = True
        elif op == "switch_leader":
            # A-5 (D-022): どちらのバックをリーダーにするかはプレイヤーが選ぶ。
            # 選択は _step_effect が prm["back"] に書き込む。
            # back が未指定でここに来た場合（_run_effects 経由）は最初の非空バック。
            if not s.leader_switch_forbidden[owner]:
                backs = [b for b in (1, 2) if p.slots[b].stack]
                b = prm.get("back")
                if b is None:
                    b = backs[0] if backs else None
                if b is not None and p.slots[b].stack:
                    # D-024: 「◯◯が切り替えされた場合」は、そのキャラが入れ替えに
                    # 関与したことを指す。リーダー→バック / バック→リーダーの
                    # **どちらの向きでも該当する**（マスター裁定 2026-08-22）。
                    # そのため入れ替わった2名の名前を両方記録する。
                    moved = [_leader_name(s, owner),
                             CHARA_CARDS[p.slots[b].stack[-1]].name]
                    p.slots[0], p.slots[b] = p.slots[b], p.slots[0]
                    et = s.slot_entered_turn[owner]
                    et[0], et[b] = et[b], et[0]
                    names = ctx.setdefault("switched", [])
                    for nm in moved:
                        if nm is not None and nm not in names:
                            names.append(nm)
                    # v0.12: 【切り替え】は**実際に行われたときだけ**誘発する (§7)。
                    _queue_fire_nested(s, Timing.SWITCHED, [owner])
        elif op == "self_damage_buff_if_switched":
            if prm["name"] in ctx.get("switched", ()):
                ctx["bonus_damage"] = ctx.get("bonus_damage", 0) + prm["amount"]
        elif op == "top_to_concerto_if_switched":
            if prm["name"] in ctx.get("switched", ()):
                for _ in range(prm["count"]):
                    if p.action_deck:
                        p.concerto.append(p.action_deck.pop(0))
        elif op == "rush_damage_buff":
            pass  # 常在型。ダメージ計算側 (_card_damage_bonus) で参照
        elif op == "dedicated_leader_card_damage_buff":
            pass  # 常在型。ダメージ計算側 (_card_damage_bonus) で参照
        elif op == "heal_self":  # D-011: ライフ上限20を超えない
            _heal(s, owner, prm["amount"])
        elif op == "raise_opponent_red_cost_next_turn":
            s.pending_red_cost_up[1 - owner] = True
        elif op == "return_clash_card_to_hand":
            # 対抗で使用した自分のカードをアクションエリアから手札へ戻す。
            # s.clash_cards[owner] は意図的に据え置く: 【判定】誘発は
            # ターンプレイヤー→非ターンプレイヤーの順に走るため、ここで None にすると
            # 後続プレイヤーの opp_color 条件が誤って不成立になる。
            # 支払い済みコストは戻さない（カードテキストに戻す旨の記載がないため）。
            cid_self = s.clash_cards[owner]
            if cid_self is not None and cid_self in p.action_area:
                p.action_area.remove(cid_self)
                p.hand.append(cid_self)
        elif op == "opponent_pay_or_damage":
            # D-015: 相手に「コストNを支払う / 支払わずダメージMを受ける」を選ばせる。
            # 支払い不能（協奏エリアが足りない）なら選択させず即ダメージ（マスター確認済み）。
            target = 1 - owner
            if len(s.players[target].concerto) < prm["cost"]:
                _damage(s, target, prm["amount"])
            else:
                s.pending_choices.append({
                    "player": target, "kind": "pay_or_damage",
                    "cost": prm["cost"], "amount": prm["amount"],
                })
        elif op == "discard_self":
            # A-4 (D-022): 捨てるカードはプレイヤーが選ぶ。選択は _step_effect が処理する。
            # ここに来るのは _run_effects 経由（選択なし）の場合のみで、左端から捨てる。
            for _ in range(prm["count"]):
                if p.hand:
                    p.trash.append(p.hand.pop(0))
                    ctx["discarded"] = True
        elif op == "draw_if_switched":
            if prm["name"] in ctx.get("switched", ()):
                _draw(s, owner, prm["count"])
        elif op == "self_damage_buff":  # 連撃ダメージへの汎用加算（switch_leader非依存）
            ctx["bonus_damage"] = ctx.get("bonus_damage", 0) + prm["amount"]
        elif op == "forbid_rush_next_turn":
            s.pending_rush_forbidden[1 - owner] = True
        # --- v0.12 / BP01（D-079 追記 3・便 K 段 K-2）--------------------
        elif op == "draw_to":
            # 「N 枚になるまでカードを引く」。既に N 枚以上なら何もしない。
            need = prm["count"] - len(p.hand)
            if need > 0:
                _draw(s, owner, need)
        elif op == "heal_if_switched":
            # 既存の `*_if_switched` 系と同じ型。切り替えが成立したときだけ効く。
            if prm["name"] in ctx.get("switched", ()):
                _heal(s, owner, prm["amount"])
        elif op == "self_damage_buff_if_discarded":
            # 「手札1枚を捨ててもよい。そうした場合、このカードのダメージ+N」
            if ctx.get("discarded"):
                ctx["bonus_damage"] = ctx.get("bonus_damage", 0) + prm["amount"]
        elif op == "self_damage_buff_per_action_area":
            # 「自分のアクションエリアのカード1枚につき、このカードのダメージ+N」
            ctx["bonus_damage"] = (ctx.get("bonus_damage", 0)
                                   + prm["amount"] * len(p.action_area))
        elif op == "first_use_damage_buff":
            pass  # 常在型。ダメージ計算側 (_card_damage_bonus) で参照
        elif op == "forbid_rush_self_now":
            # 「このターン中、自分は連撃できない」(u12)。予約を経ず即時に立てる。
            s.rush_forbidden[owner] = True
            s.rush_allowance = 0 if s.turn_player == owner else s.rush_allowance
        elif op == "forbid_rush_opponent_now":
            # 「このターン中、相手は連撃できない」(u12)。K-3 の BP01-058 が使う。
            s.rush_forbidden[1 - owner] = True
            if s.turn_player != owner:
                s.rush_allowance = 0
        elif op == "pay_cost_return_self_to_hand":
            # 「コスト N を支払ってこのカードを手札に加えてもよい」(u11)。
            # 「このカード」はアクションエリアにある**そのスキルが載っているカード自身**で、
            # 番号は `pending_effect["card"]` から取る（パラメータに書くとカード名が
            # 機構の仕様に漏れる・D-050 条件 1）。支払いは協奏エリアからトラッシュ (§6.4(1))。
            cid = ctx.get("self_card")
            if cid is None and s.pending_effect is not None:
                cid = s.pending_effect.get("card")
            if cid is not None and cid in p.action_area and len(p.concerto) >= prm["cost"]:
                # 通常入口では `_step_effect` が支払い選択を先に済ませ、paid を立てる。
                # `_run_effects` などの内部入口では従来どおり左端を既定回答にする。
                if not prm.get("paid"):
                    _pay_cost(s, owner, prm["cost"])
                p.action_area.remove(cid)
                p.hand.append(cid)
        # --- v0.12 / BP01（D-079 追記 5・便 K 段 K-3）＜音骸＞の【優勢】の妨害 5 種 ---
        #
        # **選ぶ側は効果のオーナー**（u8）だが、K-3 では選択肢化せず**自動選択**にしてある
        # （作業規約 7・D-004 の暫定の自動選択と同じ扱い）。理由: 新しい選択の種類を足すと
        # `encode.CHOICE_KINDS` が伸びて `N_SCALAR` が変わり、`ENCODING_VERSION` の上げ直しと
        # ネットの移行がもう一度必要になる。K-0 の裁定 1（登録も版上げも 1 回）と噛み合わない。
        # **戦略的に意味を持つと分かった時点で選択肢化を提案する**（作業規約 7 の文言どおり）。
        # 自動選択の規則は「左端から」で、既存の自動選択（手札の左端を捨てる等）と揃えてある。
        elif op == "opp_discard_random":
            # 「相手にダメージを与えた時、相手の手札 N 枚につき、ランダムに手札 1 枚を捨てさせる」
            # 端数は切り捨て（u9）。枚数は**捨て始める前の手札**で数える。
            opp = s.players[1 - owner]
            n = len(opp.hand) // prm["per"]
            for _ in range(n):
                if not opp.hand:
                    break
                idx = s.next_rng().randrange(len(opp.hand))
                opp.trash.append(opp.hand.pop(idx))
        elif op == "opp_concerto_to_trash":
            opp = s.players[1 - owner]
            for _ in range(prm["count"]):
                if not opp.concerto:
                    break
                opp.trash.append(opp.concerto.pop(0))      # 自動選択（左端）
        elif op == "opp_hand_random_to_deck_bottom":
            opp = s.players[1 - owner]
            for _ in range(prm["count"]):
                if not opp.hand:
                    break
                idx = s.next_rng().randrange(len(opp.hand))
                opp.action_deck.append(opp.hand.pop(idx))
        elif op == "mill_opponent_deck_top":
            opp = s.players[1 - owner]
            for _ in range(prm["count"]):
                if not opp.action_deck:
                    break                                  # 山が尽きたら再構成しない
                opp.trash.append(opp.action_deck.pop(0))
        elif op == "opp_trash_to_deck_bottom":
            # 「相手のトラッシュから N 枚までを相手のデッキの下に置く」。
            # 「まで」は自動選択で**最大枚数**を取る（既存の `up_to` の自動選択と同じ・D-022）。
            opp = s.players[1 - owner]
            for _ in range(prm["count"]):
                if not opp.trash:
                    break
                opp.action_deck.append(opp.trash.pop(0))   # 自動選択（左端）
        elif op == "concerto_set_first_use_buff":
            pass  # 常在型。ダメージ計算側 (_card_damage_bonus) で参照
        # --- v0.12 / BP01（D-079 追記 6・便 K 段 K-4）残りのキャラ固有 ---
        #
        # **回収先・置く札の選択は自動選択（トラッシュの左端＝古い順）**にしてある。
        # 理由は K-3 の妨害効果と同じで、新しい選択の種類を足すと `encode.CHOICE_KINDS` が伸びて
        # `N_SCALAR` が変わり、符号化の版上げとネットの移行がもう一度要るためである。
        # **ここは K-3 の妨害効果より戦略的な意味が大きい**（どの札を回収するかは明らかに手の強さに効く）。
        # 便 K の外で、**新しい選択をまとめて 1 回の版上げ**にする形で選択肢化を提案する（作業規約 7）。
        # 規則を「左端」にしたのは、既存の自動選択と揃えるためと、
        # 「いちばん強い札を拾う」のような**隠れた方策を入れない**ためである。
        elif op == "trash_to_hand":
            n = prm.get("count", 1)
            for _ in range(n):
                idx = next((i for i, cid in enumerate(p.trash)
                            if _trash_matches(ACTION_CARDS[cid], prm)), None)
                if idx is None:
                    break
                p.hand.append(p.trash.pop(idx))
        elif op == "trash_to_concerto":
            n = prm.get("count", 1)
            for _ in range(n):
                idx = next((i for i, cid in enumerate(p.trash)
                            if _trash_matches(ACTION_CARDS[cid], prm)), None)
                if idx is None:
                    break
                p.concerto.append(p.trash.pop(idx))
        elif op == "return_to_chara_deck":
            # 「このカードをキャラデッキに戻す」(u4)。下のカードが最上段に戻る＝レベルが下がる。
            # 戻したカードは再びレベルアップに使える（キャラデッキに帰るので）。
            # **どの枠に居るかは分からない**ので、そのカードを持つ枠を探す。
            cid = ctx.get("self_card") or (
                s.pending_effect.get("card") if s.pending_effect is not None else None)
            if cid is not None:
                for slot in p.slots:
                    if slot.stack and slot.stack[-1] == cid:
                        slot.stack.pop()
                        p.chara_deck.append(cid)
                        break
        elif op == "levelup_by_effect":
            # 「自分の「◯◯」をレベルアップする」(u3)。**コストを払わず・1ターン1回も消費しない**。
            # 次のレベルのカードをキャラデッキから探して積む。複数あれば左端（決定的）。
            name = prm["name"]
            # `level` を渡すと「そのレベルのカード」を探す（BP01-062・u21）。
            # 省略時は従来どおり「次のレベル」。**同レベルでも上に置ける**（§6.3-3）ので、
            # すでにレベル 2 の「アンコ」にレベル 2 を重ねる形も成立する。
            want_level = prm.get("level")
            for si, slot in enumerate(p.slots):
                if not slot.stack:
                    continue
                top = CHARA_CARDS[slot.stack[-1]]
                if top.name != name:
                    continue
                lv = top.level + 1 if want_level is None else want_level
                nxt = next((c for c in p.chara_deck
                            if CHARA_CARDS[c].name == name
                            and CHARA_CARDS[c].level == lv), None)
                if nxt is None:
                    break
                p.chara_deck.remove(nxt)
                slot.stack.append(nxt)
                s.slot_entered_turn[owner][si] = s.turn_no
                _queue_fire_nested(s, Timing.ENTER, [owner])
                _queue_fire_nested(s, Timing.LEVELUP, [owner])
                break
        elif op == "levelup_by_effect_if_switched":
            # 「◯◯が切り替えされた場合、自分の「◯◯」をレベルアップする」(u3)
            if prm["name"] in ctx.get("switched", ()):
                _apply_op(s, owner, "levelup_by_effect", {"name": prm["name"]}, ctx)
        elif op == "trash_to_hand_if_switched":
            # 「◯◯が切り替えされた場合、トラッシュから〈条件〉1枚を手札に加える」
            if prm["name"] in ctx.get("switched", ()):
                sub = {k: v for k, v in prm.items() if k != "name"}
                _apply_op(s, owner, "trash_to_hand", sub, ctx)
        elif op == "levelup_by_effect_only":
            pass  # 標識。`legal_actions` が `_levelup_by_effect_only` で読む
        elif op == "cost_mod":
            pass  # 常在型。`_effective_cost` が読む（BP01-062・u20）
        elif op == "grant_rush_draw_to_variation_skills":
            # BP01-057「このターン中、自分が次に使用する2枚の＜変奏スキル＞は
            # 『【連撃】カード1枚を引く。』を得る」(u19)。
            # 数えるのは**連撃で使った札だけ**。同じターンに複数回誘発したら
            # 加算する（「追撃N」の累積規則 §6.4(2)-5・D-012 と同じ扱い）。
            s.variation_rush_draw[owner] += prm["count"]
        elif op == "damage_taken_mod":
            pass  # 常在型。`_static_damage_taken_mod` が読む
        elif op == "grant_deferred_damage_on_loss":
            pass  # 常在型。判定ステップ (`_judge_step`) が読む
        elif op == "switch_leader_to":
            # 「自分のリーダーを「◯◯」に切り替える」(u14)。
            # その名前がバックに居なければ**何も起きない**（§7 の延長）。
            if not s.leader_switch_forbidden[owner]:
                name = prm["name"]
                for b in (1, 2):
                    st = p.slots[b].stack
                    if st and CHARA_CARDS[st[-1]].name == name:
                        moved = [_leader_name(s, owner), name]
                        p.slots[0], p.slots[b] = p.slots[b], p.slots[0]
                        et = s.slot_entered_turn[owner]
                        et[0], et[b] = et[b], et[0]
                        names = ctx.setdefault("switched", [])
                        for nm in moved:
                            if nm is not None and nm not in names:
                                names.append(nm)
                        _queue_fire_nested(s, Timing.SWITCHED, [owner])
                        break
        elif op == "search_deck":
            # 「自分のデッキから「◯◯」1枚を手札に加える。その後、デッキをシャッフルする。」
            # **該当が無くてもシャッフルする**（u15）＝乱数をちょうど 1 回消費する。
            idx = next((i for i, cid in enumerate(p.action_deck)
                        if ACTION_CARDS[cid].name == prm["card_name"]), None)
            if idx is not None:
                p.hand.append(p.action_deck.pop(idx))
            s.next_rng().shuffle(p.action_deck)
        elif op == "reveal_n_take_matching":
            # 「デッキの上から N 枚を公開してもよい。その中から全ての【◯◯】のカードを
            #   手札に加え、残りをトラッシュに置く。」
            revealed = [p.action_deck.pop(0) for _ in range(min(prm["count"], len(p.action_deck)))]
            for cid in revealed:
                if _trash_matches(ACTION_CARDS[cid], prm):
                    p.hand.append(cid)
                else:
                    p.trash.append(cid)
        elif op == "speed_override":
            # 「このカードのスピードは N になる」(u10)。判定の比較にだけ効く上書き。
            s.speed_override[owner] = prm["speed"]
        elif op == "peek_opponent_hand":
            # C-1 (D-023): 覗いた時点の相手の手札をスナップショットとして記録する。
            # observe() では現在の相手の手札との積集合を返すため、
            # 既に使用・破棄されたカードは自動的に落ちる（D-010の暫定no-opを解消）。
            s.peeked_opp_hand[owner] = list(s.players[1 - owner].hand)
        else:
            raise ValueError(f"unknown effect op: {op}")


def _skill_condition_met(s: GameState, owner: int, sk: Skill, ctx: dict) -> bool:
    if sk.condition is None:
        return True
    c = sk.condition
    if "self_result" in c:
        want_win = c["self_result"] == "win"
        if (s.clash_winner == owner) != want_win or s.clash_winner is None:
            return False
    if "self_color" in c:
        cid = s.clash_cards[owner]
        if cid is None or ACTION_CARDS[cid].color != c["self_color"]:
            return False
    if "opp_color" in c:
        cid = s.clash_cards[1 - owner]
        if cid is None or ACTION_CARDS[cid].color != c["opp_color"]:
            return False
    if "self_action_area_count_gte" in c:
        if len(s.players[owner].action_area) < c["self_action_area_count_gte"]:
            return False
    if "is_turn_player" in c:
        # D-014: 「自分のターン開始時」等、自分がターンプレイヤーのときだけ誘発する条件。
        # 条件を書かない TURN_START / TURN_END は従来どおり両プレイヤーで誘発する
        # （＝カードテキストの「各ターン〜」に相当）。
        if (s.turn_player == owner) != c["is_turn_player"]:
            return False
    # --- v0.12 / BP01（D-079 追記 3・便 K 段 K-2）------------------------
    # 以下は BP01 のカードだけが使う。既存カードは 1 つも書いていないので、
    # 足しただけでは SD001/SD02 の対局は変わらない（T-K-1）。
    if "hand_size_lte" in c:
        if len(s.players[owner].hand) > c["hand_size_lte"]:
            return False
    if "action_area_tag_count_gte" in c:
        # 「自分のアクションエリアに〈タグ〉が N 枚以上ある場合」
        tag, need = c["action_area_tag_count_gte"]
        n = sum(1 for cid in s.players[owner].action_area
                if tag in ACTION_CARDS[cid].tags)
        if n < need:
            return False
    if "life_greater_than_opponent" in c:
        if (s.players[owner].life > s.players[1 - owner].life) != c["life_greater_than_opponent"]:
            return False
    if "leader_name_is" in c:
        if _leader_name(s, owner) != c["leader_name_is"]:
            return False
    if "last_used_card_has_tag" in c:
        cid = s.last_used_card[owner]
        if cid is None or c["last_used_card_has_tag"] not in ACTION_CARDS[cid].tags:
            return False
    if "concerto_has_chara_card" in c:
        # 「自分の協奏エリアに【◯◯】のカードがある場合」＝専用キャラ名が一致する札
        name = c["concerto_has_chara_card"]
        if not any(ACTION_CARDS[cid].dedicated_to == name
                   for cid in s.players[owner].concerto):
            return False
    if "heals_this_turn_lt" in c:
        if s.heals_this_turn[owner] >= c["heals_this_turn_lt"]:
            return False
    if "opp_damaged_this_turn" in c:
        if s.damaged_this_turn[1 - owner] != c["opp_damaged_this_turn"]:
            return False
    if "entered_turn_is_not_current" in c:
        # 「このカードがこのターン以外に登場した場合」(BP01-011)。
        # 「このカード」の枠は、そのスキルが載っているカードが最上段に居る枠である。
        cid = s.pending_effect.get("card") if s.pending_effect is not None else None
        si = None
        if cid is not None:
            si = next((i for i, sl in enumerate(s.players[owner].slots)
                       if sl.stack and sl.stack[-1] == cid), None)
        if si is None:
            return False
        entered_this_turn = s.slot_entered_turn[owner][si] == s.turn_no
        if entered_this_turn == c["entered_turn_is_not_current"]:
            return False
    if "dominant" in c:
        # 【優勢】(u2)。実装は K-3。ここでは条件の口だけ開けておき、
        # 満たさない側に倒す（K-3 までこの条件を書いたカードは登録簿に無い）。
        if _is_dominant(s, owner) != c["dominant"]:
            return False
    return True


def _is_dominant(s: GameState, pi: int) -> bool:
    """【優勢】(rules_draft §7・u2): 直前の 1 ターンに自分が対抗に勝ったか、
    相手が対抗ステップをスキップ（パス）していたか。

    「前のターン」は**直前の 1 ターン**であり、誰のターンかを問わない（u2）。
    ゲームの最初のターンには前のターンが無いので成立しない。
    """
    if s.turn_no <= 1:
        return False
    return s.last_turn_clash_winner == pi or bool(s.last_turn_clash_pass[1 - pi])


# (card_id, timing) → 該当スキルの索引。カード定義は不変なので遅延キャッシュする（B-2）。
_CHARA_TIMING_IDX: dict = {}
_ACTION_TIMING_IDX: dict = {}


def _chara_timing_index(cid: str, timing: Timing) -> list:
    """[(skill_index, leader_only), ...]"""
    key = (cid, timing)
    v = _CHARA_TIMING_IDX.get(key)
    if v is None:
        v = [(k, sk.leader_only)
             for k, sk in enumerate(CHARA_CARDS[cid].skills)
             if sk.timing == timing]
        _CHARA_TIMING_IDX[key] = v
    return v


def _action_timing_index(cid: str, timing: Timing) -> list:
    """[skill_index, ...]"""
    key = (cid, timing)
    v = _ACTION_TIMING_IDX.get(key)
    if v is None:
        v = [k for k, sk in enumerate(ACTION_CARDS[cid].skills)
             if sk.timing == timing]
        _ACTION_TIMING_IDX[key] = v
    return v


def _active_skill_refs(s: GameState, pi: int, timing: Timing) -> list:
    """誘発対象スキルへの参照を列挙する。

    参照は `[player, "chara"|"action", card_id, skill_index]` の形で、
    JSON 直列化可能かつ盤面が変化しても解決先が変わらない。
    中断・再開のために GameState に保持する必要があるためこの形を採る（D-022）。

    対象: キャラ（重なった全カード §6.3-3、リーダー条件 §2.1）＋ 対抗カード。

    B-2: プロファイルで本関数の呼び出しが多く（計画探索6局で約14万回）、
    毎回スキル列を走査していた。カードのスキル定義は不変なので
    (card_id, timing) → 該当インデックス列 を遅延キャッシュする。
    **カード定義を実行時に書き換えるとキャッシュが古くなる。**
    カードの追加（新しい card_id）は安全で、書き換えは行わない運用である。
    """
    out = []
    p = s.players[pi]
    for si, slot in enumerate(p.slots):
        for cid in slot.stack:
            for k, leader_only in _chara_timing_index(cid, timing):
                if leader_only and si != 0:
                    continue
                out.append([pi, "chara", cid, k])
    if timing in AREA_TIMINGS:
        # 場面として発火するタイミング（【自分の対抗フェイズ開始時】【各対抗フェイズ終了時】）は、
        # 対抗カードだけでなく**アクションエリアに置かれたカード**のスキルも拾う。
        # 例: BP01-069 羽乱舞・回避は、アクションエリアに在る自分自身を手札へ戻す (u11)。
        seen = set()
        for cid in p.action_area:
            if cid in seen:
                continue                      # 同名 2 枚は 1 回だけ（枠は 1 つ）
            seen.add(cid)
            for k in _action_timing_index(cid, timing):
                out.append([pi, "action", cid, k])
        return out
    cid = s.clash_cards[pi]
    if cid is not None:
        for k in _action_timing_index(cid, timing):
            out.append([pi, "action", cid, k])
    return out


def _active_skills(s: GameState, pi: int, timing: Timing) -> list:
    """`_active_skill_refs` の Skill オブジェクト版。常在型 (STATIC) の参照に使う。"""
    return [_deref_skill(r) for r in _active_skill_refs(s, pi, timing)]


def _deref_skill(ref: list) -> Skill:
    _, kind, cid, idx = ref
    card = CHARA_CARDS[cid] if kind == "chara" else ACTION_CARDS[cid]
    return card.skills[idx]


# ---------------------------------------------------------------------------
# 効果解決エンジン（中断・再開可能） D-022
#
# 解決は「スキルの待ち行列 (pending_skills)」→「1スキルのオペコード列
# (pending_effect)」→「オペコード1個」の3層で進む。各層でプレイヤーの選択が
# 必要になった時点で pending_choices に積み、Phase.CHOICE で制御を返す。
# 選択が揃うと中断地点から再開し、待ち行列が空になったら choice_resume の
# 指す続き（判定ステップ・ダメージ計算・ターン進行など）へ移る。
#
# _queue_fire / _do_rush / _begin_turn などは「積むだけ」で、実際に進めるのは
# _pump。トップレベルの apply が最後に必ず _pump を呼ぶ。
# ---------------------------------------------------------------------------

def _queue_fire(s: GameState, timing: Timing, players_order: list,
                resume: dict) -> None:
    """§6.4(1)-4 解決順序: ターンプレイヤー先、次に非ターンプレイヤー。

    誘発対象を待ち行列に積むだけで解決はしない。解決は `_pump` が行う。

    **簡略化 B-4 の所在（SIMPLIFICATIONS.md / D-022 / レビュー §3.7）**:
    誘発するスキルは**この時点で一括して列挙**され、以後は再列挙しない。
    したがって「解決の途中で盤面が変わり、そのせいで新たに誘発条件を
    満たすスキルが現れる／既に積んだスキルが条件を失う」カードが入ると
    挙動がずれる。現行カードプールにはそのようなカードが存在しないため
    先送りしているが、**カードデータを追加する際はここを確認すること**
    （カード入力は別セッションが行うため、コード内に防御を置いている）。
    必要になったら、`_start_next_skill` の直前で条件を再評価する形に変える。
    """
    refs = []
    for pi in players_order:
        refs += _active_skill_refs(s, pi, timing)
    s.pending_skills = refs
    s.pending_effect = None
    s.pending_ctx = {}
    s.pending_shared_ctx = False
    s.choice_resume = resume


def _queue_fire_nested(s: GameState, timing: Timing, players_order: list) -> None:
    """効果の解決の**途中**で誘発したスキルを、割り込みの待ち行列に積む。

    `_queue_fire` は `pending_skills` を**置き換え**、`choice_resume` も書き換えるので、
    解決中に呼ぶと外側の解決が消える（`_queue_fire` の docstring にある簡略化 B-4 の所在）。
    BP01 では【登場】【レベルアップ】【切り替え】【回復時】【ダメージを与えた時】が
    効果の途中で起きるため、ここを分けた（D-079 追記 3）。

    積むだけで解決はしない。`_pump` が「解決中のオペコード列を終えたあと・
    外側の待ち行列より先に」引き取る。したがって意味は
    **「いま解決しているスキルを最後まで終えてから、割り込んだ誘発を解く」**である。

    SD001/SD02 のカードにはこれらのタイミングが 1 つも付かないので、既存の対局では
    この関数は 1 度も呼ばれない（`tests/test_bp01.py` T-K-1 が守る）。
    """
    refs = []
    for pi in players_order:
        refs += _active_skill_refs(s, pi, timing)
    if refs:
        s.pending_triggers += refs


def _queue_fire_on_card(s: GameState, timing: Timing, pi: int, kind: str, cid: str) -> None:
    """**そのカード 1 枚**のスキルだけを割り込みで積む（u18）。

    `_queue_fire_nested` は「その席のカードを全部見る」ので、
    「**このカードが**相手にダメージを与えた時」のような自己参照の誘発には広すぎる。
    与えたカードが分かっている場面（対抗のダメージ・連撃のダメージ・効果のダメージ）では、
    そのカードの索引を直に引く。

    盤面を走査しないので、連撃で使ったカード（対抗カードではない）も普通に拾える。
    K-2 の最初の実装は `ON_DAMAGE_DEALT` を「アクションエリアも見るタイミング」にして
    連撃のカードを拾おうとしたが、それは**探し方の都合でルールの範囲を広げていた**
    （マスター指摘 2026-09-10）。範囲は「そのカード自身が与えたときだけ」が正しい。
    """
    if kind == "chara":
        # 【リーダー】前置は、そのキャラがリーダー枠に居るときだけ有効 (§2.1)。
        in_leader = cid in s.players[pi].slots[0].stack
        refs = [[pi, "chara", cid, k]
                for k, leader_only in _chara_timing_index(cid, timing)
                if not leader_only or in_leader]
    else:
        refs = [[pi, "action", cid, k] for k in _action_timing_index(cid, timing)]
    if refs:
        s.pending_triggers += refs


def _start_next_trigger(s: GameState) -> None:
    """割り込みの待ち行列から 1 つ解決を始める。

    `pending_skills` と違い**順番の選択を挟まない**。同時に複数が誘発するカードが
    現れたらここに A-7（どれから解くかを本人が選ぶ）を足すこと。現行の BP01 では
    1 つの場面で同じ席のスキルが 2 つ以上誘発するカードは無い。
    """
    ref = s.pending_triggers.pop(0)
    if not _skill_condition_met(s, ref[0], _deref_skill(ref), {}):
        return
    sk = _deref_skill(ref)
    if sk.optional:
        s.pending_choices.append({
            "player": ref[0], "kind": "use_optional",
            "card": ref[2], "skill_index": ref[3], "ref": list(ref),
        })
        return
    _start_skill_effect(s, ref[0], sk, ref[2], ref[1])


def _start_next_skill(s: GameState) -> None:
    """待ち行列の先頭のスキルを1つ開始する。

    A-7 (§6.4(1)-4): 同一プレイヤーのスキルが2つ以上同時に誘発している場合、
    どれから解決するかはそのプレイヤーが選ぶ。
    """
    pi = s.pending_skills[0][0]
    n = 0
    while n < len(s.pending_skills) and s.pending_skills[n][0] == pi:
        n += 1
    group, rest = s.pending_skills[:n], s.pending_skills[n:]
    # 条件を満たさないスキルは誘発しない。解決の途中で条件が変わりうるため、
    # スキルを開始するたびに評価し直す。
    group = [r for r in group if _skill_condition_met(s, pi, _deref_skill(r), {})]
    s.pending_skills = group + rest
    if not group:
        return
    if len(group) >= 2:
        s.pending_choices.append({
            "player": pi, "kind": "order",
            "options": [{"index": i, "card": r[2], "skill_index": r[3]}
                        for i, r in enumerate(group)],
        })
        return
    _begin_skill(s, s.pending_skills.pop(0))


def _begin_skill(s: GameState, ref: list) -> None:
    """スキル1個の解決を開始する。optional なら実行するかどうかを本人に選ばせる。"""
    sk = _deref_skill(ref)
    if sk.optional:
        # A-1 (§7「〜してもよい」): 実行するかどうかはプレイヤーが選ぶ。
        s.pending_choices.append({
            "player": ref[0], "kind": "use_optional",
            "card": ref[2], "skill_index": ref[3], "ref": list(ref),
        })
        return
    _start_skill_effect(s, ref[0], sk, ref[2], ref[1])


def _start_skill_effect(s: GameState, pi: int, sk: Skill,
                        card: Optional[str] = None,
                        card_kind: Optional[str] = None) -> None:
    """スキル 1 個のオペコード列を積む。

    v0.12: `card` はそのスキルが載っているカードの番号である。「**このカード**を手札に加える」
    のような自己参照のオペコード（BP01-069・u11）が読む。**パラメータにカード番号を書かない**
    ためにここで持たせている——書いてしまうと「機構の仕様」にカード名が漏れ、
    初見カードに効く表現ではなくなる（D-050 条件 1・`tests/test_card_space.py`）。
    """
    if not s.pending_shared_ctx:
        s.pending_ctx = {}
    s.pending_effect = {"owner": pi, "card": card, "card_kind": card_kind,
                        "ops": [[op, dict(prm)] for op, prm in sk.effect]}


def _distinct_zone_options(cards: list, *, match=None, zone: str,
                           slot: int | None = None) -> list:
    """公開領域のカード選択肢。同じIDの複数コピーは同じ結果なので1つに畳む。"""
    out = []
    seen = set()
    for i, cid in enumerate(cards):
        if cid in seen or (match is not None and not match(cid)):
            continue
        seen.add(cid)
        a = {"type": "choose_card", "zone": zone, "index": i, "card": cid}
        if slot is not None:
            a["slot"] = slot
        out.append(a)
    return out


def _queue_zone_choice(s: GameState, *, player: int, zone_owner: int,
                       zone: str, destination: str, remaining: int,
                       optional: bool = False, match_params: dict | None = None) -> None:
    cards = getattr(s.players[zone_owner], zone)
    prm = match_params or {}
    match = ((lambda cid: _trash_matches(ACTION_CARDS[cid], prm))
             if zone == "trash" and prm else None)
    options = _distinct_zone_options(cards, match=match, zone=zone)
    if not options or remaining <= 0:
        s.pending_effect["ops"].pop(0)
        return
    if optional:
        options.append({"type": "stop"})
    s.pending_choices.append({
        "player": player, "kind": "zone_card", "zone_owner": zone_owner,
        "zone": zone, "destination": destination, "remaining": remaining,
        "optional": optional, "match_params": prm, "options": options,
    })


def _levelup_effect_options(s: GameState, owner: int, prm: dict) -> list:
    """効果レベルアップの合法候補。基本ルールどおり同レベルと次レベルを含む。"""
    p = s.players[owner]
    out = []
    seen = set()
    for si, slot in enumerate(p.slots):
        if not slot.stack:
            continue
        top = CHARA_CARDS[slot.stack[-1]]
        if top.name != prm["name"]:
            continue
        levels = ({prm["level"]} if "level" in prm
                  else {top.level, top.level + 1})
        for i, cid in enumerate(p.chara_deck):
            c = CHARA_CARDS[cid]
            if cid in seen or c.name != top.name or c.level not in levels:
                continue
            seen.add(cid)
            out.append({"type": "choose_card", "zone": "chara_deck",
                        "index": i, "card": cid, "slot": si})
    return out


def _step_effect(s: GameState) -> None:
    """解決中のスキルのオペコードを1個進める。選択が必要なら積んで中断する。"""
    pe = s.pending_effect
    owner = pe["owner"]
    op, prm = pe["ops"][0]
    p = s.players[owner]

    if op == "switch_leader" and "back" not in prm:
        # A-5: どちらのバックをリーダーにするか
        backs = [b for b in (1, 2) if p.slots[b].stack]
        if s.leader_switch_forbidden[owner] or not backs:
            pe["ops"].pop(0)
            return
        if len(backs) == 1:
            prm["back"] = backs[0]
        else:
            s.pending_choices.append({
                "player": owner, "kind": "switch_back", "options": backs,
                "names": [CHARA_CARDS[p.slots[b].stack[-1]].name for b in backs],
            })
            return

    if op == "reveal_top_to_hand" and prm.get("up_to"):
        # A-2: 「N枚まで」の枚数選択
        if "chosen" not in prm:
            s.pending_choices.append({
                "player": owner, "kind": "reveal_count", "max": prm["count"],
            })
            return
        pe["ops"].pop(0)
        _draw(s, owner, prm["chosen"])
        return

    if op == "discard_self":
        # A-4: 捨てるカードの選択。1枚ずつ処理し、count が尽きたら次のオペコードへ。
        if prm["count"] <= 0 or not p.hand:
            pe["ops"].pop(0)
            return
        if len(p.hand) == 1:
            idx = 0
        elif "hand_idx" in prm:
            idx = prm.pop("hand_idx")
        else:
            s.pending_choices.append({
                "player": owner, "kind": "discard_for_effect",
                "remaining": prm["count"],
            })
            return
        p.trash.append(p.hand.pop(idx))
        prm["count"] -= 1
        # v0.12: 「手札1枚を捨ててもよい。**そうした場合**、〜」の連結に使う
        # （BP01-065 / BP01-067 音の形・重撃）。既存カードは誰も読まない。
        s.pending_ctx["discarded"] = True
        return

    # 条件付きの包みを通常の選択対応オペコードへ展開する。ここで展開せず
    # `_apply_op` へ渡すと、内部用の左端フォールバックを通ってしまう。
    if op == "levelup_by_effect_if_switched":
        if prm["name"] in s.pending_ctx.get("switched", ()):
            pe["ops"][0] = ["levelup_by_effect", {"name": prm["name"]}]
        else:
            pe["ops"].pop(0)
        return

    if op == "trash_to_hand_if_switched":
        if prm["name"] in s.pending_ctx.get("switched", ()):
            pe["ops"][0] = ["trash_to_hand",
                             {k: v for k, v in prm.items() if k != "name"}]
        else:
            pe["ops"].pop(0)
        return

    if op == "pay_cost_return_self_to_hand" and not prm.get("paid"):
        cid = pe.get("card")
        cost = prm["cost"]
        if cid is None or cid not in p.action_area or len(p.concerto) < cost:
            pe["ops"].pop(0)
            return
        if _queue_pay_cost(s, owner, cost):
            prm["paid"] = True
            return
        prm["paid"] = True

    if op == "opp_concerto_to_trash":
        _queue_zone_choice(s, player=owner, zone_owner=1 - owner,
                           zone="concerto", destination="trash",
                           remaining=prm["count"])
        return

    if op == "opp_trash_to_deck_bottom":
        _queue_zone_choice(s, player=owner, zone_owner=1 - owner,
                           zone="trash", destination="action_deck",
                           remaining=prm["count"], optional=True)
        return

    if op in ("trash_to_hand", "trash_to_concerto"):
        _queue_zone_choice(s, player=owner, zone_owner=owner, zone="trash",
                           destination="hand" if op == "trash_to_hand" else "concerto",
                           remaining=prm.get("count", 1), match_params=prm)
        return

    if op == "levelup_by_effect":
        options = _levelup_effect_options(s, owner, prm)
        if not options:
            pe["ops"].pop(0)
        else:
            s.pending_choices.append({
                "player": owner, "kind": "levelup_by_effect",
                "options": options,
            })
        return

    pe["ops"].pop(0)
    _apply_op(s, owner, op, prm, s.pending_ctx)


def _pump(s: GameState) -> None:
    """保留中の解決を、選択待ちにぶつかるか全部片付くまで進める。"""
    while True:
        if s.outcome is not None:
            s.pending_skills = []
            s.pending_triggers = []
            s.pending_effect = None
            s.pending_choices = []
            s.choice_resume = None
            s.pending_ctx = {}
            s.pending_shared_ctx = False
            return
        if s.pending_choices:
            if s.phase != Phase.CHOICE:
                s.phase_before_choice = s.phase
                s.phase = Phase.CHOICE
            return
        if s.phase == Phase.CHOICE:
            s.phase = s.phase_before_choice or Phase.ACTION
        if s.pending_effect is not None:
            if not s.pending_effect["ops"]:
                s.pending_effect = None
            else:
                _step_effect(s)
            continue
        # 割り込み（効果の途中で誘発したもの）を、外側の待ち行列より先に片付ける。
        if s.pending_triggers:
            _start_next_trigger(s)
            continue
        if s.pending_skills:
            _start_next_skill(s)
            continue
        if s.choice_resume is not None:
            resume, s.choice_resume = s.choice_resume, None
            s.pending_shared_ctx = False
            _dispatch_resume(s, resume)
            continue
        return


def _dispatch_resume(s: GameState, r: dict) -> None:
    kind = r["kind"]
    if kind == "turn_start":
        _after_turn_start(s)
    elif kind == "judge":
        _judge_step(s)
    elif kind == "after_judge":
        _after_judge(s)
    elif kind == "turn_end":
        _after_turn_end(s)
    elif kind == "rush_damage":
        _after_rush_skills(s, r["pi"], r["cid"])
    elif kind == "action":
        s.phase = Phase.ACTION
    elif kind == "after_clash_costs":
        _after_clash_costs(s)
    elif kind == "start_rush":
        _start_rush(s, r["pi"], r["cid"])
    else:
        raise ValueError(f"unknown resume point: {kind}")


def _card_damage_bonus(s: GameState, pi: int, card: ActionCard, *,
                       in_rush: bool) -> int:
    """常在型のダメージ補正。対抗ステップ・連撃ステップの両方から呼ぶ。

    2種類の常在補正を区別する:
    - rush_damage_buff (SD02-005 今汐Lv2): カードテキストが
      「自分の赤色のカードは『【連撃】このカードのダメージ+1。』を得る」であり
      **連撃限定**。対抗ステップのダメージには乗らない。
      なお「赤色のカード」の限定はここでは見ていないが、連撃で使用できるのは
      赤色のカードのみ (§6.4(3)-1) のため挙動上の差は生じない。
    - dedicated_leader_card_damage_buff (SD01-005 熾霞Lv2): カードテキストに
      【連撃】の限定がなく「カードのダメージ+3」であるため、
      **対抗・連撃の両方**に適用する。対象は「リーダースキルを持つ専用カード」。
    """
    buff = 0
    # v0.12: **そのカード自身**に付いた常在型（BP01-055 真源演算・重撃
    # 「自分のライフが相手より多い場合、このカードのダメージ+1」）。
    # プレイヤーの常在型の走査（下）は「他のカードを強める」ものを集めるので、
    # 自分自身にだけ効くものはここで分けて見る。対抗でも連撃でも同じく効く。
    for sk in card.skills:
        if sk.timing is not Timing.STATIC:
            continue
        for op, prm in sk.effect:
            if op == "own_card_damage_buff" and _skill_condition_met(s, pi, sk, {}):
                buff += prm["amount"]
    # v0.12 / BP01（D-079 追記 5）: ＜音骸＞の強化は**協奏エリアに置かれたカード**に載っている
    # （「自分の協奏エリアに**このカードを含む**、2 種類以上の＜セット名＞がある場合」・u6）。
    # 協奏エリアは `_active_skill_refs` の走査対象ではないので、ここで別に見る。
    # このオペコードを持つカードは BP01 の＜音骸＞5 枚だけなので、既存の対局には影響しない。
    conc = s.players[pi].concerto
    if conc:
        seen_c = set()
        for ccid in conc:
            if ccid in seen_c:
                continue
            seen_c.add(ccid)
            for sk in ACTION_CARDS[ccid].skills:
                if sk.timing is not Timing.STATIC:
                    continue
                for op, prm in sk.effect:
                    if op != "concerto_set_first_use_buff":
                        continue
                    # 「種類」はカード名の異なり数で数える（u6）。このカード自身も含まれる。
                    kinds = {ACTION_CARDS[c].name for c in conc
                             if prm["set_tag"] in ACTION_CARDS[c].tags}
                    if len(kinds) < prm["count"]:
                        continue
                    tag = prm["tag"]
                    # 「各ターンに自分が最初に使用する〈属性〉」(u7)。このカードを数える前の値で見る。
                    if tag in card.tags and s.tag_uses_this_turn[pi].get(tag, 0) == 0:
                        buff += prm["amount"]
    for sk in _active_skills(s, pi, Timing.STATIC):
        for op, prm in sk.effect:
            if op == "rush_damage_buff" and in_rush:
                buff += prm["amount"]
            elif op == "dedicated_leader_card_damage_buff":
                if card.dedicated_to == prm["name"] and card.leader_skill:
                    buff += prm["amount"]
            # --- v0.12 / BP01（D-079 追記 3）---
            elif op == "name_color_damage_buff":
                # 「自分の【◯◯】の〈色〉のカードのダメージ+N」（BP01-001 / BP01-011）
                if (card.dedicated_to == prm["name"]
                        and card.color.value == prm["color"]):
                    buff += prm["amount"]
            elif op == "first_use_damage_buff":
                # 「各ターンに自分が最初に使用する〈タグ〉のダメージ+N」(u7)。
                # 数えるのは `tag_uses_this_turn`。**このカードを数える前に**呼ばれるので、
                # まだ 0 回なら「最初」である。専用キャラの限定があれば併せて見る。
                tag = prm["tag"]
                if tag not in card.tags:
                    continue
                if prm.get("name") and card.dedicated_to != prm["name"]:
                    continue
                if s.tag_uses_this_turn[pi].get(tag, 0) == 0:
                    buff += prm["amount"]
    return buff


def _first_damage_taken_mod(s: GameState, pi: int) -> int:
    """「各ターン、自分が最初に受けるダメージ +N / −N」(u7・BP01-002)。

    常在型を走査して合計する。**該当カードが 1 枚も無ければ 0** なので、
    SD001/SD02 の対局では `_damage` の挙動は従来とまったく同じである。
    """
    mod = 0
    for sk in _active_skills(s, pi, Timing.STATIC):
        for op, prm in sk.effect:
            if op == "first_damage_taken_mod":
                mod += prm["amount"]
    return mod


def _note_clash_uses(s: GameState) -> None:
    """その対抗で両者が使用したカードを記録する (v0.12・u7)。

    パス（`clash_cards` が None）は「使用していない」ので数えない。
    """
    for pi in (0, 1):
        cid = s.clash_cards[pi]
        if cid is not None:
            _note_card_use(s, pi, cid)


def _note_card_use(s: GameState, pi: int, cid: str) -> None:
    """カードを使用した記録（u7 の「最初に使用する〈タグ〉」と「直前に使用したカード」）。

    **ダメージ計算のあとに呼ぶ**こと。「最初に使用する」の判定は、そのカード自身を
    数える前の値で行うためである（`_card_damage_bonus` の `first_use_damage_buff`）。
    対抗と連撃を区別せず通しで数え、相手のターンでも数える（u7）。
    """
    s.last_used_card[pi] = cid
    counts = s.tag_uses_this_turn[pi]
    for t in ACTION_CARDS[cid].tags:
        counts[t] = counts.get(t, 0) + 1


# ---------------------------------------------------------------------------
# フェーズ進行
# ---------------------------------------------------------------------------

def _pay_cost(s: GameState, pi: int, cost: int) -> None:
    """内部・既定回答用の同期支払い。通常対局は `_queue_pay_cost` を通る。"""
    p = s.players[pi]
    for _ in range(cost):
        p.trash.append(p.concerto.pop(0))


def _queue_pay_cost(s: GameState, pi: int, cost: int) -> bool:
    """協奏の支払い選択を積む。選択を積んだ場合だけ True。"""
    if cost <= 0:
        return False
    p = s.players[pi]
    assert len(p.concerto) >= cost
    options = _distinct_zone_options(p.concerto, zone="concerto")
    if len(options) <= 1:
        _pay_cost(s, pi, cost)
        return False
    s.pending_choices.append({
        "player": pi, "kind": "pay_cost_card", "remaining": cost,
        "options": options,
    })
    return True


def _is_deadlocked(s: GameState) -> bool:
    """進行不能状態の判定 (rules_draft.md §9-5 / D-021)。

    双方が 手札・アクションデッキ・トラッシュ・アクションエリア をすべて失った状態。
    この状態では:
    - §6.2 のデッキ再構成はトラッシュを対象とするため、ドローできない。
    - 手札が空のためカードを使用できず、チャージもできない。
    - レベルアップはレベル1以上のカードで手札コストを要求するため実行できない。
    - 協奏エリアのカードはコスト支払い（＝カードの使用）以外で減らせない。
    したがって、どちらのプレイヤーも二度と盤面を変化させられない。
    ターン開始フェイズ（ドロー後）に判定する。
    """
    return all(
        not p.hand and not p.action_deck and not p.trash and not p.action_area
        for p in s.players
    )


def _begin_turn(s: GameState) -> None:
    # v0.12: 【優勢】(u2) が見る「前のターン」を 1 ターンぶん繰り越す。
    # 「前のターン」は**直前の 1 ターン**であり、誰のターンかを問わない。
    # `clash_winner` は毎ターン None に戻すので、対抗が起きなかったターンの後は
    # 正しく「勝っていない」になる（`last_clash_winner` は直近の対抗を跨いで残るので使わない）。
    s.last_turn_clash_winner = s.clash_winner
    s.last_turn_clash_pass = [s.pending_submission[i] == "PASS" for i in (0, 1)]
    # v0.12: ターンごとに数え直すもの（u7 ほか）。BP01 のカードだけが読む。
    s.heals_this_turn = [0, 0]
    s.tag_uses_this_turn = [{}, {}]
    s.last_used_card = [None, None]
    s.damaged_this_turn = [False, False]
    s.first_damage_taken_this_turn = [False, False]
    s.speed_override = [None, None]
    s.turn_no += 1
    # 「次のターン中、〜」系の継続効果 (SD02-016 赤瞳凍土 / SD01-016 旋風) の反映。
    # 予約フラグを発動フラグへ移し、予約を消す。
    #
    # 2026-08-21 修正 (D-016): 旧実装はターンプレイヤーの分だけを更新していたため、
    # 効果が「次のターン」の1ターンではなく、その次のターンまで残っていた。
    # 例: P0のターンNで予約 → ターンN+1(P1)で発動 → ターンN+2(P0)でもP1のフラグが
    # 立ったまま残り、P0のターン中にP1が対抗に勝っても連撃できなかった。
    # 両プレイヤー分を毎ターン更新することで、発動は次の1ターンのみになる。
    for pi in (0, 1):
        s.rush_forbidden[pi] = s.pending_rush_forbidden[pi]
        s.pending_rush_forbidden[pi] = False
        s.red_cost_up[pi] = s.pending_red_cost_up[pi]
        s.pending_red_cost_up[pi] = False
    s.used_charge = s.used_switch = s.used_levelup = False
    s.variation_rush_draw = [0, 0]      # u19: ターン終了で消える
    s.pending_submission = [None, None]
    s.clash_cards = [None, None]
    s.clash_winner = None
    s.rush_allowance = 0
    s.leader_switch_forbidden = [False, False]
    s.pending_choices = []
    s.choice_resume = None
    # §6.1 ターン開始フェイズ（固有処理なし・トリガーのみ）
    _queue_fire(s, Timing.TURN_START, [s.turn_player, 1 - s.turn_player],
                {"kind": "turn_start"})


def _after_turn_start(s: GameState) -> None:
    # §6.2 ドローフェイズ
    n = FIRST_TURN_DRAW if (s.turn_no == 1) else DRAW_PER_TURN
    _draw(s, s.turn_player, n)
    # §9-5 / D-021: 進行不能状態は引き分けとする（マスター裁定 2026-08-21）。
    if _is_deadlocked(s):
        s.outcome = DRAW
        s.phase = Phase.GAME_OVER
        return
    s.phase = Phase.ACTION


def _resolve_clash(s: GameState) -> None:
    """§6.4(1)-3〜(2): 公開・コスト支払い・対抗誘発・判定・ダメージ・連撃回数。"""
    tp, ntp = s.turn_player, 1 - s.turn_player
    # まず双方を公開する。支払う協奏カードは公開情報を見て本人が選ぶ。
    costs = []
    for pi in (tp, ntp):
        sub = s.pending_submission[pi]
        if sub == "PASS":
            s.clash_cards[pi] = None
            s.clash_counts[pi][CLASH_PASS] += 1        # B-3: 履歴の集計
        else:
            p = s.players[pi]
            cid = p.hand.pop(sub)
            p.action_area.append(cid)  # §4-1 左から順
            costs.append((pi, _effective_cost(s, pi, ACTION_CARDS[cid])))
            s.clash_cards[pi] = cid
            # B-3 (D-031): 公開された提出の色を数える。両者に公開される情報
            # （§6.4(1)-3）なので、これを記録しても隠蔽情報は増えない。
            s.clash_counts[pi][CLASH_COLOR_INDEX[ACTION_CARDS[cid].color]] += 1
    queued = False
    for pi, cost in costs:
        queued = _queue_pay_cost(s, pi, cost) or queued
    if queued:
        s.choice_resume = {"kind": "after_clash_costs"}
        return
    _after_clash_costs(s)


def _after_clash_costs(s: GameState) -> None:
    """双方のコスト支払い後に【対抗】の解決へ進む。"""
    tp, ntp = s.turn_player, 1 - s.turn_player
    # 【対抗】誘発 → 解決が終わったら判定ステップへ (D-015 / D-022)
    _queue_fire(s, Timing.CLASH, [tp, ntp], {"kind": "judge"})


def _judge_step(s: GameState) -> None:
    """§6.4(2) 判定ステップ。_resolve_clash から分離（中断・再開のため）。"""
    tp, ntp = s.turn_player, 1 - s.turn_player
    a, b = s.clash_cards[tp], s.clash_cards[ntp]
    winner: Optional[int] = None
    if a is None and b is None:
        winner = None                       # 引き分け (A)
    elif b is None:
        winner = tp                         # 一方のみ提出 (A)
    elif a is None:
        winner = ntp
    else:
        ca, cb = ACTION_CARDS[a], ACTION_CARDS[b]
        if ca.color != cb.color:            # (B) 3すくみ
            winner = tp if ca.color.beats(cb.color) else ntp
        elif ca.color == Color.BLUE:        # (C) 青同士 → 引き分け
            winner = None
        else:                               # (C) 赤/緑同色 → スピード比較
            # v0.12: 「このカードのスピードは N になる」(u10) は**上書き**であり、
            # 判定の比較にだけ効く。既定は None なので従来と同じ値を使う。
            sa = ca.speed if s.speed_override[tp] is None else s.speed_override[tp]
            sb = cb.speed if s.speed_override[ntp] is None else s.speed_override[ntp]
            if sa != sb:
                winner = tp if sa > sb else ntp
            else:
                winner = tp                 # 同値はターンプレイヤー
    s.clash_winner = winner
    s.last_clash_winner = winner
    s.last_clash_cards = list(s.clash_cards)
    if winner is None:
        _note_clash_uses(s)                 # v0.12: 引き分けでも「使用した」ことは変わらない (u7)
        _end_turn_begin(s)                  # 引き分け→判定誘発なし→ターン終了 (§6.4(2)-2,3)
        return
    _collect_granted_deferred_damage(s, winner)
    # 【判定】誘発（勝敗確定時のみ）→ 解決後に _after_judge へ
    _queue_fire(s, Timing.JUDGE, [tp, ntp], {"kind": "after_judge"})


def _collect_granted_deferred_damage(s: GameState, winner: int) -> None:
    """付与スキルによる持ち越しダメージを積む (v0.12・BP01-014 アンコLv1)。

    カードテキスト:
    「自分の【アンコ】の＜重撃＞と＜共鳴回路＞は『【判定】自分がこのカードで
      赤色のカードに敗北した場合、このターンの対抗フェイズの終了時に、
      相手にこのカードのダメージを与える。』を得る。」

    付与（「〜は『…』を得る」）は今汐Lv2 と同じ**常在型**の型で書く。付与先のカードに
    スキルを生やすのではなく、**付与元の常在型を判定ステップが読む**形にした。
    理由: 付与先はカード定義（不変）ではなく盤面で決まるので、`_action_timing_index` の
    キャッシュ（`(card_id, timing)` → 索引）と噛み合わない。

    与えるのは**そのターンの対抗フェイズ終了時**なので、`deferred_clash_damage` に積むだけ。
    実際に与えるのは `_close_clash_phase`。
    """
    loser = 1 - winner
    wcid = s.clash_cards[winner]
    lcid = s.clash_cards[loser]
    if wcid is None or lcid is None:
        return
    if ACTION_CARDS[wcid].color is not Color.RED:   # 「赤色のカードに敗北した場合」
        return
    lcard = ACTION_CARDS[lcid]
    for sk in _active_skills(s, loser, Timing.STATIC):
        for op, prm in sk.effect:
            if op != "grant_deferred_damage_on_loss":
                continue
            if prm.get("chara") and lcard.dedicated_to != prm["chara"]:
                continue
            tags = [t for t in (prm.get("tag"), prm.get("set_tag")) if t]
            if tags and not any(t in lcard.tags for t in tags):
                continue
            # 「相手にこのカードのダメージを与える」＝敗北した自分のカードのダメージ値。
            s.deferred_clash_damage.append([loser, lcard.damage, ["action", lcid]])


def _after_judge(s: GameState) -> None:
    """§6.4(2)-4 以降: 対抗カードのダメージと連撃回数の決定。"""
    winner = s.clash_winner
    # 勝者の対抗カードのダメージ (§6.4(2)-4)
    # 常在型のダメージ補正（熾霞Lv2等）は対抗ステップにも適用される。
    wcard = ACTION_CARDS[s.clash_cards[winner]]
    # v0.12: 「最初に使用する〈タグ〉」(u7) はこのカードを**数える前**の値で判定するので、
    # ダメージを決めてから `_note_clash_uses` を呼ぶ。順番を入れ替えないこと。
    dmg = wcard.damage + _card_damage_bonus(s, winner, wcard, in_rush=False)
    _note_clash_uses(s)
    _damage(s, 1 - winner, dmg, dealer=winner,
            source=("action", s.clash_cards[winner]))
    if s.outcome is not None:
        return
    # 連撃回数 (§6.4(2)-5): デフォルト0 / 赤勝利は無制限 / 追撃Nは【判定】解決で設定済み
    if wcard.color == Color.RED:
        s.rush_allowance = RUSH_UNLIMITED
    if s.rush_allowance > 0:
        s.phase = Phase.RUSH
    else:
        _end_turn_begin(s)


def _do_rush(s: GameState, pi: int, hand_idx: int) -> None:
    """§6.4(3) 連撃1回分。【連撃】スキルを積み、解決後に _after_rush_skills へ。"""
    p = s.players[pi]
    cid = p.hand.pop(hand_idx)
    card = ACTION_CARDS[cid]
    s.rush_allowance -= 1
    p.action_area.append(cid)
    if _queue_pay_cost(s, pi, _effective_cost(s, pi, card)):
        s.choice_resume = {"kind": "start_rush", "pi": pi, "cid": cid}
        return
    _start_rush(s, pi, cid)


def _start_rush(s: GameState, pi: int, cid: str) -> None:
    """連撃の支払い後に、そのカードの【連撃】スキルを開始する。"""
    card = ACTION_CARDS[cid]
    # 連撃で使用したカード自身の【連撃】スキル群。1枚のカード内で ctx を共有する
    # （switch_leader の結果を後続オペコード・後続スキルが参照するため）。
    s.pending_skills = [[pi, "action", cid, k]
                        for k, sk in enumerate(card.skills)
                        if sk.timing == Timing.RUSH]
    s.pending_effect = None
    s.pending_ctx = {}
    s.pending_shared_ctx = True
    s.choice_resume = {"kind": "rush_damage", "pi": pi, "cid": cid}


def _after_rush_skills(s: GameState, pi: int, cid: str) -> None:
    """§6.4(3)-2: 連撃ダメージを与え、連撃を続けられるかを判定する。"""
    card = ACTION_CARDS[cid]
    # BP01-057 で得た『【連撃】カード1枚を引く。』(u19)。カード自身の【連撃】スキルが
    # 全部片付いたあと、連撃ダメージの前に解決する（**後から得たスキルは後ろに並ぶ**）。
    # 数えるのは＜変奏スキル＞を連撃で使ったときだけ。
    if s.variation_rush_draw[pi] > 0 and "変奏スキル" in card.tags:
        s.variation_rush_draw[pi] -= 1
        _draw(s, pi, 1)
        if s.outcome is not None:
            return
    dmg = (card.damage + _card_damage_bonus(s, pi, card, in_rush=True)
           + s.pending_ctx.get("bonus_damage", 0))
    s.pending_ctx = {}
    _note_card_use(s, pi, cid)              # v0.12: ダメージを決めてから数える (u7)
    _damage(s, 1 - pi, dmg, dealer=pi, source=("action", cid))
    if s.outcome is not None:
        return
    s.phase = Phase.RUSH
    if s.rush_allowance <= 0 or not any(
        a["type"] == "rush" for a in legal_actions(s, pi)
    ):
        _end_turn_begin(s)


def _end_turn_begin(s: GameState) -> None:
    """§6.5 ターン終了フェイズ: 誘発→アクションエリア掃除→手札上限。

    v0.12: その前に**対抗フェイズの終了**を挟む（【各対抗フェイズ終了時】・持ち越しダメージ）。
    `_end_turn_begin` は対抗フェイズを抜ける唯一の道（引き分け・連撃なし・連撃終了のすべてが
    ここに集まる）なので、ここに置けば取りこぼしが出ない。
    """
    tp = s.turn_player
    _close_clash_phase(s)
    _queue_fire(s, Timing.TURN_END, [tp, 1 - tp], {"kind": "turn_end"})


def _close_clash_phase(s: GameState) -> None:
    """対抗フェイズの終了 (v0.12・§7)。

    1. 持ち越しダメージ（BP01-014 の付与スキル・K-4）を与える。
    2. 【各対抗フェイズ終了時】を両プレイヤーで誘発させる（「各」なので両方・§7）。
    3. その対抗だけ有効だったスピードの上書きを落とす (u10)。

    BP01 のカードが 1 枚も無ければ 1・2 は空振りし、3 は None を None にするだけなので、
    SD001/SD02 の対局は 1 手も変わらない（T-K-1）。
    """
    tp = s.turn_player
    if s.deferred_clash_damage:
        pending, s.deferred_clash_damage = s.deferred_clash_damage, []
        for dealer, amount, *rest in pending:
            src = tuple(rest[0]) if rest else None
            if s.outcome is not None:
                break
            _damage(s, 1 - dealer, amount, dealer=dealer, source=src)
    _queue_fire_nested(s, Timing.CLASH_PHASE_END, [tp, 1 - tp])
    s.speed_override = [None, None]


def _after_turn_end(s: GameState) -> None:
    tp = s.turn_player
    for pi in (0, 1):
        p = s.players[pi]
        p.trash.extend(p.action_area)
        p.action_area = []
    if len(s.players[tp].hand) > HAND_LIMIT:
        s.phase = Phase.TURN_END_DISCARD
    else:
        _next_turn(s)


def _next_turn(s: GameState) -> None:
    s.turn_player = 1 - s.turn_player
    _begin_turn(s)


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def apply(state: GameState, actions: dict) -> GameState:
    """actions: {player_index: action_dict}。decision_players の全員分が必要。

    行動を適用したあと `_pump` を呼び、保留中の効果解決を
    「次の選択待ち」または「全部片付く」まで進めてから**新しい** state を返す（D-022）。
    公開APIはこちら。入力の state は変更しない（作業規約2）。
    """
    return apply_owned(state.clone(), actions)


def apply_owned(state: GameState, actions: dict) -> GameState:
    """`apply` と同じだが**複製せず、渡された state を直接書き換える**（B-2）。

    **呼び出し側が state を専有している場合にのみ使うこと。**
    他所から参照されている state に使うと、非破壊更新の規約が壊れる。

    用途はロールアウトの連鎖である。`_settle` や `_value_after_turn` は
    `apply(...)` の戻り値（＝生成したばかりで誰も参照していない state）を
    受け取って、それを何十手も進める。その各手で clone するのは無駄で、
    プロファイルでは clone が計画探索の実行時間の約1/4を占めていた。

    非破壊APIの見た目は `apply` 側で維持されるので、外部の利用者から
    見た挙動は変わらない（`bench_agents.py` の fingerprint で担保）。
    """
    need = decision_players(state)
    assert set(actions.keys()) == set(need), f"actions for {need} required"
    _apply_inner(state, actions)
    _pump(state)
    return state


def _apply_inner(s: GameState, actions: dict) -> None:
    # D-050: 同時手番の行動は**席の昇順**で処理する。辞書の挿入順に依存させない
    # （旧実装は `actions.items()` の順でシャッフルの乱数を消費していた。D-040 で発覚）。
    # 既存の呼び出し側は全て昇順で組んでいたので fingerprint は不変。Rust 版と同じ規約。
    if s.phase == Phase.SETUP_CHARA:
        for pi, act in sorted(actions.items()):
            assert act["type"] == "setup"
            p = s.players[pi]
            lv0 = {CHARA_CARDS[c].name: c for c in p.chara_deck
                   if CHARA_CARDS[c].level == 0}
            leader = act["leader"]
            # 旧形式は後方互換のため名前順を既定回答として受け付ける。
            backs = act.get("backs", sorted(n for n in lv0 if n != leader))
            assert sorted(backs) == sorted(n for n in lv0 if n != leader)
            order = [leader] + backs
            for si, name in enumerate(order):
                cid = lv0[name]
                p.slots[si] = CharaSlot(stack=[cid])
                p.chara_deck.remove(cid)
        if not decision_players(s):
            for pi in (0, 1):
                _draw(s, pi, OPENING_HAND)   # §5-5
            s.phase = Phase.MULLIGAN
        return

    if s.phase == Phase.MULLIGAN:
        for pi, act in sorted(actions.items()):
            assert act["type"] == "mulligan"
            p = s.players[pi]
            # A-6: 戻す手札は任意の部分集合 (§5-5)。"cards" は手札のインデックス列。
            # 旧形式 {"count": n}（左端からn枚）も後方互換のため受け付ける。
            idxs = act.get("cards")
            if idxs is None:
                idxs = list(range(act["count"]))
            idxs = sorted(set(idxs))
            back = [p.hand[i] for i in idxs]
            p.hand = [c for i, c in enumerate(p.hand) if i not in set(idxs)]
            p.action_deck.extend(back)       # デッキ底へ (§5-5)
            for _ in range(len(back)):
                if p.action_deck:
                    p.hand.append(p.action_deck.pop(0))
            s.next_rng().shuffle(p.action_deck)
            p.mulligan_done = True
        if not decision_players(s):
            for pi in (0, 1):
                s.players[pi].charas_revealed = True  # §5-6 同時公開
            _begin_turn(s)                   # 先攻の1ターン目
        return

    if s.phase == Phase.ACTION:
        act = actions[s.turn_player]
        p = s.players[s.turn_player]
        t = act["type"]
        if t == "charge":                    # §6.3-1
            assert not s.used_charge
            p.concerto.append(p.hand.pop(act["hand"]))
            s.used_charge = True
        elif t == "switch":                  # §6.3-2
            assert not s.used_switch and not s.leader_switch_forbidden[s.turn_player]
            b = act["back"]
            p.slots[0], p.slots[b] = p.slots[b], p.slots[0]
            s.slot_entered_turn[s.turn_player][0], s.slot_entered_turn[s.turn_player][b] = (
                s.slot_entered_turn[s.turn_player][b], s.slot_entered_turn[s.turn_player][0])
            s.used_switch = True
            # v0.12: 行動としての切り替えでも【切り替え】は誘発する (§7)。
            _queue_fire_nested(s, Timing.SWITCHED, [s.turn_player])
        elif t == "levelup":                 # §6.3-3
            assert not s.used_levelup
            slot = p.slots[act["slot"]]
            cid = act["card"]
            c = CHARA_CARDS[cid]
            top = CHARA_CARDS[slot.stack[-1]]
            assert c.name == top.name and c.level in (top.level, top.level + 1)
            assert len(p.hand) >= c.level
            p.chara_deck.remove(cid)
            slot.stack.append(cid)
            s.slot_entered_turn[s.turn_player][act["slot"]] = s.turn_no
            s.used_levelup = True
            # v0.12: 【登場】と【レベルアップ】。**準備 (§5-4) では誘発しない** (u1)。
            # ここは行動としてのレベルアップなので、両方が誘発する場面である。
            _queue_fire_nested(s, Timing.ENTER, [s.turn_player])
            _queue_fire_nested(s, Timing.LEVELUP, [s.turn_player])
            # A-3: 手札コストとして捨てるカードはプレイヤーが選ぶ (§6.3-3)。
            if c.level > 0:
                for _ in range(c.level):
                    s.pending_choices.append({
                        "player": s.turn_player, "kind": "discard",
                        "reason": "levelup",
                    })
                s.choice_resume = {"kind": "action"}
        elif t == "to_clash":                # §6.3 → §6.4
            s.phase = Phase.CLASH_SUBMIT
            s.pending_submission = [None, None]
            # v0.12: 【自分の対抗フェイズ開始時】。ターンプレイヤーの側だけが誘発する
            # （カード側にも is_turn_player を書くが、ここでも席を絞る）。
            _queue_fire_nested(s, Timing.CLASH_PHASE_START, [s.turn_player])
        elif t == "end_turn":
            _end_turn_begin(s)
        else:
            raise ValueError(t)
        return

    if s.phase == Phase.CLASH_SUBMIT:
        for pi, act in sorted(actions.items()):
            if act["type"] == "pass":
                usable = [i for i, cid in enumerate(s.players[pi].hand)
                          if _usable_in_clash(s, pi, ACTION_CARDS[cid])]
                assert pi != s.turn_player or not usable, \
                    "ターンプレイヤーは可能なら提出必須"
                s.pending_submission[pi] = "PASS"
            else:
                assert act["type"] == "submit"
                cid = s.players[pi].hand[act["hand"]]
                assert _usable_in_clash(s, pi, ACTION_CARDS[cid])
                s.pending_submission[pi] = act["hand"]
        if all(v is not None for v in s.pending_submission):
            _resolve_clash(s)
        return

    if s.phase == Phase.CHOICE:
        _apply_choice(s, actions)
        return

    if s.phase == Phase.RUSH:
        act = actions[s.clash_winner]
        if act["type"] == "stop" or s.rush_allowance <= 0:
            _end_turn_begin(s)
        else:
            assert act["type"] == "rush"
            # 連撃後のダメージと継続判定は _after_rush_skills が行う
            # （【連撃】スキルの解決中に選択が挟まりうるため, D-022）。
            _do_rush(s, s.clash_winner, act["hand"])
        return

    if s.phase == Phase.TURN_END_DISCARD:
        act = actions[s.turn_player]
        assert act["type"] == "discard"
        p = s.players[s.turn_player]
        p.trash.append(p.hand.pop(act["hand"]))
        if len(p.hand) <= HAND_LIMIT:
            _next_turn(s)
        return

    raise ValueError(f"no actions expected in phase {s.phase}")


def _apply_choice(s: GameState, actions: dict) -> None:
    """Phase.CHOICE: 待ち行列の先頭の選択を1件解決する（D-015 / D-022）。"""
    ch = s.pending_choices[0]
    pi = ch["player"]
    act = actions[pi]
    kind = ch["kind"]

    if kind == "pay_or_damage":
        if act["type"] == "pay":
            assert len(s.players[pi].concerto) >= ch["cost"]
            s.pending_choices.pop(0)
            _queue_pay_cost(s, pi, ch["cost"])
        else:
            assert act["type"] == "decline"
            _damage(s, pi, ch["amount"])
            s.pending_choices.pop(0)

    elif kind == "switch_back":                      # A-5
        assert act["type"] == "choose_back" and act["back"] in ch["options"]
        s.pending_choices.pop(0)
        s.pending_effect["ops"][0][1]["back"] = act["back"]

    elif kind == "use_optional":                     # A-1
        assert act["type"] in ("use", "skip")
        s.pending_choices.pop(0)
        if act["type"] == "use":
            _start_skill_effect(s, pi, _deref_skill(ch["ref"]), ch["ref"][2], ch["ref"][1])

    elif kind == "reveal_count":                     # A-2
        assert act["type"] == "choose_count" and 0 <= act["count"] <= ch["max"]
        s.pending_choices.pop(0)
        s.pending_effect["ops"][0][1]["chosen"] = act["count"]

    elif kind == "discard_for_effect":               # A-4
        assert act["type"] == "discard" and 0 <= act["hand"] < len(s.players[pi].hand)
        s.pending_choices.pop(0)
        s.pending_effect["ops"][0][1]["hand_idx"] = act["hand"]

    elif kind == "discard":                          # A-3（レベルアップの手札コスト）
        assert act["type"] == "discard" and 0 <= act["hand"] < len(s.players[pi].hand)
        s.pending_choices.pop(0)
        p = s.players[pi]
        p.trash.append(p.hand.pop(act["hand"]))

    elif kind == "order":                            # A-7
        assert act["type"] == "resolve"
        idx = act["index"]
        assert any(o["index"] == idx for o in ch["options"])
        s.pending_choices.pop(0)
        _begin_skill(s, s.pending_skills.pop(idx))

    elif kind == "pay_cost_card":
        assert act["type"] == "choose_card" and act["zone"] == "concerto"
        p = s.players[pi]
        i = act["index"]
        assert 0 <= i < len(p.concerto) and p.concerto[i] == act["card"]
        p.trash.append(p.concerto.pop(i))
        ch["remaining"] -= 1
        options = _distinct_zone_options(p.concerto, zone="concerto")
        if ch["remaining"] <= 0:
            s.pending_choices.pop(0)
        elif len(options) <= 1:
            _pay_cost(s, pi, ch["remaining"])
            s.pending_choices.pop(0)
        else:
            ch["options"] = options

    elif kind == "zone_card":
        if act["type"] == "stop":
            assert ch["optional"]
            s.pending_choices.pop(0)
            s.pending_effect["ops"].pop(0)
        else:
            assert act["type"] == "choose_card" and act["zone"] == ch["zone"]
            src = getattr(s.players[ch["zone_owner"]], ch["zone"])
            i = act["index"]
            assert 0 <= i < len(src) and src[i] == act["card"]
            cid = src.pop(i)
            getattr(s.players[ch["zone_owner"]], ch["destination"]).append(cid)
            ch["remaining"] -= 1
            prm = ch["match_params"]
            match = ((lambda x: _trash_matches(ACTION_CARDS[x], prm))
                     if ch["zone"] == "trash" and prm else None)
            options = _distinct_zone_options(src, match=match, zone=ch["zone"])
            if ch["optional"]:
                options.append({"type": "stop"})
            if ch["remaining"] <= 0 or not any(a["type"] == "choose_card" for a in options):
                s.pending_choices.pop(0)
                s.pending_effect["ops"].pop(0)
            else:
                ch["options"] = options

    elif kind == "levelup_by_effect":
        assert act["type"] == "choose_card" and act["zone"] == "chara_deck"
        p = s.players[pi]
        cid, si = act["card"], act["slot"]
        assert cid in p.chara_deck
        assert any(a == act for a in ch["options"])
        p.chara_deck.remove(cid)
        p.slots[si].stack.append(cid)
        s.slot_entered_turn[pi][si] = s.turn_no
        s.pending_choices.pop(0)
        s.pending_effect["ops"].pop(0)
        _queue_fire_nested(s, Timing.ENTER, [pi])
        _queue_fire_nested(s, Timing.LEVELUP, [pi])

    else:
        raise ValueError(kind)


def outcome(s: GameState) -> Optional[int]:
    """決着結果。勝者の player index (0/1) / `state.DRAW`(-1) 引き分け / 未決着なら None。

    引き分けは §9-5 の進行不能状態でのみ発生する（D-021）。
    勝率を集計する側は DRAW を勝ちにも負けにも数えないこと。
    """
    return s.outcome


# ---------------------------------------------------------------------------
# 観測（情報集合） §10
# ---------------------------------------------------------------------------

def _known_opponent_hand(s: GameState, pi: int) -> list:
    """pi が「相手の手札を確認する」効果で見たカードのうち、今も相手の手札にあるもの。

    覗いた時点のスナップショットと現在の相手の手札の多重集合の積を返す（D-023）。
    """
    seen = s.peeked_opp_hand[pi]
    if not seen:
        return []
    have = Counter(s.players[1 - pi].hand)
    out = []
    for cid, n in Counter(seen).items():
        out += [cid] * min(n, have.get(cid, 0))
    return sorted(out)


def observe(s: GameState, pi: int) -> dict:
    """pi から見える情報のみを含む辞書。学習用の特徴量抽出はこの上に作る。"""
    me, opp = s.players[pi], s.players[1 - pi]

    def slots_view(p: PlayerState, revealed: bool) -> list:
        if revealed and p.charas_revealed:
            return [list(sl.stack) for sl in p.slots]
        return [["<hidden>"] * len(sl.stack) for sl in p.slots]

    return {
        "phase": s.phase.value,
        "turn_no": s.turn_no,
        "turn_player": s.turn_player,
        "me": {
            "life": me.life,
            "hand": list(me.hand),
            "concerto": list(me.concerto),
            "trash": list(me.trash),
            "action_area": list(me.action_area),
            "chara_deck": list(me.chara_deck),
            "slots": [list(sl.stack) for sl in me.slots],
            "deck_count": len(me.action_deck),
        },
        "opp": {
            "life": opp.life,
            "hand_count": len(opp.hand),
            # C-1 (D-023): 「相手の手札を確認する」効果 (スキャン) で見たカードのうち、
            # 今も相手の手札に残っているものだけを返す。手札から出るルート
            # （チャージ・レベルアップのコスト・対抗・連撃・捨て札）はすべて公開情報なので、
            # 積集合を取っても見ていない情報が漏れることはない。
            "hand_known": _known_opponent_hand(s, pi),
            "concerto": list(opp.concerto),
            "trash": list(opp.trash),
            "action_area": list(opp.action_area),
            "slots": slots_view(opp, True),
            "deck_count": len(opp.action_deck),
        },
        "clash_cards": [
            s.clash_cards[pi],
            s.clash_cards[1 - pi] if s.phase != Phase.CLASH_SUBMIT else None,
        ],
        "rush_allowance": s.rush_allowance if s.clash_winner == pi else 0,
        # --- ターン内フラグ (§6.3 各行動は1ターン1回) --------------------------
        # ターンプレイヤーが今ターンに何を使い終えたか。公開情報であり、
        # アクションフェイズの合法手そのものを決める（D-036）。
        "used": {"charge": s.used_charge, "switch": s.used_switch,
                 "levelup": s.used_levelup},
        # --- 継続効果 (D-036) --------------------------------------------------
        # いずれも表向きに公開されたカードの効果から生じる公開情報である。
        # 視点を pi 基準に揃えて {me, opp} で返す。
        # red_cost_up: 「次のターン中、相手の赤色のカードのコスト+1」(SD01-016 旋風)。
        #   `_effective_cost` がこれを見るので、観測だけからカードの実効コストを
        #   復元するには必須である（欠けていると使用可能な赤の枚数を数え違える）。
        # rush_forbidden: 「次のターン中、連撃できない」(SD02-016 赤瞳凍土)。
        # pending_*: 次の自分のターン開始時に発動する予約ぶん。
        "red_cost_up": {"me": s.red_cost_up[pi], "opp": s.red_cost_up[1 - pi]},
        "pending_red_cost_up": {"me": s.pending_red_cost_up[pi],
                                "opp": s.pending_red_cost_up[1 - pi]},
        "rush_forbidden": {"me": s.rush_forbidden[pi],
                           "opp": s.rush_forbidden[1 - pi]},
        "pending_rush_forbidden": {"me": s.pending_rush_forbidden[pi],
                                   "opp": s.pending_rush_forbidden[1 - pi]},
        "leader_switch_forbidden": {"me": s.leader_switch_forbidden[pi],
                                    "opp": s.leader_switch_forbidden[1 - pi]},
        # --- 対抗の結果 (D-036) ------------------------------------------------
        # 提出は公開されるので (§6.4(1)-3) 勝敗も提出カードも公開情報。
        # 勝者は pi 基準に写して 0=自分 / 1=相手 / None=未決 とする。
        "clash_winner": (None if s.clash_winner is None
                         else int(s.clash_winner != pi)),
        "last_clash_winner": (None if s.last_clash_winner is None
                              else int(s.last_clash_winner != pi)),
        "last_clash_cards": [s.last_clash_cards[pi],
                             s.last_clash_cards[1 - pi]],
        # C-2 の解消 (B-3 / D-031): 対抗で公開された色の経験分布。
        # [赤, 緑, 青, パス] の累積回数。両者の提出は公開される (§6.4(1)-3) ので
        # 相手の分も見てよい。相手の方策を推定する最初の履歴特徴である。
        "clash_counts": {
            "me": list(s.clash_counts[pi]),
            "opp": list(s.clash_counts[1 - pi]),
        },
        # D-015: 自分に提示されている選択（無ければ None）。相手宛の選択は見せない。
        "pending_choice": (
            dict(s.pending_choices[0])
            if s.pending_choices and s.pending_choices[0]["player"] == pi
            else None
        ),
    }
