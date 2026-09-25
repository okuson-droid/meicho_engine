# PC への依頼（アプリの持ち場）: 配布版を Windows で固めて、自動更新を手元で試す（2026-09-21）

- **所要時間の見込み**: 15〜25 分（うち PyInstaller が数分。初回の `pip install` の時間は回線による）
- **急ぎ度**: 中（知人に配る前に要る。エンジンの作業は止めない。30 分を超えない依頼なので、エンジン側の依頼書と並んでもよい・`LANES.md` §7）
- **なぜ今これが要るのか**: M5 後半（APP-010）の実装と自動検査は作業環境（Linux）で済み、Linux で固めた実行ファイルでは通しが通った。
  だが配るのは Windows の実行ファイルで、**Windows では一度も固めていない**。固まるか・立ち上がるか・保護機能に止められないかは、マスターの PC でしか分からない。
- 道具はコマンドプロンプト（cmd）。PowerShell ではない。

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine

出力先は OneDrive の外の `C:\meicho_dist\`（無ければ道具が作る）。秘密鍵は `C:\Users\奥村優斗\.meichosim\` にできる。

## 2. 何を打つか（上から 1 行ずつ）

    cd /d "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine"
    py -3.11 -m pip install -r app\requirements.txt pyinstaller
    py -3.11 -m pytest app\tests\test_release.py -q
    py -3.11 -m app.release.publish init --feed-dir C:\meicho_dist\feed --feed-url C:\meicho_dist\feed
    py -3.11 -m app.release.publish release --notes "最初の公開"
    py -3.11 -m app.release.publish launcher --out C:\meicho_dist\launcher --author "オクソン"

そのあと、エクスプローラーで `C:\meicho_dist\launcher\dist\MeichoSim\MeichoSim.exe` をダブルクリックする。

更新の試し（exe の黒い窓を閉じてから）:

    py -3.11 -m app.release.publish release --notes "二回目" --force

もう一度 `MeichoSim.exe` をダブルクリックする。

`--feed-url` を手元のフォルダにしているのは、更新元の置き場所が決まる前でも自動更新を自分の PC で試せるようにするためである。

## 3. 成功したらどう見えるか

- `pytest`: 最後の行が `33 passed`（`cryptography` が入っていなければ `32 passed, 1 skipped`）
- `init`: 「秘密鍵を作った: C:\Users\奥村優斗\.meichosim\signing_key.txt」「公開鍵: （16 進 64 桁）」。`app\mslauncher\pubkey.txt` ができる
- `release`: `[1/5] 組み立て` 〜 `[5/5] 配置` と進み、途中に「1 局（SD001・やさしい）: normal」「1 局（SD02・やさしい）: normal」「OK」、最後に「公開した: 版 2026.09.21-1」（日付は実行日）
- `launcher`: 最後に「実行ファイルの煙テスト: OK」「固めたフォルダの走査: 合格」「配る zip: C:\meicho_dist\launcher\MeichoSim_launcher1_<版>.zip」
- exe: 黒い窓に「版 … を起動している…」「起動した: http://127.0.0.1:8765/」。ブラウザにホームが開く
- 更新の試し: 黒い窓に「新しい版 … を取り込む」「版 … に更新した」

## 4. 確認のしかた

1. ホームの「CPU と対戦」で 1 局打てる（やさしいでよい）
2. ホームの一番下の「設定・版と更新の履歴」→「版と更新」に、版の名前と「最新の版を使っている」が出る
3. 更新の試しのあと、同じ場所の「更新の履歴」を開くと「二回目」「最初の公開」の 2 行がある
4. `C:\meicho_dist\launcher\dist\MeichoSim\data\games\` に対局の記録（`.jsonl`）ができていて、更新のあとも残っている
5. 秘密鍵 `C:\Users\奥村優斗\.meichosim\signing_key.txt` の控えを USB メモリなど PC の外に 1 つ取る（誰にも渡さない）

## 5. 転びやすいところと症状

- `py -3.11` が「見つからない」→ Python の呼び名が違う。`py -3.11` を `python` に読み替えて同じ行を打つ
- `No module named app` → 作業フォルダが `engine` になっていない。§2 の 1 行目からやり直す
- `No module named PyInstaller`／`aiohttp` → §2 の 2 行目（pip install）が済んでいない
- `release` で「秘密鍵が無い」→ `init` を先に打つ
- `release` で「走査を通らないので公開しない」→ 出た `NG:` の行をそのまま知らせてほしい（配ってはいけないものが混ざっている。道具が止めたのは正しい動き）
- `release` で「前の版から中身が 1 バイトも変わっていないので公開しない」→ 正常。試しで出すなら `--force` を付ける
- `launcher` で「--out が空でない」→ 別の用途のフォルダを指している。`C:\meicho_dist\launcher` を使う（この道具が前に作ったフォルダなら、自分で消して作り直す）
- `launcher` が PyInstaller の途中で落ちる → **ここが一番あやしい**（標準ライブラリを丸ごと入れる設定を Windows で試していない）。窓の最後の 30 行ほどをそのまま知らせてほしい
- exe で Windows の青い保護画面 →「詳細情報」→「実行」。ウイルス対策ソフトが隔離した場合は、その旨と製品名を知らせてほしい
- exe で「ポート 8765 を別のプログラムが使っている」→ 前の黒い窓が残っていないか確かめる。残っていないのに出るなら知らせてほしい（Windows 側の判定は未検証）
- exe で「版 … が起動しなかった」「一つ前の版に戻す」→ 中身が Windows で立ち上がっていない。窓の文を全部知らせてほしい
- 文字化け → 動作には影響しない（表示だけ）。化けた行があれば知らせてほしい

うまくいかないときは、黒い窓に出た文をそのまま貼ってもらえれば足りる。
