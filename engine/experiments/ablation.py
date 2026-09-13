"""A-4: ヒューリスティックの規則のアブレーション（レビュー 2026-08-23 §6 A-4 / §3.5）。

引継ぎ書のアブレーションは**SD001同型の自己対戦のみ**だった。レビュー §3.5 は
「同型対戦の相対寄与は絶対値を強調しうる」と指摘している。本スクリプトは
3つの条件で測り直し、条件をまたいで一貫して寄与ゼロの規則だけを削除候補とする。

1. 同型戦（SD001 vs SD001）— 従来条件の再現
2. **異型戦（SD001 vs SD02）** — デッキ非依存の知見かどうかの切り分け
3. **探索のロールアウト方策として** — ヒューリスティックは今や計画探索の
   非担当フェイズと相手モデルを兼ねている。規則を落としたときに
   **計画探索の強さ**が変わるかを見る。ここが現在いちばん重要な用途である。

読み方: 表の数字は「規則を**無効にした**版の勝率」。0.5 を明確に下回れば
その規則は効いている。0.5 と信頼区間で重なれば寄与なし。

使い方: python3 experiments/ablation.py [n] [n_planner] [workers]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import load_deck, matchup_config, mirror_config, series   # noqa: E402
from meicho.heuristic import HeuristicAgent, Params                  # noqa: E402
from meicho.planner import PlannerAgent, TUNED_PARAMS                # noqa: E402

SD001 = load_deck("SD001")
SD02 = load_deck("SD02")
MIRROR = mirror_config(SD001)
CROSS = matchup_config(SD001, SD02)
POOL = SD001["action_deck"]

# 検証する規則（Params の use_* フラグ）
RULES = [
    ("use_charge",       "協奏エリアの整備"),
    ("use_levelup",      "レベルアップ"),
    ("use_switch",       "赤を生き返らせる切り替え"),
    ("use_card_utility", "捨て札を価値で選ぶ"),
    ("use_color_mix",    "対抗の色の混合"),
]
# 2026-08-23 の測定で3条件とも寄与ゼロだった3規則は heuristic.py から削除済み。
# 測定値（無効版の勝率、同型/異型/計画探索の中で）:
#   リーサル確定          0.492 / 0.498 / 0.475
#   連撃中の変奏コンボ    0.508 / 0.505 / 0.485
#   出せないなら対抗しない 0.503 / 0.508 / 0.480
# いずれも信頼区間が 0.5 を含む。再測定したい場合はコミット履歴から戻すこと。


class MkH:
    def __init__(self, **kw):
        self.kw = kw

    def __call__(self, seed):
        return HeuristicAgent(seed, Params(**self.kw))


class MkP:
    """計画探索。fallback（ロールアウト方策・相手モデル）の規則を差し替える。"""

    def __init__(self, **kw):
        self.kw = kw

    def __call__(self, seed):
        base = dict(TUNED_PARAMS.__dict__)
        base.update(self.kw)
        return PlannerAgent(seed, opp_decklist=POOL, plan_samples=2,
                            params=Params(**base))


def run(n, n_planner, workers):
    base_h, base_p = MkH(), MkP()
    print(f"規則を無効にした版の勝率（0.5を下回れば規則が効いている）\n")
    print(f"| 無効にした規則 | 同型戦(n={n}) | 異型戦 SD001vsSD02(n={n}) | "
          f"計画探索の中で(n={n_planner}) |")
    print("|---|---|---|---|")
    for flag, label in RULES:
        off_h = MkH(**{flag: False})
        r1 = series(off_h, base_h, n, MIRROR, workers)
        r2 = series(off_h, base_h, n, CROSS, workers)
        r3 = series(MkP(**{flag: False}), base_p, n_planner, MIRROR, workers)
        print(f"| {label} | {r1} | {r2} | {r3} |", flush=True)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    n_planner = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    run(n, n_planner, workers)
