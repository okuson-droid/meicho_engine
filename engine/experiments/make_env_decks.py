#!/usr/bin/env python3
"""環境デッキ群 24 種の生成器（D-128）。出力は `decklists/env/`。

    python3 experiments/make_env_decks.py                 # decklists/env/ に 24 個書く
    python3 experiments/make_env_decks.py --out /tmp/env  # 別の場所に書く
    python3 experiments/make_env_decks.py --report        # 書かずに内訳だけ出す

マスターが 2026-09-24 に出した構築規則をそのまま実装する。検査は `tests/test_env_decks.py`。

R-1 3 グループから 1 人ずつ選ぶ。GA（役割 1）= 秧秧・散華／GB（役割 2）= 漂泊者（男）・
    漂泊者（女）・ショアキーパー／GC（アタッカー）= アンコ・ツバキ・今汐・熾霞。2×3×4 = 24 通り
R-2 色の枚数は 緑 6〜9・青 9〜11・赤 20 以上（合計 40）
R-3 ＜音骸＞タグのカードを入れない（共通カード 10 枚はすべて＜音骸＞なので、結果として全部が専用札になる）
R-4 【重撃】はアンコのカードだけ・【通常攻撃】はツバキのカードだけ
R-5 GC の赤を他の 2 人より多く入れる
R-6 キャラカードは入れられるものを全部入れる（登録簿にある 3 人分＝いまは 15 枚）

## 決め方（規則の隙間を埋める部分。乱数は使わない）

マスターの規則は枚数の範囲しか決めないので、範囲の中の 1 点を次の規則で選ぶ。
**全デッキに同じ規則を当てる**ので、デッキ間の違いはカードプールの違いだけになり、
類似度（D-126）でグループを見るときに規則そのものが交絡しない。

- 1 種あたりの上限（`copy_cap`）: コスト 0〜1 は 3 枚・コスト 2 以上は 2 枚。
  §3.2 の 3 枚上限の内側に、重いカードを積み過ぎない線を引く
- 緑: 目標 8 枚。ただし 6 以上・9 以下・プールの上限以下に丸める。GB → GA → GC の順に詰める
  （緑の主は GB。散華は緑を 1 枚も持たないので、散華＋非・今汐の 8 通りだけは上限どおり 6 枚になる）
- 青: 10 枚固定（GA 4・GB 3・GC 3）。GA は青を 2 種持つので 2 枚ずつ
- 赤: 残り（22 枚か 24 枚）。GC に min(上限, 12) を先に割り当て、残りを GB → GA に半分ずつ
  （端数は GA）。GB の上限（ショアキーパーは赤 2 種＝6 枚）で頭打ちになったぶんは GA に回る
- 1 人の中での配り方: 許されたカードを (コスト, 番号) の順に並べ、上限に当たるまで
  **1 枚ずつ順に回して**配る。こうすると使える種類は必ず 1 枚以上入り、
  端数はコストの軽い側に乗る

`--report` で 1 デッキ 1 行の内訳を出す。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from meicho.cards import ACTION_CARDS, CHARA_CARDS, ONKAI_TAG          # noqa: E402

VERSION = "env-1"          # 規則の版。変えたら上げる

# 符丁 → キャラ名。ファイル名を ASCII だけにするため（D-101）
CODE = {
    "YANG": "秧秧", "SANGE": "散華",
    "RM": "漂泊者（男）", "RF": "漂泊者（女）", "SK": "ショアキーパー",
    "ANKO": "アンコ", "TSUBAKI": "ツバキ", "JINSHI": "今汐", "CHIXIA": "熾霞",
}
GA_CODES = ("YANG", "SANGE")
GB_CODES = ("RM", "RF", "SK")
GC_CODES = ("ANKO", "TSUBAKI", "JINSHI", "CHIXIA")

GREEN_TARGET = 8
BLUE_PLAN = {"GA": 4, "GB": 3, "GC": 3}        # 合計 10
GC_RED_TARGET = 12
TOTAL = 40


def copy_cap(card) -> int:
    """1 種あたりの上限（§3.2 の 3 枚の内側）。"""
    return 3 if card.cost <= 1 else 2


def allowed(name: str, color: str) -> list:
    """R-3・R-4 を通ったそのキャラの専用札を (コスト, 番号) の順で返す。"""
    out = []
    for cid, c in ACTION_CARDS.items():
        if c.dedicated_to != name or c.color.value != color:
            continue
        if ONKAI_TAG in c.tags:                                  # R-3
            continue
        if "重撃" in c.tags and name != "アンコ":                 # R-4
            continue
        if "通常攻撃" in c.tags and name != "ツバキ":              # R-4
            continue
        out.append(c)
    return sorted(out, key=lambda c: (c.cost, c.card_id))


def cap_of(name: str, color: str) -> int:
    return sum(copy_cap(c) for c in allowed(name, color))


def deal(name: str, color: str, quota: int) -> Counter:
    """1 枚ずつ順に回して配る。種類が足りなければ例外。"""
    kinds = allowed(name, color)
    got = Counter()
    left = quota
    while left > 0:
        moved = False
        for c in kinds:
            if left == 0:
                break
            if got[c.card_id] < copy_cap(c):
                got[c.card_id] += 1
                left -= 1
                moved = True
        if not moved:
            raise ValueError(f"{name} の{color}が足りない: {quota} 枚ほしいが上限 {cap_of(name, color)} 枚")
    return got


def plan(ga: str, gb: str, gc: str) -> dict:
    """3 人（キャラ名）から、役割 → 色 → 枚数 の割り当てを決める。"""
    role = {"GA": ga, "GB": gb, "GC": gc}

    # 緑
    g_cap = {r: cap_of(n, "green") for r, n in role.items()}
    total_green = min(max(GREEN_TARGET, 6), 9, sum(g_cap.values()))
    if total_green < 6:
        raise ValueError(f"緑が 6 枚に届かない: {role} 上限 {g_cap}")
    green, left = {}, total_green
    for r in ("GB", "GA", "GC"):
        green[r] = min(g_cap[r], left)
        left -= green[r]

    # 青
    blue = dict(BLUE_PLAN)
    for r, n in role.items():
        if cap_of(n, "blue") < blue[r]:
            raise ValueError(f"{n} の青が足りない: {blue[r]} 枚ほしいが上限 {cap_of(n, 'blue')} 枚")

    # 赤
    r_cap = {r: cap_of(n, "red") for r, n in role.items()}
    total_red = TOTAL - total_green - sum(blue.values())
    red = {"GC": min(r_cap["GC"], GC_RED_TARGET)}
    rest = total_red - red["GC"]
    red["GB"] = min(r_cap["GB"], rest // 2)
    red["GA"] = rest - red["GB"]
    if red["GA"] > r_cap["GA"]:
        raise ValueError(f"赤が足りない: {role} 必要 {red} 上限 {r_cap}")
    if not (red["GC"] > red["GA"] and red["GC"] > red["GB"]):      # R-5
        raise ValueError(f"アタッカーの赤が多くならない: {role} {red}")
    return {"role": role, "green": green, "blue": blue, "red": red}


def build(ga_code: str, gb_code: str, gc_code: str) -> dict:
    ga, gb, gc = CODE[ga_code], CODE[gb_code], CODE[gc_code]
    p = plan(ga, gb, gc)
    trio = [ga, gb, gc]

    # R-6: 登録簿にあるその 3 人のキャラカードを全部（Lv.0 → Lv.1 → Lv.2 の順）
    chara = []
    for n in trio:
        chara += [cid for cid, c in sorted(CHARA_CARDS.items(), key=lambda kv: (kv[1].level, kv[0]))
                  if c.name == n]

    action = []
    for r, n in (("GA", ga), ("GB", gb), ("GC", gc)):
        for color in ("green", "blue", "red"):
            got = deal(n, color, p[color][r])
            for cid in sorted(got, key=lambda c: (ACTION_CARDS[c].cost, c)):
                action += [cid] * got[cid]
    assert len(action) == TOTAL, (ga_code, gb_code, gc_code, len(action))

    name = f"ENV_{ga_code}_{gb_code}_{gc_code}"
    colors = Counter(ACTION_CARDS[c].color.value for c in action)
    return {
        "name": name,
        "note": (f"環境デッキ群（D-128・規則 {VERSION}）。マスターの構築規則 R-1〜R-6 による自動生成。"
                 f"生成器 experiments/make_env_decks.py。"
                 f"3 人組は GA={ga}／GB={gb}／GC={gc}（アタッカー）。"
                 f"色は 緑 {colors['green']}・青 {colors['blue']}・赤 {colors['red']}。"
                 f"音骸なし・重撃はアンコのみ・通常攻撃はツバキのみ。"),
        "rules_version": VERSION,
        "groups": {"GA": ga_code, "GB": gb_code, "GC": gc_code},
        "chara_deck": chara,
        "action_deck": action,
    }


def all_decks() -> list:
    return [build(a, b, c) for a in GA_CODES for b in GB_CODES for c in GC_CODES]


def build_all(out_dir: str) -> list:
    os.makedirs(out_dir, exist_ok=True)
    decks = all_decks()
    for d in decks:
        with open(os.path.join(out_dir, f"{d['name']}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
            f.write("\n")
    return decks


def report(decks: list) -> str:
    lines = []
    for d in decks:
        col = Counter(ACTION_CARDS[c].color.value for c in d["action_deck"])
        red = Counter(ACTION_CARDS[c].dedicated_to for c in d["action_deck"]
                      if ACTION_CARDS[c].color.value == "red")
        g = d["groups"]
        order = [CODE[g["GA"]], CODE[g["GB"]], CODE[g["GC"]]]
        lines.append(f"{d['name']:26} 緑{col['green']:2} 青{col['blue']:2} 赤{col['red']:2}"
                     f"  赤の内訳 " + "／".join(f"{n} {red[n]}" for n in order)
                     + f"  種類 {len(set(d['action_deck']))}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="環境デッキ群 24 種を作る（D-128）")
    ap.add_argument("--out", default=os.path.join(_HERE, "..", "decklists", "env"))
    ap.add_argument("--report", action="store_true", help="書かずに内訳だけ出す")
    a = ap.parse_args(argv)
    if a.report:
        print(report(all_decks()))
        return
    decks = build_all(a.out)
    print(f"{len(decks)} 個を書いた: {os.path.normpath(a.out)}")
    print(report(decks))


if __name__ == "__main__":
    main()
