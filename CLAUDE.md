# Memory

> **最初に `STEER.md` を読む。**リポジトリ直下に `AGENT_STOP` が在れば新しい塊に入らず、状態を commit・push して終える（`engine/AUTONOMY_20260929.md` §3）。
> **未着手の作業は `TASKS.md` に一元化してある。**現在地を知りたいときは次にそこを読む。`engine/` の文書は記録（数字・判断の理由）、`TASKS.md` は状態（いま何をするか）。
> **2 つのチャット（エンジン／オンライン対戦アプリ）が並行している。**`LANES.md` を読む。1 つのファイルの書き手は 1 つの持ち場だけ。このファイルはエンジンの持ち場が書く。
> **正本は GitHub の `main`**（D-136）。PC のフォルダは作業ツリー（`C:\dev\meicho_engine_v0.1`）。push は Claude Code（PC）が行う。クラウドの Claude Code はブランチに push し、`results/` と報告書だけなら `main` へ早送りでよい（D-137）。

## Me
オクソン（マスター）。TCG『鳴潮：対決』の解析エンジン `meicho_engine` を個人開発。Claude（クロエ・Cowork）を設計の相談役・裁定が要る文書の書き手として使い、実装・測定・commit は Claude Code（PC・クラウド）が行う（D-137）。2026-10 以降、指示が出せるのは昼食時と夜だけ。

## People
| Who | Role |
|-----|------|
| **マスター** | オクソン本人。裁定者。提案は原則すべて推しを採用（D-069）。対人局の相手役でもある。途中の方針は `STEER.md` に書く |
| **クロエ（Cowork）** | 裁定が要る設計書・計画書・規約・引継ぎ書・比較書を書く。読みは GitHub から、書きは接続フォルダへ。台帳は Claude Code が書く |
| **Claude Code（PC）** | エンジンの実装・検査・Rust の再ビルドと指紋の確認・短い測定・**commit と push の役** |
| **Claude Code（クラウド・`cc-cloud-4`）** | 1 時間を超える測定・ラダー・門番。塊は 10 分以内・塊ごとに push |
| **採点役 `reviewer`** | `.claude/agents/reviewer.md`。区切りごとに呼ぶ。編集権限なし。`PASS`／`NEEDS_WORK` と、正しさと要件に効く指摘だけを返す。2 回 NEEDS_WORK なら止めてマスターに返す（`AUTONOMY` §2） |

（2026-09-15 まで別セッションの作業者 Codex が実装していた。止まっている。`WORKER_HANDOFF_*` 系統は読まなくてよい）

## Terms
| Term | Meaning |
|------|---------|
| 便 | 引継ぎ書 1 通ぶんの作業単位。1 便で変える探索器の要素は 1 つ |
| champion | そのカードプールでいちばん強い AI。正本 `experiments/champion.py`。現在 **`planner_vc4cps_kheb_b75`**（SD001・2026-09-13 交代・D-082 追記 2。以後交代していない） |
| fingerprint | 既定の打ち方が不変であることの指紋（4 種）。**champion は `f4b80b25c35cfa77`**。歴代は `check_champion_fingerprint.py` の `EXPECTED`。**指紋は打ち方を変えなくても動く**（決定列に選択が増える・ルールが変わるだけで動く・D-091 §3／D-104） |
| 門番 | champion 交代の直接対決。**n≥300 で勝率の 95% 下端 > 0.5**（D-081）。GSPRT は診断として残す（「越えたか」だけ・大きさは固定 n で測る） |
| 錨 | 第三者（H・貪欲・素 planner）との勝率。候補が別のところで弱くなっていないかの確認 |
| 帯 | シード帯。`experiments/seed_bands.json` に**登録してから**使う。現在値は `next_free` を読む。`kind`（train／validate／diag など）を用途と合わせ、学習に使った帯で評価しない |
| 対照 / null | 同じ AI どうしを同じ帯で回した基準。0.5 を含めば配線は健全 |
| T-14 | 回帰局面の検査（対人局で AI が詰みを逃した対抗）。候補の最初の関門 |
| 対抗 | 対抗ステップ（互いに伏せてカードを出す同時手番） |
| 詰み表 / 天井 / lc / D_t | 後知恵の勝敗表／手札が全部見えたときの上限 +77.1 Elo [+57.2, +97.5]（D-076）／葉の相関 0.105／曖昧さ解消率（中盤の中央値 0.095） |
| rules 版 | `engine/rules_draft.md` の版。**現在 v0.19**。**実装より先に版を上げ、`meicho/version.py` の `RULES_VERSION` も同時に上げる**（番人 `tests/test_versions.py`・D-117）。経緯は decisions.md |
| 符号化 | 観測・行動の符号化の版。**現在 v6**（D-124）。`meicho_rs.encoding_info()` = `(ENCODING_VERSION, OBS_DIM, ACT_DIM)` = **`(6, 1923, 317)`**（v5 の 1,825 列の末尾に信念の要約 20＋`hand_known` 78）、`ACT_CODE_LEN` 13。**`load_cards()` を先に呼ばないと `RuntimeError`** |
| A-n / B-n / R-n | 公式ルールと実装の差異の番号と、その裁定の番号（`engine/official_rules/OFFICIAL_RULE_RECHECK_20260917.md`・D-092）。12 件すべて閉じた |
| D-番号 | `engine/decisions.md` の設計判断の番号。**正本は `decisions.md` の末尾**（最新 D-170・次に使えるのは D-171）。**振るのはエンジンの持ち場だけ**（`LANES.md` §3）。アプリの決定は APP-番号で `engine/app/DECISIONS_APP.md` |
| SD001 / SD02 | カードプール（構築済みデッキ）。学習した AI があるのは SD001 のみ |
| V / π₀ / 代打ち π | 葉の価値関数／相手モデルの方策／先読み中の代打ち方策 |
| 塊 | クラウドの Claude Code の実行単位。10 分以内・塊ごとに push（D-137） |

## Projects（動いている線だけ。閉じた線は decisions.md と TASKS.md の Done）
| Name | What |
|------|------|
| **汎用 AI（段階3 → 段階4）** | 設計書 `engine/GENERALIST_STAGE3_DESIGN.md`（D-138）。反復 1 は V_1 を採らず止めた（D-144）。診断（案 M・`engine/GENERALIST_STAGE3_DIAG_COMPARE_20260929.md`・道具 D-145）は**項目 3（教師の較正）で説明できた**（D-146）。直し方の設計書 `engine/GENERALIST_STAGE3_TEACHER_FIX_DESIGN_20260930.md`（D-148）で (a)〜(c) を試したが**直らなかった**（(a) 相談で回さず・(b) 門 T-b で回さず・(c) V_c − V_0 = −0.125・D-149・D-150）。項目 4（探索の分布・D-151）は 4-a が「説明できない」（葉 ÷ 根のばらつき比 R_T = 0.965・D-152）。項目 5（容量）も 5-a で「説明できない」（D-153）。診断の 5 項目を回し終え、**段階3 は閉じた。V_0（`s2v_id_ens3`）を汎用 V として段階4 へ**（D-153 追記 1）。段階4 の設計書 `engine/GENERALIST_STAGE4_DESIGN_20261001.md` を採った（D-154）。便 4-A は P2（G − R）だけ通り、P1（G − S）は区別できなかった（D-155）。便 4-A2（D-156）は、問い 1「教材の天井ではない」（S は 3,000 局でまだ伸びる）・問い 2「汎用の出発点の優位は別の調整デッキでも出る」（D-157）。便 4-A3（G 側の学び方・D-158）は、判定 1「G@3,000 − G@0 は決まらない」・判定 2「同じ 3,000 局で S が G より強い（負の転移の疑い）」（D-159）。段 2 の学び方の腕（G-lr・G-frz）はどちらも通らなかった（D-160）。便 4-A4（教師を強くする線）の設計書 `engine/GENERALIST_STAGE4_TEACHER_DESIGN_20261005.md` を採った（D-161・Rust に `agents_follow_decks` を既定オフで足す）。判定 1 P_T・判定 2 E_T とも「区別できない」（D-162）。教材を増やす線（W 系）も止めた。**壁を越える案 `engine/GENERALIST_WALL_DESIGN_20261006.md` の 3 本の腕（A 代打ち π・B 実際の続きの目標・C 補助の目標）を回す（D-163）**。主比較は直接対決＋null、錨は素 planner・H・貪欲。進め方は D-164（推しは既定で進む・必ず止まる 7 種）。**腕 B は「伸びていない」**（V_B − V_0 = −0.009 [−0.058, +0.038]・D-165）。**腕 A も閉じた**（A-1 は追試で −0.006 [−0.033, +0.021]・A-2 の u_A = −0.0029 で門を越えない・D-166・D-167）。**腕 C も追試で伸びていない**（+0.007 [−0.026, +0.040]・D-168）。**3 本とも伸びたとは言えない**（区別できない）。**マスター裁定で、上端が +0.02 を上回るうちは追試を足し継ぐ（D-169）**。**物差しを直接の得点（挑戦 − 0.5・2,800 局で +3% を見つける・null は配線の確かめ）に替えた（D-170）**。V_1・G-lr・G@12,000 を測り直す。**最終評価の 4 デッキ（SK 系）はまだ開けない** |
| **環境デッキ群とデッキ類似度** | 設計書 `engine/DECK_SIMILARITY_DESIGN.md`（D-126）。環境デッキ 24 種 `decklists/env/`（D-128）。割り振りは学習 16・調整 4・最終評価 4（`results/decksim/env_v1_split.json`） |
| **開発の流れ（devflow）** | `engine/DEVFLOW_PLAN_20260925.md`（D-136・D-137）。段 6 進行盤 `engine/board/`（`PROGRESS_BOARD_DESIGN_20260929.md`・1 日 3 回の定期実行が db に写す） |
| **自走化の規約** | `engine/AUTONOMY_20260929.md`（D-147 で採用）。採点役・`STEER.md`・脱線の兆候・`check_done.py`（Stop hook・まず測定の便・**未実装**＝PC の Claude Code が作る） |
| **オンライン対戦アプリ（アプリの持ち場）** | 別のチャットと Claude Code が開発（D-108・APP-027）。台帳 `engine/app/TASKS_APP.md`・決定 `engine/app/DECISIONS_APP.md`・頼みごと `engine/app/TO_ENGINE.md`（こちらからは `engine/TO_APP.md`）。**エンジン本体はエンジンの持ち場が実装する**（`LANES.md` §6） |
| **配布版** | 知人向け Windows 実行ファイル（D-074）。`scripts/make_dist.py` の `verify` が**公式素材（`■【` の印）を配らないための番人**（D-098 §2(a)） |
| **対人検証アプリ** | `engine/webapp/`。記録は `engine/results/human_games/2026-09.jsonl`。`app_version < 2` の記録は `is_legacy_stage1a()` で補完（D-098 §2(b)）。引退の条件は未定（D-126） |
| **BP01 のカードデータ** | `cards/cards_official_20260910.json`（D-078・`adopted_effect` / `adopted_name` があればそちら）。画像は `cards/` 直下の 123 枚（手動スクショ・D-084）。**`cards/` は git の外・公式素材は配らない** |

閉じた線（正本の場所だけ）: 文献活用計画（`LITERATURE_PLAN_20260906.md`・便 A 後半 D-082 で閉）／公式ルール線（差異 12 件すべて閉・D-092〜D-104。**A-2・A-6 で SD001/SD02 の対局が変わった＝便 A〜C の勝率は旧エンジンの測定で、champion 交代の根拠に使わない**（D-095）／段階1A・1B（D-088〜D-091・控え `results/models/*.enc4.bak.json` は消さない）／カード線 便 K（D-083・D-085）。

## Preferences
- 返事は簡潔・表なし（モバイル）。数字は基準・n・95% 区間つき
- 引継ぎ書は 1 便ずつ。前の便の結果を確認してから次を書く。計画は変えない
- 提案はすべて推しを採用（包括方針 D-069）。判断が要る点は推測で埋めず列挙する
- 1,000 局ごとの定期報告。手を動かしてもらう依頼は手順を省略しない（5 点セット）
- 正本は `engine/` の文書（rules_draft.md・decisions.md・各 NOTES）。詳しくは `memory/`

---
## 踏みやすい罠（毎回ここで転ぶ）
- **push を忘れると、クラウドの Claude Code も GitHub から読むクロエも進行盤も古い版を見る。**作業の終わりに `git status` が空で `Push origin` に数字が無いことを見る（D-136）
- **終わりは `engine/scripts/check_done.py` が通ること。**「終わった」の宣言ではなく証拠（帯の登録・区間つきの数字・実行したコマンドの在り処・採点役の出力）で決まる（`AUTONOMY` §6）。**`check_done.py` は PC の Claude Code が実装する（D-147）。それまでは同じ項目を手で確かめる**
- **脱線の兆候 4 つを見たら、直さずに止めて `STEER.md` を読み直し、台帳に 1 行書く**——同じ直しの繰り返し／頼んでいない機能／検査の無効化／**帯・局数・対照・判定の規則の無断変更**（`AUTONOMY` §5）
- **書き戻したファイルは必ず再ステージしてバイト比較する。**「written」は載ったことを意味しない（2026-09-20 に 6 回中 3 回載らなかった・`PARALLEL_WORK_REVIEW_20260920.md` §2）。台帳類は `engine/WRITELOG_ENGINE.md` に控えを残す（`LANES.md` §5）
- **依頼書で出力をファイルに流す（`> x.txt 2>&1`）なら「画面には何も出ない」と先に書く**（D-116）
- **`python scripts\xxx.py` の形で起動すると `meicho` が見つからない。**`engine` で `set PYTHONPATH=%CD%` を先に 1 回打つ。コンソールを開き直したら打ち直す
- **D 番号は別セッションと衝突する。**書く前に `git pull` して `main` の `decisions.md` の末尾を必ず見る（2026-09-11 に衝突した）。**台帳（decisions.md・TASKS.md）を書くのは同時に 1 人**（D-137）。振るのはエンジンの持ち場だけ（`LANES.md` §3）
- **skip は「通った」ではない。**作業環境で常に skip になる検査が PC で初めて落ちることがある
- **「基準が通った」は「その基準が変更点を踏んだ」を意味しない。**通った帯がその変更を一度も踏んでいないだけかもしれない（D-097・D-098 §5）
- **判定を写して 2 箇所に書くと、写した側だけが取り残される**（D-098 §5・D-075）
- **経路も判定である。**同じ 1 行を 4 か所に書いたら、いつか 1 か所が抜ける（`scripts/` を `sys.path` に入れる行・D-105）。**全検査が緑でも、名指しで回すと落ちる**——検査どうしが import の副作用で支え合っていることがある
- **★失敗一覧は数えるものではなく読むものである。**「資材が無いから」は仮説であって、1 件ずつ理由を見るまで結論ではない。**失敗が多い環境ほど本物の失敗が隠れる**（D-106 §3）
- **ルールを覆したら、覆した前提に寄りかかっている検査を『名前ではなく挙動で』探す。**A-6 では `grep MAX_LIFE` で探したため、`MAX_LIFE` を使わず「満タンから回復する」状況で同じ前提に乗っていた検査を取りこぼした（D-106 §6）
- **★`device_commit_files` が拒否したら、書き直すときは別の名前の `stagedPath` を使う**（D-127）。同じ `stagedPath` だと、拒否された回の中身が書かれることがある
- **★`device_stage_files` は `/mnt/user-data/uploads/…` の作業用の写しを PC の中身で上書きする**（D-128）。台帳を再ステージした瞬間に、まだ書き戻していない自分の直しが消える。**再ステージの前に、自分が直したファイルの控えを別の場所に取る**
- **★書き戻す前に元の改行コードを確かめる**（D-128）。PC では `decisions.md`・`TASKS.md`・`WRITELOG_ENGINE.md` が **CRLF**、`CLAUDE.md`・設計書・`.py`・`.json` が **LF** である。**CRLF のファイルは sed で触らない**（2026-09-27 に LF に化けた）。Edit か、CRLF を保つ道具で直す
- **★検査の回し方（D-125）**: 作業環境では毎便 `python3 -m pytest tests -q -rfs --run-slow`（約 40 分・既定は重い 20 件を飛ばして約 7 分）。PC への依頼は `python -m pytest tests --pc -q -rs`（PC にしか無い資材の検査と Windows の部品の検査だけ）。検査を足したら `--junitxml` の結果から `scripts/make_test_sets.py` で組を作り直す。**作業環境で `--run-slow` を回さなかった便は完了扱いにしない**
- **★符号化 v6（D-124）の信念の要約は `encode(ob, pi, opp_decklist)` の第 3 引数が無いと 0 になる**。葉の V（`PlannerAgent._eval`・Rust `Greedy::net_value`）と記録（`series_record`）は自分の `opp_decklist` を渡す。**方策ネット（代打ち・π₀・PolicyAgent）は渡していない**——π を v6 の記録で学ぶなら、使う側の口も揃えること
- **★違うデッキ同士の対局で `rs.series` 系を使うときは `opp_from_seat=True`**（D-123）。奇数シードで A/B の席が入れ替わるがデッキは席に固定なので、既定（False）では**半分の局で相手デッキ表が誤る**。段階2 の教材は `experiments/record_mix.py`（常に True）で作る
- **★`hand_known` と `hand_known_scan` は別物**（D-122）。`hand_known` は統一した確かな既知（汎用 AI・画面・監査が読む）、`hand_known_scan` は旧来のスキャン・B-9 のぶんで**現 champion と符号化 v5 だけが読む**。champion の既知を検査するときは `hand_known_scan` を見る
- **日本語 Windows の cp932 で道具が落ちることがある**（`π₀` の `₀` は cp932 で書けない・D-082 追記 1）
