"""1 局の進行。エンジンを包み、席からの「添字の提出」を受けて `apply` し、視点と出来事を作る。

ここが守るもの:

- **サーバが唯一の正**（要件 R-SEC-1）。席が送れるのは合法手の添字だけで、行動の辞書はここで引く
- **対抗の提出順**（要件 R-CLASH-1〜3・公式 604.1.1）。エンジンは 2 人ぶんが揃ってから解決するが、
  非ターンプレイヤーの入力は、ターンプレイヤーが置き終わるまで開かない
- **決定の番号**（`token`）。席ごとに「いま開いている決定」に番号を振り、古い画面からの提出・二重送信を弾く（要件 R-NET-5）
- **記録はシード＋行動列**（要件 R-DATA-1）。盤面は保存せず、`replay` で復元する（要件 R-NET-6）
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Optional

from meicho import GameConfig, apply, decision_players, initial_state, legal_actions
from meicho.state import DRAW, GameState, Phase

try:                                    # トレース点（M1・TE-5／TA-7・D-114）。無い版のエンジンでも動くようにしておく
    from meicho import trace as _trace
except ImportError:                     # pragma: no cover
    _trace = None

from . import describe, hints
from .protocol import AppError
from .views import FULL, SPECTATOR, diff_events, view_for, visible_cards

VIEWERS = (0, 1, SPECTATOR)


def make_config(decks: list) -> GameConfig:
    """`decks` は席 0（先攻）・席 1 の順の `{chara_deck, action_deck}`。構築ルールに反すれば `AppError`。"""
    cfg = GameConfig(chara_decks=[list(d["chara_deck"]) for d in decks],
                     action_decks=[list(d["action_deck"]) for d in decks])
    try:
        cfg.validate()
    except (AssertionError, KeyError) as e:
        raise AppError("bad_deck", str(e)) from None
    return cfg


def check_deck(deck: dict) -> None:
    """デッキ 1 つを構築ルールで検査する（要件 R-ROOM-5・R-DECK-3）。正は `GameConfig.validate` である。"""
    if not isinstance(deck, dict) or not isinstance(deck.get("chara_deck"), list) \
            or not isinstance(deck.get("action_deck"), list):
        raise AppError("bad_deck", "デッキの形式が違う")
    if not all(isinstance(c, str) for c in deck["chara_deck"] + deck["action_deck"]):
        raise AppError("bad_deck", "カード番号は文字列")
    try:
        make_config([deck, deck])
    except AppError as e:
        raise AppError("bad_deck", e.msg.removeprefix("P0: ").strip("'\"")) from None


class Game:
    """進行中の 1 局。席は 0（先攻）と 1。"""

    def __init__(self, decks: list, seed: int, *, clock=time.monotonic):
        self._clock = clock
        self.times: list = []            # applies と同じ並び。1 要素＝{席(文字列): その決定にかけたミリ秒}（要件 R-DATA-7）
        self._opened_at = [None, None]
        self._held_ms: dict = {}
        self.decks = [{"name": d.get("name", ""), "chara_deck": list(d["chara_deck"]),
                       "action_deck": list(d["action_deck"])} for d in decks]
        self.seed = seed
        self.state: GameState = initial_state(make_config(self.decks), seed)
        self.applies: list = []          # 確定した行動。1 要素＝1 回の apply＝{席(文字列): 行動}
        self.held: dict = {}             # 提出済みで、まだ apply していない行動 {席: 行動}
        self.tokens = [0, 0]             # 席ごとの「決定の番号」。決定が開くたびに進む
        self._open: set = set()
        self.resigned: Optional[int] = None
        self.last_frames: dict = {}
        self.last_reveals: list = []
        # 「全員に公開されたうえで手札に入った」カード（席ごと）。見ていた全員が知っている公開情報である（_note_public を参照）
        self.public_known = [Counter(), Counter()]
        self.viewers = VIEWERS            # 出来事を作る相手。リプレイだけが全情報（FULL）を足す（replay.py）
        self._reopen()

    # ------------------------------------------------------------------ 決定の開閉
    def _wanted(self) -> list:
        """いま入力を受け付ける席。対抗の提出は、ターンプレイヤーが先（要件 R-CLASH-1）。"""
        if self.over:
            return []
        need = [p for p in decision_players(self.state) if p not in self.held]
        tp = self.state.turn_player
        if self.state.phase == Phase.CLASH_SUBMIT and tp in need:
            return [tp]
        return need

    def _reopen(self) -> None:
        now = set(self._wanted())
        for p in now - self._open:
            self.tokens[p] += 1
            self._opened_at[p] = self._clock()
        self._open = now

    @property
    def over(self) -> bool:
        return self.state.outcome is not None or self.resigned is not None

    def awaiting(self) -> list:
        return sorted(self._open)

    def legal(self, pi: int) -> list:
        return legal_actions(self.state, pi) if pi in self._open else []

    # ------------------------------------------------------------------ 提出
    def submit(self, pi: int, token, index, *, ms=None) -> dict:
        """席 pi が、番号 `token` の決定に、合法手の `index` 番を提出する。

        戻り値は `{viewer: [出来事…]}`。検査に落ちたら**何も変えずに** `AppError` を投げる。
        """
        if pi not in (0, 1):
            raise AppError("not_seated", "席に着いていない")
        if pi not in self._open:
            raise AppError("not_awaited", "いまはあなたの入力を待っていない")
        if token != self.tokens[pi]:
            raise AppError("stale", "画面が古い。最新の状態を取り直した")
        acts = legal_actions(self.state, pi)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(acts):
            raise AppError("bad_index", "その手は選べない")
        self.held[pi] = acts[index]
        # かかった時間は席ごとに測る。人間は「決定が開いてから提出まで」（画面の演出を見ている時間も入る）、
        # AI は考えた時間そのものを外から渡す。混ぜない（要件 R-DATA-7）
        if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms >= 0:
            self._held_ms[pi] = int(ms)
        else:
            t0 = self._opened_at[pi]
            self._held_ms[pi] = int((self._clock() - t0) * 1000) if t0 is not None else 0
        self._open.discard(pi)      # この決定は閉じた。続けて同じ席の決定が開くなら、番号は必ず進む（二重送信を弾くため）
        if set(self.held) != set(decision_players(self.state)):
            # 相手の提出を待つ。相手に見えるのは「提出した」という事実だけ（要件 R-CLASH-2）
            placed = self.state.phase == Phase.CLASH_SUBMIT and self.held[pi]["type"] == "submit"
            ev = {"t": "placed" if placed else "submitted", "player": pi}
            self._reopen()
            return {v: [dict(ev)] for v in VIEWERS}
        return self._apply_held()

    def _apply_held(self) -> dict:
        actions = {p: self.held[p] for p in sorted(self.held)}      # 席の昇順（D-050）
        out = self._advance(actions)
        self.times.append({str(p): self._held_ms.get(p, 0) for p in actions})
        self.held, self._held_ms = {}, {}
        self._reopen()
        return out

    def _advance(self, actions: dict) -> dict:
        """行動を `apply` し、席ごとの出来事を**起きた順に**作る（要件 R-FX-1）。復元（`load`）も同じ道を通る。

        エンジンのトレース点（解決の区切り）ごとに、その時点の状態をその相手の視点に直し、直前の視点との差分を出来事にする。
        入力はどの時点でもその相手の `observe` だけなので、見えないカード番号は出来事に入らない（APP-003）。
        ただ 1 つの例外が、エンジンが `reveal` で知らせる「公開」である。知らせの宛先（全員か、席）に入っている相手にだけ `show` として渡す。
        """
        viewers = self.viewers
        prev = {v: view_for(self.state, v) for v in viewers}
        out: dict = {v: [] for v in viewers}
        self.last_frames = {v: [prev[v]] for v in viewers}          # 検査用: この apply の間に各相手へ見えていた盤面の列
        self.last_reveals = []                                      # 検査用: エンジンが知らせた「公開」の生の内容
        hand_before = [Counter(p.hand) for p in self.state.players]
        shown: list = [Counter(), Counter()]                        # この apply の間に、全員に公開されたカード（持ち主ごと）

        def step(s) -> None:
            for v in viewers:
                cur = view_for(s, v)
                ev = diff_events(prev[v], cur)
                if v == SPECTATOR:
                    self._note_public_exits(ev)
                out[v] += ev
                prev[v] = cur
                self.last_frames[v].append(cur)

        def sink(kind: str, info: dict, s) -> None:
            step(s)
            if kind == "step" and info.get("what") == "skill":
                # 効果の解決の区切り（APP-024）。スキル 1 個の解決が始まるたびに 1 つ。
                # 番号は、その相手の視点にそのカードが写っているときだけ付ける（APP-003）
                for v in viewers:
                    cid = info.get("card")
                    out[v].append({"t": "skill", "player": info.get("player"),
                                   "card": cid if cid in visible_cards(prev[v]) else None})
            if kind == "damage":
                self._tag_damage(out, prev, info)
            if kind == "reveal" and info.get("cards"):
                self.last_reveals.append(dict(info))
                aud, owner = info.get("audience"), info.get("owner")
                if aud == "all" and owner in (0, 1):
                    if info.get("zone") == "hand":                  # 手札そのものを全員に見せた（対抗で置けないときの公開）
                        self.public_known[owner] = self.public_known[owner] | Counter(info["cards"])
                    else:
                        shown[owner] += Counter(info["cards"])
                for v in viewers:
                    if aud == "all" or aud == v or v == FULL:
                        out[v].append({"t": "show", "owner": owner, "cards": list(info["cards"]),
                                       "zone": info.get("zone")})

        if _trace is not None:
            with _trace.tracing(sink):
                self.state = apply(self.state, actions)
        else:                                                       # トレース点の無いエンジン: 前後の差分だけ（順序は粗い）
            self.state = apply(self.state, actions)
        step(self.state)
        # 全員に公開されて、そのまま手札に入ったカード。以後、その席の手札にあることを全員が知っている
        for pi in (0, 1):
            gained = Counter(self.state.players[pi].hand) - hand_before[pi]
            new = shown[pi] & gained
            if new:
                self.public_known[pi] += new
                cards = sorted(new.elements())
                for v in viewers:
                    if v != pi and v != FULL:               # 全情報では手札がもともと全部見えている
                        out[v].append({"t": "known", "player": pi, "cards": cards})
        self.applies.append({str(p): a for p, a in actions.items()})
        return out

    @staticmethod
    def _tag_damage(out: dict, prev: dict, info: dict) -> None:
        """いま起きたダメージのライフの出来事に、出どころのカードを付ける（APP-016）。

        トレース点 `damage` はライフを減らした直後に来るので、直前の `step` が作った最後の「減った」ライフの出来事がそれである。
        出どころの番号は、**その相手の視点にそのカードが写っているときだけ**付ける（見えないカードの番号を漏らさない・APP-003）。
        """
        src = info.get("source")
        cid = src[1] if src and len(src) > 1 else None
        for v in out:
            for e in reversed(out[v]):
                if e.get("t") == "life" and e.get("player") == info.get("player") and e.get("delta", 0) < 0:
                    if "src" not in e:
                        e["dealer"] = info.get("dealer")
                        e["amount"] = info.get("amount")          # 軽減・加算のあとのダメージ。とどめでは減ったライフより大きいことがある
                        e["src"] = cid if cid is not None and cid in visible_cards(prev[v]) else None
                    break

    def _note_public_exits(self, public_events: list) -> None:
        """公開情報としての「手札にあると知られているカード」を、手札から出るたびに減らす。

        材料は観戦者の視点の出来事（＝全員に見えている動き）だけである。カード番号つきで手札から出たら 1 枚減らす。
        **カード番号の見えない出方（手札 → デッキの下など）があったら、その席の分を全部忘れる。**どれが出たか分からない以上、
        「まだ手札にある」と言い切れるカードが無くなるからである。本当の手札と突き合わせて消すことはしない（それをすると、
        見えないはずの「どれが出たか」が画面から読めてしまう）。
        """
        for e in public_events:
            if e.get("t") == "move" and e.get("from") == "hand" and e.get("player") in (0, 1):
                known = self.public_known[e["player"]]
                if e.get("card") is None:
                    known.clear()
                elif known[e["card"]] > 0:
                    known[e["card"]] -= 1
                    if not known[e["card"]]:
                        del known[e["card"]]

    def resign(self, pi: int) -> dict:
        if pi not in (0, 1) or self.over:
            raise AppError("not_awaited", "投了できない")
        self.resigned = pi
        self.held, self._held_ms = {}, {}
        self._reopen()
        return {v: [{"t": "game_over", "outcome": 1 - pi, "reason": "resign"}] for v in VIEWERS}

    # ------------------------------------------------------------------ 送るもの
    def public_view(self, viewer) -> dict:
        """その相手の視点に、全員に公開されて手札に入ったカードを重ねたもの（対局中の画面とリプレイで共通）。"""
        v = view_for(self.state, viewer)
        for pi in (0, 1):                       # 全員に公開されて手札に入ったカードは、相手と観戦者に表向きで見せる
            pl = v["players"][pi]
            if pl["hand"] is None and self.public_known[pi]:
                merged = Counter(pl["hand_known"]) | self.public_known[pi]
                pl["hand_known"] = sorted(merged.elements())
        return v

    def view(self, viewer) -> dict:
        v = self.public_view(viewer)
        v["awaiting"] = self.awaiting()
        v["submitted"] = sorted(self.held)
        v["applies"] = len(self.applies)
        if viewer in (0, 1):
            legal = self.legal(viewer)
            v["token"] = self.tokens[viewer]
            v["legal"] = legal
            v["labels"] = describe.labels(self.state, viewer, legal)       # 安全網の一覧用（R-PLAY-11）
            v["hints"] = hints.make(self.state, viewer, self.awaiting(), self.held, legal)   # R-PLAY-4
            if viewer in self.held:                                        # 自分が裏向きで置いたカード（R-ACT-7）
                v["my_held"] = self.held[viewer]
        else:
            v["hints"] = hints.for_spectator()
        if self.resigned is not None:
            v["outcome"] = 1 - self.resigned
            v["resigned"] = self.resigned
        return v

    def result(self) -> Optional[dict]:
        if not self.over:
            return None
        if self.resigned is not None:
            return {"winner": 1 - self.resigned, "draw": False, "reason": "resign",
                    "turns": self.state.turn_no, "life": [p.life for p in self.state.players]}
        o = self.state.outcome
        return {"winner": None if o == DRAW else o, "draw": o == DRAW, "reason": "normal",
                "turns": self.state.turn_no, "life": [p.life for p in self.state.players]}

    # ------------------------------------------------------------------ 保存と復元
    def dump(self) -> dict:
        return {"seed": self.seed, "decks": self.decks, "applies": self.applies, "times": self.times,
                "held": {str(p): a for p, a in self.held.items()}, "resigned": self.resigned}

    @classmethod
    def load(cls, d: dict) -> "Game":
        """保存した行動列を初期局面から当て直して復元する。決定的なので盤面は保存しない。"""
        g = cls(d["decks"], d["seed"])
        for row in d["applies"]:
            actions = {int(p): a for p, a in sorted(row.items())}
            need = decision_players(g.state)
            if sorted(actions) != sorted(need):
                raise AppError("bad_record", "記録と局面が合わない")
            for p, a in actions.items():
                if a not in legal_actions(g.state, p):
                    raise AppError("bad_record", "記録に合法でない手がある")
            g._advance(actions)                  # 対局中と同じ道を通す（公開されて手札に入ったカードの覚えも一緒に戻る）
        g.times = list(d.get("times") or [])
        g.held = {int(p): a for p, a in d.get("held", {}).items()}
        g.resigned = d.get("resigned")
        g._open = set()
        g._reopen()
        return g
