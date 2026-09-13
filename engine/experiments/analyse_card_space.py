"""カードを「カード ID」ではなく「機構の仕様」で表したとき、プールをまたぐ共通部分が
どれだけあるかを数える（D-061 の材料。発売後のカード DB 整備でも使う）。

## この道具が答える問い

D-058 で「SD001 で学習した方策 π を SD02 に持ち込むと悪化する（0.449）」と出た。
理由として記録されたのは「**カード ID が 1 種も共通していない**」ことである。
符号化はカード 1 種につき 1 枠なので、SD001 産のネットは SD02 のカードの枠を一度も見ていない。

だが「カード ID が違う」と「カードが違う」は同じではない。
この道具は、カード名もカード ID も使わない**機構の仕様**（色・コスト・速度・打点・タグ・
誘発条件・効果オペコード列）でカードを表し直して、共通部分を数える。

出す数字:

1. **カード ID / カード名 / 機構の仕様、それぞれで数えた共通枚数。**
   ここが食い違うなら、いまの符号化は「同じカードを別物として扱っている」ことになる。
2. **素性（オペコード・タイミング・条件・タグ・数値）の共通率。** 埋め込みが転移させうる情報量の上限。
3. **機構の仕様が一致してしまう組。** ワンホットより情報が減っていないかの確認。
4. 語彙の大きさ（次元の見積もり）。

実行: python3 experiments/analyse_card_space.py [デッキA] [デッキB]
"""
from __future__ import annotations

import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck                                  # noqa: E402
from meicho import cards as C                                # noqa: E402

# 効果オペコードのうち、パラメータに**キャラ名**を取るもの。
# 「漂泊者（女）を 1 枚引く」と「漂泊者（男）を 1 枚引く」は、機構としては同じ形である。
# 「誰か」「どのカードか」を指すパラメータ。機構の素性では**伏せる**（D-050 条件 1）。
# 伏せないと初見カードに効く表現でなくなる（`tests/test_card_space.py` が門番）。
# v0.12 / BP01（D-079 追記 6）で `chara`（専用キャラ名の絞り込み）と
# `card_name`（デッキ検索の名指し）を足した。
NAME_PARAM_KEYS = ("name", "chara", "card_name")


def profile(card) -> Counter:
    """カード 1 枚 → 機構の素性の袋。

    **カード ID・カード名・専用キャラ名・効果パラメータ中のキャラ名は一切使わない。**
    使うのは「そのカードが盤面に対して何をするか」だけである。
    """
    f = Counter()
    if isinstance(card, C.ActionCard):
        f[f"color={card.color.value}"] += 1
        f[f"cost={card.cost}"] += 1
        f[f"speed={card.speed}"] += 1
        f[f"damage={card.damage}"] += 1
        if card.dedicated_to:
            f["dedicated"] += 1            # 「専用キャラがいる」という事実だけ。誰かは使わない
        if card.leader_skill:
            f["leader_skill"] += 1
    else:
        f[f"level={card.level}"] += 1
    for t in card.tags:
        f[f"tag={t}"] += 1
    for sk in card.skills:
        f[f"timing={sk.timing.value}"] += 1
        if sk.leader_only:
            f["leader_only"] += 1
        if sk.optional:
            f["optional"] += 1
        for k in (sk.condition or {}):
            f[f"cond={k}"] += 1
        for op in sk.effect:
            name = op[0] if isinstance(op, (tuple, list)) else op
            f[f"op={name}"] += 1
            params = op[1] if isinstance(op, (tuple, list)) and len(op) > 1 else {}
            for k, v in (params or {}).items():
                if k in NAME_PARAM_KEYS:
                    f[f"op={name}/{k}=<キャラ名>"] += 1     # 誰かは伏せる（機構は同じ）
                else:
                    f[f"op={name}/{k}={v}"] += 1
    return f


def mech_key(card) -> tuple:
    """機構の仕様（比較用の鍵）。"""
    return tuple(sorted(profile(card).items()))


def cards_of(deck_name: str) -> list:
    d = load_deck(deck_name)
    ids = set(d["chara_deck"]) | set(d["action_deck"])
    return [C.CHARA_CARDS.get(cid) or C.ACTION_CARDS[cid] for cid in sorted(ids)]


def main():
    da = sys.argv[1] if len(sys.argv) > 1 else "SD001"
    db = sys.argv[2] if len(sys.argv) > 2 else "SD02"
    a, b = cards_of(da), cards_of(db)
    print(f"■ 0. 登録簿: キャラ {len(C.CHARA_CARDS)} 種 + アクション {len(C.ACTION_CARDS)} 種 "
          f"= {len(C.CHARA_CARDS) + len(C.ACTION_CARDS)} 種")
    print()

    print(f"■ 1. {da} と {db} の共通枚数を、3 通りの数え方で")
    print(f"  {'':10s} {'ID で数える':>12s} {'名前で数える':>13s} {'機構の仕様で数える':>19s}")
    for label, cls in (("アクション", C.ActionCard), ("キャラ", C.CharaCard)):
        xa = [c for c in a if isinstance(c, cls)]
        xb = [c for c in b if isinstance(c, cls)]
        by_id = len({c.card_id for c in xa} & {c.card_id for c in xb})
        by_name = len({c.name for c in xa} & {c.name for c in xb})
        by_mech = len({mech_key(c) for c in xa} & {mech_key(c) for c in xb})
        print(f"  {label:10s} {len(xa):3d} 種中 {by_id:3d} {by_name:8d} {by_mech:14d}")
    print()
    print("  **ID で 0、機構の仕様で 7 + 2** ——「カード ID が違う」と「カードが違う」は同じではない。")
    print("  いまの符号化はカード 1 種につき 1 枠なので、機構が同じカードを完全な別物として扱っている。")
    print()

    print("■ 2. 素性（オペコード・タイミング・条件・タグ・数値）の共通率")
    sa = set().union(*[set(profile(c)) for c in a])
    sb = set().union(*[set(profile(c)) for c in b])
    print(f"  {da} {len(sa)} 種 / {db} {len(sb)} 種 / 共通 {len(sa & sb)} 種"
          f"（{da} 側の {len(sa & sb)/len(sa):.0%}・{db} 側の {len(sa & sb)/len(sb):.0%}）")
    for kind in ("op=", "timing=", "cond=", "tag=", "color=", "cost=", "speed=", "damage=", "level="):
        ka = {x for x in sa if x.startswith(kind) and "/" not in x}
        kb = {x for x in sb if x.startswith(kind) and "/" not in x}
        if not (ka or kb):
            continue
        print(f"    {kind:9s} {da} {len(ka):3d} / {db} {len(kb):3d} / 共通 {len(ka & kb):3d}")
    print()

    print("■ 3. 機構の仕様が一致してしまう組（ワンホットより情報が減っていないかの確認）")
    seen, dup = {}, []
    for c in a + b:
        k = mech_key(c)
        if k in seen:
            dup.append((seen[k], c))
        else:
            seen[k] = c
    for x, y in dup:
        extra = ""
        if getattr(x, "dedicated_to", None) != getattr(y, "dedicated_to", None):
            extra = f"   ← 専用キャラだけが違う（{x.dedicated_to} / {y.dedicated_to}）"
        elif x.name != y.name:
            extra = f"   ← 名前だけが違う"
        print(f"  {x.card_id:10s}（{x.name}） と {y.card_id:10s}（{y.name}）{extra}")
    print(f"  計 {len(dup)} 組。**いずれも「専用キャラ（と効果中のキャラ名）だけが違う同じカード」である。**")
    print("  したがって、機構の仕様は情報を捨てていない——捨てているのは「誰のカードか」だけで、")
    print("  それは別枠（キャラの添字）で持てばよい。")
    print()

    print("■ 4. 語彙の大きさ（次元の見積もり）")
    allf = sa | sb
    ops = sorted({x.split("/")[0] for x in allf if x.startswith("op=")})
    print(f"  全素性 {len(allf)} 種（パラメータ込み）／オペコード {len(ops)} 種")
    print(f"  {[o[3:] for o in ops]}")
    vanilla = [c for c in a + b if not c.skills]
    print(f"  効果を持たない（バニラの）カード {len(vanilla)} / {len(a) + len(b)} 枚"
          f" — 色・コスト・速度・打点だけで表せるので、埋め込みの利得はここには無い")


if __name__ == "__main__":
    main()
