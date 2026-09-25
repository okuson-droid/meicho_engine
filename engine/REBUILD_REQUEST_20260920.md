# 依頼 — 全検査を 1 回（クロエ → マスター・2026-09-20）

> **2026-09-21 追記: 完了（D-116）。`985 passed, 26 skipped in 9789.22s (2:43:09)`——失敗 0。skip は全部 torch 無し。期待どおり。**
> ★この依頼書の不備: `>` でファイルに流すと画面に何も出ないことを書いていなかった。以下は依頼時の文面である。

**再ビルドは要らない。Rust には触っていない。**マスターの PC の作業はこの全検査 1 回だけである。

所要時間の見込み: **約 3 時間 10 分**（前回 2026-09-19 の全検査が 3 時間 6 分 49 秒。今回増える検査は合わせて 30 秒ほど）。
急ぎ度: 中（アプリの持ち場は M1 の口を使い始めるが、この検査を待たずに進められる）。
アプリの持ち場に未実施の PC 依頼書は無い（`engine/app/` に `PC_REQUEST_*` が無いことを 2026-09-20 に確認）。

## なぜ今か

前回の全検査のあとに、エンジンの持ち場で 3 つ入れた。どれも**打ち方は変えていない**が、全検査を 1 回も通していない。

1. **D-105／D-106**（2026-09-19）: 検査の経路と、A-6 の取りこぼしの直し。名指しの 3 本は PC で確認済み（123 通過）だが、全検査はまだ
2. **D-114 M1 のトレース点**（2026-09-20）: `meicho/engine.py` にトレース点、`meicho/trace.py` と `tests/test_trace_m1.py`（19 件）を新設。
   作業環境で、既存の検査・Python↔Rust の毎手一致・`bench_agents.py` の指紋 3 種が変わらないことを確かめてある
3. **D-115**: 唯一落ちていた `tests/test_lit_c.py::test_worlds_module_matches_diag_pimc` の基準の記録を作り直した。
   **作り直しは作業環境で済ませた**（約 30 秒）。新しい記録 `results/lit/m5m1_pimc_v018.jsonl` を PC に置いてある。元の記録 `m5m1_pimc.jsonl` は消していない

**うまくいけば、全検査が「失敗 0」に戻る。**

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine

## 2. 何を打つか

**(1) 先に、書き戻したファイルが載っていることを確かめる**（検索語は ASCII だけ・D-101）。

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    set PYTHONPATH=%CD%
    findstr /c:"from . import trace as _trace" meicho\engine.py
    findstr /c:"def tracing(sink)" meicho\trace.py
    findstr /c:"m5m1_pimc_v018.jsonl" tests\test_lit_c.py
    dir results\lit\m5m1_pimc_v018.jsonl

4 つとも出ること（`dir` は 1 ファイル見つかること）。**1 つでも出なければここで止めて**、どれが出なかったかを教えてほしい（OneDrive の書き戻しの失敗で、作り直して載せ直す）。

**(2) 全検査。場所は必ず `tests` と指定する。**

    python -m pytest tests -q -rs > fails_20260920.txt 2>&1

終わったら `fails_20260920.txt` の**最後の 1 行**（「○ failed, ○ passed, ○ skipped in …」）を教えてほしい。
落ちたものがあれば、`FAILED` で始まる行を全部。

## 3. 成功したらどう見えるか

- 期待: **失敗 0・通過 985 前後・skip 26 前後**
  （前回は 2 失敗 / 964 通過 / 26 skip。落ちていた 2 件が通るようになって 966、新設の 19 件で 985 になる計算）
- 通過の数が多少ずれても、**失敗 0 なら成功**である。数のずれは報告だけしてほしい（skip の理由が環境で違うことがある）

## 4. 確認のしかた

- `fails_20260920.txt` の最後の行を見る
- 新設の検査だけ先に見たければ、全検査の前に次で 1 分かからない:

      python -m pytest tests\test_trace_m1.py tests\test_lit_c.py -k "trace or worlds_module_matches" -q

  期待: **20 通過・失敗 0**

## 5. 転びやすいところと症状

- **`python -m pytest` を場所なしで打つと、`app\tests` も集まる**（アプリの持ち場の検査・TE-7）。件数が変わるので必ず `tests` を付ける
- **`set PYTHONPATH=%CD%` を忘れると `meicho` が見つからない**（`ModuleNotFoundError: No module named 'meicho'`）。コンソールを開き直したら打ち直す
- **`findstr` で日本語を検索語にしない**（cp932 と UTF-8 の違いで、中身があっても当たらない）
- 画面に何も出ない時間が長い（全体で 3 時間ほど）。止まって見えても、`fails_20260920.txt` の更新日時が進んでいれば動いている
- `test_worlds_module_matches_diag_pimc` が **skip** になったら、`results\lit\m5m1_pimc_v018.jsonl` が PC に載っていない（(1) の `dir` で見つかるはず）
