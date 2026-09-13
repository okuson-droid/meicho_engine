# C-4 恒久評価インフラ 設計書

作成: 2026-08-24 / 準拠: rules_draft.md v0.10 / 対象: engine v0.1
前提: `HANDOFF_C4.md`。着手時テスト 94件 全通過（本セッションで再確認済）。

本書は実装前の設計を確定させるための文書である。実装後は decisions.md に
D-034 として要旨を転記し、本書は経緯の記録として残す。

---

## 0. 一言でいうと

「誰と・何局・どのシードで戦わせるか」を**データ（JSON）**として固定し、
その結果を **Bradley-Terry レーティング（Elo 換算）**に直し、
**results/ladder.json に追記**していく。champion の交代は
「現 champion との直接対決で、95%信頼区間の下限が 0.5 を上回る」ときに限る。

## 1. 解決する問題（再掲）

一次指標「対 H_default 勝率」は天井に張り付き、強いエージェント同士の差を
圧縮する（IS-MCTS 0.887 vs 計画探索 0.923、直接対決は 0.287 vs 0.713。D-033）。
測り方が壊れているので、C-1 以降の改善を判定できない。
本作業はエージェントを強くしない。**物差しだけ**を作る。

## 2. 構成（新規ファイル）

```
experiments/
  arena.py                 既存。series/gauntlet/ci95 はそのまま使う（作り直さない）
  registry.py              【新】エージェント名 → pickle 可能な生成器 (Mk) の登録簿
  rating.py                【新】Bradley-Terry 推定・Elo 換算・ブートストラップ信頼区間・循環検出
  ladder.py                【新】ガントレット定義を読み、総当たりを回し、結果を追記する CLI
  gauntlets/
    core5.json             【新】完了条件用（ランダム/H/貪欲/計画探索/MCTS）
    full10.json            【新】摂動H（X1/X2/X3/π_det/π_mix）を加えた拡張プール
  seed_bands.json          【新】使用済みシード帯の台帳（HANDOFF §3 を機械可読化）
results/
  ladder.json              【新】ラダーの追記記録（再現に必要な情報をすべて含む）
  ladder.md                【新】最新ラン の人間向け表（ladder.py が生成）
tests/
  test_ladder.py           【新】本作業のテスト
```

既存の `measure_agents.py` 等は当面そのまま残す（§4.2「寄せる」は任意項目）。

## 3. ガントレット定義（データ化）

`gauntlets/core5.json` の形:

```json
{
  "name": "core5",
  "version": 1,
  "deck": "SD001",
  "mode": "mirror",
  "seed_band": 80000,
  "n_default": 300,
  "agents": {
    "random":  {"factory": "random",  "n_cap": 300},
    "H":       {"factory": "heuristic", "n_cap": 300},
    "greedy":  {"factory": "greedy",  "n_cap": 300},
    "planner": {"factory": "planner", "n_cap": 300},
    "mcts160": {"factory": "mcts", "kwargs": {"iterations": 160}, "n_cap": 100}
  },
  "anchor": {"agent": "H", "elo": 1000},
  "champion": "planner"
}
```

設計上の決めごと:

- **`factory` は `registry.py` の登録名**。生成器は `Mk` 型（クラス＋kwargs）で
  pickle 可能。lambda 禁止の制約（arena.py）を JSON 側から満たす。
- **対戦局数は `min(n_default, n_cap_a, n_cap_b)`**。MCTS（0.29 局/秒）を含む
  ペアだけ局数を落とす。信頼区間が広くなる代わりに完走できる。局数の差は
  Bradley-Terry が自然に扱う（§5）。
- **同一ガントレット内の全ペアは同じシード列 `seed_band .. seed_band+n-1`** を
  使う。ペア間で山札の並びを共有すると（共通乱数）、ペア同士の比較の分散が
  減る。ペア内は当然すべて別シードである。先攻後攻の偶奇入替は arena.py 既存。
- **ガントレットのハッシュ**（JSON 正規化後の sha256 先頭16桁）を結果に残す。
  定義を 1 文字でも変えたら別物として記録される。
- **`anchor`**: レーティングは差しか決まらないので、H_default を 1000 に固定し
  他を相対値で表す。プールが変わっても H を含めていれば数字が接続する。
  H_default は過去の全記録の共通相手であり、参考値として残す（§4.3 準拠）。

## 4. シード帯の台帳

`experiments/seed_bands.json`:

```json
{
  "bands": [
    {"start": 0,     "end": 9999,  "purpose": "A-3 CEM 探索 / measure_agents / ablation / fingerprint"},
    {"start": 10000, "end": 19999, "purpose": "A-3 検証"},
    {"start": 20000, "end": 29999, "purpose": "A-5 被搾取性"},
    {"start": 30000, "end": 39999, "purpose": "A-4 感度"},
    {"start": 40000, "end": 49999, "purpose": "A-4 w_resource 追試"},
    {"start": 50000, "end": 59999, "purpose": "B-3 相手モデル"},
    {"start": 60000, "end": 69999, "purpose": "B-3 診断"},
    {"start": 70000, "end": 79999, "purpose": "B-1 IS-MCTS"},
    {"start": 80000, "end": 89999, "purpose": "C-4 ラダー（評価専用。調整・探索に使用禁止）"}
  ],
  "next_free": 90000
}
```

- `ladder.py` は起動時に、ガントレットの `seed_band` が台帳に「C-4 ラダー」として
  登録済みであることを検査する。未登録なら実行を拒否する。
- テストで帯の重複がないことを検査する。
- **80000.. は評価専用**である。今後の CEM や学習（C-1）は `next_free` 以降を
  取り、台帳に追記してから使う。これが D-028（探索と検証の分離）の機械化である。

## 5. レーティング

### 5.1 Bradley-Terry を採用する（Elo の逐次更新ではなく）

Elo の本来の形は対局順に少しずつ更新する逐次法で、結果が対局の順番に依存し、
対戦数の偏りにも弱い。本件は総当たりの勝敗行列が一度に手に入るので、
**Bradley-Terry モデルの最尤推定**（Hunter 2004 の MM アルゴリズム）で
一括推定するのが正しい。局数が違うペアも尤度に自然に反映される。
表示は慣れた尺度に合わせ **Elo 換算 `400·log10(γ)`** で出す。

- 完全分離（誰かが全勝／全敗）で推定が発散するのを防ぐため、
  各ペアに仮想勝敗 0.5 勝 0.5 敗を加える（弱い事前分布。標準的な処置）。
  ランダムAI は全敗に近いので、これは実際に効く。
- 引き分け・打ち切りは分母から除く（作業規約6、arena.py 既存）。

### 5.2 信頼区間

作業規約6 の「必ず信頼区間を併記」をレーティングにも適用する。
勝敗行列の各ペアを二項分布で再標本化する**パラメトリック・ブートストラップ**
（B=1000、乱数は固定シード）で、各エージェントの Elo の 2.5%〜97.5% 点を出す。
勝率の ±1.96√(p(1-p)/n) も併記する（従来の記録と接続するため）。

### 5.3 非推移性の検出（§4.2）

「A が B に有意に勝ち越す」（勝率の下限 > 0.5）を有向辺とし、
長さ 3 の閉路を全列挙して警告する。閉路があると Bradley-Terry の一次元の
序列は実態を表さないので、その旨を出力と ladder.json に残す。
現時点で閉路は観測されていない（B-1）。C-2（PSRO）を見据えた前倒しである。

## 6. champion の定義と更新手順（明文化）

1. champion はガントレット JSON の `champion` に書く。現在は `planner`。
2. 挑戦者を昇格させる条件は **現 champion との直接対決 n ≥ 300（ラダー帯）で、
   挑戦者の勝率の 95%信頼区間の下限が 0.5 を上回る**こと。
   これ以外の根拠（対 H 勝率、Elo の順位）では交代しない。
3. 昇格前に必ず (a) 覗き見監査（`meicho/audit.py`, D-026）を通す、
   (b) 別のシード帯で追試して境界の結果でないことを確認する
   （HANDOFF §6 罠3）。
4. 昇格したら JSON の `champion` を書き換え、ladder.json に理由（対戦結果）を
   残し、decisions.md に追記する。
5. Elo と直接対決が食い違う（挑戦者が Elo では上だが直接対決で勝てない）場合は
   **直接対決を優先**し、閉路として記録する。

`ladder.py` は各ランの末尾で「champion 候補」を機械的に判定して表示する
（自動では書き換えない。判断は人が行う）。

## 7. 結果の永続化

`results/ladder.json` は配列で、1 ラン＝1 要素を追記する。

```json
{
  "run_id": "2026-08-24T12:00:00+09:00/core5",
  "date": "...", "gauntlet": "core5", "gauntlet_hash": "…",
  "rules_version": "v0.10", "engine_version": "0.1",
  "python": "3.11.15", "workers": 2,
  "seed_band": 80000,
  "agents": { "planner": {"factory": "planner", "kwargs": {}, "repr": "PlannerAgent(...)"} , ... },
  "pairs": [ {"a": "planner", "b": "H", "n": 300, "wins_a": 277, "decided": 300, "p": 0.923, "ci": 0.030}, ... ],
  "ratings": { "planner": {"elo": 1443, "lo": 1391, "hi": 1502}, ... },
  "cycles": [],
  "champion": "planner",
  "champion_candidates": [],
  "wall_time_sec": 1450
}
```

再現手順は「同じ commit のコードで `python3 experiments/ladder.py core5 --workers N`」
であり、`workers` に依らず同一の `pairs` が得られる（arena.py の不変条件）。
`ladder.md` は最新ランの表（Elo 順、勝率行列、閉路、候補）を書き出す。

## 8. 計算量の見積もり（クラウド 2 コア・workers=2）

| ペア群 | 局数 | 概算 |
|---|---|---|
| MCTS160 × 4 相手 | 100 × 4 | 0.29 局/秒 → 約 12 分 |
| 計画探索 × 3 相手（R/H/貪欲） | 300 × 3 | 2.1 局/秒 → 約 4 分 |
| 貪欲 × 2（R/H）・H × R | 300 × 3 | 1 分未満 |

core5 は 1 ラン **約 20 分**。full10 は MCTS の相手が 9 になるため約 45 分。
本セッションでは core5 を完走し（完了条件）、full10 は定義だけ用意する。

## 9. テスト計画（先に書く。作業規約5）

| テスト | 検証内容 |
|---|---|
| `test_bt_recovers_known_strengths` | 既知の真の強さから生成した勝敗行列で BT の序列が復元される |
| `test_bt_handles_unequal_n` | 局数が 10 倍違うペアが混在しても推定が破綻しない |
| `test_bt_separation_regularized` | 全勝エージェントで発散しない（有限の Elo） |
| `test_bootstrap_deterministic` | 同じ入力で同じ信頼区間 |
| `test_cycle_detection` | 合成した A>B>C>A を検出し、推移的な行列では検出しない |
| `test_seed_bands_no_overlap` | 台帳の帯が重複せず、ラダー帯が登録済み |
| `test_gauntlet_hash_stable` | JSON のキー順を変えてもハッシュが同じ、値を変えると違う |
| `test_ladder_reproducible_small` | 極小ガントレット（R/H, n=6）を workers=1/2 で回し、pairs が一致 |
| `test_champion_rule` | 下限 > 0.5 のときだけ候補になる |

## 10. 本セッションで決めた設計判断（D-034 に転記する要旨）

1. レーティングは Bradley-Terry 一括推定＋Elo 換算。H_default = 1000 を錨とする。
2. ガントレットはデータ。局数は `min(n_default, n_cap)` で高価なエージェントだけ落とす。
3. シード帯 80000..89999 は評価専用。台帳を機械可読化し、未登録帯での実行を拒否する。
4. champion の交代は直接対決の信頼区間下限 > 0.5 のみを根拠とし、人が書き換える。
5. 対 H 勝率は廃止せず、参考値として ladder.json に残る（pairs に含まれる）。

## 11. 未決事項（マスターの判断を仰ぐ）

- A. 本セッションで core5 の本番ラン（約 20 分）まで実施するか。
- B. full10 も本セッションで回すか（＋約 45 分）。
- C. 対戦数の自動割り当て（§4.2）を今回入れるか、次回に回すか。
  入れる場合も「境界ペアにだけ帯の続きのシードを追加する」決定的な形にする。
