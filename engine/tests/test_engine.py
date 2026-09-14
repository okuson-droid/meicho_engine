"""ルール裁定テスト。各テストに rules_draft.md の条項番号を明記する（現行 v0.10 準拠）。"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from meicho import (
    ACTION_CARDS, CHARA_CARDS, Color, GameConfig, Phase,
    apply, decision_players, initial_state, legal_actions, observe, outcome,
)
from meicho.state import GameState, RUSH_UNLIMITED


def sample_config() -> GameConfig:
    chara = ["BP01-021", "SD02-002", "BP01-033", "SD02-004", "BP01-030", "SD02-006"]
    deck = (["SD02-007"] * 3 + ["SD02-021"] * 3 + ["SD02-018"] * 3 + ["SD02-022"] * 3 +
            ["SD02-010"] * 3 + ["SD02-009"] * 3 + ["SD02-014"] * 3)
    deck += ["SD02-007"] * 0
    # 40枚に満たない分は共通カードで埋める（テスト用に同一IDの水増しはせず、
    # コピー上限3を守るため SD02-007 / SD02-018〜SD02-014 の3枚ずつ=21枚 + 追加19枚が必要。
    # テスト専用のダミー共通カードを使う。
    return GameConfig(
        chara_decks=[list(chara), list(chara)],
        action_decks=[deck + _filler(19), deck + _filler(19)],
    )


def _filler(n: int) -> list:
    """テスト用ダミー共通カード（構築ルール検査を通すため登録簿に追加）。"""
    from meicho.cards import ACTION_CARDS, ActionCard, Color as C
    out = []
    i = 0
    while len(out) < n:
        cid = f"TEST-{i:03d}"
        if cid not in ACTION_CARDS:
            ACTION_CARDS[cid] = ActionCard(
                cid, f"テスト刃{i}", C.RED, cost=0, speed=(i % 15) + 1, damage=1)
        need = min(3, n - len(out))
        out += [cid] * need
        i += 1
    return out


# --- 選択待ちの自動消化ヘルパ (D-022) ---------------------------------------
def _default_choice(ch: dict, acts: list) -> dict:
    """既定の回答。旧実装の自動選択と同じ結果になるよう選ぶ。

    これにより「選択肢化しただけで挙動は変えていない」ことを既存テストで確認できる。
    """
    kind = ch["kind"]
    if kind == "use_optional":
        return {"type": "use"}                       # 旧: optional は常に実行
    if kind == "reveal_count":
        return {"type": "choose_count", "count": ch["max"]}   # 旧: 常に最大枚数
    if kind in ("discard", "discard_for_effect"):
        return {"type": "discard", "hand": 0}        # 旧: 手札左端
    if kind == "switch_back":
        return {"type": "choose_back", "back": ch["options"][0]}  # 旧: 最初の非空バック
    if kind == "order":
        return {"type": "resolve", "index": 0}
    if kind == "pay_or_damage":
        return {"type": "pay"}
    if kind in ("pay_cost_card", "zone_card", "levelup_by_effect"):
        return next(a for a in acts if a["type"] != "stop")
    raise AssertionError(kind)


def auto(s: GameState, pick=None) -> GameState:
    """Phase.CHOICE が続く限り自動で回答する。

    pick(ch, acts) が None 以外を返した場合はその回答を使う。
    """
    while s.phase == Phase.CHOICE:
        ch = s.pending_choices[0]
        pi = ch["player"]
        acts = legal_actions(s, pi)
        a = pick(ch, acts) if pick is not None else None
        if a is None:
            a = _default_choice(ch, acts)
        s = apply(s, {pi: a})
    return s


def start_game(seed=7) -> GameState:
    s = initial_state(sample_config(), seed)
    s = apply(s, {0: {"type": "setup", "leader": "漂泊者（男）"},
                  1: {"type": "setup", "leader": "散華"}})
    s = apply(s, {0: {"type": "mulligan", "count": 0},
                  1: {"type": "mulligan", "count": 0}})
    return s


# --- §2.2 3すくみ -----------------------------------------------------------
def test_color_triangle():
    assert Color.RED.beats(Color.GREEN)
    assert Color.GREEN.beats(Color.BLUE)
    assert Color.BLUE.beats(Color.RED)
    assert not Color.GREEN.beats(Color.RED)
    assert not Color.RED.beats(Color.RED)


# --- §3 構築ルール ----------------------------------------------------------
def test_deck_validation_rejects_wrong_size():
    cfg = sample_config()
    cfg.action_decks[0] = cfg.action_decks[0][:39]
    with pytest.raises(AssertionError):
        cfg.validate()


def test_deck_validation_rejects_four_chara_species():
    """§3.1-2: キャラはちょうど3種類。4種類以上も構築不成立。

    T-080。ルール保有者の裁定（2026-09-11・D-080）で条文を「必ず3種類」から
    「ちょうど3種類」に明確化した。実装は当初からちょうど3種類を課しており、
    この検査はその条件が緩められないことを守る。

    枚数（3〜15）・同番号1枚まで・各キャラのLv.0投入は満たしたまま、
    種類数だけを4にして弾かれることを確かめる。
    """
    cfg = sample_config()
    # 漂泊者（女）Lv.0 を足す。番号は重複せず、足したキャラのLv.0も揃っている。
    cfg.chara_decks[0] = list(cfg.chara_decks[0]) + ["BP01-018"]
    charas = [CHARA_CARDS[c] for c in cfg.chara_decks[0]]
    assert len({c.name for c in charas}) == 4
    assert 3 <= len(cfg.chara_decks[0]) <= 15
    assert len(cfg.chara_decks[0]) == len(set(cfg.chara_decks[0]))
    with pytest.raises(AssertionError):
        cfg.validate()


# --- §5 準備・§6.2 先攻1ドロー ---------------------------------------------
def test_setup_and_first_draw():
    s = start_game()
    assert s.phase == Phase.ACTION
    assert s.turn_no == 1 and s.turn_player == 0
    # 先攻: 初手5 + 最初のドロー1 = 6 (§6.2)
    assert len(s.players[0].hand) == 6
    # 後攻はまだ5枚
    assert len(s.players[1].hand) == 5
    # ライフ20 (§1)
    assert s.players[0].life == 20 and s.players[1].life == 20


# --- §6.3 アクションフェイズ 1ターン1回 -------------------------------------
def test_charge_once_per_turn():
    s = start_game()
    s = apply(s, {0: {"type": "charge", "hand": 0}})
    assert len(s.players[0].concerto) == 1
    acts = legal_actions(s, 0)
    assert not any(a["type"] == "charge" for a in acts)


# --- §6.4 判定: 一方のみ提出 → 提出側勝利、ダメージはライフ直行 --------------
def _force_clash(s, tp_card=None, ntp_card=None, tp_leader=None, ntp_leader=None):
    """手札を直接差し替えて対抗を1回実行するヘルパ。

    tp_leader / ntp_leader: 専用カードの使用条件(§6.4 使用条件II)を満たすため、
    リーダーポジションのキャラカードを差し替える。"""
    s = s.clone()
    tp, ntp = s.turn_player, 1 - s.turn_player
    if tp_leader:
        s.players[tp].slots[0].stack = [tp_leader]
    if ntp_leader:
        s.players[ntp].slots[0].stack = [ntp_leader]
    if tp_card:
        s.players[tp].hand = [tp_card]
    if ntp_card:
        s.players[ntp].hand = [ntp_card]
    else:
        s.players[ntp].hand = []
    s.players[tp].concerto = ["SD02-007"] * 5
    s.players[ntp].concerto = ["SD02-007"] * 5
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    actions = {tp: {"type": "submit", "hand": 0}}
    actions[ntp] = {"type": "submit", "hand": 0} if ntp_card else {"type": "pass"}
    return auto(apply(s, actions))


def test_unopposed_submit_wins_and_damages_life():
    s = start_game()
    s2 = _force_clash(s, tp_card="SD02-022")  # 音の刃 13/3 赤
    assert s2.last_clash_winner == 0
    assert s2.players[1].life == 20 - 3  # §6.4(2)-4, §1 直接ダメージ


def test_both_pass_is_draw_no_judge_trigger():
    s = start_game()
    s = s.clone()
    s.players[0].hand = []
    s.players[1].hand = []
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    s2 = apply(s, {0: {"type": "pass"}, 1: {"type": "pass"}})
    assert s2.last_clash_winner is None
    assert s2.players[0].life == 20 and s2.players[1].life == 20


# --- §6.4(2)B 異色は3すくみ --------------------------------------------------
def test_color_judge_red_beats_green():
    s = start_game()
    s2 = _force_clash(s, tp_card="SD02-007", ntp_card="SD02-021")  # 赤 vs 緑
    assert s2.last_clash_winner == 0


def test_color_judge_blue_beats_red():
    s = start_game()
    s2 = _force_clash(s, tp_card="SD02-007", ntp_card="SD02-018", ntp_leader="BP01-021")  # 赤 vs 青
    assert s2.last_clash_winner == 1


# --- §6.4(2)C 同色: スピード比較・同値はターンプレイヤー / 青同士引き分け -----
def test_same_red_speed_tiebreak():
    s = start_game()
    s2 = _force_clash(s, tp_card="SD02-007", ntp_card="SD02-022", ntp_leader="BP01-021")  # 赤7 vs 赤13
    assert s2.last_clash_winner == 1
    s3 = _force_clash(s, tp_card="SD02-007", ntp_card="SD02-007")  # 同速
    assert s3.last_clash_winner == 0  # ターンプレイヤー勝利


def test_blue_vs_blue_draw():
    s = start_game()
    s2 = _force_clash(s, tp_card="SD02-018", ntp_card="SD02-018", ntp_leader="BP01-021")
    assert s2.last_clash_winner is None


# --- §6.4(2)-5 連撃: デフォルト0 / 赤勝利は無制限 ----------------------------
def test_rush_default_zero_for_green_win():
    s = start_game()
    # 2026-08-20: SD02-021(鉤縄)は確定テキスト反映で勝利時「ドロー1+追撃2」を持つと
    # 判明したため、このテスト（追撃なしケース）には使えなくなった。
    # SD02-020(スキャン)は勝利時ドロー+情報公開のみで追撃を持たないため代替に使用。
    s2 = _force_clash(s, tp_card="SD02-020")  # 緑で勝利（追撃なし）
    assert s2.last_clash_winner == 0
    # 連撃回数0 → 連撃フェイズに入らずターン終了処理へ
    assert s2.phase != Phase.RUSH


def test_rush_unlimited_for_red_win():
    s = start_game()
    s2 = _force_clash(s, tp_card="SD02-022")  # 赤で勝利
    assert s2.rush_allowance >= RUSH_UNLIMITED - 10 or s2.phase != Phase.RUSH
    if s2.phase == Phase.RUSH:
        acts = legal_actions(s2, 0)
        assert any(a["type"] == "stop" for a in acts)


# --- §7 追撃N ----------------------------------------------------------------
def test_pursuit_grants_rush():
    s = start_game()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-030"]  # リーダー今汐（SD02-010使用条件）
    s2 = _force_clash(s, tp_card="SD02-010")      # 龍憑の天舞: 勝利→3ドロー+追撃8
    assert s2.last_clash_winner == 0
    assert s2.phase == Phase.RUSH
    assert s2.rush_allowance == 8


# --- §6.5 手札上限8 ----------------------------------------------------------
def test_hand_limit_discard():
    s = start_game()
    s = s.clone()
    s.players[0].hand = ["SD02-007"] * 10
    s.players[1].hand = []
    from meicho.engine import _end_turn_begin, _pump
    _end_turn_begin(s)
    _pump(s)
    # 2026-08-20: BP01-021(Lv0)は【対抗】スキルに訂正されたため各ターン終了時の
    # ドローはない（各ターン終了時ドローはLv2のSD02-001に移動, D-009関連の訂正）。
    # 手札は元々10枚で手札上限8を超えているため、そのままTURN_END_DISCARDへ。
    assert s.phase == Phase.TURN_END_DISCARD
    while s.phase == Phase.TURN_END_DISCARD:
        s = apply(s, {0: {"type": "discard", "hand": 0}})
    assert len(s.players[0].hand) == 8
    assert s.turn_player == 1  # 次のターンへ


# --- 直列化 ------------------------------------------------------------------
def test_serialization_roundtrip():
    s = start_game()
    s2 = GameState.from_json(s.to_json())
    assert s2.to_json() == s.to_json()


# --- 観測: 相手の手札・デッキ順序が見えない ----------------------------------
def test_observation_hides_private_info():
    s = start_game()
    ob = observe(s, 0)
    assert "hand" not in ob["opp"]
    assert ob["opp"]["hand_count"] == len(s.players[1].hand)


# --- 2026-08-20 SD02反映: D-009 専用キャラ/リーダースキル分離のバグ修正回帰テスト ---
def test_dedicated_card_usable_without_matching_leader():
    """D-009: 専用カードでも「リーダースキル」未指定ならリーダー不問で使用できる。

    旧実装のバグ: leader_lock(=専用キャラ名)を持つだけで一律リーダー一致を要求していた。
    SD02-018(音の形・回避)は漂泊者（男）専用だがリーダースキルは持たない。
    """
    s = start_game()
    s2 = _force_clash(s, tp_card="SD02-018", tp_leader="BP01-030")  # リーダーは今汐
    assert s2.last_clash_winner == 0


def test_leader_skill_card_unusable_without_matching_leader():
    """D-009: 「リーダースキル」が明記されたカードは対応リーダーでないと提出できない。"""
    s = start_game()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-030"]  # リーダー今汐（SD02-022は漂泊者男専用+リーダースキル）
    s.players[0].hand = ["SD02-022"]
    s.players[0].concerto = ["SD02-007"] * 5
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    acts = legal_actions(s, 0)
    assert not any(a["type"] == "submit" for a in acts)
    assert any(a["type"] == "pass" for a in acts)


def test_dodge_action_card_draws_and_discards():
    """SD02-018(音の形・回避): 確定テキストは勝利時ドロー1+捨て札1（旧unverified推測はドローのみだった）。
    捨て札は D-004 の簡略化により手札左端から自動選択。"""
    s = start_game()
    s = s.clone()
    before_deck = len(s.players[0].action_deck)
    s2 = _force_clash(s, tp_card="SD02-018")
    assert s2.last_clash_winner == 0
    assert len(s2.players[0].action_deck) == before_deck - 1  # ドロー1枚
    assert len(s2.players[0].hand) == 0  # ドロー直後に同じ1枚を捨てるため手札は空
    # SD02-018はBLUEで追撃なし→_force_clash内でターン終了処理まで進む。
    # 使用したカード自体もアクションエリア→トラッシュへ移動する。
    assert "SD02-018" in s2.players[0].trash


def test_forbid_rush_next_turn():
    """SD02-016(赤瞳凍土): 判定勝利で「次のターン中、相手は連撃できない」を予約する。"""
    s = start_game()
    s2 = _force_clash(s, tp_card="SD02-016", tp_leader="BP01-033")  # リーダー散華
    assert s2.last_clash_winner == 0
    assert s2.pending_rush_forbidden[1] is True
    if s2.phase == Phase.RUSH:
        s2 = apply(s2, {0: {"type": "stop"}})
    assert s2.turn_player == 1
    assert s2.rush_forbidden[1] is True
    # 相手(P1)が赤カードで判定勝利しても、連撃の選択肢が出ない
    s3 = _force_clash(s2, tp_card="SD02-007")
    assert s3.last_clash_winner == 1
    acts = legal_actions(s3, 1)
    assert not any(a["type"] == "rush" for a in acts)
    assert any(a["type"] == "stop" for a in acts)


def test_action_area_count_condition_grants_bonus_damage():
    """SD02-011(邪を潰す歳月の重さ): 自分のアクションエリアが3枚以上で連撃ダメージ+3。"""
    from meicho.engine import _do_rush, _pump
    s = start_game()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-030"]  # リーダー今汐（leader_skill要件）
    s.players[0].action_area = ["SD02-007", "SD02-007"]  # 場に既に2枚 → このカードで3枚目
    s.players[0].hand = ["SD02-011"]
    s.players[0].concerto = ["SD02-007"] * 5
    life_before = s.players[1].life
    _do_rush(s, 0, 0)
    _pump(s)
    assert life_before - s.players[1].life == 5 + 3  # 基礎ダメージ5 + 条件成立ボーナス3


def test_action_area_count_condition_not_met_no_bonus():
    from meicho.engine import _do_rush, _pump
    s = start_game()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-030"]
    s.players[0].action_area = []  # このカードで1枚目のみ → 条件不成立
    s.players[0].hand = ["SD02-011"]
    s.players[0].concerto = ["SD02-007"] * 5
    life_before = s.players[1].life
    _do_rush(s, 0, 0)
    _pump(s)
    assert life_before - s.players[1].life == 5


def test_sd02_decklist_validates():
    """decklists/SD02.json（マスター確定分）が構築ルール(§3)を満たすことを確認。"""
    path = os.path.join(os.path.dirname(__file__), "..", "decklists", "SD02.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    assert len(d["chara_deck"]) == 9
    assert len(d["action_deck"]) == 40
    cfg = GameConfig(
        chara_decks=[d["chara_deck"], d["chara_deck"]],
        action_decks=[d["action_deck"], d["action_deck"]],
    )
    cfg.validate()  # 例外が出なければ構築ルール§3を満たす


def test_level0_and_level2_skills_not_swapped():
    """2026-08-20訂正の回帰防止: 漂泊者（男）・散華・今汐でLv0/Lv2のスキルが入れ替わっていた
    登録ミスを訂正済み（マスター確認）。Lv0は【対抗】、Lv2は【各ターン終了時】/【常在】。"""
    from meicho.cards import CHARA_CARDS
    from meicho.cards import Timing as T
    assert CHARA_CARDS["BP01-021"].skills[0].timing == T.CLASH
    assert CHARA_CARDS["SD02-001"].skills[0].timing == T.TURN_END
    assert CHARA_CARDS["BP01-033"].skills[0].timing == T.CLASH
    assert CHARA_CARDS["SD02-003"].skills[0].timing == T.TURN_END
    assert CHARA_CARDS["BP01-030"].skills[0].timing == T.CLASH
    assert CHARA_CARDS["SD02-005"].skills[0].timing == T.STATIC


# ===========================================================================
# 2026-08-21 SD001反映: 新裁定 D-011〜D-016 と新規オペコードの回帰テスト
# 対応 rules_draft.md バージョン: v0.10
# ===========================================================================

def sd001_config() -> GameConfig:
    """SD001（漂泊者（女）・秧秧・熾霞）実デッキの構成。"""
    path = os.path.join(os.path.dirname(__file__), "..", "decklists", "SD001.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return GameConfig(
        chara_decks=[list(d["chara_deck"]), list(d["chara_deck"])],
        action_decks=[list(d["action_deck"]), list(d["action_deck"])],
    )


def start_sd001(seed=11) -> GameState:
    s = initial_state(sd001_config(), seed)
    s = apply(s, {0: {"type": "setup", "leader": "漂泊者（女）"},
                  1: {"type": "setup", "leader": "漂泊者（女）"}})
    s = apply(s, {0: {"type": "mulligan", "count": 0},
                  1: {"type": "mulligan", "count": 0}})
    return s


def _sd001_clash(s, tp_card=None, ntp_card=None, tp_stack=None, ntp_stack=None,
                 tp_concerto=5, ntp_concerto=5, choices=None, auto_choices=True):
    """SD001カードで対抗を1回実行するヘルパ（_force_clash のSD001版）。"""
    s = s.clone()
    tp, ntp = s.turn_player, 1 - s.turn_player
    if tp_stack:
        s.players[tp].slots[0].stack = list(tp_stack)
    if ntp_stack:
        s.players[ntp].slots[0].stack = list(ntp_stack)
    s.players[tp].hand = [tp_card] if tp_card else []
    s.players[ntp].hand = [ntp_card] if ntp_card else []
    s.players[tp].concerto = ["SD01-017"] * tp_concerto
    s.players[ntp].concerto = ["SD01-017"] * ntp_concerto
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    actions = {
        tp: {"type": "submit", "hand": 0} if tp_card else {"type": "pass"},
        ntp: {"type": "submit", "hand": 0} if ntp_card else {"type": "pass"},
    }
    s2 = apply(s, actions)
    if not auto_choices:
        return s2                       # 選択待ちのまま返す（選択自体を検証するテスト用）
    return auto(s2, choices)


# --- §3 SD001デッキリスト -----------------------------------------------------
def test_sd001_decklist_validates():
    """decklists/SD001.json（マスター確定分）が構築ルール(§3)を満たすことを確認。"""
    path = os.path.join(os.path.dirname(__file__), "..", "decklists", "SD001.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    assert len(d["chara_deck"]) == 9
    assert len(d["action_deck"]) == 40
    sd001_config().validate()


def test_sd001_deck_color_distribution():
    """マスター指定: 赤はすべて2枚、青と緑はすべて3枚。合計40枚。"""
    from collections import Counter
    from meicho.cards import ACTION_CARDS as AC
    path = os.path.join(os.path.dirname(__file__), "..", "decklists", "SD001.json")
    with open(path, encoding="utf-8") as f:
        deck = json.load(f)["action_deck"]
    counts = Counter(deck)
    for cid, n in counts.items():
        expected = 2 if AC[cid].color == Color.RED else 3
        assert n == expected, f"{cid} は{expected}枚のはずが{n}枚"
    assert len(deck) == 40


def test_sd001_level0_and_level2_skills_not_swapped():
    """SD02で発生したLv0/Lv2入れ替わり登録ミスがSD001で起きていないことの確認。
    Lv0は全キャラ【対抗】。Lv2はキャラごとに異なる（常時系または【対抗】）。"""
    from meicho.cards import CHARA_CARDS, Timing as T
    for cid in ("BP01-018", "BP01-024", "BP01-027"):
        assert CHARA_CARDS[cid].level == 0
        assert CHARA_CARDS[cid].skills[0].timing == T.CLASH
    for cid in ("SD01-002", "SD01-004", "SD01-006"):
        assert CHARA_CARDS[cid].skills[0].timing == T.JUDGE
    assert CHARA_CARDS["SD01-001"].skills[0].timing == T.TURN_START
    assert CHARA_CARDS["SD01-003"].skills[0].timing == T.CLASH   # Lv2で【対抗】の初例
    assert CHARA_CARDS["SD01-005"].skills[0].timing == T.STATIC


# --- D-013 キャラカードのタグ（所属/属性/武器種）------------------------------
def test_chara_card_tags_three_systems():
    """D-013: キャラタグは 所属勢力/属性/武器種 の3系統。漂泊者は所属タグを持たない。
    SD02側は当初 ("瑝瓏",) のみで登録されており不完全だった（2026-08-21 訂正）。"""
    from meicho.cards import CHARA_CARDS
    expected = {
        "漂泊者（男）": ("回折", "迅刀"),
        "漂泊者（女）": ("回折", "迅刀"),
        "散華": ("瑝瓏", "凝縮", "迅刀"),
        "今汐": ("瑝瓏", "回折", "長刃"),
        "秧秧": ("瑝瓏", "気動", "迅刀"),
        "熾霞": ("瑝瓏", "焦熱", "拳銃"),
    }
    for c in CHARA_CARDS.values():
        if c.name in expected:
            assert c.tags == expected[c.name], f"{c.card_id} {c.name} のタグ"
    # 漂泊者は所属タグを持たない
    for c in CHARA_CARDS.values():
        if c.name.startswith("漂泊者"):
            assert "瑝瓏" not in c.tags


# --- D-011 ライフ上限20 --------------------------------------------------------
def test_heal_self_below_cap():
    """SD01-023(奏鳴・女): 判定勝利で自分のライフ5回復。"""
    s = start_sd001()
    s = s.clone()
    s.players[0].life = 10
    s2 = _sd001_clash(s, tp_card="SD01-023", tp_stack=["BP01-018"])
    assert s2.last_clash_winner == 0
    assert s2.players[0].life == 15


def test_heal_self_clipped_at_max_life():
    """D-011: 回復はライフ上限20を超えない（マスター裁定 2026-08-21）。"""
    from meicho.state import MAX_LIFE
    s = start_sd001()
    s = s.clone()
    s.players[0].life = 18
    s2 = _sd001_clash(s, tp_card="SD01-023", tp_stack=["BP01-018"])
    assert s2.players[0].life == MAX_LIFE == 20


# --- D-012 追撃の加算 ----------------------------------------------------------
def test_pursuit_accumulates_across_triggers():
    """D-012: 「追撃N」は複数回発動すると加算される（上書きではない）。
    旧実装は max() による上書きだった（マスター指摘 2026-08-21）。"""
    from meicho.engine import _run_effects
    s = start_sd001()
    s = s.clone()
    s.rush_allowance = 0
    _run_effects(s, 0, (("pursuit", {"count": 2}),), {})
    _run_effects(s, 0, (("pursuit", {"count": 1}),), {})
    assert s.rush_allowance == 3


def test_pursuit_accumulates_from_chara_and_action_card():
    """キャラスキルとアクションカードの追撃が同一判定で重なった場合も加算される。
    SD01-021(鉤縄, 追撃2) + テスト用キャラカード(追撃1) = 3。"""
    from meicho.cards import CHARA_CARDS, CharaCard, Skill, Timing as T
    CHARA_CARDS["TEST-C-PURSUIT"] = CharaCard(
        "TEST-C-PURSUIT", "テスト追撃", level=0,
        skills=(Skill(T.JUDGE, (("pursuit", {"count": 1}),),
                      condition={"self_result": "win"}),),
    )
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-021", tp_stack=["TEST-C-PURSUIT"])
    assert s2.last_clash_winner == 0
    assert s2.rush_allowance == 3   # 鉤縄の追撃2 + キャラの追撃1


# --- D-014 「自分のターン開始時」 ----------------------------------------------
def test_own_turn_start_fires_only_for_turn_player():
    """D-014: SD01-001(漂泊者（女）Lv2)は「自分のターン開始時」に1ドロー。
    条件 is_turn_player により、相手のターン開始時には誘発しない。"""
    from meicho.engine import _begin_turn, _pump
    s = start_sd001()
    s = s.clone()
    stack = ["BP01-018", "SD01-002", "SD01-001"]
    s.players[0].slots[0].stack = list(stack)
    s.players[1].slots[0].stack = list(stack)
    s.turn_player = 0
    before = [len(s.players[i].hand) for i in (0, 1)]
    _begin_turn(s)
    _pump(s)
    # ターンプレイヤー(P0)のみ +1（さらに§6.2のドロー2枚が乗る）
    assert len(s.players[0].hand) == before[0] + 1 + 2
    assert len(s.players[1].hand) == before[1]


def test_own_turn_start_fires_from_back_slot():
    """SD01-001 は leader_only=False。後衛ポジションでも誘発する
    （本プロジェクト初のリーダー限定でないキャラスキル）。"""
    from meicho.engine import _begin_turn, _pump
    s = start_sd001()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-024"]                      # リーダーは秧秧
    s.players[0].slots[1].stack = ["BP01-018", "SD01-002", "SD01-001"]  # 後衛に漂泊者（女）Lv2
    s.turn_player = 0
    before = len(s.players[0].hand)
    _begin_turn(s)
    _pump(s)
    assert len(s.players[0].hand) == before + 1 + 2


# --- D-015 相手に選択を要求する効果（秧秧Lv2）----------------------------------
# D-062 (2026-08-31): 発動条件を訂正した。カードテキストは
# 「【対抗】**相手が**赤色のカードで対抗した場合」であり、秧秧側が赤を出したときではない。
# したがって以下のテストはすべて「非ターンプレイヤー(P1)が赤を出し、
# 秧秧Lv2 をリーダーに持つターンプレイヤー(P0)の【対抗】が誘発する」形で書く。
# P1 のリーダーは BP01-018（漂泊者（女）Lv0・緑条件）に固定する。
# 熾霞Lv0 が来ると「自分が赤で対抗→相手にダメージ1」が余計に乗り、
# ライフの検算が読めなくなるためである。
_YY_LV2 = ["BP01-024", "SD01-004", "SD01-003"]   # P0: 秧秧 Lv0→Lv2（最上段がリーダー）
_NEUTRAL = ["BP01-018"]                            # P1: 漂泊者（女）Lv0（赤には反応しない）


def _yy_lv2_clash(s, *, ntp_concerto=5, auto_choices=False):
    """P1 が赤（羽の刃・通常攻撃 SD01-012）で対抗し、P0 は提出しない局面を作る。"""
    return _sd001_clash(s, ntp_card="SD01-012",
                        tp_stack=_YY_LV2, ntp_stack=_NEUTRAL,
                        ntp_concerto=ntp_concerto, auto_choices=auto_choices)


def test_opponent_choice_pay_option():
    """SD01-003(秧秧Lv2): 【対抗】**相手が**赤で対抗すると、その相手が
    「コスト1を支払う」を選べる。支払うとダメージ3を受けない。"""
    s = start_sd001()
    s2 = _yy_lv2_clash(s)
    assert s2.phase == Phase.CHOICE
    assert decision_players(s2) == [1]
    acts = legal_actions(s2, 1)
    assert {a["type"] for a in acts} == {"pay", "decline"}
    concerto_before = len(s2.players[1].concerto)
    s3 = apply(s2, {1: {"type": "pay"}})
    assert len(s3.players[1].concerto) == concerto_before - 1
    # 判定へ復帰: P1の一方提出勝利。P0 が羽の刃のダメージ1を受ける。
    # P1 は支払ったので3ダメージを受けない。
    assert s3.last_clash_winner == 1
    assert s3.players[1].life == 20
    assert s3.players[0].life == 20 - 1


def test_opponent_choice_decline_option():
    """支払わなければダメージ3を受ける。"""
    s = start_sd001()
    s2 = _yy_lv2_clash(s)
    concerto_before = len(s2.players[1].concerto)
    s3 = apply(s2, {1: {"type": "decline"}})
    assert len(s3.players[1].concerto) == concerto_before
    assert s3.last_clash_winner == 1
    assert s3.players[1].life == 20 - 3      # 選択によるダメージ3
    assert s3.players[0].life == 20 - 1      # 対抗カードのダメージ1


def test_opponent_choice_skipped_when_cannot_pay():
    """協奏エリアが空で支払えない場合は選択させず、自動的にダメージ3
    （マスター確認済み 2026-08-21）。"""
    s = start_sd001()
    s2 = _yy_lv2_clash(s, ntp_concerto=0)
    assert s2.phase != Phase.CHOICE
    assert not s2.pending_choices
    assert s2.players[1].life == 20 - 3


def test_yangyang_lv2_does_not_fire_on_own_red():
    """D-062 の回帰テスト: **自分**が赤で対抗しても誘発しない。

    訂正前は self_color=RED で登録されており、この局面で誤って誘発していた。
    ここでは P0（秧秧Lv2）が赤を出し、P1 は提出しない。
    """
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-012",
                      tp_stack=_YY_LV2, ntp_stack=_NEUTRAL,
                      auto_choices=False)
    assert s2.phase != Phase.CHOICE
    assert not s2.pending_choices
    assert s2.players[1].life == 20 - 1      # 羽の刃のダメージ1のみ。3ダメージは無い


def test_yangyang_lv2_does_not_fire_on_opponent_non_red():
    """D-062 の回帰テスト: 相手が赤以外（緑）で対抗した場合も誘発しない。

    P1 のリーダー漂泊者（女）Lv0 が「緑で対抗したらデッキ上2枚まで公開」を持つため
    別の選択（reveal_count）は立つ。ここで見たいのは
    「pay_or_damage が立たないこと」なので、種類で判定する。
    """
    s = start_sd001()
    s2 = _sd001_clash(s, ntp_card="SD01-020",   # スキャン（緑）
                      tp_stack=_YY_LV2, ntp_stack=_NEUTRAL,
                      auto_choices=False)
    assert all(ch["kind"] != "pay_or_damage" for ch in s2.pending_choices)
    s3 = auto(s2)
    assert s3.players[1].life == 20          # 3ダメージは受けていない


def test_choice_state_survives_serialization():
    """選択待ち状態も JSON 直列化可能であること（作業規約2）。"""
    s = start_sd001()
    s2 = _yy_lv2_clash(s)
    assert s2.phase == Phase.CHOICE
    assert GameState.from_json(s2.to_json()).to_json() == s2.to_json()


def test_choice_is_hidden_from_the_other_player():
    """observe(): 相手宛の選択は見えない。"""
    s = start_sd001()
    s2 = _yy_lv2_clash(s)
    assert observe(s2, 1)["pending_choice"]["kind"] == "pay_or_damage"
    assert observe(s2, 0)["pending_choice"] is None


# --- 旋風: 次のターン中、相手の赤カードのコスト+1 ------------------------------
def test_red_cost_up_next_turn():
    """SD01-016(旋風): 判定勝利で「次のターン中、相手の赤色のカードのコスト+1」。"""
    from meicho.engine import _effective_cost
    from meicho.cards import ACTION_CARDS as AC
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-016",
                      tp_stack=["BP01-024", "SD01-004", "SD01-003"])
    # 秧秧Lv2の【対抗】選択が挟まる場合は先に解決する（D-015）。
    # D-062 の訂正後、この局面（自分が赤で対抗）では誘発しないが、
    # 保険として残す。
    if s2.phase == Phase.CHOICE:
        s2 = apply(s2, {1: {"type": "pay"}})
    assert s2.last_clash_winner == 0
    assert s2.pending_red_cost_up[1] is True
    while s2.phase == Phase.RUSH:
        s2 = apply(s2, {s2.clash_winner: {"type": "stop"}})
    assert s2.turn_player == 1
    assert s2.red_cost_up[1] is True
    # P1の赤カードは+1、緑・青は据え置き
    assert _effective_cost(s2, 1, AC["SD01-012"]) == AC["SD01-012"].cost + 1
    assert _effective_cost(s2, 1, AC["SD01-020"]) == AC["SD01-020"].cost
    # 効果を受けていないP0は据え置き
    assert _effective_cost(s2, 0, AC["SD01-012"]) == AC["SD01-012"].cost


def test_red_cost_up_blocks_submission_without_concerto():
    """コスト+1により、協奏エリアが空だとコスト0の赤カードすら提出できなくなる。"""
    s = start_sd001()
    s = s.clone()
    s.red_cost_up[0] = True
    s.players[0].hand = ["SD01-012"]   # 赤・素コスト0
    s.players[0].concerto = []
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    acts = legal_actions(s, 0)
    assert not any(a["type"] == "submit" for a in acts)
    assert any(a["type"] == "pass" for a in acts)


# --- D-016 「次のターン中」効果は1ターンだけ持続する ---------------------------
def test_next_turn_effect_lasts_exactly_one_turn():
    """D-016: 旧実装はターンプレイヤー分だけを更新していたため、効果が
    「次のターン」を越えてその次のターンまで残っていた。両プレイヤー分を
    毎ターン更新することで、発動は次の1ターンのみになる。"""
    from meicho.engine import _begin_turn, _pump
    s = start_sd001()
    s = s.clone()
    s.pending_rush_forbidden[1] = True
    s.pending_red_cost_up[1] = True
    s.turn_player = 1
    _begin_turn(s)                      # P1のターン: 発動
    assert s.rush_forbidden[1] is True
    assert s.red_cost_up[1] is True
    s.turn_player = 0
    _begin_turn(s)                      # 次のP0のターン: 解除されている
    assert s.rush_forbidden[1] is False
    assert s.red_cost_up[1] is False


# --- 燃える闘志: アクションエリアからカードを手札に戻す ------------------------
def test_return_clash_card_to_hand_on_loss_to_blue():
    """SD01-010(燃える闘志): 赤で青に敗北した場合、このカードを手札に戻せる。
    本プロジェクト初の「アクションエリアからカードを取り除く」効果。"""
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-010", ntp_card="SD01-018",
                      tp_stack=["BP01-027", "SD01-006", "SD01-005"])
    assert s2.last_clash_winner == 1                      # 青は赤に勝つ (§6.4(1)-1-B)
    assert "SD01-010" in s2.players[0].hand              # 手札に戻っている
    assert "SD01-010" not in s2.players[0].action_area
    assert "SD01-010" not in s2.players[0].trash         # トラッシュへ送られていない


def test_return_to_hand_does_not_break_opponent_condition():
    """カードを手札へ戻しても s.clash_cards は据え置くため、
    後から誘発する相手の opp_color 条件が壊れない。"""
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-010", ntp_card="SD01-018",
                      tp_stack=["BP01-027", "SD01-006", "SD01-005"])
    assert s2.last_clash_cards[0] == "SD01-010"
    assert s2.last_clash_cards[1] == "SD01-018"


# --- 熾霞Lv2: 対抗・連撃の両方にダメージ+3 -------------------------------------
def test_chixia_lv2_buff_applies_to_clash_damage():
    """SD01-005(熾霞Lv2): カードテキストに【連撃】の限定がないため、
    対抗ステップのダメージにも+3される（今汐Lv2 SD02-005 は【連撃】限定で異なる）。"""
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-011",
                      tp_stack=["BP01-027", "SD01-006", "SD01-005"])
    assert s2.last_clash_winner == 0
    # 熾霞Lv0の【対抗】ダメージ1 + 燃える烈火 7 + 熾霞Lv2の+3 = 11
    assert s2.players[1].life == 20 - (1 + 7 + 3)


def test_chixia_lv2_buff_applies_to_rush_damage():
    from meicho.engine import _do_rush, _pump
    s = start_sd001()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-027", "SD01-006", "SD01-005"]
    s.players[0].hand = ["SD01-010"]      # 燃える闘志 ダメージ2
    s.players[0].concerto = ["SD01-017"] * 5
    life_before = s.players[1].life
    _do_rush(s, 0, 0)
    _pump(s)
    assert life_before - s.players[1].life == 2 + 3


def test_chixia_lv2_buff_does_not_apply_to_non_leader_skill_cards():
    """対象は「リーダースキルを持つ熾霞専用カード」のみ。
    SD01-007(ババン・通常攻撃)は leader_skill=False のため加算されない。"""
    from meicho.engine import _do_rush, _pump
    s = start_sd001()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-027", "SD01-006", "SD01-005"]
    s.players[0].hand = ["SD01-007"]      # ダメージ1・リーダースキルなし
    s.players[0].concerto = ["SD01-017"] * 5
    life_before = s.players[1].life
    _do_rush(s, 0, 0)
    _pump(s)
    assert life_before - s.players[1].life == 1


def test_imbi_lv2_buff_still_rush_only():
    """回帰防止: 今汐Lv2(SD02-005)の rush_damage_buff は【連撃】限定のままであり、
    対抗ステップのダメージには乗らない。"""
    s = start_game()
    s = s.clone()
    s.players[0].slots[0].stack = ["SD02-005"]   # 今汐Lv2をリーダーに
    s2 = _force_clash(s, tp_card="SD02-007")     # 寒風散らす光・通常攻撃 赤/0/7/1
    assert s2.last_clash_winner == 0
    assert s2.players[1].life == 20 - 1          # +1されない


# --- §9-5 / D-021 進行不能状態は引き分け ---------------------------------------
def test_deadlock_is_a_draw():
    """§9-5: デッキ・手札・トラッシュ・アクションエリアが双方とも尽きた状態は
    どちらも盤面を変化させられないため引き分けとする（マスター裁定 2026-08-21）。"""
    from meicho.engine import _begin_turn, _pump
    from meicho.state import DRAW
    s = start_sd001()
    s = s.clone()
    for p in s.players:
        p.concerto = p.concerto + p.hand + p.action_deck + p.trash + p.action_area
        p.hand, p.action_deck, p.trash, p.action_area = [], [], [], []
    s.turn_player = 0
    _begin_turn(s)
    _pump(s)
    assert s.phase == Phase.GAME_OVER
    assert outcome(s) == DRAW
    assert decision_players(s) == []


def test_not_deadlocked_while_one_player_has_cards():
    """片方にカードが残っていれば進行可能なので引き分けにしない。"""
    from meicho.engine import _begin_turn, _pump
    s = start_sd001()
    s = s.clone()
    for p in s.players:
        p.concerto = p.concerto + p.hand + p.action_deck + p.trash + p.action_area
        p.hand, p.action_deck, p.trash, p.action_area = [], [], [], []
    s.players[1].action_deck = ["SD01-017"]   # P1にだけデッキが残っている
    s.turn_player = 0
    _begin_turn(s)
    _pump(s)
    assert s.phase == Phase.ACTION
    assert outcome(s) is None


def test_runner_reports_draw_not_as_a_win():
    """runner は引き分けを winner=None / draw=True で報告する（D-021）。

    進行不能状態はランダム自己対戦ではまず起きないため、
    その一歩手前の局面を作って play_game に渡し、報告のされ方を確認する。
    """
    from meicho.runner import play_game
    from meicho.agents import RandomAgent
    s = start_sd001()
    s = s.clone()
    for p in s.players:
        p.concerto = p.concerto + p.hand + p.action_deck + p.trash + p.action_area
        p.hand, p.action_deck, p.trash, p.action_area = [], [], [], []
    s.phase = Phase.ACTION
    r = play_game(sd001_config(), [RandomAgent(1), RandomAgent(2)], seed=0, initial=s)
    assert r["draw"] is True
    assert r["winner"] is None
    assert r["aborted"] is False


def test_runner_reports_draw_false_for_decided_game():
    from meicho.runner import play_game
    from meicho.agents import RandomAgent
    r = play_game(sd001_config(), [RandomAgent(1), RandomAgent(2)], seed=3)
    assert r["aborted"] is False
    assert r["draw"] is False
    assert r["winner"] in (0, 1)


# ===========================================================================
# 2026-08-21 簡略化の解消 (D-022 / D-023)
# SIMPLIFICATIONS.md の A-1〜A-7 / C-1 に対応する回帰テスト
# ===========================================================================

# --- A-5 switch_leader のバックポジション選択 ---------------------------------
def _leader_name_of(s, pi):
    from meicho.cards import CHARA_CARDS
    return CHARA_CARDS[s.players[pi].slots[0].stack[-1]].name


def _rush_with_two_backs(s, card, back):
    """バック2枠が埋まった状態で変奏スキルを連撃し、切り替え先を選ぶ。"""
    from meicho.engine import _do_rush, _pump
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-018"]   # リーダー 漂泊者（女）
    s.players[0].slots[1].stack = ["BP01-024"]   # バック1 秧秧
    s.players[0].slots[2].stack = ["BP01-027"]   # バック2 熾霞
    s.players[0].hand = [card]
    s.players[0].concerto = ["SD01-017"] * 5
    s.phase = Phase.RUSH
    s.clash_winner = 0
    s.rush_allowance = 3
    _do_rush(s, 0, 0)
    _pump(s)
    assert s.phase == Phase.CHOICE
    ch = s.pending_choices[0]
    assert ch["kind"] == "switch_back" and ch["options"] == [1, 2]
    return apply(s, {0: {"type": "choose_back", "back": back}})


def test_switch_leader_back_choice_is_offered():
    """A-5: バックが2枠とも埋まっているとき、どちらをリーダーにするか選べる。"""
    s = start_sd001()
    s2 = _rush_with_two_backs(s, "SD01-009", back=2)
    assert _leader_name_of(s2, 0) == "熾霞"


def test_switch_leader_choice_changes_bonus():
    """A-5: 選んだバックによって変奏スキルのボーナスの成否が変わる。

    SD01-009「躍動する炎」は熾霞に切り替わった場合のみダメージ+2。
    旧実装は backs[0] 固定だったため、この違いを表現できなかった。
    """
    s = start_sd001()
    hit = _rush_with_two_backs(s, "SD01-009", back=2)   # 熾霞へ切り替え
    miss = _rush_with_two_backs(s, "SD01-009", back=1)  # 秧秧へ切り替え
    assert 20 - hit.players[1].life == 2      # 素のダメージ0 + ボーナス2
    assert 20 - miss.players[1].life == 0     # ボーナスなし


def test_switch_leader_no_choice_with_single_back():
    """バックが1枠しか埋まっていなければ選択は発生しない。"""
    from meicho.engine import _do_rush, _pump
    s = start_sd001()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-018"]
    s.players[0].slots[1].stack = ["BP01-027"]
    s.players[0].slots[2].stack = []
    s.players[0].hand = ["SD01-009"]
    s.players[0].concerto = ["SD01-017"] * 5
    s.phase, s.clash_winner, s.rush_allowance = Phase.RUSH, 0, 3
    _do_rush(s, 0, 0)
    _pump(s)
    assert s.phase != Phase.CHOICE
    assert 20 - s.players[1].life == 2


# --- A-1 「〜してもよい」の実行可否 -------------------------------------------
def test_optional_skill_can_be_skipped():
    """A-1: optional なスキルは実行しない選択ができる。

    SD01-006（熾霞Lv1）: 赤で青に敗北した場合、デッキ上1枚を手札に加えて**もよい**。
    """
    s = start_sd001()
    skip = _sd001_clash(s, tp_card="SD01-007", ntp_card="SD01-018",
                        tp_stack=["BP01-027", "SD01-006"],
                        choices=lambda ch, acts:
                            {"type": "skip"} if ch["kind"] == "use_optional" else None)
    use = _sd001_clash(s, tp_card="SD01-007", ntp_card="SD01-018",
                       tp_stack=["BP01-027", "SD01-006"],
                       choices=lambda ch, acts:
                           {"type": "use"} if ch["kind"] == "use_optional" else None)
    assert skip.last_clash_winner == 1 and use.last_clash_winner == 1
    # 使った側だけ手札が1枚多い
    assert len(use.players[0].hand) == len(skip.players[0].hand) + 1


def test_optional_choice_is_offered_to_the_skill_owner():
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-007", ntp_card="SD01-018",
                      tp_stack=["BP01-027", "SD01-006"], auto_choices=False)
    assert s2.phase == Phase.CHOICE
    ch = s2.pending_choices[0]
    assert ch["kind"] == "use_optional" and ch["player"] == 0
    assert ch["card"] == "SD01-006"
    assert {a["type"] for a in legal_actions(s2, 0)} == {"use", "skip"}


# --- A-2 「N枚まで」の枚数選択 -------------------------------------------------
def test_reveal_up_to_count_is_chosen():
    """A-2: 漂泊者Lv0の「デッキの上から2枚まで」は0〜2枚から選べる。"""
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-020", tp_stack=["BP01-018"],
                      auto_choices=False)
    assert s2.phase == Phase.CHOICE
    ch = s2.pending_choices[0]
    assert ch["kind"] == "reveal_count" and ch["max"] == 2
    assert [a["count"] for a in legal_actions(s2, 0)] == [0, 1, 2]

    def pick(n):
        return lambda ch, acts: ({"type": "choose_count", "count": n}
                                 if ch["kind"] == "reveal_count" else None)
    zero = _sd001_clash(s, tp_card="SD01-020", tp_stack=["BP01-018"], choices=pick(0))
    two = _sd001_clash(s, tp_card="SD01-020", tp_stack=["BP01-018"], choices=pick(2))
    # スキャン自身の【判定】ドロー1は共通。差は0枚と2枚の分だけ。
    assert len(zero.players[0].action_deck) - len(two.players[0].action_deck) == 2


# --- A-4 効果による捨て札の選択 ------------------------------------------------
def test_discard_self_lets_the_owner_choose():
    """A-4: SD01-018（音の形・回避）の「手札1枚を捨てる」は捨てる札を選べる。"""
    s = start_sd001()
    s = s.clone()
    s.players[0].hand = ["SD01-018", "SD01-011", "SD01-022"]
    s.players[1].hand = []
    s.players[0].concerto = ["SD01-017"] * 5
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    s2 = apply(s, {0: {"type": "submit", "hand": 0}, 1: {"type": "pass"}})
    assert s2.phase == Phase.CHOICE
    ch = s2.pending_choices[0]
    assert ch["kind"] == "discard_for_effect" and ch["player"] == 0
    hand = list(s2.players[0].hand)
    # 引いたカードではなく、手札にある「燃える烈火」を残して別の札を捨てられる
    idx = hand.index("SD01-022")
    s3 = auto(apply(s2, {0: {"type": "discard", "hand": idx}}))
    assert "SD01-022" in s3.players[0].trash
    assert "SD01-011" in s3.players[0].hand


# --- A-3 レベルアップの手札コストの選択 ----------------------------------------
def test_levelup_hand_cost_is_chosen():
    """A-3: §6.3-3 のレベルアップで捨てる手札を選べる。"""
    s = start_sd001()
    s = s.clone()
    s.players[0].hand = ["SD01-011", "SD01-022"]
    s.phase = Phase.ACTION
    s.turn_player = 0
    s2 = apply(s, {0: {"type": "levelup", "slot": 0, "card": "SD01-002"}})
    assert s2.phase == Phase.CHOICE
    ch = s2.pending_choices[0]
    assert ch["kind"] == "discard" and ch["reason"] == "levelup"
    s3 = apply(s2, {0: {"type": "discard", "hand": 1}})
    assert s3.phase == Phase.ACTION
    assert s3.players[0].hand == ["SD01-011"]
    assert "SD01-022" in s3.players[0].trash
    assert s3.players[0].slots[0].stack[-1] == "SD01-002"


# --- A-6 マリガンの任意部分集合 ------------------------------------------------
def test_mulligan_allows_arbitrary_subset():
    """A-6: §5-5 のマリガンは任意の部分集合を戻せる（旧: 左端からn枚）。"""
    s = initial_state(sd001_config(), 5)
    s = apply(s, {0: {"type": "setup", "leader": "漂泊者（女）"},
                  1: {"type": "setup", "leader": "漂泊者（女）"}})
    acts = legal_actions(s, 0)
    assert len(acts) == 2 ** len(s.players[0].hand) == 32
    assert {"type": "mulligan", "cards": [1, 3]} in acts
    keep = [s.players[0].hand[i] for i in (0, 2, 4)]
    s2 = apply(s, {0: {"type": "mulligan", "cards": [1, 3]},
                   1: {"type": "mulligan", "cards": []}})
    # 戻さなかった3枚はそのまま手札に残っている
    for cid in keep:
        assert cid in s2.players[0].hand
    assert len(s2.players[0].hand) == 5 + 1   # 先攻の§6.2ドロー1枚を含む
    assert len(s2.players[1].hand) == 5


# --- A-7 同時誘発スキルの解決順序 ----------------------------------------------
def test_simultaneous_skills_resolution_order_is_chosen():
    """A-7: §6.4(1)-4「自分のすべてのスキルを任意の順序で解決」。

    同一プレイヤーのスキルが2つ以上同時に誘発した場合、どれから解決するかを選ぶ。
    """
    from meicho.cards import CHARA_CARDS, CharaCard, Skill, Timing as T
    CHARA_CARDS["TEST-C-ORDER"] = CharaCard(
        "TEST-C-ORDER", "テスト順序", level=0,
        skills=(Skill(T.JUDGE, (("draw", {"count": 1}),),
                      condition={"self_result": "win"}),),
    )
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-021", tp_stack=["TEST-C-ORDER"],
                      auto_choices=False)
    assert s2.phase == Phase.CHOICE
    ch = s2.pending_choices[0]
    assert ch["kind"] == "order" and ch["player"] == 0
    cards = {o["card"] for o in ch["options"]}
    assert cards == {"TEST-C-ORDER", "SD01-021"}
    # どちらを先に解決しても最終結果（ドロー1+ドロー1+追撃2）は同じ
    for idx in (0, 1):
        s3 = auto(apply(s2, {0: {"type": "resolve", "index": idx}}))
        assert s3.rush_allowance == 2


def test_no_order_choice_for_single_skill():
    s = start_sd001()
    s2 = _sd001_clash(s, tp_card="SD01-021", tp_stack=["BP01-018"],
                      auto_choices=False)
    # 漂泊者（女）Lv0は【対抗】かつ緑条件なので【判定】では誘発しない → 鉤縄のみ
    assert s2.phase != Phase.CHOICE or s2.pending_choices[0]["kind"] != "order"


# --- C-1 相手の手札を確認する ---------------------------------------------------
def test_peek_opponent_hand_is_visible_in_observe():
    """C-1: スキャンで見た相手の手札が observe に反映される（D-010の no-op を解消）。"""
    s = start_sd001()
    s = s.clone()
    s.players[1].hand = ["SD01-011", "SD01-022", "SD01-012"]
    s.players[0].hand = ["SD01-020"]
    s.players[0].concerto = ["SD01-017"] * 5
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    before = observe(s, 0)["opp"]["hand_known"]
    assert before == []
    s2 = auto(apply(s, {0: {"type": "submit", "hand": 0}, 1: {"type": "pass"}}))
    assert s2.last_clash_winner == 0
    known = observe(s2, 0)["opp"]["hand_known"]
    assert sorted(known) == sorted(["SD01-011", "SD01-022", "SD01-012"])
    # 相手からはこちらの手札は見えないまま
    assert observe(s2, 1)["opp"]["hand_known"] == []
    assert "hand" not in observe(s2, 1)["opp"]


def test_peeked_knowledge_drops_cards_that_left_the_hand():
    """見たカードが手札から出たら、その分は知識から落ちる（多重集合の積）。"""
    s = start_sd001()
    s = s.clone()
    s.peeked_opp_hand[0] = ["SD01-011", "SD01-022", "SD01-022"]
    s.players[1].hand = ["SD01-022", "SD01-012"]
    known = observe(s, 0)["opp"]["hand_known"]
    assert known == ["SD01-022"]      # T11は場に出た。T03は1枚だけ残っている


# --- D-024 「◯◯が切り替えされた場合」は入れ替えの両方向で成立する ---------------
def _rush_switch(s, card, leader, back1, back2, back):
    """指定の配置で変奏スキルを連撃し、切り替え先を選ぶ（選択が出る場合のみ）。"""
    from meicho.engine import _do_rush, _pump
    s = s.clone()
    s.players[0].slots[0].stack = [leader]
    s.players[0].slots[1].stack = [back1] if back1 else []
    s.players[0].slots[2].stack = [back2] if back2 else []
    s.players[0].hand = [card]
    s.players[0].concerto = ["SD01-017"] * 5
    s.phase, s.clash_winner, s.rush_allowance = Phase.RUSH, 0, 3
    _do_rush(s, 0, 0)
    _pump(s)
    if s.phase == Phase.CHOICE and s.pending_choices[0]["kind"] == "switch_back":
        s = apply(s, {0: {"type": "choose_back", "back": back}})
    return auto(s)


def test_switch_bonus_triggers_when_the_named_chara_leaves_the_leader_slot():
    """D-024: 熾霞が「もともとリーダーでバックに行った」場合もダメージ+2が発動する。

    「『熾霞』が切り替えされた場合」は入れ替えに関与したことを指し、
    リーダー→バック / バック→リーダーのどちらの向きでも成立する
    （マスター裁定 2026-08-22）。旧実装は切り替え後のリーダー名しか見ていなかった。
    """
    s = start_sd001()
    # 熾霞がリーダー、バックに秧秧のみ → 熾霞がバックへ移動する向き
    out = _rush_switch(s, "SD01-009", leader="BP01-027",
                       back1="BP01-024", back2=None, back=1)
    assert _leader_name_of(out, 0) == "秧秧"      # 熾霞はバックへ下がった
    assert 20 - out.players[1].life == 2          # それでも +2 が乗る


def test_switch_bonus_triggers_in_both_directions():
    """バック→リーダーの向きでも従来どおり発動する（両方向で成立することの確認）。"""
    s = start_sd001()
    up = _rush_switch(s, "SD01-009", leader="BP01-024",
                      back1="BP01-027", back2=None, back=1)
    assert _leader_name_of(up, 0) == "熾霞"
    assert 20 - up.players[1].life == 2


def test_switch_bonus_does_not_trigger_without_the_named_chara():
    """入れ替えに熾霞が関与しなければ発動しない。"""
    s = start_sd001()
    out = _rush_switch(s, "SD01-009", leader="BP01-018",
                       back1="BP01-024", back2=None, back=1)
    assert _leader_name_of(out, 0) == "秧秧"
    assert 20 - out.players[1].life == 0


def test_switch_bonus_both_directions_for_draw_and_concerto_variants():
    """同じ規則が「1枚引く」「協奏エリアへ1枚」の変奏スキルにも適用される。"""
    s = start_sd001()
    # 轟音（漂泊者（女））: 漂泊者（女）がリーダーからバックへ下がる向き
    before = len(s.players[0].action_deck)
    out = _rush_switch(s, "SD01-019", leader="BP01-018",
                       back1="BP01-024", back2=None, back=1)
    assert _leader_name_of(out, 0) == "秧秧"
    assert len(out.players[0].action_deck) == before - 1        # ドロー1

    # 息継ぎ（秧秧）: 秧秧がリーダーからバックへ下がる向き
    out2 = _rush_switch(s, "SD01-014", leader="BP01-024",
                        back1="BP01-018", back2=None, back=1)
    assert _leader_name_of(out2, 0) == "漂泊者（女）"
    assert len(out2.players[0].concerto) == 5 + 1               # 協奏エリアへ1枚


def test_deck_out_does_not_lose_the_game():
    """D-025: デッキ切れによる敗北はない。片方だけ枯渇しても続行する（§9-5）。"""
    from meicho.engine import _begin_turn, _pump
    s = start_sd001()
    s = s.clone()
    p = s.players[0]
    p.concerto = p.concerto + p.hand + p.action_deck + p.trash + p.action_area
    p.hand, p.action_deck, p.trash, p.action_area = [], [], [], []
    s.turn_player = 0
    _begin_turn(s)
    _pump(s)
    # 引けないまま続行する。決着もしないし引き分けにもならない。
    assert s.phase == Phase.ACTION
    assert outcome(s) is None
    assert s.players[0].hand == []
    assert s.players[0].life == 20


# ===========================================================================
# ヒューリスティックエージェント（2026-08-22）
# ===========================================================================

def test_heuristic_plays_full_games():
    """全フェイズで合法手を返し、対局が正常に決着すること。"""
    from meicho.heuristic import HeuristicAgent
    from meicho.runner import play_game
    for seed in range(20):
        r = play_game(sd001_config(),
                      [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)],
                      seed=seed)
        assert r["aborted"] is False
        assert r["winner"] in (0, 1) or r["draw"] is True


def test_heuristic_is_deterministic_given_seed():
    """同シード同結果（作業規約2）。"""
    from meicho.heuristic import HeuristicAgent
    from meicho.runner import play_game
    mk = lambda: [HeuristicAgent(1), HeuristicAgent(2)]
    a = [play_game(sd001_config(), mk(), seed=s) for s in range(10)]
    b = [play_game(sd001_config(), mk(), seed=s) for s in range(10)]
    assert a == b


def test_heuristic_does_not_peek_at_opponent_hand():
    """相手の手札・デッキ順序を見ていないこと。

    隠蔽情報 (§10) を差し替えても選択が変わらないことで確認する。
    ここが破れると「強い」のではなく「カンニングしている」ことになる。
    """
    from meicho.heuristic import HeuristicAgent
    s = start_sd001()
    for phase_setup in (lambda x: x, ):
        s2 = phase_setup(s.clone())
        base = HeuristicAgent(7).act(s2, 0)
        for trial in range(5):
            t = s2.clone()
            rng = __import__("random").Random(trial)
            t.players[1].hand = rng.sample(sd001_config().action_decks[1],
                                           len(t.players[1].hand))
            rng.shuffle(t.players[0].action_deck)   # 自分のデッキ順序も非公開
            assert HeuristicAgent(7).act(t, 0) == base, "隠蔽情報を参照している"


def test_heuristic_beats_random_decisively():
    """対ランダムで明確に勝ち越すこと（回帰防止のため低めの閾値にする）。"""
    from meicho.heuristic import HeuristicAgent
    from meicho.agents import RandomAgent
    from meicho.runner import play_game
    w = n = 0
    for seed in range(60):
        for flip in (0, 1):
            ags = ([RandomAgent(seed * 2), HeuristicAgent(seed * 2 + 1)] if flip
                   else [HeuristicAgent(seed * 2), RandomAgent(seed * 2 + 1)])
            r = play_game(sd001_config(), ags, seed=seed)
            if r["aborted"] or r["draw"]:
                continue
            n += 1
            w += (r["winner"] == (1 if flip else 0))
    assert w / n > 0.85, f"対ランダム勝率 {w/n:.3f} が低すぎる"


def test_live_reds_counts_leader_gated_cards():
    """live_reds: リーダーを替えると生き返る赤を正しく数える（追補2の中核）。"""
    from meicho.heuristic import live_reds
    s = start_sd001()
    s = s.clone()
    s.players[0].slots[0].stack = ["BP01-018"]   # リーダー 漂泊者（女）
    s.players[0].slots[1].stack = ["BP01-027"]   # バック 熾霞
    s.players[0].hand = ["SD01-010", "SD01-011"]  # どちらも熾霞のリーダースキル赤
    s.players[0].concerto = ["SD01-017"] * 5
    assert live_reds(s, 0) == 0                    # 今は2枚とも死んでいる
    assert live_reds(s, 0, "熾霞") == 2            # 熾霞をリーダーにすれば2枚生きる


def test_greedy_plays_and_is_deterministic():
    from meicho.greedy import GreedyAgent
    from meicho.runner import play_game
    deck = sd001_config().action_decks[0]
    mk = lambda: [GreedyAgent(1, opp_decklist=deck), GreedyAgent(2, opp_decklist=deck)]
    a = [play_game(sd001_config(), mk(), seed=s) for s in range(6)]
    b = [play_game(sd001_config(), mk(), seed=s) for s in range(6)]
    assert a == b
    assert all(r["aborted"] is False for r in a)


def test_greedy_does_not_peek_at_opponent_hand():
    """貪欲も相手の手札を参照しないこと。

    決定化（相手の手札の標本抽出）は未公開カードのプールから行うため、
    実際の相手の手札を差し替えても選択は変わらない。
    """
    import random as _r
    from meicho.greedy import GreedyAgent
    deck = sd001_config().action_decks[0]
    s = start_sd001()
    base = GreedyAgent(3, opp_decklist=deck).act(s, 0)
    for trial in range(4):
        t = s.clone()
        rng = _r.Random(trial)
        t.players[1].hand = rng.sample(deck, len(t.players[1].hand))
        assert GreedyAgent(3, opp_decklist=deck).act(t, 0) == base, "隠蔽情報を参照している"


def _audit_agent(make_subject, n_games=3, variants=2, node_cap=120, **scr):
    """覗き見監査の共通ドライバ（meicho/audit.py, レビュー §3.4 処置(2)）。"""
    from meicho.audit import replay_audit
    from meicho.heuristic import HeuristicAgent
    deck = sd001_config().action_decks[0]
    return replay_audit(make_subject, lambda sd: HeuristicAgent(sd),
                        sd001_config(), deck, n_games=n_games,
                        variants=variants, node_cap=node_cap, **scr)


def test_nopeek_audit_heuristic():
    """§4/§10: ヒューリスティックは実対局のどの決定ノードでも隠蔽情報を使わない。"""
    from meicho.heuristic import HeuristicAgent
    r = _audit_agent(lambda sd: HeuristicAgent(sd), n_games=4, node_cap=300)
    assert r["checked"] >= 100, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"


def test_nopeek_audit_greedy():
    """§4/§10: 貪欲の**先読み**も隠蔽情報を使わないこと（D-026）。

    評価関数の非参照だけでは足りない。`_settle` がドローを実デッキ順序で
    解決していた漏洩（レビュー §3.4）の再発防止テストである。
    """
    from meicho.greedy import GreedyAgent
    deck = sd001_config().action_decks[0]
    r = _audit_agent(lambda sd: GreedyAgent(sd, opp_decklist=deck),
                     n_games=3, node_cap=120)
    assert r["checked"] >= 60, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"


def test_greedy_determinization_is_independent_of_real_order():
    """D-026: 決定化の結果が実際のデッキ順序に依存しないこと。

    `shuffle` は入力の並びの関数なので、正規化(sorted)を省くと
    「混ぜたのに漏れている」状態になる。その退行を直接押さえる。
    """
    import random as _r
    from meicho.greedy import GreedyAgent
    deck = sd001_config().action_decks[0]
    s = start_sd001()
    g = GreedyAgent(7, opp_decklist=deck)
    st = g.rng.getstate()
    a = g._determinize(s, 0)
    for trial in range(3):
        t = s.clone()
        _r.Random(trial).shuffle(t.players[0].action_deck)
        _r.Random(trial + 50).shuffle(t.players[1].action_deck)
        g.rng.setstate(st)
        b = g._determinize(t, 0)
        assert b.players[0].action_deck == a.players[0].action_deck
        assert b.players[1].action_deck == a.players[1].action_deck
        assert b.players[1].hand == a.players[1].hand


def test_clash_counts_record_revealed_colors():
    """§6.4(1)-3 / D-031: 対抗で公開された色の累積回数が記録されること。

    提出は両者に公開されるので、この集計は公開情報である（observe で両者分を返す）。
    """
    from meicho.heuristic import HeuristicAgent
    from meicho.state import CLASH_COLOR_INDEX, CLASH_PASS
    ag = [HeuristicAgent(1), HeuristicAgent(2)]
    s = initial_state(sd001_config(), 3)
    submitted = [[], []]
    while outcome(s) is None and s.turn_no <= 10:
        need = decision_players(s)
        acts = {pi: ag[pi].act(s, pi) for pi in need}
        was_clash = s.phase == Phase.CLASH_SUBMIT
        nxt = apply(s, acts)
        if was_clash and all(v is not None for v in nxt.last_clash_cards) \
                and nxt.clash_cards != [None, None]:
            for pi in (0, 1):
                cid = nxt.clash_cards[pi]
                if cid is not None:
                    submitted[pi].append(ACTION_CARDS[cid].color)
        s = nxt
    assert sum(sum(c) for c in s.clash_counts) > 0, "1回も記録されていない"
    for pi in (0, 1):
        for col in set(submitted[pi]):
            n = submitted[pi].count(col)
            assert s.clash_counts[pi][CLASH_COLOR_INDEX[col.value]] >= n
        # パス回数と色の回数の合計は、対抗を解決した回数に一致する
        assert sum(s.clash_counts[pi]) == s.clash_counts[pi][CLASH_PASS] + \
            sum(s.clash_counts[pi][:3])


def test_apply_is_non_destructive_and_apply_owned_is_not():
    """作業規約2 / B-2: 公開APIの `apply` は入力を変更しないこと。

    高速化のため `apply_owned`（複製しない版）を追加したので、
    公開APIの非破壊性が保たれていることを明示的に押さえる。
    """
    import dataclasses
    from meicho.engine import apply_owned
    from meicho.heuristic import HeuristicAgent
    ag = [HeuristicAgent(1), HeuristicAgent(2)]
    s = initial_state(sd001_config(), 7)
    for _ in range(6):
        need = decision_players(s)
        acts = {pi: ag[pi].act(s, pi) for pi in need}
        before = dataclasses.asdict(s)
        nxt = apply(s, acts)
        assert dataclasses.asdict(s) == before, "apply が入力を書き換えている"
        assert nxt is not s
        # apply_owned は同じ結果を、同じオブジェクトを書き換えて返す
        owned = apply_owned(s.clone(), acts)
        assert dataclasses.asdict(owned) == dataclasses.asdict(nxt)
        s = nxt


def test_clone_copies_every_field():
    """作業規約2 / B-2: 高速版 clone が**全フィールド**を複製していること。

    clone は速度のため dataclass の __init__ を迂用しており、
    フィールドを足したときに更新を忘れると静かに壊れる。
    全フィールドに既定値と異なる値を入れてから複製し、
    dataclasses.asdict で全体を突き合わせて漏れを検出する。
    """
    import dataclasses
    from meicho.state import CharaSlot, GameState, PlayerState

    def fill(obj, tag, skip=()):
        """全フィールドに既定値と違う値を入れる（skip で除外）。"""
        for f in dataclasses.fields(obj):
            if f.name in skip:
                continue
            cur = getattr(obj, f.name)
            if isinstance(cur, bool):
                setattr(obj, f.name, not cur)
            elif isinstance(cur, int):
                setattr(obj, f.name, cur + tag)
            elif isinstance(cur, list):
                # 入れ子の list（clash_counts 等）も中身を変える
                new = [(v + [tag] if isinstance(v, list) else v) for v in cur]
                setattr(obj, f.name, new + [f"{f.name}-{tag}"])
            elif isinstance(cur, dict):
                setattr(obj, f.name, dict(cur, **{f"k{tag}": f.name}))
            elif cur is None:
                setattr(obj, f.name, {"filled": f.name})

    s = start_sd001().clone()
    for i, p in enumerate(s.players):
        fill(p, i + 1, skip=("slots",))
        p.slots = [CharaSlot(stack=[f"x{i}", f"y{i}"]) for _ in range(3)]
    # players / phase 系は型が特殊なので個別に扱う
    fill(s, 7, skip=("players", "phase", "phase_before_choice"))
    s.phase = Phase.CLASH_SUBMIT
    s.phase_before_choice = Phase.ACTION

    t = s.clone()
    assert dataclasses.asdict(t) == dataclasses.asdict(s), "clone に漏れがある"
    # 参照を共有していないこと（浅いコピーの検出）
    t.players[0].hand.append("ZZZ")
    t.clash_counts[0][0] += 1
    t.players[0].slots[0].stack.append("ZZZ")
    assert "ZZZ" not in s.players[0].hand
    assert "ZZZ" not in s.players[0].slots[0].stack
    assert t.clash_counts[0][0] != s.clash_counts[0][0]


def test_clash_counts_survive_clone_and_json():
    """§10: 履歴も非破壊複製とJSON直列化の規約を守ること（作業規約2）。"""
    from meicho.heuristic import HeuristicAgent
    ag = [HeuristicAgent(1), HeuristicAgent(2)]
    s = initial_state(sd001_config(), 5)
    while outcome(s) is None and s.turn_no <= 6:
        need = decision_players(s)
        s = apply(s, {pi: ag[pi].act(s, pi) for pi in need})
    t = s.clone()
    t.clash_counts[0][0] += 99
    assert s.clash_counts[0][0] != t.clash_counts[0][0], "clone が浅い"
    assert GameState.from_json(s.to_json()).clash_counts == s.clash_counts
    assert observe(s, 0)["clash_counts"]["opp"] == s.clash_counts[1]
    assert observe(s, 1)["clash_counts"]["me"] == s.clash_counts[1]


def test_opponent_model_degrades_to_fallback_without_history():
    """B-3 / D-032: 観測が無い局面では相手モデルは固定方策と同一挙動になること。"""
    from meicho.oppmodel import OpponentModel
    from meicho.heuristic import HeuristicAgent
    s = start_sd001()
    s = s.clone()
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    assert sum(s.clash_counts[1]) == 0, "この局面はまだ対抗が起きていない前提"
    h = HeuristicAgent(9)
    m = OpponentModel(HeuristicAgent(9), prior_strength=8.0, enabled=True, seed=9)
    assert m.act(s, 1) == h.act(s, 1)


def test_nopeek_audit_planner():
    """§4/§10: ターン計画探索も隠蔽情報を使わないこと（D-026）。"""
    from meicho.planner import PlannerAgent
    deck = sd001_config().action_decks[0]
    r = _audit_agent(lambda sd: PlannerAgent(sd, opp_decklist=deck,
                                             plan_samples=2),
                     n_games=2, node_cap=60)
    assert r["checked"] >= 30, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"


def test_mcts_plays_and_is_deterministic():
    """B-1 §6.4(1): IS-MCTS が最後まで対局でき、同シードで同結果になること。"""
    from meicho.mcts import MCTSAgent
    from meicho.runner import play_game
    deck = sd001_config().action_decks[0]
    mk = lambda: [MCTSAgent(1, opp_decklist=deck, iterations=20),
                  MCTSAgent(2, opp_decklist=deck, iterations=20)]
    a = [play_game(sd001_config(), mk(), seed=s) for s in range(2)]
    b = [play_game(sd001_config(), mk(), seed=s) for s in range(2)]
    assert a == b
    assert all(r["aborted"] is False for r in a)


def test_nopeek_audit_mcts():
    """§4/§10: IS-MCTS の探索も隠蔽情報を使わないこと（D-026）。

    木は決定化した局面の上でしか進まないので違反0が期待値。
    フェーズ4で探索が深くなるほどこの監査の価値は上がる。
    """
    from meicho.mcts import MCTSAgent
    deck = sd001_config().action_decks[0]
    r = _audit_agent(lambda sd: MCTSAgent(sd, opp_decklist=deck, iterations=15),
                     n_games=2, node_cap=40)
    assert r["checked"] >= 20, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"


def test_mcts_returns_legal_actions():
    """B-1: 木が返す手は必ず実局面の合法手であること。

    探索は決定化した局面の上で行うので、根の合法手集合から外れていないかを
    明示的に押さえる（隠蔽情報は相手の手札とデッキ順序だけなので、
    自分の合法手は決定化で変わらないはずである）。
    """
    from meicho.engine import apply, decision_players, initial_state, outcome
    from meicho.heuristic import HeuristicAgent
    from meicho.mcts import MCTSAgent
    deck = sd001_config().action_decks[0]
    ag = [MCTSAgent(3, opp_decklist=deck, iterations=15), HeuristicAgent(4)]
    s = initial_state(sd001_config(), 2)
    checked = 0
    while outcome(s) is None and s.turn_no <= 14:
        need = decision_players(s)
        acts = {}
        for pi in need:
            a = ag[pi].act(s, pi)
            if pi == 0:
                assert a in legal_actions(s, 0), f"非合法な手: {a} ({s.phase})"
                checked += 1
            acts[pi] = a
        s = apply(s, acts)
    assert checked > 10


def test_nopeek_audit_planner_with_history_model():
    """B-3: 相手モデルを有効にしても隠蔽情報を使わないこと。

    既定はオフ（D-032）だが機構は残してあるので、退行しないよう監査を掛けておく。
    clash_counts は公開情報の集計なので、参照しても違反にならないのが期待値である。
    """
    from meicho.planner import PlannerAgent
    deck = sd001_config().action_decks[0]
    r = _audit_agent(lambda sd: PlannerAgent(sd, opp_decklist=deck,
                                             plan_samples=2, use_history=True),
                     n_games=2, node_cap=60)
    assert r["checked"] >= 30, f"監査したノードが少なすぎる: {r}"
    assert r["violations"] == 0, f"隠蔽情報を参照している: {r['examples']}"


def test_planner_plays_and_is_deterministic():
    """§6.3: ターン計画探索が最後まで対局でき、同シードで同結果になること。"""
    from meicho.planner import PlannerAgent
    from meicho.runner import play_game
    deck = sd001_config().action_decks[0]
    mk = lambda: [PlannerAgent(1, opp_decklist=deck, plan_samples=2),
                  PlannerAgent(2, opp_decklist=deck, plan_samples=2)]
    a = [play_game(sd001_config(), mk(), seed=s) for s in range(3)]
    b = [play_game(sd001_config(), mk(), seed=s) for s in range(3)]
    assert a == b
    assert all(r["aborted"] is False for r in a)


def test_planner_returns_a_legal_action_in_action_phase():
    """§6.3: 計画探索が返す1手目は必ずそのときの合法手であること。

    計画は決定化した局面の上で立てるので、実局面の合法手集合から
    外れた行動を返していないかを明示的に押さえる。
    """
    from meicho.engine import apply, decision_players, initial_state, outcome
    from meicho.planner import PlannerAgent
    from meicho.heuristic import HeuristicAgent
    deck = sd001_config().action_decks[0]
    ag = [PlannerAgent(5, opp_decklist=deck, plan_samples=2),
          HeuristicAgent(6)]
    s = initial_state(sd001_config(), 4)
    checked = 0
    while outcome(s) is None and s.turn_no <= 30:
        need = decision_players(s)
        acts = {}
        for pi in need:
            a = ag[pi].act(s, pi)
            if pi == 0 and s.phase == Phase.ACTION:
                assert a in legal_actions(s, 0), f"非合法な計画: {a}"
                checked += 1
            acts[pi] = a
        s = apply(s, acts)
    assert checked > 10


def test_planner_beats_heuristic():
    """A-2: ターン計画探索がヒューリスティックに明確に勝ち越すこと。

    本測定は experiments/measure_agents.py（n=300 で 0.773 ±0.047）。
    ここは退行検出用の軽い版なので、対戦数が少なく信頼区間は広い。
    閾値はその広さを見込んで緩めに置く（作業規約6）。
    """
    from meicho.planner import PlannerAgent
    from meicho.heuristic import HeuristicAgent
    from meicho.runner import play_game
    deck = sd001_config().action_decks[0]
    w = n = 0
    for seed in range(24):
        flip = seed % 2
        p = PlannerAgent(seed * 2 + flip, opp_decklist=deck, plan_samples=2)
        h = HeuristicAgent(seed * 2 + 1 - flip)
        r = play_game(sd001_config(), [h, p] if flip else [p, h], seed=seed)
        if r["aborted"] or r["draw"]:
            continue
        n += 1
        w += (r["winner"] == flip)
    assert w / n > 0.55, f"対ヒューリスティック勝率 {w/n:.3f} が低すぎる"


def test_greedy_beats_heuristic_in_the_clash_phase():
    """既定構成（対抗＋連撃を貪欲）がヒューリスティックに勝ち越すこと。"""
    from meicho.greedy import GreedyAgent
    from meicho.heuristic import HeuristicAgent
    from meicho.runner import play_game
    deck = sd001_config().action_decks[0]
    w = n = 0
    for seed in range(40):
        for flip in (0, 1):
            g = GreedyAgent(seed * 2, opp_decklist=deck)
            h = HeuristicAgent(seed * 2 + 1)
            r = play_game(sd001_config(), [h, g] if flip else [g, h], seed=seed)
            if r["aborted"] or r["draw"]:
                continue
            n += 1
            w += (r["winner"] == (1 if flip else 0))
    assert w / n > 0.55, f"対ヒューリスティック勝率 {w/n:.3f} が低すぎる"


# =========================================================================
# C-1 §4.2 速度の損益分岐（D-035）で確定した事実の退行防止
# =========================================================================

# 特徴抽出そのもののテストは tests/test_c1_features.py に移した
# （D-036 で `meicho/features.py` に正式化したため。覗き見・整形・
#   from_obs との一致をそちらで扱う）。ここに残すのは探索側の事実だけである。


def test_c1_leaf_budget_is_not_binding():
    """D-035: 既定の `leaf_budget=220` は上限として機能していない。

    実対局では1決定化あたりの終端数が予算にまったく届かない（実測: 中央値 12・
    最大 112）。したがって leaf_budget は「評価関数を重くしたぶんを削って払う」
    原資にはならない。ここが破れたら（枝を広げた等）C-1 の速度結論を測り直すこと。
    """
    from meicho.heuristic import HeuristicAgent
    from meicho.planner import PlannerAgent
    from meicho.runner import play_game

    class _Counting(PlannerAgent):
        max_leaves = 0

        def _search(self, t, pi, first, depth, leaves, seen):
            top = first is None
            before = len(leaves)
            super()._search(t, pi, first, depth, leaves, seen)
            if top:
                _Counting.max_leaves = max(_Counting.max_leaves,
                                           len(leaves) - before)

    deck = sd001_config().action_decks[0]
    _Counting.max_leaves = 0
    for seed in range(2):
        play_game(sd001_config(),
                  [_Counting(seed * 2, opp_decklist=deck),
                   HeuristicAgent(seed * 2 + 1)], seed=seed)
    m = _Counting.max_leaves
    assert m > 0, "終端が1つも数えられていない（計測の側の故障）"
    assert m < 220, f"leaf_budget に到達した（最大終端数 {m}）。速度結論の再測定が要る"


# =========================================================================
# D-036: observe() の公開情報の網羅（C-1 学習データの保存単位としての完全性）
# =========================================================================

def test_observation_includes_public_turn_flags_and_continuous_effects():
    """§6.3/§6.4: 公開の継続効果とターン内フラグが観測に含まれること。

    観測を学習データの保存単位にする（C-1）ため、`observe` は
    「pi に見えてよい情報」を**過不足なく**返す必要がある。
    とくに `red_cost_up` は `_effective_cost` が参照するので、
    欠けていると観測だけからカードの実効コストを復元できない。
    """
    s = start_sd001()
    ob = observe(s, 0)
    assert set(ob["used"]) == {"charge", "switch", "levelup"}
    for key in ("red_cost_up", "pending_red_cost_up", "rush_forbidden",
                "pending_rush_forbidden", "leader_switch_forbidden"):
        assert set(ob[key]) == {"me", "opp"}, key
        assert isinstance(ob[key]["me"], bool), key
    assert "clash_winner" in ob and "last_clash_winner" in ob
    assert len(ob["last_clash_cards"]) == 2


def test_observation_orients_continuous_effects_to_the_viewer():
    """継続効果の me/opp が視点ごとに入れ替わること（写し違えの検出）。"""
    s = start_sd001()
    t = s.clone()
    t.red_cost_up = [True, False]
    t.rush_forbidden = [False, True]
    t.clash_winner = 1
    assert observe(t, 0)["red_cost_up"] == {"me": True, "opp": False}
    assert observe(t, 1)["red_cost_up"] == {"me": False, "opp": True}
    assert observe(t, 0)["rush_forbidden"] == {"me": False, "opp": True}
    assert observe(t, 1)["rush_forbidden"] == {"me": True, "opp": False}
    assert observe(t, 0)["clash_winner"] == 1      # 相手が勝った
    assert observe(t, 1)["clash_winner"] == 0      # 自分が勝った


def test_observation_still_hides_private_info_after_extension():
    """D-036 の追加で隠蔽情報が漏れていないこと（D-026 の再確認）。"""
    s = start_sd001()
    ob = observe(s, 0)
    assert "hand" not in ob["opp"]
    assert "action_deck" not in ob["opp"] and "action_deck" not in ob["me"]
    # 裏向きの提出そのものは観測に出さない（対抗提出中は相手側が None）
    assert "pending_submission" not in ob
    flat = json.dumps(ob, ensure_ascii=False)
    for cid in s.players[1].hand:
        # 相手の手札のカードIDが、公開領域に無いのに現れていないこと
        public = (s.players[1].concerto + s.players[1].trash
                  + s.players[1].action_area + s.players[0].hand)
        if cid not in public:
            assert f'"{cid}"' not in flat, f"相手の手札 {cid} が観測に漏れている"
