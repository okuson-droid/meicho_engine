# GitHub Desktop で ChatGPT に渡す — 手順（2026-09-13）

コマンドを打たない手順。**上がるファイルを目で確かめてから公開できる**ので、
このプロジェクトの制約（公式素材を含む成果物を公開しない）とは相性がよい。

---

## 0. 先に確かめてほしいこと（ここで詰まると以降が無駄になる）

**ChatGPT がその private リポジトリを読めるか。** ChatGPT から GitHub を読むには
コネクタ（または Codex の GitHub 連携）が要り、**契約しているプランによっては使えない**。

- 読めるなら → 下の手順どおり **private** で作る。
- 読めないなら → public にするか、GitHub をやめて**ファイルを直接貼る**形に戻すほうが早い。

**public にするかはマスターの判断事項である。** `.gitignore` で公式素材は外してあるので
残るのは我々が書いたコードと文書だけになるが、プロジェクトの制約は
「個人研究用途に留める」なので、**公開そのものの是非はクロエが決めてよい話ではない**。

---

## 1. どこで

GitHub Desktop を開く。まだ GitHub にサインインしていなければ先に済ませる
（`File` → `Options` → `Accounts`）。

## 2. 何をするか

### (1) リポジトリとして登録する

`File` → **`Add local repository...`** を選び、`Choose...` からこのフォルダを指定する。

```
C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1
```

まだ git 管理されていないので、

> This directory does not appear to be a Git repository.
> Would you like to **create a repository** here instead?

と出る。青い **`create a repository`** の文字を押す。

### (2) 「Create a repository」ダイアログ（**ここが唯一の要注意**）

- **Name**: `meicho_engine`（好きな名前でよい）
- **Local path**: 上のフォルダが入っているはず。**変えない**
- **Initialize this repository with a README**: **チェックを外す**
- **Git ignore**: **必ず `None`** ← ★ここ
- **License**: `None`

★ **`Git ignore` で何かを選ぶと、クロエが置いた `.gitignore` が上書きされる恐れがある。**
あの 1 行目（`cards/`）が公式素材を止めている唯一の仕掛けなので、消えると
カード画像と公式テキストがそのまま上がる。**必ず `None`。**

`Create repository` を押す。

### (3) 上がるファイルを目で確かめる（**公開の前に必ず**）

左の **`Changes`** タブに、これから登録されるファイルが全部並ぶ。
タブの見出しに **`XXX changed files`** と件数が出る。

**確かめることは 3 つ。**

1. 件数が **300 前後**であること。**4 桁なら何かが漏れている**
2. 一覧に **`cards/` で始まる行が 1 つも無い**こと（`.png` が並んでいたら赤信号）
3. `.whl` `.pyd` `target/` が無いこと

一覧はパス順に並ぶので、先頭のほうを少しスクロールすれば `cards/` の有無はすぐ分かる。

**1 つでも当てはまったら、そこで止めてクロエに件数と見えているファイル名を貼ってほしい。**

> より厳密に見たいときは `Repository` → `Open in Command Prompt` から
> `git ls-files | findstr /i "cards\\"` を打つ。**何も出ないのが正解。**

### (4) コミットする

左下の入力欄に要約を書いて、**`Commit to main`** を押す。

```
meicho_engine: 初回（公式素材は除外）
```

### (5) 公開する

上の **`Publish repository`** を押す。ダイアログで:

- **Keep this code private**: ★**チェックを入れたまま**（§0 で private と決めた場合）
- `Publish repository` を押す

## 3. 成功したらどう見えるか

- `Changes` タブが空になる（`No local changes`）
- 上のボタンが `Publish repository` から **`Fetch origin`** に変わる
- `Repository` → `View on GitHub` でブラウザが開き、ファイルが並んでいる
- そのページに **`Private`** のバッジが付いている ← ここも目で確かめる

## 4. これから毎回やること（更新のしかた）

クロエがファイルを書き戻したあと、ChatGPT に相談する前に:

1. GitHub Desktop を開く（`Changes` に変更が出ている）
2. 要約を書いて `Commit to main`
3. **`Push origin`** を押す

**push を忘れると ChatGPT は古い版を読む。** 相談の前に `Changes` が空か、
`Push origin` に数字が付いていないかを見ること。

## 5. 転びやすいところと症状

- **`Git ignore` を `None` にし忘れた**: 症状は `Changes` に `.png` が何百行も並ぶ。
  直し方は、フォルダの `.gitignore` の 1 行目が `cards/` になっているか確認し、
  違っていたらクロエが出した `.gitignore` で置き換えてから `Changes` を見直す。
- **OneDrive の同期とぶつかる**: このフォルダは OneDrive の中にある。同期中に
  ファイルが掴まれて `Permission denied` / `unable to index file` が出ることがある。
  OneDrive を一時停止してからやり直す。
- **ファイル数が多くて `Changes` が重い**: 300 前後なら数秒。いつまでも出ないなら
  除外が効いていない可能性が高いので、先に `.gitignore` を疑う。
- **改行コードの警告**: `LF will be replaced by CRLF` は無害。
- **`Publish` のときに private のチェックが外れていた**: 公開後に GitHub のページで
  `Settings` → 一番下の `Change repository visibility` から private に戻せる。
  ただし**一度公開したものは見られた可能性が残る**ので、気づいた時点で戻すこと。

---

## 6. ChatGPT に最初に言うこと（テンプレ）

リポジトリを読ませたら、最初にこれを渡すと話が通じるようになる。

> このリポジトリは TCG『鳴潮：対決』の解析エンジン。既製品の解析であり、ルールの改変は目的外。
> 用語は `memory/glossary.md` と `CLAUDE.md` にある（便・門番・錨・帯・champion）。
> 現在地は `TASKS.md`、設計判断の履歴は `engine/decisions.md`（末尾が新しい）。
> **カードの公式テキストと画像はこのリポジトリに入れていない**ので、
> カードの効果は `engine/meicho/cards.py` のオペコード表現だけで読むこと。
> 提案するときは、費用（局/秒・時間）と、採否を決める測り方（対戦数と 95% 信頼区間）を必ず添えて。

## 7. 運用の約束

- **ChatGPT の返答をそのまま採らない。**「反論」として受け取り、測れる基準に落としてから裁定へ。
- 合意は `engine/decisions.md` に書かれるまで確定ではない（既存の規約がそのまま効く）。
- リポジトリは**貼るための置き場**であって正本ではない。正本は PC のフォルダのまま。
