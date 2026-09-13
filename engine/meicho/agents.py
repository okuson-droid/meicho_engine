"""ベースラインエージェント。乱数はすべてシード指定可能。"""

from __future__ import annotations

import random

from .engine import legal_actions, observe


class RandomAgent:
    """合法手から一様ランダムに選択するベースライン。"""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def act(self, state, player: int) -> dict:
        acts = legal_actions(state, player)
        assert acts, f"no legal actions for P{player} in {state.phase}"
        return self.rng.choice(acts)
