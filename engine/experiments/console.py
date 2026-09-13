"""道具の**表示**を、環境のロケールに左右されず UTF-8 で出す（D-082 追記 1・2026-09-13）。

## なぜ要るのか

報告の文には `π₀`・`—`・`≥` のような文字が入っている。このうち **`₀`（U+2080）は
cp932 で書けない**。Python は、標準出力が**コンソールのとき**は Windows のコンソール API を
直に叩くので日本語 Windows でも問題ないが、**パイプやファイルに向けるとロケールの符号化
（cp932）を使う**。その瞬間、報告の途中で `UnicodeEncodeError` が飛んで道具が落ちる。

実際に起きた: `tests/test_value_bootstrap.py::test_resume_refuses_a_different_measurement` は
`eval_vb.py` を子プロセスで回して出力を捕まえる検査で、**マスターの PC（日本語 Windows）でだけ
落ちた**。道具は「別の条件の途中経過には足し込まない」と**言えずに**死んでいた——
つまりこれは検査の都合ではなく、**道具が PC で報告できないという本物の不具合**である。

## 何をするか／しないか

**するのは表示の符号化を UTF-8 に寄せることだけ。** 記録する文字列（ラベル・
途中経過の鍵・結果 JSON）は**1 文字も変えない**——`π₀` は `eval_vb` の `--resume` の鍵にも
結果の `new` / `old` 欄にも入っているので、書き換えると**過去の途中経過と結果が読めなくなる**。

**子プロセスで道具を回して出力を読む側**は、あわせて `encoding="utf-8"` で受けること
（`scripts/make_dist.py` の `_UTF8` が同じ手当てを先にしている）。片側だけ直すと
親が cp932 で読んで文字化けする。
"""
from __future__ import annotations

import sys


def use_utf8_console() -> None:
    """標準出力・標準エラーを UTF-8 にする。できない環境では何もしない。

    **道具の `main()` の先頭で呼ぶ。**ライブラリ（`meicho/`）からは呼ばない——
    アプリや配布版の標準出力を勝手に付け替えないためである。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")      # Python 3.7 以降
        except (AttributeError, ValueError):
            pass                                       # 置き換え済みの stdout など
