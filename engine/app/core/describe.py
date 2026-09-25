"""表示用の言い換え（要件 R-PLAY-7・R-PLAY-11・R-ASSET-2／4）。**ここはルールを持たない。**

カードの表示データと合法手の日本語ラベルを作る。言い換えの本体は現行 `webapp/view.py`
（エンジンの持ち場）にあり、**写さずに import して使う**（APP-002。写した側が取り残される罠を避ける）。
`webapp` が無い環境でも落ちないよう、無ければ素っ気ない表示に落とす。

**公式のカードテキストは含まない**（要件 R-ASSET-1）。`skills` はエンジンのオペコードの言い換え文である。
"""
from __future__ import annotations

from functools import lru_cache

from meicho import ACTION_CARDS, CHARA_CARDS, observe

try:                                    # エンジンの持ち場のモジュール。読むだけ
    from webapp import view as _wv
except Exception:                       # pragma: no cover - webapp が無い配布形態に備える
    _wv = None

COLOR_KEY = {"red": "red", "green": "green", "blue": "blue"}


def _color(c) -> str:
    v = getattr(c, "value", c)
    return v if isinstance(v, str) else str(v)


def _skills(card) -> list:
    if _wv is None:
        return []
    out = []
    for sk in card.skills:
        try:
            out.append(_wv.skill_text(sk))
        except Exception:               # 新しいオペコードに言い換えが追いついていない
            out.append("（このスキルの説明は準備中）")
    return out


@lru_cache(maxsize=1)
def card_db() -> dict:
    """全カードの表示データ。番号・名前・色・数値・言い換え文だけ（要件 R-ASSET-2）。"""
    db = {}
    for cid, c in ACTION_CARDS.items():
        db[cid] = {"kind": "action", "name": c.name, "color": _color(c.color), "cost": c.cost,
                   "speed": c.speed, "damage": c.damage, "tags": list(c.tags),
                   "dedicated_to": c.dedicated_to, "leader_skill": bool(c.leader_skill),
                   "skills": _skills(c), "unverified": bool(c.unverified_fields)}
    for cid, c in CHARA_CARDS.items():
        db[cid] = {"kind": "chara", "name": c.name, "level": c.level, "tags": list(c.tags),
                   "skills": _skills(c)}
    return db


def labels(s, pi: int, legal: list) -> list:
    """合法手の日本語ラベル（安全網の一覧用・要件 R-PLAY-11）。席 pi の観測だけから作る。"""
    if not legal:
        return []
    if _wv is None:
        return [str(a) for a in legal]
    ob = observe(s, pi)
    out = []
    for a in legal:
        try:
            out.append(_wv.action_label(ob, a))
        except Exception:
            out.append(str(a))
    return out


def prompt(s, pi: int) -> str:
    """いま何を選ばされているのかの一文（席 pi 宛の選択があるときだけ）。"""
    if _wv is None:
        return ""
    try:
        return _wv.choice_reason(observe(s, pi))
    except Exception:
        return ""
