# 引継ぎ書（アプリの持ち場）2026-09-22: M5 後半を閉じた。基本設計を閉じた。更新元は本物の Cloudflare Pages で動いている。次はトンネル越しの対局

- 持ち場: **アプリ**（`LANES.md`）。書くのは `engine/app/` の下と Claude Docs の文書だけ
- 最初に読む順: `LANES.md` §0 の 4 つ → `engine/app/TASKS_APP.md`（状態の正本）→ この文書 → 要るところだけ `DECISIONS_APP.md`（**APP-011 と追記 1 が今回**）
- 準拠: rules **v0.18**（PC の実物の見出しで確認した。`meicho/version.py` の `RULES_VERSION` も同じ・TA-8）。通信の版 1。記録の版 3。起動役の版 `LAUNCHER_API` 1
- この文書は**台帳に収まらない文脈だけ**を書く。やること・待ちは `TASKS_APP.md`、決定の本文は `DECISIONS_APP.md`、設計の全体像は Claude Docs の基本設計書が正本
- アプリの引継ぎ書は 2 本目。前は `HANDOFF_20260921_APP.md`（そこに書いた落とし穴は今も有効。この文書は足した分だけを書く）。エンジンの系統（`engine/HANDOFF_20260921_ENGINE.md`）とは独立で、併読は要らない

## 0. いまの状態

- **M5 後半（配布版と自動更新）を閉じた。**2026-09-21 にマスターが Windows で固め、起動・CPU 対戦・手元のフォルダからの更新・更新後に記録が残ること・秘密鍵の控えまで確かめた
- **基本設計を閉じた。**基本設計書を Claude Docs に作った（§5）。(4) サーバの置き場所はマスター裁定「1〜4 全て推しを採用」（APP-011）: 対戦サーバ＝マスターの PC＋トンネル／更新元＝Cloudflare Pages／更新元に合言葉／棋譜の受け口＝Worker＋R2（作るのは M7）
- **更新元は本物の Cloudflare Pages で動いている**（2026-09-22・APP-011 追記 1）。プロジェクト `meichosim-hhdmauhgjr`。合言葉なしのブラウザには 404、合言葉つきの起動役は https 越しに更新が入る。マスターの報告は「CPU との対戦まで全て確認できた」で、
  依頼書 `PC_REQUEST_20260922_APP.md` §4 の 4 点が確かめられたと読んでいる（窓の文は、途中で落ちた 1 件と PyInstaller の冒頭しか受け取っていない）
- 検査: 作業環境で **87 件通過**（2026-09-21 夜・全部）。そのあと `test_release.py` に 2 件足して、配布と更新は **46 件通過**（全体は回し直していない。足したのは公開の道具の検査だけ）。
  マスターの PC で `test_release.py` が何件通ったかは**聞いていない**（依頼書の期待は 44。いまは 46 になる）
- 送り箱: エンジンの `TO_APP.md` は TA-8 まで受けた（台帳に記録済み）。こちらの `TO_ENGINE.md` は TE-3・TE-4 を「済」にした（D-117・TA-8 を確認）。頼みごとは出していない
- マスターはいま作業を抱えていない。もらえると進むもの: CPU 対戦（つよい SD001）の手ごたえと待ち時間の感想／演出の速さの数字

## 1. 次にやること

1. **`TASKS_APP.md` Active「トンネル越しの対局を試す」。**順番はこう考えている（マスターには提案済み・着手の了承はまだ）:
   (a) `server.py` に `Origin` の検査を入れる。**許すホスト名を設定（起動の引数か環境変数）で受ける形**にする——トンネルが TLS を終端するので、サーバは自分の外向きの名前を知らない。Quick Tunnel は URL が毎回変わるので、
   固定の名前を焼き込めない。手元起動（127.0.0.1）は今までどおり通す。検査を先に書く（`tests/test_server.py`）。WebSocket の接続（`/ws`）と、状態を変える HTTP の API の両方に掛ける。ここまでは作業環境で閉じる
   (b) マスターの PC で Cloudflare の Quick Tunnel（`cloudflared tunnel --url http://localhost:8765`。登録不要・URL は毎回変わる）を立て、別の回線（スマホ回線など）から招待リンクで 1 局。依頼書は 5 点セットで書く。
   見る点: WebSocket が通るか／切断復帰／遅い回線。**外から届く形の起動では CPU 対戦は出ない**（`--host` を付けた起動・APP-009）。配布版の起動役は `--host 127.0.0.1` 固定で子を起こすので、トンネル用の起動のしかた（開発ツリーから `python -m app.server --host …` か、起動役に口を足すか）を (a) の中で決める
   (c) 続けて使うなら固定 URL へ（Cloudflare の名前つきトンネル＝独自ドメインが要る／Tailscale Funnel＝無料・`…ts.net`。**Funnel は公式文書に WebSocket の可否の記載が無い**）
2. マスターから数字か感想が来たら、演出の速さ（`static/css/tokens.css` の `--fx-*`）を直す
3. `persist.rules_version()` を `meicho.version.RULES_VERSION` に替える（TA-8 の提案。後回しにした。公開の道具を次に触る便で一緒に行う。いまの作りで正しく動いている）
4. その先は M6（デッキメーカーと素材パック）。先取りしない

## 2. このチャットで決めたことと理由（本文は APP-011 と追記 1・基本設計書 7 章）

- **届けるものは 3 種類で、要るものが違う。1 か所にまとめない。**要件定義書の心配（PC＋トンネルだと更新も棋譜も PC が点いている間しか届かない）は、3 つを同じ場所に置く前提から来ていた
- 対戦サーバを PC＋トンネルにした理由: 前提（D-108）が「知人と通話しながら」で、遊ぶときはマスターがその場にいる／遊んでいない間は公開 URL に何も載らない／対戦サーバの URL はどこにも焼き込まれないので、後から Fly.io か VPS へ移す費用がほぼ 0
- 更新元を Cloudflare Pages にした理由: 無料・`*.pages.dev` でドメイン不要・リポジトリを公開しなくてよい。GitHub Pages は無料プランだと公開リポジトリが要り「再配布なし」の線に弱い
- **合言葉**: `launcher.json` の `feed_key` → ヘッダ `X-MeichoSim-Key`。送るのは https と自分の PC の中だけ／別のホストへ回されたら持っていかない／形のおかしい合言葉は無いものとして扱う／置き場の門番は `FEED_KEY` 未設定でも 404（開いた状態にならない）。
  **暗号的な守りではない**（起動役を持つ人は読める）。守るのは「URL だけ漏れたとき、起動役を持たない人が取れない」ことまで。更新の正しさは引き続き署名と `seq`
- `LAUNCHER_API` は 1 のまま（合言葉は中身が起動役に求めるものではない。配った起動役はまだ 1 つも無い）
- **運用の決まり**: wrangler は `C:\meicho_dist\site` で打つ（打った場所に `.wrangler` を作る）／マスターが遊ぶのは zip を展開した `C:\meicho_dist\play\MeichoSim`（`launcher --out` の出力は作り直すたびに消える）／窓の文を貼るとき合言葉は伏せる

## 3. 却下した案・撤回した結論（再提案しない）

- **Render の無料枠に対戦サーバ** → 却下。ディスクが消え「いつでも再起動しうる」ので、部屋の復元（R-NET-6）と記録を守れない
- **Oracle Cloud Always Free** → 却下。2026-06-15 に告知なしで A1 の枠が半減。OS・TLS の管理も要る
- **さくらの VPS・Fly.io** → いまは採らない（月額か運用の手間）。「マスター抜きで遊びたい」となったときの移り先として残す
- **GitHub Pages に更新元** → 却下（上の理由）
- **合言葉を署名つきの目録で配り直す** → 作らなかった。目録は合言葉の内側にあるので、合言葉が漏れた相手にも新しい合言葉が届き、守りにならない。替えるときは `launcher.json` を渡し直す
- **門番の `functions/` を更新元のフォルダ（`public/`）の中に置く** → 却下。静的ファイルとして配られてしまう。`C:\meicho_dist\site\functions\` と `…\public\` に分ける
- **（撤回）依頼書の wrangler を `npx wrangler` で書く** → `release --after` の中で「入れてよいか」の問いに止まる恐れがあるので、`npm install -g wrangler` して素の `wrangler` にした。`release/feed_host/README.md` も、実際に通った手順に直した（2026-09-22）
- **（撤回）`launcher` の出力フォルダを `shutil.rmtree(out)` で丸ごと消す** → Windows で落ちた（§4）。目印を残して 1 つずつ・待ってやり直す形にした
- 前の引継ぎ書 §3 の却下案（起動役に `cryptography`／同じプロセスで中身を動かす／目録と署名を別ファイル／公開鍵の置き場を環境変数で差し替え／`make_dist.verify` を写す）はそのまま有効

## 4. 落とし穴（前の引継ぎ書 §4 に足す分）

- **Windows の `rmtree` は、消した直後のフォルダで「アクセスが拒否されました」になることがある**（ウイルス対策・検索の索引・開いたままのエクスプローラーや cmd がつかんでいる）。Linux の作業環境では起きない。
  フォルダを消す道具は `publish.rmtree_patiently`（待ってやり直す）を使う。**「途中で止まったら次が進めなくなる」順序になっていないか**も見る（古い作りは目印を先に消していた）
- **OneDrive の書き戻し**: このチャットで 4 回起きた（`TASKS_APP.md` 1 回・`WRITELOG_APP.md` 3 回）。どれも「written」・更新日時だけ進む・中身は古い、で、2 回目で載った。`WRITELOG_APP.md` は行の長さが変わらずサイズが同じなので、`cmp` でしか分からない。コードのファイル（9 個まとめて）は 1 回で載った
- **相手の送り箱は、チャットの途中でも増える。**始めに見たあと TA-8 が足されていた（エンジンのチャットが並行して動いている）。PC への依頼書を出す前と、引継ぎの前にもう一度見る。`meicho/`・`webapp/` のファイルも途中で変わるので、検査の前に取り直す
- **`pgrep -f <語>`／`pkill -f <語>` は、その語を含む自分のシェルも殺す**（終了コード 144）。前の引継ぎ書に書いてあったのに、また踏んだ。止めるのは控えた PID で
- **Claude Docs の本文で `**太字。**続き` は太字にならない**（閉じの `**` の直後が日本語の字だと効かない）。太字は 1 行に独立させるか、後ろに空白を入れる
- 控え（`WRITELOG_APP.md`）の時刻は `TZ=Asia/Tokyo date` で取る。前のチャットの控えの時刻は実際の更新時刻と 40 分〜1 時間半ずれていた（中身は一致していたので実害なし）
- **作業環境は消える。**今回ステージし直して検査 87 件が回った組: `engine/app/` の全部（`__pycache__` 以外）／`engine/meicho/*.py`（23 個）／`engine/webapp/*.py`（9 個）と `webapp/static/` の 3 個／`engine/scripts/make_dist.py`／
  `engine/experiments/` の `registry.py`・`champion.py`・`arena.py`・`vb.py`／`engine/decklists/SD001.json`・`SD02.json`／`engine/results/models/` の `drl_sd001_s1.json`・`drl_sd001_vc4.json`・`pi_small64_e10.json`（champion の定義が指す 3 つ。合計 15 MB）／`engine/rules_draft.md`。
  入れ直すもの: `pip install --break-system-packages pytest pytest-asyncio aiohttp numpy`。Playwright と Chromium は作業環境に初めから入っていた。門番を試すなら `npm install -g wrangler` → `wrangler pages dev public --port <番号> --ip 127.0.0.1 --binding FEED_KEY=<値>`（アカウント不要）
- PC の `app/mslauncher/pubkey.txt` は**マスターの本物の鍵**（`009897114d60…`）になっている。検査は触らない作りだが、作業環境で `publish init` を素で打つと作業環境の側の `pubkey.txt` を書き換えるので、それを書き戻さない

## 5. 再開に要る外部資源

- PC のフォルダ `C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1` への接続（チャットごとに許可の取り直しが要ることがある）
- Claude Docs: 計画書 `36c70594-96e6-4ff6-be45-9c160699273c`／要件定義書 `644bd767-54a9-4b24-8a93-0ad439d4359a`／**基本設計書 `ac841c45-9b40-455a-8b1a-4dc573cc27f0`**（https://claude.ai/code/artifact/ac841c45-9b40-455a-8b1a-4dc573cc27f0 。今回作った。2〜6 章は APP-004・006・007・009・010 の要約、7 章がサーバの置き場所、8 章が確かめていないこと）
- マスターの PC にだけあるもの（接続フォルダの外なので、こちらからは見えない）:
  秘密鍵 `C:\Users\奥村優斗\.meichosim\signing_key.txt`（控えは PC の外に取った・マスターの報告）／公開の設定と合言葉 `C:\Users\奥村優斗\.meichosim\publish.json`／
  置き場の元 `C:\meicho_dist\site\`（`functions\`・`public\`）／起動役の出力 `C:\meicho_dist\launcher\`／マスターが遊ぶ場所 `C:\meicho_dist\play\MeichoSim\`／2026-09-21 の対局の記録の控え `C:\meicho_dist\data_backup_20260922`／
  2026-09-21 の手元の試しの更新元 `C:\meicho_dist\feed`（もう使わない。消してよい）
- Cloudflare: マスターのアカウント・Pages のプロジェクト `meichosim-hhdmauhgjr`・秘密の設定 `FEED_KEY`。**合言葉の値はリポジトリのどこにも書いていない**（書かない）
- 作業環境で使った wrangler・模擬の置き場は使い捨て

## 6. 確かめていないこと

知人の PC での起動（保護機能・ウイルス対策の反応は、固めた本人の PC では参考にとどまる）／合言葉を替える手順の通し／無料枠（1 日 10 万リクエスト）に収まること（収まる見込み）／トンネル越しの対局の全部（WebSocket・切断復帰・遅い回線）／
`Origin` の検査（未実装）／遅い PC で起動待ち 60 秒が足りるか／マスターの PC での CPU の思考時間（記録の `times` に残っている。`C:\meicho_dist\play\MeichoSim\data\games\` なのでこちらからは読めない）／
マスターの PC での `test_release.py` の件数（46 のはず）と、アプリの全検査／**リポジトリの GitHub 側が非公開かどうか**（`GITHUB_SETUP.md` は private で作る手順を勧め、public にするかはマスターの判断としている。実際にどちらで作ったか・もう上げたかは聞いていない。
プロジェクト名＝更新元の URL が `PC_REQUEST_20260922_APP.md`・`DECISIONS_APP.md`・`TASKS_APP.md`・この文書に載っている。合言葉が無ければ 404 なので実害は小さいが、公開リポジトリなら URL は知られている前提になる）
