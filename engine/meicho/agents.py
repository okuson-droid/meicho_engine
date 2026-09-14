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
        # 段階1Aで増えた選択は、v5の方策へ移すまで旧実装の既定回答を使う。
        # setup は従来と同じ3リーダーから乱択し、バックは名前順に固定する。
        if state.phase.value == "setup_chara":
            acts = [a for a in acts if a.get("backs") == sorted(a.get("backs", []))]
        if state.phase.value == "choice" and state.pending_choices:
            if state.pending_choices[0]["kind"] in {
                    "pay_cost_card", "zone_card", "levelup_by_effect"}:
                return next(a for a in acts if a["type"] != "stop")
        return self.rng.choice(acts)
