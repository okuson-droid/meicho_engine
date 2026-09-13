# 引継ぎ書（2026-09-07）— 文献計画 便 D（前半）: 測定の道具と診断を先に揃える

rules_draft.md v0.11 準拠 / engine v0.1 / 2026-09-07 / champion = `planner_vb3cps`（Elo 1479 [1454,1502]・1.09 秒/局 Rust 版）/ 発売 2026-09-12（土）
報告の作法は `REPORTING_RULES.md`。用語は `GLOSSARY.md`。マスターへの作業依頼は 5 点セット（`REPORTING_RULES.md` §2.6）。

**位置づけ**: `LITERATURE_PLAN_20260906.md`（以下「計画書」）の裁定 D-069 (1)〜(7)（2026-09-07・すべて推しどおり採用）を受けた**最初の便**である。中身は計画書 §3.4 の便 D のうち前半（D-1・D-2/D-3・D-6・D-7）、§2 の診断のうち M2・M3 の残り・M7、そして便 A の**下見 1 本**（対局なし）。**Python だけを触る。Rust は触らない。champion は変えない。再ビルドは無い。**

**マスターの指示（2026-09-07）**: 引継ぎ書は**次に作業させる便だけ**を書く。後の便は先取りしない。**本便の結果を確認してから**便 A の引継ぎ書を書く。したがって本書に「便 A の実装」は含まれない。本書に書いていない設計判断が必要になったら、推測で補完せず「判断が要る点」として報告すること（作業規約 1）。

---

## この文書の読み方

§0 が結論（何を作るか・完了の判定）。§1 が守ること。§2 が便 4 の結果の確認（本便の前提）。§3 が各項目の仕様。§4 が先に書く検査。§5 が帯。§6 が手順（順番）。§7 が報告の形。§8 が転びやすいところ。§9 が成果物。§10 が次の便の予告（作らない）。

---

## 0. 結論（先に）

### 0.1 何を作るか

| # | 項目 | 新設／変更 | 何のため | 対局 |
|---|---|---|---|---|
| D-1 | 対人局の区間 `experiments/human_games_ci.py` ＋ `REPORTING_RULES.md` §2.7 | 新設・追記 | n=4 全敗を「対マスター勝率は 49〜60% を上回らない」と正しく読む | なし |
| D-2/D-3 | 由来ブロック `experiments/provenance.py` を測定結果の JSON に添える（champion 名・kwargs・モデルの sha256・engine・帯・時刻） ＋ V 凍結の規約（`REPORTING_RULES.md` §2.8） | 新設・変更 4 本 | すべての数値を「どの champion の・どの探索予算で」の条件つきにする。門番の前に V を凍結する | なし |
| D-6 | `diag_optimism.py --by-legal`（合法手数で層別） ＋ 診断用の記録 100 局で 1 回出す | 変更 | M3 の残り（楽観が合法手数とともに増えるか） | 100 局（診断） |
| D-7 | 対人記録に AI の対抗の候補点数 `ai_clash` を残す | 変更 2 本 | 発売初日から相手の型の材料を貯める（便 F の前倒し） | なし |
| M2 | 対抗の混合率と利得幅 `experiments/clash_mix_rate.py` | 新設 | 便 A で束ねたソルバ（A-2）を作るかどうかの分岐 | 自己対戦 ≤200 局（局面採取） |
| M7 | 透視カウンター `experiments/peek_counter.py` と champion の被搾取ベースライン | 新設 | 便 A の候補を比べる第 3 の軸。**測定専用** | 600 局（Python） |
| A-下見 | `proto_matrix_clash.py` に `regret` と `softfloor` を足し、回帰 2 局面での選択を出す | 変更 | 便 A の候補のうち、どれが T-14 を通りうるかを対局なしで知る | なし |
| 検査 | `tests/test_lit_d.py`（§4） | 新設 | 上のすべて。**本体より先に書く** | — |
| 報告 | `LIT_NOTES.md`（新設）・`decisions.md` 追記・プロジェクトメモリ | 新設 | 便 A の引継ぎ書を書くための材料 | — |

### 0.2 完了の判定

1. `tests/test_lit_d.py` が全部通り、既存の検査（約 7 分・2 本に割る）も通る。既定の挙動は 1 ビットも変わらない（fingerprint 3 種不変）。
2. `LIT_NOTES.md` に次の 5 つの数字が **n と 95% 信頼区間つき**で載っている: (a) 対人 4 局の Wilson / Clopper-Pearson 区間、(b) 合法手数で層別した楽観（root−z・root−fresh）、(c) 対抗の混合率と利得幅、(d) champion の対 透視カウンター 勝率、(e) 回帰 2 局面での `regret` / `softfloor` の選択。
3. 測定結果の JSON に `provenance` ブロックが入っている（新しく出した結果すべて）。
4. 対人アプリで 1 局打つと、AI の対抗の行に `ai_clash` が残り、再生（`webapp.record.replay`）が壊れていない。
5. 帯が `seed_bands.json` に登録され、`next_free` が進んでいる。

---

## 1. 守ること（不変条件・全項目共通）

- **champion（`experiments/champion.py` の `CHAMPIONS["SD001"]`）を変えない。** 定義は 4 か所（`champion.py` / `gauntlets/core5.json` / `webapp/agents.py` / `vb.py` 輪 2）で、本便はどれも触らない。
- **既定の挙動は不変。** 足すのは道具・任意引数・記録の追加欄だけ。`bench_agents.py` の fingerprint 3 種（`773a71c15c5bc16e` / `677f28cc3b6995ee` / `6e39c2aa4b35d876`）と新 champion の fingerprint（seeds 471500-471509 = `f82625f68bb79a2d`）が変わらないこと。
- **Rust（`engine/rust`）は触らない。** マスターの PC の再ビルドは無い。
- **覗き見禁止（D-026）**: 透視カウンター（M7）は相手の伏せた提出と真の局面を見る**測定専用の相手役**である。名前は `peek_` で始め、`CHAMPIONS`・`gauntlets/*.json`・`webapp/agents.py` の登録簿に**決して載せない**（検査 T-L6 で固定）。学習の相手にもしない。
- **帯は `seed_bands.json` に登録してから回す（D-028）。台帳は複数セッションが触るので、書く前に必ずマスターの PC から取り直して読む。** 診断の帯は評価にも学習にも使わない。
- **前面・短い塊・再開可能で回す。** コンテナは約 10 分の無操作で回収され、`nohup` の裏回しは消える（2026-09-07 に門番 1 回ぶんを失った）。`bash` は 600 秒上限。長い測定（M2・M7）は `--budget-sec 480` 程度の塊に割り、途中経過をファイルに残して同じコマンドで続きから回る形にする。
- **1,000 局ごとに定期報告する**（マスターの要望・2026-09-07）。本便の測定は 600 局までなので、塊ごと（50〜100 局）に途中経過を報告する。
- **1 便で変える探索器の要素は 0。** 本便は測る道具を作る便であり、AI の打ち方は変えない。`proto_matrix_clash.py` の新モードは試作であって champion の定義ではない。
- **成果物は `SendUserFile` → `device_commit_files` でマスターの PC に書き戻す。** パスは `C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine\...`。記録の `.bin` は持ち帰らない（manifest と結果の JSON は持ち帰る）。
- **数字には基準・n・95% 信頼区間**。区間が広いうちは「まだ読めない」と書く。**判断が要る点は勝手に決めず裁定を仰ぐ**（選択肢と推しは用意する）。

---

## 2. 便 4 の結果の確認（本便の前提。読み直しは不要）

2026-09-07 に D-065 便 4 本体（輪 2 の反復 4'）が完走した。本便に効く事実だけを書く（出典: `decisions.md` D-066〜D-068、`D065_NOTES.md` 末尾）。

| 事実 | 数値 | 本便への含意 |
|---|---|---|
| V_4'（`drl_sd001_vc4.json`）は門番を越えた | 同じ探索器で葉だけ差し替え 0.606 ±0.028（n=1,200・帯 530000・下端 0.578）。錨 3 種は差の区間が 0 をまたぐ。カナリア 153/200 → 77/200（採否には効かせない・D-043） | champion 交代の判定（D-034）は未実施。本便では扱わない |
| 楽観の分解は実質的に出た（D-067） | 検証 94,664 決定で `root − fresh = +0.008`、`root − z = +0.050`。後者の大半は較正を自己対戦とリーグの混合で取った見かけの偏りで、自己対戦だけで取り直すと −0.0001 | 第 2 集第 6 章の「成分 1（勝者の呪い）」は小さい。M3 の残りは**合法手数の層別**だけ（D-6） |
| 較正の偏りは直すと弱くなった（D-067 決着） | 案 A 0.446 ±0.028、案 B 0.465 ±0.028（どちらも上端 < 0.5）。既定 `--league-mode keep` のまま | 教師の当てはまりは強さの代理にならない。採否は対局で決める |
| `eval_vb.py` が中断・再開できる（D-068） | `--chunk` / `--budget-sec` / `--resume`。塊に割っても一括と一致することを確認済み | 本便の M2・M7 も同じ形で作る |
| 帯 | `next_free = 650000`。630000..643999 は D-067 の判定で使用済み | 計画書 §9.1 の初版の帯案は無効。本書 §5 で取り直す |

---

## 3. 各項目の仕様

### 3.1 D-1 対人局の区間 — `experiments/human_games_ci.py`（新設）

**何をするか**: `results/human_games/*.jsonl`（`webapp.record.load_all("results")`）を読み、AI の勝ち数を数え、**Wilson 95% 区間**と **Clopper-Pearson（正確）95% 区間**を出す。勝率の点推定だけを書かない。

- 集計の単位: 全体／相手の版ごと（`opponent.name`）／デッキごと（`deck`）。AI の勝ち = `result.winner == "ai"`、人間の勝ち = `"human"`。`draw`・`aborted`・`reason == "error"` は分母から外し、件数だけ別に出す。
- 式（z = 1.96、p̂ = x/n）:
  - Wilson: 中心 (p̂ + z²/2n) / (1 + z²/n)、半幅 z/(1 + z²/n) · √(p̂(1−p̂)/n + z²/4n²)
  - Clopper-Pearson: 上端 U は P(X ≤ x | U) = 0.025 の解、下端 L は P(X ≥ x | L) = 0.025 の解（二項分布の累積を二分法で解く。scipy は使わない。x=0 なら L=0・U = 1 − 0.025^(1/n)、x=n なら U=1・L = 0.025^(1/n)）
- 出力: 表（n・AI 勝ち・p̂・Wilson [lo, hi]・CP [lo, hi]・除外件数）と、最後に 1 行「言えること: AI の対マスター勝率は CP 上端 X を上回らない（95%）／言えないこと: どれくらい弱いか」。`--json <path>` で JSON も書く。
- **注意書きを出力に含める**: 相手の版が混在している場合（現状は planner／planner_pi／planner_vb3 の 3 版・現 champion との対局は 0 局）は「1 つの二項として扱うのは近似」と印字する。
- 検算値（検査 T-L1 で固定）: n=4, x=0 → Wilson [0.000, 0.490]、CP 上端 0.602。n=10, x=0 → Wilson [0.000, 0.278]、CP 上端 0.309。n=4, x=4 → Wilson [0.510, 1.000]、CP 下端 0.398。n=100, x=50 → Wilson [0.404, 0.596]。

**`REPORTING_RULES.md` §2.7 を足す**（既存の節は変えない）: 「対人局や n が小さい勝率は、点推定ではなく Wilson 区間と Clopper-Pearson 上端を併記する。0 勝・全勝など極端なときは判断に Clopper-Pearson を使う。相手の版が混在しているときはその旨を書く。対人局は判定ではなく診断（どの対抗で価値の見立てが崩れたか）に使う」。

### 3.2 D-2 / D-3 由来ブロック — `experiments/provenance.py`（新設）と測定の出力 4 本

**何をするか**: 測定結果の JSON に `provenance` という 1 ブロックを足し、「どの champion の・どのモデルの・どの実装で・どの帯で」測ったかを機械可読にする。

```python
# experiments/provenance.py
def block(kwargs: dict, engine: str, band: tuple[int, int] | None,
          label: str | None = None, extra: dict | None = None) -> dict:
    """測定結果に添える由来。kwargs はモデルの**名前**のまま渡す（パスに直す前）。"""
    return {
        "label": label,                          # 例 "champion:planner_vb3cps"
        "kwargs": {k: v for k, v in kwargs.items()},      # 名前のまま
        "models": {k: {"file": basename, "sha256": sha256_of(resolve_model(v)), "bytes": size}
                   for k, v in kwargs.items() if k in ("value_net", "opp_policy_net", "policy_net")},
        "engine": engine,                        # "rust" / "python"
        "rust_features": sorted(meicho_rs.features()) if engine == "rust" else None,
        "band": list(band) if band else None,    # [seed0, seed_last]
        "rules_version": "v0.11",
        "written_at": <JST の ISO 文字列>,
        "extra": extra or {},
    }
```

- `sha256_of(path)` は 64 桁の 16 進。同じファイルなら同じ値（検査 T-L2）。
- **足す先**（既存のキーは変えない・増やすだけ）: `eval_vb.py` の最終 JSON（新旧それぞれの kwargs で `provenance_new` / `provenance_old`）、`probe_d065.py` の結果 JSON（候補と基準）、`champion_challenge_vb.py` の結果 JSON、`ladder.py` の `ladder.json` の先頭（ガントレットの各体の kwargs）。既存の検査が読むキーはそのまま残す。
- `label` には `champion.py` の名前が分かるときはそれを入れる（kwargs が `CHAMPIONS["SD001"]` と一致すれば `"champion:planner_vb3cps"`）。
- **V 凍結の規約**（`REPORTING_RULES.md` §2.8 に追記）: 「門番・錨・ラダーを回す前に、その時点の V と π のファイルの sha256 を結果に記録する。門番の対局データで V を再学習しない。門番の結果を見てから V を差し替えない」。実装上は `provenance` を測定の**開始時**に作って書き出す（終了時ではない）。

### 3.3 D-6 楽観の合法手数層別 — `experiments/diag_optimism.py --by-legal`（変更）

**何をするか**: 既存の層（局面の種類 × 自分のターンか）に加えて、`--by-legal` を付けたときは**その決定で探索が点数を付けた候補の数**（`len(recs.scores_of(i))` の有限な要素数）で層を切り、`root − z`・`fresh − z`・`root − fresh` を出す。第 2 集 §6.4.2「合法手数とともに楽観が増えるなら勝者の呪いが主因」の検定である。

- 層: 2／3／4〜5／6〜8／9 以上（点数が 1 つ以下の決定は「探索なし」として別行）。
- 既定（`--by-legal` なし）の出力と JSON は**1 文字も変えない**（T-20 の検査がある）。`--by-legal` のときは `rows_by_legal` を JSON に**追加**する。
- **記録**: 輪 2 の反復 4' の検証記録（`results/drl/vc4_valid_*`）はマスターの PC に無い（`.bin` は持ち帰らない規約）。本便では**診断用の記録を 100 局だけ取り直す**: `results/drl/vc4_ALL.manifest.json` の各塊の `regenerate` と同じ形で、輪 2 の探索器（champion と同じ・取り直し 4 は loop 2 の定義に含まれる）を使う:

```
python3 experiments/drl_record.py --deck SD001 --vb 4 --loop 2 --record both --tau 0.01 --seed0 650000 --n 100 --out results/drl/lit_d6_diag --workers 2
```

帯は §5 の 650000..650199（100 局・両席記録）。Rust 版で 1 局約 2.3 秒なので約 4 分。manifest（`lit_d6_diag.manifest.json`）は持ち帰り、`.bin` は持ち帰らない。**この記録は評価にも学習にも使わない。** 取り直した記録に `--calib-from results/models/drl_sd001_vc4.meta.json` を当てて表を出す。
- 期待される読み方: 合法手数が多い層ほど `root − fresh` が大きければ、勝者の呪いは「小さいが確かに存在する」。全層でほぼ一定なら、残る楽観は較正と strategy fusion の側にある。**どちらでも便 A・B の順序は変わらない**（第 2 集 §6.4.6 の分岐は縮小推定の要否にだけ効き、D-067 で既にその要は消えている）。数字は `LIT_NOTES.md` に残す。

### 3.4 D-7 対人記録に AI の対抗の候補点数を残す（変更 2 本）

**何をするか**: 対人アプリの記録（`results/human_games/*.jsonl`）の **AI の対抗の行**に、AI が対抗で見比べた候補と点数を残す。便 F（相手の型）で「AI が何を迷ってどれを選んだか」と「マスターが実際に何を出したか」を突き合わせる材料になる。

- `meicho/greedy.py::_clash`（`PlannerAgent` も同じ経路）の末尾で `self.last_clash = {"acts": [各候補の表示名], "totals": [totals[i] / samples ...], "chosen": 選んだ添字}` を持つ。**戻り値と挙動は変えない。** 表示名は `tests/test_d065.py::_submitted_name` と同じ規則（`submit` ならカード名、それ以外は `type`）。
- `webapp/session.py::_step` で、AI の行（`by == "ai"`）かつ `before.phase == Phase.CLASH_SUBMIT` のとき、`self.ai` に `last_clash` があれば行に `"ai_clash": {...}` を足す。人間の行には足さない。
- 再生（`webapp.record.replay`）は `action` しか読まないので壊れないはずだが、**実際に 1 局記録して再生し、`RecordMismatch` が出ないことを検査で確かめる**（T-L4）。古い記録（`ai_clash` 無し）もそのまま読めること。
- `APP_VERSION` は変えない（欄の追加は後方互換）。`webapp/README.md` に欄の説明を 3 行足す。
- 思考時間は既に `ms` として各行にある（追加不要）。「型の事後確率」の欄は便 F で足す（本便では作らない）。

### 3.5 M2 対抗の混合率と利得幅 — `experiments/clash_mix_rate.py`（新設）

**何を知りたいか**: 対抗の行列ゲームを解いたとき、**均衡が混合戦略になる局面がどれだけあるか**と、**手による値の幅（利得幅）がどれだけか**。第 2 集 §1.5（混合が要る局面は少数・根の近く）の meicho 版であり、**便 A で束ねたソルバ（A-2・Rust 150〜250 行）を作るかどうか**を決める（計画書 §2 M2: 混合率 < 5% なら作らない）。

- **局面の採取**: 現 champion の設定（`champion.kwargs_for("SD001")` をモデル解決したもの）の Python `PlannerAgent` 同士で SD001 同型戦を回し（帯 §5 の 650200..650399、必要な局だけ）、`Phase.CLASH_SUBMIT` で決定者の合法手が 2 以上の局面を、**両席から**集める。1,000 局面で止める（1 局あたり数局面なので 200 局以内で足りる見込み）。局面は `(seed, ply)` で再現できるように記録し、状態は保持しない。
- **各局面で**（`experiments/diag_nash_delta.py::probe` と同じ組み立て。ただし kwargs は現 champion）: `agent.samples`（6）本の決定化 t ごとに、行 = AI の合法手、列 = その決定化での相手の合法手（`legal_actions(t, 1 − pi)`）の行列 m を `agent._score_clash`（CRN を毎回復元）で埋める。
- **解く**: RM+（regret matching plus・負の後悔を 0 に切り上げ・**平均戦略を出力**）を 400 反復。可搾取度 = max_i (m ȳ)_i − min_j (x̄ᵀ m)_j が 0.01 を超えたら 1,000 反復まで延ばし、それでも超えるものは「未収束」と数える。小さな既知の行列（じゃんけん・鞍点のある 3×3）で LP と一致することを検査で固定（T-L5）。
- **数えるもの**（決定化 1 本を 1 件として）: (a) AI の均衡戦略の台（重み > 0.05 の手の数）が 2 以上の割合 = **AI 側の混合率**、(b) 相手側の混合率、(c) 利得幅 = 行列の最大 − 最小、および「均衡値 − 最良の純戦略の保証値（max_i min_j m_ij）」（混合で得している量）、(d) 均衡の最良応答と**現行の argmax-π₀ の選択**が一致する割合、(e) 局面ごとに 6 本を通しての一致（「6 本すべてで純戦略」の局面の割合）。
- **出力**: `results/lit/m2_clash_mix_rate.json`（局面ごとの 1 行を JSONL に書き足して再開可能にし、最後に集計）と表。集計に**分岐の結論**を 1 行で書く: 「AI 側の混合率 X%（n=…・95% 区間 …）→ 5% 未満なら A-2 は作らない／以上なら作る」。
- 費用: 1 局面あたり 6 本 × 行 ≤ 9 × 列 ≤ 9 の `_score_clash`（1 回数〜十数 ms）で最大数秒。1,000 局面で 1〜2 時間。`--budget-sec 480 --resume` で塊に割る。

### 3.6 M7 透視カウンター — `experiments/peek_counter.py`（新設・**測定専用**）

**何を知りたいか**: champion の対抗が「読まれたときにどれだけ損をするか」（被搾取の大きさ）。第 2 集 §1.2 の Ex_d（相手に最適反撃させたときの損失）の meicho 版で、便 A の候補を「錨で悪化なし」に加えて「被搾取が増えていない」で比べる第 3 の軸になる。**本便では現 champion のベースラインを 1 つ測るだけ。**

- **透視カウンター** `PeekCounter(PlannerAgent)`: champion と同じ kwargs で作る。属性 `peek`（相手の提出。既定 None）。`_clash(self, s, pi, acts)` を上書きし、`peek is None` なら親クラスの `_clash`、そうでなければ**決定化せず真の局面 s の上で**各自分の手 a について `self._score_clash(s, pi, a, self.peek, goal)`（CRN を毎回復元）を取り、最大の手を返す。対抗以外の決定は champion と同じ（透視しない）。`last_clash` も持つ。
- **専用の対局ループ** `play_game_peek(config, agents, seed, peek_seat)`: `meicho.runner.play_game` と同じだが、`Phase.CLASH_SUBMIT` で両者が決めるときだけ、**先に相手（champion）の手を取り、それを `agents[peek_seat].peek` に入れてから透視側の手を取る**。行動の辞書は**席の昇順**に組み直して `apply` に渡す（`webapp/session.py` の注記と同じ理由。順序が違うと乱数の消費順が変わる）。それ以外の局面は `play_game` と同一。
- **測定** `series_peek(make_champ, n, seed0, workers=2)`: champion 対 透視カウンター。席は seed の偶奇で入れ替える（透視側の席 = flip）。**champion から見た勝率** p ± 95% CI を出す（0.5 を大きく下回るのが自然）。あわせて**透視が手を変えた割合**（同じ局面で親クラスの `_clash` が選ぶ手と透視の手が違った対抗の割合）を数える。
- n=600・帯 §5 の 651000..651599・Python・2 コア。**50 局ごとの塊**で 1 局ごとの勝敗を JSONL に書き足し、同じコマンドで再開する（`--budget-sec 480`）。1 局約 10〜20 秒なので 600 局で 1.5〜3 時間。**塊ごとに途中経過を報告する。**
- **守り**: モジュールの先頭に「測定専用・champion 候補にしない・学習の相手にしない（D-026）」を書く。エージェント名は `peek_counter`。検査 T-L6 で `CHAMPIONS`・`gauntlets/*.json`・`webapp/agents.py` に `peek` を含む名前が無いことを固定する。`review_nopeek_audit.py` の対象にはしない（透視するのが仕事）。

### 3.7 A-下見 — `proto_matrix_clash.py` に 2 モードを足し、回帰 2 局面での選択を出す（対局なし）

**何を知りたいか**: 便 A の候補のうち、**どれが T-14（対人 2 局の回帰局面）を通りうるか**を、実装に入る前に知る。既に分かっていること（`HUMAN_GAMES_20260903_NOTES.md` §6・decisions.md A-8/A-9）: `soft τ=1` は直らない（π₀ が安い赤・緑にほぼ 0 を与える）、`uniform`（= `opp_mix=1.0`）は直るが錨が悪化、`minimax` と `nash`（決定化ごと）はパス／青を選ぶ、`opp_mix` は両局面を直すのに 0.9 以上が要る。

- 足すモード（`MatrixPlanner._clash` の分岐として。既存モードは変えない）:
  - `regret`: 決定化ごとに行列 m（行 = 自分・列 = 相手の合法手）を作り、列ごとの最良 `colbest_j = max_i m[i][j]`、各行の最大後悔 `R_i = max_j (colbest_j − m[i][j])` を取り、`totals[i] −= R_i`。全決定化を足して最大（= 最大後悔が最小）の手を選ぶ（第 2 集 §4.8・Savage のミニマックス後悔）。
  - `softfloor(ε)`: 相手の分布を `(1−ε)·softmax(π₀/τ) + ε·一様`（τ=1）にして期待値。ε ∈ {0.3, 0.6} の 2 つ。
- `pos` サブコマンドで、既存 7 モードに新 3 モード（`regret`・`softfloor 0.3`・`softfloor 0.6`）を足して **g001 T9・g002 T10 の選択と点数**を印字する。これが本便の成果物（表）。
- **併せて**: M2 で採った局面のうち先頭 100 局面で、`regret` の選択が現行 `argmax` と**違う割合**と、`uniform` と一致する割合を出す（`--compare-rules argmax,regret,uniform`）。「回帰 2 局面は直るが普段の対抗をどれだけ変えるか」の目安になる。対局はしない。
- **やらないこと**: 新モードで champion と対局すること（それは便 A）。Rust に写すこと。

---

## 4. 検査の一覧（`tests/test_lit_d.py`・**本体より先に書く**）

| # | 検査 | 何を固定するか |
|---|---|---|
| T-L1 | `test_wilson_and_clopper_pearson_known_values` | §3.1 の検算値 4 組（小数第 3 位まで一致）。x=0 と x=n の対称性。n=0 で落ちずに「なし」を返す |
| T-L1b | `test_human_games_ci_reads_records` | 手元の 4 局から n=4・AI 0 勝・相手の版 3 種を数え、混在の注意書きが出る |
| T-L2 | `test_provenance_block_is_stable_and_complete` | 同じ kwargs から 2 回作った `sha256` が一致。`models` に value_net / opp_policy_net / policy_net の 3 つが揃う。`engine` が "rust"/"python" 以外なら `ValueError` |
| T-L2b | `test_measurement_outputs_carry_provenance` | `eval_vb.py`・`probe_d065.py`・`champion_challenge_vb.py` の**結果を組み立てる関数**（対局は空回し・`--n 0` 相当か疑似結果）が `provenance` を含む。既存キーが消えていない |
| T-L3 | `test_diag_optimism_by_legal_partitions_the_decisions` | 合成の記録（`test_d065.py` の `_fake_records` を流用）で、層別の n の合計が全体の n に等しく、`--by-legal` なしの出力が従来と**バイト単位で**同じ |
| T-L4 | `test_record_carries_ai_clash_and_still_replays` | アプリのセッションで 1 局を最後まで自動で打ち（`test_webapp.py` の型）、AI の対抗の行に `ai_clash` があり、`replay` が `RecordMismatch` を出さない。`ai_clash` を落とした古い形式の記録も読める |
| T-L5 | `test_rm_plus_matches_lp_on_small_games` | じゃんけん（均衡 1/3 ずつ・値 0）、鞍点のある 3×3（純戦略）、2×2 の混合（既知の解）で、平均戦略の可搾取度 < 1e-3 かつ値が一致。**最終反復ではなく平均戦略**を出していることを、最終反復が振動する例で固定 |
| T-L5b | `test_clash_mix_rate_counts` | 手作りの行列 3 つ（純・混合・未収束もどき）で混合率・利得幅・一致率の数え方が正しい |
| T-L6 | `test_peek_counter_best_responds_and_is_not_registered` | 小さな対抗局面で `peek` を与えると真の最良応答を選ぶ（親クラスの選択と違う例を 1 つ含む）。`peek=None` なら親クラスと同じ手。`CHAMPIONS`・`gauntlets/*.json`・`webapp/agents.py` に `peek` を含む名前が無い |
| T-L6b | `test_play_game_peek_equals_play_game_without_peek` | 透視を切った `PeekCounter` 同士で `play_game_peek` と `play_game` の結果（勝者・ターン数・steps）が 20 局一致 |
| T-L7 | `test_proto_regret_and_softfloor_rules` | 手作りの 2×2 行列で `regret` が最大後悔最小の手を選ぶ。`softfloor(ε=1)` が `uniform` と同じ分布。`softfloor(ε=0)` が `soft τ=1` と同じ |
| T-L8 | `test_defaults_unchanged_lit_d` | fingerprint 3 種と新 champion の fingerprint が不変（`bench_agents.py` の値と、`test_d065.py::test_defaults_unchanged_d065` の型） |

**「直した」と言う前に、わざと壊して検査が落ちることを確かめる**（D-065 の教訓）。特に T-L5 の「平均戦略」と T-L6 の「登録簿に無い」は、通り抜けやすい。

---

## 5. 帯（`seed_bands.json`・**着手時にマスターの PC から取り直して読み、登録してから回す**）

`next_free` は 2026-09-07 時点で 650000。次を登録し、`next_free` を 652000 に進める。**登録の直前に台帳の `next_free` がまだ 650000 であることを確かめる**（別セッションが進めていたら、その値から取り直し、本書の番号を読み替えて `LIT_NOTES.md` に書く）。

| 帯 | kind | 用途 | 局数 |
|---|---|---|---|
| 650000..650199 | diag | D-6 楽観の診断用の記録（輪 2 の探索器・100 局・両席）。**評価にも学習にも使わない** | 100 |
| 650200..650399 | diag | M2 対抗局面の採取（champion 同士・Python）。1,000 局面で止める | ≤200 |
| 650400..650999 | diag | 予備（M2 の追加採取・A-下見の局面比較） | — |
| 651000..651599 | diag | M7 透視カウンター 対 champion（n=600・Python・席は偶奇で入替） | 600 |
| 651600..651999 | diag | M7 の追試予備 | — |

`purpose` には「文献計画 便 D（前半）・`HANDOFF_20260907_LIT_D.md` §5」と書く。**A-下見は対局しないので帯は要らない。**

---

## 6. 手順（この順で）

1. **持ち込み**: `HANDOFF_20260905_D065_BIN4.md` §5 の一覧どおり（`engine/meicho`・`experiments`（`datasets/`・`gauntlets/` も）・`tests`・`scripts`・`webapp`・`rust`（触らないが検査が読む）・`results`（`models/` は必須・`human_games/` も）・`decklists`・`cards/cards_structured.{csv,json}`）。`device_stage_files` は 1 回 50 ファイルまで。**`seed_bands.json`・`decisions.md`・`D065_NOTES.md` は最新を取り直す。** Rust wheel は `cd engine/rust && maturin build --release --out dist` で自前ビルド（約 45 秒）し、`pip install --force-reinstall --no-deps dist/*manylinux*.whl`。カード画像は 1 枚ずつ違う中身のプレースホルダ（SD01-018 と SD01-019 だけ同じ）。
2. **帯の登録**（§5）。台帳を書き戻す。
3. **検査を先に書く**（§4）。この時点では新設モジュールが無いので import で落ちてよい。
4. **D-1**（区間の道具と REPORTING_RULES §2.7）→ 手元の 4 局で表を出す。
5. **D-2/D-3**（provenance と出力 4 本、REPORTING_RULES §2.8）。
6. **D-6**（`--by-legal`）→ 診断用の記録 100 局を取り（帯 650000..・Rust 版・約 4 分）→ 表を出す。manifest を持ち帰る。
7. **M2**（局面採取 → 解く → 集計）。塊に割って回し、塊ごとに途中経過を報告する。
8. **A-下見**（`regret`・`softfloor` を足し、`pos` の表と、M2 の局面 100 個での一致率）。
9. **M7**（透視カウンターと 600 局）。塊ごとに報告する。
10. **D-7**（`last_clash` と `ai_clash`）。アプリで 1 局打って再生を確かめる。
11. **全検査**（新設 + 既存。既存は `pytest tests -q -p no:randomly --ignore=tests/test_discovery.py` と `pytest tests/test_discovery.py -q -p no:randomly` の 2 本に割る。約 7 分）。fingerprint 3 種 + 新 champion の fingerprint。
12. **報告**（§7）と書き戻し（§9）。

順序の理由: D-1〜D-3 は他の項目の出力形式を決めるので先。M2 の局面は A-下見でも使うので M2 が先。M7 は最も時間がかかるので、他が終わってから塊で回す。D-7 はアプリを触るので最後にまとめて検査する。

---

## 7. 報告の形（`LIT_NOTES.md`・新設。`D065_NOTES.md` の型）

各項目に「0. 結論（先に）／1. 何をしたか／2. 数字（n・95% CI・帯・engine）／3. 言えること／言えないこと／4. 判断が要る点」。特に次を必ず含める。

- D-1: 対人 4 局の表。「対マスター勝率は CP 上端 0.602 を上回らない」の 1 行と、相手の版が混在している注意。
- D-6: 合法手数の層別表（層ごとの n・root−z・fresh−z・root−fresh）と、「合法手数とともに増えるか」の一文。
- M2: 混合率（AI 側・相手側）と 95% 区間、利得幅の平均と中央値、argmax-π₀ との一致率、**分岐の結論（A-2 を作るか）**。
- A-下見: g001・g002 での全モードの選択と点数の表（既存 7 + 新 3）。`regret` が 2 局面とも烈火を選ぶか。M2 の局面 100 個での `regret` と `argmax` の不一致率。
- M7: champion 対 透視カウンター の勝率 p ±CI（n=600）と、透視が手を変えた割合。**これが便 A の候補を比べる「被搾取」の基準値になる。**
- 検査の件数（通過・skip とその理由）、fingerprint 4 種。
- **判断が要る点**は本便では原則出ない見込みだが、出たら選択肢と推しをつけて書く。

途中経過は**塊ごと**にマスターへ報告する（数字は途中である旨を添える）。

---

## 8. 転びやすいところ（症状 → 意味 → 直し方）

| 症状 | 意味 | 直し方 |
|---|---|---|
| Python の champion 同士が 1 局 10〜20 秒かかる | 代打ち π と選択フェイズの探索で Python は遅い（Rust 版の 1.09 秒/局とは別物） | M2・M7 は Python でしか組めないので、局数を本書の値（≤200・600）に留め、塊と再開で回す。速さの数字を報告するときは **engine を必ず書く** |
| `proto_matrix_clash.MatrixPlanner` の選択が `greedy._clash` の同モードと僅かに違う | 試作は CRN の保存・復元をしていない（本体は `_save_crn` / `_restore_crn` で候補間の乱数を揃える） | 下見の用途では許容。新モードを本体に写すときは本体の CRN の型に合わせる（それは便 A） |
| `regret` で 2 局面が直らない | 後悔表は列ごとの最良との差なので、相手の合法手に「烈火に勝つ手」が無い決定化では 烈火 の後悔が 0 になるはず。直らないなら行列の向き（行 = 自分・列 = 相手）か符号（`totals −= R`）の取り違え | T-L7 の 2×2 で先に固定する。`HUMAN_GAMES_20260903_NOTES.md` §2 の詰み表で手計算と突き合わせる |
| 透視カウンターの勝率が champion と互角 | `peek` が渡っていない（`play_game_peek` の順序・席の取り違え）か、対抗が両者同時に決まる局面で `peek` を入れる前に act を呼んでいる | T-L6 で「peek を与えると親と違う手を選ぶ例」を先に固定する。`play_game_peek` の中で `agents[peek_seat].peek` を**相手の act の後・自分の act の前**に入れているか見る |
| `play_game_peek` と `play_game` の結果が透視なしでも違う | 行動の辞書の挿入順が席の昇順でない（乱数の消費順が変わる） | `{pi: acts[pi] for pi in sorted(acts)}` に組み直してから `apply` |
| RM+ の値が LP と合わない | 最終反復を出している／負の後悔を切り上げていない／行と列の最大化・最小化を取り違え | 平均戦略（累積 ÷ 反復数）を出す。じゃんけんで 1/3 が出るまで直す |
| `--by-legal` を付けないのに JSON が変わった | 新しいキーを既定でも書いている | 既定では `rows_by_legal` を書かない。T-L3 のバイト比較で固定 |
| 記録の再生で `RecordMismatch` | `ai_clash` を足すときに `action` の中身や行の並びを変えた | 行に**キーを 1 つ足すだけ**。`action` と `ply` の並びは触らない |
| `seed_bands.json` の `next_free` が 650000 でない | 別セッションが進めた | その値から取り直し、本書の帯番号を読み替えて `LIT_NOTES.md` に対応表を書く。**上書きしない** |
| 診断用の記録の `drl_record.py --loop 2` が `policy_net` のパスで落ちる | D-068 で直した `_resolve` の穴と同種（spec を作る口が複数ある） | `eval_vb._resolve` と同じ解決を通す。`test_every_spec_maker_resolves_the_proxy_pi` が見ている口を使う |
| `bash` が 600 秒で切れて塊の途中で止まる | `--budget-sec` が大きすぎる | 480 に下げる。塊は必ず「終わった局だけ」を数える |
| 検査が torch 無しで落ちる | 学習側の検査は `pytest.importorskip("torch")` で skip にする規約 | 本便の検査は torch を要らない形で書く（記録の合成は `_fake_records`） |

---

## 9. 成果物と書き戻し

| 成果物 | 置き場所（マスターの PC の `engine\` 配下） |
|---|---|
| `experiments/human_games_ci.py`・`experiments/provenance.py`・`experiments/clash_mix_rate.py`・`experiments/peek_counter.py`（新） | `experiments\` |
| `experiments/diag_optimism.py`・`experiments/proto_matrix_clash.py`・`experiments/eval_vb.py`・`experiments/probe_d065.py`・`experiments/champion_challenge_vb.py`・`experiments/ladder.py`（変更） | `experiments\` |
| `meicho/greedy.py`（`last_clash` のみ）・`webapp/session.py`・`webapp/README.md` | `meicho\`・`webapp\` |
| `tests/test_lit_d.py`（新） | `tests\` |
| `REPORTING_RULES.md` §2.7・§2.8 | `engine\` |
| `results/lit/m2_clash_mix_rate.json`・`results/lit/m7_peek_baseline.json`・`results/lit/d6_optimism_by_legal.json`・`results/lit/d1_human_games_ci.json`・診断記録の manifest | `results\lit\`・`results\drl\` |
| `experiments/seed_bands.json`（登録） | `experiments\` |
| `LIT_NOTES.md`（新）・`decisions.md`（末尾に「D-070 文献計画 便 D（前半）の結果」を追記）・プロジェクトメモリ（`literature_plan.md` の進み具合の表と索引） | `engine\`・メモリ |

**マスターの PC で要る作業**: 無い（Rust を触らないので再ビルドは無い。アプリの確認は作業環境で行う）。

---

## 10. 次の便（予告のみ・本便では作らない）

本便の結果（M2 の混合率、A-下見の表、M7 のベースライン、D-1 の区間）を確認してから、**便 A（対抗の作り直し）の引継ぎ書**を書く。候補の数（A-2 を作るか）と最初に実装する順（`regret` が 2 局面を直すなら A-3 を先）は、本便の数字で決まる。便 A は Rust を触るので、マスターの PC の再ビルドが 1 回入る（5 点セット）。それまでの間、champion は `planner_vb3cps` のまま、対人アプリの既定の相手も変えない。
