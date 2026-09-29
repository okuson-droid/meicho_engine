# engine/board — 進行盤（段 6）

設計書: `engine/PROGRESS_BOARD_DESIGN_20260929.md`（裁定済み 2026-09-29）。
進行盤: https://claude.ai/artifact/2hz36T6UcuDakKhn2x3awC （非公開・マスターだけが開ける）

## 中身

- `extract_board.py` — `main` の写し（sparse clone でよい）から進行盤の JSON を作る切り出し道具。判断はしない。切り出せなければ `status: failed`
- `tests/test_extract_board.py` — 検査 14 件（通る側・壊す側・`BOARD_REPO` があれば本物の写しでも 1 回）
- `progress_board.html` — 進行盤のページの控え（正本はアーティファクト側。作り直すときはこの HTML を Cowork の Artifact で公開する）
- `SCHEDULED_PROMPT.md` — 定期実行（スケジュールタスク 2 本）の prompt の正本。タスクの prompt を変えるときはここを先に直す

## 回し方

```
cd engine/board
python3 -m pytest tests -q
# 本物の写しでも回す:
git clone --depth 1 --filter=blob:none --sparse https://github.com/okuson-droid/meicho_engine /tmp/repo
(cd /tmp/repo && git sparse-checkout init --no-cone && git sparse-checkout set '/TASKS.md' '/CLAUDE.md' '/LANES.md' '/engine/*.md' '/engine/meicho/version.py' '/engine/experiments/champion.py' '/engine/experiments/seed_bands.json' '/engine/scripts/check_champion_fingerprint.py' '/engine/app/*.md')
BOARD_REPO=/tmp/repo python3 -m pytest tests -q
python3 extract_board.py /tmp/repo --out /tmp/board.json
```

PC の Windows では `python -m pytest tests -q`（資材は要らない・数秒）。

## 定期実行

- 「進行盤の更新（朝・夜）」 `CRON_TZ=Asia/Tokyo 48 6,18 * * *`
- 「進行盤の更新（昼）」 `CRON_TZ=Asia/Tokyo 40 11 * * *`
- どちらも自動承認・クラウドだけで動く。PC は要らない

**この道具が `main` に push されるまで、定期実行は「未 push」の失敗を書き、盤は赤い帯になる。**push されれば次の回から緑に戻る。
