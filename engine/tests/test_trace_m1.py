"""M1 トレース点（`meicho/trace.py`・送り箱 TE-5・`engine/app/M1_EVENT_SPEC.md`・D-114）の検査。

守ること（仕様書 §5・§8）:
- トレースの有無で `apply` の結果が 1 ビットも変わらない（毎手の `to_json` が一致）
- 切れているときは何も呼ばない。別スレッドの `apply` は流れ込まない。sink の例外は伝わる
- `draw` の回数・`damage`/`heal` の合計が状態の変化と合う
- 公開（`reveal`）が要るオペコードで出る（search_deck は公式 103.3・B-9 は公式 904.1）
"""
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from meicho import engine as E                                   # noqa: E402
from meicho import trace                                          # noqa: E402
from meicho.agents import RandomAgent                            # noqa: E402
from meicho.heuristic import HeuristicAgent                      # noqa: E402
from meicho.state import Phase                                    # noqa: E402

_DECKS = os.path.join(os.path.dirname(__file__), "..", "decklists")


def _deck(name):
    with open(os.path.join(_DECKS, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def _mirror(name):
    d = _deck(name)
    return E.GameConfig(chara_decks=[d["chara_deck"]] * 2, action_decks=[d["action_deck"]] * 2)


def _pair(a, b):
    da, db = _deck(a), _deck(b)
    return E.GameConfig(chara_decks=[da["chara_deck"], db["chara_deck"]],
                        action_decks=[da["action_deck"], db["action_deck"]])


def _play(config, seed, sink=None, agent_cls=HeuristicAgent, max_steps=3000):
    """1 局回して毎手の to_json を返す。sink を与えたらトレースしながら回す。"""
    ags = [agent_cls(seed * 2), agent_cls(seed * 2 + 1)]
    s = E.initial_state(config, seed)
    snaps = [s.to_json()]
    for _ in range(max_steps):
        if E.outcome(s) is not None:
            break
        need = E.decision_players(s)
        acts = {pi: ags[pi].act(s, pi) for pi in need}
        if sink is None:
            s = E.apply(s, acts)
        else:
            with trace.tracing(sink):
                s = E.apply(s, acts)
        snaps.append(s.to_json())
    return snaps, s


CONFIGS = [("SD001", lambda: _mirror("SD001")), ("SD02", lambda: _mirror("SD02")),
           ("TSUBAKI", lambda: _mirror("K_smoke_TSUBAKI")),
           ("ANKO_vs_SANGE", lambda: _pair("K_smoke_ANKO", "K_smoke_SANGE"))]


def test_inactive_by_default():
    assert trace.ACTIVE == 0
    got = []
    trace.emit(None, "x")          # sink が無ければ何もしない
    assert got == []


@pytest.mark.parametrize("name,mk", CONFIGS)
@pytest.mark.parametrize("agent_cls", [HeuristicAgent, RandomAgent])
def test_tracing_does_not_change_any_state(name, mk, agent_cls):
    """§5-1・§5-2: トレースあり・なしで毎手の状態（乱数の消費を含む）が一致する。"""
    cfg = mk()
    for seed in (1, 2, 3):
        events = []
        plain, _ = _play(cfg, seed, None, agent_cls)
        traced, _ = _play(cfg, seed, lambda k, i, s: events.append((k, i)), agent_cls)
        assert plain == traced, f"{name} seed={seed}: トレースで状態が変わった"
        assert events, "トレース点が 1 つも通っていない"
        assert trace.ACTIVE == 0


@pytest.mark.parametrize("name,mk", CONFIGS)
def test_event_counts_match_state(name, mk):
    """§8: draw の回数・damage/heal の合計・info が JSON にできること。"""
    cfg = mk()
    for seed in (4, 5):
        ev = []
        _, end = _play(cfg, seed, lambda k, i, s: ev.append((k, dict(i))))
        json.dumps([[k, i] for k, i in ev])            # info は JSON にできる値だけ
        kinds = {k for k, _ in ev}
        assert {"action", "step", "wait", "draw"} <= kinds
        for pi in (0, 1):
            dmg = sum(i["amount"] for k, i in ev if k == "damage" and i["player"] == pi)
            heal = sum(i["amount"] for k, i in ev if k == "heal" and i["player"] == pi)
            assert 20 - dmg + heal == end.players[pi].life or end.players[pi].life == 0
        if end.outcome is not None:
            assert [k for k, _ in ev].count("game_over") == 1
            assert ev[-1][0] == "game_over"


def test_draw_events_count_each_card():
    """§4.2: _draw は 1 枚ごとに draw を出す（開始の 5 枚は 1 席 5 回）。"""
    cfg = _mirror("SD02")
    s = E.initial_state(cfg, 7)
    ev = []
    ags = [HeuristicAgent(0), HeuristicAgent(1)]
    acts = {pi: ags[pi].act(s, pi) for pi in E.decision_players(s)}
    with trace.tracing(lambda k, i, st: ev.append((k, i))):
        s2 = E.apply(s, acts)
    draws = [i["player"] for k, i in ev if k == "draw"]
    assert draws.count(0) == 5 and draws.count(1) == 5
    assert [k for k, _ in ev][:2] == ["action", "action"]      # 行動は当てる前に・席の昇順
    assert ev[-1][0] == "wait" and ev[-1][1]["phase"] == s2.phase.value


def test_other_thread_is_isolated():
    """§3: 別スレッドの apply は、sink を設定したスレッドの sink に流れ込まない。"""
    cfg = _mirror("SD02")
    mine, theirs = [], []
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            _play(cfg, 11, None, max_steps=50)
    th = threading.Thread(target=worker)
    th.start()
    try:
        _play(cfg, 12, lambda k, i, s: mine.append(threading.get_ident()), max_steps=200)
    finally:
        stop.set()
        th.join()
    assert mine and set(mine) == {threading.get_ident()}
    assert trace.ACTIVE == 0


def test_sink_exception_propagates():
    cfg = _mirror("SD02")
    s = E.initial_state(cfg, 1)
    ags = [HeuristicAgent(0), HeuristicAgent(1)]
    acts = {pi: ags[pi].act(s, pi) for pi in E.decision_players(s)}

    def bad(k, i, st):
        raise RuntimeError("sink failed")
    with pytest.raises(RuntimeError, match="sink failed"):
        with trace.tracing(bad):
            E.apply(s, acts)
    assert trace.ACTIVE == 0


# ---------------------------------------------------------------- 公開（§4.3）
def _state_after_setup(cfgname="K_smoke_TSUBAKI"):
    s = E.initial_state(_mirror(cfgname), 3)
    ags = [HeuristicAgent(0), HeuristicAgent(1)]
    while s.phase in (Phase.SETUP_CHARA, Phase.MULLIGAN):
        s = E.apply(s, {pi: ags[pi].act(s, pi) for pi in E.decision_players(s)})
    return s


def _collect(fn):
    ev = []
    with trace.tracing(lambda k, i, st: ev.append((k, dict(i)))):
        fn()
    return [(k, i) for k, i in ev if k == "reveal"]


def test_reveal_search_deck():
    """公式 103.3: 条件指定で山札から選んだカードは公開する。該当が無ければ出さない。"""
    s = _state_after_setup()
    p = s.players[0]
    target = next(c for c in p.action_deck if E.ACTION_CARDS[c].name == "龍憑の天舞") \
        if any(E.ACTION_CARDS[c].name == "龍憑の天舞" for c in p.action_deck) else None
    if target is None:
        p.action_deck.append("SD02-010")                        # 龍憑の天舞
        target = "SD02-010"
    assert E.ACTION_CARDS[target].name == "龍憑の天舞"
    rv = _collect(lambda: E._apply_op(s, 0, "search_deck", {"card_name": "龍憑の天舞"}, {}))
    assert rv == [("reveal", {"owner": 0, "cards": [target], "audience": "all", "zone": "action_deck"})]
    s.players[0].action_deck = [c for c in s.players[0].action_deck
                                if E.ACTION_CARDS[c].name != "龍憑の天舞"]
    assert _collect(lambda: E._apply_op(s, 0, "search_deck", {"card_name": "龍憑の天舞"}, {})) == []


def test_reveal_top_to_hand_and_take_matching_and_peek():
    s = _state_after_setup()
    top = s.players[0].action_deck[0]
    rv = _collect(lambda: E._apply_op(s, 0, "reveal_top_to_hand", {"count": 1}, {}))
    assert rv == [("reveal", {"owner": 0, "cards": [top], "audience": "all", "zone": "action_deck"})]
    five = list(s.players[1].action_deck[:5])
    rv = _collect(lambda: E._apply_op(s, 1, "reveal_n_take_matching", {"count": 5, "chara": "今汐"}, {}))
    assert rv == [("reveal", {"owner": 1, "cards": five, "audience": "all", "zone": "action_deck"})]
    hand1 = list(s.players[1].hand)
    rv = _collect(lambda: E._apply_op(s, 0, "peek_opponent_hand", {}, {}))
    assert rv == [("reveal", {"owner": 1, "cards": hand1, "audience": 0, "zone": "hand"})]


def test_reveal_b9_stuck_hand():
    """公式 604.1.1.2・904.1: 対抗で置けないターンプレイヤーの手札公開は全員に。"""
    s = _state_after_setup()
    tp = s.turn_player
    s.phase = Phase.CHOICE          # いったん外してから対抗の提出待ちを作る
    s.phase = Phase.CLASH_SUBMIT
    s.pending_submission = [None, None]
    s.players[tp].hand = [c for c in s.players[tp].hand
                          if not E._usable_in_clash(s, tp, E.ACTION_CARDS[c])]
    hand = list(s.players[tp].hand)
    rv = _collect(lambda: E._reveal_stuck_turn_player_hand(s))
    assert rv == [("reveal", {"owner": tp, "cards": hand, "audience": "all", "zone": "hand"})]
