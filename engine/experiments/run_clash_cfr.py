"""対抗ステップ CFR 実験の実行スクリプト。

再現: python3 experiments/run_clash_cfr.py
シードはすべて固定。乱数はエージェント側の random.Random(seed) のみ。
"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import clash_cfr as C

HERE = os.path.dirname(__file__)
SD001 = json.load(open(os.path.join(HERE, "..", "decklists", "SD001.json"), encoding="utf-8"))
SD02 = json.load(open(os.path.join(HERE, "..", "decklists", "SD02.json"), encoding="utf-8"))

LEADERS_SD001 = {"漂泊者（女）": "BP01-018", "秧秧": "BP01-024", "熾霞": "BP01-027"}
LEADERS_SD02 = {"漂泊者（男）": "BP01-021", "散華": "BP01-033", "今汐": "BP01-030"}

ITERS = 20000
BR_SAMPLES = 20000


def color_mix(cfr, side):
    """情報集合ごとの平均戦略を、色ごとの重みつき平均に畳み込む。"""
    agg = Counter()
    total = 0.0
    per_infoset = {}
    for key in cfr.regret:
        if key[0] != side:
            continue
        w = sum(cfr.strategy_sum[key])
        if w <= 0:
            continue
        avg = cfr.average(key)
        per_infoset[key] = (w, avg)
        for a, p in avg.items():
            agg[a] += p * w
        total += w
    return {a: v / total for a, v in agg.items()}, per_infoset, total


def fmt_mix(mix):
    order = ["赤", "青", "緑", C.PASS]
    return "  ".join(f"{a}:{mix.get(a, 0.0)*100:5.1f}%" for a in order if a in mix)


def run(label, decks, chara_decks, leaders, w_card, w_conc, seed=1, verbose=True):
    cfr = C.run_cfr(decks, chara_decks, leaders, ITERS, seed, w_card, w_conc)
    mixT, perT, _ = color_mix(cfr, "T")
    mixN, perN, _ = color_mix(cfr, "N")
    v0, v1, gap = C.exploitability(cfr, decks, chara_decks, leaders,
                                   BR_SAMPLES, seed + 1000, w_card, w_conc)
    if verbose:
        print(f"\n### {label}")
        print(f"  ターンプレイヤー   {fmt_mix(mixT)}")
        print(f"  非ターンプレイヤー {fmt_mix(mixN)}")
        print(f"  ナッシュ・ギャップ {gap:+.3f}（0に近いほど均衡, BR0={v0:+.3f} BR1={v1:+.3f}）")
    return cfr, mixT, mixN, gap, perT, perN


# ---------------------------------------------------------------------------
# 固定方策との比較（混ぜることの価値を測る）
# ---------------------------------------------------------------------------

def fixed_policy(kind):
    """比較用の単純方策。infoset の行動集合から確率分布を返す。"""
    def policy(acts):
        cols = [a for a in acts if a != C.PASS]
        if not cols:
            return {C.PASS: 1.0}
        if kind == "uniform":
            return {a: 1.0 / len(acts) for a in acts}
        pref = {"always_red": "赤", "always_blue": "青", "always_green": "緑"}[kind]
        if pref in cols:
            return {pref: 1.0}
        return {cols[0]: 1.0}
    return policy


def head_to_head(cfr, decks, chara_decks, leaders, p0, p1, samples, seed,
                 w_card, w_conc):
    """P0方策 vs P1方策 の期待利得（P0視点）。方策は cfr または fixed_policy。"""
    import random
    rng = random.Random(seed)
    tot = 0.0
    n = 0
    for _ in range(samples):
        h0, h1 = C.deal(decks[0], rng), C.deal(decks[1], rng)
        s = C.make_state(decks, chara_decks, leaders, [h0, h1])
        a0, a1 = C.actions_for(s, 0), C.actions_for(s, 1)
        k0, k1 = C.infoset_key(s, 0), C.infoset_key(s, 1)
        d0 = cfr.average(k0) if p0 == "cfr" and k0 in cfr.regret else p0(a0) if callable(p0) else None
        d1 = cfr.average(k1) if p1 == "cfr" and k1 in cfr.regret else p1(a1) if callable(p1) else None
        if d0 is None or d1 is None:
            continue
        v = 0.0
        for i, x in enumerate(a0):
            px = d0.get(x, 0.0)
            if px <= 0:
                continue
            for j, y in enumerate(a1):
                py = d1.get(y, 0.0)
                if py <= 0:
                    continue
                v += px * py * C.payoff(s, C.to_engine_action(s, 0, x),
                                        C.to_engine_action(s, 1, y), w_card, w_conc)
        tot += v
        n += 1
    return tot / max(n, 1)


# ---------------------------------------------------------------------------
# 実験の実行
# ---------------------------------------------------------------------------

def experiment_leader_matrix(w_card=1.0, w_conc=0.5, iters=10000):
    """リーダーの組み合わせ別の均衡混合戦略（本実験の主結果）。"""
    global ITERS, BR_SAMPLES
    ITERS, BR_SAMPLES = iters, 6000
    deck, ch = SD001["action_deck"], SD001["chara_deck"]
    print("=" * 78)
    print(f"リーダーの組み合わせ別の均衡混合戦略（SD001同型, "
          f"w_card={w_card}/w_conc={w_conc}, {iters}反復）")
    print("  各セル = ターンプレイヤー(P0)の色の出現比率")
    print("=" * 78)
    print(f"{'P0リーダー':12s}{'P1リーダー':12s}  {'赤':>7s}{'青':>7s}{'緑':>7s}   gap")
    for n0, c0 in LEADERS_SD001.items():
        for n1, c1 in LEADERS_SD001.items():
            _, mT, _, gap, _, _ = run("", [deck, deck], [ch, ch], [c0, c1],
                                      w_card, w_conc, verbose=False)
            print(f"{n0:12s}{n1:12s}  " +
                  "".join(f"{mT.get(k, 0)*100:6.1f}%" for k in ["赤", "青", "緑"]) +
                  f"   {gap:+.3f}")


def experiment_weight_sensitivity(iters=10000):
    """利得関数の重みに対する感度。結論の頑健性を確認する。"""
    global ITERS, BR_SAMPLES
    ITERS, BR_SAMPLES = iters, 6000
    deck, ch = SD001["action_deck"], SD001["chara_deck"]
    print("\n" + "=" * 78)
    print(f"利得関数の重みに対する感度（SD001同型, {iters}反復）")
    print("=" * 78)
    for name, cid in LEADERS_SD001.items():
        print(f"\n--- 両者リーダー {name} ---")
        for wc, wo in [(0.0, 0.0), (0.5, 0.3), (1.0, 0.5), (2.0, 1.0)]:
            _, mT, _, gap, _, _ = run("", [deck, deck], [ch, ch], [cid, cid],
                                      wc, wo, verbose=False)
            print(f"  w_card={wc:<4} w_conc={wo:<4} 手番 {fmt_mix(mT):46s} gap={gap:+.3f}")


def experiment_vs_fixed(w_card=1.0, w_conc=0.5, iters=20000, samples=5000):
    """CFRの混合戦略が単純な固定方策をどれだけ上回るか。"""
    global ITERS
    ITERS = iters
    deck, ch = SD001["action_deck"], SD001["chara_deck"]
    print("\n" + "=" * 78)
    print(f"CFRの混合戦略 vs 固定方策（w_card={w_card}/w_conc={w_conc}）")
    print("  数値 = 均衡値からの上振れ。大きいほどその固定方策が搾取されている")
    print("=" * 78)
    for name, cid in LEADERS_SD001.items():
        cfr = C.run_cfr([deck, deck], [ch, ch], [cid, cid], ITERS, 1, w_card, w_conc)
        base = head_to_head(cfr, [deck, deck], [ch, ch], [cid, cid],
                            "cfr", "cfr", samples, 77, w_card, w_conc)
        cells = []
        for k in ["always_red", "always_blue", "always_green", "uniform"]:
            v = head_to_head(cfr, [deck, deck], [ch, ch], [cid, cid],
                             "cfr", fixed_policy(k), samples, 77, w_card, w_conc)
            cells.append(f"{k:12s}{v - base:+6.2f}")
        print(f"  リーダー{name:8s} 均衡値={base:+5.2f}")
        print("    " + "  ".join(cells))


if __name__ == "__main__":
    experiment_leader_matrix()
    experiment_weight_sensitivity()
    experiment_vs_fixed()
