"""対局セッション（APP_DESIGN.md §2・段階1）。

人間が 1 人入るので、エンジンの対局ループを「人間の入力待ちで止まる」形に開く。
ルールの判断は一切しない。`decision_players` / `legal_actions` / `apply` を
そのまま呼ぶだけである。

## 同時提出の扱い（§2.3・最重要）

対抗ステップは両者が裏向きで同時に出す。したがって:

1. 人間の選択を受け取る（**まだ apply しない**）
2. **同じ局面**を AI に渡して手を聞く
3. 両方を揃えて 1 回の `apply` で解決する

`_step` がこの順序を守る。AI が受け取る局面に人間の提出は入っていないので、
**構造的に覗けない**。`tests/test_webapp.py` で固定している。

## ログの作り方（漏洩を防ぐ）

AI の行動をそのまま日本語にすると、まだ公開されていない情報が漏れる
（対抗の提出は裏向きである）。そこで **AI の行動は動詞だけを述べ、
カード名は「人間の観測が適用後に公開領域で見たもの」からのみ書く**。
こうすると漏れようがなく、しかもログとしては十分に詳しくなる。
"""
from __future__ import annotations

import time

from meicho.engine import (apply, decision_players, initial_state,
                           legal_actions, observe, outcome)
from meicho.state import DRAW, Phase

from . import view

MAX_TURNS = 200

# 合法手の並び順（§4.2 の「数字キーで選ぶ」を安定させるため）。
# **`snapshot` と `play` は必ず同じ `legal()` を通す。** 別々に並べ替えると
# 画面の番号と実際に適用される手がずれ、取り返しのつかない事故になる。
_TYPE_ORDER = {
    "setup": 0, "mulligan": 0,
    "charge": 10, "switch": 11, "levelup": 12, "to_clash": 18, "end_turn": 19,
    "submit": 20, "pass": 29,
    "rush": 30, "stop": 39,
    "pay": 40, "decline": 41, "use": 42, "skip": 43,
    "choose_back": 44, "choose_count": 45, "resolve": 46, "discard": 47,
}


def _sort_key(item):
    i, a = item
    # マリガンは「戻す枚数が少ない順」に並べる（既定の全列挙は読みにくい）
    extra = len(a["cards"]) if a["type"] == "mulligan" else 0
    return (_TYPE_ORDER.get(a["type"], 99), extra, i)


class IllegalMove(Exception):
    """合法手一覧に無い手が送られた。"""


class StaleView(Exception):
    """画面が古い（別の手が既に適用されている）。"""


# ------------------------------------------------------------------ ログ
def _zone_added(before: list, after: list) -> list:
    """公開領域に増えたカード（多重集合の差）。"""
    rest = list(before)
    out = []
    for cid in after:
        if cid in rest:
            rest.remove(cid)
        else:
            out.append(cid)
    return out


_AI_VERB = {
    "setup": "リーダーを配置した", "mulligan": "マリガンした",
    "charge": "チャージした", "switch": "リーダーを切り替えた",
    "levelup": "レベルアップした", "to_clash": "対抗フェイズへ進んだ",
    "end_turn": "ターンを終えた", "submit": "対抗カードを提出した（裏向き）",
    "pass": "対抗をパスした", "pay": "コストを支払った",
    "decline": "支払わずダメージを受けた", "choose_back": "リーダーを選んだ",
    "use": "効果を使った", "skip": "効果を使わなかった",
    "choose_count": "枚数を選んだ", "discard": "手札を捨てた",
    "resolve": "スキルの解決順を選んだ", "rush": "連撃した",
    "stop": "連撃をやめた",
}



# 領域の移動をどう言うか（D-063 v4）。
# **同じ「トラッシュに置かれた」でも意味が違う**ので、出どころで書き分ける。
_MOVE_JA = {
    ("concerto", "trash"): "をコストとして支払った（協奏エリア → トラッシュ）",
    ("action_area", "trash"): "が使い終わってトラッシュへ（アクションエリア → トラッシュ）",
    ("hand", "trash"): "を手札から捨てた（→ トラッシュ）",
    (None, "trash"): "がトラッシュへ",
    ("hand", "concerto"): "を手札から協奏エリアへ（チャージ）",
    ("action_area", "concerto"): "がアクションエリアから協奏エリアへ",
    (None, "concerto"): "がデッキから協奏エリアへ",
    ("hand", "action_area"): "を手札から場に出した（アクションエリア）",
    ("concerto", "action_area"): "が協奏エリアからアクションエリアへ",
    (None, "action_area"): "がアクションエリアに現れた",
}

# 出どころを探す順番。**協奏エリアを先に見る**（コストの支払いが最も紛れやすい）。
_SOURCES = ("concerto", "action_area", "hand")


def _pool(ob: dict, side: str, zone: str) -> list:
    """観測に写っている領域。相手の手札は写らないので空になる。"""
    v = ob[side].get(zone)
    return list(v) if isinstance(v, list) else []


def card_moves(ob_b: dict, ob_a: dict, side: str) -> list:
    """公開領域に現れたカードを「どこから来たか」つきで返す。

    **情報は足していない。** 出どころは「その apply でどの領域から同じカードが
    減ったか」から引いているだけで、観測に写っているものしか使わない。

    相手の手札は観測に写らないので、`hand_count` の減りぶんを上限として
    「手札から」に割り当てる（枚数は公開情報である）。

    同じ ID の札が複数の出どころから同時に動いたときは、どちらがどちらか
    区別できない。ただし**付く説明の集合は正しい**（1枚がコスト、1枚が使用済み）
    ので、読む上での実害はない。
    """
    left = {z: _zone_added(_pool(ob_a, side, z), _pool(ob_b, side, z))
            for z in _SOURCES}
    # 相手の手札は中身が見えない。減った枚数だけを使う（公開情報）
    hand_budget = None
    if not left["hand"]:
        b = ob_b[side].get("hand_count")
        a = ob_a[side].get("hand_count")
        hand_budget = max(0, (b - a)) if (b is not None and a is not None) else 0

    out = []
    for zone in ("concerto", "action_area", "trash"):
        for cid in _zone_added(_pool(ob_b, side, zone), _pool(ob_a, side, zone)):
            src = None
            for z in _SOURCES:
                if z == zone:
                    continue
                if cid in left[z]:
                    left[z].remove(cid)
                    src = z
                    break
            if src is None and hand_budget:
                src, hand_budget = "hand", hand_budget - 1
            out.append((cid, _MOVE_JA[(src, zone)]))
    return out


def log_lines(ob_b: dict, ob_a: dict, actions: dict, human_seat: int,
              auto: bool) -> list:
    """1回の `apply` で起きたことを日本語にする。

    人間の行動は自分の情報なのでそのまま書ける。AI の行動は動詞だけを書き、
    カード名は**適用後に公開領域へ現れたもの**からのみ拾う（漏洩の防止）。
    """
    out = []
    for pi, a in sorted(actions.items()):
        if pi == human_seat:
            tag = "（自動）" if auto else ""
            out.append(f"あなた: {view.action_label(ob_b, a)}{tag}")
        else:
            out.append(f"CPU: {_AI_VERB.get(a['type'], a['type'])}")

    # 公開領域に現れたカード（相手側）。ここで初めて名前を出す。
    # **どこから来たかを書く**（D-063 v4）。同じ「トラッシュに置かれた」でも、
    # コストとして支払った札と、使い終わった札と、手札から捨てた札は別物である。
    for side, who in (("opp", "CPU"), ("me", "あなた")):
        for cid, text in card_moves(ob_b, ob_a, side):
            out.append(f"  → {who}: {view.action_card(cid)['label']} {text}")

    # ライフの増減
    for side, who in (("me", "あなた"), ("opp", "CPU")):
        d = ob_a[side]["life"] - ob_b[side]["life"]
        if d:
            out.append(f"  → {who} のライフ {ob_b[side]['life']} → "
                       f"{ob_a[side]['life']}（{d:+d}）")

    # 相手の手札を確認した（スキャン等）。**確定情報なので必ずログに残す。**
    # 画面の「判明した手札」欄と同じものだが、いつ判ったのかはログにしか出ない。
    new_known = _zone_added(ob_b["opp"]["hand_known"], ob_a["opp"]["hand_known"])
    if new_known:
        out.append("◇ CPU の手札を確認: "
                   + "、".join(view.action_card(c)["label"] for c in new_known))

    # 対抗の結果（両者の提出は公開されている §6.4(1)-3）
    if ob_a["last_clash_winner"] != ob_b["last_clash_winner"] or \
            ob_a["last_clash_cards"] != ob_b["last_clash_cards"]:
        mine, theirs = ob_a["last_clash_cards"]
        def _c(x):
            if x is None:
                return "（なし）"
            return "パス" if x == "PASS" else view.action_card(x)["label"]
        w = ob_a["last_clash_winner"]
        who = "引き分け" if w is None else ("あなたの勝ち" if w == 0 else "CPU の勝ち")
        out.append(f"◆ 対抗: あなた {_c(mine)} × CPU {_c(theirs)} → {who}")

    # キャラの変化
    for side, who in (("me", "あなた"), ("opp", "CPU")):
        if ob_a[side]["slots"] != ob_b[side]["slots"]:
            lead = ob_a[side]["slots"][0]
            nm = view.chara_card(lead[-1])["label"] if lead else "（空）"
            out.append(f"  → {who} のキャラエリアが変化（リーダー: {nm}）")

    if ob_a["turn_no"] != ob_b["turn_no"]:
        tp = "あなた" if ob_a["turn_player"] == human_seat else "CPU"
        out.append(f"── ターン {ob_a['turn_no']}（{tp} の番）──")
    return out


# ------------------------------------------------------------------ 本体
class Session:
    """1 局ぶんの対局。人間の入力待ちで止まる。"""

    def __init__(self, game_id: str, config, pool: list, seed: int,
                 human_seat: int, opponent_name: str, ai, ai_seed: int,
                 deck_name: str = "SD001", show_ai_thinking: bool = False):
        self.game_id = game_id
        self.config, self.pool, self.seed = config, pool, seed
        self.human_seat = human_seat
        self.opponent_name, self.ai, self.ai_seed = opponent_name, ai, ai_seed
        self.deck_name = deck_name
        self.show_ai_thinking = show_ai_thinking

        self.state = initial_state(config, seed)
        self.actions: list = []          # 記録（§6.1）
        self.log: list = []              # 画面用の日本語ログ
        self.flags: list = []
        self.ply = 0
        self.error: str | None = None    # 例外は握りつぶさず画面に出す（§1.3）
        self._t0 = time.monotonic()
        self.advance()

    # -- 進行 -------------------------------------------------------------
    def _step(self, human_action, auto: bool = False) -> None:
        before = self.state
        need = decision_players(before)
        ob_b = observe(before, self.human_seat)

        acts = {}
        think_ms: dict = {}
        if human_action is not None:
            if self.human_seat not in need:
                raise IllegalMove("あなたの決定を求められていない")
            acts[self.human_seat] = human_action
        # §2.3: 人間の手はまだ適用していない。AI は同じ局面で決める。
        for pi in need:
            if pi in acts:
                continue
            # D-7: 前の対抗の記録を持ち越さない。合法手が 1 つの対抗では探索器が
            # 早く戻り `last_clash` を書かないので、消しておかないと**別の局面の
            # 候補表が別の行に付く**（記録としては嘘になる）。
            if hasattr(self.ai, "last_clash"):
                self.ai.last_clash = None
            # D-117（TE-4）: AI が考えた時間だけを測る。下の `ms` は「前のステップの終わりから」
            # なので、人間の入力を待つステップでは人間の操作時間が混ざる。`ms` の意味は変えない。
            t_ai = time.perf_counter()
            acts[pi] = self.ai.act(before, pi)
            think_ms[pi] = int((time.perf_counter() - t_ai) * 1000)

        # **辞書は必ず席の昇順で組み直してから渡す。**
        # `engine._apply_inner` は `actions.items()` を回すので、
        # **同じ行動でも辞書への挿入順が違うと結果が変わる**（マリガンや
        # デッキ再構成のシャッフルが消費する乱数の順序が入れ替わるため）。
        # 既存の呼び出し側（runner.play_game / arena / ladder）はすべて
        # `{pi: ... for pi in need}` で席の昇順に組んでいる。ここだけ
        # 「人間の手を先に入れる」順で組んでいたため、記録の再生と食い違った。
        # この脆さ自体はエンジン側の課題として別途報告する。
        acts = {pi: acts[pi] for pi in sorted(acts)}
        after = apply(before, acts)
        ob_a = observe(after, self.human_seat)

        now = time.monotonic()
        for pi, a in sorted(acts.items()):
            row = {
                "ply": self.ply, "turn": before.turn_no,
                "phase": before.phase.value,
                "by": "human" if pi == self.human_seat else "ai",
                "seat": pi, "action": a, "auto": bool(auto and pi == self.human_seat),
                "ms": int((now - self._t0) * 1000),
            }
            # D-117（TE-4）: AI の行にだけ、AI 自身の思考時間を足す。**思考時間を集計するならこちらを使う。**
            # 足すのはキー 1 つだけ——再生（`record.replay`）は `action` しか読まないので壊れない。
            if pi in think_ms:
                row["think_ms"] = think_ms[pi]
            # D-7（文献計画 便 D）: AI の**対抗**の行にだけ、見比べた候補と点数を足す。
            # 便 F（相手の型）で「AI が何を迷って何を選んだか」と「マスターが実際に
            # 何を出したか」を突き合わせる材料になる。
            # **足すのはキー 1 つだけ**——`action` と行の並びは触らないので、
            # 記録の再生（`webapp.record.replay`）は `action` しか読まず壊れない。
            # 人間の行には付けない（AI の内心であって、人間の手の情報ではない）。
            if (row["by"] == "ai" and before.phase == Phase.CLASH_SUBMIT
                    and getattr(self.ai, "last_clash", None) is not None):
                row["ai_clash"] = self.ai.last_clash
            self.actions.append(row)
            self.ply += 1
        self._t0 = now
        self.log += log_lines(ob_b, ob_a, acts, self.human_seat, auto)
        self.state = after

    def advance(self) -> None:
        """人間の入力が必要になるまで進める。

        合法手が 1 つしかない場面は自動で通す（§4.2「意味のない操作を減らす」）。
        自動で通したことはログと記録に残す。
        """
        guard = 0
        try:
            while self.state.outcome is None:
                guard += 1
                if guard > 20000:
                    raise RuntimeError("進行が止まらない（エンジンの異常）")
                if self.state.turn_no > MAX_TURNS:
                    raise RuntimeError(f"ターン数が {MAX_TURNS} を超えた（異常）")
                need = decision_players(self.state)
                if not need:
                    raise RuntimeError("決定者がいないのに未決着（エンジンの異常）")
                if self.human_seat in need:
                    acts = legal_actions(self.state, self.human_seat)
                    if not acts:
                        raise RuntimeError("あなたに合法手が無い（エンジンの異常）")
                    if len(acts) != 1:
                        return
                    self._step(acts[0], auto=True)
                else:
                    self._step(None)
        except Exception as e:               # 握りつぶさない（§1.3）
            self.error = f"{type(e).__name__}: {e}"
            self.log.append(f"■ 異常が発生しました: {self.error}")

    # -- 人間の入力 -------------------------------------------------------
    def legal(self) -> list:
        """人間の合法手。**並び順をここで決め、画面も適用も必ずこれを通す。**"""
        if self.finished or self.error:
            return []
        need = decision_players(self.state)
        if self.human_seat not in need:
            return []
        acts = legal_actions(self.state, self.human_seat)
        return [a for _, a in sorted(enumerate(acts), key=_sort_key)]

    def play(self, index: int, expected_ply: int) -> None:
        """合法手一覧の添字で受け取る。**添字なので不正な手を送れない。**

        `expected_ply` は画面が古くないことの確認（二重送信よけ）。
        """
        if self.error:
            raise IllegalMove("異常発生後は続行できない")
        if expected_ply != self.ply:
            raise StaleView(f"画面が古い（期待 {expected_ply} / 現在 {self.ply}）")
        acts = self.legal()
        if not acts:
            raise IllegalMove("いまは入力を求めていない")
        if not (0 <= index < len(acts)):
            raise IllegalMove(f"合法手の範囲外: {index}（0..{len(acts) - 1}）")
        try:
            self._step(acts[index])
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.log.append(f"■ 異常が発生しました: {self.error}")
            return
        self.advance()

    def flag(self, note: str = "") -> dict:
        """「気になる」印。対局中は 1 クリックで終わらせる（§4.4）。"""
        f = {"ply": max(0, self.ply - 1), "turn": self.state.turn_no,
             "target": "ai", "when": "live", "note": note}
        self.flags.append(f)
        self.log.append(f"★ 直前の手に印を付けた（ply {f['ply']}）")
        return f

    def resign(self) -> None:
        if not self.finished:
            self.log.append("あなたは投了した")
            self._resigned = True

    # -- 状態 -------------------------------------------------------------
    _resigned = False

    @property
    def finished(self) -> bool:
        return (self.state.outcome is not None or self._resigned
                or self.error is not None)

    def result(self) -> dict | None:
        if not self.finished:
            return None
        if self._resigned:
            return {"winner": "ai", "reason": "resign", "turns": self.state.turn_no,
                    "life": [self.state.players[0].life, self.state.players[1].life],
                    "aborted": False, "draw": False}
        if self.error:
            return {"winner": None, "reason": "error", "error": self.error,
                    "turns": self.state.turn_no,
                    "life": [self.state.players[0].life, self.state.players[1].life],
                    "aborted": True, "draw": False}
        o = self.state.outcome
        return {
            "winner": None if o == DRAW else ("human" if o == self.human_seat else "ai"),
            "reason": "normal", "turns": self.state.turn_no,
            "life": [self.state.players[0].life, self.state.players[1].life],
            "aborted": False, "draw": o == DRAW,
        }

    def snapshot(self) -> dict:
        """画面に送るもの一式。**対局中は observe だけから作る（§2.2）。**"""
        ob = observe(self.state, self.human_seat)
        acts = self.legal()
        return {
            "game_id": self.game_id, "ply": self.ply, "seed": self.seed,
            "human_seat": self.human_seat, "opponent": self.opponent_name,
            "deck": self.deck_name,
            "board": view.board(ob),
            "choice_reason": view.choice_reason(ob),
            # `action` は**人間自身の合法手**なので、そのまま画面へ渡してよい
            # （隠蔽情報は入りようがない）。マリガンの「1枚ずつ選ぶ」画面が、
            # 選んだ組み合わせに対応する添字を引くために使う（§4.2）。
            "legal": [{"index": i, "label": view.action_label(ob, a),
                       "type": a["type"], "action": a}
                      for i, a in enumerate(acts)],
            "your_turn": bool(acts),
            "log": self.log[-60:],
            "flags": len(self.flags),
            "finished": self.finished,
            "result": self.result(),
            "error": self.error,
        }
