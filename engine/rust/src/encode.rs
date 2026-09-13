//! 観測と行動の符号化（`meicho/encode.py` の写し・DRL 段階 0）。
//!
//! **真実源は Python 版**（`meicho/encode.py`）。ここは `GameState` から同じ整数列を直接作る
//! （探索の葉から `observe` の JSON を組まずに呼ぶため）。読むのは公開情報と自席の私有情報だけで、
//! 相手の手札の中身・両デッキの順序には触れない（D-026）。一致は `tests/test_drl.py` が固定する。
//! 符号化を変えるときは Python 側と同時に変え、`ENCODING_VERSION` を上げること。

use crate::agents::live_reds;
use crate::cards::CardDb;
use crate::engine::Action;
use crate::state::{Choice, GameState, Phase};

// D-062: AC-001 削除でカード種数が変わった（2→3）。
// D-079 追記 2（便 K 段 K-1）: BP01 の 68 番号＋未掲載 3 枠を登録して 3→4。
// **次元そのものは `CardDb` の大きさから導いている**（`obs_dim` / `act_dim`）ので、
// カードが増えてもこのファイルの構造は変わらない。上げるのは版の札だけである。
pub const ENCODING_VERSION: i64 = 4;
pub const N_SCALAR: usize = 62;
pub const N_ACTION_TYPES: usize = 19;
pub const ACT_CODE_LEN: usize = 11;

const CLIP: i64 = 127;

fn c(x: i64) -> i8 {
    x.clamp(-CLIP, CLIP) as i8
}

pub fn obs_dim(db: &CardDb) -> usize {
    N_SCALAR + 12 * db.action.len() + 7 * db.chara.len()
}

pub fn act_dim(db: &CardDb) -> usize {
    N_ACTION_TYPES + db.action.len() + db.chara.len() + 3 + 2 + 1 + db.action.len()
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

/// `encode.encode(observe(s, pi), pi)` と同じ列。
pub fn encode_state(db: &CardDb, s: &GameState, pi: u8) -> Vec<i8> {
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
    if let Some(ch) = s.pending_choices.first() {
        if ch.player() == pi {
            chk[choice_index(ch)] = 1;
        }
    }
    out.extend_from_slice(&chk);
    out.push(c(me.chara_deck.len() as i64));
    out.push(c(me.action_area.len() as i64));
    out.push(c(opp.action_area.len() as i64));
    out.push(c(known.len() as i64));
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
    let t: i64 = match a {
        Action::Setup { leader } => {
            chara = lv0_chara_index(db, leader);
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
    };
    [t, card, chara, slot, back, count, mull[0], mull[1], mull[2], mull[3], mull[4]]
}

/// `encode.expand_action(code)` と同じ float 列。
pub fn expand_action(db: &CardDb, code: &[i64; ACT_CODE_LEN]) -> Vec<f32> {
    let na = db.action.len();
    let nc = db.chara.len();
    let mut v = vec![0f32; act_dim(db)];
    let [t, card, chara, slot, back, count, m0, m1, m2, m3, m4] = *code;
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
