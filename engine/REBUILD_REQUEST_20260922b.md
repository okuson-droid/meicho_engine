# 依頼 — ネットの移行・Rust の再ビルド・PC の組の検査を 1 回（クロエ → マスター・2026-09-22 その 2）

> **2026-09-22 追記: 完了（D-124 追記 1）。**マスターの報告「検査はすべて正常」。以下は依頼時の文面である。

> **2026-09-22 改訂（D-125）**: (4) を「全検査（約 3 時間）」から「PC の組（`--pc`・15〜30 分の見込み）」に替えた。全検査は作業環境でクロエが回し済み（資材の無い 25 件を除いて全部通過）。

**段階1C-c 符号化 v6（D-124）のための依頼である。**AI の入力（観測の符号化）の版を 5 から 6 に上げた。
PC のネット 12 本を新しい版に移し、Rust を作り直し、**PC で回す組の検査**を 1 回回してほしい。

所要時間の見込み: **30〜40 分**（移行 2〜5 分・ビルド 1〜3 分・PC の組の検査 15〜30 分。PC では測っていない。作業環境では同じ組が 1 分だが、作業環境で資材が無くてすぐ落ちる検査が PC では最後まで走るので、PC では長くなる）。
急ぎ度: **高**——**書き戻した時点で PC の AI の相手（champion）が立たなくなっている**（下の「なぜ今か」）。(1)〜(3) は続けて、今日のうちに打ってほしい。(4) は続けてでも、あとででもよい。
アプリの持ち場の未実施の PC 依頼書: `engine/app/PC_REQUEST_20260922b_APP.md`（トンネル越しの 1 局）がある。**この依頼の (1)〜(3) が終わるまでは、そちらを始めないこと**（AI が立たない）。

## なぜ今か

- 符号化 v6 は、AI の入力の末尾に「相手の手札について知っていること」の列を 118 本足した（信念の要約 20 本と、統一した既知の手札 78 本）。**それまでの列は 1 つも動かしていない**
- ネットは「入力の長さが合わないものは読まない」という安全装置を持っている（D-062）。**v6 のコードを PC に書き戻したので、PC の v5 のネットはいま読めない**。対人検証アプリと新アプリの champion もネットを読むので、移行が済むまで AI の相手が立たない
- 移行は、足した列の重みを 0 にするだけである。**AI の打ち方は 1 手も変わらない**（作業環境で champion の指紋 `f4b80b25c35cfa77` の一致を確認済み）

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine

## 2. 何を打つか（上から 1 行ずつ）

**(0) 始める前に**: 対人検証アプリ・新アプリのサーバの窓が開いていたら閉じる。

**(1) 書き戻したファイルが載っていることを確かめる**（検索語は ASCII だけ・D-101）。

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    set PYTHONPATH=%CD%
    findstr /c:"ENCODING_VERSION = 6" meicho\encode.py
    findstr /c:"ENCODING_VERSION: i64 = 6" rust\src\encode.rs
    findstr /c:"fn push_belief" rust\src\encode.rs
    findstr /c:"enc5.bak.json" scripts\migrate_nets_v6.py
    findstr /c:"def test_belief_matches_full_enumeration" tests\test_encoding_v6.py
    findstr /c:"def pytest_addoption" tests\conftest.py
    findstr /c:"pc_tests" tests\test_sets.json

どれも 1 行以上出ること。1 つでも出なければ**ここで止めて**、どれが出なかったかを教えてほしい（OneDrive の書き戻しの失敗で、載せ直す）。

**(2) ネット 12 本を v6 に移す**

    python scripts\migrate_nets_v6.py results\models\*.json

**(3) 再ビルドと、指紋の確認**

    cd rust
    maturin build --release --out dist
    pip install --force-reinstall --no-deps dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
    cd ..
    python -c "import meicho_rs; print('encoding_v6' in meicho_rs.features(), meicho_rs.encoding_info())"
    python scripts\check_champion_fingerprint.py

**(3) まで終われば、アプリの AI はまた使える。**

**(4) PC の組の検査（D-125）。場所は必ず `tests` と指定する。**結果は画面に出る（点 `.` が増えていく）。

    python -m pytest tests --pc -q -rs

`--pc` は「PC で回す組」だけを集める印である。Windows で作った Rust の部品の毎手一致・Windows の時計・移行したネットの検算と、作業環境に資材（ネット `vb3`・ラダーの記録・対人の記録・カード画像など）が無くて回らなかった 50 件を回す。残りの約 750 件は作業環境で回し済み

## 3. 成功したらどう見えるか

- (2): `drl_sd001_s1.json: migrated max_abs=0` のような行が **12 行**（`drl_sd001_*` 10 本・`drl_sd02_s1`・`pi_small64_e10`）。`c1_*.json` の 4 行は `skip（ネットではない）`。**`max_abs` はすべて 0**。
  `results\models` に `<名前>.json.enc5.bak.json`（移行前の原本）が 12 個増える。消さないこと
- (3): ビルドの行の最後に `Built wheel for CPython 3.11 to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl`、インストールの行の最後に `Successfully installed meicho-rs-0.1.0`。
  確認の 1 行目が `True (6, 1923, 317)`。2 行目の最後が **`→ 一致`**（期待 `f4b80b25c35cfa77`）
- (4): 最後の 1 行が `○ passed, ○ skipped, 749 deselected in …` で **`failed` が無い**こと。通過は 270〜290、skip は数件の見込み（数のずれは報告だけでよい）。`deselected`（集めなかった数）が出るのは正常

## 4. 確認のしかた

- (2) の出力のうち `max_abs` が 0 でない行と、`migrated` でも `skip` でもない行があれば、そのまま貼ってほしい（無ければ「12 本 0」でよい）
- (3) の確認の 2 行
- (4) は**最後の 1 行**と、`FAILED` で始まる行があれば全部。`SKIPPED` の行もあれば全部（PC の組の skip は、PC にも資材が無いという意味なので知りたい）

## 5. 転びやすいところと症状

- **(2) を 2 回打っても壊れない**（2 回目は全部 `already v6` と出る）。途中で止まったら、そのまま打ち直してよい
- (2) で `NG ... v5 のネットではない` の行が出たら、そのファイルは想定外の版である。その行を貼ってほしい（他のネットの移行は続けて行われる。最後に「移行できなかったもの ○ 本」と出る）
- (3) で `pip install` が「アクセスが拒否されました」で落ちる → サーバの窓が開いたまま。閉じて `pip install` の行だけ打ち直す
- (3) の確認の 1 行目が `False` や `(5, 1825, 317)` → 古い部品のまま。`pip install` の行を `--force-reinstall` 付きで打ち直す
- (3) の指紋が一致しない → **(2) の移行を飛ばしている**か、途中のネットが古い。ここで止めて、2 行を貼ってほしい
- (4) で `error: unrecognized arguments: --pc` と出たら、`tests\conftest.py` の書き戻しが載っていない。`findstr /c:"def pytest_addoption" tests\conftest.py` が 1 行出るか見て、出なければ教えてほしい
- (4) の途中で点が数分止まって見えるところがある（champion の指紋を取る検査）。止まっていない
- `set PYTHONPATH=%CD%` を忘れると `No module named 'meicho'`。コンソールを開き直したら打ち直す
- `python -m pytest` を `tests` 無しで打つと `app\tests` も集まる（TE-7）
