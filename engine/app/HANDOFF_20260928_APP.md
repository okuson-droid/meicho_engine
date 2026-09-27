# 引継ぎ書（アプリの持ち場）2026-09-28: アプリの実装を Cowork から Claude Code へ移す。最初の仕事は送り箱の片づけと古い経路の置き換え、その次が M7 の棋譜の書き出しと取り込み

- 持ち場: **アプリ**（`LANES.md`）。読む人は Claude Code（PC 版を主とする）。最初に `engine/app/CLAUDE.md` を読むこと。この文書は台帳に収まらない文脈だけを書く
- 最初に読む順: `engine/app/CLAUDE.md` → `LANES.md` → `engine/TO_APP.md` → `engine/app/TASKS_APP.md`（状態の正本）→ この文書 → 要るところだけ `DECISIONS_APP.md`（**APP-020〜APP-027 が前の引継ぎ書のあと**）
- 準拠: rules **v0.19**（D-134・TE-13 の直し）。`meicho/version.py` の `RULES_VERSION` も同じ。通信の版 1・記録の版 3・`LAUNCHER_API` 1・符号化 v6（アプリは符号化に触れない）
- 前の引継ぎ書は `HANDOFF_20260923_APP.md`（その前に 0922b・0922・0921）。**そこに書いた落とし穴で今も効くものは `CLAUDE.md` §6〜§8 にまとめた。**Cowork 固有の落とし穴（OneDrive の書き戻し・`device_commit_files` の `stagedPath`）は Claude Code には関係しない

## 0. いまの状態

- 2026-09-23 から 09-25 に Cowork のクロエが実装したもの（本文は `DECISIONS_APP.md`）:
  - APP-020 知人との試しの対戦（固定の URL は Tailscale Funnel・カード画像は知人に直接渡す）
  - APP-021 部屋が残り続けて上限に当たる不具合（空いた時刻を保存して再起動をまたぐ・満室なら古い空き部屋を閉じる）
  - APP-022 知人戦の感想 4 件（先攻後攻の表示・対抗の提出の知らせ・対抗の見せ場・自動支払いのボタン）
  - APP-023 効果の解決の見える化（中央の帯の上の「効果 N 件」・解決中のカードの光り・帯の文の頭の【カード名】）
  - APP-024 演出の速さの第 1 回（手札の判明・効果の公開を長く・効果の解決の区切り）
  - APP-025 【レベルアップ】は下に重なった全部のカードで誘発する（今のまま・マスター裁定）
  - APP-026 場のキャラを選んでレベルアップ
  - APP-027 アプリの実装を Claude Code へ移す（この引継ぎ）
- 検査: 作業環境（Linux）で全体 121 件通過（2026-09-25・全体を 2 回続けて）。**Windows ではまだ一度も全体を回していない**
- 知人との対戦はマスターの PC のサーバ＋Tailscale Funnel で 1 回できた。APP-021〜026 は**配布版にまだ入っていない**（`publish release` を打っていない）
- 送り箱: エンジンの `TO_APP.md` に **TA-11（TE-13 を終えた・D-134）が届いていて、まだ受けていない**。TA-11 の 7. で「TA-9・TA-10 を受けた記録が見当たらない」と言われているが、記録は `TASKS_APP.md` の Waiting On の長い行の中にある（2026-09-22）。Done に 1 行立てて見つけやすくする
- 2026-09-27 にリポジトリが `C:\dev\meicho_engine_v0.1` に移った。**09-25 までに Cowork が書いた `engine/app/` の変更が commit 済みかは確かめていない**（§1 の 1）

## 1. 最初の仕事（この順で・1 つずつ commit）

1. **`git status` と `git log --oneline -5 -- engine/app` を見る。**`engine/app/` に未 commit の変更があれば、中身が APP-021〜027（と、この引継ぎ書・`CLAUDE.md`）であることを見て commit・push する。要約例「app: APP-021〜026 の実装と台帳（Cowork で作ったぶん）」
2. **検査を 1 回回す。**PC なら Playwright が入っているかを `python -c "import playwright"` で見て、無ければ `pip install playwright` → `python -m playwright install chromium`。回して、通過・skip・失敗の数と、失敗と skip の理由を 1 件ずつ報告する（`CLAUDE.md` §7）。Windows で初めての全体なので、落ちたら直す前にマスターに見せる
3. **TA-11 を受ける。**
   - `engine/` で `python -m pytest tests/test_te13_switched_scope.py -q`（TE-13 の再現局面: リーダー `BP01-018`・バック 1 `BP01-024`・バック 2 `BP01-008` で `{"type": "switch", "back": 1}` のあと、`BP01-008` の `use_optional` が出ない）が通ることを見る
   - `TASKS_APP.md` の Waiting On の TE-13 の行を消し、Done に「TA-11 を受けた。TE-13 はエンジンが D-134（rules v0.19）で直した。再現の検査が通ることを確かめた」と書く。同じく Done に「TA-9・TA-10 を受けた（2026-09-22。記録は Waiting On の行にあったものを移した）」
   - `TO_ENGINE.md` の TE-13 の見出しの状態を「**済**。D-134・TA-11 を確認して 2026-09-28 に閉じた」にする
   - `WRITELOG_APP.md` の 2 行（`TASKS_APP.md`・`TO_ENGINE.md`）を置き換える
4. **古い経路を置き換える。**`engine/app/` の中の `C:\Users\…\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1` を `C:\dev\meicho_engine_v0.1` に（`README.md` の 32 行目・94 行目あたり）。本名を含む経路が `HANDOFF_20260923_APP.md` などの古い文書にあれば `<ユーザー名>` に置き換える（リポジトリは Public・DEVFLOW §0.1 の条件）。`grep -rn "OneDrive" engine/app` と `grep -rn "Users" engine/app` で探し、`<ユーザー名>` になっていない経路を直す。`README.md` の「OneDrive の外に置く」という注意書き（`--data`・`--out`）は、意味が今も正しいので残す
5. ここまでで一度止め、マスターに報告する

## 2. その次（`TASKS_APP.md` の Active の順）

1. **M7: 棋譜の書き出しと取り込み（R-KIF-1・2）。****作る前に Claude Docs の要件定義書（`644bd767-54a9-4b24-8a93-0ad439d4359a`）で R-KIF-1・2 の本文を読む**（Claude Code から読める・2026-09-28 マスターが確かめた）。作りの見当（要件ではない）:
   - 記録 1 件は `data/games/YYYY-MM.jsonl` の 1 行。`persist.Store.get_record(rid)` で取り、`persist.record_problem(rec)` で版を確かめる
   - 書き出し: 手元の記録の一覧（`main.js` の `openRecords()`・`GET /api/records`）の行から 1 件をファイルにする
   - 取り込み: 読んだファイルを `record_problem` と `replay.build(dump, result)` に通し、通ればリプレイで開く。`build` は合法手・決定者・結果まで照合するので、改ざんや版違いは理由つきで落ちる
   - 手元起動だけの口（`_local_only`）にするかは要件の本文で決める
2. M7 の残り: 感想戦（R-REP-4）／「気になる」印とメモ（R-REP-5）／AI の候補と点数（R-REP-6・記録の `ai_clash`）／自動送信と初回の同意（R-KIF-3〜6・Worker＋R2）
3. マスターの感想待ち（来たら直す）: APP-022〜024・026 の見た目と使い勝手、演出の速さ（`--fx-*`）、CPU 対戦（つよい SD001）の手ごたえと待ち時間、スマホのダイアログの中の長押し（任意）
4. 小物: `persist.rules_version()` を `meicho.version.RULES_VERSION` に替える（公開の道具を次に触るとき）／`public_known`（APP-007 追記 1）を外すか決める（盤面の表示を次に触るとき・急がない）／Origin の無い `POST /api/rooms` を通している（APP-021 に記録・悪用が見えたら直す）
5. 配布版への反映: 次に `publish release` を打つと APP-021〜026 と TE-13 の直しが知人に届く。打つのはマスターの PC（PC の Claude Code が打ってよい。合言葉と鍵は `~/.meichosim` にある。出力を貼るときは合言葉を伏せる）
6. Claude Docs の基本設計書に APP-012〜027 を反映する。Claude Code から書き込めるかは未確認なので、ここで試す。書けなければ台帳に残し、Cowork のクロエに頼むようマスターに伝える
7. その先は M8。先取りしない

## 3. 決めたことと理由（今回ぶん）

- **アプリの実装は Claude Code が行う（APP-027・2026-09-28 マスター）。**理由: 正本が GitHub になり（D-136）、Cowork から接続フォルダへ書き戻して比べる手間が無くなる。PC の Claude Code ならサーバを立てる・実機のブラウザで開く・`publish` を打つ、まで 1 か所でできる
- Cowork のクロエに残るもの: 設計の相談・マスターの裁定が要る文書／知人との対戦の段取り（カード画像の手渡しなど）／Claude Docs の文書のうち、Claude Code が書き込めなかったもの（読むのは Claude Code もできる）
- 持ち場の決まり（`LANES.md`）は変えない。書き手が Cowork から Claude Code に替わるだけ。ブランチで持ち場を分けない
- 【レベルアップ】は下に重なった全部のカードで誘発する（APP-025）。**再び「不具合では」と言われても今のまま**。遊び方に書いてある
- 【切り替え】の不具合はアプリ側で直さずエンジンへ送った（TE-13）。ルールの疑いは今後も同じ扱い

## 4. 落とし穴（今回ぶん。常に効くものは `CLAUDE.md` に移した）

- **`replaceChildren(...)` に null を渡すと、スマホ幅で「null」という文字が出る。**`[...].filter(Boolean)` を通す（APP-023 で踏んだ）
- **盤面の上に重ねる表示は `pointer-events: none` にする。**効果の一覧がクリックを奪い、全体の検査が 1 回揺れた
- 対抗の見せ場でカードを裏返すとき、面を回すと文字が鏡に映った形になる。裏の要素を別に持ち、裏から表へ返す（APP-022）
- 新しい画面の検査が全体の中でだけ揺れたら、自動の打ち手を止めた直後の競り合い（ダイアログが開いている・演出の途中）を疑う。`settle()` で閉じて落ち着かせてから条件を見る（APP-026）
- Microsoft Store の Python は `%LOCALAPPDATA%` への書き込みを別の場所に移すことがある。サーバの `--data "%LOCALAPPDATA%\MeichoSim\data"` の部屋のファイルが `dir` で見えなかった。確かめ方は `README.md` にある（マスターの `where python` の結果はまだ無い）
- Tailscale の Tailnet の名前は自由に打てない（候補から選ぶ・証明書を出したあとは作り直せない）

## 5. 再開に要る外部資源

- リポジトリ `okuson-droid/meicho_engine`（Public）の `main`。PC の作業ツリーは `C:\dev\meicho_engine_v0.1`
- Claude Docs（Claude Code から読める・書き込みは未確認）: 計画書 `36c70594-96e6-4ff6-be45-9c160699273c`／要件定義書 `644bd767-54a9-4b24-8a93-0ad439d4359a`／基本設計書 `ac841c45-9b40-455a-8b1a-4dc573cc27f0`（APP-012〜027 は未反映）
- マスターのブラウザの中にだけあるもの: 画像（IndexedDB）・デッキと設定（localStorage）。オリジンごとに別（手元の `127.0.0.1` とトンネルの URL で別になる）
- マスターの PC の `data/games/*.jsonl`（記録の一覧とリプレイの元）・`~/.meichosim/`（署名の秘密鍵と合言葉）

## 6. 確かめていないこと

- Windows でのアプリの全検査（§1 の 2 で初めて回す）
- APP-022〜024・026 のマスターの実物での見た目と使い勝手（自動検査と画面の写しだけ）
- スマホでのダイアログの中の長押し・リプレイの操作・デッキコードの貼り付け
- 配布版の exe での APP-013〜026（`publish release` を打っていない）
- 09-25 までの `engine/app/` の変更が git に載っているか（§1 の 1）
