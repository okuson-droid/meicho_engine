//! 観測と行動の符号化（`meicho/encode.py` の写し・DRL 段階 0）。
//!
//! **真実源は Python 版**（`meicho/encode.py`）。ここは `GameState` から同じ整数列を直接作る
//! （探索の葉から `observe` の JSON を組まずに呼ぶため）。読むのは公開情報と自席の私有情報だけで、
//! 相手の手札の中身・両デッキの順序には触れない（D-026）。一致は `tests/test_drl.py` が固定する。
//! 符号化を変えるときは Python 側と同時に変え、`ENCODING_VERSION` を上げること。

use crate::agents::live_reds;
use crate::cards::CardDb;
use crate::engine::Action;
use crate::state::{Choice, GameState, Phase, Zone};

// D-062: AC-001 削除でカード種数が変わった（2→3）。
// D-079 追記 2（便 K 段 K-1）: BP01 の 68 番号＋未掲載 3 枠を登録して 3→4。
// **次元そのものは `CardDb` の大きさから導いている**（`obs_dim` / `act_dim`）ので、
// カードが増えてもこのファイルの構造は変わらない。上げるのは版の札だけである。
// D-124（段階1C-c）: 5→6。v5 の列は動かさず、末尾に信念の要約（N_BELIEF）と統一した hand_known（NA）を足した。
pub const ENCODING_VERSION: i64 = 6;
pub const N_BELIEF: usize = 20;
pub const LEGACY_N_SCALAR: usize = 62;
pub const N_SCALAR: usize = 100;
pub const N_ACTION_TYPES: usize = 20;
pub const ACT_CODE_LEN: usize = 13;

const CLIP: i64 = 127;

fn c(x: i64) -> i8 {
    x.clamp(-CLIP, CLIP) as i8
}

pub fn obs_dim(db: &CardDb) -> usize {
    let mut tags: Vec<&str> = db.action.iter().flat_map(|c| c.tags.iter().map(String::as_str)).collect();
    tags.sort(); tags.dedup();
    N_SCALAR + 14 * db.action.len() + 13 * db.chara.len() + 2 * tags.len() + N_BELIEF + db.action.len()
}

pub fn act_dim(db: &CardDb) -> usize {
    N_ACTION_TYPES + db.action.len() + 3 * db.chara.len() + 3 + 2 + 1 + db.action.len()
}

fn phase_index(p: Phase) -> usize {
    match p {
        Phase::SetupChara => 0,
        Phase::Mulligan => 1,
        Phase::Action => 2,
        Phase::ClashSubmit => 3,
        Phase::Choice => 4,
        Phase::Rush => 5,
        Phase::TurnEndDiscard => 6,
        Phase::GameOver => 7,
    }
}

fn choice_index(ch: &Choice) -> usize {
    match ch {
        Choice::PayOrDamage { .. } => 0,
        Choice::SwitchBack { .. } => 1,
        Choice::UseOptional { .. } => 2,
        Choice::RevealCount { .. } => 3,
        Choice::Discard { .. } => 4,
        Choice::DiscardForEffect { .. } => 5,
        Choice::Order { .. } => 6,
        Choice::PayCostCard { .. } => 7,
        Choice::ZoneCard { .. } => 8,
        Choice::LevelupByEffect { .. } => 9,
    }
}

fn levels(db: &CardDb, slots: &[Vec<u16>; 3]) -> i64 {
    slots.iter().filter_map(|sl| sl.last()).map(|&c| db.chara[c as usize].level).sum()
}

fn push_counts(out: &mut Vec<i8>, ids: &[u16], n: usize) {
    let start = out.len();
    out.resize(start + n, 0);
    for &cid in ids {
        out[start + cid as usize] += 1;
    }
}

fn push_onehot(out: &mut Vec<i8>, id: Option<u16>, n: usize) {
    let start = out.len();
    out.resize(start + n, 0);
    if let Some(cid) = id {
        out[start + cid as usize] = 1;
    }
}

fn push_slot(out: &mut Vec<i8>, stack: &[u16], visible: bool, n: usize) {
    if visible {
        push_onehot(out, stack.last().copied(), n);
    } else {
        push_onehot(out, None, n);
    }
}

/// `encode.encode(observe(s, pi), pi)` と同じ列（相手のデッキ表の想定なし＝信念の要約の多くが 0）。
pub fn encode_state(db: &CardDb, s: &GameState, pi: u8) -> Vec<i8> {
    encode_state_with(db, s, pi, None)
}

/// 相手の手札について**確かに知っている札**（統一版・D-122）。`engine::known_opponent_hand_unified` の ID 版。
/// 並びは `known_opp_hand` のまま（枚数ベクトルと W にしか使わないので並びは効かない）。
fn known_unified_ids(s: &GameState, pu: usize) -> Vec<u16> {
    let mut have: Vec<u16> = s.players[1 - pu].hand.clone();
    let mut out: Vec<u16> = Vec::new();
    for &cid in &s.known_opp_hand[pu] {
        if let Some(p) = have.iter().position(|&c| c == cid) {
            have.remove(p);
            out.push(cid);
        }
    }
    out
}

/// 信念の要約（PT-3・D-124）。`meicho/encode.py::_belief` の写し。並びと意味はそちらの docstring。
fn push_belief(db: &CardDb, s: &GameState, pu: usize, opp_deck: Option<&[u16]>, known: &[u16], out: &mut Vec<i8>) {
    let opp = &s.players[1 - pu];
    let n_hand = opp.hand.len();
    let mut v = [0i8; N_BELIEF];
    v[1] = c(known.len() as i64);
    v[2] = c(n_hand.saturating_sub(known.len()) as i64);
    if let Some(deck) = opp_deck {
        v[0] = 1;
        let mut pool: Vec<u16> = deck.to_vec();
        for cid in opp.concerto.iter().chain(&opp.trash).chain(&opp.action_area) {
            if let Some(pos) = pool.iter().position(|x| x == cid) {
                pool.remove(pos);
            }
        }
        match crate::worlds::world_count_w(db, &pool, n_hand, known) {
            None => {
                v[3] = -1;
                v[4] = 1;
            }
            Some(w) => {
                // floor(2·log2 W) を整数だけで: W² のビット長 − 1（Python の `_pow2_floor_x2`）
                v[3] = if w >= 1 { c((128 - ((w as u128) * (w as u128)).leading_zeros()) as i64 - 1) } else { -1 };
                v[5] = if w == 1 { 1 } else { 0 };
                let left = crate::worlds::remove_multiset(&pool, known);
                let k = n_hand - known.len();
                let color = |cid: u16| -> usize {
                    match db.action[cid as usize].color { crate::cards::Color::Red => 0, crate::cards::Color::Green => 1, crate::cards::Color::Blue => 2 }
                };
                let band = |cid: u16| -> usize { crate::buckets::cost_band(db.action[cid as usize].cost) };
                let mut bounds = |key: &dyn Fn(u16) -> usize, n: usize, at: usize| {
                    let mut kn = vec![0usize; n];
                    let mut lf = vec![0usize; n];
                    for &x in known { kn[key(x)] += 1; }
                    for &x in &left { lf[key(x)] += 1; }
                    for g in 0..n {
                        let other = left.len() - lf[g];
                        v[at + 2 * g] = c((kn[g] + k.saturating_sub(other)) as i64);
                        v[at + 2 * g + 1] = c((kn[g] + k.min(lf[g])) as i64);
                    }
                };
                bounds(&color, 3, 6);
                bounds(&band, 4, 12);
            }
        }
    }
    out.extend_from_slice(&v);
}

/// v6: `encode.encode(observe(s, pi), pi, opp_decklist)` と同じ列。`opp_deck` は相手のデッキ表の想定（D-124）。
pub fn encode_state_with(db: &CardDb, s: &GameState, pi: u8, opp_deck: Option<&[u16]>) -> Vec<i8> {
    let pu = pi as usize;
    let me = &s.players[pu];
    let opp = &s.players[1 - pu];
    let na = db.action.len();
    let nc = db.chara.len();
    let mut out: Vec<i8> = Vec::with_capacity(obs_dim(db));

    // --- スカラ（62） ---
    // 相手の既知手札（スキャン）: peeked と現在の手札の多重集合の積（engine::known_opponent_hand と同じ）
    let mut known: Vec<u16> = Vec::new();
    if let Some(seen) = &s.peeked_opp_hand[pu] {
        let mut done: Vec<u16> = Vec::new();
        for &cid in seen {
            if done.contains(&cid) {
                continue;
            }
            done.push(cid);
            let n_seen = seen.iter().filter(|&&x| x == cid).count();
            let n_have = opp.hand.iter().filter(|&&x| x == cid).count();
            for _ in 0..n_seen.min(n_have) {
                known.push(cid);
            }
        }
    }
    out.push(c(me.life));
    out.push(c(opp.life));
    out.push(c(me.concerto.len() as i64));
    out.push(c(opp.concerto.len() as i64));
    out.push(c(me.hand.len() as i64));
    out.push(c(opp.hand.len() as i64));
    out.push(c(live_reds(db, s, pu, None)));
    out.push(c(levels(db, &me.slots)));
    out.push(c(if opp.charas_revealed { levels(db, &opp.slots) } else { 0 }));
    out.push(c(me.action_deck.len() as i64));
    out.push(c(opp.action_deck.len() as i64));
    out.push(c(me.trash.len() as i64));
    out.push(c(opp.trash.len() as i64));
    out.push(c(s.turn_no));
    out.push(if s.turn_player == pi { 1 } else { 0 });
    let mut ph = [0i8; 8];
    ph[phase_index(s.phase)] = 1;
    out.extend_from_slice(&ph);
    out.push(s.used_charge as i8);
    out.push(s.used_switch as i8);
    out.push(s.used_levelup as i8);
    out.push(c(if s.clash_winner == Some(pi) { s.rush_allowance } else { 0 }));
    out.push(s.red_cost_up[pu] as i8);
    out.push(s.red_cost_up[1 - pu] as i8);
    out.push(s.pending_red_cost_up[pu] as i8);
    out.push(s.pending_red_cost_up[1 - pu] as i8);
    out.push(s.rush_forbidden[pu] as i8);
    out.push(s.rush_forbidden[1 - pu] as i8);
    out.push(s.pending_rush_forbidden[pu] as i8);
    out.push(s.pending_rush_forbidden[1 - pu] as i8);
    out.push(s.leader_switch_forbidden[pu] as i8);
    out.push(s.leader_switch_forbidden[1 - pu] as i8);
    let rel = |w: Option<u8>| -> [i8; 3] {
        match w {
            None => [1, 0, 0],
            Some(x) if x == pi => [0, 1, 0],
            Some(_) => [0, 0, 1],
        }
    };
    out.extend_from_slice(&rel(s.clash_winner));
    out.extend_from_slice(&rel(s.last_clash_winner));
    for &x in &s.clash_counts[pu] {
        out.push(c(x));
    }
    for &x in &s.clash_counts[1 - pu] {
        out.push(c(x));
    }
    let mut chk = [0i8; 7];
    let mut chk5 = [0i8; 3];
    if let Some(ch) = s.pending_choices.first() {
        if ch.player() == pi {
            let i=choice_index(ch); if i < 7 { chk[i] = 1; } else { chk5[i-7] = 1; }
        }
    }
    out.extend_from_slice(&chk);
    out.push(c(me.chara_deck.len() as i64));
    out.push(c(me.action_area.len() as i64));
    out.push(c(opp.action_area.len() as i64));
    out.push(c(known.len() as i64));
    debug_assert_eq!(out.len(), LEGACY_N_SCALAR);
    out.extend_from_slice(&chk5);
    out.extend_from_slice(&rel(s.last_turn_clash_winner));
    out.push(s.last_turn_clash_pass[pu] as i8); out.push(s.last_turn_clash_pass[1-pu] as i8);
    out.push(c(s.damage_taken_mod[pu])); out.push(c(s.damage_taken_mod[1-pu]));
    out.push(s.first_damage_taken_this_turn[pu] as i8); out.push(s.first_damage_taken_this_turn[1-pu] as i8);
    out.push(c(s.speed_override[pu].unwrap_or(0))); out.push(c(s.speed_override[1-pu].unwrap_or(0)));
    out.push(c(s.heals_this_turn[pu])); out.push(c(s.heals_this_turn[1-pu]));
    out.push(s.damaged_this_turn[pu] as i8); out.push(s.damaged_this_turn[1-pu] as i8);
    out.push(c(s.variation_rush_draw[pu])); out.push(c(s.variation_rush_draw[1-pu]));
    for who in [pu,1-pu] { for &t in &s.slot_entered_turn[who] { out.push(c(if t==0 {0} else {s.turn_no-t+1})); } }
    for who in [pu,1-pu] { out.push(c(s.deferred_clash_damage.iter().filter(|(p,_,_)| *p as usize==who).map(|x|x.1).sum())); }
    let mut detail=[0i8;10];
    if let Some(ch)=s.pending_choices.first() { if ch.player()==pi { match ch {
        Choice::PayOrDamage{cost,amount,..}=>{detail[0]=c(*cost);detail[1]=c(*amount)},
        Choice::RevealCount{max,..}=>detail[2]=c(*max),
        Choice::SwitchBack{options,..}=>detail[5]=c(options.len() as i64),
        Choice::Order{options,..}=>detail[5]=c(options.len() as i64),
        Choice::DiscardForEffect{remaining,..}=>detail[3]=c(*remaining),
        Choice::PayCostCard{remaining,options,..}=>{detail[3]=c(*remaining);detail[5]=c(options.len() as i64)},
        Choice::ZoneCard{zone_owner,zone,destination,remaining,optional,options,..}=>{detail[3]=c(*remaining);detail[4]=*optional as i8;detail[5]=c((options.len()+usize::from(*optional)) as i64);detail[6]=(*zone_owner!=pi) as i8;detail[7]=*zone as i8+1;detail[8]=*destination as i8+1},
        Choice::LevelupByEffect{options,..}=>detail[5]=c(options.len() as i64),
        _=>{}
    }}}
    out.extend_from_slice(&detail);
    debug_assert_eq!(out.len(), N_SCALAR);

    // --- 枚数ベクトル（8 × NA） ---
    push_counts(&mut out, &me.hand, na);
    push_counts(&mut out, &me.concerto, na);
    push_counts(&mut out, &me.trash, na);
    push_counts(&mut out, &me.action_area, na);
    push_counts(&mut out, &known, na);
    push_counts(&mut out, &opp.concerto, na);
    push_counts(&mut out, &opp.trash, na);
    push_counts(&mut out, &opp.action_area, na);
    // --- 対抗カード（4 × NA） ---
    push_onehot(&mut out, s.clash_cards[pu], na);
    push_onehot(&mut out, if s.phase != Phase::ClashSubmit { s.clash_cards[1 - pu] } else { None }, na);
    push_onehot(&mut out, s.last_clash_cards[pu], na);
    push_onehot(&mut out, s.last_clash_cards[1 - pu], na);
    // --- キャラ枠（6 × NC）: 自分は常に見える。相手は公開後のみ ---
    for sl in &me.slots {
        push_slot(&mut out, sl, true, nc);
    }
    for sl in &opp.slots {
        push_slot(&mut out, sl, opp.charas_revealed, nc);
    }
    // --- 自分のキャラデッキ（NC） ---
    push_counts(&mut out, &me.chara_deck, nc);
    for stack in &me.slots { push_counts(&mut out, &stack[..stack.len().saturating_sub(1)], nc); }
    for stack in &opp.slots {
        if opp.charas_revealed { push_counts(&mut out, &stack[..stack.len().saturating_sub(1)], nc); }
        else { push_counts(&mut out, &[], nc); }
    }
    let mut tags: Vec<&str> = db.action.iter().flat_map(|x| x.tags.iter().map(String::as_str)).collect(); tags.sort(); tags.dedup();
    for who in [pu,1-pu] { for tag in &tags { out.push(c(s.tag_uses_this_turn[who].iter().find(|(t,_)|t==tag).map_or(0,|x|x.1))); } }
    push_onehot(&mut out, s.last_used_card[pu], na); push_onehot(&mut out, s.last_used_card[1-pu], na);
    // --- v6（D-124）: 信念の要約と、統一した hand_known の枚数ベクトル ---
    let known_u = known_unified_ids(s, pu);
    push_belief(db, s, pu, opp_deck, &known_u, &mut out);
    push_counts(&mut out, &known_u, na);
    debug_assert_eq!(out.len(), obs_dim(db));
    out
}

fn lv0_chara_index(db: &CardDb, name: &str) -> i64 {
    for (i, ch) in db.chara.iter().enumerate() {
        if ch.name == name && ch.level == 0 {
            return i as i64;
        }
    }
    -1
}

/// `encode.action_code(ob, a)` と同じ ACT_CODE_LEN 整数。
pub fn action_code(db: &CardDb, s: &GameState, pi: u8, a: &Action) -> [i64; ACT_CODE_LEN] {
    let hand = &s.players[pi as usize].hand;
    let (mut card, mut chara, mut slot, mut back, mut count) = (-1i64, -1i64, -1i64, -1i64, -1i64);
    let mut mull = [-1i64; 5];
    let mut setup_backs=[-1i64;2];
    let t: i64 = match a {
        Action::Setup { leader, backs } => {
            chara = lv0_chara_index(db, leader);
            for (i,n) in backs.iter().take(2).enumerate(){setup_backs[i]=lv0_chara_index(db,n);}
            0
        }
        Action::Mulligan { cards } => {
            count = cards.len() as i64;
            for (k, &hi) in cards.iter().take(5).enumerate() {
                mull[k] = hand[hi] as i64;
            }
            1
        }
        Action::Charge { hand: h } => {
            card = hand[*h] as i64;
            2
        }
        Action::Switch { back: b } => {
            back = *b as i64;
            3
        }
        Action::Levelup { slot: sl, card: cd } => {
            chara = *cd as i64;
            slot = *sl as i64;
            4
        }
        Action::ToClash => 5,
        Action::EndTurn => 6,
        Action::Submit { hand: h } => {
            card = hand[*h] as i64;
            7
        }
        Action::Pass => 8,
        Action::Pay => 9,
        Action::Decline => 10,
        Action::ChooseBack { back: b } => {
            back = *b;
            11
        }
        Action::Use => 12,
        Action::Skip => 13,
        Action::ChooseCount { count: n } => {
            count = *n;
            14
        }
        Action::Discard { hand: h } => {
            card = hand[*h] as i64;
            15
        }
        Action::Resolve { index } => {
            count = *index;
            16
        }
        Action::Stop => 17,
        Action::Rush { hand: h } => {
            card = hand[*h] as i64;
            18
        }
        Action::ChooseCard { zone, card: cd, slot: sl, .. } => {
            if *zone==Zone::CharaDeck { chara=*cd as i64; } else { card=*cd as i64; }
            slot=sl.map(|x|x as i64).unwrap_or(-1); 19
        }
    };
    [t, card, chara, slot, back, count, mull[0], mull[1], mull[2], mull[3], mull[4], setup_backs[0], setup_backs[1]]
}

/// `encode.expand_action(code)` と同じ float 列。
pub fn expand_action(db: &CardDb, code: &[i64; ACT_CODE_LEN]) -> Vec<f32> {
    let na = db.action.len();
    let nc = db.chara.len();
    let mut v = vec![0f32; act_dim(db)];
    let [t, card, chara, slot, back, count, m0, m1, m2, m3, m4, b0, b1] = *code;
    v[t as usize] = 1.0;
    let mut o = N_ACTION_TYPES;
    if card >= 0 {
        v[o + card as usize] = 1.0;
    }
    o += na;
    if chara >= 0 {
        v[o + chara as usize] = 1.0;
    }
    o += nc;
    for b in [b0,b1] { if b>=0 {v[o+b as usize]=1.0;} o+=nc; }
    if (0..=2).contains(&slot) {
        v[o + slot as usize] = 1.0;
    }
    o += 3;
    if back == 1 || back == 2 {
        v[o + (back - 1) as usize] = 1.0;
    }
    o += 2;
    v[o] = if count >= 0 { count as f32 / 8.0 } else { 0.0 };
    o += 1;
    for m in [m0, m1, m2, m3, m4] {
        if m >= 0 {
            v[o + m as usize] += 1.0;
        }
    }
    v
}
