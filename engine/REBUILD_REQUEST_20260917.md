# 依頼 — 2026-09-17 の Rust の直し 2 件を PC に反映する（クロエ → マスター）

**この 1 通で B-8 と B-1/B-2/B-3 の両方をまとめてある。**
先に書いた `engine/B8_REBUILD_REQUEST_20260917.md` は**これに差し替わった**（同日に 2 件目の直しが入ったため。再ビルドは 1 回で済む）。

## なぜ今これが要るのか

Rust のソースを 3 ファイル直した（`rust/src/engine.rs`・`rust/src/cards.rs`、および Python 側の `meicho/engine.py`）。
`.pyd`／wheel はソースと一緒に配られないので、**PC で再ビルドしないと PC 側は直る前の wheel で動き続ける**。

直したのは 4 件である。

1. **B-8**（Python↔Rust の写し間違い 2 箇所）。**打ち方は変わらない。**
2. **B-1/B-2/B-3**（公式 603.1.2.2.1/.2 との食い違い）。**BP01 のキャラを使う対局の打ち方は変わる。**
   `rules_draft.md` を **v0.13** に上げてから反映した（作業規約 1）。SD001/SD02 は 1 手も変わらない。
3. **A-1/A-2**（公式 701 のルールチェック）。**★SD001/SD02 の対局も変わる。**`rules_draft.md` は **v0.14**。
   リフレッシュの時点が早まって山札の並びが変わるため、ミラー 200 局で手順が 42%・55%、勝敗が 20%・19% 動いた。
   **基準は作業環境で貼り替え済み**（fingerprint H・G と `FROZEN_DIGESTS` 8 件・D-095 §4）。
   **`BASELINE_DIGESTS_230000` と fingerprint P は不変**だったので、**champion の指紋も不変の見込みである**——
   ただし作業環境にネットが無くて測れていない。**§4 の `check_champion_fingerprint.py` が今回いちばん大事な確認である。**

---

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine\rust

## 2. 何を打つか（1 行ずつ）

**先に、書き戻したソースが PC に載っていることを確かめる。**（OneDrive で「更新日時だけ進んで中身が古い」事故が D-091 で起きている）

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    findstr /c:"Op::TrashToHand | Op::TrashToConcerto => prm0," rust\src\engine.rs
    findstr /c:"ops[0].1.paid = Some(true);" rust\src\engine.rs
    findstr /c:"fn queue_levelup_triggers" rust\src\engine.rs
    findstr /c:"fn rule_check" rust\src\engine.rs
    findstr /c:"pub paid: Option<bool>," rust\src\cards.rs
    findstr /c:"def _queue_levelup_triggers" meicho\engine.py
    findstr /c:"def _rule_check" meicho\engine.py
    findstr /c:"def _keep_triggering" meicho\engine.py
    findstr /c:"fn keep_triggering" rust\src\engine.rs
    findstr /c:"v0.15" rules_draft.md

10 個とも該当行が表示されること。1 つでも出なければ**ここで止める**（載っていない）。

4 件目は **A-4/B-4**（誘発条件を判定する時点・公式 800.5.3／800.4／FAQ 47・48）で、`rules_draft.md` は **v0.15**。
**SD001/SD02 の対局は 1 手も変わらない**ので、この 4 件目では基準は動いていない。

そのうえでビルドする。

    cd rust
    maturin build --release -o dist
    pip install --force-reinstall dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl

## 3. 成功したらどう見えるか

- ビルドの最後に `Built wheel for CPython 3.11 to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl` が出る。
- 警告は **`src/engine.rs:1850` の `unused_mut` 1 件だけ**である（前回と同じ。増えていたら §5 を読む）。
- `dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl` の日時が今の時刻になる。

## 4. 確認のしかた（期待される値つき）

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    set PYTHONPATH=%CD%
    python -m pytest tests\test_official_b123.py tests\test_official_a12.py tests\test_official_a4b4.py tests\test_bp01_k3.py -q

期待: **161 通過・失敗 0**（B-1/B-2/B-3 の 13 件＋A-1/A-2 の 9 件＋A-4/B-4 の 4 件＋K-3 の 135 件）。

続けて、**SD001/SD02 の打ち方が動いていない**ことの確認。ここが今回いちばん大事である。

    python -m pytest tests\test_d065.py::test_defaults_unchanged_d065 tests\test_rust_engine.py -q
    python scripts\check_champion_fingerprint.py

期待: 前者は **失敗 0**（digest の基準 `BASELINE_DIGESTS_230000` が一致・Python↔Rust の毎手一致）。
後者は `planner_vc4cps_kheb_b75` / 期待 `9d4ff39d024e4394` / 実測 `9d4ff39d024e4394` / **→ 一致**。

**★後者が不一致だったら、そこで止めて知らせてほしい。**A-1/A-2 で SD001 の対局は変わったが、
planner の digest と fingerprint P が不変だったので champion の指紋も不変と見込んでいる。
**作業環境ではネットが無くて測れなかった唯一の確認がこれである。**不一致なら見込みが外れたということで、
貼り替えるかどうかから考え直す必要がある（勝手に貼り替えないでほしい）。

最後に全検査。**これは D-091 追記 1 が未取得のまま残した数字でもある。**

    python -m pytest -q

**通過・失敗・skip の 3 つの数と、失敗・skip の理由**を教えてほしい。
作業環境（Linux・資材なし）では **853 通過 / 60 失敗 / 46 skip** で、60 失敗はすべて
作業環境に置かなかった資材（カード画像・ネット・ガントレット等）によるものだった。
**PC には資材が揃っているので、失敗はもっと少ないはずである。**

## 5. 転びやすいところと、その症状

- **`findstr` が何も表示しない** → 書き戻しが PC に載っていない。ビルドしても直らない。わたしに知らせてほしい。
- **`maturin` が見つからない** → `pip install maturin` を先に打つ。
- **ビルドは通るのに検査が直らない** → `pip install --force-reinstall` を打ち忘れている可能性がある。
  ビルドは wheel を作るだけで、入れ替えはしない。
- **`python -m pytest` で `meicho` が見つからない** → `set PYTHONPATH=%CD%` を `engine` で打ち直す。
  コンソールを開き直すと消える。
- **`test_official_b123.py` が見つからない** → 新設ファイルの書き戻しが載っていない。
- **`check_champion_fingerprint.py` が不一致になった** → **そこで止めてほしい。**
  今回の直しは SD001 の打ち方を変えない想定なので、不一致が出たら想定が崩れている。
  測り直しではなく原因の特定が要る。
- **警告が 1 件より増えた** → ソースの取り違えが起きている可能性がある。警告の全文を見せてほしい。
