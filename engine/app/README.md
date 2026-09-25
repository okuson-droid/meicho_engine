# MeichoSim（オンライン対戦アプリ）

『鳴潮：対決』の**非公式**のファン製ツール。公式のカード画像・テキストを含まない。書き手はアプリの持ち場だけ（`LANES.md`）。
文書の正本は Claude Docs（計画書・要件定義書。URL は `DECISIONS_APP.md` の冒頭）。

## いまあるもの（M2: 通信層と部屋／M3: 盤面／M4: 演出・決着・音／M5: CPU 対戦・配布版と自動更新）

カードの画像はまだ無い（素材パックは M6）。

- `core/protocol.py` 通信の版・メッセージの種類・エラー
- `core/views.py` 席ごと・観戦者ごとの視点と、視点の差分から作る出来事
- `core/game.py` 1 局の進行（添字の提出・決定の番号・対抗の提出順・保存と復元）
- `core/room.py` 部屋（入退室・席・デッキ・先攻後攻・再戦・観戦）。通信に触らない
- `core/persist.py` 保存（開いている部屋と、終局した対局の記録）
- `core/describe.py` カードの表示データと合法手の日本語ラベル（言い換えの本体は `webapp/view.py` を import する）
- `core/hints.py` 「できない理由」の文（サーバが作る）
- `core/cpu.py` CPU 対戦の段の割り当て（やさしい・ふつう・つよい → 登録簿の名前）。AI の中身は持たず、`webapp/agents.py` の登録簿を通して作る
- `core/release.py` いま動いている版と更新の結果（設定画面に出すために読むだけ）
- `server.py` aiohttp のサーバ（画面のファイル・`/api/rooms`・`/api/cards`・`/api/decks`・`/ws`）
- `static/` 画面。ビルド不要の素の JavaScript（ES モジュール）。外部の配信元には一切つながない
  - `css/tokens.css` デザイン値と演出の時間はここ 1 か所／`js/intents.js` 合法手 → 所作 の対応表／`js/board.js` 盤面と入力／`js/main.js` ホーム・入室・ロビー
  - `js/fx.js` 演出（出来事を 1 拍ずつ再生する）／`js/sfx.js` 効果音（ファイルを持たず、その場で合成する）／`js/settings.js` 音と演出の設定
- `mslauncher/` **起動役**（配布版の実行ファイルに入る側）。標準ライブラリだけ。更新の確認・署名の検証・取り込み・切り替え・巻き戻し・子プロセスでの起動。`app`・`meicho`・`webapp` を import しない
- `release/` **公開の道具**（マスターの PC で使う）。`publish.py`（init・release・launcher）と、PyInstaller の設定・配布の説明書・更新元の置き場の門番（`feed_host/`）
- `selfcheck.py` 中身の煙テスト（公開の前と、固めた実行ファイルの確認に回る）
- `bot.py` 画面なしの自動クライアント（乱数で打つだけ。テストと手動確認用）
- `tests/` 検査。`test_ui.py` は本物のブラウザをマウスとタッチで動かす（Playwright が無ければ skip）

## 動かし方（Windows の PowerShell。`engine/` の直下で）

```
cd "C:\Users\<ユーザー名>\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine"
pip install -r app\requirements.txt
python -m pytest app\tests -q
python -m app.server --data "$env:LOCALAPPDATA\MeichoSim\data"
```

最後の行でサーバが立つ。**CPU 対戦**は、`--host` を付けずに（＝この PC の中からしか届かない形で）起動したときだけホームに出る。外から届く形（`--host 0.0.0.0`）では出ない（`--cpu on` で強制できる）。
ブラウザで `http://127.0.0.1:8765/` を開く。止めるときは PowerShell で Ctrl+C。
保存先（`--data`）は OneDrive の外に置くこと（対局の記録と部屋の状態が入る。同期の対象にしない）。

**1 台で 2 人ぶんを試すとき**は、2 人目を**シークレットウィンドウか別のブラウザ**で開く。同じブラウザの別タブは席の鍵を共有するので、
同じ人の開き直しとして扱われ、先に開いていた画面が止まる（仕様）。

同じ LAN のスマホから開くときは `--host 0.0.0.0` を足し、スマホで `http://<PC の IP アドレス>:8765/` を開く。

**トンネル越しに外から入るとき**（APP-011・APP-012）は、先にトンネルを立てて URL（`https://xxxx.trycloudflare.com`）を確かめ、その URL を `--allow-origin` に書いてサーバを立てる（`--host` は付けない。トンネルは PC の中の 127.0.0.1 へつなぐ）。
`--allow-origin` を書いた起動は外向きとみなし、CPU 対戦は出ない。Quick Tunnel の URL は立てるたびに変わるので、そのたびに書き直す。
書き忘れると、ブラウザに「知らない名前で届いたので断った」と出て、付けるべき引数が文の中に出る。環境変数 `MEICHOSIM_ALLOW_ORIGINS`（カンマ区切り）でも書ける。

```
cloudflared tunnel --url http://localhost:8765
python -m app.server --data "$env:LOCALAPPDATA\MeichoSim\data" --allow-origin https://xxxx.trycloudflare.com
```

**固定の URL で続けて遊ぶとき**（APP-020）は Tailscale Funnel を使う（無料・ドメイン不要・URL は `https://<マシン名>.<tailnet名>.ts.net` で固定）。
画像はブラウザの中にオリジンごとに保管されるので、URL が変わらなければ知人の画像の読み込みは 1 回で済む。窓を 2 つ使う（Funnel を先に立てる）:

```
tailscale funnel --https=443 127.0.0.1:8765
python -m app.server --data "%LOCALAPPDATA%\MeichoSim\data" --allow-origin https://<マシン名>.<tailnet名>.ts.net
```

- マスター自身も ts.net の URL で開く（招待リンクは開いている URL から作られる。画像もこの URL 用に 1 回読み込む）
- 遊ばないときは Funnel の窓を閉じる（`--bg` は使わない）。証明書の名前は公開の記録に載るので、立てると数分で自動の巡回が来る。守り（APP-012）が断るので害は無いが、窓に `refused` の行が流れる
- Tailnet name は候補から選ぶ形で、一度証明書を出すと作り直せない。マシン名は身元につながらない名前にする

**部屋の上限と掃除**（APP-021）: 部屋は 4 つまで（R-NF-5）。全員が切れてから 30 分（対局の途中なら 24 時間）で閉じる。
この時刻は保存されるので、サーバを立て直しても数え直さない。上限に当たったときは、誰もいなくなって 2 分以上たった部屋（対局の途中なら 30 分以上）を古い順に 1 つ閉じて場所を空ける。

**保存先が見えないとき**: Microsoft Store 版の Python は `%LOCALAPPDATA%` への書き込みを
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.xx_…\LocalCache\Local\…` へ振り替えるので、`dir` では見えないことがある（`where python` の結果に `WindowsApps` があれば Store 版）。
中身を見たり消したりするときは Python から行う（例: `python -c "import glob;print(glob.glob(r'%LOCALAPPDATA%\MeichoSim\data\rooms\*.json'))"`）。

## カード画像（APP-013）

アプリはカードの画像を 1 枚も持たない。**設定 →「カード画像」→「フォルダを選ぶ」で、手元の `cards` フォルダを選ぶ**と、ファイル名の先頭のカード番号（`BP01-001_…png`）で対応づけて盤面と拡大に出す。
`parallel/` の別版（`-R`／`-SP`／`-PR`）も入るが、盤面には通常の版を出す。画像はそのブラウザの保管領域（IndexedDB）にだけ入り、次からは自動で出る。サーバにも相手にも送らない（相手の画面の画像は、相手が自分で読み込んだもの）。
ブラウザや端末を替えたら読み込み直す。方式はデッキメーカー（アーティファクト版）と同じ。

## デッキメーカー（APP-014）

ホームの「デッキを組む」（`/deck`）。アーティファクト版「鳴潮：対決 デッキメーカー」と同じ仕様・同じ画面で、組んだデッキはロビーのデッキ選択にそのまま出る。
カードの一覧はアプリが持つ（エンジンが遊べる番号だけ）。「データ」から手元の `cards/cards_structured.json` を選ぶと、属性・武器・所属・レアリティ・公式のテキストを重ねる（このブラウザにだけ保管）。
画像は上の「カード画像」と同じもの。書き出しはブラウザの普通のダウンロード。

## 配布版と自動更新（APP-010。Windows のコマンドプロンプト。`engine/` の直下で）

配布物は「起動役」（実行ファイル。めったに変わらない）と「中身」（エンジン・アプリ・画面・AI・モデル。自動更新で入れ替わる）の 2 層。

### 最初の 1 回

```
cd /d "C:\Users\<ユーザー名>\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine"
py -3.11 -m pip install -r app\requirements.txt pyinstaller
py -3.11 -m pytest app\tests\test_release.py -q
py -3.11 -m app.release.publish init --feed-dir C:\meicho_dist\feed --feed-url C:\meicho_dist\feed
py -3.11 -m app.release.publish release --notes "最初の公開"
py -3.11 -m app.release.publish launcher --out C:\meicho_dist\launcher --author "オクソン"
```

- `init` は署名の鍵を作る。秘密鍵は `%USERPROFILE%\.meichosim\signing_key.txt`。**控えを PC の外に 1 つ取る。誰にも渡さない。**公開鍵 `app\mslauncher\pubkey.txt` はリポジトリに入れてよい。
- `--feed-url` を手元のフォルダにしておくと、置き場を決める前でも自動更新を自分の PC で試せる。置き場が決まったら `init --feed-url https://…` をやり直し、`launcher` を作り直す。
- できあがり: `C:\meicho_dist\launcher\dist\MeichoSim\MeichoSim.exe`（試す用）と `C:\meicho_dist\launcher\MeichoSim_launcher1_<版>.zip`（配る用）。

### 更新元の置き場と合言葉（APP-011）

更新元は Cloudflare Pages に置き、合言葉で守る（2026-09-21 マスター裁定）。`init --feed-key new` で合言葉を作ると、`launcher` がそれを `launcher.json` の `feed_key` に書き、
起動役は要求ごとにヘッダ `X-MeichoSim-Key` で送る。置き場の側の門番と、置き場を作る手順は `release/feed_host/README.md`。
合言葉は暗号的な守りではない（起動役を持つ人は読める）。更新の正しさは引き続き署名が守る。

### 中身を更新するたび（AI の交代・カードの追加・画面の直し）

```
py -3.11 -m app.release.publish release --notes "変更点を 1 行で"
```

組み立て → 走査 → 署名 → 煙テスト → 更新元のフォルダへの配置、までを 1 回で行う。どこかで落ちたら公開されない。
置き場へのアップロードが要る場合は、`init --after "<命令>"` で覚えさせると最後に続けて実行する。知人の手元へは、次に起動したときに届く。

### 起動役を配り直すのは

Python 本体や外部ライブラリ（numpy・aiohttp）を入れ替えるとき・新しい外部ライブラリが要るとき・署名の鍵を替えるときだけ。
`mslauncher/__init__.py` の `LAUNCHER_API` を 1 上げて `launcher` を作り直し、中身は `release --launcher-api-min <新しい番号>` で公開する。古い起動役の人には「新しい起動役が必要」と出る。
