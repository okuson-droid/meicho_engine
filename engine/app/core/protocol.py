"""通信の版・メッセージの種類・エラーの符号（要件 R-NET-5・R-UPD-10）。

メッセージは JSON の辞書で、必ず `t`（種類）を持つ。画面が送るのは**合法手の添字と、
その決定の番号（`token`）だけ**であり、行動の中身を組み立てない（要件 R-PLAY-3・D-063 の
「画面はルールを持たない」を引き継ぐ）。
"""
from __future__ import annotations

PROTOCOL_VERSION = 1

# 画面 → サーバ
C_HELLO = "hello"        # {v, room, name, pass?, key?}
C_SIT = "sit"            # {seat: 0|1}
C_STAND = "stand"        # {}
C_DECK = "deck"          # {deck: {name, chara_deck, action_deck}}
C_READY = "ready"        # {on: bool}
C_SETTINGS = "settings"  # {first: "random"|"seat0"|"seat1"|"loser"}  部屋主だけ
C_FIRST = "first"        # {choice: "me"|"opp"}  first="loser" のとき、前の局の敗者だけ
C_ACT = "act"            # {token, index}
C_RESIGN = "resign"      # {}
C_REMATCH = "rematch"    # {}
C_PING = "ping"          # {}
C_REPLAY = "replay"      # {viewer: 0|1|"spec"|"full"}  終局したあとだけ。この部屋の最後の局を再生する（APP-019）

# サーバ → 画面
S_WELCOME = "welcome"    # {v, member, key, room}
S_ROOM = "room"          # {room}
S_VIEW = "view"          # {view, events, full}
S_ERROR = "error"        # {code, msg, ref?}
S_PONG = "pong"
S_REPLAY = "replay"      # {viewer, frames, names, result, source}
S_BYE = "bye"            # {code}  この接続は閉じられる

FIRST_MODES = ("random", "seat0", "seat1", "loser")

MAX_ROOMS = 4            # 要件 R-NF-5
MAX_SPECTATORS = 4       # 要件 R-SPEC-4
MAX_NAME = 24


class AppError(Exception):
    """画面へ `error` として返す失敗。**状態を変えずに**投げること（要件 R-NF-11）。"""

    def __init__(self, code: str, msg: str = ""):
        super().__init__(f"{code}: {msg}")
        self.code, self.msg = code, msg
        self.resync: list = []      # エラーの前に本人へ送り直すメッセージ（古い画面の取り直し・R-NET-5）
