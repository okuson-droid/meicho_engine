"""V の反復ブートストラップ（D-064）の 1 反復ぶんの検証。`VALUE_BOOTSTRAP_DESIGN.md` §4.6・§7。

## この道具が出す数字（4 種類）と、その読み方

1 反復は「記録 → 学習 → 新しい価値ネット V_k → それを葉に差した AI を測る」である。
ここは最後の「測る」を担う。`eval_drl_stage2.py` を型にしているが、**採否の条件が違う**
（門番だけでは決めない・§7.1）ので、出す数字も読み方も別に書く。

1. **門番** — 新しい版（葉 = V_k）と前の版（葉 = V_{k-1}）を直接対決させた勝率。
   うしろの ± は 95% 信頼区間、つまり「同じ条件で測り直したらだいたいこの幅に収まる」幅。
   **下端が 0.5 を超えたときだけ**「強くなった」と言ってよい。
   下端が 0.5 を ±0.01 でまたぐ「境界」なら、別帯で 2,400 局の追試をすること（D-059 の型）。
2. **錨 3 種** — 素の計画探索・H（規則ベース）・貪欲に対する勝率を、新旧で**同じシード**で取り、
   差を**局ごとに対にして**測る（`measurement_discipline`。別々に測って引き算すると区間が広すぎる）。
   D-059 で「前の版専用に尖って、他の相手には弱くなる」が起きたので、その再発を見張る。
   **どれかで明確に負ける（差の区間が 0 をまたがず悪化）なら、門番を通っても採用しない。**
3. **カナリア** — 漂泊者（女）Lv2 への到達率（`measure_horizon.py` の測り方・n=200）。
   これは強さではなく**癖**の指標であり、**目標ではない**（§7.4・D-043）。
   「反復 2〜4 で上がり始め、門番も通る」が設計どおりの姿。
   「カナリアだけ上がって門番を通らない」は過剰レベルアップへの逸脱を疑う。
4. **対照（空回し）** — `--null` を付けると前の版どうしを当てる。0.5 付近に出るのが正しい。
   ここがずれていたら測り方が壊れているので、1 の数字も信用しない（配管の検査）。

## 版の数え方（間違えやすい）

`--iter k` は「**反復 k を回し終えた**ので、その成果 V_k を測る」という意味である。
- 新しい版 = `vb.kwargs_for(deck, k+1)`（葉 = V_k）
- 前の版　 = `vb.kwargs_for(deck, k)`  （葉 = V_{k-1}。k=1 なら葉は手作り評価）

使い方:
    python3 experiments/eval_vb.py --deck SD001 --iter 1 --workers 2
    python3 experiments/eval_vb.py --deck SD001 --iter 1 --null      # 配管の空回し

## 中断と再開（2026-09-07）

作業環境は約 10 分の無操作で回収され、裏に回した長い測定は**消える**。輪 2 の探索器は
1 局あたり数秒かかるので、全部で 3,600 局のこの検証は 1 回では終わらない。そこで
**塊に割って前面で回し、途中経過をファイルに残す**。

    python3 experiments/eval_vb.py --deck SD001 --iter 4 --loop 2 --seed0 530000 \
        --out results/vb/loop2_iter4.json --budget-sec 400        # 何度でも打ち直す

- `--budget-sec` を越えると**その塊の切れ目で止まり、終了コード 2 で返る**。
  同じコマンドをもう一度打てば続きから回る。
- 途中経過は `--out` に `.resume.json` を付けた名前に貯まる。**測る条件（版・帯・局数）が
  1 つでも違えば拒否する**——別の測定の途中経過に足し込むと、混ざった数が出てしまうから。
- 塊に割っても結果は 1 回で回したときと**同じ**である。1 局はシードだけで決まるので、
  1,200 局を 100 局 × 12 に割っても各局は変わらない（`test_eval_vb_resume_matches_one_shot`）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import numpy as np                                                       # noqa: E402

import meicho_rs as rs                                                    # noqa: E402

import vb as vbmod                                                       # noqa: E402
from arena import load_deck, mirror_config                               # noqa: E402
from arena_rs import (GREEDY, HEURISTIC, PLANNER, ensure_cards,        # noqa: E402
                      series_rs, series_rs_detail)

# §7.6 の帯。反復ごとに 4,000 幅（390000..409999 に反復 1〜5）。
EVAL_BAND0 = 390000
EVAL_BAND_WIDTH = 4000
# 帯の中の割り当て（内訳。重ならないこと・`test_seed_bands_registered` が固定する）。
OFFSETS = {"gate": 0, "anchor_planner": 1300, "anchor_h": 2000,
           "anchor_greedy": 2700, "canary": 3400}
SPARE = 3600          # 3600..3999 は検算・予備（`measure_rush_lv2` の強いる版など）


def eval_band(k: int) -> int:
    """反復 k の評価に使う帯の先頭。**記録の帯（34〜38万台）とは重ならない。**"""
    assert k >= 1, f"反復は 1 から数える（k={k}）"
    if k > 5:
        raise SystemExit(f"反復 {k} の評価帯は未登録。seed_bands.json に "
                         f"next_free（410000）から新規に登録してから回すこと（§7.6）")
    return EVAL_BAND0 + (k - 1) * EVAL_BAND_WIDTH


def _resolve(kw: dict) -> dict:
    """Rust に渡す前にネットのパスを解決する（Rust 側は配置を知らない）。"""
    from meicho.drlnet import resolve_model
    out = dict(kw)
    # **`policy_net`（代打ちの π）を落とさないこと。**輪 2 の探索器はこれを積む。
    # 落とすと Rust 側が生のファイル名を開こうとして「No such file」で落ちる（2026-09-07）。
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in out:
            out[key] = resolve_model(out[key])
            rs.net_forget(out[key])       # 同じパスを上書きした場合に備える（規約）
    return out


def specs_for(deck: str, pool: list, k: int, null: bool = False,
              new_net: str = None, loop: int = 1, old_net: str = None) -> tuple:
    """(新しい版, 前の版) の spec。`null=True` なら両方とも前の版（配管の空回し）。

    `new_net` / `old_net` を渡すと、その席の葉に積む価値ネットを**差し替える**。
    同じ反復の記録から別の条件で学習した 2 つの版を、**まったく同じ探索器の上で**
    突き合わせるための口である（変えた部品だけが違う対照・D-067 の案 B の判定に使った）。
    """
    # **同じ輪の同じ探索器どうしで比べる**（計画書 §5.1）。輪が違うと探索器の差を
    # V の差と取り違える。`loop` を両方に同じだけ渡すことがその保証である。
    new_kw = _resolve(vbmod.kwargs_for(deck, k + 1, loop))
    old_kw = _resolve(vbmod.kwargs_for(deck, k, loop))
    if new_net:
        new_kw = dict(new_kw)
        new_kw["value_net"] = os.path.abspath(new_net)
        rs.net_forget(new_kw["value_net"])
    if old_net:
        old_kw = dict(old_kw)
        old_kw["value_net"] = os.path.abspath(old_net)
        rs.net_forget(old_kw["value_net"])
    if null:
        new_kw = dict(old_kw)
    return PLANNER(pool, **new_kw), PLANNER(pool, **old_kw)


def result_skeleton(deck: str, k: int, base: int, null: bool, label_new: str,
                    label_old: str, new_net, old_net, loop: int, n: int,
                    anchor_n: int, new_kw: dict, old_kw: dict,
                    workers: int = 1) -> dict:
    """結果 JSON の骨組み。**由来（provenance）は測定の開始時にここで作る**（D-2 / D-3）。

    終了時に作ると「門番の結果を見てから V を差し替える」抜け道が残るので、
    必ず開始時に作って書き出す（`REPORTING_RULES.md` §2.8 の V 凍結）。
    既存のキーは 1 つも変えていない——増やしただけである。
    """
    import provenance
    band = (base, base + EVAL_BAND_WIDTH - 1)
    return {"deck": deck, "iter": k, "seed0": base, "null": bool(null),
            "new": label_new, "new_net": new_net, "loop": loop,
            "old": label_old, "old_net": old_net,
            "n": n, "anchor_n": anchor_n, "runs": [],
            # D-072 判断 6: 機械と並列数（`COMPUTE_PLAN` §5-3）。既存の鍵は 1 つも変えない。
            "provenance_new": provenance.block(
                new_kw, "rust", band,
                extra={"role": "new", "host": provenance.host_name(),
                       "workers": int(workers)}),
            "provenance_old": provenance.block(
                old_kw, "rust", band,
                extra={"role": "old", "host": provenance.host_name(),
                       "workers": int(workers)})}


def paired_diff(config, new: dict, old: dict, opp: dict, seed0: int, n: int,
                workers: int) -> dict:
    """新旧を同じ相手・**同じシード**に当て、差を「局ごとに対にして」測る（`measurement_discipline`）。

    2 本の勝率を別々に測って引き算すると、区間が実際より広くなる。同じシードなら
    「配られた札」が共通なので、**同じ局で新は勝てたか／前は勝てたか**を並べて差を取れる。
    差の平均の 95% 区間は `1.96 · 標準偏差 / √(対にした局数)`。

    返り値の `new_only` / `old_only` は「新だけ勝った局」「前だけ勝った局」の数で、
    差はこの 2 つの数の開きから来る（両方勝った局・両方負けた局は差に効かない）。
    """
    rn = series_rs_detail(new, opp, n, config, workers=workers, seed0=seed0)
    ro = series_rs_detail(old, opp, n, config, workers=workers, seed0=seed0)
    d, new_only, old_only, nw, ow = [], 0, 0, 0, 0
    for x, y in zip(rn, ro):
        if x[0] is None or y[0] is None:      # 引き分け・打ち切りは分母から除く（arena の約束）
            continue
        a, b = float(bool(x[0])), float(bool(y[0]))
        d.append(a - b)
        nw += a
        ow += b
        if a > b:
            new_only += 1
        elif b > a:
            old_only += 1
    m = len(d)
    if m == 0:
        return {"pairs": 0, "new_p": None, "old_p": None, "diff": None, "ci": None,
                "new_only": 0, "old_only": 0, "clearly_worse": False}
    arr = np.asarray(d, float)
    diff = float(arr.mean())
    ci = float(1.96 * arr.std(ddof=1) / (m ** 0.5)) if m > 1 else float("inf")
    return {"pairs": m, "new_p": nw / m, "old_p": ow / m, "diff": diff, "ci": ci,
            "new_only": new_only, "old_only": old_only,
            "clearly_worse": bool(diff + ci < 0)}


# --- 中断と再開 -------------------------------------------------------------
class OutOfBudget(Exception):
    """持ち時間を使い切った。塊の切れ目で投げる（途中経過は保存済み）。"""


class Budget:
    """持ち時間を数え、塊の切れ目でだけ止める係。

    塊の**途中**では止めない。止めると「回したのに数えていない局」が出て、
    再開したときに同じ局をもう一度回すか、取りこぼすかのどちらかになる。
    """

    def __init__(self, sec: float | None):
        self.sec, self.t0 = sec, time.time()

    def check(self) -> None:
        if self.sec is not None and time.time() - self.t0 >= self.sec:
            raise OutOfBudget


def paired_counts(config, new: dict, old: dict, opp: dict, seed0: int, n: int,
                  workers: int) -> dict:
    """`paired_diff` の**数え上げだけ**を返す（足し算できる形）。

    差 d は局ごとに −1 / 0 / +1 のどれかしか取らない。だから 4 つの数
    （両方勝ち・新だけ勝ち・前だけ勝ち・両方負け）さえ持っていれば、
    平均も標準偏差も後から厳密に出せる。**塊に割って足せる**のはそのためである。
    """
    rn = series_rs_detail(new, opp, n, config, workers=workers, seed0=seed0)
    ro = series_rs_detail(old, opp, n, config, workers=workers, seed0=seed0)
    c = {"both_win": 0, "new_only": 0, "old_only": 0, "both_lose": 0}
    for x, y in zip(rn, ro):
        if x[0] is None or y[0] is None:      # 引き分け・打ち切りは分母から除く
            continue
        a, b = bool(x[0]), bool(y[0])
        c["both_win" if (a and b) else "new_only" if a else "old_only" if b else "both_lose"] += 1
    return c


def paired_from_counts(c: dict) -> dict:
    """数え上げから `paired_diff` と**同じ形**の結果を組み立てる。"""
    m = c["both_win"] + c["new_only"] + c["old_only"] + c["both_lose"]
    if m == 0:
        return {"pairs": 0, "new_p": None, "old_p": None, "diff": None, "ci": None,
                "new_only": 0, "old_only": 0, "clearly_worse": False}
    diff = (c["new_only"] - c["old_only"]) / m
    # d は ±1 か 0 なので E[d²] = (新だけ勝ち + 前だけ勝ち)/m。標本分散は ddof=1 で揃える。
    var = (c["new_only"] + c["old_only"]) / m - diff * diff
    ci = float(1.96 * ((max(var, 0.0) * m / (m - 1)) ** 0.5) / (m ** 0.5)) if m > 1 else float("inf")
    return {"pairs": m, "new_p": (c["both_win"] + c["new_only"]) / m,
            "old_p": (c["both_win"] + c["old_only"]) / m, "diff": diff, "ci": ci,
            "new_only": c["new_only"], "old_only": c["old_only"],
            "clearly_worse": bool(diff + ci < 0)}


def merge_canary(acc: dict, t: dict) -> dict:
    """カナリアの結果を足し合わせる（平均は合計と件数から出し直す）。"""
    a = dict(acc)
    a["games"] = a.get("games", 0) + t["games"]
    a["reached"] = a.get("reached", 0) + t["reached"]
    a["never"] = a.get("never", 0) + t["never"]
    a["_sum_turn"] = a.get("_sum_turn", 0.0) + (t["mean_turn"] or 0.0) * t["reached"]
    a["_sum_extra"] = a.get("_sum_extra", 0.0) + t["total_extra_draws_per_game"] * t["games"]
    a["mean_turn"] = (a["_sum_turn"] / a["reached"]) if a["reached"] else None
    a["mean_extra_draws"] = (a["_sum_extra"] / a["reached"]) if a["reached"] else 0.0
    a["total_extra_draws_per_game"] = a["_sum_extra"] / max(1, a["games"])
    return a


def canary(deck: str, pool: list, k: int, seeds, loop: int = 1) -> dict:
    """漂泊者 Lv2 の到達率（Python 版・`measure_rush_lv2._trace`）。"""
    from measure_rush_lv2 import _trace
    from meicho.heuristic import HeuristicAgent
    return _trace(lambda s: vbmod.make(deck, pool, k, s, loop),
                  lambda s: HeuristicAgent(s), seeds)


def main(argv=None) -> int:
    # D-082 追記 1: 報告の文には `π₀` が入っていて、`₀`（U+2080）は cp932 で書けない。
    # 出力をパイプやファイルに向けると日本語 Windows ではロケールの符号化が使われ、
    # **報告の途中で落ちる**（`experiments/console.py` に経緯）。表示だけ UTF-8 に寄せる——
    # **記録する文字列（ラベル・`--resume` の鍵・結果 JSON）は 1 文字も変えない。**
    from console import use_utf8_console
    use_utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--iter", type=int, required=True, help="回し終えた反復の番号 k")
    ap.add_argument("--n", type=int, default=1200, help="門番の局数（§7.1）")
    ap.add_argument("--anchor-n", type=int, default=600, help="錨 1 種あたりの局数")
    ap.add_argument("--canary-n", type=int, default=200, help="カナリアの局数（§7.4）")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=None, help="既定は §7.6 の帯（反復から決まる）")
    ap.add_argument("--null", action="store_true", help="配管の空回し（同じ版どうし）")
    ap.add_argument("--skip-canary", action="store_true")
    ap.add_argument("--skip-anchors", action="store_true",
                    help="門番だけ回す（§7.1 の**境界の追試**用。追試は必ず別の帯で取ること）")
    ap.add_argument("--new-net", default=None,
                    help="新しい版の葉に積む価値ネットを差し替える（既定は vb.py の drl_<deck>_vb<k>.json）。"
                         "同じ記録から別条件で学習した版を同じ土俵で比べるときに使う")
    ap.add_argument("--loop", type=int, default=1,
                    help="輪の番号（既定 1 = D-064 の輪。2 = D-065 便 4 の輪）")
    ap.add_argument("--out", default=None, help="既定 results/vb/iter<k>.json")
    ap.add_argument("--chunk", type=int, default=100,
                    help="1 塊の局数（この単位で途中経過を残す）")
    ap.add_argument("--budget-sec", type=float, default=None,
                    help="この秒数を越えたら塊の切れ目で止まる（終了コード 2）。同じコマンドで再開")
    ap.add_argument("--old-net", default=None,
                    help="**前の版**の葉に積む価値ネットを差し替える。--new-net と合わせて使うと、"
                         "同じ探索器の上で 2 つの V を直接突き合わせられる")
    ap.add_argument("--resume", default=None,
                    help="途中経過の置き場（既定は --out に .resume.json を付けた名前）")
    args = ap.parse_args(argv)

    k = args.iter
    base = args.seed0 if args.seed0 is not None else eval_band(k)
    ensure_cards()
    deck = load_deck(args.deck)
    config = mirror_config(deck)
    pool = deck["action_deck"]
    if not args.null:
        # 反復 k の成果 V_k が無ければ何も測れない。先に分かるように落とす。
        from meicho.drlnet import resolve_model
        want = args.new_net or resolve_model(vbmod.model_name(args.deck, k, args.loop))
        if not os.path.exists(want):
            raise SystemExit(f"反復 {k} の価値ネットが無い: {want}\n"
                             f"先に drl_record.py --vb {k} と drl_train.py で作ること"
                             f"（配管だけ試すなら --null）")
    new, old = specs_for(args.deck, pool, k, args.null, args.new_net, args.loop, args.old_net)

    print(f"■ 反復 {k} の検証（{args.deck}・シード帯 {base}..{base + EVAL_BAND_WIDTH - 1}）")
    label_new = vbmod.describe(args.deck, k + 1, args.loop)
    if args.new_net:
        label_new += f"　※葉を {os.path.basename(args.new_net)} に差し替え"
    label_old = vbmod.describe(args.deck, k, args.loop)
    if args.old_net:
        label_old += f"　※葉を {os.path.basename(args.old_net)} に差し替え"
    print(f"  新しい版: {label_new}")
    print(f"  前の版　: {label_old}")
    if args.null:
        print("  ※ --null: 両席とも前の版（配管の空回し。0.5 付近に出るのが正しい）")
    print()

    out = result_skeleton(
        deck=args.deck, k=k, base=base, null=bool(args.null),
        label_new=label_new, label_old=label_old, new_net=args.new_net,
        old_net=args.old_net, loop=args.loop, n=args.n, anchor_n=args.anchor_n,
        new_kw={x: y for x, y in new.items() if x != "opp_decklist"},
        old_kw={x: y for x, y in old.items() if x != "opp_decklist"},
        workers=args.workers)

    # --- 途中経過の読み書き。**条件が違う途中経過には足し込まない。** ---------
    path = args.out or os.path.join(_HERE, "..", "results", "vb", f"iter{k}.json")
    rpath = args.resume or (os.path.splitext(path)[0] + ".resume.json")
    key = {"deck": args.deck, "iter": k, "loop": args.loop, "seed0": base,
           "null": bool(args.null), "new_net": args.new_net, "old_net": args.old_net,
           "new": label_new, "old": out["old"], "n": args.n, "anchor_n": args.anchor_n,
           "canary_n": args.canary_n}
    st = {"key": key, "gate": {"n_done": 0, "wins": 0, "decided": 0},
          "anchors": {}, "canary": {}}
    if os.path.exists(rpath):
        old_st = json.load(open(rpath, encoding="utf-8"))
        if old_st.get("key") != key:
            raise SystemExit(
                f"途中経過 {rpath} は**別の条件**のものである（版・帯・局数のどれかが違う）。\n"
                f"  貯まっている: {json.dumps(old_st.get('key'), ensure_ascii=False)}\n"
                f"  いま回そうとしている: {json.dumps(key, ensure_ascii=False)}\n"
                f"足し込むと混ざった数が出る。別の --resume を指すか、要らなければ消すこと。")
        st = old_st
        print(f"  ※ 途中から再開する（{os.path.basename(rpath)}）\n")

    def save_state():
        os.makedirs(os.path.dirname(os.path.abspath(rpath)), exist_ok=True)
        tmp = rpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, rpath)                 # 書きかけを残さない

    budget = Budget(args.budget_sec)

    def run(name, a, b, seed, n):
        """門番。`--chunk` 局ずつ回し、切れ目ごとに途中経過を残す。"""
        g = st["gate"]
        t0, done0 = time.time(), g["n_done"]
        g.setdefault("sec", 0.0)               # 何回に分けても、速さは通算で出す
        while g["n_done"] < n:
            budget.check()
            c = min(args.chunk, n - g["n_done"])
            tc = time.time()
            r = series_rs(a, b, c, config, workers=args.workers, seed0=seed + g["n_done"])
            g["sec"] += time.time() - tc      # 塊の実時間だけを足す（待ち時間は入れない）
            g["wins"] += r.wins
            g["decided"] += r.decided
            g["n_done"] += c
            save_state()
            el = time.time() - t0
            rate = (g["n_done"] - done0) / el if el else 0
            p = g["wins"] / g["decided"] if g["decided"] else float("nan")
            left = (n - g["n_done"]) / rate if rate else float("nan")
            print(f"  … {g['n_done']:>5}/{n} 局  途中の勝率 {p:.3f}"
                  f"  （{rate * 60:.1f} 局/分・残り約 {left / 60:.0f} 分）", flush=True)
        from arena import Result
        r = Result(g["wins"], g["decided"], n)
        lo, hi = r.p - r.ci, r.p + r.ci
        row = {"name": name, "seed0": seed, "wins": r.wins, "decided": r.decided,
               "games": r.games, "p": r.p, "ci": r.ci, "lo": lo, "hi": hi,
               "sec": round(g["sec"], 1),
               "rate": (n / g["sec"]) if g["sec"] else None}
        out["runs"].append(row)
        return row, r

    # 1. 門番（§7.1）
    row, r = run("1. 門番: 新 vs 前の版", new, old, base + OFFSETS["gate"], args.n)
    lo = row["lo"]
    border = abs(lo - 0.5) <= 0.01
    row["passes_gate"] = bool(lo > 0.5)
    row["border"] = bool(border)
    verdict = "**門番を越えた**" if lo > 0.5 else "越えない"
    if border:
        verdict += "（境界。別帯で 2,400 局の追試が要る・D-059 の型）"
    print(f"{row['name']:26s} {r}  下端 {lo:.3f} / 上端 {row['hi']:.3f}  → {verdict}")

    # 2. 錨 3 種（§7.1）。**新旧を同じシードで対にする**（D-039 の対照実験の約束）。
    print()
    if not args.skip_anchors:
        print("■ 錨（前の版と同じシードで対にした差。どれかで明確に悪化したら採用しない）")
    anchors = [("素planner", PLANNER(pool), "anchor_planner"),
               ("H", HEURISTIC(), "anchor_h"),
               ("貪欲", GREEDY(pool), "anchor_greedy")]
    if args.skip_anchors:
        anchors = []
    out["anchors"] = []
    for label, opp, akey in anchors:
        seed = base + OFFSETS[akey]
        acc = st["anchors"].setdefault(
            label, {"n_done": 0, "both_win": 0, "new_only": 0, "old_only": 0, "both_lose": 0})
        while acc["n_done"] < args.anchor_n:
            budget.check()
            c = min(args.chunk, args.anchor_n - acc["n_done"])
            got = paired_counts(config, new, old, opp, seed + acc["n_done"], c, args.workers)
            for kk, vv in got.items():
                acc[kk] += vv
            acc["n_done"] += c
            save_state()
            print(f"  … 錨 vs {label}: {acc['n_done']:>4}/{args.anchor_n} 局", flush=True)
        a = paired_from_counts(acc)
        a.update({"opponent": label, "seed0": seed})
        out["anchors"].append(a)
        out["runs"].append({"name": f"2. 錨: vs {label}", "seed0": seed,
                            "new_p": a["new_p"], "old_p": a["old_p"], "paired": True})
        mark = "  ← **明確に悪化。門番を通っても採用しない**" if a["clearly_worse"] else ""
        print(f"  vs {label:10s} 新 {a['new_p']:.3f} / 前 {a['old_p']:.3f}"
              f"  差 {a['diff']:+.3f} ±{a['ci']:.3f}（対にした {a['pairs']} 局"
              f"／新だけ勝ち {a['new_only']}・前だけ勝ち {a['old_only']}）{mark}", flush=True)

    # 3. カナリア（§7.4）。**目標ではない。予言の検証である。**
    if not args.skip_canary:
        print()
        cs0 = base + OFFSETS["canary"]
        print(f"■ カナリア: 漂泊者(女)Lv2 到達（対 H・{args.canary_n} 局・"
              f"シード {cs0}..{cs0 + args.canary_n - 1}）")
        out["canary"] = {}
        pairs = (("前の版", k), ("前の版（対照）", k)) if args.null \
            else (("前の版", k), ("新しい版", k + 1))
        for label, kk in pairs:
            acc = st["canary"].setdefault(label, {"n_done": 0})
            while acc["n_done"] < args.canary_n:
                budget.check()
                c = min(args.chunk, args.canary_n - acc["n_done"])
                cs = list(range(cs0 + acc["n_done"], cs0 + acc["n_done"] + c))
                acc = merge_canary(acc, canary(args.deck, pool, kk, cs, args.loop))
                acc["n_done"] += c
                st["canary"][label] = acc
                save_state()
                print(f"  … カナリア {label}: {acc['n_done']:>4}/{args.canary_n} 局", flush=True)
            t = acc
            mt = "—" if t["mean_turn"] is None else f"{t['mean_turn']:.1f}"
            print(f"  {label:8s}: 到達 {t['reached']:3d}/{t['games']}／到達ターン 平均 {mt:>5s}"
                  f"／Lv2 が引かせた枚数 平均 {t['total_extra_draws_per_game']:.2f}")
            out["canary"][label] = t
        print("  （比較: 素の計画探索 5/40・貪欲 28/40・H 28/40 — D-046。"
              "カナリアを最大化する調整をしてはならない・D-043）")

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {path}")
    if os.path.exists(rpath):
        os.remove(rpath)                       # 全部終わったので途中経過は要らない
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OutOfBudget:
        print("\n■ 持ち時間を使い切った。**途中経過は残してある**ので、"
              "同じコマンドをもう一度打てば続きから回る。")
        sys.exit(2)
