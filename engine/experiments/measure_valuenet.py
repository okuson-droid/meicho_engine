"""C-1 §4.1-2 学習価値関数の強さを測る（D-038）。

rules_draft.md v0.10 準拠。**予測が良くなったことと強くなったことは別である。**
`train_linear.py` は予測性能（logloss）で CEM の到達点を上回ったが、
計画探索が `_eval` に求めているのは「近接する葉の順序づけ」であって
確率の当てやすさではない。ここでその翻訳が起きるかを実測する。

- 相手: H_default（歴史的な物差し）と **現 champion の計画探索**（D-034 の判定基準）
- シード帯 110000..（**学習にも λ 選択にも使っていない**。D-028）
- 勝率は必ず n と 95%CI を伴う（作業規約6）

実行: python3 experiments/measure_valuenet.py [n] [--workers 2]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from arena import load_deck, mirror_config, series                  # noqa: E402
from registry import make                                           # noqa: E402

SEED0 = 110000          # seed_bands.json に登録済み（C-1 §4.1-2 の測定専用）
MODEL = "c1_linear_v1.json"


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 300
    workers = 2 if "--workers" in sys.argv else 1
    deck = load_deck("SD001")
    cfg, pool = mirror_config(deck), deck["action_deck"]
    mk = {
        "planner_v": make("planner_v", {"model": MODEL}, pool),
        # 共線性の仮説を切り分けるための変種（D-038 の診断）。
        # logit6 は現行と同じ6特徴で、厳密な線形従属を含まない。
        "planner_v6": make("planner_v", {"model": "c1_logit6.json"}, pool),
        "planner": make("planner", None, pool),
        "H": make("heuristic", None, None),
    }
    print(f"モデル {MODEL} / シード帯 {SEED0}.. / n={n} / workers={workers}")
    print(f"{'対戦':<28}{'勝率':>26}")
    pairs = [("planner_v", "H"), ("planner", "H"), ("planner_v", "planner")]
    if "--v6" in sys.argv:
        pairs = [("planner_v6", "H"), ("planner_v6", "planner")]
    for a, b in pairs:
        r = series(mk[a], mk[b], n, cfg, workers=workers, seed0=SEED0)
        lo = r.p - r.ci
        mark = ""
        if b == "planner":
            mark = ("  ← 95%下限 > 0.5。champion 交代の条件を満たす" if lo > 0.5
                    else "  ← 95%下限 ≤ 0.5。交代しない（D-034）")
        print(f"{a + ' vs ' + b:<28}{str(r):>26}{mark}")


if __name__ == "__main__":
    main()
