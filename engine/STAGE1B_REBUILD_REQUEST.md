# 依頼 — 段階1B を PC に反映する（ネット移行 → Rust 再ビルド → 検査）

2026-09-15・クロエ。根拠は `engine/decisions.md` D-089、`engine/STAGE1B_NOTES.md`。
準拠版: rules_draft v0.12 ／ engine v0.1 ／ 符号化 **v5**（`ENCODING_VERSION = 5`）。

---

## なぜ今それが要るか

段階1B のマージで `ENCODING_VERSION` が 4 → **5** に上がり、Python 側（`meicho/encode.py`・
`engine.py`・`state.py`）と Rust の**ソース**（`rust/src/` の `encode.rs`・`engine.rs`・`lib.rs`・
`state.rs`・`agents.rs`・`intervene.rs`）が書き換わった。

しかし PC の状態は次の 2 点で取り残されている。

1. **Windows の wheel が 2026-09-13 のまま**（`engine/rust/dist/meicho_rs-0.1.0-cp311-cp311-win_amd64.whl`）。
   `.pyd`（Python から呼ばれる Rust の実体）はソースと一緒には配られないので、再ビルドするまで
   PC の Rust は符号化 v4 のままである。**Python が v5 で Rust が v4 という食い違った状態**であり、
   D-085 追記 1 と同じく対局が始められない可能性が高い。
2. **学習済みネット 12 本が v4 のまま**（`engine/results/models/`。`.enc4.bak.json` が 1 つも無い）。
   移行しないと champion が読み込めない。

D-089 は段階1B の完了条件を「**PC での Rust 再ビルド・一致検査・実在 v4 モデルの移行**」と
明記して Active に残している。この依頼はその 3 つである。

**D-089 の但し書き（重要）**: 作業環境には `cargo` / `rustc` が無く、apt 導入も権限で失敗したため、
**Rust はビルドも毎手一致も未確認**のまま記録されている。`.github/workflows/stage1b-rust.yml`
（Ubuntu で Rust を建てて一致検査 5 本を回す CI）は追加されているが、**それが通ったという記録は
decisions.md に無い**。したがってこの再ビルドは「Windows への反映」であると同時に、
**Rust が通ること自体の初めての確認**でもある。コンパイルエラーで止まることは十分ありうる。

---

## (1) どこで

リポジトリのルートは

```
C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1
```

手順 A と C は `engine`（`meicho\` と `tests\` がある階層）、
手順 B は `engine\rust`（`Cargo.toml` がある階層）で行う。

**先に `git status` が clean であることを確かめる。** 途中で書き換わるのは
`results\models\*.json`（移行）と `rust\dist\*.whl`（ビルド）だけである。

---

## (2) 何を打つか

### 手順 A — ネットの移行（12 本・Rust 不要）

```
cd engine
python scripts\migrate_nets_stage1b.py --check results\models\drl_sd001_s1.json results\models\drl_sd001_s2r1.json results\models\drl_sd001_vb1.json results\models\drl_sd001_vb2.json results\models\drl_sd001_vb3.json results\models\drl_sd001_vb4.json results\models\drl_sd001_vb4w.json results\models\drl_sd001_vc4.json results\models\drl_sd001_vc4a.json results\models\drl_sd001_vc4b.json results\models\drl_sd02_s1.json results\models\pi_small64_e10.json
```

`--check` は**書き換えない**。12 本すべてが通ることを見てから、同じ行から `--check` だけを
外してもう一度打つ。

```
python scripts\migrate_nets_stage1b.py results\models\drl_sd001_s1.json results\models\drl_sd001_s2r1.json results\models\drl_sd001_vb1.json results\models\drl_sd001_vb2.json results\models\drl_sd001_vb3.json results\models\drl_sd001_vb4.json results\models\drl_sd001_vb4w.json results\models\drl_sd001_vc4.json results\models\drl_sd001_vc4a.json results\models\drl_sd001_vc4b.json results\models\drl_sd02_s1.json results\models\pi_small64_e10.json
```

**★ `results\models\*.json` のようなワイルドカードで打たないこと。** 同じフォルダに
`*.meta.json`（メタ情報）と `*.enc3.bak.json`（版3の控え）があり、どちらもネットではないので
assert で落ちる。**12 本を名指しする上の行をそのまま使うこと。**

### 手順 B — Rust の再ビルド

```
cd ..\engine\rust
cargo build --release
maturin build --release --out dist
pip install --force-reinstall dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
```

4 行目のファイル名は環境で変わることがある。`dir dist` で `.whl` の名前を確かめて、
できたものをそのまま指定する。

### 手順 C — 検査

```
cd ..
python -c "import meicho_rs; print(meicho_rs.encoding_info())"
python -m pytest tests\test_stage1b_encoding.py tests\test_stage1a_choices.py tests\test_drl.py tests\test_rust_engine.py tests\test_rust_agents.py -q
python experiments\bench_agents.py
python scripts\check_champion_fingerprint.py
```

ここまでが通ったら、最後に全検査を回す（**約 1 時間**かかる。D-083 のときは 1 時間 7 分）。

```
python -m pytest -q
```

---

## (3) 成功したらどう見えるか

**手順 A**: 12 行、それぞれ

```
drl_sd001_vc4.json: migrated max_abs=3.55e-15
```

の形で出る。`max_abs` は移行前後の出力の食い違いで、**すべて 1e-10 未満**なら無損失である
（assert で止まるので、行が出た時点で条件は満たしている）。
`--check` のときは `migrated` ではなく `checked` と出る。

**生成されるファイル**: `results\models\*.enc4.bak.json` が 12 本。**原本の控えなので消さない。**

**手順 B**:

- `cargo build --release` の最後に ``Finished `release` profile [optimized] target(s) in ...``
- `maturin build --release --out dist` の最後に
  `📦 Built wheel ... to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl`
- `pip install` の最後に `Successfully installed meicho_rs-0.1.0`
- **生成されるファイル**: `engine\rust\dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl`
  （前の版は 625,554 バイト・2026-09-13。バイト数が変わっているはず）

---

## (4) 確認のしかた（期待値つき）

1. **`meicho_rs.encoding_info()`** → **`(5, 1825, 317)`**
   （符号化の版・観測の長さ・行動の長さ。D-089 の記載と一致する）
   - `(4, 1313, 226)` が出たら **古い `.pyd` をまだ読んでいる**。手順 B の `pip install` に戻る。

2. **一致検査 5 本** → **失敗 0**。skip があってもよいが、件数と理由を書く。
   `test_rust_engine.py` と `test_rust_agents.py` が「Rust が無い」で skip したら、
   それは**通ったのではなく**、`pip install` が効いていない。

3. **`experiments\bench_agents.py`** → fingerprint 3 種が
   **`773a71c15c5bc16e` / `677f28cc3b6995ee` / `6e39c2aa4b35d876`** のままであること。
   この 3 つは学習しない AI なので、符号化を変えても動かないのが正しい。

4. **`scripts\check_champion_fingerprint.py`** → champion `planner_vc4cps_kheb_b75` の指紋が
   **`e1662edb32b144a9`** のままであること。
   - **★ここは動く可能性がある。** 移行の検算は float64 では厳密一致だが、**実際の推論は float32** で、
     v4 → v5 でゼロの列が増えたぶん足し算の順序が変わりうる（D-079 追記 2 で踏んだのと同じ形）。
     **動いていたら、そこで止めて値を連絡してほしい。** 直し方をこちらで決める。
     指紋が動いた状態は「打ち方が変わった」ということなので、**過去の勝率がすべて読み直しになる。**

5. **全検査** → 通過・失敗・skip の**件数と、skip の内訳**を書く。
   D-089 の作業環境では 391 通過・**48 失敗**・115 skip で、失敗は Git 管理外の資産・モデル・
   Linux 版 Rust が無いことによるものだった。**PC では資産もモデルも Rust も揃うので、
   その 48 件は消えるはず**である。消えなければ本物の失敗なので、落ちた名前を連絡してほしい。

---

## (5) 転びやすいところと、その症状

- **`maturin` が見つからない** → `pip install maturin` を先に打つ。
- **`pip install` が `already satisfied` で終わる** → `--force-reinstall` を付け忘れている。
  版番号が 0.1.0 のままなので、付けないと古い `.pyd` が残る。
  **症状は (4) の 1 つ目が `(4, 1313, 226)` を返すこと。**
- **`dist\` が空** → 過去に `target\wheels` を見る手順と混ざった事故がある。
  `--out dist` を付けた行を打ったか確かめる。
- **`error: linker \`link.exe\` not found`** → Visual Studio の C++ ビルドツールが入っていない。
  Rust の再ビルド自体ができないので、そこで止めて連絡すること。
- **`error[E0433]` などの Rust のコンパイルエラー** → **これは十分ありうる。**
  D-089 の作業環境では Rust を一度もビルドしていない（構文解析まで）。
  エラー文をそのまま貼ってくれれば直す。**自分で直そうとしなくてよい。**
- **手順 A で `AssertionError` が出る** → ワイルドカードで `*.meta.json` か `*.enc3.bak.json` を
  拾っている。12 本を名指しする行に戻る。
- **手順 A が `already` と出る** → そのファイルは移行済み。2 回打っても壊れないので、
  そのまま次へ進んでよい。
- **文字化けして落ちる（`UnicodeEncodeError`）** → 日本語 Windows の cp932。
  出力をパイプやリダイレクトに向けず、コンソールにそのまま出す。
- **OneDrive の同期とぶつかる**（`Permission denied` / `unable to index file`）
  → OneDrive を一時停止してからやり直す。

---

## 報告してほしいこと

1. `encoding_info()` が返した 3 つ組
2. 手順 A の 12 行（`max_abs` の値つき）
3. 一致検査 5 本の通過・失敗・skip の件数と、skip の理由
4. fingerprint 3 種と champion の指紋（**動いたかどうかを明記**）
5. 全検査の通過・失敗・skip の件数と、skip の内訳
6. 新しい wheel のバイト数と日時

止まった場合は、**止まった手順の番号とエラー文をそのまま**貼ってほしい。
途中まででも構わない。回していないものを回したように書かないこと。
