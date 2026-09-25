# 更新元の置き場（Cloudflare Pages）と合言葉の門番（APP-011）

2026-09-21 マスター裁定: 更新元は Cloudflare Pages に置き、合言葉で守る。
ここにあるのは置き場の側で動く門番 `functions/_middleware.js` と、置き場を作る手順である。
**配布物には入らない**（`publish.APP_ALLOW` に無い）。

## 何を守って、何を守らないか

- 門番は、ヘッダ `X-MeichoSim-Key` が秘密の設定 `FEED_KEY` と同じ要求にだけ中身を返す。違えば 404（何があるかを教えない）。
  `FEED_KEY` が未設定でも 404 にする（設定を忘れたまま公開しても、開いた状態にならない）。
- **暗号的な守りではない。**合言葉は配った `launcher.json` に平文で入っているので、起動役を持つ人は読める。
  守るのは「URL だけが漏れたときに、起動役を持たない人が中身を取れない」ことまでである。
- 更新の正しさ（偽の版を取り込まない・古い版へ戻されない）は、これまでどおり起動役の側の署名の検証と `seq` が守る。
  置き場が乗っ取られても、合言葉が漏れても、ここは破れない。
- 起動役が合言葉を送るのは、https の更新元と、自分の PC の中（127.0.0.1・検査と手元の試し）だけ。
  置き場が別のホストへ回したときは、回された先へ合言葉を持っていかない（`mslauncher/updater.py::_KeepKeyHome`）。

## フォルダの形（マスターの PC・OneDrive の外）

    C:\meicho_dist\site\
      functions\_middleware.js     このフォルダの functions\ を写す
      public\                      更新元のフォルダ（publish の --feed-dir）。latest.json・files\・manifests\

`functions\` を `public\` の中に置かない（静的ファイルとして配られてしまう）。

## 確かめたこと・確かめていないこと

- **確かめた（作業環境・2026-09-21）**: wrangler 4.136.0 の手元の模擬環境（`wrangler pages dev`）でこの門番を動かし、
  本物の `updater.update` をつないだ。合言葉なし → 404 →「更新元に届かない」で手元の版のまま／違う合言葉 → 同じ／
  正しい合言葉 → 取り込める。応答に `Cache-Control: private, no-cache` と `X-Robots-Tag: noindex, nofollow` が付く。
  `functions/_middleware.js` そのものは外から取れない（404）。
- **確かめた（マスターの PC・本物の Cloudflare Pages・2026-09-22）**: 下の手順で配置し、ブラウザ（合言葉なし）には 404、
  合言葉つきの起動役は https 越しに更新が入った（APP-011 追記 1）。`--after` から呼ぶ `--cwd` つきの `pages deploy` も通った。
- **確かめていない**: 合言葉を替える手順の通し／無料枠の 1 日 10 万リクエスト（Functions の呼び出しとして数えられる。
  起動 1 回で 1〜数十リクエスト）に知人の人数で収まること（収まる見込み）。

## 手順（2026-09-22 に実際に通ったもの。5 点セットの全文は `PC_REQUEST_20260922_APP.md`）

**wrangler は必ず `C:\meicho_dist\site` で打つ**（打った場所に `.wrangler` という作業フォルダを作るので、OneDrive の中のリポジトリで打たない）。

1. Cloudflare のアカウントを作る（無料）。Node.js を入れる。`npm install -g wrangler`
2. `cd /d C:\meicho_dist\site` → `wrangler login`（ブラウザで Allow）
3. `wrangler pages project create <名前> --production-branch main`
   名前は URL（`<名前>.pages.dev`）になる。当てにくい名前にする（`meichosim-` の後ろに乱数）。最後に出る URL を控える。
4. `engine` で: `py -3.11 -m app.release.publish init --feed-dir C:\meicho_dist\site\public --feed-url https://<名前>.pages.dev --feed-key new --after "wrangler pages deploy public --project-name <名前> --branch main --cwd C:\meicho_dist\site"`
5. `type %USERPROFILE%\.meichosim\publish.json` で `feed_key` の値を見て、`C:\meicho_dist\site` で
   `wrangler pages secret put FEED_KEY --project-name <名前>` に貼る（**最初の配置より前に入れる。**秘密の設定は、その後の配置から効く）
6. `publish release --notes "…"`（最後に置き場へ送り出される）→ `publish launcher --out C:\meicho_dist\launcher`（`launcher.json` に URL と合言葉が入る）
7. 確かめる: ブラウザで `https://<名前>.pages.dev/latest.json` が **404**。zip を展開した exe を起動 → `release --force` → もう一度起動して更新が入る。

`--branch main` を付けないと「プレビュー」の配置になり、秘密の設定が効かない環境に出てしまうことがある。
`wrangler` が見つからないときは `npx wrangler` に読み替える（`--after` の中も）。

## 合言葉を替えるとき

`publish init --feed-key new` → 手順 5 をやり直す → 配った全員に新しい `launcher.json` を渡す（実行ファイルの外にあるので、固め直さなくてよい）。
替えた直後から、古い `launcher.json` の人は更新が届かなくなる（遊ぶことはできる）。
