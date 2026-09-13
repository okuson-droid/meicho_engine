"""カードから導出する特徴の検査（D-047）。

この特徴の値打ちは「カード名を知らずに正しく数えられる」ことにある。
だから固定すべきは**分類の結果**であって、勝率ではない（勝率は負の結果だった）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from measure_persistent_feature import (ALWAYS_KEYS, PERSISTENT,  # noqa: E402
                                        persistent_count)
from meicho.cards import CHARA_CARDS                              # noqa: E402


# **基準のカードは番号で直書きする**（D-083 追記 4）。
# BP01 が SD のキャラ全員に Lv1 / Lv2 の別版を足したので、「名前とレベル」では
# カードが 1 枚に決まらなくなった（漂泊者（女）Lv2 は SD01-001 と BP01-016）。
# D-047 の測定が見ていたのは **SD001 のカード**なので、そちらを名指しする。
SD001_LV2 = {"漂泊者（女）": "SD01-001", "熾霞": "SD01-005", "秧秧": "SD01-003"}
SD001_LV0 = {"漂泊者（女）": "BP01-018", "熾霞": "BP01-027", "秧秧": "BP01-024"}


def _counted(card_id: str) -> int:
    c = CHARA_CARDS[card_id]
    return sum(1 for sk in c.skills
               if sk.timing in PERSISTENT and not sk.optional
               and (not sk.condition or set(sk.condition) <= ALWAYS_KEYS))


def test_persistent_classification_matches_the_card_texts():
    """持続効果の判定が、実際のカードの型と一致すること。

    - 漂泊者（女）Lv2: 【ターン開始時】無条件 → **数える**
    - 熾霞 Lv2:       【常在】             → **数える**
    - 秧秧 Lv2:       【対抗】条件付き      → 数えない
    - Lv0 の【対抗】  : 条件付き            → 数えない

    ここが崩れたら D-047 の測定は読めない。
    """
    assert _counted(SD001_LV2["漂泊者（女）"]) == 1
    assert _counted(SD001_LV2["熾霞"]) == 1
    assert _counted(SD001_LV2["秧秧"]) == 0
    for nm, cid in SD001_LV0.items():
        assert _counted(cid) == 0, f"{nm} Lv0（{cid}）の条件付きスキルを数えている"


def test_the_feature_is_derived_not_hard_coded():
    """特徴の定義にカード名が現れないこと。

    **ここがこの特徴の存在理由である。** カード名を書いた瞬間に、
    新しいプールが来るたび書き足す必要が生まれる。
    """
    import measure_persistent_feature as m
    src = open(m.__file__, encoding="utf-8").read()
    body = src.split("def persistent_count", 1)[1].split("\nclass ", 1)[0]
    for nm in ("漂泊者", "熾霞", "秧秧", "今汐", "散華", "SD001", "SD02"):
        assert nm not in body, f"特徴の実装にカード名 {nm} が埋め込まれている"


def test_opening_position_has_no_persistent_effects():
    """開幕（全員Lv0）では 0 であること。数え方の下限の確認。"""
    from arena import load_deck, mirror_config
    from meicho.engine import apply, initial_state
    cfg = mirror_config(load_deck("SD001"))
    s = initial_state(cfg, 172000)
    s = apply(s, {0: {"type": "setup", "leader": "漂泊者（女）"},
                  1: {"type": "setup", "leader": "熾霞"}})
    assert persistent_count(s, 0) == 0
    assert persistent_count(s, 1) == 0
