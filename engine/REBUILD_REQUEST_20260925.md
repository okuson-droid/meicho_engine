# 依頼 — TE-13 の直しのための Rust の再ビルドと確認（クロエ → マスター・2026-09-25）

**TE-13（D-134・rules v0.19）のための依頼である。**【切り替え】のスキルが、入れ替えに関わっていないキャラでも誘発していた不具合を、Python と Rust の両方で直した。
PC の Rust の部品（wheel）を作り直し、指紋と、足した検査を回してほしい。

所要時間の見込み: **20〜40 分**（ビルド 1〜3 分・指紋の確認 5〜10 分・PC の組の検査 15〜30 分。PC では測っていない）。
急ぎ度: **中**——段階3 の記録（作業環境か Kaggle で回す）には効かないが、**再ビルドが済むまで PC の Rust は直す前の挙動で動く**（下の「なぜ今か」）。(1)〜(3) は続けて打ってほしい。(4) は続けてでも、あとででもよい。
アプリの持ち場の未実施の PC 依頼書: **無い**（`engine/app/PC_REQUEST_*_APP.md` の 3 通はすべて実施済み・`TASKS_APP.md` で確認）。

## なぜ今か

- 公式総合ルール 913.9.1 は「【切り替え】は、このスキルを持つキャラカードが**切り替えられた時**に誘発する」と定める。エンジンはその席のキャラ全員の【切り替え】を拾っていた。現行カードでは `BP01-008` ショアキーパー Lv1 だけが該当する（マスターが知人との対戦で見つけた不具合）
- Rust は Python の写しなので、Rust も同じ直しを入れた。**PC の wheel は直す前のまま**なので、Rust で対局する道具（対人検証アプリの AI・新アプリの CPU・`rs.series` 系の測定）は再ビルドまで古い挙動で動く
- **SD001/SD02 の対局は 1 手も変わらない**（両デッキに【切り替え】を持つカードが無い）。**champion の指紋 `f4b80b25c35cfa77` は作業環境で一致を確認済み**＝指紋の貼り替えは無い。PC でも一致することを (3) で確かめる

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine

## 2. 何を打つか（上から 1 行ずつ）

**(0) 始める前に**: 対人検証アプリ・新アプリのサーバの窓が開いていたら閉じる（開いていると (2) の `pip install` が「アクセスが拒否されました」で落ちる）。

**(1) 書き戻したファイルが載っていることを確かめる**（検索語は ASCII だけ・D-101）。

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    set PYTHONPATH=%CD%
    findstr /c:"def _queue_switch_triggers" meicho\engine.py
    findstr /c:"fn queue_switch_triggers" rust\src\engine.rs
    findstr /c:"te13_switched_scope" rust\src\lib.rs
    findstr /c:"v0.19" meicho\version.py
    findstr /c:"def test_action_switch_does_not_fire_the_uninvolved_back" tests\test_te13_switched_scope.py
    findstr /c:"test_te13_switched_scope.py" tests\test_sets.json

どれも 1 行以上出ること。1 つでも出なければ**ここで止めて**、どれが出なかったかを教えてほしい（OneDrive の書き戻しの失敗で、載せ直す）。

**(2) 再ビルド**

    cd rust
    maturin build --release --out dist
    pip install --force-reinstall --no-deps dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
    cd ..
    python -c "import meicho_rs; print('te13_switched_scope' in meicho_rs.features())"

**(3) 指紋と、足した検査**

    python scripts\check_champion_fingerprint.py
    python -m pytest tests\test_te13_switched_scope.py tests\test_versions.py -q -rs

**(3) まで終われば、PC の Rust も直った挙動で動く。**

**(4) PC の組の検査（D-125）。場所は必ず `tests` と指定する。**結果は画面に出る（点 `.` が増えていく）。

    python -m pytest tests --pc -q -rs

`--pc` は「PC で回す組」だけを集める印である。今回 `tests\test_te13_switched_scope.py` をこの組に足した（Windows で作った Rust と Python の毎手一致をショアキーパーのデッキで回すため）。

## 3. 成功したらどう見えるか

- (2): ビルドの行の最後に `Built wheel for CPython 3.11 to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl`、インストールの行の最後に `Successfully installed meicho-rs-0.1.0`。確認の 1 行が **`True`**
- (3) の 1 行目: 最後が **`→ 一致`**（期待 `f4b80b25c35cfa77`）。数分かかる
- (3) の 2 行目: 最後の 1 行が **`○ passed in …`** で `failed` も `skipped` も無いこと（作業環境では `test_te13_switched_scope.py` 41 件＋`test_versions.py` がすべて通った）
- (4): 最後の 1 行が `○ passed, ○ skipped, ○ deselected in …` で **`failed` が無い**こと。通過は前回（2026-09-22）より 41 件前後増える見込み（数のずれは報告だけでよい）

## 4. 確認のしかた

- (2) の確認の 1 行（`True` か `False` か）
- (3) の指紋の最後の行と、pytest の最後の 1 行。`FAILED` や `SKIPPED` で始まる行があれば全部
- (4) は**最後の 1 行**と、`FAILED` で始まる行があれば全部。`SKIPPED` の行もあれば全部

## 5. 転びやすいところと症状

- (2) の確認が `False` → 古い部品のまま。`pip install` の行を打ち直す（`--force-reinstall` を付けたまま）
- (3) の pytest で `test_rust_matches_python_with_shorekeeper` が **skip** になる → 部品が古い（`te13_switched_scope` の札が無いと飛ばす作り）。(2) をやり直す
- (3) の pytest で `test_rust_matches_python_with_shorekeeper` が **失敗**する → Rust の書き戻しが載っていないか、ビルドが古い。(1) の 2 行目・3 行目をもう一度見て、失敗の行を貼ってほしい
- (3) の指紋が一致しない → **ここで止めて**、指紋の 2 行を貼ってほしい（作業環境では一致しているので、PC 側の取り違えを疑う）
- (4) の途中で点が数分止まって見えるところがある（champion の指紋を取る検査）。止まっていない
- `set PYTHONPATH=%CD%` を忘れると `No module named 'meicho'`。コンソールを開き直したら打ち直す
- `python -m pytest` を `tests` 無しで打つと `app\tests` も集まる（TE-7）
