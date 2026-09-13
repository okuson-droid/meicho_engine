//! 決定化の山札を散らすための**層（バケット）**（文献計画 便 C 段 C-4・D-077 追記 4）。
//!
//! Python の `meicho/buckets.py` の**写し**である。層の番号の付け方（コスト帯 × 3 ＋ 色）と
//! `stratum_plan` の割り当て、`stratify_top` の乱数の引き方（`choice_index` を位置ごとに
//! 高々 1 回）まで同じでなければ、同じシードで別の並びになり毎手一致が崩れる。

use crate::cards::{CardDb, Color};

/// 層の総数（コスト帯 4 × 色 3）
pub const N_BUCKETS: usize = 12;

/// 層を散らす対象にする「次に引く」枚数（§0.3 (vii)「上位 3 枚」）
pub const TOP_K: usize = 3;

/// コスト帯 {0-1, 2, 3, 4+} を 0..3 に落とす。
pub fn cost_band(cost: i64) -> usize {
    if cost <= 1 {
        0
    } else if cost == 2 {
        1
    } else if cost == 3 {
        2
    } else {
        3
    }
}

/// カードの層番号（0..11）。色の順序は Python の `_COLOR_IX` と同じ。
pub fn bucket_of(db: &CardDb, cid: u16) -> usize {
    let card = &db.action[cid as usize];
    let color = match card.color {
        Color::Red => 0,
        Color::Green => 1,
        Color::Blue => 2,
    };
    cost_band(card.cost) * 3 + color
}

/// `cards` に実際に現れる層を**昇順**で返す（Python の `strata_present`）。
pub fn strata_present(db: &CardDb, cards: &[u16]) -> Vec<usize> {
    let mut seen = [false; N_BUCKETS];
    for &c in cards {
        seen[bucket_of(db, c)] = true;
    }
    (0..N_BUCKETS).filter(|&b| seen[b]).collect()
}

/// 決定化 `world_ix` 本目の上位 `top_k` 枚に割り当てる層（決定的・乱数を引かない）。
pub fn stratum_plan(present: &[usize], world_ix: usize, top_k: usize) -> Vec<usize> {
    let m = present.len();
    if m == 0 || top_k == 0 {
        return Vec::new();
    }
    (0..top_k).map(|r| present[(world_ix * top_k + r) % m]).collect()
}

/// 混ぜ終わった山札の**上位 `TOP_K` 枚**を層別に並べ替える（その場で書き換え）。
///
/// 位置 r ごとに「目標の層の札が位置 r 以降に残っていれば、その中から一様に 1 枚選んで
/// 入れ替える」。乱数は `choice_index` を高々 1 回引く（Python の `rng.choice` と同じ）。
pub fn stratify_top(db: &CardDb, cards: &mut Vec<u16>, world_ix: usize,
                    rng: &mut crate::pyrandom::PyRandom) {
    let n = cards.len();
    if n < 2 {
        return;
    }
    let present = strata_present(db, cards);
    let plan = stratum_plan(&present, world_ix, TOP_K.min(n));
    for (r, &b) in plan.iter().enumerate() {
        let cand: Vec<usize> = (r..n).filter(|&i| bucket_of(db, cards[i]) == b).collect();
        if cand.is_empty() {
            continue;
        }
        let j = cand[rng.choice_index(cand.len())];
        if j != r {
            cards.swap(r, j);
        }
    }
}
