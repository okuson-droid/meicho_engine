"""C-1 §4.1-2 学習価値関数が「予測は良いのに強くならない」理由の診断（D-038）。

rules_draft.md v0.10 準拠。B-3（`B3_NOTES.md` / D-032）が相手モデルの負の結果を
「なぜ効かないか」まで診断した手本にならう。

## 診断の着眼

計画探索が `_eval` に求めているのは**勝率の当てやすさではない**。
1つの決定の中で作られる候補終端どうしを**正しく順序づけること**である。

したがって、決定の中で**値が動かない特徴**は、どれだけ予測に効いても
選択にはまったく寄与しない。線形モデルの得点は Σ wᵢxᵢ なので、
決定内での得点のばらつきへの寄与は **wᵢ × (決定内での xᵢ の標準偏差)** に分解できる。
これを CEM の重みと学習した重みで比べれば、**学習が精度をどこに使ったか**が見える。

## 測ること

1. 各特徴の「決定内の標準偏差 ÷ 全体の標準偏差」= 決定に効きうる余地
2. 決定内の得点のばらつきへの寄与の分解（CEM の重み vs 学習した重み）
3. 学習モデルと手書き評価の**順位の一致度**（Spearman）と argmax の一致率
4. 飽和の検査: 勝勢・敗勢の局面で log-odds のばらつきが潰れていないか

実行: python3 experiments/diag_valuenet.py [n_games]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np                                                  # noqa: E402

from arena import load_deck, mirror_config                          # noqa: E402
from train_linear import cem_score                                  # noqa: E402
from meicho import features as F                                    # noqa: E402
from meicho.engine import apply, decision_players, initial_state, outcome  # noqa: E402
from meicho.heuristic import HeuristicAgent                         # noqa: E402
from meicho.valuenet import LinearValue, ValuePlannerAgent          # noqa: E402

SEED0 = 110000          # 測定と同じ帯（seed_bands.json 登録済み）
MODEL = "c1_linear_v1.json"


class _Probe(ValuePlannerAgent):
    """1決定化ぶんの候補終端をまとめて記録する。

    比較は1つの決定化の中で行われる（`_plan` は max-then-mean で、
    決定化ごとに最良を取ってから平均する）。したがって決定化を
    またいで混ぜると、引く札の違いによるばらつきを数えてしまう。
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.groups = []
        self._cur = None

    def _search(self, t, pi, first, depth, leaves, seen):
        if first is None:                 # 根＝1つの決定化の開始
            self._cur = []
            self.groups.append(self._cur)
        return super()._search(t, pi, first, depth, leaves, seen)

    def _eval(self, s, pi):
        v = super()._eval(s, pi)
        if self._cur is not None and s.outcome is None:
            self._cur.append(F.from_state(s, pi))
        return v


def collect(n_games=6):
    deck = load_deck("SD001")
    cfg, pool = mirror_config(deck), deck["action_deck"]
    groups = []
    for seed in range(SEED0, SEED0 + n_games):
        a = _Probe(seed * 2, model=MODEL, opp_decklist=pool)
        b = HeuristicAgent(seed * 2 + 1)
        s = initial_state(cfg, seed)
        while outcome(s) is None and s.turn_no <= 200:
            need = decision_players(s)
            s = apply(s, {pi: [a, b][pi].act(s, pi) for pi in need})
        groups += [g for g in a.groups if len(g) >= 3]
    return [np.array(g) for g in groups]


def main():
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    print("== 学習価値関数の診断（C-1 §4.1-2 / D-038）==")
    groups = collect(n_games)
    allX = np.vstack(groups)
    print(f"{n_games} 局 / 決定化 {len(groups)} 件 / 候補終端 {len(allX)} 件"
          f"（1決定化あたり中央値 {int(np.median([len(g) for g in groups]))} 件）\n")

    v = LinearValue(MODEL)
    w_learned = np.zeros(F.N_FEAT)
    for k, i in enumerate(v.idx):
        w_learned[i] = v.w[k]
    # CEM の重み（現行 evaluate）を同じ 22 次元に写す
    from meicho.planner import TUNED_WEIGHTS as T
    w_cem = np.zeros(F.N_FEAT)
    for name, val in (("life_diff", T.life), ("concerto_diff", T.concerto),
                      ("hand_diff", T.hand), ("live_reds", T.live_red),
                      ("level_diff", T.level)):
        w_cem[F.FEATURE_NAMES.index(name)] = val
    for name, sgn in (("deck_me", 1), ("trash_me", 1),
                      ("deck_opp", -1), ("trash_opp", -1)):
        w_cem[F.FEATURE_NAMES.index(name)] = sgn * T.resource

    # --- 1〜2. 決定内の可動域と、得点のばらつきへの寄与 --------------------
    within = np.zeros(F.N_FEAT)
    for g in groups:
        within += g.std(axis=0)
    within /= len(groups)
    overall = allX.std(axis=0)

    contrib_l = np.abs(w_learned) * within
    contrib_c = np.abs(w_cem) * within
    order = np.argsort(-(contrib_l + contrib_c))
    print("== 決定内で動く余地と、選択への寄与 ==")
    print("（寄与 = |重み| × 決定内の標準偏差。決定内で動かない特徴は寄与ゼロ）")
    print(f"{'特徴':<18}{'決定内sd':>9}{'全体sd':>9}{'可動比':>8}"
          f"{'寄与:学習':>11}{'寄与:CEM':>10}")
    for i in order:
        if contrib_l[i] < 1e-6 and contrib_c[i] < 1e-6 and within[i] < 1e-6:
            continue
        ratio = within[i] / overall[i] if overall[i] > 1e-12 else 0.0
        print(f"{F.FEATURE_NAMES[i]:<18}{within[i]:>9.3f}{overall[i]:>9.3f}"
              f"{ratio:>8.2f}{contrib_l[i]:>11.4f}{contrib_c[i]:>10.4f}")
    print(f"{'合計':<18}{'':>9}{'':>9}{'':>8}"
          f"{contrib_l.sum():>11.4f}{contrib_c.sum():>10.4f}")

    # 決定内で動かない特徴に、学習はどれだけ重みを置いたか
    frozen = [i for i in range(F.N_FEAT)
              if overall[i] > 1e-12 and within[i] / overall[i] < 0.05]
    tot_l = np.abs(w_learned * overall).sum()
    fz_l = np.abs(w_learned[frozen] * overall[frozen]).sum()
    print(f"\n決定内でほぼ動かない特徴（可動比 < 0.05）: "
          f"{[F.FEATURE_NAMES[i] for i in frozen]}")
    print(f"  学習モデルがそこに置いた重み（全体sd で正規化）: "
          f"{fz_l / tot_l * 100:.1f}%")

    # --- 3. 順位の一致 ------------------------------------------------------
    def spearman(a, b):
        ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
        ra, rb = ra - ra.mean(), rb - rb.mean()
        d = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
        return float((ra * rb).sum() / d) if d > 0 else 1.0

    rho, same_top, sd_l, sd_c, mean_lo = [], 0, [], [], []
    for g in groups:
        vl = g @ w_learned
        vc = cem_score(g)
        rho.append(spearman(vl, vc))
        same_top += int(np.argmax(vl) == np.argmax(vc))
        sd_l.append(vl.std())
        sd_c.append(vc.std())
        mean_lo.append(vl.mean() + v.b)
    print("\n== 手書き評価との順位の一致（決定化ごと）==")
    print(f"  Spearman ρ: 中央値 {np.median(rho):.3f} / 平均 {np.mean(rho):.3f}")
    print(f"  最良候補が一致した決定化: {same_top}/{len(groups)} "
          f"({same_top / len(groups) * 100:.1f}%)")

    # --- 4. 飽和の検査 ------------------------------------------------------
    mean_lo = np.array(mean_lo)
    sd_l = np.array(sd_l)
    print("\n== 飽和の検査（決定化の平均 log-odds 別の、決定内のばらつき）==")
    print(f"{'|平均log-odds|':>14}{'件数':>7}{'学習のsd':>11}{'CEMのsd':>10}")
    sd_c = np.array(sd_c)
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 100)):
        m = (np.abs(mean_lo) >= lo) & (np.abs(mean_lo) < hi)
        if m.sum():
            print(f"{f'{lo}–{hi}':>14}{m.sum():>7}{sd_l[m].mean():>11.4f}"
                  f"{sd_c[m].mean():>10.4f}")
    print("\n（学習側は log-odds、CEM 側は素点なので絶対値は比較できない。"
          "見るのは**帯によって潰れるかどうか**である）")
    rel_l = sd_l / (np.abs(sd_l).mean() + 1e-12)
    rel_c = sd_c / (np.abs(sd_c).mean() + 1e-12)
    for lo, hi in ((0, 1), (4, 100)):
        m = (np.abs(mean_lo) >= lo) & (np.abs(mean_lo) < hi)
        if m.sum():
            print(f"  |log-odds| {lo}–{hi}: 相対ばらつき 学習 {rel_l[m].mean():.3f} / "
                  f"CEM {rel_c[m].mean():.3f}")


if __name__ == "__main__":
    main()
