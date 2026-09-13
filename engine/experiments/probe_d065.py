"""D-065 便 2 の測定: 候補を**別々に**現 champion に当てる（門番＋錨）。**中断・再開できる。**

## 何をする道具か

`D065_IMPLEMENTATION_PLAN.md` §3.1 の表そのものである。現 champion（`experiments/champion.py`
の定義＝ `planner_vb3`）の設定に、便 1 で作ったつまみの差分を 1 つずつ重ねた版を作り、

1. **門番**: 現 champion との直接対決 n=1,200。**勝率の下端が 0.5 を超える**ことを見る
   （「下端」とは、測り直したときに収まる範囲の下側の端。これが 0.5 を超えて初めて
   「たまたま勝ったのではない」と言える）
2. **錨**: 同じシードで、新旧の両方を第三者（H・貪欲・素の計画探索）と戦わせ、
   **どの相手にも悪化していない**ことを見る。
   門番だけで採否を決めない——champion だけに強い版は、他の相手に弱くなっていることがある
   （測定の作法・`measurement_discipline`）

**一度に 2 つ変えない。** だから候補は 1 つずつ測る。組み合わせ（`a12` / `all`）も
「単独の和より小さくないか」を見るために別に測る。

## 中断・再開できること（この道具の要）

作業環境（クラウドの計算機）は**手が止まると片付けられる**ため、10 時間走り続ける処理は
途中で消える。そこで本道具は測定を**小さな塊（既定 100 局）に割り**、1 局ごとの勝敗を
そのまま `results/vb/d065_<候補>.json` に書き足していく。同じコマンドをもう一度打てば
**終わった塊は飛ばして続きから**回る。`--budget-sec` の秒数を使い切ったらそこで正常終了する。

塊に割っても結果は変わらない。対局はシードだけで決まるからである（同じシードは何度回しても同じ 1 局）。

## 候補

| 名前 | 差分 | 何を試しているか |
|---|---|---|
| `a0` | `samples=12` | 対抗の決定化を倍に（レビューで 0.541 が出た零コード候補） |
| `a1` | `choice_phases=True, solo_samples=4` | 選択フェイズと手札上限の捨て札も探索の担当に |
| `a2` | `align_leaves=True` | 対抗・連撃・選択の葉を「次の自分のターン開始」に揃える |
| `a12` | a1 ＋ a2 | 上の 2 つは同じ場所（選択と葉）に触るので、干渉を見る |
| `a5` | `policy_net=drl_sd001_vb3.json, policy_scope="proxy"` | 探索の中の代打ちを π に（レビューで 0.614。**12 倍遅い**） |
| `all` | a0 ＋ a12 ＋ a5 | 全部入り |
| `a15` | a1 ＋ a5 | 門番を通った 2 つだけの組み合わせ（予備帯 457500..・§3.2） |
| `a12e` | a1 ＋ 葉の整列の別解（`align_stop="turn_end"`） | 有害だった本案の代わりに、道中の短い版（帯 452600..） |
| `a15lite` | a1 ＋ 代打ち π を絞った版（`policy_scope="proxy_lite"`） | 速度の手当て。強さを保てるか（帯 560000..） |
| `m25` / `m50` / `m100` | a15 ＋ `opp_mix` 0.25／0.5／1.0（A-8・計画書 §12） | 対抗の相手モデルを広げる。**基準は a15**（門番の相手も a15 にすること） |

## 使い方

    python3 experiments/probe_d065.py --cand a0                      # 続きから回す（既定 8 分で戻る）
    python3 experiments/probe_d065.py --cand a0 --budget-sec 500     # 塊を回す時間を指定
    python3 experiments/probe_d065.py --cand a0 --report             # 回さずに今の集計だけ出す

帯は `seed_bands.json` の 440100..459999（候補ごとに 2,500 幅）。**回す前に
`seed0 + n − 1 ≤ 帯の終わり` を確かめる**（D-065 案でここを 1 件はみ出した）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                             # noqa: E402
from arena_rs import (GREEDY, HEURISTIC, PLANNER, ensure_cards,        # noqa: E402
                      series_rs_detail)
from meicho.drlnet import resolve_model                                # noqa: E402
import champion as chmod                                               # noqa: E402

A0 = {"samples": 12}
A1 = {"choice_phases": True, "solo_samples": 4}
A2 = {"align_leaves": True}
A5 = {"policy_net": "drl_sd001_vb3.json", "policy_scope": "proxy"}

CANDIDATES = {
    "a0": dict(A0),
    "a1": dict(A1),
    "a2": dict(A2),
    "a12": {**A1, **A2},
    "a5": dict(A5),
    "all": {**A0, **A1, **A2, **A5},
    # a2（葉の整列）が明確に悪く、a0（対抗の決定化 12）が効かないと分かったので、
    # 「通った 2 つだけ」の組み合わせを予備の帯で測る（計画書 §3.2 の「1 つ抜いた版」）。
    "a15": {**A1, **A5},
    # 便 2 の追加（2026-09-03・マスター裁定）:
    # a12e = a1 ＋ 葉の整列の**別解**（いま進行中のターンの終わりで止める・§2.4）。
    #        本案（a2・次の自分のターンまで運ぶ）が有害だったので、道中の短い版を試す。
    # a15lite = a1 ＋ 代打ち π を**相手の ACTION と自分の対抗だけ**に絞った版（§9-4 (a) の速度の手当て）。
    #        a15（0.632）と同じ強さを保ったまま速くなるかを見る。
    "a12e": {**A1, "align_leaves": True, "align_stop": "turn_end"},
    "a15lite": {**A1, "policy_net": A5["policy_net"], "policy_scope": "proxy_lite"},
    # A-8（計画書 §12・対人 2 局の裏取り）: 対抗の相手モデルを広げる。**a15 を基準に測る。**
    "m25": {**A1, **A5, "opp_mix": 0.25},
    "m50": {**A1, **A5, "opp_mix": 0.5},
    "m100": {**A1, **A5, "opp_mix": 1.0},
    # A-9（`D065_NOTES.md` A-9）: 均衡を土台にした δ 制限つきの搾取。**a15 を基準に測る。**
    # δ=0.06 は回帰 2 局面が両方直る最小の値（閾値走査で決めた）。
    "n06": {**A1, **A5, "nash_delta": 0.06},
    # 便 4 の速度の手当て（計画書 §9-4 (b)・マスター裁定 2026-09-05）:
    # **代打ちの π を蒸留した小さい版に置き換える。** champion は既に a1+a5 なので、
    # 置き換えるのは `policy_net` だけ（範囲 `policy_scope="proxy"` はそのまま）。
    # 目的は速さであって強化ではないので、採用基準は「弱くなっていないこと」＝
    # **勝率の上端が 0.5 を下回らないこと**（マスター裁定）。
    "pi64": {"policy_net": "pi_small64_e10.json"},      # 幹 64・頭 32（先生と一致 88.1%・5.6 倍速い）
    "pi128": {"policy_net": "pi_small128_e8.json"},     # 幹 128・頭 64（一致 89.4%・2.5 倍速い）
    # 文献計画 便 A（前半・D-071）: 対抗の相手モデルの**評価規則**を変える。
    # 基準は現 champion（`--base` を渡さない）。帯は共通帯 652000..（`--seed0 652000` を明示する）。
    #   lu50 / lu30 … 詰みが見えるときだけ相手を等重みに見る（θ=0.5 / 0.3）
    #   m100        … 常に等重み（比較の基準。旧 m100 は a15 基準なので測り直す）
    "lu50": {"lethal_uniform": 0.5},
    "lu30": {"lethal_uniform": 0.3},
    "m100b": {"opp_mix": 1.0},
    # 文献計画 便 C 段 C-1（II-7 (a)・D-077）: スキャンで見た札を決定化に必ず入れる。
    # 基準は現 champion（`--base` を渡さない）。帯は 676000..（§5 の段 C-1 の帯）。
    "kh": {"known_hand": True},
    # 段 C-2（II-8・D-077 追記 2）: 段 C-1 のつまみに π₀ の到達確率の重みを**積む**（階段）。
    # T=2.0・ε=0.2・一様分 1/4 は引継ぎ書 §0.3 (v) の既定値。帯は 682000..（段 C-2 の帯）。
    "khw": {"known_hand": True, "world_weight": 0.75},
    # 段 C-3（II-9・D-077 追記 3）: 終盤（W ≤ 64）は決定化をやめて整合世界を全列挙し、
    # 本ごとの最良の 1 手目に重みを載せて投票する（信頼度 C < 0.6 なら加重平均に戻る）。
    # **段 C-2 の重みは積まない**——段 C-2 が門番に落ちたので、階段に残るのは
    # `known_hand` だけである（D-077 追記 2）。帯は 688000..（段 C-3 の帯）。
    "khe": {"known_hand": True, "endgame_enum": 64},
    # 段 C-4（ドローのバケット化・D-077 追記 4）: 段 C-1・C-3 で残った 2 つに
    # `draw_buckets` を積む（階段）。**段 C-2 の `world_weight` は積まない**ので、
    # 引継ぎ書 §3.4 の候補名 `khweb` ではなく `kheb` である（D-077 追記 2 の「次」）。
    # 帯は 694000..（段 C-4 の帯）。
    "kheb": {"known_hand": True, "endgame_enum": 64, "draw_buckets": 1},
    # 文献計画 便 A 後半（A-2・D-082）: 対抗の集約規則を変える。基準は現 champion。
    # AI の提出分布を決定化 K 本に**共通**に置いて束ねたゲームを解き、平均戦略から選ぶ。
    # `p` は「現行の評価（π₀ の最尤 1 手）」と「最悪想定」の混ぜ方で、
    # **p = 0（純粋な最悪想定）は候補にしない**（A-9 の δ=0 で「相手を強く見積もりすぎて
    # 詰みを逃す」が実測されている・計画書 §3.1 の転びやすいところ (1)）。
    # 帯は 710000..（§5 の錨の帯）。錨は `--anchor-offsets litc`。
    "b90": {"bundle_p": 0.9},
    "b75": {"bundle_p": 0.75},
    "b50": {"bundle_p": 0.5},
    # 対照（配管の検査・D-034 の第 2 項）: 現 champion どうし。**0.5 付近に出るのが正しい。**
    # ここが 0.5 を外したら測り方が壊れているので、他の数字を信用してはならない。
    "null": {},
}

# 候補ごとの帯の先頭（§7 の割り当て）。幅は 2,500。
BANDS = {"a0": 440100, "a1": 442600, "a2": 445100, "a12": 447600,
         "a5": 450100, "all": 452600, "a15": 457500,
         # `all` の帯は未使用のまま残ったので別解の測定に回した（台帳に追記済み）
         "a12e": 452600, "a15lite": 560000,
         # 交代の判定用の帯（550000..）の「対照」の区画。`champion_challenge_vb.py` の OFFSETS と同じ配置
         "null": 551300,
         # A-8 の測定（便 2'）。帯は next_free（610000）から候補ごとに 2,500 幅で登録した
         "m25": 610000, "m50": 612500, "m100": 615000,
         # A-9 の測定。next_free（617500）から 2,500 幅で登録した
         "n06": 617500,
         # 便 4 の速度の手当て。next_free（625000）から 2,500 幅で登録した
         "pi64": 625000, "pi128": 627500,
         # 便 A（前半）の**共通帯**。候補 3 つ＋null が同じシードを使うので、既定も同じ値にする
         # （`--seed0 652000` を明示するのが本筋だが、書き忘れても同じ帯に落ちるようにしておく）。
         "lu50": 652000, "lu30": 652000, "m100b": 652000,
         # 便 C 段 C-1。錨は `--anchor-offsets litc`（H +0／貪欲 +600／素 planner +1200）。
         # 門番は `gate_sprt.py`（GSPRT）が別に 678000.. を使うので、ここは錨の先頭を指す。
         "kh": 676000,
         # 段 C-2 の錨（`--anchor-offsets litc`）。門番は gate_sprt.py が 684000.. を使う。
         "khw": 682000,
         # 段 C-3 の錨（`--anchor-offsets litc`）。門番は gate_sprt.py が 690000.. を使う。
         "khe": 688000,
         # 段 C-4 の錨（`--anchor-offsets litc`）。門番は gate_sprt.py が 696000.. を使う。
         "kheb": 694000,
         # 便 A 後半（A-2）の錨（`--anchor-offsets litc`）。候補 3 つが**同じ帯・同じシード**を
         # 使う（引継ぎ書 §3.4「候補 3 つとも同じシード」）。門番は 1 つの候補だけを
         # `gate_sprt.py` が別帯 712000.. で回すので、ここは錨の先頭を指す。
         "b90": 710000, "b75": 710000, "b50": 710000}
# 帯の中の配置: 門番 +0（1,200）／錨 H +1300／貪欲 +1600／素 planner +1900（各 300）／予備 +2200
OFF_GATE, OFF_H, OFF_GREEDY, OFF_PLAIN = 0, 1300, 1600, 1900
ANCHORS = (("H", OFF_H), ("貪欲", OFF_GREEDY), ("素planner", OFF_PLAIN))
# 便 A（前半）は錨を 600 対ずつ取る（`HANDOFF_20260907_LIT_A.md` §6）。
# 300 対の配置のままでは H(+1300)+600 が貪欲(+1900)... ではなく貪欲(+1600) と重なるので、
# **錨の間隔を広げた配置**を用意する。`--anchor-offsets wide` で選ぶ。
ANCHORS_WIDE = (("H", 1300), ("貪欲", 1900), ("素planner", 2500))
# 便 C（段 C-1〜C-4）は錨 600 対を**帯の先頭から詰めて**置く
# （`HANDOFF_20260910_LIT_C.md` §5: H 676000..676599／貪欲 676600..677199／
# 素 planner 677200..677799）。門番は `gate_sprt.py` が別の帯（678000..）で回すので、
# 錨だけがこの帯を使う——つまり `--skip-gate` と組で使う配置である。
ANCHORS_LITC = (("H", 0), ("貪欲", 600), ("素planner", 1200))
ANCHOR_LAYOUTS = {"narrow": ANCHORS, "wide": ANCHORS_WIDE, "litc": ANCHORS_LITC}


def _resolve(kw: dict) -> dict:
    """モデルの名前を実ファイルのパスに直す（Rust 側はファイル配置を知らない）。"""
    out = dict(kw)
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in out:
            out[key] = resolve_model(out[key])
    return out


def provenance_for(base: str, champ_kw: dict, diff: dict, seed0: int,
                   n_gate: int, workers: int = 1) -> dict:
    """候補と基準の由来（D-2 / D-3）。**測定の開始時に作る**（`REPORTING_RULES.md` §2.8）。

    `cand` は「現 champion ＋ 差分」、`base` は門番の相手（既定は現 champion）。
    どちらもモデルの sha256 を持つので、後から「同じ名前で中身が違う」事故を見分けられる。
    """
    import provenance
    base_kw = {**champ_kw, **(CANDIDATES.get(base, {}) if base != "champion" else {})}
    band = provenance.band_of(seed0 + OFF_GATE, n_gate)
    # D-072 判断 6: 機械と並列数を由来に足す（`COMPUTE_PLAN` §5-3）。既存の鍵は変えない。
    where = {"host": provenance.host_name(), "workers": int(workers)}
    return {"cand": provenance.block({**champ_kw, **diff}, "rust", band,
                                     extra={"role": "candidate", **where}),
            "base": provenance.block(base_kw, "rust", band,
                                     extra={"role": "base", "name": base, **where})}


def _check_band(seed0: int, n: int) -> None:
    """`seed0 + n − 1` が登録済みの帯の中に収まっているか確かめる（§7・§9-10）。"""
    with open(os.path.join(_HERE, "seed_bands.json"), encoding="utf-8") as f:
        bands = json.load(f)["bands"]
    last = seed0 + n - 1
    for b in bands:
        if b["start"] <= seed0 and last <= b["end"]:
            return
    raise SystemExit(f"帯からはみ出している: {seed0}..{last} は登録済みの帯に収まらない")


def _load(path: str, cand: str, seed0: int, n_gate: int, n_anchor: int,
          diff: dict, base_kw: dict) -> dict:
    """途中経過を読む（無ければ作る）。設定が食い違うファイルは上書きせず止める。"""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
        # n_anchor は錨ごとに変えられる（`--anchor` ＋ `--n-anchor`）ので同一性の鍵に含めない
        if (st.get("cand"), st.get("seed0"), st.get("n_gate")) != (cand, seed0, n_gate):
            raise SystemExit(f"{path} は別の設定で書かれている（帯や n が違う）。"
                             f"消すか --out を変えること")
        return st
    return {"cand": cand, "diff": diff, "champion": base_kw, "seed0": seed0,
            "n_gate": n_gate, "n_anchor": n_anchor,
            "gate": [], "anchors": {name: {"new": [], "old": []} for name, _ in ANCHORS},
            "anchor_targets": {}, "sec": 0.0}


def _save(path: str, st: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, path)          # 途中で落ちても壊れた JSON を残さない


def _wilson(wins: float, n: int):
    """勝率と 95% 区間（作業規約 6 の ±1.96√(p(1-p)/n)）。"""
    if n == 0:
        return None, None
    p = wins / n
    return p, 1.96 * (p * (1 - p) / n) ** 0.5


def _gate_summary(st: dict) -> dict:
    res = [r for r in st["gate"] if r is not None]
    p, ci = _wilson(sum(res), len(res))
    return {"played": len(st["gate"]), "decided": len(res), "wins": int(sum(res)),
            "p": p, "ci": ci, "lo": (p - ci) if p is not None else None,
            "hi": (p + ci) if p is not None else None}


def _anchor_summary(a: dict) -> dict:
    """新旧を**同じ局で対にして**差を取る（`eval_vb.paired_diff` と同じ計算）。"""
    d, new_only, old_only, nw, ow = [], 0, 0, 0.0, 0.0
    for x, y in zip(a["new"], a["old"]):
        if x is None or y is None:
            continue
        x, y = float(x), float(y)
        d.append(x - y)
        nw += x
        ow += y
        if x > y:
            new_only += 1
        elif y > x:
            old_only += 1
    m = len(d)
    if m == 0:
        return {"pairs": 0, "played": len(a["new"])}
    arr = np.asarray(d, float)
    diff = float(arr.mean())
    ci = float(1.96 * arr.std(ddof=1) / (m ** 0.5)) if m > 1 else float("inf")
    return {"pairs": m, "played": len(a["new"]), "new_p": nw / m, "old_p": ow / m,
            "diff": diff, "ci": ci, "new_only": new_only, "old_only": old_only,
            "clearly_worse": bool(diff + ci < 0)}


def summarize(st: dict) -> dict:
    return {"cand": st["cand"], "diff": st["diff"], "seed0": st["seed0"],
            "n_gate": st["n_gate"], "n_anchor": st["n_anchor"],
            "anchor_targets": st.get("anchor_targets", {}), "sec": st.get("sec", 0.0),
            "gate": _gate_summary(st),
            "anchors": {k: _anchor_summary(v) for k, v in st["anchors"].items()}}


def _print(st: dict) -> None:
    s = summarize(st)
    g = s["gate"]
    if g["decided"]:
        print(f"  門番 {g['p']:.3f} ±{g['ci']:.3f} (n={g['decided']}/{s['n_gate']})"
              f"  下端 {g['lo']:.3f} / 上端 {g['hi']:.3f}", flush=True)
    for name, a in s["anchors"].items():
        if a["pairs"]:
            print(f"  錨 vs {name}: 新 {a['new_p']:.3f} / 前 {a['old_p']:.3f}"
                  f"  差 {a['diff']:+.3f} ±{a['ci']:.3f}"
                  f"  新だけ勝ち {a['new_only']} / 前だけ勝ち {a['old_only']}"
                  f"  （対にできた {a['pairs']} 局 / 予定 "
                  f"{s.get('anchor_targets', {}).get(name, s['n_anchor'])}）", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--cand", required=True, choices=sorted(CANDIDATES))
    ap.add_argument("--n-gate", type=int, default=1200)
    ap.add_argument("--n-anchor", type=int, default=300)
    ap.add_argument("--block", type=int, default=100, help="1 塊の局数（中断の粒度）")
    ap.add_argument("--budget-sec", type=float, default=480.0, help="この秒数を超えたら戻る")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=None)
    ap.add_argument("--base", default=None, choices=sorted(CANDIDATES),
                    help="門番と錨の**相手**（既定は現 champion）。A-8 は a15 を基準にする（§12.2）")
    ap.add_argument("--anchor", default=None, choices=[n for n, _ in ANCHORS],
                    help="この錨だけを回す（錨ごとに n を変えるときに使う）")
    ap.add_argument("--anchor-offsets", default="narrow", choices=sorted(ANCHOR_LAYOUTS),
                    help="錨の配置。narrow=+1300/+1600/+1900（各 300 対まで）／"
                         "wide=+1300/+1900/+2500（各 600 対まで・便 A）")
    ap.add_argument("--skip-gate", action="store_true",
                    help="門番が途中でも錨を先に回す（採否の主役が錨のときに使う）")
    ap.add_argument("--report", action="store_true", help="回さずに集計だけ出す")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    anchors = ANCHOR_LAYOUTS[args.anchor_offsets]
    span = min(b - a for (_, a), (_, b) in zip(anchors, anchors[1:]))
    if args.n_anchor > span:
        raise SystemExit(f"錨 {args.n_anchor} 対は配置 {args.anchor_offsets}（間隔 {span}）に"
                         f"収まらない。--anchor-offsets wide を使うこと")
    ensure_cards()
    deck = load_deck(args.deck)
    config = mirror_config(deck)
    pool = deck["action_deck"]
    diff = CANDIDATES[args.cand]
    champ_kw = chmod.kwargs_for(args.deck)
    # 門番の相手（基準）。既定は現 champion、`--base` を渡すとその候補が相手になる。
    base_kw = {**champ_kw, **(CANDIDATES[args.base] if args.base else {})}
    new = PLANNER(pool, **_resolve({**champ_kw, **diff}))
    old = PLANNER(pool, **_resolve(base_kw))
    seed0 = args.seed0 if args.seed0 is not None else BANDS[args.cand]
    path = args.out or os.path.join(_HERE, "..", "results", "vb", f"d065_{args.cand}.json")

    st = _load(path, args.cand, seed0, args.n_gate, args.n_anchor, diff, base_kw)
    st["base"] = args.base or "champion"
    # 由来は**測定の開始時**に作って残す（D-2 / D-3・`REPORTING_RULES.md` §2.8）
    st["provenance"] = provenance_for(st["base"], champ_kw, diff, seed0, args.n_gate,
                                     args.workers)
    _check_band(seed0 + OFF_GATE, args.n_gate)
    for _, off in anchors:
        _check_band(seed0 + off, args.n_anchor)

    print(f"候補 {args.cand}: {diff}", flush=True)
    if args.base:
        print(f"  基準（門番の相手）: {args.base} = {CANDIDATES[args.base]}", flush=True)
    if args.report:
        _print(st)
        print(f"  進み具合: 門番 {len(st['gate'])}/{args.n_gate}  "
              + "  ".join(f"{k} {len(v['new'])}+{len(v['old'])}/{2 * args.n_anchor}"
                          for k, v in st["anchors"].items()), flush=True)
        return 0

    start = last = time.time()      # start は予算の基準（塊ごとに戻さないこと）
    done_all = True
    # --- 門番（現 champion との直接対決） ---------------------------------
    while not args.skip_gate and len(st["gate"]) < args.n_gate:
        if time.time() - start > args.budget_sec:
            done_all = False
            break
        k = min(args.block, args.n_gate - len(st["gate"]))
        s0 = seed0 + OFF_GATE + len(st["gate"])
        r = series_rs_detail(new, old, k, config, workers=args.workers, seed0=s0)
        st["gate"] += [None if x[0] is None else bool(x[0]) for x in r]
        st["sec"] = st.get("sec", 0.0) + (time.time() - last)
        last = time.time()
        _save(path, st)
        g = _gate_summary(st)
        print(f"  門番 {len(st['gate'])}/{args.n_gate}  "
              f"いま {g['p']:.3f} ±{g['ci']:.3f}（下端 {g['lo']:.3f}）", flush=True)

    # --- 錨（第三者に対して悪化していないか） -----------------------------
    if args.skip_gate or len(st["gate"]) >= args.n_gate:
        for name, off in anchors:
            if args.anchor and name != args.anchor:
                continue
            opp = {"H": HEURISTIC(), "貪欲": GREEDY(pool), "素planner": PLANNER(pool)}[name]
            a = st["anchors"][name]
            st.setdefault("anchor_targets", {})[name] = args.n_anchor
            for side, spec in (("new", new), ("old", old)):
                while len(a[side]) < args.n_anchor:
                    if time.time() - start > args.budget_sec:
                        done_all = False
                        break
                    k = min(args.block, args.n_anchor - len(a[side]))
                    s0 = seed0 + off + len(a[side])
                    r = series_rs_detail(spec, opp, k, config, workers=args.workers, seed0=s0)
                    a[side] += [None if x[0] is None else bool(x[0]) for x in r]
                    st["sec"] = st.get("sec", 0.0) + (time.time() - last)
                    last = time.time()
                    _save(path, st)
                    print(f"  錨 vs {name} [{side}] {len(a[side])}/{args.n_anchor}", flush=True)
                if not done_all:
                    break
            if not done_all:
                break

    _save(path, st)
    _print(st)
    print(f"  → {path}  （{'完了' if done_all else '途中。同じコマンドで続きから'}）", flush=True)
    return 0 if done_all else 3


if __name__ == "__main__":
    sys.exit(main())
