# 引継ぎ（2026-08-26・DRL）— 段階 0 完了、次は段階 1 から

> **この引継ぎ書は消化済みである（2026-08-26・D-057）。段階 1 は完了した。**
> **最新の引継ぎは `HANDOFF_20260826_DRL2.md`、結果の正本は `DRL_STAGE1_NOTES.md`。**
> 以下は履歴として残す。

rules_draft.md v0.10 準拠 / engine v0.1 / 決定記録 D-001〜**D-056** / 検査 **433 件**
報告の作法は `REPORTING_RULES.md`。計画 `DRL_PLAN.md`、実施記録 `DRL_NOTES.md`、目標の評価 `GOALS_ASSESSMENT_20260826.md`。
発見ループ側の引継ぎ（`HANDOFF_20260826.md`）はそのまま有効（未裁定 2 件・語彙 D・効果クラス分類）。

## 0. 最初にやること（マスターの PC）

1. **Rust を再ビルドする**（`agents.rs` / `lib.rs` を変え、`encode.rs` / `net.rs` を足した）。`RUST_PORT_NOTES.md` §4.1 のとおり
   `maturin build --release --out <OneDrive外>` → `pip install --force-reinstall --no-deps <wheel>`。
   `rust/dist/` の Linux wheel は更新済み（Kaggle 用）。**Windows の wheel は古いまま**。
2. `python -m pytest tests/test_drl.py tests/test_rust_agents.py -q`（11 ＋ 80 件）と `bench_agents.py` の fingerprint 3 種で確認。
3. `pip install torch`（学習に使う。CPU 版で足りる）。

## 1. 現在地

- 段階 0 の 6 項目はすべて完了（`DRL_NOTES.md` §0）。**既定の planner は一手も変わっていない。**
- 記録データ（SD001 planner 同型・train 9,000 局／valid 900 局・計 97 万決定）は `results/drl/*.manifest.json` の指定で再生成する
  （配布していない。Rust 2 スレッドで約 4 分）:
  ```
  python3 experiments/drl_record.py --deck SD001 --seed0 230100 --n 900  --out results/drl/sd001_s1_valid.bin --workers 2
  python3 experiments/drl_record.py --deck SD001 --seed0 231000 --n 9000 --out results/drl/sd001_s1_train.bin --workers 2
  ```
- 煙試験モデル（1 エポック・6 万決定・隠れ 128）は配管確認だけに使い、**残していない**。同じものは
  `python3 experiments/drl_train.py --train results/drl/sd001_s1_train.bin --valid results/drl/sd001_s1_valid.bin --out results/models/drl_smoke.json --epochs 1 --max-records 60000 --hidden 128 --phead 64` で 25 秒で作れる。

## 2. 次の作業（順）— 段階 1（`DRL_PLAN.md` §5）

1. **代打ち π の速度の手当て**（`DRL_NOTES.md` §3-1）。推し: まず「相手モデル（対抗の提出）だけ π」にする口を `agents.rs` に足す
   （`policy_net` を `opp_policy_net` と分ける）。1 葉に 1 回しか呼ばれないので速い。
2. **模倣学習の本番**: `python3 experiments/drl_train.py --train results/drl/sd001_s1_train.bin --valid results/drl/sd001_s1_valid.bin
   --out results/models/drl_sd001_s1.json --epochs 6`（CPU 2 スレッドで 1 エポック 2〜3 分の見込み）。
   一致率はフェイズ別に見る。**数値の目安は測ってから置く**（先に置かない）。
3. **検証 3 つ**（帯 240700.. から。`series_rs` で n=1200・別帯）:
   - π 単体（`{"kind":"policy","net":path,"tau":0}`）vs H／貪欲／planner
   - planner（`value_net` = 学習した V）vs planner
   - planner（`policy_net` または opp だけ）vs planner
   いずれも **下端 > 0.5 でなければ champion 候補にしない**（D-034）。届かなくても段階 1 の目的は「表現できるか」の確認。
4. 隠しカード検査（カード X の行を train から抜く）は任意。
5. **段階 2 の準備**: `drl_train.py --lam 0.5 --init <前の版>` と `drl_record.py --value-net --policy-net --tau 0.05` で 1 反復回せる。
   門番は D-034。**カナリア**（漂泊者 Lv2 到達率・`experiments/measure_horizon.py` の型）を毎反復記録する。

## 3. 使い方の要点

- spec（`arena_rs.PLANNER(pool, value_net=path, policy_net=path, tau=0.05)`）。ネットは JSON のパス。同じパスを上書きしたら
  `meicho_rs.net_forget(path)` を呼ぶ（プロセス内 cache）。
- `series_record(..., record_a, record_b)`: 記録する席を選べる。相手が H のときは A だけ記録する（H の手を学ばないため）。
- 学習の教師: π = 選んだ手（合法手の中の交差エントロピー）、V = z（`--lam` で探索値を混ぜる）。探索値は planner が採点した決定にしか無い（65%）。
- 記録・モデルには**絶対パスを書かない**（C-1 の教訓）。

## 4. 守ること

- `Action` に手を足したら `engine.rs::hash_action` **と** `encode.rs::action_code` / `encode.py::ACTION_TYPES` にも足す。
- 符号化を変えたら Python・Rust 両方を変え、`ENCODING_VERSION` を上げ、記録は作り直す（読み手が版を検査する）。
- 帯は `seed_bands.json` に登録してから。`next_free` = **250000**。80000.. は使わない。
- 「予測が良くなった」を進捗と呼ばない（D-038）。採用の物差しはラダーの直接対決だけ。
