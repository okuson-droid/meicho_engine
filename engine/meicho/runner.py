"""自己対戦ランナー。UIを介さず純粋関数APIのみで対局を回す。"""

from __future__ import annotations

from .engine import GameConfig, apply, decision_players, initial_state, outcome
from .state import DRAW, GameState


def play_game(config: GameConfig, agents: list, seed: int,
              max_turns: int = 200, initial: GameState = None) -> dict:
    """1局実行して結果を返す。max_turns 超過は異常系として報告する。

    戻り値の "winner" は 0/1（勝者のindex）または None。
    引き分け (§9-5 の進行不能状態, D-021) の場合は "winner" が None で
    "draw" が True になる。打ち切りの場合は "aborted" が True。
    勝率集計では draw を勝敗のどちらにも数えないこと（作業規約6）。

    initial: 途中の局面から再開する場合の GameState（テスト・リプレイ用）。
        省略時は config と seed から初期局面を生成する。
    """
    s = initial.clone() if initial is not None else initial_state(config, seed)
    steps = 0
    while outcome(s) is None:
        if s.turn_no > max_turns:
            return {"winner": None, "turns": s.turn_no, "aborted": True,
                    "draw": False, "steps": steps}
        need = decision_players(s)
        actions = {pi: agents[pi].act(s, pi) for pi in need}
        s = apply(s, actions)
        steps += 1
    result = outcome(s)
    is_draw = (result == DRAW)
    return {"winner": None if is_draw else result, "turns": s.turn_no,
            "aborted": False, "draw": is_draw, "steps": steps,
            "life": [s.players[0].life, s.players[1].life]}
