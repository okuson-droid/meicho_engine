//! CPython `random.Random` 互換の乱数（MT19937）。
//!
//! D-049 の受け入れ基準「同シード同結果」を満たすため、CPython 3.11 の
//! `_random` / `random.py` の消費列を bit 単位で再現する。
//!
//! - `from_str_seed`: `random.Random("seed:calls")`（`seed(a, version=2)`:
//!   `a = a.encode() + sha512(a.encode()).digest()` を big-endian 整数にして
//!   `init_by_array`）。エンジンの `GameState.next_rng` が使う形。
//! - `from_int_seed`: `random.Random(int)`。エージェント側（H の混合戦略・決定化）が使う。
//! - `random` / `getrandbits` / `randbelow` / `shuffle` / `choice` / `sample` /
//!   `getstate` / `setstate` を再現する。
//!
//! 検証は `tests/test_pyrandom.rs`（Python で生成した固定値との突き合わせ）。

use sha2::{Digest, Sha512};

const N: usize = 624;
const M: usize = 397;
const MATRIX_A: u32 = 0x9908_b0df;
const UPPER_MASK: u32 = 0x8000_0000;
const LOWER_MASK: u32 = 0x7fff_ffff;

#[derive(Clone)]
pub struct PyRandom {
    mt: [u32; N],
    mti: usize,
}

impl PyRandom {
    fn init_genrand(&mut self, s: u32) {
        self.mt[0] = s;
        for i in 1..N {
            let prev = self.mt[i - 1];
            self.mt[i] = 1812433253u32
                .wrapping_mul(prev ^ (prev >> 30))
                .wrapping_add(i as u32);
        }
        self.mti = N;
    }

    fn init_by_array(&mut self, key: &[u32]) {
        self.init_genrand(19650218);
        let mut i = 1usize;
        let mut j = 0usize;
        let klen = key.len().max(1);
        let mut k = if N > klen { N } else { klen };
        while k > 0 {
            let prev = self.mt[i - 1];
            let kj = if key.is_empty() { 0 } else { key[j] };
            self.mt[i] = (self.mt[i] ^ ((prev ^ (prev >> 30)).wrapping_mul(1664525)))
                .wrapping_add(kj)
                .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= N {
                self.mt[0] = self.mt[N - 1];
                i = 1;
            }
            if j >= klen {
                j = 0;
            }
            k -= 1;
        }
        k = N - 1;
        while k > 0 {
            let prev = self.mt[i - 1];
            self.mt[i] = (self.mt[i] ^ ((prev ^ (prev >> 30)).wrapping_mul(1566083941)))
                .wrapping_sub(i as u32);
            i += 1;
            if i >= N {
                self.mt[0] = self.mt[N - 1];
                i = 1;
            }
            k -= 1;
        }
        self.mt[0] = 0x8000_0000;
        self.mti = N;
    }

    fn blank() -> PyRandom {
        PyRandom { mt: [0u32; N], mti: N + 1 }
    }

    /// big-endian のバイト列を「abs 値の 32bit little-endian ワード列」に変換する
    /// （CPython `random_seed` の `_PyLong_AsByteArray(..., little_endian=1)` 相当）。
    fn key_from_be_bytes(bytes: &[u8]) -> Vec<u32> {
        // 先頭の 0 バイトは整数としては無意味なので落とす（int.from_bytes と同じ）。
        let mut start = 0;
        while start < bytes.len() && bytes[start] == 0 {
            start += 1;
        }
        let sig = &bytes[start..];
        if sig.is_empty() {
            return vec![0];
        }
        // little-endian 32bit ワードに詰める
        let mut words = Vec::with_capacity(sig.len() / 4 + 1);
        let mut i = sig.len();
        while i > 0 {
            let lo = i.saturating_sub(4);
            let mut w: u32 = 0;
            for (shift, b) in sig[lo..i].iter().rev().enumerate() {
                w |= (*b as u32) << (8 * shift);
            }
            words.push(w);
            i = lo;
        }
        words
    }

    /// `random.Random(s)`（s は str）。
    pub fn from_str_seed(s: &str) -> PyRandom {
        let mut bytes = s.as_bytes().to_vec();
        let digest = Sha512::digest(s.as_bytes());
        bytes.extend_from_slice(&digest);
        let key = Self::key_from_be_bytes(&bytes);
        let mut r = Self::blank();
        r.init_by_array(&key);
        r
    }

    /// `random.Random(n)`（n は非負整数。負なら abs）。
    pub fn from_int_seed(n: i64) -> PyRandom {
        let a = n.unsigned_abs();
        let key: Vec<u32> = if a == 0 {
            vec![0]
        } else {
            let mut v = Vec::new();
            let mut x = a;
            while x > 0 {
                v.push((x & 0xffff_ffff) as u32);
                x >>= 32;
            }
            v
        };
        let mut r = Self::blank();
        r.init_by_array(&key);
        r
    }

    pub fn genrand_u32(&mut self) -> u32 {
        if self.mti >= N {
            let mt = &mut self.mt;
            let mut kk = 0;
            while kk < N - M {
                let y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK);
                mt[kk] = mt[kk + M] ^ (y >> 1) ^ if y & 1 != 0 { MATRIX_A } else { 0 };
                kk += 1;
            }
            while kk < N - 1 {
                let y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK);
                mt[kk] = mt[kk + M - N] ^ (y >> 1) ^ if y & 1 != 0 { MATRIX_A } else { 0 };
                kk += 1;
            }
            let y = (mt[N - 1] & UPPER_MASK) | (mt[0] & LOWER_MASK);
            mt[N - 1] = mt[M - 1] ^ (y >> 1) ^ if y & 1 != 0 { MATRIX_A } else { 0 };
            self.mti = 0;
        }
        let mut y = self.mt[self.mti];
        self.mti += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^= y >> 18;
        y
    }

    /// `random.random()`: 53bit の一様乱数。
    pub fn random(&mut self) -> f64 {
        let a = (self.genrand_u32() >> 5) as f64;
        let b = (self.genrand_u32() >> 6) as f64;
        (a * 67108864.0 + b) * (1.0 / 9007199254740992.0)
    }

    /// `random.getrandbits(k)`（k ≤ 64 に限定。エンジンの用途では十分）。
    pub fn getrandbits(&mut self, k: u32) -> u64 {
        assert!(k >= 1 && k <= 64);
        if k <= 32 {
            return (self.genrand_u32() >> (32 - k)) as u64;
        }
        // CPython: 下位ワードから順に埋め、最後のワードは残りビット分だけ右シフト
        let mut out: u64 = 0;
        let mut remaining = k;
        let mut shift = 0;
        while remaining > 0 {
            let mut r = self.genrand_u32();
            if remaining < 32 {
                r >>= 32 - remaining;
            }
            out |= (r as u64) << shift;
            shift += 32;
            remaining = remaining.saturating_sub(32);
        }
        out
    }

    /// `random._randbelow(n)`（getrandbits 版）。n ≥ 1。
    pub fn randbelow(&mut self, n: u64) -> u64 {
        if n == 0 {
            return 0;
        }
        let k = 64 - n.leading_zeros();
        let mut r = self.getrandbits(k);
        while r >= n {
            r = self.getrandbits(k);
        }
        r
    }

    /// `random.shuffle(x)`。
    pub fn shuffle<T>(&mut self, x: &mut [T]) {
        let n = x.len();
        if n < 2 {
            return;
        }
        for i in (1..n).rev() {
            let j = self.randbelow((i + 1) as u64) as usize;
            x.swap(i, j);
        }
    }

    /// `random.choice(seq)` の添字。seq は空でないこと。
    pub fn choice_index(&mut self, len: usize) -> usize {
        assert!(len > 0, "choice from empty sequence");
        self.randbelow(len as u64) as usize
    }

    /// `random.sample(population, k)`（CPython 3.11 のアルゴリズム）。返すのは添字列。
    pub fn sample_indices(&mut self, n: usize, k: usize) -> Vec<usize> {
        assert!(k <= n, "sample larger than population");
        let mut result = vec![0usize; k];
        let mut setsize: usize = 21;
        if k > 5 {
            // setsize += 4 ** ceil(log(k * 3, 4))
            let target = (k * 3) as f64;
            let e = (target.ln() / 4f64.ln()).ceil() as u32;
            setsize += 4usize.pow(e);
        }
        if n <= setsize {
            let mut pool: Vec<usize> = (0..n).collect();
            for i in 0..k {
                let j = self.randbelow((n - i) as u64) as usize;
                result[i] = pool[j];
                pool[j] = pool[n - i - 1];
            }
        } else {
            let mut selected = std::collections::HashSet::new();
            for i in 0..k {
                let mut j = self.randbelow(n as u64) as usize;
                while selected.contains(&j) {
                    j = self.randbelow(n as u64) as usize;
                }
                selected.insert(j);
                result[i] = j;
            }
        }
        result
    }

    /// `getstate()` 相当（MT の 624 語と位置）。
    pub fn getstate(&self) -> ([u32; N], usize) {
        (self.mt, self.mti)
    }

    pub fn setstate(&mut self, st: &([u32; N], usize)) {
        self.mt = st.0;
        self.mti = st.1;
    }
}
