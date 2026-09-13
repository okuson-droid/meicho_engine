//! ゲーム状態（`meicho/state.py` の写し・D-049）。
//!
//! カードは `CardDb` の添字（u16）で持つ。`to_json` は Python の `GameState.to_json`
//! と同じ構造の JSON を返す（同一性テストはこれを突き合わせる）。

use crate::cards::{CardDb, Op, Params};
use serde_json::{json, Map, Value};

pub const HAND_LIMIT: usize = 8;
pub const STARTING_LIFE: i64 = 20;
pub const MAX_LIFE: i64 = 20;
pub const OPENING_HAND: usize = 5;
pub const DRAW_PER_TURN: usize = 2;
pub const FIRST_TURN_DRAW: usize = 1;
pub const RUSH_UNLIMITED: i64 = 1_000_000_000;
pub const DRAW: i8 = -1;
pub const CLASH_PASS: usize = 3;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Phase {
    SetupChara,
    Mulligan,
    Action,
    ClashSubmit,
    Choice,
    Rush,
    TurnEndDiscard,
    GameOver,
}

impl Phase {
    pub fn as_str(self) -> &'static str {
        match self {
            Phase::SetupChara => "setup_chara",
            Phase::Mulligan => "mulligan",
            Phase::Action => "action",
            Phase::ClashSubmit => "clash_submit",
            Phase::Choice => "choice",
            Phase::Rush => "rush",
            Phase::TurnEndDiscard => "turn_end_discard",
            Phase::GameOver => "game_over",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Submission {
    None,
    Pass,
    Hand(usize),
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum CardKind {
    Chara,
    Action,
}

/// `[player, "chara"|"action", card_id, skill_index]`
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct SkillRef {
    pub player: u8,
    pub kind: CardKind,
    pub card: u16,
    pub idx: u8,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Choice {
    PayOrDamage { player: u8, cost: i64, amount: i64 },
    SwitchBack { player: u8, options: Vec<i64>, names: Vec<String> },
    UseOptional { player: u8, card: u16, skill_index: u8, r: SkillRef },
    RevealCount { player: u8, max: i64 },
    DiscardForEffect { player: u8, remaining: i64 },
    /// レベルアップの手札コスト（reason = "levelup"）
    Discard { player: u8 },
    Order { player: u8, options: Vec<(i64, SkillRef)> },
}

impl Choice {
    pub fn player(&self) -> u8 {
        match self {
            Choice::PayOrDamage { player, .. }
            | Choice::SwitchBack { player, .. }
            | Choice::UseOptional { player, .. }
            | Choice::RevealCount { player, .. }
            | Choice::DiscardForEffect { player, .. }
            | Choice::Discard { player }
            | Choice::Order { player, .. } => *player,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct PendingEffect {
    pub owner: u8,
    /// v0.12: そのスキルが載っているカード（自己参照のオペコードが読む・u11）。
    /// **パラメータにカード番号を書かない**ためにここで持つ（D-050 条件 1）。
    pub card: Option<(CardKind, u16)>,
    pub ops: Vec<(Op, Params)>,
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct Ctx {
    pub switched: Option<Vec<String>>,
    pub bonus_damage: Option<i64>,
    /// v0.12: 「手札1枚を捨ててもよい。**そうした場合**〜」の連結 (BP01-065 / 067)。
    pub discarded: Option<bool>,
}

impl Ctx {
    pub fn is_empty(&self) -> bool {
        self.switched.is_none() && self.bonus_damage.is_none() && self.discarded.is_none()
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Resume {
    TurnStart,
    Judge,
    AfterJudge,
    TurnEnd,
    RushDamage { pi: u8, cid: u16 },
    Action,
}

#[derive(Clone, Debug)]
pub struct PlayerState {
    pub life: i64,
    pub action_deck: Vec<u16>,
    pub hand: Vec<u16>,
    pub concerto: Vec<u16>,
    pub trash: Vec<u16>,
    pub action_area: Vec<u16>,
    pub chara_deck: Vec<u16>,
    pub slots: [Vec<u16>; 3],
    pub mulligan_done: bool,
    pub charas_revealed: bool,
}

impl PlayerState {
    pub fn new() -> PlayerState {
        PlayerState {
            life: STARTING_LIFE,
            action_deck: Vec::new(),
            hand: Vec::new(),
            concerto: Vec::new(),
            trash: Vec::new(),
            action_area: Vec::new(),
            chara_deck: Vec::new(),
            slots: [Vec::new(), Vec::new(), Vec::new()],
            mulligan_done: false,
            charas_revealed: false,
        }
    }
}

#[derive(Clone, Debug)]
pub struct GameState {
    pub seed: i64,
    pub rng_calls: i64,
    pub phase: Phase,
    pub turn_no: i64,
    pub turn_player: u8,
    pub players: [PlayerState; 2],
    pub used_charge: bool,
    pub used_switch: bool,
    pub used_levelup: bool,
    pub pending_submission: [Submission; 2],
    pub clash_cards: [Option<u16>; 2],
    pub clash_winner: Option<u8>,
    pub rush_allowance: i64,
    pub last_clash_winner: Option<u8>,
    pub last_clash_cards: [Option<u16>; 2],
    pub clash_counts: [[i64; 4]; 2],
    pub leader_switch_forbidden: [bool; 2],
    pub rush_forbidden: [bool; 2],
    pub pending_rush_forbidden: [bool; 2],
    pub red_cost_up: [bool; 2],
    pub pending_red_cost_up: [bool; 2],
    pub pending_choices: Vec<Choice>,
    pub pending_skills: Vec<SkillRef>,
    pub pending_effect: Option<PendingEffect>,
    pub pending_ctx: Ctx,
    pub pending_shared_ctx: bool,
    pub choice_resume: Option<Resume>,
    pub phase_before_choice: Option<Phase>,
    pub peeked_opp_hand: [Option<Vec<u16>>; 2],
    // --- v0.12 / BP01（D-079 追記 3）。`meicho/state.py` の同名の欄と 1 対 1。---
    // **すべて既定値で SD001/SD02 の対局が 1 手も変わらない**（T-K-1）。
    pub last_turn_clash_winner: Option<u8>,
    pub last_turn_clash_pass: [bool; 2],
    pub damage_taken_mod: [i64; 2],
    pub first_damage_taken_this_turn: [bool; 2],
    pub speed_override: [Option<i64>; 2],
    pub heals_this_turn: [i64; 2],
    /// このターンに使用したタグごとの回数 (u7)。タグの種類は少ないので Vec の線形探索で足りる。
    pub tag_uses_this_turn: [Vec<(String, i64)>; 2],
    pub last_used_card: [Option<u16>; 2],
    pub damaged_this_turn: [bool; 2],
    pub slot_entered_turn: [[i64; 3]; 2],
    /// BP01-057「終末ループ」で得た付与の残り枚数 (u19)。**連撃で使った
    /// ＜変奏スキル＞だけを数える**。ターンをまたぐと 0 に戻る。
    pub variation_rush_draw: [i64; 2],
    /// [与える側, 量, 与えたカード]。`meicho/state.py` は [pi, amount, [kind, card_id]]。
    pub deferred_clash_damage: Vec<(u8, i64, Option<(CardKind, u16)>)>,
    /// 効果の途中で誘発したスキルの割り込み待ち行列（`_queue_fire_nested`）。
    pub pending_triggers: Vec<SkillRef>,
    pub outcome: Option<i8>,
}

impl GameState {
    pub fn new(seed: i64) -> GameState {
        GameState {
            seed,
            rng_calls: 0,
            phase: Phase::SetupChara,
            turn_no: 0,
            turn_player: 0,
            players: [PlayerState::new(), PlayerState::new()],
            used_charge: false,
            used_switch: false,
            used_levelup: false,
            pending_submission: [Submission::None, Submission::None],
            clash_cards: [None, None],
            clash_winner: None,
            rush_allowance: 0,
            last_clash_winner: None,
            last_clash_cards: [None, None],
            clash_counts: [[0; 4]; 2],
            leader_switch_forbidden: [false, false],
            rush_forbidden: [false, false],
            pending_rush_forbidden: [false, false],
            red_cost_up: [false, false],
            pending_red_cost_up: [false, false],
            pending_choices: Vec::new(),
            pending_skills: Vec::new(),
            pending_effect: None,
            pending_ctx: Ctx::default(),
            pending_shared_ctx: false,
            choice_resume: None,
            phase_before_choice: None,
            peeked_opp_hand: [None, None],
            last_turn_clash_winner: None,
            last_turn_clash_pass: [false, false],
            damage_taken_mod: [0, 0],
            first_damage_taken_this_turn: [false, false],
            speed_override: [None, None],
            heals_this_turn: [0, 0],
            tag_uses_this_turn: [Vec::new(), Vec::new()],
            last_used_card: [None, None],
            damaged_this_turn: [false, false],
            slot_entered_turn: [[0, 0, 0], [0, 0, 0]],
            variation_rush_draw: [0, 0],
            deferred_clash_damage: Vec::new(),
            pending_triggers: Vec::new(),
            outcome: None,
        }
    }

    // ------------------------------------------------------------ JSON
    fn aids(db: &CardDb, v: &[u16]) -> Value {
        Value::Array(v.iter().map(|&i| Value::String(db.action[i as usize].card_id.clone())).collect())
    }
    fn cids(db: &CardDb, v: &[u16]) -> Value {
        Value::Array(v.iter().map(|&i| Value::String(db.chara[i as usize].card_id.clone())).collect())
    }
    fn aid_opt(db: &CardDb, v: Option<u16>) -> Value {
        match v {
            None => Value::Null,
            Some(i) => Value::String(db.action[i as usize].card_id.clone()),
        }
    }
    fn skill_ref_json(db: &CardDb, r: &SkillRef) -> Value {
        let (kind, cid) = match r.kind {
            CardKind::Chara => ("chara", db.chara[r.card as usize].card_id.clone()),
            CardKind::Action => ("action", db.action[r.card as usize].card_id.clone()),
        };
        json!([r.player, kind, cid, r.idx])
    }
    pub fn choice_json(db: &CardDb, c: &Choice) -> Value {
        match c {
            Choice::PayOrDamage { player, cost, amount } => {
                json!({"player": player, "kind": "pay_or_damage", "cost": cost, "amount": amount})
            }
            Choice::SwitchBack { player, options, names } => {
                json!({"player": player, "kind": "switch_back", "options": options, "names": names})
            }
            Choice::UseOptional { player, card, skill_index, r } => json!({
                "player": player, "kind": "use_optional",
                "card": db.chara_or_action_id(r.kind, *card),
                "skill_index": skill_index, "ref": Self::skill_ref_json(db, r)
            }),
            Choice::RevealCount { player, max } => {
                json!({"player": player, "kind": "reveal_count", "max": max})
            }
            Choice::DiscardForEffect { player, remaining } => {
                json!({"player": player, "kind": "discard_for_effect", "remaining": remaining})
            }
            Choice::Discard { player } => {
                json!({"player": player, "kind": "discard", "reason": "levelup"})
            }
            Choice::Order { player, options } => json!({
                "player": player, "kind": "order",
                "options": options.iter().map(|(i, r)| json!({
                    "index": i, "card": db.chara_or_action_id(r.kind, r.card), "skill_index": r.idx
                })).collect::<Vec<_>>()
            }),
        }
    }

    pub fn to_json(&self, db: &CardDb) -> Value {
        let players: Vec<Value> = self
            .players
            .iter()
            .map(|p| {
                json!({
                    "life": p.life,
                    "action_deck": Self::aids(db, &p.action_deck),
                    "hand": Self::aids(db, &p.hand),
                    "concerto": Self::aids(db, &p.concerto),
                    "trash": Self::aids(db, &p.trash),
                    "action_area": Self::aids(db, &p.action_area),
                    "chara_deck": Self::cids(db, &p.chara_deck),
                    "slots": p.slots.iter().map(|s| json!({"stack": Self::cids(db, s)})).collect::<Vec<_>>(),
                    "mulligan_done": p.mulligan_done,
                    "charas_revealed": p.charas_revealed,
                })
            })
            .collect();
        let sub = |s: &Submission| match s {
            Submission::None => Value::Null,
            Submission::Pass => Value::String("PASS".into()),
            Submission::Hand(i) => json!(i),
        };
        let mut ctx = Map::new();
        if let Some(sw) = &self.pending_ctx.switched {
            ctx.insert("switched".into(), json!(sw));
        }
        if let Some(d) = self.pending_ctx.discarded {
            ctx.insert("discarded".into(), json!(d));
        }
        if let Some(b) = self.pending_ctx.bonus_damage {
            ctx.insert("bonus_damage".into(), json!(b));
        }
        let resume = match &self.choice_resume {
            None => Value::Null,
            Some(Resume::TurnStart) => json!({"kind": "turn_start"}),
            Some(Resume::Judge) => json!({"kind": "judge"}),
            Some(Resume::AfterJudge) => json!({"kind": "after_judge"}),
            Some(Resume::TurnEnd) => json!({"kind": "turn_end"}),
            Some(Resume::Action) => json!({"kind": "action"}),
            Some(Resume::RushDamage { pi, cid }) => {
                json!({"kind": "rush_damage", "pi": pi, "cid": db.action[*cid as usize].card_id})
            }
        };
        let effect = match &self.pending_effect {
            None => Value::Null,
            Some(pe) => json!({
                "owner": pe.owner,
                "card": match pe.card {
                    None => Value::Null,
                    Some((kind, idx)) => Value::String(db.chara_or_action_id(kind, idx)),
                },
                "card_kind": match pe.card {
                    None => Value::Null,
                    Some((CardKind::Chara, _)) => Value::String("chara".into()),
                    Some((CardKind::Action, _)) => Value::String("action".into()),
                },
                "ops": pe.ops.iter().map(|(op, prm)| json!([op.as_str(), prm.to_json()])).collect::<Vec<_>>()
            }),
        };
        json!({
            "seed": self.seed,
            "rng_calls": self.rng_calls,
            "phase": self.phase.as_str(),
            "turn_no": self.turn_no,
            "turn_player": self.turn_player,
            "players": players,
            "used_charge": self.used_charge,
            "used_switch": self.used_switch,
            "used_levelup": self.used_levelup,
            "pending_submission": [sub(&self.pending_submission[0]), sub(&self.pending_submission[1])],
            "clash_cards": [Self::aid_opt(db, self.clash_cards[0]), Self::aid_opt(db, self.clash_cards[1])],
            "clash_winner": self.clash_winner,
            "rush_allowance": self.rush_allowance,
            "last_clash_winner": self.last_clash_winner,
            "last_clash_cards": [Self::aid_opt(db, self.last_clash_cards[0]), Self::aid_opt(db, self.last_clash_cards[1])],
            "clash_counts": self.clash_counts,
            "leader_switch_forbidden": self.leader_switch_forbidden,
            "rush_forbidden": self.rush_forbidden,
            "pending_rush_forbidden": self.pending_rush_forbidden,
            "red_cost_up": self.red_cost_up,
            "pending_red_cost_up": self.pending_red_cost_up,
            "pending_choices": self.pending_choices.iter().map(|c| Self::choice_json(db, c)).collect::<Vec<_>>(),
            "pending_skills": self.pending_skills.iter().map(|r| Self::skill_ref_json(db, r)).collect::<Vec<_>>(),
            "pending_effect": effect,
            "pending_ctx": Value::Object(ctx),
            "pending_shared_ctx": self.pending_shared_ctx,
            "choice_resume": resume,
            "phase_before_choice": self.phase_before_choice.map(|p| p.as_str()),
            "peeked_opp_hand": self.peeked_opp_hand.iter().map(|h| match h {
                None => Value::Null,
                Some(v) => Self::aids(db, v),
            }).collect::<Vec<_>>(),
            // --- v0.12 / BP01（D-079 追記 3）。Python の `asdict` と同じ鍵・同じ形。---
            "last_turn_clash_winner": self.last_turn_clash_winner,
            "last_turn_clash_pass": self.last_turn_clash_pass,
            "damage_taken_mod": self.damage_taken_mod,
            "first_damage_taken_this_turn": self.first_damage_taken_this_turn,
            "speed_override": self.speed_override,
            "heals_this_turn": self.heals_this_turn,
            "tag_uses_this_turn": self.tag_uses_this_turn.iter().map(|v| {
                let mut m = serde_json::Map::new();
                for (t, n) in v {
                    m.insert(t.clone(), (*n).into());
                }
                Value::Object(m)
            }).collect::<Vec<_>>(),
            "last_used_card": self.last_used_card.iter().map(|c| match c {
                None => Value::Null,
                Some(cid) => Value::String(db.action[*cid as usize].card_id.clone()),
            }).collect::<Vec<_>>(),
            "damaged_this_turn": self.damaged_this_turn,
            "slot_entered_turn": self.slot_entered_turn,
            "variation_rush_draw": self.variation_rush_draw,
            "deferred_clash_damage": self.deferred_clash_damage.iter()
                .map(|(d, a, src)| {
                    let mut v = vec![Value::from(*d), Value::from(*a)];
                    v.push(match src {
                        None => Value::Null,
                        Some((kind, idx)) => Value::Array(vec![
                            Value::String(match kind {
                                CardKind::Chara => "chara".into(),
                                CardKind::Action => "action".into(),
                            }),
                            Value::String(db.chara_or_action_id(*kind, *idx)),
                        ]),
                    });
                    Value::Array(v)
                })
                .collect::<Vec<_>>(),
            "pending_triggers": self.pending_triggers.iter()
                .map(|r| Self::skill_ref_json(db, r)).collect::<Vec<_>>(),
            "outcome": self.outcome,
        })
    }
}

impl CardDb {
    pub fn chara_or_action_id(&self, kind: CardKind, idx: u16) -> String {
        match kind {
            CardKind::Chara => self.chara[idx as usize].card_id.clone(),
            CardKind::Action => self.action[idx as usize].card_id.clone(),
        }
    }
}
