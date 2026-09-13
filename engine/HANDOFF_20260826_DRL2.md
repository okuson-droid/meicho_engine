# 引継ぎ（2026-08-26・DRL 第 2 便）— 段階 1 完了、次は段階 2 から

rules_draft.md v0.10 準拠 / engine v0.1 / 決定記録 D-001〜**D-058** / 検査 **439 件**
報告の作法は `REPORTING_RULES.md`。計画 `DRL_PLAN.md`、段階 0 の記録 `DRL_NOTES.md`、
**段階 1 の記録 `DRL_STAGE1_NOTES.md`（正本）**。
発見ループ側の引継ぎ（`HANDOFF_20260826.md`）はそのまま有効（未裁定 2 件・語彙 D・効果クラス分類）。

## 0. 最初にやること（マスターの PC）— Rust の再ビルド

**なぜ要るか**: D-057 と D-058 で `rust/src/agents.rs` と `rust/src/lib.rs` を変えた。
Rust の成果物（`.pyd`）は**ソースと一緒には配られない**ので、手元で作り直さないと
古い拡張のまま動く（しかもエラーにならず、静かに古い挙動になる）。

### 手順（`engine\rust` で・所要 1〜3 分）

**1. 作業ディレクトリへ移動する**

```
cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine\rust
```

**2. `.pyd` を掴んでいるプロセスを閉じる**（開いている Python・pytest・対人検証アプリのサーバー）。
掴まれていると 3 の `pip install` が「アクセスが拒否されました」で落ちる。

**3. ビルドする**

```
maturin build --release --out dist
```

成功すると最後にこう出る:

```
📦 Built wheel for CPython 3.11 to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
```

**4. 入れ直す**

```
pip install --force-reinstall --no-deps dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
```

`Successfully installed meicho_rs-0.1.0` と出れば成功。

**5. 確認する**（`engine` に戻ってから）

```
cd ..
python -m pytest tests\test_drl.py tests\test_rust_agents.py -q
python experiments\bench_agents.py
```

- 検査は **17 ＋ 80 = 97 件**が通ること。
- fingerprint 3 種が `905073e2e202bd39` / `7cfceac12f2c070f` / `1f5e2e218cc54acc` であること
  （Python 実装の値なので、Rust を変えても**変わらないのが正しい**）。
- 全部回すなら `python -m pytest tests\ -q` で **439 件**。

**6. 学習を回すなら**: `pip install torch`（CPU 版で足りる）。

### 転びやすいところ（症状 → 読み方）

| 症状 | 意味 | 直し方 |
|---|---|---|
| `looks like a filename, but the file does not exist` → `OSError: [Errno 2]` | **ビルドしていない**（失敗ではない） | 3 に戻る |
| `Successfully installed` と出るのに挙動が変わらない | `--force-reinstall` を付け忘れた。crate の版は `0.1.0` のままなので pip が「already satisfied」で古い拡張を残す | 4 をやり直す |
| `アクセスが拒否されました` | `.pyd` を掴んでいるプロセスがある | 2 に戻る |
| `Couldn't find a virtualenv or conda environment` | `maturin develop` を使った | `maturin build` ＋ `pip install` に戻す（**`develop` は使わない**） |
| `error[E….]` でコンパイルが止まる | Rust 側の問題。クロエに全文を貼る | — |

**`--out dist` を省かないこと。** 省くと wheel は `target\wheels\` に出る。
`rust/dist/` はこのプロジェクトの wheel 置き場（Linux 版も同じ場所）で、行き先がずれると
「古い wheel を入れ直して入ったつもりになる」事故が起きる。詳細は `RUST_PORT_NOTES.md` §4.1。

## 1. 現在地

- 段階 1 の 3 項目（速度の手当て・模倣学習の本番・検証 3 本）はすべて完了。**追試も別帯で済ませてある。**
- モデル `results/models/drl_sd001_s1.json`（5.9 MB・幹 256×2・方策の頭 128・6 エポック・992 秒）と
  `*.meta.json`（学習の全ログ）を置いた。**記録データ（600 MB）は配布しない**。manifest から再生成（Rust 2 スレッドで 4 分）:
  ```
  python3 experiments/drl_record.py --deck SD001 --seed0 230100 --n 900  --out results/drl/sd001_s1_valid.bin --workers 2
  python3 experiments/drl_record.py --deck SD001 --seed0 231000 --n 9000 --out results/drl/sd001_s1_train.bin --workers 2
  ```
- **既定の planner は一手も変わっていない**（導入前 wheel の digest 一致）。

## 2. champion は交代済み（D-058・裁定は解決した）

マスターの裁定「交代する／推し（根だけ）を採る」を実施済み。**SD001 のみ交代、SD02 は据え置き。**

| プール | champion | 根拠 |
|---|---|---|
| SD001 | 計画探索 ＋ 相手モデル = π（`drl_sd001_s1.json`・根だけ） | ラダー Elo **1358**（旧 1329）。直接対決 0.553 ±0.056 |
| SD02 | 計画探索（据え置き） | 専用 π でも 0.493 ±0.028（下端 0.465）で門番を越えない |

**定義は `experiments/champion.py` が唯一の真実源。** ラダーのガントレット・対人検証アプリ・発見ループがここを見る。
3 か所が食い違ったら検査が落ちる。**champion を変えるときはこのファイルだけを変える。**

**Python 側にも差し替え口を実装した**ので、対人検証アプリでマスターが新 champion と対戦できる
（アプリの既定の相手も新 champion。π はプール専用なので SD02 では選択肢に出ない）。

**発見ループへの注意**: SD001 の土台が変わった。**巡をまたいだ比較は台帳の `champion_base` が同じときだけ有効**である。

## 3. 次の作業（順）— 段階 2（`DRL_PLAN.md` §6）

1. **記録を取り直す。** 教師が新 champion になったので、段階 1 の記録（`sd001_s1_*`）は旧 champion のものである。
2. **1 反復目**: `drl_record.py --policy-net <model> --tau 0.05`（自己対戦で新しい記録）→
   `drl_train.py --init <前の版> --lam 0.5` → 検証（D-034）。
3. **カナリアを毎反復記録する**: 漂泊者 Lv2 到達率（`experiments/measure_horizon.py` の型）。
4. **V の頭の早期打ち切り**（§4-2）。段階 2 で V を使うなら必須。

## 4. 段階 1 で分かった、次に効く事実

1. **学習した V を planner の葉に挿すのは失敗した**（0.383）。C-1 の教訓の再現。
   段階 2 で V を使うなら、目的関数を「勝敗の予測」から「葉どうしの比較」に寄せる工夫が要る。
2. **価値 V の予測は 1 エポック目が最良で以降は悪化した**（0.616 → 0.667）。方策 π だけが伸びた（0.704 → 0.750）。
   `drl_train.py` は最後のエポックを保存するので、**保存された V は最良の V ではない**。
3. **ネットを大きくした費用は対局速度に出る。** 隠れ層 128 → 256 で、ネットを使う構成はおおむね 1/4 の速度になる。
   段階 2 の自己対戦は π を大量に回すので、幅を落とした版との強さ比較を先にやる価値がある。
4. **`policy_net` は `Greedy::clash` の相手の提出には届いていない**（段階 0 の実装の穴）。`opp_policy_net` だけが届く。

## 5. 守ること（段階 0 から変わらず）

- `Action` に手を足したら `engine.rs::hash_action` **と** `encode.rs::action_code` / `encode.py::ACTION_TYPES` にも足す。
- 符号化を変えたら Python・Rust 両方を変え、`ENCODING_VERSION` を上げ、記録は作り直す。
- 帯は `seed_bands.json` に登録してから。`next_free` = **290000**。80000.. は使わない。
- **記録に使った帯は評価に使わない**（`--seed0 271000 --n 9000` は 271000..279999 を占める・D-058 §5）。
- **マスターに作業を頼むときは手順を省略しない**（`REPORTING_RULES.md` §2.6）。
- 記録・モデルには**絶対パスを書かない**。同じパスのネットを上書きしたら `meicho_rs.net_forget(path)`。
- **「予測が良くなった」を進捗と呼ばない（D-038）。採用の物差しはラダーの直接対決だけ。**
