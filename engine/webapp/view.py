"""表示用の変換（APP_DESIGN.md §4）。

**ここはルールを持たない。** 盤面は `engine.observe()` の出力を、
合法手は `engine.legal_actions()` の出力を、それぞれ人間に読める形に
言い換えるだけである。判断は一切しない。

対局中の盤面は必ず `observe(s, 人間の席)` から作る（§2.2）。
`GameState` を直接読んで画面を作ってはならない。相手の手札が漏れる。
"""
from __future__ import annotations

from meicho.cards import ACTION_CARDS, CHARA_CARDS, Color

from webapp import images

COLOR_JA = {Color.RED: "赤", Color.GREEN: "緑", Color.BLUE: "青",
            "red": "赤", "green": "緑", "blue": "青"}

TIMING_JA = {"clash": "【対抗】", "judge": "【判定】", "rush": "【連撃】",
             "turn_end": "【ターン終了時】", "turn_start": "【ターン開始時】",
             "static": "【常在】",
             # --- v0.12 / BP01（D-079 追記 3）---
             "enter": "【登場】", "levelup": "【レベルアップ】",
             "switched": "【切り替え】",
             "clash_phase_start": "【自分の対抗フェイズ開始時】",
             "clash_phase_end": "【各対抗フェイズ終了時】",
             "on_heal": "【自分のライフが回復した時】",
             "on_damage_dealt": "【相手にダメージを与えた時】"}

PHASE_JA = {
    "setup_chara": "キャラ配置", "mulligan": "マリガン",
    "action": "アクションフェイズ", "clash_submit": "対抗ステップ（提出）",
    "choice": "効果の選択", "rush": "連撃ステップ",
    "turn_end_discard": "手札上限の調整", "game_over": "終了",
}

HIDDEN = "<hidden>"


# ------------------------------------------------------------------ スキル文
# カードテキストの逐語転記ではなく、**エンジンが実際に実装しているオペコード列**を
# 日本語に言い換える。検証アプリとしてはこちらが正しい: 画面に出るのは
# 「カードにこう書いてある」ではなく「エンジンはこう動かす」である。
# 実装とテキストが食い違っていれば、それはここに現れる（＝見つけられる）。

_RESULT_JA = {"win": "判定に勝ったとき", "lose": "判定に負けたとき"}


def _color_ja(c) -> str:
    return COLOR_JA.get(c, COLOR_JA.get(getattr(c, "value", c), str(c)))


def _cond_text(c: dict | None) -> str:
    if not c:
        return ""
    parts = []
    if "self_result" in c:
        parts.append(_RESULT_JA.get(c["self_result"], str(c["self_result"])))
    if "self_color" in c:
        parts.append(f"自分の対抗カードが{_color_ja(c['self_color'])}")
    if "opp_color" in c:
        parts.append(f"相手の対抗カードが{_color_ja(c['opp_color'])}")
    if "self_action_area_count_gte" in c:
        parts.append(
            f"自分のアクションエリアが{c['self_action_area_count_gte']}枚以上")
    if "is_turn_player" in c:
        parts.append("自分のターン" if c["is_turn_player"] else "相手のターン")
    # --- v0.12 / BP01（D-079 追記 3）---
    if "hand_size_lte" in c:
        parts.append(f"自分の手札が{c['hand_size_lte']}枚以下")
    if "action_area_tag_count_gte" in c:
        tag, n = c["action_area_tag_count_gte"]
        parts.append(f"自分のアクションエリアに＜{tag}＞が{n}枚以上")
    if "life_greater_than_opponent" in c:
        parts.append("自分のライフが相手より多い" if c["life_greater_than_opponent"]
                     else "自分のライフが相手以下")
    if "leader_name_is" in c:
        parts.append(f"自分のリーダーが「{c['leader_name_is']}」")
    if "last_used_card_has_tag" in c:
        parts.append(f"このターン直前に使ったカードが＜{c['last_used_card_has_tag']}＞")
    if "concerto_has_chara_card" in c:
        parts.append(f"自分の協奏エリアに【{c['concerto_has_chara_card']}】のカードがある")
    if "heals_this_turn_lt" in c:
        parts.append(f"このターンの回復が{c['heals_this_turn_lt'] - 1}回まで")
    if "dominant" in c:
        parts.append("【優勢】（前のターンに対抗で勝ったか、相手がパスしていた）"
                     if c["dominant"] else "【優勢】でない")
    return "・".join(parts)


def _op_text(op: str, prm: dict) -> str:
    n = prm.get("count")
    a = prm.get("amount")
    nm = prm.get("name")
    if op == "draw":
        return f"カードを{n}枚引く"
    if op == "reveal_top_to_hand":
        upto = "まで" if prm.get("up_to") else ""
        return f"デッキの上{n}枚{upto}を公開して手札に加える"
    if op == "top_to_concerto":
        return f"デッキの上{n}枚を協奏エリアに置く"
    if op == "damage_opponent":
        return f"相手にダメージ{a}"
    if op == "pursuit":
        return f"追撃{n}（このあとの連撃で使える枚数が{n}増える）"
    if op == "forbid_leader_switch_this_turn":
        return "このターン、自分はリーダーを切り替えられない"
    if op == "switch_leader":
        return "自分のリーダーとバックを入れ替える（どちらのバックかは選ぶ）"
    if op == "self_damage_buff_if_switched":
        return f"この効果で{nm}が入れ替わっていたら、このカードのダメージ+{a}"
    if op == "top_to_concerto_if_switched":
        return f"この効果で{nm}が入れ替わっていたら、デッキの上{n}枚を協奏エリアに置く"
    if op == "draw_if_switched":
        return f"この効果で{nm}が入れ替わっていたら、カードを{n}枚引く"
    if op == "self_damage_buff":
        return f"このカードのダメージ+{a}"
    if op == "rush_damage_buff":
        return f"連撃で使うカードのダメージ+{a}（対抗のダメージには乗らない）"
    if op == "dedicated_leader_card_damage_buff":
        return (f"{nm} の専用カードのうちリーダースキルを持つものは"
                f"ダメージ+{a}（対抗・連撃の両方）")
    if op == "heal_self":
        return f"自分のライフを{a}回復する（上限 20）"
    if op == "raise_opponent_red_cost_next_turn":
        return "次の相手のターン、相手の赤のカードのコスト+1"
    if op == "return_clash_card_to_hand":
        return "対抗で使ったこのカードを手札に戻す（払ったコストは戻らない）"
    if op == "opponent_pay_or_damage":
        return (f"相手は協奏エリアから{prm.get('cost')}枚支払う。"
                f"払わなければダメージ{a}（払えないときは即ダメージ）")
    if op == "discard_self":
        return f"自分の手札を{n}枚捨てる"
    if op == "forbid_rush_next_turn":
        return "次の相手のターン、相手は連撃できない"
    if op == "peek_opponent_hand":
        return "相手の手札を見る"
    # --- v0.12 / BP01（D-079 追記 3・便 K 段 K-2）---
    if op == "draw_to":
        return f"手札が{n}枚になるまでカードを引く"
    if op == "heal_if_switched":
        return f"この効果で{nm}が入れ替わっていたら、自分のライフを{a}回復する"
    if op == "self_damage_buff_if_discarded":
        return f"手札を捨てていたら、このカードのダメージ+{a}"
    if op == "self_damage_buff_per_action_area":
        return f"自分のアクションエリアのカード1枚につき、このカードのダメージ+{a}"
    if op == "first_use_damage_buff":
        who = f"{nm} の" if nm else ""
        return (f"各ターン、自分が最初に使う{who}＜{prm.get('tag')}＞の"
                f"ダメージ+{a}")
    if op == "first_damage_taken_mod":
        return f"各ターン、自分が最初に受けるダメージ{a:+d}"
    if op == "name_color_damage_buff":
        return f"自分の {nm} の{COLOR_JA.get(prm.get('color'), prm.get('color'))}のカードのダメージ+{a}"
    if op == "own_card_damage_buff":
        return f"このカードのダメージ+{a}"
    if op == "forbid_rush_self_now":
        return "このターン中、自分は連撃できない"
    if op == "forbid_rush_opponent_now":
        return "このターン中、相手は連撃できない"
    if op == "pay_cost_return_self_to_hand":
        return (f"協奏エリアから{prm.get('cost')}枚支払って、"
                f"このカードをアクションエリアから手札に戻す")
    if op == "speed_override":
        return f"このカードのスピードは{prm.get('speed')}になる（判定の比較だけに効く）"
    # --- v0.12 / BP01 K-3（D-079 追記 5）---
    if op == "concerto_set_first_use_buff":
        return (f"自分の協奏エリアにこのカードを含む{prm.get('count')}種類以上の"
                f"＜{prm.get('set_tag')}＞があれば、各ターン最初に使う"
                f"＜{prm.get('tag')}＞のダメージ+{a}")
    if op == "opp_discard_random":
        return (f"相手の手札{prm.get('per')}枚につき、ランダムに手札1枚を捨てさせる"
                f"（端数切り捨て）")
    if op == "opp_concerto_to_trash":
        return f"相手の協奏エリアから{n}枚をトラッシュに置く（いまは左端から自動で選ぶ）"
    if op == "opp_hand_random_to_deck_bottom":
        return f"相手の手札からランダムに{n}枚をデッキの下に置く"
    if op == "mill_opponent_deck_top":
        return f"相手のデッキの上から{n}枚をトラッシュに置く"
    if op == "opp_trash_to_deck_bottom":
        return (f"相手のトラッシュから{n}枚までを相手のデッキの下に置く"
                f"（いまは左端から自動で選ぶ）")
    # --- v0.12 / BP01 K-4（D-079 追記 6）---
    if op in ("trash_to_hand", "trash_to_hand_if_switched", "trash_to_concerto"):
        cond = []
        if prm.get("chara"):
            cond.append(f"【{prm['chara']}】の")
        if prm.get("color"):
            cond.append(COLOR_JA.get(prm["color"], prm["color"]) + "色の")
        if prm.get("tag"):
            cond.append("／".join(f"＜{t}＞" for t in str(prm["tag"]).split("|")))
        if prm.get("exclude_tag"):
            cond.append(f"（＜{prm['exclude_tag']}＞以外）")
        where = "協奏エリアに置く" if op == "trash_to_concerto" else "手札に加える"
        head = (f"この効果で{nm}が入れ替わっていたら、"
                if op.endswith("_if_switched") else "")
        return (f"{head}トラッシュから{''.join(cond)}カード{n}枚を{where}"
                f"（いまは左端から自動で選ぶ）")
    if op == "return_to_chara_deck":
        return "このカードをキャラデッキに戻す（下のカードが最上段に戻る＝レベルが下がる）"
    if op in ("levelup_by_effect", "levelup_by_effect_if_switched"):
        head = f"この効果で{nm}が入れ替わっていたら、" if op.endswith("_if_switched") else ""
        lv = prm.get("level")
        where = (f"自分のキャラデッキからレベル{lv}の「{nm}」1枚を自分の「{nm}」の上に置く"
                 if lv is not None else f"自分の「{nm}」をレベルアップする")
        return (f"{head}{where}"
                f"（コストを払わず、1ターン1回も消費しない。レベルアップとしても扱う）")
    if op == "levelup_by_effect_only":
        return "このカードはカード効果でのみレベルアップできる"
    if op == "cost_mod":
        return f"このカードのコスト{prm.get('delta'):+d}（下限 0）"
    if op == "grant_rush_draw_to_variation_skills":
        return (f"このターン中、自分が次に使用する{n}枚の＜変奏スキル＞は"
                f"『【連撃】カード1枚を引く。』を得る（連撃で使った札だけを数える）")
    if op == "damage_taken_mod":
        return f"自分が受けるダメージ{a:+d}"
    if op == "grant_deferred_damage_on_loss":
        tags = "／".join(f"＜{t}＞" for t in (prm.get("tag"), prm.get("set_tag")) if t)
        return (f"自分の【{prm.get('chara')}】の{tags}は"
                f"『【判定】赤色のカードに敗北した場合、この対抗フェイズの終了時に"
                f"相手にこのカードのダメージを与える』を得る")
    if op == "switch_leader_to":
        return f"自分のリーダーを「{nm}」に切り替える（バックに居なければ何も起きない）"
    if op == "search_deck":
        return (f"自分のデッキから「{prm.get('card_name')}」1枚を手札に加え、"
                f"デッキをシャッフルする（無くてもシャッフルする）")
    if op == "reveal_n_take_matching":
        return (f"デッキの上から{n}枚を公開し、【{prm.get('chara')}】のカードを"
                f"すべて手札に加えて残りをトラッシュに置く")
    return f"{op} {prm}"        # 未対応のオペコードは隠さず生で出す


def skill_text(sk) -> str:
    """スキル 1 個を 1 行の日本語にする。**情報を落とさない。**"""
    timing = TIMING_JA.get(getattr(sk.timing, "value", sk.timing), str(sk.timing))
    head = timing + ("【リーダー】" if sk.leader_only else "")
    cond = _cond_text(sk.condition)
    body = "、".join(_op_text(op, dict(prm)) for op, prm in sk.effect)
    if sk.optional:
        body += "（してもよい）"
    if sk.unverified:
        body += "（※テキスト未確認）"
    return head + (f" {cond}: " if cond else " ") + body


# ------------------------------------------------------------------ カード
def action_card(cid: str) -> dict:
    """アクションカード1枚の表示用データ。**常に全項目を出す**（§4.3）。"""
    c = ACTION_CARDS[cid]
    return {
        # 画像は**見た目でしかない**（UI_DESIGN.md §P1）。無ければ None を返し、
        # 画面は現行のテキスト表示に落ちる（§P3）。既存の項目は一切削らない:
        # `skills`（エンジンのオペコード言い換え）が検証機能の本体である（§P4）。
        "img": images.url_for(cid),
        "id": cid, "name": c.name,
        "color": COLOR_JA.get(c.color, str(c.color)),
        "cost": c.cost, "speed": c.speed, "damage": c.damage,
        "dedicated_to": c.dedicated_to,
        "leader_skill": bool(c.leader_skill),
        "skills": [skill_text(sk) for sk in c.skills],
        "unverified": bool(c.unverified_fields),
        "label": (f"{cid} {c.name} "
                  f"{COLOR_JA.get(c.color, c.color)}"
                  f"/コスト{c.cost}/速{c.speed}/ダメ{c.damage}"),
    }


def chara_card(cid: str) -> dict:
    if cid == HIDDEN:
        # 非公開のキャラには**画像を持たせない**（§P2）。裏面は画面側が描く。
        return {"id": HIDDEN, "name": "？", "level": None, "label": "（非公開）",
                "skills": [], "tags": [], "img": None}
    c = CHARA_CARDS[cid]
    return {"id": cid, "name": c.name, "level": c.level,
            "img": images.url_for(cid),
            "tags": list(c.tags),
            "skills": [skill_text(sk) for sk in c.skills],
            "label": f"{c.name} Lv{c.level}"}


def _slot(stack: list) -> dict:
    """キャラ1枠。重ねたカードは全部持つ（スキルは重ねた全部が有効・§6.3-3）。

    **重ねた下のカードのスキルも有効**なので、下の分も文面ごと持たせる。
    「覚えていないと分からない」状態を作らないため、ここで全部出す。
    """
    if not stack:
        return {"empty": True, "label": "（空）", "stack": [], "under": [],
                "skills": []}
    cards = [chara_card(c) for c in stack]
    skills = []
    for c in cards:                      # 下から順（重ねた全部が有効・§6.3-3）
        for t in c["skills"]:
            skills.append({"from": c["label"], "text": t})
    return {"empty": False, "stack": cards,
            "label": cards[-1]["label"],
            "under": [c["label"] for c in cards[:-1]],
            "skills": skills}


SLOT_JA = ("リーダー", "バック1", "バック2")


def chara_overview(ob: dict) -> list:
    """**自分のキャラデッキ全体**を、いまどこにあるかを添えて返す（ルール §3.1）。

    自分のキャラデッキは自分にとって公開情報である（隠蔽情報は相手の手札・
    両デッキの順序・準備段階のキャラ配置のみ・rules_draft.md §11）。
    ところが `observe` の `chara_deck` は**まだ引いていない残り**なので、
    レベルアップで場に出た分が消えて見える。そこで
    「残り」と「場に重なっている分」を合わせ、キャラ名ごとに並べ直す。

    情報は足していない（どちらも観測に写っている）。並べ替えているだけである。
    """
    me = ob["me"]
    rows: dict[str, dict] = {}

    def put(cid: str, where: str):
        c = chara_card(cid)
        r = rows.setdefault(c["name"], {"name": c["name"], "levels": []})
        r["levels"].append({**c, "where": where})

    for si, stack in enumerate(me["slots"]):
        for cid in stack:
            put(cid, SLOT_JA[si] if si < len(SLOT_JA) else f"枠{si}")
    for cid in me["chara_deck"]:
        put(cid, "キャラデッキ")

    out = list(rows.values())
    for r in out:
        r["levels"].sort(key=lambda x: (x["level"] is None, x["level"]))
    out.sort(key=lambda r: r["name"])
    return out


# ------------------------------------------------------------------ 盤面
def board(ob: dict) -> dict:
    """`observe()` の出力を画面用に言い換える。**情報は一切足さない。**"""
    me, opp = ob["me"], ob["opp"]
    return {
        "phase": ob["phase"], "phase_ja": PHASE_JA.get(ob["phase"], ob["phase"]),
        "turn_no": ob["turn_no"], "turn_player": ob["turn_player"],
        "me": {
            "life": me["life"],
            "hand": [action_card(c) for c in me["hand"]],
            "concerto": [action_card(c) for c in me["concerto"]],
            # トラッシュは**両者とも公開情報**である（rules_draft.md §11 の
            # 隠蔽情報は「相手の手札・両デッキの順序・準備段階のキャラ配置」だけ）。
            # observe が最初から中身を返しているので、情報は足していない。
            "trash_count": len(me["trash"]),
            "trash": [action_card(c) for c in me["trash"]],
            "action_area": [action_card(c) for c in me["action_area"]],
            "deck_count": me["deck_count"],
            "slots": [_slot(st) for st in me["slots"]],
            "chara_deck": [chara_card(c) for c in me["chara_deck"]],
            "chara_overview": chara_overview(ob),
        },
        "opp": {
            "life": opp["life"],
            "hand_count": opp["hand_count"],
            "hand_known": [action_card(c) for c in opp["hand_known"]],
            "concerto": [action_card(c) for c in opp["concerto"]],
            "trash_count": len(opp["trash"]),
            "trash": [action_card(c) for c in opp["trash"]],
            "action_area": [action_card(c) for c in opp["action_area"]],
            "deck_count": opp["deck_count"],
            "slots": [_slot(st) for st in opp["slots"]],
        },
        # D-036 で observe に足した公開情報。見えないと挙動が不可解に見える（§4.3）
        "used": ob["used"],
        "effects": {
            "red_cost_up": ob["red_cost_up"],
            "pending_red_cost_up": ob["pending_red_cost_up"],
            "rush_forbidden": ob["rush_forbidden"],
            "pending_rush_forbidden": ob["pending_rush_forbidden"],
            "leader_switch_forbidden": ob["leader_switch_forbidden"],
        },
        "clash": {
            "mine": action_card(ob["clash_cards"][0]) if ob["clash_cards"][0]
                    and ob["clash_cards"][0] != "PASS" else None,
            "mine_pass": ob["clash_cards"][0] == "PASS",
            "theirs": action_card(ob["clash_cards"][1]) if ob["clash_cards"][1]
                      and ob["clash_cards"][1] != "PASS" else None,
            "theirs_pass": ob["clash_cards"][1] == "PASS",
            "winner": ob["clash_winner"],
            "rush_allowance": ob["rush_allowance"],
        },
        "last_clash": {
            "winner": ob["last_clash_winner"],
            "cards": [action_card(c) if c and c != "PASS" else None
                      for c in ob["last_clash_cards"]],
            "pass": [c == "PASS" for c in ob["last_clash_cards"]],
        },
        "clash_counts": ob["clash_counts"],
        "pending_choice": ob["pending_choice"],
    }


# ------------------------------------------------------------------ 行動
def action_label(ob: dict, a: dict) -> str:
    """合法手 1 つを日本語にする。**観測に写っている情報だけを使う。**"""
    t = a["type"]
    hand = ob["me"]["hand"]

    def card(i):
        return action_card(hand[i])["label"] if 0 <= i < len(hand) else "？"

    if t == "setup":
        return f"リーダーを {a['leader']} にする"
    if t == "mulligan":
        idx = a["cards"]
        if not idx:
            return "マリガン: 1枚も戻さない"
        return ("マリガン: " + "、".join(card(i) for i in idx)
                + f" を戻す（{len(idx)}枚）")
    if t == "charge":
        return f"チャージ: {card(a['hand'])} を協奏エリアに置く"
    if t == "switch":
        st = ob["me"]["slots"][a["back"]]
        nm = chara_card(st[-1])["label"] if st else "（空）"
        return f"切り替え: {nm} をリーダーにする"
    if t == "levelup":
        c = CHARA_CARDS[a["card"]]
        cost = f"（手札を{c.level}枚捨てる）" if c.level else "（手札コストなし）"
        return f"レベルアップ: {c.name} Lv{c.level} を重ねる{cost}"
    if t == "to_clash":
        return "対抗フェイズへ進む"
    if t == "end_turn":
        return "ターンを終える"
    if t == "submit":
        return f"対抗に提出: {card(a['hand'])}"
    if t == "pass":
        return "対抗: 提出しない（パス）"
    if t == "pay":
        return "コストを支払う"
    if t == "decline":
        return "支払わずダメージを受ける"
    if t == "choose_back":
        st = ob["me"]["slots"][a["back"]]
        nm = chara_card(st[-1])["label"] if st else "（空）"
        return f"{nm} をリーダーにする"
    if t == "use":
        return "効果を使う"
    if t == "skip":
        return "効果を使わない"
    if t == "choose_count":
        return f"{a['count']} 枚にする"
    if t == "discard":
        return f"捨てる: {card(a['hand'])}"
    if t == "resolve":
        return f"スキル {a['index'] + 1} 番目から解決する"
    if t == "rush":
        return f"連撃: {card(a['hand'])} を使う"
    if t == "stop":
        return "連撃をやめる"
    return str(a)


CHOICE_JA = {
    "pay_or_damage": "コストを支払うか、ダメージを受けるかを選ぶ",
    "switch_back": "どちらのバックをリーダーにするかを選ぶ",
    "use_optional": "「〜してもよい」効果を使うかを選ぶ",
    "reveal_count": "何枚にするかを選ぶ",
    "discard": "捨てる手札を選ぶ",
    "discard_for_effect": "効果によって捨てる手札を選ぶ",
    "order": "同時に誘発したスキルの解決順を選ぶ",
}


def choice_reason(ob: dict) -> str:
    """今なぜ選択を求められているのかを一文で（§4.3）。"""
    ch = ob.get("pending_choice")
    if not ch:
        return ""
    base = CHOICE_JA.get(ch["kind"], ch["kind"])
    src = ch.get("source") or ch.get("card")
    if src and src in ACTION_CARDS:
        base += f"（{ACTION_CARDS[src].name} の効果）"
    elif src and src in CHARA_CARDS:
        base += f"（{CHARA_CARDS[src].name} の効果）"
    return base
