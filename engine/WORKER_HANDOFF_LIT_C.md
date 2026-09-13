# 作業者セッション間の引き継ぎ — 文献計画 便 C（2026-09-11・**便 C は完了**）

> **これは「作業者チャット → 次の作業者チャット」の引き継ぎであり、クロエが書く
> `HANDOFF_*.md`（引継ぎ役 → 作業者）とは別系統である。**
> **作業の中身の正本は `HANDOFF_20260910_LIT_C.md`**（便 C の指示書）。
> **便 C は交代判定まで終わった。次の便の指示書はまだ無い**（マスターの裁定待ち）。
> このファイルに残っているのは、**次の便でもそのまま効く環境の作り方と落とし穴**である。
> ここに書くのは、そちらにも `TASKS.md` にも `decisions.md` にも収まらない
> **「このセッション固有の文脈」だけ**である。次の作業者は次の順で読む:
>
> 1. `TASKS.md`（接続フォルダ直下・状態の正本。Active の該当行が着手先）
> 2. その便の指示書（クロエが書く `HANDOFF_*.md`）
> 3. このファイルの **§3 環境の作り直し**と **§5 落とし穴**（便が変わっても効く）
> 4. `LIT_NOTES.md` 便 C の章（§C-A の階段の表 → §C-5 交代判定）・`decisions.md` D-077 追記 1〜5
>
> 更新のしかた: **このファイルは 1 本だけを上書きして使う**（版を増やさない）。
> 段が進むたびに「現在地」「次にやること」「落とし穴」を書き換える。

---

## 1. 現在地（2026-09-11）

- champion は **`planner_vc4cps_kheb`**（**2026-09-11 に交代した**・D-081 追記 1）。
  fingerprint **`e82b796960e04c4a`**。一つ前の `planner_vc4cps` は `9b5ad48d2de6a7e0`（不変）。
- **便 C は完了した。** 階段 C-0 → C-1 `known_hand` 残す → C-2 `world_weight` 落とす →
  C-3 `endgame_enum` 残す → C-4 `draw_buckets` 残す → 交代判定は GSPRT の門番に**不合格** →
  **マスターが D-034 改訂 1（p₁ = 0.55）を撤回**（D-081）→ 戻した門番で 5 条件を満たし**交代**。
- **撤回は事後の閾値変更である。** 0.534 を見たあとで閾値を下げているので、この 1 件は
  事後選択である。**記録は「マスターが規則を直したうえで通した」。以後この前例は使わない。**
- 強さ: 別帯 701200 の固定 n=1,200 で **0.542 [0.513, 0.570]**、段 C-4 の帯と合算して
  **0.534 [0.514, 0.554]（n=2,400）＝Elo +23.5**・費用 +17.3%。
- **ラダー core5 の最新の記録は v11**（2026-09-11・3 時間 11 分・使い回し 70 組）。
  新 champion が **Nash の台に単独で乗り nA = 0.0000**、Elo 1542 [1521, 1565] の 1 位
  （2 位 1522 [1500, 1546] と**区間は重なる**）。ガントレット定義は **v12**（`champion` 欄を更新）。
- **マスターの PC では Rust の再ビルドが要る**（下の §9）。アプリは Python だけで動くので
  再ビルド前でも使える。
- 数字は書き写さない。**`python3 experiments/verify_report.py C` の出力が正**（不一致 0）。

## 2. 次にやること

**次の便はまだ決まっていない。** 引継ぎ書 §8 の分岐（便 A 後半か便 E 本体か）を
マスターが裁定するのを待っている（`TASKS.md` の Waiting On）。
先走って対局を回さないこと。

**交代したことで新しく要る仕事が 2 つある**:

1. **マスターの PC の Rust 再ビルド**（§9）。済むまで、PC 側で Rust を使う測定
   （ラダー・門番・fingerprint）は新 champion を回せない。
2. **輪 2 の探索器を champion に揃えるかの裁定。** `vb.py` は変えていないので、
   いま輪 2 は**一つ前の champion** の探索器で回る。便 E 本体に入る前に決めること。

**次に交代判定をするときの手順**（便 C で道具ができている）:

1. `gauntlets/core5.json` に候補を足す（`champion` 欄は据え置き）。
2. GSPRT ＋ 固定 n=1,200 ＋ 対照（現 champion どうし）＋ 覗き見監査 ＋ fingerprint を
   **別帯**で。監査は `python3 experiments/c4_cost_audit.py --cand <名> --audit-seed0 <帯> --skip-cost`。
3. **ラダーは使い回す**——約 2.4 時間で済む（体は減らさない）:

   ```
   python3 experiments/ladder.py core5 --engine auto --workers 2 \
     --budget-sec 3000 --block 20 \
     --reuse-from -1 \
     --reuse-verify "random|H,greedy|planner,planner_pi|planner_pi_r1,\
   planner_lh|planner_vb1,planner_vb3|planner_vb3cps,planner_vc4cps|H,\
   planner_vb3cp|greedy,mcts160|random"
   ```

   **`--reuse-verify` は体ごとに最低 1 組**入れること（上の並びで 13 体すべてを覆う）。
   抜き取り検査が 1 局でも違えば、そこで止まって「使い回しをやめて全部回せ」と言ってくる。
4. 5 条件を満たせば交代。**便 C で実際にやった手順**は次のとおり（4 か所を同時に変える）:
   `experiments/champion.py`（正本の `CHAMPIONS`）／`gauntlets/core5.json`（版を上げて
   `champion` 欄）／`webapp/agents.py`（`DEFAULT_OPPONENT`。**一つ前は一覧に残す**）／
   `experiments/provenance.py`（由来ブロックの表示名の対応表。**忘れると新 champion の由来に
   旧 champion の札が付く**）。そのうえで検査を回し、落ちたものを**読み替える**
   （消さない）。便 C では 10 件落ちて、内訳は「交代の反映漏れ 3・便 C の土台の崩れ 4・
   由来の表示名 2・検査が狭すぎた 1」だった（§6 と `LIT_NOTES.md` §C-6）。
   最後に **5 点セット**で PC の再ビルドを依頼する（§9）。

## 3. 環境の作り直し（※ここがいちばん大事。コンテナは残らない）

このセッションのクラウドコンテナは**次のチャットには残らない**。次の作業者は最初に次をやる。

1. **接続フォルダの許可を取り直す。** 正本はマスターの PC の
   `C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1`。
   `mcp__remote-devices__get_device_info` で `connectedFolders` を確認する。
   **`device_bash` は使えないことがある**（段 C-4 のセッションでは最初から無かった）。
   その場合は `device_stage_files` でコンテナへ持ち込み、コンテナ内で作業し、
   `device_commit_files` で書き戻す。
2. **リポジトリをコンテナへ持ち込む。** `device_stage_files` は **1 回 50 パスまで**なので分割する。
   段 C-4 で実際に要ったものは次のとおり（これを落とすと検査が落ちる）:
   - `engine/meicho/*.py`・`engine/rust/src/*.rs`・`engine/rust/{Cargo.toml,Cargo.lock,pyproject.toml}`
   - `engine/tests/*.py`・`engine/tests/fixtures/*`
   - `engine/experiments/*.py`（全部）・`experiments/seed_bands.json`・`experiments/gauntlets/*.json`
   - **`engine/experiments/datasets/c1_v1.json`**（無いと `test_gendata` が 2 件落ちる）
   - **`engine/scripts/*.py` と `engine/scripts/dist_templates/*`**（無いと `test_dist` が 3 件落ち、
     `test_cards_folder` が**収集の時点で**落ちて全体が止まる）
   - `engine/webapp/*.py` と `engine/webapp/static/*`
   - `engine/decklists/*`・`cards/*`（**png 76 枚を忘れると画像の検査が落ちる**）
   - `engine/results/models/*`（champion のネット 3 本は必須）・`engine/results/lit/*`・
     `engine/results/vb/*`・`engine/results/human_games/*.jsonl`
     （**human_games を忘れると 8 件が「対人の記録が無い環境」で skip になり、
     skip の数が基準線と合わなくなる**）
3. **Rust の wheel を作り直す**（PC の wheel は古い。**PC には戻さない**）:

   ```
   pip install --break-system-packages pytest maturin      # コンテナに入っていない
   cd engine/rust && python3 -m maturin build --release     # 約 35〜50 秒
   python3 -m pip install --force-reinstall --no-deps \
       target/wheels/meicho_rs-0.1.0-cp311-cp311-manylinux_2_34_x86_64.whl --break-system-packages
   python3 -c "import meicho_rs; print(meicho_rs.features())"
   ```

   **`features()` に `draw_buckets` まで出れば段 C-4 の版**である。
4. **検査の基準線を取る**: `cd engine && MEICHO_HOST=cowork-2 python3 -m pytest tests -q`
   → **段 C-4 時点で 666 通過・26 skip・失敗 0**（約 12 分）。
   skip の内訳は torch 無し 25（`test_d065` 16／`test_drl` 3／`test_lit_d` 2／`test_value_bootstrap` 4）と
   データセット未生成 1。**ここが合わなければ持ち込みが欠けている。**
5. 測定を回すときは `export MEICHO_HOST=cowork-2`（由来の host。知らない値は拒否される）。

**揮発したもの**: `/tmp/run_c4.sh`（測定を順に流すシェル）と、コンテナ内の作業コピー。
**残っているもの**: 結果 `.jsonl` / `.json`・文書・コードはすべて PC に書き戻し済み
（一覧は `results/manifest_lit_c.json`）。**費用と監査は `experiments/c4_cost_audit.py` に
残る形で置いた**（段 C-3 で `/tmp` に置いて失った反省）。

## 4. 段 C-4 と交代判定で実際に使ったコマンド

```sh
export MEICHO_HOST=cowork-2
# 被覆率（影のつまみだけ差し替え。対局は現 champion ミラーのまま）
python3 experiments/coverage.py --n 100 --seed0 680400 --known-hand --endgame 64 --buckets \
  --workers 2 --budget-sec 3000 --title "段 C-4 候補 kheb" --out results/lit/c_cov_kheb.json
python3 experiments/coverage.py --mode regression --known-hand --endgame 64 --buckets \
  --out results/lit/c_cov_regression_kheb.json
# 錨 3 種（各 600 対・新旧とも回すので 3,600 局・約 44 分）
python3 experiments/probe_d065.py --cand kheb --seed0 694000 --anchor-offsets litc \
  --n-anchor 600 --skip-gate --workers 2 --block 100 --budget-sec 3000 \
  --out results/vb/c4_kheb_anchor.json
# 門番（GSPRT・約 16 分）と 固定 n=1,200（約 26 分）
python3 experiments/gate_sprt.py --deck SD001 \
  --challenger-json '{"known_hand": true, "endgame_enum": 64, "draw_buckets": 1}' --seed0 696000 \
  --workers 2 --budget-sec 3000 --out results/vb/c4_kheb_gsprt.json \
  --resume results/vb/c4_kheb_gsprt.resume.json
python3 experiments/gate_sprt.py --deck SD001 \
  --challenger-json '{"known_hand": true, "endgame_enum": 64, "draw_buckets": 1}' --mode fixed \
  --n 1200 --seed0 697200 --workers 2 --budget-sec 3000 --out results/vb/c4_kheb_fixedn.json \
  --resume results/vb/c4_kheb_fixedn.resume.json
# 費用と覗き見監査（1 本の道具にまとめた・約 3 分）
python3 experiments/c4_cost_audit.py --cand kheb \
  --cost-seed0 698500 --cost-n 40 --audit-seed0 698600 --workers 2
```

交代判定（別帯 700000..）:

```sh
CJ='{"known_hand": true, "endgame_enum": 64, "draw_buckets": 1}'
python3 experiments/gate_sprt.py --deck SD001 --challenger-json "$CJ" --seed0 700000 \
  --workers 2 --budget-sec 3000 --out results/vb/swap_kheb_gsprt.json \
  --resume results/vb/swap_kheb_gsprt.resume.json                      # 約 52 分（2,280 局）
python3 experiments/gate_sprt.py --deck SD001 --challenger-json "$CJ" --mode fixed --n 1200 \
  --seed0 701200 --workers 2 --budget-sec 3000 --out results/vb/swap_kheb_fixedn.json \
  --resume results/vb/swap_kheb_fixedn.resume.json                     # 約 26 分
python3 experiments/gate_sprt.py --deck SD001 --challenger-json '{}' --mode fixed --n 1200 \
  --seed0 702400 --workers 2 --budget-sec 3000 --out results/vb/swap_null.json \
  --resume results/vb/swap_null.resume.json                            # 対照・約 24 分
python3 experiments/c4_cost_audit.py --cand kheb --audit-seed0 703600 \
  --cost-seed0 703700 --skip-cost --prefix swap_kheb                   # 監査・約 1.5 分
```

fingerprint は `tests/test_champion_vc4.py` の `_fingerprint` と同じ手順
（Rust・同型ミラー 10 局・seeds 471500..471509・workers=2・digest 列の sha256 先頭 16 桁）。

**回し方**: コンテナは **2 コア**（Rust の自己対戦で約 1.2 秒/局・workers=2 固定）。
1 本が 3,500 秒を超えるので、`timeout 3500 … && break` の `for` ループを
`setsid nohup bash script.sh > log 2>&1 < /dev/null & disown` で流し、
`--budget-sec 3000` と `--resume` で再開させる。**段 C-4 の実測は
被覆率 12 分／錨 44 分／GSPRT 16 分／固定 n 26 分／費用・監査 3 分。**

## 5. 落とし穴（このセッションで実際に踏んだもの）

1. **`pytest` は `python3 -m pytest` で呼ぶ。** `/root/.local/bin/pytest` は別の Python を指している。
2. **Bash ツールの既定タイムアウトは 120 秒。** 長い待ちは `timeout` パラメータ（最大 600,000 ミリ秒）を渡す。
   **ツール呼び出しがタイムアウトすると、そのシェルの子プロセスも道連れになる**ので、
   長い測定は必ず `setsid nohup … & disown` で切り離す。
3. **`device_list_dir` を `recursive` で使わない。** `engine/rust` は `target/` があるので特に大きく、
   出力が 79,000 文字を超えて失敗した。成果物の所在は `results/manifest_lit_c.json` を見る。
4. **`replay_audit(node_cap=…)` は「1 局あたり」ではなく「全局の合計」の上限。**
   段 C-1〜C-3 と同じ 120 件にするには `n_games=6, variants=2, node_cap=120`。
5. **マスター（と便 K の作業者）は同じ時間帯に `decisions.md` / `TASKS.md` を編集している。**
   段 C-4 の書き戻し直前に **D-079（便 K 段 K-0）** が `decisions.md` に入り、`TASKS.md` も伸びていた。
   **書き戻す前に必ず `device_list_dir` か `device_stage_files` の `mtimeMs` を見比べ、
   変わっていたら再ステージして自分の追記を当て直す**（今回そうした。force はしない）。
6. **`resolved_kwargs()` は `opp_decklist` を含まない。** `endgame_enum` は
   `opp_decklist` と組でしか使えないので、`PlannerAgent` を直に作る道具では自分で足す
   （`c4_cost_audit.py` で実際に落ちた）。`arena_rs.PLANNER(pool, **kw)` の道は別で、こちらは pool が先頭引数。
7. **`_determinize` を差し替えた検査用の子クラスがいる**（`test_lit_a.py` の `_StubClash`）。
   引数を増やすと**既存の検査が落ちる**。**既存の検査は 1 件も動かさない**規約なので、
   増やした引数は**つまみが立っているときだけ渡す**形にした（`_worlds` の分岐）。
8. **Python の `sorted` はカード ID の文字列順。Rust では `db.action_rank` で同じ順序を作る。**
9. **`rng.choice(cand)` は Rust の `choice_index` と同じ実装**（`_randbelow`）。
   層の中から 1 枚選ぶところはこれで一致する。`sample` を使うと消費が変わるので使わない。

10. **`_load_resume` はガントレットの hash で守られている。** 候補を足すと hash が変わるので、
    **v9 の組を途中経過のファイルに流し込むことはできない**（そういう事故を防ぐ仕掛けである）。
    使い回しは `--reuse-from` という**別の口**を通す——拾う条件が違う（体の定義の一致）からで、
    途中経過の仕掛けに相乗りさせてはいけない。
11. **ラダーの組の費用は「片席の費用の足し算」では見積もれない。** 弱い相手との組は
    対局が短く終わるので安くなる。見積もるなら**組ごとに少数局だけ実測する**（78 組で約 8 分）。
12. **`--reuse-verify` に指定した組は使い回されない**（わざと回し直すため）。
    抜き取り検査をたくさん入れるほど節約が減るので、**体ごとに 1 組・いちばん安い相手で**選ぶ。

## 6. このセッションで撤回した結論（次チャットが古い値を拾わないように）

1. **「つまみ 1 は山札の並びだけを変える」は誤り。** 乱数は 1 本の流れなので、
   `stratify_top` が引いたぶん**以降の引き（相手の手札の抽選）もずれる**。
   既定不変の約束は「**つまみ 0 のとき**」にしかかからない。検査 T-C-13 はこの形に直してある。
2. **段 C-3 の引き継ぎに書いた「錨 75 分」は過大。** 段 C-4 の実測は 44 分だった（同じ 3,600 局）。
3. **「段の門番に合格した＝交代に足る」は誤り。** 階段の 3 段が合格した候補が、
   別帯の交代判定では不合格側に止まった（§C-5）。**同じ比較を段ごとに検定するのは多重検定**で、
   真の値が p₀ と p₁ の中間（今回 0.534）にあると帯によってどちらにも転ぶ。
   段の門番は「その段で悪くなっていないか」の関門であって、強さの証拠ではない。
4. **「ラダー v10」という呼び名は誤り。** v10 は champion 欄だけ変えた版（ラダー未実施）で、
   候補を足した定義は **v11**、交代で `champion` 欄を更新した定義が **v12** である。
   **ラダーの最新の記録は v11**（2026-09-11 に回した）。
5. **「交代しない」は覆った**（2026-09-11 同日）。§C-5 の結論を読むときは、
   その上の註（マスターが D-034 改訂 1 を撤回した）を必ず一緒に読むこと。
   **測った数字は 1 つも変わっていない。変わったのは関門のほうである。**
6. **「PC の Rust 再ビルドは要らない」も覆った。** 交代したので要る（§9）。

## 7. 保留・未解決（判断待ちであって、手つかずではない）

- **判断が要る点は合計 31 件**（うち 28 番は**マスター裁定で推しが採られなかった**——
  閾値は撤回され、交代した。29〜31 は交代の作業で新しく出たもの）。
  **すべて推しで進めてある**（包括方針 D-069）。一覧は `TASKS.md` の Waiting On と
  `LIT_NOTES.md` §C-D。**マスターの異議が来たら戻す**。
- **交代判定は済んだ**（2026-09-11・**交代した**）。ラダーは `--reuse-from` で
  3 時間強に縮んだので、**この件で Kaggle は要らなくなった**（要るのは便 E 本体だけ）。
- **未決: 輪 2 の探索器を champion に揃えるか**（`vb.py` は変えていない）。便 E 本体の前に。
- 測っていないもの: 「上位 3 枚」の枚数と層の切り方の掃引（§C-D の 19）、
  **段ごとの寄与**（§C-D の 17・23）、`endgame_eval` を 64 に上げた場合（12）、
  投票の寄与の分離（15）、**ラダー v11**（24）。どれも計画を変えないので便 C では回していない。

## 8. 触ってはいけないもの（便 C を通しての約束）

- **`webapp/` は交代のとき以外触らない。** 例外は「選べる相手に候補を 1 行足す」だけで、既定は変えない。
  （2026-09-11 の交代で既定を変えたのは、**交代そのもの**という例外にあたる。）
- **`experiments/vb.py`・`cards/`・`decklists/` は触らない。**
  `gauntlets/core5.json` と `experiments/champion.py` も**交代のとき以外は触らない**。
  **`cards/` は便 K の作業者が同時に触っている**（D-079 で 166 レコードに更新済み）。
  便 C 側から `cards/` と `meicho/cards.py` に手を出すと衝突するので、絶対に触らない。
- **マスターの PC の Rust 再ビルドは champion が交代したときだけ**（依頼は `REPORTING_RULES.md` §2.6 の 5 点セット）。
  Linux の wheel は PC に戻さない。`.bin` は持ち帰らない。**ファイルは消さない。**
- 覗き見禁止（D-026）: `hand_known` は `observe(s, pi)["opp"]["hand_known"]` からだけ読む。
  探索側は `s.peeked_opp_hand` にも相手の真の手札にも触れない。候補は必ず覗き見監査を通す。

## 9. PC でやってもらうこと — Rust の再ビルド（`REPORTING_RULES.md` §2.6 の 5 点）

**なぜ今それが要るのか**: champion が `planner_vc4cps_kheb` に交代し、この体は
`draw_buckets`（便 C 段 C-4 で Rust に足したつまみ）を使う。`.pyd` はソースと一緒に
配られないので、**PC に入っている wheel が古いままだと Rust 側で新 champion を作れない**
（`ValueError` になるか、検査が「Rust が便 C 段 C-4 より古い」と skip する）。
**対人検証アプリ（`webapp/`）は Python だけで動くので、再ビルド前でも今までどおり使える。**

1. **どこで**: `engine\rust`（`meicho_engine_v0.1\engine\rust`）
2. **何を打つか**（1 行ずつ）:

   ```
   cd engine\rust
   maturin build --release --out dist
   pip install --force-reinstall dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
   ```

   （ファイル名の `cp311` は Python の版で変わる。`dist` に出来たものをそのまま指定すること。）
3. **成功したらどう見えるか**: `maturin` の最後に
   `📦 Built wheel for CPython 3.11 to dist\meicho_rs-...whl`、
   `pip` の最後に `Successfully installed meicho_rs-0.1.0`。
4. **確認のしかた**（`engine` に戻ってから）:

   ```
   cd ..
   python -c "import meicho_rs; print(meicho_rs.features())"
   python -m pytest tests/test_lit_c.py -q
   ```

   期待: `features()` の一覧に **`draw_buckets` が入っている**こと。
   検査は **skip 0 で全部通る**こと（古い wheel だと「Rust が便 C 段 C-4 より古い」で skip になる）。
5. **転びやすいところと、その症状**:
   - `maturin` が無い → `pip install maturin`。
   - **`dist` ではなく `target\wheels` を見てしまう**（過去に実際に起きた）。
     `--out dist` を付けているので**出来上がりは `dist`** にある。
   - `pip install` を**古い wheel の上から**やると入れ替わらないことがある。
     `--force-reinstall` を付けてある。
   - ビルドは通ったのに `features()` に `draw_buckets` が無い → **別の Python に入った**。
     `python -c "import sys; print(sys.executable)"` で、検査を回すのと同じ Python か確かめる。
   - 「rustup が無い」と出たら Rust の導入から（`https://rustup.rs`）。
