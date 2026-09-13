# -*- coding: utf-8 -*-
"""D-062: 仮のカードIDを cards/ の公式番号へ一斉に付け替える。

## なぜ2段階でやるか

**同じ文字列が、旧体系と新体系で別のカードを指す組が3つある。**

| 文字列 | 旧（engine） | 新（cards/） |
|---|---|---|
| SD02-001 | 漂泊者（男）Lv0 | 漂泊者（男）Lv2 |
| SD02-003 | 散華 Lv0 | 散華 Lv2 |
| SD02-005 | 今汐 Lv0 | 今汐 Lv2 |

素朴に「SD02-001 を BP01-021 に置換」してから「BP01-021 を SD02-001 に置換」すると、
1回目で作った BP01-021 を2回目が巻き戻してしまう。したがって
**いったん全部を衝突しない一時ID（`__MIG####__`）に退避してから、新IDへ移す**。

## 置換の単位

単語境界つきの完全一致のみ（`SD02-T1` が `SD02-T15` に巻き込まれないようにする）。

## 対象にするもの・しないもの

対象は「いま動いているもの」: 実装・テスト・デッキリスト・対人対局の記録・
README・ルール仕様書。

対象にしないのは**過去の記録**である: `decisions.md` の D-001〜D-061、各 `*_NOTES.md`、
発見ループのログ、データセットの manifest。これらは「その時点でそう書いた」という記録で
あり、後から書き換えると記録として嘘になる。読み替えができるよう、D-062 に
対応表そのものを載せる。

使い方:
    python3 scripts/rename_card_ids_d062.py            # 実行
    python3 scripts/rename_card_ids_d062.py --dry-run  # 件数を数えるだけ
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

# 旧ID → 新ID（公式番号）。cards/cards_structured.csv の code 列が正。
MAPPING = {
    # --- キャラ（★ が付いた6件は「同じ文字列が別カードを指す」衝突組）---
    "SD02-001": "BP01-021",   # ★ 漂泊者（男）Lv0
    "BP01-021": "SD02-001",   # ★ 漂泊者（男）Lv2
    "SD02-002": "SD02-002",   #   漂泊者（男）Lv1（変わらず）
    "SD02-003": "BP01-033",   # ★ 散華 Lv0
    "BP01-033": "SD02-003",   # ★ 散華 Lv2
    "SD02-004": "SD02-004",   #   散華 Lv1（変わらず）
    "SD02-005": "BP01-030",   # ★ 今汐 Lv0
    "BP01-030": "SD02-005",   # ★ 今汐 Lv2
    "SD02-006": "SD02-006",   #   今汐 Lv1（変わらず）
    "SD001-C01": "BP01-018",  # 漂泊者（女）Lv0
    "SD001-C02": "SD01-002",  # 漂泊者（女）Lv1
    "SD001-C03": "SD01-001",  # 漂泊者（女）Lv2
    "SD001-C04": "BP01-024",  # 秧秧 Lv0
    "SD001-C05": "SD01-004",  # 秧秧 Lv1
    "SD001-C06": "SD01-003",  # 秧秧 Lv2
    "SD001-C07": "BP01-027",  # 熾霞 Lv0
    "SD001-C08": "SD01-006",  # 熾霞 Lv1
    "SD001-C09": "SD01-005",  # 熾霞 Lv2
    # --- アクション: SD01（漂泊者（女）・秧秧・熾霞）---
    "SD001-T01": "SD01-017",  # 音の形・通常攻撃
    "SD001-T02": "SD01-019",  # 轟音
    "SD001-T03": "SD01-022",  # 音の刃
    "SD001-T04": "SD01-023",  # 奏鳴
    "SD001-T05": "SD01-012",  # 羽の刃・通常攻撃
    "SD001-T06": "SD01-014",  # 息継ぎ
    "SD001-T07": "SD01-016",  # 旋風
    "SD001-T08": "SD01-007",  # ババン・通常攻撃
    "SD001-T09": "SD01-009",  # 躍動する炎
    "SD001-T10": "SD01-010",  # 燃える闘志
    "SD001-T11": "SD01-011",  # 燃える烈火
    "SD001-T12": "SD01-018",  # 音の形・回避
    "SD001-T13": "SD01-013",  # 羽の刃・回避
    "SD001-T14": "SD01-008",  # ババン・回避反撃
    "SD001-T15": "SD01-020",  # スキャン
    "SD001-T16": "SD01-021",  # 鉤縄
    "SD001-T17": "SD01-015",  # ジャンプ
    # --- アクション: SD02（漂泊者（男）・散華・今汐）---
    "SD02-T01": "SD02-017",   # 音の形・通常攻撃
    "SD02-T02": "SD02-019",   # 轟音
    "SD02-T04": "SD02-023",   # 奏鳴
    "SD02-T05": "SD02-012",   # 冷徹な光・通常攻撃
    "SD02-T07": "SD02-015",   # 永劫新雪
    "SD02-T08": "SD02-016",   # 赤瞳凍土
    "SD02-T09": "SD02-007",   # 寒風散らす光・通常攻撃
    "SD02-T11": "SD02-011",   # 邪を潰す歳月の重さ
    "SD02-T13": "SD02-013",   # 冷徹な光・回避
    "SD02-T14": "SD02-008",   # 寒風散らす光・回避反撃
    "SD02-T15": "SD02-020",   # スキャン
    "AC-002": "SD02-018",     # 音の形・回避
    "AC-003": "SD02-022",     # 音の刃
    "AC-004": "SD02-021",     # 鉤縄
    "AC-005": "SD02-010",     # 龍憑の天舞
    "AC-006": "SD02-009",     # 蟠龍の輝き
    "AC-007": "SD02-014",     # 凛然浄化
}

# 「いま動いているもの」だけを対象にする（理由は上の docstring）。
TARGETS = [
    "meicho/cards.py", "meicho/engine.py", "meicho/state.py",
    "tests/test_engine.py", "tests/test_card_space.py", "tests/test_c1_features.py",
    "experiments/run_clash_cfr.py",
    "decklists/SD001.json", "decklists/SD02.json",
    "decklists/SD001.md", "decklists/SD02.md",
    "results/human_games/2026-08.jsonl",
    "README.md", "rules_draft.md",
]

_TMP = {old: f"__MIG{i:04d}__" for i, old in enumerate(sorted(MAPPING))}


def _sub_all(text: str, table: dict) -> tuple:
    """単語境界つきで一括置換し、(置換後, 件数) を返す。"""
    if not table:
        return text, 0
    pat = re.compile(r"(?<![A-Za-z0-9_-])(" +
                     "|".join(re.escape(k) for k in sorted(table, key=len, reverse=True)) +
                     r")(?![A-Za-z0-9_-])")
    n = 0

    def rep(m):
        nonlocal n
        n += 1
        return table[m.group(1)]

    return pat.sub(rep, text), n


def main(argv: list) -> int:
    dry = "--dry-run" in argv
    # 対応表の健全性を先に確かめる: 新IDに重複が無いこと（別カードが同じ番号になると壊れる）
    news = list(MAPPING.values())
    assert len(news) == len(set(news)), "新IDに重複がある"

    print("D-062 カードIDの付け替え（旧 %d 種 → 公式番号）" % len(MAPPING))
    total = 0
    for rel in TARGETS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f"  - {rel}: 見つからない（飛ばす）")
            continue
        with open(path, encoding="utf-8", newline="") as f:
            src = f.read()
        # 第1段: 旧ID → 一時ID
        mid, n1 = _sub_all(src, _TMP)
        # 第2段: 一時ID → 新ID
        out, n2 = _sub_all(mid, {tmp: MAPPING[old] for old, tmp in _TMP.items()})
        assert n1 == n2, f"{rel}: 段の件数が合わない ({n1} != {n2})"
        total += n1
        if n1 and not dry:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(out)
        print(f"  {'(試算) ' if dry else ''}{rel}: {n1} 箇所")
    print(f"合計 {total} 箇所")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
