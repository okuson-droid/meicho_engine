"""対局の記録と再生（APP_DESIGN.md §6）。

## 設計の要点

**記録は「シード＋全行動列」だけを持ち、盤面は保存しない。**
エンジンは決定的なので（作業規約6 / D-006）、同じシードから同じ行動を順に
適用すれば全局面が完全に再現される。盤面も保存すると同じ事実が 2 か所に書かれ、
食い違いうる。導出すれば真実源は 1 つのままである。

**再生は AI を必要としない。** 記録には AI の行動も入っているので、
再生は両者の手を記録から取り出すだけで済む。したがって
**AI の実装が将来変わっても、古い記録はそのまま再生できる**。
安定していなければならないのはエンジンだけである。

`replay()` が返す局面列が、対局後レビュー（§5）の土台になる。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

from meicho.engine import apply, decision_players, initial_state, legal_actions, outcome
from meicho.state import DRAW

APP_VERSION = "2"
RULES_VERSION = "v0.10"
ENGINE_VERSION = "v0.1"
JST = timezone(timedelta(hours=9))


class RecordMismatch(Exception):
    """記録の再生が元の結果と一致しない（記録の欠落かエンジンの非決定性）。"""


# ------------------------------------------------------------------ 書き出し
def to_record(sess) -> dict:
    return {
        "app_version": APP_VERSION,
        "rules_version": RULES_VERSION, "engine_version": ENGINE_VERSION,
        "played_at": datetime.now(JST).isoformat(timespec="seconds"),
        "game_id": sess.game_id,
        "seed": sess.seed, "deck": sess.deck_name, "mode": "mirror",
        "human_seat": sess.human_seat,
        "opponent": {"name": sess.opponent_name, "seed": sess.ai_seed},
        "show_ai_thinking": bool(sess.show_ai_thinking),
        "actions": sess.actions,
        "flags": sess.flags,
        "result": sess.result(),
    }


def save(rec: dict, base_dir: str) -> str:
    """月ごとの JSON Lines に追記する。"""
    d = os.path.join(base_dir, "human_games")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, rec["played_at"][:7] + ".jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def load_all(base_dir: str) -> list:
    d = os.path.join(base_dir, "human_games")
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(d, name), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


# ------------------------------------------------------------------ 再生
class ReplayAgent:
    """記録された行動を順に返すだけのエージェント。

    席ごとに待ち行列を作る。`apply` は 1 回で複数人ぶんを受け取るが、
    席ごとの順序さえ保たれていれば `act` の呼ばれる順に依存しない。
    """

    def __init__(self, actions: list, seat: int, *, legacy_stage1a: bool = False):
        self.queue = [r["action"] for r in actions if r["seat"] == seat]
        self.pos = 0
        self.seat = seat
        self.legacy_stage1a = legacy_stage1a

    def act(self, s, pi):
        assert pi == self.seat, f"席違い: {pi} != {self.seat}"
        # 段階1Aより前の記録には、当時は自動だった選択行動が存在しない。
        # その3種類だけは旧実装と同じ先頭候補を補い、記録の行動列は消費しない。
        if (self.legacy_stage1a and s.phase.value == "choice" and s.pending_choices
                and s.pending_choices[0]["kind"] in {
                    "pay_cost_card", "zone_card", "levelup_by_effect"}):
            return next(a for a in legal_actions(s, pi) if a["type"] != "stop")
        if self.pos >= len(self.queue):
            raise RecordMismatch(
                f"席{self.seat} の記録が足りない（{len(self.queue)} 手で尽きた）")
        a = self.queue[self.pos]
        self.pos += 1
        return a

    @property
    def exhausted(self) -> bool:
        return self.pos >= len(self.queue)


def replay(rec: dict, config, keep_states: bool = False) -> dict:
    """記録を再生する。

    keep_states=True なら各 `apply` の直前の局面をすべて返す（レビューの土台）。
    **返す局面には両者の手札も山札も入っている**ので、
    対局中の画面に渡してはならない（§5.7 の安全装置はサーバ側で行う）。
    """
    legacy_stage1a = int(rec.get("app_version", "1")) < 2
    agents = [ReplayAgent(rec["actions"], 0, legacy_stage1a=legacy_stage1a),
              ReplayAgent(rec["actions"], 1, legacy_stage1a=legacy_stage1a)]
    s = initial_state(config, rec["seed"])
    states, steps = ([s] if keep_states else []), 0
    while outcome(s) is None and s.turn_no <= 200:
        need = decision_players(s)
        if not need:
            break
        if all(agents[pi].exhausted for pi in need):
            break                      # 記録が途中で終わっている（投了・異常）
        s = apply(s, {pi: agents[pi].act(s, pi) for pi in need})
        steps += 1
        if keep_states:
            states.append(s)
        if steps > 20000:
            raise RecordMismatch("再生が終わらない")
    o = outcome(s)
    res = {
        "winner": None if o is None or o == DRAW else
                  ("human" if o == rec["human_seat"] else "ai"),
        "turns": s.turn_no,
        "life": [s.players[0].life, s.players[1].life],
        "draw": o == DRAW,
        "unfinished": o is None,
    }
    return {"result": res, "states": states, "final": s}


def verify(rec: dict, config) -> dict:
    """記録どおりに再生できることを確かめる。食い違ったら例外。

    ここが通れば同時に保証されること（§6.2）:
      - 記録に漏れがない（漏れていたら再生できない）
      - エンジンが決定的である
      - アプリがエンジンを迂回していない
    """
    got = replay(rec, config)["result"]
    want = rec.get("result") or {}
    if want.get("reason") in ("resign", "error"):
        return got                     # 投了・異常は最後まで進んでいないので照合しない
    for key in ("winner", "turns", "life", "draw"):
        if key in want and want[key] != got[key]:
            raise RecordMismatch(
                f"再生が一致しない: {key} 記録={want[key]!r} 再生={got[key]!r}")
    return got
