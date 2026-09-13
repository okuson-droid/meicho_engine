"""ヒューリスティック（規則ベース）エージェント。

rules_draft.md v0.10 準拠。決定ノードの多い順に方策を持つ:
アクション(85回/局) > 対抗提出(33) > 選択(29) > 連撃(15) > 手札上限調整(8)。

## 設計方針

- **強さ優先**（マスター指示 2026-08-22）。規則の分岐と調整パラメータを許容する。
- 調整可能な数値はすべて `Params` に外出しする。自己対戦で調整できるようにするため。
- **相手の手札は見ない**。`GameState` を直接読むが、参照するのは
  `observe()` で公開される情報に限る（`test_heuristic_does_not_peek` で担保）。

## 実験から得た知見のうち、方策に組み込んでいるもの

- 対抗の色は**自分のリーダーの担当色を出し続ける**のが基本
  （既定 own_color_weight=12.0 で自色が約8割）。キャラのLv0【対抗】スキルは
  **勝敗を問わず**担当色を出せば発動するため、負けた対抗でもリソースが残る。
  この「負けても得」の蓄積がターンをまたいで効く。
- **3すくみで相手のリーダーの色を踏むのは逆効果**（既定 counter_weight=0.0）。
  CLASH_CFR_REPORT.md の主結果はこれと反対だが、**実ゲームの勝率検証で逆転した**
  （自色確定 vs カウンター確定 = 0.657）。CFR が解いたのは手札を毎回引き直す
  1手番の部分ゲームであり、「同じ色の札は有限」「担当色の報酬が蓄積する」という
  多ターンの構造が入っていなかったことが原因である。
  経緯は HEURISTIC_NOTES.md と CLASH_CFR_REPORT.md §0 を参照。
- **青と緑はデッキに9枚ずつしかない希少資源**。使うほど手が細る（同 追補1）。
- **赤が撃てない原因の96%はリーダー条件**であり、コストではない（同 追補2）。
  リーダー選択と切り替えが「どの赤が生きるか」を決める。
- 連撃中の変奏スキルは、死んでいる赤を解放する鍵になりうる（効果量は未測定）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import ACTION_CARDS, CHARA_CARDS, Color, Timing
from .engine import _effective_cost, _leader_name, legal_actions
from .state import HAND_LIMIT, Phase

# 3すくみ (§6.4(1)-1-B): 赤>緑>青>赤。BEATEN_BY[X] = X に勝つ色
BEATEN_BY = {Color.RED: Color.BLUE, Color.GREEN: Color.RED, Color.BLUE: Color.GREEN}

def _derive_leader_color() -> dict:
    """キャラのLv0【対抗】スキルが報酬を出す色を `cards.py` から導く。

    D-047 の監査で「高」が付いていたキャラ名 6 件の直書きを、便 K 段 K-1 で
    ここに置き換えた（D-079 追記 2）。直書きのままだと BP01 の新しいキャラが
    増えるたびに人手で足すことになり、足し忘れが H の打ち方を静かに変える。

    導き方は「そのキャラの **Lv.0** のカードが持つ **【対抗】** スキルの発動条件
    `self_color`」である。Lv.0 に【対抗】スキルが無いキャラ（BP01 のツバキ・アンコなど、
    【判定】や常在型で報酬を出すキャラ）は**入らない**。参照側は
    `LEADER_COLOR.get(name)` で受けるので、入っていなくても落ちない
    （担当色による加点が無いだけで、それが実態に合っている）。

    SD001/SD02 の 6 キャラについて、この導出が従来の直書きと一致することは
    `tests/test_bp01.py` が固定する。H の既定の打ち方が不変であることは
    fingerprint `6e39c2aa4b35d876` が守る。
    """
    out = {}
    for card in CHARA_CARDS.values():
        if card.level != 0:
            continue
        for sk in card.skills:
            if sk.timing is not Timing.CLASH:
                continue
            col = (sk.condition or {}).get("self_color")
            if col is not None:
                out[card.name] = col
                break
    return out


# キャラのLv0【対抗】スキルが報酬を出す色（cards.py の登録内容から導出）
LEADER_COLOR = _derive_leader_color()


@dataclass
class Params:
    """調整パラメータ。自己対戦で調整する。"""

    # --- 対抗ステップ ---
    # 自己対戦での調整結果（2026-08-22, 各2000局）:
    #   counter_weight=0 が最も強い。3すくみで相手リーダーの色を踏みに行くのは**逆効果**。
    #   own_color_weight は大きいほど強く、単調に改善する（1.5→0.528, 15→0.591, 1000→0.599）。
    #   ただし完全な確定は読まれうるため、12.0（自色が約8割）で止めている。
    #   詳細と理由は HEURISTIC_NOTES.md を参照。
    counter_weight: float = 0.0     # 相手リーダーの担当色を踏む色への重み
    own_color_weight: float = 12.0  # 自分のリーダーの担当色への重み（勝敗問わず発動）
    base_weight: float = 1.0        # その他の色への重み
    scarce_penalty: float = 0.35    # 青緑が手札に少ないときに比率を下げる強さ

    # --- アクションフェイズ ---
    concerto_target: int = 4        # 協奏エリアの目標枚数（2は明確に弱い。3以上は同等）
    charge_min_hand: int = 2        # これ以下の手札ならチャージしない
    levelup_min_hand: int = 5       # これ以下の手札ならレベルアップしない
    switch_min_gain: int = 2        # 切り替えで生き返る赤がこの枚数以上なら切り替える

    # --- 選択 ---
    pay_min_concerto: int = 3       # 協奏がこれ以上なら「コスト1を支払う」を選ぶ
    keep_deck_min: int = 3          # デッキ残がこれ以下ならドロー系の枚数を絞る

    # --- 規則のオンオフ（寄与を切り分けるため。既定はすべて有効）---
    # A-4 (2026-08-23): 3条件すべてで寄与ゼロだった3規則
    # （リーサル確定・連撃中の変奏コンボ・出せないなら対抗しない）は
    # フラグごと削除した。測定値は HEURISTIC_NOTES.md「A-4 規則の整理」を参照。
    use_color_mix: bool = True      # 対抗の色を相手リーダーに応じて混合する
    use_switch: bool = True         # 死んだ赤を生き返らせる切り替え
    use_charge: bool = True         # 協奏エリアの整備
    use_levelup: bool = True        # レベルアップ
    use_card_utility: bool = True   # 捨て札・チャージ対象を価値で選ぶ


def _c(cid):
    return ACTION_CARDS[cid]


def _leader(s, pi):
    return _leader_name(s, pi)


def _back_names(s, pi):
    p = s.players[pi]
    return {b: CHARA_CARDS[p.slots[b].stack[-1]].name
            for b in (1, 2) if p.slots[b].stack}


def live_reds(s, pi, leader=None):
    """指定のリーダーだったとき、手札の赤のうち使用条件を満たす枚数。

    リーダースキル条件 (§6.4 使用条件II) は leader に依存するため、
    「このキャラをリーダーにしたら何枚の赤が生きるか」を数えられる形にする。
    """
    p = s.players[pi]
    n = 0
    for cid in p.hand:
        c = _c(cid)
        if c.color != Color.RED:
            continue
        if c.leader_skill and c.dedicated_to != (leader or _leader(s, pi)):
            continue
        if _effective_cost(s, pi, c) > len(p.concerto):
            continue
        n += 1
    return n


def card_utility(s, pi, cid, params: Params) -> float:
    """そのカードを手札に持ち続ける価値。低いものから手放す。"""
    c = _c(cid)
    p = s.players[pi]
    v = float(c.damage)
    if c.skills:
        v += 0.5
    # 撃てないカードは価値が低い
    if c.leader_skill and c.dedicated_to != _leader(s, pi):
        v -= 1.0 if c.dedicated_to in _back_names(s, pi).values() else 2.5
    over = _effective_cost(s, pi, c) - len(p.concerto)
    if over > 0:
        v -= 1.2 * over
    # 青緑は希少資源（デッキに9枚ずつ）。同じ点数なら赤より残す
    if c.color != Color.RED:
        v += 0.8
    return v


class HeuristicAgent:
    """規則ベースのエージェント。乱数はシード指定可能（対抗の混合戦略に使う）。"""

    def __init__(self, seed: int, params: Params = None):
        self.rng = random.Random(seed)
        self.p = params or Params()

    # -- 補助 --------------------------------------------------------------
    def _pick(self, weights: dict):
        """重みつき抽選。"""
        tot = sum(weights.values())
        if tot <= 0:
            return self.rng.choice(list(weights))
        r = self.rng.random() * tot
        acc = 0.0
        for k, w in weights.items():
            acc += w
            if r <= acc:
                return k
        return list(weights)[-1]

    # -- 各フェイズ --------------------------------------------------------
    def act(self, s, pi):
        acts = legal_actions(s, pi)
        assert acts, f"no legal actions for P{pi} in {s.phase}"
        if s.phase == Phase.SETUP_CHARA:
            return self._setup(s, pi, acts)
        if s.phase == Phase.MULLIGAN:
            return self._mulligan(s, pi, acts)
        if s.phase == Phase.ACTION:
            return self._action(s, pi, acts)
        if s.phase == Phase.CLASH_SUBMIT:
            return self._clash(s, pi, acts)
        if s.phase == Phase.CHOICE:
            return self._choice(s, pi, acts)
        if s.phase == Phase.RUSH:
            return self._rush(s, pi, acts)
        if s.phase == Phase.TURN_END_DISCARD:
            return self._discard(s, pi, acts)
        return self.rng.choice(acts)

    def _setup(self, s, pi, acts):
        """§5-4 リーダー選択。専用カードが最も多いキャラを立てる。

        リーダーは「どの赤が生きるか」を決めるため、支援カードの多いキャラを選ぶ。
        """
        p = s.players[pi]
        cnt = {}
        for a in acts:
            n = a["leader"]
            cnt[n] = sum(1 for cid in p.action_deck if _c(cid).dedicated_to == n)
        return max(acts, key=lambda a: cnt[a["leader"]])

    def _mulligan(self, s, pi, acts):
        """§5-5 マリガン。協奏エリアが空の序盤に使えない高コスト札を戻す。"""
        p = s.players[pi]
        drop = []
        for i, cid in enumerate(p.hand):
            c = _c(cid)
            if c.cost >= 2:                      # 序盤は協奏がなく撃てない
                drop.append(i)
            elif c.leader_skill and c.dedicated_to != _leader(s, pi):
                drop.append(i)
        drop = sorted(drop)[:3]                  # 戻しすぎない
        for a in acts:
            if a["cards"] == drop:
                return a
        return next(a for a in acts if a["cards"] == [])

    def _action(self, s, pi, acts):
        """§6.3 アクションフェイズ。レベルアップ → 切り替え → チャージ → 対抗の順に検討する。"""
        p = s.players[pi]
        by = lambda t: [a for a in acts if a["type"] == t]

        # 1. レベルアップ: 手札に余裕があるときだけ。リーダーを優先して伸ばす。
        lv = by("levelup") if self.p.use_levelup else []
        if lv and len(p.hand) > self.p.levelup_min_hand:
            best = max(lv, key=lambda a: (a["slot"] == 0,
                                          CHARA_CARDS[a["card"]].level))
            if len(p.hand) >= CHARA_CARDS[best["card"]].level + self.p.charge_min_hand:
                return best

        # 2. 切り替え: 死んでいる赤が生き返るなら替える（追補2の知見）
        sw = by("switch") if self.p.use_switch else []
        if sw:
            now = live_reds(s, pi)
            backs = _back_names(s, pi)
            best, gain = None, 0
            for a in sw:
                nm = backs.get(a["back"])
                if nm is None:
                    continue
                g = live_reds(s, pi, nm) - now
                if g > gain:
                    best, gain = a, g
            if best is not None and gain >= self.p.switch_min_gain:
                return best

        # 3. チャージ: 協奏が目標に届いていないなら、最も要らない札を置く
        ch = by("charge") if self.p.use_charge else []
        if ch and len(p.concerto) < self.p.concerto_target \
                and len(p.hand) > self.p.charge_min_hand:
            return min(ch, key=lambda a: card_utility(s, pi, p.hand[a["hand"]], self.p))

        # 4. 対抗へ進む。
        #    かつて「出せる札がないなら進まない」規則を置いていた（§6.4(2)-1-A の
        #    一方的な被弾を避ける意図）が、A-4 のアブレーションで3条件とも
        #    寄与ゼロだったため削除した。発火条件（手札の**全部**が使用不能）が
        #    稀すぎて効果が出ない規則だった。
        return {"type": "to_clash"}

    def _clash(self, s, pi, acts):
        """§6.4(1) 対抗提出。色を混合戦略で選び、同色内はダメージ重視で選ぶ。"""
        p = s.players[pi]
        sub = [a for a in acts if a["type"] == "submit"]
        if not sub:
            return {"type": "pass"}

        # かつてここに「削り切れる打点があれば確定で出す」規則があったが、
        # A-4 のアブレーションで3条件とも寄与ゼロだったため削除した。
        # 規則として書けない種類の判断だからである: ダメージは**対抗に勝たなければ
        # 入らない** (§6.4(2)-4) ので `damage >= 相手ライフ` は確定ではなく、
        # 「対抗に勝つ見込み」の見積もりが要る。それは決定化して数える側
        # （greedy / planner の evaluate は勝利を WIN=10000 として直接見る）の仕事である。
        opp_leader = _leader(s, 1 - pi)
        my_leader = _leader(s, pi)
        counter = BEATEN_BY.get(LEADER_COLOR.get(opp_leader))
        mine = LEADER_COLOR.get(my_leader)

        # 色ごとの重み
        bycol = {}
        for a in sub:
            bycol.setdefault(_c(p.hand[a["hand"]]).color, []).append(a)
        if not self.p.use_color_mix:
            a = self.rng.choice(sub)
            return a
        weights = {}
        for col, cand in bycol.items():
            w = self.p.base_weight
            if col == counter:
                w += self.p.counter_weight
            if col == mine:
                w += self.p.own_color_weight
            # 青緑は希少（デッキ9枚ずつ）。手札の残りが薄いほど出し渋る
            if col != Color.RED:
                held = sum(1 for cid in p.hand if _c(cid).color == col)
                w *= (1.0 - self.p.scarce_penalty / max(held, 1))
            weights[col] = max(w, 0.01)
        col = self._pick(weights)
        cand = bycol[col]
        return max(cand, key=lambda a: (_c(p.hand[a["hand"]]).damage,
                                        _c(p.hand[a["hand"]]).speed))

    def _rush(self, s, pi, acts):
        """§6.4(3) 連撃。最大打点を撃つ。

        かつて「変奏スキルで死んでいる赤を解放してから殴る」規則を置いていたが、
        A-4 のアブレーションで3条件とも寄与ゼロだったため削除した
        （CFRレポート追補の「変奏コンボは判定不能」という負の結果と整合する）。
        解放の価値は連撃の継続に依存し、規則の閾値では表現しきれない。
        """
        p = s.players[pi]
        r = [a for a in acts if a["type"] == "rush"]
        if not r:
            return {"type": "stop"}
        return max(r, key=lambda a: _c(p.hand[a["hand"]]).damage)

    def _discard(self, s, pi, acts):
        p = s.players[pi]
        d = [a for a in acts if a["type"] == "discard"]
        if not d:
            return self.rng.choice(acts)
        if not self.p.use_card_utility:
            return self.rng.choice(d)
        return min(d, key=lambda a: card_utility(s, pi, p.hand[a["hand"]], self.p))

    def _choice(self, s, pi, acts):
        """効果解決中の選択（D-015 / D-022）。"""
        p = s.players[pi]
        ch = s.pending_choices[0]
        kind = ch["kind"]

        if kind == "pay_or_damage":
            # 協奏1枚 vs ライフ3点。協奏に余裕があれば払う
            if len(p.concerto) >= self.p.pay_min_concerto and p.life > ch["amount"]:
                return {"type": "pay"}
            return {"type": "decline"}

        if kind == "switch_back":
            # 追補2: リーダー選択は「どの赤が生きるか」を決める
            backs = _back_names(s, pi)
            return max((a for a in acts),
                       key=lambda a: live_reds(s, pi, backs.get(a["back"])))

        if kind == "use_optional":
            return {"type": "use"}       # 現行カードプールでは実行して損な optional はない

        if kind == "reveal_count":
            n = ch["max"]
            if len(p.action_deck) + len(p.trash) <= self.p.keep_deck_min:
                n = min(n, max(len(p.action_deck), 0))
            return {"type": "choose_count", "count": n}

        if kind in ("discard", "discard_for_effect"):
            return self._discard(s, pi, acts)

        if kind == "order":
            return acts[0]

        return self.rng.choice(acts)
