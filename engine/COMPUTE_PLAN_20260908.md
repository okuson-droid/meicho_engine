# 計算資源の計画 — 長い測定をどこで回すか（2026-09-08）

rules_draft.md v0.11 準拠 / engine v0.1 / champion = `planner_vb3cps`（交代していない）
裁定は `decisions.md` D-072。報告の作法は `REPORTING_RULES.md`（作業依頼は §2.6 の 5 点セット）。
関連: `LITERATURE_PLAN_20260906.md` §3.5・§4.2（D-069(5) 「輪 2 は Kaggle に寄せる」）、
`HANDOFF_20260905_D065_BIN4.md` §5（作業環境の制約）、`RUST_PORT_NOTES.md`（wheel の扱い）。

---

## 0. 結論（先に）

1. **長い測定は無料の Kaggle ノートブックに移す。** 4 コア・約 30 GB メモリ・1 回 12 時間まで・
   「Save & Run All」で**ブラウザを閉じても裏で走り続ける**。費用 0 円。
   いまの作業環境（2 コア・1 コマンド 600 秒・10 分放置で消滅）に無い性質はこの「裏で走り続ける」である。
2. **作業環境は短い測定と実装・検査に絞る。** 目安は 1 本 30 分以内（回帰局面・fingerprint・錨 1 候補・検査）。
3. **有料の時間貸し VM（GCP など）は、Kaggle の 4 コアで待ちきれないと分かってから足す。**
   マスターの方針は「まず無料枠だけ」（2026-09-08）。有料化の判断は §6 の条件で行い、勝手に始めない。
4. **Colab と Hetzner は今回は採らない。** Colab は CPU 主体の長時間ジョブに向かず、裏で回し続ける契約は
   月 50 ドル級。Hetzner は 2026 年 6 月の値上げで専用コアが 4 コア月 100 ユーロ級になり、
   常時回さないこのプロジェクトには合わない。
5. **どの機械で回しても結果は同じ。** Python・Linux Rust・Windows Rust の三者一致（D-052）は確認済みで、
   同じシード・同じ wheel なら同じ結果が出る。したがって Kaggle で取った記録は、いまの帯の記録と
   そのまま対にできる。**ただし wheel は必ず Kaggle 上でソースからビルドする**（§4.3。`rust/dist/` の
   Linux 用 wheel は便 A より古く、`lethal_uniform` を持たない）。
6. **測定規律は変えない。** 帯の台帳（`seed_bands.json`）・同シード対照・manifest の持ち帰り・由来
   （provenance）・1,000 局ごとの報告は、そのまま Kaggle の運用にも適用する（§5）。

---

## 1. いま何に時間を取られているか

### 1.1 作業環境の制約（`HANDOFF_20260905_D065_BIN4.md` §5）

- Linux・2 コア。
- `bash` 1 回の上限 600 秒。長い測定は `--budget-sec 480` の塊に割り、`--resume` で継ぎ足す。
- 約 10 分の無操作でコンテナごと回収される。`nohup` の裏プロセスは死ぬ
  （2026-09-07 に門番 1 回ぶん・約 45 分を丸ごと失った）。
- 毎回まっさら。engine 一式の持ち込み（50 ファイル/回）と wheel のビルドから始まる。

### 1.2 測定の実測費用（すべて Rust 版・2 コア・workers=2）

| 測定 | 実測 | 出典 |
|---|---|---|
| champion 同士 1 局 | 1.09 秒 | D065_NOTES（蒸留後） |
| 門番 1 局（champion 対 候補） | 2.3 秒（26 局/分） | D065_NOTES 便 4 |
| 門番 n=1,200 | 約 46 分 | 同上 |
| 錨 3 種 × 600 対（1 候補） | 約 35 分 | HANDOFF_LIT_A §4.3 |
| 被搾取（透視カウンター 300 局・1 本） | 1〜1.5 時間 | HANDOFF_LIT_A §4.4 |
| 詰み見逃し（4 本 × 70 局。1 局 10〜20 秒） | 1〜2 時間 | HANDOFF_LIT_A §4.2 |
| ラダー core5 v8（11 体・66 組・17,600 局） | 255 分 | D065_NOTES |
| ラダー core5 v9（12〜13 体） | 5〜6 時間（見込み） | HANDOFF_LIT_A §7.1 |
| 輪 2 の 1 反復（記録・τ の下見・門番と錨） | 約 6 時間 | D065_NOTES・LITERATURE_PLAN §3.5 |
| 学習（V のネット 1 本） | 十数分（GPU） | D065_NOTES |
| 検査一式 | 約 7 分 | HANDOFF_D065_BIN4 |

便 A（前半）の測定一式（詰み見逃し・錨 3 候補・被搾取・門番）はおよそ 13〜16 時間（2 コア換算）で、
480 秒の塊に割ると **100 回以上の再開**になった。残っているのはラダー v9（5〜6 時間・交代する場合）と
輪 2 の反復 5' 以降（1 反復 6 時間 × 複数）である。

### 1.3 並列化の余地

対局はシードごとに独立で、`--workers` の数に比例して速くなる（Rust 版はスレッド並列）。
2 コア → 4 コアで約 2 倍、16 コアで約 8 倍。**測定の中身を変えずに機械だけで縮む種類の遅さ**である。
例外は学習（`drl_train.py`）で、これは CPU 並列でなく GPU が効く。

---

## 2. 候補の比較

「1 回あたり何時間・何コアで回せるか」「裏で走り続けるか」「費用」の 3 点で見る。
価格は 2026-09-08 時点の公開情報で、変わりうる。金額は目安として読むこと。

### 2.1 Kaggle ノートブック（無料）

- CPU セッション: 4 コア・約 30 GB メモリ・1 セッション最長 12 時間（2020 年に 9 → 12 時間に延長）。
- GPU セッション: T4 ×2 または P100。週 30 時間まで。学習の十数分にはこれで足りる。
- **「Save & Run All (Commit)」で実行すると、ブラウザを閉じても最長 12 時間まで裏で走る。**
  出力（`/kaggle/working` 以下）はノートブックの「Output」として保存され、次の実行の入力に使える。
- インターネット接続つきのノートブックには電話番号による本人確認が要る（`pip install` に必要）。
- 弱点: 4 コアという上限（作業環境の 2 倍止まり）。コードを非公開データセットとして置く手間。
  12 時間で切れるので `--resume` が前提。
- メモリ 30 GB は、輪 1 で「3 反復ぶん 234 万決定が 7 GB に入らなかった」（VALUE_BOOTSTRAP §41）を解く。

### 2.2 Google Colab

- 無料枠は「最長 12 時間だが、それより早く切られることがある」と明記され、CPU 主体の 6 時間ジョブの
  完走は保証されない。裏で走り続ける機能は Pro+（月 50 ドル前後）から。
- CPU 仕事に対して Kaggle より優れる点が無い。**採らない。**

### 2.3 時間貸し VM（GCP / AWS のスポット）

- 例: GCP `c3d-highcpu-8`（8 vCPU）の通常価格が約 0.30 ドル/時（us-central1）。16 vCPU で約 0.60 ドル/時。
  スポット（空きを安く借りる代わりに突然止められる契約）は通常価格の 3 分の 1 程度が相場だが、
  **本日はその数字を一次情報で確かめられていない**。
- 見積り: 便 A 級の測定一式（約 30 コア時間）は 16 vCPU で約 2 時間・通常価格で 1〜2 ドル。
  輪 2 の 1 反復（約 12 コア時間）は 1 時間弱。**月 100 時間回しても数千円**に収まる見込み。
- 突然止められても `probe_d065.py` / `eval_vb.py` / `ladder.py` / `scan_missed_lethal.py` は `--resume` が
  入っているので、帯の途中から続けられる。
- 弱点: アカウント作成・請求先の登録・起動と停止の管理がマスターの手に乗る。止め忘れると課金が続く。
- GCP は新規登録に無料クレジット（300 ドル・90 日）の制度があったが、**現時点の条件は申込画面で
  確かめること**（本計画では当てにしない）。

### 2.4 Hetzner（月額固定の VPS）

- 2026 年 6 月 15 日の改定で専用コアの CPX/CCX が 2 倍以上に値上がり（CPX52 4 vCPU が月 100.49 ユーロ、
  CCX63 8 vCPU が月 853.49 ユーロ）。共有コアの CX23（2 vCPU）は月 5.49 ユーロだが 2 コアでは意味が無い。
- 測定は断続的なので月額固定は不利。**採らない。**

### 2.5 比較のまとめ

| 候補 | コア | 1 回の上限 | 裏で走るか | 費用 | 判定 |
|---|---|---|---|---|---|
| 作業環境（現状） | 2 | 600 秒 × 再開 | 走らない（10 分で消える） | 0 | 短い測定と実装に限る |
| **Kaggle** | **4** | **12 時間** | **走る** | **0** | **段 1・本命** |
| Colab 無料 | 2 程度 | 不定（12 時間以下） | 走らない | 0 | 採らない |
| Colab Pro+ | 不定 | 24 時間 | 走る | 月 50 ドル級 | 採らない |
| GCP/AWS スポット | 8〜32 | 無制限（中断あり） | 走る | 時間あたり数十円〜 | 段 2・条件つき |
| Hetzner 専用コア | 4〜8 | 無制限 | 走る | 月 100 ユーロ級〜 | 採らない |

---

## 3. 方針: 二段構え

### 3.1 段 1（今週・無料）— Kaggle に「長い測定」を寄せる

分担を次のとおり固定する。

| 場所 | 回すもの | 上限の目安 |
|---|---|---|
| 作業環境（2 コア） | 実装・検査（7 分）・回帰局面 T-14・fingerprint・錨 1 候補（35 分）・門番 1 本（46 分） | 1 本 1 時間まで。それ以上は Kaggle |
| Kaggle CPU（4 コア） | ラダー v9（5〜6 時間 → 約 3 時間）・輪 2 の記録（21 時間 → 約 10 時間・2 回に分割）・被搾取・詰み見逃し | 12 時間/回。`--resume` で継ぐ |
| Kaggle GPU（週 30 時間） | 学習（`drl_train.py`・十数分） | — |
| マスターの PC | 対人局・アプリ・再ビルド・結果の保管（正本） | — |

最初の 1 回は測定ではなく**機械の差が無いことの確認**（§4.3）に使う。これを通してから本番の測定に入る。

### 3.2 段 2（条件つき・有料）— 時間貸し VM

§6 の条件を満たしたときだけ、GCP のスポット VM（16 vCPU）を測定のときだけ起こす。
起動スクリプトで wheel のビルドから測定の再開まで自動化し、マスターの操作は「起動」と「停止」だけにする。
段 2 の手順書は、条件を満たした時点で 5 点セットで別に書く（本計画には含めない）。

---

## 4. Kaggle 導入の手順（マスターへの依頼・5 点セット）

**なぜ今これが要るのか**: 残っている長い測定（ラダー v9・輪 2 の反復 5' 以降）は作業環境では
1 本 5〜6 時間以上で、480 秒ごとの再開を 40 回以上繰り返すことになる。Kaggle なら 1 回の操作で
裏で走り切る。アカウント作成と本人確認はマスターにしかできない。

### 4.1 アカウントを作る（マスター・約 10 分）

1. **どこで**: ブラウザで https://www.kaggle.com/ を開く。
2. **何をするか**: 「Register」から Google アカウントまたはメールで登録する。
   登録後、右上のアイコン → **Settings** → **Phone Verification** で電話番号を登録し、届いた確認コードを入力する。
3. **成功したらどう見えるか**: Settings の Phone Verification に「Verified」と表示される。
4. **確認のしかた**: 新しいノートブック（Code → New Notebook）を開き、右側の設定パネルに
   「Internet」のスイッチが現れ、On にできること。
5. **転びやすいところ**: Internet のスイッチが灰色で押せない → 本人確認が済んでいない（`pip install` も
   rustup も動かない）。Phone Verification に戻る。

### 4.2 engine 一式を非公開データセットとして置く（マスター・約 15 分）

1. **どこで**: マスターの PC・PowerShell。作業ディレクトリは
   `C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1`。
2. **何を打つか**（1 行ずつ。zip は OneDrive の外に作る）:
   ```powershell
   cd "C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1"
   New-Item -ItemType Directory -Force "C:\kaggle_bundle" | Out-Null
   Copy-Item -Recurse -Force engine "C:\kaggle_bundle\engine"
   New-Item -ItemType Directory -Force "C:\kaggle_bundle\cards" | Out-Null
   Copy-Item cards\cards_structured.csv, cards\cards_structured.json "C:\kaggle_bundle\cards\"
   Remove-Item -Recurse -Force "C:\kaggle_bundle\engine\rust\target" -ErrorAction SilentlyContinue
   Get-ChildItem -Recurse -Directory -Filter "__pycache__" "C:\kaggle_bundle" | Remove-Item -Recurse -Force
   Get-ChildItem -Recurse -Directory -Filter ".pytest_cache" "C:\kaggle_bundle" | Remove-Item -Recurse -Force
   Compress-Archive -Path "C:\kaggle_bundle\engine", "C:\kaggle_bundle\cards" -DestinationPath "C:\kaggle_bundle\meicho_bundle.zip" -Force
   ```
   **カード画像（`cards/*.png`）は入れない。** 構造化データ（csv/json）だけを入れる。
   データセットは**必ず Private**にする（プロジェクトの制約「カード画像・公式テキストの複製を公開しない」）。
3. **成功したらどう見えるか**: `C:\kaggle_bundle\meicho_bundle.zip` ができる（数十 MB〜100 MB 程度。
   `results/models/*.json` が大半）。
4. **Kaggle に上げる**: https://www.kaggle.com/datasets → **New Dataset** → zip をドラッグ →
   タイトルを `meicho-engine` にする → 右側の可視性が **Private** であることを確認 → **Create**。
   出来上がった URL の末尾（`/datasets/<ユーザー名>/meicho-engine`）を控える。
5. **確認のしかた**: データセットのページの「Data」タブに `engine/` と `cards/` のフォルダが見える
   （Kaggle は zip を展開して置く）。見えなければ zip がそのまま置かれているので、§4.3 のセル 1 が展開する。
6. **転びやすいところ**:
   - `Compress-Archive` が「パスが長すぎる」で落ちる → `C:\kaggle_bundle` に置いたのはそのため。
     OneDrive の下で zip を作らない。
   - アップロードが途中で止まる → `results/datasets/*.gz` と `results/models/*_s1.json` など古い
     モデルを除いても検査は通る（§4.4 の検査で 7 件落ちるのは `gauntlets/`・`datasets/`・`models/c1_*.json`
     を忘れたときで、別物）。
   - Public のまま作ってしまった → データセットの Settings → Visibility を Private にする。

### 4.3 ノートブックを作って「機械の差が無いこと」を確かめる（マスター・操作 10 分・実行 15 分）

1. **どこで**: Kaggle の **Code → New Notebook**。右側の設定パネルで
   **Accelerator: None**（CPU）、**Internet: On**、**Persistence: Files only** にする。
   **Add Input** → **Datasets** → 自分の `meicho-engine` を選ぶ。
2. **何を打つか**: 次の 4 セルを順に貼り、上から実行する（各セルの先頭の `%%bash` を含めてそのまま）。

   セル 1 — 持ち込みと展開:
   ```bash
   %%bash
   set -e
   SRC=$(ls -d /kaggle/input/meicho-engine* | head -1)
   echo "input: $SRC"
   rm -rf /kaggle/working/proj && mkdir -p /kaggle/working/proj
   if ls "$SRC"/*.zip >/dev/null 2>&1; then unzip -q "$SRC"/*.zip -d /kaggle/working/proj
   else cp -r "$SRC"/engine "$SRC"/cards /kaggle/working/proj/; fi
   ls /kaggle/working/proj/engine | head
   python3 --version
   nproc; free -g | head -2
   ```
   セル 2 — Rust の wheel をソースからビルドして入れる（**`rust/dist/` の Linux 用 wheel は使わない**。
   便 A より古く `lethal_uniform` を持たない）:
   ```bash
   %%bash
   set -e
   curl -sSf https://sh.rustup.rs | sh -s -- -y >/dev/null
   export PATH="$HOME/.cargo/bin:$PATH"
   pip install -q maturin
   cd /kaggle/working/proj/engine/rust
   export CARGO_TARGET_DIR=/kaggle/working/cargo_target
   maturin build --release --out /kaggle/working/wheels
   pip install -q --force-reinstall --no-deps /kaggle/working/wheels/meicho_rs-*.whl
   python3 -c "import meicho_rs; print(meicho_rs.features())"
   ```
   セル 3 — 依存と検査:
   ```bash
   %%bash
   set -e
   pip install -q pytest torch
   cd /kaggle/working/proj/engine
   python3 -m pytest tests/ -q --ignore=tests/test_discovery.py -x 2>&1 | tail -5
   ```
   セル 4 — fingerprint（機械の差が無いことの確認）:
   ```bash
   %%bash
   set -e
   cd /kaggle/working/proj/engine
   python3 experiments/bench_agents.py 2>&1 | tail -8
   python3 -m pytest tests/test_lit_d.py::test_champion_fingerprint_unchanged_lit_d -q 2>&1 | tail -3
   ```
3. **成功したらどう見えるか**:
   - セル 1: `Python 3.11.x`（3.12 でもセル 2 がその版の wheel を作るので問題ない）、`nproc` が `4`、
     `free -g` の total が 30 前後。
   - セル 2: 最後の行に `lethal_uniform` を含む札の一覧（例 `['digest', ..., 'lethal_uniform']`）。
     **`lethal_uniform` が無ければ古い wheel が入っている**。
   - セル 3: `xxx passed, 2 skipped`（落ちるもの 0。件数は便 A 後の値。`test_discovery.py` は別に回す）。
   - セル 4: fingerprint 3 種 `773a71c15c5bc16e` / `677f28cc3b6995ee` / `6e39c2aa4b35d876`（Python 実装の値）
     と、champion の `1 passed`（`7251a931d252a57a` と一致）。
4. **確認のしかた**: セル 4 の 4 つの値が上と一致していれば、Kaggle の機械で取る記録はいまの帯の記録と
   同じ意味を持つ。**1 つでも違えば、そのノートブックで測定を始めてはならない**（値を控えて報告する）。
5. **転びやすいところと症状**:

   | 症状 | 意味 | 直し方 |
   |---|---|---|
   | セル 2 で `curl: (6) Could not resolve host` | Internet が Off | 設定パネルで On にして再実行 |
   | セル 2 の `maturin build` が 5 分以上 | 初回のフルビルド（依存 crate の取得） | 待つ。2 回目以降は `cargo_target` が残るので速い |
   | `features()` に `lethal_uniform` が無い | `dist/` の古い wheel が先に入っている | セル 2 をそのまま再実行（`--force-reinstall`） |
   | セル 3 で 7 件落ちる | `experiments/gauntlets/`・`datasets/`・`results/models/c1_*.json` が zip に無い | §4.2 の zip を作り直す |
   | セル 3 で `torch` 絡みが落ちる | Kaggle の torch と版が違う | `pip install torch` を外して Kaggle 同梱の torch で再実行 |
   | セル 4 の fingerprint が違う | 機械の差ではなく**コードが違う**（zip が古いか、作業中の版が混ざった） | zip を作った時点の `git`/ファイル更新日時を確認し、作業環境の版と揃える |

### 4.4 本番の測定を裏で回す（型・以後の引継ぎ書はこの型で書く）

1. **どこで**: §4.3 のノートブック。セル 1〜3 はそのまま残す（毎回の実行で環境を作り直す）。
2. **何を打つか**: セル 5 に測定コマンドを置く。`--workers 4`・`--resume`・`--budget-sec 41400`（11.5 時間。
   12 時間の上限の手前で自分から止まる）を必ず付け、出力は `/kaggle/working/proj/engine/results/` の下に書く。
   例（ラダー v9 の場合。実際の引数は引継ぎ書の値を使う）:
   ```bash
   %%bash
   cd /kaggle/working/proj/engine
   # 前回の出力があれば results に戻す（2 回目以降。§4.4-6）
   if [ -d /kaggle/input/prev-run ]; then cp -r /kaggle/input/prev-run/results/. results/; fi
   python3 experiments/ladder.py core5 --engine auto --workers 4 --resume results/ladder_resume_core5.json --budget-sec 41400 2>&1 | tee results/kaggle_run.log
   ```
   貼ったら、右上の **Save Version** → **Save & Run All (Commit)** → **Save**。ブラウザは閉じてよい。
3. **成功したらどう見えるか**: ノートブックの右上「Versions」で実行中の版が **Running** → **Complete** になる。
   「Output」タブに `results/` 以下のファイル（`ladder.json`・`*.manifest.json`・`kaggle_run.log`）が並ぶ。
4. **確認のしかた**: `kaggle_run.log` の末尾に、そのスクリプトの完了行（ラダーなら順位表、`probe_d065` なら
   勝率と区間）があること。`--budget-sec` で止まった場合は「再開可能」の旨が出る。
5. **終わったら何を送るか**: Output から `results/` 以下の **JSON・manifest・log をすべて**ダウンロードし、
   マスターの PC の `engine/results/` の同じ場所に置く（**正本はマスターの PC**。Kaggle に置いたままにしない）。
   `.bin`（記録本体）は持ち帰らない（D-065 便 3 の規約。manifest があれば `regenerate` で作り直せる）。
6. **12 時間で切れたとき（2 回目以降の実行）**: そのノートブックの **Add Input → Your Work → Notebooks** から
   前回の版の出力を入力に足し（`/kaggle/input/<ノートブック名>` として見える。セル 5 の `prev-run` を
   その名前に読み替える）、同じセル 5 をもう一度 **Save & Run All** する。`--resume` が帯の途中から続ける。
7. **転びやすいところ**:

   | 症状 | 意味 | 直し方 |
   |---|---|---|
   | Versions で **Failed**・ログが途中で切れる | 12 時間の上限か、メモリ超過 | `--budget-sec` を 41400 以下にしているか確認。メモリなら `--workers 2` |
   | Output が空 | 出力先が `/kaggle/working` の外 | パスを `/kaggle/working/proj/engine/results/` に |
   | 再開したのに最初から回る | 前回の出力を results に戻していない | セル 5 の `cp` 行と入力の追加を確認 |
   | 実行が Queued のまま進まない | 同時実行の上限（CPU セッションは複数まで。上限は画面の表示に従う） | 他の実行が終わるのを待つ |

---

## 5. 規約（Kaggle で回すときも変えないこと）

1. **帯の台帳**: 使う帯は作業環境の `seed_bands.json` に**先に**登録し、zip に含めてから回す。
   Kaggle 上で帯を切らない（台帳は複数セッションが触る。書く前に必ず読む）。
2. **同シード対照**: 候補と対照（`null`）は同じ帯・同じ `--workers` で回す。workers は結果を変えない
   （シードごとに決定的）が、**速度の数字は workers とセットで記録する**。
3. **由来**: `provenance.py` が出す sha256 つきの由来ブロックには `engine` と `rust_features`（wheel の札）が
   既に入る。これに `extra` として `host`（`kaggle-cpu-4` / `workenv-2` / `gcp-c3d-16`）と `workers` を足す
   （`provenance.block(..., extra={"host": ..., "workers": ...})`。呼び出し側 4 本の小さな変更。便の実装時に行う）。
   作業環境で取った記録と混ぜてもどこで取ったか分かるようにする。
4. **manifest の持ち帰り**: 記録を取ったら `.manifest.json` を必ずマスターの PC に書き戻す。`.bin` は持ち帰らない。
5. **報告**: 1,000 局ごとの定期報告は、Kaggle では `kaggle_run.log` の進捗行が代わりになる
   （裏で走っている間は誰も見ていない）。完了後の報告で「何局を何時間で・どの機械で」を必ず書く。
6. **公開しない**: データセット・ノートブックとも Private のまま。カード画像は入れない。
7. **fingerprint を先に**: ノートブックの環境を作り直すたび（zip を更新したとき）に §4.3 のセル 4 を通す。

---

## 6. 段 2（有料 VM）に進む条件

次の**どれか**を満たしたとき、段 2 の手順書（5 点セット）を書いて裁定に出す。それまでは進まない。

1. Kaggle の 12 時間 × 4 コアで 1 本の測定が 3 回以上の再開を要する（＝36 時間超）。
2. 輪 2 の反復を週 2 回以上回したいのに、Kaggle の実行待ち（Queued）や週の GPU 枠で詰まる。
3. 発売後のフェーズ 3（マッチアップ勝率行列）でデッキ数が増え、行列 1 枚が 100 時間（2 コア換算）を超える。

進むときの第一候補は GCP のスポット VM（16 vCPU）。費用の上限（例: 月 3,000 円）を先に決め、
止め忘れ対策（自動停止のスケジュール）を手順書に含める。

---

## 7. 未確認事項（Kaggle 上で初回に確かめる）

- Kaggle の Python の版（3.11 か 3.12 か）。どちらでもセル 2 が対応する wheel を作る。
- CPU セッションの同時実行数の上限と、週あたりの CPU 時間の上限の有無（GPU は週 30 時間。CPU は
  明示の週枠が無いと理解しているが、画面の表示を正とする）。
- zip をアップロードしたとき Kaggle が自動展開するか（セル 1 は両方に対応）。
- `pip install torch` が Kaggle 同梱の torch と衝突しないか（衝突したら同梱版を使う）。
- 4 コアでの実測速度（champion 同士・門番・ラダー）。**初回の本番測定で速度を記録し、§1.2 の表に
  「Kaggle 4 コア」の列を足す。**

---

## 8. 出典（2026-09-08 に確認した公開情報）

- Kaggle Product Update: セッション上限 9 → 12 時間 — https://www.kaggle.com/discussions/product-feedback/302908
- Kaggle Notebooks Documentation — https://www.kaggle.com/docs/notebooks
- Kaggle の使い方まとめ（2025-11・GPU 週 30 時間・12 時間/回） — https://huggingface.co/datasets/John6666/knowledge_base_md_for_rag_1/blob/main/kaggle_20251121.md
- Google Colab 2026 guide（無料枠は最長 12 時間・保証なし。Pro/Pro+ の価格） — https://joshthompson.co.uk/ai/google-colab-2026-guide-free-compute-automations-pro-tips/
- Google Colab pricing — https://aisotools.com/pricing/google-colab
- Hetzner 2026 年 6 月の値上げ — https://wz-it.com/en/blog/hetzner-price-increase-june-2026-cpx-ccx-alternatives/
- GCP Compute Engine 料金表（CloudPrice・us-central1 通常価格） — https://cloudprice.net/gcp/compute
