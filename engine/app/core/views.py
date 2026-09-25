"""視点（席ごと・観戦者）と、視点の差分から作る出来事。

**設計の芯（APP-003）: ある相手に送るものは、その相手の観測だけから作る。**

- 席の視点は `meicho.observe(s, pi)` を絶対座標（席 0／1）に並べ直しただけである
- 観戦者の視点は、2 つの席の観測の「相手側」を組み合わせて作る（要件 R-SPEC-1）。エンジンは変えない
- 出来事は、**同じ相手の視点の前後の差分**から作る。入力がその相手の観測だけなので、
  相手に見えないカード番号が出来事に混ざることが構造的に起きない（要件 R-FX-6・R-SEC-1）

出来事は**見せるためのもの**であって、状態の正本ではない。画面は毎回 `view` の全量を受け取り、
出来事はその間を埋める演出の材料に使う。出来事の復元が粗くても対局は壊れない。

いまは 1 回の `apply` の前後でしか差分を取れない（順序が粗い）。エンジンにトレース点が入ったら
（`M1_EVENT_SPEC.md`）、同じ `diff_events` を区切りごとに呼ぶだけで順序が細かくなる。
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from meicho import observe
from meicho.state import GameState, Phase

SPECTATOR = "spec"
FULL = "full"             # リプレイの全情報（終局した対局だけ・replay.py）

# 観測のうち、席に依らない公開の欄（そのまま写す）
_PUBLIC_PLAIN = ("used", "rush_allowance")
# 観測のうち、[自分, 相手] または {"me","opp"} で持っている公開の欄（絶対座標に直す）
_PUBLIC_PAIR_LIST = ("last_clash_cards", "last_turn_clash_pass", "damage_taken_mod",
                     "speed_override", "heals_this_turn", "damaged_this_turn",
                     "first_damage_taken_this_turn", "deferred_clash_damage")
_PUBLIC_PAIR_DICT = ("red_cost_up", "pending_red_cost_up", "rush_forbidden",
                     "pending_rush_forbidden", "leader_switch_forbidden", "clash_counts")
# 0=自分／1=相手 で持っている欄（勝者）
_RELATIVE_WINNER = ("clash_winner", "last_clash_winner", "last_turn_clash_winner")


def _own(me: dict) -> dict:
    return {
        "life": me["life"], "hand": list(me["hand"]), "hand_count": len(me["hand"]),
        "hand_known": [], "concerto": list(me["concerto"]), "trash": list(me["trash"]),
        "action_area": list(me["action_area"]), "slots": [list(x) for x in me["slots"]],
        "chara_deck": list(me["chara_deck"]), "deck_count": me["deck_count"],
    }


def _other(opp: dict, *, known: bool) -> dict:
    return {
        "life": opp["life"], "hand": None, "hand_count": opp["hand_count"],
        "hand_known": list(opp["hand_known"]) if known else [],
        "concerto": list(opp["concerto"]), "trash": list(opp["trash"]),
        "action_area": list(opp["action_area"]), "slots": [list(x) for x in opp["slots"]],
        "chara_deck": None, "deck_count": opp["deck_count"],
    }


def _absolute(ob: dict, pi: int, out: dict) -> None:
    """観測 `ob`（席 pi から見たもの）の公開の欄を、絶対座標で `out` に写す。"""
    for k in _PUBLIC_PLAIN:
        out[k] = ob[k]
    for k in _PUBLIC_PAIR_LIST:
        mine, theirs = ob[k]
        out[k] = [mine, theirs] if pi == 0 else [theirs, mine]
    for k in _PUBLIC_PAIR_DICT:
        out[k] = [ob[k]["me"], ob[k]["opp"]] if pi == 0 else [ob[k]["opp"], ob[k]["me"]]
    for k in _RELATIVE_WINNER:
        v = ob[k]
        out[k] = None if v is None else (pi if v == 0 else 1 - pi)


def seat_view(s: GameState, pi: int) -> dict:
    """席 pi に送ってよい全部。`observe(s, pi)` の並べ直しであり、足しも引きもしない。"""
    ob = observe(s, pi)
    players = [None, None]
    players[pi] = _own(ob["me"])
    players[1 - pi] = _other(ob["opp"], known=True)
    mine, theirs = ob["clash_cards"]
    v = {
        "viewer": pi, "phase": ob["phase"], "turn_no": ob["turn_no"],
        "turn_player": ob["turn_player"], "players": players,
        "clash_cards": [mine, theirs] if pi == 0 else [theirs, mine],
        "choice": ob["pending_choice"], "outcome": s.outcome,
    }
    _absolute(ob, pi, v)
    return v


def spectator_view(s: GameState) -> dict:
    """観戦者に送ってよい全部。両者の手札・判明した手札・選択肢は含まない（要件 R-SPEC-1）。

    席 0 の公開情報は「席 1 の観測の相手側」、席 1 の公開情報は「席 0 の観測の相手側」である。
    どちらの席にも見えているものだけを組み合わせるので、片方しか知らない情報は入らない。
    """
    ob0, ob1 = observe(s, 0), observe(s, 1)
    players = [_other(ob1["opp"], known=False), _other(ob0["opp"], known=False)]
    v = {
        "viewer": SPECTATOR, "phase": ob0["phase"], "turn_no": ob0["turn_no"],
        "turn_player": ob0["turn_player"], "players": players,
        # 対抗の提出は、相手に見えるようになった時点（＝公開後）で観戦者にも見える
        "clash_cards": [ob1["clash_cards"][1], ob0["clash_cards"][1]],
        "choice": None, "outcome": s.outcome,
    }
    _absolute(ob0, 0, v)
    # `rush_allowance` は「判定に勝った本人から見たときだけ非 0」なので、観戦者には両方を見て大きい方を渡す
    v["rush_allowance"] = max(ob0["rush_allowance"], ob1["rush_allowance"])
    return v


def full_view(s: GameState) -> dict:
    """両者の手札・キャラデッキ・伏せた提出まで全部見える視点（リプレイの「全情報」・要件 R-REP-2／R-REP-3）。

    **終局した対局のリプレイにだけ使う。**対局中の部屋へは決して送らない（呼ぶのは `replay.py` だけ）。
    席 0 の観測の自分側と、席 1 の観測の自分側を組み合わせる。山札の並びは観測に無いので、ここにも無い。
    """
    ob0, ob1 = observe(s, 0), observe(s, 1)
    v = {
        "viewer": FULL, "phase": ob0["phase"], "turn_no": ob0["turn_no"],
        "turn_player": ob0["turn_player"], "players": [_own(ob0["me"]), _own(ob1["me"])],
        "clash_cards": [ob0["clash_cards"][0], ob1["clash_cards"][0]],
        "choice": None, "outcome": s.outcome,
    }
    _absolute(ob0, 0, v)
    v["rush_allowance"] = max(ob0["rush_allowance"], ob1["rush_allowance"])
    return v


def view_for(s: GameState, viewer) -> dict:
    if viewer == FULL:
        v = full_view(s)
    else:
        v = spectator_view(s) if viewer == SPECTATOR else seat_view(s, viewer)
    v["effects"] = effect_stack(s, v)
    return v


def effect_stack(s: GameState, view: dict) -> dict:
    """いま解決している効果と、解決を待っている効果の列（APP-023）。`{"resolving": 項目|None, "queue": [項目…]}`。

    項目は `{"player": 持ち主の対局の席, "card": カード番号|None, "skill_index": 何番目のスキル|None}`。
    紙の対戦では誘発したスキルは宣言されるので公開の情報だが、念のため**その視点に写っているカードだけ**番号を出す
    （写っていなければ `None`＝「伏せたカードの効果」として見せる。APP-003 と同じ考え方）。

    - 解決中: エンジンが解決を始めたスキル（`pending_effect` の `card`）。まだ始めていないが「使うか」を尋ねているもの
      （`use_optional`）も、そのスキルを解決中として扱う。カードに載らない処理（ルールの処理）は `None`
    - 待ち: 効果の途中で誘発した割り込み（`pending_triggers`）が先、外側の待ち行列（`pending_skills`）が後。エンジンが解く順
    """
    vis = visible_cards(view)

    def item(player, card, skill_index=None):
        seen = card in vis
        return {"player": player, "card": card if seen else None, "skill_index": skill_index if seen else None}

    resolving = None
    pe = s.pending_effect
    if pe is not None and pe.get("ops") and pe.get("card"):
        resolving = item(pe["owner"], pe["card"])
    elif s.pending_choices and s.pending_choices[0].get("kind") == "use_optional":
        c = s.pending_choices[0]
        resolving = item(c["player"], c["card"], c.get("skill_index"))
    queue = [item(r[0], r[2], r[3]) for r in list(s.pending_triggers) + list(s.pending_skills)]
    return {"resolving": resolving, "queue": queue}


# --------------------------------------------------------------------------- 出来事

_LIST_ZONES = ("concerto", "trash", "action_area")


def _zone_cards(p: dict) -> dict:
    """視点の 1 人ぶんから、領域ごとの「見えているカード」の多重集合を作る。"""
    z = {k: Counter(p[k]) for k in _LIST_ZONES}
    z["hand"] = Counter(p["hand"] if p["hand"] is not None else p["hand_known"])
    z["chara_deck"] = Counter(p["chara_deck"] or [])
    for i, stack in enumerate(p["slots"]):
        z[f"slot{i}"] = Counter(c for c in stack if c != "<hidden>")
    return z


def visible_cards(view: dict) -> set:
    """その視点に写っているカード番号の集合（両者の全領域と対抗のカード）。出来事に番号を足してよいかの判定に使う（APP-003）。"""
    out = {c for c in view.get("clash_cards") or [] if c}
    for p in view["players"]:
        for z in _zone_cards(p).values():
            out.update(z)
    return out


def _zone_counts(p: dict) -> dict:
    """枚数だけは見えている領域（中身が見えない手札と山札）。"""
    return {"hand": p["hand_count"], "deck": p["deck_count"]}


def diff_events(before: Optional[dict], after: dict) -> list:
    """同じ相手の視点 2 つの差分から、出来事の列を作る。

    返すのは辞書の列で、`t` が種類。カード番号 `card` は、その視点に写っているときだけ入る
    （写っていなければ `None`＝裏向きの 1 枚として見せる）。
    """
    if before is None:
        return [{"t": "start"}]
    ev: list = []
    if after["turn_no"] != before["turn_no"]:
        ev.append({"t": "turn", "turn_no": after["turn_no"], "player": after["turn_player"]})
    for pi in (0, 1):
        ev += _player_moves(pi, before["players"][pi], after["players"][pi])
    for pi in (0, 1):
        b, a = before["clash_cards"][pi], after["clash_cards"][pi]
        if a is not None and a != b:
            ev.append({"t": "clash_reveal", "player": pi, "card": a})
    if after["clash_winner"] != before["clash_winner"] and after["clash_winner"] is not None:
        ev.append({"t": "judge", "winner": after["clash_winner"]})
    for pi in (0, 1):
        # ライフは 0 で止めて比べる。とどめのダメージでは、エンジンがライフを負にした直後にトレース点を出し、
        # そのあと 0 に直す。そのまま比べると「-5 → 負の値」のあとに「+5 → 0」の回復が出てしまっていた（APP-016）
        la, lb = max(0, after["players"][pi]["life"]), max(0, before["players"][pi]["life"])
        if la != lb:
            ev.append({"t": "life", "player": pi, "delta": la - lb, "value": la})
    if after["phase"] != before["phase"]:
        ev.append({"t": "phase", "phase": after["phase"]})
    if after["outcome"] is not None and before["outcome"] is None:
        ev.append({"t": "game_over", "outcome": after["outcome"]})
    return _choreograph(ev, after)


def _choreograph(ev: list, after: dict) -> list:
    """出来事を「見せる順」に並べ替える（要件 R-FX-1・R-CLASH-4）。**並べ替えるだけで、中身は足しも引きもしない。**

    差分からは 1 回の `apply` の中の本当の順序が分からない。そこで、ルール上の流れ
    （置く・重ねる → 公開 → コストの支払い → 判定 → ライフ → 効果による移動 → 使い終わった札の片付け →
    ターンの交代 → 新しいターンのドロー）に沿った段に振り分け、段の中では元の順を保つ。
    エンジンにトレース点（`M1_EVENT_SPEC.md`）が入ったら本当の順序が手に入るので、この関数は要らなくなる。
    """
    turn_changed = any(e["t"] == "turn" for e in ev)
    tp = after["turn_player"]

    def rank(e: dict) -> float:
        t = e["t"]
        if t == "move":
            src, dst = e["from"], e["to"]
            if dst == "action_area" or (src == "hand" and dst == "concerto"):
                return 0
            if dst.startswith("slot"):
                return 0                                   # レベルアップ・切り替え・開始時の公開
            if src == "concerto" and dst == "trash":
                return 2
            if src == "action_area":
                return 6
            if turn_changed and e["player"] == tp and src == "deck" and dst == "hand":
                return 8
            return 5
        if t == "refresh":
            return 7.5 if turn_changed and e["player"] == tp else 4.5
        return {"start": -1, "clash_reveal": 1, "judge": 3, "life": 4, "known": 5, "count": 5,
                "turn": 7, "phase": 9, "game_over": 10}.get(t, 5)

    return sorted(ev, key=rank)            # sorted は安定なので、同じ段の中の順は変わらない


def _player_moves(pi: int, b: dict, a: dict) -> list:
    """席 pi のカードの出入りを、視点に写っている範囲で復元する。

    見える領域（協奏・トラッシュ・アクションエリア・キャラ枠、本人なら手札とキャラデッキ）は
    カード番号の多重集合で比べ、見えない領域（山札、相手なら手札）は枚数で比べる。
    """
    zb, za = _zone_cards(b), _zone_cards(a)
    own = a["hand"] is not None
    left: list = []     # (領域, カード): 見えていたカードがその領域から消えた
    came: list = []     # (領域, カード): 見えるカードがその領域に現れた
    for zone in za:
        for c, n in sorted((zb[zone] - za[zone]).items()):
            left += [(zone, c)] * n
        for c, n in sorted((za[zone] - zb[zone]).items()):
            came += [(zone, c)] * n
    out: list = []

    def move(card, src, dst):
        out.append({"t": "move", "player": pi, "card": card, "from": src, "to": dst})

    # 見えない領域の枚数の増減（本人の手札は中身が見えているので、枚数では追わない）
    d_deck = a["deck_count"] - b["deck_count"]
    d_hand = 0 if own else a["hand_count"] - b["hand_count"]
    known: list = []

    # 1. 同じカードが、ある領域から消えて別の領域に現れた → 表向きの移動
    for src in list(left):
        dst = next((d for d in came if d[1] == src[1] and d[0] != src[0]), None)
        if dst is not None:
            left.remove(src)
            came.remove(dst)
            move(src[1], src[0], dst[0])
            if not own:                         # 判明していた相手の手札が表向きに出入りした分
                d_hand += (src[0] == "hand") - (dst[0] == "hand")

    # 2. 見えない所から、見える所へ出てきた
    for zone, c in came:
        if zone == "hand" and not own:
            known.append(c)                     # 移動ではなく「相手の手札が判明した」
        elif zone.startswith("slot"):
            move(c, "chara_deck", zone)
        elif not own and d_hand < 0:
            d_hand += 1
            move(c, "hand", zone)
        elif own or d_deck < 0:                 # 本人にとって見えない領域は山札だけである
            d_deck += 1
            move(c, "deck", zone)
        else:
            move(c, "unknown", zone)
    # 3. 見える所から、見えない所へ入った
    for zone, c in left:
        if zone.startswith("slot"):
            move(c, zone, "chara_deck")
        elif zone == "hand" and not own:
            # 判明していた相手の手札が消えた。行き先が見える場合は 1. で拾っているので、ここは山札行きか、
            # 単に「判明している」集合から外れただけである。枚数が合うときだけ移動として見せる
            if d_hand < 0 and d_deck > 0:
                d_hand += 1
                d_deck -= 1
                move(c, "hand", "deck")
        elif not own and d_hand > 0:
            d_hand -= 1
            move(c, zone, "hand")
        elif own or d_deck > 0:
            d_deck -= 1
            move(c, zone, "deck")
        else:
            move(c, zone, "unknown")
    # 4. どちらの端も見えない移動（相手のドローなど）。裏向きの 1 枚として枚数だけ伝える
    while d_deck < 0 and d_hand > 0:
        d_deck, d_hand = d_deck + 1, d_hand - 1
        move(None, "deck", "hand")
    while d_hand < 0 and d_deck > 0:
        d_hand, d_deck = d_hand + 1, d_deck - 1
        move(None, "hand", "deck")
    if known:
        out.append({"t": "known", "player": pi, "cards": known})
    # 5. トラッシュが山札に戻る（リフレッシュ）のような大量の移動は 1 件に畳む
    bulk = [m for m in out if m["t"] == "move" and m["from"] == "trash" and m["to"] == "deck"]
    if len(bulk) >= 3:
        out = [m for m in out if m not in bulk]
        out.append({"t": "refresh", "player": pi, "n": len(bulk)})
    if d_deck or d_hand:
        out.append({"t": "count", "player": pi, "hand": d_hand, "deck": d_deck})
    return out


def card_ids_in(obj) -> set:
    """メッセージに含まれるカード番号らしき文字列を全部拾う（漏洩の検査用・要件 R-SEC-2）。"""
    import re
    out: set = set()
    pat = re.compile(r"^[A-Z]{2,4}\d{0,2}-\d{3}")

    def walk(x):
        if isinstance(x, str):
            if pat.match(x):
                out.add(x)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(obj)
    return out
