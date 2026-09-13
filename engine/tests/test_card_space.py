"""カードの「機構の仕様」による表現の性質（D-061）。

`experiments/analyse_card_space.py` の `profile` は、カードを
**カード ID・カード名・専用キャラ名を一切使わずに**表す。これは
「初見カードにも意味のある値を返せる表現」の土台であり（`DRL_PLAN.md` §3）、
D-050 条件 1「カード名は添字にしか使わない」とも整合する。

ここで固定するのは**数値ではなく性質**である（カードが増えるたびに落ちる検査にしない）。
"""
from __future__ import annotations

import dataclasses

from experiments.analyse_card_space import cards_of, mech_key, profile
from meicho import cards as C


def _all_cards():
    return list(C.CHARA_CARDS.values()) + list(C.ACTION_CARDS.values())


def test_profile_never_leaks_card_id_or_names():
    """素性の名前に、カード ID・カード名・キャラ名が現れないこと。

    ここが漏れると「初見カードに効く表現」ではなくなる（そのカードを見たことが前提になる）。
    """
    ids = set(C.CHARA_CARDS) | set(C.ACTION_CARDS)
    names = {c.name for c in _all_cards()}
    dedicated = {c.dedicated_to for c in C.ACTION_CARDS.values() if c.dedicated_to}
    forbidden = ids | names | dedicated
    for card in _all_cards():
        for feat in profile(card):
            for bad in forbidden:
                assert bad not in feat, f"{card.card_id} の素性 {feat!r} に {bad!r} が漏れている"


def test_profile_is_blind_to_which_character_a_card_belongs_to():
    """専用キャラだけが違う 2 枚は、同じ機構の仕様になること。

    実例（D-061）: SD01-017 と SD02-017（どちらも「音の形・通常攻撃」。
    専用キャラが 漂泊者（女）／漂泊者（男））。**カード ID で見ると共通 0 種**なのに、
    機構で見ると同じカードである。ここを同じに扱えることが、プールをまたぐ転移の前提になる。
    """
    a = C.ACTION_CARDS["SD01-017"]
    b = C.ACTION_CARDS["SD02-017"]
    assert a.card_id != b.card_id
    assert a.dedicated_to != b.dedicated_to
    assert mech_key(a) == mech_key(b)


def test_profile_still_separates_genuinely_different_cards():
    """名前が同じでも中身が違うカードは、別の仕様として区別されること。

    実例: 「音の刃」は SD01-022（速度 16・打点 1）と SD02-022（速度 13・打点 3）で数値が違う。
    名前を鍵にすると混ざるが、機構の仕様なら分かれる。**表現が情報を捨てていない**ことの確認。
    """
    a = C.ACTION_CARDS["SD01-022"]
    b = C.ACTION_CARDS["SD02-022"]
    assert a.name == b.name
    assert mech_key(a) != mech_key(b)


def test_mechanically_identical_cards_differ_only_by_owner():
    """機構の仕様が一致する組は、**専用キャラかカード名だけ**が違うこと。

    もし色やコストや効果まで違う組が一致してしまったら、表現が情報を捨てている。
    その場合はこの検査が落ちるので、`profile` に素性を足すこと。
    """
    seen, dup = {}, []
    for card in _all_cards():
        k = mech_key(card)
        if k in seen:
            dup.append((seen[k], card))
        else:
            seen[k] = card
    for x, y in dup:
        dx = dataclasses.asdict(x)
        dy = dataclasses.asdict(y)
        changed = {k for k in dx if dx[k] != dy[k]}
        assert changed <= {"card_id", "name", "dedicated_to", "skills"}, \
            f"{x.card_id} と {y.card_id} が一致したが、違いが {changed} に及んでいる"


def test_pools_share_nothing_by_id_but_do_share_by_mechanics():
    """SD001 と SD02 は、カード ID では 1 種も共通しないが、機構では共通する（D-061）。

    D-058 が「共通 0 種」と記録したのは **ID で数えた値**である。
    転移が効くかどうかを決めるのは機構の方なので、両方を残しておく。
    """
    a, b = cards_of("SD001"), cards_of("SD02")
    aa = [c for c in a if isinstance(c, C.ActionCard)]
    ba = [c for c in b if isinstance(c, C.ActionCard)]
    assert len({c.card_id for c in aa} & {c.card_id for c in ba}) == 0
    assert len({mech_key(c) for c in aa} & {mech_key(c) for c in ba}) > 0
