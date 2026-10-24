# 探索器の読みと記録の読み（2026-10-20・クロエ）の台本

`engine/GENERALIST_WALL_READING_20261020.md` の数字を出した台本。**打ち方には使わない・検査は無い・判定には使わない**（帯を登録していない下見）。
`engine` で `set PYTHONPATH=%CD%` を打ってから `python experiments\reading_20261020\<台本>` の形で回す。

- `analyze_rec.py <val|train> [chunk,chunk,...]`: `results/drl/s3_it1_rec/*.xz` を `results/reading_20261020/` に伸ばし、決定ごとの決め手（1 位 − 2 位）・V_0 の部品 3 本の揺れ・膨らみ（root − V_0・root − z）を集計する。`results/models/s2v_id_s{0,1,2}.json` が要る
- `twoseat.py <deck> <局数> <seed0>`: Python の参照実装で netfree＋葉 V_0（部品 s0）の自己対戦を回し、各局面をターンプレイヤーと相手の両視点で V_0・V_1 に当てて勝敗との当てはまりを出す。`results/models/s3v1_id_s{0,1,2}.json` も要る
- `pilot_tpview.py <deck> <局数> <seed0> <出力 json> <avg|tp>`: 葉の採点を両視点の平均（avg）か手番側の視点（tp）にした版と従来の netfree_v の下見の直接対決（席は局の組で入れ替え）
