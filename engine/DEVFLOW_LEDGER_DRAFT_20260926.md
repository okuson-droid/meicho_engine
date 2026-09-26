# 台帳への反映の下書き — 開発の流れの組み替え（2026-09-26・番号は振っていない）

書き手: クロエ（別端末のチャット）。**エンジンの持ち場の別のチャットが同時に動いていたので、この下書きは台帳に触らずに置いた。**
使い方: エンジンの持ち場のチャットが 1 つになったら、そのチャットに「`engine/DEVFLOW_LEDGER_DRAFT_20260926.md` を台帳に落として」と言う。
落とすときの決まり: `decisions.md` の末尾を見てから D-番号を振る／改行は `decisions.md`・`TASKS.md` が CRLF、`CLAUDE.md`・`LANES.md`・`GITHUB_SETUP.md` は元のまま／落としたらこの下書きは消してよい（`DEVFLOW_PLAN_20260925.md` が正本）。
正本: `engine/DEVFLOW_PLAN_20260925.md`（§0.1 が裁定・§9 が反映先）。

---

## 1. `engine/decisions.md` に足す 1 項（末尾に追記・番号は末尾を見て振る）

### D-xxx 開発の流れの組み替え — GitHub を正本に・push は Claude Code・results/ を git に（2026-09-25〜26・マスター裁定）

**何を決めたか**（正本 `engine/DEVFLOW_PLAN_20260925.md` §0.1）

1. **ファイルの追加・更新は GitHub 一か所**（`okuson-droid/meicho_engine` の `main`）。**GitHub が唯一の正本。**PC のフォルダは作業ツリーであり正本ではない。D-（2026-09-15 の「正本は PC のフォルダ」の裁定・`CLAUDE.md` 冒頭・`GITHUB_SETUP.md` §7・`LANES.md` §10 の当該文）を覆す。
2. **push するのは Claude Code（PC 版）。**マスターが GitHub Desktop で押すのは Claude Code が使えないときの例外。
3. **PC で生まれるファイル**（対人局の記録・カードの手動スクショ・ネットの移行の出力・配布版の検査結果）**も PC の Claude Code が commit して push する。**PC は「pull するだけ」ではなく、PC 生まれのものを push する働き手の一人。
4. **Cowork（クロエ）の文書は接続フォルダ（作業ツリー）に書き、PC の Claude Code が commit・push する。**プロジェクトナレッジ経由は Claude Code が読めないので使わない。読みは GitHub からでよい（clone のほうが速い）。
5. **クラウドの Claude Code はブランチに push する。**`main` への merge は PC の Claude Code かマスター。
6. **`cards/` は除外のまま**（公式素材）。**`results/` は git に上げる。**除くのは `.bak.json`（移行前の原本・約 230 MB）・`.bin`（記録本体）・`s2v_id_ens3.json`（部品 3 本から決定的に作り直せる）の 3 種。`.gitignore` の `engine/results/*/` と `!engine/results/human_games/` を消し、`engine/results/**/*.bin`・`engine/results/**/*.bak.json`・`engine/results/models/s2v_id_ens3.json` の 3 行に置き換えた（実施済み・2026-09-26）。
7. **リポジトリは Public のまま**（条件: 秘密の値を書かない／`cards/` の除外を動かさない／本名を含む Windows の経路は移設のあとに置き換える）。2026-09-25 に写しを grep して秘密の値が無いことを確かめた（署名の秘密鍵はリポジトリの外・公開鍵だけ・合言葉やトークンの実値なし）。Public の実利は Actions の無料枠が無制限であること。
8. **OneDrive の外への移設（D-126 の (5)）は「今やる」。**2026-09-26 にリポジトリの実体が `C:\Users\奥村優斗\Documents\eclipse_workフォルダ\meicho_engine_v0.1` に移っていたが、PC の Claude Code が数えると 2,750 ファイル（`.git` の 729 件を含む）が OneDrive のクラウドファイルの印を持っていた＝まだ OneDrive の根の下。行き先は `C:\dev\meicho_engine_v0.1`、実行は PC の Claude Code（正本 §3）。
9. **Cowork の書き戻しのバイト比較（`LANES.md` §5・D-113）は、OneDrive の外（`C:\dev`）で 5 回以上の書き戻しが全部一致するまで残す。**

**やったこと**

- 段 1（2026-09-25）: 9 月 16 日以降の未 commit 9 日分（D-089〜D-133）を commit・push した。
- 段 4（2026-09-25）: GitHub Actions を 2 本置いた。`Tests`（`ubuntu-latest`・Rust を建てて `pytest tests -q -rfs`・既定＝重い検査は飛ばす）と `Windows wheel`（`windows-latest`・maturin で cp311 の wheel を作り Actions の成果物に置く・`engine/rust/**` か `cards.py` が変わった push で動く）。**資材が無くて落ちる検査は `engine/ci/missing_assets_allowlist.txt` に名指しで持ち、一覧で説明できない失敗があるときだけ赤にする**（最初の実行で落ちた 46 件はすべて `FileNotFoundError` か画像の索引が空であることによる失敗で、説明できない失敗は 0。作業環境に同じ clone を作って集合の一致を確かめた）。`results/` を上げたあとは 37 件が通るようになり、一覧は 9 件（`cards/` を要する 8 件＋保留 1 件）に縮めた。
- 段 3（2026-09-26）: PC に Claude Code を入れた。初仕事として `REBUILD_REQUEST_20260922b.md` の (1)(3)(4) を回し、**指紋 `f4b80b25c35cfa77` 一致・`--pc` の組 335 通過・1 skip・失敗 0**（再ビルド 656 秒）。報告は `engine/CC_PC_RUN_20260925.md`。**これで 5 点セットの依頼文をマスターが手で打つ工程は引退**——以後の再ビルド・検査は Claude Code への貼りつけ文にする（書き方の決まり REPORTING_RULES §2.6 は変えない。読む相手が人から Claude Code に変わるだけ）。
- 気づき: `findstr /i "bak.json .bin"` は `.bin.manifest.json` にも当たる粗い検索で、Claude Code が誤ヒットを見抜いて末尾の厳密一致で確かめ直した。確認コマンドは末尾一致で書くこと。

**次**: 段 5（クラウドセッションで D-132 追記 4 と同じシードの再現を 1 便）。前に `experiments/provenance.py` の `HOSTS` に `cc-cloud-4` を足す（打ち方には関わらない・検査を通してから）。段 6（進行盤）は段 5 のあと。

**残っている判断 2 件**（急がない・推しつき）: Codex の名残 `stage1b-encoding-v5` ブランチと `stage1b-rust.yml` を消す（推し: 消す・ahead 0 を見てから）／`GITHUB_SETUP.md` §7 と `LANES.md` §10 の書き換え（本下書き §3・§5）。

---

## 2. `TASKS.md` Active の置き換え

「**監査の採用 2 件の実行（D-126）**」の (5) の部分（`webapp/` の引退の条件と日付・リポジトリを OneDrive の外へ移す日・PC 側の Claude Code を試す）を、次に置き換える。(1) はそのまま残す。

- [ ] **開発の流れの組み替え（D-xxx・正本 `engine/DEVFLOW_PLAN_20260925.md`）** - GitHub が正本・push は Claude Code・`results/` は git に（§0.1）。
  - [x] 段 1 未 commit 分の commit・push（2026-09-25）
  - [x] 段 4 GitHub Actions 2 本（`Tests`・`Windows wheel`・資材の一覧 `engine/ci/missing_assets_allowlist.txt`）（2026-09-25）
  - [x] 段 3 PC に Claude Code・初仕事（指紋一致・`--pc` 335 通過・`results/` を git に）（2026-09-26）
  - [ ] 段 5 クラウドセッションで測定を 1 便試す（D-132 追記 4 と同じシードの再現・§6）。**前に `provenance.py` の `HOSTS` に `cc-cloud-4`**
  - [ ] 段 6 進行盤（アーティファクト）の設計（§7・段 5 のあと）
  - [ ] 段 2 OneDrive の外（`C:\dev\meicho_engine_v0.1`）へ——PC の Claude Code が robocopy（§3）。段 5 の前に
  - [ ] `webapp/` の引退の条件と日付（D-126 の (5) の残り・未定）

---

## 3. `LANES.md` の書き換え

§5 の冒頭に 1 文を足す: 「**正本は GitHub の `main` である（D-xxx・2026-09-25）。**PC のフォルダは作業ツリー（段 2 のあとは `C:\dev\meicho_engine_v0.1`）。書き戻しの再ステージとバイト比較の決まりは、移設後 5 回以上の一致を見てから緩める。」
§10 を次に置き換える:
「- 2026-09-25 に見直した（D-xxx・`engine/DEVFLOW_PLAN_20260925.md`）。git を受け渡しの土台にし、push は Claude Code（PC）が行う。ブランチで持ち場を分けることはしない。
- リポジトリは `C:\dev\meicho_engine_v0.1` に移す（段 2・2026-09-26 着手）。書き戻しのバイト比較は、移設後 5 回以上の一致を見てから緩める。」

---

## 4. `CLAUDE.md` の書き換え

冒頭の「**正本は PC のこのフォルダである**（2026-09-15 裁定）。GitHub は貼るための置き場であって正本ではない（`GITHUB_SETUP.md` §7）。」を
「**正本は GitHub の `main` である**（D-xxx・2026-09-25 裁定・`engine/DEVFLOW_PLAN_20260925.md`）。PC のフォルダは作業ツリー。push は Claude Code（PC）が行う。」に。
「踏みやすい罠」に 1 行: 「**push を忘れると、クラウドの Claude Code も GitHub から読むクロエも古い版を見る。**作業の終わりに `git status` が空で `Push origin` に数字が無いことを見る。」
People の表の「マスター」の行の「**PC でしかできない作業（Rust のビルド・全体検査の実行）の実行者**」を「PC でしかできない作業は PC の Claude Code が行う（D-xxx）。マスターは裁定者」に。

---

## 5. `GITHUB_SETUP.md` §7 の書き換え

「- リポジトリは**貼るための置き場**であって正本ではない。正本は PC のフォルダのまま。」を
「- **リポジトリが正本である**（D-xxx・2026-09-25）。PC のフォルダは作業ツリーで、push は Claude Code（PC）が行う。push を忘れると、クラウドの Claude Code もクロエも古い版を読む。」に。
§0 の「ChatGPT が private リポジトリを読めるか」の段は経緯として残し、末尾に「（2026-09-25: Public で運用中・D-xxx）」を足す。

---

## 6. `engine/DEVFLOW_PLAN_20260925.md` §4 の確認コマンドの訂正（クロエが直す・台帳ではない）

`git status --short | findstr /i "bak.json .bin"` は `.bin.manifest.json` にも当たる。末尾一致に直す:
`git status --short | findstr /i /r "\.bak\.json$ \.bin$"`（何も出なければ合格）。
