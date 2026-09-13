# 環境・道具
- PC: Windows・`C:\Users\...\eclipse_workフォルダ\meicho_engine_v0.1`（OneDrive）。低スペック前提。torch 無し・Rust wheel は古いのが正常。
- 作業環境（作業者）: Linux 2 コア・Rust 自前ビルド可（約 1 分）・bash 600 秒・10 分無操作で回収。
  **PC とは別の機械のことがある**（便 M はクラウドの作業機で、PC の約半分の速さ）。
  由来ブロックの `host` は `workenv-2` / `kaggle-cpu-4` / `gcp-c3d-16` の 3 択しかなく、
  クラウドの作業機を表す名前が無い（`cowork-2` を足すのが推し・D-076 判断 5）。
- 外部資源: Kaggle（未登録・D-072。要るのは便 E 本体）。Hugging Face は学習済みモデルと結果の置き場。
- 真実源: `engine/rules_draft.md`（v0.11）・`engine/decisions.md`・`experiments/champion.py`・`experiments/seed_bands.json`。Python が真実源、Rust は写し。
- 発売日: 2026-09-12（土）。発売前でも計画は変えない。
- **未着手の作業は `TASKS.md`**（このフォルダの直下）。Claude 側の記憶は Cowork のプロジェクト記憶（地図と作法だけ）。
