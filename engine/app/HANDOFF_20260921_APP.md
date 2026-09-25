# 引継ぎ書（アプリの持ち場）2026-09-21: M5 後半まで実装済み。次は Windows での確認待ち

- 持ち場: **アプリ**（`LANES.md`）。書くのは `engine/app/` の下と Claude Docs の文書だけ
- 最初に読む順: `LANES.md` §0 の 4 つ → `engine/app/TASKS_APP.md`（状態の正本）→ この文書 → 要るところだけ `DECISIONS_APP.md`（APP-010 が今回）
- 準拠: rules は作業環境の写しで **v0.18**（`rules_draft.md` の見出し。PC の実物が進んでいないかは未確認）。通信の版 1。記録の版 3
- この文書は**台帳に収まらない文脈だけ**を書く。やること・待ちの一覧は `TASKS_APP.md`、決定の本文は `DECISIONS_APP.md`、マスターの手順は `PC_REQUEST_20260921_APP.md` が正本
- アプリの引継ぎ書はこれが 1 本目（これまでは会話の要約で繋いでいた）

## 0. いまの状態

- M2〜M4・M5 前半（CPU 対戦）・**M5 後半（配布版と自動更新・APP-010）**まで、実装と自動検査が済んでいる。作業環境で検査 **76 件通過**（Playwright あり。PC では Playwright が無ければ `test_ui.py` は skip）
- M5 後半の PC への書き戻しは 25 ファイル、全部を再ステージして `cmp` でバイト一致を確かめた（2026-09-21 16 時台）。そのあとこの引継ぎで `TASKS_APP.md`・`WRITELOG_APP.md` をもう一度書き、依頼書とこの文書を足した
- **Windows では一度も固めていない。**Linux で固めた実行ファイルでは通しが通った（最新のまま起動／1 ファイルだけの更新／壊れた版 → 自動で一つ前へ → 次回は取り込み直さない／更新元を止めて起動／`data/` が残る）
- マスターはまだ M5 前半（CPU 対戦）も M5 後半も手で触っていない。演出の速さの数字もまだ来ていない
- エンジンの送り箱 `engine/TO_APP.md` は TA-1〜TA-7 が全部「済」。新しい項目は無かった（2026-09-21 に確認）
- こちらの送り箱は TE-12（`scripts/make_dist.py` を import して使い始めた知らせ）を足した。頼みごとは出していない

## 1. 次にやること

1. **`TASKS_APP.md` Active「M5 後半をマスターの PC で固めて確かめる」**。マスターが `PC_REQUEST_20260921_APP.md` を回した結果を受ける。落ちたら、貼られた文から直す。あやしい順に:
   (a) `release/MeichoSimLauncher.spec` の「標準ライブラリを丸ごと hiddenimports に入れる」部分（Windows 固有のモジュールで `collect_submodules` が転ぶ可能性。転んだモジュールを `SKIP` に足すのが最小の直し）
   (b) `mslauncher/main.py::port_free` の Windows の枝（`SO_EXCLUSIVEADDRUSE`。未検証）
   (c) 端末の文字コード（cp932）。`errors="replace"` は入れたが未検証
   (d) 保護機能・ウイルス対策ソフト。コードでは直せないので、説明書 `release/README_配布.txt` の書き足しになる
2. **更新元の置き場所**（マスターの裁定待ち）。基本設計 (4)「サーバの置き場所の比較」と同じ問いなので、そこで一緒に比べるのがクロエの推し。要件: 知人が起動したときにいつでも届く・静的ファイルが置ければ足りる・D-074 の 3 線（特定少数・再配布なし）と公開 URL の折り合い。決まったら `publish init --feed-url https://…` → `launcher` を作り直す。`--after` に置き場へのアップロード命令を覚えさせる
3. 基本設計書を Claude Docs に作る（未作成。APP-004・006・007・009・010 の内容を写す）
4. マスターから数字か感想が来たら、演出の速さ（`static/css/tokens.css` の `--fx-*`）を直す
5. その先は M6（デッキメーカーと素材パック）。先取りしない

## 2. このチャットで決めたことと理由（本文は APP-006〜APP-010）

- M3 盤面: 配置は公式プレイマットに合わせる・協奏のカードは横向き（マスターの指示）
- M4: 出来事はエンジンのトレース点から「起きた順」に作る。公開して手札に加えたカードは相手と観戦者に表向きで見せ続ける（`public_known`。実際の手札と突き合わせない——突き合わせるとどの札が出たかが漏れる）
- M5 前半: AI は「席に座る参加者の 1 種」。登録簿 `webapp/agents.py` を通して作る。SD02 のつよいは `planner_lh` のまま
- M5 後半: 2 層（起動役 `mslauncher`＝標準ライブラリだけ／中身＝版フォルダの素のファイル）。中身は子プロセスで動かす。署名は Ed25519 を標準ライブラリだけで実装。目録と署名は 1 ファイル（`latest.json`）。中身は sha256 で名付ける。`seq` が今より大きい版しか取り込まない。
  秘密鍵は `%USERPROFILE%\.meichosim\signing_key.txt`（リポジトリと OneDrive の外）、公開鍵は `app/mslauncher/pubkey.txt`（起動役の側）

## 3. 却下した案・撤回した結論（再提案しない）

- **起動役に `cryptography` を入れる** → 却下。起動役はめったに配り直さないので外部ライブラリの版に縛られたくない。Ed25519 は 1 起動に 1〜2 回で、純 Python で 8 ミリ秒
- **中身を起動役と同じプロセスで動かす** → 却下。新しい版が import で落ちたときに、前の版へ戻す側まで一緒に落ちる
- **目録 `manifest.json` と署名 `.sig` を別ファイルにする** → 却下。静的な置き場では 2 つを同時に差し替えられず、半端な瞬間に検証が落ちる
- **公開鍵の置き場を環境変数で差し替えられるようにする（検査のため）** → 却下。配布版に抜け道が残る。検査は `publish.LAUNCHER_PARENT` を一時フォルダの写しに差し替える形にした
- **`make_dist.verify` を写して持つ** → 却下（APP-002）。import して呼ぶ
- **（撤回）子プロセスを `python -m app.mslauncher.main --child` で起動する** → 書いてすぐ撤回。開発ツリーの `app` が先に読み込まれ、版フォルダの `app.server` に届かない。固めたときも同じで、固めた `app` が版フォルダの `app` を隠す。
  だから起動役は最上位の `mslauncher` として動かす（固めていないときは `python -c` の小さな起動文で `engine/app` を import 経路に足す）
- **（撤回）更新元に届かなかったことをホームに警告で出す** → 出してみて撤回。繋がっていないのは普通のことなので、ホームでは騒がず設定画面にだけ出す。ホームに出すのは「取り込み失敗」「一つ前に戻した」「新しい起動役が必要」
- **（撤回）`selfcheck.py` の CPU の段を `level: 1` で「やさしい」とした** → 段は 0・1・2。0 がやさしい。直した

## 4. 落とし穴

- **OneDrive の書き戻し**: 「written」でも中身が古いままのことがある。今回の 25 ファイルは 1 回で全部載ったが、前の回までに `WRITELOG_APP.md` で 3 回起きた（行の長さが同じだとサイズも同じで、`cmp` でしか分からない）。手順は `LANES.md` §5
- **`device_commit_files` の `stagedPath` は `/mnt/user-data/outputs/…` で書く。**`os.path.abspath` は `/mnt/attach/outputs/…` を返すので、そのまま渡さない
- **`publish init` はリポジトリの `app/mslauncher/pubkey.txt` を書く。**作業環境で試した鍵を PC に書き戻してはいけない（今回は書き戻す前に消した。PC に `pubkey.txt` は無く、マスターの `init` で初めてできる）。検査は本物の `pubkey.txt` に触らない作りにしてある
- **直前に終了したサーバのポートを「使用中」と見誤った**（Linux の TIME_WAIT）。`port_free` に `SO_REUSEADDR` を入れて直した。Windows の枝は別の書き方で、未検証
- **起動役だけを止めると子（サーバ）が残った** → SIGTERM／SIGBREAK で子も止めるようにした。タスクマネージャで起動役を殺した場合は今も残る（次の起動は「すでに起動している」でブラウザを開くだけ）
- **作業環境の写し（`/home/claude/work/engine`）は PC の全部ではない。**`experiments/arena.py` などが無いので、組み立ての「66 ファイル」は作業環境だけの数。PC では増える。数を検査に書かない
- **`make_dist.verify` は `tests`・`cards` という名前のフォルダと `*.md` をどこにあっても落とす。**アプリ側の allowlist（`publish.APP_ALLOW`）に足すときは気を付ける
- 作業環境で `pkill -f <語>` を打つと、その語を含む自分のシェルも死ぬ（終了コード 144）。PID で止める
- 作業環境は消える。次のチャットで写しが無ければ、PC から `engine/app/`・`engine/meicho/`・`engine/webapp/`・`engine/experiments/`（registry・champion・arena）・`engine/scripts/`・`engine/decklists/`・`engine/results/models/`（champion のモデル）・`engine/rules_draft.md` をステージし直す。PyInstaller と Playwright も入れ直しになる

## 5. 再開に要る外部資源

- PC のフォルダ `C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1` への接続（次のチャットで許可の取り直しが要ることがある）
- Claude Docs: 計画書 `36c70594-96e6-4ff6-be45-9c160699273c`／要件定義書 `644bd767-54a9-4b24-8a93-0ad439d4359a`。基本設計書は未作成
- マスターの PC にだけあるもの（まだ無い。依頼書を回すとできる）: 秘密鍵 `C:\Users\奥村優斗\.meichosim\`／更新元のフォルダ `C:\meicho_dist\feed`／起動役 `C:\meicho_dist\launcher`
- 作業環境で固めた Linux 版の起動役と、設定画面の画面写真は使い捨て（残っていなくてよい）

## 6. 確かめていないこと

Windows でのビルドと起動／保護機能とウイルス対策ソフトの反応／本物の HTTPS の置き場からの更新（検査はフォルダと、届かない URL だけ）／遅い PC で起動待ち 60 秒が足りるか／PC の `rules_draft.md` の版／マスターの PC での CPU の思考時間（記録の `times` に残る）
