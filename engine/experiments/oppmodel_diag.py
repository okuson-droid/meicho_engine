"""B-3 の診断: 相手モデルは「当たっているか」と「手を変えているか」。

勝率が動かなかったとき、原因は2つに切り分けられる。

1. **予測が当たっていない** → モデルの作りが悪い
2. **予測は当たっているが、自分の手が変わらない** → そもそも対抗の最適手が
   相手の色にほとんど依存しない（A-5 で「踏むのは割に合わない」と出たことと整合）

本スクリプトは実対局のリプレイ中、プレイヤー0の対抗提出ノードで
次の3つを記録して、どちらなのかを判定する。

- 固定方策（事前分布）が予測した相手の色
- 履歴モデルが予測した相手の色
- 実際に相手が提出した色

さらに、履歴あり／なしのエージェントが**同じ手を選ぶか**を数える。
予測はどちらも決定化した局面の上で行う（探索が実際に使う条件と揃える）。

使い方: python3 experiments/oppmodel_diag.py [n_games]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import load_deck, mirror_config                            # noqa: E402
from meicho.cards import ACTION_CARDS                                 # noqa: E402
from meicho.engine import apply, decision_players, initial_state, outcome  # noqa: E402
from meicho.heuristic import HeuristicAgent, Params                   # noqa: E402
from meicho.planner import PlannerAgent                               # noqa: E402
from meicho.state import Phase                                        # noqa: E402

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]


def _rngs(a):
    out = [a.rng, a.fallback.rng, a.opp_model.rng]
    return out


def run(n_games, opponent, label):
    hit_prior = hit_hist = pred_n = 0
    same_action = act_n = 0
    used_history = 0
    for g in range(n_games):
        seed = 60000 + g
        a0 = PlannerAgent(seed * 2, opp_decklist=POOL, plan_samples=2,
                          use_history=True)
        a0_off = PlannerAgent(seed * 2, opp_decklist=POOL, plan_samples=2,
                              use_history=False)
        a1 = opponent(seed * 2 + 1)
        s = initial_state(CONFIG, seed)
        while outcome(s) is None and s.turn_no <= 200:
            need = decision_players(s)
            acts = {}
            if s.phase == Phase.CLASH_SUBMIT and 0 in need:
                # --- 予測の当たり具合 ---
                st = [r.getstate() for r in _rngs(a0)]
                t = a0._determinize(s, 0)
                p_prior = a0.fallback.act(t, 1)
                n_obs = sum(s.clash_counts[1][:3])
                if n_obs > 0:
                    used_history += 1
                p_hist = a0.opp_model.act(t, 1)
                for r, x in zip(_rngs(a0), st):
                    r.setstate(x)
                # --- 手が変わるか ---
                for r, x in zip(_rngs(a0_off), st):
                    r.setstate(x)
                mine_on = a0.act(s, 0)
                for r, x in zip(_rngs(a0), st):
                    r.setstate(x)
                mine_off = a0_off.act(s, 0)
                same_action += (mine_on == mine_off)
                act_n += 1
                for r, x in zip(_rngs(a0), st):
                    r.setstate(x)
                acts[0] = a0.act(s, 0)
                for pi in need:
                    if pi != 0:
                        acts[pi] = a1.act(s, pi)
                nxt = apply(s, acts)
                # 実際に相手が出した色（公開後）
                real = nxt.clash_cards[1] if nxt.clash_cards[1] else None
                if real is not None:
                    pred_n += 1
                    rc = ACTION_CARDS[real].color
                    hit_prior += (p_prior.get("type") == "submit"
                                  and ACTION_CARDS[t.players[1].hand[
                                      p_prior["hand"]]].color == rc)
                    hit_hist += (p_hist.get("type") == "submit"
                                 and ACTION_CARDS[t.players[1].hand[
                                     p_hist["hand"]]].color == rc)
                s = nxt
                continue
            for pi in need:
                acts[pi] = (a0 if pi == 0 else a1).act(s, pi)
            s = apply(s, acts)
    print(f"--- {label} ({n_games}局) ---")
    print(f"  対抗の予測ノード {pred_n} 件（うち履歴が使える状態 {used_history}）")
    if pred_n:
        print(f"  色の的中率: 固定方策 {hit_prior/pred_n:.3f} / "
              f"履歴モデル {hit_hist/pred_n:.3f}")
    if act_n:
        print(f"  自分の手が**一致**した割合: {same_action/act_n:.3f} "
              f"（{act_n} ノード中 {act_n - same_action} 件だけ違う手になった）")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    run(n, lambda sd: HeuristicAgent(sd, Params(counter_weight=6.0,
                                                own_color_weight=1.5)),
        "vs X3（踏み型・事前分布と最も違う相手）")
    run(n, lambda sd: HeuristicAgent(sd), "vs H_default（事前分布と一致）")
