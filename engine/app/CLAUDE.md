# engine/app/CLAUDE.md — オンライン対戦アプリ（MeichoSim）の持ち場の案内

2026-09-28 から、アプリの実装は Claude Code が行う（APP-027）。この文書は、`engine/app/` で作業する Claude Code が最初に読む 1 枚である。
リポジトリ直下の `CLAUDE.md` はエンジンの持ち場の書き物で、用語・罠の多くはそちらにある。両方を読むこと。この文書の書き手はアプリの持ち場である（`LANES.md` §1）。

## 1. 始めにやること（毎回・この順）

1. `git pull --rebase`（正本は GitHub の `main`・D-136）。`git status` が空であることを見る。空でなければ、何が残っているかをマスターに見せてから進む
2. `LANES.md` を読む（持ち場の決まり）。**アプリが書くのは `engine/app/` の下だけ**
3. エンジンからの送り箱 `engine/TO_APP.md` を読み、`TASKS_APP.md` から参照されていない TA 項目があれば最初の報告で挙げる
4. `engine/app/TASKS_APP.md`（状態の正本）→ 最新の `engine/app/HANDOFF_*_APP.md` → 要るところだけ `DECISIONS_APP.md`

## 2. 持ち場（`LANES.md` の要約。食い違えば `LANES.md` が正）

- 書いてよい: `engine/app/**`（コード・検査・文書）
- 書かない: `engine/meicho/`・`engine/webapp/`・`engine/experiments/`・`engine/scripts/`・`engine/rust/`・`engine/tests/`・`rules_draft.md`・`decisions.md`・`TASKS.md`・`CLAUDE.md`（直下）・`LANES.md`・`engine/TO_APP.md`。誤字 1 つでも直さない
- エンジンに直してほしいこと・知らせたいことは `engine/app/TO_ENGINE.md` に TE-番号で書く（通し番号・日付・内容・欲しい結果・急ぎ度）
- 受けた TA 項目は `TASKS_APP.md` に「TA-n を受けた」と書く。エンジンの送り箱には印を付けない。こちらの TE 項目は、エンジンの `TASKS.md` に「終えた」とあるのを見てから `TO_ENGINE.md` で「済」にする
- アプリの決定は `DECISIONS_APP.md` に APP-番号で書く（次の番号は末尾を見る）。D-番号は振らない
- **台帳を書くのは同時に 1 人**（D-137）。Cowork のクロエが台帳を書いている間は書かない。迷ったらマスターに聞く

## 3. commit と push

- Claude Code（PC）: `main` で作業してよい。push の直前に必ず `git pull --rebase`。エンジンの Claude Code も同じ `main` に push するので、ここを抜くとぶつかる
- Claude Code（クラウド）: ブランチ `app/<語>` に push する。`main` への merge は PC の Claude Code かマスター（`engine/DEVFLOW_PLAN_20260925.md` §0.1）
- 1 commit は 1 つのまとまり（1 つの APP-番号か、1 つの直し）。要約の頭に `app:` を付ける
- 作業の終わりに `git status` が空で、push し残しが無いことを見る
- Cowork のクロエが接続フォルダ（`C:\dev\meicho_engine_v0.1`）に書いた文書は、作業ツリーの「未 commit の変更」として現れる。中身を見てから commit する

## 4. 権利と秘密（**リポジトリは Public である**）

- `cards/` は `.gitignore` で丸ごと外してある。**カード画像・公式テキストを `engine/app/` に置かない・commit しない**。検査も `cards/` を要らない作りにしてある（要る検査を足さない）
- カード画像は、知人へ**直接・私的に**渡すことだけが許されている（APP-020）。配布版・更新元（Cloudflare Pages）・対戦サーバには載せない。公式から注意があれば取り下げる
- 配るページに `http` を含めない・公式サイトの URL を載せない・「非公式」を名乗る（検査 `test_pages_carry_no_official_assets_and_say_unofficial`）
- 秘密はリポジトリの外にある: 署名の秘密鍵 `%USERPROFILE%\.meichosim\signing_key.txt`・更新元の合言葉 `~/.meichosim/publish.json`。**合言葉・鍵・トンネルの URL を文書にもコードにも書かない**。出力を貼るときは合言葉を伏せる
- `app/mslauncher/pubkey.txt` はマスターの本物の公開鍵である。作業環境で `publish init` を打つと書き換わるので、その変更を commit しない
- 起動役の出力（`publish launcher --out`）はリポジトリの外（`C:\meicho_dist\…`）。`dist/`・`build/` を commit しない
- 本名を含む Windows の経路を新しく書かない（`C:\Users\<ユーザー名>\…` と書く）

## 5. 構成

- `server.py`: aiohttp のサーバ。Hub・部屋の掃除（APP-021: 上限 4 部屋・空いた部屋の猶予）・`origin_guard`（Host と Origin の検査・APP-012）・手元起動だけの口 `_local_only`（CPU 対戦・記録の一覧・リプレイ）
- `core/`: `room.py`（部屋）／`game.py`（`Game._advance` がエンジンのトレース点から出来事を作る）／`views.py`（`view_for`・`diff_events`・`visible_cards`・`effect_stack`）／`cpu.py`（AI の席）／`persist.py`（記録・版の照合）／`replay.py`（当て直し）／`protocol.py`・`describe.py`・`hints.py`・`release.py`
- `static/`: `index.html`・`deck.html`、`js/`（`board.js` 盤面・`fx.js` 演出・`intents.js`・`net.js`・`replay.js`・`deckcode.js`・`settings.js`・`sfx.js`・`help.js` ほか）、`css/`（`tokens.css`・`app.css`・`deck.css`）
- `mslauncher/`: 配布版の起動役（標準ライブラリだけ・`app`・`meicho`・`webapp` を import しない）
- `release/`: 公開の道具 `publish.py`（init・release・launcher）と更新元の門番 `feed_host/`
- `start_local.bat`・`start_friends.bat`: マスターの PC でサーバを立てる bat（APP-031）。CRLF・UTF-8（`.gitattributes` で CRLF に固定）。配布版には入らない。静的な検査は `tests/test_launch_bat.py`
- `tests/`: `test_server.py`・`test_room.py`・`test_game.py`・`test_cpu.py`・`test_replay.py`・`test_release.py`・`test_ui.py`（Playwright で本物のブラウザを動かす）
- エンジンから使っている口: `meicho` の純粋関数とトレース点（`meicho/trace.py`・D-114）、`webapp/view.py` の 3 関数、`webapp/agents.py`、`webapp/record.py`、`scripts/make_dist.py`、`experiments/registry.py`・`champion.py`（TE-7〜TE-12 で知らせ済み）

## 6. 設計の約束（破ると事故になるもの）

- **見せてよい情報は `visible_cards(view)` を通す。**伏せ札の番号を出来事・効果の一覧・ダメージの出どころに載せない（APP-016・APP-023・APP-024）。新しい表示を足したら、見えない視点で番号が出ないことを検査で確かめる
- **サーバが正、画面は並べるだけ。**合法手・結果の判定を画面で作らない。リプレイもサーバが当て直す（APP-019）
- 出来事は `Game._advance` のトレース点から起きた順に作る。対局中とリプレイで一字一句同じになる
- **演出の時間は `static/css/tokens.css` の `--fx-*` に集める。**JS に数字を直書きしない（APP-024）
- `KNOWN_SETS` = ["SD01","SD02","BP01"] は**後ろに足すだけ**（並びがデッキコードの符号の一部・APP-018）
- 記録には版（app_version・rules_version・cards_version）が付く。版の違う記録は再生を断る
- ルールの解釈はしない。ルールの疑いはエンジンへ送る（TE-13 の例）。rules の版は `meicho/version.py` の `RULES_VERSION` から取る
- 棋譜の送信は既定で送らない。送り先（Worker＋R2）ができるまで同意の初回画面を作らない

## 7. 検査

- 回し方（`engine/` を作業場所に）: Linux・Git Bash は `PYTHONPATH=. python -m pytest app/tests -q -p no:cacheprovider`。コマンドプロンプトは `set PYTHONPATH=%CD%` を打ってから `python -m pytest app/tests -q -p no:cacheprovider`。全体で 4〜5 分
- 要るもの: `pip install -r app/requirements.txt` と `playwright`（Chromium が要る）
- **`test_ui.py` は Playwright が無いと丸ごと skip になる。skip は「通った」ではない。**画面を触った変更は、`test_ui.py` が実際に走った（skip 0）ことを見てから完了にする。PC に Playwright が無ければ入れるか、クラウドで回す
- 2026-09-25 の時点で作業環境（Linux）で 121 件通過。**Windows で全体を回したことはまだ無い**（最初の 1 回は、落ちたものを 1 件ずつ理由まで読む）
- 検査の揺れは時間ではなく局の中身で止める条件を書く（APP-015）。`FX_SEED` で局を固定している
- 画面の検査の決まり: `Rig` はページを移るたびに設定を入れ直す（途中で変えたいなら画面の上で）／`first_visit` の既定は「遊び方を見た」扱い／リプレイを開くと `#board` の id が二重になるのでセレクタは `#layer-replay` の中に絞る／重なったカードは `.last` をホバーする／効果の一覧（`.effects`）は `pointer-events:none`
- `pkill -f <語>`／`pgrep -f <語>` は自分のシェルも殺す。止めるのは PID で
- 検査の件数を文書やコードに書き込まない（環境で変わる）

## 8. 改行コードと文字

- `engine/app/` の文書（`.md`）は **CRLF**、コード（`.py`・`.js`・`.css`・`.html`）は **LF**。書く前に確かめ、書いたあと `git diff --stat` で全行が変わっていないことを見る
- CRLF のファイルを `sed -i` で触らない（LF に化ける）。Edit の道具か、`open(..., "rb")` のバイト処理で直す
- 日本語 Windows の cp932 で落ちる文字（`π₀` の `₀` など）を、コンソールに出す文字列に使わない

## 9. 台帳の書き方

- `TASKS_APP.md`: Active／Waiting On／Done。終えたら Done に 1 行（日付・APP-番号・何を確かめたか）
- `DECISIONS_APP.md`: `## APP-0NN <題>（日付・きっかけ／実装は誰）`。本文は「作り」「確かめたこと」「確かめていないこと」を分けて書く
- `WRITELOG_APP.md`: 台帳 3 種（`TASKS_APP.md`・`DECISIONS_APP.md`・`TO_ENGINE.md`）を書いたら、その行を `- <パス> | <バイト数> | <sha256 の先頭 12 桁> | <JST の時刻>` に置き換える（`LANES.md` §5.3。時刻は `TZ=Asia/Tokyo date`）

## 10. マスターとのやりとり

- 返事は簡潔に・表を使わない（マスターはスマホで読むことが多い）。数字には基準と n を付ける
- 判断が要る点は推測で埋めず、選択肢と推しを並べて聞く。マスターは原則として推しを採る（D-069）
- マスターに手を動かしてもらう依頼（実機のブラウザ・スマホ・知人との対戦）は、チャットに全文で書く: どこで・何を打つか・成功の見え方・確かめ方・引っかかりやすい所の 5 点と「なぜいま」の 1 行。「前と同じ手順で」と書かない
- Claude Docs の文書（計画書 `36c70594-96e6-4ff6-be45-9c160699273c`・要件定義書 `644bd767-54a9-4b24-8a93-0ad439d4359a`・基本設計書 `ac841c45-9b40-455a-8b1a-4dc573cc27f0`）は Claude Code から読める（2026-09-28 マスターが確かめた）。**要件は作る前に要件定義書の本文を読む。**書き込めるかはまだ確かめていない。最初に反映が要るときに試し、書けなければ `TASKS_APP.md` に残して Cowork のクロエに頼むようマスターに伝える
