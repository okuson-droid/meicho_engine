//! 相手の手札としてありうる世界の**数え上げと列挙**（文献計画 便 C 段 C-3・II-9）。
//!
//! **真実源は Python の `meicho/worlds.py`。ここはその写しである。**
//! 並び（`sorted`）はカード ID の文字列順であり、Rust では `db.action_rank` で表す
//! （`agents.rs::Greedy::sort_by_id` と同じ規約）。数え方・重みの定義・切り方まで
//! Python と 1 対 1 に保つこと。ずれると毎手一致の検査が「同じ手だが別の理由」で崩れる。

use crate::cards::CardDb;

/// 多重集合の引き算（`pool` から `take` を 1 枚ずつ）。並びは `pool` のまま。
pub fn remove_multiset(pool: &[u16], take: &[u16]) -> Vec<u16> {
    let mut left: Vec<u16> = take.to_vec();
    let mut out: Vec<u16> = Vec::with_capacity(pool.len());
    for &cid in pool {
        match left.iter().position(|&x| x == cid) {
            Some(ix) => {
                left.remove(ix);
            }
            None => out.push(cid),
        }
    }
    out
}

/// 二項係数 C(n, k)（小さい値しか使わないので f64 で十分）。
fn comb(n: usize, k: usize) -> f64 {
    if k > n {
        return 0.0;
    }
    let k = k.min(n - k);
    let mut v = 1.0f64;
    for i in 0..k {
        v = v * ((n - i) as f64) / ((i + 1) as f64);
    }
    v.round()
}

/// 種類ごとの枚数（カード ID 順）。`sorted(Counter(left).items())` の写し。
fn kinds(db: &CardDb, left: &[u16]) -> Vec<(u16, usize)> {
    let mut ks: Vec<(u16, usize)> = Vec::new();
    for &c in left {
        match ks.iter_mut().find(|(x, _)| *x == c) {
            Some(e) => e.1 += 1,
            None => ks.push((c, 1)),
        }
    }
    ks.sort_by_key(|(c, _)| db.action_rank[*c as usize]);
    ks
}

/// ありうる**区別できる手札**の数 W。情報が食い違うときは `None`。
///
/// Python の `world_counts(...)["W"]` と同じ値。エントロピー H_w は探索が使わないので
/// ここでは持たない（診断側は Python の `worlds.py` を呼ぶ）。
pub fn world_count_w(db: &CardDb, pool: &[u16], n_hand: usize, known: &[u16]) -> Option<u64> {
    let left = remove_multiset(pool, known);
    if n_hand < known.len() {
        return None;
    }
    let k = n_hand - known.len();
    if k > left.len() {
        return None;
    }
    let mut w: Vec<u64> = vec![0; k + 1];
    w[0] = 1;
    let mut counts: Vec<usize> = kinds(db, &left).iter().map(|(_, c)| *c).collect();
    counts.sort_unstable();
    for c in counts {
        let mut nw: Vec<u64> = vec![0; k + 1];
        for j in 0..=k {
            if w[j] == 0 {
                continue;
            }
            for a in 0..=c.min(k - j) {
                nw[j + a] = nw[j + a].saturating_add(w[j]);
            }
        }
        w = nw;
    }
    Some(w[k])
}

/// ありうる手札を**全部**並べる。返すのは `(手札, 重み)` で、手札はカード ID 順に並べた
/// `known` 込みのもの、重みは「その型になる物理的な配り方の数」。
/// 並びは**重みの大きい順・同点は手札の並び順**（切っても決定的）。
/// `limit` は 0 のとき「切らない」を意味する（Python の `limit=None`）。
pub fn enumerate_hands(db: &CardDb, pool: &[u16], n_hand: usize, known: &[u16],
                       limit: usize) -> Vec<(Vec<u16>, f64)> {
    let left = remove_multiset(pool, known);
    if n_hand < known.len() {
        return Vec::new();
    }
    let k = n_hand - known.len();
    if k > left.len() {
        return Vec::new();
    }
    let ks = kinds(db, &left);
    let mut known_sorted = known.to_vec();
    known_sorted.sort_by_key(|&c| db.action_rank[c as usize]);
    let mut out: Vec<(Vec<u16>, f64)> = Vec::new();
    let mut taken: Vec<(u16, usize)> = Vec::new();
    walk(db, &ks, 0, k, &mut taken, 1.0, &known_sorted, &mut out);
    // 重みの大きい順（同点はカード ID 順の手札の並び順）
    out.sort_by(|a, b| {
        b.1.partial_cmp(&a.1).unwrap().then_with(|| {
            let ra: Vec<u32> = a.0.iter().map(|&c| db.action_rank[c as usize] as u32).collect();
            let rb: Vec<u32> = b.0.iter().map(|&c| db.action_rank[c as usize] as u32).collect();
            ra.cmp(&rb)
        })
    });
    if limit > 0 && out.len() > limit {
        out.truncate(limit);
    }
    out
}

#[allow(clippy::too_many_arguments)]
fn walk(db: &CardDb, ks: &[(u16, usize)], i: usize, rest: usize,
        taken: &mut Vec<(u16, usize)>, weight: f64, known: &[u16],
        out: &mut Vec<(Vec<u16>, f64)>) {
    if rest == 0 {
        let mut hand: Vec<u16> = known.to_vec();
        for (cid, a) in taken.iter() {
            for _ in 0..*a {
                hand.push(*cid);
            }
        }
        hand.sort_by_key(|&c| db.action_rank[c as usize]);
        out.push((hand, weight));
        return;
    }
    if i >= ks.len() {
        return;
    }
    let (cid, cnt) = ks[i];
    // 残りの札で足りるかを先に見る（Python と同じ枝刈り）
    let avail: usize = ks[i..].iter().map(|(_, c)| *c).sum();
    if avail < rest {
        return;
    }
    for a in (0..=cnt.min(rest)).rev() {
        if a > 0 {
            taken.push((cid, a));
        }
        walk(db, ks, i + 1, rest - a, taken, weight * comb(cnt, a), known, out);
        if a > 0 {
            taken.pop();
        }
    }
}
