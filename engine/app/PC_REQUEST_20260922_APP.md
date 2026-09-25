# PC への依頼（アプリの持ち場）: 更新元を Cloudflare Pages に出し、合言葉つきの起動役を作り直す（2026-09-22）

- **所要時間の見込み**: 30〜45 分（うち PyInstaller が数分、Cloudflare へのログインと最初のアップロードが数分。測っていない）
- **急ぎ度**: 中（知人に配る前に要る。エンジンの作業は止めない。エンジンの持ち場の未実施の依頼書は無い——`REBUILD_REQUEST_20260921.md` は完了済み・`LANES.md` §7）
- **なぜ今これが要るのか**: 2026-09-21 の裁定（APP-011）で、更新元は Cloudflare Pages に置き、合言葉で守ると決まった。道具と門番は作業環境の模擬環境で確かめたが、
  **本物の Cloudflare には一度も出していない。**また、2026-09-21 に固めた起動役は合言葉を送らない版なので、配る前に作り直しが要る。Windows での新しい検査 11 件もまだ回っていない。
- 道具はコマンドプロンプト（cmd）。PowerShell ではない。
- この依頼で決め打ちにしている名前: プロジェクト名 **`meichosim-hhdmauhgjr`**（URL の一部になる。当てにくいようにクロエが乱数で作った。変えたければ、下の全部の行で同じ名前に読み替える）

## 1. どこで

2 か所を行き来する。**wrangler（Cloudflare の道具）は必ず `C:\meicho_dist\site` で打つ**（打った場所に `.wrangler` という作業フォルダを作るので、OneDrive の中のリポジトリで打たない）。

    A: C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine     （py -3.11 の行）
    B: C:\meicho_dist\site                                                                      （wrangler の行）

## 2. 何を打つか（上から 1 行ずつ）

### 2.1 準備と検査（A）

    cd /d "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine"
    node --version
    py -3.11 -m pytest app\tests\test_release.py -q
    xcopy /E /I /Y C:\meicho_dist\launcher\dist\MeichoSim\data C:\meicho_dist\data_backup_20260922
    mkdir C:\meicho_dist\site\public
    xcopy /E /I /Y app\release\feed_host\functions C:\meicho_dist\site\functions

`xcopy` の 1 本目は、2026-09-21 に打った対局の記録の控えである（このあと起動役を作り直すと、前の出力フォルダは中身ごと消える）。

### 2.2 Cloudflare の側（B）

    cd /d C:\meicho_dist\site
    npm install -g wrangler
    wrangler login
    wrangler pages project create meichosim-hhdmauhgjr --production-branch main

`wrangler login` はブラウザが開くので、作ったアカウントでログインして「Allow」を押す。
`project create` の最後に出る URL（`https://meichosim-hhdmauhgjr.pages.dev/` のはず）を控える。**違う URL が出たら、以後の `--feed-url` はそちらを使う。**

### 2.3 合言葉を作り、置き場に教える（A → B）

    cd /d "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine"
    py -3.11 -m app.release.publish init --feed-dir C:\meicho_dist\site\public --feed-url https://meichosim-hhdmauhgjr.pages.dev --feed-key new --after "wrangler pages deploy public --project-name meichosim-hhdmauhgjr --branch main --cwd C:\meicho_dist\site"
    type %USERPROFILE%\.meichosim\publish.json

`type` で出た中の `"feed_key": "……"` の **引用符の中身だけ**をコピーする（cmd では、マウスで選んで Enter）。続けて:

    cd /d C:\meicho_dist\site
    wrangler pages secret put FEED_KEY --project-name meichosim-hhdmauhgjr

「Enter a secret value:」と聞かれたら、コピーした合言葉を貼り付けて（右クリック）Enter。**貼った文字は画面に出ない**のが正常である。

### 2.4 公開して、起動役を作り直す（A）

    cd /d "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine"
    py -3.11 -m app.release.publish release --notes "Cloudflare Pages への最初の公開"
    py -3.11 -m app.release.publish launcher --out C:\meicho_dist\launcher --author "オクソン"

そのあと、エクスプローラーで `C:\meicho_dist\launcher\MeichoSim_launcher1_<版>.zip` を右クリック →「すべて展開」→ 展開先を `C:\meicho_dist\play` にする。
**これからは `C:\meicho_dist\play\MeichoSim\MeichoSim.exe` で遊ぶ**（知人と同じ「zip を展開して起動する」形。`launcher` の出力フォルダは作り直すたびに消えるので、そこで遊ばない）。
前の対局の記録を引き継ぐなら、`C:\meicho_dist\data_backup_20260922` の中身を `C:\meicho_dist\play\MeichoSim\data` に写す（任意）。

### 2.5 https 越しの更新を試す（A）

`C:\meicho_dist\play\MeichoSim\MeichoSim.exe` を 1 回起動して閉じてから:

    py -3.11 -m app.release.publish release --notes "置き場からの更新の試し" --force

もう一度 `C:\meicho_dist\play\MeichoSim\MeichoSim.exe` をダブルクリックする。

## 3. 成功したらどう見えるか

- `node --version`: `v18` 以上の番号が出る
- `pytest`: 最後の行が `44 passed`（`cryptography` が入っていなければ `43 passed, 1 skipped`）。2026-09-21 は 33 件だった。増えた 11 件が合言葉の検査である
- `project create`: 「Successfully created the 'meichosim-hhdmauhgjr' project.」と URL
- `init`: 「秘密鍵はすでにある（作り直さない）」「公開鍵: 009897114d60…」（2026-09-21 と同じ鍵）「更新元の合言葉を覚えている。…」
- `secret put`: 「Success! Uploaded secret FEED_KEY」
- `release`: `[1/5]`〜`[5/5]` のあとに「続けて実行: wrangler pages deploy …」、wrangler の「Deployment complete!」、最後に「公開した: 版 2026.09.22-1」（版の番号は新しい置き場なので 1 から）
- `launcher`: 「実行ファイルの煙テスト: OK」「固めたフォルダの走査: 合格」「配る zip: …」
- 2.5 の 2 回目の起動: 黒い窓に「新しい版 … を取り込む」「版 … に更新した」

## 4. 確認のしかた

1. ブラウザで `https://meichosim-hhdmauhgjr.pages.dev/latest.json` を開く →「Not found」（404）になる。**これが正しい**（合言葉を持たない人には何も見せない）。目録の JSON が見えてしまったら、門番が効いていないので知らせてほしい
2. `C:\meicho_dist\play\MeichoSim\launcher.json` をメモ帳で開くと、`"feed": "https://…pages.dev"` と `"feed_key": "…"` の 2 つが入っている
3. 2.5 のあと、ホームの一番下の「設定・版と更新の履歴」→「版と更新」→「更新の履歴」に「置き場からの更新の試し」と「Cloudflare Pages への最初の公開」の 2 行がある
4. CPU と 1 局打てる（やさしいでよい）

## 5. 転びやすいところと症状

- `node` が「認識されていません」→ Node.js が入っていない。https://nodejs.org/ から LTS 版を入れて、cmd を開き直す
- `wrangler` が「認識されていません」（`npm install -g` のあと）→ cmd を開き直す。それでもだめなら、`wrangler` をすべて `npx wrangler` に読み替える（`init` の `--after "…"` の中も）
- `wrangler login` でブラウザが開かない → 窓に出た URL をブラウザに貼る
- `project create` が「メールアドレスの確認が要る」という意味の英語で止まる → Cloudflare から届いた確認メールのリンクを押してから、もう一度
- `project create` が「already exists / 名前が使われている」→ 名前の末尾を 1 文字変えて、以後の全部の行で同じ名前にする
- `secret put` が「デプロイが無い」という意味の英語で断る → 順番を入れ替える。先に 2.4 の `release` を打ち、次に `secret put`、最後に `release --notes "門番を効かせる" --force` をもう 1 回（秘密の設定は、その後の配置から効く）
- `release` の最後で「NG: 置き場への送り出しが失敗した」→ wrangler の赤い文をそのまま知らせてほしい（**ここがいちばんあやしい**。`--cwd` つきの `pages deploy` は本物では試していない）。手元の更新元フォルダは新しい版になっているので、直ったら `cd /d C:\meicho_dist\site` → `wrangler pages deploy public --project-name meichosim-hhdmauhgjr --branch main` だけをやり直せばよい
- 4 の 1 で JSON が見えてしまう → `C:\meicho_dist\site\functions\_middleware.js` があるか確かめる（`public` の中に置いていないか）。あるのに見えるなら知らせてほしい
- 2.5 で「更新しなかった: 更新元に届かない（HTTPError）」→ 合言葉が置き場と合っていない。`secret put` をやり直し、`release --force` をもう 1 回。それでもだめなら知らせてほしい
- 2.5 で「更新元に届かない（URLError）」→ ネットワークか URL。`launcher.json` の `feed` をブラウザで開いて 404 が返るか（＝届いてはいる）を見る
- `launcher` で「--out が空でない」→ `C:\meicho_dist\launcher` 以外を指している
- exe で「ポート 8765 を別のプログラムが使っている」→ 前の黒い窓（`launcher\dist` の側の exe を含む）が残っていないか確かめる
- 文字化け → 動作には影響しない。化けた行があれば知らせてほしい

うまくいかないときは、黒い窓に出た文をそのまま貼ってもらえれば足りる。**合言葉（`feed_key` の値）だけは貼らない**（伏せ字にする）。
