# Rust 移植（D-049）— 実施記録と使い方

rules_draft.md v0.10 準拠 / engine v0.1 / 2026-08-25
報告の作法は `REPORTING_RULES.md` に従う。

## この文書の読み方

§0 が結果。§1 が何を移したか、§2 が「同じ結果になること」をどう確かめたか、§3 が速度。
§4 はビルドと使い方（マスターの PC・Kaggle/Colab）、§5 は今後コードを触るときの規約、
§6 は移していないもの、§7 は次にやること、§8 は限界。

---

## 0. 結論（先に）

**エンジンだけでなく、H・貪欲・計画探索・地平延長版まで Rust に移し、Python 版と同じ結果を出す。**

| 対戦（SD001 同型・単一スレッド・クラウド 2 コア） | Python | Rust | 倍率 |
|---|---|---|---|
| ヒューリスティック同型 | 287 局/秒 | 3,268 局/秒（Rust 内完結なら 14,000/2 スレッド） | 11 倍 |
| 計画探索 vs H | 2.5 局/秒 | **77 局/秒** | **31 倍** |
| 計画探索同士 | 1.2 局/秒 | **36.7 局/秒**（2 スレッドで 60） | **29 倍** |
| 地平延長版 vs 計画探索 | （未計測） | 23 局/秒 | — |

同じ結果であることの根拠（§2）: 全 apply 後の state の JSON・合法手・観測・**エージェントが選ぶ手**が
毎手一致する（テスト 228 件追加、全通過）。さらに **D-046 の測定（地平延長 vs 通常、n=1200、帯 166600..）を
Rust で回し直したところ 0.567 ±0.028／下端 0.5386 と、記録と同じ数字が 24 秒で出た**（Python では 20 分以上）。

発見ループ（`DISCOVERY_LOOP_DESIGN.md`）の一巡約 11 万局は、ローカル 4 コアで **15 分前後**の見込みになる
（レビュー時点の見積 30 時間 → 削減案で 1〜2 時間 → Rust 化でさらに 1/8）。

---

## 1. 何を移したか

`engine/rust/` に crate `meicho_rs`（PyO3 で Python 拡張）。

| Rust | 元の Python | 内容 |
|---|---|---|
| `src/pyrandom.rs` | `random.Random` | CPython 互換 MT19937。文字列シード（sha512 経由）・整数シード・`random` / `getrandbits` / `shuffle` / `choice` / `sample` / `getstate` / `setstate` |
| `src/cards.rs` | `cards.py` | カード表。**真実源は Python**。`meicho/cards_export.py` の JSON を起動時に読む |
| `src/state.rs` | `state.py` | `GameState`。`to_json` が Python の `to_json` と同じ構造を返す |
| `src/engine.rs` | `engine.py` | `initial_state / decision_players / legal_actions / apply / apply_owned / outcome / observe`、効果解決の 3 層（D-022） |
| `src/agents.rs` | `heuristic.py` / `oppmodel.py` / `greedy.py` / `planner.py` / `measure_horizon.LongHorizonPlanner` | H・相手モデル・貪欲（決定化・安定化・葉の採点）・計画探索（木・racing・共通乱数）・地平延長 |
| `src/intervene.rs` | （新規・D-050/051） | 発見ループの `Intervention` 13 種と `Challenger`（champion ＋ δ）。禁じる型は `agents::Restrict` として計画探索の木の中まで効く |
| `src/lib.rs` | — | Python への公開。`GameState` / `HeuristicAgent` / `GreedyAgent` / `PlannerAgent` / `Challenger` / `play_game` / `series`（スレッド並列・`delta` で挑戦者） |

Python 側の追加:

| ファイル | 内容 |
|---|---|
| `meicho/cards_export.py` | `cards.py` → JSON（Rust に渡す） |
| `experiments/arena_rs.py` | `arena.series` と同じ約束で Rust 内完結の対局列を回す `series_rs` / `gauntlet_rs` |
| `tests/test_rust_engine.py` | エンジンの同一性（148 件） |
| `tests/test_rust_agents.py` | エージェントの同一性（80 件） |

境界は `UNSEEN_CARDS_AND_SPEED.md` §3.3 の **(c)**（計画探索ごと）に相当する。
Python から 1 局に 1 回呼ぶだけで、対局中に境界をまたがない。

### 順序依存（D-040）について

Rust 版の `apply` は行動を**席の昇順で処理する**。Python 版の「辞書の挿入順」依存は Rust 版には無い
（`test_apply_is_order_independent_in_rust`）。Python 側も D-050 で同じ規約に直した（fingerprint 不変）。

---

## 2. 同じ結果であることの確かめ方

**受け入れ基準（D-049）は「全 apply 後の GameState の JSON が Python 版と完全一致」**であり、
fingerprint（勝者・ターン数・ライフ）より厳しい。実際にはそれ以上を比べている。

### 2.1 エンジン（`tests/test_rust_engine.py`）

Python 版で対局を進め、同じ行動を Rust 版にも流し、**毎手**次を突き合わせる。

- state の JSON（`pending_*`・`choice_resume`・`peeked_opp_hand` まで全項目）
- `decision_players`
- `legal_actions`（両席・順序込み）
- `observe`（両席）
- `outcome`

条件: SD001 同型 50 局・SD02 同型 30 局・異型戦 20 局（random 同士）／H 同士 30 局／貪欲 vs H 10 局／計画探索 vs H 4 局。
網羅の確認（別途 240 局）: 選択の全種類（pay_or_damage / switch_back / use_optional / reveal_count /
discard / discard_for_effect / order）・連撃・手札上限調整・山札の再構成（`rng_calls` 最大 6）に到達している。

### 2.2 エージェント（`tests/test_rust_agents.py`）

同じ局面で Python 版と Rust 版のエージェントに手を選ばせ、**毎手の選択が一致**することを確かめる。
乱数の消費列（H の混合戦略の抽選・決定化のシャッフル・共通乱数の巻き戻し）が bit 単位で合わないと通らない。

条件: H 既定 40 局（両デッキ）・H パラメータ指定・貪欲（デッキリスト有／無・重み指定・標本 3）・
計画探索（既定／未調整＋racing／SD02）・計画探索同士・地平延長版・`play_game` の戻り値。

### 2.3 実測値の再現

D-046 の n=1200 測定を Rust で回し直し、**0.567 ±0.028／下端 0.5386** で記録と一致した。
`arena_rs.series_rs(PLANNER(pool, extra_turns=1), PLANNER(pool), 1200, CONFIG, workers=2, seed0=166600)`。

---

## 3. 速度（詳細）

測定環境: クラウド 2 コア・CPython 3.11・`opt-level=3, lto="fat"`。**ローカル PC の絶対値は違う**が、
Python 版の実測（計画探索 vs H 2.1 局/秒）がクラウドとほぼ同じだったので、倍率はそのまま持ち越せると見込む。

| | Python | Rust（Python から `play_game` で 1 局ずつ） | Rust（`series`・内完結） |
|---|---|---|---|
| H 同型 | 287 | 3,268 | 7,100/スレッド |
| 計画探索 vs H | 2.5 | 77 | — |
| 計画探索同士 | 1.2 | 33.6 | 36.7（2 スレッドで 60.2） |

`series` は `py.allow_threads` で GIL を放し、シードをスレッドに割り振る。プロセス並列は不要になった。
結果はスレッド数に依存しない（シード順に並べ直して返す）。

---

## 4. ビルドと使い方

### 4.1 マスターの PC（Windows）

1. Rust: https://rustup.rs から `rustup-init.exe`。MSVC ツールチェーンが要るので
   「Visual Studio Build Tools」の「C++ によるデスクトップ開発」を先に入れる
2. `pip install maturin`
3. `engine\rust` で:

```
maturin build --release --out dist
pip install --force-reinstall --no-deps dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
```

4. 確認: `python -m pytest tests/test_rust_engine.py tests/test_rust_agents.py tests/test_discovery.py -q`（241 件）と
   `python experiments\bench_agents.py` の fingerprint 3 種
   （`905073e2e202bd39` / `7cfceac12f2c070f` / `1f5e2e218cc54acc`）。
   DRL の口まで含めるなら `tests/test_drl.py`（14 件）も足す。

**`--out dist` は省かないこと。** 省くと wheel は `target\wheels\` に出る。
`rust/dist/` はこのプロジェクトが wheel を置く場所として使っており（4.2 の Linux 版も同じ場所）、
**行き先を揃えておかないと「古い wheel を入れ直して、変更が入っていないのに入ったつもりになる」事故が起きる。**
実際 2026-08-26 に、手順書きが `target\wheels` で運用が `dist` だったために
「ビルドしていないのに `pip install` して file does not exist」で 1 往復した（D-057）。

**注意 1: `maturin develop` は使わない。** 仮想環境（`VIRTUAL_ENV` / `CONDA_PREFIX` / `.venv`）が無いと
`Couldn't find a virtualenv or conda environment` で落ちる。ここで仮想環境を作ると
**その中にしか `meicho_rs` が入らず**、ふだん pytest を回している Python とは別物になる。
`maturin build` ＋ `pip install` のほうが素直である。

**注意 2: `--force-reinstall` を必ず付ける。** crate の版は `0.1.0` のまま変えていないので、
素の `pip install` は「already satisfied」と言って**古い拡張を残したまま成功したふりをする**。
中身だけ新しい同じ版を入れ直すときは必須。`--no-deps` は依存を巻き込まないため。

**注意 3: `.pyd` を掴んでいるプロセスがあると上書きできない**（`アクセスが拒否されました`）。
開いている Python・pytest・対人検証アプリのサーバーを閉じてから入れ直す。

**注意 4: `pip install` の前に必ず `maturin build` を走らせる。** wheel が無い状態で入れ直そうとすると
`WARNING: ... looks like a filename, but the file does not exist` に続いて `OSError: [Errno 2]` で落ちる。
これは「ビルドが失敗した」ではなく「**ビルドをしていない**」の合図である。
`rust\dist\` に前回の wheel が残っていても、それはソースを変える前のものなので入れ直しても意味がない。

Python の版が変わったら作り直す（拡張は版ごと）。

### 4.2 Kaggle / Colab（Linux）

`rust/dist/` に Linux x86_64・CPython 3.11 用の wheel を置いてある。Python 3.11 なら
`pip install meicho_rs-0.1.0-cp311-cp311-manylinux_2_34_x86_64.whl` だけで済む。
版が違う場合は `apt`/`curl` で Rust を入れて 4.1 と同じ手順（数分）。

### 4.3 API

```python
import meicho_rs as rs
from meicho.cards_export import cards_json
rs.load_cards(cards_json())                       # 起動時に1回（真実源は cards.py）

s = rs.initial_state(cfg.chara_decks, cfg.action_decks, seed)
rs.decision_players(s); rs.legal_actions(s, pi); rs.observe(s, pi); rs.outcome(s)
t = rs.apply(s, {pi: action_dict})                # 非破壊。action は Python 版と同じ dict
rs.apply_owned(s, actions)                        # 破壊的（専有しているときだけ）
s.to_json()                                       # Python 版 GameState.to_json と同じ構造

h = rs.HeuristicAgent(seed, params=None)          # params は heuristic.Params の項目名の dict
g = rs.GreedyAgent(seed, opp_decklist=pool, samples=6, ...)
p = rs.PlannerAgent(seed, opp_decklist=pool, tuned=True, plan_samples=4, race_after=99, extra_turns=0)
a = p.act(s, pi)                                  # dict（Python 版と同じ手）
```

対局列は `experiments/arena_rs.py`:

```python
from experiments.arena_rs import series_rs, PLANNER, HEURISTIC
r = series_rs(PLANNER(pool, extra_turns=1), PLANNER(pool), 1200, CONFIG, workers=4, seed0=180000)
print(r, r.p - r.ci)                              # arena.Result と同じ
```

**手の記録のハッシュ（D-053）**。`series` と同じ引数で、各局の
`(a_won, turns, steps, fired_a, digest)` を返す:

```python
from experiments.arena_rs import series_rs_digest
out = series_rs_digest(PLANNER(pool, delta=[...]), PLANNER(pool), 30, CONFIG, workers=2, seed0=210000)
[r[4] for r in out]                               # 各局の digest（全決定を畳み込んだ 64 ビット）
```

`digest` はその局の全決定 `(決定者, 選んだ手)` を `engine::hash_action`（FNV-1a）で畳み込んだもの。
**同じシード・同じ相手で digest が全局一致する＝毎手同じ手を選んだ**。
勝敗・ターン数・手数の一致は挙動の一致を意味しないので、挙動の比較にはこちらを使う。
発見ループの選別（δ が champion の手を変えたか）がこれを使っている。
`series` の戻り値（4 要素）は変えていない。

---

## 5. 規約（コードを触るとき）

1. **Python 版が真実源。** ルール裁定・カード処理の変更は Python に先に入れ、Rust を追従させる。
   追従したら `tests/test_rust_engine.py` / `test_rust_agents.py` が通ることを確認する。
   **Rust 側だけで挙動を変えてはならない**（同一性テストが落ちるので実質できない）。
2. **新オペコード**は `engine.py::_apply_op` と `rust/src/cards.rs`（`Op` 列挙・`from_str`/`as_str`）と
   `rust/src/engine.rs::apply_op` の 3 箇所に足す。Rust 版は未知のオペコードを読んだ時点で落ちる
   （`Op::from_str` の panic）ので、足し忘れは `load_cards` で露見する。
3. **`heuristic.LEADER_COLOR`（キャラ名の直書き）は Rust 側にも複製がある**（`agents.rs::leader_color`）。
   D-047 で予定している「Lv0【対抗】の `self_color` からの導出化」は、**両方同時に**行うこと。
   片方だけ直すと `test_rust_agents.py` が落ちる。
4. 新しいエージェントや葉評価の差し替え（学習価値関数など）は、まず Python で書いて測り、
   champion 候補になったら Rust に移す。同一性テストを先に書く（`_lockstep` の型をそのまま使える）。
5. シード帯の台帳（`seed_bands.json`）の規律は変わらない。`series_rs` も `seed0` を受け取る。
6. **`Action` に手の種類を足したら `engine.rs::hash_action` にも足す**（D-053）。
   `match` が網羅的なのでコンパイラが落としてくれる（足し忘れは `error[E0004]`）。
   ここは記録用であってルールの裁定には関与しないが、**タグ番号を後から変えてはならない**——
   過去に測った digest と比べられなくなる。
7. **Rust を変えたらマスターの PC でも `maturin develop --release` を回し直すこと。**
   `.so`/`.pyd` はソースと一緒には配られない。古いままだと Python 側のテストは通るのに
   Rust 側の挙動だけ古い、という最悪の食い違いが起きる（同一性テストで露見はする）。

---

## 6. 移していないもの

| もの | 理由 | 使うときは |
|---|---|---|
| IS-MCTS（`mcts.py`） | champion ではない（Elo 1262 < 計画探索 1338）。木の構造が別 | `arena.series`（Python） |
| 学習価値関数（`valuenet.py` / `planner_v`） | D-038 で負の結果。C-1 の続きが決まってから | 同上 |
| 対人検証アプリ（`webapp/`） | 人間の速度で十分。エンジンの真実源は Python のまま | 変更不要 |
| ラダー（`ladder.py`） | `arena.series` で回っている。`series_rs` への差し替えは小さいが、Elo の再計測と定義ハッシュの更新が要る | §7 |
| `experiments/measure_*.py`（10 本） | `load_deck("SD001")` 固定の `--deck` 横断対応（D-047 §6.1-1）と一緒に `arena_rs` へ移すのが筋 | §7 |
| `RushWandererLv2` 等の診断用エージェント | **済**: `Intervention` の `rush_chara` が同じ手を選ぶ（`tests/test_discovery.py`） | `DISCOVERY_NOTES.md` |
| `PersistentAwarePlanner`（D-047 対策 B） | 評価関数の項の差し替え。発見ループの第二段で改めて設計する | — |

---

## 7. 次にやること（順）

1. ~~発見ループの実装~~ **済**（D-051・`DISCOVERY_NOTES.md`）。1 巡 35 候補が 2 スレッドで 5〜9 分
2. `experiments/measure_*.py` の `--deck` 横断対応と `arena_rs` への移行（既存の測定値が再現することを 1 本ずつ確認）
3. ラダーを `series_rs` で回し直し、Elo と定義ハッシュを更新（D-034 の規律どおり 80000.. 帯）
4. `LEADER_COLOR` の導出化（Python・Rust 同時）

---

## 8. 限界

1. 速度の絶対値はクラウド 2 コアの値。ローカル PC と Kaggle で測り直すこと（倍率は持ち越せる見込み）。
2. 同一性テストは有限の局数（エンジン 190 局＋エージェント 80 局超）に対するもの。
   到達していない分岐（例: 進行不能による引き分け D-021）は Python 版のテストが担保している。
   Rust 版に固有の分岐は無い（写しである）が、**未知の差は「起きたら同一性テストが落ちる」形で見つける**。
3. `sample`（CPython の `random.sample`）は k > 5 で `setsize` の計算に `math.log` を使う。
   Rust の `ln` と丸めが違う境界（k·3 が 4 の冪のとき）が理論上ありうるが、エンジンの用途（手札 ≤ 8）では
   `_sample_opponent` が使われておらず、`determinize` は `shuffle` のみである。固定値テストは通っている。
4. Rust 版の `Params` / `Weights` の既定値は Python 版の写しである。Python 側の既定値を変えたら
   `agents.rs` の `Default` / `tuned_*` も変えること（同一性テストが落ちて気づける）。
