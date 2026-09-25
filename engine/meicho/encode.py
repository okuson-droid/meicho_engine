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
#
# D-124（2026-09-22・段階1C-c）: 5→6。v5 の列は**1 つも動かさず**、末尾に 2 つのブロックを足した。
#   信念の要約 N_BELIEF=20（PT-3・`_belief`）／統一した `hand_known` の枚数ベクトル NA（D-122）。
#   v5 の `hand_known_scan` の列（スカラ 1 と枚数ベクトル）は現 champion のネットが読むので残す。
#   OBS_DIM = v5 + 20 + NA。v5 のネットは新しい列の重みを 0 で足せば出力が数学的に不変
#   （`scripts/migrate_nets_v6.py`）。v5 で保存したネット・データセットを v6 と混ぜてはいけない。
ENCODING_VERSION = 6

ACTION_IDS = list(ACTION_CARDS)
CHARA_IDS = list(CHARA_CARDS)
A_INDEX = {cid: i for i, cid in enumerate(ACTION_IDS)}
C_INDEX = {cid: i for i, cid in enumerate(CHARA_IDS)}
NA = len(ACTION_IDS)
NC = len(CHARA_IDS)

PHASES = ("setup_chara", "mulligan", "action", "clash_submit", "choice", "rush",
          "turn_end_discard", "game_over")
CHOICE_KINDS = ("pay_or_damage", "switch_back", "use_optional", "reveal_count",
                "discard", "discard_for_effect", "order", "pay_cost_card",
                "zone_card", "levelup_by_effect")
# rust/src/engine.rs::Action の並び
ACTION_TYPES = ("setup", "mulligan", "charge", "switch", "levelup", "to_clash", "end_turn",
                "submit", "pass", "pay", "decline", "choose_back", "use", "skip",
                "choose_count", "discard", "resolve", "stop", "rush", "choose_card")
T_INDEX = {t: i for i, t in enumerate(ACTION_TYPES)}

LEGACY_N_SCALAR = 62
# v5 はv4の62スカラーを先頭に保ち、その直後へ公開状態の固定長要約を足す。
# タグとカード・キャラのベクトルはさらに後ろへ置く。
ACTION_TAGS = tuple(sorted({tag for c in ACTION_CARDS.values() for tag in c.tags}))
N_PUBLIC_SCALAR = 35
N_SCALAR = LEGACY_N_SCALAR + 3 + N_PUBLIC_SCALAR
OBS_DIM_V5 = N_SCALAR + (12 + 2) * NA + (7 + 6) * NC + 2 * len(ACTION_TAGS)
# v6（D-124）: 信念の要約（PT-3）と統一した hand_known（D-122）を末尾に足す。
N_BELIEF = 20
OBS_DIM = OBS_DIM_V5 + N_BELIEF + NA
# 行動の符号（11 個の小さな整数）:
#   [種類, アクションカード, キャラカード, 枠, バック, 数, マリガンで捨てる札 ×5（カード添字・無ければ -1）]
# マリガンは手札の任意部分集合なので、捨てる札の**カードの多重集合**を持たないと区別できない
# （枚数だけでは 32 通りの部分集合のうち同じ枚数のものが同じ入力になる）。
ACT_CODE_LEN = 13
# 展開後の行動特徴の次元:
#   種類 one-hot + カード one-hot + キャラ one-hot + 枠(3) + バック(2) + 数(1) + 捨てる札の枚数ベクトル(NA)
ACT_DIM = len(ACTION_TYPES) + NA + 3 * NC + 3 + 2 + 1 + NA

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
    # v4の7種は元の位置に置き、新設3種は公開状態ブロックの先頭へ追記する。
    choice = [0] * 7
    choice_v5 = [0] * 3
    pc = ob.get("pending_choice")
    if pc is not None:
        ci = CHOICE_KINDS.index(pc["kind"])
        (choice if ci < 7 else choice_v5)[ci if ci < 7 else ci - 7] = 1
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
             len(opp["hand_known_scan"])]   # D-121: v5 はスキャン・B-9 のぶんだけ（旧 hand_known）
    assert len(scal) == LEGACY_N_SCALAR, len(scal)

    def rel_turn(x):
        return 0 if x in (None, 0) else _c(ob["turn_no"] - x + 1)

    lw = ob["last_turn_clash_winner"]
    public = choice_v5 + [
        1 if lw is None else 0, 1 if lw == 0 else 0, 1 if lw == 1 else 0,
        *map(int, ob["last_turn_clash_pass"]),
        *map(_c, ob["damage_taken_mod"]),
        *map(int, ob["first_damage_taken_this_turn"]),
        *[_c(x or 0) for x in ob["speed_override"]],
        *map(_c, ob["heals_this_turn"]),
        *map(int, ob["damaged_this_turn"]),
        *map(_c, ob["variation_rush_draw"]),
        *[rel_turn(x) for row in ob["slot_entered_turn"] for x in row],
        *map(_c, ob["deferred_clash_damage"]),
    ]
    # 現在の選択に必要な公開条件だけを固定長で要約する。
    zones = ("concerto", "trash", "chara_deck")
    dests = ("trash", "action_deck", "hand", "concerto")
    public += [
        _c((pc or {}).get("cost", 0)), _c((pc or {}).get("amount", 0)),
        _c((pc or {}).get("max", 0)), _c((pc or {}).get("remaining", 0)),
        int((pc or {}).get("optional", False)), _c(len((pc or {}).get("options", ()))),
        int((pc or {}).get("zone_owner", ob["_pi"]) != ob["_pi"]),
        0 if (pc or {}).get("zone") not in zones else zones.index(pc["zone"]) + 1,
        0 if (pc or {}).get("destination") not in dests else dests.index(pc["destination"]) + 1,
        _c((pc or {}).get("count", 0)),
    ]
    assert len(public) == 3 + N_PUBLIC_SCALAR, len(public)
    scal += public
    assert len(scal) == N_SCALAR, len(scal)

    out = scal
    out += _counts(me["hand"], A_INDEX, NA)
    out += _counts(me["concerto"], A_INDEX, NA)
    out += _counts(me["trash"], A_INDEX, NA)
    out += _counts(me["action_area"], A_INDEX, NA)
    out += _counts(opp["hand_known_scan"], A_INDEX, NA)   # D-121: 同上。v6 で統一した hand_known に替える
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
    for who in (me, opp):
        for sl in who["slots"]:
            out += _counts(sl[:-1], C_INDEX, NC)
    for uses in ob["tag_uses_this_turn"]:
        out += [_c(uses.get(tag, 0)) for tag in ACTION_TAGS]
    out += _onehot(ob["last_used_card"][0], A_INDEX, NA)
    out += _onehot(ob["last_used_card"][1], A_INDEX, NA)
    assert len(out) == OBS_DIM_V5, (len(out), OBS_DIM_V5)
    # --- v6（D-124）---
    out += _belief(ob, ob.get("_opp_decklist"))
    out += _counts(opp["hand_known"], A_INDEX, NA)     # 統一した既知（D-122）
    assert len(out) == OBS_DIM, (len(out), OBS_DIM)
    return out


def _pow2_floor_x2(w: int) -> int:
    """floor(2·log2 W) を**整数だけで**出す（Rust と 1 ビットも違わないように浮動小数点を使わない）。

    2·log2 W ≥ n ⇔ W² ≥ 2ⁿ なので、W² のビット長 − 1 が答え。W = 1 なら 0。
    """
    return (w * w).bit_length() - 1


def _belief(ob: dict, opp_decklist) -> list:
    """信念の要約（PT-3・D-124）。長さ N_BELIEF の整数列。

    並び:
      0 デッキ表を渡されたか（0 なら 3.. は全部 0）
      1 既知の枚数（統一した hand_known）   2 未知の枚数（手札の枚数 − 既知）
      3 floor(2·log2 W)（W = 区別できる相手の手札の数・`worlds.world_counts`。食い違いは −1）
      4 食い違いの旗（公開情報とデッキ表が合わない）   5 確定の旗（W = 1＝手札も山札の中身も確定）
      6..11  色 赤・緑・青 ごとの手札の枚数の［下限, 上限］
      12..19 コスト帯 {0-1}{2}{3}{4+} ごとの［下限, 上限］

    **読むのは `observe` の欄と、呼び出し側が渡した「相手のデッキ表の想定」だけ**（D-026）。
    デッキ表は探索器の `opp_decklist` と同じもの（D-124 裁定: 引数で渡す）。候補の作り方は
    `GreedyAgent._unseen` と同じ（デッキ表 − 相手の協奏・トラッシュ・アクションエリア）。
    対抗に出して手札から抜けた札も候補に残るので、W は大きめに、上下限は緩めに出る（常に正しい上下限）。
    """
    from collections import Counter
    from .buckets import _COLOR_IX, cost_band
    from .worlds import remove_multiset, world_counts
    opp = ob["opp"]
    known = list(opp["hand_known"])
    n_hand = int(opp["hand_count"])
    v = [0] * N_BELIEF
    v[1] = _c(len(known))
    v[2] = _c(max(0, n_hand - len(known)))
    if opp_decklist is None:
        return v
    v[0] = 1
    pool = Counter(opp_decklist)
    for cid in list(opp["concerto"]) + list(opp["trash"]) + list(opp["action_area"]):
        if pool[cid] > 0:
            pool[cid] -= 1
    pool_list = [cid for cid in sorted(pool) for _ in range(pool[cid])]
    wc = world_counts(pool_list, n_hand, known)
    left = remove_multiset(pool_list, known)
    k = n_hand - len(known)
    if wc["inconsistent"]:
        v[3], v[4] = -1, 1
        return v
    w = int(wc["W"])
    v[3] = _c(_pow2_floor_x2(w)) if w >= 1 else -1
    v[5] = 1 if w == 1 else 0
    def bounds(key, n_groups):
        kn = [0] * n_groups
        lf = [0] * n_groups
        for cid in known:
            kn[key(cid)] += 1
        for cid in left:
            lf[key(cid)] += 1
        out = []
        for g in range(n_groups):
            other = len(left) - lf[g]
            out += [_c(kn[g] + max(0, k - other)), _c(kn[g] + min(k, lf[g]))]
        return out
    v[6:12] = bounds(lambda cid: _COLOR_IX[ACTION_CARDS[cid].color], 3)
    v[12:20] = bounds(lambda cid: cost_band(ACTION_CARDS[cid].cost), 4)
    return v


def encode(ob: dict, pi: int, opp_decklist=None) -> list:
    """`observe(s, pi)` の出力と席番号から符号化する（`turn_player` の相対化に pi が要る）。

    `opp_decklist`（v6・D-124）は**相手のデッキ表の想定**（探索器の `opp_decklist` と同じもの）。
    渡さなければ信念の要約のうちデッキ表の要る列は 0 になる。"""
    ob = dict(ob)
    ob["_pi"] = pi
    ob["_opp_decklist"] = None if opp_decklist is None else list(opp_decklist)
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
    setup_backs = [-1, -1]
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
    elif typ == "choose_card":
        cid = a["card"]
        if cid in A_INDEX:
            card = A_INDEX[cid]
        else:
            chara = C_INDEX[cid]
        slot = a.get("slot", -1)
    elif typ == "setup":
        chara = _lv0_chara_index(a["leader"])
        for i, name in enumerate(a.get("backs", ())[:2]):
            setup_backs[i] = _lv0_chara_index(name)
    return [t, card, chara, slot, back, count] + mull + setup_backs


def expand_action(code) -> list:
    """符号 → 長さ ACT_DIM の float 列（学習側と Rust 側で同じ展開）。"""
    t, card, chara, slot, back, count = code[:6]
    mull = code[6:11]
    setup_backs = code[11:13]
    v = [0.0] * ACT_DIM
    v[t] = 1.0
    o = len(ACTION_TYPES)
    if card >= 0:
        v[o + card] = 1.0
    o += NA
    if chara >= 0:
        v[o + chara] = 1.0
    o += NC
    for b in setup_backs:
        if b >= 0:
            v[o + b] += 1.0
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
