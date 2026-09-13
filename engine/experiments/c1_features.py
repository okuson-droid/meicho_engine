"""このモジュールは `meicho/features.py` に移動した（D-038, 2026-08-24）。

学習価値関数エージェント (`meicho/valuenet.py`) が特徴抽出に依存するようになったため、
`experiments/` から `meicho/` へ昇格させた。`experiments` は `sys.path` に載るので、
古いコピーを残すと `import c1_features` が静かに通ってしまい、
特徴を更新したのに古い定義が使われる事故になる。それを防ぐためにここで止める。

**このファイルは削除してよい。**
"""
raise ImportError(
    "c1_features は meicho/features.py に移動しました。"
    "`from meicho import features` を使ってください（D-038）。"
    "このファイル experiments/c1_features.py は削除して構いません。")
