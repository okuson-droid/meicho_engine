"""段階1C-a（D-121）: 相手の手札の「確かな既知」を 1 つの欄で持つ。

マスター裁定（2026-09-22）「hand_public と hand_known は最終的には統一するのが合理的」を受けて、
`observe` の `opp.hand_known` を**統一した既知**（スキャン・B-9 の公開＋公開されてから手札に入った札）にした。
現 champion の打ち方を変えないため、旧 `hand_known`（スキャン・B-9 のぶんだけ・D-023 の積）は
`opp.hand_known_scan` として残し、`GreedyAgent._known_in_hand` と符号化 v5 はそちらを読む。

ここで固定すること:
1. 公開されてから手札に入った札（山札の公開・サーチ・トラッシュや場からの回収）は相手の `hand_known` に出る
2. 見える形で出た札は 1 枚減る（使用・チャージ・捨てる・対抗・連撃）
3. **D-023 の積の漏れ**: 知っていた札を見える形で使ったあと、同じ番号を見えない形で引いても「知っている」にならない
   （旧 `hand_known_scan` では「知っている」になる——現 champion の退役とともに消す）
4. 見えない出方（BP01-039 手札 → デッキの下）のあとは、使った側の知識を全部捨てる（TE-10・D-118 R-2）
5. Python と Rust で状態（`known_opp_hand`）と `observe` が毎手一致し、BP01-039 の道を実際に通る
"""
from __future__ import annotations

import json

import pytest

from experiments.arena import load_deck, matchup_config, mirror_config  # noqa: E402
from meicho import trace                                                # noqa: E402
from meicho.engine import (_apply_op, _do_rush, apply, decision_players,  # noqa: E402
                           initial_state, legal_actions, observe, outcome)
from meicho.heuristic import HeuristicAgent                             # noqa: E402

SD001 = load_deck("SD001")


def _start(seed=11):
    s = initial_state(mirror_config(SD001), seed)
    s = apply(s, {0: {"type": "setup", "leader": "漂泊者（女）"},
                  1: {"type": "setup", "leader": "漂泊者（女）"}})
    s = apply(s, {0: {"type": "mulligan", "count": 0}, 1: {"type": "mulligan", "count": 0}})
    return s


def _blank(seed=11):
    """手札を手で置き換える検査のために、両者の知識を空にした局面。"""
    s = _start(seed).clone()
    s.known_opp_hand = [[], []]
    s.peeked_opp_hand = [None, None]
    return s


def test_reveal_top_to_hand_is_known_and_leaves_when_used():
    s = _blank()
    s.players[0].hand = []
    top = s.players[0].action_deck[0]
    ctx: dict = {}
    _apply_op(s, 0, "reveal_top_to_hand", {"count": 1}, ctx)
    assert s.players[0].hand == [top]
    assert observe(s, 1)["opp"]["hand_known"] == [top]
    assert observe(s, 1)["opp"]["hand_known_scan"] == []          # 旧欄には入らない（champion 不変）
    # 見える形で出る（連撃で使う）→ 知識から落ちる
    s.phase, s.clash_winner, s.rush_allowance = s.phase, 0, 3
    _do_rush(s, 0, 0)
    assert observe(s, 1)["opp"]["hand_known"] == []


def test_known_card_used_then_same_card_drawn_hidden_is_not_known():
    """D-023 の積の漏れ: 知っていた X を公開して使い、そのあと X を見えない形で引いた。"""
    s = _blank()
    x = "SD01-011"
    s.players[1].hand = [x, "SD01-022"]
    _apply_op(s, 0, "peek_opponent_hand", {}, {})                 # 0 が 1 の手札を見る
    assert observe(s, 0)["opp"]["hand_known"] == sorted([x, "SD01-022"])
    # 1 が X を見える形で捨てる（トラッシュは公開領域）
    from meicho.engine import _know_hand_out
    s.players[1].trash.append(s.players[1].hand.pop(0))
    _know_hand_out(s, 1, x)
    # 1 が見えない形で X を引く（ドロー）
    s.players[1].hand.append(x)
    assert observe(s, 0)["opp"]["hand_known"] == ["SD01-022"]       # 新しい欄: 漏れない
    assert sorted(observe(s, 0)["opp"]["hand_known_scan"]) == sorted([x, "SD01-022"])  # 旧欄: 漏れる（既知の欠陥）


def test_hidden_move_to_deck_bottom_forgets_everything():
    """TE-10: BP01-039 相当（手札からランダムに 1 枚をデッキの下へ）のあと、使った側は相手の手札を何も知らない。"""
    s = _blank()
    s.players[1].hand = ["SD01-011", "SD01-022", "SD01-012"]
    _apply_op(s, 0, "peek_opponent_hand", {}, {})
    assert len(observe(s, 0)["opp"]["hand_known"]) == 3
    _apply_op(s, 0, "opp_hand_random_to_deck_bottom", {"count": 1}, {})
    assert len(s.players[1].hand) == 2
    assert observe(s, 0)["opp"]["hand_known"] == []
    assert observe(s, 0)["opp"]["hand_known_scan"] == []


def test_known_is_always_a_submultiset_of_the_true_hand_in_real_games():
    """実際の対局（SD001 同型・heuristic）で、既知は常に本当の手札の部分多重集合（安全柵の積に頼らない）。"""
    from collections import Counter
    more = [0]
    for seed in range(6):
        s = initial_state(mirror_config(SD001), 900 + seed)
        ags = [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)]
        steps = 0
        while outcome(s) is None and steps < 3000:
            for pi in (0, 1):
                k, h = Counter(s.known_opp_hand[pi]), Counter(s.players[1 - pi].hand)
                assert not (k - h), f"seed={seed} step={steps} P{pi}: 知識が手札に無い札を含む {dict(k - h)}"
            for pi in (0, 1):
                ob = observe(s, pi)["opp"]
                # 旧欄（スキャン・D-023 の積）にあって新しい欄に無い札は、**旧欄の漏れ**のぶんだけである
                # （知っていた札が見える形で出たあと、同じ番号を見えない形で引いた）。ここでは数えない。
                more[0] += len(ob["hand_known"]) > len(ob["hand_known_scan"])
            need = decision_players(s)
            if not need:
                break
            s = apply(s, {pi: ags[pi].act(s, pi) for pi in need})
            steps += 1
    assert more[0] > 0, "公開して手札に入った札を知っている局面が 1 度も無い（機能が発火していない）"


rs = None
try:
    import meicho_rs as rs                                               # noqa: F811
except ImportError:                                                      # pragma: no cover
    rs = None


def _lockstep_count(cfg, seed, agents):
    """Python と Rust を毎手突き合わせ、BP01-039 の効果が解決した回数を返す。"""
    from meicho.cards_export import cards_json
    rs.load_cards(cards_json())
    fired = [0]

    def sink(kind, info, _s):
        if kind == "step" and info.get("what") == "op" and info.get("op") == "opp_hand_random_to_deck_bottom":
            fired[0] += 1

    py = initial_state(cfg, seed)
    rss = rs.initial_state(cfg.chara_decks, cfg.action_decks, seed)
    steps = 0
    while True:
        assert json.loads(json.dumps(json.loads(py.to_json()))) == json.loads(rss.to_json()), f"state seed={seed} step={steps}"
        for pi in (0, 1):
            assert json.loads(json.dumps(observe(py, pi), ensure_ascii=False)) == rs.observe(rss, pi), \
                f"observe P{pi} seed={seed} step={steps}"
        need = decision_players(py)
        if outcome(py) is not None or not need or py.turn_no > 200:
            break
        acts = {pi: agents[pi].act(py, pi) for pi in need}
        with trace.tracing(sink):
            py = apply(py, acts)
        rss = rs.apply(rss, acts)
        steps += 1
    return fired[0]


@pytest.mark.skipif(rs is None, reason="meicho_rs が無い")
def test_python_and_rust_agree_including_the_hidden_move():
    """BP01-039 を含むデッキ（K_smoke_ANKO）とスキャンを含むデッキ（K_smoke_SANGE）で毎手一致し、BP01-039 を実際に通る。"""
    anko, sange = load_deck("K_smoke_ANKO"), load_deck("K_smoke_SANGE")
    total = 0
    for seed in range(12):
        cfg = matchup_config(anko, sange) if seed % 2 == 0 else mirror_config(anko)
        total += _lockstep_count(cfg, 5000 + seed, [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)])
    assert total > 0, "BP01-039 の道を一度も通っていない（検査が何も確かめていない）"
