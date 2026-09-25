"""CPU 対戦の相手（要件 R-CPU-1〜8・APP-005）。**AI の中身はここに書かない。**

相手は必ずエンジンの持ち場の登録簿（`webapp/agents.py` → `experiments/registry.py`）を通して作る（要件 R-EXT-1）。
ここが持つのは「デッキごとに、どの登録名を やさしい／ふつう／つよい に割り当てるか」の表だけである。
AI が交代しても、この表の登録名を差し替えるだけで済む。SD001 の「つよい」は登録簿の既定の相手（＝現 champion）を指すので、
champion が交代すれば自動で付いてくる。

v1 は同じ固定デッキどうし（ミラー）だけである。現 champion は相手のデッキリストを知っていることに寄りかかる（`endgame_enum`）ので、
人と AI が違うデッキで打つ形は v1 の後になる（D-108 追記 1）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .protocol import AppError

ENGINE_DIR = Path(__file__).resolve().parents[2]
LEVEL_JA = ("やさしい", "ふつう", "つよい")
CHAMPION = "@champion"                  # 登録簿の既定の相手（そのデッキの champion）を指す印

# デッキ → [やさしい, ふつう, つよい] の登録名。根拠は APP-005 追記 1（SD02 は D-112 の測定で 3 段とも区間が離れている）
TIERS = {
    "SD001": ("heuristic", "planner_lh", CHAMPION),
    "SD02": ("heuristic", "greedy", "planner_lh"),
}


def _agents():
    try:
        from webapp import agents            # エンジンの持ち場のモジュール。読むだけ
        return agents
    except Exception as e:                   # 登録簿や学習済みモデルが無い配布形態
        raise AppError("cpu_unavailable", f"CPU 対戦の相手を読み込めない: {e}") from None


def resolve(deck_name: str, level: int) -> str:
    """そのデッキ・その段の登録名。champion が使えない環境では、1 つ下の段に落とす。"""
    if deck_name not in TIERS or level not in (0, 1, 2) or isinstance(level, bool):
        raise AppError("bad_message", "デッキか強さの指定が違う")
    agents = _agents()
    ok = agents.available(deck_name)
    name = TIERS[deck_name][level]
    if name == CHAMPION:
        name = agents.default_for(deck_name)
    if name not in ok:
        lower = [n for n in TIERS[deck_name][:level] if n in ok]
        if not lower:
            raise AppError("cpu_unavailable", f"{deck_name} で使える相手がいない")
        name = lower[-1]
    return name


def options() -> dict:
    """画面に出す選択肢。使えないデッキは出さない。"""
    out = {}
    for deck in TIERS:
        if not (ENGINE_DIR / "decklists" / f"{deck}.json").exists():
            continue
        try:
            out[deck] = [{"level": lv, "label": LEVEL_JA[lv], "agent": resolve(deck, lv)} for lv in (0, 1, 2)]
        except AppError:
            continue
    return out


def load_deck(deck_name: str) -> dict:
    if deck_name not in TIERS:
        raise AppError("bad_message", "デッキの指定が違う")
    with open(ENGINE_DIR / "decklists" / f"{deck_name}.json", encoding="utf-8") as f:
        d = json.load(f)
    return {"name": deck_name, "chara_deck": list(d["chara_deck"]), "action_deck": list(d["action_deck"])}


def build(agent_name: str, deck: dict, ai_seed: int):
    """相手を 1 体作る。先読みする相手には、相手（＝人間）のデッキとして同じデッキを渡す（ミラー）。"""
    return _agents().build(agent_name, list(deck["action_deck"]), ai_seed, deck_name=deck["name"])
