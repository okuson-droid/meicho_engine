# 引継ぎ書 — Kaggle「ポケモンTCG AI Battle Challenge」上位解法の読み込み

作成 2026-09-16 ／ **改訂 2026-09-19**（クロエ・照合のうえ状態を更新）
当初の宛先 上位モデル（設計判断を任せる役）
位置づけ **文献読解の便（D-090）**。エンジンの変更・測定は含まない。

---

## ★0. この便は完了している（2026-09-19 改訂）

**依頼した作業は 2026-09-16 に完了した。再実行しないこと。**
以下は 2026-09-19 に実ファイルと突き合わせて確かめた結果である。

- 裁定番号 **D-090**（`decisions.md`）。
- 成果物 **`engine/PTCG_KAGGLE_NOTES_20260916.md`**（記事 12 本の要約・論点 A〜E への当てはめ・
  提案 **PT-1〜PT-10**・噛み合わない提案の棄却理由・出典）。
- `LITERATURE_PLAN_20260906.md` **§10.11** に追記済み。
- `TASKS.md` の Done に記載済み。
- **champion・探索器・帯・計画の順序は不変。実装も測定も行っていない。**

### ★残っている唯一のもの: 判断が要る点 J-1〜J-6（未裁定）

`PTCG_KAGGLE_NOTES_20260916.md` §5 の 6 件。「次の引継ぎ書 §0.3 で閉じる」と書かれたが、
**次の引継ぎ書（`HANDOFF_20260919_OFFICIAL_RULES_CLOSE.md`）は公式ルール線のもので §0.3 を持たず、
J-1〜J-6 に触れていない。`TASKS.md` の Active にも Waiting On にも無い。**
＝**未裁定のまま台帳から漏れている。**次に拾う者がこれを閉じること。

- **J-1** PT-1（詰みの証明器）の位置づけ。推し (a) 診断 → 候補化 → 通常の門番。
- **J-2** PT-5（オラクル批評家 V_oracle）と **D-026「覗き見禁止」の線引き**。推し (a) 教師専用として認める。
  **6 件でいちばん重い。**規約の条文に例外を書き足す話なので、裁定なしでは便 E に入れない。
- **J-3** 符号化 v6（PT-3＋PT-4）の時期。推し (a) 段階 1B が PC で閉じてから。
  **→ 前提条件はすでに満たされている。**段階 1B は 2026-09-16 に閉じ（D-089・D-091）、
  PC の wheel は `encoding_info()` が `(5, 1825, 317)` を返す。J-3 が待っていた障害は無くなった。
- **J-4** PT-2（搾取者リーグ）の置き場。推し (a) 便 F の前倒し部分。
- **J-5** 便 E の反復に入れる順序。推し 6' は PT-6（分布ヘッド）を先。
- **J-6** PT-1 の診断の対象。推し (a) 対 H 40 局の 19 回＋T-14＋対人 6 局。

**いちばん安い次の一手**（本便の結論）: **PT-1 の診断**。対局を回さず 1 日。
対 H 40 局の詰み見逃し 19 回・T-14・対人 6 局のうち「公開情報だけで証明可能な詰み」の割合を数えるだけ。

### 本書と成果物が書かれた時点との差（2026-09-19 現在）

本書と `PTCG_KAGGLE_NOTES_20260916.md` は **rules v0.12・符号化 v5** の時点で書かれた。その後:

- **rules は v0.18 に上がった**（公式ルール線・D-092 の差異 12 件を D-094〜D-104 ですべて解消）。
  **★A-2（D-095）と A-6（D-104）で SD001 の対局が変わった**＝本書 §0 の論点 A〜E が引用している
  便 A〜C の数字は**旧エンジンの測定**である。提案の当否には影響しないが、**数字を再利用しないこと。**
- champion は `planner_vc4cps_kheb_b75` のまま交代していない。指紋は 2026-09-19 に
  `f4b80b25c35cfa77` へ貼り替え済み（D-104）。
- 次に使える D-番号は **D-108**、帯の `next_free` は **715000**。

以下 §1 以降は当初の依頼内容である。**リンク集としては引き続き使える**ので残す。

---

## §1 当初の依頼（完了済み・記録として残す）

Kaggle で 2026 年に行われた『ポケモンカードゲーム』の AI 対戦コンペ（参加 6,807 チーム）の
上位解法記事が、9 月上旬に一斉公開された。**不完全情報 TCG を自己対戦で学習させるという
問題設定が meicho_engine とほぼ同一**であり、規模（H200 4 枚・110 億ステップ級）も
到達点（人間の競技プレイヤーに勝つ水準）も、こちらより 1〜2 桁上にある。

依頼はこの 2 つだった。

1. 下記の記事群を読み、**meicho_engine に移植可能な設計上の知見**を抽出すること。
2. 抽出した知見を、既存の文献計画（`engine/LITERATURE_PLAN_20260906.md`）の
   便の枠組みに載る形の提案として整理すること。判断が要る点は選択肢＋推しを添える。

### 当てるよう指定した 5 箇所

meicho_engine 側で詰まっている、または未解決の論点。**答えは成果物 §2 にある。**

- **A. 対人で負ける原因**——相手モデル π₀ の決めつけにより、安い赤・緑の列が評価から消える
  （`human_games_20260903.md`・便 2 の本命 a15 でも同型）。上位陣は相手モデルをどう置いているか。
- **B. 詰み探索**——便 A の `lethal_uniform` は条件を 1 本だけ通ったが、対照と対にすると
  約 3.5 ポイント弱く 25.8% 遅く、champion 交代に至らなかった。上位陣の「証明可能な詰み探索」は
  何が違うのか。
- **C. 決定化と信念**——`hand_known` を決定化が使っていない件（便 M）。
  上位陣は隠れ情報をどう状態表現に入れているか。
- **D. 価値関数 V の頭打ち**——反復 4' で門番を越えたがデータ窓を広げても動かなかった
  （`value_bootstrap.md`）。目的関数の設計（`c1_value_function.md` の D-038）に効く記述はあるか。
- **E. 評価の分散**——ラダーと門番の信号が弱い問題。上位陣の評価設計（何体・何局・どう対にするか）。

---

## §2 記事一覧（Simulation トラック最終順位 = 実力順）

いずれも Strategy トラック（ハッカソン）に投稿された解説記事。
順位は Simulation トラック（実際の対戦リーグ、6,807 チーム）の最終順位。
**12 本すべて読了済み。**要約は `PTCG_KAGGLE_NOTES_20260916.md` §1 にある。

### 論点に直接当たったもの

**1位 Luca —「Aim to Be a Pokémon Master」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1784257142000
優勝解法。単独チーム。

**5位 Petit Canard —「The Deck Is Half the Game」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1787069823045
行動クローン＋自己対戦リーグ＋マッチアップ別の専門家＋不完全情報向けに作り直した Gumbel 探索。
→ 論点 C・E。**成果物 §6-1 の「葉 V の視点の点検」はこの記事から出た気づきである。**

**14位 213tubo（Preferred）—「14th Place Solution」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1785817601057
BC → アーキタイプ専門家 → デッキ専門家の段階学習、＋証明可能な詰み探索。
→ 論点 B。**PT-1 の直接の出どころ。**

**7位 LumenLiquidity**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/7th-place-solution-for-the-ptcg-ai-battle-challeng
デッキ非依存の方策を「自分専用のエクスプロイタのリーグ」で鍛える。
→ 論点 A。**PT-2 の直接の出どころ。**

### その他

**2位 palsystem —「From 3,341 Decks to One Specialist」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1788449799640

**3位 Unown Gradiant —「All Decks on Hand」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/team-unown-gradiant-solution-all-decks-on-hand

**4位 flg —「A Simple Learning Loop for a Complex Card Game」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1782463123738

**8位 やる気元気ミワハルキ —「Generalist-to-Specialist PPO」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/8th-place-solution-yaruki-genki-miwa-haruki

**9位 Rmy**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1788435877208
780 万パラメータの方策のみで 9 位。対局時に MCTS を使わない。→ **PT-10 の出どころ。**

**12位 Majkel1337 —「Self-Play RL for the Pokémon TCG」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1788197347997
本書 §3 に要点あり。実装は MIT ライセンスで公開。
GitHub: https://github.com/Michal1337/pkmn-kaggle
**★ただし GitHub の README にライセンス表記が見当たらない**（成果物 §6-4）。
コードを参照するときは LICENSE ファイルを確かめること。

**順位未確認 Mew World Order —「An atomic theory of the Pokémon TCG」**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1788280148225
カードを「繰り返し現れる要素の合成」として見るモデル。記事に最終順位の記載が無く、**順位は未確認のまま**。

**記事一覧のトップページ**（全 9 ページ・得票順）
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups?orderBy=votes

**Simulation トラック最終順位表**
https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/leaderboard

---

## §3 12 位の要点（本便の着手時点で唯一の既読記事）

他を読む基準として置いたもの。**成果物 §1.9 は本節との差分だけを書いている**ので、
12 位の全体像を知りたいときはここを読む。

- 規模: 2,000 万パラメータの Transformer、110 億ステップ、H200 4 枚で毎秒 16,500 ステップ。
- **状態表現**: 全ゾーン（山札・手札・場・スタジアム・トラッシュを自他とも）を 1 カード 1 トークンの
  列に符号化。合計 300 トークン超。相手の未知部分は UNK トークン。
  各トークン ＝ 学習されたカード埋め込み ＋ 59 次元の静的カード特徴の射影 ＋ ゾーン埋め込み。
  **位置埋め込みを与えないことで順序不変性を得ている**（手札やベンチの並び順に意味がないため）。
- **行動表現**: エンジンが返す各行動候補も 1 トークンにして状態列の末尾に連結。
  方策ヘッドは選択肢トークンを採点する＋ターン終了の SUBMIT ロジット。
- **学習**: 素の自己対戦 PPO＋GAE。1 つのネットが両サイドを打つ。凍結した過去のコピー（teacher）と
  定期的に直接対戦させ、勝ち越したら teacher を差し替える（`promote_winrate = 0.53`）。
  → こちらの「門番」「champion 交代」とほぼ同じ構造。
- **停滞対策**: 1 ターンが 200 手を超えたらその場で停滞側の負け。
- **高速化**: エンジンの観測出力を JSON から生バイナリバッファに変え、状態符号化を C に移した。
  これが最大の改善だった。**ただし無条件には流用しない**（D-086 追記・観測と符号化の費用を先に分離する）。
- **相手デッキのサンプリング**: デッキを文書・カードを単語とみなした tf-idf ベクトルを作り、
  「他デッキとの平均コサイン類似度の逆数」を重みにする。**採用済み**（D-086 追記の 3 点の 1 つ）。
- **ファインチューニング（2ネット方式）**: 本命デッキを打つネット A と、相手側を打つネット B を
  同時に学習させ、A を 2 ポイント勝ち越すまで学習 → 凍結 → B が取り返すまで学習、を交互に繰り返す。
  **採用済み**（D-086 追記の 3 点の 1 つ）。
- **本人が挙げた反省**: 評価が広すぎて信号が薄まった（1,553 デッキは多すぎた）／
  学習率スケジュールは使わず固定のほうが良かった／トークンが多すぎた／
  ハイパーパラメータの最適化より先にモデルを大きくしてしまった。
  → **PT-8（評価電池の固定と n の下限）はこの反省と 5 位・7 位の設計が一致したもの。**

---

## §4 読むときの注意（当初の指示・そのまま有効）

- **これらは他人の成果物であり、こちらの真実源ではない。** 記事の記述は提案の材料として扱い、
  meicho_engine への適用は必ず裁定（`decisions.md`）を経ること。
- **ゲームが違う。** ポケカと『鳴潮：対決』では、同時手番（対抗ステップ）の有無、カードプールの
  大きさ、1 ターンの手数が異なる。構造が噛み合わない提案は、噛み合わない理由まで書いて棄却する。
  → **実際に棄却したものは成果物 §4 にある。再提案しないこと。**
- **計算資源が 1〜2 桁違う。** H200 4 枚・110 億ステップ級の前提に依存する結論は、
  こちらの計画（`COMPUTE_PLAN_20260908.md`・Kaggle の無料枠 4 コア 12 時間）では再現できない。
  資源に依存しない構造上の知見だけを拾う。
  → ただし**賃貸 GPU の費用感は材料になる**（5 位が全パイプライン約 $70、3 位が 6B ステップで約 $110）。
  D-072「有料 VM は条件つき」の条件を検討するときに使う（成果物 §6-2）。計画は変えていない。
- 記事本文の複製は成果物に含めない（個人研究用途に留める・プロジェクト制約）。

---

## §5 未着手の作業

本書には書かない。**`TASKS.md` が一元管理**。
**ただし J-1〜J-6 は現在どちらにも載っていない**（§0 参照）。拾った者が `TASKS.md` に戻すこと。
