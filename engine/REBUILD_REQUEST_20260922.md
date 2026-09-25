# 依頼 — Rust の再ビルドと名指しの検査を 1 回（クロエ → マスター・2026-09-22）

> **2026-09-22 追記: 完了（D-123 追記 1）。**417 通過・1 失敗・3 skip（27 分 23 秒）。失敗 1 件は `test_versions.py` の時間の検査（Windows の時計の刻み）で、検査を直して打ち直しで通過。札 True・指紋一致。以下は依頼時の文面である。

**Rust に触ったので再ビルドが要る。**段階1C-a（D-122）と段階1C-b（D-123）と、相乗りの D-107（`MAX_LIFE` の削除）をまとめて 1 回にした。
全検査ではなく、変えたところに関わる検査だけを回す（全検査は次の 1C-c でまとめて 1 回お願いする予定）。

所要時間の見込み: **30〜60 分**（ビルド 1〜3 分・名指しの検査 20〜50 分。PC では測っていない。作業環境では同じ検査が約 17 分で、うち `test_champion_vc4.py` の 1 件が 4 分半・`test_lit_c.py` の指紋の 1 件が 2 分弱）。
急ぎ度: 中（**これが済むまで PC で全検査を回せない**。対人検証アプリと新アプリは Python だけで動くので、待たずに使ってよい）。
アプリの持ち場の未実施の PC 依頼書: `engine/app/PC_REQUEST_20260922b_APP.md`（トンネル越しの 1 局）がある。**順番はどちらが先でもよい**が、同時にはやらないこと（下の §5 の 1 つ目）。

## なぜ今か

- **1C-a（D-122）**: 相手の手札について「確かに知っている札」をエンジンが覚えるようにした（Python と Rust の両方）。PC の Rust は古いままなので、Python と Rust の毎手一致の検査が落ちる状態にある
- **1C-b（D-123）**: 違うデッキ同士の対局で、AI が**半分の局で相手のデッキ表を取り違える**不具合を直す口を足した（既定では使わないので打ち方は変わらない）。段階2 の教材づくりの入口 `experiments/record_mix.py` を新設
- **D-107**: 回復に上限は無いのに `MAX_LIFE`（上限の名前）が残っていたので消した。「次に Rust を触る便に相乗り」の裁定どおり

**どれも現 champion の打ち方は変えていない**（作業環境で指紋 4 種が一致）。

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine

## 2. 何を打つか（上から 1 行ずつ）

**(1) 先に、書き戻したファイルが載っていることを確かめる**（検索語は ASCII だけ・D-101）。

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    set PYTHONPATH=%CD%
    findstr /c:"fn seat_agents" rust\src\lib.rs
    findstr /c:"known_opp_hand" rust\src\state.rs
    findstr /c:"fn know_forget" rust\src\engine.rs
    findstr /c:"opp_from_seat=True" experiments\record_mix.py
    findstr /c:"825000" experiments\seed_bands.json
    findstr /c:"def test_heterogeneous_opp_decklist_follows_seat" tests\test_record_mix_1cb.py
    findstr /c:"MAX_LIFE =" meicho\state.py

**最後の 1 行だけは何も出ないのが正しい**（消した印）。それ以外の 6 行は 1 行以上出ること。
1 つでも違えば**ここで止めて**、どれが違ったかを教えてほしい（OneDrive の書き戻しの失敗で、載せ直す）。

**(2) 再ビルド**（対人検証アプリ・新アプリのサーバの窓が開いていたら、先に閉じる）。

    cd rust
    maturin build --release --out dist
    pip install --force-reinstall --no-deps dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
    cd ..

**(3) 新しい部品が入ったかと、champion の指紋。**

    python -c "import meicho_rs; print('opp_from_seat' in meicho_rs.features())"
    python scripts\check_champion_fingerprint.py

**(4) 名指しの検査。**結果は画面に出る（ファイルに流さない）ので、終わるまで点（`.`）が増えていく。

    python -m pytest tests\test_record_mix_1cb.py tests\test_known_hand_1ca.py tests\test_rust_engine.py tests\test_rust_agents.py tests\test_engine.py tests\test_official_a6.py tests\test_drl.py tests\test_versions.py tests\test_lit_c.py tests\test_champion_vc4.py -q -rs

## 3. 成功したらどう見えるか

- (2) の 2 行目の最後に `Built wheel for CPython 3.11 to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl`、3 行目の最後に `Successfully installed meicho-rs-0.1.0`
- (3) の 1 行目が `True`。2 行目の最後が **`→ 一致`**（期待 `f4b80b25c35cfa77`）
- (4) の最後の 1 行が `○ passed, ○ skipped in …` で、**`failed` が無い**こと。作業環境では 421 件が集まり、落ちたのは資材の無い 2 件（`drl_sd001_vb3.json`・`results/ladder.json`）だけ——PC には両方あるので通るはず。
  skip は torch 無し・資材の無いものが数件出うる（理由の行 `SKIPPED [..]` を見れば分かる）
- 途中で点が長く止まって見えるところがある（1 件で数分かかる検査が 2 つ）。止まっていない

## 4. 確認のしかた

(3) の 2 行と、(4) の最後の 1 行と、`FAILED` で始まる行があれば全部を貼ってほしい。skip があれば `SKIPPED` の行も。

## 5. 転びやすいところと症状

- **サーバの窓が開いたまま (2) を打つと、`pip install` が「アクセスが拒否されました」で落ちる**（Windows は使用中の `.pyd` を差し替えられない）。窓を閉じて 3 行目だけ打ち直す。アプリの依頼（トンネルの 1 局）と同時にやらないのはこのため
- `set PYTHONPATH=%CD%` を忘れると `ModuleNotFoundError: No module named 'meicho'`。コンソールを開き直したら打ち直す
- (3) の 1 行目が `False`、または (4) で `test_feature_tag_present` が落ちる → 古い部品のまま。(2) の 3 行目の `--force-reinstall` を付けて打ち直す
- `pip install` が「そんなファイルは無い」と言う → ビルドが失敗しているかファイル名が違う。`dir rust\dist` で実際の名前を見て、その名前で打つ
- `test_rust_engine.py` が大量に落ちて `known_opp_hand` の語が出る → 新しい部品が入っていない（上と同じ）
- `python -m pytest` を `tests\...` を付けずに打つと `app\tests` も集まる（TE-7）。上の 1 行をそのまま打つ
