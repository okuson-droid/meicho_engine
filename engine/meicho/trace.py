"""トレース点（M1・`engine/app/M1_EVENT_SPEC.md`・送り箱 TE-5・D-114）。

エンジンの解決の区切りごとに「いまここを通った」を外へ知らせる口である。
出来事の組み立て・席ごとの伏せ方・観戦視点は**使う側（`engine/app/`）が作る**。ここはトレース点だけを持つ。

使い方::

    from meicho import trace
    def sink(kind, info, s): ...          # s は解決途中の生の状態。読むだけ・保持しない
    with trace.tracing(sink):
        s2 = apply(s, actions)            # この with の中で、このスレッド（文脈）から呼んだ apply だけが流れる

不変条件（仕様書 §5）:

- **トレースは状態を読むだけで書かない。**sink の有無で `apply` の結果・乱数の消費・digest・指紋は変わらない
- `GameState` に欄を足さない。Rust（`meicho_rs`）は追従しない
- **切れているときの費用は、トレース点 1 か所につき大域の整数 1 回の読み取り**（`if trace.ACTIVE:`）
- **文脈ごとに隔離する。**`contextvars` で持つので、別スレッド（AI の探索など）の `apply` は
  sink を設定したスレッドの sink に流れ込まない。`ACTIVE` はプロセス全体の「どこかで有効か」の数にすぎず、
  別スレッドは `ACTIVE` が 0 でないと `emit` まで来るが、自分の文脈に sink が無いので何もしない
- sink の中の例外は握りつぶさず、呼び出し元へそのまま伝える

`kind` と `info` の一覧は `engine/TO_APP.md`（TA-7）と `tests/test_trace_m1.py` にある。
"""
from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager

# プロセス内で有効な sink の数。トレース点は `if trace.ACTIVE:` で読むだけにする（仕様書 §3）。
ACTIVE = 0
_lock = threading.Lock()
_sink: contextvars.ContextVar = contextvars.ContextVar("meicho_trace_sink", default=None)


@contextmanager
def tracing(sink):
    """この with の中で、この文脈から呼ばれた `apply` のトレース点を `sink(kind, info, s)` に渡す。"""
    global ACTIVE
    token = _sink.set(sink)
    with _lock:
        ACTIVE += 1
    try:
        yield
    finally:
        with _lock:
            ACTIVE -= 1
        _sink.reset(token)


def emit(s, kind: str, **info) -> None:
    """エンジン内部から呼ぶ。この文脈に sink が無ければ何もしない。"""
    sink = _sink.get()
    if sink is not None:
        sink(kind, info, s)
