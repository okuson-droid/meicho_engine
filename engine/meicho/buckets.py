"""決定化の山札を散らすための**層（バケット）**（文献計画 便 C 段 C-4・D-077 追記 4）。

## 何のためにあるか

決定化は K 本引く。その K 本は「相手の手札」だけでなく「山札の並び」も別々に混ぜる。
ところが混ぜ方が一様だと、K 本の**次に引く札**が偶然かたよる——たとえば 6 本すべての
上位 3 枚が「コスト 0 の赤」ばかり、ということが普通に起きる。そうなると探索は
「引ける札の幅」を見ないまま手を決める。

段 C-4 はここを**層別サンプリング**にする。層は「コスト帯 × 色」で切り、K 本を層に
割り振ってから層内で一様に引く（`HANDOFF_20260910_LIT_C.md` §0.3 (vii)）。
散らばりを作るのが目的なので、**層の割り当ては乱数任せにしない**——乱数で割り当てると
「散らす」という約束そのものが確率的になり、K が小さいうちは何も変わらない。
決定的に割り当て、層の**中**だけを乱数で選ぶ。

## 層の定義（§0.3 (vii)）

- コスト帯 4 通り: {0-1} {2} {3} {4 以上}
- 色 3 通り: 赤 / 緑 / 青
- 層の番号 = コスト帯 × 3 ＋ 色 → 0..11 の 12 通り

番号の付け方を固定しておくのは、Rust 側（`rust/src/buckets.rs`）と**同じ順序**で
層を並べるためである。順序がずれると同じシードで別の並びになり、毎手一致が崩れる。

## なぜ `meicho/` に置くか

段 C-3 で `meicho/worlds.py` を作ったのと同じ理由である。探索の本体（`greedy.py`）と
診断（`experiments/coverage.py` ほか）が**同じ関数**を呼べるようにしておかないと、
片方だけ直したときに「診断が言う層」と「探索が使う層」が黙ってずれる。
`cards/` は触らない——層はカード表の属性（`cost` / `color`）から**導く**ものであって、
カードデータに書き足す情報ではない。
"""
from __future__ import annotations

from .cards import ACTION_CARDS, Color

#: 層の総数（コスト帯 4 × 色 3）
N_BUCKETS = 12

#: 色の番号。Rust の `bucket_of` と同じ順序でなければならない。
_COLOR_IX = {Color.RED: 0, Color.GREEN: 1, Color.BLUE: 2}


def cost_band(cost: int) -> int:
    """コスト帯 {0-1, 2, 3, 4+} を 0..3 に落とす。"""
    c = int(cost)
    if c <= 1:
        return 0
    if c == 2:
        return 1
    if c == 3:
        return 2
    return 3


def bucket_of(card_id: str) -> int:
    """カード ID の層番号（0..11）。未知の ID は 0 に落とす（黙って落とさない場所は
    呼び出し側にある——探索が扱うのは必ずデッキリストに載った札である）。"""
    card = ACTION_CARDS.get(card_id)
    if card is None:
        return 0
    return cost_band(card.cost) * 3 + _COLOR_IX[card.color]


def strata_present(cards) -> list:
    """`cards` に実際に現れる層を**昇順**で返す（空なら空リスト）。

    実際に現れる層だけを使うのは、無い層に割り当てても散らせないからである。
    昇順に固定してあるので、同じ札の集合なら常に同じ並びになる。
    """
    return sorted({bucket_of(c) for c in cards})


def stratum_plan(present, world_ix: int, top_k: int) -> list:
    """決定化 `world_ix` 本目の上位 `top_k` 枚に割り当てる層を返す。

    割り当ては `present[(world_ix * top_k + r) % m]`（r は 0..top_k-1）である。
    - **決定的**（乱数を 1 ビットも引かない）
    - K 本 × top_k 枚を層に**順ぐりに**配るので、割り振りの偏りは高々 1
    - 1 本の中でも r ごとに層が変わるので、同じ本の上位 3 枚も散る

    `present` が空なら空リストを返す。
    """
    m = len(present)
    if m == 0 or top_k <= 0:
        return []
    return [present[(world_ix * top_k + r) % m] for r in range(top_k)]


#: 層を散らす対象にする「次に引く」枚数（§0.3 (vii)「上位 3 枚」）
TOP_K = 3


def stratify_top(cards: list, world_ix: int, rng, top_k: int = TOP_K) -> None:
    """`cards`（混ぜ終わった山札）の**上位 `top_k` 枚**を層別に並べ替える（その場で書き換え）。

    手順は位置 r = 0, 1, 2 の順に:

    1. 目標の層 b = `stratum_plan(...)[r]` を取る（決定的）
    2. 位置 r 以降に層 b の札があれば、その中から**一様に 1 枚**選んで位置 r と入れ替える
    3. 無ければ何もしない（引ける層が尽きた場合。乱数も引かない）

    2 で引くのは `rng.choice`（＝ `_randbelow`）1 回だけである。Rust 側は
    `choice_index` が同じ実装なので、同じ乱数状態なら同じ札を選ぶ。

    **中身の多重集合は変わらない**（入れ替えているだけ）。呼び出し側は
    `draw_buckets` が 0 のときこの関数を**呼ばない**ので、既定の乱数消費は不変である。
    """
    n = len(cards)
    if n < 2:
        return
    present = strata_present(cards)
    plan = stratum_plan(present, world_ix, min(top_k, n))
    for r, b in enumerate(plan):
        cand = [i for i in range(r, n) if bucket_of(cards[i]) == b]
        if not cand:
            continue
        j = rng.choice(cand)
        if j != r:
            cards[r], cards[j] = cards[j], cards[r]
