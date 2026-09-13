# 引継ぎ書（2026-09-08）— 便 E-0: 輪 2 の成果 V_4'（`drl_sd001_vc4.json`）を D-034 の手順で champion 交代の判定にかけ、通れば交代する

rules_draft.md v0.11 準拠 / engine v0.1 / 2026-09-08 / champion = `planner_vb3cps`（Elo 1479 [1454,1502]・1.09 秒/局 Rust 版・fingerprint `7251a931d252a57a`＝§1 の手順）/ 発売 2026-09-12（土）
報告の作法は `REPORTING_RULES.md`（§2.6 5 点セット・§2.7 対人局の区間・§2.8 V 凍結）。用語は `GLOSSARY.md`。

**位置づけ**: `LITERATURE_PLAN_20260906.md`（計画書）§3.5 の便 E（学習の輪 2 への追加）の**0 番目**である。輪 2 の反復 4' は D-065 便 4 本体で完走し、その成果 V_4' は**同じ探索器で葉だけ差し替えた門番を 0.606 ±0.028（n=1,200・下端 0.578）で越えている**（decisions.md D-066）。しかし D-034 の交代判定（別帯の直接対決・対照・覗き見監査・fingerprint・ラダー）は**未実施のまま**で、その間に便 D（前半）と便 A（前半）が先に進んだ。便 A（前半）の候補 `lu50` が「条文は通るが対にすると約 3.5 ポイント弱い」（D-071）で止まったいま、**発売前に champion を強くできる根拠が最も厚いのは V_4' である。** 本便はそれを判定にかける。**Python の定義とモデルの指定を変えるだけで、探索器（Rust）は変えない。したがってマスターの PC の再ビルドは要らない。**

**マスターの指示（2026-09-07）**: 引継ぎ書は**次に作業させる便だけ**を書く。本便の結果を確認してから次の引継ぎ書を書く。本書に書いていない設計判断が必要になったら、推測で補完せず「判断が要る点」として報告する。**提案はすべて推しを採用する**（包括方針・D-069）。

---

## この文書の読み方

§0 が結論（何をし、何をもって終わりとするか）。§1 が守ること。§2 が便 A（前半）の結果の確認と、そこから出た 3 つの判断の扱い。§3 が「なぜ今 V_4' か」（根拠と、足りない条件）。§4 が手順（この順で）。§5 が検査。§6 が帯。§7 が判定の分岐。§8 がマスターへの依頼文（対人局）。§9 が報告。§10 が転びやすいところ。§11 が次の便の予告（作らない）。

---

## 0. 結論（先に）

### 0.1 何をするか

1. **V_4' を D-034 の交代判定にかける。** 挑戦者は「現 champion `planner_vb3cps` の葉だけを `drl_sd001_vc4.json` に差し替えた版」。差分はこれ 1 つで、探索器・π₀・代打ち・選択フェイズは動かさない。判定は `experiments/champion_challenge_vb.py --challenger-json '{"value_net": "drl_sd001_vc4.json"}'` を**新しい帯**（§6）で回す: 直接対決 n=1,200・対照（現 champion 同士）n=1,200・覗き見監査・fingerprint。
2. **ラダー core5 に候補を足して回す**（v9・`planner_vc4cps`・champion 欄は据え置き）。交代条件のうちラダーの条件（decisions.md D-064 の表では**条件 2**。D-069(2)・`core5.json`・`results/ladder.md` が「第 4 条件」と呼んでいるのも同じもの。本書は以後 D-064 の番号＝1 直接対決／2 ラダー／3 監査／4 fingerprint／5 判断は人、で呼ぶ）。Rust 版で回せる組は Rust（`--engine auto`）。**Kaggle が整っていれば Kaggle（4 コア・約 3 時間）、整っていなければ作業環境（約 5 時間・`--budget-sec 480` の塊）**（§4.4・D-072）。
3. **通れば交代する**: 名前は **`planner_vc4cps`**（葉が `vc4` に変わったので名前を変える・D-065 便 4 の規律）。**3 か所同時**（`experiments/champion.py`／`experiments/gauntlets/core5.json`（v10・champion 欄）／`webapp/agents.py`（`DEFAULT_OPPONENT` も））。D-065 便 4 で 4 か所目だった `experiments/vb.py` は**変更不要**（§4.5 に理由。代わりに一致の検査を 1 本足す）。新 fingerprint を記録し、検査を張り替える。
4. **マスターに対人局を依頼する**（§8・5 点セット）。再ビルドは要らない。アプリの既定の相手が新 champion になるので、SD001 で 3 局・SD02 で 3 局を打ってもらう。**対人局は判定ではなく診断**（`REPORTING_RULES.md` §2.7）。
5. 便 A（前半）の判断① を冒頭で直す（`lethal_uniform > 0` かつ `value_net` 無しは `ValueError`）。**打ち方は変わらない。**

### 0.2 作らないもの（本便では）

- **輪 2 の反復 5'（記録・学習）**: 便 E の本体。Kaggle に寄せる分担（D-069(5)）なので別の引継ぎ書で扱う。
- **`lethal_uniform` の再測定**: `lu50` の数字（D-071）は**葉が V_3 のときの値**である。champion が V_4' になれば土俵が変わるので、測り直すなら別の便。本便では**アプリの選べる相手に「新 champion ＋ θ=0.5」を候補・未測定として置く**（§4.5）だけ。
- **A-2（束ねたソルバ）・便 B・便 C・便 F・GSPRT（D-4）・`ladder_analysis.py`（D-5）**: 手を付けない。D-4・D-5 が無いので、門番は n=1,200 固定、ラダーの条件は従来の Bradley-Terry の Elo で読む（D-069(2) の「切り替え前は現行どおり」）。
- **判断③（`lu50` の対 貪欲 の追試）**: 推し A（しない）。V_3 上の数字なので、champion が替われば問い自体が消える。

### 0.3 前提の裁定（便 A（前半）の判断が要る点 3 件・D-071）

**マスターの包括方針「提案は推しを採用する」に従い、3 件とも推し（選択肢 A）で進める。** 異なる裁定が出た場合は、本書の該当箇所を読み替える。

| 判断 | 採る案 | 本書での扱い |
|---|---|---|
| ① `lethal_uniform` が `value_net` を前提にしている（設計の穴） | **A: `lethal_uniform > 0` かつ `value_net is None` なら `ValueError`** | 本便の冒頭で直す（§4.0）。Python と Rust の両方。既定 0.0 の挙動は不変 |
| ② `lu50` を交代させるか | **A: いまは交代しない。アプリの選べる相手として残し、対人局を先に** | 本便で champion が V_4' に替われば、`lu50` の測定は V_3 上の値になる。対人局の依頼（§8）は**新 champion に対して**出し直す。`planner_vb3cps_lu50` は残す（表示名を「旧champion＋」に直す） |
| ③ `lu50` の対 貪欲 の上端 +0.0001 を追試するか | **A: しない** | 何もしない。`decisions.md` に「V_3 上の問いとして閉じる」と記す（§9） |

### 0.4 完了の判定

1. `champion_challenge_vb.py` の結果 JSON（`results/vb/champion_challenge_vc4.json`）が新しい帯で揃っている: 直接対決の下端・対照の区間・監査の違反数・digest。**由来（provenance）が開始時に入っている。**
2. ラダー core5 v9 が完走し、`results/ladder.md` / `results/ladder.json` に `planner_vc4cps` の順位と Elo の区間がある。
3. 交代する場合: 3 か所（§4.5）が揃い、`tests/test_drl.py::test_champion_definition_is_consistent_everywhere` を含む検査が全部通る。新 champion の fingerprint（§1 の手順）が `decisions.md` と検査に記録されている。旧 champion の fingerprint `7251a931d252a57a` は**旧 champion の spec を明示した検査**として残っている。アプリを起動すると既定の相手が新 champion で、1 手打てる。
4. 交代しない場合: 何を満たさなかったかが数字つきで `decisions.md` にあり、champion は据え置き。`planner_vc4cps` はガントレット v9 とアプリの選べる相手に残る。
5. 帯が登録され、`next_free` が進んでいる。
6. マスターへの依頼文（§8）が、判定の結果に合わせて埋まっている。

---

## 1. 守ること（不変条件・全項目共通）

- **1 便で変える探索器の要素は 1 つ。** 本便が変えるのは**葉の価値関数 V**（`drl_sd001_vb3.json` → `drl_sd001_vc4.json`）だけである。判断① の `ValueError` は打ち方に触れない。
- **既定の挙動は不変。** `bench_agents.py` の fingerprint 3 種（`773a71c15c5bc16e` / `677f28cc3b6995ee` / `6e39c2aa4b35d876`）は素の探索器を測るので、本便の前後で動かない。**champion の fingerprint は交代すれば変わる**——それは「壊れた」ではなく「替えた」である。区別のため、旧 champion（`planner_vb3cps`）の値 `7251a931d252a57a` は spec を明示した検査で固定し続ける。**fingerprint の手順**: Rust 版・同型ミラー 10 局・seeds 471500..471509・workers=2・各局の digest 列を `sha256(repr(digests))` して先頭 16 桁（便 D §8.2）。
- **Python が真実源、Rust はその写し。** 本便で Rust に触るのは判断① の引数検査だけ。Linux wheel は作業環境で自前ビルド（`cd engine/rust && maturin build --release --out dist` → `pip install --force-reinstall --no-deps dist/*manylinux*.whl`）。**マスターの PC の再ビルドは出さない**（打ち方に関わる Rust の変更が無い。§4.5 の確認を通すこと）。
- **D-034 の 5 条件（D-064 の表の番号で 1 直接対決／2 ラダー／3 監査／4 fingerprint／5 判断は人）は、勝ち越す挑戦者の条件をそのまま当てる。** 直接対決の 95% 下限 > 0.5（n=1,200・**別帯**）／ラダー core5 で 1 位相当／覗き見監査 0／fingerprint 記録／判断は人。D-065 便 4 の交代は「同じ強さで速い」基準だったが、**本便は「勝ち越したから交代」**であり、記録にそう書く。
- **覗き見禁止（D-026）**: 監査 0 は必須。透視・カンニング版は候補にしない。
- **帯は `seed_bands.json` に登録してから回す（D-028）。着手時に台帳をマスターの PC から取り直し、`next_free` が 660000 であることを確かめる。** ラダーは 80000.. 専用帯（登録済み）。
- **V を凍結する（§2.8）**: `champion_challenge_vb.py` と `ladder.py` は由来を開始時に**作る**が、ファイルに**書き出すのは完走時**である（`champion_challenge_vb.py` は最後の `json.dump`、`ladder.py` の途中経過ファイルには由来が入らない）。§4.0 で足す `--budget-sec` の途中経過ファイルには**由来を最初の塊の前に書き込む**こと（開始時に凍結した証拠を残す）。`drl_sd001_vc4.json` と `drl_sd001_vb3.json` の sha256 が結果に入っていることを確かめ、報告に書く。**門番の結果を見てから V を差し替えない。**
- **前面・短い塊・再開可能で回す。** 裏回しは消える。`champion_challenge_vb.py` は `--budget-sec` を**受け取るが使っていない**（§4.0 で直す）。`ladder.py` は `--budget-sec 480 --engine auto` で回る（既定の途中経過は `results/ladder_resume_core5.json`）。**1,000 局ごとに定期報告する**（マスターの要望）。
- **計算資源の分担（decisions.md D-072・`COMPUTE_PLAN_20260908.md`・2026-09-08）**: 作業環境は 1 本 1 時間以内の測定と実装・検査。**それより長いもの（本便ではラダー v9）は Kaggle（4 コア・`--workers 4 --resume --budget-sec 41400`・§4.4 の型）に寄せる。** ただし Kaggle の導入（アカウント・非公開データセット・機械の差の確認＝`COMPUTE_PLAN` §4.1〜4.3）はマスターの作業で、まだ整っていない。**発売（9/12）前に判定を終えるため、§4.4 に「整っていなければ作業環境で回す」条件を置く**（推し。包括方針により採用）。由来ブロックには D-072 の判断 6 のとおり `extra={"host": ..., "workers": ...}` を足す（`champion_challenge_vb.py` / `eval_vb.py` / `probe_d065.py` / `ladder.py` の呼び出し側 4 本。§4.0）。Kaggle で回す前には fingerprint 4 種（`COMPUTE_PLAN` §4.3）を通す。
- **数字には基準・n・95% 信頼区間。** ラダーの Elo は区間つきで、順位は「区別できるか」を添える。
- **判断が要る点は勝手に決めず裁定を仰ぐ**（選択肢と推しは用意する）。
- **成果物は `SendUserFile` → `device_commit_files` でマスターの PC に書き戻す。** `.bin` は持ち帰らない。**ファイルは消さない。** `results/ladder.md` は `ladder.py` が上書きするので、完走後に「この回の読み方」を書き足す（D-065 便 4 と同じ）。
- **旧 champion の登録は消さない。** `planner_vb3cps` はガントレットとアプリに「旧 champion」として残す（`planner_vb3cp`・`planner_vb3` と同じ扱い）。

---

## 2. 便 A（前半）の結果の確認（本便の前提。`LIT_NOTES.md` §A の読み直しは不要）

結果 JSON（`results/vb/d065_lu50.json`・`d065_null_lit_a.json`・`results/lit/a/*`）から数字を組み立て直し、報告と**すべて一致**することを確かめた（門番 0.4892 ±0.0283／対照 0.5242 ±0.0283／対差 −0.035 ±0.023＝79/121/1,000／錨 3 種の対差／詰み見逃し 36/55・34/41・34/40・34/43・20/25・20/22・20/22・14/14／被搾取 32/300・31/300）。

| 事実 | 数値 | 本便への含意 |
|---|---|---|
| `lethal_uniform` は回帰 2 局面を直す | lu50・lu30 とも g001・g002 で烈火。既定（θ=0）は当時の手 | 道具としては成立。ただし V_3 上の測定 |
| `lu50` は D-069(1) の条文を通る | 錨 +0.008 ±0.014／−0.020 ±0.020／−0.025 ±0.030、被搾取 −0.003 ±0.029、門番 0.489 ±0.028 | 条文は通る |
| **対照と対にすると弱い** | 対差 −0.035 [−0.058, −0.012]・0 を含まない。錨は 3 種のうち 2 種（貪欲 −0.020・素planner −0.025）が負、H は +0.008 でわずかに正（`LIT_NOTES.md` §A-3 の 2' にある「3 種すべてが 0 以下」は H の符号と食い違う——報告の本文を直すこと） | **「弱くなっていない」とは言えない。** 便 A の候補は発売前の champion にはならない（判断② 推し A） |
| 費用 +25.8% | 2.694 → 3.388 秒/局（作業環境・比だけ読む） | 見積もり（1 割未満）を外した。行列を毎回埋める構造による |
| A-8 は決着 | `opp_mix=1.0` の素planner −0.092 [−0.141, −0.043]（600 対） | 「広げる場面を絞る」で −0.025 まで縮む。設計思想は正しいが足りない |
| 詰み見逃し 0.700 → 0.857 なのに門番は上がらない | 自己対戦では相手も同じ穴を持つ | **対人でしか価値の出ない直しを自己対戦は検出できない**。便 F（相手の型）の前倒しの根拠。次の便以降 |
| 検査 | `tests/test_lit_a.py` 12 件を含め全部通過。fingerprint 4 種不変。監査 115 件・違反 0 | 便 A の Rust 変更は既定で無害。**マスターの PC の wheel は便 4 のまま**で、アプリ（Python 版）は動く |
| 帯 | 652000..659999 登録済み・`next_free = 660000` | §6 |

**便 A（前半）で残った作業**: 対人局（マスター・§A-8 の依頼）は**まだ打たれていない**（`results/human_games/2026-09.jsonl` は 9/3 のまま）。本便で champion が替わるので、依頼は §8 の形で**新 champion に対して**出し直す。

---

## 3. なぜ今 V_4' か — 根拠と、足りない条件

### 3.1 手元にある根拠（decisions.md D-066・`results/vb/loop2_iter4.json`・帯 530000..533999・Rust・workers=2）

| 条件 | 数値 | 状態 |
|---|---|---|
| 門番（同じ探索器・葉だけ差し替え・n=1,200） | **0.606 ±0.028（下端 0.578・上端 0.633・引き分け 0）** | 越えた。境界ではない |
| 錨 3 種（新旧を同じシードで対にした差・各 600 対） | 素planner −0.003 ±0.047／H −0.002 ±0.025／貪欲 +0.018 ±0.030 | 3 種とも 0 をまたぐ。D-059 の型（前の版にだけ勝つ）は出ていない |
| カナリア（漂泊者（女）Lv2 到達） | 153/200 → 77/200 | 癖の指標。採否に効かせない（D-043） |
| 較正の偏り（D-067） | 直すと弱くなる → 何もしない | V_4' はそのまま使う |

**この門番は D-034 の第 1 条件そのものである**（相手は現 champion と同じ定義: `vb.kwargs_for("SD001", 4, loop=2)` ＝ `champion.kwargs_for("SD001")`。`tests/test_value_bootstrap.py::test_loop2_proxy_pi_is_fixed_across_iterations` が代打ちの一致を、`test_loop2_joins_onto_loop1_v3` が葉の一致を固定している）。ただし当時は由来ブロックが無く（D-2/D-3 より前）、帯は輪 2 の評価帯であって「交代の判定用」の別帯ではない。

### 3.2 足りない条件（本便で埋めるもの）

| D-034 | 何が足りないか | 本便でどう埋めるか |
|---|---|---|
| 1 直接対決（別帯・由来つき） | 別帯での追試が無い（多重比較対策・D-034 裁定 4） | `champion_challenge_vb.py` を帯 660000 で。由来は開始時に入る |
| 対照（配管） | 現 champion 同士の空回しが無い | 同スクリプトが回す（+1300） |
| 2 ラダー core5 で 1 位相当 | 未測定 | v9 に `planner_vc4cps` を足して完走 |
| 3 覗き見監査 0 | V_4' の構成で未実施 | 同スクリプト（`replay_audit`・3 局・node_cap 120） |
| 4 fingerprint | 未記録 | 同スクリプトの digest（6 局）＋ §1 の手順（ミラー 10 局） |
| 5 判断は人 | — | 本書 §0.3 の包括方針のもと、§7 の分岐どおりに進め、**判断が要る点が出たら止めて報告** |
| D-069(2) の改訂 | (ii) V 凍結 → 由来で満たす。(iii) Nash averaging は道具（D-5）が無い → Elo で読み、後で `ladder.json` に遡及適用できることを報告に書く。(iv) 対人局は Wilson/CP → §8 | — |

---

## 4. 手順（この順で）

### 4.0 準備（対局なし・半日）

1. **台帳を取り直し、帯を登録する**（§6）。`next_free` が 660000 でなければ止めて報告。
2. **`champion_challenge_vb.py` の `--budget-sec` を実装する。** いまは引数を受け取るだけで使っていない（`args.budget_sec` が本文に現れない）。docstring は「途中経過を書いて正常終了する。同じコマンドで続きから回る」と約束しているので、その約束どおりにする。型は D-068（`eval_vb.py` の `Budget` / `OutOfBudget` / `.resume.json` / 条件の鍵照合）。鍵は `{deck, challenger_diff or vb, seed0, n, retest}`。**直接対決と対照の両方**を塊に割る。塊に割っても一括と同じ勝ち数・決着数になることを検査で固定する（`test_eval_vb_resume_matches_one_shot` と同じ型。n=6 を一括と 3+3 で比べる）。
3. **判断①**（推し A を、コードの実態に合わせて置く場所を決める）: `value_net` は **`PlannerAgent` だけの引数**で（`meicho/planner.py`・`super().__init__` の後に設定される）、`GreedyAgent` は持たない。したがって `ValueError` は **`PlannerAgent.__init__`**（Python）と **Rust `lib.rs` の `PyPlanner`**（メッセージも揃える）に置く。`GreedyAgent` は「素の評価尺度の上で対抗の規則だけを単体検査する土台」として残し、`lethal_uniform > 0` を許す——ただし **champion 候補にもアプリの相手にもしない**と `decisions.md` に書く。既存の検査で `value_net` 無しの `lethal_uniform > 0` を組み立てているもの（T-A2 の後半＝素の評価器での Python/Rust 一致、T-A4、T-A5/T-A5' の `_StubClash`）は**意図を残したまま**通す: 単体検査は `GreedyAgent` 系のまま、T-A2 の後半は Rust 側も `kind: greedy` の spec に揃えるか、`value_net` を積んだ構成に替える（どちらにしたかを報告）。T-A4 に「`PlannerAgent` で `value_net` 無し × `lethal_uniform > 0` は `ValueError`」を 1 件足す。**判断① は「1 行で済む」ではなかった**ので、変更の一覧を報告に書く。
4. **wheel の札での skip は既に入っている**（`tests/test_lit_a.py::_rs_has_lit_a` が `"lethal_uniform" not in rs.features()` で T-A2・T-A6・T-A9 を skip する。便 D の検査に Rust の新機能を前提にするものは無い）。ここでは**確かめるだけ**: 古い wheel を模した状態（`features()` を monkeypatch）で 3 件が理由つきで skip になることを見る（新設の検査 T-C3）。作業環境では新しい wheel を入れてあるので skip せず通る。
5. **由来ブロックに `host` と `workers` を足す**（D-072 判断 6）: `provenance.block(..., extra={...})` を呼ぶ 4 本（`champion_challenge_vb.py` / `eval_vb.py` / `probe_d065.py` / `ladder.py`）で `extra` に `host`（作業環境は `workenv-2`、Kaggle は `kaggle-cpu-4`。環境変数か引数で渡す）と `workers` を足す。既存の鍵は 1 つも変えない。既存の結果 JSON は読めるまま。
6. 自前 wheel を作り直し、`python -c "import meicho_rs; print(meicho_rs.features())"` に `lethal_uniform` があることを見る。検査を全部回し、通過・失敗・skip の件数と理由を控える。

### 4.1 交代判定（**作業環境**・Rust・帯 660000..・直接対決 約 46 分＋対照 約 46 分。D-072 の「1 本 1 時間」の内側）

```
python3 experiments/champion_challenge_vb.py --deck SD001 --seed0 660000 --n 1200 --workers 2 \
    --challenger-json '{"value_net": "drl_sd001_vc4.json"}' \
    --out results/vb/champion_challenge_vc4.json --budget-sec 480      # 何度でも打ち直す
```

- 直接対決は 660000..661199、対照は 661300..662499、監査は 662600..、fingerprint（digest 6 局）は 660000..660005（スクリプトの OFFSETS）。
- 出てくるもの: 挑戦者の勝率 p ±CI と下端／対照の区間／監査の決定ノード数と違反数／digest。**由来ブロック**に `drl_sd001_vc4.json` と `drl_sd001_vb3.json` の sha256 が入っていることを確かめる。
- **期待**: 下端 > 0.5（D-066 と同じ向き。0.606 前後が出るはず）。対照は区間が 0.5 を含む。監査 0。
- 分岐は §7。

### 4.2 錨

D-066 の錨（新旧を同じシードで対にした差・各 600 対・帯 531300..533299）を**そのまま使う**。3 種とも 0 をまたいでおり、測り直す理由が無い。報告には D-066 の数字を再掲し、「帯 530000 系・由来ブロック無し（D-2 以前）。モデルのファイルは §4.1 の由来と同じ sha256」と注記する。ファイルの sha256 は `experiments/provenance.py` で今から計算して添える（**後づけの由来**であることを明記する。測定の開始時に作ったものではない）。

### 4.3 回帰局面 T-14（Python・対局なし・数分）

`tests/test_d065.py` の `_human_clash_positions()` で g001 T9／g002 T10 を再生し、次の 3 つが何を選ぶかを表にする: (a) 現 champion（V_3・既定）＝当時どおり pass／音の形・回避のはず、(b) **V_4' の版（既定・θ=0）**、(c) **V_4' ＋ `lethal_uniform=0.5`**。

- これは**診断**であり合否ではない。V を替えただけで 2 局面が直るとは考えにくいが、直るなら「詰みの見立てが V で変わった」という別の情報になる。
- (c) が両方で烈火なら、アプリの選べる相手 `planner_vc4cps_lu50`（§4.5）を「候補・未測定」として置く根拠になる。片方でも直らなければ置かない。
- **T-14 の検査（`test_opp_mix_fixes_the_human_positions` と同型の 2 本・`test_lit_a.py::T-A3`）は `champion.kwargs_for` を動的に読んでいる。** 交代すると `want_old`（pass／音の形・回避）が新 champion の選択と食い違って落ちうる。**検査は旧 champion の spec（`webapp.agents.OPPONENTS["planner_vb3cps"]["kwargs"]`）を明示して固定し直し、新 champion の既定の選択は別の検査で「現在の基準値」として記録する**（直したのではないので「直った」と書かない）。

### 4.4 ラダー core5 v9（候補を足す・交代の前に回す・**Kaggle なら約 3 時間、作業環境なら約 5 時間**）

1. `experiments/gauntlets/core5.json` を **v9** にする: `agents` に **`planner_vc4cps`** を足す（`factory: planner_vb`・kwargs は `planner_vb3cps` と同じで `value_net` だけ `drl_sd001_vc4.json`・`n_cap 300`）。**`agents` の先頭に置く**——組は名前の並び順で回るので、新しい 12 組が最初に終わり、早い段階で直接対決の数字が読める。既存の組の向き（a, b）は変わらない。**`champion` 欄は `planner_vb3cps` のまま**（交代前なので）。`description` に v9 の一行を足す。
2. **どこで回すか（D-072）**: **Kaggle が使える状態**（`COMPUTE_PLAN_20260908.md` §4.3 の「機械の差の確認」＝fingerprint 4 種の再現が通っている）なら Kaggle。**9/10（木）の朝までに整っていなければ作業環境で回す**（発売前に判定を終えるため。推し・包括方針により採用）。どちらで回したかを `host` と `workers` つきで報告する（結果はどちらでも同じ。速さだけが違う）。
   - Kaggle（`COMPUTE_PLAN` §4.4 の型・セル 5）:
     ```bash
     %%bash
     cd /kaggle/working/proj/engine
     if [ -d /kaggle/input/prev-run ]; then cp -r /kaggle/input/prev-run/results/. results/; fi
     python3 experiments/ladder.py core5 --engine auto --workers 4 --resume results/ladder_resume_core5.json --budget-sec 41400 --block 50 2>&1 | tee results/kaggle_run.log
     ```
     zip には **v9 の `core5.json`・登録済みの `seed_bands.json`・新しい `ladder.py`（由来の `host`）**を含める。完走したら `results/ladder.json`・`results/ladder.md`・`kaggle_run.log` をマスターの PC の `engine/results/` に置く（正本はマスターの PC）。
   - 作業環境:
     ```
     python3 experiments/ladder.py core5 --workers 2 --engine auto --budget-sec 480 --block 50
     ```
     途中経過は `results/ladder_resume_core5.json`。**1,000 局ごとに定期報告**（1 組 300 局なので 3〜4 組ごと）。
   どちらも、完走すると `results/ladder.json` に追記・`results/ladder.md` を上書きし、途中経過は消える。
3. 読み方: 新 champion 候補の Elo と区間、1 位との差、**非推移性の有無**、`champion 候補` の欄（現 champion `planner_vb3cps` に対する直接対決 n=300 の下端が 0.5 を超えれば候補として出る。n=300 の ±0.055 では 0.606 なら下端 0.55 前後で出る見込み。出なくても §4.1 の n=1,200 が第 1 条件の根拠であり、ラダーの欄は補助）。
4. 完走後、`results/ladder.md` に「この回の読み方（便 E-0）」を書き足す（D-065 便 4 の型: 順位・区間の重なり・3 位以下との差・実装の内訳・所要時間）。

**時間の見積もり**: v8 は 66 組・17,600 局・255 分（46 組 Rust・20 組 Python・2 コア）。v9 は 78 組。足す 12 組のうち 11 組は Rust（champion 級どうしは 300 局で 6〜12 分）、`mcts160` との 1 組は Python（100 局・約 6 分）。**作業環境なら合計 5 時間前後（480 秒の塊で 40 回弱）、Kaggle の 4 コアなら約 3 時間（1 回の実行で終わる見込み）。** Kaggle で回したら実測の速さを `COMPUTE_PLAN` §1.2 の表に「Kaggle 4 コア」の列として足す（§7 の未確認事項）。

### 4.5 交代（§4.1 と §4.4 を通ったときだけ・対局なし・1〜2 時間）

**名前は `planner_vc4cps`。** 中身が変わった（葉の V）ので名前を変える。`planner_vb3cps` は旧 champion として残す。

| 場所 | 変更 |
|---|---|
| `experiments/champion.py` | `CHAMPIONS["SD001"]["value_net"]` を `drl_sd001_vc4.json` に。docstring の表とコメントを本便の根拠（§4.1・§4.4 の数字・「勝ち越したから交代」）に書き換える。旧 champion の段落は「一つ前」に繰り下げる |
| `experiments/gauntlets/core5.json` | **v10**: `champion` 欄を `planner_vc4cps` に。**それ以外は v9 のまま**（組は同一なので測り直さない。`description` に「v10 は champion 欄のみ。ラダーは v9 の記録を参照」と書く） |
| `webapp/agents.py` | `planner_vc4cps` を先頭に登録（表示名に「現champion・2026-09-08 交代・Elo は v9 の値と区間」）。`DEFAULT_OPPONENT = "planner_vc4cps"`。`planner_vb3cps` の表示名を「旧champion（V_3）・Elo 1479」に。`planner_vb3cps_lu50` / `_m100` の表示名の「現champion＋」を「旧champion(V_3)＋」に。§4.3 (c) が両方で烈火なら `planner_vc4cps_lu50`（`lethal_uniform: 0.5`・表示名「現champion＋詰みが見えるときだけ相手を等重みに（θ=0.5・候補・**未測定**）」）を足す。**既定は新 champion。** |
| `experiments/vb.py` | **変更しない。** 輪 2 の探索器は champion と同じで、葉は反復番号で決まる（`kwargs_for("SD001", 5, loop=2)["value_net"] == "drl_sd001_vc4.json"`）。交代後は `champion.kwargs_for("SD001") == vb.kwargs_for("SD001", 5, loop=2)` が成り立つ。**この一致を検査に 1 本足す**（`test_champion_matches_loop2_iteration5`。反復番号を定数で書き、次の交代で意識して動かす） |
| `tests/test_lit_a.py::T-A1`・`tests/test_lit_d.py::test_champion_fingerprint_unchanged_lit_d` | `champion.spec` を動的に読んでいるので、**旧 champion の spec を明示**して `7251a931d252a57a` を固定し続ける検査に直し、**新 champion の fingerprint**（§1 の手順で今回取る値）を固定する検査を 1 本足す |
| `tests/test_d065.py` の T-14 2 本・`tests/test_lit_a.py::T-A3` | §4.3 のとおり旧 champion の spec を明示 |
| `results/ladder.md` | v9 の記録に「この回の読み方」を追記済みであること（§4.4） |
| `decisions.md` | D-073（§9。D-072 は計算資源の計画で使用済み） |

**再ビルドが要らないことの確認**（交代の前に必ず）: (1) 新 champion の spec の鍵は `planner_vb3cps` と同じ集合で、`value_net` の値だけが違う。(2) `drl_sd001_vc4.meta.json` の構造（hidden 256・depth 2・phead 128・init `drl_sd001_vb3.json`）は V_3 と同じで、Rust の読み込み口は D-066 の門番で実際に読んでいる。(3) マスターの PC には `results/models/drl_sd001_vc4.json`（5,848,050 バイト）が既にある。sha256 を §4.1 の由来と突き合わせるため、§8 の依頼に 1 行の確認コマンドを入れる。(4) アプリは Python 版の agent（`registry.make`）で動くので、PC の wheel が便 4 のままでも影響しない。

交代後の**通し確認**: 検査を全部回す（通過・失敗・skip の件数と理由）。`python3 -m webapp.server` を作業環境で起動し、SD001 の新規対局で既定の相手が `planner_vc4cps` と表示され、AI が 1 手打つところまで見る。記録の `agent` 名が新しい名前になっていることも見る。

### 4.6 マスターへの依頼（§8）

交代した場合は §8 の文をそのまま埋めて渡す。交代しなかった場合は、§8 を「現 champion のまま。`planner_vc4cps` は選べる相手として置いた」に読み替え、対人局の依頼は現 champion に対して出す（PRERELEASE_GOAL の一次基準は現 champion との対局であり、**現 champion との対局はまだ 0 局**）。

---

## 5. 検査の一覧（`tests/test_champion_vc4.py` を新設。**本体より先に書く**）

| # | 検査 | 何を固定するか |
|---|---|---|
| T-C1 | `test_challenge_budget_resume_matches_one_shot` | `champion_challenge_vb.py` を n=6 一括と 3+3 で回し、勝ち数・決着数・digest が一致。条件の鍵が違う途中経過は拒否 |
| T-C2 | `test_planner_lethal_uniform_requires_value_net` | `PlannerAgent`（Python）と `PyPlanner`（Rust）で `lethal_uniform > 0` かつ `value_net` 無しは `ValueError`（判断①）。`GreedyAgent` は許す（単体検査の土台） |
| T-C3 | `test_rust_feature_tests_skip_on_old_wheel` | `features()` を monkeypatch して古い wheel を模したとき、`_rs_has_lit_a` を使う検査が理由つきで skip になる（既にある仕組みの確認） |
| T-C4 | `test_old_champion_fingerprint_pinned` | `planner_vb3cps` の spec を**明示**して `7251a931d252a57a`（§1 の手順） |
| T-C5 | `test_new_champion_fingerprint`（交代時） | `planner_vc4cps` の fingerprint（今回取る値）。手順は同じ |
| T-C6 | `test_champion_matches_loop2_iteration5`（交代時） | `champion.kwargs_for("SD001") == vb.kwargs_for("SD001", 5, loop=2)` |
| T-C7 | `test_core5_v10_agents_match_ladder_v9_record`（交代時） | 直近の `results/ladder.json` の記録（v9）の agents（factory・kwargs）と現行 `core5.json` の agents が一致し、差が `champion`・`version`・`description` だけ（組が同一＝ラダーを測り直さない根拠） |
| T-C8 | `test_webapp_default_is_new_champion`（交代時） | `default_for("SD001") == "planner_vc4cps"`、旧 champion と便 A の候補が残っている、`planner_vc4cps_lu50` は置いた場合だけ `build` できる |
| T-C9 | `test_t14_positions_pinned_to_explicit_specs` | T-14 の 2 局面で旧 champion の spec が pass／音の形・回避を選ぶ（§4.3）。新 champion の選択は基準値として記録（合否にしない） |
| T-C10 | `test_seed_bands_vc4_registered` | §6 の帯が台帳にあり、重なりが無い |

既存の検査で**張り替えが要るもの**: `test_lit_a.py::T-A1`・`T-A3`・**T-A7（`test_webapp_candidates_registered_default_unchanged` は `DEFAULT_OPPONENT == "planner_vb3cps"` を直書きしているので、交代で落ちる。「既定は現 champion（`champion.py` と一致）」に書き換える）**、`test_lit_d.py::test_champion_fingerprint_unchanged_lit_d`、`test_d065.py` の T-14 2 本（`test_opp_mix_fixes_the_human_positions`・`test_nash_delta_fixes_the_human_positions`。§4.3・§4.5）。**「直した」と言う前にわざと壊す**（D-065 の教訓）: 交代後に `champion.py` だけ旧に戻して `test_champion_definition_is_consistent_everywhere` と T-C6 が落ちること、`core5.json` の kwargs を 1 文字変えて T-C7 が落ちることを見る。

---

## 6. 帯（`seed_bands.json`・着手時にマスターの PC から取り直し、`next_free` が 660000 であることを確かめてから登録）

| 帯 | kind | 用途 | 内訳 |
|---|---|---|---|
| 660000..665999 | validate | **champion 交代の判定（V_4'・便 E-0）**。`champion_challenge_vb.py --seed0 660000` | 直接対決 660000..661199（n=1,200）／対照 661300..662499（n=1,200）／監査 662600..／追試 663000..665399（n=2,400・境界のときだけ）／予備 665400..665999 |

`next_free` → **666000**。ラダーは 80000..（ラダー専用・登録済み）。T-14 と検査は対局を生まない（fingerprint の seeds 471500..471509 は既存の手順のもの）。**学習に使用禁止**と書く。

---

## 7. 判定の分岐

| 結果 | 次にすること |
|---|---|
| §4.1 下端 > 0.5 かつ 境界でない（\|下端−0.5\| > 0.01）、対照が 0.5 を含む、監査 0 | §4.4 のラダーへ |
| §4.1 下端 > 0.5 だが境界 | `--retest`（n=2,400・663000..）。**`--out results/vb/champion_challenge_vc4_retest.json` と別名にする**（同じ `--out` だと最初の結果を上書きする）。それでも下端 > 0.5 ならラダーへ。2 本を併記し、どちらも消さない |
| §4.1 下端 ≤ 0.5 | **止めて報告。** 帯 530000（0.606・下端 0.578）と食い違うことになるので、両方を併記し「帯によって難易度が違う」以上の推測をしない。champion は据え置き。判断が要る点として出す |
| 対照が 0.5 を外す | 測り方が壊れている。上の数字を読まず、原因（wheel・モデルの解決・シード）を調べて報告 |
| 監査に違反 | 交代しない。違反の例を報告（V を替えただけで違反が出るなら、探索器の側に元からあった問題なので、それ自体が大きな発見である） |
| §4.4 で `planner_vc4cps` が Elo 1 位、または 1 位と区間が重なる、非推移性なし | **交代**（§4.5） |
| §4.4 で 1 位と区間が離れて下、または `planner_vc4cps` を含む 3 巡回が出る | **交代しない。止めて報告。** D-059 の型（門番は通るがラダーで下がる）。門番と錨と食い違う理由の候補（どの相手に負けたか）を勝率行列から抜いて添える |

**交代しても消えない限界を報告に 1 行**: 現在の基準は搾取可能性を測っていない（被搾取の基準値 0.112 ±0.025 は V_3 上の値。新 champion の値は測っていない）。

---

## 8. マスターへの依頼文（対人局・交代した場合・**5 点すべてを省略せずにこのまま使う**。〔 〕は結果で埋める）

> **なぜ今これが要るか**: champion を `planner_vb3cps`（葉 V_3）から `planner_vc4cps`（葉 V_4'）に替えました。自己対戦の直接対決で〔p ±CI・下端〕（n=1,200・帯 660000）、ラダー core5 v9 で〔順位・Elo [区間]〕です。ただし**現 champion との対人局はまだ 0 局**で、一次基準（マスターとの直接対局・PRERELEASE_GOAL）は測れていません。**再ビルドは不要**です（変えたのは Python の定義とモデルの指定だけで、Rust は触っていません。アプリは Python 版で動きます）。
>
> 1. **どこで**: `engine` フォルダ（`C:\Users\...\meicho_engine_v0.1\engine`）。
> 2. **何を打つか**:
>    ```
>    python -c "import hashlib;print(hashlib.sha256(open('results/models/drl_sd001_vc4.json','rb').read()).hexdigest()[:16])"
>    python -m webapp.server
>    ```
>    1 行目はモデルの中身の確認（**〔sha256 先頭 16 桁〕** と出れば、こちらで測ったものと同じファイルです）。2 行目でアプリが起動するので、ブラウザで開き、**SD001 で 3 局・SD02 で 3 局**打ってください。SD001 の既定の相手は `planner_vc4cps`（表示名「…現champion・2026-09-08 交代…」）になっています。相手を選ぶ画面で既定のままにしてください。
> 3. **成功したらどう見えるか**: 1 行目は 16 桁の英数字が 1 行。2 行目は `ブラウザで開く: http://127.0.0.1:8765` と `終了: Ctrl-C` の行が出て止まり、ブラウザが自動で開いて対局画面が出ます（開かなければそのアドレスを手で開いてください）。対局が終わるごとに `results/human_games/2026-09.jsonl` に 1 行増えます。
> 4. **確認のしかた**: 6 局終わったら `results/human_games/2026-09.jsonl` を送ってください。こちらで `human_games_ci.py`（Wilson と Clopper-Pearson）にかけ、負けた対抗の局面を `ai_clash` から抜いて報告します。**負けた対抗があればその手番を覚えておいてほしい**です（AI が詰みを見ていたのに取らなかったのか、見えていなかったのかを分けます）。
> 5. **転びやすいところと症状**: (a) 1 行目の 16 桁が違う → モデルのファイルが別物です。打たずに知らせてください。(b) 相手の一覧に `planner_vc4cps` が無い → `webapp/agents.py` が古いままです。ファイルの更新が届いていないので知らせてください。(c) AI の 1 手が 10 秒以上かかる → Python 版の速さの範囲です。20 秒を超えて止まっているように見えたら、ターミナルのエラーを送ってください。(d) 対人局は**判定ではなく診断**です。n=6 では勝率は決まりません（6 局全敗でも「AI の勝率は 0.459 を上回らない」（Clopper-Pearson 上端 = 1 − 0.025^(1/6)）までしか言えません）。2026-09-03 の 2 局と同じ形の負け——AI が詰みの烈火を持ちながらパスや青で受ける——が出たら、それが次の便の材料です。

交代しなかった場合は、冒頭を「champion は `planner_vb3cps` のままです。〔満たさなかった条件と数字〕」に替え、2 の既定の相手を `planner_vb3cps` に読み替える。

---

## 9. 報告

- **`LIT_NOTES.md` に「便 E-0（2026-09-08）」の章を足す**（便 D・便 A と同じ形: 結論を先に／何をしたか／数字（すべて n と 95% 区間・由来の sha256）／言えること・言えないこと／検査と不変／判断が要る点／帯／成果物／マスターへの依頼）。
- **`decisions.md` に D-073** を書く（D-072 は計算資源の計画・2026-09-08 で使用済み。D-071 の裁定は「D-071 裁定」として既に追記してある）: 「勝ち越したから交代」か「据え置き」か、根拠の数字（直接対決 2 帯の併記・対照・監査・fingerprint 新旧・ラダー v9 の順位と区間・どの機械で回したか）、3 か所の変更、判断① の修正、判断② ③ の閉じ方（V_3 上の問いとして閉じる。`lethal_uniform` の再測定は新 champion の上で別の便）。**D-034 のどちらの基準で交代したかを必ず書く。**
- **`results/ladder.md`** に「この回の読み方（便 E-0）」。
- **`D065_NOTES.md`** の末尾に「反復 4' の成果の交代判定は `LIT_NOTES.md` 便 E-0 と D-073」と 2 行の案内。
- 検査の件数は通過・失敗・skip を理由つきで。
- **1,000 局ごとに定期報告**（直接対決・対照・ラダーのそれぞれで）。
- 最後に「確定した数値」「境界で追試が要るもの」「設計に返す所見（次の便へ）」を分けて書く。

---

## 10. 転びやすいところ（症状 → 意味 → 直し方）

1. **`champion_challenge_vb.py` が 600 秒で落ちる** → `--budget-sec` が未実装のまま回している。§4.0 の 2 を先にやる。
2. **`--challenger-json` の挑戦者が「そんなファイルは無い」で落ちる** → モデル名の解決漏れ。`challenger_spec_json` は `resolve_model` を通すので出ないはずだが、出たら `policy_net` の解決（D-068 の同型）を疑う。
3. **対照（現 champion 同士）が 0.5 を外す** → 席の入れ替え（seed の偶奇）か wheel の食い違い。数字を読まずに原因を調べる。
4. **T-14 の既存検査が落ちる** → `champion.kwargs_for` を動的に読んでいるため、交代で `want_old` と食い違った。§4.3・§4.5 の張り替え。**新 champion の選択に合わせて `want_old` を書き換えてはいけない**（それは「直った」ではない）。
5. **fingerprint の検査が落ちる** → 交代したなら当然変わる。旧 champion の spec を明示した検査に直し、新 champion の値を別に固定する。**交代していないのに変わったら止める。**
6. **`ladder.py` の途中経過が「今の定義と食い違う」と言って止まる** → v8 の途中経過が残っているか、v9 を回している途中で `core5.json` を触った。**ラダーの途中で champion 欄を変えない**（v10 への変更はラダー完走後）。
7. **ラダーの Elo が v8 と数字が違う（旧 12 体の値まで動く）** → Bradley-Terry は一括推定なので、1 体足すと全員の Elo が少し動く。**相対値**として読む（錨 H=1000 は固定）。v8 の値との引き算をしない。
8. **`results/ladder.md` の読み方の節が消えた** → `ladder.py` が上書きする仕様。完走後に書き足す（§4.4 の 4）。
9. **アプリの既定が変わらない** → `DEFAULT_OPPONENT` を変えたのに `default_for` が `available()` の外だと `planner` に落ちる。`decks: ("SD001",)` を忘れていないか。
10. **マスターの PC で検査が落ちたと報告が来る** → 古い wheel（便 4）で新機能の検査が走った。§4.0 の 4 の skip が入っていれば起きない。起きたら skip の抜けを直し、**再ビルドを頼まない**（本便は再ビルド不要が前提）。
11. **判断が要る点が出た** → 止めて報告。推測で先に進まない。

---

## 11. 次の便（予告のみ・本便では作らない）

本便の結果を確認してから 1 通だけ書く。候補は次の 3 つで、**対人局の結果と本便の判定で決める**: (a) 便 E 本体（輪 2 の反復 5' を Kaggle で。交代したなら探索器は不変で葉が V_4' になる）、(b) `lethal_uniform` を新 champion の上で測り直す小さな便（対人局で 9/3 型の負けが再現した場合）、(c) 便 F 前倒し（相手の型: 「対人でしか価値の出ない直しを自己対戦で測れる相手」を作る。便 A の所見が根拠）。
