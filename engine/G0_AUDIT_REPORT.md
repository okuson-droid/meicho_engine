# 段階0報告 — 汎用化の前提監査と測定設計

更新日: 2026-09-14  
対象コミット: `c76f968cf61c48cdc2dc935f2f584d65e73b9c86` (`main`)  
準拠: rules_draft v0.12 / engine v0.1 / encoding v4 (`N_SCALAR=62`, `OBS_DIM=1313`, `ACT_DIM=226`)  
現 champion: `planner_vc4cps_kheb_b75`（SD001、fingerprint `e1662edb32b144a9`）

## 0. 結論

段階1へ進む前に、**選べない手と、公開されているのにネットへ入っていない状態を一度に棚卸しして、符号化 v5 の範囲を固定する必要がある。** 特に、K-4 の回収札、K-3 の公開領域の対象、協奏から払う札は戦略的な意味が大きい。入力側はBP01の追加状態だけでなく、自分のキャラデッキの中身、積まれたキャラの下層、直近の対抗カード、選択の条件値が欠けている。

既存の記録入口 `drl_record.py` は `mirror_config` 固定であり、異なるデッキ同士を記録できない。さらにGitHubの対象コミットには `results/drl/`、`results/vb/`、`results/datasets/` の生記録・manifestが無い。そのため、既存記録の**形式上の利用範囲**は判定できるが、PCにある個々のファイルを完全教材として認定することはできない。

当初は非公開GitHubの認証をシェルへ渡せずcloneできなかったが、マスターがリポジトリを公開へ変更した後、HEAD `66fe9ddbab6c94476386894300e03d14cdf4c7e1`をローカルに展開できた。Python fingerprint 3種と全検査を実行した。400局の速度下見は、Git管理外のモデルJSONとLinux用`meicho_rs`が無いため**未実施**である。帯も予約していない。

この便ではコード、Rust、符号化、モデル、champion、`TASKS.md`、`seed_bands.json`を変更していない。強さの結論も出していない。

## 1. 成果物1 — 合法にすべき選択

### 1.1 優先度A: 段階1で選択肢化する推し

1. **通常のコスト支払いで、協奏エリアのどの札を払うか**
   - 場所: `engine.py::_pay_cost`。現在は左端から自動でトラッシュへ送る。
   - 起きる局面: 対抗、連撃、`pay_or_damage`、`pay_cost_return_self_to_hand`。
   - 意味: 協奏に残した札は後の支払い資源であり、＜音骸＞の種類数や常在効果の成立にも関わる。単なる同価値の支払いではない。
   - v5案: `CHOICE_KINDS` に `pay_cost_card` を1種追加し、1枚ずつ選ぶ。行動は汎用の `choose_card` を追加して既存のaction-card欄を使う。
   - 寸法: `N_SCALAR +1`、`ACTION_TYPES +1`なので `ACT_DIM +1`。複数枚支払いは同じ選択を反復する。

2. **K-3: 相手の協奏エリアからトラッシュへ送る札**
   - 場所: `opp_concerto_to_trash`。現在は相手協奏の左端。
   - 選ぶ人: 効果のオーナー（u8）。対象は公開領域。
   - 意味: 相手の色・専用札・＜音骸＞の組を崩す選択になる。

3. **K-3: 相手のトラッシュからデッキ下へ置く札と「N枚まで」の枚数**
   - 場所: `opp_trash_to_deck_bottom`。現在は最大枚数を古い順に取る。
   - 意味: 相手が再利用しそうな札を遠ざける一方、山札再構成後の内容も変える。0枚を含む「まで」も意思決定である。

4. **K-4: 自分のトラッシュから手札へ回収する札**
   - 場所: `trash_to_hand` / `trash_to_hand_if_switched`。現在は条件に合う左端。
   - 意味: 即時の手札強度に直結し、引継ぎ書の指摘どおり最優先である。

5. **K-4: 自分のトラッシュから協奏へ置く札**
   - 場所: `trash_to_concerto`。現在は条件に合う左端。
   - 意味: 支払い資源、色・専用札、＜音骸＞の常在条件を選ぶ。

2〜5は公開領域のカード選択なので、1つの汎用 `zone_card` choiceと `choose_card` actionにまとめるのが推しである。選択元・所有者・残り枚数・0枚で止められるかはpending choiceの値に持つ。

- 共通化した場合の寸法: `CHOICE_KINDS +1`で `N_SCALAR +1`。`choose_card`は成果物1-1と共用するので追加の`ACT_DIM`増加はない。停止は既存`stop`を再利用できる。
- 成果物1-1と合わせた最小案: **`N_SCALAR 62→64`、`OBS_DIM 1313→1315`、`ACT_DIM 226→227`**。ただし後述の観測追加分は別に加わる。

### 1.2 優先度B: v5設計時に裁定する項目

6. **効果によるレベルアップの対象**
   - `levelup_by_effect`は同名キャラの最初の枠、該当カードの最初の1枚を自動選択する。
   - 現在の登録簿で複数候補が実際に生じるかをカード定義から機械的に数え、2候補以上があり得るなら選択肢化する。候補が常に同一カード・同一結果なら新しいchoiceを増やさない。

7. **準備時のバック2枠の順序**
   - `setup`はリーダーだけを選び、バックは名前順に自動配置する。
   - バック番号は`switch_back`等で区別されるため、ルール上配置順を選べるなら戦略的意味がある。
   - これはCHOICEではなくsetup行動を3キャラの順列として表すのが自然。ただし現行の行動符号にはバック2名を同時に表す欄が無い。`ACT_CODE_LEN`と行動特徴を変える別設計になるため、v5の選択便で明示裁定する。

### 1.3 選択肢化しないもの

- `opp_discard_random`と`opp_hand_random_to_deck_bottom`はカード文がランダムを要求するため、プレイヤー選択にしない。
- `mill_opponent_deck_top`、ドロー、デッキ検索後のシャッフルは山札順が非公開なので選ばせない。
- `_run_effects`の左端フォールバックは内部・テスト用で、通常の中断可能な効果解決入口ではない。通常対局から到達しないことを検査で固定する。
- 同一IDの複数コピーから1枚を取るだけで結果が完全に同じ場合は選択を増やさない。

## 2. 成果物1 — 公開情報と符号化の監査

### 2.1 `observe`にも無い公開状態

次は`GameState`にあるが`observe`へ出ていない。すべて公開済みカードの効果・公開された進行から決まる状態であり、隠れ状態を渡す提案ではない。

- `last_turn_clash_winner` / `last_turn_clash_pass`: 【優勢】の成立を決める。
- `damage_taken_mod`: 今後受けるダメージを変える。
- `first_damage_taken_this_turn`: 「各ターン最初」の補正がまだ残っているかを決める。
- `speed_override`: 対抗の判定を変える。
- `heals_this_turn`: 1ターン内の回復回数制限を決める。
- `tag_uses_this_turn`: 「各ターン最初に使うタグ」の補正を決める。
- `last_used_card`: 直前のカードタグ条件を決める。
- `damaged_this_turn`: ダメージ済み条件を決める。
- `slot_entered_turn`: 「このターン以外に登場」の条件を決める。
- `variation_rush_draw`: 次の＜変奏スキル＞連撃にドローが付くかを決める。
- `deferred_clash_damage`: 対抗フェイズ終了時に確定しているダメージ。

`pending_triggers`、`pending_skills`、`pending_effect`、`pending_ctx`、`choice_resume`は解決エンジン内部の継続である。カード番号や条件をそのまま渡すのではなく、プレイヤーが現在行う選択に必要な公開要約だけを`pending_choice`へ載せる。

### 2.2 `observe`にはあるが`encode_obs`が捨てている情報

- `last_clash_cards`: 直近に何を出したか。現状は勝者だけを符号化している。
- `clash_cards`: 現在公開済みの対抗カード。CHOICE中に効果・条件を理解するのに要る。
- 自分の`chara_deck`の中身: 現状は枚数だけ。どのレベルアップ札が残るかを区別できない。
- キャラスロットの下層: 現状は最上段だけ。`return_to_chara_deck`後に何が表へ戻るかを区別できない。
- `pending_choice`の詳細: `pay_or_damage`のcost/amount、`reveal_count`のmax、`discard_for_effect`のremaining、`switch_back`や`order`の候補内容を捨て、kindだけをone-hotにしている。同じkindでも意味の違う選択が同じ入力になる。
- トラッシュと協奏の順序: 現在は枚数ベクトルへ潰す。左端自動選択を残す限り、エンジンが次に取る札をネットが復元できない。成果物1の推しどおり選択肢化すれば、この欠落の重要度は下がる。

### 2.3 v5へ入れる推しと寸法の数え方

まず`observe`へ上記公開状態を追加する。`encode_obs`では、固定長で意味を保てる次の単位を採る。

- 2席ぶんの単純な数値・真偽・小さな列: `damage_taken_mod`、`first_damage_taken_this_turn`、`heals_this_turn`、`damaged_this_turn`、`variation_rush_draw`、`slot_entered_turn`、`last_turn_clash_pass`。
- 視点化した3値one-hot: `last_turn_clash_winner`。
- カード枚数/one-hot: `last_clash_cards`、公開後の`clash_cards`、自分の`chara_deck`、キャラ下層。
- タグ回数は登録タグを固定順にしたベクトル、`last_used_card`はaction-card one-hot。
- `pending_choice`はkindだけでなく、cost/amount/max/remaining、対象領域、選べる枚数をスカラー化する。候補カード自体は合法手のaction codeで区別する。
- `deferred_clash_damage`は席別の確定量に要約する。内部のsource参照をそのまま渡さない。

**正確な`N_SCALAR`と`OBS_DIM`は、登録タグ数とキャラ下層の表現を確定してから生成スクリプトで数える。** 現時点で仮の数を正本にしない。少なくとも成果物1のchoice追加だけで`N_SCALAR`は62→64になる。観測追加、Python/Rust一致、ネット移行を同じ便でまとめ、`ENCODING_VERSION`を4→5へ一度だけ上げる。

## 3. 成果物2 — 既存記録を横断教材に使える範囲

### 3.1 GitHubで確認できたこと

- `experiments/datasets/c1_v1.json`はSD001・mirror・planner中心の旧データ定義である。
- `drl_record.py`は現在も`mirror_config(deck)`固定で、異種デッキの記録ができない。
- 対象コミットのGitHubには`results/drl/`、`results/vb/`、`results/datasets/`の生記録とmanifestが無い。モデルJSONも置かれていない。
- したがって、PC側の各ファイルのMCDR版、encoding version、seed帯、教師、記録席をこの監査では照合できない。

### 3.2 利用区分

1. **そのまま利用可**
   - encoding v4で、追加するv5情報を必要としない比較・回帰検査。
   - SD001内での旧方策再現や、旧モデルとの挙動比較。ただし横断教材の中心にはしない。

2. **限定利用可**
   - 旧SD001記録を、v5で新設した入力が常に既知の既定値だった範囲に限って移行する場合。
   - 例: BP01専用状態はSD001で常に0とコード・デッキから証明できる。一方、既存からあった`last_clash_cards`や自分のキャラデッキ内容は0ではないため、旧記録だけから復元できなければ完全教材にしない。
   - 方策教師は合法手集合・action codeがv5と同じ意味で再構成できる決定だけに限定する。新しい選択が発生する決定は除外する。

3. **横断教材として不可**
   - encoding v3以前の記録を版検査なしにv4/v5へ混ぜること。
   - 新入力を根拠なく0で埋めること。
   - SD001だけの記録を「複数構築を学んだ」証拠にすること。
   - H・貪欲側の決定を、ループ教師の決定と同じ母集団として混ぜること。

### 3.3 PC側で行うファイル監査

各manifestと各bin先頭について、`path / size / sha256 / MCDR version / encoding_version / deck / config / spec_a / spec_b / seed0 / n / record seat`を一覧化する。manifestが無い生記録は由来不明として学習へ入れない。v5移行可否は「欠落した各欄を元状態から厳密に再構成できるか」を列ごとに判定する。

## 4. 成果物3 — デッキ分割案

現存する通常デッキはSD001とSD02だけで、K smoke 3本は検査専用である。2デッキだけでは「未知構築」を測れないため、まず全カードから合法な環境デッキ群を作る。全候補は`GameConfig.validate`と同条件（キャラ3種類ちょうど、アクション40枚、同番号3枚まで、専用カードには対応キャラ）を通す。

推しは**カード単位の無作為分割ではなく、構築単位の固定分割**である。

- 開発用 train: 6〜8構築。主要なキャラ組、色配分、コスト帯、タグ、回収・音骸・優勢などの機構を広く含める。
- 開発用 valid: 2構築。trainとカードが一部重なってもよいが、キャラ3人組と中核の機構組合せは重ねない。エポック選択・較正にだけ使う。
- 固定 holdout: 4構築以上。デッキ作成後は内容を封印し、学習、較正、ハイパーパラメータ選択、候補選別に一切使わない。
- 既存基準: SD001は退化検査と現champion直接対決専用。SD02は既知の別構築診断として残し、未知構築holdoutには数えない。

分割はデッキ間のJaccard類似度だけでなく、キャラ3人組、中核タグ、効果profileの分布で層化する。同じ中核を枚数だけ変えた姉妹デッキをtrainとholdoutへ割らない。split定義にはデッキJSONのsha256を保存し、後から中身を変えない。

未知構築Aの主試験は、**カードはtrainで見たことがあっても、その3キャラと40枚の組合せは一度も教材に出ていないholdout**で行う。未知カードBとは混ぜない。

## 5. 成果物4 — 互換性のある教師設定

### 5.1 採用する推し

- 教師の骨格は現championの探索能力を使うが、SD001専用ネット3種を横断教師へ無条件に持ち込まない。
- `value_net=drl_sd001_vc4.json`、`policy_net=pi_small64_e10.json`、`opp_policy_net=drl_sd001_s1.json`はSD001由来である。未知構築では新カード列が未学習で、π₀は相手の提出分布、代打ちπは自分の行動という別の役割を持つ。3つを一括して「champion」としてコピーしない。
- 初回の横断記録教師は、**素のplannerを共通土台**にし、`extra_turns=1`、`choice_phases=True`、`solo_samples=4`、`known_hand=True`、`draw_buckets=1`などネット非依存の探索器部分だけを候補にする。`endgame_enum`は正しい相手デッキリストを各席へ渡せる異種戦入口ができてから使う。
- 比較する表現候補間では、教師spec、デッキ、対戦相手、seed、記録席、局数を固定する。

### 5.2 排他条件

- 現championの`bundle_p=0.75`と`tau>0`はコード上で排他である。記録に探索性を入れるため`tau>0`を使うなら`bundle_p=0`にする。
- `bundle_p`は`lethal_uniform`、`opp_mix`、`nash_delta`とも排他である。
- `nash_delta`と`tau`も排他である。
- したがって初回候補は次のどちらか一方に固定する。
  - 決定論教師: `bundle_p=0.75`, `tau=0`。
  - 探索教師（推し）: `bundle_p=0`, 小さい`tau`。tauはSD001だけで選ばず、train構築だけの速度・手の多様性下見で事前固定する。

教師自身の良し悪しと表現の良し悪しを同時に動かさないため、段階2の表現比較では上記のどちらかを全候補で固定する。

## 6. 成果物5 — 速度下見

**未実施。** 公開化後にソース一式はcloneできたが、`meicho_rs`、championが読むモデルJSON、PC側の記録がリポジトリに無い。現championの記録200局とRust評価200局を正しい構成で回せないため、帯715000..715999は登録せず、`next_free`も715000のままとする。

### 6.1 PCでの正確な手順

作業場所: リポジトリの`engine`ディレクトリ。

1. `experiments/seed_bands.json`へ、`715000..715999`、purpose=`段階0の速度下見（記録200局・評価200局）`、kind=`diag`を追加し、`next_free`を`716000`にする。
2. 記録200局:

```powershell
python experiments/drl_record.py --deck SD001 --seed0 715000 --n 200 --out results/drl/g0_speed_record.bin --workers 2 --champion --record both
```

成功時は最後にmanifestのJSONと`g0_speed_record.bin.manifest.json`の保存案内が出る。manifestの`seconds`、`mean_turns`、`files`を使い、局/秒=`n / seconds`、記録サイズ/局=`各filesの合計バイト / n`を出す。

3. 評価200局は、同じSD001 mirror、同じchampion同士、seed 715200..715399、workers=2で`arena_rs.series_rs_detail`を呼ぶ小さな一時スクリプトから実行する。出力には`seconds`、`games_per_sec`、`mean_turns`、`mean_steps`、`n=200`をJSONで出す。強さの採否には使わない。
4. 同じseed 715200で評価を2回実行し、`series_rs_digest`の200局ぶんが完全一致することを確認する。

### 6.2 時間の見積もり

過去実測は機械と構成が異なる参考値で、対象構成の実測ではない。Rust固定nはマスターPCで0.79〜0.83局/秒、2コア作業機で0.36〜0.40局/秒だった。評価200局なら約4〜9分が目安である。記録は代打ちπ等により大幅に遅くなる可能性があるため、まず20局で秒/局を測り、200局見積=`20局実測秒×10`とする。合計が1時間を超えるなら打ち切り、実測20局と未実施180局を分けて報告する。

## 7. 成果物6 — 最初の比較の固定局数と95%区間

### 7.1 主試験

- 非劣性の主指標: **SD001での候補generalist対SD001現championの直接対決得点率**。引き分けは0.5点として得点率へ含める。D-086追記1の非劣性幅0.03を使い、95%下端が0.47を上回れば非劣性。SD001専用ネットを未知構築へ持ち込んだ体を「現champion相当」と呼ばない。
- 未知構築の主指標: holdout各構築で、候補generalistを**同じ探索器から学習ネットを外した素planner**と直接比較する。これは未知構築で学習済み表現が役立つかの試験であり、0.03の非劣性判定とは別に報告する。将来、その構築専用に同量追加学習した基準ができたら追加学習効率も比較する。
- 固定局数: **1比較あたり2,400局**。1,200局ではp=0.5付近の正規近似半幅が約0.028、2,400局では約0.020であり、0.03幅の判定に余裕を持たせる。
- 先後: 1つのbase seedにつき先後を入れ替えた2局を1ペアとし、1,200ペア=2,400局。両局でデッキの組も反転する。
- 区間: 採否の単位に合わせ、ペア得点（0, 0.25, 0.5, 0.75, 1）の平均差を観測単位として、1,200ペアの標準誤差から95%区間`mean ± 1.96*SE`を出す。単純な二項式を併記する場合は、独立1局を仮定した参考値と明記して混ぜない。

引継ぎ書の`±1.96√(p(1-p)/n)`を使う二項表示が正本として必要なら、勝敗のみの2,400局で同式を出し、ペア差の区間を主にする。どちらを採用したかを結果JSONへ固定する。

### 7.2 比較の順序

1. 配線対照: 同一spec同士。0.5を含むこと。
2. SD001退化検査: 候補対現champion。95%下端>0.47。
3. 未知構築holdout: デッキごとに候補対固定基準。
4. 錨: H、貪欲、素planner。採否の主条件ではなく、どこで崩れたかの診断。
5. 追加学習小試験: 同じ追加教材量・同じ計算量で、generalist初期値、random初期値、専用初期値を比較する。出発点と学習後を分けて報告する。

### 7.3 多重比較

事前に1本だけ主比較を指定し、その比較に補正をかけない。複数holdoutを同時に合否へ使うなら、各デッキの片側p値へHolm補正を使うか、「全デッキで下端>0.47」というintersection-union判定にする。錨と診断を主試験へ混ぜない。GSPRTはふるいと早期停止だけに使い、効果の大きさは固定2,400局で述べる。

## 8. 検査とfingerprint

### 8.1 実施結果

- 全検査: `python3 -m pytest -q`を実行。**381通過 / 46失敗 / 114 skip**、実時間5分16秒。
- 46失敗の主因: Git管理外の`cards/cards_structured.csv`、`BP01_UNLISTED.json`、`BP01_NO_IMAGE.json`、カード画像、`results/models/*.json`、Linux用`meicho_rs`が無いこと。`eval_vb`等がimport時に`meicho_rs`を要求するため、依存不足がskipではなく失敗として波及する検査もある。したがって46件を実装回帰とは判定しない一方、「全件成功」とも数えない。
- Python fingerprint 3種: **すべて一致**。`773a71c15c5bc16e` / `677f28cc3b6995ee` / `6e39c2aa4b35d876`。この環境での速度は順に228.2 / 27.7 / 1.9局/秒。
- champion fingerprint: **未実施**。`meicho_rs`とモデルJSONが無い。期待値は`e1662edb32b144a9`。
- 速度下見digest再現: **未実施**。

### 8.2 PCでの再実行

作業場所: `engine`。

```powershell
python -m pytest
python experiments/bench_agents.py
python scripts/check_champion_fingerprint.py
```

pytestは最終行のpassed / failed / skipped / xfailedをそのまま記録し、skipはテスト名と理由を一覧化する。`meicho_rs`が古い、torchが無い、データセットが無い場合は失敗とskipを混ぜずに記録する。

## 9. 段階1へ渡す判断点と推し

1. **推し: v5を1回だけ上げ、成果物1の優先度Aと成果物2の公開入力を同時に整備する。** 意味のある選択を増やす実装便と、符号化・モデル移行便は分ける。
2. **推し: setupのバック順と効果レベルアップは、実際に複数の異なる結果が生じるカード構成を機械的に数えてからv5対象を確定する。**
3. **推し: 異種デッキ記録入口は`--deck-a` / `--deck-b`を追加し、`matchup_config`を使う。** agent A/Bへ相手側の正しい`opp_decklist`を渡し、seed偶奇でagentとデッキを一緒に反転する。manifestの`config`を`matchup`、`deck_a`、`deck_b`、両デッキsha256まで拡張する。
4. **推し: 旧記録はPC上のmanifest監査が終わるまで横断学習へ入れない。**
5. **推し: 最初の固定評価は2,400局、主条件はSD001直接対決得点率の95%下端>0.47。** BP01での現champion対素plannerは診断に留める。

## 10. 変更・未実施事項

- 新規: `engine/G0_AUDIT_REPORT.md`（本報告）
- 変更なし: その他すべて
- 対局: 0局
- 学習: 0件
- モデル更新: 0件
- seed帯予約: なし
- 強さの結論: なし
- 次の一作業: 本報告の判断点を裁定し、段階1の「選択実装便」の範囲を固定する。
