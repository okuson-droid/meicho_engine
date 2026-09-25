// serde_json の json! マクロが状態の全欄を一度に組むため、既定の展開上限 128 を超える。
// v0.12 / BP01 で欄が 12 個増えたときに当たった（D-079 追記 3）。挙動は変わらない。
#![recursion_limit = "512"]
//! `meicho_rs` — 鳴潮：対決 ルールエンジンの Rust 版（D-049）。
//!
//! Python 側からは `meicho/rs_engine.py` が包んで、`meicho.engine` と同じ形の
//! API（`initial_state / decision_players / legal_actions / apply / outcome / observe`）を提供する。
//! カード表は起動時に `load_cards(cards_export.cards_json())` で受け取る（真実源は `cards.py`）。

pub mod agents;
pub mod buckets;
pub mod bundle;
pub mod cards;
pub mod encode;
pub mod engine;
pub mod intervene;
pub mod net;
pub mod pyrandom;
pub mod state;
pub mod worlds;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};
use std::sync::{Arc, RwLock};

use cards::CardDb;
use engine::Action;
use crate::state::Zone;
use state::GameState;

static DB: RwLock<Option<Arc<CardDb>>> = RwLock::new(None);

fn db() -> PyResult<Arc<CardDb>> {
    DB.read()
        .unwrap()
        .clone()
        .ok_or_else(|| PyRuntimeError::new_err("meicho_rs.load_cards() が未呼び出し"))
}

/// `cards_export.cards_json()` の文字列を読み込む。
#[pyfunction]
fn load_cards(json_text: &str) -> PyResult<usize> {
    let d = CardDb::from_json(json_text).map_err(PyValueError::new_err)?;
    let n = d.chara.len() + d.action.len();
    *DB.write().unwrap() = Some(Arc::new(d));
    Ok(n)
}

#[pyclass(name = "GameState")]
#[derive(Clone)]
pub struct PyGameState {
    inner: GameState,
}

#[pymethods]
impl PyGameState {
    /// Python 版 `GameState.to_json()` と同じ構造の JSON 文字列。
    fn to_json(&self) -> PyResult<String> {
        Ok(self.inner.to_json(&*db()?).to_string())
    }
    fn clone_state(&self) -> PyGameState {
        self.clone()
    }
    #[getter]
    fn phase(&self) -> &'static str {
        self.inner.phase.as_str()
    }
    #[getter]
    fn turn_no(&self) -> i64 {
        self.inner.turn_no
    }
    #[getter]
    fn turn_player(&self) -> u8 {
        self.inner.turn_player
    }
    #[getter]
    fn outcome(&self) -> Option<i8> {
        self.inner.outcome
    }
    #[getter]
    fn rng_calls(&self) -> i64 {
        self.inner.rng_calls
    }
    #[getter]
    fn seed(&self) -> i64 {
        self.inner.seed
    }
    #[getter]
    fn clash_winner(&self) -> Option<u8> {
        self.inner.clash_winner
    }
    #[getter]
    fn rush_allowance(&self) -> i64 {
        self.inner.rush_allowance
    }
    #[getter]
    fn used_charge(&self) -> bool {
        self.inner.used_charge
    }
    #[getter]
    fn used_switch(&self) -> bool {
        self.inner.used_switch
    }
    #[getter]
    fn used_levelup(&self) -> bool {
        self.inner.used_levelup
    }
    /// 両プレイヤーのライフ。
    fn lives(&self) -> (i64, i64) {
        (self.inner.players[0].life, self.inner.players[1].life)
    }
    /// 席 pi の手札（card_id 列）。
    fn hand(&self, pi: usize) -> PyResult<Vec<String>> {
        let d = db()?;
        Ok(self.inner.players[pi].hand.iter().map(|&c| d.action[c as usize].card_id.clone()).collect())
    }
}

fn to_py(py: Python<'_>, v: &serde_json::Value) -> PyObject {
    match v {
        serde_json::Value::Null => py.None(),
        serde_json::Value::Bool(b) => b.into_py(py),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.into_py(py)
            } else {
                n.as_f64().unwrap().into_py(py)
            }
        }
        serde_json::Value::String(s) => s.into_py(py),
        serde_json::Value::Array(a) => {
            let l = PyList::new_bound(py, a.iter().map(|x| to_py(py, x)));
            l.into_py(py)
        }
        serde_json::Value::Object(o) => {
            let d = PyDict::new_bound(py);
            for (k, x) in o {
                d.set_item(k, to_py(py, x)).unwrap();
            }
            d.into_py(py)
        }
    }
}

fn action_to_py(py: Python<'_>, d: &CardDb, a: &Action) -> PyResult<PyObject> {
    let out = PyDict::new_bound(py);
    match a {
        Action::Setup { leader, backs } => {
            out.set_item("type", "setup")?;
            out.set_item("leader", leader)?;
            out.set_item("backs", backs)?;
        }
        Action::Mulligan { cards } => {
            out.set_item("type", "mulligan")?;
            out.set_item("cards", cards.clone())?;
        }
        Action::Charge { hand } => {
            out.set_item("type", "charge")?;
            out.set_item("hand", *hand)?;
        }
        Action::Switch { back } => {
            out.set_item("type", "switch")?;
            out.set_item("back", *back)?;
        }
        Action::Levelup { slot, card } => {
            out.set_item("type", "levelup")?;
            out.set_item("slot", *slot)?;
            out.set_item("card", &d.chara[*card as usize].card_id)?;
        }
        Action::ToClash => out.set_item("type", "to_clash")?,
        Action::EndTurn => out.set_item("type", "end_turn")?,
        Action::Submit { hand } => {
            out.set_item("type", "submit")?;
            out.set_item("hand", *hand)?;
        }
        Action::Pass => out.set_item("type", "pass")?,
        Action::Pay => out.set_item("type", "pay")?,
        Action::Decline => out.set_item("type", "decline")?,
        Action::ChooseBack { back } => {
            out.set_item("type", "choose_back")?;
            out.set_item("back", *back)?;
        }
        Action::Use => out.set_item("type", "use")?,
        Action::Skip => out.set_item("type", "skip")?,
        Action::ChooseCount { count } => {
            out.set_item("type", "choose_count")?;
            out.set_item("count", *count)?;
        }
        Action::Discard { hand } => {
            out.set_item("type", "discard")?;
            out.set_item("hand", *hand)?;
        }
        Action::Resolve { index } => {
            out.set_item("type", "resolve")?;
            out.set_item("index", *index)?;
        }
        Action::Stop => out.set_item("type", "stop")?,
        Action::Rush { hand } => {
            out.set_item("type", "rush")?;
            out.set_item("hand", *hand)?;
        }
        Action::ChooseCard { zone, index, card, slot } => {
            out.set_item("type", "choose_card")?;
            out.set_item("zone", match zone { Zone::Concerto => "concerto", Zone::Trash => "trash", Zone::CharaDeck => "chara_deck" })?;
            out.set_item("index", *index)?;
            let cid = match zone { Zone::CharaDeck => &d.chara[*card as usize].card_id, _ => &d.action[*card as usize].card_id };
            out.set_item("card", cid)?;
            if let Some(sl) = slot { out.set_item("slot", *sl)?; }
        }
    }
    Ok(out.into_py(py))
}

fn action_from_py(d: &CardDb, a: &Bound<'_, PyDict>) -> PyResult<Action> {
    let t: String = a
        .get_item("type")?
        .ok_or_else(|| PyValueError::new_err("action has no type"))?
        .extract()?;
    let get_usize = |k: &str| -> PyResult<usize> {
        a.get_item(k)?
            .ok_or_else(|| PyValueError::new_err(format!("action missing {k}")))?
            .extract()
    };
    let get_i64 = |k: &str| -> PyResult<i64> {
        a.get_item(k)?
            .ok_or_else(|| PyValueError::new_err(format!("action missing {k}")))?
            .extract()
    };
    Ok(match t.as_str() {
        "setup" => Action::Setup {
            leader: a.get_item("leader")?.unwrap().extract()?,
            backs: a.get_item("backs")?.map(|x| x.extract()).transpose()?.unwrap_or_default(),
        },
        "mulligan" => {
            let cards: Vec<usize> = match a.get_item("cards")? {
                Some(c) if !c.is_none() => c.extract()?,
                _ => (0..get_usize("count")?).collect(), // 旧形式 {"count": n}
            };
            Action::Mulligan { cards }
        }
        "charge" => Action::Charge { hand: get_usize("hand")? },
        "switch" => Action::Switch { back: get_usize("back")? },
        "levelup" => {
            let cid: String = a.get_item("card")?.unwrap().extract()?;
            Action::Levelup { slot: get_usize("slot")?, card: d.chara_id(&cid).map_err(PyValueError::new_err)? }
        }
        "to_clash" => Action::ToClash,
        "end_turn" => Action::EndTurn,
        "submit" => Action::Submit { hand: get_usize("hand")? },
        "pass" => Action::Pass,
        "pay" => Action::Pay,
        "decline" => Action::Decline,
        "choose_back" => Action::ChooseBack { back: get_i64("back")? },
        "use" => Action::Use,
        "skip" => Action::Skip,
        "choose_count" => Action::ChooseCount { count: get_i64("count")? },
        "discard" => Action::Discard { hand: get_usize("hand")? },
        "choose_card" => {
            let zone_s: String = a.get_item("zone")?.unwrap().extract()?;
            let zone = match zone_s.as_str() { "concerto" => Zone::Concerto, "trash" => Zone::Trash,
                "chara_deck" => Zone::CharaDeck, _ => return Err(PyValueError::new_err("unknown zone")) };
            let cid: String = a.get_item("card")?.unwrap().extract()?;
            let card = if zone == Zone::CharaDeck { d.chara_id(&cid) } else { d.action_id(&cid) }.map_err(PyValueError::new_err)?;
            Action::ChooseCard { zone, index: get_usize("index").unwrap_or(0), card,
                slot: a.get_item("slot")?.map(|x| x.extract()).transpose()? }
        }
        "resolve" => Action::Resolve { index: get_i64("index")? },
        "stop" => Action::Stop,
        "rush" => Action::Rush { hand: get_usize("hand")? },
        other => return Err(PyValueError::new_err(format!("unknown action type {other}"))),
    })
}

fn actions_from_py(d: &CardDb, actions: &Bound<'_, PyDict>) -> PyResult<Vec<(u8, Action)>> {
    let mut out = Vec::with_capacity(2);
    for (k, v) in actions.iter() {
        let pi: u8 = k.extract()?;
        let a = action_from_py(d, v.downcast::<PyDict>()?)?;
        out.push((pi, a));
    }
    Ok(out)
}

/// `initial_state(chara_decks, action_decks, seed)`。デッキは card_id のリスト（席 0, 1）。
/// 構築ルールの検査（`GameConfig.validate`）は Python 側で済ませてから呼ぶこと。
#[pyfunction]
fn initial_state(chara_decks: Vec<Vec<String>>, action_decks: Vec<Vec<String>>, seed: i64) -> PyResult<PyGameState> {
    let d = db()?;
    if chara_decks.len() != 2 || action_decks.len() != 2 {
        return Err(PyValueError::new_err("decks for 2 players required"));
    }
    let conv_c = |v: &Vec<String>| -> PyResult<Vec<u16>> {
        v.iter().map(|s| d.chara_id(s).map_err(PyValueError::new_err)).collect()
    };
    let conv_a = |v: &Vec<String>| -> PyResult<Vec<u16>> {
        v.iter().map(|s| d.action_id(s).map_err(PyValueError::new_err)).collect()
    };
    let cd = [conv_c(&chara_decks[0])?, conv_c(&chara_decks[1])?];
    let ad = [conv_a(&action_decks[0])?, conv_a(&action_decks[1])?];
    Ok(PyGameState { inner: engine::initial_state(&d, &cd, &ad, seed) })
}

#[pyfunction]
fn decision_players(s: &PyGameState) -> Vec<u8> {
    engine::decision_players(&s.inner)
}

#[pyfunction]
fn legal_actions(py: Python<'_>, s: &PyGameState, pi: u8) -> PyResult<PyObject> {
    let d = db()?;
    let acts = engine::legal_actions(&d, &s.inner, pi);
    let items: Vec<PyObject> = acts.iter().map(|a| action_to_py(py, &d, a)).collect::<PyResult<_>>()?;
    Ok(PyList::new_bound(py, items).into_py(py))
}

/// 非破壊 apply。
#[pyfunction]
fn apply(s: &PyGameState, actions: &Bound<'_, PyDict>) -> PyResult<PyGameState> {
    let d = db()?;
    let acts = actions_from_py(&d, actions)?;
    let ns = engine::apply(&d, &s.inner, &acts).map_err(PyValueError::new_err)?;
    Ok(PyGameState { inner: ns })
}

/// 破壊的 apply（呼び出し側が state を専有しているときだけ）。
#[pyfunction]
fn apply_owned(s: &mut PyGameState, actions: &Bound<'_, PyDict>) -> PyResult<()> {
    let d = db()?;
    let acts = actions_from_py(&d, actions)?;
    engine::apply_owned(&d, &mut s.inner, &acts).map_err(PyValueError::new_err)
}

#[pyfunction]
fn outcome(s: &PyGameState) -> Option<i8> {
    engine::outcome(&s.inner)
}

#[pyfunction]
fn observe(py: Python<'_>, s: &PyGameState, pi: u8) -> PyResult<PyObject> {
    let d = db()?;
    Ok(to_py(py, &engine::observe(&d, &s.inner, pi)))
}

// ---------------------------------------------------------------------------
// DRL（`DRL_PLAN.md` 段階 0）: 符号化・ネットの推論（Python 版との一致テスト用の入口）
// ---------------------------------------------------------------------------

/// `encode.encode(observe(s, pi), pi, opp_decklist)` と同じ整数列（Rust 版・`GameState` から直接）。
/// `opp_decklist` は相手のデッキ表の想定（v6・D-124）。
#[pyfunction]
#[pyo3(signature = (s, pi, opp_decklist=None))]
fn encode_obs(s: &PyGameState, pi: u8, opp_decklist: Option<Vec<String>>) -> PyResult<Vec<i8>> {
    let d = db()?;
    let deck = decklist_from_py(&d, opp_decklist)?;
    Ok(encode::encode_state_with(&d, &s.inner, pi, deck.as_deref()))
}

/// 合法手それぞれの行動符号（`encode.action_code` と同じ 6 整数）。順序は `legal_actions` と同じ。
#[pyfunction]
fn encode_actions(s: &PyGameState, pi: u8) -> PyResult<Vec<[i64; encode::ACT_CODE_LEN]>> {
    let d = db()?;
    let acts = engine::legal_actions(&d, &s.inner, pi);
    Ok(acts.iter().map(|a| encode::action_code(&d, &s.inner, pi, a)).collect())
}

/// ネットを読んで (価値, 合法手のスコア) を返す（一致テスト用）。価値の頭が無ければ NaN。
#[pyfunction]
#[pyo3(signature = (path, s, pi, opp_decklist=None))]
fn net_eval(path: &str, s: &PyGameState, pi: u8, opp_decklist: Option<Vec<String>>) -> PyResult<(f64, Vec<f64>)> {
    let d = db()?;
    let n = net::load(path).map_err(PyValueError::new_err)?;
    let deck = decklist_from_py(&d, opp_decklist)?;
    let x: Vec<f32> = encode::encode_state_with(&d, &s.inner, pi, deck.as_deref()).iter().map(|&v| v as f32).collect();
    let h = n.trunk(&x);
    let v = if n.has_value() { n.value_from_trunk(&h) as f64 } else { f64::NAN };
    let acts = engine::legal_actions(&d, &s.inner, pi);
    let scores = if n.has_policy() {
        let feats: Vec<Vec<f32>> = acts.iter().map(|a| encode::expand_action(&d, &encode::action_code(&d, &s.inner, pi, a))).collect();
        n.policy_scores(&h, &feats).iter().map(|&v| v as f64).collect()
    } else {
        Vec::new()
    };
    Ok((v, scores))
}

/// 読み込み済みのネットを忘れる（同じパスを上書きした後に呼ぶ）。
#[pyfunction]
fn net_forget(path: &str) {
    net::forget(path)
}

/// 符号化の版と次元（Python 側の定数と一致することをテストで確かめる）。
#[pyfunction]
fn encoding_info() -> PyResult<(i64, usize, usize)> {
    let d = db()?;
    Ok((encode::ENCODING_VERSION, encode::obs_dim(&d), encode::act_dim(&d)))
}


/// 束ねた対抗ゲームのソルバ（便 A 後半・A-2）を Python から直に呼ぶ口。**検査専用**である。
///
/// なぜ要るか: 対局を回して毎手一致を見るだけでは、**足し算の順序のずれを取りこぼす**
/// ——順序が変わっても平均戦略は 1e-16 しか動かず、同点の手がめったに起きないので
/// 手が割れないことがある（実際に「わざと j を降順に足す」壊し方が対局の検査を
/// すり抜けた）。ここを開けておけば、**戻り値をビット単位で比べられる**。
/// 打ち方には一切関係しない（誰も対局中には呼ばない）。
#[pyfunction]
#[pyo3(signature = (mats, weights, iters=bundle::DEFAULT_ITERS))]
fn solve_bundled(mats: Vec<Vec<Vec<f64>>>, weights: Vec<f64>, iters: usize) -> PyResult<Vec<f64>> {
    if mats.is_empty() || mats.len() != weights.len() {
        return Err(PyValueError::new_err("mats と weights の本数が合わない"));
    }
    Ok(bundle::solve_bundled(&mats, &weights, iters))
}


// ---------------------------------------------------------------------------
// エージェント（R2/R3）
// ---------------------------------------------------------------------------

fn params_from_py(d: Option<&Bound<'_, PyDict>>, base: agents::Params) -> PyResult<agents::Params> {
    let mut p = base;
    let Some(d) = d else { return Ok(p) };
    for (k, v) in d.iter() {
        let k: String = k.extract()?;
        match k.as_str() {
            "counter_weight" => p.counter_weight = v.extract()?,
            "own_color_weight" => p.own_color_weight = v.extract()?,
            "base_weight" => p.base_weight = v.extract()?,
            "scarce_penalty" => p.scarce_penalty = v.extract()?,
            "concerto_target" => p.concerto_target = v.extract()?,
            "charge_min_hand" => p.charge_min_hand = v.extract()?,
            "levelup_min_hand" => p.levelup_min_hand = v.extract()?,
            "switch_min_gain" => p.switch_min_gain = v.extract()?,
            "pay_min_concerto" => p.pay_min_concerto = v.extract()?,
            "keep_deck_min" => p.keep_deck_min = v.extract()?,
            "use_color_mix" => p.use_color_mix = v.extract()?,
            "use_switch" => p.use_switch = v.extract()?,
            "use_charge" => p.use_charge = v.extract()?,
            "use_levelup" => p.use_levelup = v.extract()?,
            "use_card_utility" => p.use_card_utility = v.extract()?,
            other => return Err(PyValueError::new_err(format!("unknown Params field {other}"))),
        }
    }
    Ok(p)
}

fn weights_from_py(d: Option<&Bound<'_, PyDict>>, base: agents::Weights) -> PyResult<agents::Weights> {
    let mut w = base;
    let Some(d) = d else { return Ok(w) };
    for (k, v) in d.iter() {
        let k: String = k.extract()?;
        match k.as_str() {
            "life" => w.life = v.extract()?,
            "concerto" => w.concerto = v.extract()?,
            "hand" => w.hand = v.extract()?,
            "live_red" => w.live_red = v.extract()?,
            "level" => w.level = v.extract()?,
            "resource" => w.resource = v.extract()?,
            other => return Err(PyValueError::new_err(format!("unknown Weights field {other}"))),
        }
    }
    Ok(w)
}

fn decklist_from_py(d: &CardDb, v: Option<Vec<String>>) -> PyResult<Option<Vec<u16>>> {
    match v {
        None => Ok(None),
        Some(ids) => Ok(Some(ids.iter().map(|s| d.action_id(s).map_err(PyValueError::new_err)).collect::<PyResult<_>>()?)),
    }
}

/// `heuristic.HeuristicAgent`
#[pyclass(name = "HeuristicAgent")]
pub struct PyHeuristic {
    inner: agents::Heuristic,
}

#[pymethods]
impl PyHeuristic {
    #[new]
    #[pyo3(signature = (seed, params=None))]
    fn new(seed: i64, params: Option<&Bound<'_, PyDict>>) -> PyResult<Self> {
        Ok(PyHeuristic { inner: agents::Heuristic::new(seed, params_from_py(params, agents::Params::default())?) })
    }
    fn act(&mut self, py: Python<'_>, s: &PyGameState, pi: u8) -> PyResult<PyObject> {
        let d = db()?;
        let a = self.inner.act(&d, &s.inner, pi);
        action_to_py(py, &d, &a)
    }
}

/// 便 C 段 C-2（D-077）: `world_weight` の前提を Python と**同じ文言で**弾く。
/// π₀ が無ければ「相手が出しそうか」を測る物差しが無く、黙って等重みに落ちてしまう。
fn check_world_weight(world_weight: f64, weight_temp: f64, weight_floor: f64,
                      has_opp_policy: bool) -> PyResult<()> {
    if !(0.0..=1.0).contains(&world_weight) {
        return Err(PyValueError::new_err(format!("world_weight は 0..1（受け取った値 {world_weight}）")));
    }
    if weight_temp <= 0.0 {
        return Err(PyValueError::new_err(format!("weight_temp は 0 より大きい（受け取った値 {weight_temp}）")));
    }
    if !(0.0..=1.0).contains(&weight_floor) {
        return Err(PyValueError::new_err(format!("weight_floor は 0..1（受け取った値 {weight_floor}）")));
    }
    if world_weight > 0.0 && !has_opp_policy {
        return Err(PyValueError::new_err(
            "world_weight は opp_policy_net と組でしか使えない（重みが π₀ の到達確率だから）"));
    }
    Ok(())
}

/// 便 C 段 C-3（D-077 追記 3）: `endgame_enum` の前提を Python と**同じ文言で**弾く。
/// 相手のデッキリストを知らないまま列挙すると、相手のデッキが違うとき真の手札を 1 本も含まない。
fn check_endgame(endgame_enum: usize, endgame_eval: usize, endgame_conf: f64,
                 has_decklist: bool) -> PyResult<()> {
    if endgame_eval < 1 {
        return Err(PyValueError::new_err(format!("endgame_eval は 1 以上（受け取った値 {endgame_eval}）")));
    }
    if !(0.0..=1.5).contains(&endgame_conf) {
        return Err(PyValueError::new_err(format!("endgame_conf は 0..1.5（受け取った値 {endgame_conf}）")));
    }
    if endgame_enum > 0 && !has_decklist {
        return Err(PyValueError::new_err(
            "endgame_enum は opp_decklist と組でしか使えない（列挙が相手のデッキリストに寄りかかっているため）"));
    }
    Ok(())
}

/// `greedy.GreedyAgent`
#[pyclass(name = "GreedyAgent")]
pub struct PyGreedy {
    inner: agents::Greedy,
}

#[pymethods]
impl PyGreedy {
    #[new]
    #[pyo3(signature = (seed, weights=None, opp_decklist=None, samples=6, rollout_depth=24, params=None, use_history=false, prior_strength=8.0,
                        lethal_uniform=0.0, known_hand=false,
                        endgame_enum=0, endgame_eval=16, endgame_conf=0.6,
                        world_weight=0.0,
                        weight_temp=2.0, weight_floor=0.2, weight_lookback=3,
                        draw_buckets=0, bundle_p=0.0))]
    #[allow(clippy::too_many_arguments)]
    fn new(seed: i64, weights: Option<&Bound<'_, PyDict>>, opp_decklist: Option<Vec<String>>, samples: usize,
           rollout_depth: usize, params: Option<&Bound<'_, PyDict>>, use_history: bool, prior_strength: f64,
           lethal_uniform: f64, known_hand: bool,
           endgame_enum: usize, endgame_eval: usize, endgame_conf: f64,
           world_weight: f64,
           weight_temp: f64, weight_floor: f64, weight_lookback: usize,
           draw_buckets: usize, bundle_p: f64) -> PyResult<Self> {
        let d = db()?;
        let w = weights_from_py(weights, agents::Weights::default())?;
        let p = params_from_py(params, agents::Params::default())?;
        let pool = decklist_from_py(&d, opp_decklist)?;
        let mut inner = agents::Greedy::new(seed, w, pool, samples, rollout_depth,
                                            vec![state::Phase::ClashSubmit, state::Phase::Rush], p, use_history, prior_strength);
        // 便 A の判断①（D-071 裁定・便 E-0）: `PlannerAgent` は `value_net` 無しの
        // `lethal_uniform` を拒むようにした。しかし切り替え規則そのものは**素の評価の尺度**
        // （±WIN）でしか `uniform` の道を通らないので、Python と Rust の毎手一致を
        // そこで確かめる土台が要る。それがこの口である（既定 0.0＝挙動不変・T-A2 後半）。
        // **champion 候補にもアプリの相手にもしない。**
        if !(0.0..=1.0).contains(&lethal_uniform) {
            return Err(PyValueError::new_err(format!("lethal_uniform は 0..1（受け取った値 {lethal_uniform}）")));
        }
        inner.lethal_uniform = lethal_uniform;
        // 便 C 段 C-1（D-077）: 既定 false＝挙動不変。
        inner.known_hand = known_hand;
        // 便 C 段 C-3（D-077 追記 3）: 既定 0＝挙動不変。
        check_endgame(endgame_enum, endgame_eval, endgame_conf, inner.opp_decklist.is_some())?;
        inner.endgame_enum = endgame_enum;
        inner.endgame_eval = endgame_eval;
        inner.endgame_conf = endgame_conf;
        // 便 C 段 C-2（D-077）: 既定 0.0＝挙動不変。π₀ が無いと重みが測れないので弾く。
        check_world_weight(world_weight, weight_temp, weight_floor,
                           inner.opp_policy_net.is_some())?;
        inner.world_weight = world_weight;
        inner.weight_temp = weight_temp;
        inner.weight_floor = weight_floor;
        inner.weight_lookback = weight_lookback;
        // 便 C 段 C-4（D-077 追記 4）: 既定 0＝挙動不変。
        inner.draw_buckets = draw_buckets;
        inner.bundle_p = bundle_p;
        Ok(PyGreedy { inner })
    }
    fn act(&mut self, py: Python<'_>, s: &PyGameState, pi: u8) -> PyResult<PyObject> {
        let d = db()?;
        let a = self.inner.act(&d, &s.inner, pi);
        action_to_py(py, &d, &a)
    }
    /// 便 A（D-071）: 直前の対抗で使った規則（"uniform" / "pi0" / None）。打ち方には効かない。
    #[getter]
    fn last_clash_rule(&self) -> Option<String> {
        self.inner.last_clash_rule.map(|b| if b { "uniform".to_string() } else { "pi0".to_string() })
    }
    /// 直前の決定で採点した値（決定化 1 本あたり）。毎手一致の検査が点数まで見るために開ける。
    #[getter]
    fn last_scores(&self) -> Vec<f64> {
        self.inner.last_scores.iter().map(|(_, v)| *v).collect()
    }
}

/// `planner.PlannerAgent`（`extra_turns>=1` で `LongHorizonPlanner`・D-046 対策A）
#[pyclass(name = "PlannerAgent")]
pub struct PyPlanner {
    inner: agents::Planner,
}

#[pymethods]
impl PyPlanner {
    #[new]
    #[pyo3(signature = (seed, weights=None, opp_decklist=None, samples=6, rollout_depth=24, charge_candidates=3,
                        leaf_budget=220, turn_rollout=40, plan_samples=4, params=None, tuned=true,
                        use_history=false, prior_strength=8.0, race_after=99, extra_turns=0,
                        opp_policy_net=None, opp_policy_root_only=false, value_net=None,
                        policy_net=None, policy_scope="all", choice_phases=false, solo_samples=1,
                        align_leaves=false, align_rollout=80, align_stop="my_turn",
                        reeval_samples=0, tau=0.0, opp_mix=0.0, nash_delta=0.0, lethal_uniform=0.0,
                        known_hand=false, endgame_enum=0, endgame_eval=16, endgame_conf=0.6,
                        world_weight=0.0, weight_temp=2.0,
                        weight_floor=0.2, weight_lookback=3, draw_buckets=0,
                        bundle_p=0.0))]
    #[allow(clippy::too_many_arguments)]
    fn new(seed: i64, weights: Option<&Bound<'_, PyDict>>, opp_decklist: Option<Vec<String>>, samples: usize,
           rollout_depth: usize, charge_candidates: usize, leaf_budget: i64, turn_rollout: usize,
           plan_samples: usize, params: Option<&Bound<'_, PyDict>>, tuned: bool, use_history: bool,
           prior_strength: f64, race_after: usize, extra_turns: usize,
           opp_policy_net: Option<String>, opp_policy_root_only: bool,
           value_net: Option<String>,
           policy_net: Option<String>, policy_scope: &str, choice_phases: bool, solo_samples: usize,
           align_leaves: bool, align_rollout: usize, align_stop: &str,
           reeval_samples: usize, tau: f64, opp_mix: f64, nash_delta: f64,
           lethal_uniform: f64, known_hand: bool,
           endgame_enum: usize, endgame_eval: usize, endgame_conf: f64,
           world_weight: f64,
           weight_temp: f64, weight_floor: f64, weight_lookback: usize,
           draw_buckets: usize, bundle_p: f64) -> PyResult<Self> {
        let d = db()?;
        // Python 版と同じ既定: weights 未指定かつ tuned なら TUNED_WEIGHTS、params 未指定かつ tuned なら TUNED_PARAMS
        let w = match weights {
            Some(wd) => weights_from_py(Some(wd), agents::Weights::default())?,
            None => if tuned { agents::tuned_weights() } else { agents::Weights::default() },
        };
        let p = match params {
            Some(pd) => params_from_py(Some(pd), agents::Params::default())?,
            None => if tuned { agents::tuned_params() } else { agents::Params::default() },
        };
        let pool = decklist_from_py(&d, opp_decklist)?;
        let mut inner = agents::Planner::new(seed, w, p, pool, samples, rollout_depth, charge_candidates, leaf_budget,
                                             turn_rollout, plan_samples, use_history, prior_strength, race_after, extra_turns);
        // DRL: 相手モデルだけを学習した方策に差し替える（D-057）。真実源は Python の `greedy.py`。
        if let Some(path) = opp_policy_net {
            inner.g.opp_policy_net = Some(net::load(&path).map_err(PyValueError::new_err)?);
        }
        inner.g.opp_policy_root_only = opp_policy_root_only;
        // D-064: 葉の採点を学習した価値ネットに差し替える。spec 経由（`series` / `series_record`）では
        // 前から渡せたが、**1 手ずつ比べる同一性テスト**（`tests/test_value_bootstrap.py::
        // test_vb_rust_matches_python`）はこのクラスを使うので、ここにも同じ口を開けておく。
        // 既定 None なので挙動は変わらない。
        if let Some(path) = value_net {
            inner.g.value_net = Some(net::load(&path).map_err(PyValueError::new_err)?);
        }
        // D-065 便 1 のつまみ。spec 経由（`series`）とクラス経由で**同じ挙動**になること
        // （`tests/test_d065.py` の毎手一致検査はこのクラスを使う）。既定はすべて無効。
        if let Some(path) = policy_net {
            inner.g.policy_net = Some(net::load(&path).map_err(PyValueError::new_err)?);
        }
        inner.g.policy_scope = match policy_scope {
            "all" => 0u8, "proxy" => 1u8, "fallback" => 2u8, "proxy_lite" => 3u8,
            other => return Err(PyValueError::new_err(format!("unknown policy_scope {other}"))),
        };
        inner.g.align_stop = match align_stop {
            "my_turn" => 0u8, "turn_end" => 1u8,
            other => return Err(PyValueError::new_err(format!("unknown align_stop {other}"))),
        };
        inner.g.set_choice_phases(choice_phases);
        inner.g.solo_samples = solo_samples;
        inner.g.align_leaves = align_leaves;
        inner.g.align_rollout = align_rollout;
        inner.g.reeval_samples = reeval_samples;
        inner.g.tau = tau;
        inner.g.opp_mix = opp_mix;
        inner.g.nash_delta = nash_delta;
        // 便 A の判断①（D-071 裁定・便 E-0）: `lethal_uniform` は葉の採点が勝率の尺度
        // （決着済み = 1.0 / 0.0 / 0.5）であることに依存する。`value_net` が無い素の評価では
        // 1.0 は詰みを意味しないので黙って別の意味で動く。Python の `PlannerAgent` と同じ文言で弾く。
        if lethal_uniform > 0.0 && inner.g.value_net.is_none() {
            return Err(PyValueError::new_err(
                "lethal_uniform は value_net と組でしか使えない（詰みの判定が勝率の尺度 1.0 に依存しているため）"));
        }
        inner.g.lethal_uniform = lethal_uniform;
        // 便 C 段 C-1（D-077）: 既定 false＝挙動不変。
        inner.g.known_hand = known_hand;
        // 便 C 段 C-3（D-077 追記 3）: 既定 0＝挙動不変。
        check_endgame(endgame_enum, endgame_eval, endgame_conf, inner.g.opp_decklist.is_some())?;
        inner.g.endgame_enum = endgame_enum;
        inner.g.endgame_eval = endgame_eval;
        inner.g.endgame_conf = endgame_conf;
        // 便 C 段 C-2（D-077）: 既定 0.0＝挙動不変。
        check_world_weight(world_weight, weight_temp, weight_floor,
                           inner.g.opp_policy_net.is_some())?;
        inner.g.world_weight = world_weight;
        inner.g.weight_temp = weight_temp;
        inner.g.weight_floor = weight_floor;
        inner.g.weight_lookback = weight_lookback;
        // 便 C 段 C-4（D-077 追記 4）: 既定 0＝挙動不変。
        inner.g.draw_buckets = draw_buckets;
        inner.g.bundle_p = bundle_p;
        Ok(PyPlanner { inner })
    }
    fn act(&mut self, py: Python<'_>, s: &PyGameState, pi: u8) -> PyResult<PyObject> {
        let d = db()?;
        let a = self.inner.act(&d, &s.inner, pi);
        action_to_py(py, &d, &a)
    }
    /// 便 A（D-071）: 直前の対抗で使った規則（"uniform" / "pi0" / None）。
    /// **打ち方には一切効かない**（検査と診断のためだけ）。
    #[getter]
    fn last_clash_rule(&self) -> Option<String> {
        self.inner.g.last_clash_rule.map(|b| if b { "uniform".to_string() } else { "pi0".to_string() })
    }
    /// 便 A: 直前の対抗の**取り直し**で使った規則（T-A6 が読む）。
    #[getter]
    fn last_reeval_rule(&self) -> Option<String> {
        self.inner.g.last_reeval_rule.map(|b| if b { "uniform".to_string() } else { "pi0".to_string() })
    }
    /// 直前の決定で採点した値（決定化 1 本あたり）。Python の `last_clash["totals"]` と対で、
    /// **毎手一致の検査が「同じ手を選んだ」だけでなく「同じ点数を付けた」ことまで見る**ために開ける。
    /// 打ち方には一切効かない。
    #[getter]
    fn last_scores(&self) -> Vec<f64> {
        self.inner.g.last_scores.iter().map(|(_, v)| *v).collect()
    }
}

/// 発見ループの挑戦者（champion ＋ δ）。`PlannerAgent` の引数に `deltas`（dict のリスト）を足したもの。
#[pyclass(name = "Challenger")]
pub struct PyChallenger {
    inner: intervene::Challenger,
}

#[pymethods]
impl PyChallenger {
    #[new]
    #[pyo3(signature = (seed, deltas, opp_decklist=None, tuned=true, plan_samples=4, race_after=99, extra_turns=0))]
    fn new(seed: i64, deltas: Vec<Bound<'_, PyDict>>, opp_decklist: Option<Vec<String>>, tuned: bool,
           plan_samples: usize, race_after: usize, extra_turns: usize) -> PyResult<Self> {
        let d = db()?;
        let w = if tuned { agents::tuned_weights() } else { agents::Weights::default() };
        let p = if tuned { agents::tuned_params() } else { agents::Params::default() };
        let pool = decklist_from_py(&d, opp_decklist)?;
        let planner = agents::Planner::new(seed, w, p, pool, 6, 24, 3, 220, 40, plan_samples, false, 8.0, race_after, extra_turns);
        let ds: Vec<intervene::Intervention> = deltas.iter().map(|x| delta_from_py(x)).collect::<PyResult<_>>()?;
        Ok(PyChallenger { inner: intervene::Challenger::new(planner, ds) })
    }
    fn act(&mut self, py: Python<'_>, s: &PyGameState, pi: u8) -> PyResult<PyObject> {
        let d = db()?;
        let a = self.inner.act(&d, &s.inner, pi);
        action_to_py(py, &d, &a)
    }
    #[getter]
    fn fired(&self) -> u64 {
        self.inner.fired
    }
}

/// 1局を Rust 内で完結させる。`agents` は "heuristic" / "greedy" / "planner" / "random" の 2 要素。
/// 戻り値は (winner or None, turns, life0, life1, draw, aborted, steps)。
#[pyfunction]
#[pyo3(signature = (chara_decks, action_decks, seed, agent0, agent1, max_turns=200))]
fn play_game(chara_decks: Vec<Vec<String>>, action_decks: Vec<Vec<String>>, seed: i64,
             agent0: &Bound<'_, PyAny>, agent1: &Bound<'_, PyAny>, max_turns: i64)
             -> PyResult<(Option<i8>, i64, i64, i64, bool, bool, i64)> {
    let d = db()?;
    let mut s = initial_state(chara_decks, action_decks, seed)?.inner;
    let mut steps = 0i64;
    while s.outcome.is_none() {
        if s.turn_no > max_turns {
            return Ok((None, s.turn_no, s.players[0].life, s.players[1].life, false, true, steps));
        }
        let need = engine::decision_players(&s);
        if need.is_empty() {
            break;
        }
        let ps = PyGameState { inner: s.clone() };
        let mut acts: Vec<(u8, Action)> = Vec::new();
        for &pi in &need {
            let ag = if pi == 0 { agent0 } else { agent1 };
            let a = ag.call_method1("act", (ps.clone(), pi))?;
            let a = action_from_py(&d, a.downcast::<PyDict>()?)?;
            acts.push((pi, a));
        }
        engine::apply_owned(&d, &mut s, &acts).map_err(PyValueError::new_err)?;
        steps += 1;
    }
    let o = s.outcome;
    let draw = o == Some(state::DRAW);
    Ok((if draw { None } else { o }, s.turn_no, s.players[0].life, s.players[1].life, draw, false, steps))
}


// ---------------------------------------------------------------------------
// Rust 内で完結する対局列（実験の駆動用・並列可）
// ---------------------------------------------------------------------------

/// エージェントの仕様（Python の dict から作る。`kind` で種別を選ぶ）。
#[derive(Clone)]
enum AgentSpec {
    Random,
    Heuristic { params: agents::Params },
    Greedy { w: agents::Weights, params: agents::Params, pool: Option<Vec<u16>>, samples: usize, rollout_depth: usize,
             use_history: bool, prior_strength: f64 },
    Planner { w: agents::Weights, params: agents::Params, pool: Option<Vec<u16>>, samples: usize, rollout_depth: usize,
              charge_candidates: usize, leaf_budget: i64, turn_rollout: usize, plan_samples: usize,
              use_history: bool, prior_strength: f64, race_after: usize, extra_turns: usize,
              deltas: Vec<intervene::Intervention>,
              /// DRL: 葉の価値ネット／代打ちの方策ネット／相手モデルだけの方策ネット（ファイルパス）／根の温度
              value_net: Option<std::sync::Arc<net::Net>>, policy_net: Option<std::sync::Arc<net::Net>>,
              opp_policy_net: Option<std::sync::Arc<net::Net>>, opp_policy_root_only: bool, tau: f64,
              /// D-065 便 1 のつまみ（すべて既定で無効）。真実源は Python の `greedy.py`／`planner.py`。
              policy_scope: u8, choice_phases: bool, solo_samples: usize,
              align_leaves: bool, align_rollout: usize, align_stop: u8, reeval_samples: usize,
              opp_mix: f64, nash_delta: f64, lethal_uniform: f64, known_hand: bool,
              endgame_enum: usize, endgame_eval: usize, endgame_conf: f64,
              world_weight: f64, weight_temp: f64, weight_floor: f64, weight_lookback: usize,
              draw_buckets: usize, bundle_p: f64 },
    /// DRL 段階 1: 探索なし・方策ネットだけで打つ
    Policy { net: std::sync::Arc<net::Net>, tau: f64 },
}

/// 発見ループの δ を Python の dict から作る。`kind` で種別を選ぶ。
fn delta_from_py(d: &Bound<'_, PyDict>) -> PyResult<intervene::Intervention> {
    use intervene::Intervention as I;
    let kind: String = d.get_item("kind")?.ok_or_else(|| PyValueError::new_err("delta.kind required"))?.extract()?;
    let gs = |k: &str| -> PyResult<String> { d.get_item(k)?.ok_or_else(|| PyValueError::new_err(format!("delta.{k} required")))?.extract() };
    let gi = |k: &str, default: i64| -> PyResult<i64> { Ok(match d.get_item(k)? { Some(v) if !v.is_none() => v.extract()?, _ => default }) };
    Ok(match kind.as_str() {
        "rush_chara" => I::RushChara { name: gs("name")?, goal: gi("goal", 2)?, from_turn: gi("from_turn", 1)? },
        "forbid_levelup" => I::ForbidLevelup { name: gs("name")?, level: gi("level", 2)? },
        "fix_leader" => I::FixLeader { name: gs("name")? },
        "prefer_in_clash" => I::PreferInClash { card: gs("card")? },
        "forbid_in_clash" => I::ForbidInClash { card: gs("card")? },
        "forbid_in_rush" => I::ForbidInRush { card: gs("card")? },
        "reserve" => I::Reserve { card: gs("card")? },
        "always_free_rush" => I::AlwaysFreeRush,
        "never_free_rush" => I::NeverFreeRush,
        "charge_if_concerto_empty" => I::ChargeIfConcertoEmpty,
        "levelup_if_hand" => I::LevelupIfHand { min_hand: gi("min_hand", 5)? },
        "no_pass_if_behind" => I::NoPassIfBehind { margin: gi("margin", 3)? },
        "no_switch_until" => I::NoSwitchUntil { until_turn: gi("until_turn", 3)? },
        other => return Err(PyValueError::new_err(format!("unknown delta kind {other}"))),
    })
}

enum AnyAgent {
    Random(pyrandom::PyRandom),
    Heuristic(agents::Heuristic),
    Greedy(agents::Greedy),
    Planner(agents::Planner),
    Challenger(intervene::Challenger),
    Policy(agents::PolicyAgent),
}

impl AnyAgent {
    fn act(&mut self, d: &CardDb, s: &GameState, pi: u8) -> Action {
        match self {
            AnyAgent::Random(r) => {
                let acts = engine::legal_actions(d, s, pi);
                acts[r.choice_index(acts.len())].clone()
            }
            AnyAgent::Heuristic(h) => h.act(d, s, pi),
            AnyAgent::Greedy(g) => g.act(d, s, pi),
            AnyAgent::Planner(p) => p.act(d, s, pi),
            AnyAgent::Challenger(c) => c.act(d, s, pi),
            AnyAgent::Policy(p) => p.act(d, s, pi),
        }
    }
    fn fired(&self) -> u64 {
        match self {
            AnyAgent::Challenger(c) => c.fired,
            _ => 0,
        }
    }
    /// 直前の決定で採点した (手, 値)。探索しなかった決定は空。
    fn last_scores(&self) -> &[(Action, f64)] {
        match self {
            AnyAgent::Greedy(g) => &g.last_scores,
            AnyAgent::Planner(p) => &p.g.last_scores,
            AnyAgent::Challenger(c) => &c.planner.g.last_scores,
            AnyAgent::Policy(p) => &p.last_scores,
            _ => &[],
        }
    }
    /// 直前の決定の「選んだ手を別の決定化で取り直した値」（記録形式 v3 の `fresh`・D-065 §2.5）。
    /// 探索していない決定・`reeval_samples=0`・そもそも探索しない種別なら NaN。
    /// 相手のデッキ表の想定（記録の符号化の信念の要約に使う・D-124）。探索しない種別は None。
    fn opp_pool(&self) -> Option<&[u16]> {
        match self {
            AnyAgent::Greedy(g) => g.opp_decklist.as_deref(),
            AnyAgent::Planner(p) => p.g.opp_decklist.as_deref(),
            AnyAgent::Challenger(c) => c.planner.g.opp_decklist.as_deref(),
            _ => None,
        }
    }

    fn last_fresh(&self) -> f64 {
        match self {
            AnyAgent::Greedy(g) => g.last_fresh,
            AnyAgent::Planner(p) => p.g.last_fresh,
            AnyAgent::Challenger(c) => c.planner.g.last_fresh,
            _ => f64::NAN,
        }
    }
}

fn spec_from_py(d: &CardDb, spec: &Bound<'_, PyDict>) -> PyResult<AgentSpec> {
    let kind: String = spec.get_item("kind")?.ok_or_else(|| PyValueError::new_err("spec.kind required"))?.extract()?;
    let get = |k: &str| -> PyResult<Option<Bound<'_, PyAny>>> { spec.get_item(k) };
    let opt_dict = |k: &str| -> PyResult<Option<Bound<'_, PyDict>>> {
        Ok(match get(k)? { Some(v) if !v.is_none() => Some(v.downcast::<PyDict>()?.clone()), _ => None })
    };
    let opt_pool = |k: &str| -> PyResult<Option<Vec<u16>>> {
        Ok(match get(k)? { Some(v) if !v.is_none() => decklist_from_py(d, Some(v.extract()?))?, _ => None })
    };
    macro_rules! num {
        ($k:expr, $default:expr) => {
            match get($k)? { Some(v) if !v.is_none() => v.extract()?, _ => $default }
        };
    }
    let tuned: bool = num!("tuned", true);
    let opt_net = |k: &str| -> PyResult<Option<std::sync::Arc<net::Net>>> {
        Ok(match get(k)? {
            Some(v) if !v.is_none() => {
                let path: String = v.extract()?;
                Some(net::load(&path).map_err(PyValueError::new_err)?)
            }
            _ => None,
        })
    };
    let spec = match kind.as_str() {
        "random" => AgentSpec::Random,
        "policy" => AgentSpec::Policy {
            net: opt_net("net")?.ok_or_else(|| PyValueError::new_err("policy spec needs net"))?,
            tau: num!("tau", 0.0f64),
        },
        "heuristic" => AgentSpec::Heuristic { params: params_from_py(opt_dict("params")?.as_ref(), agents::Params::default())? },
        "greedy" => AgentSpec::Greedy {
            w: weights_from_py(opt_dict("weights")?.as_ref(), agents::Weights::default())?,
            params: params_from_py(opt_dict("params")?.as_ref(), agents::Params::default())?,
            pool: opt_pool("opp_decklist")?,
            samples: num!("samples", 6usize), rollout_depth: num!("rollout_depth", 24usize),
            use_history: num!("use_history", false), prior_strength: num!("prior_strength", 8.0f64),
        },
        "planner" => AgentSpec::Planner {
            w: match opt_dict("weights")? { Some(wd) => weights_from_py(Some(&wd), agents::Weights::default())?,
                                            None => if tuned { agents::tuned_weights() } else { agents::Weights::default() } },
            params: match opt_dict("params")? { Some(pd) => params_from_py(Some(&pd), agents::Params::default())?,
                                                None => if tuned { agents::tuned_params() } else { agents::Params::default() } },
            pool: opt_pool("opp_decklist")?,
            samples: num!("samples", 6usize), rollout_depth: num!("rollout_depth", 24usize),
            charge_candidates: num!("charge_candidates", 3usize), leaf_budget: num!("leaf_budget", 220i64),
            turn_rollout: num!("turn_rollout", 40usize), plan_samples: num!("plan_samples", 4usize),
            use_history: num!("use_history", false), prior_strength: num!("prior_strength", 8.0f64),
            race_after: num!("race_after", 99usize), extra_turns: num!("extra_turns", 0usize),
            value_net: opt_net("value_net")?, policy_net: opt_net("policy_net")?,
            opp_policy_net: opt_net("opp_policy_net")?,
            opp_policy_root_only: num!("opp_policy_root_only", false),
            tau: num!("tau", 0.0f64),
            // D-065 便 1。`policy_scope` は文字列（未知の値はエラー）。
            policy_scope: {
                let s: String = match get("policy_scope")? { Some(v) if !v.is_none() => v.extract()?, _ => "all".to_string() };
                match s.as_str() {
                    "all" => 0u8, "proxy" => 1u8, "fallback" => 2u8, "proxy_lite" => 3u8,
                    other => return Err(PyValueError::new_err(format!("unknown policy_scope {other}"))),
                }
            },
            choice_phases: num!("choice_phases", false),
            solo_samples: num!("solo_samples", 1usize),
            align_leaves: num!("align_leaves", false),
            align_rollout: num!("align_rollout", 80usize),
            align_stop: {
                let s: String = match get("align_stop")? { Some(v) if !v.is_none() => v.extract()?, _ => "my_turn".to_string() };
                match s.as_str() {
                    "my_turn" => 0u8, "turn_end" => 1u8,
                    other => return Err(PyValueError::new_err(format!("unknown align_stop {other}"))),
                }
            },
            reeval_samples: num!("reeval_samples", 0usize),
            opp_mix: num!("opp_mix", 0.0f64),
            nash_delta: num!("nash_delta", 0.0f64),
            lethal_uniform: num!("lethal_uniform", 0.0f64),
            known_hand: num!("known_hand", false),
            endgame_enum: num!("endgame_enum", 0usize),
            endgame_eval: num!("endgame_eval", 16usize),
            endgame_conf: num!("endgame_conf", 0.6f64),
            world_weight: num!("world_weight", 0.0f64),
            weight_temp: num!("weight_temp", 2.0f64),
            weight_floor: num!("weight_floor", 0.2f64),
            weight_lookback: num!("weight_lookback", 3usize),
            draw_buckets: num!("draw_buckets", 0usize),
            bundle_p: num!("bundle_p", 0.0f64),
            deltas: match get("delta")? {
                Some(v) if !v.is_none() => {
                    if let Ok(one) = v.downcast::<PyDict>() {
                        vec![delta_from_py(one)?]
                    } else {
                        let items: Vec<Bound<'_, PyAny>> = v.extract()?;
                        items.iter().map(|x| delta_from_py(x.downcast::<PyDict>()?)).collect::<PyResult<_>>()?
                    }
                }
                _ => Vec::new(),
            },
        },
        other => return Err(PyValueError::new_err(format!("unknown agent kind {other}"))),
    };
    // 便 A の判断①（D-071 裁定・便 E-0）: `lethal_uniform` は `value_net` と組でしか意味を持たない。
    // **測定は spec の道を通る**（`series` / `series_record`）ので、クラス（`PyPlanner`）だけ塞いでも
    // 穴は残る。ここでも同じ文言で弾く。
    if let AgentSpec::Planner { lethal_uniform, value_net, .. } = &spec {
        if *lethal_uniform > 0.0 && value_net.is_none() {
            return Err(PyValueError::new_err(
                "lethal_uniform は value_net と組でしか使えない（詰みの判定が勝率の尺度 1.0 に依存しているため）"));
        }
    }
    Ok(spec)
}

fn build_agent(spec: &AgentSpec, seed: i64) -> AnyAgent {
    match spec {
        AgentSpec::Random => AnyAgent::Random(pyrandom::PyRandom::from_int_seed(seed)),
        AgentSpec::Heuristic { params } => AnyAgent::Heuristic(agents::Heuristic::new(seed, params.clone())),
        AgentSpec::Greedy { w, params, pool, samples, rollout_depth, use_history, prior_strength } => {
            AnyAgent::Greedy(agents::Greedy::new(seed, w.clone(), pool.clone(), *samples, *rollout_depth,
                                                 vec![state::Phase::ClashSubmit, state::Phase::Rush],
                                                 params.clone(), *use_history, *prior_strength))
        }
        AgentSpec::Policy { net, tau } => AnyAgent::Policy(agents::PolicyAgent::new(seed, net.clone(), *tau)),
        AgentSpec::Planner { w, params, pool, samples, rollout_depth, charge_candidates, leaf_budget, turn_rollout,
                             plan_samples, use_history, prior_strength, race_after, extra_turns, deltas,
                             value_net, policy_net, opp_policy_net, opp_policy_root_only, tau,
                             policy_scope, choice_phases, solo_samples, align_leaves, align_rollout,
                             align_stop, reeval_samples, opp_mix, nash_delta, lethal_uniform, known_hand,
                             endgame_enum, endgame_eval, endgame_conf,
                             world_weight, weight_temp, weight_floor, weight_lookback,
                             draw_buckets, bundle_p } => {
            let mut p = agents::Planner::new(seed, w.clone(), params.clone(), pool.clone(), *samples, *rollout_depth,
                                             *charge_candidates, *leaf_budget, *turn_rollout, *plan_samples,
                                             *use_history, *prior_strength, *race_after, *extra_turns);
            p.g.value_net = value_net.clone();
            p.g.policy_net = policy_net.clone();
            p.g.opp_policy_net = opp_policy_net.clone();
            p.g.opp_policy_root_only = *opp_policy_root_only;
            p.g.tau = *tau;
            p.g.policy_scope = *policy_scope;
            p.g.set_choice_phases(*choice_phases);
            p.g.solo_samples = *solo_samples;
            p.g.align_leaves = *align_leaves;
            p.g.align_rollout = *align_rollout;
            p.g.align_stop = *align_stop;
            p.g.reeval_samples = *reeval_samples;
            p.g.opp_mix = *opp_mix;
            p.g.nash_delta = *nash_delta;
            p.g.lethal_uniform = *lethal_uniform;
            p.g.known_hand = *known_hand;
            p.g.endgame_enum = *endgame_enum;
            p.g.endgame_eval = *endgame_eval;
            p.g.endgame_conf = *endgame_conf;
            p.g.world_weight = *world_weight;
            p.g.weight_temp = *weight_temp;
            p.g.weight_floor = *weight_floor;
            p.g.weight_lookback = *weight_lookback;
            p.g.draw_buckets = *draw_buckets;
            p.g.bundle_p = *bundle_p;
            if deltas.is_empty() {
                AnyAgent::Planner(p)
            } else {
                AnyAgent::Challenger(intervene::Challenger::new(p, deltas.clone()))
            }
        }
    }
}

/// 1局（Rust 内で完結）。戻り値は (winner, turns, life0, life1, draw, aborted, steps, digest)。
///
/// `digest` は全決定の (決定者, 選んだ手) を畳み込んだハッシュ（D-053）。
/// 同じシード・同じ相手で digest が一致する＝**毎手同じ手を選んだ**。
fn run_one(d: &CardDb, cd: &[Vec<u16>; 2], ad: &[Vec<u16>; 2], seed: i64, ags: &mut [AnyAgent; 2], max_turns: i64)
           -> (Option<i8>, i64, i64, i64, bool, bool, i64, u64) {
    let mut s = engine::initial_state(d, cd, ad, seed);
    let mut steps = 0i64;
    let mut digest: u64 = 0xcbf2_9ce4_8422_2325;      // FNV-1a offset basis
    while s.outcome.is_none() {
        if s.turn_no > max_turns {
            return (None, s.turn_no, s.players[0].life, s.players[1].life, false, true, steps, digest);
        }
        let need = engine::decision_players(&s);
        if need.is_empty() {
            break;
        }
        let acts: Vec<(u8, Action)> = need.iter().map(|&pi| (pi, ags[pi as usize].act(d, &s, pi))).collect();
        for (pi, a) in &acts {
            digest = engine::hash_action(digest, *pi, a);
        }
        engine::apply_owned(d, &mut s, &acts).expect("apply failed in run_one");
        steps += 1;
    }
    let o = s.outcome;
    let draw = o == Some(state::DRAW);
    (if draw { None } else { o }, s.turn_no, s.players[0].life, s.players[1].life, draw, false, steps, digest)
}

/// 段階 1C-b（D-123）: 相手デッキ表（`pool`）を**その局の相手の席の**行動デッキに差し替えた仕様を返す。
///
/// `series` 系は奇数シードで A/B の席を入れ替えるが、デッキは席に固定である。仕様に固定の
/// `pool` を持たせると、異種デッキ戦では半分の局で相手デッキ表が誤る。`opp_from_seat=true`
/// のとき、Greedy／Planner の `pool` を `ad[1 - seat]` に置き換える（ほかの種別はそのまま）。
fn with_opp_pool(spec: &AgentSpec, opp_deck: &[u16]) -> AgentSpec {
    let mut sp = spec.clone();
    match &mut sp {
        AgentSpec::Greedy { pool, .. } | AgentSpec::Planner { pool, .. } => *pool = Some(opp_deck.to_vec()),
        _ => {}
    }
    sp
}

/// 1 局ぶんのエージェント 2 体を席順に作る（`series` 系の共通部分）。
/// `flip` なら A が席 1。`opp_from_seat` なら各自の `pool` を相手の席の行動デッキにする。
fn seat_agents(ad: &[Vec<u16>; 2], sa: &AgentSpec, sb: &AgentSpec, seed: i64, flip: bool, opp_from_seat: bool) -> [AnyAgent; 2] {
    let (s0, s1) = if flip { (sb, sa) } else { (sa, sb) };
    if opp_from_seat {
        [build_agent(&with_opp_pool(s0, &ad[1]), seed * 2), build_agent(&with_opp_pool(s1, &ad[0]), seed * 2 + 1)]
    } else {
        [build_agent(s0, seed * 2), build_agent(s1, seed * 2 + 1)]
    }
}

/// `series` / `series_digest` の中身。各シードの (a_won, turns, steps, fired_a, digest)。
fn run_series(d: &Arc<CardDb>, cd: &[Vec<u16>; 2], ad: &[Vec<u16>; 2], sa: &AgentSpec, sb: &AgentSpec,
              seed0: i64, n: i64, workers: usize, max_turns: i64, opp_from_seat: bool) -> Vec<(Option<bool>, i64, i64, u64, u64)> {
    let seeds: Vec<i64> = (seed0..seed0 + n).collect();
    let workers = workers.max(1);
    let job = |seed: i64| -> (Option<bool>, i64, i64, u64, u64) {
        let flip = seed % 2 == 1;
        let mut ags: [AnyAgent; 2] = seat_agents(ad, sa, sb, seed, flip, opp_from_seat);
        let (winner, turns, _l0, _l1, draw, aborted, steps, digest) = run_one(d, cd, ad, seed, &mut ags, max_turns);
        let a_seat: usize = if flip { 1 } else { 0 };
        let fired = ags[a_seat].fired();
        if aborted || draw {
            return (None, turns, steps, fired, digest);
        }
        (Some(winner == Some(a_seat as i8)), turns, steps, fired, digest)
    };
    if workers == 1 {
        seeds.iter().map(|&s| job(s)).collect()
    } else {
        let chunks: Vec<Vec<i64>> = (0..workers).map(|w| seeds.iter().copied().filter(|s| ((s - seed0) as usize) % workers == w).collect()).collect();
        let results: Vec<Vec<(i64, (Option<bool>, i64, i64, u64, u64))>> = std::thread::scope(|sc| {
            let handles: Vec<_> = chunks.iter().map(|ch| sc.spawn(|| ch.iter().map(|&s| (s, job(s))).collect::<Vec<_>>())).collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        });
        let mut flat: Vec<(i64, (Option<bool>, i64, i64, u64, u64))> = results.into_iter().flatten().collect();
        flat.sort_by_key(|(s, _)| *s);
        flat.into_iter().map(|(_, r)| r).collect()
    }
}

/// 記録つきの 1 局（DRL 段階 0・`series_record`）。各決定を `buf` に追記する。
///
/// 1 決定のレコード（リトルエンディアン・**版 3**）:
///   seed i64 / step u32 / turn u16 / pi u8 / phase u8 / n_acts u8 / chosen u8 / z f32 / fresh f32 /
///   obs i8[obs_dim] / acts i8[n_acts*ACT_CODE_LEN] / scores f32[n_acts]（探索していない手は NaN）
/// z は決定者から見た最終結果（勝 1 / 負 0 / 引き分け 0.5 / 打ち切り NaN）。局の終わりに埋める。
/// fresh は「選んだ手を別の決定化で取り直した値」（D-065 A-3 (i)・`reeval_samples=0` なら NaN）。
/// 版 2（fresh 無し）の記録も読み側（`meicho/drl_data.py`）はそのまま読める。
fn run_one_record(d: &CardDb, cd: &[Vec<u16>; 2], ad: &[Vec<u16>; 2], seed: i64, ags: &mut [AnyAgent; 2],
                  max_turns: i64, buf: &mut Vec<u8>, record_seats: [bool; 2])
                  -> (Option<i8>, i64, i64, i64, bool, bool, i64, u64) {
    let mut s = engine::initial_state(d, cd, ad, seed);
    let mut steps = 0i64;
    let mut digest: u64 = 0xcbf2_9ce4_8422_2325;
    let start = buf.len();
    let mut z_slots: Vec<(usize, u8)> = Vec::new();   // (z の位置, 決定者)
    let mut aborted = false;
    while s.outcome.is_none() {
        if s.turn_no > max_turns {
            aborted = true;
            break;
        }
        let need = engine::decision_players(&s);
        if need.is_empty() {
            break;
        }
        let mut acts: Vec<(u8, Action)> = Vec::with_capacity(need.len());
        for &pi in &need {
            let legal = engine::legal_actions(d, &s, pi);
            let a = ags[pi as usize].act(d, &s, pi);
            if record_seats[pi as usize] && legal.len() > 1 {
                let scores = ags[pi as usize].last_scores();
                let chosen = legal.iter().position(|x| *x == a).unwrap_or(255) as u8;
                buf.extend_from_slice(&seed.to_le_bytes());
                buf.extend_from_slice(&(steps as u32).to_le_bytes());
                buf.extend_from_slice(&(s.turn_no.clamp(0, 65535) as u16).to_le_bytes());
                buf.push(pi);
                buf.push(encode_phase(s.phase));
                buf.push(legal.len().min(255) as u8);
                buf.push(chosen);
                z_slots.push((buf.len(), pi));
                buf.extend_from_slice(&f32::NAN.to_le_bytes());
                // 版 3: z の直後に fresh（探索していない決定・reeval_samples=0 なら NaN）
                buf.extend_from_slice(&(ags[pi as usize].last_fresh() as f32).to_le_bytes());
                // v6（D-124）: 信念の要約は記録する席のエージェントの想定デッキ表で作る
                for v in encode::encode_state_with(d, &s, pi, ags[pi as usize].opp_pool()) {
                    buf.push(v as u8);
                }
                for x in legal.iter().take(255) {
                    for v in encode::action_code(d, &s, pi, x) {
                        buf.push((v.clamp(-128, 127) as i8) as u8);
                    }
                }
                for x in legal.iter().take(255) {
                    let sc = scores.iter().find(|(k, _)| k == x).map(|(_, v)| *v as f32).unwrap_or(f32::NAN);
                    buf.extend_from_slice(&sc.to_le_bytes());
                }
            }
            acts.push((pi, a));
        }
        for (pi, a) in &acts {
            digest = engine::hash_action(digest, *pi, a);
        }
        engine::apply_owned(d, &mut s, &acts).expect("apply failed in run_one_record");
        steps += 1;
    }
    let o = s.outcome;
    let draw = o == Some(state::DRAW);
    for (pos, pi) in z_slots {
        let z: f32 = if aborted { f32::NAN } else if draw { 0.5 } else if o == Some(pi as i8) { 1.0 } else { 0.0 };
        buf[pos..pos + 4].copy_from_slice(&z.to_le_bytes());
    }
    let _ = start;
    if aborted {
        return (None, s.turn_no, s.players[0].life, s.players[1].life, false, true, steps, digest);
    }
    (if draw { None } else { o }, s.turn_no, s.players[0].life, s.players[1].life, draw, false, steps, digest)
}

fn encode_phase(p: state::Phase) -> u8 {
    match p {
        state::Phase::SetupChara => 0,
        state::Phase::Mulligan => 1,
        state::Phase::Action => 2,
        state::Phase::ClashSubmit => 3,
        state::Phase::Choice => 4,
        state::Phase::Rush => 5,
        state::Phase::TurnEndDiscard => 6,
        state::Phase::GameOver => 7,
    }
}

/// `series` と同じ約束で回し、A 側（`record_a`）／B 側（`record_b`）の決定を `out_path.<worker>` に書く。
/// 戻り値は各シードの (a_won, turns, steps, fired_a, digest) と、書いたファイルの一覧。
fn run_series_record(d: &Arc<CardDb>, cd: &[Vec<u16>; 2], ad: &[Vec<u16>; 2], sa: &AgentSpec, sb: &AgentSpec,
                     seed0: i64, n: i64, workers: usize, max_turns: i64, out_path: &str,
                     record_a: bool, record_b: bool, opp_from_seat: bool) -> std::io::Result<(Vec<(Option<bool>, i64, i64, u64, u64)>, Vec<String>)> {
    use std::io::Write;
    let seeds: Vec<i64> = (seed0..seed0 + n).collect();
    let workers = workers.max(1);
    let header = |f: &mut std::fs::File| -> std::io::Result<()> {
        f.write_all(b"MCDR")?;
        f.write_all(&3u32.to_le_bytes())?;      // 版 3（`fresh` を足した・D-065 §2.5）
        f.write_all(&(encode::obs_dim(d) as u32).to_le_bytes())?;
        f.write_all(&(encode::ACT_CODE_LEN as u32).to_le_bytes())?;
        Ok(())
    };
    let job = |seed: i64, buf: &mut Vec<u8>| -> (Option<bool>, i64, i64, u64, u64) {
        let flip = seed % 2 == 1;
        let mut ags: [AnyAgent; 2] = seat_agents(ad, sa, sb, seed, flip, opp_from_seat);
        let rec = if flip { [record_b, record_a] } else { [record_a, record_b] };
        let (winner, turns, _l0, _l1, draw, aborted, steps, digest) = run_one_record(d, cd, ad, seed, &mut ags, max_turns, buf, rec);
        let a_seat: usize = if flip { 1 } else { 0 };
        let fired = ags[a_seat].fired();
        if aborted || draw {
            return (None, turns, steps, fired, digest);
        }
        (Some(winner == Some(a_seat as i8)), turns, steps, fired, digest)
    };
    let chunks: Vec<Vec<i64>> = (0..workers).map(|w| seeds.iter().copied().filter(|s| ((s - seed0) as usize) % workers == w).collect()).collect();
    let paths: Vec<String> = (0..workers).map(|w| format!("{out_path}.{w}")).collect();
    let results: Vec<std::io::Result<Vec<(i64, (Option<bool>, i64, i64, u64, u64))>>> = std::thread::scope(|sc| {
        let handles: Vec<_> = chunks.iter().zip(paths.iter()).map(|(ch, path)| sc.spawn(move || {
            let mut f = std::fs::File::create(path)?;
            header(&mut f)?;
            let mut out = Vec::with_capacity(ch.len());
            let mut buf: Vec<u8> = Vec::with_capacity(1 << 20);
            for &s in ch {
                buf.clear();
                let r = job(s, &mut buf);
                f.write_all(&buf)?;
                out.push((s, r));
            }
            f.flush()?;
            Ok(out)
        })).collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });
    let mut flat: Vec<(i64, (Option<bool>, i64, i64, u64, u64))> = Vec::new();
    for r in results {
        flat.extend(r?);
    }
    flat.sort_by_key(|(s, _)| *s);
    Ok((flat.into_iter().map(|(_, r)| r).collect(), paths))
}

fn decks_from_py(d: &CardDb, chara_decks: &[Vec<String>], action_decks: &[Vec<String>])
                 -> PyResult<([Vec<u16>; 2], [Vec<u16>; 2])> {
    let conv_c = |v: &Vec<String>| -> PyResult<Vec<u16>> { v.iter().map(|s| d.chara_id(s).map_err(PyValueError::new_err)).collect() };
    let conv_a = |v: &Vec<String>| -> PyResult<Vec<u16>> { v.iter().map(|s| d.action_id(s).map_err(PyValueError::new_err)).collect() };
    Ok(([conv_c(&chara_decks[0])?, conv_c(&chara_decks[1])?],
        [conv_a(&action_decks[0])?, conv_a(&action_decks[1])?]))
}

/// `arena.series` と同じ約束で A vs B を n 局回す（Rust 内で完結・スレッド並列）。
///
/// シード `seed` の局は、`seed % 2 == 1` なら A が後攻。エージェントの乱数シードは
/// 先攻側が `seed*2`、後攻側が `seed*2+1`（`arena._one` と同じ）。
/// 戻り値は各シードの (a_won: Optional[bool], turns, steps, fired_a)。引き分け・打ち切りは None。
/// `fired_a` は A が挑戦者（delta つき）のとき δ が手に関与した回数（それ以外は 0）。
#[pyfunction]
#[pyo3(signature = (chara_decks, action_decks, spec_a, spec_b, seed0, n, workers=1, max_turns=200, opp_from_seat=false))]
fn series(py: Python<'_>, chara_decks: Vec<Vec<String>>, action_decks: Vec<Vec<String>>,
          spec_a: &Bound<'_, PyDict>, spec_b: &Bound<'_, PyDict>, seed0: i64, n: i64, workers: usize, max_turns: i64,
          opp_from_seat: bool) -> PyResult<Vec<(Option<bool>, i64, i64, u64)>> {
    let d = db()?;
    let sa = spec_from_py(&d, spec_a)?;
    let sb = spec_from_py(&d, spec_b)?;
    let (cd, ad) = decks_from_py(&d, &chara_decks, &action_decks)?;
    let out = py.allow_threads(|| run_series(&d, &cd, &ad, &sa, &sb, seed0, n, workers, max_turns, opp_from_seat));
    Ok(out.into_iter().map(|(w, t, s, f, _)| (w, t, s, f)).collect())
}

/// `series` と同じだが、各局の**手の記録のハッシュ**を 5 番目に返す（D-053）。
///
/// 戻り値は (a_won, turns, steps, fired_a, digest)。同じシード帯・同じ相手で回した
/// 2 つの列の digest が全局一致したら、その 2 者は**毎手同じ手を選んだ**（挙動が同じ）。
/// 発見ループの選別（δ が champion の手を変えたか）に使う。
#[pyfunction]
#[pyo3(signature = (chara_decks, action_decks, spec_a, spec_b, seed0, n, workers=1, max_turns=200, opp_from_seat=false))]
fn series_digest(py: Python<'_>, chara_decks: Vec<Vec<String>>, action_decks: Vec<Vec<String>>,
                 spec_a: &Bound<'_, PyDict>, spec_b: &Bound<'_, PyDict>, seed0: i64, n: i64, workers: usize, max_turns: i64,
                 opp_from_seat: bool) -> PyResult<Vec<(Option<bool>, i64, i64, u64, u64)>> {
    let d = db()?;
    let sa = spec_from_py(&d, spec_a)?;
    let sb = spec_from_py(&d, spec_b)?;
    let (cd, ad) = decks_from_py(&d, &chara_decks, &action_decks)?;
    Ok(py.allow_threads(|| run_series(&d, &cd, &ad, &sa, &sb, seed0, n, workers, max_turns, opp_from_seat)))
}

/// 記録つき自己対戦（DRL 段階 0）。`series_digest` と同じ戻り値に加えて、書いたファイルの一覧を返す。
/// 各決定（合法手が 2 つ以上のもの）を `out_path.<worker>` にバイナリで書く（形式は `run_one_record`）。
#[pyfunction]
#[pyo3(signature = (chara_decks, action_decks, spec_a, spec_b, seed0, n, out_path, workers=1, max_turns=200, record_a=true, record_b=true, opp_from_seat=false))]
fn series_record(py: Python<'_>, chara_decks: Vec<Vec<String>>, action_decks: Vec<Vec<String>>,
                 spec_a: &Bound<'_, PyDict>, spec_b: &Bound<'_, PyDict>, seed0: i64, n: i64, out_path: String,
                 workers: usize, max_turns: i64, record_a: bool, record_b: bool, opp_from_seat: bool)
                 -> PyResult<(Vec<(Option<bool>, i64, i64, u64, u64)>, Vec<String>)> {
    let d = db()?;
    let sa = spec_from_py(&d, spec_a)?;
    let sb = spec_from_py(&d, spec_b)?;
    let (cd, ad) = decks_from_py(&d, &chara_decks, &action_decks)?;
    py.allow_threads(|| run_series_record(&d, &cd, &ad, &sa, &sb, seed0, n, workers, max_turns, &out_path, record_a, record_b, opp_from_seat))
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

/// この wheel に入っている変更の札（検査が「入っている Rust が古いか」を見分けるため）。
///
/// **つまみを増やさない修正を入れたら、ここに 1 行足すこと。** 引数の有無では見分けられないからである
/// （D-065 便 4 の「取り直し専用の乱数」がまさにそれで、外から見える引数は 1 つも変わらない）。
#[pyfunction]
fn features() -> Vec<String> {
    vec![
        "d065_bin1".to_string(),                  // 便 1 のつまみ 5 つ
        "d065_reeval_isolated_rng".to_string(),   // 便 4: 取り直しが本編の乱数列を汚さない（案 C）
        "lethal_uniform".to_string(),             // 便 A（D-071）: 詰みが見えるときだけ相手を等重みに見る
        "known_hand".to_string(),                 // 便 C 段 C-1（D-077）: スキャンで見た札を決定化に必ず入れる
        "world_weight".to_string(),               // 便 C 段 C-2（D-077）: π₀ の到達確率で決定化に重み付け
        "endgame_enum".to_string(),               // 便 C 段 C-3（D-077）: 終盤の整合世界を全列挙して投票
        "draw_buckets".to_string(),               // 便 C 段 C-4（D-077）: 決定化の山札の上位をコスト帯×色で層別に散らす
        "bundle_p".to_string(),                   // 便 A 後半（D-082）: 束ねた対抗ゲームを解いて提出分布を決める
        "bp01_k5".to_string(),                    // 段 K-5: cost_mod / grant_rush_draw_to_variation_skills / levelup の level
        "opp_from_seat".to_string(),              // 段階 1C-b（D-123）: series 系の相手デッキ表を席ごとに相手の行動デッキにする
        "encoding_v6".to_string(),                // 段階 1C-c（D-124）: 符号化 v6（信念の要約・統一した hand_known）
        "te13_switched_scope".to_string(),        // TE-13（D-134）: 【切り替え】は入れ替わった 2 枠だけが誘発する
    ]
}

#[pymodule]
fn meicho_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(encode_obs, m)?)?;
    m.add_function(wrap_pyfunction!(encode_actions, m)?)?;
    m.add_function(wrap_pyfunction!(net_eval, m)?)?;
    m.add_function(wrap_pyfunction!(net_forget, m)?)?;
    m.add_function(wrap_pyfunction!(encoding_info, m)?)?;
    m.add_function(wrap_pyfunction!(solve_bundled, m)?)?;
    m.add_function(wrap_pyfunction!(features, m)?)?;
    m.add_function(wrap_pyfunction!(series_record, m)?)?;
    m.add_class::<PyGameState>()?;
    m.add_function(wrap_pyfunction!(load_cards, m)?)?;
    m.add_function(wrap_pyfunction!(initial_state, m)?)?;
    m.add_function(wrap_pyfunction!(decision_players, m)?)?;
    m.add_function(wrap_pyfunction!(legal_actions, m)?)?;
    m.add_function(wrap_pyfunction!(apply, m)?)?;
    m.add_function(wrap_pyfunction!(apply_owned, m)?)?;
    m.add_function(wrap_pyfunction!(outcome, m)?)?;
    m.add_function(wrap_pyfunction!(observe, m)?)?;
    m.add_function(wrap_pyfunction!(series_digest, m)?)?;
    m.add_class::<PyHeuristic>()?;
    m.add_class::<PyGreedy>()?;
    m.add_class::<PyPlanner>()?;
    m.add_class::<PyChallenger>()?;
    m.add_function(wrap_pyfunction!(play_game, m)?)?;
    m.add_function(wrap_pyfunction!(series, m)?)?;
    Ok(())
}
