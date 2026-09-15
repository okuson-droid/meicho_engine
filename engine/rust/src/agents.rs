//! エージェント（`heuristic.py` / `greedy.py` / `oppmodel.py` / `planner.py` の写し・D-049 R2/R3）。
//!
//! 乱数の消費列を Python 版と bit 単位で揃えるため、同じ順序で同じ関数を呼ぶ。
//! 同一性テスト（`tests/test_rust_agents.py`）が「同じ局面で同じ手を選ぶ」ことを毎手で検証する。
//! 選択の同点処理（`max` / `min` は最初の要素・`sort` は安定）も Python に合わせてある。

use crate::cards::{CardDb, Color};
use crate::encode;
use crate::engine::{self, Action};
use crate::net::Net;
use crate::pyrandom::PyRandom;
use crate::state::{GameState, Phase, DRAW};
use crate::worlds;
use std::sync::Arc;

// ---------------------------------------------------------------------------
// heuristic.py
// ---------------------------------------------------------------------------

/// `heuristic.Params`
#[derive(Clone, Debug)]
pub struct Params {
    pub counter_weight: f64,
    pub own_color_weight: f64,
    pub base_weight: f64,
    pub scarce_penalty: f64,
    pub concerto_target: i64,
    pub charge_min_hand: i64,
    pub levelup_min_hand: i64,
    pub switch_min_gain: i64,
    pub pay_min_concerto: i64,
    pub keep_deck_min: i64,
    pub use_color_mix: bool,
    pub use_switch: bool,
    pub use_charge: bool,
    pub use_levelup: bool,
    pub use_card_utility: bool,
}

impl Default for Params {
    fn default() -> Params {
        Params {
            counter_weight: 0.0,
            own_color_weight: 12.0,
            base_weight: 1.0,
            scarce_penalty: 0.35,
            concerto_target: 4,
            charge_min_hand: 2,
            levelup_min_hand: 5,
            switch_min_gain: 2,
            pay_min_concerto: 3,
            keep_deck_min: 3,
            use_color_mix: true,
            use_switch: true,
            use_charge: true,
            use_levelup: true,
            use_card_utility: true,
        }
    }
}

/// `planner.TUNED_PARAMS`
pub fn tuned_params() -> Params {
    Params {
        own_color_weight: 10.373,
        counter_weight: 0.722,
        scarce_penalty: 0.255,
        concerto_target: 4,
        charge_min_hand: 1,
        levelup_min_hand: 4,
        switch_min_gain: 2,
        pay_min_concerto: 2,
        ..Params::default()
    }
}

/// `heuristic.BEATEN_BY[x]` = x に勝つ色
fn beaten_by(c: Color) -> Color {
    match c {
        Color::Red => Color::Blue,
        Color::Green => Color::Red,
        Color::Blue => Color::Green,
    }
}

/// `heuristic.LEADER_COLOR`（キャラ名 → Lv0【対抗】スキルが報酬を出す色）。
/// Python 版と同じ直書き表（D-047 で導出化が予定されている。導出化は両方同時に行うこと）。
fn leader_color(name: Option<&str>) -> Option<Color> {
    match name? {
        "漂泊者（男）" | "漂泊者（女）" => Some(Color::Green),
        "散華" | "秧秧" => Some(Color::Blue),
        "今汐" | "熾霞" => Some(Color::Red),
        _ => None,
    }
}

fn leader<'a>(db: &'a CardDb, s: &GameState, pi: usize) -> Option<&'a str> {
    s.players[pi].slots[0].last().map(|&c| db.chara[c as usize].name.as_str())
}

/// `_back_names`: [(back, name)]（back = 1, 2 の順）
fn back_names<'a>(db: &'a CardDb, s: &GameState, pi: usize) -> Vec<(usize, &'a str)> {
    (1..3usize)
        .filter_map(|b| s.players[pi].slots[b].last().map(|&c| (b, db.chara[c as usize].name.as_str())))
        .collect()
}

fn effective_cost(s: &GameState, pi: usize, cid: u16, db: &CardDb) -> i64 {
    let c = &db.action[cid as usize];
    let mut cost = c.cost;
    if s.red_cost_up[pi] && c.color == Color::Red {
        cost += 1;
    }
    cost
}

/// `heuristic.live_reds(s, pi, leader=None)`
pub fn live_reds(db: &CardDb, s: &GameState, pi: usize, leader_override: Option<&str>) -> i64 {
    let p = &s.players[pi];
    let ld = match leader_override {
        Some(l) => Some(l),
        None => leader(db, s, pi),
    };
    let mut n = 0;
    for &cid in &p.hand {
        let c = &db.action[cid as usize];
        if c.color != Color::Red {
            continue;
        }
        if c.leader_skill && c.dedicated_to.as_deref() != ld {
            continue;
        }
        if effective_cost(s, pi, cid, db) > p.concerto.len() as i64 {
            continue;
        }
        n += 1;
    }
    n
}

/// `heuristic.card_utility`
pub fn card_utility(db: &CardDb, s: &GameState, pi: usize, cid: u16) -> f64 {
    let c = &db.action[cid as usize];
    let p = &s.players[pi];
    let mut v = c.damage as f64;
    if !c.skills.is_empty() {
        v += 0.5;
    }
    if c.leader_skill && c.dedicated_to.as_deref() != leader(db, s, pi) {
        let in_back = back_names(db, s, pi).iter().any(|(_, n)| Some(*n) == c.dedicated_to.as_deref());
        v -= if in_back { 1.0 } else { 2.5 };
    }
    let over = effective_cost(s, pi, cid, db) - p.concerto.len() as i64;
    if over > 0 {
        v -= 1.2 * over as f64;
    }
    if c.color != Color::Red {
        v += 0.8;
    }
    v
}

/// Python の `max(seq, key)` / `min(seq, key)`（最初の最大／最小を返す）。
fn argmax_by<T, K: PartialOrd>(items: &[T], key: impl Fn(&T) -> K) -> usize {
    let mut best = 0;
    let mut bk = key(&items[0]);
    for (i, it) in items.iter().enumerate().skip(1) {
        let k = key(it);
        if k > bk {
            best = i;
            bk = k;
        }
    }
    best
}
fn argmin_by<T, K: PartialOrd>(items: &[T], key: impl Fn(&T) -> K) -> usize {
    let mut best = 0;
    let mut bk = key(&items[0]);
    for (i, it) in items.iter().enumerate().skip(1) {
        let k = key(it);
        if k < bk {
            best = i;
            bk = k;
        }
    }
    best
}

#[derive(Clone)]
pub struct Heuristic {
    pub rng: PyRandom,
    pub p: Params,
}

impl Heuristic {
    pub fn new(seed: i64, p: Params) -> Heuristic {
        Heuristic { rng: PyRandom::from_int_seed(seed), p }
    }

    /// `_pick`: 重みつき抽選。weights は挿入順。
    fn pick(&mut self, weights: &[(Color, f64)]) -> Color {
        let tot: f64 = weights.iter().map(|(_, w)| w).sum();
        if tot <= 0.0 {
            return weights[self.rng.choice_index(weights.len())].0;
        }
        let r = self.rng.random() * tot;
        let mut acc = 0.0;
        for (k, w) in weights {
            acc += w;
            if r <= acc {
                return *k;
            }
        }
        weights[weights.len() - 1].0
    }

    pub fn act(&mut self, db: &CardDb, s: &GameState, pi: u8) -> Action {
        let acts = engine::legal_actions(db, s, pi);
        assert!(!acts.is_empty(), "no legal actions for P{pi} in {:?}", s.phase);
        match s.phase {
            Phase::SetupChara => self.setup(db, s, pi as usize, &acts),
            Phase::Mulligan => self.mulligan(db, s, pi as usize, &acts),
            Phase::Action => self.action(db, s, pi as usize, &acts),
            Phase::ClashSubmit => self.clash(db, s, pi as usize, &acts),
            Phase::Choice => self.choice(db, s, pi as usize, &acts),
            Phase::Rush => self.rush(db, s, pi as usize, &acts),
            Phase::TurnEndDiscard => self.discard(db, s, pi as usize, &acts),
            Phase::GameOver => acts[self.rng.choice_index(acts.len())].clone(),
        }
    }

    fn setup(&mut self, db: &CardDb, s: &GameState, pi: usize, acts: &[Action]) -> Action {
        let p = &s.players[pi];
        let cnt = |a: &Action| -> i64 {
            let Action::Setup { leader, .. } = a else { unreachable!() };
            p.action_deck.iter().filter(|&&cid| db.action[cid as usize].dedicated_to.as_deref() == Some(leader.as_str())).count() as i64
        };
        let old: Vec<Action> = acts.iter().filter(|a| matches!(a, Action::Setup { backs, .. } if {
            let mut b=backs.clone(); b.sort(); *backs==b })).cloned().collect();
        old[argmax_by(&old, cnt)].clone()
    }

    fn mulligan(&mut self, db: &CardDb, s: &GameState, pi: usize, acts: &[Action]) -> Action {
        let p = &s.players[pi];
        let ld = leader(db, s, pi);
        let mut drop: Vec<usize> = Vec::new();
        for (i, &cid) in p.hand.iter().enumerate() {
            let c = &db.action[cid as usize];
            if c.cost >= 2 {
                drop.push(i);
            } else if c.leader_skill && c.dedicated_to.as_deref() != ld {
                drop.push(i);
            }
        }
        drop.sort_unstable();
        drop.truncate(3);
        for a in acts {
            if let Action::Mulligan { cards } = a {
                if *cards == drop {
                    return a.clone();
                }
            }
        }
        acts.iter().find(|a| matches!(a, Action::Mulligan { cards } if cards.is_empty())).unwrap().clone()
    }

    fn action(&mut self, db: &CardDb, s: &GameState, pi: usize, acts: &[Action]) -> Action {
        let p = &s.players[pi];
        // 1. レベルアップ
        if self.p.use_levelup {
            let lv: Vec<&Action> = acts.iter().filter(|a| matches!(a, Action::Levelup { .. })).collect();
            if !lv.is_empty() && p.hand.len() as i64 > self.p.levelup_min_hand {
                let bi = argmax_by(&lv, |a| {
                    let Action::Levelup { slot, card } = a else { unreachable!() };
                    ((*slot == 0) as i64, db.chara[*card as usize].level)
                });
                let Action::Levelup { card, .. } = lv[bi] else { unreachable!() };
                if p.hand.len() as i64 >= db.chara[*card as usize].level + self.p.charge_min_hand {
                    return lv[bi].clone();
                }
            }
        }
        // 2. 切り替え
        if self.p.use_switch {
            let sw: Vec<&Action> = acts.iter().filter(|a| matches!(a, Action::Switch { .. })).collect();
            if !sw.is_empty() {
                let now = live_reds(db, s, pi, None);
                let backs = back_names(db, s, pi);
                let mut best: Option<&Action> = None;
                let mut gain = 0;
                for a in &sw {
                    let Action::Switch { back } = a else { unreachable!() };
                    let Some((_, nm)) = backs.iter().find(|(b, _)| b == back) else { continue };
                    let g = live_reds(db, s, pi, Some(nm)) - now;
                    if g > gain {
                        best = Some(a);
                        gain = g;
                    }
                }
                if let Some(b) = best {
                    if gain >= self.p.switch_min_gain {
                        return b.clone();
                    }
                }
            }
        }
        // 3. チャージ
        if self.p.use_charge {
            let ch: Vec<&Action> = acts.iter().filter(|a| matches!(a, Action::Charge { .. })).collect();
            if !ch.is_empty()
                && (p.concerto.len() as i64) < self.p.concerto_target
                && p.hand.len() as i64 > self.p.charge_min_hand
            {
                let bi = argmin_by(&ch, |a| {
                    let Action::Charge { hand } = a else { unreachable!() };
                    card_utility(db, s, pi, p.hand[*hand])
                });
                return ch[bi].clone();
            }
        }
        Action::ToClash
    }

    fn clash(&mut self, db: &CardDb, s: &GameState, pi: usize, acts: &[Action]) -> Action {
        let p = &s.players[pi];
        let sub: Vec<&Action> = acts.iter().filter(|a| matches!(a, Action::Submit { .. })).collect();
        if sub.is_empty() {
            return Action::Pass;
        }
        let opp_leader = leader(db, s, 1 - pi);
        let my_leader = leader(db, s, pi);
        let counter = leader_color(opp_leader).map(beaten_by);
        let mine = leader_color(my_leader);

        // 色ごとの候補（挿入順）
        let mut bycol: Vec<(Color, Vec<&Action>)> = Vec::new();
        for a in &sub {
            let Action::Submit { hand } = a else { unreachable!() };
            let col = db.action[p.hand[*hand] as usize].color;
            if let Some(e) = bycol.iter_mut().find(|(c, _)| *c == col) {
                e.1.push(a);
            } else {
                bycol.push((col, vec![a]));
            }
        }
        if !self.p.use_color_mix {
            return sub[self.rng.choice_index(sub.len())].clone();
        }
        let mut weights: Vec<(Color, f64)> = Vec::new();
        for (col, _) in &bycol {
            let mut w = self.p.base_weight;
            if Some(*col) == counter {
                w += self.p.counter_weight;
            }
            if Some(*col) == mine {
                w += self.p.own_color_weight;
            }
            if *col != Color::Red {
                let held = p.hand.iter().filter(|&&cid| db.action[cid as usize].color == *col).count();
                w *= 1.0 - self.p.scarce_penalty / (held.max(1) as f64);
            }
            weights.push((*col, w.max(0.01)));
        }
        let col = self.pick(&weights);
        let cand = &bycol.iter().find(|(c, _)| *c == col).unwrap().1;
        let bi = argmax_by(cand, |a| {
            let Action::Submit { hand } = a else { unreachable!() };
            let c = &db.action[p.hand[*hand] as usize];
            (c.damage, c.speed)
        });
        cand[bi].clone()
    }

    fn rush(&mut self, db: &CardDb, s: &GameState, pi: usize, acts: &[Action]) -> Action {
        let p = &s.players[pi];
        let r: Vec<&Action> = acts.iter().filter(|a| matches!(a, Action::Rush { .. })).collect();
        if r.is_empty() {
            return Action::Stop;
        }
        let bi = argmax_by(&r, |a| {
            let Action::Rush { hand } = a else { unreachable!() };
            db.action[p.hand[*hand] as usize].damage
        });
        r[bi].clone()
    }

    fn discard(&mut self, db: &CardDb, s: &GameState, pi: usize, acts: &[Action]) -> Action {
        let p = &s.players[pi];
        let d: Vec<&Action> = acts.iter().filter(|a| matches!(a, Action::Discard { .. })).collect();
        if d.is_empty() {
            return acts[self.rng.choice_index(acts.len())].clone();
        }
        if !self.p.use_card_utility {
            return d[self.rng.choice_index(d.len())].clone();
        }
        let bi = argmin_by(&d, |a| {
            let Action::Discard { hand } = a else { unreachable!() };
            card_utility(db, s, pi, p.hand[*hand])
        });
        d[bi].clone()
    }

    fn choice(&mut self, db: &CardDb, s: &GameState, pi: usize, acts: &[Action]) -> Action {
        use crate::state::Choice;
        let p = &s.players[pi];
        match &s.pending_choices[0] {
            Choice::PayOrDamage { amount, .. } => {
                if p.concerto.len() as i64 >= self.p.pay_min_concerto && p.life > *amount {
                    Action::Pay
                } else {
                    Action::Decline
                }
            }
            Choice::SwitchBack { .. } => {
                let backs = back_names(db, s, pi);
                let bi = argmax_by(acts, |a| {
                    let Action::ChooseBack { back } = a else { unreachable!() };
                    let nm = backs.iter().find(|(b, _)| *b as i64 == *back).map(|(_, n)| *n);
                    live_reds(db, s, pi, nm)
                });
                acts[bi].clone()
            }
            Choice::UseOptional { .. } => Action::Use,
            Choice::RevealCount { max, .. } => {
                let mut n = *max;
                if (p.action_deck.len() + p.trash.len()) as i64 <= self.p.keep_deck_min {
                    n = n.min(p.action_deck.len() as i64);
                }
                Action::ChooseCount { count: n }
            }
            Choice::Discard { .. } | Choice::DiscardForEffect { .. } => self.discard(db, s, pi, acts),
            Choice::Order { .. } => acts[0].clone(),
            Choice::PayCostCard { .. } | Choice::ZoneCard { .. } =>
                acts.iter().find(|a| matches!(a, Action::ChooseCard { .. })).unwrap_or(&acts[0]).clone(),
            Choice::LevelupByEffect { .. } => {
                let i=argmax_by(acts, |a| match a { Action::ChooseCard { card, .. } => db.chara[*card as usize].level, _ => -1 });
                acts[i].clone()
            }
        }
    }
}

// ---------------------------------------------------------------------------
// oppmodel.py
// ---------------------------------------------------------------------------

#[derive(Clone)]
pub struct OppModel {
    pub rng: PyRandom,
    pub k: f64,
    pub enabled: bool,
}

impl OppModel {
    pub fn new(seed: i64, k: f64, enabled: bool) -> OppModel {
        OppModel { rng: PyRandom::from_int_seed(seed), k, enabled }
    }

    pub fn act(&mut self, db: &CardDb, fallback: &mut Heuristic, s: &GameState, opp: u8) -> Action {
        if !self.enabled || s.phase != Phase::ClashSubmit {
            return fallback.act(db, s, opp);
        }
        let acts = engine::legal_actions(db, s, opp);
        let sub: Vec<&Action> = acts.iter().filter(|a| matches!(a, Action::Submit { .. })).collect();
        if acts.len() <= 1 || sub.is_empty() {
            return fallback.act(db, s, opp);
        }
        let counts = s.clash_counts[opp as usize];
        let n = (counts[0] + counts[1] + counts[2]) as f64;
        if n <= 0.0 || self.rng.random() >= n / (n + self.k) {
            return fallback.act(db, s, opp);
        }
        let hand = &s.players[opp as usize].hand;
        let mut bycol: Vec<(Color, Vec<&Action>)> = Vec::new();
        for a in &sub {
            let Action::Submit { hand: h } = a else { unreachable!() };
            let col = db.action[hand[*h] as usize].color;
            if let Some(e) = bycol.iter_mut().find(|(c, _)| *c == col) {
                e.1.push(a);
            } else {
                bycol.push((col, vec![a]));
            }
        }
        let weights: Vec<(Color, i64)> = bycol.iter().map(|(c, _)| (*c, counts[c.clash_index()])).collect();
        let total: i64 = weights.iter().map(|(_, w)| w).sum();
        if total <= 0 {
            return fallback.act(db, s, opp);
        }
        let r = self.rng.random() * total as f64;
        let mut acc = 0.0;
        let mut col = weights[weights.len() - 1].0;
        for (c, w) in &weights {
            acc += *w as f64;
            if r <= acc {
                col = *c;
                break;
            }
        }
        let cand = &bycol.iter().find(|(c, _)| *c == col).unwrap().1;
        let bi = argmax_by(cand, |a| {
            let Action::Submit { hand: h } = a else { unreachable!() };
            let c = &db.action[hand[*h] as usize];
            (c.damage, c.speed)
        });
        cand[bi].clone()
    }
}

// ---------------------------------------------------------------------------
// 合法手の制限（発見ループの「禁じる」型 δ・D-050）
// ---------------------------------------------------------------------------

/// 「禁じる」型の制限。`None` なら合法手はそのまま（既定の挙動と完全に同じ）。
#[derive(Clone, Debug)]
pub enum Restrict {
    ForbidLevelup { name: String, level: i64 },
    ForbidInClash { card: String },
    ForbidInRush { card: String },
    Reserve { card: String },
    NeverFreeRush,
    NoPassIfBehind { margin: i64 },
    NoSwitchUntil { until_turn: i64 },
}

impl Restrict {
    pub fn allows(&self, db: &CardDb, s: &GameState, pi: u8, a: &Action) -> bool {
        let pu = pi as usize;
        let hand = &s.players[pu].hand;
        match (self, a) {
            (Restrict::ForbidLevelup { name, level }, Action::Levelup { card, .. }) => {
                let c = &db.chara[*card as usize];
                !(c.name == *name && c.level == *level)
            }
            (Restrict::ForbidInClash { card }, Action::Submit { hand: h }) => db.action[hand[*h] as usize].name != *card,
            (Restrict::Reserve { card }, Action::Submit { hand: h }) => db.action[hand[*h] as usize].name != *card,
            (Restrict::ForbidInRush { card }, Action::Rush { hand: h }) => db.action[hand[*h] as usize].name != *card,
            (Restrict::NeverFreeRush, Action::Rush { hand: h }) => {
                let c = &db.action[hand[*h] as usize];
                !(c.cost == 0 && c.damage > 0)
            }
            (Restrict::NoPassIfBehind { margin }, Action::Pass) => {
                !(s.players[pu].life <= s.players[1 - pu].life - margin)
            }
            (Restrict::NoSwitchUntil { until_turn }, Action::Switch { .. }) => s.turn_no > *until_turn,
            _ => true,
        }
    }
}

/// 制限つきの合法手。絞った結果が空なら絞らない（合法手が無くなることはない）。
/// 複数の制限は「すべてが許す手」だけを残す。
pub fn restricted_legal(db: &CardDb, s: &GameState, pi: u8, rs: &[Restrict]) -> Vec<Action> {
    let acts = engine::legal_actions(db, s, pi);
    if rs.is_empty() {
        return acts;
    }
    let kept: Vec<Action> = acts.iter().filter(|a| rs.iter().all(|r| r.allows(db, s, pi, a))).cloned().collect();
    if kept.is_empty() { acts } else { kept }
}

// ---------------------------------------------------------------------------
// greedy.py
// ---------------------------------------------------------------------------

pub const WIN: f64 = 10_000.0;

#[derive(Clone, Debug)]
pub struct Weights {
    pub life: f64,
    pub concerto: f64,
    pub hand: f64,
    pub live_red: f64,
    pub level: f64,
    pub resource: f64,
}

impl Default for Weights {
    fn default() -> Weights {
        Weights { life: 1.0, concerto: 0.8, hand: 0.5, live_red: 0.4, level: 0.0, resource: 0.05 }
    }
}

/// `planner.TUNED_WEIGHTS`
pub fn tuned_weights() -> Weights {
    Weights { life: 1.0, concerto: 1.034, hand: 1.126, live_red: 0.533, level: 0.498, resource: 0.061 }
}

fn levels(db: &CardDb, p: &crate::state::PlayerState) -> i64 {
    p.slots.iter().filter_map(|sl| sl.last()).map(|&c| db.chara[c as usize].level).sum()
}

/// `greedy.evaluate`。加算の順序を Python と揃える（浮動小数の一致のため）。
pub fn evaluate(db: &CardDb, s: &GameState, pi: usize, w: &Weights) -> f64 {
    if let Some(o) = s.outcome {
        if o == DRAW {
            return 0.0;
        }
        return if o as usize == pi { WIN } else { -WIN };
    }
    let me = &s.players[pi];
    let opp = &s.players[1 - pi];
    let mut v = w.life * ((me.life - opp.life) as f64);
    v += w.concerto * ((me.concerto.len() as i64 - opp.concerto.len() as i64) as f64);
    v += w.hand * ((me.hand.len() as i64 - opp.hand.len() as i64) as f64);
    v += w.live_red * (live_reds(db, s, pi, None) as f64);
    v += w.level * ((levels(db, me) - levels(db, opp)) as f64);
    v += w.resource
        * (((me.action_deck.len() + me.trash.len()) as i64 - (opp.action_deck.len() + opp.trash.len()) as i64) as f64);
    v
}

/// `GreedyAgent`（決定化・安定化・葉の採点・対抗と単独決定）。`Planner` の土台。
#[derive(Clone)]
pub struct Greedy {
    pub rng: PyRandom,
    pub w: Weights,
    pub opp_decklist: Option<Vec<u16>>,
    pub samples: usize,
    pub rollout_depth: usize,
    /// 担当フェイズ（それ以外は fallback）
    pub phases: Vec<Phase>,
    pub fallback: Heuristic,
    pub opp_model: OppModel,
    /// 発見ループの「禁じる」型 δ（複数可）。空なら既定の挙動。
    pub restrict: Vec<Restrict>,
    /// DRL（`DRL_PLAN.md`）: 葉の採点をネットの価値に差し替える。None なら `evaluate`（既定・挙動不変）。
    pub value_net: Option<Arc<Net>>,
    /// DRL: 代打ち（自分のロールアウト方策・相手モデル・非担当フェイズ）をネットの方策に差し替える。
    /// None なら H（既定・挙動不変）。
    pub policy_net: Option<Arc<Net>>,
    /// DRL（D-057・`DRL_NOTES.md` §3-1 案 (b)）: **相手モデルの決定だけ**をネットの方策に差し替える。
    /// 相手モデルが働くのは対抗の提出（`OppModel::act` 自身がそれ以外を H に落とす）だけなので、
    /// 差し替わるのも対抗の提出だけである。自分の代打ち・非担当フェイズは H のまま。
    /// 覆う範囲は**対抗の提出における相手の手だけ**であり、`policy_net`（それ以外の代打ちを覆う）とは別の口。
    /// 両方渡した場合、対抗の提出は `opp_policy_net`・それ以外の代打ちは `policy_net` が担う。
    /// なお `Greedy::clash` が標本ごとに読む相手の提出は `policy_net` では差し替わらない
    /// （段階 0 の実装がそこを相手モデル直呼びにしているため）。この口だけがそこに届く。
    /// None なら従来の色履歴モデル（既定・挙動不変）。
    pub opp_policy_net: Option<Arc<Net>>,
    /// DRL（D-057）: `opp_policy_net` を効かせる範囲。
    /// `true` なら**根の対抗の決定で標本ごとに読む相手の提出だけ**（1 決定につき `samples` 回・ほぼ無料）。
    /// `false` なら葉のロールアウト中の相手の提出にも効かせる（1 決定につき数百回・約 45 倍遅い）。
    pub opp_policy_root_only: bool,
    /// DRL: 根の手を softmax(値/tau) で抽選する温度（自己対戦の多様性用）。0 なら最良手（既定）。
    pub tau: f64,
    /// D-065 A-5': `policy_net` を効かせる範囲。0 = all（従来どおり代打ちと担当外の手の両方）／
    /// 1 = proxy（代打ちだけ）／2 = fallback（担当外の実際の手だけ）／
    /// 3 = proxy_lite（代打ちのうち**相手のアクションフェイズと自分の対抗の提出だけ**・§9-4 (a) の速度の手当て）。既定 0。
    pub policy_scope: u8,
    /// D-065 A-1: 選択フェイズ（Choice）と手札上限の捨て札（TurnEndDiscard）も担当にする。既定 false。
    pub choice_phases: bool,
    /// D-065 A-1: `solo` の決定化の本数（1 = 従来どおり）。
    pub solo_samples: usize,
    /// D-065 A-2: 対抗・連撃・選択の葉を「次に自分がターンプレイヤーになるターン」まで揃える。既定 false。
    pub align_leaves: bool,
    /// D-065 A-2: そこまで進める最大手数。
    pub align_rollout: usize,
    /// D-065 §2.4: 葉をどこまで運ぶか。0 = my_turn（次に自分がターンプレイヤーになるターン・本案）／
    /// 1 = turn_end（いま進行中のターンが終わるところ＝計画探索の `to_clash` の葉と同じ地点・別解）。
    pub align_stop: u8,
    /// D-065 A-3 (i): 選んだ手を**別の決定化**で取り直す本数（0 = 取り直さない・既定）。
    pub reeval_samples: usize,
    /// D-065 便 4（案 C・マスター裁定 2026-09-04）: **取り直し専用の乱数**。
    ///
    /// 取り直しは「選んだ手を別の決定化で測り直す」処理だが、その別の決定化を
    /// 本編と同じ乱数の流れから引いていたため、**同じシードでも取り直しの有無で対局が変わって**いた。
    /// そうなると (1) manifest の `regenerate` を打っても同じ記録が作り直せない
    /// (2) 取り直しの有無を同じシードで比べられない、の 2 つが壊れる。
    /// そこで取り直しの間だけ 3 本の乱数器（`rng` / `fallback.rng` / `opp_model.rng`）を
    /// この流れから作った種に差し替え、終わったら元の状態に戻す（`reeval_begin` / `reeval_end`）。
    pub reeval_rng: PyRandom,
    /// D-065 A-8（§12・`HUMAN_GAMES_20260903_NOTES.md`）: 対抗の相手モデルを広げる度合い。
    /// 0 なら従来どおり「決定化ごとに π₀ の最尤 1 手」。0 より大きいと
    /// 「(1−opp_mix)·最尤 ＋ opp_mix·相手の合法手の等重み」で期待値を取る。
    pub opp_mix: f64,
    /// D-065 A-9（`D065_NOTES.md` A-9）: 均衡を土台にした δ 制限つきの搾取。
    /// 0 なら従来どおり。0 より大きいと、決定化ごとに 自分×相手 の行列を regret matching で解いて
    /// **均衡値**を合計し、均衡値が最大から `nash_delta` 以内の手のうち
    /// 「相手の合法手が等重み（＝うっかりする相手）」での期待値が最大の手を選ぶ。
    pub nash_delta: f64,
    /// 文献計画 便 A（D-071）: 「詰みが見えるときだけ、相手を等重みに見る」しきい値 θ。
    /// 0 なら従来どおり（挙動不変）。0 より大きいと、対抗の決定化ごとに自分×相手の行列を全部埋め、
    /// `lethal_frac[i]`（手 i が相手の列のうち詰みになった割合の平均）を作り、
    /// `max_i lethal_frac[i] >= θ` のときだけ**相手の合法手を等重みで見た期待値**で選ぶ。
    /// 真実源は Python の `greedy.py`。`opp_mix` / `nash_delta` とは同時に使えない。
    pub lethal_uniform: f64,
    /// 文献計画 便 C 段 C-2（II-8・D-077）: 決定化に「もっともらしさ」の重みを付ける。
    /// 0（既定）なら重みはちょうど 1.0 になり 1 ビットも変わらない。真実源は Python の `greedy.py`。
    pub world_weight: f64,
    /// 段 C-2: π₀ のロジットを割る温度 T（既定 2.0）。
    pub weight_temp: f64,
    /// 段 C-2: 確率の下限 ε（既定 0.2）。どの世界の重みも 0 にしない。
    pub weight_floor: f64,
    /// 段 C-2: 何回前までの対抗提出を見るか（既定 3）。
    pub weight_lookback: usize,
    /// 段 C-2: 相手の対抗提出の履歴 (公開局面, 出した札, そのときの相手の公開領域)。
    /// **相手の手札も山札も入らない**（`public_frame` が落とす）。
    pub opp_history: Vec<(GameState, Option<u16>, Vec<u16>)>,
    /// 段 C-2: 自分が提出した時点の公開局面（結果待ち）。
    pub pending_clash: Option<(GameState, Vec<u16>)>,
    /// 文献計画 便 C 段 C-3（II-9・D-077 追記 3）: W ≤ この数なら決定化をやめて全列挙する。
    /// 0（既定）なら 1 ビットも変わらない。真実源は Python の `greedy.py` / `meicho/worlds.py`。
    pub endgame_enum: usize,
    /// 段 C-3: 列挙した手札を重みの大きい順に何本まで使うか（既定 16）。
    pub endgame_eval: usize,
    /// 段 C-3: 投票の信頼度のしきい値 C（既定 0.6）。下回ったら加重平均の手に戻す。
    pub endgame_conf: f64,
    /// 便 C 段 C-4（D-077 追記 4）: 決定化の山札の上位 3 枚を層別に散らす（0 = 従来どおり）
    pub draw_buckets: usize,
    /// 文献計画 便 A 後半（A-2・D-082）: 束ねた対抗ゲームを解いて提出分布を決める。
    /// 0（既定）なら 1 ビットも変わらない。真実源は Python の `greedy.py`。
    /// `opp_mix` / `nash_delta` / `lethal_uniform` / `tau` とは同時に使えない
    /// （Python 側が起動時に弾くので、ここでは弾かない）。
    /// **p = 1.0 は全列が同値**になるので、列を 1 本しか採点せず現行と一手一点まで同じに落ちる。
    pub bundle_p: f64,
    /// 段 C-3: 直前の `worlds` が列挙だったか。**打ち方には効かない**（投票の入口の判定に使う）。
    pub worlds_enumerated: bool,
    /// 段 C-3: 列挙に入った決定の数（検査と診断用。打ち方には効かない）。
    pub endgame_uses: usize,
    /// 文献計画 便 C 段 C-1（II-7 (a)・D-077）: スキャンで見た札を決定化に必ず入れる。
    /// `false`（既定）なら 1 ビットも変わらない。真実源は Python の `greedy.py`。
    /// **覗き見ではない**——使うのは `engine::known_opponent_hand_ids`
    /// （＝`observe` が返す `opp.hand_known` と同じ中身）だけで、相手の真の手札には触れない。
    pub known_hand: bool,
    /// 直前の対抗で使った規則（true = uniform／false = pi0）。`lethal_uniform=0` なら None。
    /// **打ち方には効かない**（検査と記録のためだけ）。
    pub last_clash_rule: Option<bool>,
    /// 直前の対抗の**取り直し**で使った規則。T-A6（取り直しが同じ規則を使う）が読む。
    pub last_reeval_rule: Option<bool>,
    /// 直前の決定で採点した (手, 値)。記録つき自己対戦（`series_record`）が教師として読む。
    pub last_scores: Vec<(Action, f64)>,
    /// 直前の決定の「選んだ手を別の決定化で取り直した値」（記録形式 v3 の `fresh`）。
    /// 探索していない決定・`reeval_samples=0` なら NaN。
    pub last_fresh: f64,
}

impl Greedy {
    pub fn new(seed: i64, w: Weights, opp_decklist: Option<Vec<u16>>, samples: usize, rollout_depth: usize,
               phases: Vec<Phase>, params: Params, use_history: bool, prior_strength: f64) -> Greedy {
        Greedy {
            rng: PyRandom::from_int_seed(seed),
            w,
            opp_decklist,
            samples,
            rollout_depth,
            phases,
            fallback: Heuristic::new(seed, params),
            opp_model: OppModel::new(seed, prior_strength, use_history),
            restrict: Vec::new(),
            value_net: None,
            policy_net: None,
            opp_policy_net: None,
            opp_policy_root_only: false,
            tau: 0.0,
            policy_scope: 0,
            choice_phases: false,
            solo_samples: 1,
            align_leaves: false,
            align_rollout: 80,
            align_stop: 0,
            reeval_samples: 0,
            // 本編（`rng`）と同じ種から作ると流れが重なるので、札をずらして別の流れにする。
            // ずらし方は固定なので、同じ seed なら取り直しの値も毎回同じである。
            reeval_rng: PyRandom::from_int_seed(seed ^ 0x5245_4556),   // "REEV"
            opp_mix: 0.0,
            nash_delta: 0.0,
            lethal_uniform: 0.0,
            world_weight: 0.0,
            weight_temp: 2.0,
            weight_floor: 0.2,
            weight_lookback: 3,
            opp_history: Vec::new(),
            pending_clash: None,
            endgame_enum: 0,
            endgame_eval: 16,
            endgame_conf: 0.6,
            draw_buckets: 0,
            bundle_p: 0.0,
            worlds_enumerated: false,
            endgame_uses: 0,
            known_hand: false,
            last_clash_rule: None,
            last_reeval_rule: None,
            last_scores: Vec::new(),
            last_fresh: f64::NAN,
        }
    }

    /// D-065 A-1: 選択フェイズと手札上限の捨て札を担当に加える（既に入っていれば何もしない）。
    /// `Greedy::new` / `Planner::new` のあとに呼ぶ（Python 版 `GreedyAgent.__init__` と同じ結果）。
    pub fn set_choice_phases(&mut self, on: bool) {
        self.choice_phases = on;
        if on {
            for p in [Phase::Choice, Phase::TurnEndDiscard] {
                if !self.phases.contains(&p) {
                    self.phases.push(p);
                }
            }
        }
    }

    /// ネットの方策で手を選ぶ（合法手の中で softmax）。tau=0 なら最大スコアの手（同点は最初）。
    /// 抽選の乱数は `rng` で受け取る（代打ちでは fallback の乱数＝共通乱数の対象）。
    pub fn policy_pick(db: &CardDb, net: &Net, s: &GameState, q: u8, acts: &[Action], tau: f64,
                       rng: &mut PyRandom) -> usize {
        if acts.len() == 1 {
            return 0;
        }
        let x: Vec<f32> = encode::encode_state(db, s, q).iter().map(|&v| v as f32).collect();
        let h = net.trunk(&x);
        let feats: Vec<Vec<f32>> = acts.iter().map(|a| encode::expand_action(db, &encode::action_code(db, s, q, a))).collect();
        let scores = net.policy_scores(&h, &feats);
        soft_pick(&scores.iter().map(|&v| v as f64).collect::<Vec<_>>(), tau, rng)
    }

    /// ネットの価値（勝つ確率）。決着済みなら 1 / 0 / 0.5（学習の教師と同じ）。
    pub fn net_value(db: &CardDb, net: &Net, s: &GameState, pi: usize) -> f64 {
        if let Some(o) = s.outcome {
            if o == DRAW {
                return 0.5;
            }
            return if o as usize == pi { 1.0 } else { 0.0 };
        }
        let x: Vec<f32> = encode::encode_state(db, s, pi as u8).iter().map(|&v| v as f32).collect();
        net.value(&x) as f64
    }

    // ---- 段 C-2（II-8・D-077）: 決定化の重み -----------------------------
    /// 相手の手札と山札の**中身を落とした**局面の写し（履歴に積む器）。
    /// 山札は枚数だけ残す（枚数は公開情報。π₀ の入力に入るのは `deck_count` だけ）。
    fn public_frame(&self, db: &CardDb, s: &GameState, pi: usize) -> GameState {
        let mut t = s.clone();
        let n_deck = t.players[1 - pi].action_deck.len();
        let filler = self.deck_filler(db, s, pi);
        t.players[1 - pi].hand.clear();
        t.players[1 - pi].action_deck = match filler {
            Some(c) => vec![c; n_deck],
            None => Vec::new(),
        };
        t
    }

    /// 山札の枚数合わせに使う札（中身は答えに効かない・選び方は決定的）。
    /// **並べ替えは card_id の文字列順**（Python の `sorted(deck)[0]` と同じ）。
    fn deck_filler(&self, db: &CardDb, s: &GameState, pi: usize) -> Option<u16> {
        let me = &s.players[pi];
        let deck: Vec<u16> = match &self.opp_decklist {
            Some(d) => d.clone(),
            None => me.action_deck.iter().chain(&me.hand).chain(&me.concerto)
                .chain(&me.trash).chain(&me.action_area).copied().collect(),
        };
        deck.iter().copied().min_by_key(|&c| db.action_rank[c as usize])
    }

    /// 相手が手札から出し終えた札（公開領域）の多重集合。**並びは揃えておく**。
    fn opp_public_cards(s: &GameState, pi: usize) -> Vec<u16> {
        let opp = &s.players[1 - pi];
        let mut v: Vec<u16> = opp.concerto.iter().chain(&opp.trash).chain(&opp.action_area)
            .copied().collect();
        v.sort_unstable();
        v
    }

    /// `act` の入口で呼ぶ。前の対抗の結果が公開されていれば履歴に積む。
    /// 相手が何を出したかは `last_clash_cards`（公開情報・§6.4(1)-3）から取る。
    pub fn note_history(&mut self, s: &GameState, pi: usize) {
        if self.world_weight <= 0.0 || self.pending_clash.is_none() {
            return;
        }
        if s.phase == Phase::ClashSubmit {
            return;                      // まだ解決していない（同じ対抗の中）
        }
        let (frame, before) = self.pending_clash.take().unwrap();
        let cid = s.last_clash_cards[1 - pi];
        self.opp_history.push((frame, cid, before));
        let keep = self.weight_lookback;
        if self.opp_history.len() > keep {
            let drop = self.opp_history.len() - keep;
            self.opp_history.drain(0..drop);
        }
    }

    /// 自分が対抗で提出する時点の公開局面を控える（結果は次の `act` で確定する）。
    fn remember_clash(&mut self, db: &CardDb, s: &GameState, pi: usize) {
        if self.world_weight <= 0.0 {
            return;
        }
        self.pending_clash = Some((self.public_frame(db, s, pi), Self::opp_public_cards(s, pi)));
    }

    /// 「相手がその手札を持っていたら、π₀ は `cid` を出しただろうか」の確率。
    /// `p_{T,ε} = (1−ε)·softmax(ロジット / T) + ε/|合法手|`。同じ札が複数あれば**和**を取る。
    fn reach_prob(&self, db: &CardDb, frame: &GameState, pi: usize, hand: &[u16],
                  cid: Option<u16>) -> f64 {
        let q = (1 - pi) as u8;
        let mut u = frame.clone();
        u.players[1 - pi].hand = hand.to_vec();
        let acts = engine::legal_actions(db, &u, q);
        if acts.is_empty() {
            return 1.0;
        }
        let net = match &self.opp_policy_net {
            Some(n) => n.clone(),
            None => return 1.0,
        };
        let x: Vec<f32> = encode::encode_state(db, &u, q).iter().map(|&v| v as f32).collect();
        let h = net.trunk(&x);
        let feats: Vec<Vec<f32>> = acts.iter()
            .map(|a| encode::expand_action(db, &encode::action_code(db, &u, q, a))).collect();
        let scores = net.policy_scores(&h, &feats);
        let t = self.weight_temp;
        let mx = scores.iter().map(|&v| v as f64 / t).fold(f64::NEG_INFINITY, f64::max);
        let ex: Vec<f64> = scores.iter().map(|&v| (v as f64 / t - mx).exp()).collect();
        let tot: f64 = ex.iter().sum();
        let eps = self.weight_floor;
        let n = acts.len() as f64;
        let mut p = 0.0;
        for (a, e) in acts.iter().zip(ex.iter()) {
            let hit = match cid {
                None => matches!(a, Action::Pass),
                Some(c) => match a {
                    Action::Submit { hand: idx } => u.players[1 - pi].hand[*idx] == c,
                    _ => false,
                },
            };
            if hit {
                p += (1.0 - eps) * (e / tot) + eps / n;
            }
        }
        p
    }

    /// 決定化 K 本の重み（合計 1）。履歴が空なら等重み。
    pub fn world_weights(&self, db: &CardDb, s: &GameState, pi: usize,
                         hands: &[Vec<u16>]) -> Vec<f64> {
        let k = hands.len();
        if k == 0 {
            return Vec::new();
        }
        let u = 1.0 - self.world_weight;
        if self.opp_history.is_empty() {
            return vec![1.0 / k as f64; k];
        }
        let now_public = Self::opp_public_cards(s, pi);
        let mut etas = Vec::with_capacity(k);
        for hand in hands {
            let mut eta = 1.0f64;
            for (frame, cid, before) in &self.opp_history {
                // 手札_w^t ＝「w が仮定するいまの手札」＋「t 以降に相手が手札から出した札」。
                // **上限の近似**である（§7 の 6）。多重集合の引き算は Python の
                // `Counter - Counter`（負にならない）と同じ結果になるように書く。
                let mut left = before.clone();
                let mut since: Vec<u16> = Vec::new();
                for &c in &now_public {
                    match left.iter().position(|&x| x == c) {
                        Some(ix) => { left.remove(ix); }
                        None => since.push(c),
                    }
                }
                since.sort_unstable();
                let mut seq = hand.clone();
                seq.extend_from_slice(&since);
                eta *= self.reach_prob(db, frame, pi, &seq, *cid);
            }
            etas.push(eta);
        }
        let tot: f64 = etas.iter().sum();
        if tot <= 0.0 {
            return vec![1.0 / k as f64; k];
        }
        etas.iter().map(|e| (1.0 - u) * (e / tot) + u / k as f64).collect()
    }

    /// 決定化 n 本とその重み（つまみ 0 なら**ちょうど 1.0 が n 個**）。
    /// `determinize` が引くのは `self.rng` だけ、採点が引くのは `fallback.rng` と
    /// `opp_model.rng` で**別の流れ**なので、まとめて先に作っても乱数の並びは変わらない。
    pub fn worlds(&mut self, db: &CardDb, s: &GameState, pi: usize, n: usize)
                  -> (Vec<GameState>, Vec<f64>) {
        // 段 C-3（II-9）: W が小さければ引かずに全部数える。つまみ 0 なら通らない。
        self.worlds_enumerated = false;
        if self.endgame_enum > 0 {
            if let Some(got) = self.enumerated_worlds(db, s, pi, n) {
                self.worlds_enumerated = true;
                self.endgame_uses += 1;
                return got;
            }
        }
        let ts: Vec<GameState> = (0..n).map(|j| self.determinize(db, s, pi, j)).collect();
        if self.world_weight <= 0.0 {
            return (ts, vec![1.0; n]);
        }
        let hands: Vec<Vec<u16>> = ts.iter().map(|t| t.players[1 - pi].hand.clone()).collect();
        let ws = self.world_weights(db, s, pi, &hands);
        let scaled = ws.iter().map(|w| w * n as f64).collect();
        (ts, scaled)
    }

    /// `_unseen`: 相手の手札にありうるカード（多重集合。順序は呼び出し側で sorted する）
    fn unseen(&self, s: &GameState, pi: usize) -> Vec<u16> {
        let opp = &s.players[1 - pi];
        let me = &s.players[pi];
        let deck: Vec<u16> = match &self.opp_decklist {
            Some(d) => d.clone(),
            None => me.action_deck.iter().chain(&me.hand).chain(&me.concerto).chain(&me.trash).chain(&me.action_area).copied().collect(),
        };
        let mut pool = deck;
        for cid in opp.concerto.iter().chain(&opp.trash).chain(&opp.action_area) {
            if let Some(pos) = pool.iter().position(|c| c == cid) {
                pool.remove(pos);
            }
        }
        pool
    }

    /// `sorted(list_of_card_ids)`（card_id 文字列順）
    fn sort_by_id(db: &CardDb, v: &mut Vec<u16>) {
        v.sort_by_key(|&c| db.action_rank[c as usize]);
    }

    /// 段 C-3: `hand_known` 込みの「必ず手札に入る札」（`known_hand` が false なら空）。
    fn known_in_hand(&self, db: &CardDb, s: &GameState, pi: usize) -> Vec<u16> {
        if !self.known_hand {
            return Vec::new();
        }
        let mut known = engine::known_opponent_hand_ids(s, pi);
        Self::sort_by_id(db, &mut known);
        known
    }

    /// 段 C-3（II-9）: W ≤ `endgame_enum` なら列挙した世界と重みを返す。そうでなければ `None`。
    /// 重みは多重度を正規化して合計 n に揃える（下流の目盛りを決定化 n 本と同じに保つ）。
    /// 真実源は Python の `GreedyAgent._enumerated_worlds`。
    fn enumerated_worlds(&mut self, db: &CardDb, s: &GameState, pi: usize, n: usize)
                         -> Option<(Vec<GameState>, Vec<f64>)> {
        let pool = self.unseen(s, pi);
        let known = self.known_in_hand(db, s, pi);
        let n_hand = s.players[1 - pi].hand.len();
        let w = worlds::world_count_w(db, &pool, n_hand, &known)?;
        if w == 0 || w > self.endgame_enum as u64 {
            return None;
        }
        let hands = worlds::enumerate_hands(db, &pool, n_hand, &known, self.endgame_eval);
        if hands.is_empty() {
            return None;
        }
        let ts: Vec<GameState> = hands.iter()
            .enumerate()
            .map(|(j, (h, _))| self.determinize_with_hand(db, s, pi, h, j))
            .collect();
        let mut ws: Vec<f64> = hands.iter().map(|(_, w)| *w).collect();
        if self.world_weight > 0.0 {
            let only: Vec<Vec<u16>> = hands.iter().map(|(h, _)| h.clone()).collect();
            let extra = self.world_weights(db, s, pi, &only);
            ws = ws.iter().zip(extra.iter()).map(|(a, b)| a * b).collect();
        }
        let tot: f64 = ws.iter().sum();
        let k = ts.len();
        if tot <= 0.0 {
            return Some((ts, vec![n as f64 / k as f64; k]));
        }
        let scaled = ws.iter().map(|w| w / tot * n as f64).collect();
        Some((ts, scaled))
    }

    /// 段 C-4: `draw_buckets` が立っているときだけ山札の上位を層別に並べ替える。
    /// つまみ 0 のときは**何もしない**（乱数も引かない）ので既定の道は 1 ビットも変わらない。
    fn stratify(&mut self, db: &CardDb, deck: &mut Vec<u16>, world_ix: usize) {
        if self.draw_buckets > 0 {
            crate::buckets::stratify_top(db, deck, world_ix, &mut self.rng);
        }
    }

    /// 段 C-3: 相手の手札を**指定した多重集合に固定**して決定化する。
    /// `determinize` との違いは「手札を引くかどうか」だけで、乱数の引き方は同じである。
    fn determinize_with_hand(&mut self, db: &CardDb, s: &GameState, pi: usize, hand: &[u16],
                             world_ix: usize) -> GameState {
        let mut t = s.clone();
        let mut deck = t.players[pi].action_deck.clone();
        Self::sort_by_id(db, &mut deck);
        self.rng.shuffle(&mut deck);
        self.stratify(db, &mut deck, world_ix);
        t.players[pi].action_deck = deck;

        let mut pool = self.unseen(s, pi);
        Self::sort_by_id(db, &mut pool);
        let mut rest = worlds::remove_multiset(&pool, hand);
        self.rng.shuffle(&mut rest);
        t.players[1 - pi].hand = hand.to_vec();
        let n_deck = t.players[1 - pi].action_deck.len();
        if rest.len() >= n_deck {
            t.players[1 - pi].action_deck = rest[..n_deck].to_vec();
        } else {
            let mut d = t.players[1 - pi].action_deck.clone();
            Self::sort_by_id(db, &mut d);
            self.rng.shuffle(&mut d);
            t.players[1 - pi].action_deck = d;
        }
        let mut od = std::mem::take(&mut t.players[1 - pi].action_deck);
        self.stratify(db, &mut od, world_ix);
        t.players[1 - pi].action_deck = od;
        t
    }

    /// `_determinize`（D-026）
    pub fn determinize(&mut self, db: &CardDb, s: &GameState, pi: usize, world_ix: usize) -> GameState {
        let mut t = s.clone();
        let mut deck = t.players[pi].action_deck.clone();
        Self::sort_by_id(db, &mut deck);
        self.rng.shuffle(&mut deck);
        // 段 C-4（D-077 追記 4）: つまみが立っているときだけ上位 3 枚を層別に散らす。
        self.stratify(db, &mut deck, world_ix);
        t.players[pi].action_deck = deck;

        let mut pool = self.unseen(s, pi);
        Self::sort_by_id(db, &mut pool);
        // 段 C-1（II-7 (a)・D-077）: `known_hand` が立っているときは、スキャンで見えている札を
        // **候補から抜いてから混ぜ、必ず相手の手札に戻す**。乱数の消費は `shuffle` 1 回のままで、
        // つまみが false なら `known` は空＝従来と 1 ビットも変わらない。
        let mut known: Vec<u16> = if self.known_hand {
            engine::known_opponent_hand_ids(s, pi)
        } else {
            Vec::new()
        };
        if !known.is_empty() {
            Self::sort_by_id(db, &mut known);
            for &cid in known.iter() {
                match pool.iter().position(|&c| c == cid) {
                    Some(ix) => { pool.remove(ix); }
                    // Python 版は ValueError を投げる。ここで黙って無視すると
                    // 毎手一致が「同じ手だが別の理由」で崩れるので、同じ場所で落とす。
                    None => panic!("hand_known の札が未公開の候補に無い: {}", db.action[cid as usize].card_id),
                }
            }
        }
        self.rng.shuffle(&mut pool);
        let n_hand = t.players[1 - pi].hand.len().min(known.len() + pool.len());
        let n_draw = n_hand.saturating_sub(known.len());
        // 見えている札を先頭に置く（並びは `sort_by_id` で決まるので決定的）。
        let mut hand = known.clone();
        hand.extend_from_slice(&pool[..n_draw]);
        t.players[1 - pi].hand = hand;
        let rest = &pool[n_draw..];
        let n_deck = t.players[1 - pi].action_deck.len();
        if rest.len() >= n_deck {
            t.players[1 - pi].action_deck = rest[..n_deck].to_vec();
        } else {
            let mut d = t.players[1 - pi].action_deck.clone();
            Self::sort_by_id(db, &mut d);
            self.rng.shuffle(&mut d);
            t.players[1 - pi].action_deck = d;
        }
        let mut od = std::mem::take(&mut t.players[1 - pi].action_deck);
        self.stratify(db, &mut od, world_ix);
        t.players[1 - pi].action_deck = od;
        t
    }

    pub fn eval(&self, db: &CardDb, s: &GameState, pi: usize) -> f64 {
        match &self.value_net {
            Some(n) => Self::net_value(db, n, s, pi),
            None => evaluate(db, s, pi, &self.w),
        }
    }

    /// `_proxy_act`。`policy_net` があれば自分の代打ちも相手の手もネットの方策（最良手）で埋める。
    /// ただし**相手の対抗の提出**は `opp_policy_net` が設定されていればそちらが優先する（D-057）。
    pub fn proxy_act(&mut self, db: &CardDb, s: &GameState, q: u8, me: u8) -> Action {
        if q != me && s.phase == Phase::ClashSubmit && !self.opp_policy_root_only
            && self.opp_policy_net.is_some() {
            return self.opp_act(db, s, q, true);
        }
        // D-065 A-5': policy_scope=2（fallback だけ）のときは代打ちに効かせない。
        // 3（proxy_lite）は相手の ACTION と自分の対抗の提出だけに絞る（§9-4 (a)）。
        if self.policy_scope != 2 && (self.policy_scope != 3 || Self::lite_target(s, q, me)) {
            if let Some(net) = self.policy_net.clone() {
                let acts = engine::legal_actions(db, s, q);
                let i = Self::policy_pick(db, &net, s, q, &acts, 0.0, &mut self.fallback.rng);
                return acts[i].clone();
            }
        }
        if q == me {
            self.fallback.act(db, s, q)
        } else {
            self.opp_act(db, s, q, !self.opp_policy_root_only)
        }
    }

    /// 相手モデルの手。`opp_policy_net` があれば**対抗の提出だけ**ネットの方策（最良手）で埋め、
    /// それ以外のフェイズは従来どおり H（`OppModel::act` の落とし先と同じ）。D-057。
    /// 抽選の乱数は `fallback.rng`（共通乱数の対象）を使うが、tau=0 のため実際には消費しない。
    /// `allow_net` が false の呼び出し（`opp_policy_root_only` のときの葉のロールアウト）では
    /// ネットを読まず従来の相手モデルに落とす。
    fn opp_act(&mut self, db: &CardDb, s: &GameState, q: u8, allow_net: bool) -> Action {
        if allow_net && s.phase == Phase::ClashSubmit {
            if let Some(net) = self.opp_policy_net.clone() {
                let acts = engine::legal_actions(db, s, q);
                let i = Self::policy_pick(db, &net, s, q, &acts, 0.0, &mut self.fallback.rng);
                return acts[i].clone();
            }
        }
        self.opp_model.act(db, &mut self.fallback, s, q)
    }

    /// 非担当フェイズの手（`policy_net` があればネット、無ければ H）。
    fn fallback_act(&mut self, db: &CardDb, s: &GameState, pi: u8) -> Action {
        // D-065 A-5': policy_scope=1（代打ちだけ）と 3（proxy_lite）は実際の手に効かせない
        if self.policy_scope != 1 && self.policy_scope != 3 {
            if let Some(net) = self.policy_net.clone() {
                let acts = engine::legal_actions(db, s, pi);
                let i = Self::policy_pick(db, &net, s, pi, &acts, self.tau, &mut self.rng);
                return acts[i].clone();
            }
        }
        self.fallback.act(db, s, pi)
    }

    /// D-065 A-2: `align_leaves` の目標ターン（**決定した局面**から決める）。
    /// `align_stop=1`（turn_end・§2.4 の別解）では常に +1＝いま進行中のターンの終わりまで。
    fn goal_turn(&self, s: &GameState, pi: u8) -> i64 {
        if self.align_stop == 1 {
            return s.turn_no + 1;
        }
        s.turn_no + if s.turn_player == pi { 2 } else { 1 }
    }

    /// `proxy_lite` で π を使う代打ちか（相手のアクションフェイズ／自分の対抗の提出）。
    fn lite_target(s: &GameState, q: u8, me: u8) -> bool {
        (q != me && s.phase == Phase::Action) || (q == me && s.phase == Phase::ClashSubmit)
    }

    /// D-065 A-2: turn_no が goal 以上の最初の非 Choice 局面まで代打ちで進めて採点する。
    /// `Planner::value_after_turn`（extra_turns=1）と同じ打ち切りである。
    fn value_to_my_turn(&mut self, db: &CardDb, mut u: GameState, pi: u8, goal: i64) -> f64 {
        for _ in 0..self.align_rollout {
            if u.outcome.is_some() || u.phase == Phase::GameOver {
                break;
            }
            if u.turn_no >= goal && u.phase != Phase::Choice {
                break;
            }
            let need = engine::decision_players(&u);
            if need.is_empty() {
                break;
            }
            self.step_proxy(db, &mut u, &need, pi);
        }
        self.eval(db, &u, pi as usize)
    }

    /// D-065 A-2: 共通乱数の保存（`align_leaves` のときだけ・Python の `_save_crn` と同じ）。
    fn save_crn(&self) -> Option<(RngState, RngState)> {
        if !self.align_leaves {
            return None;
        }
        Some((self.fallback.rng.getstate(), self.opp_model.rng.getstate()))
    }

    fn restore_crn(&mut self, crn: &Option<(RngState, RngState)>) {
        if let Some((f, o)) = crn {
            self.fallback.rng.setstate(f);
            self.opp_model.rng.setstate(o);
        }
    }

    /// D-065 便 4（案 C）: 取り直しの間だけ、乱数器を**取り直し専用の流れ**に差し替える。
    /// 返り値を `reeval_end` に渡すと本編の乱数列が完全に元へ戻る。
    ///
    /// 取り直しの中で乱数を引くのは次の 3 本だけである。
    /// `rng`（決定化の混ぜ方）／`fallback.rng`（葉のロールアウトの手）／`opp_model.rng`（相手の提出）。
    /// **ここに 4 本目が増えたら、この関数にも足すこと。**
    fn reeval_begin(&mut self) -> (RngState, RngState, RngState) {
        let saved = (self.rng.getstate(), self.fallback.rng.getstate(), self.opp_model.rng.getstate());
        // 取り直しごとに違う決定化になるよう、専用の流れから 3 本ぶんの種を引く
        let a = self.reeval_rng.getrandbits(62) as i64;
        let b = self.reeval_rng.getrandbits(62) as i64;
        let c = self.reeval_rng.getrandbits(62) as i64;
        self.rng = PyRandom::from_int_seed(a);
        self.fallback.rng = PyRandom::from_int_seed(b);
        self.opp_model.rng = PyRandom::from_int_seed(c);
        saved
    }

    fn reeval_end(&mut self, saved: (RngState, RngState, RngState)) {
        self.rng.setstate(&saved.0);
        self.fallback.rng.setstate(&saved.1);
        self.opp_model.rng.setstate(&saved.2);
    }

    fn step_proxy(&mut self, db: &CardDb, s: &mut GameState, need: &[u8], me: u8) {
        let acts: Vec<(u8, Action)> = need.iter().map(|&q| (q, self.proxy_act(db, s, q, me))).collect();
        engine::apply_owned(db, s, &acts).expect("proxy apply failed");
    }

    /// `_settle`（s を専有していること）
    pub fn settle(&mut self, db: &CardDb, mut s: GameState, pi: u8) -> GameState {
        let turn0 = s.turn_no;
        for _ in 0..self.rollout_depth {
            if s.outcome.is_some() {
                break;
            }
            if matches!(s.phase, Phase::Action | Phase::ClashSubmit | Phase::GameOver) {
                break;
            }
            if s.turn_no != turn0 && s.phase != Phase::Choice {
                break;
            }
            let need = engine::decision_players(&s);
            if need.is_empty() {
                break;
            }
            self.step_proxy(db, &mut s, &need, pi);
        }
        s
    }

    pub fn act(&mut self, db: &CardDb, s: &GameState, pi: u8) -> Action {
        // 段 C-2: 前の対抗の結果（公開情報）が出ていれば履歴に積む。つまみ 0 なら何もしない。
        self.note_history(s, pi as usize);
        self.last_scores.clear();
        self.last_fresh = f64::NAN;
        self.last_clash_rule = None;
        self.last_reeval_rule = None;
        let acts = restricted_legal(db, s, pi, &self.restrict);
        assert!(!acts.is_empty(), "no legal actions for P{pi} in {:?}", s.phase);
        if acts.len() == 1 {
            return acts[0].clone();
        }
        if !self.phases.contains(&s.phase) || matches!(s.phase, Phase::SetupChara | Phase::Mulligan) {
            return self.fallback_act(db, s, pi);
        }
        if s.phase == Phase::ClashSubmit {
            return self.clash(db, s, pi, &acts);
        }
        self.solo(db, s, pi, &acts)
    }

    /// `_solo`（D-065 A-1: 決定化を `solo_samples` 本にし、合計で比べる）
    pub fn solo(&mut self, db: &CardDb, s: &GameState, pi: u8, acts: &[Action]) -> Action {
        let goal = if self.align_leaves { self.goal_turn(s, pi) } else { 0 };
        let n = self.solo_samples.max(1);
        let mut totals = vec![0.0f64; acts.len()];
        let (ts, ws) = self.worlds(db, s, pi as usize, n);   // 段 C-2: つまみ 0 なら重み 1.0
        for (t, w) in ts.iter().zip(ws.iter()) {
            let crn = self.save_crn();
            for (i, a) in acts.iter().enumerate() {
                self.restore_crn(&crn);
                totals[i] += w * self.score_solo(db, t, pi, a, goal);
            }
        }
        self.last_scores = acts.iter().cloned().zip(totals.iter().map(|v| v / n as f64)).collect();
        let bi = Self::pick_index(&totals, n, self.tau, &mut self.rng);
        // D-065 A-3 (i): 選んだ手を**別の決定化**で取り直す（記録の `fresh`）。
        if self.reeval_samples > 0 {
            let saved = self.reeval_begin();
            self.last_fresh = self.reeval_solo(db, s, pi, &acts[bi], goal);
            self.reeval_end(saved);
        }
        acts[bi].clone()
    }

    /// 合計から 1 つ選ぶ（同点は最初）。`tau > 0` のときだけ平均で抽選する。
    /// 合計と平均は同じ順序だが、割り算の丸めで同点が生まれうるので既定の道では割らない。
    fn pick_index(totals: &[f64], n: usize, tau: f64, rng: &mut PyRandom) -> usize {
        if tau > 0.0 {
            let avg: Vec<f64> = totals.iter().map(|v| v / n.max(1) as f64).collect();
            soft_pick(&avg, tau, rng)
        } else {
            argmax_by(totals, |v| *v)
        }
    }

    fn score_solo(&mut self, db: &CardDb, t: &GameState, pi: u8, a: &Action, goal: i64) -> f64 {
        let u = engine::apply(db, t, &[(pi, a.clone())]).expect("apply failed in score_solo");
        let u = self.settle(db, u, pi);
        if self.align_leaves {
            self.value_to_my_turn(db, u, pi, goal)
        } else {
            self.eval(db, &u, pi as usize)
        }
    }

    /// D-065 A-3 (i): 選んだ手だけを新しい決定化で採点し直して平均する（二重推定）。
    fn reeval_solo(&mut self, db: &CardDb, s: &GameState, pi: u8, a: &Action, goal: i64) -> f64 {
        let mut tot = 0.0;
        for j in 0..self.reeval_samples {
            let t = self.determinize(db, s, pi as usize, j);
            tot += self.score_solo(db, &t, pi, a, goal);
        }
        tot / self.reeval_samples as f64
    }

    fn clash(&mut self, db: &CardDb, s: &GameState, pi: u8, acts: &[Action]) -> Action {
        let goal = if self.align_leaves { self.goal_turn(s, pi) } else { 0 };
        // 段 C-2: この対抗の公開局面を控える（結果は次の `act` で確定する）。
        self.remember_clash(db, s, pi as usize);
        let (totals, alts, rule, bmats, bws) =
            self.clash_totals(db, s, pi, acts, self.samples, goal, None);
        self.last_clash_rule = rule;
        self.last_reeval_rule = None;
        self.last_scores = acts.iter().cloned().zip(totals.iter().map(|v| v / self.samples.max(1) as f64)).collect();
        let bi = if self.bundle_p > 0.0 {
            // A-2: 束ねたゲームを解き、**平均戦略**の最大の手を出す（同点は最初）。
            let x = crate::bundle::solve_bundled(&bmats, &bws, crate::bundle::DEFAULT_ITERS);
            let mut bi = 0usize;
            for i in 1..x.len() {
                if x[i] > x[bi] {
                    bi = i;
                }
            }
            bi
        } else if self.nash_delta > 0.0 {
            Self::pick_index_safe(&totals, &alts, self.samples, self.nash_delta)
        } else {
            Self::pick_index(&totals, self.samples, self.tau, &mut self.rng)
        };
        if self.reeval_samples > 0 {
            let saved = self.reeval_begin();
            let one = [acts[bi].clone()];
            // 便 A: 取り直しは**根で選んだ規則と同じ規則**で 1 手を測る。
            // 1 手だけで規則を決め直すと `fresh` の意味（同じ物差しでの取り直し）が壊れる。
            let (t, _, rrule, _, _) = self.clash_totals(db, s, pi, &one, self.reeval_samples, goal, rule);
            self.last_reeval_rule = rrule;
            self.last_fresh = t[0] / self.reeval_samples as f64;
            self.reeval_end(saved);
        }
        acts[bi].clone()
    }

    /// A-9 の選び方: 均衡値が最大から δ 以内の手のうち、等重み相手での期待値が最大（同点は最初）。
    /// `nash_totals` / `alt_totals` は標本 n 本の**合計**なので、しきい値も n 倍する。
    fn pick_index_safe(nash_totals: &[f64], alt_totals: &[f64], n: usize, delta: f64) -> usize {
        let best = nash_totals.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let thr = best - delta * n.max(1) as f64 - 1e-12;
        let mut bi = 0usize;
        let mut bv = f64::NEG_INFINITY;
        for i in 0..nash_totals.len() {
            if nash_totals[i] >= thr && alt_totals[i] > bv {
                bv = alt_totals[i];
                bi = i;
            }
        }
        bi
    }

    /// 対抗の採点（`samples` 本の決定化で合計）。`reeval` はここを新しい決定化で呼び直す。
    /// 返すのは (均衡値の合計 or 従来の合計, A-9 の第 2 基準＝等重み相手での期待値の合計)。
    /// 第 2 基準は `nash_delta > 0` のときだけ埋まる。
    fn clash_totals(&mut self, db: &CardDb, s: &GameState, pi: u8, acts: &[Action], samples: usize,
                    goal: i64, force_rule: Option<bool>)
                    -> (Vec<f64>, Vec<f64>, Option<bool>, Vec<Vec<Vec<f64>>>, Vec<f64>) {
        let mut totals = vec![0.0f64; acts.len()];
        // A-2: 世界ごとの点数表とその重み（`bundle_p = 0` なら空のまま）
        let mut bundle_mats: Vec<Vec<Vec<f64>>> = Vec::new();
        let mut bundle_ws: Vec<f64> = Vec::new();
        let mut alts = vec![0.0f64; acts.len()];
        // 便 A（D-071）: 詰みの割合と、等重み相手での期待値の合計。
        let mut lethal = vec![0.0f64; acts.len()];
        let mut uni = vec![0.0f64; acts.len()];
        let (worlds, weights) = self.worlds(db, s, pi as usize, samples);  // 段 C-2
        for (t, &w) in worlds.iter().zip(weights.iter()) {
            let t = t.clone();
            let crn = self.save_crn();
            let opp_act = self.opp_act(db, &t, 1 - pi, true);
            if self.lethal_uniform > 0.0 {
                // 便 A: 行列を全部埋める。**列の順序・足す順序は A-9 の経路と同じ**
                // （Python の `greedy._clash` の写し。浮動小数の丸めまで揃える）。
                let mut cols = engine::legal_actions(db, &t, 1 - pi);
                if cols.is_empty() {
                    cols = vec![opp_act.clone()];
                }
                let k = cols.len();
                let mut m = vec![vec![0.0f64; k]; acts.len()];
                for (j, b) in cols.iter().enumerate() {
                    for (i, a) in acts.iter().enumerate() {
                        self.restore_crn(&crn);
                        m[i][j] = self.score_clash(db, &t, pi, a, b, goal);
                    }
                }
                let j0 = cols.iter().position(|b| b == &opp_act);
                if j0.is_none() {
                    // opp_act が列に無い（起きない想定の保険）。π₀ の列だけ別に採点する。
                    for (i, a) in acts.iter().enumerate() {
                        self.restore_crn(&crn);
                        totals[i] += w * self.score_clash(db, &t, pi, a, &opp_act, goal);
                    }
                }
                for i in 0..acts.len() {
                    lethal[i] += w * (0..k).filter(|&j| m[i][j] >= 1.0 - LETHAL_EPS).count() as f64
                        / k as f64;
                    uni[i] += w * (0..k).map(|j| m[i][j]).sum::<f64>() / k as f64;
                    if let Some(j) = j0 {
                        totals[i] += w * m[i][j];
                    }
                }
            } else if self.nash_delta > 0.0 {
                // A-9: 決定化ごとに 自分×相手 の行列を作り、相手の均衡戦略で期待値を取る。
                // 列の順序と足す順序は Python 版と同じ（浮動小数の丸めまで揃える）。
                let mut cols = engine::legal_actions(db, &t, 1 - pi);
                if cols.is_empty() {
                    cols = vec![opp_act.clone()];
                }
                let k = cols.len();
                let mut m = vec![vec![0.0f64; k]; acts.len()];
                for (j, b) in cols.iter().enumerate() {
                    for (i, a) in acts.iter().enumerate() {
                        self.restore_crn(&crn);
                        m[i][j] = self.score_clash(db, &t, pi, a, b, goal);
                    }
                }
                let pc = nash_col(&m, NASH_ITERS);
                for i in 0..acts.len() {
                    totals[i] += w * (0..k).map(|j| m[i][j] * pc[j]).sum::<f64>();
                    alts[i] += w * (0..k).map(|j| m[i][j]).sum::<f64>() / k as f64;
                }
            } else if self.bundle_p > 0.0 {
                // A-2: 束ねた対抗ゲーム（便 A 後半・D-082）。Python の写し。
                let base: Vec<f64>;
                if self.bundle_p >= 1.0 {
                    // 全列が同値になるので π₀ の列だけ採点する。**採点の呼び出しも
                    // 乱数の消費も既定の道と 1 回も違わない**（T-A2-2）。
                    let mut col = Vec::with_capacity(acts.len());
                    for a in acts.iter() {
                        self.restore_crn(&crn);
                        col.push(self.score_clash(db, &t, pi, a, &opp_act, goal));
                    }
                    bundle_mats.push(col.iter().map(|&c| vec![c]).collect());
                    base = col;
                } else {
                    let mut cols = engine::legal_actions(db, &t, 1 - pi);
                    if cols.is_empty() {
                        cols = vec![opp_act.clone()];
                    }
                    let k = cols.len();
                    let mut m = vec![vec![0.0f64; k]; acts.len()];
                    for (j, b) in cols.iter().enumerate() {
                        for (i, a) in acts.iter().enumerate() {
                            self.restore_crn(&crn);
                            m[i][j] = self.score_clash(db, &t, pi, a, b, goal);
                        }
                    }
                    let j0 = cols.iter().position(|b| b == &opp_act);
                    base = match j0 {
                        Some(j) => (0..acts.len()).map(|i| m[i][j]).collect(),
                        None => {
                            // π₀ の手が列に無い（起きない想定の保険）。別に採点する。
                            let mut v = Vec::with_capacity(acts.len());
                            for a in acts.iter() {
                                self.restore_crn(&crn);
                                v.push(self.score_clash(db, &t, pi, a, &opp_act, goal));
                            }
                            v
                        }
                    };
                    let q = self.bundle_p;
                    bundle_mats.push((0..acts.len())
                        .map(|i| (0..k).map(|j| q * base[i] + (1.0 - q) * m[i][j]).collect())
                        .collect());
                }
                bundle_ws.push(w);
                // `totals` の意味は従来のまま（π₀ に対する期待値）。混ぜた行列の
                // **π₀ の列は p に依らず m[i][j0] そのもの**なので、p=1 で自動的に一致する。
                for i in 0..acts.len() {
                    totals[i] += w * base[i];
                }
            } else if self.opp_mix <= 0.0 {
                // 従来の道（既定・挙動不変）
                for (i, a) in acts.iter().enumerate() {
                    self.restore_crn(&crn);
                    totals[i] += w * self.score_clash(db, &t, pi, a, &opp_act, goal);
                }
            } else {
                // A-8: 相手の合法手の表で期待値を取る（列の順序と足す順序は Python と同じ）
                for (b, wb) in self.opp_mix_dist(db, &t, 1 - pi, &opp_act) {
                    for (i, a) in acts.iter().enumerate() {
                        self.restore_crn(&crn);
                        totals[i] += w * wb * self.score_clash(db, &t, pi, a, &b, goal);
                    }
                }
            }
        }
        let mut rule: Option<bool> = None;
        if self.lethal_uniform > 0.0 {
            let n = samples.max(1) as f64;
            let use_uni = match force_rule {
                Some(f) => f,
                None => lethal.iter().map(|v| v / n).fold(f64::NEG_INFINITY, f64::max)
                    >= self.lethal_uniform,
            };
            rule = Some(use_uni);
            if use_uni {
                totals = uni;
            }
        }
        (totals, alts, rule, bundle_mats, bundle_ws)
    }

    /// 決定化 t の上で「自分が a・相手が b」を提出した結果を採点する。
    fn score_clash(&mut self, db: &CardDb, t: &GameState, pi: u8, a: &Action, b: &Action,
                   goal: i64) -> f64 {
        let u = engine::apply(db, t, &[(pi, a.clone()), (1 - pi, b.clone())]).expect("apply failed in clash");
        let u = self.settle(db, u, pi);
        if self.align_leaves {
            self.value_to_my_turn(db, u, pi, goal)
        } else {
            self.eval(db, &u, pi as usize)
        }
    }

    /// A-8: 相手の提出の分布（`(1−opp_mix)·最尤 ＋ opp_mix·合法手の等重み`・合計で正規化）。
    fn opp_mix_dist(&self, db: &CardDb, t: &GameState, q: u8, opp_act: &Action) -> Vec<(Action, f64)> {
        let opp_acts = engine::legal_actions(db, t, q);
        if opp_acts.len() <= 1 {
            let one = opp_acts.into_iter().next().unwrap_or_else(|| opp_act.clone());
            return vec![(one, 1.0)];
        }
        let k = opp_acts.iter().position(|b| b == opp_act);
        let m = self.opp_mix;
        let ws: Vec<f64> = (0..opp_acts.len())
            .map(|i| m / opp_acts.len() as f64 + if Some(i) == k { 1.0 - m } else { 0.0 })
            .collect();
        let tot: f64 = ws.iter().sum();
        opp_acts.into_iter().zip(ws).map(|(b, w)| (b, w / tot)).collect()
    }
}

/// A-9: regret matching の反復回数（Python の `greedy.NASH_ITERS` と同じ 400）。
pub const NASH_ITERS: usize = 400;

/// 便 A（D-071）: 詰みと見なす葉の値のしきい値（Python の `greedy.LETHAL_EPS` と同じ）。
pub const LETHAL_EPS: f64 = 1e-9;

/// 行列ゲームを regret matching で解き、**列側（相手）の平均戦略**を返す。
/// 行 = 自分（最大化）・列 = 相手（最小化）。乱数を一切引かない。
/// Python の `greedy.nash_col` の写しで、足す順序まで同じである。
pub fn nash_col(matrix: &[Vec<f64>], iters: usize) -> Vec<f64> {
    let m = matrix.len();
    let k = if m > 0 { matrix[0].len() } else { 0 };
    if m == 0 || k == 0 {
        return Vec::new();
    }
    if k == 1 {
        return vec![1.0];
    }
    let mut rr = vec![0.0f64; m];
    let mut rc = vec![0.0f64; k];
    let mut sc = vec![0.0f64; k];
    for _ in 0..iters {
        let pos: Vec<f64> = rr.iter().map(|x| if *x > 0.0 { *x } else { 0.0 }).collect();
        let tot: f64 = pos.iter().sum();
        let pr: Vec<f64> = if tot > 0.0 {
            pos.iter().map(|x| x / tot).collect()
        } else {
            vec![1.0 / m as f64; m]
        };
        let pos: Vec<f64> = rc.iter().map(|x| if *x > 0.0 { *x } else { 0.0 }).collect();
        let tot: f64 = pos.iter().sum();
        let pc: Vec<f64> = if tot > 0.0 {
            pos.iter().map(|x| x / tot).collect()
        } else {
            vec![1.0 / k as f64; k]
        };
        let u_r: Vec<f64> = (0..m).map(|i| (0..k).map(|j| matrix[i][j] * pc[j]).sum()).collect();
        let u_c: Vec<f64> = (0..k).map(|j| (0..m).map(|i| pr[i] * matrix[i][j]).sum()).collect();
        let v: f64 = (0..m).map(|i| pr[i] * u_r[i]).sum();
        for i in 0..m {
            rr[i] += u_r[i] - v;
        }
        for j in 0..k {
            rc[j] += v - u_c[j];
            sc[j] += pc[j];
        }
    }
    sc.iter().map(|x| x / iters as f64).collect()
}

/// softmax(values / tau) で 1 つ選ぶ。tau <= 0 なら最大（同点は最初）。
pub fn soft_pick(values: &[f64], tau: f64, rng: &mut PyRandom) -> usize {
    if values.len() <= 1 {
        return 0;
    }
    if tau <= 0.0 {
        return argmax_by(values, |v| *v);
    }
    let m = values.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let ws: Vec<f64> = values.iter().map(|v| ((v - m) / tau).exp()).collect();
    let tot: f64 = ws.iter().sum();
    let r = rng.random() * tot;
    let mut acc = 0.0;
    for (i, w) in ws.iter().enumerate() {
        acc += w;
        if r <= acc {
            return i;
        }
    }
    values.len() - 1
}

/// 探索なし・ネットの方策だけで打つ agent（DRL 段階 1 の「π 単体」）。
pub struct PolicyAgent {
    pub rng: PyRandom,
    pub net: Arc<Net>,
    pub tau: f64,
    pub last_scores: Vec<(Action, f64)>,
}

impl PolicyAgent {
    pub fn new(seed: i64, net: Arc<Net>, tau: f64) -> PolicyAgent {
        PolicyAgent { rng: PyRandom::from_int_seed(seed), net, tau, last_scores: Vec::new() }
    }
    pub fn act(&mut self, db: &CardDb, s: &GameState, pi: u8) -> Action {
        let acts = engine::legal_actions(db, s, pi);
        assert!(!acts.is_empty(), "no legal actions for P{pi} in {:?}", s.phase);
        if acts.len() == 1 {
            self.last_scores.clear();
            return acts[0].clone();
        }
        let x: Vec<f32> = encode::encode_state(db, s, pi).iter().map(|&v| v as f32).collect();
        let h = self.net.trunk(&x);
        let feats: Vec<Vec<f32>> = acts.iter().map(|a| encode::expand_action(db, &encode::action_code(db, s, pi, a))).collect();
        let scores: Vec<f64> = self.net.policy_scores(&h, &feats).iter().map(|&v| v as f64).collect();
        self.last_scores = acts.iter().cloned().zip(scores.iter().copied()).collect();
        let i = soft_pick(&scores, self.tau, &mut self.rng);
        acts[i].clone()
    }
}

// ---------------------------------------------------------------------------
// planner.py
// ---------------------------------------------------------------------------

type RngState = ([u32; 624], usize);

/// `PlannerAgent`
#[derive(Clone)]
pub struct Planner {
    pub g: Greedy,
    pub charge_candidates: usize,
    pub leaf_budget: i64,
    pub turn_rollout: usize,
    pub plan_samples: usize,
    pub race_after: usize,
    /// D-046 対策A: 地平を延ばす（0 = 通常）
    pub extra_turns: usize,
    budget: i64,
    crn: Option<(RngState, RngState)>,
}

/// `_akey(a)` の代わり。同じ行動なら同じ値。
fn akey(a: &Action) -> Action {
    a.clone()
}

impl Planner {
    pub fn new(seed: i64, w: Weights, params: Params, opp_decklist: Option<Vec<u16>>, samples: usize,
               rollout_depth: usize, charge_candidates: usize, leaf_budget: i64, turn_rollout: usize,
               plan_samples: usize, use_history: bool, prior_strength: f64, race_after: usize,
               extra_turns: usize) -> Planner {
        let g = Greedy::new(seed, w, opp_decklist, samples, rollout_depth,
                            vec![Phase::Action, Phase::ClashSubmit, Phase::Rush], params, use_history, prior_strength);
        Planner { g, charge_candidates, leaf_budget, turn_rollout, plan_samples, race_after, extra_turns, budget: 0, crn: None }
    }

    pub fn act(&mut self, db: &CardDb, s: &GameState, pi: u8) -> Action {
        // 段 C-2: 前の対抗の結果（公開情報）が出ていれば履歴に積む。つまみ 0 なら何もしない。
        // **`Greedy::act` に落ちる道でも二重には積まれない**（`pending_clash` を取り出すため）。
        self.g.note_history(s, pi as usize);
        self.g.last_scores.clear();
        self.g.last_fresh = f64::NAN;
        // 便 A: 対抗まで来なかった決定のあとに**前の対抗の規則が残らない**ようにする
        // （Python 側は `last_clash` を呼び出し側が消す約束だが、こちらは持ち主が消す）。
        self.g.last_clash_rule = None;
        self.g.last_reeval_rule = None;
        let acts = restricted_legal(db, s, pi, &self.g.restrict);
        assert!(!acts.is_empty(), "no legal actions for P{pi} in {:?}", s.phase);
        if acts.len() == 1 {
            return acts[0].clone();
        }
        if s.phase == Phase::Action && self.g.phases.contains(&Phase::Action) {
            return self.plan(db, s, pi, &acts);
        }
        self.g.act(db, s, pi)
    }

    fn plan(&mut self, db: &CardDb, s: &GameState, pi: u8, acts: &[Action]) -> Action {
        // total/count は挿入順を保つ（Python の dict と同じ同点処理のため）
        let mut keys: Vec<Action> = Vec::new();
        let mut total: Vec<f64> = Vec::new();
        let mut count: Vec<f64> = Vec::new();
        let mut alive: Option<Vec<Action>> = None;
        // 段 C-2（II-8・D-077）: 決定化をまたぐ平均を**加重平均**にする。
        // つまみ 0 なら重みはちょうど 1.0 なので、合計も件数も従来と同じ値になる。
        let (ts, ws) = self.g.worlds(db, s, pi as usize, self.plan_samples.max(1));
        // 段 C-3（II-9・D-077 追記 3）: 列挙した本を使ったときだけ、
        // **本ごとの最良の 1 手目**に重みを載せて投票する（下の安全弁で使う）。
        let enumerated = self.g.worlds_enumerated;
        let mut vote_keys: Vec<Action> = Vec::new();
        let mut vote_w: Vec<f64> = Vec::new();
        for (i, (t, &w)) in ts.iter().zip(ws.iter()).enumerate() {
            let t = t.clone();
            let mut leaves: Vec<(f64, Action)> = Vec::new();
            self.budget = self.leaf_budget;
            self.crn = Some((self.g.fallback.rng.getstate(), self.g.opp_model.rng.getstate()));
            let mut seen: Vec<Sig> = vec![sig(&t)];
            self.search(db, &t, pi, None, 3, &mut leaves, &mut seen, &alive);
            let mut best_here: Vec<(Action, f64)> = Vec::new();
            for (score, a) in &leaves {
                let k = akey(a);
                if let Some(e) = best_here.iter_mut().find(|(x, _)| *x == k) {
                    if *score > e.1 {
                        e.1 = *score;
                    }
                } else {
                    best_here.push((k, *score));
                }
            }
            // この本での最良の 1 手目（同点は先に出てきた方＝挿入順。Python の max と同じ）
            let mut bk: Option<(Action, f64)> = None;
            for (k, v) in &best_here {
                if bk.as_ref().map_or(true, |(_, bv)| *v > *bv) {
                    bk = Some((k.clone(), *v));
                }
            }
            for (k, v) in best_here {
                if let Some(idx) = keys.iter().position(|x| *x == k) {
                    total[idx] += w * v;
                    count[idx] += w;
                } else {
                    keys.push(k);
                    total.push(w * v);
                    count.push(w);
                }
            }
            if enumerated {
                if let Some((k, _)) = bk {
                    match vote_keys.iter().position(|x| *x == k) {
                        Some(ix) => vote_w[ix] += w,
                        None => { vote_keys.push(k); vote_w.push(w); }
                    }
                }
            }
            if i + 1 >= self.race_after {
                alive = Some(self.survivors(&keys, &total, &count, &alive));
            }
        }
        if keys.is_empty() {
            return self.g.solo(db, s, pi, acts);
        }
        let avg: Vec<f64> = (0..keys.len()).map(|i| total[i] / count[i]).collect();
        self.g.last_scores = keys.iter().cloned().zip(avg.iter().copied()).collect();
        // 段 C-3 の投票と安全弁（列挙した本を使ったときだけ通る）。
        // C = 勝った手の重みの割合。C ≥ `endgame_conf` ならその手、そうでなければ加重平均の手。
        let mut vote_pick: Option<Action> = None;
        if enumerated && !vote_keys.is_empty() && self.g.tau <= 0.0 {
            let tw: f64 = vote_w.iter().sum();
            if tw > 0.0 {
                let vi = argmax_by(&vote_w, |v| *v);
                if vote_w[vi] / tw >= self.g.endgame_conf {
                    vote_pick = Some(vote_keys[vi].clone());
                }
            }
        }
        let bi = if self.g.tau > 0.0 { soft_pick(&avg, self.g.tau, &mut self.g.rng) } else { argmax_by(&avg, |v| *v) };
        // 投票が勝ったらそちらを指す（取り直しも**実際に指す手**に対して行う）。
        let chosen: Action = vote_pick.unwrap_or_else(|| keys[bi].clone());
        // D-065 A-3 (i): 選んだ 1 手目だけを**別の決定化**で探索し直して平均する（記録の `fresh`）。
        // 根の探索値は max-then-mean のぶん楽観する（勝者の呪い・レビュー §2.3 で +0.17）。
        // 取り直した値はその偏りを持たないので、学習側（便 3 の `--vtarget fresh`）の教師になる。
        if self.g.reeval_samples > 0 {
            // 乱数のほかに、探索の残り予算と共通乱数の控えも取り直しで書き換わる。
            // どちらも次の決定の頭で入れ直されるが、**戻しておかないと「汚していない」と言えない**。
            let saved = self.g.reeval_begin();
            let (budget0, crn0) = (self.budget, self.crn);
            self.g.last_fresh = self.reeval_plan(db, s, pi, &chosen);
            self.budget = budget0;
            self.crn = crn0;
            self.g.reeval_end(saved);
        }
        chosen
    }

    /// 選んだ 1 手目だけに根を絞って `reeval_samples` 本の新しい決定化で探索し、平均を返す。
    /// 1 本も葉が採れなければ NaN（記録側は「取り直せなかった」として NaN のまま扱う）。
    fn reeval_plan(&mut self, db: &CardDb, s: &GameState, pi: u8, chosen: &Action) -> f64 {
        let alive = Some(vec![chosen.clone()]);
        let mut tot = 0.0;
        let mut got = 0usize;
        for j in 0..self.g.reeval_samples {
            let t = self.g.determinize(db, s, pi as usize, j);
            let mut leaves: Vec<(f64, Action)> = Vec::new();
            self.budget = self.leaf_budget;
            self.crn = Some((self.g.fallback.rng.getstate(), self.g.opp_model.rng.getstate()));
            let mut seen: Vec<Sig> = vec![sig(&t)];
            self.search(db, &t, pi, None, 3, &mut leaves, &mut seen, &alive);
            let mut best: Option<f64> = None;
            for (score, a) in &leaves {
                if a == chosen && best.map_or(true, |b| *score > b) {
                    best = Some(*score);
                }
            }
            if let Some(v) = best {
                tot += v;
                got += 1;
            }
        }
        if got == 0 { f64::NAN } else { tot / got as f64 }
    }

    fn survivors(&self, keys: &[Action], total: &[f64], count: &[f64], alive: &Option<Vec<Action>>) -> Vec<Action> {
        let mut idx: Vec<usize> = (0..keys.len())
            .filter(|&i| alive.as_ref().map_or(true, |al| al.contains(&keys[i])))
            .collect();
        if idx.len() <= 2 {
            return idx.iter().map(|&i| keys[i].clone()).collect();
        }
        // 安定な降順ソート（Python の sort(reverse=True) と同じ同点処理）
        idx.sort_by(|&a, &b| {
            let va = total[a] / count[a];
            let vb = total[b] / count[b];
            vb.partial_cmp(&va).unwrap()
        });
        let keep = 2usize.max((idx.len() + 1) / 2);
        idx[..keep].iter().map(|&i| keys[i].clone()).collect()
    }

    fn search(&mut self, db: &CardDb, t: &GameState, pi: u8, first: Option<&Action>, depth: i32,
              leaves: &mut Vec<(f64, Action)>, seen: &mut Vec<Sig>, alive: &Option<Vec<Action>>) {
        let acts = restricted_legal(db, t, pi, &self.g.restrict);
        let has_to_clash = acts.iter().any(|a| matches!(a, Action::ToClash));
        let has_end_turn = acts.iter().any(|a| matches!(a, Action::EndTurn));
        let top = first.is_none();
        let allowed = |a: &Action| -> bool {
            !(top && alive.as_ref().map_or(false, |al| !al.contains(a)))
        };

        if has_to_clash && self.budget > 0 && allowed(&Action::ToClash) {
            self.budget -= 1;
            let u = engine::apply(db, t, &[(pi, Action::ToClash)]).expect("apply to_clash");
            let v = self.value_after_turn(db, u, pi);
            leaves.push((v, first.cloned().unwrap_or(Action::ToClash)));
        }

        let p = &t.players[pi as usize];
        if has_end_turn && self.budget > 0 && allowed(&Action::EndTurn)
            && !p.hand.iter().any(|&cid| engine::usable_in_clash(db, t, pi as usize, &db.action[cid as usize]))
        {
            self.budget -= 1;
            let u = engine::apply(db, t, &[(pi, Action::EndTurn)]).expect("apply end_turn");
            let v = self.value_after_turn(db, u, pi);
            leaves.push((v, first.cloned().unwrap_or(Action::EndTurn)));
        }

        if depth <= 0 || self.budget <= 0 {
            return;
        }

        for a in self.branches(db, t, pi, &acts) {
            if top && alive.as_ref().map_or(false, |al| !al.contains(&a)) {
                continue;
            }
            let u = engine::apply(db, t, &[(pi, a.clone())]).expect("apply branch");
            let u = self.g.settle(db, u, pi);
            let nxt: Action = first.cloned().unwrap_or_else(|| a.clone());
            if u.outcome.is_some() || u.phase != Phase::Action {
                if self.budget > 0 {
                    self.budget -= 1;
                    leaves.push((self.g.eval(db, &u, pi as usize), nxt));
                }
                continue;
            }
            let key = sig(&u);
            if seen.contains(&key) {
                continue;
            }
            seen.push(key);
            self.search(db, &u, pi, Some(&nxt), depth - 1, leaves, seen, alive);
        }
    }

    fn branches(&self, db: &CardDb, t: &GameState, pi: u8, acts: &[Action]) -> Vec<Action> {
        let p = &t.players[pi as usize];
        let mut out: Vec<Action> = Vec::new();
        // チャージ: 同じカードIDへの重複を潰し（最初の行動を残す）、card_utility の低い順に上位数枚
        let mut ch: Vec<(u16, Action)> = Vec::new();
        for a in acts {
            if let Action::Charge { hand } = a {
                let cid = p.hand[*hand];
                if !ch.iter().any(|(c, _)| *c == cid) {
                    ch.push((cid, a.clone()));
                }
            }
        }
        if !ch.is_empty() {
            let mut ranked: Vec<(f64, &Action)> = ch.iter().map(|(cid, a)| (card_utility(db, t, pi as usize, *cid), a)).collect();
            ranked.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap()); // 安定
            out.extend(ranked.iter().take(self.charge_candidates).map(|(_, a)| (*a).clone()));
        }
        out.extend(acts.iter().filter(|a| matches!(a, Action::Switch { .. })).cloned());
        let mut lv: Vec<Action> = Vec::new();
        for a in acts {
            if let Action::Levelup { slot, card } = a {
                if !lv.iter().any(|x| matches!(x, Action::Levelup { slot: s2, card: c2 } if s2 == slot && c2 == card)) {
                    lv.push(a.clone());
                }
            }
        }
        out.extend(lv);
        out
    }

    /// `_value_after_turn`（extra_turns=0）／`LongHorizonPlanner._value_after_turn`（extra_turns≥1）
    fn value_after_turn(&mut self, db: &CardDb, mut u: GameState, pi: u8) -> f64 {
        let (fs, os) = self.crn.as_ref().expect("crn not set");
        self.g.fallback.rng.setstate(fs);
        self.g.opp_model.rng.setstate(os);
        if self.extra_turns == 0 {
            let turn0 = u.turn_no;
            for _ in 0..self.turn_rollout {
                if u.outcome.is_some() || u.phase == Phase::GameOver {
                    break;
                }
                if u.turn_no != turn0 && u.phase != Phase::Choice {
                    break;
                }
                let need = engine::decision_players(&u);
                if need.is_empty() {
                    break;
                }
                self.g.step_proxy(db, &mut u, &need, pi);
            }
        } else {
            let goal = u.turn_no + self.extra_turns as i64 + 1;
            for _ in 0..(self.turn_rollout * (1 + self.extra_turns)) {
                if u.outcome.is_some() || u.phase == Phase::GameOver {
                    break;
                }
                if u.turn_no >= goal && u.phase != Phase::Choice {
                    break;
                }
                let need = engine::decision_players(&u);
                if need.is_empty() {
                    break;
                }
                self.g.step_proxy(db, &mut u, &need, pi);
            }
        }
        self.g.eval(db, &u, pi as usize)
    }
}

/// `_sig`: 重複除去用の局面署名。
#[derive(Clone, PartialEq, Eq, Debug)]
pub struct Sig {
    phase: Phase,
    turn_no: i64,
    used: (bool, bool, bool),
    life: (i64, i64),
    decks: (usize, usize),
    hand0: Vec<u16>,
    conc0: Vec<u16>,
    slots0: [Vec<u16>; 3],
    hand1: Vec<u16>,
    conc1: Vec<u16>,
    slots1: [Vec<u16>; 3],
}

fn sig(u: &GameState) -> Sig {
    let sorted = |v: &Vec<u16>| {
        let mut x = v.clone();
        x.sort_unstable();
        x
    };
    let p0 = &u.players[0];
    let p1 = &u.players[1];
    Sig {
        phase: u.phase,
        turn_no: u.turn_no,
        used: (u.used_charge, u.used_switch, u.used_levelup),
        life: (p0.life, p1.life),
        decks: (p0.action_deck.len(), p1.action_deck.len()),
        hand0: sorted(&p0.hand),
        conc0: sorted(&p0.concerto),
        slots0: p0.slots.clone(),
        hand1: sorted(&p1.hand),
        conc1: sorted(&p1.concerto),
        slots1: p1.slots.clone(),
    }
}
