"""行動の価値を「やった場合／やらなかった場合」の勝率差で直接測る（D-039）。

rules_draft.md v0.10 準拠 / engine v0.1。
マスターの提案（2026-08-24）:「行動の価値を測るなら、その行動をする前後で
勝率がどう変わったかを見るのが自然ではないか」。

## この実験が答える問い

D-038 で、レベルアップの重みについて 2 つの答えが食い違った。

- 現行の評価関数（対戦の勝率で調整。A-3）: **+0.498**（やる価値がある）
- 学習した重み（勝敗の予測で調整）: **−0.197**（やらない方がよい）

どちらが正しいのかは、**実際にやってみれば分かる**。このゲームは
シミュレータを我々が所有しているので、「やった世界」と「やらなかった世界」を
両方走らせられる。医学や経済学と違い、反実仮想を実演できるのが強みである。

## 測り方（対照実験）

1. 計画探索 vs H_default の対局を進め、**計画探索が k 回目にレベルアップを
   選べる決定点**まで来たら、そこで局面を複製する。k はシードごとに 1〜8 で
   変える（最初の機会だけを見ると序盤に偏り、「早すぎるレベルアップ」の
   評価にしかならないため）。
2. **枝A**: そのレベルアップを強制的に実行し、以後は通常どおり指す。
3. **枝B**: そのターンの間だけレベルアップを禁じ、以後は通常どおり指す
   （＝「今はやらない」。次のターン以降はやってよい）。
4. 両方を最後まで進め、勝敗を比べる。

**両枝で同じシードを使う**（共通乱数, CRN）。同じ山札・同じ相手・同じ分岐点から
始まるので、勝敗の差は「レベルアップしたかどうか」だけに帰せる。
対応のある比較になるため、少ない対局数でも差が見えやすい
（この分散抑制の効き目は PLANNER_NOTES.md で実証済み）。

## なぜ「学習した価値関数の差分」ではだめか

同じ「前後の差」でも、`V(行動後) − V(行動前)` を**学習した V で計算しても
何も直らない**。理由は 2 つある。

1. 計画探索は候補どうしを比べて最大を選ぶだけなので、**全候補に共通の
   `V(行動前)` を引いても選ぶ手はまったく変わらない**（順位が変わらない）。
2. そもそも V 自体が「レベルが高い局面は悪い」と誤って学んでいるので、
   その差分もまた誤る。V(レベルアップ後) は手札が減った分もレベルが上がった分も
   両方が負に効き、差は負になる。

**必要なのは V の引き算ではなく、実際に両方の枝を走らせることである。**
本スクリプトはそれを行う。

実行: python3 experiments/measure_action_value.py [n] [--workers 2]
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from arena import ci95, load_deck, mirror_config                  # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,  # noqa: E402
                           legal_actions, outcome)
from meicho.heuristic import HeuristicAgent                       # noqa: E402
from meicho.planner import PlannerAgent                           # noqa: E402
from meicho.runner import play_game                               # noqa: E402
from meicho.state import Phase                                    # noqa: E402

SEED0 = 120000        # seed_bands.json に登録済み（D-039 の測定専用）
DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]


class NoLevelupThisTurn(PlannerAgent):
    """指定のターンの間だけレベルアップを選ばない計画探索。

    `_branches` は探索が展開する資源行動を返す関数であり、根でも枝でも
    ここを通る。したがってここで落とせば、そのターンのあいだ
    「レベルアップは無いもの」として計画を立てることになる。
    次のターン以降は通常どおり選べる（＝「今はやらない」であって「一生やらない」ではない）。
    """

    def __init__(self, seed: int, ban_turn: int = -1, **kw):
        super().__init__(seed, **kw)
        self.ban_turn = ban_turn

    def _branches(self, t, pi, acts):
        out = super()._branches(t, pi, acts)
        if self.ban_turn == "all" or t.turn_no == self.ban_turn:
            out = [a for a in out if a["type"] != "levelup"]
        return out


def _mk(seed, seat_planner, ban_turn=-1, mirror=False):
    """[席0のエージェント, 席1のエージェント] を作る。両枝で同じシードを使う。

    mirror=True なら相手も計画探索にする（強い相手のもとでも同じ結論かを見る）。
    相手側には制約をかけない。測りたいのは**自分の行動**の価値だからである。
    """
    p = NoLevelupThisTurn(seed * 2 + seat_planner, ban_turn=ban_turn,
                          opp_decklist=POOL)
    if mirror:
        o = PlannerAgent(seed * 2 + (1 - seat_planner), opp_decklist=POOL)
    else:
        o = HeuristicAgent(seed * 2 + (1 - seat_planner))
    return [p, o] if seat_planner == 0 else [o, p]


def _find_fork(seed, seat_planner, k):
    """計画探索が k 回目にレベルアップを選べる決定点まで進め、局面を返す。

    戻り値 (state, levelup_action, planner_choice) または None。
    k 回目が存在しない対局では、**最後の機会**で分岐する（None を返して
    捨てると、レベルアップの機会が少ない＝短い対局ばかりが落ちて偏る）。
    """
    agents = _mk(seed, seat_planner)
    s = initial_state(CONFIG, seed)
    seen, last = 0, None
    while outcome(s) is None and s.turn_no <= 200:
        need = decision_players(s)
        if s.phase == Phase.ACTION and seat_planner in need:
            acts = legal_actions(s, seat_planner)
            ups = [a for a in acts if a["type"] == "levelup"]
            # 「選べる」＝レベルアップが合法で、かつ他の選択肢もあること。
            # 唯一の合法手なら比較にならないので飛ばす。
            if ups and len(acts) > len(ups):
                seen += 1
                choice = agents[seat_planner].act(s, seat_planner)
                last = (s, ups[0], choice)
                if seen >= k:
                    return last
        s = apply(s, {pi: agents[pi].act(s, pi) for pi in need})
    return last


def _one(seed):
    """1シードぶんの対照実験。両枝の勝敗を返す。"""
    seat = seed % 2                      # 席の偏りを消す
    k = (seed // 2) % 8 + 1              # 分岐させる機会をターン全体に散らす
    found = _find_fork(seed, seat, k)
    if found is None:
        return None
    s, up, choice = found

    # 枝A: レベルアップを強制してから、以後は通常の計画探索
    sa = apply(s, {seat: up})
    ra = play_game(CONFIG, _mk(seed, seat), seed=seed, initial=sa)

    # 枝B: このターンだけレベルアップを禁じて、そこから通常どおり
    rb = play_game(CONFIG, _mk(seed, seat, ban_turn=s.turn_no), seed=seed,
                   initial=s)

    if ra["aborted"] or rb["aborted"] or ra["draw"] or rb["draw"]:
        return None
    return {"seed": seed, "turn": s.turn_no, "seat": seat, "k": k,
            "planner_chose_levelup": choice["type"] == "levelup",
            "a_won": ra["winner"] == seat, "b_won": rb["winner"] == seat,
            "a_turns": ra["turns"], "b_turns": rb["turns"]}


def _one_ban_all_mirror(seed):
    """対照3: 相手も計画探索（強い相手）のもとで同じことを測る。"""
    seat = seed % 2
    ra = play_game(CONFIG, _mk(seed, seat, mirror=True), seed=seed)
    rb = play_game(CONFIG, _mk(seed, seat, ban_turn="all", mirror=True), seed=seed)
    if ra["aborted"] or rb["aborted"] or ra["draw"] or rb["draw"]:
        return None
    return {"seed": seed, "turn": 0, "seat": seat, "k": 0,
            "planner_chose_levelup": False,
            "a_won": ra["winner"] == seat, "b_won": rb["winner"] == seat,
            "a_turns": ra["turns"], "b_turns": rb["turns"]}


def _one_ban_all(seed):
    """対照2: **その対局で一度もレベルアップしない**場合との比較。

    対照1（今やるか1ターン待つか）は「タイミングの価値」しか測らない。
    もし遅らせてもすぐやるなら、差が出なくて当然である。
    こちらは「そもそもレベルアップという行動に価値があるか」を測る。
    """
    seat = seed % 2
    ra = play_game(CONFIG, _mk(seed, seat), seed=seed)                    # 通常
    rb = play_game(CONFIG, _mk(seed, seat, ban_turn="all"), seed=seed)    # 一切禁止
    if ra["aborted"] or rb["aborted"] or ra["draw"] or rb["draw"]:
        return None
    return {"seed": seed, "turn": 0, "seat": seat, "k": 0,
            "planner_chose_levelup": False,
            "a_won": ra["winner"] == seat, "b_won": rb["winner"] == seat,
            "a_turns": ra["turns"], "b_turns": rb["turns"]}


def _report(rows, n, label_a, label_b, show_turns=True):
    import random as _r
    m = len(rows)
    print(f"シード帯 {SEED0}.. / 試行 {n} / 有効な対 {m}")
    if not m:
        print("分岐点が見つからなかった")
        return
    a = sum(r["a_won"] for r in rows)
    b = sum(r["b_won"] for r in rows)
    if show_turns:
        print(f"\n分岐点: 平均ターン {sum(r['turn'] for r in rows) / m:.1f} / "
              f"そこで計画探索が実際にレベルアップを選んだ割合 "
              f"{sum(r['planner_chose_levelup'] for r in rows) / m * 100:.1f}%")
    print(f"\n{'枝':<30}{'勝率':>22}")
    print(f"{label_a:<30}{a / m:>10.3f} ±{ci95(a, m):.3f} (n={m})")
    print(f"{label_b:<30}{b / m:>10.3f} ±{ci95(b, m):.3f} (n={m})")
    ab = sum(1 for r in rows if r["a_won"] and not r["b_won"])
    ba = sum(1 for r in rows if r["b_won"] and not r["a_won"])
    same = m - ab - ba
    print(f"\n対応のある比較（同じシード・同じ分岐点から両方走らせた {m} 対）:")
    print(f"  同じ結果になった対: {same} ({same / m * 100:.1f}%)")
    print(f"  A だけ勝った: {ab} / B だけ勝った: {ba}")
    print(f"  **勝率差 (A − B) = {(ab - ba) / m:+.3f}**")
    rng = _r.Random(20260824)
    d = [int(r["a_won"]) - int(r["b_won"]) for r in rows]
    boot = sorted(sum(rng.choice(d) for _ in range(m)) / m for _ in range(2000))
    lo, hi = boot[int(2000 * 0.025)], boot[int(2000 * 0.975)]
    print(f"  95% 区間 [{lo:+.3f}, {hi:+.3f}]  "
          f"{'→ 0 を含まないので差があると言える' if lo > 0 or hi < 0 else '→ 0 を含むので差があるとは言えない'}")
    return (ab - ba) / m, lo, hi


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 200
    workers = 2 if "--workers" in sys.argv else 1
    seeds = list(range(SEED0, SEED0 + n))
    if "--ban-all" in sys.argv or "--mirror" in sys.argv:
        mir = "--mirror" in sys.argv
        fn = _one_ban_all_mirror if mir else _one_ban_all
        print(f"== 対照{'3: 相手も計画探索' if mir else '2: 相手は H_default'}: "
              f"レベルアップという行動そのものの価値（D-039）==")
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                rows = [r for r in ex.map(fn, seeds, chunksize=4) if r]
        else:
            rows = [r for r in map(fn, seeds) if r]
        _report(rows, n, "A: 通常どおり（レベルアップ可）",
                "B: この対局では一切しない", show_turns=False)
        print("\n【解釈の手引き】")
        print("  差がプラス = レベルアップという行動に価値がある")
        print("  差が 0 付近 = この構成ではレベルアップはほぼ無関係だった")
        return
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            rows = [r for r in ex.map(_one, seeds, chunksize=4) if r]
    else:
        rows = [r for r in map(_one, seeds) if r]

    m = len(rows)
    print("== 行動の価値を勝率差で直接測る（D-039）==")
    print(f"シード帯 {SEED0}.. / 試行 {n} / 有効な対 {m}")
    if not m:
        print("分岐点が見つからなかった")
        return

    a = sum(r["a_won"] for r in rows)
    b = sum(r["b_won"] for r in rows)
    print(f"\n分岐点: 平均ターン {sum(r['turn'] for r in rows) / m:.1f} / "
          f"そこで計画探索が実際にレベルアップを選んだ割合 "
          f"{sum(r['planner_chose_levelup'] for r in rows) / m * 100:.1f}%")
    print(f"\n{'枝':<28}{'勝率':>22}")
    print(f"{'A: 今レベルアップする':<28}{a / m:>10.3f} ±{ci95(a, m):.3f} (n={m})")
    print(f"{'B: 今はレベルアップしない':<28}{b / m:>10.3f} ±{ci95(b, m):.3f} (n={m})")

    # 対応のある比較。同じ分岐点・同じシードなので、食い違った対だけが情報を持つ。
    ab = sum(1 for r in rows if r["a_won"] and not r["b_won"])
    ba = sum(1 for r in rows if r["b_won"] and not r["a_won"])
    same = m - ab - ba
    diff = (ab - ba) / m
    print(f"\n対応のある比較（同じ分岐点から両方走らせた {m} 対）:")
    print(f"  同じ結果になった対: {same} ({same / m * 100:.1f}%)")
    print(f"  A だけ勝った: {ab} / B だけ勝った: {ba}")
    print(f"  **勝率差 (A − B) = {diff:+.3f}**")

    # 差の信頼区間は対を単位にしたブートストラップで出す（作業規約6）。
    import random as _r
    rng = _r.Random(20260824)
    d = [int(r["a_won"]) - int(r["b_won"]) for r in rows]
    boot = sorted(sum(rng.choice(d) for _ in range(m)) / m for _ in range(2000))
    lo, hi = boot[int(2000 * 0.025)], boot[int(2000 * 0.975)]
    print(f"  95% 区間 [{lo:+.3f}, {hi:+.3f}]  "
          f"{'→ 0 を含まないので差があると言える' if lo > 0 or hi < 0 else '→ 0 を含むので差があるとは言えない'}")

    # ターン帯別の内訳。**いつやるか**で答えが変わるなら、それ自体が知見である。
    print("\nターン帯別の内訳（A − B の勝率差）:")
    print(f"{'ターン':>10}{'対の数':>8}{'Aの勝率':>10}{'Bの勝率':>10}{'差':>9}")
    for lo_t, hi_t in ((1, 2), (3, 4), (5, 6), (7, 9), (10, 99)):
        g = [r for r in rows if lo_t <= r["turn"] <= hi_t]
        if not g:
            continue
        pa = sum(x["a_won"] for x in g) / len(g)
        pb = sum(x["b_won"] for x in g) / len(g)
        print(f"{f'{lo_t}-{hi_t}':>10}{len(g):>8}{pa:>10.3f}{pb:>10.3f}{pa - pb:>+9.3f}")

    print("\n【解釈の手引き】")
    print("  差がプラス = 今レベルアップした方が勝ちやすい（現行評価関数 +0.498 を支持）")
    print("  差がマイナス = 今はやらない方が勝ちやすい（学習した重み −0.197 を支持）")


if __name__ == "__main__":
    main()
