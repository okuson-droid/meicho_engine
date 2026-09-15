//! ルールエンジン中核（`meicho/engine.py` の写し・rules_draft.md v0.10 準拠・D-049）。
//!
//! 関数の分割と順序は Python 版に揃えてある。挙動の差は同一性テスト
//! （`tests/test_rust_engine.py`）で検出する。**Python 版が真実源**であり、
//! ここに独自の裁定を入れてはならない。
//!
//! 順序依存（D-040）: `apply` は行動を席の昇順で処理する（Python 版の
//! `actions.items()` 挿入順ではない）。既存の呼び出し側は全て昇順なので結果は同じ。

use crate::cards::{ActionCard, CardDb, Color, Op, Params, Skill, Timing, ONKAI_TAG};
use crate::pyrandom::PyRandom;
use crate::state::*;

/// 行動。`legal_actions` が返し、`apply` が受け取る。
#[derive(Clone, Debug, PartialEq)]
pub enum Action {
    Setup { leader: String, backs: Vec<String> },
    Mulligan { cards: Vec<usize> },
    Charge { hand: usize },
    Switch { back: usize },
    Levelup { slot: usize, card: u16 },
    ToClash,
    EndTurn,
    Submit { hand: usize },
    Pass,
    Pay,
    Decline,
    ChooseBack { back: i64 },
    Use,
    Skip,
    ChooseCount { count: i64 },
    Discard { hand: usize },
    Resolve { index: i64 },
    Stop,
    Rush { hand: usize },
    ChooseCard { zone: Zone, index: usize, card: u16, slot: Option<usize> },
}

/// 手の記録のハッシュ（D-053）。決定者と選ばれた手を FNV-1a で畳み込む。
///
/// 発見ループの選別で「δ 入りの挑戦者と champion が**同じ手を選んだか**」を
/// 直接見るために使う。勝敗・ターン数・手数の一致は挙動の一致を意味しないので、
/// 手そのものを畳み込む。ルールの裁定には一切関与しない（記録用）。
pub fn hash_action(h: u64, pi: u8, a: &Action) -> u64 {
    const PRIME: u64 = 0x0000_0100_0000_01b3;
    fn byte(x: &mut u64, b: u8) {
        *x ^= b as u64;
        *x = x.wrapping_mul(PRIME);
    }
    fn num(x: &mut u64, v: i64) {
        for b in (v as u64).to_le_bytes() {
            byte(x, b);
        }
    }
    let mut x = h;
    byte(&mut x, pi);
    let tag: u8 = match a {
        Action::Setup { .. } => 1,
        Action::Mulligan { .. } => 2,
        Action::Charge { .. } => 3,
        Action::Switch { .. } => 4,
        Action::Levelup { .. } => 5,
        Action::ToClash => 6,
        Action::EndTurn => 7,
        Action::Submit { .. } => 8,
        Action::Pass => 9,
        Action::Pay => 10,
        Action::Decline => 11,
        Action::ChooseBack { .. } => 12,
        Action::Use => 13,
        Action::Skip => 14,
        Action::ChooseCount { .. } => 15,
        Action::Discard { .. } => 16,
        Action::Resolve { .. } => 17,
        Action::Stop => 18,
        Action::Rush { .. } => 19,
        Action::ChooseCard { .. } => 20,
    };
    byte(&mut x, tag);
    match a {
        Action::Setup { leader, backs } => {
            for b in leader.as_bytes() {
                byte(&mut x, *b);
            }
            for name in backs { for b in name.as_bytes() { byte(&mut x, *b); } }
        }
        Action::Mulligan { cards } => {
            num(&mut x, cards.len() as i64);
            for c in cards {
                num(&mut x, *c as i64);
            }
        }
        Action::Charge { hand } | Action::Submit { hand } | Action::Discard { hand } | Action::Rush { hand } => {
            num(&mut x, *hand as i64)
        }
        Action::Switch { back } => num(&mut x, *back as i64),
        Action::Levelup { slot, card } => {
            num(&mut x, *slot as i64);
            num(&mut x, *card as i64);
        }
        Action::ChooseBack { back } => num(&mut x, *back),
        Action::ChooseCount { count } => num(&mut x, *count),
        Action::Resolve { index } => num(&mut x, *index),
        Action::ChooseCard { zone, index, card, slot } => {
            num(&mut x, *zone as i64); num(&mut x, *index as i64);
            num(&mut x, *card as i64); num(&mut x, slot.map(|x| x as i64).unwrap_or(-1));
        }
        _ => {}
    }
    x
}

pub type Result<T> = std::result::Result<T, String>;

fn err<T>(msg: impl Into<String>) -> Result<T> {
    Err(msg.into())
}

// ---------------------------------------------------------------------------
// 初期化 (§5)
// ---------------------------------------------------------------------------

fn next_rng(s: &mut GameState) -> PyRandom {
    let r = PyRandom::from_str_seed(&format!("{}:{}", s.seed, s.rng_calls));
    s.rng_calls += 1;
    r
}

pub fn initial_state(db: &CardDb, chara_decks: &[Vec<u16>; 2], action_decks: &[Vec<u16>; 2], seed: i64) -> GameState {
    let _ = db;
    let mut s = GameState::new(seed);
    for pi in 0..2 {
        s.players[pi].chara_deck = chara_decks[pi].clone();
        s.players[pi].action_deck = action_decks[pi].clone();
        let mut r = next_rng(&mut s);
        r.shuffle(&mut s.players[pi].action_deck); // §5-2
    }
    s.phase = Phase::SetupChara;
    s
}

// ---------------------------------------------------------------------------
// 決定要求と合法手
// ---------------------------------------------------------------------------

pub fn decision_players(s: &GameState) -> Vec<u8> {
    match s.phase {
        Phase::SetupChara => (0..2u8).filter(|&pi| s.players[pi as usize].slots[0].is_empty()).collect(),
        Phase::Mulligan => (0..2u8).filter(|&pi| !s.players[pi as usize].mulligan_done).collect(),
        Phase::Action => vec![s.turn_player],
        Phase::ClashSubmit => (0..2u8).filter(|&pi| s.pending_submission[pi as usize] == Submission::None).collect(),
        Phase::Choice => match s.pending_choices.first() {
            Some(c) => vec![c.player()],
            None => vec![],
        },
        Phase::Rush => match s.clash_winner {
            Some(w) => vec![w],
            None => vec![],
        },
        Phase::TurnEndDiscard => vec![s.turn_player],
        Phase::GameOver => vec![],
    }
}

/// カードの実効コスト (§6.4 使用条件I)。`meicho/engine.py::_effective_cost` の写し。
///
/// 修正要因は 2 つ: SD01-016「旋風」の赤コスト +1 と、そのカード自身が持つ
/// 常在型の `cost_mod`（BP01-062「【優勢】このカードのコスト-1」・u20）。
/// **下限は 0**。既存のカードは `cost_mod` を持たないので、ループは空回りする。
fn effective_cost(s: &GameState, pi: usize, card: &ActionCard) -> i64 {
    let mut cost = card.cost;
    if s.red_cost_up[pi] && card.color == Color::Red {
        cost += 1;
    }
    for sk in card.skills.iter() {
        if sk.timing != Timing::Static {
            continue;
        }
        if !sk.effect.iter().any(|(op, _)| *op == Op::CostMod) {
            continue;
        }
        if !skill_condition_met_static(s, pi, sk) {
            continue;
        }
        for (op, prm) in &sk.effect {
            if *op == Op::CostMod {
                cost += prm.delta.unwrap_or(0);
            }
        }
    }
    cost.max(0)
}

/// `effective_cost` から呼ぶ常在型スキルの条件判定 (u20)。
///
/// コストは `db` を持たない場所からも引かれるので、ここで扱えるのは
/// **`db` も対抗の文脈も要らない条件だけ**である。いまは【優勢】(`dominant`) だけ。
/// それ以外の条件を書いた `cost_mod` が来たら **panic する**。黙って無視すると
/// 「割引が効かないだけ」になって対局が静かにずれる——`meicho/engine.py` 側は
/// `_skill_condition_met` を丸ごと通すので、そちらとの食い違いにも気づけない。
fn skill_condition_met_static(s: &GameState, owner: usize, sk: &Skill) -> bool {
    let Some(c) = sk.condition.as_ref() else { return true };
    assert!(
        c.self_result_win.is_none()
            && c.self_color.is_none()
            && c.opp_color.is_none()
            && c.self_action_area_count_gte.is_none()
            && c.is_turn_player.is_none()
            && c.hand_size_lte.is_none()
            && c.action_area_tag_count_gte.is_none()
            && c.life_greater_than_opponent.is_none()
            && c.leader_name_is.is_none()
            && c.last_used_card_has_tag.is_none()
            && c.concerto_has_chara_card.is_none()
            && c.heals_this_turn_lt.is_none()
            && c.opp_damaged_this_turn.is_none()
            && c.entered_turn_is_not_current.is_none(),
        "cost_mod の条件は【優勢】(dominant) しか実装していない"
    );
    match c.dominant {
        Some(want) => is_dominant(s, owner) == want,
        None => true,
    }
}

fn leader_name<'a>(db: &'a CardDb, s: &GameState, pi: usize) -> Option<&'a str> {
    s.players[pi].slots[0].last().map(|&c| db.chara[c as usize].name.as_str())
}

pub fn usable_in_clash(db: &CardDb, s: &GameState, pi: usize, card: &ActionCard) -> bool {
    if effective_cost(s, pi, card) > s.players[pi].concerto.len() as i64 {
        return false;
    }
    // v0.12 / BP01（u5）: ＜音骸＞は自分のアクションエリアに 1 枚まで。2 枚目は使用できない。
    if card.tags.iter().any(|t| t == ONKAI_TAG)
        && s.players[pi]
            .action_area
            .iter()
            .any(|&c| db.action[c as usize].tags.iter().any(|t| t == ONKAI_TAG))
    {
        return false;
    }
    if card.leader_skill {
        let leader = leader_name(db, s, pi);
        if leader != card.dedicated_to.as_deref() {
            return false;
        }
    }
    true
}

fn zone_ref(p: &PlayerState, zone: Zone) -> &Vec<u16> {
    match zone { Zone::Concerto => &p.concerto, Zone::Trash => &p.trash, Zone::CharaDeck => &p.chara_deck }
}

fn zone_mut(p: &mut PlayerState, zone: Zone) -> &mut Vec<u16> {
    match zone { Zone::Concerto => &mut p.concerto, Zone::Trash => &mut p.trash, Zone::CharaDeck => &mut p.chara_deck }
}

fn distinct_zone_options(cards: &[u16], zone: Zone, prm: Option<&Params>, db: &CardDb) -> Vec<Action> {
    let mut seen = Vec::new();
    let mut out = Vec::new();
    for (index, &card) in cards.iter().enumerate() {
        if seen.contains(&card) { continue; }
        if zone == Zone::Trash && prm.map_or(false, |p| !trash_matches(&db.action[card as usize], p)) { continue; }
        seen.push(card);
        out.push(Action::ChooseCard { zone, index, card, slot: None });
    }
    out
}

fn queue_pay_cost(s: &mut GameState, pi: usize, cost: i64) -> bool {
    if cost <= 0 { return false; }
    assert!(s.players[pi].concerto.len() as i64 >= cost);
    let mut seen = s.players[pi].concerto.clone(); seen.sort_unstable(); seen.dedup();
    if seen.len() <= 1 { pay_cost(s, pi, cost); return false; }
    let mut seen=Vec::new(); let options=s.players[pi].concerto.iter().enumerate().filter_map(|(i,&c)|if seen.contains(&c){None}else{seen.push(c);Some((i,c))}).collect();
    s.pending_choices.push(Choice::PayCostCard { player: pi as u8, remaining: cost, options });
    true
}

fn levelup_effect_options(db: &CardDb, s: &GameState, owner: usize, prm: &Params) -> Vec<(usize, usize, u16)> {
    let name = prm.name.as_deref().unwrap();
    let mut out = Vec::new(); let mut seen = Vec::new();
    for (slot, stack) in s.players[owner].slots.iter().enumerate() {
        let Some(&top_id) = stack.last() else { continue };
        let top = &db.chara[top_id as usize];
        if top.name != name { continue; }
        for (index, &cid) in s.players[owner].chara_deck.iter().enumerate() {
            let c = &db.chara[cid as usize];
            let level_ok = prm.level.map_or(c.level == top.level || c.level == top.level + 1, |l| c.level == l);
            if !seen.contains(&cid) && c.name == top.name && level_ok { seen.push(cid); out.push((slot, index, cid)); }
        }
    }
    out
}

pub fn legal_actions(db: &CardDb, s: &GameState, pi: u8) -> Vec<Action> {
    let pu = pi as usize;
    let p = &s.players[pu];
    let mut acts: Vec<Action> = Vec::new();

    if s.phase == Phase::SetupChara && p.slots[0].is_empty() {
        let mut names: Vec<&str> = p
            .chara_deck
            .iter()
            .map(|&c| &db.chara[c as usize])
            .filter(|c| c.level == 0)
            .map(|c| c.name.as_str())
            .collect();
        names.sort();
        names.dedup();
        let owned: Vec<String> = names.into_iter().map(str::to_string).collect();
        let mut out = Vec::new();
        for leader in &owned {
            let backs: Vec<String> = owned.iter().filter(|n| *n != leader).cloned().collect();
            out.push(Action::Setup { leader: leader.clone(), backs: backs.clone() });
            out.push(Action::Setup { leader: leader.clone(), backs: backs.into_iter().rev().collect() });
        }
        return out;
    }

    if s.phase == Phase::Mulligan && !p.mulligan_done {
        let n = p.hand.len();
        return (0..(1usize << n))
            .map(|mask| Action::Mulligan { cards: (0..n).filter(|i| (mask >> i) & 1 == 1).collect() })
            .collect();
    }

    if s.phase == Phase::Action && pi == s.turn_player {
        if !s.used_charge && !p.hand.is_empty() {
            acts.extend((0..p.hand.len()).map(|i| Action::Charge { hand: i }));
        }
        if !s.used_switch && !s.leader_switch_forbidden[pu] {
            for b in 1..3usize {
                if !p.slots[b].is_empty() {
                    acts.push(Action::Switch { back: b });
                }
            }
        }
        if !s.used_levelup {
            for (si, slot) in p.slots.iter().enumerate() {
                let Some(&topc) = slot.last() else { continue };
                let top = &db.chara[topc as usize];
                for &cid in &p.chara_deck {
                    let c = &db.chara[cid as usize];
                    // v0.12 / BP01（u3・BP01-011）: 「カード効果でのみレベルアップできる」カードは
                    // 行動としてのレベルアップの候補から外す。
                    if levelup_by_effect_only(db, cid) {
                        continue;
                    }
                    if c.name == top.name
                        && (c.level == top.level || c.level == top.level + 1)
                        && p.hand.len() as i64 >= c.level
                    {
                        acts.push(Action::Levelup { slot: si, card: cid });
                    }
                }
            }
        }
        acts.push(Action::ToClash);
        acts.push(Action::EndTurn);
        return acts;
    }

    if s.phase == Phase::ClashSubmit && s.pending_submission[pu] == Submission::None {
        let usable: Vec<usize> = p
            .hand
            .iter()
            .enumerate()
            .filter(|(_, &cid)| usable_in_clash(db, s, pu, &db.action[cid as usize]))
            .map(|(i, _)| i)
            .collect();
        acts.extend(usable.iter().map(|&i| Action::Submit { hand: i }));
        if pi != s.turn_player || usable.is_empty() {
            acts.push(Action::Pass);
        }
        return acts;
    }

    if s.phase == Phase::Choice {
        if let Some(ch) = s.pending_choices.first() {
            if ch.player() == pi {
                return match ch {
                    Choice::PayOrDamage { .. } => vec![Action::Pay, Action::Decline],
                    Choice::SwitchBack { options, .. } => {
                        options.iter().map(|&b| Action::ChooseBack { back: b }).collect()
                    }
                    Choice::UseOptional { .. } => vec![Action::Use, Action::Skip],
                    Choice::RevealCount { max, .. } => (0..=*max).map(|n| Action::ChooseCount { count: n }).collect(),
                    Choice::Discard { .. } | Choice::DiscardForEffect { .. } => {
                        (0..p.hand.len()).map(|i| Action::Discard { hand: i }).collect()
                    }
                    Choice::Order { options, .. } => {
                        options.iter().map(|(i, _)| Action::Resolve { index: *i }).collect()
                    }
                    Choice::PayCostCard { options, .. } => options.iter().map(|&(index,card)|Action::ChooseCard{zone:Zone::Concerto,index,card,slot:None}).collect(),
                    Choice::ZoneCard { zone, optional, options, .. } => {
                        let mut v:Vec<Action> = options.iter().map(|&(index,card)|Action::ChooseCard{zone:*zone,index,card,slot:None}).collect();
                        if *optional { v.push(Action::Stop); }
                        v
                    }
                    Choice::LevelupByEffect { options, .. } => options.iter().map(|&(slot, index, card)|
                        Action::ChooseCard { zone: Zone::CharaDeck, index, card, slot: Some(slot) }).collect(),
                };
            }
        }
    }

    if s.phase == Phase::Rush && Some(pi) == s.clash_winner {
        acts.push(Action::Stop);
        if s.rush_allowance > 0 && !s.rush_forbidden[pu] {
            for (i, &cid) in p.hand.iter().enumerate() {
                let c = &db.action[cid as usize];
                if c.color == Color::Red && usable_in_clash(db, s, pu, c) {
                    acts.push(Action::Rush { hand: i });
                }
            }
        }
        return acts;
    }

    if s.phase == Phase::TurnEndDiscard && pi == s.turn_player {
        return (0..p.hand.len()).map(|i| Action::Discard { hand: i }).collect();
    }

    acts
}

// ---------------------------------------------------------------------------
// 効果解決
// ---------------------------------------------------------------------------

fn draw(s: &mut GameState, pi: usize, count: usize) {
    for _ in 0..count {
        if s.players[pi].action_deck.is_empty() {
            if s.players[pi].trash.is_empty() {
                return; // 引けない（裁定未確認だが実害なし）
            }
            let t = std::mem::take(&mut s.players[pi].trash);
            s.players[pi].action_deck = t;
            let mut r = next_rng(s);
            r.shuffle(&mut s.players[pi].action_deck); // §6.2 デッキ再構成
        }
        let c = s.players[pi].action_deck.remove(0);
        s.players[pi].hand.push(c);
    }
}

/// v0.12: `meicho/engine.py::_damage` の写し。`dealer` を渡すと
/// 【相手にダメージを与えた時】(u18) を割り込みで積む。
fn damage_by(
    db: &CardDb,
    s: &mut GameState,
    pi: usize,
    amount: i64,
    dealer: Option<usize>,
    source: Option<(CardKind, u16)>,
) {
    if amount <= 0 {
        return;
    }
    let mut amount = amount + s.damage_taken_mod[pi] + static_damage_taken_mod(db, s, pi);
    if !s.first_damage_taken_this_turn[pi] {
        amount += first_damage_taken_mod(db, s, pi);
        s.first_damage_taken_this_turn[pi] = true;
    }
    if amount <= 0 {
        return;
    }
    let p = &mut s.players[pi];
    p.life -= amount;
    let dead = p.life <= 0;
    s.damaged_this_turn[pi] = true;
    if dead && s.outcome.is_none() {
        s.players[pi].life = 0;
        s.outcome = Some((1 - pi) as i8);
        s.phase = Phase::GameOver;
        return;
    }
    if let (Some(d), Some((kind, cid))) = (dealer, source) {
        queue_fire_on_card(db, s, Timing::OnDamageDealt, d, kind, cid);
    }
}

/// **そのカード 1 枚**のスキルだけを割り込みで積む（u18・`_queue_fire_on_card` の写し）。
/// 盤面を走査しないので、連撃で使ったカード（対抗カードではない）も普通に拾える。
fn queue_fire_on_card(
    db: &CardDb,
    s: &mut GameState,
    timing: Timing,
    pi: usize,
    kind: CardKind,
    cid: u16,
) {
    let refs: Vec<SkillRef> = match kind {
        CardKind::Chara => {
            // 【リーダー】前置はリーダー枠に居るときだけ有効 (§2.1)。
            let in_leader = s.players[pi].slots[0].contains(&cid);
            db.chara_timing_index(cid, timing)
                .iter()
                .filter(|(_, leader_only)| !*leader_only || in_leader)
                .map(|&(k, _)| SkillRef { player: pi as u8, kind, card: cid, idx: k })
                .collect()
        }
        CardKind::Action => db
            .action_timing_index(cid, timing)
            .iter()
            .map(|&k| SkillRef { player: pi as u8, kind, card: cid, idx: k })
            .collect(),
    };
    if !refs.is_empty() {
        s.pending_triggers.extend(refs);
    }
}

/// v0.12: `meicho/engine.py::_heal` の写し。実際に 1 以上回復したときだけ数え、
/// 【自分のライフが回復した時】を割り込みで積む。
fn heal(db: &CardDb, s: &mut GameState, pi: usize, amount: i64) {
    let before = s.players[pi].life;
    s.players[pi].life = MAX_LIFE.min(before + amount);
    if s.players[pi].life > before {
        s.heals_this_turn[pi] += 1;
        queue_fire_nested(db, s, Timing::OnHeal, &[pi]);
    }
}

/// 「各ターン、自分が最初に受けるダメージ +N / −N」(u7・BP01-002)。
fn first_damage_taken_mod(db: &CardDb, s: &GameState, pi: usize) -> i64 {
    let mut m = 0;
    let mut refs = Vec::new();
    active_skill_refs(db, s, pi, Timing::Static, &mut refs);
    for r in &refs {
        for (op, prm) in &deref_skill(db, r).effect {
            if *op == Op::FirstDamageTakenMod {
                m += prm.amount.unwrap_or(0);
            }
        }
    }
    m
}


fn ctx_switched_contains(ctx: &Ctx, name: &str) -> bool {
    ctx.switched.as_ref().map_or(false, |v| v.iter().any(|n| n == name))
}

/// オペコード1個を適用する。`ctx` は `s.pending_ctx` を一時的に取り出したもの。
fn apply_op(db: &CardDb, s: &mut GameState, owner: usize, op: Op, prm: &Params, ctx: &mut Ctx) -> Result<()> {
    match op {
        Op::Draw | Op::RevealTopToHand => draw(s, owner, prm.count.unwrap() as usize),
        Op::TopToConcerto => {
            for _ in 0..prm.count.unwrap() {
                if !s.players[owner].action_deck.is_empty() {
                    let c = s.players[owner].action_deck.remove(0);
                    s.players[owner].concerto.push(c);
                }
            }
        }
        Op::DamageOpponent => {
            let src = s.pending_effect.as_ref().and_then(|pe| pe.card);
            damage_by(db, s, 1 - owner, prm.amount.unwrap(), Some(owner), src)
        }
        Op::Pursuit => s.rush_allowance += prm.count.unwrap(), // D-012: 加算
        Op::ForbidLeaderSwitchThisTurn => s.leader_switch_forbidden[owner] = true,
        Op::SwitchLeader => {
            if !s.leader_switch_forbidden[owner] {
                let backs: Vec<usize> = (1..3usize).filter(|&b| !s.players[owner].slots[b].is_empty()).collect();
                let b: Option<usize> = match prm.back {
                    Some(b) => Some(b as usize),
                    None => backs.first().copied(),
                };
                if let Some(b) = b {
                    if !s.players[owner].slots[b].is_empty() {
                        // D-024: 入れ替わった2名の名前を両方記録する
                        let moved = [
                            leader_name(db, s, owner).map(|x| x.to_string()),
                            s.players[owner].slots[b].last().map(|&c| db.chara[c as usize].name.clone()),
                        ];
                        s.players[owner].slots.swap(0, b);
                        s.slot_entered_turn[owner].swap(0, b);
                        let names = ctx.switched.get_or_insert_with(Vec::new);
                        for nm in moved.into_iter().flatten() {
                            if !names.contains(&nm) {
                                names.push(nm);
                            }
                        }
                        // v0.12: 【切り替え】は実際に行われたときだけ誘発する (§7)。
                        queue_fire_nested(db, s, Timing::Switched, &[owner]);
                    }
                }
            }
        }
        Op::SelfDamageBuffIfSwitched => {
            if ctx_switched_contains(ctx, prm.name.as_deref().unwrap()) {
                ctx.bonus_damage = Some(ctx.bonus_damage.unwrap_or(0) + prm.amount.unwrap());
            }
        }
        Op::TopToConcertoIfSwitched => {
            if ctx_switched_contains(ctx, prm.name.as_deref().unwrap()) {
                for _ in 0..prm.count.unwrap() {
                    if !s.players[owner].action_deck.is_empty() {
                        let c = s.players[owner].action_deck.remove(0);
                        s.players[owner].concerto.push(c);
                    }
                }
            }
        }
        Op::RushDamageBuff | Op::DedicatedLeaderCardDamageBuff => {} // 常在型
        Op::HealSelf => heal(db, s, owner, prm.amount.unwrap()),
        Op::RaiseOpponentRedCostNextTurn => s.pending_red_cost_up[1 - owner] = true,
        Op::ReturnClashCardToHand => {
            if let Some(cid) = s.clash_cards[owner] {
                let p = &mut s.players[owner];
                if let Some(pos) = p.action_area.iter().position(|&c| c == cid) {
                    p.action_area.remove(pos);
                    p.hand.push(cid);
                }
            }
        }
        Op::OpponentPayOrDamage => {
            let target = 1 - owner;
            let cost = prm.cost.unwrap();
            let amount = prm.amount.unwrap();
            if (s.players[target].concerto.len() as i64) < cost {
                damage_by(db, s, target, amount, None, None);
            } else {
                s.pending_choices.push(Choice::PayOrDamage { player: target as u8, cost, amount });
            }
        }
        Op::DiscardSelf => {
            // `_run_effects` 経由（選択なし）のときだけここに来る。左端から捨てる。
            for _ in 0..prm.count.unwrap() {
                if !s.players[owner].hand.is_empty() {
                    let c = s.players[owner].hand.remove(0);
                    s.players[owner].trash.push(c);
                    ctx.discarded = Some(true);
                }
            }
        }
        Op::DrawIfSwitched => {
            if ctx_switched_contains(ctx, prm.name.as_deref().unwrap()) {
                draw(s, owner, prm.count.unwrap() as usize);
            }
        }
        Op::SelfDamageBuff => {
            ctx.bonus_damage = Some(ctx.bonus_damage.unwrap_or(0) + prm.amount.unwrap());
        }
        Op::ForbidRushNextTurn => s.pending_rush_forbidden[1 - owner] = true,
        Op::PeekOpponentHand => {
            s.peeked_opp_hand[owner] = Some(s.players[1 - owner].hand.clone());
        }
        // --- v0.12 / BP01（D-079 追記 3）。`meicho/engine.py::_apply_op` の写し。---
        Op::DrawTo => {
            let need = prm.count.unwrap() - s.players[owner].hand.len() as i64;
            if need > 0 {
                draw(s, owner, need as usize);
            }
        }
        Op::HealIfSwitched => {
            if ctx_switched_contains(ctx, prm.name.as_deref().unwrap()) {
                heal(db, s, owner, prm.amount.unwrap());
            }
        }
        Op::SelfDamageBuffIfDiscarded => {
            if ctx.discarded == Some(true) {
                ctx.bonus_damage = Some(ctx.bonus_damage.unwrap_or(0) + prm.amount.unwrap());
            }
        }
        Op::SelfDamageBuffPerActionArea => {
            let n = s.players[owner].action_area.len() as i64;
            ctx.bonus_damage = Some(ctx.bonus_damage.unwrap_or(0) + prm.amount.unwrap() * n);
        }
        // 常在型。ダメージ計算側 (`card_damage_bonus`) で参照する。
        Op::FirstUseDamageBuff | Op::FirstDamageTakenMod
        | Op::NameColorDamageBuff | Op::OwnCardDamageBuff => {}
        Op::ForbidRushSelfNow => {
            s.rush_forbidden[owner] = true;
            if s.turn_player as usize == owner {
                s.rush_allowance = 0;
            }
        }
        Op::ForbidRushOpponentNow => {
            s.rush_forbidden[1 - owner] = true;
            if s.turn_player as usize != owner {
                s.rush_allowance = 0;
            }
        }
        Op::PayCostReturnSelfToHand => {
            let cost = prm.cost.unwrap();
            // 「このカード」はそのスキルが載っているカード自身（`pending_effect.card`）。
            let want = match s.pending_effect.as_ref().and_then(|pe| pe.card) {
                Some((CardKind::Action, cid)) => Some(cid),
                _ => None,
            };
            if let Some(cid) = want {
                let p = &s.players[owner];
                if p.action_area.contains(&cid) && p.concerto.len() as i64 >= cost {
                    if prm.chosen != Some(1) { pay_cost(s, owner, cost); }
                    let pos = s.players[owner].action_area.iter().position(|&x| x == cid).unwrap();
                    s.players[owner].action_area.remove(pos);
                    s.players[owner].hand.push(cid);
                }
            }
        }
        Op::SpeedOverride => s.speed_override[owner] = Some(prm.speed.unwrap()),
        // --- v0.12 / BP01 K-3（D-079 追記 5）＜音骸＞の【優勢】の妨害 5 種 ---
        //
        // **選ぶ側は効果のオーナー**（u8）だが、K-3 では選択肢化せず自動選択（左端）にしてある
        // （`meicho/engine.py` の同じ箇所に理由を書いた。要は `CHOICE_KINDS` を伸ばすと
        // `N_SCALAR` が変わり、符号化の版上げとネットの移行がもう一度要るため）。
        //
        // **乱数は `next_rng` からだけ引き、Python と消費回数まで揃える**（作業規約 2）。
        // Python の `random.randrange(n)` は `_randbelow(n)` なので `randbelow` と一致する。
        Op::OppDiscardRandom => {
            let target = 1 - owner;
            let n = s.players[target].hand.len() / prm.per.unwrap() as usize;
            for _ in 0..n {
                if s.players[target].hand.is_empty() {
                    break;
                }
                let len = s.players[target].hand.len();
                let idx = next_rng(s).randbelow(len as u64) as usize;
                let c = s.players[target].hand.remove(idx);
                s.players[target].trash.push(c);
            }
        }
        Op::OppConcertoToTrash => {
            let target = 1 - owner;
            for _ in 0..prm.count.unwrap() {
                if s.players[target].concerto.is_empty() {
                    break;
                }
                let c = s.players[target].concerto.remove(0);
                s.players[target].trash.push(c);
            }
        }
        Op::OppHandRandomToDeckBottom => {
            let target = 1 - owner;
            for _ in 0..prm.count.unwrap() {
                if s.players[target].hand.is_empty() {
                    break;
                }
                let len = s.players[target].hand.len();
                let idx = next_rng(s).randbelow(len as u64) as usize;
                let c = s.players[target].hand.remove(idx);
                s.players[target].action_deck.push(c);
            }
        }
        Op::MillOpponentDeckTop => {
            let target = 1 - owner;
            for _ in 0..prm.count.unwrap() {
                if s.players[target].action_deck.is_empty() {
                    break;                               // 山が尽きたら再構成しない
                }
                let c = s.players[target].action_deck.remove(0);
                s.players[target].trash.push(c);
            }
        }
        Op::OppTrashToDeckBottom => {
            let target = 1 - owner;
            for _ in 0..prm.count.unwrap() {
                if s.players[target].trash.is_empty() {
                    break;
                }
                let c = s.players[target].trash.remove(0);
                s.players[target].action_deck.push(c);
            }
        }
        // 常在型。ダメージ計算側 (`card_damage_bonus`) で参照する。
        Op::ConcertoSetFirstUseBuff => {}
        // --- v0.12 / BP01 K-4（D-079 追記 6）---
        // **回収先・置く札は自動選択（トラッシュの左端）**。理由は `meicho/engine.py` の同じ箇所。
        Op::TrashToHand => {
            let n = prm.count.unwrap_or(1);
            for _ in 0..n {
                let idx = s.players[owner]
                    .trash
                    .iter()
                    .position(|&c| trash_matches(&db.action[c as usize], prm));
                let Some(i) = idx else { break };
                let c = s.players[owner].trash.remove(i);
                s.players[owner].hand.push(c);
            }
        }
        Op::TrashToConcerto => {
            let n = prm.count.unwrap_or(1);
            for _ in 0..n {
                let idx = s.players[owner]
                    .trash
                    .iter()
                    .position(|&c| trash_matches(&db.action[c as usize], prm));
                let Some(i) = idx else { break };
                let c = s.players[owner].trash.remove(i);
                s.players[owner].concerto.push(c);
            }
        }
        Op::ReturnToCharaDeck => {
            // 「このカードをキャラデッキに戻す」(u4)。下のカードが最上段に戻る＝レベルが下がる。
            let cid = match s.pending_effect.as_ref().and_then(|pe| pe.card) {
                Some((CardKind::Chara, c)) => Some(c),
                _ => None,
            };
            if let Some(cid) = cid {
                for si in 0..3usize {
                    if s.players[owner].slots[si].last() == Some(&cid) {
                        s.players[owner].slots[si].pop();
                        s.players[owner].chara_deck.push(cid);
                        break;
                    }
                }
            }
        }
        Op::LevelupByEffect => {
            levelup_by_effect(db, s, owner, prm.name.as_deref().unwrap(), prm.level)
        }
        Op::LevelupByEffectIfSwitched => {
            if ctx_switched_contains(ctx, prm.name.as_deref().unwrap()) {
                levelup_by_effect(db, s, owner, prm.name.as_deref().unwrap(), prm.level);
            }
        }
        Op::TrashToHandIfSwitched => {
            if ctx_switched_contains(ctx, prm.name.as_deref().unwrap()) {
                let mut sub = prm.clone();
                sub.name = None;
                let n = sub.count.unwrap_or(1);
                for _ in 0..n {
                    let idx = s.players[owner]
                        .trash
                        .iter()
                        .position(|&c| trash_matches(&db.action[c as usize], &sub));
                    let Some(i) = idx else { break };
                    let c = s.players[owner].trash.remove(i);
                    s.players[owner].hand.push(c);
                }
            }
        }
        // 標識・常在型。`legal_actions` / `static_damage_taken_mod` /
        // `collect_granted_deferred_damage` が読む。
        // 標識・常在型。`legal_actions` / `static_damage_taken_mod` /
        // `collect_granted_deferred_damage` / `effective_cost` が読む。
        Op::LevelupByEffectOnly | Op::DamageTakenMod | Op::GrantDeferredDamageOnLoss
            | Op::CostMod => {}
        Op::GrantRushDrawToVariationSkills => {
            // BP01-057 (u19)。同じターンに複数回誘発したら加算（「追撃N」と同じ扱い）。
            s.variation_rush_draw[owner] += prm.count.unwrap_or(0);
        }
        Op::SwitchLeaderTo => {
            // 「自分のリーダーを「◯◯」に切り替える」(u14)。居なければ何も起きない。
            if !s.leader_switch_forbidden[owner] {
                let name = prm.name.as_deref().unwrap();
                for b in 1..3usize {
                    let is_target = s.players[owner].slots[b]
                        .last()
                        .map_or(false, |&c| db.chara[c as usize].name == name);
                    if !is_target {
                        continue;
                    }
                    let moved = [
                        leader_name(db, s, owner).map(|x| x.to_string()),
                        Some(name.to_string()),
                    ];
                    s.players[owner].slots.swap(0, b);
                    s.slot_entered_turn[owner].swap(0, b);
                    let names = ctx.switched.get_or_insert_with(Vec::new);
                    for nm in moved.into_iter().flatten() {
                        if !names.contains(&nm) {
                            names.push(nm);
                        }
                    }
                    queue_fire_nested(db, s, Timing::Switched, &[owner]);
                    break;
                }
            }
        }
        Op::SearchDeck => {
            // **該当が無くてもシャッフルする**（u15）＝乱数をちょうど 1 回消費する。
            let want = prm.card_name.as_deref().unwrap();
            let idx = s.players[owner]
                .action_deck
                .iter()
                .position(|&c| db.action[c as usize].name == want);
            if let Some(i) = idx {
                let c = s.players[owner].action_deck.remove(i);
                s.players[owner].hand.push(c);
            }
            let mut r = next_rng(s);
            r.shuffle(&mut s.players[owner].action_deck);
        }
        Op::RevealNTakeMatching => {
            let n = (prm.count.unwrap() as usize).min(s.players[owner].action_deck.len());
            let revealed: Vec<u16> = s.players[owner].action_deck.drain(..n).collect();
            for cid in revealed {
                if trash_matches(&db.action[cid as usize], prm) {
                    s.players[owner].hand.push(cid);
                } else {
                    s.players[owner].trash.push(cid);
                }
            }
        }
    }
    Ok(())
}

fn skill_condition_met(db: &CardDb, s: &GameState, owner: usize, sk: &Skill) -> bool {
    let Some(c) = &sk.condition else { return true };
    if let Some(want_win) = c.self_result_win {
        let is_win = s.clash_winner == Some(owner as u8);
        if is_win != want_win || s.clash_winner.is_none() {
            return false;
        }
    }
    if let Some(col) = c.self_color {
        match s.clash_cards[owner] {
            Some(cid) if db.action[cid as usize].color == col => {}
            _ => return false,
        }
    }
    if let Some(col) = c.opp_color {
        match s.clash_cards[1 - owner] {
            Some(cid) if db.action[cid as usize].color == col => {}
            _ => return false,
        }
    }
    if let Some(n) = c.self_action_area_count_gte {
        if (s.players[owner].action_area.len() as i64) < n {
            return false;
        }
    }
    if let Some(want) = c.is_turn_player {
        if (s.turn_player as usize == owner) != want {
            return false;
        }
    }
    // --- v0.12 / BP01（D-079 追記 3）。`_skill_condition_met` の写し。---
    if let Some(n) = c.hand_size_lte {
        if s.players[owner].hand.len() as i64 > n {
            return false;
        }
    }
    if let Some((tag, need)) = &c.action_area_tag_count_gte {
        let n = s.players[owner]
            .action_area
            .iter()
            .filter(|&&cid| db.action[cid as usize].tags.iter().any(|t| t == tag))
            .count() as i64;
        if n < *need {
            return false;
        }
    }
    if let Some(want) = c.life_greater_than_opponent {
        if (s.players[owner].life > s.players[1 - owner].life) != want {
            return false;
        }
    }
    if let Some(name) = &c.leader_name_is {
        if leader_name(db, s, owner) != Some(name.as_str()) {
            return false;
        }
    }
    if let Some(tag) = &c.last_used_card_has_tag {
        match s.last_used_card[owner] {
            Some(cid) if db.action[cid as usize].tags.iter().any(|t| t == tag) => {}
            _ => return false,
        }
    }
    if let Some(name) = &c.concerto_has_chara_card {
        let hit = s.players[owner]
            .concerto
            .iter()
            .any(|&cid| db.action[cid as usize].dedicated_to.as_deref() == Some(name.as_str()));
        if !hit {
            return false;
        }
    }
    if let Some(n) = c.heals_this_turn_lt {
        if s.heals_this_turn[owner] >= n {
            return false;
        }
    }
    if let Some(want) = c.dominant {
        if is_dominant(s, owner) != want {
            return false;
        }
    }
    // --- v0.12 / BP01 K-4 ---
    if let Some(want) = c.opp_damaged_this_turn {
        if s.damaged_this_turn[1 - owner] != want {
            return false;
        }
    }
    if let Some(want) = c.entered_turn_is_not_current {
        // 「このカードがこのターン以外に登場した場合」(BP01-011)。
        let cid = match s.pending_effect.as_ref().and_then(|pe| pe.card) {
            Some((CardKind::Chara, c)) => Some(c),
            _ => None,
        };
        let si = cid.and_then(|cid| {
            (0..3usize).find(|&i| s.players[owner].slots[i].last() == Some(&cid))
        });
        let Some(si) = si else { return false };
        let entered_this_turn = s.slot_entered_turn[owner][si] == s.turn_no;
        if entered_this_turn == want {
            return false;
        }
    }
    true
}

/// 【優勢】(u2)。`meicho/engine.py::_is_dominant` の写し。
fn is_dominant(s: &GameState, pi: usize) -> bool {
    if s.turn_no <= 1 {
        return false;
    }
    s.last_turn_clash_winner == Some(pi as u8) || s.last_turn_clash_pass[1 - pi]
}

fn active_skill_refs(db: &CardDb, s: &GameState, pi: usize, timing: Timing, out: &mut Vec<SkillRef>) {
    let p = &s.players[pi];
    for (si, slot) in p.slots.iter().enumerate() {
        for &cid in slot {
            for &(k, leader_only) in db.chara_timing_index(cid, timing) {
                if leader_only && si != 0 {
                    continue;
                }
                out.push(SkillRef { player: pi as u8, kind: CardKind::Chara, card: cid, idx: k });
            }
        }
    }
    if timing.is_area() {
        // v0.12: 場面として発火するタイミングは**アクションエリア**のカードも拾う（u11・u18）。
        let mut seen: Vec<u16> = Vec::new();
        for &cid in p.action_area.iter() {
            if seen.contains(&cid) {
                continue;                    // 同名 2 枚は 1 回だけ（枠は 1 つ）
            }
            seen.push(cid);
            for &k in db.action_timing_index(cid, timing) {
                out.push(SkillRef { player: pi as u8, kind: CardKind::Action, card: cid, idx: k });
            }
        }
        return;
    }
    if let Some(cid) = s.clash_cards[pi] {
        for &k in db.action_timing_index(cid, timing) {
            out.push(SkillRef { player: pi as u8, kind: CardKind::Action, card: cid, idx: k });
        }
    }
}

fn deref_skill<'a>(db: &'a CardDb, r: &SkillRef) -> &'a Skill {
    match r.kind {
        CardKind::Chara => &db.chara[r.card as usize].skills[r.idx as usize],
        CardKind::Action => &db.action[r.card as usize].skills[r.idx as usize],
    }
}

// ---------------------------------------------------------------------------
// 効果解決エンジン（中断・再開可能） D-022
// ---------------------------------------------------------------------------

fn queue_fire(db: &CardDb, s: &mut GameState, timing: Timing, players_order: [usize; 2], resume: Resume) {
    let mut refs = Vec::new();
    for &pi in &players_order {
        active_skill_refs(db, s, pi, timing, &mut refs);
    }
    s.pending_skills = refs;
    s.pending_effect = None;
    s.pending_ctx = Ctx::default();
    s.pending_shared_ctx = false;
    s.choice_resume = Some(resume);
}

/// v0.12: 効果の解決の**途中**で誘発したスキルを割り込みの待ち行列に積む
/// （`meicho/engine.py::_queue_fire_nested` の写し）。`queue_fire` と違って
/// `pending_skills` も `choice_resume` も触らない。
fn queue_fire_nested(db: &CardDb, s: &mut GameState, timing: Timing, players_order: &[usize]) {
    let mut refs = Vec::new();
    for &pi in players_order {
        active_skill_refs(db, s, pi, timing, &mut refs);
    }
    if !refs.is_empty() {
        s.pending_triggers.extend(refs);
    }
}

/// 割り込みの待ち行列から 1 つ解決を始める（`_start_next_trigger` の写し）。
/// 順番の選択 (A-7) は挟まない。
fn start_next_trigger(db: &CardDb, s: &mut GameState) -> Result<()> {
    let r = s.pending_triggers.remove(0);
    if !skill_condition_met(db, s, r.player as usize, deref_skill(db, &r)) {
        return Ok(());
    }
    let sk = deref_skill(db, &r);
    if sk.optional {
        s.pending_choices.push(Choice::UseOptional {
            player: r.player, card: r.card, skill_index: r.idx, r: r.clone(),
        });
        return Ok(());
    }
    let pi = r.player as usize;
    start_skill_effect(s, pi, sk, Some((r.kind, r.card)));
    Ok(())
}

fn start_next_skill(db: &CardDb, s: &mut GameState) -> Result<()> {
    let pi = s.pending_skills[0].player;
    let mut n = 0;
    while n < s.pending_skills.len() && s.pending_skills[n].player == pi {
        n += 1;
    }
    let rest: Vec<SkillRef> = s.pending_skills[n..].to_vec();
    let group: Vec<SkillRef> = s.pending_skills[..n]
        .iter()
        .copied()
        .filter(|r| skill_condition_met(db, s, pi as usize, deref_skill(db, r)))
        .collect();
    s.pending_skills = group.iter().copied().chain(rest.into_iter()).collect();
    if group.is_empty() {
        return Ok(());
    }
    if group.len() >= 2 {
        s.pending_choices.push(Choice::Order {
            player: pi,
            options: group.iter().enumerate().map(|(i, r)| (i as i64, *r)).collect(),
        });
        return Ok(());
    }
    let r = s.pending_skills.remove(0);
    begin_skill(db, s, r)
}

fn begin_skill(db: &CardDb, s: &mut GameState, r: SkillRef) -> Result<()> {
    let sk = deref_skill(db, &r);
    if sk.optional {
        s.pending_choices.push(Choice::UseOptional { player: r.player, card: r.card, skill_index: r.idx, r });
        return Ok(());
    }
    start_skill_effect(s, r.player as usize, sk, Some((r.kind, r.card)));
    Ok(())
}

fn start_skill_effect(s: &mut GameState, pi: usize, sk: &Skill, card: Option<(CardKind, u16)>) {
    if !s.pending_shared_ctx {
        s.pending_ctx = Ctx::default();
    }
    s.pending_effect = Some(PendingEffect { owner: pi as u8, card, ops: sk.effect.clone() });
}

fn step_effect(db: &CardDb, s: &mut GameState) -> Result<()> {
    let owner = s.pending_effect.as_ref().unwrap().owner as usize;
    let (op, prm0) = s.pending_effect.as_ref().unwrap().ops[0].clone();

    if op == Op::LevelupByEffectIfSwitched {
        if ctx_switched_contains(&s.pending_ctx, prm0.name.as_deref().unwrap()) {
            s.pending_effect.as_mut().unwrap().ops[0].0 = Op::LevelupByEffect;
        } else { s.pending_effect.as_mut().unwrap().ops.remove(0); }
        return Ok(());
    }
    if op == Op::TrashToHandIfSwitched {
        if ctx_switched_contains(&s.pending_ctx, prm0.name.as_deref().unwrap()) {
            let pe = s.pending_effect.as_mut().unwrap(); pe.ops[0].0 = Op::TrashToHand; pe.ops[0].1.name = None;
        } else { s.pending_effect.as_mut().unwrap().ops.remove(0); }
        return Ok(());
    }
    if op == Op::PayCostReturnSelfToHand && prm0.chosen.is_none() {
        let cost = prm0.cost.unwrap();
        let valid = s.pending_effect.as_ref().unwrap().card.map_or(false, |(k,c)|
            k == CardKind::Action && s.players[owner].action_area.contains(&c))
            && s.players[owner].concerto.len() as i64 >= cost;
        if !valid { s.pending_effect.as_mut().unwrap().ops.remove(0); return Ok(()); }
        s.pending_effect.as_mut().unwrap().ops[0].1.chosen = Some(1);
        if queue_pay_cost(s, owner, cost) { return Ok(()); }
    }
    if matches!(op, Op::OppConcertoToTrash | Op::OppTrashToDeckBottom | Op::TrashToHand | Op::TrashToConcerto) {
        let (zone_owner, zone, destination, optional) = match op {
            Op::OppConcertoToTrash => (1-owner, Zone::Concerto, Destination::Trash, false),
            Op::OppTrashToDeckBottom => (1-owner, Zone::Trash, Destination::ActionDeck, true),
            Op::TrashToHand => (owner, Zone::Trash, Destination::Hand, false),
            _ => (owner, Zone::Trash, Destination::Concerto, false),
        };
        let remaining = prm0.count.unwrap_or(1);
        let opts = distinct_zone_options(zone_ref(&s.players[zone_owner], zone), zone, Some(&prm0), db);
        if remaining <= 0 || opts.is_empty() { s.pending_effect.as_mut().unwrap().ops.remove(0); }
        else { let options=opts.into_iter().filter_map(|a|match a{Action::ChooseCard{index,card,..}=>Some((index,card)),_=>None}).collect();
            s.pending_choices.push(Choice::ZoneCard { player: owner as u8, zone_owner: zone_owner as u8,
            zone, destination, remaining, optional, match_params: prm0, options }); }
        return Ok(());
    }
    if op == Op::LevelupByEffect {
        let options = levelup_effect_options(db, s, owner, &prm0);
        if options.is_empty() { s.pending_effect.as_mut().unwrap().ops.remove(0); }
        else { s.pending_choices.push(Choice::LevelupByEffect { player: owner as u8, options }); }
        return Ok(());
    }

    if op == Op::SwitchLeader && prm0.back.is_none() {
        // A-5: どちらのバックをリーダーにするか
        let backs: Vec<i64> = (1..3usize).filter(|&b| !s.players[owner].slots[b].is_empty()).map(|b| b as i64).collect();
        if s.leader_switch_forbidden[owner] || backs.is_empty() {
            s.pending_effect.as_mut().unwrap().ops.remove(0);
            return Ok(());
        }
        if backs.len() == 1 {
            s.pending_effect.as_mut().unwrap().ops[0].1.back = Some(backs[0]);
        } else {
            let names = backs
                .iter()
                .map(|&b| db.chara[*s.players[owner].slots[b as usize].last().unwrap() as usize].name.clone())
                .collect();
            s.pending_choices.push(Choice::SwitchBack { player: owner as u8, options: backs, names });
            return Ok(());
        }
    }

    if op == Op::RevealTopToHand && prm0.up_to == Some(true) {
        // A-2: 「N枚まで」の枚数選択
        if prm0.chosen.is_none() {
            s.pending_choices.push(Choice::RevealCount { player: owner as u8, max: prm0.count.unwrap() });
            return Ok(());
        }
        s.pending_effect.as_mut().unwrap().ops.remove(0);
        draw(s, owner, prm0.chosen.unwrap() as usize);
        return Ok(());
    }

    if op == Op::DiscardSelf {
        // A-4: 捨てるカードの選択。1枚ずつ処理する。
        let count = prm0.count.unwrap();
        if count <= 0 || s.players[owner].hand.is_empty() {
            s.pending_effect.as_mut().unwrap().ops.remove(0);
            return Ok(());
        }
        let idx: usize = if s.players[owner].hand.len() == 1 {
            0
        } else if let Some(h) = prm0.hand_idx {
            s.pending_effect.as_mut().unwrap().ops[0].1.hand_idx = None; // prm.pop("hand_idx")
            h as usize
        } else {
            s.pending_choices.push(Choice::DiscardForEffect { player: owner as u8, remaining: count });
            return Ok(());
        };
        let c = s.players[owner].hand.remove(idx);
        s.players[owner].trash.push(c);
        s.pending_effect.as_mut().unwrap().ops[0].1.count = Some(count - 1);
        // v0.12: 「そうした場合」の連結（BP01-065 / 067）。既存カードは誰も読まない。
        s.pending_ctx.discarded = Some(true);
        return Ok(());
    }

    let (op, prm) = s.pending_effect.as_mut().unwrap().ops.remove(0);
    let mut ctx = std::mem::take(&mut s.pending_ctx);
    let r = apply_op(db, s, owner, op, &prm, &mut ctx);
    s.pending_ctx = ctx;
    r
}

fn pump(db: &CardDb, s: &mut GameState) -> Result<()> {
    loop {
        if s.outcome.is_some() {
            s.pending_skills.clear();
            s.pending_triggers.clear();
            s.pending_effect = None;
            s.pending_choices.clear();
            s.choice_resume = None;
            s.pending_ctx = Ctx::default();
            s.pending_shared_ctx = false;
            return Ok(());
        }
        if !s.pending_choices.is_empty() {
            if s.phase != Phase::Choice {
                s.phase_before_choice = Some(s.phase);
                s.phase = Phase::Choice;
            }
            return Ok(());
        }
        if s.phase == Phase::Choice {
            s.phase = s.phase_before_choice.unwrap_or(Phase::Action);
        }
        if let Some(pe) = &s.pending_effect {
            if pe.ops.is_empty() {
                s.pending_effect = None;
            } else {
                step_effect(db, s)?;
            }
            continue;
        }
        // 割り込み（効果の途中で誘発したもの）を、外側の待ち行列より先に片付ける。
        if !s.pending_triggers.is_empty() {
            start_next_trigger(db, s)?;
            continue;
        }
        if !s.pending_skills.is_empty() {
            start_next_skill(db, s)?;
            continue;
        }
        if let Some(resume) = s.choice_resume.take() {
            s.pending_shared_ctx = false;
            dispatch_resume(db, s, resume)?;
            continue;
        }
        return Ok(());
    }
}

fn dispatch_resume(db: &CardDb, s: &mut GameState, r: Resume) -> Result<()> {
    match r {
        Resume::TurnStart => after_turn_start(s),
        Resume::Judge => judge_step(db, s),
        Resume::AfterJudge => after_judge(db, s),
        Resume::TurnEnd => after_turn_end(db, s),
        Resume::RushDamage { pi, cid } => after_rush_skills(db, s, pi as usize, cid),
        Resume::Action => s.phase = Phase::Action,
        Resume::AfterClashCosts => after_clash_costs(db, s),
        Resume::StartRush { pi, cid } => start_rush(db, s, pi as usize, cid),
    }
    Ok(())
}

fn card_damage_bonus(db: &CardDb, s: &GameState, pi: usize, card: &ActionCard, in_rush: bool) -> i64 {
    let mut buff = 0;
    // v0.12: **そのカード自身**に付いた常在型（BP01-055 真源演算・重撃
    // 「自分のライフが相手より多い場合、このカードのダメージ+1」）。
    // 下のプレイヤーの常在型の走査は「他のカードを強める」ものを集めるので、
    // 自分自身にだけ効くものはここで分けて見る。対抗でも連撃でも同じく効く。
    for sk in card.skills.iter().filter(|sk| sk.timing == Timing::Static) {
        for (op, prm) in &sk.effect {
            if *op == Op::OwnCardDamageBuff && skill_condition_met(db, s, pi, sk) {
                buff += prm.amount.unwrap();
            }
        }
    }
    // v0.12 / BP01 K-3: ＜音骸＞の強化は**協奏エリアに置かれたカード**に載っている（u6）。
    // 協奏エリアは `active_skill_refs` の走査対象ではないので、ここで別に見る。
    if !s.players[pi].concerto.is_empty() {
        let mut seen: Vec<u16> = Vec::new();
        for &ccid in s.players[pi].concerto.iter() {
            if seen.contains(&ccid) {
                continue;
            }
            seen.push(ccid);
            for sk in db.action[ccid as usize].skills.iter() {
                if sk.timing != Timing::Static {
                    continue;
                }
                for (op, prm) in &sk.effect {
                    if *op != Op::ConcertoSetFirstUseBuff {
                        continue;
                    }
                    let set_tag = prm.set_tag.as_deref().unwrap_or("");
                    // 「種類」はカード名の異なり数（u6）。このカード自身も含まれる。
                    let mut kinds: Vec<&str> = Vec::new();
                    for &c in s.players[pi].concerto.iter() {
                        let ac = &db.action[c as usize];
                        if ac.tags.iter().any(|t| t == set_tag)
                            && !kinds.contains(&ac.name.as_str())
                        {
                            kinds.push(ac.name.as_str());
                        }
                    }
                    if (kinds.len() as i64) < prm.count.unwrap() {
                        continue;
                    }
                    let tag = prm.tag.as_deref().unwrap_or("");
                    if card.tags.iter().any(|t| t == tag) && tag_uses(s, pi, tag) == 0 {
                        buff += prm.amount.unwrap();
                    }
                }
            }
        }
    }
    let mut refs = Vec::new();
    active_skill_refs(db, s, pi, Timing::Static, &mut refs);
    for r in &refs {
        let sk = deref_skill(db, r);
        for (op, prm) in &sk.effect {
            match op {
                Op::RushDamageBuff if in_rush => buff += prm.amount.unwrap(),
                Op::DedicatedLeaderCardDamageBuff => {
                    if card.dedicated_to.as_deref() == prm.name.as_deref() && card.leader_skill {
                        buff += prm.amount.unwrap();
                    }
                }
                // --- v0.12 / BP01（D-079 追記 3）---
                Op::NameColorDamageBuff => {
                    // 「自分の【◯◯】の〈色〉のカードのダメージ+N」（BP01-001 / BP01-011）
                    if card.dedicated_to.as_deref() == prm.name.as_deref()
                        && card.color.as_str() == prm.color.as_deref().unwrap_or("")
                    {
                        buff += prm.amount.unwrap();
                    }
                }
                Op::FirstUseDamageBuff => {
                    // 「各ターンに自分が最初に使用する〈タグ〉のダメージ+N」(u7)。
                    // **このカードを数える前**に呼ばれるので、0 回なら「最初」。
                    let tag = prm.tag.as_deref().unwrap_or("");
                    if card.tags.iter().any(|t| t == tag)
                        && prm
                            .name
                            .as_ref()
                            .map_or(true, |n| card.dedicated_to.as_deref() == Some(n.as_str()))
                        && tag_uses(s, pi, tag) == 0
                    {
                        buff += prm.amount.unwrap();
                    }
                }
                _ => {}
            }
        }
    }
    buff
}

// ---------------------------------------------------------------------------
// フェーズ進行
// ---------------------------------------------------------------------------

fn pay_cost(s: &mut GameState, pi: usize, cost: i64) {
    for _ in 0..cost {
        let c = s.players[pi].concerto.remove(0);
        s.players[pi].trash.push(c);
    }
}

fn is_deadlocked(s: &GameState) -> bool {
    s.players
        .iter()
        .all(|p| p.hand.is_empty() && p.action_deck.is_empty() && p.trash.is_empty() && p.action_area.is_empty())
}

/// トラッシュ回収の絞り込み（`_trash_matches` の写し）。書いていない欄は「問わない」。
fn trash_matches(card: &ActionCard, prm: &Params) -> bool {
    if let Some(tag) = &prm.tag {
        if !tag.split('|').any(|t| card.tags.iter().any(|x| x == t)) {
            return false;
        }
    }
    if let Some(ex) = &prm.exclude_tag {
        if card.tags.iter().any(|x| x == ex) {
            return false;
        }
    }
    if let Some(col) = &prm.color {
        if card.color.as_str() != col.as_str() {
            return false;
        }
    }
    if let Some(ch) = &prm.chara {
        if card.dedicated_to.as_deref() != Some(ch.as_str()) {
            return false;
        }
    }
    if let Some(nm) = &prm.card_name {
        if card.name != *nm {
            return false;
        }
    }
    true
}

/// 「このカードはカード効果でのみレベルアップできる」か (u3・BP01-011)。
fn levelup_by_effect_only(db: &CardDb, cid: u16) -> bool {
    db.chara[cid as usize].skills.iter().any(|sk| {
        sk.timing == Timing::Static && sk.effect.iter().any(|(op, _)| *op == Op::LevelupByEffectOnly)
    })
}

/// 「自分が受けるダメージ +N / −N」(u13) の常在型ぶん（`_static_damage_taken_mod` の写し）。
fn static_damage_taken_mod(db: &CardDb, s: &GameState, pi: usize) -> i64 {
    let mut mod_ = 0;
    let mut refs = Vec::new();
    active_skill_refs(db, s, pi, Timing::Static, &mut refs);
    for r in &refs {
        for (op, prm) in &deref_skill(db, r).effect {
            if *op == Op::DamageTakenMod {
                mod_ += prm.amount.unwrap_or(0);
            }
        }
    }
    mod_
}

/// 効果によるレベルアップ (u3)。コストを払わず、1 ターン 1 回も消費しない。
/// 効果によるレベルアップ。`level` を渡すと**そのレベルのカード**を探す (u21)。
/// 省略時（`None`）は従来どおり「次のレベル」。同レベルの上にも置ける（§6.3-3）。
fn levelup_by_effect(db: &CardDb, s: &mut GameState, owner: usize, name: &str, level: Option<i64>) {
    for si in 0..3usize {
        let Some(&topc) = s.players[owner].slots[si].last() else { continue };
        let top = &db.chara[topc as usize];
        if top.name != name {
            continue;
        }
        let want_level = level.unwrap_or(top.level + 1);
        let nxt = s.players[owner].chara_deck.iter().position(|&c| {
            db.chara[c as usize].name == name && db.chara[c as usize].level == want_level
        });
        let Some(pos) = nxt else { break };
        let cid = s.players[owner].chara_deck.remove(pos);
        s.players[owner].slots[si].push(cid);
        s.slot_entered_turn[owner][si] = s.turn_no;
        queue_fire_nested(db, s, Timing::Enter, &[owner]);
        queue_fire_nested(db, s, Timing::Levelup, &[owner]);
        break;
    }
}

/// 付与スキルによる持ち越しダメージ（`_collect_granted_deferred_damage` の写し・BP01-014）。
fn collect_granted_deferred_damage(db: &CardDb, s: &mut GameState, winner: usize) {
    let loser = 1 - winner;
    let (Some(wcid), Some(lcid)) = (s.clash_cards[winner], s.clash_cards[loser]) else { return };
    if db.action[wcid as usize].color != Color::Red {
        return;
    }
    let lcard = &db.action[lcid as usize];
    let mut refs = Vec::new();
    active_skill_refs(db, s, loser, Timing::Static, &mut refs);
    let mut add: Vec<(u8, i64, Option<(CardKind, u16)>)> = Vec::new();
    for r in &refs {
        for (op, prm) in &deref_skill(db, r).effect {
            if *op != Op::GrantDeferredDamageOnLoss {
                continue;
            }
            if let Some(ch) = &prm.chara {
                if lcard.dedicated_to.as_deref() != Some(ch.as_str()) {
                    continue;
                }
            }
            let tags: Vec<&String> = [prm.tag.as_ref(), prm.set_tag.as_ref()]
                .into_iter().flatten().collect();
            if !tags.is_empty() && !tags.iter().any(|t| lcard.tags.iter().any(|x| x == *t)) {
                continue;
            }
            add.push((loser as u8, lcard.damage, Some((CardKind::Action, lcid))));
        }
    }
    s.deferred_clash_damage.extend(add);
}

/// このターンにそのタグを使用した回数 (u7)。
fn tag_uses(s: &GameState, pi: usize, tag: &str) -> i64 {
    s.tag_uses_this_turn[pi]
        .iter()
        .find(|(t, _)| t == tag)
        .map_or(0, |(_, n)| *n)
}

/// カードを使用した記録（u7 の「最初に使用する〈タグ〉」と「直前に使用したカード」）。
/// **ダメージ計算のあとに呼ぶ**こと（`_note_card_use` の写し）。
fn note_card_use(db: &CardDb, s: &mut GameState, pi: usize, cid: u16) {
    s.last_used_card[pi] = Some(cid);
    for tag in db.action[cid as usize].tags.clone() {
        match s.tag_uses_this_turn[pi].iter_mut().find(|(t, _)| *t == tag) {
            Some(e) => e.1 += 1,
            None => s.tag_uses_this_turn[pi].push((tag, 1)),
        }
    }
}

fn note_clash_uses(db: &CardDb, s: &mut GameState) {
    for pi in 0..2 {
        if let Some(cid) = s.clash_cards[pi] {
            note_card_use(db, s, pi, cid);
        }
    }
}

/// 対抗フェイズの終了 (v0.12・`_close_clash_phase` の写し)。
fn close_clash_phase(db: &CardDb, s: &mut GameState) {
    let tp = s.turn_player as usize;
    if !s.deferred_clash_damage.is_empty() {
        let pending: Vec<(u8, i64, Option<(CardKind, u16)>)> =
            s.deferred_clash_damage.drain(..).collect();
        for (dealer, amount, src) in pending {
            if s.outcome.is_some() {
                break;
            }
            let d = dealer as usize;
            damage_by(db, s, 1 - d, amount, Some(d), src);
        }
    }
    queue_fire_nested(db, s, Timing::ClashPhaseEnd, &[tp, 1 - tp]);
    s.speed_override = [None, None];
}

fn begin_turn(db: &CardDb, s: &mut GameState) {
    // v0.12: 【優勢】(u2) が見る「前のターン」を 1 ターンぶん繰り越し、
    // ターンごとに数え直すものを片付ける（`_begin_turn` の写し）。
    s.last_turn_clash_winner = s.clash_winner;
    s.last_turn_clash_pass = [
        s.pending_submission[0] == Submission::Pass,
        s.pending_submission[1] == Submission::Pass,
    ];
    s.heals_this_turn = [0, 0];
    s.tag_uses_this_turn = [Vec::new(), Vec::new()];
    s.last_used_card = [None, None];
    s.damaged_this_turn = [false, false];
    s.first_damage_taken_this_turn = [false, false];
    s.speed_override = [None, None];
    s.turn_no += 1;
    for pi in 0..2 {
        s.rush_forbidden[pi] = s.pending_rush_forbidden[pi];
        s.pending_rush_forbidden[pi] = false;
        s.red_cost_up[pi] = s.pending_red_cost_up[pi];
        s.pending_red_cost_up[pi] = false;
    }
    s.used_charge = false;
    s.used_switch = false;
    s.used_levelup = false;
    s.variation_rush_draw = [0, 0];      // u19: ターン終了で消える
    s.pending_submission = [Submission::None, Submission::None];
    s.clash_cards = [None, None];
    s.clash_winner = None;
    s.rush_allowance = 0;
    s.leader_switch_forbidden = [false, false];
    s.pending_choices.clear();
    s.choice_resume = None;
    let tp = s.turn_player as usize;
    queue_fire(db, s, Timing::TurnStart, [tp, 1 - tp], Resume::TurnStart);
}

fn after_turn_start(s: &mut GameState) {
    let n = if s.turn_no == 1 { FIRST_TURN_DRAW } else { DRAW_PER_TURN };
    let tp = s.turn_player as usize;
    draw(s, tp, n);
    if is_deadlocked(s) {
        s.outcome = Some(DRAW);
        s.phase = Phase::GameOver;
        return;
    }
    s.phase = Phase::Action;
}

fn resolve_clash(db: &CardDb, s: &mut GameState) {
    let tp = s.turn_player as usize;
    let ntp = 1 - tp;
    let mut costs = Vec::new();
    for pi in [tp, ntp] {
        match s.pending_submission[pi] {
            Submission::Pass => {
                s.clash_cards[pi] = None;
                s.clash_counts[pi][CLASH_PASS] += 1;
            }
            Submission::Hand(idx) => {
                let cid = s.players[pi].hand.remove(idx);
                s.players[pi].action_area.push(cid);
                let cost = effective_cost(s, pi, &db.action[cid as usize]);
                costs.push((pi, cost));
                s.clash_cards[pi] = Some(cid);
                s.clash_counts[pi][db.action[cid as usize].color.clash_index()] += 1;
            }
            Submission::None => unreachable!("resolve_clash with missing submission"),
        }
    }
    let mut queued = false;
    for (pi, cost) in costs { queued = queue_pay_cost(s, pi, cost) || queued; }
    if queued { s.choice_resume = Some(Resume::AfterClashCosts); return; }
    after_clash_costs(db, s);
}

fn after_clash_costs(db: &CardDb, s: &mut GameState) {
    let tp = s.turn_player as usize;
    let ntp = 1 - tp;
    queue_fire(db, s, Timing::Clash, [tp, ntp], Resume::Judge);
}

fn judge_step(db: &CardDb, s: &mut GameState) {
    let tp = s.turn_player as usize;
    let ntp = 1 - tp;
    let (a, b) = (s.clash_cards[tp], s.clash_cards[ntp]);
    let winner: Option<usize> = match (a, b) {
        (None, None) => None,
        (Some(_), None) => Some(tp),
        (None, Some(_)) => Some(ntp),
        (Some(a), Some(b)) => {
            let ca = &db.action[a as usize];
            let cb = &db.action[b as usize];
            if ca.color != cb.color {
                Some(if ca.color.beats(cb.color) { tp } else { ntp })
            } else if ca.color == Color::Blue {
                None
            } else {
                // v0.12: 「このカードのスピードは N になる」(u10) は判定の比較だけに効く上書き。
                let sa = s.speed_override[tp].unwrap_or(ca.speed);
                let sb = s.speed_override[ntp].unwrap_or(cb.speed);
                if sa != sb {
                    Some(if sa > sb { tp } else { ntp })
                } else {
                    Some(tp)
                }
            }
        }
    };
    s.clash_winner = winner.map(|w| w as u8);
    s.last_clash_winner = s.clash_winner;
    s.last_clash_cards = s.clash_cards;
    if winner.is_none() {
        note_clash_uses(db, s);          // v0.12: 引き分けでも「使用した」ことは変わらない (u7)
        end_turn_begin(db, s);
        return;
    }
    collect_granted_deferred_damage(db, s, winner.unwrap());
    queue_fire(db, s, Timing::Judge, [tp, ntp], Resume::AfterJudge);
}

fn after_judge(db: &CardDb, s: &mut GameState) {
    let winner = s.clash_winner.unwrap() as usize;
    let wcid = s.clash_cards[winner].unwrap();
    let wcard = &db.action[wcid as usize];
    let dmg = wcard.damage + card_damage_bonus(db, s, winner, wcard, false);
    // v0.12: 「最初に使用する〈タグ〉」(u7) はこのカードを数える前の値で判定するので、
    // ダメージを決めてから記録する。順番を入れ替えないこと。
    note_clash_uses(db, s);
    damage_by(db, s, 1 - winner, dmg, Some(winner), Some((CardKind::Action, wcid)));
    if s.outcome.is_some() {
        return;
    }
    if wcard.color == Color::Red {
        s.rush_allowance = RUSH_UNLIMITED;
    }
    if s.rush_allowance > 0 {
        s.phase = Phase::Rush;
    } else {
        end_turn_begin(db, s);
    }
}

fn do_rush(db: &CardDb, s: &mut GameState, pi: usize, hand_idx: usize) {
    let cid = s.players[pi].hand.remove(hand_idx);
    let card = &db.action[cid as usize];
    s.rush_allowance -= 1;
    let cost = effective_cost(s, pi, card);
    s.players[pi].action_area.push(cid);
    if queue_pay_cost(s, pi, cost) {
        s.choice_resume = Some(Resume::StartRush { pi: pi as u8, cid });
        return;
    }
    start_rush(db, s, pi, cid);
}

fn start_rush(db: &CardDb, s: &mut GameState, pi: usize, cid: u16) {
    let card = &db.action[cid as usize];
    s.pending_skills = card
        .skills
        .iter()
        .enumerate()
        .filter(|(_, sk)| sk.timing == Timing::Rush)
        .map(|(k, _)| SkillRef { player: pi as u8, kind: CardKind::Action, card: cid, idx: k as u8 })
        .collect();
    s.pending_effect = None;
    s.pending_ctx = Ctx::default();
    s.pending_shared_ctx = true;
    s.choice_resume = Some(Resume::RushDamage { pi: pi as u8, cid });
}

fn after_rush_skills(db: &CardDb, s: &mut GameState, pi: usize, cid: u16) {
    // BP01-057 で得た『【連撃】カード1枚を引く。』(u19)。カード自身の【連撃】スキルを
    // 全部片付けたあと、連撃ダメージの前に解決する（後から得たスキルは後ろに並ぶ）。
    if s.variation_rush_draw[pi] > 0
        && db.action[cid as usize].tags.iter().any(|t| t == "変奏スキル")
    {
        s.variation_rush_draw[pi] -= 1;
        draw(s, pi, 1);
        if s.outcome.is_some() {
            return;
        }
    }
    let card = &db.action[cid as usize];
    let dmg = card.damage + card_damage_bonus(db, s, pi, card, true) + s.pending_ctx.bonus_damage.unwrap_or(0);
    s.pending_ctx = Ctx::default();
    note_card_use(db, s, pi, cid);       // v0.12: ダメージを決めてから数える (u7)
    damage_by(db, s, 1 - pi, dmg, Some(pi), Some((CardKind::Action, cid)));
    if s.outcome.is_some() {
        return;
    }
    s.phase = Phase::Rush;
    if s.rush_allowance <= 0 || !legal_actions(db, s, pi as u8).iter().any(|a| matches!(a, Action::Rush { .. })) {
        end_turn_begin(db, s);
    }
}

fn end_turn_begin(db: &CardDb, s: &mut GameState) {
    let tp = s.turn_player as usize;
    close_clash_phase(db, s);            // v0.12: 【各対抗フェイズ終了時】と持ち越しダメージ
    queue_fire(db, s, Timing::TurnEnd, [tp, 1 - tp], Resume::TurnEnd);
}

fn after_turn_end(db: &CardDb, s: &mut GameState) {
    let tp = s.turn_player as usize;
    for pi in 0..2 {
        let aa = std::mem::take(&mut s.players[pi].action_area);
        s.players[pi].trash.extend(aa);
    }
    if s.players[tp].hand.len() > HAND_LIMIT {
        s.phase = Phase::TurnEndDiscard;
    } else {
        next_turn(db, s);
    }
}

fn next_turn(db: &CardDb, s: &mut GameState) {
    s.turn_player = 1 - s.turn_player;
    begin_turn(db, s);
}

// ---------------------------------------------------------------------------
// apply
// ---------------------------------------------------------------------------

/// `apply`（非破壊）。
pub fn apply(db: &CardDb, state: &GameState, actions: &[(u8, Action)]) -> Result<GameState> {
    let mut s = state.clone();
    apply_owned(db, &mut s, actions)?;
    Ok(s)
}

/// `apply_owned`（渡された state を直接書き換える）。`actions` は席の昇順に処理する。
pub fn apply_owned(db: &CardDb, s: &mut GameState, actions: &[(u8, Action)]) -> Result<()> {
    let need = decision_players(s);
    let mut given: Vec<u8> = actions.iter().map(|(pi, _)| *pi).collect();
    given.sort_unstable();
    let mut need_sorted = need.clone();
    need_sorted.sort_unstable();
    if given != need_sorted {
        return err(format!("actions for {:?} required", need));
    }
    let mut sorted: Vec<&(u8, Action)> = actions.iter().collect();
    sorted.sort_by_key(|(pi, _)| *pi);
    apply_inner(db, s, &sorted)?;
    pump(db, s)
}

fn apply_inner(db: &CardDb, s: &mut GameState, actions: &[&(u8, Action)]) -> Result<()> {
    match s.phase {
        Phase::SetupChara => {
            for (pi, act) in actions {
                let pu = *pi as usize;
                let Action::Setup { leader, backs: chosen_backs } = act else { return err("setup expected") };
                // lv0: name → cid（同名の Lv0 が複数あれば後勝ち。Python の dict 内包と同じ）
                let mut lv0: Vec<(String, u16)> = Vec::new();
                for &c in &s.players[pu].chara_deck {
                    let cc = &db.chara[c as usize];
                    if cc.level == 0 {
                        if let Some(e) = lv0.iter_mut().find(|(n, _)| *n == cc.name) {
                            e.1 = c;
                        } else {
                            lv0.push((cc.name.clone(), c));
                        }
                    }
                }
                let mut backs: Vec<String> = if chosen_backs.is_empty() {
                    let mut b: Vec<String> = lv0.iter().map(|(n, _)| n.clone()).filter(|n| n != leader).collect();
                    b.sort(); b
                } else { chosen_backs.clone() };
                let mut order = vec![leader.clone()];
                order.extend(backs);
                for (si, name) in order.iter().enumerate() {
                    let cid = lv0.iter().find(|(n, _)| n == name).map(|(_, c)| *c).ok_or("unknown leader")?;
                    s.players[pu].slots[si] = vec![cid];
                    let pos = s.players[pu].chara_deck.iter().position(|&c| c == cid).unwrap();
                    s.players[pu].chara_deck.remove(pos);
                }
            }
            if decision_players(s).is_empty() {
                for pi in 0..2 {
                    draw(s, pi, OPENING_HAND);
                }
                s.phase = Phase::Mulligan;
            }
            Ok(())
        }
        Phase::Mulligan => {
            for (pi, act) in actions {
                let pu = *pi as usize;
                let Action::Mulligan { cards } = act else { return err("mulligan expected") };
                let mut idxs: Vec<usize> = cards.clone();
                idxs.sort_unstable();
                idxs.dedup();
                let p = &mut s.players[pu];
                let back: Vec<u16> = idxs.iter().map(|&i| p.hand[i]).collect();
                p.hand = p.hand.iter().enumerate().filter(|(i, _)| !idxs.contains(i)).map(|(_, &c)| c).collect();
                p.action_deck.extend(back.iter().copied());
                for _ in 0..back.len() {
                    if !p.action_deck.is_empty() {
                        let c = p.action_deck.remove(0);
                        p.hand.push(c);
                    }
                }
                let mut r = next_rng(s);
                r.shuffle(&mut s.players[pu].action_deck);
                s.players[pu].mulligan_done = true;
            }
            if decision_players(s).is_empty() {
                for pi in 0..2 {
                    s.players[pi].charas_revealed = true;
                }
                begin_turn(db, s);
            }
            Ok(())
        }
        Phase::Action => {
            let tp = s.turn_player;
            let act = &actions.iter().find(|(pi, _)| *pi == tp).ok_or("turn player action missing")?.1;
            let tpu = tp as usize;
            match act {
                Action::Charge { hand } => {
                    if s.used_charge {
                        return err("charge already used");
                    }
                    let c = s.players[tpu].hand.remove(*hand);
                    s.players[tpu].concerto.push(c);
                    s.used_charge = true;
                }
                Action::Switch { back } => {
                    if s.used_switch || s.leader_switch_forbidden[tpu] {
                        return err("switch not allowed");
                    }
                    s.players[tpu].slots.swap(0, *back);
                    s.slot_entered_turn[tpu].swap(0, *back);
                    s.used_switch = true;
                    // v0.12: 行動としての切り替えでも【切り替え】は誘発する (§7)。
                    queue_fire_nested(db, s, Timing::Switched, &[tpu]);
                }
                Action::Levelup { slot, card } => {
                    if s.used_levelup {
                        return err("levelup already used");
                    }
                    let c = &db.chara[*card as usize];
                    let top = &db.chara[*s.players[tpu].slots[*slot].last().ok_or("empty slot")? as usize];
                    if !(c.name == top.name && (c.level == top.level || c.level == top.level + 1)) {
                        return err("illegal levelup");
                    }
                    if (s.players[tpu].hand.len() as i64) < c.level {
                        return err("not enough hand for levelup");
                    }
                    let pos = s.players[tpu].chara_deck.iter().position(|&x| x == *card).ok_or("card not in chara deck")?;
                    s.players[tpu].chara_deck.remove(pos);
                    s.players[tpu].slots[*slot].push(*card);
                    s.slot_entered_turn[tpu][*slot] = s.turn_no;
                    s.used_levelup = true;
                    // v0.12: 【登場】と【レベルアップ】。準備 (§5-4) では誘発しない (u1)。
                    queue_fire_nested(db, s, Timing::Enter, &[tpu]);
                    queue_fire_nested(db, s, Timing::Levelup, &[tpu]);
                    if c.level > 0 {
                        for _ in 0..c.level {
                            s.pending_choices.push(Choice::Discard { player: tp });
                        }
                        s.choice_resume = Some(Resume::Action);
                    }
                }
                Action::ToClash => {
                    s.phase = Phase::ClashSubmit;
                    s.pending_submission = [Submission::None, Submission::None];
                    // v0.12: 【自分の対抗フェイズ開始時】。ターンプレイヤーの側だけ。
                    queue_fire_nested(db, s, Timing::ClashPhaseStart, &[tpu]);
                }
                Action::EndTurn => end_turn_begin(db, s),
                other => return err(format!("unexpected action in ACTION: {other:?}")),
            }
            Ok(())
        }
        Phase::ClashSubmit => {
            for (pi, act) in actions {
                let pu = *pi as usize;
                match act {
                    Action::Pass => {
                        let usable = s.players[pu].hand.iter().any(|&cid| usable_in_clash(db, s, pu, &db.action[cid as usize]));
                        if *pi == s.turn_player && usable {
                            return err("ターンプレイヤーは可能なら提出必須");
                        }
                        s.pending_submission[pu] = Submission::Pass;
                    }
                    Action::Submit { hand } => {
                        let cid = s.players[pu].hand[*hand];
                        if !usable_in_clash(db, s, pu, &db.action[cid as usize]) {
                            return err("card not usable in clash");
                        }
                        s.pending_submission[pu] = Submission::Hand(*hand);
                    }
                    other => return err(format!("unexpected action in CLASH_SUBMIT: {other:?}")),
                }
            }
            if s.pending_submission.iter().all(|x| *x != Submission::None) {
                resolve_clash(db, s);
            }
            Ok(())
        }
        Phase::Choice => apply_choice(db, s, actions),
        Phase::Rush => {
            let w = s.clash_winner.ok_or("no clash winner")?;
            let act = &actions.iter().find(|(pi, _)| *pi == w).ok_or("winner action missing")?.1;
            match act {
                Action::Stop => end_turn_begin(db, s),
                _ if s.rush_allowance <= 0 => end_turn_begin(db, s),
                Action::Rush { hand } => do_rush(db, s, w as usize, *hand),
                other => return err(format!("unexpected action in RUSH: {other:?}")),
            }
            Ok(())
        }
        Phase::TurnEndDiscard => {
            let tp = s.turn_player;
            let act = &actions.iter().find(|(pi, _)| *pi == tp).ok_or("turn player action missing")?.1;
            let Action::Discard { hand } = act else { return err("discard expected") };
            let tpu = tp as usize;
            let c = s.players[tpu].hand.remove(*hand);
            s.players[tpu].trash.push(c);
            if s.players[tpu].hand.len() <= HAND_LIMIT {
                next_turn(db, s);
            }
            Ok(())
        }
        Phase::GameOver => err("no actions expected in phase game_over"),
    }
}

fn apply_choice(db: &CardDb, s: &mut GameState, actions: &[&(u8, Action)]) -> Result<()> {
    let ch = s.pending_choices[0].clone();
    let pi = ch.player();
    let pu = pi as usize;
    let act = &actions.iter().find(|(p, _)| *p == pi).ok_or("choice player action missing")?.1;
    match ch {
        Choice::PayOrDamage { cost, amount, .. } => {
            match act {
                Action::Pay => {
                    if (s.players[pu].concerto.len() as i64) < cost {
                        return err("cannot pay");
                    }
                    s.pending_choices.remove(0);
                    queue_pay_cost(s, pu, cost);
                }
                Action::Decline => { damage_by(db, s, pu, amount, None, None); s.pending_choices.remove(0); },
                other => return err(format!("unexpected: {other:?}")),
            }
        }
        Choice::SwitchBack { options, .. } => {
            let Action::ChooseBack { back } = act else { return err("choose_back expected") };
            if !options.contains(back) {
                return err("back not in options");
            }
            s.pending_choices.remove(0);
            s.pending_effect.as_mut().unwrap().ops[0].1.back = Some(*back);
        }
        Choice::UseOptional { r, .. } => {
            match act {
                Action::Use => {
                    s.pending_choices.remove(0);
                    let sk = deref_skill(db, &r);
                    start_skill_effect(s, pu, sk, Some((r.kind, r.card)));
                }
                Action::Skip => {
                    s.pending_choices.remove(0);
                }
                other => return err(format!("unexpected: {other:?}")),
            }
        }
        Choice::RevealCount { max, .. } => {
            let Action::ChooseCount { count } = act else { return err("choose_count expected") };
            if !(0 <= *count && *count <= max) {
                return err("count out of range");
            }
            s.pending_choices.remove(0);
            s.pending_effect.as_mut().unwrap().ops[0].1.chosen = Some(*count);
        }
        Choice::DiscardForEffect { .. } => {
            let Action::Discard { hand } = act else { return err("discard expected") };
            if *hand >= s.players[pu].hand.len() {
                return err("hand index out of range");
            }
            s.pending_choices.remove(0);
            s.pending_effect.as_mut().unwrap().ops[0].1.hand_idx = Some(*hand as i64);
        }
        Choice::Discard { .. } => {
            let Action::Discard { hand } = act else { return err("discard expected") };
            if *hand >= s.players[pu].hand.len() {
                return err("hand index out of range");
            }
            s.pending_choices.remove(0);
            let c = s.players[pu].hand.remove(*hand);
            s.players[pu].trash.push(c);
        }
        Choice::Order { options, .. } => {
            let Action::Resolve { index } = act else { return err("resolve expected") };
            if !options.iter().any(|(i, _)| i == index) {
                return err("index not in options");
            }
            s.pending_choices.remove(0);
            let r = s.pending_skills.remove(*index as usize);
            begin_skill(db, s, r)?;
        }
        Choice::PayCostCard { remaining, .. } => {
            let Action::ChooseCard { zone: Zone::Concerto, index, card, .. } = act else { return err("choose_card concerto expected") };
            if s.players[pu].concerto.get(*index) != Some(card) { return err("card/index mismatch"); }
            s.pending_choices.remove(0);
            let cid = s.players[pu].concerto.remove(*index); s.players[pu].trash.push(cid);
            let left = remaining - 1;
            if left > 0 {
                let mut seen=s.players[pu].concerto.clone(); seen.sort_unstable(); seen.dedup();
                if seen.len() <= 1 { pay_cost(s, pu, left); }
                else { let mut used=Vec::new(); let options=s.players[pu].concerto.iter().enumerate().filter_map(|(i,&c)|if used.contains(&c){None}else{used.push(c);Some((i,c))}).collect();
                    s.pending_choices.insert(0, Choice::PayCostCard { player: pi, remaining: left, options }); }
            }
        }
        Choice::ZoneCard { zone_owner, zone, destination, remaining, optional, match_params, .. } => {
            if matches!(act, Action::Stop) {
                if !optional { return err("stop not allowed"); }
                s.pending_choices.remove(0); s.pending_effect.as_mut().unwrap().ops.remove(0);
            } else {
                let Action::ChooseCard { zone: az, index, card, .. } = act else { return err("choose_card expected") };
                if *az != zone || zone_ref(&s.players[zone_owner as usize], zone).get(*index) != Some(card) { return err("card/index mismatch"); }
                s.pending_choices.remove(0);
                let cid = zone_mut(&mut s.players[zone_owner as usize], zone).remove(*index);
                match destination { Destination::Trash => s.players[zone_owner as usize].trash.push(cid),
                    Destination::ActionDeck => s.players[zone_owner as usize].action_deck.push(cid),
                    Destination::Hand => s.players[zone_owner as usize].hand.push(cid),
                    Destination::Concerto => s.players[zone_owner as usize].concerto.push(cid) }
                let left = remaining - 1;
                let opts = distinct_zone_options(zone_ref(&s.players[zone_owner as usize], zone), zone, Some(&match_params), db);
                if left <= 0 || opts.is_empty() { s.pending_effect.as_mut().unwrap().ops.remove(0); }
                else { let options=opts.into_iter().filter_map(|a|match a{Action::ChooseCard{index,card,..}=>Some((index,card)),_=>None}).collect();
                    s.pending_choices.insert(0, Choice::ZoneCard { player: pi, zone_owner, zone, destination,
                    remaining: left, optional, match_params, options }); }
            }
        }
        Choice::LevelupByEffect { options, .. } => {
            let Action::ChooseCard { zone: Zone::CharaDeck, index, card, slot: Some(slot) } = act else { return err("choose_card chara_deck expected") };
            if !options.contains(&(*slot, *index, *card)) { return err("levelup option mismatch"); }
            s.pending_choices.remove(0);
            if s.players[pu].chara_deck.get(*index) != Some(card) { return err("chara index mismatch"); }
            let cid=s.players[pu].chara_deck.remove(*index); s.players[pu].slots[*slot].push(cid);
            s.slot_entered_turn[pu][*slot]=s.turn_no;
            s.pending_effect.as_mut().unwrap().ops.remove(0);
            queue_fire_nested(db, s, Timing::Enter, &[pu]);
            queue_fire_nested(db, s, Timing::Levelup, &[pu]);
        }
    }
    Ok(())
}

pub fn outcome(s: &GameState) -> Option<i8> {
    s.outcome
}

// ---------------------------------------------------------------------------
// 観測（情報集合） §10
// ---------------------------------------------------------------------------

/// `observe` が返す `opp.hand_known` の中身を**カード番号のまま**返す
/// （文献計画 便 C 段 C-1・D-077 で `agents::Greedy::determinize` からも呼ぶために切り出した）。
///
/// 並びは呼ぶ側で決める（文字列版は `card_id` 順に並べ替える）。
/// **中身は切り出す前と 1 枚も変わらない**——`hand_known` は
/// 「覗いた時点のスナップショット ∩ いまの相手の手札」である（D-023）。
pub fn known_opponent_hand_ids(s: &GameState, pi: usize) -> Vec<u16> {
    let Some(seen) = &s.peeked_opp_hand[pi] else { return vec![] };
    if seen.is_empty() {
        return vec![];
    }
    let have = &s.players[1 - pi].hand;
    let mut out: Vec<u16> = Vec::new();
    let mut done: Vec<u16> = Vec::new();
    for &cid in seen {
        if done.contains(&cid) {
            continue;
        }
        done.push(cid);
        let n_seen = seen.iter().filter(|&&c| c == cid).count();
        let n_have = have.iter().filter(|&&c| c == cid).count();
        for _ in 0..n_seen.min(n_have) {
            out.push(cid);
        }
    }
    out
}

fn known_opponent_hand(db: &CardDb, s: &GameState, pi: usize) -> Vec<String> {
    let mut out: Vec<String> = known_opponent_hand_ids(s, pi)
        .into_iter()
        .map(|cid| db.action[cid as usize].card_id.clone())
        .collect();
    out.sort();
    out
}

pub fn observe(db: &CardDb, s: &GameState, pi: u8) -> serde_json::Value {
    use serde_json::{json, Value};
    let pu = pi as usize;
    let me = &s.players[pu];
    let opp = &s.players[1 - pu];
    let aids = |v: &[u16]| Value::Array(v.iter().map(|&i| json!(db.action[i as usize].card_id)).collect());
    let cids = |v: &[u16]| Value::Array(v.iter().map(|&i| json!(db.chara[i as usize].card_id)).collect());
    let aid_opt = |v: Option<u16>| match v {
        None => Value::Null,
        Some(i) => json!(db.action[i as usize].card_id),
    };
    let opp_slots: Vec<Value> = if opp.charas_revealed {
        opp.slots.iter().map(|sl| cids(sl)).collect()
    } else {
        opp.slots.iter().map(|sl| Value::Array(vec![json!("<hidden>"); sl.len()])).collect()
    };
    let rel = |w: Option<u8>| match w {
        None => Value::Null,
        Some(w) => json!(if w != pi { 1 } else { 0 }),
    };
    let tag_map = |who: usize| Value::Object(
        s.tag_uses_this_turn[who].iter()
            .map(|(tag, count)| (tag.clone(), json!(count)))
            .collect()
    );
    let pending_choice = match s.pending_choices.first() {
        Some(c) if c.player() == pi => GameState::choice_json(db, c),
        _ => Value::Null,
    };
    json!({
        "phase": s.phase.as_str(),
        "turn_no": s.turn_no,
        "turn_player": s.turn_player,
        "me": {
            "life": me.life,
            "hand": aids(&me.hand),
            "concerto": aids(&me.concerto),
            "trash": aids(&me.trash),
            "action_area": aids(&me.action_area),
            "chara_deck": cids(&me.chara_deck),
            "slots": me.slots.iter().map(|sl| cids(sl)).collect::<Vec<_>>(),
            "deck_count": me.action_deck.len(),
        },
        "opp": {
            "life": opp.life,
            "hand_count": opp.hand.len(),
            "hand_known": known_opponent_hand(db, s, pu),
            "concerto": aids(&opp.concerto),
            "trash": aids(&opp.trash),
            "action_area": aids(&opp.action_area),
            "slots": opp_slots,
            "deck_count": opp.action_deck.len(),
        },
        "clash_cards": [
            aid_opt(s.clash_cards[pu]),
            if s.phase != Phase::ClashSubmit { aid_opt(s.clash_cards[1 - pu]) } else { Value::Null },
        ],
        "rush_allowance": if s.clash_winner == Some(pi) { s.rush_allowance } else { 0 },
        "used": {"charge": s.used_charge, "switch": s.used_switch, "levelup": s.used_levelup},
        "red_cost_up": {"me": s.red_cost_up[pu], "opp": s.red_cost_up[1 - pu]},
        "pending_red_cost_up": {"me": s.pending_red_cost_up[pu], "opp": s.pending_red_cost_up[1 - pu]},
        "rush_forbidden": {"me": s.rush_forbidden[pu], "opp": s.rush_forbidden[1 - pu]},
        "pending_rush_forbidden": {"me": s.pending_rush_forbidden[pu], "opp": s.pending_rush_forbidden[1 - pu]},
        "leader_switch_forbidden": {"me": s.leader_switch_forbidden[pu], "opp": s.leader_switch_forbidden[1 - pu]},
        "clash_winner": rel(s.clash_winner),
        "last_clash_winner": rel(s.last_clash_winner),
        "last_clash_cards": [aid_opt(s.last_clash_cards[pu]), aid_opt(s.last_clash_cards[1 - pu])],
        "last_turn_clash_winner": rel(s.last_turn_clash_winner),
        "last_turn_clash_pass": [s.last_turn_clash_pass[pu], s.last_turn_clash_pass[1 - pu]],
        "damage_taken_mod": [s.damage_taken_mod[pu], s.damage_taken_mod[1 - pu]],
        "first_damage_taken_this_turn": [s.first_damage_taken_this_turn[pu], s.first_damage_taken_this_turn[1 - pu]],
        "speed_override": [s.speed_override[pu], s.speed_override[1 - pu]],
        "heals_this_turn": [s.heals_this_turn[pu], s.heals_this_turn[1 - pu]],
        "tag_uses_this_turn": [tag_map(pu), tag_map(1 - pu)],
        "last_used_card": [aid_opt(s.last_used_card[pu]), aid_opt(s.last_used_card[1 - pu])],
        "damaged_this_turn": [s.damaged_this_turn[pu], s.damaged_this_turn[1 - pu]],
        "slot_entered_turn": [s.slot_entered_turn[pu], s.slot_entered_turn[1 - pu]],
        "variation_rush_draw": [s.variation_rush_draw[pu], s.variation_rush_draw[1 - pu]],
        "deferred_clash_damage": [
            s.deferred_clash_damage.iter().filter(|(p, _, _)| *p as usize == pu).map(|x| x.1).sum::<i64>(),
            s.deferred_clash_damage.iter().filter(|(p, _, _)| *p as usize == 1 - pu).map(|x| x.1).sum::<i64>(),
        ],
        "clash_counts": {"me": s.clash_counts[pu], "opp": s.clash_counts[1 - pu]},
        "pending_choice": pending_choice,
    })
}
