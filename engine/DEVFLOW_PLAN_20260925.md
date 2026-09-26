# 開発の流れの組み替え — Cowork と Claude Code の使い分け（計画と手順・2026-09-25）

書き手: クロエ（別端末のチャット・エンジンの持ち場の文書として `engine/` 直下に置く）。
位置づけ: 2026-09-25 にマスターが裁定した**開発の流れの正本**（裁定の内容は §0.1）。台帳への反映は §9。
改訂 3（2026-09-26）: 段 3 完了・台帳への反映は `engine/DEVFLOW_LEDGER_DRAFT_20260926.md`（別チャットが動いていたので番号を振らずに置いた）。
改訂 2（2026-09-25 夜）: 段 1・段 4 が完了。マスターの裁定で §0.1 を確定し、段 2 を「いつか」に格下げ、§6.1 のネットの置き場を確定した。

準拠版: rules_draft v0.18 ／ engine v0.1 ／ 符号化 v6 ／ champion `planner_vc4cps_kheb_b75`（指紋 `f4b80b25c35cfa77`）。
**この文書はエンジンの打ち方・Rust・符号化に一切触れない。**変えるのは「ファイルの受け渡し方」と「どの機械で何を回すか」だけである。

---

## 0. 結論

**いちばん効くのは「使い分け」そのものではなく、受け渡しの土台を git に寄せることである。**
いま人手を食っているのは (a) クロエが書いたファイルを PC へ書き戻す往復と OneDrive の載らない事故、
(b) 5 点セットで書いた再ビルドの依頼をマスターが手で打つ作業、(c) D-番号の衝突と控え（WRITELOG）の照合、の 3 つで、
どれも「ファイルを人が運んでいる」ことから来ている。git を受け渡しの単位にすると 3 つとも構造で消える。

### 0.1 マスターの裁定（2026-09-25）— これが決まり

- **ファイルの追加・更新は GitHub 一か所**（`okuson-droid/meicho_engine` の `main`）。**GitHub が唯一の正本**。PC のフォルダは作業ツリーであり、正本ではない（`LANES.md` §10・`GITHUB_SETUP.md` §7 の「正本は PC」はここで覆る）。
- **push するのは Claude Code**（PC 版）。マスターが GitHub Desktop で押すのは例外（Claude Code が使えないとき）。
- **PC で生まれるファイル**（対人局の記録 `results/human_games/`・カードの手動スクショ・ネットの移行の出力・配布版の検査結果）**も PC の Claude Code が commit して push する**。PC は「pull するだけ」ではなく「PC 生まれのものを push する働き手の一人」。
- **Cowork（クロエ）の文書は接続フォルダに書く**（＝作業ツリーに「未 commit の変更」として現れる）。それを PC の Claude Code が commit・push する。Claude Code の文書作成が足りないときだけ Cowork が書く、という分担でよい。プロジェクトナレッジ経由は Claude Code が読めないので使わない。
- **クラウドの Claude Code はブランチに push する。** `main` への merge は PC の Claude Code かマスター。
- **`cards/` は除外のまま**（公式素材。触る作業はほとんど無い）。**`results/` は上げる**——ただし `.bak.json`（移行前の原本・約 230 MB）・`.bin`（記録本体）・`s2v_id_ens3.json`（部品 3 本から決定的に作り直せる）は除く。上がるのは約 200 MB、1 ファイル最大 14 MB。
- **リポジトリは Public のまま**（条件: 秘密の値を書かない／`cards/` の除外を動かさない／本名を含む Windows の経路は段 2 のあとに置き換える）。2026-09-25 に写しを grep して、秘密の値は入っていないことを確かめた（署名の秘密鍵はリポジトリの外・公開鍵だけ・合言葉やトークンの実値なし）。Public の実利: Actions の無料枠が無制限（Private は月 2,000 分・Windows は 2 倍で数える）。
- **読むのは GitHub から**（clone のほうが接続フォルダ経由の 50 ファイルずつより速く、Rust まで建てて検査を回せる）。接続フォルダは「書く口」「資材（`cards/`）と未 push の状態を見る口」として残す。

### 0.2 役割分担

- **Cowork（このクロエ）**: 設計判断・報告書・引継ぎ書・decisions の追記・デッキ構築・アプリの文書・進行盤。読んで考えて書く仕事。**読みは GitHub から、書きは接続フォルダへ。**
- **Claude Code（PC 版）**: エンジンの実装・検査・**Rust の再ビルドと指紋の確認**・短い測定・**commit と push の役**（Cowork の文書と PC 生まれの記録を含む）。**5 点セットの依頼文を引退させる**のが役目。
- **Claude Code（クラウド版）**: 1 時間を超える測定・ラダー・門番。4 コア 2.8GHz・15GiB で、Cowork の作業環境（2 コア 2.1GHz・7GiB）の 2.5 倍前後、マスターの PC と同等以上と見込む。**Kaggle 登録の代わりになるかを 1 便で試す。**結果はブランチに push する。

### 0.3 進める順序（**前の段が済むまで次に入らない**。いま動いている便は現行の運用のまま続けてよい）

1. ~~**段 1** 未 commit の 9 日分を commit・push する~~ → **2026-09-25 に完了**
2. **段 4** GitHub Actions を 2 本置く → **2026-09-25 に完了**（`Tests` は資材の無い 46 件を名指しの一覧で説明して緑・`Windows wheel` は緑）
3. ~~**段 3** PC に Claude Code を入れ、最初の仕事として再ビルドを 1 回やらせる~~ → **2026-09-26 に完了**（指紋 `f4b80b25c35cfa77` 一致・`--pc` の組 335 通過・1 skip・失敗 0・再ビルド 656 秒・`results/` を git に・報告 `engine/CC_PC_RUN_20260925.md`）。**5 点セットの依頼文は引退**
4. **段 5** クラウドセッションで測定を 1 便試す。**次はここ**（§6。ネットの置き場は §6.1 で確定した。先に `.gitignore` の 3 行と host 名の 1 行を入れる）
5. **段 6** 進行盤（アーティファクト）— 段 5 のあとに設計だけ出す（§7）
6. **段 2** リポジトリを OneDrive の外へ移す — **「いつか」に格下げ**（§3）。GitHub が正本になったので必須ではなくなった。残る理由は「OneDrive と git がぶつかる事故を避ける」と「本名を含む経路を文書から消す」の 2 つ

§8 は裁定の記録（決まったこと）と、残っている判断 2 件。

---

## 1. 現状（2026-09-25 に PC を読んで確かめたこと）

- **git 化は済んでいる。**`.git` があり、remote は `https://github.com/okuson-droid/meicho_engine.git`、既定ブランチ `main`。
  `GITHUB_SETUP.md`（2026-09-13・ChatGPT に読ませる目的）の手順で作られたもので、`.gitignore` の先頭が `cards/` になっていることを確認した。
- **最後の commit は 2026-09-16 01:30（JST）、最後の fetch は 2026-09-20。**それ以後 `TASKS.md`（09-25 10:06）・`decisions.md`・`CLAUDE.md`・
  `engine/HANDOFF_20260925_ENGINE.md`・`experiments/`・`tests/` など **9 日分が commit されていない。**
- リモートに `stage1b-encoding-v5` というブランチが残っている（連携を中断した Codex の作業ブランチ。`.github/workflows/stage1b-rust.yml` はそのブランチ用の検査）。
- **除外されているもの**（`.gitignore`）: `cards/`（公式素材・**この除外は動かさない**）／`Claude outputs/`／`engine/results/*/`（`human_games/` を除く）／`engine/rust/target/`・`dist/`。
  つまり **学習済みネット（`engine/results/models/`）は GitHub に無い。**クラウドで champion を立てるにはこれが要る（§5）。
- エンジン本体のカード定義は `engine/meicho/cards.py`（オペコード表現・公式文は転記していない）なので、**`cards/` が無くても対局・測定は回る。**
  `cards/` が要るのは画像と `cards_structured` の突き合わせの検査だけで、それらは D-125 の `--pc` の組として PC に残っている。
- `LANES.md` §10 は「device_bash か Claude Code が使えるようになったら git を『越境の検出』と『便ごとの記録』に使う設計へ見直す」
  「書き戻しの失敗が続くならリポジトリを OneDrive の外へ移す」を見直しの条件としている。**両方とも成立した**（D-126 で「OneDrive の外へ・PC 側の Claude Code を試す」は採用済み・日付と手順が未定）。
- PC の道具: Python 3.11・maturin・cargo（`build_stage1b.txt` で `cargo` の release ビルドが 39.5 秒）・GitHub Desktop。

---

## 2. 段 1 — 未 commit の 9 日分を commit・push する

**なぜ今か**: 段 2 の移設も、段 3 の Claude Code も、段 5 のクラウドも、GitHub にある版を起点にする。9 日分が乗っていないと、どれも 9 月 16 日の世界で始まってしまう。

### どこで
GitHub Desktop（コマンドは打たない）。対象は `C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1`。

### 何をするか
1. **OneDrive を一時停止する**（通知領域の OneDrive → 設定 → 同期の一時停止 → 2 時間）。git がファイルを掴むときに OneDrive とぶつかる事故を避けるため。
2. GitHub Desktop を開く。左上の `Current repository` が `meicho_engine` になっていることを見る。違えば切り替える。
3. `Changes` タブの件数を見る。**数十〜200 前後なら正常。**一覧の先頭のほうを少しスクロールして、`cards/` で始まる行が無いことを見る（`.gitignore` の先頭行が効いている証拠）。
4. 一覧に `engine/results/` で始まる行があれば、それが `human_games/` の下だけであることを見る（それ以外の `results/` は除外されているはず）。
5. 左下の要約に次を書いて `Commit to main` を押す。

       2026-09-16〜25 の作業をまとめて commit（D-089〜D-133・段階1B〜段階2・環境デッキ 24 種・アプリ M2〜M5）

6. 上の `Push origin` を押す。
7. 終わったら OneDrive の一時停止を解く。

### 成功したらどう見えるか
- `Changes` が `No local changes` になる。
- `Push origin` のボタンから数字が消え、`Fetch origin` に戻る。
- `Repository` → `View on GitHub` で開いたページの最新 commit が、いま書いた要約になっている。

### 確認のしかた
- GitHub のページで `TASKS.md` を開き、冒頭の「最新の引継ぎ書」が `engine/HANDOFF_20260925_ENGINE.md` になっていること。

### 転びやすいところと症状
- **`Changes` に `.png` が何百行も並ぶ** → `.gitignore` の先頭行 `cards/` が消えている。**commit せずに止めて**、クロエに知らせる。
- **`Permission denied` / `unable to index file`** → OneDrive が掴んでいる。一時停止して `Retry`。
- **`Changes` に 4 桁の件数** → `engine/rust/target/` か `results/` の除外が外れている。止めて件数を貼ってほしい。
- 改行の警告 `LF will be replaced by CRLF` は無害。
- 大きいファイルの警告（50 MB 超）が出たら、そのファイル名を貼ってほしい（想定では出ない。`decisions.md` は 0.8 MB）。

---

## 3. 段 2 — リポジトリを OneDrive の外へ移す（**「いつか」・マスター裁定 2026-09-25**）

**位置づけ**: GitHub が正本になった（§0.1）ので、移設は必須ではなくなった。**やる価値が残る理由は 2 つ**——(1) OneDrive が `.git` の小さいファイルを掴んで git が止まる事故（`Permission denied` / `unable to index file`）は、Claude Code が PC で commit するようになると頻度が上がる。当面は「Claude Code が commit する前に OneDrive を一時停止する」運用で避ける。(2) 本名を含む Windows の経路（`C:\Users\…`）が引継ぎ書・依頼書に 20 ファイルほど入っていて、Public のリポジトリに見えている。移設して経路を `C:\dev\…` に置き換えると、副作用としてこれが消える。
移設先は **`C:\dev\meicho_engine_v0.1`**（ASCII だけ・短い）。OneDrive の古いフォルダは消さず、名前を変えて凍結する。**やるときは段 3 のあと**（Claude Code に経路の置き換えをさせられる）。

### どこで
コマンドプロンプト（`cmd`）。**PowerShell ではない**（`PS C:\` と出ていたら別の窓を開く）。

### 何を打つか（上から 1 行ずつ）
**(0)** GitHub Desktop・対人検証アプリ・新アプリのサーバの窓・エディタを全部閉じる。OneDrive を一時停止する。

**(1) 写す**（`.git`・`cards`・`results`・`Claude outputs` を含めて全部。`target`・`__pycache__`・`.pytest_cache` は除く。**元は消さない**）

    mkdir C:\dev
    robocopy "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1" "C:\dev\meicho_engine_v0.1" /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XD target __pycache__ .pytest_cache /LOG:C:\dev\robocopy_20260925.log /TEE /NP

**(2) 写しが git として健全かを見る**

    cd /d C:\dev\meicho_engine_v0.1
    git status --short | find /c /v ""
    git log --oneline -1
    git remote -v

**(3) 元のフォルダを凍結する**（消さない。名前を変えるだけ）

    ren "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1" meicho_engine_v0.1_OLD_20260925

**(4) GitHub Desktop に新しい場所を教える**: GitHub Desktop を開くと `meicho_engine` に「Can't find "meicho_engine"」と出る。`Locate...` を押して `C:\dev\meicho_engine_v0.1` を選ぶ。

**(5) Cowork の接続フォルダを付け替える**: Claude デスクトップアプリで、このプロジェクトの接続フォルダから古い場所を外し、`C:\dev\meicho_engine_v0.1` を `Add folder` で足す。

**(6)** OneDrive の一時停止を解く。

### 成功したらどう見えるか
- (1): 最後に `Files : <合計> <Copied> 0 0 0 0` のような表が出て、**`FAILED` の列が 0**。ログは `C:\dev\robocopy_20260925.log`。
- (2): 1 行目は **`0`**（段 1 で commit 済みなら未 commit は無い）。2 行目は段 1 の要約。3 行目に `okuson-droid/meicho_engine.git` が 2 回。
- (4): GitHub Desktop の `Changes` が `No local changes`。
- (5): Cowork のチャットでクロエが新しい場所のファイル一覧を取れる。

### 確認のしかた
- `dir C:\dev\meicho_engine_v0.1\engine\results\models\*.json | find /c ".json"` が **元のフォルダで同じ行を打った値と一致**する（除外していない場所が全部写った証拠）。
- `dir C:\dev\meicho_engine_v0.1\cards\*.png | find /c ".png"` も同様に一致。

### 転びやすいところと症状
- **robocopy の `FAILED` が 0 でない** → ログの `ERROR` 行を貼ってほしい。多くは OneDrive の「ファイル オンデマンド」で中身がクラウドにしか無いファイル（アイコンが雲）。そのファイルを右クリック → `このデバイス上に常に保持する` にしてから (1) を打ち直す（robocopy は写し済みを飛ばすので 2 回目は速い）。
- **(2) の 1 行目が 0 でない** → 段 1 のあとに誰かが書いた（並行チャットの書き戻し）。`git status --short` の中身を貼ってほしい。移設は続けてよい。
- **(3) で「別のプログラムが使用中」** → エクスプローラーかエディタが古いフォルダを開いている。閉じて打ち直す。
- **`git` が無いと言われる** → GitHub Desktop 同梱の git は PATH に無い。`Repository` → `Open in Command Prompt` から開いた窓で打つ。
- 古いフォルダの中の `Claude outputs/` は写しにも入っている。二重に持つのは意図どおり（凍結）。
- 台帳・引継ぎ書に書いてある古い経路（`C:\Users\奥村優斗\OneDrive\...`）は、**段 3 の Claude Code に置き換えさせる**（§4 の最初の仕事の 2 件目）。

---

## 4. 段 3 — PC に Claude Code を入れ、再ビルドを 1 回やらせる

**なぜ今か**: PC でしかできない作業（Rust の再ビルド・指紋の確認・`--pc` の組の検査）を、5 点セットの依頼文からマスターの手を経由せずに回せるようにする。
最初の仕事を「もう済んでいる再ビルド」にするのは、結果が分かっている作業で道具の癖を見るためである（わざと壊して落ちることを見るのと同じ発想）。

### どこで
コマンドプロンプト（`cmd`）。作業ディレクトリは `C:\dev\meicho_engine_v0.1`。

### 何を打つか
**(1) 入れる**（公式の手順・管理者権限は不要）

    curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
    claude --version

**(2) Git for Windows が入っていなければ入れる**（Claude Code の Bash 道具に要る。GitHub Desktop の git は別物で使えない）。
https://git-scm.com/downloads/win からインストーラを実行し、選択肢は既定のまま進める。入れたら窓を開き直す。

    git --version

**(3) 起動してログインする**

    cd /d C:\dev\meicho_engine_v0.1
    claude

ブラウザが開くので、いつもの claude.ai のアカウントでログインする。信頼の確認（このフォルダを信頼するか）には `Yes`。

**(4) 最初の仕事（次の文をそのまま貼る）**

    このリポジトリの決まりは CLAUDE.md と LANES.md にある。最初に両方を読むこと。
    やってほしいことは 2 つ。
    1. engine/REBUILD_REQUEST_20260922b.md の (1)〜(4) を、このフォルダ（C:\dev\meicho_engine_v0.1）で順に実行する。
       ただし (2) のネットの移行は済んでいるので飛ばし、(1) 確認・(3) 再ビルドと指紋・(4) --pc の組の検査 を回す。
       期待は (3) の指紋が f4b80b25c35cfa77 で「→ 一致」、(4) が failed 0。
       結果は engine/CC_PC_RUN_20260925.md に、通過・失敗・skip の件数と理由、指紋の実測、ビルドにかかった秒数を書く。
       失敗があっても直さない。件数と名前と理由を書くだけにする。
    2. TASKS.md・CLAUDE.md・LANES.md・engine/HANDOFF_20260925_ENGINE.md・engine/REBUILD_REQUEST_2026092*.md の中の
       古い経路「C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1」を
       「C:\dev\meicho_engine_v0.1」に置き換える。改行コードは元のまま（TASKS.md・decisions.md は CRLF・CLAUDE.md は LF）。
       decisions.md は触らない。
    3. .gitignore の「engine/results/*/」と「!engine/results/human_games/」の 2 行を消し、代わりに
       engine/ci/gitignore_additions.txt の 3 行を同じ場所に入れる。git status で engine/results/ の下が
       約 200 MB・.bak.json と .bin が 1 つも含まれないことを確かめる（git status --short | findstr /i /r "\.bak\.json$ \.bin$" が空。
       部分一致だと .bin.manifest.json に当たるので末尾一致で見る）。
    終わったら git status の一覧を見せて止まる。commit と push は、マスターが一覧を見て「よい」と言ってから行う。

**(5) 終わったら**: Claude Code が見せた `git status` の一覧が「置き換えた台帳 5 種＋`engine/CC_PC_RUN_20260925.md`＋`.gitignore`＋`engine/results/` の下」だけであることを確かめ、「commit して push して」と返す（§0.1: push は Claude Code の役）。要約は「段 3: PC の Claude Code の初仕事（再ビルド確認・経路の置き換え・results/ を git に）」でよい。

### 成功したらどう見えるか
- (1): `2.x.xxx (Claude Code)` のような版が出る。
- (4): Claude Code が 1 行ずつコマンドを実行し、実行の許可を求めてくる（`maturin build`・`pip install`・`pytest`）。**許可してよいのはこの依頼書の (1)(3)(4) に書いてあるコマンドだけ**。それ以外（ファイルの削除・`git push`・`pip install` の別パッケージ）を求めてきたら `No` にして、何を求めたかをクロエに貼ってほしい。
- `engine/CC_PC_RUN_20260925.md` に、9 月 22 日の依頼書の結果（指紋一致・`--pc` の組 failed 0）と同じ結論が書かれている。

### 確認のしかた
- `python scripts\check_champion_fingerprint.py` を自分で 1 回打って `→ 一致` が出る（Claude Code の報告を鵜呑みにしない。**報告と実物の照合は今後も 1 回は人がやる**）。

### 転びやすいところと症状
- **`claude` が見つからない** → 窓を開き直す（PATH が新しい窓にしか効かない）。それでも出なければ `%USERPROFILE%\.local\bin` に `claude.exe` があるか見る。
- **`The token '&&' is not a valid statement separator`** → PowerShell で打っている。`cmd` を開く。
- **Bash 道具が使えないと言われる** → Git for Windows が無いか、見つけられていない。(2) を済ませてから、`%USERPROFILE%\.claude\settings.json` に次を書く。

      { "env": { "CLAUDE_CODE_GIT_BASH_PATH": "C:\\Program Files\\Git\\bin\\bash.exe" } }

- **`No module named 'meicho'`** → Claude Code が `set PYTHONPATH=%CD%` を打っていない。CLAUDE.md の罠の節に書いてあるので「CLAUDE.md の PYTHONPATH の罠を読んで」と返す。
- **指紋が一致しない** → 段 2 の写しに古い wheel が入っている可能性（`pip install --force-reinstall` を飛ばした）。依頼書 §5 のとおり `--force-reinstall` で打ち直させる。
- **Claude Code が `decisions.md` を直そうとする** → 断る（LANES §3。D-番号はチャットが振る）。
- **cp932 の `UnicodeEncodeError`** → 道具の出力に `₀` などが混ざったとき。`set PYTHONUTF8=1` を打ってから再実行（D-082 追記 1 と同じ罠）。

**段 3 が済んだら**: 以後の再ビルドの依頼書は、5 点セットの本文をそのまま Claude Code への貼りつけ文にする。書き方の決まり（REPORTING_RULES §2.6）は変えない——**読む相手が人から Claude Code に変わるだけ**で、手順を省かない理由は同じである。

---

## 5. 段 4 — GitHub Actions を 2 本置く

本書と一緒に `engine/ci/tests.yml` と `engine/ci/wheel-windows.yml` を置いた（**`.github/` はリモートの道具からは書けない保護フォルダだったので、いったん `engine/ci/` に置いた**）。
段 1 の前に、次の 2 行をコマンドプロンプトで打って `.github/workflows/` へ写す（写したあとの `engine/ci/` は残してよい。段 3 の Claude Code に消させてもよい）。

    copy "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine\ci\tests.yml" "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\.github\workflows\tests.yml"
    copy "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine\ci\wheel-windows.yml" "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\.github\workflows\wheel-windows.yml"

どちらも `1 個のファイルをコピーしました。` と出れば済み。**段 1 の commit に乗せて push すれば動く。**設定は要らない（`GITHUB_TOKEN` は Actions が自動で持つ）。

### 5.1 `tests.yml` — push のたびに検査を回して「通過・失敗・skip」を出す
- `ubuntu-latest` で Python 3.11 と Rust を入れ、`pip install ./engine/rust` で部品を作り、`engine/` で `python -m pytest tests -q -rfs` を回す（既定＝重い 20 件は飛ばす。約 7 分の見込み）。
- **`cards/`（画像・`cards_structured`・BP01 の台帳 JSON）と `results/`（ネット・`decksim/`）が GitHub に無いので、それらに触る検査は落ちる。**
  2026-09-25 の実行 #2 で落ちたのは 46 件（パラメータ違いを含めて 49）。**46 件すべて理由を読んだ**（作業環境に同じ clone を作って同じ組を回し、失敗の集合が一致することを確かめた）——全部が `FileNotFoundError`（上の 2 か所の資材）か、画像の索引が空であることによる `StopIteration`／`AssertionError` で、**説明できない失敗は 0**。
  その 46 件は `engine/ci/missing_assets_allowlist.txt` に**名指し**で持つ。Summary は失敗を「一覧で説明できる」「説明できない」に分けて出し、**赤にするのは説明できない失敗があるときだけ**。一覧にあるのに通った検査も別枠で出す（資材を置いたら一覧から消す合図）。
  `test_sets.json` の `pc_tests`（50 件）とは重なりが 32 件しか無い——あちらは「作業環境にネット 4 本などがあった状態」で作った組で、CI は「GitHub にあるものだけ」の状態なので、別の集合として持つのが正しい。**説明できない失敗が 1 件でもあれば、それは PC でも作業環境でも見えていなかった本物**である。
- 出力は Actions の画面の `Summary` に「通過 / 失敗 / skip」の 3 つの数と、失敗・skip の名前が並ぶ。**skip は「通った」ではない**ので skip も名前で出す。
- `.github/workflows/stage1b-rust.yml`（Codex のブランチ用）は残しておく。動くのは `stage1b-encoding-v5` への push か PR のときだけなので邪魔にならない。要らなくなったら段 1 のあとに消す（判断 §8-3）。

### 5.2 `wheel-windows.yml` — Windows の wheel を GitHub が作る
- `windows-latest` で `maturin build --release`（Python 3.11）を回し、できた `meicho_rs-0.1.0-cp311-cp311-win_amd64.whl` を **Actions の成果物（artifact）** として置く。90 日残る。
- 動くのは **`engine/rust/**` か `engine/meicho/cards.py` が変わった push** と、手で押したとき（`Actions` → `Windows wheel` → `Run workflow`）。
- **使いどころ**: champion の交代や Rust の変更で PC の再ビルドが要るとき、段 3 の Claude Code が手元で作る代わりに、この成果物を落として `pip install --force-reinstall --no-deps <whl>` するだけにできる。**どちらで作った wheel でも指紋の確認は必ずする**（`scripts\check_champion_fingerprint.py`）。
- **ここで作る wheel は「打ち方に関わる Rust 変更」の検証には使わない。**毎手一致（Python↔Rust）は資材の要る検査なので PC か作業環境で回す（D-125 の `--pc`）。CI の wheel は「Windows で建つこと」と「配布に使える部品を人手なしで作ること」の 2 つのためにある。

### 転びやすいところと症状
- `tests.yml` が `pip install ./engine/rust` で落ちる → Rust の toolchain の版。`dtolnay/rust-toolchain@stable` を使っているので通常は出ない。ログの最初の `error` を貼ってほしい。
- `wheel-windows.yml` が `maturin` の版で落ちる → `pyproject.toml` の `maturin>=1.5,<2` に合わせて `PyO3/maturin-action@v1` を使っている。落ちたらログの最初の `error` を貼ってほしい。
- Actions が動かない → リポジトリの `Settings` → `Actions` → `General` で「Allow all actions」になっているか見る（private リポジトリの既定は許可）。

---

## 6. 段 5 — クラウドセッションで測定を 1 便試す

**前提**: クラウドセッションは **GitHub のリポジトリを clone して始まる**（`main` の最新）。手元の未 push の変更は見えない。
結果は **ブランチに commit して push しないと消える**（容器は使い捨て・しばらく放置すると回収される・裏で走らせていた仕事は復元されない）。

### 6.1 ネットの置き場（**確定・マスター裁定 2026-09-25**）
champion を立てるには `engine/results/models/` の現行ネットが要るが、`.gitignore` の `engine/results/*/` で GitHub に無い。
**裁定: `results/` を main のリポジトリで管理する。**除くのは `.bak.json`・`.bin`・`s2v_id_ens3.json` の 3 種。`.gitignore` の `engine/results/*/` の行を次の 4 行に置き換える（`engine/ci/gitignore_additions.txt` に同じものを置いた）:

    engine/results/**/*.bin
    engine/results/**/*.bak.json
    engine/results/models/s2v_id_ens3.json

（3 行目までが除外。既存の `engine/results/*/` と `!engine/results/human_games/` の 2 行は**消す**。）
理由: ネットも記録も我々の成果物で公式素材を含まない／1 本 7〜14 MB で GitHub の上限（1 ファイル 100 MB）に収まる／上がるのは約 200 MB。
ネットは移行や再学習のたびに差し替わるので履歴は 80〜170 MB ずつ太る。年に数回なら問題にならない。太りすぎたら LFS に移す。
**これは段 3 の Claude Code の最初の仕事に足す**（§4 の (4) の 3 件目）。push のあと `Tests` の Summary の「一覧にあるのに通った検査」に名前が並ぶはずなので、その分を `engine/ci/missing_assets_allowlist.txt` から消す。

### 6.2 host の名前（エンジンの持ち場の 1 行・打ち方には関わらない）
`experiments/provenance.py` の `HOSTS` は知らない名前を拒否する。クラウドセッションの機械を **`cc-cloud-4`**（Claude Code のクラウド・4 コア）として足す。
測定の由来（provenance）に `host` が残るので、あとから「どの機械で測ったか」を区別できる。**これは段 5 に入る前にエンジンの持ち場のチャットで足す**（この文書では変えない）。

### 6.3 試す便（結果が分かっているものを回す）
最初の便は **新しい測定ではなく、既に数字のあるものの再現**にする。推し: D-132 追記 4 と同じ課題（調整デッキ 4 つ・2,400 局・帯 841000..841149・`eval_s2_repr.py`）を、**同じシードで**回して、同じ数字が出ることを見る。
同じシードは同じ対局（決定的）なので、**1 局でも違えば環境の差（wheel の版・ネットの版・host）である**。数字が一致して初めて、新しい測定に使ってよい。
所要は Cowork の作業環境で約 2 時間だったので、クラウドでは 1 時間弱の見込み。

### 6.4 セッションの始め方
1. 段 1・段 2 が済んでいて、`main` が push 済みであること。
2. Claude デスクトップアプリで新しいセッションを作り、`Local` ではなく **`Cloud`** を選ぶ。リポジトリは `okuson-droid/meicho_engine`。
   （初回は GitHub の接続を求められる。Claude GitHub App を `meicho_engine` に入れる。**private のまま**でよい）
3. 最初の文（そのまま貼る）:

       この機械の CPU コア数・メモリ・Python と rustc の版を最初に報告すること。
       CLAUDE.md と engine/HANDOFF_20260925_ENGINE.md を読む。
       engine/rust を `pip install ./engine/rust` で建てる。engine/ に移って `export PYTHONPATH=$PWD` と `export MEICHO_HOST=cc-cloud-4` を打つ（Linux なので set ではない）。
       `python scripts/check_champion_fingerprint.py` を回し、f4b80b25c35cfa77 と一致するか報告する。一致しなければそこで止まる。
       一致したら、decisions.md D-132 追記 4 に書いてある評価（eval_s2_repr.py・調整デッキ 4 つ・各ブロック 150 局・seed0 841000）を
       同じ引数で回し、results/drl/ の出力を D-132 追記 4 の数字と局ごとに突き合わせて、一致した局数／全局数を報告する。
       長い実行は 1 回 10 分以内の塊に分けて再開可能に回し、塊ごとに results/ の JSON（.bin は除く）を
       ブランチ cc-cloud-trial-20260925 に commit して push する。裏で走らせない。
       打ち方に関わるコード・Rust・符号化・champion の定義は変えない。decisions.md・TASKS.md は書かない。

4. 終わったら、ブランチ `cc-cloud-trial-20260925` を GitHub Desktop で `Fetch origin` → ブランチを切り替えて中身を見る。**採用するなら main に merge、しないなら残しておく**（消さない）。

### 転びやすいところと症状
- **`check_champion_fingerprint.py` がネットを見つけられない** → §6.1 の置き場が決まっていない。ここで止める（当然の失敗）。
- **数字が D-132 追記 4 と合わない** → 環境の差。局ごとの突き合わせで最初にずれた局を貼ってほしい。wheel の `features()` の札とネットの `sha256` を先に疑う。
- **セッションが「Environment expired」で止まる** → 放置時間が長かった。開き直せば会話は戻るが、走っていた塊は消えている。**塊ごとに push していれば失うのは最後の 1 塊だけ**。
- **クレジットの消費**: クラウド VM そのものに別料金は無く、消費は Claude のトークン（会話・ツール出力）である。長い測定でトークンを食うのは「出力を全部読ませる」ときなので、進捗は 1,000 局ごとの 1 行に絞らせる（測定の作法と同じ）。

---

## 7. 段 6 — 進行盤（アーティファクト）の設計（着手は段 5 のあと）

マスターが「今どうなってる?」をクロエに聞かなくても見える 1 枚。**書く仕事はしない。読むだけ。**

- 読む元: GitHub の `main`（raw で `TASKS.md`・`engine/decisions.md` の末尾・`experiments/champion.py`・`results/manifest_*.json`・`results/decksim/*.md`）。
- 見せるもの: champion と指紋／rules と符号化の版／`TASKS.md` の Active・Waiting On／最新 3 便の結果の要点（manifest から）／裁定待ちの項目と推し／直近の commit と Actions の結果（通過・失敗・skip）。
- private リポジトリの raw を読むには token が要る。**token をページに埋め込まない**——ページは「貼られた JSON を表示する」だけにし、JSON は Actions（`tests.yml` の末尾）が `gh-pages` ではなく **Actions の成果物**として出す形か、Cowork のクロエが定期実行で作って進行盤の記憶（アーティファクトの保存領域）に書く形のどちらか。**推しは後者**（token をどこにも置かない・スケジュール実行は Cowork で作れる）。
- 「推しを採用」ボタンは **段 6 の 2 回目**。押した結果を Cowork のクロエが拾って `decisions.md` に追記する形（D-番号はエンジンの持ち場が振る決まりを守る）。

---

## 8. 裁定の記録と、残っている判断

**2026-09-25 に決まったこと**（§0.1 の裏づけ）: (1) ネットの置き場＝`results/` を main で管理（`.bak.json`・`.bin`・`ens3` を除く）／(2) 正本は GitHub・push は Claude Code・PC 生まれのものも Claude Code が push／(3) Cowork の文書は接続フォルダに書き、Claude Code が commit／(4) Public のまま（条件つき）／(5) 段 2（移設）は「いつか」／(6) Cowork の書き戻しのバイト比較は、OneDrive にある間は残す。

**残っている判断 2 件**（推しつき・急がない）:

1. **Codex の名残 `stage1b-encoding-v5` ブランチと `.github/workflows/stage1b-rust.yml`**: **推し: 消す**（段階1B は D-089/D-091 で閉じており、ブランチの中身は main に merge 済み——`logs/HEAD` の最後の pull が ort strategy の merge）。消す前に GitHub の画面で ahead が 0 であることを見る。段 3 の Claude Code にやらせてよい。
2. **`GITHUB_SETUP.md` §7「リポジトリは正本ではない」と `LANES.md` §10「正本が PC のフォルダであることは変えない」**: §0.1 で覆ったので書き換える。**推し: §9 の台帳反映と同時に**。

## 9. 台帳へ落とすこと（クロエがやる・エンジンの持ち場の 1 チャットで・PC の `decisions.md` の末尾を見てから）

- `engine/decisions.md` に D-番号を 1 つ（§0.1 の裁定 6 件と、段 1・段 4 の完了）。
- `TASKS.md` Active の「監査の採用 2 件の実行（D-126）」の (5) を、本書の段 3 → 5 → 6 → 2 に置き換える（段ごとに `[ ]`・段 1 と段 4 は `[x]`）。
- `LANES.md` §10 を「見直した（本書）」に、§5 を「正本は GitHub。書き戻しのバイト比較は OneDrive にある間は残す」に。「正本が PC のフォルダ」の文は消す。
- `CLAUDE.md` の冒頭「正本は PC のこのフォルダである」を「正本は GitHub の main。PC は作業ツリー」に。罠の節に「push を忘れるとクラウドの起点が古い」を 1 行。
- `GITHUB_SETUP.md` §7 を「正本は GitHub・PC は作業ツリー・push は Claude Code」に書き換える。
- `experiments/provenance.py` の `HOSTS` に `cc-cloud-4`（§6.2・検査があれば同時に）。
- `.gitignore` の書き換え（§6.1）——これは段 3 の Claude Code がやる。

## 10. この文書で言えないこと

- クラウドセッションの機械が「4 コア 2.8GHz・15GiB」であることはマスターの報告で、クロエは測っていない。§6.4 の最初の 1 行で毎回測らせる。
- `tests.yml` の最初の実行で何件落ちるかは分からない（資材の無い検査の数は作業環境の実測 25 件が目安）。**最初の失敗一覧を読んでから CI の除外を決める**。
- 段 3 の Claude Code が依頼書どおりに動くかは、最初の 1 回を人が照合するまで分からない。**報告と実物の照合は残す**。
