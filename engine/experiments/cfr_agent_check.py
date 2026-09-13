"""CFR均衡戦略を実ゲームで走らせ、色の出現頻度が「持続可能か」を検証する。

問題意識（マスター指摘, 2026-08-22）:
対抗ステップCFRは1手番ゲームとして解いており、毎反復まっさらな手札を
デッキから引き直す。つまり**手札の枯渇を無視している**。
青を出し続ければ手札とデッキの青は減るが、1手番モデルではそれが起きない。

検証方法:
学習した均衡戦略に従うエージェントで実ゲームを回し、
**実際の色の出現頻度**を、**学習時の想定頻度**と比較する。
乖離が大きいほど、1手番モデルの「i.i.d.な手札」という仮定が破れている。
"""
import json
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import clash_cfr as C
import run_clash_cfr as R
from meicho.cards import ACTION_CARDS, CHARA_CARDS
from meicho.engine import (GameConfig, apply, decision_players, initial_state,
                           legal_actions, outcome)
from meicho.state import Phase


class CFRClashAgent:
    """対抗ステップだけ CFR の均衡戦略に従い、他はランダムに指すエージェント。

    リーダーは対局中に切り替わるため、現在のリーダー組に対応する表を引く。
    """

    def __init__(self, tables, seed):
        self.tables = tables            # {(自リーダー名, 相手リーダー名): CFR}
        self.rng = random.Random(seed)
        self.log = Counter()            # 実際に選ばれた色
        self.fallback = 0               # 表が引けず一様に落ちた回数

    def _leader(self, s, pi):
        st = s.players[pi].slots[0].stack
        return CHARA_CARDS[st[-1]].name if st else None

    def act(self, s, pi):
        acts = legal_actions(s, pi)
        if s.phase != Phase.CLASH_SUBMIT:
            return self.rng.choice(acts)
        key = (self._leader(s, pi), self._leader(s, 1 - pi))
        cfr = self.tables.get(key)
        cols = C.usable_by_color(s, pi)
        choices = C.actions_for(s, pi)
        dist = None
        if cfr is not None:
            ik = C.infoset_key(s, pi)
            if ik in cfr.regret and set(cfr.action_list[ik]) == set(choices):
                dist = cfr.average(ik)
        if dist is None:
            self.fallback += 1
            dist = {a: 1.0 / len(choices) for a in choices}
        r = self.rng.random()
        acc = 0.0
        pick = choices[-1]
        for a in choices:
            acc += dist.get(a, 0.0)
            if r <= acc:
                pick = a
                break
        self.log[pick] += 1
        return C.to_engine_action(s, pi, pick)
