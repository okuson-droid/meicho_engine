"""固めた実行ファイルの入口。やることは起動役（`mslauncher`）を呼ぶだけ。

`freeze_support()` は、中身が将来 multiprocessing を使ったときの備えである（固めた実行ファイルでは、
子プロセスが同じ実行ファイルを特別な引数つきで呼び直す。それをここで受ける）。
"""
import multiprocessing
import sys

from mslauncher.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
