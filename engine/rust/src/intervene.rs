//! 発見ループの `Intervention`（`DISCOVERY_LOOP_DESIGN.md` §2.5・D-050）。
//!
//! champion（計画探索）の方策を**機械的に少しだけ変える** δ。2 つの型がある。
//! - 「禁じる」型: 合法手を絞る（`agents::Restrict`）。絞りは計画探索の木の中まで効く
//!   （禁じた手を計画にも使わない）。
//! - 「急ぐ／優先／必ず」型: 条件が立ったとき champion の代わりに手を返す。
//! カード名・キャラ名は**データとして**受け取る（コードには書かない）。
//!
//! `fired` は「δ が実際に手に関与した回数」。禁じる型は「絞りで合法手が減った決定」、
//! 上書き型は「δ が手を返した決定」を数える。発火確認（対 H・40 局）で 0 のものは測らない。

use crate::agents::{card_utility, Planner, Restrict};
use crate::cards::CardDb;
use crate::engine::{self, Action};
use crate::state::{GameState, Phase};

#[derive(Clone, Debug)]
pub enum Intervention {
    /// A: そのキャラのレベルアップが合法なら到達できる最高レベルを選ぶ（from_turn 以降、goal に着くまで）
    RushChara { name: String, goal: i64, from_turn: i64 },
    /// A: そのキャラをレベル `level` に上げる行動を禁じる
    ForbidLevelup { name: String, level: i64 },
    /// A: 準備段階でそのキャラをリーダーにする
    FixLeader { name: String },
    /// B: そのカードが手札にあり対抗で使えるなら、必ず出す（複数あれば手札の左から）
    PreferInClash { card: String },
    /// B: そのカードを対抗で出さない
    ForbidInClash { card: String },
    /// B: そのカードを連撃で使わない
    ForbidInRush { card: String },
    /// B: 温存。対抗では出さず（禁じる型）、**かつ連撃で使えるなら必ず使う**（強いる型）。
    /// D-053 で後半を実装した。それ以前は `ForbidInClash` と同一の規則だった（D-052 裁定 2）。
    Reserve { card: String },
    /// C: コスト0・ダメージ>0 の連撃が選べるなら必ずする（最大ダメージ）
    AlwaysFreeRush,
    /// C: コスト0・ダメージ>0 の連撃が選べても必ずやめる
    NeverFreeRush,
    /// C: 協奏エリアが空でチャージが選べるなら必ずチャージ（card_utility 最小の札）
    ChargeIfConcertoEmpty,
    /// C: 手札が min_hand 枚以上ならレベルアップを必ずする（リーダー優先・高レベル優先）
    LevelupIfHand { min_hand: i64 },
    /// C: 自分のライフ ≤ 相手のライフ − margin のとき対抗でパスを禁じる
    NoPassIfBehind { margin: i64 },
    /// C: until_turn 以下のターンでは切り替えを禁じる
    NoSwitchUntil { until_turn: i64 },
}

impl Intervention {
    /// 「禁じる」型なら対応する `Restrict`。
    pub fn restrict(&self) -> Option<Restrict> {
        match self {
            Intervention::ForbidLevelup { name, level } => Some(Restrict::ForbidLevelup { name: name.clone(), level: *level }),
            Intervention::ForbidInClash { card } => Some(Restrict::ForbidInClash { card: card.clone() }),
            Intervention::ForbidInRush { card } => Some(Restrict::ForbidInRush { card: card.clone() }),
            Intervention::Reserve { card } => Some(Restrict::Reserve { card: card.clone() }),
            Intervention::NeverFreeRush => Some(Restrict::NeverFreeRush),
            Intervention::NoPassIfBehind { margin } => Some(Restrict::NoPassIfBehind { margin: *margin }),
            Intervention::NoSwitchUntil { until_turn } => Some(Restrict::NoSwitchUntil { until_turn: *until_turn }),
            _ => None,
        }
    }
}

fn chara_name<'a>(db: &'a CardDb, cid: u16) -> &'a str {
    &db.chara[cid as usize].name
}

fn top_level(db: &CardDb, s: &GameState, pi: usize, name: &str) -> Option<i64> {
    s.players[pi]
        .slots
        .iter()
        .filter_map(|sl| sl.last())
        .find(|&&c| chara_name(db, c) == name)
        .map(|&c| db.chara[c as usize].level)
}

/// 挑戦者 = champion ＋ δ（複数可。上書き型は並び順に最初に条件が立ったものが手を決める）。
pub struct Challenger {
    pub planner: Planner,
    pub deltas: Vec<Intervention>,
    pub fired: u64,
}

impl Challenger {
    pub fn new(mut planner: Planner, deltas: Vec<Intervention>) -> Challenger {
        planner.g.restrict = deltas.iter().filter_map(|d| d.restrict()).collect();
        Challenger { planner, deltas, fired: 0 }
    }

    /// 条件が立ったときに返す手（「急ぐ／優先／必ず」型）。並び順に最初のもの。
    fn override_action(&self, db: &CardDb, s: &GameState, pi: u8, acts: &[Action]) -> Option<Action> {
        for d in &self.deltas {
            if let Some(a) = Self::override_one(d, db, s, pi, acts) {
                return Some(a);
            }
        }
        None
    }

    fn override_one(delta: &Intervention, db: &CardDb, s: &GameState, pi: u8, acts: &[Action]) -> Option<Action> {
        let pu = pi as usize;
        let p = &s.players[pu];
        match delta {
            Intervention::RushChara { name, goal, from_turn } => {
                if s.phase != Phase::Action || s.turn_player != pi || s.turn_no < *from_turn {
                    return None;
                }
                let lv = top_level(db, s, pu, name)?;
                if lv >= *goal {
                    return None;
                }
                let ups: Vec<&Action> = acts
                    .iter()
                    .filter(|a| matches!(a, Action::Levelup { card, .. } if chara_name(db, *card) == name))
                    .collect();
                if ups.is_empty() {
                    return None;
                }
                let mut best = ups[0];
                for a in &ups[1..] {
                    let (Action::Levelup { card: c1, .. }, Action::Levelup { card: c0, .. }) = (a, best) else { unreachable!() };
                    if db.chara[*c1 as usize].level > db.chara[*c0 as usize].level {
                        best = a;
                    }
                }
                Some(best.clone())
            }
            Intervention::FixLeader { name } => {
                if s.phase != Phase::SetupChara {
                    return None;
                }
                acts.iter().find(|a| matches!(a, Action::Setup { leader, backs } if leader == name && {
                    let mut b=backs.clone(); b.sort(); *backs==b })).cloned()
            }
            Intervention::PreferInClash { card } => {
                if s.phase != Phase::ClashSubmit {
                    return None;
                }
                acts.iter()
                    .find(|a| matches!(a, Action::Submit { hand: h } if db.action[p.hand[*h] as usize].name == *card))
                    .cloned()
            }
            Intervention::Reserve { card } => {
                // 温存の後半（強いる側・D-053）: 連撃でそのカードが使えるなら必ず使う。
                // 前半（対抗で出さない）は `restrict()` の `Restrict::Reserve` が担う。
                if s.phase != Phase::Rush {
                    return None;
                }
                acts.iter()
                    .find(|a| matches!(a, Action::Rush { hand: h } if db.action[p.hand[*h] as usize].name == *card))
                    .cloned()
            }
            Intervention::AlwaysFreeRush => {
                if s.phase != Phase::Rush {
                    return None;
                }
                let mut best: Option<(&Action, i64)> = None;
                for a in acts {
                    if let Action::Rush { hand: h } = a {
                        let c = &db.action[p.hand[*h] as usize];
                        if c.cost == 0 && c.damage > 0 && best.map_or(true, |(_, d)| c.damage > d) {
                            best = Some((a, c.damage));
                        }
                    }
                }
                best.map(|(a, _)| a.clone())
            }
            Intervention::ChargeIfConcertoEmpty => {
                if s.phase != Phase::Action || s.turn_player != pi || !p.concerto.is_empty() || s.used_charge {
                    return None;
                }
                let mut best: Option<(&Action, f64)> = None;
                for a in acts {
                    if let Action::Charge { hand: h } = a {
                        let u = card_utility(db, s, pu, p.hand[*h]);
                        if best.map_or(true, |(_, v)| u < v) {
                            best = Some((a, u));
                        }
                    }
                }
                best.map(|(a, _)| a.clone())
            }
            Intervention::LevelupIfHand { min_hand } => {
                if s.phase != Phase::Action || s.turn_player != pi || (p.hand.len() as i64) < *min_hand {
                    return None;
                }
                let mut best: Option<(&Action, (bool, i64))> = None;
                for a in acts {
                    if let Action::Levelup { slot, card } = a {
                        let k = (*slot == 0, db.chara[*card as usize].level);
                        if best.map_or(true, |(_, bk)| k > bk) {
                            best = Some((a, k));
                        }
                    }
                }
                best.map(|(a, _)| a.clone())
            }
            _ => None,
        }
    }

    pub fn act(&mut self, db: &CardDb, s: &GameState, pi: u8) -> Action {
        let full = engine::legal_actions(db, s, pi);
        assert!(!full.is_empty(), "no legal actions");
        if full.len() == 1 {
            return full[0].clone();
        }
        if let Some(a) = self.override_action(db, s, pi, &full) {
            self.fired += 1;
            return a;
        }
        if !self.planner.g.restrict.is_empty() {
            let kept = crate::agents::restricted_legal(db, s, pi, &self.planner.g.restrict);
            if kept.len() != full.len() {
                self.fired += 1;
            }
        }
        self.planner.act(db, s, pi)
    }
}
