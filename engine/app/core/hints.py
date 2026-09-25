"""「できない理由」（要件 R-PLAY-4）。文言はサーバが作り、画面は表示するだけである。

**理由は説明であって、判定ではない。**何ができるかを決めるのは合法手だけで、ここは
「合法手に無い所作」に後から言葉を添える。だから理由が外れても対局は壊れない。

作り方の決まり:

- 合法手に**ある**所作には理由を付けない（`None`）
- 公開の旗（このターンに使い終えた行動・継続効果）とエンジンの関数（実効コスト）から言えることだけを言う。
  言い切れないときは当たり障りのない文に落とす。**エンジンの判定を写さない**
- 本人の手札についての理由は本人にしか送らない（`Game.view` が席の視点にだけ入れる）
"""
from __future__ import annotations

from typing import Optional

from meicho import ACTION_CARDS
from meicho import engine as _eng
from meicho.state import Phase

from . import describe


def _cost_reason(s, pi: int, cid: str) -> str:
    try:
        need = _eng._effective_cost(s, pi, ACTION_CARDS[cid])
        have = len(s.players[pi].concerto)
    except Exception:
        return "このカードはいま使えない"
    if need > have:
        return f"協奏が足りない（コスト {need}・協奏 {have} 枚）"
    return "このカードは使用条件を満たしていない"


def make(s, pi: int, awaiting: list, held: dict, legal: list) -> dict:
    """席 pi 宛の理由の表。キー: general／charge／switch／levelup／hand（添字→理由）／prompt。"""
    types = {a["type"] for a in legal}
    hand = s.players[pi].hand
    out = {"general": None, "charge": None, "switch": None, "levelup": None, "hand": {}, "prompt": ""}

    if s.outcome is not None:
        out["general"] = "対局は終わっている"
        return out
    if pi not in awaiting:
        if s.phase == Phase.CLASH_SUBMIT and pi in held:
            out["general"] = "置き終えた。相手が置くのを待っている"
        elif s.phase == Phase.CLASH_SUBMIT:
            out["general"] = "ターンプレイヤーが先に置く。置かれるまで待つ"
        else:
            out["general"] = "いまは相手の入力を待っている"
        return out

    ph = s.phase
    if ph == Phase.ACTION:
        if "charge" not in types:
            out["charge"] = "このターンはもうチャージした" if s.used_charge else "チャージできる手札が無い"
        if "switch" not in types:
            if s.used_switch:
                out["switch"] = "このターンはもうリーダーを切り替えた"
            elif s.leader_switch_forbidden[pi]:
                out["switch"] = "効果で、リーダーの切り替えを禁じられている"
            else:
                out["switch"] = "切り替えられるバックがいない"
        if "levelup" not in types:
            out["levelup"] = ("このターンはもうレベルアップした" if s.used_levelup
                              else "レベルアップできるキャラカードが無い（重ねられるカードか、捨てる手札が足りない）")
        out["general"] = "アクションフェイズでは、チャージ・レベルアップ・リーダーの切り替えができる"
    elif ph == Phase.CLASH_SUBMIT:
        ok = {a["hand"] for a in legal if a["type"] == "submit"}
        for i, cid in enumerate(hand):
            if i not in ok:
                out["hand"][i] = _cost_reason(s, pi, cid)
        out["general"] = "手札から 1 枚をアクションエリアに置く"
    elif ph == Phase.RUSH:
        ok = {a["hand"] for a in legal if a["type"] == "rush"}
        for i, cid in enumerate(hand):
            if i in ok:
                continue
            if s.rush_forbidden[pi]:
                out["hand"][i] = "効果で、連撃を禁じられている"
            elif s.rush_allowance <= 0:
                out["hand"][i] = "連撃できる回数を使い切った"
            elif str(getattr(ACTION_CARDS[cid].color, "value", "")) != "red":
                out["hand"][i] = "連撃に使えるのは赤のカード"
            else:
                out["hand"][i] = _cost_reason(s, pi, cid)
        out["general"] = "連撃するか、連撃を終える"
    elif ph == Phase.CHOICE:
        out["prompt"] = describe.prompt(s, pi)
        out["general"] = "先に、出ている選択に答える" + (f"（{out['prompt']}）" if out["prompt"] else "")
    elif ph == Phase.TURN_END_DISCARD:
        out["prompt"] = "手札の上限を超えている。捨てる手札を選ぶ"
        out["general"] = "先に、捨てる手札を選ぶ"
    elif ph == Phase.SETUP_CHARA:
        out["general"] = "Lv.0 のキャラ 3 枚を、リーダーとバックに置く"
    elif ph == Phase.MULLIGAN:
        out["general"] = "戻したい手札に印を付けて、引き直す"
    return out


def for_spectator() -> dict:
    return {"general": "観戦中は操作できない", "charge": None, "switch": None, "levelup": None,
            "hand": {}, "prompt": ""}
