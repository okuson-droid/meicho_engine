# 依頼 — A-3・B-9・A-5・B-7 の直しを PC に反映し、あわせて未検証の指紋を確かめる（クロエ → マスター）

> **2026-09-18 追記（D-101）**: §2〜§4(c) は**実行済み**で、結果まで出ている。
> 指紋は **B-9 が原因で動き、裁定により貼り替えた**（`099a7f9382843ff2`）。
> **残っているのは §4(d) の全検査だけ**である。§2 の `findstr` と §4(c) の期待値は下で訂正した。

**この 1 通に 2 つ入っている。**
1. 2026-09-18 の直し 4 件（**A-3・B-9 が D-099、A-5・B-7 が D-100**）の再ビルドと確認。
   同じ日のうちに 2 便ぶん入ったので、**再ビルドは 1 回で済む**ように書き直した
   （最初に書いた版は A-3・B-9 だけだった）。
2. **D-098 で貼り替えたまま一度も回していない指紋の検証**（`TASKS.md` の Waiting On の★項目）。
   同じ PC 作業なので 1 回にまとめた。

## なぜ今これが要るのか

**(1) 再ビルド。**Rust のソースを 2 ファイル直した（`rust/src/engine.rs`・`rust/src/state.rs`）。
`.pyd`／wheel はソースと一緒に配られないので、**PC で再ビルドしないと PC 側は直る前の wheel で動き続ける**。
そのあいだ Python↔Rust の毎手一致の検査は落ち続ける。

直したのは 4 件である。

> **★訂正（D-101）**: ここに「どれも SD001/SD02 の対局を 1 手も変えない」と書いていたが**誤り**。
> 測ったのは**素の planner・帯 230000** であって、**champion（`known_hand` つき・帯 471500）では
> B-9 が打ち方を変える**。10 局中 1 局・勝敗は 0/10 という小ささだが、指紋は動く。
> 「基準が不変でも、その基準が変更点を踏んでいないだけかもしれない」（D-097）を踏んだ。

- **A-3**（処理待ちの解決順・公式 700.1.2/.3・rules v0.16）。SD001/SD02 では 1 度も発火しない（BP01 のカードだけ）。
- **B-9**（対抗で置けないときの手札全公開・公式 604.1.1.2 後段・rules v0.16）。
  **★champion の打ち方を変える**（`known_hand` 経由・D-101）。素の planner では動かない。
- **A-5**（Lv.0 はちょうど 1 枚・公式 101.1.1.1・rules v0.17）。**構築の検査が厳しくなっただけ**で、
  現プールには同名の Lv.0 が 2 枚無いので対局は変わらない。
- **B-7**（0 ダメージに削られたら「各ターン最初に受けるダメージ」の旗を消費しない・公式 901.2.1・rules v0.17）。
  効くのは `BP01-002` を含む構築だけである。

**BP01 の仮デッキ `K_smoke_TSUBAKI` では打ち方が変わる**（4 件あわせて random で手順 123/200・勝敗 37/200）。

**符号化は動いていない**（`ENCODING_VERSION` 5 ／ `OBS_DIM` 1,825 ／ `ACT_DIM` 317 のまま）。
既存の選択の種類 `order` を使い回したので、**学習済みネット 12 本は 1 本も触っていない**。

**(2) 指紋の検証。**D-098 で歴代 champion 3 体の指紋と `B75_FINGERPRINT` を貼り替えたが、
**書き替えた 5 ファイルを一度も回していない**（作業規約 5 の意味でその便は閉じていない）。
`PREV_FINGERPRINT` と `B75_FINGERPRINT` は**推定値**で、前回は手前の行で落ちて一度も走っていない。

---

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine

## 2. 何を打つか（1 行ずつ）

**先に、書き戻したソースが PC に載っていることを確かめる。**（OneDrive で「更新日時だけ進んで中身が古い」事故が D-091 で起きている）

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    findstr /c:"def _start_next_pending" meicho\engine.py
    findstr /c:"def _reveal_stuck_turn_player_hand" meicho\engine.py
    findstr /c:"fn start_next_pending" rust\src\engine.rs
    findstr /c:"fn reveal_stuck_turn_player_hand" rust\src\engine.rs
    findstr /c:"pub enum PendingQueue" rust\src\state.rs
    findstr /c:"lv0 = sum(1 for c in charas" meicho\engine.py
    findstr /c:"is_first = not s.first_damage_taken_this_turn" meicho\engine.py
    findstr /c:"let is_first = !s.first_damage_taken_this_turn" rust\src\engine.rs
    findstr /c:"v0.17" rules_draft.md
    dir tests\test_official_a3b9.py
    dir tests\test_official_a5b7.py

11 個とも該当行（最後の 2 つはファイル 1 件ずつ）が表示されること。
1 つでも出なければ**ここで止める**（載っていない）。

> **★`findstr` の検索語は ASCII だけにすること**（D-101）。Windows のコンソールは cp932、
> ソースは UTF-8 なので、**日本語を検索語にすると中身があっても当たらない**。
> 最初の版は `"の Lv.0 はちょうど1枚"` と書いていて、載っているのに空振りした。
> `.md` を検索すると結果が文字化けして見えるが、**マッチ自体は成立している**（表示だけの問題）。

そのうえでビルドする。

    cd rust
    maturin build --release -o dist
    pip install --force-reinstall --no-deps dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl

## 3. 成功したらどう見えるか

- ビルドの最後に `Built wheel for CPython 3.11 to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl` が出る。
- **警告は `unused_mut` 1 件だけ**である（前回と同じ。行番号は前回の 1850 から少しずれる）。増えていたら §5 を読む。
- `dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl` の日時が今の時刻になる。

## 4. 確認のしかた（期待される値つき）

### (a) 今回の直し（4 件）

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    set PYTHONPATH=%CD%
    python -m pytest tests\test_official_a3b9.py tests\test_official_a5b7.py -q

期待: **22 通過・失敗 0**（A-3 が 6 件・B-9 が 6 件・A-5 が 4 件・B-7 が 6 件）。

    python -m pytest tests\test_official_b123.py tests\test_official_a12.py tests\test_official_a4b4.py tests\test_bp01_k3.py -q

期待: **161 通過・失敗 0**（前回と同じ。今回の直しでここは動かない）。

### (b) SD001/SD02 の打ち方が動いていないこと

    python -m pytest tests\test_d065.py::test_defaults_unchanged_d065 tests\test_rust_engine.py tests\test_rust_agents.py -q

期待: **失敗 0**（`BASELINE_DIGESTS_230000` が一致・Python↔Rust の毎手一致）。

### (c) ★指紋 — 今回いちばん大事な確認

    python scripts\check_champion_fingerprint.py

期待: **`planner_vc4cps_kheb_b75` が `099a7f9382843ff2` で一致**（D-101 で貼り替えた）。

> **★訂正（D-101）**: この道具は**現 champion 1 体しか見ない**。「4 体とも一致」は誤りだった。
> 歴代 3 体（`planner_vc4cps_kheb` `f3d1b52aed0abdad` / `planner_vc4cps` `2d884df547ac6990` /
> `planner_vb3cps` `c84616b0d707a705`）を確かめるのは下の pytest の節点である。
> **この 3 体は動いていない**（作業環境で確認済み）。
> また、当初ここに書いた期待値 `9d4ff39d024e4394` は **2 世代古い値**だった。

続けて、D-098 で貼り替えて一度も回していない 5 ファイルぶんを**節点を名指しで**回す
（全体を回すと 2 時間かかる。名指しなら前回 11 節点で 29 分だった）。

    python -m pytest tests\test_champion_vc4.py -q
    python -m pytest "tests\test_lit_a.py::test_defaults_unchanged_lit_a" "tests\test_lit_a2.py::test_a2_defaults_unchanged" "tests\test_lit_a2.py::test_a2_rust_p_one_has_the_champion_fingerprint" "tests\test_lit_c.py::test_kheb_champion_fingerprint" "tests\test_lit_d.py::test_champion_fingerprint_unchanged_lit_d" -q

期待: **失敗 0**。`test_lit_a2.py` の `B75_FINGERPRINT` は **`099a7f9382843ff2`**（D-101 で貼り替え）。

> **2026-09-18: この節点はすべて作業環境で実行済み**（ネット 4 本を持ち込んで再現した）。
> 落ちたのは `test_a2_defaults_unchanged` の B75 の行だけで、貼り替えで通過を確認した。
> **D-098 の貼り替えは 4 つとも正しかった**＝`TASKS.md` の★項目は閉じてよい。

**★どれかが不一致だったら、そこで止めて知らせてほしい。**勝手に貼り替えないでほしい。
（2026-09-18 は実際にこれが起き、止めてもらったおかげで B-9 単独に切り分けられた・D-101。）

### (d) 最後に全検査

    python -m pytest -q

**通過・失敗・skip の 3 つの数と、失敗・skip の理由**を教えてほしい。
前回（D-098・2026-09-17）は **922 通過 / 13 失敗 / 27 skip（2 時間 3 分）**だった。
今回は新設の検査が 22 件増えている。
13 件は全部仕分けて直したので、**今回は減っているはずである**。
残っている既知の未決は次の 2 件だけである。

- `tests\test_bp01_k4.py::test_every_bp01_card_renders_as_japanese_without_an_image`
  （画像が揃った PC でだけ落ちる。**マスターへの質問が未回答**——下の §6）
- `tests\test_lit_c.py::test_worlds_module_matches_diag_pimc`
  （記録が旧エンジン製。作り直し待ち）

**`test_lit_a2.py::test_a2_defaults_unchanged` は貼り替え後は通る。**
作業環境（Linux・資材なし）では **859 通過 / 74 失敗 / 46 skip** で、
74 失敗は**すべて**置かなかった資材（カード画像・ネット・ガントレット・`results/`・`scripts/`）による。
**直す前と直した後で失敗の集合は完全に同一**だった（`diff` で 1 行も違わない）。

## 5. 転びやすいところと、その症状

- **`findstr` が何も表示しない** → 書き戻しが PC に載っていない。ビルドしても直らない。わたしに知らせてほしい。
- **`maturin` が見つからない** → `pip install maturin` を先に打つ。
- **ビルドは通るのに検査が直らない** → `pip install --force-reinstall` を打ち忘れている可能性がある。
  ビルドは wheel を作るだけで、入れ替えはしない。
- **`python -m pytest` で `meicho` が見つからない** → `set PYTHONPATH=%CD%` を `engine` で打ち直す。
  コンソールを開き直すと消える。
- **`test_official_a3b9.py` / `test_official_a5b7.py` が見つからない** → 新設ファイルの書き戻しが載っていない。
- **`check_champion_fingerprint.py` が不一致** → **そこで止めてほしい**（§4(c)）。
- **警告が 1 件より増えた** → ソースの取り違えの可能性がある。警告の全文を見せてほしい。
- **`python scripts\xxx.py` で `meicho` が見つからない** → `engine` で `set PYTHONPATH=%CD%` を先に 1 回。

## 6. あわせて聞きたいこと（PC が要らない・返事だけでよい）

`tests\test_bp01_k4.py::test_every_bp01_card_renders_as_japanese_without_an_image` の末尾が
`assert shown > 0`（**画像の無いカードが 1 枚も無いと落ちる**）で、画像の揃った PC でだけ落ちる。
この検査は「**マスター裁定 2026-09-10 により BP01 の画像は取得しない**」を前提に書かれているが、
2026-09-13 に手動スクショへ切り替えた（D-084）ので**実装カード 123 番号すべてに画像がある**。

**裁定が変わったという理解でよいか？**よければ検査のほうを書き替える（D-084 を前提に、
「画像があること」を確かめる形にする）。意図せず入ったのなら別の直しになる。
