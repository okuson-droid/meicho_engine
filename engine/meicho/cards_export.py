"""カード登録簿を JSON に書き出す（Rust 版エンジンへの受け渡し・D-049）。

真実源は `cards.py` のままである。Rust 版は起動時にこの JSON を受け取って
カード表を組み立てる。ファイルには書かず、`cards_json()` の戻り値をそのまま渡す。
`tests/test_rust_engine.py` が「書き出し → Rust で読み戻し → 同じ内容」を固定する。
"""
from __future__ import annotations

import json

from .cards import ACTION_CARDS, CHARA_CARDS, Skill


def _skill(sk: Skill) -> dict:
    cond = None
    if sk.condition is not None:
        cond = {}
        for k, v in sk.condition.items():
            # Color は str Enum なので value を書く。bool/int/str はそのまま。
            cond[k] = getattr(v, "value", v)
    return {
        "timing": sk.timing.value,
        "effect": [[op, dict(prm)] for op, prm in sk.effect],
        "condition": cond,
        "leader_only": bool(sk.leader_only),
        "optional": bool(sk.optional),
    }


def cards_dict() -> dict:
    chara = [{
        "card_id": c.card_id, "name": c.name, "level": c.level,
        "tags": list(c.tags), "skills": [_skill(s) for s in c.skills],
    } for c in CHARA_CARDS.values()]
    action = [{
        "card_id": c.card_id, "name": c.name, "color": c.color.value,
        "cost": c.cost, "speed": c.speed, "damage": c.damage,
        "tags": list(c.tags), "skills": [_skill(s) for s in c.skills],
        "dedicated_to": c.dedicated_to, "leader_skill": bool(c.leader_skill),
    } for c in ACTION_CARDS.values()]
    return {"chara": chara, "action": action}


def cards_json() -> str:
    return json.dumps(cards_dict(), ensure_ascii=False)
