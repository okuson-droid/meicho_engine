"""版の定数を 1 か所で持つ（D-117・送り箱 TE-3）。

`RULES_VERSION` は `rules_draft.md` の見出しの版と**同じでなければならない**。
食い違えば `tests/test_versions.py` が落ちる（番人）。rules の版を上げたら、ここも同時に上げる。

なぜファイルを読まずに定数で持つか: 配布版（D-074）には `rules_draft.md` を入れない。
記録に版を書く側（`webapp/record.py` など）は、配布版でも同じ値を得られる必要がある。

以前は `webapp/record.py` に `RULES_VERSION = "v0.10"` が直書きされていて、
rules が v0.18 まで上がるあいだ誰にも気づかれずに取り残された（TE-3）。
"""
RULES_VERSION = "v0.19"
ENGINE_VERSION = "v0.1"
