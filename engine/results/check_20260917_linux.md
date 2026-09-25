# 全検査の実行記録（作業環境・Linux・2026-09-17・クロエ）

D-091 追記 1 が「全検査は回していない」として残した穴を、**作業環境（Cowork のサンドボックス）**で埋めた記録である。
**マスターの PC（Windows）での実行の代わりにはならない。**理由は §5 に書く。

## 1. 環境

- Python **3.11.15** / numpy 2.4.4 / pytest 9.1.1 / **torch なし**
- **cargo 1.95.0 / rustc 1.95.0 / maturin 1.15.0** — D-089 が「作業環境に `cargo`/`rustc` が無い」としたのは別の作業環境の話で、
  **この作業環境にはある**。よって Linux 版 wheel を自前でビルドして Python↔Rust の毎手一致を回せた。
- 対象は PC の作業ツリーから取った実ファイル（`main` / HEAD `b767f30adf0ad6015b2c6511625a4bca903b1b38`）。
- 作業環境に**置かなかった**もの: カード画像 123 枚（`cards/*.png`）・`results/models/` の学習済みネット・
  `experiments/gauntlets/`・`experiments/datasets/`・`webapp/static/`・`results/human_games/`・`scripts/dist_templates/`。

## 2. wheel のビルド

    cd engine/rust && maturin build --release -o dist
    → dist/meicho_rs-0.1.0-cp311-cp311-manylinux_2_34_x86_64.whl（26 秒）

- 警告は **1 件だけ**で、PC のビルドログ（`build_stage1b.txt`）と**同一**である（`src/engine.rs:1850` の `unused_mut`）。
- `meicho_rs.features()` = `['d065_bin1', 'd065_reeval_isolated_rng', 'lethal_uniform', 'known_hand', 'world_weight', 'endgame_enum', 'draw_buckets', 'bundle_p', 'bp01_k5']`
  ＝ PC の `check_stage1b.txt` と**同じ集合**。
- `meicho_rs.encoding_info()` = **`(5, 1825, 317)`**。Python 側の `(ENCODING_VERSION, OBS_DIM, ACT_DIM)` と**一致**。

## 3. 結果

    python -m pytest tests -q
    → 714 通過 / 61 失敗 / 46 skip（7 分 28 秒・816 件収集）

### 3.1 失敗 61 件の内訳

**60 件は作業環境に資材を置かなかったことによる失敗**である。

- 34 件 `results/models/*.json`（学習済みネット 12 本）が無い
- 9 件 `experiments/gauntlets/core5.json` 等が無い
- 9 件 `cards/*.png`（カード画像 123 枚）が無い（`test_card_images.py` の 9 件）
- 4 件 `webapp/static/index.html` が無い
- 3 件 `experiments/datasets/*.json` が無い
- 2 件 `scripts/dist_templates/` が無い
- 1 件 `results/human_games/2026-09.jsonl` が無い

**残る 1 件が本物の失敗**である。

- `tests/test_bp01_k3.py::test_rust_matches_python_on_a_bp01_deck[5]`
  → **Python↔Rust の毎手一致が BP01 の仮デッキで落ちる**（詳細は §4）

### 3.2 skip 46 件の内訳（すべて理由つき）

- 25 件 `torch` が無い（作業環境に入れていない）
- 8 件 線形モデル未生成（`experiments/train_linear.py` を回していない）
- 8 件 対人の記録が無い環境
- 2 件 `results/ladder.json` が無い
- 1 件 データセット未生成 ／ 1 件 便 M の記録が無い ／ 1 件 条件を満たす局面が見つからない（`test_lit_c.py:958`）

## 4. 本物の失敗 1 件（B-8）

**症状**。`K_smoke_ANKO` の仮デッキ・シード 5・22 手目で、状態の JSON が 1 欄だけ食い違う。

    Python : "match_params": {}
    Rust   : "match_params": {"count": 2}

ほかの 42 欄・`options`・`remaining` は同一である。踏んだ効果は `BP01-043`「哀切の凶鳥」の
`opp_trash_to_deck_bottom {count: 2}`（相手のトラッシュ 2 枚をデッキの下へ）。

**原因**。

- Python（`meicho/engine.py:1194-1196`）は `opp_trash_to_deck_bottom` について
  `_queue_zone_choice(...)` を **`match_params` を渡さずに**呼ぶ。`_queue_zone_choice` の既定は `{}` で、
  絞り込み関数も `None` になる（`prm` が空なので）。
- Rust（`rust/src/engine.rs:1175-1188`）は `OppConcertoToTrash` / `OppTrashToDeckBottom` /
  `TrashToHand` / `TrashToConcerto` の 4 つを**1 本の分岐**で扱い、つねに `prm0` を `match_params` に入れ、
  `distinct_zone_options` の絞り込みにも `Some(&prm0)` を渡す。

**範囲（実測）**。シード 0〜39 の 40 局を回して突き合わせた。

- `match_params` だけの食い違い: **3 シード（5・12・37）の計 4 ステップ**
- それ以外の欄・`decision_players`・`legal_actions`・`outcome`: **40 シードすべてで一致**

＝**いまは打ち方に影響していない。**`count` は絞り込みの鍵ではないので、Rust が余分に渡しても選択肢は変わらない。

**ただし潜在的な挙動差である。**Rust は絞り込みにも `prm0` を渡しているので、将来
`opp_trash_to_deck_bottom` に `tag` などの絞り込み条件が付いたカードが来ると、
**Rust だけが絞り込んで本物の食い違いになる。**

**正しいのは Python**（作業規約 2: Python が真実源・Rust は写し）。Rust を「この op では `match_params` を渡さない」に直す。

**含意**。D-091 §4 は「champion の打ち方は変わっていない」を (a) Python↔Rust の毎手一致が通っている、
(b) 段階1A が決定列の変化を申告している、の 2 点からの推論とした。
**(a) は BP01 の仮デッキでは成立していない。**ただし SD001/SD02 の毎手一致（`tests/test_rust_engine.py`）は通っており、
champion は SD001 なので**推論そのものは崩れない**。崩れるのは D-083 の「三者一致が名乗れる」で、
**BP01 を含めた三者一致はいま名乗れない。**

## 5. この記録で「言えないこと」

- **Windows の wheel を検証していない。** ここでビルドしたのは Linux（manylinux_2_34）版である。
  マスターが対局に使うのは PC の win_amd64 wheel（655,617 バイト）であって、**そちらは別物である**。
  ソースは同じで、警告も `features()` も `encoding_info()` も一致したので**同じ形だと考えられる**が、測っていない。
- **「失敗 0」とは言えない。**60 件は資材を置かなかったことによる失敗で、資材を置けば通る見込みだが、
  **置いて確かめたわけではない。**とくにカード画像 123 枚とネット 12 本は転送していない。
- **torch を使う 25 件は 1 件も動いていない。**学習側の検査はここでは無検証である。
- 対人の記録・ラダー・データセットを使う検査も動いていない（skip の内訳のとおり）。
- **これは D-091 追記 1 が求めた「PC での全検査」の代わりではない。**PC でしか分からないのは
  (1) Windows wheel での毎手一致、(2) 資材が揃った状態での失敗 0、(3) torch を使う検査の結果である。
