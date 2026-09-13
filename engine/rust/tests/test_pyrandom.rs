use meicho_rs::pyrandom::PyRandom;
use serde_json::Value;

fn fixtures() -> Value {
    let p = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/pyrandom.json");
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

#[test]
fn str_seed_shuffle_and_u32_match_cpython() {
    let fx = fixtures();
    for c in fx["str_seed"].as_array().unwrap() {
        let key = c["key"].as_str().unwrap();
        let mut r = PyRandom::from_str_seed(key);
        let mut xs: Vec<u64> = (0..40).collect();
        r.shuffle(&mut xs);
        let want: Vec<u64> = c["shuffle40"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
        assert_eq!(xs, want, "shuffle40 for {key}");
        let mut r2 = PyRandom::from_str_seed(key);
        let mut ys: Vec<u64> = (0..7).collect();
        r2.shuffle(&mut ys);
        let want7: Vec<u64> = c["shuffle7"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
        assert_eq!(ys, want7, "shuffle7 for {key}");
        let mut r3 = PyRandom::from_str_seed(key);
        let got: Vec<u64> = (0..5).map(|_| r3.getrandbits(32)).collect();
        let want32: Vec<u64> = c["u32"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
        assert_eq!(got, want32, "u32 for {key}");
    }
}

#[test]
fn int_seed_random_and_randbelow_match_cpython() {
    let fx = fixtures();
    for c in fx["int_seed"].as_array().unwrap() {
        let seed = c["seed"].as_i64().unwrap();
        let mut r = PyRandom::from_int_seed(seed);
        let got: Vec<f64> = (0..6).map(|_| r.random()).collect();
        let want: Vec<f64> = c["random"].as_array().unwrap().iter().map(|v| v.as_f64().unwrap()).collect();
        assert_eq!(got, want, "random for {seed}");
        let mut r = PyRandom::from_int_seed(seed);
        let got: Vec<u64> = (0..4).map(|_| r.getrandbits(32)).collect();
        let want: Vec<u64> = c["u32"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
        assert_eq!(got, want, "u32 for {seed}");
        let mut r = PyRandom::from_int_seed(seed);
        let got: Vec<u64> = [1u64, 2, 3, 10, 100, 1000].iter().map(|n| r.randbelow(*n)).collect();
        let want: Vec<u64> = c["randbelow"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
        assert_eq!(got, want, "randbelow for {seed}");
    }
}

#[test]
fn sample_matches_cpython() {
    let fx = fixtures();
    for c in fx["sample"].as_array().unwrap() {
        let seed = c["seed"].as_i64().unwrap();
        let n = c["n"].as_u64().unwrap() as usize;
        let k = c["k"].as_u64().unwrap() as usize;
        let mut r = PyRandom::from_int_seed(seed);
        let got = r.sample_indices(n, k);
        let want: Vec<usize> = c["idx"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap() as usize).collect();
        assert_eq!(got, want, "sample seed={seed} n={n} k={k}");
    }
}

#[test]
fn getstate_setstate_and_wide_getrandbits() {
    let fx = fixtures();
    let mut r = PyRandom::from_int_seed(77);
    for _ in 0..3 { r.random(); }
    let st = r.getstate();
    let a: Vec<f64> = (0..2).map(|_| r.random()).collect();
    r.setstate(&st);
    let b: Vec<f64> = (0..2).map(|_| r.random()).collect();
    let want: Vec<f64> = fx["state"]["after"].as_array().unwrap().iter().map(|v| v.as_f64().unwrap()).collect();
    assert_eq!(a, want);
    assert_eq!(a, b);
    let mut r = PyRandom::from_int_seed(3);
    let got33: Vec<u64> = (0..3).map(|_| r.getrandbits(33)).collect();
    let want33: Vec<u64> = fx["bits"]["k33"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
    assert_eq!(got33, want33);
    let got64: Vec<u64> = (0..2).map(|_| r.getrandbits(64)).collect();
    let want64: Vec<u64> = fx["bits"]["k64"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
    assert_eq!(got64, want64);
}
