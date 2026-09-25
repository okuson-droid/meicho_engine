import json
import random
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[2]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from meicho import ACTION_CARDS, CHARA_CARDS  # noqa: E402


def load_deck(name: str) -> dict:
    with open(ENGINE / "decklists" / f"{name}.json", encoding="utf-8") as f:
        d = json.load(f)
    return {"name": d["name"], "chara_deck": d["chara_deck"], "action_deck": d["action_deck"]}


def random_deck(rnd: random.Random) -> dict:
    """カードプール全体から、構築ルール（rules §3.1・§3.2）を満たすデッキを無作為に組む。

    カードが増えても書き換えなくてよいように、カード番号を直書きしない（要件 R-EXT-12）。
    """
    by_name: dict = {}
    for cid, c in sorted(CHARA_CARDS.items()):
        by_name.setdefault(c.name, []).append(cid)
    ok_names = sorted(n for n, ids in by_name.items()
                      if any(CHARA_CARDS[i].level == 0 for i in ids))
    names = rnd.sample(ok_names, 3)
    chara = []
    for n in names:
        lv0 = [i for i in by_name[n] if CHARA_CARDS[i].level == 0]
        rest = [i for i in by_name[n] if CHARA_CARDS[i].level != 0]
        rnd.shuffle(rest)
        chara += [rnd.choice(lv0)] + rest[:4]
    pool = [cid for cid, c in sorted(ACTION_CARDS.items())
            if c.dedicated_to is None or c.dedicated_to in names]
    action: list = []
    while len(action) < 40:
        cid = rnd.choice(pool)
        if action.count(cid) < 3:
            action.append(cid)
    return {"name": "random", "chara_deck": chara, "action_deck": action}


@pytest.fixture(scope="session")
def sd001():
    return load_deck("SD001")


@pytest.fixture(scope="session")
def sd02():
    return load_deck("SD02")
