# 依頼 — A-6 の直しを PC に反映する（クロエ → マスター）

> **2026-09-19 追記（D-105）**: **§2〜§4 は実行済み。残っているのは §5 の全検査だけである。**
> 結果: 公式 3 ファイル **29 通過** ／ 指紋 **`f4b80b25c35cfa77` 一致** ／
> 歴代 3 体と H・G・P の **14 節点すべて通過**（56 分 35 秒）。**A-6 の反映は成功している。**
>
> §4 の 2 本目で 1 件落ちた。
> `tests/test_bp01.py::test_unlisted_list_is_empty_because_the_three_were_published`
> （`ModuleNotFoundError: No module named 'reconcile_cards'`）。
> **A-6 とは無関係の、前からあった検査の欠陥である**——`scripts/` を `sys.path` に入れる行が
> `test_bp01.py` の 4 か所のうち 1 か所で抜けていて、全検査では `test_cards_folder.py` が
> 先に入れてくれるので通り、**そのファイルを名指しで回すと落ちる**形になっていた。
> **わたしが今回の依頼書で §4 に `test_bp01.py` を足したので表に出た。**
> **D-105 で直した**（経路を `tests/conftest.py` 1 か所にまとめ、散っていた 4 か所を消した）。
> **再ビルドは要らない。検査だけの直しである。**
>
> **→ いま打つのは §5 の `python -m pytest -q` だけでよい。**

**これで公式ルール再照合（D-092）の差異 12 件がすべて片付く。**

## なぜ今これが要るのか

Rust のソースを 1 ファイル直した（`rust/src/engine.rs` の `heal`）。
`.pyd`／wheel はソースと一緒に配られないので、**PC で再ビルドしないと PC 側は直る前の wheel で動き続ける**。

**A-6**（回復にライフの上限は無い・公式 101.6・rules **v0.18**・D-104）。
**D-011（2026-08-21 のマスター裁定「上限 20 でクリップ」）を覆した。**

**★これは SD001 の対局を大きく変える。**`SD01-023`「奏鳴」(+5) が序盤から本当に +5 回復するようになった。

    SD001/random     手順  4/200  勝敗  1/200
    SD001/heuristic  手順  8/200  勝敗  1/200
    planner/SD001    手順 80/200  勝敗 37/200
    champion の指紋の帯 471500..471509  手順 4/10  勝敗 4/10
    SD02 と BP01 の仮デッキは 0/200（どちらも回復カードを持たない）

**基準 8 種は 2026-09-19 のマスター裁定で貼り替え済み**（D-104 §4。旧値は札として残してある）。
**符号化は動いていない**（`ENCODING_VERSION` 5 ／ `OBS_DIM` 1,825 ／ `ACT_DIM` 317）。
**学習済みネットは 1 本も触っていない。**

あわせて **D-103**（BP01 の画像の検査を環境に依存しない形に書き替え）も入っている。**再ビルドは要らない直しである。**

---

## 1. どこで

    C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine

## 2. 何を打つか（1 行ずつ）

**先に、書き戻したソースが PC に載っていることを確かめる。**
**★`findstr` の検索語は ASCII だけにすること**（D-101。コンソールは cp932、ソースは UTF-8）。

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    findstr /c:"p.life = p.life + amount if amount > 0 else p.life" meicho\engine.py
    findstr /c:"if amount > 0 { before + amount } else { before }" rust\src\engine.rs
    findstr /c:"f4b80b25c35cfa77" scripts\check_champion_fingerprint.py
    findstr /c:"6668190221415650951" meicho\drl_data.py
    findstr /c:"77502dad26c172ef" tests\test_bp01.py
    findstr /c:"6427a7b28f7a10fe" tests\test_lit_a.py
    findstr /c:"v0.18" rules_draft.md
    findstr /c:"monkeypatch" tests\test_bp01_k4.py
    dir tests\test_official_a6.py

9 個とも該当行（最後はファイル 1 件）が表示されること。1 つでも出なければ**ここで止める**。

そのうえでビルドする。

    cd rust
    maturin build --release -o dist
    pip install --force-reinstall --no-deps dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl

## 3. 成功したらどう見えるか

- `Built wheel for CPython 3.11 to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl` が出る。
- **警告は `unused_mut` 1 件だけ**である。増えていたら §5 を読む。

## 4. 確認のしかた（期待される値つき）

    cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
    set PYTHONPATH=%CD%
    python -m pytest tests\test_official_a6.py tests\test_official_a3b9.py tests\test_official_a5b7.py -q

期待: **29 通過・失敗 0**（A-6 が 7 件・A-3 が 6 件・B-9 が 6 件・A-5 が 4 件・B-7 が 6 件）。

    python -m pytest tests\test_bp01.py tests\test_d065.py::test_defaults_unchanged_d065 tests\test_rust_engine.py tests\test_rust_agents.py -q

期待: **失敗 0**。`FROZEN_DIGESTS`（貼り替え後）・`BASELINE_DIGESTS_230000`（貼り替え後）・
Python↔Rust の毎手一致。

    python scripts\check_champion_fingerprint.py

期待: `planner_vc4cps_kheb_b75` が **`f4b80b25c35cfa77`** で一致。

    python -m pytest tests\test_champion_vc4.py "tests\test_lit_a.py::test_defaults_unchanged_lit_a" "tests\test_lit_a2.py::test_a2_defaults_unchanged" "tests\test_lit_c.py::test_kheb_champion_fingerprint" "tests\test_lit_d.py::test_champion_fingerprint_unchanged_lit_d" -q

期待: **失敗 0**（歴代 3 体と H・G・P の指紋も貼り替え済み）。
**作業環境ではこの 7 節点すべて通過を確認してある**（8 分 51 秒）。

**★不一致が出たらそこで止めて知らせてほしい。**貼り替えは作業環境の実測に基づくので、
PC で違う値が出るなら**環境の差**という別の問題である。

## 5. 最後に全検査

    python -m pytest -q

前回（D-102・2026-09-18）は **955 通過 / 2 失敗 / 27 skip（1 時間 53 分）**だった。
今回は新設 **8 件**が増える（A-6 の 7 件＋D-105 の 1 件）。
**落ちていた 2 件のうち `test_bp01_k4` の画像の件は D-103 で直した**ので、
**残る失敗は `tests\test_lit_c.py::test_worlds_module_matches_diag_pimc` の 1 件だけのはず**である
（記録が旧エンジン製・作り直し待ち）。

**先に D-105 の直しが載っていることを確かめてほしい**（ASCII の検索語で）。

    findstr /c:"os.path.join(_ROOT, \"scripts\")" tests\conftest.py
    findstr /c:"test_scripts_is_importable_without_another_test_module_having_run" tests\test_bp01.py

2 つとも出ること。そのうえで念のため、落ちた検査を**単独で**回して直っていることを見る。

    python -m pytest tests\test_bp01.py -q

期待: **失敗 0**（前回はここで 1 件落ちた）。

## 6. 転びやすいところ

- **`findstr` が何も表示しない** → 書き戻しが PC に載っていない。ビルドしても直らない。知らせてほしい。
- **`maturin` が見つからない** → `pip install maturin` を先に。
- **ビルドは通るのに検査が直らない** → `pip install --force-reinstall` の打ち忘れ。
- **`meicho` が見つからない** → `engine` で `set PYTHONPATH=%CD%` を打ち直す。
- **指紋が不一致** → そこで止めてほしい（§4）。

## 7. 次に決めてほしいこと（PC は要らない）

**A-6 で champion が弱くなっていないかを測るか。**

`SD01-023`「奏鳴」はコスト 3 で +5 回復。上限があったころは序盤ほぼ死に効果だったものが、
いま本物の +5 になった。**champion のネットは上限があった世界で学習している**ので、
**奏鳴の価値を過小評価している可能性がある**。

D-097 §5 の「次の champion 交代の判定は新エンジンで測り直してから行う」はもともと効いているが、
**A-6 に関しては測り直しの優先度が上がる**というのがクロエの見立てである。
測るなら「新エンジンでの champion 対 一つ前」を帯を取って回す形になる（`TASKS.md` に項目を立ててある）。
