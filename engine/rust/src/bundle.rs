//! 束ねた対抗ゲームのソルバ（文献計画 便 A 後半・A-2）。
//!
//! **Python の `meicho/bundle.py` の写しである。** 設計と理屈はそちらに書いてある。
//! ここで守るのは 1 つだけ——**足す順序を Python と完全に揃える**こと。
//! 浮動小数は順序で最後の桁が変わり、平均戦略が 1e-12 ずれると同点の手の
//! 選ばれ方が変わって**手が割れる**（毎手一致の検査は点数まで見る）。
//!
//! 走査順:
//!   1. 相手側の `c[j]` は **i の昇順**に `x[i]·A_k[i][j]` を足す。
//!   2. 自分側の `u[i]` は **k の昇順** → 内側は **j の昇順**。
//!   3. 平均戦略の累積は **t の昇順**。
//!
//! 乱数は 1 回も引かない（初期値は一様・反復数は固定）。

/// 反復数の既定。Python の `bundle.DEFAULT_ITERS` と同じ値でなければならない。
pub const DEFAULT_ITERS: usize = 300;

/// 累積後悔 ＋ 予測項から次の戦略を作る。正の部分が無ければ一様。
///
/// **正の部分を取ってから正規化する。** 予測項を足すと負になりうるので、
/// ここを省くと分母に負が混ざって収束が壊れる（Python 側と同じ罠）。
fn strategy(regret: &[f64], pred: &[f64]) -> Vec<f64> {
    let n = regret.len();
    let mut pos = vec![0.0f64; n];
    let mut s = 0.0f64;
    for i in 0..n {
        let v = regret[i] + pred[i];
        if v > 0.0 {
            pos[i] = v;
            s += v;
        }
    }
    if s <= 0.0 {
        let u = 1.0 / n as f64;
        return vec![u; n];
    }
    for v in pos.iter_mut() {
        *v /= s;
    }
    pos
}

/// 束ねた対抗ゲームを解き、**AI 側の平均戦略**を返す。
///
/// `mats[k][i][j]` は世界 k の点数表（行 = 自分の手・列 = 相手の手）。
/// 行数はすべての k で同じ、列数は世界ごとに違ってよい。
pub fn solve_bundled(mats: &[Vec<Vec<f64>>], weights: &[f64], iters: usize) -> Vec<f64> {
    assert!(!mats.is_empty(), "mats が空");
    assert_eq!(mats.len(), weights.len(), "mats と weights の本数が合わない");
    let n = mats[0].len();
    assert!(n > 0, "行（自分の手）が 0");
    let kn = mats.len();
    let ncols: Vec<usize> = mats.iter().map(|a| a[0].len()).collect();
    for k in 0..kn {
        assert_eq!(mats[k].len(), n, "世界 {} の行数が違う", k);
        assert!(ncols[k] > 0, "世界 {} の列が 0", k);
    }
    let iters = iters.max(1);

    let mut rx = vec![0.0f64; n];
    let mut ry: Vec<Vec<f64>> = ncols.iter().map(|&m| vec![0.0f64; m]).collect();
    let mut px = vec![0.0f64; n];
    let mut py: Vec<Vec<f64>> = ncols.iter().map(|&m| vec![0.0f64; m]).collect();
    let mut xbar = vec![0.0f64; n];
    let mut wsum = 0.0f64;

    for t in 1..=iters {
        let x = strategy(&rx, &px);

        // 1. 相手側を、いまの x に対して更新する（世界ごと・i の昇順）
        for k in 0..kn {
            let a = &mats[k];
            let m = ncols[k];
            let mut c = vec![0.0f64; m];
            for i in 0..n {
                let xi = x[i];
                let row = &a[i];
                for j in 0..m {
                    c[j] += xi * row[j];
                }
            }
            let y = strategy(&ry[k], &py[k]);
            let mut vk = 0.0f64;
            for j in 0..m {
                vk += c[j] * y[j];
            }
            for j in 0..m {
                let inst = vk - c[j]; // 相手は最小化するので符号が逆
                py[k][j] = inst;
                let v = ry[k][j] + inst;
                ry[k][j] = if v > 0.0 { v } else { 0.0 };
            }
        }

        // 2. 更新後の相手に対して自分を更新する（k の昇順 → j の昇順）
        let ys: Vec<Vec<f64>> = (0..kn).map(|k| strategy(&ry[k], &py[k])).collect();
        let mut u = vec![0.0f64; n];
        for k in 0..kn {
            let a = &mats[k];
            let wk = weights[k];
            let y = &ys[k];
            let m = ncols[k];
            for i in 0..n {
                let row = &a[i];
                let mut acc = 0.0f64;
                for j in 0..m {
                    acc += row[j] * y[j];
                }
                u[i] += wk * acc;
            }
        }
        let mut v = 0.0f64;
        for i in 0..n {
            v += x[i] * u[i];
        }
        for i in 0..n {
            let inst = u[i] - v;
            px[i] = inst;
            let q = rx[i] + inst;
            rx[i] = if q > 0.0 { q } else { 0.0 };
        }

        // 3. 平均戦略（線形平均・t の昇順）
        let tw = t as f64;
        for i in 0..n {
            xbar[i] += tw * x[i];
        }
        wsum += tw;
    }

    xbar.iter().map(|q| q / wsum).collect()
}

/// 提出分布 `x` を固定したときの**最悪想定の値** Σ_k w_k · min_j (xᵀA_k)_j。
/// 診断と記録のための量である（打ち方には効かない）。
pub fn bundled_value(mats: &[Vec<Vec<f64>>], weights: &[f64], x: &[f64]) -> f64 {
    let mut total = 0.0f64;
    for (k, a) in mats.iter().enumerate() {
        let m = a[0].len();
        let mut c = vec![0.0f64; m];
        for i in 0..a.len() {
            let xi = x[i];
            let row = &a[i];
            for j in 0..m {
                c[j] += xi * row[j];
            }
        }
        let mut best = c[0];
        for j in 1..m {
            if c[j] < best {
                best = c[j];
            }
        }
        total += weights[k] * best;
    }
    total
}
