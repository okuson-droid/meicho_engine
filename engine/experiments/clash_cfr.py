"""対抗ステップだけを抜き出した CFR 実験。

目的: 対抗ステップ (rules_draft.md v0.10 §6.4(1)-(2)) は同時提出の行列ゲームであり、
決定論的な最適手が存在しない。どの色をどの比率で提出すべきかという
混合戦略を、反実仮想後悔最小化 (CFR) で求める。

## 部分ゲームの定義

1回の対抗だけを取り出した1手番ゲームとして扱う。
- チャンス: 両プレイヤーが自分のデッキから手札 HAND_SIZE 枚を引く（非復元抽出）
- 同時手番: ターンプレイヤーは使用条件を満たすカードを1枚提出（可能なら必須, §6.4(1)-1）。
  非ターンプレイヤーは提出またはパス（任意, §6.4(1)-2）
- 利得: 実エンジンで対抗を解決し、そのターンが終わるまで進めたときの
  ライフ差・手札差・協奏差の変化（ゼロサム。詳細は payoff() 参照）

## 抽象化（結果を読むときの前提）

- **行動を色に抽象化する**。同色の中でどのカードを出すかは固定規則
  （使用可能なもののうち ダメージ→スピード の順で最大のもの）で選ぶ。
  実際には「安い赤で様子を見る」等の選択があるが、本実験では扱わない。
- **情報集合を手札の色構成に抽象化する**。「赤2枚・青1枚・緑1枚」までしか見ない。
  同じ色構成でも中身（燃える烈火か通常攻撃か）は区別しない。
- 盤面は固定する（協奏 CONCERTO 枚、アクションエリア空、ライフ20、キャラはLv0）。
- 連撃は固定方策（使用可能な赤のうち最大ダメージを出し続ける）で処理する。

これらは第一次近似であり、実戦の対抗ステップそのものではない。
"""
from __future__ import annotations

import json
import os
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from meicho.cards import ACTION_CARDS, CHARA_CARDS, Color
from meicho.engine import (GameConfig, apply, decision_players, initial_state,
                           legal_actions, _usable_in_clash)
from meicho.state import GameState, Phase, PlayerState, CharaSlot

HAND_SIZE = 4        # 実測: 対抗時の使用可能枚数の中央値は4
CONCERTO = 4         # 実測: 対抗時の協奏枚数の中央値は4
COLORS = [Color.RED, Color.BLUE, Color.GREEN]
COLOR_JA = {Color.RED: "赤", Color.BLUE: "青", Color.GREEN: "緑"}
PASS = "PASS"


# ---------------------------------------------------------------------------
# 局面の構築と利得
# ---------------------------------------------------------------------------

def make_state(decks: list, chara_decks: list, leaders: list, hands: list,
               seed: int = 0) -> GameState:
    """対抗ステップ直前の局面を組み立てる。

    キャラは3体ともLv0で配置する（リーダー1体＋バック2体）。バックを空にすると
    変奏スキルのリーダー切り替えが機能しなくなるため、実局面に合わせて埋める。
    """
    s = GameState(seed=seed, players=[PlayerState(), PlayerState()])
    for pi in (0, 1):
        p = s.players[pi]
        lv0 = [c for c in chara_decks[pi] if CHARA_CARDS[c].level == 0]
        order = [leaders[pi]] + [c for c in lv0 if c != leaders[pi]]
        for si, cid in enumerate(order[:3]):
            p.slots[si] = CharaSlot(stack=[cid])
        p.chara_deck = [c for c in chara_decks[pi] if c not in order[:3]]
        p.hand = list(hands[pi])
        p.concerto = [decks[pi][0]] * CONCERTO
        p.action_deck = list(decks[pi])
        p.charas_revealed = True
        p.mulligan_done = True
    s.turn_no = 5
    s.turn_player = 0
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    return s


def _greedy_choice(ch: dict, s: GameState) -> dict:
    """効果解決中の選択の固定方策（抽象化の一部）。"""
    kind = ch["kind"]
    pi = ch["player"]
    if kind == "use_optional":
        return {"type": "use"}
    if kind == "reveal_count":
        return {"type": "choose_count", "count": ch["max"]}
    if kind in ("discard", "discard_for_effect"):
        # 最も弱い手札（ダメージ→コストの順で最小）を捨てる
        hand = s.players[pi].hand
        idx = min(range(len(hand)),
                  key=lambda i: (ACTION_CARDS[hand[i]].damage,
                                 -ACTION_CARDS[hand[i]].cost))
        return {"type": "discard", "hand": idx}
    if kind == "switch_back":
        return {"type": "choose_back", "back": ch["options"][0]}
    if kind == "order":
        return {"type": "resolve", "index": 0}
    if kind == "pay_or_damage":
        # 協奏1枚とライフ3点なら、協奏に余裕があれば払う
        return ({"type": "pay"} if len(s.players[pi].concerto) >= 3
                else {"type": "decline"})
    raise AssertionError(kind)


def _rush_action(s: GameState, pi: int) -> dict:
    """連撃の固定方策: 使用可能な赤のうち最大ダメージを出し続ける。"""
    acts = [a for a in legal_actions(s, pi) if a["type"] == "rush"]
    if not acts:
        return {"type": "stop"}
    return max(acts, key=lambda a: ACTION_CARDS[s.players[pi].hand[a["hand"]]].damage)


def _snapshot(s: GameState) -> list:
    return [(p.life, len(p.hand), len(p.concerto)) for p in s.players]


class _StopAtTurnEnd:
    """利得の測定範囲を「対抗＋連撃」に限定するためのコンテキストマネージャ。

    `_end_turn_begin` を差し替えて、ターン終了フェイズに入る直前で解決を止める。
    こうしないと同じ apply の中でターンが進み、**相手の次ターンのドロー2枚**まで
    利得に混入してしまい、カード差の項が意味をなさなくなる。
    """

    def __enter__(self):
        import meicho.engine as E
        self._E = E
        self._orig = E._end_turn_begin

        def stop(s):
            s.phase = Phase.GAME_OVER      # 決定要求を止めるためのマーカー（outcomeは変えない）

        E._end_turn_begin = stop
        return self

    def __exit__(self, *exc):
        self._E._end_turn_begin = self._orig
        return False


def payoff(s0: GameState, act0: dict, act1: dict,
           w_card: float, w_conc: float) -> float:
    """対抗＋連撃を解決し、P0視点の利得を返す（ゼロサム）。

    利得 = ライフ差の変化 + w_card × 手札差の変化 + w_conc × 協奏差の変化
    ターン終了フェイズ以降は測定範囲に含めない（_StopAtTurnEnd 参照）。
    """
    before = _snapshot(s0)
    with _StopAtTurnEnd():
        s = apply(s0, {0: act0, 1: act1})
        guard = 0
        while s.outcome is None and s.phase != Phase.GAME_OVER and guard < 100:
            guard += 1
            need = decision_players(s)
            if not need:
                break
            acts = {}
            for pi in need:
                if s.phase == Phase.CHOICE:
                    acts[pi] = _greedy_choice(s.pending_choices[0], s)
                elif s.phase == Phase.RUSH:
                    acts[pi] = _rush_action(s, pi)
                else:
                    acts = {}
                    break
            if not acts:
                break
            s = apply(s, acts)
    after = _snapshot(s)
    life = (before[1][0] - after[1][0]) - (before[0][0] - after[0][0])
    card = (after[0][1] - before[0][1]) - (after[1][1] - before[1][1])
    conc = (after[0][2] - before[0][2]) - (after[1][2] - before[1][2])
    return life + w_card * card + w_conc * conc


# ---------------------------------------------------------------------------
# 色抽象化
# ---------------------------------------------------------------------------

def usable_by_color(s: GameState, pi: int) -> dict:
    """使用可能なカードを色ごとに分け、各色の代表カード（手札index）を返す。"""
    p = s.players[pi]
    best = {}
    for i, cid in enumerate(p.hand):
        c = ACTION_CARDS[cid]
        if not _usable_in_clash(s, pi, c):
            continue
        key = (c.damage, c.speed)
        if c.color not in best or key > best[c.color][1]:
            best[c.color] = (i, key)
    return {col: v[0] for col, v in best.items()}


def infoset_key(s: GameState, pi: int) -> tuple:
    """情報集合: (手番か, 使用可能カードの色構成)。"""
    p = s.players[pi]
    ct = Counter()
    for cid in p.hand:
        c = ACTION_CARDS[cid]
        if _usable_in_clash(s, pi, c):
            ct[COLOR_JA[c.color]] += 1
    return ("T" if pi == s.turn_player else "N",
            tuple(sorted(ct.items())))


def actions_for(s: GameState, pi: int) -> list:
    """色に抽象化した行動の一覧。"""
    cols = usable_by_color(s, pi)
    acts = [COLOR_JA[c] for c in COLORS if c in cols]
    if pi != s.turn_player or not acts:
        acts.append(PASS)
    return acts


def to_engine_action(s: GameState, pi: int, a: str) -> dict:
    if a == PASS:
        return {"type": "pass"}
    cols = usable_by_color(s, pi)
    col = next(c for c in COLORS if COLOR_JA[c] == a)
    return {"type": "submit", "hand": cols[col]}


# ---------------------------------------------------------------------------
# CFR（後悔マッチング）
# ---------------------------------------------------------------------------

def regret_match(regret: list) -> list:
    pos = [max(r, 0.0) for r in regret]
    tot = sum(pos)
    n = len(regret)
    return [p / tot for p in pos] if tot > 0 else [1.0 / n] * n


class CFR:
    def __init__(self):
        self.regret = {}
        self.strategy_sum = {}
        self.action_list = {}

    def _get(self, key, acts):
        if key not in self.regret:
            self.regret[key] = [0.0] * len(acts)
            self.strategy_sum[key] = [0.0] * len(acts)
            self.action_list[key] = list(acts)
        return self.regret[key], self.strategy_sum[key]

    def average(self, key):
        ssum = self.strategy_sum[key]
        tot = sum(ssum)
        n = len(ssum)
        probs = [x / tot for x in ssum] if tot > 0 else [1.0 / n] * n
        return dict(zip(self.action_list[key], probs))


def deal(deck: list, rng: random.Random) -> list:
    """デッキから HAND_SIZE 枚を非復元抽出する。"""
    return rng.sample(deck, HAND_SIZE)


def run_cfr(decks, chara_decks, leaders, iters, seed, w_card, w_conc, log=None):
    """外部サンプリング型 CFR。1手番同時ゲームなので後悔マッチングを直接回す。"""
    rng = random.Random(seed)
    cfr = CFR()
    for t in range(iters):
        h0, h1 = deal(decks[0], rng), deal(decks[1], rng)
        s = make_state(decks, chara_decks, leaders, [h0, h1])
        k0, k1 = infoset_key(s, 0), infoset_key(s, 1)
        a0, a1 = actions_for(s, 0), actions_for(s, 1)
        r0, ss0 = cfr._get(k0, a0)
        r1, ss1 = cfr._get(k1, a1)
        # 同じ情報集合でも手札の中身により行動数が変わりうるため長さを合わせる
        if len(r0) != len(a0) or len(r1) != len(a1):
            continue
        sig0, sig1 = regret_match(r0), regret_match(r1)
        u = [[payoff(s, to_engine_action(s, 0, x), to_engine_action(s, 1, y),
                     w_card, w_conc) for y in a1] for x in a0]
        cfv0 = [sum(sig1[j] * u[i][j] for j in range(len(a1))) for i in range(len(a0))]
        v0 = sum(sig0[i] * cfv0[i] for i in range(len(a0)))
        for i in range(len(a0)):
            r0[i] += cfv0[i] - v0
            ss0[i] += sig0[i]
        cfv1 = [sum(sig0[i] * (-u[i][j]) for i in range(len(a0))) for j in range(len(a1))]
        v1 = sum(sig1[j] * cfv1[j] for j in range(len(a1)))
        for j in range(len(a1)):
            r1[j] += cfv1[j] - v1
            ss1[j] += sig1[j]
        if log is not None and (t + 1) % log == 0:
            print(f"  iter {t+1}", flush=True)
    return cfr


def exploitability(cfr, decks, chara_decks, leaders, samples, seed, w_card, w_conc):
    """平均戦略に対する最適応答の値（ナッシュ・ギャップ）を推定する。

    ゼロサムなので、双方の最適応答値の和が0に近いほど均衡に近い。
    """
    rng = random.Random(seed)
    br0 = defaultdict(lambda: defaultdict(float))   # infoset -> action -> 期待値
    br1 = defaultdict(lambda: defaultdict(float))
    cnt0, cnt1 = Counter(), Counter()
    for _ in range(samples):
        h0, h1 = deal(decks[0], rng), deal(decks[1], rng)
        s = make_state(decks, chara_decks, leaders, [h0, h1])
        k0, k1 = infoset_key(s, 0), infoset_key(s, 1)
        a0, a1 = actions_for(s, 0), actions_for(s, 1)
        if k0 not in cfr.regret or k1 not in cfr.regret:
            continue
        avg0, avg1 = cfr.average(k0), cfr.average(k1)
        u = [[payoff(s, to_engine_action(s, 0, x), to_engine_action(s, 1, y),
                     w_card, w_conc) for y in a1] for x in a0]
        for i, x in enumerate(a0):
            br0[k0][x] += sum(avg1.get(y, 0.0) * u[i][j] for j, y in enumerate(a1))
        cnt0[k0] += 1
        for j, y in enumerate(a1):
            br1[k1][y] += sum(avg0.get(x, 0.0) * (-u[i][j]) for i, x in enumerate(a0))
        cnt1[k1] += 1
    n0, n1 = max(sum(cnt0.values()), 1), max(sum(cnt1.values()), 1)
    v0 = sum(max(d.values()) for d in br0.values()) / n0
    v1 = sum(max(d.values()) for d in br1.values()) / n1
    return v0, v1, v0 + v1
