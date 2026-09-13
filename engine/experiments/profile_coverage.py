# -*- coding: utf-8 -*-
"""初見カードが「機構の素性」でどれだけ説明できるかを数える（D-086 案 段 G-0）。

対局を 1 局も回さずに、**効果プロファイル射影（DRL_PLAN §3.1）が初見カードに
効く見込みがあるか**を判定するための道具。`analyse_card_space.py` の `profile()`
（カード → 機構の素性の袋。カード ID・名前・キャラ名を一切使わない・D-050 条件 1）
をそのまま使う。

読み方:

- **素性の共通率**が低い ＝ 新しいセットは新しい語彙で書かれている。
  射影しても、初出の素性ぶんは重みが伸びない。
- **1 枚ごとの被覆率**が高い ＝ その枚は既出の語彙でおおむね説明できる。
  いまの符号化（カード ID ごとに 1 枠）だと初見カードの枠は
  **学習で一度も立たない**ので、そこからの改善幅がこの値になる。
- **機構が完全一致する組**が多い ＝ D-061 第 1 段（機構ごとに 1 枠）が効く。
  少なければ、枠をまとめても初見カードは繋がらない。

実行: python3 experiments/profile_coverage.py [既知のセット...] -- [初見のセット...]
既定は「既知 = SD01 SD02 / 初見 = BP01」。
"""
from __future__ import annotations

import os
import statistics
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, ".."), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from analyse_card_space import mech_key, profile          # noqa: E402
from meicho import cards as C                              # noqa: E402


def card_set(card) -> str:
    """カード番号の接頭辞（`SD01-007` → `SD01`）。"""
    return card.card_id.split("-")[0]


def all_cards() -> list:
    return list(C.CHARA_CARDS.values()) + list(C.ACTION_CARDS.values())


def coverage(known_sets, unseen_sets) -> dict:
    cards = all_cards()
    known = [c for c in cards if card_set(c) in known_sets]
    unseen = [c for c in cards if card_set(c) in unseen_sets]
    if not known or not unseen:
        raise SystemExit(f"カードが無い: 既知 {len(known)} 枚 / 初見 {len(unseen)} 枚")

    kf = set().union(*[set(profile(c)) for c in known])
    uf = set().union(*[set(profile(c)) for c in unseen])

    per_card = []
    for c in unseen:
        p: Counter = profile(c)
        tot = sum(p.values())
        hit = sum(n for f, n in p.items() if f in kf)
        per_card.append((c.card_id, hit / tot))
    rates = sorted(r for _, r in per_card)

    by_mech: dict = {}
    for c in cards:
        by_mech.setdefault(mech_key(c), []).append(c.card_id)
    dup = {k: sorted(v) for k, v in by_mech.items() if len(v) > 1}
    bridge = {k: v for k, v in dup.items()
              if {x.split("-")[0] for x in v} & set(unseen_sets)
              and {x.split("-")[0] for x in v} & set(known_sets)}

    return {
        "known_cards": len(known), "unseen_cards": len(unseen),
        "known_feats": len(kf), "unseen_feats": len(uf), "shared_feats": len(uf & kf),
        "per_card": per_card, "rates": rates,
        "dup_groups": dup, "bridge_groups": bridge,
    }


def main() -> None:
    argv = sys.argv[1:]
    if "--" in argv:
        i = argv.index("--")
        known, unseen = argv[:i] or ["SD01", "SD02"], argv[i + 1:] or ["BP01"]
    else:
        known, unseen = ["SD01", "SD02"], ["BP01"]
    r = coverage(set(known), set(unseen))
    rates = r["rates"]
    full = [x for x in r["per_card"] if x[1] == 1.0]
    weak = [x for x in r["per_card"] if x[1] < 0.5]

    print(f"■ 既知 {'+'.join(known)} {r['known_cards']} 枚 / "
          f"初見 {'+'.join(unseen)} {r['unseen_cards']} 枚")
    print(f"■ 素性の種類: 既知 {r['known_feats']} / 初見 {r['unseen_feats']} / "
          f"初見のうち既出 {r['shared_feats']}"
          f"（初見側の {r['shared_feats'] / r['unseen_feats']:.0%}）")
    print()
    print("■ 初見カード 1 枚ごとの被覆率（その枚の素性の延べ回数のうち既出の割合）")
    print(f"  中央値 {statistics.median(rates):.0%} / 最小 {rates[0]:.0%} / 最大 {rates[-1]:.0%}")
    print(f"  全部が既出（射影がそのまま効く）: {len(full)} 枚"
          f"（{len(full) / r['unseen_cards']:.0%}）")
    print(f"  半分以上が初出: {len(weak)} 枚")
    print()
    print("■ 機構が完全一致する組（ID は違うが同じカード＝D-061 第 1 段がまとめる枠）")
    print(f"  全 {len(r['dup_groups'])} 組 / **既知と初見をまたぐ組 {len(r['bridge_groups'])} 組**")
    for v in sorted(r["bridge_groups"].values()):
        print("   ", v)


if __name__ == "__main__":
    main()
