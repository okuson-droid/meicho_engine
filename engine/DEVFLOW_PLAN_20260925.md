# 開発の流れの組み替え — Cowork と Claude Code の使い分け（計画と手順・2026-09-25）

書き手: クロエ（別端末のチャット・エンジンの持ち場の文書として `engine/` 直下に置く）。
位置づけ: **マスターの裁定待ちの提案書**である。台帳（`TASKS.md`・`decisions.md`・`LANES.md`・`CLAUDE.md`）は
裁定が出るまで触らない（同日にエンジンの持ち場のチャットが動いていた形跡があり、D-番号の衝突を避ける）。
裁定のあとに §9 のとおり台帳へ落とす。

準拠版: rules_draft v0.18 ／ engine v0.1 ／ 符号化 v6 ／ champion `planner_vc4cps_kheb_b75`（指紋 `f4b80b25c35cfa77`）。
**この文書はエンジンの打ち方・Rust・符号化に一切触れない。**変えるのは「ファイルの受け渡し方」と「どの機械で何を回すか」だけである。

---

## 0. 結論

**いちばん効くのは「使い分け」そのものではなく、受け渡しの土台を git に寄せることである。**
いま人手を食っているのは (a) クロエが書いたファイルを PC へ書き戻す往復と OneDrive の載らない事故、
(b) 5 点セットで書いた再ビルドの依頼をマスターが手で打つ作業、(c) D-番号の衝突と控え（WRITELOG）の照合、の 3 つで、
どれも「ファイルを人が運んでいる」ことから来ている。git を受け渡しの単位にすると 3 つとも構造で消える。

役割分担（提案）:

- **Cowork（このクロエ）**: 設計判断・報告書・引継ぎ書・decisions の追記・デッキ構築・アプリの文書・進行盤。読んで考えて書く仕事。
- **Claude Code（PC 版）**: エンジンの実装・検査・**Rust の再ビルドと指紋の確認**・短い測定。**5 点セットの依頼文を引退させる**のが役目。
- **Claude Code（クラウド版）**: 1 時間を超える測定・ラダー・門番。4 コア 2.8GHz・15GiB で、Cowork の作業環境（2 コア 2.1GHz・7GiB）の 2.5 倍前後、マスターの PC と同等以上と見込む。**Kaggle 登録の代わりになるかを 1 便で試す。**

進める順序（**前の段が済むまで次に入らない**。いま動いている便は現行の運用のまま続けてよい）:

1. **段 1** 未 commit の 9 日分を commit・push する（GitHub Desktop・30 分）
2. **段 2** リポジトリを OneDrive の外へ移す（robocopy・30 分＋Cowork の接続フォルダの付け替え）
3. **段 3** PC に Claude Code を入れ、**最初の仕事として再ビルドを 1 回やらせる**（1 時間）
4. **段 4** GitHub Actions を 2 本置く（検査／Windows の wheel）— ファイルは本書と一緒に置いた。push すれば動く
5. **段 5** クラウドセッションで測定を 1 便試す（ネットの置き場を先に決める・§5）
6. **段 6** 進行盤（アーティファクト）— 段 5 のあとに設計だけ出す（§6）

判断が要る点は §8 にまとめた（推しつき・提案はすべて推しを採用の方針 D-069 に従う）。

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

## 3. 段 2 — リポジトリを OneDrive の外へ移す

**なぜ今か**: 書き戻しが「written でも載らない」事故（D-113・LANES §5）と、日本語を含む長い経路で道具が転ぶ問題（cp932・D-082 追記 1）は、どちらも置き場所が原因である。
移設先は **`C:\dev\meicho_engine_v0.1`**（ASCII だけ・短い）。**正本が PC のフォルダであることは変えない**（LANES §10）。OneDrive の古いフォルダは消さず、名前を変えて凍結する。

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
    終わったら git status の一覧を見せて止まる。commit はしない。

**(5) 終わったら**（クロエの推し: 最初のうちは commit はマスターが GitHub Desktop で押す）
GitHub Desktop の `Changes` を見て、変わったファイルが「置き換えた台帳 5 種＋`engine/CC_PC_RUN_20260925.md`」だけであることを確かめ、`Commit to main` → `Push origin`。

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

### 6.1 先に決めること: ネットの置き場（判断 §8-1）
champion を立てるには `engine/results/models/` の現行ネット（`drl_*.json` 12 本 約 80 MB＋`s2v_*_s?.json` 6 本 約 84 MB）が要るが、`.gitignore` の `engine/results/*/` で GitHub に無い。
**クロエの推し（案 A）**: `.gitignore` に次の 3 行を足して、**現行のネットだけ**を main のリポジトリで管理する。

    !engine/results/models/
    engine/results/models/*.bak.json
    engine/results/models/s2v_id_ens3.json

理由: ネットは我々の成果物で公式素材を含まない／リポジトリは private／1 本 7〜14 MB で GitHub の上限（1 ファイル 100 MB）に収まる／
`.bak.json`（移行前の原本・約 200 MB）と `ens3`（39 MB・部品 3 本から決定的に作り直せる）は除く。
ネットは移行や再学習のたびに差し替わるので履歴は太る（1 回 80〜170 MB）が、年に数回なら問題にならない。
**代案 B**: 別の private リポジトリ `meicho_assets` に置き、クラウドの環境の setup script で clone する（main を軽く保てるが、置き場が 2 つになり控えの照合が増える）。
**代案 C**: セッションのたびに zip を手で上げる（Cowork でこれまでやってきた方法・人手が要るので目的に反する）。

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

## 8. 判断が要る点（推しつき）

1. **ネットの置き場**（§6.1）: 案 A（main で現行ネットだけ管理）／案 B（別リポジトリ）／案 C（手上げ）。**推し A**。
2. **移設先の経路**（§3）: `C:\dev\meicho_engine_v0.1`。別の場所がよければそこに読み替える（**ASCII だけ・空白なし**が条件）。**推し `C:\dev`**。
3. **`stage1b-encoding-v5` ブランチと `stage1b-rust.yml`**: Codex の作業の名残。**推し: 段 1 のあとに消す**（段階1B は D-089/D-091 で閉じており、ブランチの中身は main に merge 済み——`logs/HEAD` の最後の pull が ort strategy の merge）。消す前に GitHub の画面で「This branch is N commits behind main」で ahead が 0 であることを見る。
4. **段 3 以後の commit を誰が押すか**: 最初のうちは**マスターが GitHub Desktop で押す**（`Changes` の一覧を目で見る工程を残す）。段 5 のあと、Claude Code に「ブランチに commit・push まで」を許す。**推し: 段階的に**。
5. **Cowork の書き戻しの作法（LANES §5）をどうするか**: 段 2 で OneDrive の外に出れば「written でも載らない」事故は消える見込みだが、**再ステージしてバイト比較する決まりは段 5 まで残す**（消えたことを 5 回以上の書き戻しで確かめてから緩める）。**推し: 残す**。
6. **GITHUB_SETUP §7「リポジトリは正本ではない」**: 段 2 のあとも **正本は PC のフォルダ**のまま（LANES §10）。ただし「GitHub は貼るための置き場」から「クラウドの起点」に役目が増えるので、§7 を「正本は PC・GitHub は写し・push 忘れはクラウドの起点が古くなる」に書き換える。**推し: 書き換える**。

---

## 9. 裁定のあとに台帳へ落とすこと（クロエがやる・エンジンの持ち場の 1 チャットで）

- `engine/decisions.md` に D-番号を 1 つ（本書の採用と §8 の裁定。末尾の番号は書く直前に PC で見る）。
- `TASKS.md` Active の「監査の採用 2 件の実行（D-126）」の (5) を、本書の段 1〜6 に置き換える（段ごとに `[ ]`）。
- `LANES.md` §10 を「見直した（本書）」に更新し、§5 の書き戻しの作法に「段 5 まで残す」を明記。
- `CLAUDE.md` の罠の節に「push を忘れるとクラウドの起点が古い」を 1 行足す。
- `GITHUB_SETUP.md` §7 を §8-6 のとおり書き換える。
- `experiments/provenance.py` の `HOSTS` に `cc-cloud-4`（§6.2・検査があれば同時に）。
- `.gitignore` に §6.1 の 3 行（案 A のとき）。

---

## 10. この文書で言えないこと

- クラウドセッションの機械が「4 コア 2.8GHz・15GiB」であることはマスターの報告で、クロエは測っていない。§6.4 の最初の 1 行で毎回測らせる。
- `tests.yml` の最初の実行で何件落ちるかは分からない（資材の無い検査の数は作業環境の実測 25 件が目安）。**最初の失敗一覧を読んでから CI の除外を決める**。
- 段 3 の Claude Code が依頼書どおりに動くかは、最初の 1 回を人が照合するまで分からない。**報告と実物の照合は残す**。
