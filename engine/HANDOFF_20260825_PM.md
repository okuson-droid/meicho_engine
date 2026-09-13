# 引継ぎ書（2026-08-25 夕方）— 次のセッションへ

rules_draft.md v0.10 準拠 / engine v0.1 / 検査 413 件全通過（1 件は データセット未生成で skip）
報告の作法は `REPORTING_RULES.md`。決定記録は `decisions.md` D-001〜**D-051**。

## 0. 30 秒版

今日 1 日で次の 4 つが終わった。順に読めば現在地が分かる。

1. **レビュー**（`REVIEW_2026-08-25.md`）→ マスターが **15 件の裁定を一括で下した（D-050・全て推しを採用、15 は今はやらない）**
2. **Rust 移植が完了**（D-049・`RUST_PORT_NOTES.md`）。エンジン・H・貪欲・計画探索・地平延長版を `engine/rust/`（crate `meicho_rs`）に移し、
   Python 版と**毎手の state・合法手・観測・エージェントの選ぶ手**が一致。計画探索同士で **29〜31 倍**
3. **自動発見ループを実装し、第 1 巡を回した**（D-051・`DISCOVERY_NOTES.md`）。マスターの指摘を入れずに
   SD001 で「漂泊者（女）を 1 ターン目から急いで Lv2 に」（0.552 ±0.028・n=1200）を再発見、
   SD02 で誰も指摘していなかった「漂泊者（男）を 1 ターン目から急いで Lv2 に」（0.540 ±0.020・n=2400）を新発見
4. **エンジンの順序依存（D-040）を Python 側でも修正**（fingerprint 3 種不変）。`PRERELEASE_GOAL.md` を D-050 に合わせて改訂

**次の作業は「語彙 B で発見ループ」「SD02 第 2 巡」「効果クラス分類の提案」の 3 つ**（§4）。
マスターにしてもらうことは「Rust のビルド」と「対局（2 局ごとに渡す）」の 2 つ（§3）。

---

## 1. 現在地

### 1.1 champion（プールごと・D-050-12）

| プール | champion | 作り方 |
|---|---|---|
| SD001 | 計画探索 ＋ δ「漂泊者（女）を 1 ターン目から急いで Lv2 に」 | `arena_rs.PLANNER(pool, delta=[{"kind":"rush_chara","name":"漂泊者（女）","goal":2,"from_turn":1}])` |
| SD02 | 計画探索 ＋ δ「漂泊者（男）を 1 ターン目から急いで Lv2 に」 | 同 `"name":"漂泊者（男）"` |

δ の中身は台帳 `results/discoveries/<deck>.jsonl` のデータにあり、コードには無い（D-050-3）。
**ラダー（`ladder.py` / `results/ladder.md`）はまだ旧 champion のまま**。`series_rs` での再計測は 2 週目（D-050-14）。
対人検証アプリ（`webapp/agents.py` の `DEFAULT_OPPONENT`）も旧 champion のまま（Python 版・変更不要。新 champion を相手にするなら
Python 側に同じ δ を `RushWandererLv2` の形で用意する必要がある。未着手）。

### 1.2 受け入れ基準（D-050-6・`PRERELEASE_GOAL.md` §1.2）

一次: **マスター対 新 AI の直接対局**で「再現できる搾取を名指しできず、F 印から作った対照実験で +5 ポイント以上の修正が出ない」。
二次: 対 champion の直接対決（発見ループでは n=1200）。**隠しカード検査**も含める（未実装・台帳が溜まってから）。

### 1.3 テストと再現

```
python3 -m pytest tests -q                    # 413 件（Rust 拡張が無い環境では test_rust_*.py と test_discovery.py が skip）
python3 experiments/bench_agents.py           # fingerprint 905073e2e202bd39 / 7cfceac12f2c070f / 1f5e2e218cc54acc
python3 experiments/discovery.py --deck SD001 --list
```

---

## 2. 今日できたもの（ファイル地図）

| 種類 | ファイル | 内容 |
|---|---|---|
| 裁定 | `decisions.md` D-049 / D-050 / D-051 | Rust 化の決定と実施記録／15 件の裁定／発見ループ第 1 巡 |
| 評価 | `REVIEW_2026-08-25.md` | 引継ぎ書 `HANDOFF_REVIEW_20260825.md` へのレビュー |
| 設計 | `DISCOVERY_LOOP_DESIGN.md` / `UNSEEN_CARDS_AND_SPEED.md` | 発見ループの設計／初見カードへの一般化 3 段階と高速化 |
| Rust | `rust/`（`src/pyrandom.rs` `cards.rs` `state.rs` `engine.rs` `agents.rs` `intervene.rs` `lib.rs`）、`rust/dist/*.whl`（Linux cp311） | `RUST_PORT_NOTES.md` |
| Python | `meicho/cards_export.py`、`experiments/arena_rs.py`、`experiments/discovery.py` | Rust への受け渡し／対局列／発見ループ |
| テスト | `tests/test_rust_engine.py`(148) `test_rust_agents.py`(80) `test_discovery.py`(13) | 同一性と発見ループの前提 |
| 台帳 | `results/discoveries/SD001.jsonl` `SD02.jsonl`、`*_report.md`、`*_round*.log` | 全候補の測定値（シード帯つき） |
| 目標 | `PRERELEASE_GOAL.md`（D-050 改訂） | §1.2 受け入れ基準／§2.2 対局の使い方／§5 3 週間 |
| 帯 | `experiments/seed_bands.json` | 180000..189999 SD001 発見ループ／190000..199999 SD02／`next_free` 200000 |

---

## 3. マスターにしてもらうこと

1. **Rust のビルド**（`RUST_PORT_NOTES.md` §4.1）: rustup ＋ Visual Studio Build Tools（C++）→ `pip install maturin` →
   `engine/rust` で `maturin develop --release` → `python -m pytest tests/test_rust_engine.py tests/test_rust_agents.py -q`。
   Kaggle/Colab（Python 3.11）なら `rust/dist/` の wheel を `pip install` するだけ。
   **これが無いと発見ループもラダーの再計測も回せない**（Python 版で回すと 30 倍遅い）。
2. **対局**（`PRERELEASE_GOAL.md` §2.2）: 各デッキ 10 局・相手は `planner`。**2 局ごとに渡す**。気になった手には F 印。
   印から頻度診断 → 対照実験（発見ループの δ）に回す。
3. **語彙の追加**（任意・D-050-4）: 「型」として足したい規則があれば `discovery.py` の生成器に足す。カード 1 枚の方針ではなく型。

---

## 4. 次の作業（順）

1. **語彙 B で発見ループ**（SD001 34 候補。`--full-b` で 68）:
   `python3 experiments/discovery.py --deck SD001 --gens B --workers 4 --round 2 --champion '[{"kind":"rush_chara","name":"漂泊者（女）","goal":2,"from_turn":1}]'`
   帯は巡ごとにずれる（`--round` に前回の最終巡を渡す。SD001 は第 2 巡まで使ったので `--round 2` → 第 3 巡）。
   **帯は 1 プール 3 巡分しか無い。** 4 巡目からは `seed_bands.json` に帯を足し、`discovery.py` の `MAX_ROUNDS_PER_BAND` を上げる。
2. **SD02 第 2 巡**（A+C を新 champion に対して）: `--deck SD02 --round 1 --champion '[{"kind":"rush_chara","name":"漂泊者（男）","goal":2,"from_turn":1}]'`
3. **効果クラス分類の提案**（D-050-13）: 較正の表（台帳）と並べて出す。最初の型は「毎ターン誘発・ドロー」（両デッキの発見がこれ）。
4. `--deck` 横断対応（`experiments/measure_*.py` 10 本）と `LEADER_COLOR` の導出化（**Python と Rust を同時に**。`agents.rs::leader_color`）。
5. 2 週目: CEM の設計し直し（対 champion・局数・個体数）→ 発見が絞った次元で CEM → bake-off（再調整した地平延長版を含む）→ ラダー再計測。
6. 3 週目: マスター対新 champion（一次基準）／隠しカード検査／未確認の前提一覧と差分テスト／記録。

---

## 5. 守ること（今日増えた分）

- **Python が真実源。** ルール裁定・カード処理の変更は Python に先に入れ、Rust を追従させる。同一性テストが両者を結ぶ。
- **新オペコードは 3 箇所**（`engine.py::_apply_op`・`rust/src/cards.rs` の `Op`・`rust/src/engine.rs::apply_op`）＋日本語化＋unverified＋裁定テスト 1 本（D-050-11 の standing approval の条件）。
- **`LEADER_COLOR` の複製**が `rust/src/agents.rs::leader_color` にある。導出化は両方同時に。
- **Params / Weights の既定値も複製**（`agents.rs` の `Default` / `tuned_*`）。Python 側を変えたら Rust も。
- **発見ループの規律**: 確認 n=1200、逐次打ち切りなし、境界（下端 0.50〜0.52）は別帯で再確認して合算、候補が複数のときは合算しない。
- **シード帯**: 発見ループは 180000..199999。次の実験は 200000.. から。
- 勝率には n と 95% 区間、見出しには測定の範囲（プール・処置・相手）を書く（レビュー §0.1）。

---

## 6. 未解決・注意

1. **削減 2「分岐点までの再生」は未実装**（D-051 裁定 3・D-050-5 からの逸脱）。挑戦者の乱数消費列が再生では一致しないため見送り。
2. **D-047 の説明「SD02 に該当カードが 1 枚」は数え落とし**だった（`persistent_count` が【ターン終了時】を数えていない）。
   対策 A が SD02 で効かなかった理由は未確定（雑音費用か重みの較正）。`POOL_GROWTH_PLAN.md` §4.5 の説明文は未修正のまま。
3. 発見ループの「発火回数」は上限（禁じる型は合法手が減った決定を数える）。
4. `PersistentAwarePlanner`（D-047 対策 B）は Rust に無い。第二段（評価関数の項＋CEM）で設計し直す。
5. IS-MCTS・学習価値関数は Rust に無い（champion でないため）。使うなら `arena.series`（Python）。
6. Rust の速度の絶対値はクラウド 2 コアの値。ローカル PC と Kaggle で測り直すこと（倍率は持ち越せる見込み）。
7. `results/human_games/` はマスターの 1 局（g001）のみ。

---

## 7. 数字（今日の主要な測定値）

| 測定 | 値 | 出典 |
|---|---|---|
| Rust 計画探索 vs H | 77 局/秒（Python 2.5・31 倍） | RUST_PORT_NOTES §0 |
| Rust 計画探索同士 | 36.7 局/秒（2 スレッド 60.2） | 同 |
| D-046 再現（地平延長 vs 通常・帯 166600・n=1200） | 0.567 ±0.028 下端 0.5386（記録と一致・24 秒） | 同 §2.3 |
| D-045 再現（`Intervention` 版・帯 160200・n=600） | 0.555 ±0.040 下端 0.5152（記録と一致） | test_discovery / 会話記録 |
| SD001 発見 | 漂泊者（女）L2 T1: 0.552 ±0.028（n=1200）下端 0.5235 | DISCOVERY_NOTES §1 |
| SD02 発見 | 漂泊者（男）L2 T1: 0.540 ±0.020（n=2400 合算）下端 0.5205 | 同 §2 |
| 発見ループの費用 | 35 候補で 5〜9 分（2 コア・2 スレッド） | 同 §0 |
