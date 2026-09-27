# クラウドセッションでの測定の試行（段 5）——D-132 追記 4 の再現（2026-09-27）

`engine/DEVFLOW_PLAN_20260925.md` §6 の段 5。新しい測定ではなく、既に数字のある評価を同じシードで回し、クラウドセッションの機械が PC・作業環境と同じ対局を出すかを確かめた。
ブランチ `cc-cloud-trial-20260927`（`main` の `269d60a` から切った）。打ち方に関わるコード・Rust・符号化・champion の定義は変えていない。

## 結論

**4,800 局中 4,800 局が一致した（得点と手数の両方）。ずれた局は無い。**ブロックごとの得点・候補ごとの得点と 95% 区間も元の値と小数点以下まで同じである。
この機械（`cc-cloud-4`）の wheel とネットは、元の測定を出した環境と同じ対局を出す。新しい測定に使ってよい条件（§6.3）を満たした。

## 機械

- CPU: Intel Xeon Processor @ 2.10GHz・4 コア（`nproc` = 4）
- メモリ: 15 GiB（スワップ無し）
- Python 3.11.15・rustc 1.94.1（cargo 1.94.1）
- `MEICHO_HOST=cc-cloud-4`

## 手順と確認

1. `pip install ./engine/rust pytest numpy`（所要 44 秒）
2. `meicho_rs.features()` の札: `['bp01_k5', 'bundle_p', 'd065_bin1', 'd065_reeval_isolated_rng', 'draw_buckets', 'encoding_v6', 'endgame_enum', 'known_hand', 'lethal_uniform', 'opp_from_seat', 'te13_switched_scope', 'world_weight']`
3. `python scripts/check_champion_fingerprint.py`: 期待 `f4b80b25c35cfa77`・実測 `f4b80b25c35cfa77`・**一致**（所要 49 秒）
4. ネットの sha256 先頭 16 桁: `s2v_id_s1.json` = `9b43aa3975fb5bfd`・`s2v_id_s2.json` = `eb56088a611782ab`。元の記録 `s2_repr_eval_v1_seeds.json` の `arms` と一致
5. 評価（D-132 追記 4 の V_id 乱数 1 番・2 番の部分）:

       python experiments/eval_s2_repr.py run --arm v_id_s1=results/models/s2v_id_s1.json \
           --arm v_id_s2=results/models/s2v_id_s2.json --n 150 --seed0 841000 --workers 4 \
           --budget-sec 450 --out results/drl/cc_trial/s2_repr_eval_cc.json
       python experiments/eval_s2_repr.py report --in results/drl/cc_trial/s2_repr_eval_cc.json \
           --new v_id_s2 --old v_id_s1 --out results/drl/cc_trial/s2_repr_eval_cc_report.json

   デッキは既定の `results/decksim/env_v1.json` の調整 4 つ（`ENV_SANGE_RF_TSUBAKI`・`ENV_SANGE_RM_TSUBAKI`・`ENV_YANG_RF_TSUBAKI`・`ENV_YANG_RM_TSUBAKI`）、順序つき 16 ブロック × 150 局 × 候補 2 つ＝ 4,800 局。シード 841000..841149。相手は素 planner、手数上限 200、`opp_from_seat=True`（スクリプト内で固定）。
   V_pf の 2 本は今回回していない（依頼の範囲が V_id の 2 本だけ）。

同じコマンドを 5 回打って続きから再開した（`--budget-sec 450` で塊を切る。予算の判定はブロックの開始前なので、塊は 450 秒を少し超える）。塊ごとに `results/drl/cc_trial/` を commit・push した。

## 局ごとの突き合わせ

- 比べたもの: 各局の `[得点, 手数]`（元の `results/drl/s2_repr_eval_v1_seeds.json` の同じキー・同じ添字）
- **一致 4,800／4,800**。最初にずれた局: なし
- 引き分け 0・手数の平均 10.44

## 候補ごとの得点（デッキ等重み・局を再標本化した 95% 区間・各 2,400 局）

- v_id_s1: 本環境 0.599 [0.580, 0.618]／元 0.599 [0.580, 0.618]
- v_id_s2: 本環境 0.645 [0.626, 0.665]／元 0.645 [0.626, 0.665]
- デッキ別（v_id_s1）: SANGE_RF 0.563・SANGE_RM 0.558・YANG_RF 0.668・YANG_RM 0.605（元と同じ）
- デッキ別（v_id_s2）: SANGE_RF 0.640・SANGE_RM 0.637・YANG_RF 0.662・YANG_RM 0.643（元と同じ）

## ブロックごとの得点（各 150 局・Wilson の 95% 区間）

ブロックは（候補・deck_a・deck_b）。候補は偶数シードで deck_a（席 0）、奇数シードで deck_b（席 1）を持つ。

| ブロック（候補・席 0 のデッキ・席 1 のデッキ） | 一致 | 本環境の得点 [95% 区間] | 元の得点 [95% 区間] | 秒 |
|---|---|---|---|---|
| v_id_s1・SANGE_RF・SANGE_RF | 150/150 | 0.700 [0.622, 0.768] | 0.700 [0.622, 0.768] | 77 |
| v_id_s1・SANGE_RF・SANGE_RM | 150/150 | 0.647 [0.567, 0.719] | 0.647 [0.567, 0.719] | 79 |
| v_id_s1・SANGE_RF・YANG_RF | 150/150 | 0.667 [0.588, 0.737] | 0.667 [0.588, 0.737] | 76 |
| v_id_s1・SANGE_RF・YANG_RM | 150/150 | 0.520 [0.441, 0.598] | 0.520 [0.441, 0.598] | 75 |
| v_id_s1・SANGE_RM・SANGE_RF | 150/150 | 0.580 [0.500, 0.656] | 0.580 [0.500, 0.656] | 77 |
| v_id_s1・SANGE_RM・SANGE_RM | 150/150 | 0.513 [0.434, 0.592] | 0.513 [0.434, 0.592] | 72 |
| v_id_s1・SANGE_RM・YANG_RF | 150/150 | 0.540 [0.460, 0.618] | 0.540 [0.460, 0.618] | 70 |
| v_id_s1・SANGE_RM・YANG_RM | 150/150 | 0.460 [0.382, 0.540] | 0.460 [0.382, 0.540] | 73 |
| v_id_s1・YANG_RF・SANGE_RF | 150/150 | 0.640 [0.561, 0.712] | 0.640 [0.561, 0.712] | 75 |
| v_id_s1・YANG_RF・SANGE_RM | 150/150 | 0.613 [0.533, 0.688] | 0.613 [0.533, 0.688] | 76 |
| v_id_s1・YANG_RF・YANG_RF | 150/150 | 0.667 [0.588, 0.737] | 0.667 [0.588, 0.737] | 74 |
| v_id_s1・YANG_RF・YANG_RM | 150/150 | 0.640 [0.561, 0.712] | 0.640 [0.561, 0.712] | 71 |
| v_id_s1・YANG_RM・SANGE_RF | 150/150 | 0.620 [0.540, 0.694] | 0.620 [0.540, 0.694] | 75 |
| v_id_s1・YANG_RM・SANGE_RM | 150/150 | 0.647 [0.567, 0.719] | 0.647 [0.567, 0.719] | 72 |
| v_id_s1・YANG_RM・YANG_RF | 150/150 | 0.587 [0.507, 0.662] | 0.587 [0.507, 0.662] | 77 |
| v_id_s1・YANG_RM・YANG_RM | 150/150 | 0.540 [0.460, 0.618] | 0.540 [0.460, 0.618] | 63 |
| v_id_s2・SANGE_RF・SANGE_RF | 150/150 | 0.740 [0.664, 0.804] | 0.740 [0.664, 0.804] | 74 |
| v_id_s2・SANGE_RF・SANGE_RM | 150/150 | 0.740 [0.664, 0.804] | 0.740 [0.664, 0.804] | 76 |
| v_id_s2・SANGE_RF・YANG_RF | 150/150 | 0.713 [0.636, 0.780] | 0.713 [0.636, 0.780] | 85 |
| v_id_s2・SANGE_RF・YANG_RM | 150/150 | 0.620 [0.540, 0.694] | 0.620 [0.540, 0.694] | 75 |
| v_id_s2・SANGE_RM・SANGE_RF | 150/150 | 0.607 [0.527, 0.681] | 0.607 [0.527, 0.681] | 73 |
| v_id_s2・SANGE_RM・SANGE_RM | 150/150 | 0.573 [0.493, 0.650] | 0.573 [0.493, 0.650] | 71 |
| v_id_s2・SANGE_RM・YANG_RF | 150/150 | 0.607 [0.527, 0.681] | 0.607 [0.527, 0.681] | 77 |
| v_id_s2・SANGE_RM・YANG_RM | 150/150 | 0.620 [0.540, 0.694] | 0.620 [0.540, 0.694] | 66 |
| v_id_s2・YANG_RF・SANGE_RF | 150/150 | 0.687 [0.609, 0.755] | 0.687 [0.609, 0.755] | 78 |
| v_id_s2・YANG_RF・SANGE_RM | 150/150 | 0.720 [0.643, 0.786] | 0.720 [0.643, 0.786] | 77 |
| v_id_s2・YANG_RF・YANG_RF | 150/150 | 0.660 [0.581, 0.731] | 0.660 [0.581, 0.731] | 78 |
| v_id_s2・YANG_RF・YANG_RM | 150/150 | 0.620 [0.540, 0.694] | 0.620 [0.540, 0.694] | 73 |
| v_id_s2・YANG_RM・SANGE_RF | 150/150 | 0.600 [0.520, 0.675] | 0.600 [0.520, 0.675] | 72 |
| v_id_s2・YANG_RM・SANGE_RM | 150/150 | 0.653 [0.574, 0.725] | 0.653 [0.574, 0.725] | 69 |
| v_id_s2・YANG_RM・YANG_RF | 150/150 | 0.587 [0.507, 0.662] | 0.587 [0.507, 0.662] | 71 |
| v_id_s2・YANG_RM・YANG_RM | 150/150 | 0.580 [0.500, 0.656] | 0.580 [0.500, 0.656] | 67 |

## 所要時間

- 塊 1: 456 秒（v_id_s1 のブロック 1〜6）
- 塊 2: 514 秒（v_id_s1 の 7〜13）
- 塊 3: 524 秒（v_id_s1 の 14〜16・v_id_s2 の 1〜4）
- 塊 4: 519 秒（v_id_s2 の 5〜11）
- 塊 5: 353 秒（v_id_s2 の 12〜16）
- **合計 2,366 秒（39.4 分）**。ブロックの実行時間の合計は 2,364 秒・1 ブロック 63〜85 秒
- **1 局あたり 0.49 秒**（壁時計・workers 4・4 コア）。D-132 追記 2 の作業環境（2 コア・workers 4）は V 1 本で 4,800 局に約 82 分＝ 1 局約 1.0 秒だったので、約 2 倍速い

## 記録の訂正

- 塊 2 と塊 3 の commit の要約のブロック番号が 1 つずつずれている（塊 2 を「7-12」、塊 3 を「14-16・v_id_s2 1-3」と書いたが、正しくは上の「所要時間」のとおり 7〜13／14〜16・1〜4）。中身の JSON は正しい

## 出力

- `results/drl/cc_trial/s2_repr_eval_cc.json`（局ごとの `[得点, 手数]`・形式は元と同じ `s2eval-1`）
- `results/drl/cc_trial/s2_repr_eval_cc_report.json`（区間）
- `results/drl/cc_trial/run_log.txt`（ブロックごとの秒数と塊ごとの秒数）

## この文書で言えないこと

- V_pf の 2 本・netfree・乱数 0 番の 4,800 局は回していない。それらの一致は確かめていない（同じ wheel・同じ経路なので一致が見込まれるが、見込みである）
- 全検査（pytest）はこの機械では回していない
