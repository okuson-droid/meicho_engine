"""観測と行動の符号化（DRL 段階 0・`DRL_PLAN.md` §3.1）。

rules_draft.md v0.10 準拠 / engine v0.1。

## 何をするか

`engine.observe(s, pi)` の出力（pi に見えてよい情報の定義そのもの）を、ニューラルネットが
読める**固定長の整数列**に直す。`GameState` は受け取らない——観測だけを入力にすることで、
覗き見の禁止（D-026）が**構造的に**守られる（`features.from_obs` と同じ方針）。

Rust 版（`rust/src/encode.rs`）は `GameState` から同じ列を直接作る（探索の葉から呼ぶため）。
**Python 版が真実源**であり、両者の一致は `tests/test_drl.py` が実対局で固定する。
符号化を変えるときは必ず両方を変え、`ENCODING_VERSION` を上げること。

## 設計（`DRL_PLAN.md` §3.1）

- 値はすべて整数（int8 に収まる）。学習側で float に直す。保存が軽い（1 決定 608 バイト）。
- **カード単位の枚数ベクトル**（手札・協奏・トラッシュ・アクションエリア）で、D-046 証拠 A の
  「集計値では漂泊者 Lv2 と秧秧 Lv2 が同じ入力になる」穴を埋める。
- **キャラ枠は最上段のカード（キャラ×レベル）を one-hot** で持つ。
- カード ID は**添字にしか使わない**（カード名を書いた特徴は作らない＝D-050 条件 1）。
  新カードは `cards.py` に入れば添字が増えるだけである（そのとき `ENCODING_VERSION` が変わる）。
- 効果プロファイル（初見カードへの汎用性）は**学習側の第 1 層の構造**として入れる
  （`experiments/drl_train.py`）。数学的には count @ P @ W1 = count @ (P @ W1) なので、
  Rust に渡す重みには畳み込んで書き出せる。Rust 側はカードの意味を知らなくてよい。

## 添字の空間

- `ACTION_IDS[i]` / `CHARA_IDS[i]`: Rust の `CardDb` と同じ順（`cards_export.cards_dict()` の順）。
- 行動の種類 `ACTION_TYPES`: `rust/src/engine.rs::Action` の並びと同じ。
"""
from __future__ import annotations

from .cards import ACTION_CARDS, CHARA_CARDS
from .features import _levels, _live_reds_from_obs

# D-062 (2026-08-31): AC-001 の削除でカード種数が 35→34 になり、
# 観測 608→596 / 行動 113→111 に変わったため 2→3 に上げた。
# 版2で保存したネット・データセットは版3と混ぜてはいけない。
# 版2のネットは `scripts/migrate_nets_d062.py` で移行できる（値は変わらない）。
#
# D-079 追記 2 (2026-09-10・便 K 段 K-1): BP01 の 68 番号＋未掲載 3 枠を登録したため
# 3→4 に上げた。
#   NA  34 → 78   （アクション 34 + BP01 41 + 未掲載の枠 3）
#   NC  18 → 45   （キャラ 18 + BP01 27）
#   OBS_DIM 596 → 1313   （= 62 + 12·NA + 7·NC）
#   ACT_DIM 111 → 226    （= 19 + 2·NA + NC + 6）
# **登録は末尾追記**なので既存 52 枚の添字は動いていない（`tests/test_bp01.py` T-K-2）。
# したがって版3のネットは「新カードの列を 0 として末尾に挿す」だけで版4になり、
# 出力は数学的に不変である（`scripts/migrate_nets_k.py`。原本は `*.enc3.bak.json` に残す）。
# 版3で保存したネット・データセットを版4と混ぜてはいけない。
ENCODING_VERSION = 4

ACTION_IDS = list(ACTION_CARDS)
CHARA_IDS = list(CHARA_CARDS)
A_INDEX = {cid: i for i, cid in enumerate(ACTION_IDS)}
C_INDEX = {cid: i for i, cid in enumerate(CHARA_IDS)}
NA = len(ACTION_IDS)
NC = len(CHARA_IDS)

PHASES = ("setup_chara", "mulligan", "action", "clash_submit", "choice", "rush",
          "turn_end_discard", "game_over")
CHOICE_KINDS = ("pay_or_damage", "switch_back", "use_optional", "reveal_count",
                "discard", "discard_for_effect", "order")
# rust/src/engine.rs::Action の並び
ACTION_TYPES = ("setup", "mulligan", "charge", "switch", "levelup", "to_clash", "end_turn",
                "submit", "pass", "pay", "decline", "choose_back", "use", "skip",
                "choose_count", "discard", "resolve", "stop", "rush")
T_INDEX = {t: i for i, t in enumerate(ACTION_TYPES)}

N_SCALAR = 62
OBS_DIM = N_SCALAR + 12 * NA + 7 * NC
# 行動の符号（11 個の小さな整数）:
#   [種類, アクションカード, キャラカード, 枠, バック, 数, マリガンで捨てる札 ×5（カード添字・無ければ -1）]
# マリガンは手札の任意部分集合なので、捨てる札の**カードの多重集合**を持たないと区別できない
# （枚数だけでは 32 通りの部分集合のうち同じ枚数のものが同じ入力になる）。
ACT_CODE_LEN = 11
# 展開後の行動特徴の次元:
#   種類 one-hot + カード one-hot + キャラ one-hot + 枠(3) + バック(2) + 数(1) + 捨てる札の枚数ベクトル(NA)
ACT_DIM = len(ACTION_TYPES) + NA + NC + 3 + 2 + 1 + NA

_CLIP = 127


def _c(x) -> int:
    x = int(x)
    return _CLIP if x > _CLIP else (-_CLIP if x < -_CLIP else x)


def _counts(ids, index, n) -> list:
    v = [0] * n
    for cid in ids:
        if cid == "<hidden>" or cid is None:
            continue
        v[index[cid]] += 1
    return v


def _onehot(cid, index, n) -> list:
    v = [0] * n
    if cid is not None and cid != "<hidden>":
        v[index[cid]] = 1
    return v


def _slot_onehot(stack) -> list:
    """枠の最上段（現在レベル）のキャラカード one-hot。裏向き・空ならゼロ。"""
    if not stack:
        return [0] * NC
    top = stack[-1]
    return _onehot(top, C_INDEX, NC)


def encode_obs(ob: dict) -> list:
    """観測 → 長さ OBS_DIM の整数列。"""
    me, opp = ob["me"], ob["opp"]
    ph = [0] * len(PHASES)
    ph[PHASES.index(ob["phase"])] = 1
    used = ob["used"]
    ck = [0, 0, 0]
    ck[0 if ob["clash_winner"] is None else 1 + ob["clash_winner"]] = 1
    lk = [0, 0, 0]
    lk[0 if ob["last_clash_winner"] is None else 1 + ob["last_clash_winner"]] = 1
    choice = [0] * len(CHOICE_KINDS)
    pc = ob.get("pending_choice")
    if pc is not None:
        choice[CHOICE_KINDS.index(pc["kind"])] = 1
    cc_me, cc_op = ob["clash_counts"]["me"], ob["clash_counts"]["opp"]
    scal = [
        _c(me["life"]), _c(opp["life"]),
        len(me["concerto"]), len(opp["concerto"]),
        len(me["hand"]), opp["hand_count"],
        _live_reds_from_obs(ob),
        _levels(me["slots"]), _levels(opp["slots"]),
        _c(me["deck_count"]), _c(opp["deck_count"]),
        _c(len(me["trash"])), _c(len(opp["trash"])),
        _c(ob["turn_no"]),
        1 if ob["turn_player"] == ob["_pi"] else 0,   # "_pi" は呼び出し側が足す（下記 encode）
    ]
    scal += ph
    scal += [int(used["charge"]), int(used["switch"]), int(used["levelup"])]
    scal += [_c(ob["rush_allowance"])]
    scal += [int(ob["red_cost_up"]["me"]), int(ob["red_cost_up"]["opp"]),
             int(ob["pending_red_cost_up"]["me"]), int(ob["pending_red_cost_up"]["opp"]),
             int(ob["rush_forbidden"]["me"]), int(ob["rush_forbidden"]["opp"]),
             int(ob["pending_rush_forbidden"]["me"]), int(ob["pending_rush_forbidden"]["opp"]),
             int(ob["leader_switch_forbidden"]["me"]), int(ob["leader_switch_forbidden"]["opp"])]
    scal += ck + lk
    scal += [_c(x) for x in cc_me] + [_c(x) for x in cc_op]
    scal += choice
    scal += [len(me["chara_deck"]), _c(len(me["action_area"])), _c(len(opp["action_area"])),
             len(opp["hand_known"])]
    assert len(scal) == N_SCALAR, len(scal)

    out = scal
    out += _counts(me["hand"], A_INDEX, NA)
    out += _counts(me["concerto"], A_INDEX, NA)
    out += _counts(me["trash"], A_INDEX, NA)
    out += _counts(me["action_area"], A_INDEX, NA)
    out += _counts(opp["hand_known"], A_INDEX, NA)
    out += _counts(opp["concerto"], A_INDEX, NA)
    out += _counts(opp["trash"], A_INDEX, NA)
    out += _counts(opp["action_area"], A_INDEX, NA)
    out += _onehot(ob["clash_cards"][0], A_INDEX, NA)
    out += _onehot(ob["clash_cards"][1], A_INDEX, NA)
    out += _onehot(ob["last_clash_cards"][0], A_INDEX, NA)
    out += _onehot(ob["last_clash_cards"][1], A_INDEX, NA)
    for sl in me["slots"]:
        out += _slot_onehot(sl)
    for sl in opp["slots"]:
        out += _slot_onehot(sl)
    out += _counts(me["chara_deck"], C_INDEX, NC)
    assert len(out) == OBS_DIM, (len(out), OBS_DIM)
    return out


def encode(ob: dict, pi: int) -> list:
    """`observe(s, pi)` の出力と席番号から符号化する（`turn_player` の相対化に pi が要る）。"""
    ob = dict(ob)
    ob["_pi"] = pi
    return encode_obs(ob)


def _lv0_chara_index(name: str) -> int:
    for i, cid in enumerate(CHARA_IDS):
        c = CHARA_CARDS[cid]
        if c.name == name and c.level == 0:
            return i
    return -1


def action_code(ob: dict, a: dict) -> list:
    """行動 → ACT_CODE_LEN 個の整数 [種類, アクションカード添字, キャラカード添字, 枠, バック, 数, 捨て札×5]。
    無いものは -1。`ob["me"]["hand"]` で手札添字をカードに直す。"""
    t = T_INDEX[a["type"]]
    card = chara = slot = back = count = -1
    mull = [-1] * 5
    typ = a["type"]
    if typ in ("charge", "submit", "rush", "discard"):
        card = A_INDEX[ob["me"]["hand"][a["hand"]]]
    elif typ == "levelup":
        chara = C_INDEX[a["card"]]
        slot = a["slot"]
    elif typ == "switch":
        back = a["back"]
    elif typ == "choose_back":
        back = a["back"]
    elif typ == "choose_count":
        count = a["count"]
    elif typ == "mulligan":
        count = len(a["cards"])
        for k, hi in enumerate(a["cards"][:5]):
            mull[k] = A_INDEX[ob["me"]["hand"][hi]]
    elif typ == "resolve":
        count = a["index"]
    elif typ == "setup":
        chara = _lv0_chara_index(a["leader"])
    return [t, card, chara, slot, back, count] + mull


def expand_action(code) -> list:
    """符号 → 長さ ACT_DIM の float 列（学習側と Rust 側で同じ展開）。"""
    t, card, chara, slot, back, count = code[:6]
    mull = code[6:11]
    v = [0.0] * ACT_DIM
    v[t] = 1.0
    o = len(ACTION_TYPES)
    if card >= 0:
        v[o + card] = 1.0
    o += NA
    if chara >= 0:
        v[o + chara] = 1.0
    o += NC
    if 0 <= slot <= 2:
        v[o + slot] = 1.0
    o += 3
    if back in (1, 2):
        v[o + back - 1] = 1.0
    o += 2
    v[o] = (count / 8.0) if count >= 0 else 0.0
    o += 1
    for m in mull:
        if m >= 0:
            v[o + m] += 1.0
    return v
