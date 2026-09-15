# -*- coding: utf-8 -*-
"""未経験カードが「機構の素性」でどれだけ説明できるかを数える（D-086 案 段 G-0）。

対局を 1 局も回さずに、**効果プロファイル射影（DRL_PLAN §3.1）が未経験カードに
効く見込みがあるか**を見るための道具。`analyse_card_space.py` の `profile()`
（カード → 機構の素性の袋。カード ID・名前・キャラ名を一切使わない・D-050 条件 1）を使う。

## ★「既知」はデッキで決める。セットの接頭辞で決めない（D-086 追記 1）

最初の版は `SD01` / `SD02` / `BP01` という**カード番号の接頭辞**で既知と未経験を
分けていた。これは誤りである。接頭辞は**どのセットで刷られたか**であって、
**学習でそのカードを踏んだか**ではない。実際 `SD001` のデッキには `BP01-018`
`BP01-024` `BP01-027` が、`SD02` には `BP01-021` `BP01-030` `BP01-033` が入っている
（どれも Lv0 キャラ）。**接頭辞で数えると、この 6 枚を「未経験」と誤って数える。**

外部レビュー（`GENERALIST_AI_REVIEW_D086.md` §2.3）の指摘で気づいた。測り直しても
結論は動かなかったが、**道具のほうを直す**——次に数える人が同じ誤りを踏まないように、
既定を**デッキ基準**にし、接頭辞モードは `--sets` を明示したときだけにした。

## 読み方（ここも誤読しやすい）

- **被覆率は「理解度」ではない。** `profile()` は学習用の完全なカード仕様ではなく、
  condition の**値**を持たず、スキル内の結び付きを持たず、効果列の順序を持たず、
  対象（誰に・どのカードに）を伏せている。だから被覆率は**転移の見込みの診断**であって、
  勝率の改善幅でも、カードを理解した割合でもない（レビュー §2.3）。
- `mech_key()` の一致は「**この特徴表現の上での**一致」と読む。

実行:
    python3 experiments/profile_coverage.py                     # 既定: SD001+SD02 のデッキが既知
    python3 experiments/profile_coverage.py --decks SD001       # 既知を 1 デッキに絞る
    python3 experiments/profile_coverage.py --sets SD01 SD02    # 旧来の接頭辞モード（非推奨）
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from analyse_card_space import mech_key, profile          # noqa: E402
from meicho import cards as C                              # noqa: E402

DEFAULT_DECKS = ("SD001", "SD02")


def all_cards() -> dict:
    return {**C.CHARA_CARDS, **C.ACTION_CARDS}


def deck_card_ids(names) -> set:
    """デッキリストに実際に入っているカード番号の集合（キャラ＋アクション）。"""
    ids: set = set()
    for n in names:
        path = os.path.join(_ROOT, "decklists", f"{n}.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        ids |= set(d.get("chara_deck", [])) | set(d.get("action_deck", []))
    return ids


def coverage(known_ids: set) -> dict:
    cards = all_cards()
    unknown = sorted(known_ids - set(cards))
    if unknown:
        raise SystemExit(f"登録簿に無い番号がデッキに入っている: {unknown}")
    known = [c for cid, c in cards.items() if cid in known_ids]
    unseen = [c for cid, c in cards.items() if cid not in known_ids]
    if not known or not unseen:
        raise SystemExit(f"片側が空: 既知 {len(known)} / 未経験 {len(unseen)}")

    kf = set().union(*[set(profile(c)) for c in known])
    uf = set().union(*[set(profile(c)) for c in unseen])

    per_card = []
    for c in unseen:
        p: Counter = profile(c)
        tot = sum(p.values())
        per_card.append((c.card_id, sum(n for f, n in p.items() if f in kf) / tot))

    by_mech: dict = {}
    for cid, c in cards.items():
        by_mech.setdefault(mech_key(c), []).append(cid)
    dup = {k: sorted(v) for k, v in by_mech.items() if len(v) > 1}
    bridge = [v for v in dup.values()
              if (set(v) & known_ids) and (set(v) - known_ids)]

    return {"known": known, "unseen": unseen, "kf": kf, "uf": uf,
            "per_card": per_card, "dup": dup, "bridge": bridge}


def main() -> None:
    argv = sys.argv[1:]
    mode, names = "decks", list(DEFAULT_DECKS)
    if argv and argv[0] == "--sets":
        mode, names = "sets", argv[1:] or ["SD01", "SD02"]
    elif argv and argv[0] == "--decks":
        names = argv[1:] or list(DEFAULT_DECKS)

    if mode == "decks":
        known_ids = deck_card_ids(names)
        label = f"デッキ {'+'.join(names)} に実際に入っているカード"
    else:
        known_ids = {cid for cid in all_cards() if cid.split("-")[0] in set(names)}
        label = (f"セット {'+'.join(names)} の全カード"
                 f"（★非推奨: 接頭辞は学習経験の代わりにならない）")

    r = coverage(known_ids)
    rates = sorted(x[1] for x in r["per_card"])
    full = [x for x in r["per_card"] if x[1] == 1.0]
    weak = [x for x in r["per_card"] if x[1] < 0.5]

    print(f"■ 既知の取り方: {label}")
    print(f"  既知 {len(r['known'])} 枚 / 未経験 {len(r['unseen'])} 枚 "
          f"（登録簿 {len(all_cards())} 枚）")
    print(f"■ 素性の種類: 既知 {len(r['kf'])} / 未経験 {len(r['uf'])} / "
          f"未経験のうち既出 {len(r['uf'] & r['kf'])}"
          f"（未経験側の {len(r['uf'] & r['kf']) / len(r['uf']):.0%}）")
    print()
    print("■ 未経験カード 1 枚ごとの被覆率（その枚の素性の延べ回数のうち既出の割合）")
    print(f"  中央値 {statistics.median(rates):.0%} / 最小 {rates[0]:.0%} / "
          f"最大 {rates[-1]:.0%}")
    print(f"  全部が既出: {len(full)} 枚（{len(full) / len(r['unseen']):.0%}）")
    print(f"  半分以上が初出: {len(weak)} 枚")
    print("  ※ これは転移の見込みの診断であって、理解度でも勝率の改善幅でもない。")
    print()
    print("■ 機構が完全一致する組（この特徴表現の上で・D-061 第 1 段がまとめる枠）")
    print(f"  全 {len(r['dup'])} 組 / **既知と未経験をまたぐ組 {len(r['bridge'])} 組**")
    for v in sorted(r["bridge"]):
        print("   ", v)


if __name__ == "__main__":
    main()
