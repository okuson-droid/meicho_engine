"""リプレイ（要件 R-REP-1〜3・APP-019）。終局した対局の記録（シード＋行動列）を初期局面から当て直し、1 手ごとの盤面と出来事を作る。

- 1 手＝1 回の `apply`。対局中と同じ `Game._advance` を通すので、出来事（演出の材料）も対局中と同じものが出る
- 視点は 4 つ: 席 0（先攻）・席 1（後攻）・観戦（公開情報のみ）・全情報（`FULL`）。**全情報は終局した対局にだけ使う**（R-REP-3）。
  このモジュールは終局した記録しか受け取らない（`build` が確かめる）
- 記録と局面が合わなければ（合法でない手・決定者の違い）、理由つきで `AppError` にする
- 盤面の中身は画面の対局中の `view` と同じ形。入力は無いので、合法手・決定の番号・手がかりは空にする
"""
from __future__ import annotations

from meicho import decision_players, legal_actions

from .game import Game
from .protocol import AppError
from .views import FULL, SPECTATOR

REPLAY_VIEWERS = (0, 1, SPECTATOR, FULL)
MAX_APPLIES = 5000


def parse_viewer(x):
    """画面から来た視点の名前を検める。"""
    if x in (0, 1, "0", "1"):
        return int(x)
    if x in (SPECTATOR, FULL):
        return x
    raise AppError("bad_message", "視点は 0・1・spec・full のどれか")


def _frame_view(g: Game, viewer, applies: int, result: dict = None) -> dict:
    v = g.public_view(viewer)
    v.update({"awaiting": [] if g.state.outcome is not None else sorted(decision_players(g.state)),
              "submitted": [], "applies": applies, "legal": [], "labels": [], "hints": {}, "token": 0})
    if result is not None and result.get("reason") == "resign":
        v["outcome"] = result["winner"]
        v["resigned"] = 1 - result["winner"]
    return v


def build(dump: dict, result: dict = None) -> dict:
    """記録 1 件から、4 つの視点ぶんの手の列を作る。

    戻り値: `{viewer: [{"view": 盤面, "events": [出来事…]}, …]}`。先頭は最初の盤面（出来事なし）。
    投了で終わった局は、最後に「投了」の 1 手を足す。`result` を渡すと、当て直した結果と照合する。
    """
    applies = dump.get("applies") or []
    if len(applies) > MAX_APPLIES:
        raise AppError("bad_record", "記録が長すぎる")
    g = Game(dump["decks"], dump["seed"])
    g.viewers = REPLAY_VIEWERS
    frames = {v: [{"view": _frame_view(g, v, 0), "events": []}] for v in REPLAY_VIEWERS}
    for n, row in enumerate(applies, 1):
        try:
            actions = {int(p): a for p, a in sorted(row.items())}
        except (AttributeError, ValueError):
            raise AppError("bad_record", "記録の形が違う") from None
        if sorted(actions) != sorted(decision_players(g.state)):
            raise AppError("bad_record", f"{n} 手目で記録と局面が合わない")
        for p, a in actions.items():
            if a not in legal_actions(g.state, p):
                raise AppError("bad_record", f"{n} 手目に合法でない手がある")
        out = g._advance(actions)
        g.applies.append(row)
        for v in REPLAY_VIEWERS:
            frames[v].append({"view": _frame_view(g, v, n), "events": out.get(v, [])})
    resigned = dump.get("resigned")
    if resigned is not None:
        g.resigned = resigned
        fin = g.result()
        for v in REPLAY_VIEWERS:
            frames[v].append({"view": _frame_view(g, v, len(applies), fin),
                              "events": [{"t": "game_over", "outcome": 1 - resigned, "reason": "resign"}]})
    if not g.over:
        raise AppError("not_finished", "終局していない対局は再生しない（全情報を開かないため・R-REP-3）")
    got = g.result()
    if result is not None and (got["winner"], got["reason"]) != (result.get("winner"), result.get("reason")):
        raise AppError("bad_record", "当て直した結果が記録と違う（エンジンの版が違う可能性がある）")
    return frames


def message(frames: dict, viewer, *, names: list, result: dict, source: dict) -> dict:
    """画面へ送る 1 通。`source` はどの対局か（部屋の最後の局／手元の記録の番号）。"""
    return {"t": "replay", "viewer": viewer, "frames": frames[viewer], "names": list(names),
            "result": result, "source": source}
