//! 小さな全結合ネットの推論（DRL 段階 0・`DRL_PLAN.md` §3.3）。
//!
//! 学習は Python（`experiments/drl_train.py`）で行い、重みを JSON で書き出す。ここは読むだけ。
//! 構造: 幹（trunk）= 全結合 + ReLU の列 → 価値の頭（1 出力・sigmoid）／方策の頭
//! （幹の出力と行動特徴を連結 → 全結合 + ReLU の列 → 1 出力のスコア。合法手の中で softmax）。
//!
//! JSON の形（行列は [out][in] の入れ子配列・f32 に丸める）:
//! {"encoding_version": 1, "obs_dim": D, "act_dim": A, "hidden": H,
//!  "trunk": [{"w": [[..]], "b": [..]}, ...], "value": {"w": [[..]], "b": [..]},
//!  "policy": [{"w": [[..]], "b": [..]}, ...]}
//! `value` が無ければ価値は使えない（`has_value()`）。`policy` が空なら方策は使えない。
//!
//! 数値は f32・加算順は固定（行ごとに in の昇順）なので、同じ重み・同じ入力なら常に同じ出力を返す。
//! Python 側（numpy f32）との一致は `tests/test_drl.py` が許容誤差つきで確かめる。

use serde::Deserialize;
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

#[derive(Deserialize)]
struct DenseJson {
    w: Vec<Vec<f32>>,
    b: Vec<f32>,
}

#[derive(Deserialize)]
struct NetJson {
    encoding_version: i64,
    obs_dim: usize,
    act_dim: usize,
    trunk: Vec<DenseJson>,
    value: Option<DenseJson>,
    #[serde(default)]
    policy: Vec<DenseJson>,
}

#[derive(Clone)]
pub struct Dense {
    pub n_in: usize,
    pub n_out: usize,
    /// 行優先 [out][in]
    pub w: Vec<f32>,
    pub b: Vec<f32>,
}

impl Dense {
    fn from_json(j: &DenseJson) -> Result<Dense, String> {
        let n_out = j.w.len();
        if n_out == 0 {
            return Err("empty dense layer".into());
        }
        let n_in = j.w[0].len();
        if j.b.len() != n_out {
            return Err(format!("bias length {} != out {}", j.b.len(), n_out));
        }
        let mut w = Vec::with_capacity(n_in * n_out);
        for row in &j.w {
            if row.len() != n_in {
                return Err("ragged weight matrix".into());
            }
            w.extend_from_slice(row);
        }
        Ok(Dense { n_in, n_out, w, b: j.b.clone() })
    }

    #[inline]
    pub fn forward(&self, x: &[f32], out: &mut Vec<f32>, relu: bool) {
        debug_assert_eq!(x.len(), self.n_in);
        out.clear();
        out.reserve(self.n_out);
        for o in 0..self.n_out {
            let row = &self.w[o * self.n_in..(o + 1) * self.n_in];
            let mut acc = self.b[o];
            for (a, b) in row.iter().zip(x.iter()) {
                acc += a * b;
            }
            out.push(if relu && acc < 0.0 { 0.0 } else { acc });
        }
    }
}

pub struct Net {
    pub encoding_version: i64,
    pub obs_dim: usize,
    pub act_dim: usize,
    pub trunk: Vec<Dense>,
    pub value: Option<Dense>,
    pub policy: Vec<Dense>,
}

impl Net {
    pub fn from_json(text: &str) -> Result<Net, String> {
        let j: NetJson = serde_json::from_str(text).map_err(|e| e.to_string())?;
        let trunk: Vec<Dense> = j.trunk.iter().map(Dense::from_json).collect::<Result<_, _>>()?;
        let value = match &j.value {
            Some(v) => Some(Dense::from_json(v)?),
            None => None,
        };
        let policy: Vec<Dense> = j.policy.iter().map(Dense::from_json).collect::<Result<_, _>>()?;
        if let Some(first) = trunk.first() {
            if first.n_in != j.obs_dim {
                return Err(format!("trunk input {} != obs_dim {}", first.n_in, j.obs_dim));
            }
        }
        Ok(Net { encoding_version: j.encoding_version, obs_dim: j.obs_dim, act_dim: j.act_dim, trunk, value, policy })
    }

    pub fn has_value(&self) -> bool {
        self.value.is_some()
    }
    pub fn has_policy(&self) -> bool {
        !self.policy.is_empty()
    }

    /// 幹の出力（最後の層も ReLU）。
    pub fn trunk(&self, x: &[f32]) -> Vec<f32> {
        let mut cur: Vec<f32> = x.to_vec();
        let mut nxt: Vec<f32> = Vec::new();
        for layer in &self.trunk {
            layer.forward(&cur, &mut nxt, true);
            std::mem::swap(&mut cur, &mut nxt);
        }
        cur
    }

    /// 価値（勝つ確率）。
    pub fn value_from_trunk(&self, h: &[f32]) -> f32 {
        let v = self.value.as_ref().expect("net has no value head");
        let mut out = Vec::new();
        v.forward(h, &mut out, false);
        1.0 / (1.0 + (-out[0]).exp())
    }

    pub fn value(&self, x: &[f32]) -> f32 {
        let h = self.trunk(x);
        self.value_from_trunk(&h)
    }

    /// 各行動のスコア（softmax 前）。`acts` は展開済みの行動特徴。
    pub fn policy_scores(&self, h: &[f32], acts: &[Vec<f32>]) -> Vec<f32> {
        let mut scores = Vec::with_capacity(acts.len());
        let mut cur: Vec<f32> = Vec::with_capacity(h.len() + self.act_dim);
        let mut nxt: Vec<f32> = Vec::new();
        for a in acts {
            cur.clear();
            cur.extend_from_slice(h);
            cur.extend_from_slice(a);
            let n = self.policy.len();
            for (i, layer) in self.policy.iter().enumerate() {
                layer.forward(&cur, &mut nxt, i + 1 < n);
                std::mem::swap(&mut cur, &mut nxt);
            }
            scores.push(cur[0]);
        }
        scores
    }
}

/// 読み込み済みのネットの共有（パスをキーに 1 回だけ読む。対局ごとに JSON を読まないため）。
static CACHE: RwLock<Option<HashMap<String, Arc<Net>>>> = RwLock::new(None);

pub fn load(path: &str) -> Result<Arc<Net>, String> {
    {
        let g = CACHE.read().unwrap();
        if let Some(m) = g.as_ref() {
            if let Some(n) = m.get(path) {
                return Ok(n.clone());
            }
        }
    }
    let text = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    let net = Arc::new(Net::from_json(&text)?);
    let mut g = CACHE.write().unwrap();
    let m = g.get_or_insert_with(HashMap::new);
    m.insert(path.to_string(), net.clone());
    Ok(net)
}

/// 同じパスを読み直したいとき（学習の反復で上書きした後）に呼ぶ。
pub fn forget(path: &str) {
    let mut g = CACHE.write().unwrap();
    if let Some(m) = g.as_mut() {
        m.remove(path);
    }
}
