"""C-1 学習価値関数の特徴抽出（`bench_evaluate.py` の叩き台を正式化したもの）。

rules_draft.md v0.10 準拠 / engine v0.1。判断は D-035（速度）/ D-036（観測）。

## 実装が2つある理由と、その扱い

同じ特徴を**2つの入口**から作る必要がある。

- `from_obs(ob)`  : 保存済みの観測（`engine.observe` の出力）から。**学習時**に使う。
- `from_state(s, pi)` : `GameState` から直接。**探索の葉**から呼ぶので速い必要がある。

`from_state` を `from_obs(observe(s, pi))` にしてしまえば実装は1本で済むが、
`observe` は毎回大きな dict を組むので探索のホットループには置けない。
逆に学習側で `GameState` を触らせると D-026（覗き見の禁止）が構造的に守れない。

**したがって実装は2本にし、「両者が一致すること」をテストで担保する**
（`tests/test_c1_features.py::test_from_obs_matches_from_state_on_real_games`）。
片方だけ直すと落ちる。特徴を足すときは必ず両方に足すこと。

## 覗き見について (D-026)

参照するのは公開情報＋自分の私有情報のみ。`from_obs` は定義上それしか
受け取らない。`from_state` は同じ量を `GameState` から読むだけで、
相手の手札の中身とデッキ順序には触れない。
`test_c1_features_do_not_peek_at_hidden_information` が押さえている。

## 特徴の設計方針

現行 `greedy.evaluate` の6項（差分）に、それが潰している情報を足す。

- **差分だけでなく素の値**: ライフ差 5 の意味は 18-13 と 6-1 で違う。
- **協奏目標からの乖離**: `Params.concerto_target=4` との差。
- **対抗の色の累積回数** (`clash_counts`, D-031): 公開情報の履歴。
  B-3 では相手モデルとして効かなかったが、価値の特徴としては未検証である。
- **ターン内フラグ** (`used_*`, D-036): このターンにまだチャージできるかは
  局面の価値そのものに効く。差分特徴では表現できない。

`live_reds` は現行 `evaluate` も払っているコストなので、22項に増やしても
実効コストはほぼ変わらない（D-035: 22項の抽出 3.26 µs ≒ 現行 evaluate 3.10 µs）。
"""
from __future__ import annotations

from .cards import ACTION_CARDS, CHARA_CARDS, Color
from .heuristic import live_reds

CONCERTO_TARGET = 4        # heuristic.Params の既定値（A-3 の CEM でも 4）

FEATURE_NAMES = (
    "life_diff", "life_me", "life_opp",
    "concerto_diff", "concerto_me", "concerto_opp", "concerto_gap",
    "hand_diff", "hand_me", "hand_opp",
    "live_reds", "live_red_ratio",
    "level_diff", "level_me",
    "deck_me", "deck_opp",
    "trash_me", "trash_opp",
    "turn_no",
    "clash_red_diff", "clash_green_diff", "clash_pass_diff",
)
N_FEAT = len(FEATURE_NAMES)


def _assemble(life_me, life_opp, cm, co, hm, ho, lr, lv_me, lv_op,
              deck_me, deck_opp, trash_me, trash_opp, turn_no, cc_me, cc_op):
    """特徴ベクトルの組み立て。2つの入口で**必ずここを通す**。

    順序と定義を1箇所に閉じ込めるための関数である。
    `from_obs` と `from_state` の差は「素材の取り出し方」だけになる。
    """
    return [
        float(life_me - life_opp), float(life_me), float(life_opp),
        float(cm - co), float(cm), float(co), float(cm - CONCERTO_TARGET),
        float(hm - ho), float(hm), float(ho),
        float(lr), lr / (hm + 1.0),
        float(lv_me - lv_op), float(lv_me),
        float(deck_me), float(deck_opp),
        float(trash_me), float(trash_opp),
        float(turn_no),
        float(cc_me[0] - cc_op[0]), float(cc_me[1] - cc_op[1]),
        float(cc_me[3] - cc_op[3]),
    ]


# ------------------------------------------------------------------ 状態から
def _levels(slots) -> int:
    """スタック最上段のレベルの合計。"<hidden>" は 0 として数える。"""
    n = 0
    for stack in slots:
        if stack and stack[-1] != "<hidden>":
            n += CHARA_CARDS[stack[-1]].level
    return n


def from_state(s, pi: int) -> list:
    """`GameState` から。探索の葉から呼ばれるので dict を作らない。"""
    me, opp = s.players[pi], s.players[1 - pi]
    return _assemble(
        me.life, opp.life,
        len(me.concerto), len(opp.concerto),
        len(me.hand), len(opp.hand),
        live_reds(s, pi),
        sum(CHARA_CARDS[sl.stack[-1]].level for sl in me.slots if sl.stack),
        sum(CHARA_CARDS[sl.stack[-1]].level for sl in opp.slots if sl.stack),
        len(me.action_deck), len(opp.action_deck),
        len(me.trash), len(opp.trash),
        s.turn_no,
        s.clash_counts[pi], s.clash_counts[1 - pi])


# ------------------------------------------------------------------ 観測から
def _live_reds_from_obs(ob) -> int:
    """観測だけから「使用条件を満たす手札の赤の枚数」を数える。

    `heuristic.live_reds` と同じ判定を、観測の材料だけで行う:
    - 色が赤であること
    - リーダースキル指定カードなら、自分のリーダーが `dedicated_to` と同名であること
      (§6.4 使用条件II / D-009)
    - 実効コスト ≤ 協奏エリアの枚数 (§6.4 使用条件I)

    実効コストは素のコスト + 旋風の修正 (`red_cost_up`, D-036)。
    **この修正が観測に無いと数え違える**ため、D-036 で `observe` に足した。
    """
    me = ob["me"]
    stack = me["slots"][0] if me["slots"] else []
    leader = (CHARA_CARDS[stack[-1]].name
              if stack and stack[-1] != "<hidden>" else None)
    up = ob["red_cost_up"]["me"]
    n_conc = len(me["concerto"])
    n = 0
    for cid in me["hand"]:
        c = ACTION_CARDS[cid]
        if c.color != Color.RED:
            continue
        if c.leader_skill and c.dedicated_to != leader:
            continue
        if c.cost + (1 if up else 0) > n_conc:
            continue
        n += 1
    return n


def from_obs(ob) -> list:
    """保存済みの観測から。学習時はこちらだけを使う（D-026 が構造的に守られる）。"""
    me, opp = ob["me"], ob["opp"]
    return _assemble(
        me["life"], opp["life"],
        len(me["concerto"]), len(opp["concerto"]),
        len(me["hand"]), opp["hand_count"],
        _live_reds_from_obs(ob),
        _levels(me["slots"]), _levels(opp["slots"]),
        me["deck_count"], opp["deck_count"],
        len(me["trash"]), len(opp["trash"]),
        ob["turn_no"],
        ob["clash_counts"]["me"], ob["clash_counts"]["opp"])
