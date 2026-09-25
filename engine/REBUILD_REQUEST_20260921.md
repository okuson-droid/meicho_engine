# 依頼 — 名指しの検査を 1 回（クロエ → マスター・2026-09-21）

> **2026-09-21 追記: 完了（D-117 追記 1）。`67 passed, 2 skipped in 353.36s (0:05:53)`——失敗 0。skip は `test_lit_d.py` の torch 無し 2 件。期待どおり。**以下は依頼時の文面である。

**再ビルドは要らない。Rust には触っていない。**全検査ではなく、変えたところに関わる 4 本だけを回す。

所要時間の見込み: **10〜30 分**（測っていない。いちばん重いのは `test_lit_d.py`。前回の全検査 2 時間 43 分のうちの一部）。
急ぎ度: 低（アプリの持ち場はこの結果を待たずに進められる）。
アプリの持ち場の未実施の PC 依頼書: 2026-09-21 の時点で `engine/app/` に `PC_REQUEST_*` は無い。

## なぜ今か

D-117（送り箱 TE-3・TE-4）で、rules の版を `meicho/version.py` の 1 か所に集め、対人検証アプリの記録に `think_ms` を足した。
作業環境では `test_versions.py`（5 件）と `test_webapp.py`（28 件）が通ったが、`test_lit_d.py` の一部（`meicho_rs` や `seed_bands.json` が要るもの）と
`test_dist.py`（配布版の組み立て）は作業環境に資材が無くて回せなかった。**打ち方は変えていない**（指紋 3 種は作業環境で一致を確認済み）。

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine

## 2. 何を打つか

**(1) 先に、書き戻したファイルが載っていることを確かめる**（検索語は ASCII だけ・D-101）。

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    set PYTHONPATH=%CD%
    findstr /c:"v0.18" meicho\version.py
    findstr /c:"from meicho.version import" webapp\record.py experiments\provenance.py experiments\ladder.py
    findstr /c:"think_ms" webapp\session.py
    findstr /c:"def test_no_rules_version_is_written_by_hand_anywhere_else" tests\test_versions.py

どれも 1 行以上出ること（2 行目の `findstr` は 3 ファイル分の 3 行）。**1 つでも出なければここで止めて**、どれが出なかったかを教えてほしい（OneDrive の書き戻しの失敗で、載せ直す）。

**(2) 名指しの検査。**今回は結果を画面に出す（ファイルに流さない）ので、終わるまで点（`.`）が増えていく。

    python -m pytest tests\test_versions.py tests\test_webapp.py tests\test_lit_d.py tests\test_dist.py -q -rs

## 3. 成功したらどう見えるか

- 最後の 1 行が `○ passed, ○ skipped in …` で、**`failed` が無い**こと
- skip は torch が無いための 2 件（`test_lit_d.py`）前後が正常。それ以外の skip があれば理由の行（`SKIPPED [..] ...`）を教えてほしい

## 4. 確認のしかた

最後の 1 行と、`FAILED` で始まる行があれば全部を貼ってほしい。

## 5. 転びやすいところと症状

- `set PYTHONPATH=%CD%` を打たずに回すと `ModuleNotFoundError: No module named 'meicho'`。コンソールを開き直したら打ち直す
- `ImportError: cannot import name 'RULES_VERSION' from 'meicho.version'` や `No module named 'meicho.version'` は、`meicho\version.py` が PC に載っていない印（(1) で止まるはず）
- `test_versions.py::test_no_rules_version_is_written_by_hand_anywhere_else` が落ちて `experiments\...py:行: RULES_VERSION = "v0.10"` のような行が出たら、その .py の書き戻しが載っていない。行をそのまま教えてほしい
- `test_versions.py::test_think_ms_excludes_the_time_the_human_spent` は 0.6 秒待つ検査。PC がとても混んでいると `think_ms < 300` で落ちることがありうる。落ちたら数字を教えてほしい（もう 1 回回して通れば混み具合）
