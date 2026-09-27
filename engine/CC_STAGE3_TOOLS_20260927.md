# 段階3 反復 1 の道具（D-139）——クラウドの Claude Code の便の報告（2026-09-27）

設計書 `GENERALIST_STAGE3_DESIGN.md` §3.1・§3.3・§3.7・§9 の道具を作った。裁定は D-138（7 件すべて推し）。
種類はつまみの追加（meicho-engine-impl (iii)）で、**既定の打ち方・記録は変えない**。エンジン本体・Rust・符号化・champion には触れていない。
ブランチ `claude/charming-mendel-yzlmua`（`main` の `89a79fd` から）。コードに触るので `main` への取り込みは PC の Claude Code かマスターが行う（D-137 §2 の 4）。

## 1. 変えたもの

- `experiments/record_mix.py`
  - 教師 `netfree_v`: `NETFREE` に `value_net` を足しただけの教師。`value_net` は engine/ からの相対パスか絶対パス。`value_net_sha16`（sha256 の先頭 16 桁）を書けば、回す前にファイルと照合して違えば落とす。組み合わせ表の検査（`check_schedule`）の段階で確かめるので、1 局も回さずに落ちる
  - manifest に `nonargmax`（「argmax 以外を選んだ決定の割合」・D-064 §6.2 の τ の下見の尺度）をブロックごとと全体で書く。合法手が 2 つ以上の決定が分母。**τ = 0 でも 0 にはならない**——終盤の総当たりの投票（`rust/src/agents.rs` の `vote_pick`・段 C-3）が勝つと平均点の最大でない手を指すため。SD001 ミラー 2 局で τ = 0 は 9／241（3.7%）、τ = 5 は 97／224（43%）だった
  - 葉の V の指紋は、既存の `net_fingerprints` がブロックの `nets` に書く（`value_net` の欄を読むので、`netfree_v` でそのまま入る）
- `experiments/make_s2_schedule.py`
  - `--teacher netfree|netfree_v`（既定 netfree）・`--value-net <パス>`・`--tau <τ>`。`netfree_v` は `--value-net` が要り、パスと指紋を表の教師に書く。既定の引数で作る表は D-131 のものとバイト単位で同じ
  - `--merge` は、教師（表の教師の定義と、ブロックが実際に読んだネットの指紋）が部分ごとに違えば落とす
- `experiments/eval_s2_repr.py`
  - 同じ `--out` に大きい `--n` で打ち直すと、各ブロックの足りない局（seed0＋既存の局数から）だけを回して後ろに足す（足し継ぎ）。局数を減らす打ち直しは落とす
  - `--import 元.json:候補名`: 別ファイルで回した同じ候補の結果を取り込む。シード・デッキ・ネットの指紋のどれかが違う、取り込み元の局数が取り込み先より多い、候補が `--arm` に無い、のどれでも落とす。取り込んだ元は `imported` に残す。**用途: V_0 の 150 局（D-135・`s3_ens_vs_single_v1.json` の `v_ens3`）を 300 局の選択の課題に取り込み、後半の 150 局だけを回す**
- 検査 `tests/test_stage3_tools.py`（19 件・T-1〜T-7）

## 2. 変わらないことを確かめた方法

- **T-5: D-129 の下見（`s2_pilot`・rules v0.18 で記録）を打ち直し、TE-13 に関わらない 15 ブロック（SK 系のデッキが絡む 4 ブロックを除く）の決定数がブロックごと・席ごとに当時の manifest と一致した。**直す前の道具でも直したあとの道具でも一致した（既定の教師は 1 ビットも変わっていない）
- T-1: 既定の教師の spec が従来の `PLANNER(pool, **NETFREE)` と同じ
- T-6: 既定の引数で作り直した組み合わせ表が D-131 の `s2_v1_train_schedule.json`・`s2_v1_val_schedule.json` とバイト単位で同じ
- T-7: 2 局で回してから 4 局に足し継いだ結果が、最初から 4 局で回した結果と同じ（同じファイルでも、別ファイルからの取り込みでも）
- champion の指紋 `f4b80b25c35cfa77` 一致（`check_champion_fingerprint.py`）
- 検査は先に書き、直す前に回して 15 件が落ち（新しい口が無い）、既定を守る 4 件（T-1・T-5・T-6 の 2 件）が通ることを見てから直した。途中で見つけたバグ（全体の `nonargmax` の集計がジェネレータを 2 回回して `off` が 0 になる）は、直したあとに一度戻して、強めた検査が落ちることを確かめた

## 3. 全検査（`--run-slow`・D-125）

- この機械（`cc-cloud-4`）に CPU 版の torch 2.14.0 を入れて回した（学習側の検査を skip にしないため）
- `python -m pytest tests -q -rfs --run-slow`: **1,327 通過・9 失敗・7 skip・70 分 24 秒**
- 失敗 9 件は 1 件ずつ理由を読んだ:
  - 8 件は `cards/` が git に無いため（公式素材の除外・D-136）。`test_bp01.py` の 4 件（`cards/BP01_UNLISTED.json`・`cards_structured.csv`・`BP01_NO_IMAGE.json` が無い）と `test_card_images.py` の 4 件（画像が無い）。CI の一覧 `engine/ci/missing_assets_allowlist.txt` と同じ顔ぶれ
  - 1 件は前からある `test_d065.py::test_distil_makes_the_student_agree_with_the_teacher`（TASKS.md に控え済み・偽の記録では学習前から一致率 1.000）
- skip 7 件: `cards/cards_structured.csv` が無い 5 件・段階2 の記録（`.bin`）が無い 1 件・移行したネットが無い 1 件。どれも資材の無さ
- **この便の変更による失敗は無い**
- 検査の組（`tests/test_sets.json`）は作り直していない。足した 19 件はどれも 20 秒未満（最長 15.5 秒）で `slow` に入らず、どれも通るので `pc_tests` にも入らない。クラウドの結果から組を作り直すと、資材の違い（`cards/` が無い・torch の有無）で作業環境の組とずれるので、作り直しは作業環境か PC の結果で行う

## 4. 1 セッションの区切りの案（推しを先に・裁定が要る）

見積もりは設計書 §8 の作業環境の値を段 5 の実測（約 2 倍速）で割ったもので、**未実測**。反復 1 は束ねた V（1 局 約 1.5 秒と見込む）を葉にする。

- **推し: 1 反復を 6 セッションに分ける。**セッションの中は 10 分以内の塊で、塊ごとに push する（D-137）
  1. τ の下見（帯の先頭 200 局 × τ 3〜4 通り・1 通り約 9 分で 1 塊）と検証の記録 1,000 局（`--parts 5`）。約 1.5 時間
  2. 〜4. 学習の記録 10,000 局を `--parts 50`（1 部分 約 200 局・約 9 分）に分け、1 セッションで約 17 部分（約 2.5 時間）
  5. V を乱数 3 本で学び直して束ねる。約 1〜1.5 時間
  6. 選択の評価: V_1 の 4,800 局（約 17 塊）と V_0 の後半 2,400 局（`--import results/drl/s3_ens_vs_single_v1.json:v_ens3` で前半を取り込む・約 8 塊）。約 3 時間
- **学習は 10 分の塊に切れない**: `drl_train.py` に途中から再開する口が無く、1 本 6 エポックで 10 分を超えると見込む（作業環境で 1 エポック約 210 秒）。推し: 学習だけは例外として裏で回し、数分ごとに進み具合を見て、1 本終わるごとにネットを push する（学習の再開の口を作るのは 1 便ぶんの工事なので、今回はしない）
- ほか: セッションの数を減らして 1 セッションを長くする（容器の回収で失う塊が増える）

## 5. 使い方（反復 1 の記録の例・帯は未登録）

    python experiments/ensemble_net.py --out results/models/s2v_id_ens3.json \
        results/models/s2v_id_s0.json results/models/s2v_id_s1.json results/models/s2v_id_s2.json
    python experiments/make_s2_schedule.py --n-total 10000 --seed0 <帯の先頭> --band-end <帯の終わり> \
        --name s3_it1_train --teacher netfree_v --value-net results/models/s2v_id_ens3.json --tau <下見で決めた τ> \
        --parts 50 --out results/drl/s3_it1_train_schedule.json
    python experiments/record_mix.py --schedule results/drl/s3_it1_train_schedule.p0of50.json \
        --out <記録の置き場>/s3_it1_train.p0 --workers 4

- 束ねた V は git に入っていない（D-136）ので、セッションの初めに作り直し、sha 先頭 16 桁が `2d4504e2125bc244` であることを見る（2026-09-27 に一致を確認済み）
- 帯は回す前に `seed_bands.json` に登録する（設計書 §3.4 の案: 反復ごとに train 12,000 幅＋検証 2,000 幅＋τ 下見 1,000 幅）

## 6. マスターの PC で要る作業

- なし（Python の道具だけ。Rust・wheel は変えていない）。PC の検査は取り込んだあとに `--pc` の組で足りる

## 7. 未定義のまま残ったこと

- τ の下見の尺度は τ = 0 でも投票のぶんだけ 0 にならない（§1）。D-064 の「10〜30%」を τ = 0 の値を引いてから当てるか、そのまま当てるかは決めていない。**推し: そのまま当てる**（記録に入る「教師の最善でない手」の割合そのものが D-064 の狙いなので、由来を問わない）。τ = 0 の値は manifest に並べて残す
