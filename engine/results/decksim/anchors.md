# デッキ類似度（decksim-2）

閾値: s2_trio=3, s1_idf=0.5, s3=0.8, variant_s1_idf=[0.5, 0.8], version=th-1-provisional, provisional=True

idf と平均の基準: 錨だけで回したので、錨を基準にした（候補を読んだら候補だけで計算し直す）（K_smoke_ANKO・K_smoke_SANGE・K_smoke_TSUBAKI・SD001・SD001_swap1・SD02）

## デッキ

- K_smoke_ANKO（錨）: アンコ・ショアキーパー・熾霞／専用札 0.55／色 {'blue': 3, 'green': 2, 'red': 35}
- K_smoke_SANGE（錨）: 散華・漂泊者（女）・漂泊者（男）／専用札 0.90／色 {'blue': 7, 'green': 4, 'red': 29}
- K_smoke_TSUBAKI（錨）: ツバキ・今汐・秧秧／専用札 0.82／色 {'blue': 6, 'green': 2, 'red': 32}
- SD001（錨）: 漂泊者（女）・熾霞・秧秧／専用札 1.00／色 {'blue': 9, 'green': 9, 'red': 22}
- SD001_swap1（錨）: 漂泊者（女）・熾霞・秧秧／専用札 1.00／色 {'blue': 9, 'green': 9, 'red': 22}
- SD02（錨）: 今汐・散華・漂泊者（男）／専用札 1.00／色 {'blue': 9, 'green': 8, 'red': 23}

## 組ごとの値（S1_raw・S1_idf・S1_common・S2_trio・S2_deck・S3〔平均を引いた値〕・S3_raw〔引かない値〕）

- K_smoke_ANKO 対 K_smoke_SANGE: 0.053・0.042・0.222・0・0.000・-0.116・0.846
- K_smoke_ANKO 対 K_smoke_TSUBAKI: 0.096・0.078・0.389・0・0.000・0.541・0.907
- K_smoke_ANKO 対 SD001: 0.067・0.057・—・1・0.143・-0.823・0.746
- K_smoke_ANKO 対 SD001_swap1: 0.067・0.057・—・1・0.143・-0.814・0.744
- K_smoke_ANKO 対 SD02: 0.000・0.000・—・0・0.000・-0.774・0.736
- K_smoke_SANGE 対 K_smoke_TSUBAKI: 0.053・0.042・0.571・0・0.000・0.148・0.960
- K_smoke_SANGE 対 SD001: 0.127・0.115・—・1・0.143・-0.244・0.946
- K_smoke_SANGE 対 SD001_swap1: 0.111・0.101・—・1・0.143・-0.275・0.944
- K_smoke_SANGE 対 SD02: 0.270・0.269・—・2・0.333・-0.069・0.947
- K_smoke_TSUBAKI 対 SD001: 0.067・0.058・—・1・0.143・-0.764・0.895
- K_smoke_TSUBAKI 対 SD001_swap1: 0.067・0.058・—・1・0.143・-0.773・0.892
- K_smoke_TSUBAKI 対 SD02: 0.067・0.064・—・1・0.143・-0.592・0.895
- SD001 対 SD001_swap1: 0.951・0.951・—・3・1.000・0.988・0.999
- SD001 対 SD02: 0.000・0.000・—・0・0.000・0.550・0.971
- SD001_swap1 対 SD02: 0.000・0.000・—・0・0.000・0.562・0.971

## グループ

- 0: K_smoke_ANKO
- 1: K_smoke_SANGE
- 2: K_smoke_TSUBAKI
- 3: SD001・SD001_swap1
- 4: SD02
  - SD001 〜 SD001_swap1（s1_idf・s2_trio・s3）

## 最遠点の並び（後ろほど既にある系統の変種）

- K_smoke_ANKO → SD02 → SD001 → K_smoke_TSUBAKI → K_smoke_SANGE → SD001_swap1

