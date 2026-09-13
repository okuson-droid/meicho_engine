"""エージェントの覗き見監査（レビュー 2026-08-23 §3.4 の処置(2)）。

## なぜ必要か

「評価関数が相手の手札を読まない」ことをテストしても足りない。
先読みを行うエージェントは `apply` / `_settle` を実局面の上で走らせるため、
**探索の過程**がドローを実際のデッキ順序で解決してしまい、
「次に引く札を知った上で」手を比較しうる（実際に貪欲 v0.1 がそうだった）。

この監査は実対局のリプレイ中、対象プレイヤーの**すべての実決定ノード**
（合法手2以上）で隠蔽情報を差し替え、選択が変わらないことを検査する。
フェーズ4の IS-MCTS は同じ `_settle` 系の部品をより深く使うため、
漏洩は探索の深さに比例して拡大する。新しいエージェントを追加したら
必ずこの監査にかけること。

## 隠蔽情報の定義（rules_draft.md §4 / §10）

- 相手の手札の**中身**（枚数は公開）
- **両者の**デッキ順序（自分のデッキも中身は既知だが順序は未知）

自分の手札・両者の協奏／トラッシュ／アクションエリア／キャラは公開情報。

## 差し替えは情報集合の中に収める（2026-09-10・文献計画 便 C 段 C-1・D-077）

**「隠蔽情報」は「`observe` が返さないもの」と定義する。** これは言い換えではなく、
実際に効く違いである。スキャンでこちらが見た相手の札は `observe` が
`opp.hand_known` として返す——**pi にとって隠れていない**（D-023）。ところが素朴に
相手の手札を丸ごと引き直すと `hand_known` まで変わってしまい、その札を正当に使う
エージェント（`known_hand=True`・段 C-1）は「差し替えたら手が変わった」と報告される。
それは覗き見ではなく、**差し替えた局面が pi の情報集合の外に出ていた**だけである。

そこで差し替えは `observe(差し替えた局面, pi) == observe(元の局面, pi)` を満たすものだけを
使う（満たすまで作り直し、`_SCRAMBLE_TRIES` 回で諦めたらその試行は数えない）。
`hand_known` が空の局面では従来と同じ差し替えになる。
"""
from __future__ import annotations

import random

from .engine import (apply, decision_players, initial_state, legal_actions,
                     observe, outcome)

# 差し替えを作り直す回数の上限（§「差し替えは情報集合の中に収める」）。
_SCRAMBLE_TRIES = 8


def _rngs(agent) -> list:
    """エージェントが持つ乱数源をすべて集める（入れ子のエージェントも辿る）。

    比較の条件を揃えるため、差し替え試行のたびに状態を復元する必要がある。
    """
    found, seen = [], set()

    def walk(obj, depth=0):
        if depth > 3 or id(obj) in seen or not hasattr(obj, "__dict__"):
            return
        seen.add(id(obj))
        for v in vars(obj).values():
            if isinstance(v, random.Random):
                if id(v) not in seen:
                    seen.add(id(v))
                    found.append(v)
            else:
                walk(v, depth + 1)

    walk(agent)
    return found


def scramble(s, pi, pool, rng, opp_hand=True, own_deck=True, opp_deck=True):
    """pi から見た隠蔽情報だけを差し替えた局面を返す。

    フラグで対象を絞れるので、違反が出たときに原因を切り分けられる。
    pool は相手のデッキリスト（相手の手札の差し替え候補）。
    """
    t = s.clone()
    if opp_hand:
        # スキャンで pi に見えている札は**隠蔽情報ではない**ので、差し替えても残す
        # （§「差し替えは情報集合の中に収める」）。見えていなければ従来どおり全部引き直す。
        known = list(observe(s, pi)["opp"]["hand_known"])
        rest = list(pool)
        for cid in known:
            if cid in rest:
                rest.remove(cid)
        n = min(len(t.players[1 - pi].hand), len(known) + len(rest)) - len(known)
        t.players[1 - pi].hand = known + (rng.sample(rest, n) if n > 0 else [])
    if own_deck:
        rng.shuffle(t.players[pi].action_deck)
    if opp_deck:
        rng.shuffle(t.players[1 - pi].action_deck)
    return t


def replay_audit(make_subject, make_opponent, config, pool, n_games=4,
                 variants=2, node_cap=10 ** 9, audit_pi=0, seed0=0,
                 max_turns=200, **scr):
    """実対局をリプレイしながら監査する。

    戻り値 {"checked": 決定ノード数, "violations": 違反数, "examples": [...]}。
    """
    checked = violations = skipped = 0
    examples = []

    def scramble_in_infoset(s, pi, srng):
        """情報集合の中に収まる差し替えを 1 つ返す（作れなければ None）。

        「収まる」＝ `observe` が 1 ビットも変わらないこと（§「差し替えは情報集合の中に収める」）。
        """
        want = observe(s, pi)
        for _ in range(_SCRAMBLE_TRIES):
            alt = scramble(s, pi, pool, srng, **scr)
            if observe(alt, pi) == want:
                return alt
        return None
    for g in range(n_games):
        seed = seed0 + g
        agents = [None, None]
        agents[audit_pi] = make_subject(seed * 2)
        agents[1 - audit_pi] = make_opponent(seed * 2 + 1)
        s = initial_state(config, seed)
        srng = random.Random(seed + 999)
        while outcome(s) is None and s.turn_no <= max_turns:
            need = decision_players(s)
            actions = {}
            for pi in need:
                if (pi == audit_pi and checked < node_cap
                        and len(legal_actions(s, pi)) > 1):
                    rngs = _rngs(agents[pi])
                    states = [r.getstate() for r in rngs]
                    base = agents[pi].act(s, pi)
                    for _ in range(variants):
                        for r, st in zip(rngs, states):
                            r.setstate(st)
                        alt_state = scramble_in_infoset(s, pi, srng)
                        if alt_state is None:
                            skipped += 1
                            continue
                        alt = agents[pi].act(alt_state, pi)
                        if alt != base:
                            violations += 1
                            if len(examples) < 3:
                                examples.append({
                                    "seed": seed, "turn": s.turn_no,
                                    "phase": s.phase.value,
                                    "base": base, "alt": alt})
                            break
                    for r, st in zip(rngs, states):
                        r.setstate(st)
                    checked += 1
                    actions[pi] = agents[pi].act(s, pi)
                else:
                    actions[pi] = agents[pi].act(s, pi)
            s = apply(s, actions)
    return {"checked": checked, "violations": violations, "examples": examples,
            "skipped_variants": skipped}
