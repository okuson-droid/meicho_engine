# 引継ぎ: 配布版（Windows 実行ファイル）をマスターの PC で作る手順（D-074・2026-09-08）

rules_draft.md v0.11 準拠 / engine v0.1。報告の作法は `REPORTING_RULES.md` §2.6（作業依頼の 5 点）に従う。
設計と根拠は `decisions.md` D-074。**ルールにも AI にも触っていない**（fingerprint 3 種は着手前と一致）。
便 E-0（D-073）の champion 交代を取り込んであるので、配布版の「最強 AI」は **`planner_vc4cps`（葉 = V_4'）**になる。

## 0. なぜ今これが要るか

知人に配る対戦アプリを**案 B（PyInstaller で固めた Windows 実行ファイル）**にすると裁定した。
実行ファイルは**配る OS で**作る必要がある（作業環境は Linux なので、Linux 版しか作れない。
Linux 版で手順とスクリプトの動作は確認済み）。したがって Windows 版の組み立てはマスターの PC で 1 回要る。
所要は初回 10 分（PyInstaller の導入込み）、2 回目以降 3 分。

## 1. 準備（初回だけ）

**どこで**: `C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine`
（PowerShell またはコマンドプロンプトでこのフォルダに移動する）

**何を打つか**（1 行ずつ）:

```
py -3.11 -m pip install pyinstaller
py -3.11 -c "import numpy, PyInstaller; print(numpy.__version__, PyInstaller.__version__)"
```

**成功したらどう見えるか**: 2 行目が `2.x.x 6.x.x` のような版を 2 つ出す。

**転びやすいところ**:

| 症状 | 意味 | 直し方 |
|---|---|---|
| `py` が見つからない | Python ランチャが無い | `python -m pip install pyinstaller` のように `py -3.11` を `python` に読み替える（以下同じ） |
| `No module named numpy` | numpy が入っていない | `py -3.11 -m pip install numpy` |
| 版が 3.11 でない | 別の Python が動いている | `py -0` で入っている版を確かめ、3.11 を指定する（Rust の wheel が cp311 なので、開発と同じ 3.11 に揃える。配布版自体は Rust を使わない） |

## 2. 組み立て → 検査 → 固める（毎回これ 1 本）

**どこで**: 同じ `engine` フォルダ。

**何を打つか**:

```
py -3.11 scripts\make_dist.py --smoke --exe --author "オクソン" --out C:\meicho_dist\dist_src
```

`--out` は OneDrive の外を推す（OneDrive 配下で PyInstaller を回すと同期が割り込んで遅くなったりファイルが掴まれたりする）。
`--author` は説明書の末尾に載る名前（伏せるなら省略してよい）。`--name` でアプリ名、`--version` で版（既定は今日の日付）を変えられる。

**成功したらどう見えるか**（この順に出る。途中の `INFO:` 行は PyInstaller のもので読まなくてよい）:

```
配るモデル: ['drl_sd001_vc4.json', 'drl_sd001_s1.json', 'pi_small64_e10.json']
相手の allowlist: ['planner_vc4cps', 'planner_vb3cps', 'planner_vb3', 'planner_pi', 'planner_lh', 'planner', 'mcts160', 'greedy', 'heuristic', 'random']
写したファイル: 42
警告: engine/meicho/cards.py:430: カード文の短い引用 → # カードテキスト「【対抗】相手が赤色のカードで対抗した場合」。
検査: 合格（画像・公式文の転記・棋譜・内部文書は入っていない）
合計 42 ファイル / 13,18x,xxx バイト
配布モード: あり（対決シミュレータ（非公式））
1 局: planner_vc4cps 対 heuristic  勝者 0  ターン 9
OK
煙テスト: OK
実行ファイル: C:\meicho_dist\dist_src\dist\MeichoSim
（もう一度「配布モード: あり … OK」が出る＝固めた版の煙テスト）
実行ファイルの煙テスト: OK
固めたフォルダの検査: 合格（画像・公式文の転記・棋譜・内部文書は入っていない）
配る zip: C:\meicho_dist\dist_src\dist\MeichoSim_2026-09-xx.zip
```

「警告」の 1 行は想定内（`cards.py` のコメントの短い引用。D-074 の判断 1）。**「NG:」が 1 行でも出たら配らない**。

**確認のしかた**:

1. `C:\meicho_dist\dist_src\dist\MeichoSim\MeichoSim.exe` をダブルクリックする。黒い窓が開き、続けてブラウザが開く。
   開始画面の見出しが **「対決シミュレータ（非公式）」**、その下に注意書きと権利表記、相手の一覧が
   「最強 AI（先読み＋学習した評価）」のような言い換えになっていること。「画像が見つからない」の**赤い警告が出ていない**こと
   （「カード画像は含まれていない（文字表示）」の 1 行が出る）。
2. 「対局を始める」を押し、リーダーを選び、マリガンを決め、2〜3 手打つ。カードが名前・コスト・ダメージの文字で並ぶこと。
   最強 AI の 1 手は 1 秒以内。
3. 黒い窓を閉じる。`C:\meicho_dist\dist_src\dist\MeichoSim\results\human_games\` は**対局を「記録して終了」で終えたときだけ**できる
   （途中で閉じたら何も残らない）。
4. 配るのは **zip 1 つ**（`MeichoSim_2026-09-xx.zip`・約 40〜60 MB 見込み）。`dist_src` フォルダや `build` フォルダは配らない。
   心配なら zip を開いて `.png` / `.jpg` / `.jsonl` / `cards_structured` が無いことを目で確かめる。中の `MANIFEST.txt` に
   全ファイルの一覧と sha256 が入っている。

**転びやすいところ**:

| 症状 | 意味 | 直し方 |
|---|---|---|
| `No module named PyInstaller` | §1 を飛ばした | §1 の 1 行目 |
| `NG: 禁止の拡張子: …png` 等 | allowlist の外から権利物が入った（本来起きない） | 配らずに報告。`--out` の先に古いフォルダが残っていた可能性。`--out` のフォルダを消してやり直す |
| `PyInstaller が失敗した` | 固める工程で落ちた | 直前の `ERROR` 行を報告。よくあるのはウイルス対策ソフトが `dist\MeichoSim\MeichoSim.exe` を隔離した、というもの（下の行） |
| 実行ファイルができた直後に消える／「ウイルスを検出」 | ウイルス対策の誤検知（PyInstaller 製の exe は誤検知されやすい） | 対策ソフトで `C:\meicho_dist` を除外に入れて `make_dist.py` をやり直す。配る相手にも README の「動作環境」の段落を読んでもらう |
| ダブルクリックで「WindowsによってPCが保護されました」 | 署名の無い exe への SmartScreen | 「詳細情報」→「実行」。README に書いてある |
| ブラウザが開かない | 自動起動が塞がれた | 黒い窓に出ている `http://127.0.0.1:8765` を手で開く。ポートが使用中なら `MeichoSim.exe --port 9000` |
| 黒い窓に `Address already in use` | 前の MeichoSim が残っている | 前の窓を閉じる。残っていればタスクマネージャで `MeichoSim.exe` を終了 |
| 煙テストで `FileNotFoundError … results\models` | モデルが `_internal` に入っていない | `MeichoSim.spec` の `datas` が壊れた。作業環境で直すので報告 |

## 3. 配るとき（線を守るために）

- 相手は**特定の知人**に限り、**無償**で、**再配布しない**よう伝える（README に書いてあるが口頭でも一言）。
- 配布ページや SNS に置かない。zip を直接渡す。
- 相手の棋譜（`results\human_games\*.jsonl`）を送ってもらえれば便 F の材料になる（任意・README に明記済み）。
- UCP への問い合わせ（D-074 判断 3）を出すなら、文面はわたしが書く。

## 4. 作業環境に持ち帰るもの

zip は持ち帰らなくてよい。次回のセッションで要るのは**上の出力の最後の 5 行**（検査・煙テスト・zip のパス）と、
§2 の確認 1〜2 で見た画面の様子（見出し・相手の一覧・赤い警告の有無）。うまく行かなかったときは「症状」の行をそのまま。
