"""エージェントの生成。登録簿は experiments/registry.py を正本として再利用する。

ラダー（C-4）と同じ登録名を使うことで、
「アプリで戦った相手」と「ラダーに載っている相手」が同一であることを保証する。
別に定義を持つと、名前は同じで中身が違う事故が起きうる。
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for _p in (_ROOT, os.path.join(_ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from registry import FACTORIES, Mk, make        # noqa: E402,F401

# アプリで相手に選べるもの。ラダーの登録名と一対一で対応する。
# Elo はラダー core5 v9（`results/ladder.md`）の値。champion を替えたら**ここも同時に直す**
# （`tests/test_drl.py::test_champion_definition_is_consistent_everywhere` が食い違いを見つける）。
OPPONENTS = {
    # 便 E-0（2026-09-08 交代・D-073）。旧 champion `planner_vb3cps` から**葉の V だけ**を
    # 学習の輪 2 の反復 4' の成果に替えたもの。直接対決 0.569 ±0.028（下端 0.541・n=1,200）。
    "planner_vc4cps": {"factory": "planner_vb",
                       "kwargs": {"extra_turns": 1,
                                  "value_net": "drl_sd001_vc4.json",
                                  "opp_policy_net": "drl_sd001_s1.json",
                                  "opp_policy_root_only": True,
                                  "choice_phases": True,
                                  "solo_samples": 4,
                                  "policy_net": "pi_small64_e10.json",
                                  "policy_scope": "proxy"},
                       "label": "計画探索＋地平延長＋葉=V_4'＋選択フェイズも探索＋代打ちπ(小)"
                                "（現champion・2026-09-08 交代・Elo 1522 [1500,1546]"
                                "・ラダー core5 v9・SD001専用）",
                       "decks": ("SD001",)},
    # 便 E-0 §4.3 の診断で、この構成は 2026-09-03 の回帰 2 局面の**両方**で「燃える烈火」を選んだ
    # （現 champion の既定は当時どおりパス／音の形・回避）。**強さは未測定**——`lu50` の数字
    # （D-071・対差 −0.035）は**葉が V_3 のときの値**であり、この土俵では測り直していない。
    "planner_vc4cps_lu50": {"factory": "planner_vb",
                            "kwargs": {"extra_turns": 1,
                                       "value_net": "drl_sd001_vc4.json",
                                       "opp_policy_net": "drl_sd001_s1.json",
                                       "opp_policy_root_only": True,
                                       "choice_phases": True,
                                       "solo_samples": 4,
                                       "policy_net": "pi_small64_e10.json",
                                       "policy_scope": "proxy",
                                       "lethal_uniform": 0.5},
                            "label": "現champion＋詰みが見えるときだけ相手を等重みに"
                                     "（θ=0.5・候補・**未測定**・SD001専用）",
                            "decks": ("SD001",)},
    # 文献計画 便 C 段 C-1（II-7 (a)・D-077）の候補。**現 champion への差分は 1 つだけ**——
    # スキャンで見た札を決定化に必ず入れる。被覆率は上がった（真の手札を捉える割合は
    # 見えている札がある決定で 0.018 → 0.257・K=6）。**強さは測定中**。
    "planner_vc4cps_kh": {"factory": "planner_vb",
                          "kwargs": {"extra_turns": 1,
                                     "value_net": "drl_sd001_vc4.json",
                                     "opp_policy_net": "drl_sd001_s1.json",
                                     "opp_policy_root_only": True,
                                     "choice_phases": True,
                                     "solo_samples": 4,
                                     "policy_net": "pi_small64_e10.json",
                                     "policy_scope": "proxy",
                                     "known_hand": True},
                          "label": "現champion＋スキャンで見た札を決定化に必ず入れる"
                                   "（便 C 段 C-1 の候補・SD001専用）",
                          "decks": ("SD001",)},
    # 文献計画 便 C 段 C-2（II-8・D-077 追記 2）の候補。段 C-1 のつまみに
    # 「相手が直近の対抗で出した札から、どの手札がもっともらしいか」の重みを積んだもの。
    "planner_vc4cps_khw": {"factory": "planner_vb",
                           "kwargs": {"extra_turns": 1,
                                      "value_net": "drl_sd001_vc4.json",
                                      "opp_policy_net": "drl_sd001_s1.json",
                                      "opp_policy_root_only": True,
                                      "choice_phases": True,
                                      "solo_samples": 4,
                                      "policy_net": "pi_small64_e10.json",
                                      "policy_scope": "proxy",
                                      "known_hand": True,
                                      "world_weight": 0.75},
                           "label": "現champion＋スキャンの札を必ず入れる＋π₀ の到達確率で"
                                    "決定化に重み付け（便 C 段 C-2 の候補・SD001専用）",
                           "decks": ("SD001",)},
    # 文献計画 便 C 段 C-3（II-9・D-077 追記 3）の候補。段 C-1 のつまみに
    # 「終盤（ありうる手札が 64 通り以下）は決定化をやめて全部数え、投票で決める」を積んだもの。
    # **SD001 ミラー専用**——列挙は相手のデッキリストが分かっていることに寄りかかっており、
    # 相手のデッキが違うと真の手札を 1 本も含まないまま確信する（§7 の 14）。
    "planner_vc4cps_khe": {"factory": "planner_vb",
                           "kwargs": {"extra_turns": 1,
                                      "value_net": "drl_sd001_vc4.json",
                                      "opp_policy_net": "drl_sd001_s1.json",
                                      "opp_policy_root_only": True,
                                      "choice_phases": True,
                                      "solo_samples": 4,
                                      "policy_net": "pi_small64_e10.json",
                                      "policy_scope": "proxy",
                                      "known_hand": True,
                                      "endgame_enum": 64},
                           "label": "現champion＋スキャンの札を必ず入れる＋終盤は整合世界を"
                                    "全列挙して投票（便 C 段 C-3 の候補・SD001専用）",
                           "decks": ("SD001",)},
    # 文献計画 便 C 段 C-4（ドローのバケット化・D-077 追記 4）の候補。段 C-3 の候補に
    # 「決定化 K 本の山札の上位 3 枚をコスト帯 × 色の層で散らす」を積んだもの。
    # 段 C-3 と同じく **SD001 ミラー専用**（`endgame_enum` を含むため）。
    "planner_vc4cps_kheb": {"factory": "planner_vb",
                            "kwargs": {"extra_turns": 1,
                                       "value_net": "drl_sd001_vc4.json",
                                       "opp_policy_net": "drl_sd001_s1.json",
                                       "opp_policy_root_only": True,
                                       "choice_phases": True,
                                       "solo_samples": 4,
                                       "policy_net": "pi_small64_e10.json",
                                       "policy_scope": "proxy",
                                       "known_hand": True,
                                       "endgame_enum": 64,
                                       "draw_buckets": 1},
                            "label": "一つ前のchampion（便 C・世界の作り方まで・SD001専用）",
                            "decks": ("SD001",)},
    # 文献計画 便 A 後半（A-2・D-082 追記 2）の **現 champion**。上に
    # 「対抗は束ねたゲームを解いて平均戦略から選ぶ」（`bundle_p=0.75`）を積んだもの。
    # 段 C-3 以降と同じく **SD001 ミラー専用**（`endgame_enum` を含むため）。
    "planner_vc4cps_kheb_b75": {"factory": "planner_vb",
                                "kwargs": {"extra_turns": 1,
                                           "value_net": "drl_sd001_vc4.json",
                                           "opp_policy_net": "drl_sd001_s1.json",
                                           "opp_policy_root_only": True,
                                           "choice_phases": True,
                                           "solo_samples": 4,
                                           "policy_net": "pi_small64_e10.json",
                                           "policy_scope": "proxy",
                                           "known_hand": True,
                                           "endgame_enum": 64,
                                           "draw_buckets": 1,
                                           "bundle_p": 0.75},
                                "label": "現champion（便 A 後半・束ねた対抗ゲーム・SD001専用）",
                                "decks": ("SD001",)},
    "planner_vb3cps": {"factory": "planner_vb",
                       "kwargs": {"extra_turns": 1,
                                  "value_net": "drl_sd001_vb3.json",
                                  "opp_policy_net": "drl_sd001_s1.json",
                                  "opp_policy_root_only": True,
                                  "choice_phases": True,
                                  "solo_samples": 4,
                                  "policy_net": "pi_small64_e10.json",
                                  "policy_scope": "proxy"},
                       "label": "計画探索＋地平延長＋葉=V_3＋選択フェイズも探索＋代打ちπ(小)"
                                "（旧champion・Elo 1474 [1452,1499]・SD001専用）",
                       "decks": ("SD001",)},
    # 文献計画 便 A（前半）の候補。**旧 champion（V_3）への差分**である。便 E-0 で champion が
    # 替わったので、この 2 つの数字（D-071）は「一つ前の土俵の値」になった。
    # マスターが対人局で試せるように残す（`HANDOFF_20260907_LIT_A.md` §3.3・§4.6）。
    "planner_vb3cps_lu50": {"factory": "planner_vb",
                            "kwargs": {"extra_turns": 1,
                                       "value_net": "drl_sd001_vb3.json",
                                       "opp_policy_net": "drl_sd001_s1.json",
                                       "opp_policy_root_only": True,
                                       "choice_phases": True,
                                       "solo_samples": 4,
                                       "policy_net": "pi_small64_e10.json",
                                       "policy_scope": "proxy",
                                       "lethal_uniform": 0.5},
                            "label": "旧champion(V_3)＋詰みが見えるときだけ相手を等重みに"
                                     "（θ=0.5・便 A の候補・対差 −0.035 で不採用・SD001専用）",
                            "decks": ("SD001",)},
    "planner_vb3cps_m100": {"factory": "planner_vb",
                            "kwargs": {"extra_turns": 1,
                                       "value_net": "drl_sd001_vb3.json",
                                       "opp_policy_net": "drl_sd001_s1.json",
                                       "opp_policy_root_only": True,
                                       "choice_phases": True,
                                       "solo_samples": 4,
                                       "policy_net": "pi_small64_e10.json",
                                       "policy_scope": "proxy",
                                       "opp_mix": 1.0},
                            "label": "旧champion(V_3)＋対抗の相手モデルを常に等重みに"
                                     "（比較の基準・便 A・−0.092 で不採用・SD001専用）",
                            "decks": ("SD001",)},
    "planner_vb3cp": {"factory": "planner_vb",
                      "kwargs": {"extra_turns": 1,
                                 "value_net": "drl_sd001_vb3.json",
                                 "opp_policy_net": "drl_sd001_s1.json",
                                 "opp_policy_root_only": True,
                                 "choice_phases": True,
                                 "solo_samples": 4,
                                 "policy_net": "drl_sd001_vb3.json",
                                 "policy_scope": "proxy"},
                      "label": "計画探索＋地平延長＋葉=V_3＋選択フェイズも探索＋代打ちπ(大)"
                               "（旧champion・Elo 1474 [1452,1499]・5.6 倍遅い・SD001専用）",
                      "decks": ("SD001",)},
    "planner_vb3": {"factory": "planner_vb",
                    "kwargs": {"extra_turns": 1,
                               "value_net": "drl_sd001_vb3.json",
                               "opp_policy_net": "drl_sd001_s1.json",
                               "opp_policy_root_only": True},
                    "label": "計画探索＋地平延長＋葉=学習した価値V_3（旧champion・Elo 1409 [1385,1433]・SD001専用）",
                    "decks": ("SD001",)},
    "planner_pi": {"factory": "planner_pi",
                   "kwargs": {"opp_policy_net": "drl_sd001_s1.json",
                              "opp_policy_root_only": True},
                   "label": "計画探索＋相手モデルπ（旧champion・Elo 1340 [1318,1364]・SD001専用）",
                   "decks": ("SD001",)},
    "planner_lh": {"factory": "planner",  "kwargs": {"extra_turns": 1},
                   "label": "計画探索＋地平延長のみ（Elo 1335 [1314,1357]）"},
    "planner":   {"factory": "planner",   "kwargs": {},
                  "label": "計画探索（Elo 1318 [1296,1343]）"},
    "mcts160":   {"factory": "mcts",      "kwargs": {"iterations": 160},
                  "label": "IS-MCTS(160)（Elo 1210 [1180,1241]）"},
    "greedy":    {"factory": "greedy",    "kwargs": {},
                  "label": "貪欲（Elo 1109 [1088,1132]）"},
    "heuristic": {"factory": "heuristic", "kwargs": {},
                  "label": "H_default（基準・Elo 1000）"},
    "random":    {"factory": "random",    "kwargs": {},
                  "label": "ランダム（Elo 363 [295,421]）"},
}
# APP_DESIGN §8.2。便 A 後半で champion 交代（2026-09-13・D-082 追記 2）。
# **歴代の champion は一覧から消さない**——一つ前の `planner_vc4cps_kheb`（便 C）も
# 二つ前の `planner_vc4cps`（便 E-0）も残してあるので、版をそろえて比べ直せる。
DEFAULT_OPPONENT = "planner_vc4cps_kheb_b75"


def available(deck_name: str = "SD001") -> dict:
    """そのデッキで選べる相手。`decks` を持つものはそのプール専用（D-058）。

    学習した方策 π はカードの枠ごとに意味を持つので、別プールに持ち込むと
    相手モデルとして悪化する。プール外では選ばせない。

    配布モード（D-074）では、さらに `dist.json` の `opponents`（allowlist）で絞り、
    `labels` で表示名を言い換える。マーカーが無ければどちらも効かず、従来どおり全部出る。
    """
    from webapp import distribution
    allow = distribution.opponent_allowlist()
    labels = distribution.opponent_labels()
    out = {}
    for k, v in OPPONENTS.items():
        if "decks" in v and deck_name not in v["decks"]:
            continue
        if allow is not None and k not in allow:
            continue
        # 表示名の差し替えは配布モードだけ（labels が空なら従来の辞書をそのまま返す）
        out[k] = dict(v, label=labels[k]) if k in labels else v
    return out


def default_for(deck_name: str = "SD001") -> str:
    """そのデッキの既定の相手（＝champion）。

    配布モードで champion が allowlist に無いときは、allowlist の中で
    「素の計画探索 → 先頭」の順に落とす（既定の相手が一覧に無い状態を作らない）。
    """
    ok = available(deck_name)
    if DEFAULT_OPPONENT in ok:
        return DEFAULT_OPPONENT
    if "planner" in ok:
        return "planner"
    return next(iter(ok)) if ok else "planner"


def build(name: str, pool: list, seed: int, deck_name: str = "SD001"):
    """相手エージェントを1体作る。"""
    if name not in OPPONENTS:
        raise KeyError(f"未登録の相手: {name!r}（登録済: {sorted(OPPONENTS)}）")
    if name not in available(deck_name):
        raise KeyError(f"{name!r} は {deck_name} では使えない"
                       f"（対応プール: {OPPONENTS[name]['decks']}）")
    spec = OPPONENTS[name]
    return make(spec["factory"], dict(spec["kwargs"]), pool)(seed)
