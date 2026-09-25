//! カードデータ（`meicho/cards.py` の写し。真実源は Python 側・D-049）。
//!
//! Python の `cards_export.cards_json()` が出す JSON を `CardDb::from_json` で読む。
//! カードは配列の添字（u16）で参照し、JSON へ戻すときだけ card_id 文字列に変換する。

use serde::Deserialize;
use std::collections::HashMap;

#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum Color {
    Red,
    Green,
    Blue,
}

impl Color {
    pub fn from_str(s: &str) -> Color {
        match s {
            "red" => Color::Red,
            "green" => Color::Green,
            "blue" => Color::Blue,
            _ => panic!("unknown color {s}"),
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Color::Red => "red",
            Color::Green => "green",
            Color::Blue => "blue",
        }
    }
    /// 3すくみ (rules §2.2): 赤>緑, 緑>青, 青>赤
    pub fn beats(self, other: Color) -> bool {
        matches!(
            (self, other),
            (Color::Red, Color::Green) | (Color::Green, Color::Blue) | (Color::Blue, Color::Red)
        )
    }
    /// `state.CLASH_COLOR_INDEX`
    pub fn clash_index(self) -> usize {
        match self {
            Color::Red => 0,
            Color::Green => 1,
            Color::Blue => 2,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum Timing {
    Clash,
    Judge,
    Rush,
    TurnEnd,
    TurnStart,
    Static,
    // --- v0.12 / BP01（D-079 追記 3）。`meicho/cards.py` の Timing と 1 対 1。---
    Enter,
    Levelup,
    Switched,
    ClashPhaseStart,
    ClashPhaseEnd,
    OnHeal,
    OnDamageDealt,
}

/// タイミングの総数。`CardDb` の索引配列の幅であり、`timing_slot` の値域でもある。
pub const N_TIMINGS: usize = 13;

/// ＜音骸＞のタグ（rules_draft v0.12 §7・u5）。`meicho/cards.py::ONKAI_TAG` と同じ文字列。
pub const ONKAI_TAG: &str = "音骸";

impl Timing {
    pub fn from_str(s: &str) -> Timing {
        match s {
            "clash" => Timing::Clash,
            "judge" => Timing::Judge,
            "rush" => Timing::Rush,
            "turn_end" => Timing::TurnEnd,
            "turn_start" => Timing::TurnStart,
            "static" => Timing::Static,
            "enter" => Timing::Enter,
            "levelup" => Timing::Levelup,
            "switched" => Timing::Switched,
            "clash_phase_start" => Timing::ClashPhaseStart,
            "clash_phase_end" => Timing::ClashPhaseEnd,
            "on_heal" => Timing::OnHeal,
            "on_damage_dealt" => Timing::OnDamageDealt,
            // **知らないタイミングは落とす**（黙って無視すると Python と手が割れる）。
            _ => panic!("unknown timing {s}"),
        }
    }

    /// 盤面の「場面」として発火し、アクションエリアのカードも拾うタイミング
    /// （`meicho/cards.py` の `AREA_TIMINGS`）。
    ///
    /// **`OnDamageDealt` は入らない**（u18・マスター裁定 2026-09-10）。
    /// 「相手にダメージを与えた時」はそのカード自身が与えたときだけ誘発するので、
    /// 盤面を走査せず `queue_fire_on_card` でそのカードの索引を直に引く。
    pub fn is_area(self) -> bool {
        matches!(self, Timing::ClashPhaseStart | Timing::ClashPhaseEnd)
    }
}

/// オペコード。`engine._apply_op` の分岐と 1 対 1。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Op {
    Draw,
    RevealTopToHand,
    TopToConcerto,
    DamageOpponent,
    Pursuit,
    ForbidLeaderSwitchThisTurn,
    SwitchLeader,
    SelfDamageBuffIfSwitched,
    TopToConcertoIfSwitched,
    RushDamageBuff,
    DedicatedLeaderCardDamageBuff,
    HealSelf,
    RaiseOpponentRedCostNextTurn,
    ReturnClashCardToHand,
    OpponentPayOrDamage,
    DiscardSelf,
    DrawIfSwitched,
    SelfDamageBuff,
    ForbidRushNextTurn,
    PeekOpponentHand,
    // --- v0.12 / BP01（D-079 追記 3）---
    DrawTo,
    HealIfSwitched,
    SelfDamageBuffIfDiscarded,
    SelfDamageBuffPerActionArea,
    FirstUseDamageBuff,
    FirstDamageTakenMod,
    NameColorDamageBuff,
    OwnCardDamageBuff,
    ForbidRushSelfNow,
    ForbidRushOpponentNow,
    PayCostReturnSelfToHand,
    SpeedOverride,
    // --- v0.12 / BP01 K-3（D-079 追記 5）---
    OppDiscardRandom,
    OppConcertoToTrash,
    OppHandRandomToDeckBottom,
    MillOpponentDeckTop,
    OppTrashToDeckBottom,
    ConcertoSetFirstUseBuff,
    // --- v0.12 / BP01 K-4（D-079 追記 6）---
    TrashToHand,
    TrashToConcerto,
    ReturnToCharaDeck,
    LevelupByEffect,
    LevelupByEffectIfSwitched,
    TrashToHandIfSwitched,
    LevelupByEffectOnly,
    DamageTakenMod,
    GrantDeferredDamageOnLoss,
    SwitchLeaderTo,
    SearchDeck,
    RevealNTakeMatching,
    // --- v0.12 / BP01 K-5（掲載が遅れた 2 枚・u19〜u21）---
    CostMod,
    GrantRushDrawToVariationSkills,
}

impl Op {
    pub fn from_str(s: &str) -> Op {
        match s {
            "draw" => Op::Draw,
            "reveal_top_to_hand" => Op::RevealTopToHand,
            "top_to_concerto" => Op::TopToConcerto,
            "damage_opponent" => Op::DamageOpponent,
            "pursuit" => Op::Pursuit,
            "forbid_leader_switch_this_turn" => Op::ForbidLeaderSwitchThisTurn,
            "switch_leader" => Op::SwitchLeader,
            "self_damage_buff_if_switched" => Op::SelfDamageBuffIfSwitched,
            "top_to_concerto_if_switched" => Op::TopToConcertoIfSwitched,
            "rush_damage_buff" => Op::RushDamageBuff,
            "dedicated_leader_card_damage_buff" => Op::DedicatedLeaderCardDamageBuff,
            "heal_self" => Op::HealSelf,
            "raise_opponent_red_cost_next_turn" => Op::RaiseOpponentRedCostNextTurn,
            "return_clash_card_to_hand" => Op::ReturnClashCardToHand,
            "opponent_pay_or_damage" => Op::OpponentPayOrDamage,
            "discard_self" => Op::DiscardSelf,
            "draw_if_switched" => Op::DrawIfSwitched,
            "self_damage_buff" => Op::SelfDamageBuff,
            "forbid_rush_next_turn" => Op::ForbidRushNextTurn,
            "peek_opponent_hand" => Op::PeekOpponentHand,
            "draw_to" => Op::DrawTo,
            "heal_if_switched" => Op::HealIfSwitched,
            "self_damage_buff_if_discarded" => Op::SelfDamageBuffIfDiscarded,
            "self_damage_buff_per_action_area" => Op::SelfDamageBuffPerActionArea,
            "first_use_damage_buff" => Op::FirstUseDamageBuff,
            "first_damage_taken_mod" => Op::FirstDamageTakenMod,
            "name_color_damage_buff" => Op::NameColorDamageBuff,
            "own_card_damage_buff" => Op::OwnCardDamageBuff,
            "forbid_rush_self_now" => Op::ForbidRushSelfNow,
            "forbid_rush_opponent_now" => Op::ForbidRushOpponentNow,
            "pay_cost_return_self_to_hand" => Op::PayCostReturnSelfToHand,
            "speed_override" => Op::SpeedOverride,
            "opp_discard_random" => Op::OppDiscardRandom,
            "opp_concerto_to_trash" => Op::OppConcertoToTrash,
            "opp_hand_random_to_deck_bottom" => Op::OppHandRandomToDeckBottom,
            "mill_opponent_deck_top" => Op::MillOpponentDeckTop,
            "opp_trash_to_deck_bottom" => Op::OppTrashToDeckBottom,
            "concerto_set_first_use_buff" => Op::ConcertoSetFirstUseBuff,
            "trash_to_hand" => Op::TrashToHand,
            "trash_to_concerto" => Op::TrashToConcerto,
            "return_to_chara_deck" => Op::ReturnToCharaDeck,
            "levelup_by_effect" => Op::LevelupByEffect,
            "levelup_by_effect_if_switched" => Op::LevelupByEffectIfSwitched,
            "trash_to_hand_if_switched" => Op::TrashToHandIfSwitched,
            "levelup_by_effect_only" => Op::LevelupByEffectOnly,
            "damage_taken_mod" => Op::DamageTakenMod,
            "grant_deferred_damage_on_loss" => Op::GrantDeferredDamageOnLoss,
            "switch_leader_to" => Op::SwitchLeaderTo,
            "search_deck" => Op::SearchDeck,
            "reveal_n_take_matching" => Op::RevealNTakeMatching,
            "cost_mod" => Op::CostMod,
            "grant_rush_draw_to_variation_skills" => Op::GrantRushDrawToVariationSkills,
            _ => panic!("unknown effect op: {s}"),
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Op::Draw => "draw",
            Op::RevealTopToHand => "reveal_top_to_hand",
            Op::TopToConcerto => "top_to_concerto",
            Op::DamageOpponent => "damage_opponent",
            Op::Pursuit => "pursuit",
            Op::ForbidLeaderSwitchThisTurn => "forbid_leader_switch_this_turn",
            Op::SwitchLeader => "switch_leader",
            Op::SelfDamageBuffIfSwitched => "self_damage_buff_if_switched",
            Op::TopToConcertoIfSwitched => "top_to_concerto_if_switched",
            Op::RushDamageBuff => "rush_damage_buff",
            Op::DedicatedLeaderCardDamageBuff => "dedicated_leader_card_damage_buff",
            Op::HealSelf => "heal_self",
            Op::RaiseOpponentRedCostNextTurn => "raise_opponent_red_cost_next_turn",
            Op::ReturnClashCardToHand => "return_clash_card_to_hand",
            Op::OpponentPayOrDamage => "opponent_pay_or_damage",
            Op::DiscardSelf => "discard_self",
            Op::DrawIfSwitched => "draw_if_switched",
            Op::SelfDamageBuff => "self_damage_buff",
            Op::ForbidRushNextTurn => "forbid_rush_next_turn",
            Op::PeekOpponentHand => "peek_opponent_hand",
            Op::DrawTo => "draw_to",
            Op::HealIfSwitched => "heal_if_switched",
            Op::SelfDamageBuffIfDiscarded => "self_damage_buff_if_discarded",
            Op::SelfDamageBuffPerActionArea => "self_damage_buff_per_action_area",
            Op::FirstUseDamageBuff => "first_use_damage_buff",
            Op::FirstDamageTakenMod => "first_damage_taken_mod",
            Op::NameColorDamageBuff => "name_color_damage_buff",
            Op::OwnCardDamageBuff => "own_card_damage_buff",
            Op::ForbidRushSelfNow => "forbid_rush_self_now",
            Op::ForbidRushOpponentNow => "forbid_rush_opponent_now",
            Op::PayCostReturnSelfToHand => "pay_cost_return_self_to_hand",
            Op::SpeedOverride => "speed_override",
            Op::OppDiscardRandom => "opp_discard_random",
            Op::OppConcertoToTrash => "opp_concerto_to_trash",
            Op::OppHandRandomToDeckBottom => "opp_hand_random_to_deck_bottom",
            Op::MillOpponentDeckTop => "mill_opponent_deck_top",
            Op::OppTrashToDeckBottom => "opp_trash_to_deck_bottom",
            Op::ConcertoSetFirstUseBuff => "concerto_set_first_use_buff",
            Op::TrashToHand => "trash_to_hand",
            Op::TrashToConcerto => "trash_to_concerto",
            Op::ReturnToCharaDeck => "return_to_chara_deck",
            Op::LevelupByEffect => "levelup_by_effect",
            Op::LevelupByEffectIfSwitched => "levelup_by_effect_if_switched",
            Op::TrashToHandIfSwitched => "trash_to_hand_if_switched",
            Op::LevelupByEffectOnly => "levelup_by_effect_only",
            Op::DamageTakenMod => "damage_taken_mod",
            Op::GrantDeferredDamageOnLoss => "grant_deferred_damage_on_loss",
            Op::SwitchLeaderTo => "switch_leader_to",
            Op::SearchDeck => "search_deck",
            Op::RevealNTakeMatching => "reveal_n_take_matching",
            Op::CostMod => "cost_mod",
            Op::GrantRushDrawToVariationSkills => "grant_rush_draw_to_variation_skills",
        }
    }
}

/// オペコードのパラメータ。Python 側の `dict(prm)` と同じ内容を持ち、
/// 効果解決の途中で足されるキー（back / chosen / hand_idx）も同じ名前で持つ。
/// JSON に戻すときは Some のキーだけを書く（Python の dict と一致させるため）。
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Params {
    pub count: Option<i64>,
    pub amount: Option<i64>,
    pub cost: Option<i64>,
    pub name: Option<String>,
    pub up_to: Option<bool>,
    pub back: Option<i64>,
    pub chosen: Option<i64>,
    pub hand_idx: Option<i64>,
    // --- v0.12 / BP01（D-079 追記 3）---
    pub tag: Option<String>,
    pub color: Option<String>,
    pub speed: Option<i64>,
    pub card: Option<String>,
    // --- v0.12 / BP01 K-3 ---
    pub set_tag: Option<String>,
    pub per: Option<i64>,
    // --- v0.12 / BP01 K-4 ---
    pub chara: Option<String>,
    pub exclude_tag: Option<String>,
    pub card_name: Option<String>,
    // --- v0.12 / BP01 K-5 ---
    /// `levelup_by_effect` で「そのレベルのカードを探す」(u21)。省略時は次のレベル。
    pub level: Option<i64>,
    /// `cost_mod` のコスト修正値 (u20)。下限 0 は `effective_cost` が掛ける。
    pub delta: Option<i64>,
    // --- B-8 の直し（D-093 追記 1）---
    /// `pay_cost_return_self_to_hand` の「支払いはもう済んだ」印。**Python の `prm["paid"]` の写し**。
    /// 以前は `chosen` を流用していたが、`chosen` はドロー枚数などにも使うため名前が食い違い、
    /// 状態の JSON が Python と一致しなかった（`paid: true` 対 `chosen: 1`）。
    pub paid: Option<bool>,
}

impl Params {
    fn from_json(v: &serde_json::Value) -> Params {
        let o = v.as_object().expect("params must be an object");
        let mut p = Params::default();
        for (k, val) in o {
            match k.as_str() {
                "count" => p.count = val.as_i64(),
                "amount" => p.amount = val.as_i64(),
                "cost" => p.cost = val.as_i64(),
                "name" => p.name = val.as_str().map(|s| s.to_string()),
                "up_to" => p.up_to = val.as_bool(),
                "back" => p.back = val.as_i64(),
                "chosen" => p.chosen = val.as_i64(),
                "hand_idx" => p.hand_idx = val.as_i64(),
                "tag" => p.tag = val.as_str().map(|s| s.to_string()),
                "color" => p.color = val.as_str().map(|s| s.to_string()),
                "speed" => p.speed = val.as_i64(),
                "card" => p.card = val.as_str().map(|s| s.to_string()),
                "set_tag" => p.set_tag = val.as_str().map(|s| s.to_string()),
                "per" => p.per = val.as_i64(),
                "chara" => p.chara = val.as_str().map(|s| s.to_string()),
                "exclude_tag" => p.exclude_tag = val.as_str().map(|s| s.to_string()),
                "card_name" => p.card_name = val.as_str().map(|s| s.to_string()),
                "level" => p.level = val.as_i64(),
                "delta" => p.delta = val.as_i64(),
                // B-8 の直し（D-093 追記 1）。カードデータには現れないが to_json が書くので受け皿を置く。
                "paid" => p.paid = val.as_bool(),
                _ => panic!("unknown op param {k}"),
            }
        }
        p
    }
    pub fn to_json(&self) -> serde_json::Value {
        let mut m = serde_json::Map::new();
        if let Some(x) = self.count { m.insert("count".into(), x.into()); }
        if let Some(x) = self.amount { m.insert("amount".into(), x.into()); }
        if let Some(x) = self.cost { m.insert("cost".into(), x.into()); }
        if let Some(x) = &self.name { m.insert("name".into(), x.clone().into()); }
        if let Some(x) = self.up_to { m.insert("up_to".into(), x.into()); }
        if let Some(x) = self.back { m.insert("back".into(), x.into()); }
        if let Some(x) = self.chosen { m.insert("chosen".into(), x.into()); }
        if let Some(x) = self.hand_idx { m.insert("hand_idx".into(), x.into()); }
        if let Some(x) = &self.tag { m.insert("tag".into(), x.clone().into()); }
        if let Some(x) = &self.color { m.insert("color".into(), x.clone().into()); }
        if let Some(x) = self.speed { m.insert("speed".into(), x.into()); }
        if let Some(x) = &self.card { m.insert("card".into(), x.clone().into()); }
        if let Some(x) = &self.set_tag { m.insert("set_tag".into(), x.clone().into()); }
        if let Some(x) = self.per { m.insert("per".into(), x.into()); }
        if let Some(x) = &self.chara { m.insert("chara".into(), x.clone().into()); }
        if let Some(x) = &self.exclude_tag { m.insert("exclude_tag".into(), x.clone().into()); }
        if let Some(x) = &self.card_name { m.insert("card_name".into(), x.clone().into()); }
        if let Some(x) = self.level { m.insert("level".into(), x.into()); }
        if let Some(x) = self.delta { m.insert("delta".into(), x.into()); }
        if let Some(x) = self.paid { m.insert("paid".into(), x.into()); }
        serde_json::Value::Object(m)
    }
}

/// 誘発条件（`engine._skill_condition_met` が読むキー）。
#[derive(Clone, Debug, Default)]
pub struct Condition {
    pub self_result_win: Option<bool>,
    pub self_color: Option<Color>,
    pub opp_color: Option<Color>,
    pub self_action_area_count_gte: Option<i64>,
    pub is_turn_player: Option<bool>,
    // --- v0.12 / BP01（D-079 追記 3）。`_skill_condition_met` の新しい鍵と 1 対 1。---
    pub hand_size_lte: Option<i64>,
    pub action_area_tag_count_gte: Option<(String, i64)>,
    pub life_greater_than_opponent: Option<bool>,
    pub leader_name_is: Option<String>,
    pub last_used_card_has_tag: Option<String>,
    pub concerto_has_chara_card: Option<String>,
    pub heals_this_turn_lt: Option<i64>,
    pub dominant: Option<bool>,
    // --- v0.12 / BP01 K-4 ---
    pub opp_damaged_this_turn: Option<bool>,
    pub entered_turn_is_not_current: Option<bool>,
}

#[derive(Clone, Debug)]
pub struct Skill {
    pub timing: Timing,
    pub effect: Vec<(Op, Params)>,
    pub condition: Option<Condition>,
    pub leader_only: bool,
    pub optional: bool,
}

#[derive(Clone, Debug)]
pub struct CharaCard {
    pub card_id: String,
    pub name: String,
    pub level: i64,
    pub skills: Vec<Skill>,
}

#[derive(Clone, Debug)]
pub struct ActionCard {
    pub card_id: String,
    pub name: String,
    pub color: Color,
    pub cost: i64,
    pub speed: i64,
    pub damage: i64,
    /// 特徴タグ（v0.12 / BP01 で条件が読むようになった。`meicho/cards.py` の `tags` と同じ並び）。
    pub tags: Vec<String>,
    pub skills: Vec<Skill>,
    pub dedicated_to: Option<String>,
    pub leader_skill: bool,
}

#[derive(Deserialize)]
struct SkillJson {
    timing: String,
    effect: Vec<(String, serde_json::Value)>,
    condition: Option<serde_json::Map<String, serde_json::Value>>,
    leader_only: bool,
    optional: bool,
}

#[derive(Deserialize)]
struct CharaJson {
    card_id: String,
    name: String,
    level: i64,
    skills: Vec<SkillJson>,
}

#[derive(Deserialize)]
struct ActionJson {
    card_id: String,
    name: String,
    color: String,
    cost: i64,
    speed: i64,
    damage: i64,
    #[serde(default)]
    tags: Vec<String>,
    skills: Vec<SkillJson>,
    dedicated_to: Option<String>,
    leader_skill: bool,
}

#[derive(Deserialize)]
struct DbJson {
    chara: Vec<CharaJson>,
    action: Vec<ActionJson>,
}

fn skill_from_json(j: SkillJson) -> Skill {
    let condition = j.condition.map(|m| {
        let mut c = Condition::default();
        for (k, v) in m {
            match k.as_str() {
                "self_result" => c.self_result_win = Some(v.as_str().unwrap() == "win"),
                "self_color" => c.self_color = Some(Color::from_str(v.as_str().unwrap())),
                "opp_color" => c.opp_color = Some(Color::from_str(v.as_str().unwrap())),
                "self_action_area_count_gte" => c.self_action_area_count_gte = v.as_i64(),
                "is_turn_player" => c.is_turn_player = v.as_bool(),
                // --- v0.12 / BP01（D-079 追記 3）---
                "hand_size_lte" => c.hand_size_lte = v.as_i64(),
                "action_area_tag_count_gte" => {
                    // Python 側は (タグ, 枚数) のタプル。JSON では 2 要素の配列で来る。
                    let a = v.as_array().expect("action_area_tag_count_gte must be [tag, n]");
                    c.action_area_tag_count_gte = Some((
                        a[0].as_str().unwrap().to_string(),
                        a[1].as_i64().unwrap(),
                    ));
                }
                "life_greater_than_opponent" => c.life_greater_than_opponent = v.as_bool(),
                "leader_name_is" => {
                    c.leader_name_is = v.as_str().map(|x| x.to_string())
                }
                "last_used_card_has_tag" => {
                    c.last_used_card_has_tag = v.as_str().map(|x| x.to_string())
                }
                "concerto_has_chara_card" => {
                    c.concerto_has_chara_card = v.as_str().map(|x| x.to_string())
                }
                "heals_this_turn_lt" => c.heals_this_turn_lt = v.as_i64(),
                "dominant" => c.dominant = v.as_bool(),
                "opp_damaged_this_turn" => c.opp_damaged_this_turn = v.as_bool(),
                "entered_turn_is_not_current" => c.entered_turn_is_not_current = v.as_bool(),
                _ => panic!("unknown condition key {k}"),
            }
        }
        c
    });
    Skill {
        timing: Timing::from_str(&j.timing),
        effect: j.effect.into_iter().map(|(op, prm)| (Op::from_str(&op), Params::from_json(&prm))).collect(),
        condition,
        leader_only: j.leader_only,
        optional: j.optional,
    }
}

/// カード表。キャラとアクションは別の添字空間を持つ。
pub struct CardDb {
    pub chara: Vec<CharaCard>,
    pub action: Vec<ActionCard>,
    pub chara_index: HashMap<String, u16>,
    pub action_index: HashMap<String, u16>,
    /// (chara idx, timing) → [(skill idx, leader_only)]（`engine._chara_timing_index` のキャッシュ相当）
    chara_timing: Vec<[Vec<(u8, bool)>; N_TIMINGS]>,
    action_timing: Vec<[Vec<u8>; N_TIMINGS]>,
    /// card_id 文字列で並べたときの順位（Python の `sorted(list_of_ids)` を再現するため）
    pub action_rank: Vec<usize>,
}

fn timing_slot(t: Timing) -> usize {
    match t {
        Timing::Clash => 0,
        Timing::Judge => 1,
        Timing::Rush => 2,
        Timing::TurnEnd => 3,
        Timing::TurnStart => 4,
        Timing::Static => 5,
        Timing::Enter => 6,
        Timing::Levelup => 7,
        Timing::Switched => 8,
        Timing::ClashPhaseStart => 9,
        Timing::ClashPhaseEnd => 10,
        Timing::OnHeal => 11,
        Timing::OnDamageDealt => 12,
    }
}

impl CardDb {
    pub fn from_json(text: &str) -> Result<CardDb, String> {
        let j: DbJson = serde_json::from_str(text).map_err(|e| e.to_string())?;
        let chara: Vec<CharaCard> = j
            .chara
            .into_iter()
            .map(|c| CharaCard {
                card_id: c.card_id,
                name: c.name,
                level: c.level,
                skills: c.skills.into_iter().map(skill_from_json).collect(),
            })
            .collect();
        let action: Vec<ActionCard> = j
            .action
            .into_iter()
            .map(|c| ActionCard {
                card_id: c.card_id,
                name: c.name,
                color: Color::from_str(&c.color),
                cost: c.cost,
                speed: c.speed,
                damage: c.damage,
                tags: c.tags,
                skills: c.skills.into_iter().map(skill_from_json).collect(),
                dedicated_to: c.dedicated_to,
                leader_skill: c.leader_skill,
            })
            .collect();
        let chara_index = chara.iter().enumerate().map(|(i, c)| (c.card_id.clone(), i as u16)).collect();
        let action_index = action.iter().enumerate().map(|(i, c)| (c.card_id.clone(), i as u16)).collect();
        let chara_timing = chara
            .iter()
            .map(|c| {
                let mut arr: [Vec<(u8, bool)>; N_TIMINGS] = Default::default();
                for (k, sk) in c.skills.iter().enumerate() {
                    arr[timing_slot(sk.timing)].push((k as u8, sk.leader_only));
                }
                arr
            })
            .collect();
        let action_timing = action
            .iter()
            .map(|c| {
                let mut arr: [Vec<u8>; N_TIMINGS] = Default::default();
                for (k, sk) in c.skills.iter().enumerate() {
                    arr[timing_slot(sk.timing)].push(k as u8);
                }
                arr
            })
            .collect();
        let mut order: Vec<usize> = (0..action.len()).collect();
        order.sort_by(|&a, &b| action[a].card_id.cmp(&action[b].card_id));
        let mut action_rank = vec![0usize; action.len()];
        for (rank, &i) in order.iter().enumerate() {
            action_rank[i] = rank;
        }
        Ok(CardDb { chara, action, chara_index, action_index, chara_timing, action_timing, action_rank })
    }

    #[inline]
    pub fn chara_timing_index(&self, cid: u16, t: Timing) -> &[(u8, bool)] {
        &self.chara_timing[cid as usize][timing_slot(t)]
    }
    #[inline]
    pub fn action_timing_index(&self, cid: u16, t: Timing) -> &[u8] {
        &self.action_timing[cid as usize][timing_slot(t)]
    }
    pub fn chara_id(&self, s: &str) -> Result<u16, String> {
        self.chara_index.get(s).copied().ok_or_else(|| format!("unknown chara card {s}"))
    }
    pub fn action_id(&self, s: &str) -> Result<u16, String> {
        self.action_index.get(s).copied().ok_or_else(|| format!("unknown action card {s}"))
    }
}
