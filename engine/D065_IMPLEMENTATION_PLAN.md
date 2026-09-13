# D-065 実装引継ぎ書 — 探索を V に追いつかせる（代打ち π・選択フェイズ・葉の整列・決定化・楽観の除去）

rules_draft.md v0.11 準拠 / engine v0.1 / 2026-09-03 / champion = `planner_vb3`（Elo 1423）
報告の作法は `REPORTING_RULES.md`。用語は `GLOSSARY.md`。マスターへの依頼は 5 点セット（`REPORTING_RULES.md` §2.6）。

**位置づけ**: `STRENGTH_REVIEW_20260902.md`（以下「レビュー」）の裁定（`decisions.md`「D-065 裁定」・2026-09-03）を
実装するための引継ぎ書である。**実装は下位モデルが引き継ぐ。** そのため本書は、変更するファイル・足す引数の名前と既定値・
先に書く検査・受け入れ基準・シード帯・実装の順番まで指定する。

**本書に書いていない設計判断が必要になったら、推測で補完せず「判断が要る点」として報告すること**（作業規約 1）。
「こう決めて進めた」の報告でよいのは、本書が「実装者が決めてよい」と明記した箇所だけである。

---

## この文書の読み方

§0 が結論（何をどの順で作るか）。§1 が守ること（不変条件）。§2 が便 1（Rust を変える作業を全部まとめる。作業環境で自前ビルド）。
§3 が便 2（測定と champion 交代）。§4 が便 3（学習側・Python だけ）。§5 が便 4（輪の再始動）。§6 が便 5（発見ループと対人アプリ）。
§7 がシード帯。§8 が検査の一覧。§9 が転びやすいところ。§10 がマスターの PC の Rust 再ビルドの依頼文（便 2 の交代の直前に 1 回・そのまま使う）。

**再ビルドの扱い（マスター裁定・2026-09-03）**: Rust の変更は便 1 で**作業環境（Linux）が自前で wheel をビルドして**検査を通す。
**マスターの PC（Windows）の再ビルドは便 2 の champion 交代の直前に 1 回だけ**依頼する（§3.5・§10）。
それまでマスターの PC の Rust は古いままなので、Rust を要する新しい検査は「入っている Rust が新しい引数を知らなければ skip」にする（§8）。
便 1 の中は §2.1 の順に進める。**便 1 が終わる（作業環境で全検査通過・fingerprint 3 種不変）まで便 2 に進まない。**

---

## 0. 結論（先に）

### 0.1 何を作るか（レビュー §4 の A-5'／A-1／A-2／A-0／A-3／A-7／B-2／B-3）

| 便 | 中身 | 変えるもの | 完了の判定 |
|---|---|---|---|
| **1** | 探索器の新しいつまみ 5 つ（すべて**既定で無効**）: `policy_net`（Python 側）＋`policy_scope`／`choice_phases`＋`solo_samples`／`align_leaves`／`reeval_samples`（記録の二重推定）／`tau`（Python 側） | `meicho/greedy.py`・`meicho/planner.py`・`rust/src/agents.rs`・`rust/src/lib.rs`・`meicho/drl_data.py`・`tests/test_d065.py`（新設） | 新検査が全部通る／既存 473 件が通る／fingerprint 3 種が不変。**Rust は作業環境で Linux wheel を自前ビルド**（§2.9）。マスターの再ビルドは**しない** |
| **2** | 候補を**別々に**測り、効いた組み合わせで champion 交代（D-034） | `experiments/probe_d065.py`（新設）・`experiments/champion.py`・`gauntlets/core5.json`・`webapp/agents.py`・`seed_bands.json` | 門番＋錨＋ラダー＋監査＋fingerprint（§3.4）。**交代の直前にマスターの PC で再ビルド 1 回**（§3.5・§10）→ マスターの PC でも全検査通過 |
| **3** | 教師の楽観を除く（学習側）: `--vtarget fresh`・`--calib-by phase_turn`・楽観の診断 | `experiments/drl_train.py`・`experiments/diag_optimism.py`（新設） | 検査（§8 の T-9〜T-11）／既存の記録（v2）が読めること |
| **4** | 輪の再始動（loop 2）: 新しい探索器で記録→学習→門番 | `experiments/vb.py`・`drl_record.py`・`eval_vb.py`・`pilot_tau_vb.py` に `--loop` | 反復 4' の報告（§5.4） |
| **5** | 発見ループを新 champion に向ける／対人アプリだけ対抗を確率化 | `experiments/discovery.py`（BANDS）・`webapp/agents.py` | 発見 0 件の確認／アプリで tau が効く |

### 0.2 実測済みの前提（レビュー §3・§9.1。再測定は不要）

| 候補 | vs 現 champion | 錨（同シード対・n=300） |
|---|---|---|
| 代打ちを π に（Rust の `policy_net`=vb3 の π 頭） | **0.614 ±0.022（n=1,800・2 帯）** | H −0.013 ±0.038／貪欲 +0.050 ±0.048／素 planner +0.057 ±0.073 |
| 対抗の決定化 `samples` 6→12 | **0.541 ±0.016（n=3,600・2 帯）**（plan_samples 8 は効かない） | 未測定 → 便 2 で取る |
| `tau`=0.005 | 0.484 ±0.028（費用 −0.016 ±0.028） | — |

便 1 の実装が正しければ、**Python 版の `policy_net` は Rust 版と毎手一致する**ので、この数字は Python 版にもそのまま当てはまる。

---

## 1. 守ること（不変条件・全便共通）

1. **既定値では一手も挙動が変わらない。** 新しい引数はすべて「無効」が既定。`bench_agents.py` の fingerprint 3 種
   （`773a71c15c5bc16e` / `677f28cc3b6995ee` / `6e39c2aa4b35d876`）が着手前と一致すること。
   `tests/test_value_bootstrap.py::test_planner_defaults_unchanged` が通ること。
2. **Python が真実源、Rust はその写し**（D-049・作業規約 1）。新しいつまみは Python と Rust の両方に入れ、
   `tests/test_value_bootstrap.py::test_vb_rust_matches_python` と同じ型の「毎手一致」検査で固定する。
   作業環境の wheel（新）とマスターの PC の wheel（旧）が**便 2 の交代までずれる**ので、Rust を要する新しい検査は
   「入っている Rust が新しい引数を受け付けなければ理由つきで skip」にする（§8 の冒頭）。**skip は「通った」ではない**——
   便 1 の完了判定は作業環境の新しい wheel で skip なしに通すこと。
3. **検査を先に書く**（作業規約 5）。落ちる状態で置いてから本体を書く。**検査が落ちた状態で「完了」としない。**
4. **覗き見監査を通す**（D-026）。相手のターンを想像で進める範囲が増える（`align_leaves`）ので必須。
5. **帯は §7 に登録済みのものを使う。** `seed0 + n − 1 ≤ end` を回す前に確かめる。記録の帯で評価しない。
6. **一度に 2 つ変えない。** 便 2 の測定は候補を別々に。
7. **champion を変えるのは D-034 の 5 条件が揃ってから、`champion.py`・`gauntlets/core5.json`・`webapp/agents.py` の 3 か所同時**
   （`tests/test_drl.py::test_champion_definition_is_consistent_everywhere` が食い違いを見つける）。
8. コメント・docstring・テスト名に rules の条項番号か D 番号を書く（作業規約 1）。文書は「である調」。

---

## 2. 便 1 — 探索器のつまみ 5 つ（Python → Rust → 作業環境で自前ビルド）

### 2.1 順番

| # | 作業 | 完了の判定 |
|---|---|---|
| 1 | `tests/test_d065.py` に §8 の T-1〜T-8 を書く（落ちる状態で置く） | 新検査が期待どおり fail する。既存検査は通ったまま |
| 2 | Python: `policy_net`／`policy_scope`（§2.2） | T-1・T-2 の Python 側が通る |
| 3 | Python: `choice_phases`／`solo_samples`（§2.3） | T-3・T-4 の Python 側が通る |
| 4 | Python: `align_leaves`（§2.4） | T-5 の Python 側が通る |
| 5 | Python: `tau`（§2.6） | T-7 の Python 側が通る |
| 6 | Rust: 2〜5 の写し＋`reeval_samples`（§2.5）＋記録形式 v3（§2.5）＋`PyPlanner` クラスの口（§2.7） | **作業環境で Linux wheel をビルドして入れ替える（§2.9）**。fingerprint 3 種不変 |
| 7 | Python: `drl_data.py` の v3 読み（§2.5） | T-8 が通る |
| 8 | 便 1 の完了報告（`D065_NOTES.md`）: fingerprint 3 種・検査の件数（skip 0）・wheel のファイル名 | **マスターの再ビルドはここでは依頼しない**（便 2 の §3.5 で 1 回） |

### 2.2 `policy_net`／`policy_scope` — 代打ちを π にする（レビュー A-5'）

**何を直すか**: Rust の spec には `policy_net`（段階 0・D-056）があり、`agents.rs::proxy_act` と `fallback_act` の両方で使われる。
Python（`meicho/greedy.py`）には無い。Python に同じものを足し、加えて**効かせる範囲を選ぶ口**を両方に足す。

**引数（`GreedyAgent.__init__` と `PlannerAgent.__init__` の両方。PlannerAgent は `super().__init__` に渡す）**:

```python
policy_net: str = None          # results/models/ 配下のファイル名か絶対パス（opp_policy_net と同じ扱い・load_net で読む）
policy_scope: str = "all"       # "all" | "proxy" | "fallback"
```

- `"all"`: Rust の現行どおり。探索の中の代打ち（`_proxy_act`）**と**担当外フェイズの実際の手（`act` の fallback 分岐）の両方を π にする。
- `"proxy"`: 代打ちだけ。担当外フェイズの実際の手は従来どおり H。
- `"fallback"`: 担当外フェイズの実際の手だけ。代打ちは従来どおり H／相手モデル。

**Python の実装（`greedy.py`）**:

```python
def _policy_pick(self, net, s, q) -> dict:
    """ネットの方策の最良手（同点は最初）。乱数は消費しない。Rust の `policy_pick(tau=0)` と同じ。"""
    acts = legal_actions(s, q)
    if len(acts) == 1:
        return acts[0]
    import numpy as np
    from .encode import action_code, encode
    ob = observe(s, q)
    x = np.asarray(encode(ob, q), np.float32)
    scores = net.policy_scores(x, [action_code(ob, a) for a in acts])
    return acts[int(np.argmax(scores))]
```

`_opp_act` の既存のネット分岐は `_policy_pick(load_net(self.opp_policy_net), s, q)` を呼ぶ形に畳む（挙動は同じ。`argmax` の同点処理も同じ）。

`_proxy_act` を **Rust の `proxy_act` と同じ順序**にする（順序が違うと一致しない）:

```python
def _proxy_act(self, s, q, me):
    # 1. 相手の対抗の提出は opp_policy_net が優先（root_only でないとき）— D-057
    if q != me and s.phase == Phase.CLASH_SUBMIT and not self.opp_policy_root_only \
            and self.opp_policy_net is not None:
        return self._opp_act(s, q, True)
    # 2. 代打ちの π（D-065）
    if self.policy_net is not None and self.policy_scope in ("all", "proxy"):
        return self._policy_pick(load_net(self.policy_net), s, q)
    # 3. 従来どおり
    if q == me:
        return self.fallback.act(s, q)
    return self._opp_act(s, q, not self.opp_policy_root_only)
```

`act` の fallback 分岐（`if s.phase not in self.phases or s.phase in (SETUP_CHARA, MULLIGAN): return self.fallback.act(s, pi)`）を
`return self._fallback_act(s, pi)` に替え、

```python
def _fallback_act(self, s, pi):
    if self.policy_net is not None and self.policy_scope in ("all", "fallback"):
        return self._policy_pick(load_net(self.policy_net), s, pi)   # tau は §2.6 で足す
    return self.fallback.act(s, pi)
```

**Rust の実装（`agents.rs`）**: `Greedy` に `pub policy_scope: u8`（0=all・1=proxy・2=fallback。既定 0）を足し、
`proxy_act` の `if let Some(net) = self.policy_net.clone()` を `if self.policy_scope != 2` で、
`fallback_act` の同じ分岐を `if self.policy_scope != 1` で囲む。spec（`lib.rs::spec_from_py`）に
`"policy_scope": "all"|"proxy"|"fallback"`（文字列。未知の値はエラー）を足し、`build_agent` で `p.g.policy_scope` に写す。

**Rust の `fallback_act` は `self.tau` と `self.rng` で soft_pick する**（既存）。Python も §2.6 で同じにする。
tau=0 のときは乱数を消費しない（`soft_pick` は tau≤0 で argmax）。**一致検査は tau=0 で行う。**

**判断が要る点として報告してよいもの**: `load_net` の cache は Python が `_NET_CACHE`、Rust が `net::load` の cache。
同じパスを上書きした場合の `forget_net` は既存どおり（新設不要）。

### 2.3 `choice_phases`／`solo_samples` — 選択フェイズを V で（レビュー A-1）

**何を直すか**: champion の担当フェイズは {ACTION, CLASH_SUBMIT, RUSH}。CHOICE と TURN_END_DISCARD を担当に加えられるようにし、
`_solo` の決定化を複数本の平均にできるようにする。**マリガンとリーダー選択は対象外のまま**（`act` の
`s.phase in (SETUP_CHARA, MULLIGAN)` の除外は残す。第 2 段は本書の範囲外）。

**引数（Greedy／Planner 両方）**:

```python
choice_phases: bool = False     # True で phases に Phase.CHOICE と Phase.TURN_END_DISCARD を加える
solo_samples: int = 1           # _solo の決定化の本数（1 = 従来どおり）
```

`PlannerAgent.__init__` の既定 `phases` は `{ACTION, CLASH_SUBMIT, RUSH}` のまま。`choice_phases=True` なら
`phases = set(phases) | {Phase.CHOICE, Phase.TURN_END_DISCARD}`。`phases` を明示した場合も `choice_phases` は加える側に働く。

**Python `_solo` の実装**:

```python
def _solo(self, s, pi, acts):
    n = max(1, self.solo_samples)
    totals = [0.0] * len(acts)
    for _ in range(n):
        t = self._determinize(s, pi)
        for i, a in enumerate(acts):
            totals[i] += self._score_solo(t, pi, a)
    return acts[max(range(len(acts)), key=lambda i: totals[i])]     # 同点は最初（従来の max と同じ）
```

`solo_samples=1` のとき、従来の `max(acts, key=...)` と**同じ手**を返すこと（同点処理も同じ）を T-3 が固定する。

**Rust**: `Greedy` に `pub choice_phases: bool`（既定 false）と `pub solo_samples: usize`（既定 1）。`Planner::new` の
`vec![Phase::Action, Phase::ClashSubmit, Phase::Rush]` の直後に、`choice_phases` なら `Phase::Choice` と `Phase::TurnEndDiscard` を push
（`build_agent` と `PyPlanner::new` の両方で。`Planner::new` に引数を足してもよい——**実装者が決めてよい**）。
`solo` を `solo_samples` 本にし、**Python も Rust も合計で argmax**（同点は最初）し、`last_scores` には平均を入れる（`clash` と同じ形）。
spec に `"choice_phases"`（bool）・`"solo_samples"`（usize）。

**注意**: `last_scores` が CHOICE でも入るようになるので、記録（`series_record`）の CHOICE 決定に探索値が付く。
これは意図どおり（V の教師が増える）。`pilot_tau_vb.py` の「探索した決定」の数が増えるので、便 4 で τ の下見をやり直す理由になる。

### 2.4 `align_leaves` — 対抗・連撃・選択の葉を「次の自分のターン開始」に揃える（レビュー A-2）

**何を直すか**: `_clash` と `_score_solo` の葉は `_settle` の地点（自分のターンなら相手のターンの開始）で V を当てている。
V が学習していない種類の局面である（レビュー §2.2）。`align_leaves=True` のとき、葉を**次に自分がターンプレイヤーになる
ターンの最初の非 CHOICE 局面**まで進めてから採点する。

**引数（Greedy／Planner 両方）**:

```python
align_leaves: bool = False
align_rollout: int = 80         # 進める最大手数（Planner の turn_rollout*2 に相当）
```

**Python の実装（`greedy.py`）**: 目標のターン `goal` は**決定した局面 `s`**（`_settle` の前）から決める。
自分のターン中の決定なら `goal = s.turn_no + 2`（次の自分のターン）、相手のターン中の決定なら `goal = s.turn_no + 1`。
`_settle` が返した局面がすでに goal に着いていれば 1 手も進めない（相手のターンの対抗はここに当たる＝従来と同じ葉）。

```python
def _value_to_my_turn(self, u, pi, goal) -> float:
    """turn_no が goal 以上の最初の非 CHOICE 局面まで固定方策で進めて採点する（D-065 A-2）。
    goal は決定した局面から `self._goal_turn(s, pi)` で決める。`planner._value_after_turn`（extra_turns=1）と同じ打ち切り。"""
    for _ in range(self.align_rollout):
        if u.outcome is not None or u.phase == Phase.GAME_OVER:
            break
        if u.turn_no >= goal and u.phase != Phase.CHOICE:
            break
        need = decision_players(u)
        if not need:
            break
        u = apply_owned(u, {q: self._proxy_act(u, q, pi) for q in need})
    return self._eval(u, pi)

def _goal_turn(self, s, pi) -> int:
    return s.turn_no + (2 if s.turn_player == pi else 1)
```

`_score_solo(t, pi, a, goal=None)`: `align_leaves` なら `self._value_to_my_turn(self._settle(apply(t, {pi: a}), pi), pi, goal)`、
でなければ従来どおり `self._eval(self._settle(...), pi)`。`_solo` と `_clash` は `goal = self._goal_turn(s, pi)` を 1 回だけ計算して渡す。
`_clash`: `nxt = self._settle(...)` のあと `align_leaves` なら `_value_to_my_turn(nxt, pi, goal)`。

**注意（自分のアクションフェイズ中の CHOICE＝レベルアップの捨て札）**: `_settle` は自分の ACTION に戻って止まるが、goal は
次の自分のターンなので、**残りのアクションフェイズ・対抗・相手のターンを代打ち（H か π）で進めた先**が葉になる。
これは計画探索の `to_clash` の葉と同じ扱いである。「自分の ACTION に戻った時点で止める（そこも学習分布の中）」という
別解もあり、便 2 の `a1`＋`a2` が `a1` 単独より悪ければその別解を**判断が要る点として報告**する。

**共通乱数（CRN）**: `_clash` と `_solo` の**各決定化の直後**に `crn = (self.fallback.rng.getstate(), self.opp_model.rng.getstate())`
を取り、候補ごとの `apply` → `_settle` → `_value_to_my_turn` の**前に** `setstate` で戻す（`planner._plan` の CRN と同じ理由: 相手のターンを H が
乱数で打つので、候補ごとに乱数列が違うと揺れが優劣に化ける）。**CRN を戻すのは `align_leaves=True` のときだけ**
（False のときに戻すと既定の挙動が変わる）。Rust も同じ位置で同じことをする。

`u.turn_player` が GameState に無ければ `observe` の `turn_player` に相当する属性名を `state.py` で確かめる（`s.turn_player` は
`tests/test_value_bootstrap.py::_first_action_phase` で使われているので存在する）。

**Rust**: `Greedy` に `align_leaves: bool`・`align_rollout: usize`。`value_to_my_turn` を `settle` の隣に書く。`step_proxy` を使う。
spec に `"align_leaves"`（bool）・`"align_rollout"`（usize・既定 80）。

**監査**: T-6（覗き見監査）は `align_leaves=True` を含む構成で回す。

### 2.5 `reeval_samples` と記録形式 v3 — 二重推定（レビュー A-3 (i)・Rust だけ＋読み側）

**何を直すか**: 記録の教師は「根の探索値の最大値」で、決定化の揺れを最大で拾うため楽観する（レビュー §2.3・+0.17）。
選んだ手を**別の決定化で取り直した値**（fresh）を記録に足す。学習側（便 3）が `--vtarget fresh` で使う。

**Rust（`agents.rs`）**: `Greedy` に `pub reeval_samples: usize`（既定 0）と `pub last_fresh: f64`（既定 NaN）。

- `Planner::plan` の最後、`keys[bi]` を決めた**あと**に `if self.g.reeval_samples > 0 { self.g.last_fresh = self.reeval_plan(db, s, pi, &keys[bi]); }`。
  `reeval_plan` は `plan` の 1 決定化ぶんのループを `reeval_samples` 回まわし、`alive = Some(vec![chosen])`（根を chosen だけに絞る）で
  `search` を呼び、`best_here` の chosen の値を平均して返す。決定化は `self.g.determinize`（**新しい**乱数の続き＝別の決定化）。
- `Greedy::clash`: 選んだ `acts[bi]` を `reeval_samples` 本の新しい決定化で採点し直して平均（`opp_act` も新しい決定化で引く）。
- `Greedy::solo`: 同じ。
- `Planner::act` の先頭で `self.g.last_fresh = f64::NAN` にする（`last_scores.clear()` の隣）。

**記録形式（`lib.rs::run_one_record`）**: ヘッダの version を **3** にし、レコードの `z f32` の直後に `fresh f32` を足す
（値は `ags[pi].last_fresh()`。探索していない決定・reeval_samples=0 なら NaN）。`AnyAgent` に `last_fresh()` を足す
（Planner→`p.g.last_fresh`、Challenger→`c.planner.g.last_fresh`、Greedy→`g.last_fresh`、それ以外 NaN）。

**Python（`meicho/drl_data.py`）**: `read_records` が version 2 と 3 の両方を読む。`Records` に `fresh: np.ndarray`（float32 [n]）を足し、
v2 は NaN で埋める。`REC_HEAD` を版で切り替える（v3 は `"<qIHBBBBff"`）。docstring の形式説明を更新。
既存の記録（vb1_*〜vb4_*）は v2 のまま読めること（T-8）。

**既定の挙動は不変**: `reeval_samples=0` なら探索は 1 回も増えず、記録の中身は `fresh` 列（NaN）が増えるだけ。
**ただし記録ファイルの形式は変わる**ので、`drl_train.py`・`pilot_tau_vb.py`・`pick_lambda_vb.py`・`test_drl.py` など
`read_records` を使うところが v3 で動くことを確かめる（T-8）。

### 2.6 `tau` — Python 側の確率化（レビュー B-3 の準備）

Rust の `Greedy.tau`（`solo`・`clash`・`plan`・`fallback_act` の `soft_pick`）を Python に写す。

```python
tau: float = 0.0
```

`greedy.py` に Rust と同じ `soft_pick(values, tau, rng)` を書く（`rng.random()` を 1 回だけ消費。tau≤0 なら argmax・同点は最初。
`values.len() <= 1` なら 0）。`_solo`・`_clash`・`_plan`（`planner.py` の `best = max(...)` の箇所）・`_fallback_act` で
`tau > 0` のとき `soft_pick` を使う。乱数は **`self.rng`**（Rust の `self.rng` と同じ。`fallback.rng` ではない）。
tau=0 のとき挙動不変（乱数を消費しない）。T-7 は tau=0.01 で Python と Rust が同じ手を選ぶことを固定する
（両者の rng は同じ PyRandom の写しなので、消費の順序が同じなら一致する。**一致しなければ消費の順序が違う**）。

### 2.7 `PyPlanner` クラスの口（`lib.rs`）

`PyPlanner::new` の signature に次を足す（すべて既定で無効）:
`policy_net=None, policy_scope="all", choice_phases=false, solo_samples=1, align_leaves=false, align_rollout=80, reeval_samples=0, tau=0.0`。
中身は `build_agent` の Planner 分岐と同じ写し方。**spec 経由（`series`）とクラス経由で同じ挙動になること**を T-2 が使う。

### 2.8 `registry.py`・`vb.py`・`champion.py`

- `registry.py`: 新しい引数は `PlannerAgent` の kwargs としてそのまま通る（`Mk`）。登録名は増やさない。
  `planner_vb` の kwargs 例のコメントに `policy_net`／`policy_scope`／`samples`／`choice_phases`／`solo_samples`／`align_leaves` を足す。
- `champion.py`: `spec()` の `resolve_model` の対象に `"policy_net"` を足す。`describe()` に代打ち π・選択 V・葉の整列・samples を出す
  （**便 2 で champion を替えるときまで `CHAMPIONS` は触らない**）。`factory_for` は変えない（`value_net` があれば `planner_vb`）。
- `vb.py`: `spec()` の `resolve_model` の対象に `"policy_net"` を足す。**便 4 まで `kwargs_for` は変えない**（loop 1 の定義を壊さない）。

### 2.9 作業環境で Linux wheel をビルドする（便 1 の 6 番目）

作業環境（Linux・2 コア）には `cargo`・`rustc` が入っている（`/root/.cargo/bin`）。`maturin` は `pip install maturin`。

```bash
cd <engine>/rust
maturin build --release --out dist
ls dist                                  # 新しい wheel の名前を確かめる（manylinux_2_34_x86_64 か linux_x86_64）
pip install --force-reinstall --no-deps dist/<新しい wheel のファイル名>
cd <engine>
python3 experiments/bench_agents.py     # 3 種が 773a71c15c5bc16e / 677f28cc3b6995ee / 6e39c2aa4b35d876
python3 -m pytest tests -q               # 全通過・skip は画像の検査だけ
```

- `ls dist` に古い manylinux の wheel（8/31 ビルド）が残っていても消さない（マスターの PC の Windows wheel と対で置いてある）。
  **新しい wheel も `dist/` に残す**（マスターの PC には使えないが、次のセッションの作業環境が再ビルドせずに使える）。
- fingerprint が 1 つでも違ったら止める（§1-1）。`test_d065.py` の一致検査が落ちたら §9-1〜3。
- 作業環境に `cargo` が無い場合（別の環境で引き継いだとき）は `rustup` を入れる。入れられなければ**判断が要る点として報告**
  （そのときだけ、マスターの再ビルドを便 1 に前倒しする）。

---

## 3. 便 2 — 測定と champion 交代

### 3.1 道具 `experiments/probe_d065.py`（新設・`probe_strength_candidates.py` を型に）

候補 = champion の kwargs に差分を重ねたもの。**すべて Rust（spec）で回す**。差分の表:

| 名前 | 差分 | 帯（§7・2,500 幅の先頭） |
|---|---|---|
| `a0` | `{"samples": 12}` | 440100 |
| `a1` | `{"choice_phases": True, "solo_samples": 4}` | 442600 |
| `a2` | `{"align_leaves": True}` | 445100 |
| `a12` | a1 ＋ a2 | 447600 |
| `a5` | `{"policy_net": "drl_sd001_vb3.json", "policy_scope": "proxy"}`（Python 実装後の再確認・scope=proxy で「代打ちだけ」の値を取る） | 450100 |
| `all` | a0 ＋ a12 ＋ a5 | 452600 |

各候補につき: 門番（vs 現 champion・n=1,200・帯先頭 +0）→ 錨 3 種（`eval_vb.paired_diff`・各 n=300・+1300 H／+1600 貪欲／+1900 素 planner）。
結果は `results/vb/d065_<名前>.json`。**門番が境界（下端 0.5 ±0.01）なら 455100.. で n=2,400 の追試**（1 候補ぶんしか幅が無いので、
2 つ目が境界なら判断が要る点として報告）。

**先にやる下見（`a1` の前）**: `experiments/diag_choice_agreement.py`（新設・Python）。vb3 対 H を 100 局（帯 470000..470099）、
CHOICE 決定ごとに「H の手」と「`choice_phases=True, solo_samples=4` の手」を並べ、種類（PayOrDamage／Discard／UseOptional／
RevealCount／SwitchBack／Order／TurnEndDiscard）ごとに**違う手を選んだ割合**を出す。**違う手を選ぶ割合が全種類で 0 なら a1 は効きようが
無いので、a1 の門番を回さず報告する。**

### 3.2 読み方（採否）

- 門番: 下端 > 0.5。錨: 3 種のどれも「差の区間が 0 をまたがず悪化」でない（設計書 §7.1）。
- `a5` は Rust で測った 0.614 の再確認である。**大きくずれたら Python 実装の前に Rust の `policy_scope` の実装を疑う**
  （`proxy_pi` の 0.614 は scope=all で取った値。scope=proxy で同じ程度なら「利得は代打ち側」が確定する）。
- `a0`・`a1`・`a2` は単独の効果。`all` が単独の和を大きく下回るなら、干渉している（例: `align_leaves` と `samples 12` が
  同じ揺れを二重に潰している）。その場合は `all` から 1 つ抜いた版を追加で測る（帯は予備 457500.. を使い、登録を更新）。

### 3.3 ラダー

門番と錨を通った候補を `gauntlets/core5.json` に足して回す（登録名は `planner_vb`・kwargs に差分）。
**`policy_net` を含む候補は 12 倍遅い**（2 スレッドで 0.26 局/秒）。core5 は 10 体・約 2 時間が、この候補 1 体で +20 時間になる。
対策: (a) ラダーは `all` の 1 体だけ足す (b) `n` を落とさない（Elo の区間が広がる）(c) 無人で回す。
**それでも 1 日かかるなら判断が要る点として報告**（候補: 代打ちの範囲の絞り込み＝§9-4 の速度の手当てを先にする）。

### 3.4 champion 交代（D-034 の 5 条件）

道具は `experiments/champion_challenge_vb.py`。ただし現状は挑戦者を `vb.kwargs_for(deck, k)`（loop 1）からしか作れないので、
**挑戦者の kwargs を JSON 文字列で渡す口 `--challenger-json '{...}'` を足す**（`--vb` と排他）。帯は `--seed0 550000`
（OFFSETS は道具のまま: 直接対決 +0／対照 +1300／監査 +2600／追試 +3000）。

1. 直接対決 vs 現 champion（`planner_vb3`）: 550000..551199・n=1,200・下端 > 0.5。**対照**（現 champion どうし）551300..552499 が 0.5 を区間に含むこと。
2. ラダー core5 で 1 位相当。
3. 覗き見監査（同じ道具・552600..552602）違反 0。
4. fingerprint（digest 6 局）を記録。
5. **判断は人が行う** → マスターに報告し、裁定を待つ。

交代したら `champion.py`（`CHAMPIONS["SD001"]`・`describe`）・`gauntlets/core5.json`（版を上げ `"champion"` を書き換え）・
`webapp/agents.py`（既定の相手・ラベル・Elo）の 3 か所を**同時に**。`test_champion_definition_is_consistent_everywhere` が通ること。
`vb.py` は触らない（loop 1 の π₀ 据え置き。便 4 で loop 2 を別に定義する）。

### 3.5 マスターの PC の再ビルド（交代の直前に 1 回・§10 の文をそのまま）

裁定（2026-09-03）により、マスターの PC の Rust を入れ替えるのは**ここで 1 回**である。順番は次のとおり。

1. §3.4 の 1〜4 が揃い、マスターが 5（交代の裁定）を出す。
2. 3 か所を同時に変える**前に**、§10 の依頼文でマスターに再ビルドを頼む。理由: 交代後はマスターの PC で `pytest` を全部通す必要があり、
   古い wheel のままだと `test_d065.py` の一致検査が skip のままになる（**skip は「通った」ではない**・§1-2）。
3. マスターの PC で fingerprint 3 種一致・全検査通過（skip は画像の検査だけ）を確かめてから、3 か所を変えて交代する。
4. アプリで 1 局打って速度の体感を報告に書く（新 champion に `policy_net` が入る場合、1 手 約 0.7 秒の見込み）。

**交代の候補が `samples 12` だけだった場合も再ビルドは要る**——アプリ（Python）は動くが、マスターの PC の検査が通らないままになるため。
再ビルドが何らかの理由でできないときは、交代を止めるのではなく、**「マスターの PC では一致検査が skip のまま」と報告に明記して**交代する
（判断が要る点として挙げる）。

---

## 4. 便 3 — 学習側（Python だけ・レビュー A-3 (ii)(iii)・A-4）

### 4.1 `drl_train.py`

- `--vtarget fresh` を足す: `Batcher.vsearch` に `recs.fresh` を使い、NaN のところは `max` で埋める（fresh が無い v2 の記録でも動く）。
- `--calib-by {none,phase_turn}`（既定 `none`）: `phase_turn` なら較正を「phase × 自分のターンか」の層ごとに取る。
  層の鍵は `recs.phase`（0〜7）と `obs[:, 14]`（`encode.py` の scal の 15 番目 = `turn_player == pi`）。
  **層の決定数が 1,000 未満なら全体の較正に落とす**（`calibrate_vsearch` が 1,000 未満で落ちるため）。
  meta に層ごとの `{a, b, c, n, spread, logloss, base}` を残し、**層ごとの「教師 p の広がり」を出力**する。
- `--select target_v`（新設・任意）: 保存する版を「検証の**教師**（`target`）に対する対数損失」で選ぶ（現行 `best_v` は z に対する損失）。
  検証側の較正は**学習側の較正をそのまま当てる**（`va.set_lam(args.lam, calib)`・valid で取り直さない）。`evaluate()` に
  `t_logloss`（`target` に対する二値交差エントロピー）を足し、`BestKeeper` に `"t"` の鍵を足す。

### 4.2 `experiments/diag_optimism.py`（新設・楽観の診断）

レビュー §2.3 の診断を道具にする。入力: 記録ファイル（接頭辞）とネット。出力: 「局面の種類（phase × turn）ごとの V の平均 vs z」
と「探索した決定の根の最大値の平均 vs z」「fresh の平均 vs z（v3 のとき）」。JSON と表。
**便 4 の毎反復で `eval_vb.py` の後に回し、報告に貼る**（楽観が反復ごとに縮んでいるかが A-3 の効きの指標）。

### 4.3 A-4 学習の衛生（記録を取り直さず・任意・一晩）

反復 3 の記録（`results/drl/vb3_*`・作業環境に無ければ manifest から再生成）で `--wd 1e-4`／`--lr 3e-4`／`--wp 0`／`--wp 0.3`／
`--hidden 128`／`--select target_v` を 1 本ずつ学習し（`--init drl_sd001_vb2.json`・V_3 と同じ条件で）、
`eval_vb.py --iter 4 --new-net <版> --skip-canary --skip-anchors --seed0 <帯>` で **V_3 版と門番**
（`--iter 4` にすると「新 = 反復 5 の版の葉を差し替えたもの」「前 = 反復 4 の版 = 葉が V_3」になる）。
帯は**未登録**——`next_free`（登録時の値。2026-09-03 時点 610000）から 4,000 幅 × 本数を「A-4 学習の衛生の門番」として登録してから回す。
**どれか 1 本でも下端 > 0.5 なら便 4 の学習条件に採る。** 無ければ現行（lr 1e-3・wd 0・wp 1・best_v）のまま。

---

## 5. 便 4 — 輪の再始動（loop 2・レビュー A-7）

### 5.1 `vb.py` に `loop` を足す

```python
LOOPS = {
    1: {"search": {"extra_turns": 1}, "init": "drl_sd001_s1.json", "prefix": "drl_sd001_vb",
        "pi_proxy": False},
    2: {"search": {"extra_turns": 1, "samples": 12, "choice_phases": True, "solo_samples": 4,
                   "align_leaves": True, "reeval_samples": 4},    # ← 便 2 で採った組み合わせに合わせる
        "init": "drl_sd001_vb3.json", "prefix": "drl_sd001_vc",
        "pi_proxy": True},        # 反復 k の代打ちに V_{k-1} のファイルの π 頭を使う（policy_scope="proxy"）
}
```

`kwargs_for(deck, k, loop=1)`: loop 2 の反復 k は `value_net = V_{k-1}`、`policy_net = V_{k-1} と同じファイル`（`pi_proxy` のとき）、
`opp_policy_net = π₀`（据え置き・変えない）。**k=4' の V_{k-1} は `drl_sd001_vb3.json`**（loop 1 の V_3。`init` と同じ）。
`model_name(deck, k, loop)` は `prefix + str(k)`。`describe`・`spec`・`make` に `loop` を通す。
`drl_record.py --vb k --loop 2`、`eval_vb.py --iter k --loop 2 --seed0 <§7 の帯>`、`pilot_tau_vb.py --loop 2`、
`pick_lambda_vb.py --loop 2` に `--loop`（既定 1）を足す。**loop 1 の定義と既定の挙動は変えない**（T-12）。

**注意**: loop 2 の反復 4' の記録エージェントは「V_3 の葉＋V_3 の π 頭の代打ち＋新しい探索器」で、門番は
「反復 4' の版（V_4'）vs 反復 3'（= V_3 を載せた**同じ探索器**）」でなければならない。探索器が違うと探索器の差を V の差と取り違える。
`eval_vb.py` の `specs_for` が loop 2 では `kwargs_for(deck, k, loop=2)` と `kwargs_for(deck, k+1, loop=2)` を使うので自然にそうなる。
`model_name(deck, 3, loop=2)` は **`drl_sd001_vb3.json`**（loop 1 の V_3）を返すこと（T-12）。

### 5.2 1 反復の輪（設計書 §5.2 と同じ・違いだけ書く）

- 記録: `--loop 2`。τ の下見は**必ず**やり直す（`choice_phases` で探索した決定が増え、尺度も変わる）。混合率 10〜30%。
- 学習: `--init <V_{k-1}> --vtarget fresh --calib-by phase_turn --calib-scale bulk --lam 0.7 --select best_v`（便 3 の A-4 で変えた条件があればそれ）。
  **fresh が NaN の決定（探索していない決定）は max→z の順に落ちる**ことを確かめる。
- 評価: `eval_vb.py --loop 2 --seed0 <帯>` ＋ `diag_optimism.py`。
- 速度: `policy_net` の代打ちで **記録は 12 倍遅い**。2 スレッドで 9,650 局 ≈ 10 時間。**Kaggle（4 コア）で回す**か、
  §9-4 の速度の手当て（代打ちの範囲の絞り込み）を先に入れる。**判断が要る点として、最初の反復の前に報告する。**

### 5.3 停止条件

設計書 §7.5（3 反復連続で門番不通過）に加え、`diag_optimism` の「根の最大値 − z」が反復ごとに縮まないなら A-3 が効いていない
（停止ではなく報告）。反復 4' で門番を越えたら、D-034 の手順（§3.4）で champion 交代の判定へ（帯は便 2 で 550000.. を使っていれば `next_free` から新規登録）。

### 5.4 報告

反復ごとに `VALUE_BOOTSTRAP_NOTES.md` の便の形式で `D065_LOOP2_NOTES.md` に追記（結論先・数字に区間・読み方）。
`decisions.md` に 1 節。

---

## 6. 便 5 — 発見ループと対人アプリ

### 6.1 B-2 発見ループを新 champion に向ける

`discovery.py` の `BANDS["SD001"]` の**末尾に** 460000 を足す（列の並びを変えない・D-053）。champion は `champion.py` から読む
（`--champion` に δ は無し）。`--gens A,C` で 1 巡、次に `--gens B`。**発見 0 件が期待される結果**。
下端 > 0.5 の δ が出たら、それはマスターが見つける前に塞ぐ穴であり、判断が要る点として報告する（δ 介入の教材にもなる）。
`--out` を必ず付ける（既定名は既存の報告を消す・discovery_loop の運用規則）。

### 6.2 B-3 対人アプリだけ対抗を確率化

`webapp/agents.py` の `OPPONENTS[<champion 名>]["kwargs"]` に `"tau": 0.003` を足す**のではなく**、アプリ専用の登録名
`<champion 名>_app`（例 `planner_vb3_app`）を足し、`DEFAULT_OPPONENT` をそれにする。理由: `test_champion_definition_is_consistent_everywhere`
が champion の kwargs の一致を見るので、champion 自体に tau を入れるとラダーと食い違う。**ラダー・輪には tau を入れない。**
`available()`・`build()` はそのまま。混合率の目安 5〜15%（`pilot_tau_vb.py` の型で 200 局・帯 471000..471099）。

---

## 7. シード帯（`seed_bands.json` に**登録済み**・`next_free` = 610000。600000..609999 は §12.5・560000..599999 は未使用の予備）

| 帯 | 用途 |
|---|---|
| 440100..459999 | 便 2 の測定。候補ごとに 2,500 幅（a0 440100／a1 442600／a2 445100／a12 447600／a5 450100／all 452600／追試 455100／予備 457500）。幅の中: 門番 +0（1,200）／錨 H +1300／貪欲 +1600／素 planner +1900（各 300）／予備 +2200 |
| 460000..469999 | B-2 発見ループ（`BANDS["SD001"]` の末尾に追加。2 巡で 1 帯） |
| 470000..479999 | 診断（強さは読まない）: `diag_choice_agreement` 470000..470099／楽観の診断 470200..470999／速度・τ の下見 471000..471099 |
| 480000..529999 | loop 2 の記録（反復ごと 10,000 幅・内訳は D-064 と同じ）。**評価に使わない** |
| 530000..549999 | loop 2 の評価（反復ごと 4,000 幅・`eval_vb.py --seed0`） |
| 550000..559999 | champion 交代の判定・1 回ぶん（`champion_challenge_vb.py` の OFFSETS: 直接対決 +0／対照 +1300／監査 +2600／追試 +3000..5399）。2 回目は `next_free` から登録 |

**回す前に `seed0 + n − 1 ≤ end` を確かめる。** 足りなければ予備を使い、台帳の `purpose` を更新する。
A-4（§4.3）の門番の帯は未登録——**登録してから回す**（`next_free` から 4,000 幅）。

---

## 8. 検査の一覧（`tests/test_d065.py`・本体より先に書く）

**Rust を要する検査（T-2・T-4・T-5・T-7・T-8）の skip 規則**: `meicho_rs` が無ければ `pytest.importorskip`。あっても
**入っている Rust が新しい引数を受け付けなければ skip する**（マスターの PC は便 2 の交代まで古い wheel のまま・§1-2）。
判定は `tests/test_d065.py` の先頭に置くヘルパーで行う:

```python
def _rs_has_d065():
    rs = pytest.importorskip("meicho_rs")
    try:
        rs.PlannerAgent(0, policy_scope="all")      # 便 1 で足した引数。古い wheel では TypeError
    except TypeError:
        pytest.skip("Rust が D-065 便 1 より古い（未再ビルド）。作業環境では §2.9、マスターの PC では §3.5 のあとに通る")
    return rs
```

skip されたことは `pytest -q` の末尾に `s` の数として出る。**便 1 の完了判定は skip 0（画像の検査を除く）で通すこと。**

| # | 検査 | 固定する性質 |
|---|---|---|
| T-1 | `test_defaults_unchanged_d065` | 新しい引数の既定値で `PlannerAgent` の属性が無効（`policy_net None`・`policy_scope "all"`・`choice_phases False`・`solo_samples 1`・`align_leaves False`・`tau 0.0`）で、`BASELINE_DIGESTS_230000` と一致（`test_planner_defaults_unchanged` と同じ型）。spec `PLANNER(POOL)` に新しい鍵が漏れていない |
| T-2 | `test_policy_net_python_matches_rust` | `policy_net`（乱数ネット）＋`extra_turns=1`＋`value_net` で Python と Rust が毎手同じ手（`test_vb_rust_matches_python` の型）。`policy_scope` の 3 値すべて |
| T-3 | `test_solo_samples_1_is_identical` | `solo_samples=1` の `_solo` が従来と同じ手（同点処理込み）。`choice_phases=False` なら CHOICE は `fallback.act` と同じ手 |
| T-4 | `test_choice_phases_python_matches_rust` | `choice_phases=True, solo_samples=4, value_net=乱数ネット` で毎手一致。加えて `_eval` を spy して CHOICE 決定で V が呼ばれること |
| T-5 | `test_align_leaves_stops_at_my_turn` | `_eval` を spy: `align_leaves=True` の対抗・連撃・選択の葉は `outcome is not None` か `(turn_no >= goal and phase != CHOICE)`（goal は決定局面から `_goal_turn`）。自分のターンの対抗では葉の `turn_player == pi`。`align_leaves=False` では従来どおり（葉の turn_no が変わらない）。Python/Rust 毎手一致 |
| T-6 | `test_nopeek_audit_d065` | `policy_net`＋`choice_phases`＋`align_leaves`＋`samples=12` の構成で `replay_audit` 違反 0（`node_cap=120`） |
| T-7 | `test_tau_python_matches_rust` | `tau=0.01` で Python と Rust が毎手同じ手（同じシード）。`tau=0` では乱数を消費しない（`rng.getstate()` 不変） |
| T-8 | `test_record_v3_fresh` | `series_record` の出力が v3 で `fresh` を持ち、`reeval_samples=0` なら NaN・`>0`（`value_net` を積んだ構成）なら [0,1] の値。v2 のファイル（既存の `results/drl/` にあれば。無ければ検査内で v2 のバイト列を手で作る）が読める |
| T-9 | `test_vtarget_fresh_falls_back` | `--vtarget fresh` は fresh が NaN の決定で max に落ち、両方 NaN なら z |
| T-10 | `test_calib_by_phase_turn` | 層ごとに (a,b) が別に取れ、1,000 未満の層は全体に落ちる。層の鍵が `obs[:,14]` と `phase` |
| T-11 | `test_diag_optimism_runs` | `diag_optimism.py` が小さな記録で表を返す（数値の意味は問わない） |
| T-12 | `test_loop2_definitions` | `vb.kwargs_for(deck, k, loop=1)` は従来と完全に同じ dict。loop 2 は `value_net`＝`policy_net`＝V_{k-1}・`opp_policy_net`＝π₀・`init` が `drl_sd001_vb3.json`・絶対パス無し |
| T-13 | `test_seed_bands_d065` | §7 の帯が登録済みで重なりが無い（既存の `test_seed_bands_registered` を延ばしてもよい） |

既存 473 件（`472 passed, 2 skipped`＋1）が全部通ったままであること。

---

## 9. 転びやすいところ（症状 → 意味 → 直し方）

| # | 症状 | 意味 | 直し方 |
|---|---|---|---|
| 1 | T-2 が「step N で python と rust が違う」 | `_proxy_act` の分岐の**順序**が Rust と違う／`_policy_pick` の同点処理（argmax は最初）が違う／`load_net` のパス解決が違う | §2.2 の順序に揃える。`np.argmax` は最初の最大を返すので同じ |
| 2 | T-4 で CHOICE の手が違う | Rust の `solo` が `restricted_legal` を使い Python が `legal_actions` を使う（δ 無しなら同じはず）／`solo_samples` の平均の丸め | 合計で比べる（平均で割らない）か、両方とも同じ順で足す |
| 3 | T-5 で葉が相手のターン開始のまま | `_clash` のほうを直し忘れ／`goal` の式が turn_player を見ていない | §2.4 の式。`u.turn_player` は `_settle` 後の `u` で見る |
| 4 | `policy_net` を入れると 12 倍遅い | 仕様（レビュー §4 A-5）。代打ち 1 決定ごとにネットを読む | 便 2 は n を落とさず時間で払う。**速度の手当て**（判断が要る点として報告してから）: (a) `policy_scope="proxy"` に加え、代打ちの範囲を「相手の ACTION フェイズと自分の対抗」に絞る第 4 の値 `"proxy_lite"` を足す (b) 幹 64・頭 32 の小さな π を `drl_train.py --hidden 64 --phead 32 --wv 0` で蒸留 |
| 5 | fingerprint が 1 つでも違う | 既定の挙動を変えてしまった（CRN の戻し・`_solo` の同点処理・`phases` の既定など） | **止めて原因を探す。** 便 2 に進まない |
| 6 | `read_records` が v3 で落ちる | `REC_HEAD` の切り替え忘れ／`fresh` の 4 バイトを飛ばしていない | §2.5。v2 のファイルで回帰検査（T-8） |
| 7 | 便 2 の `a5` が 0.614 から大きく下がる | `policy_scope="proxy"` の実装で `fallback_act` 側も切れている、または逆 | T-2 の 3 値で `_proxy_act`／`_fallback_act` の出力を個別に比べる |
| 8 | 門番が境界（下端 0.5 ±0.01） | 揺れ | 別帯 n=2,400（455100..）。2 つ目は判断が要る点 |
| 9 | `test_champion_definition_is_consistent_everywhere` が落ちる | 3 か所のどれかを直し忘れ | `champion.py`・`gauntlets/core5.json`・`webapp/agents.py` |
| 10 | 記録の帯で評価しようとして `check_record_band` 以外で止まらない | 評価側には帯の検査が無い | §7 の表を見て手で確かめる（`seed0 + n − 1 ≤ end`） |
| 11 | Rust の `maturin build` が作業環境で通らない | `cargo`/`rustc`/`maturin` のどれかが無い（作業環境には `/root/.cargo/bin` に cargo がある。無い環境で引き継いだとき） | `rustup` と `pip install maturin` を入れる（§2.9）。入れられなければ判断が要る点として報告し、そのときだけマスターの再ビルド（§10）を便 1 に前倒しする |
| 12 | マスターの PC で `test_d065.py` の一致検査が `s`（skip）になる | マスターの PC の wheel が古い（便 2 の交代まではこれが正常） | 便 2 の §3.5 で再ビルドしてから通す。**skip を「通った」と報告しない** |

---

## 10. マスターへの依頼文（Rust 再ビルド・**便 2 の champion 交代の直前に 1 回**・§3.5 でそのまま使う）

**なぜ今それが要るのか**: 便 1 で `rust/src/agents.rs` と `rust/src/lib.rs` に新しいつまみ（代打ち π の範囲・選択フェイズ・葉の整列・
二重推定・確率化）を足し、便 2 でそれを使う版が champion 交代の条件を満たした。Rust のソースを変えても、入っている `.pyd` は
自動では入れ替わらない。入れ替えないと、マスターの PC では Python 版と Rust 版の毎手一致の検査（`tests/test_d065.py`）が
**skip のまま**（「Rust が未再ビルド」と出る）で、交代後の全検査通過が確かめられない。**既定値ではすべて無効**で、既存の挙動は変わらない。
これまでの測定は作業環境（Linux）で自前にビルドした wheel で取ってあり、この再ビルドで数字が変わることはない。

1. **どこで**
   ```
   C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine\rust
   ```
2. **何を打つか**（1 行ずつ。先に開いている Python・pytest・対人アプリのサーバーを閉じる）
   ```bat
   cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine\rust
   maturin build --release --out dist
   pip install --force-reinstall --no-deps dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl
   ```
3. **成功したらどう見えるか**: 2 行目の最後に `📦 Built wheel for CPython 3.11 to dist\meicho_rs-0.1.0-cp311-cp311-win_amd64.whl`、
   3 行目の最後に `Successfully installed meicho-rs-0.1.0`。
4. **確認のしかた**
   ```bat
   cd C:\Users\奥村優斗\OneDrive\ドキュメント\eclipse_workフォルダ\meicho_engine_v0.1\engine
   python experiments\bench_agents.py
   python -m pytest tests -q
   ```
   `bench_agents.py` の 3 行が `773a71c15c5bc16e` / `677f28cc3b6995ee` / `6e39c2aa4b35d876` と一致し、`pytest` が全部通る
   （件数は 473＋新規 13 件前後。マスターの PC では画像の検査も走るので少し多く出る）。
   **再ビルドの前**に同じ `pytest` を打つと、末尾に `s`（skip）が数件出るのが正常で、**再ビルドの後は skip が消える**。
   これが「入れ替わった」ことの確認になる。
5. **転びやすいところと症状**

   | 症状 | 意味 | 直し方 |
   |---|---|---|
   | `maturin` が見つからない | ビルド道具が無い | `pip install maturin` |
   | `pip install` が「そんなファイルは無い」 | 2 行目が失敗している／ファイル名が違う | `dir dist` で名前を見て打ち直す |
   | `アクセスが拒否されました` | `.pyd` を掴んでいるプロセスがある | Python・pytest・アプリを閉じて 3 行目をやり直す |
   | `Successfully installed` と出るのに `test_d065.py` が skip のまま | `--force-reinstall` を忘れた（古い `.pyd` が残っている） | 3 行目をそのまま打ち直す |
   | fingerprint が 1 つでも違う | **既定の挙動が変わっている（実装のミス）** | **止めて報告。**便 2 に進まない |
   | `test_d065.py` の一致検査だけ落ちる | Rust の写しが Python と違う（§9-1〜3） | 落ちた検査名とメッセージをそのまま報告 |

（Linux 用の wheel は便 1 で作業環境が自前にビルドしている（§2.9）。マスターの PC でビルドした Windows 用 wheel は Linux では使えず、
その逆も同じである。）

---

## 11. 成果物と報告

- 便ごとに `D065_NOTES.md` に便の形式で追記（結論先・数字に区間・読み方・使った帯・判断が要る点）。
- `decisions.md` に便ごとに 1 節（「D-065 便 N」）。
- `README.md` の索引に `D065_IMPLEMENTATION_PLAN.md` と `D065_NOTES.md` を足す。
- champion を替えたら `results/ladder.md` を更新し、`webapp/agents.py` の Elo 表示も直す。

---

## 12. 追記（2026-09-03・マスター対 planner_vb3 の 2 局から）— A-8 対抗の相手モデルを広げる

根拠は `HUMAN_GAMES_20260903_NOTES.md`（以下「所見」）。要点: 2 局とも負けを決めた対抗で AI は詰みの烈火を持っていたのに
パス／青を選んだ。原因は `_clash` が決定化ごとに相手の提出を **π₀ の最尤 1 手**に決めることで、π₀ が「安い赤・緑を対抗に出す」
列にほぼ 0 を与える（真の手札で 闘志 0.05・鉤縄 0.00）ため、その列が評価から消える。**便 2 の本命 a15（a1＋a5）でも
両局面の選択は変わらない**（新しい `meicho/` で確認。所見 §3）。samples 12・24 でも変わらない。

### 12.1 つまみ `opp_mix`（便 1 の 6 番目・Python と Rust・既定 0.0 で挙動不変）

- `GreedyAgent.__init__` に `opp_mix: float = 0.0` を足し、`PlannerAgent`・Rust `PyPlanner`・spec（`agents.rs` の `opp_mix`）に通す。
- `_clash` の決定化ごとに、相手の提出の分布を「(1−opp_mix)·π₀ の最尤 1 手 ＋ opp_mix·相手の合法手の等重み」にし、
  自分の各手の葉の V をその分布で期待する（所見 §6 の試作 `experiments/proto_matrix_clash.py` の `mix`／`uniform` と同じ計算。
  `opp_mix=1` が uniform）。`opp_mix=0` なら合法手を列挙せず現行と同じ経路を通る（fingerprint 不変の条件）。
- 費用: 対抗の決定 1 回あたり葉の採点が「合法手の数」倍（5〜8 倍）。対抗は決定の 1〜2 割なので全体では 2〜3 倍を見込む。
- **π₀ の softmax で広げる案は採らない**（τ=1 で両局面とも不変。所見 §6）。**均衡（regret matching）も採らない**
  （均衡では相手は烈火を出すので AI の手はどれも同じ 0 になり、決め手が青の列に残ってパスになる。所見 §6）。

### 12.2 測定（便 2'・Rust・帯は §7 の予備 457500.. ではなく **新規登録**する）

`probe_d065.py` に候補 `m25`＝a15＋`{"opp_mix": 0.25}`／`m50`＝`{"opp_mix": 0.5}`／`m100`＝`{"opp_mix": 1.0}` を足し、
**a15 を基準**（現 champion ではなく）に門番＋錨 3 種を測る。帯は `next_free`（610000）から候補ごとに 2,500 幅で登録する。
所見 §6 の Python 同士・n=400 の下見では uniform 0.512 ±0.049／mix 0.495 ±0.049 で**損はしないが利得も見えない**——
利得は「決めつけを突く相手」に対してしか出ないので、門番（champion 同士）で + が出なくても、
**対人の回帰局面（12.3）を通り、錨 3 種が悪化しなければ採用**とする（判断が要る点として裁定を仰ぐ）。

### 12.3 検査 T-14（回帰局面・`tests/test_d065.py`）

`results/human_games/2026-09.jsonl` の g001（シード 130002）・g002（130003）を `webapp.record.replay(rec, cfg, keep_states=True)` で
再生し、最後の両者決定の対抗局面（`Phase.CLASH_SUBMIT`・`decision_players == {0,1}`）を取る（`experiments/verify_lethal_human.py`
の `last_clash_state`）。検査は 2 本:

1. `opp_mix=0`（既定）の champion は g001 でパス、g002 で 音の形・回避 を選ぶ（**旧挙動の固定**。変わったら fingerprint も疑う）。
2. `opp_mix=1.0` の champion は両局面で 燃える烈火 を選ぶ（所見 §6 uniform の再現）。採用する opp_mix の値でも同じであること。

### 12.4 便 5 への但し書き

- B-2（発見ループ）: 語彙は固定の温存・禁止なので、条件つきの読み（所見 §4: 温存だけでは 0.39〜0.49 で champion に負ける）は
  表せない。**「発見 0 件」を「穴なし」と読まない。** 対人の記録が増えるたびに `verify_lethal_human.py` の詰み表で決定的な対抗を洗う。
- B-3（tau）: 僅差の手を混ぜるだけで、所見 §3 のように 0.1 以上差が開いた局面では烈火は選ばれない。**A-8 の代わりにならない。**

### 12.5 帯

`seed_bands.json` に 600000..609999「対人 2 局の裏取り」を登録済み（`next_free`＝610000。**560000..599999 は未使用の予備**で、
便 2' の帯はそこではなく next_free から取る）。
