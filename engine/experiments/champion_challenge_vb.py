"""champion 交代の判定（D-034 の条件を 1 コマンドで揃える）。D-064 の V 版を挑戦者にする。

## champion を替えるとは何を決めることか

champion は「そのカードプールでいちばん強い AI」の定義であり、**アプリでマスターの相手をする AI**
でもある（`webapp/agents.py` の既定）。だから替えるときの条件は重い。D-034 が定めた 5 つ:

1. **直接対決**で現 champion に勝ち越す（n ≥ 1,200・**別帯**・勝率の 95% 区間の**下端 > 0.5**）
2. **ラダー core5 で 1 位相当**（総当たりの Elo。この道具の対象外——`ladder.py` で別に回す）
3. **覗き見監査**を通る（隠蔽情報を見ていない）
4. **fingerprint を記録**する（あとから同じ AI を再現できるように）
5. **判断は人が行う**（この道具は候補を出すだけで、`champion.py` は書き換えない）

この道具は 1・3・4 と、配管の検査（現 champion どうしを当てて 0.5 付近に出るか）をまとめて回す。
**2 は `python3 experiments/ladder.py core5` を別に回すこと。**

## なぜ「別帯」でなければならないか

学習に使った局や、反復の途中で使った評価帯で測ると、**その帯に向けて調整された分だけ上振れる**。
D-058 の SD02 では実際にそれが起き、0.515 という数字が約 +0.02 汚染されていた。
`seed_bands.json` に「交代の判定用」として新しく登録した帯だけを使う。

使い方:
    python3 experiments/champion_challenge_vb.py --deck SD001 --vb 4 --n 1200 --workers 2
`--vb k` は挑戦者（葉に V_{k-1} を積んだ版）。反復 3 まで回したなら `--vb 4`。

D-065 便 2 で `--challenger-json` を足した（計画書 §3.4）。反復の輪から作れない挑戦者
（探索器のつまみを重ねた版）を、**現 champion の設定への差分**として JSON で渡す:

    python3 experiments/champion_challenge_vb.py --deck SD001 --seed0 550000 \
        --challenger-json '{"choice_phases": true, "solo_samples": 4,
                            "policy_net": "drl_sd001_vb3.json", "policy_scope": "proxy"}'

`--vb` と `--challenger-json` は排他である。`--budget-sec` を渡すと、その秒数を超えたところで
**途中経過を書いて終了コード 2 で戻る**（作業環境が長時間走れないため。同じコマンドで続きから回る）。

## 中断と再開（便 E-0 で実装。それまでは引数を受け取るだけだった）

型は `eval_vb.py`（D-068）と同じである。

- 直接対決と対照を `--chunk` 局ずつに割り、**塊の切れ目でだけ**止める。塊の途中で止めると
  「回したのに数えていない局」が出て、再開時に取りこぼすか二重に数えるかになる。
- 途中経過は `--out` に `.resume.json` を付けた名前（`--resume` で変えられる）。
  **測る条件（デッキ・挑戦者・帯・局数・追試か）が違う途中経過には足し込まない。**
- 塊に割っても一括と同じ勝ち数・決着数になる（各局はシードだけで決まる。T-C1 が固定）。
- **由来（provenance）は最初の塊の前に途中経過へ書き込む**（`REPORTING_RULES.md` §2.8 の
  V 凍結。開始時に凍結した証拠を、完走を待たずに残しておくため）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                                    # noqa: E402

import champion                                                          # noqa: E402
import vb as vbmod                                                       # noqa: E402
from arena import load_deck, mirror_config                               # noqa: E402
from arena_rs import PLANNER, ensure_cards, series_rs, series_rs_digest   # noqa: E402

JST = timezone(timedelta(hours=9))

# `seed_bands.json` に「D-064 の champion 交代の判定」として登録済みの帯（§D-034 の「別帯」）。
BAND = 420000
OFFSETS = {"challenge": 0, "control": 1300, "audit": 2600, "retest": 3000}


def challenger_spec_json(deck: str, pool: list, diff: dict) -> dict:
    """現 champion の設定に差分を重ねた挑戦者（D-065 便 2・計画書 §3.4）。

    反復の輪（`vb.py`）から作れない挑戦者——探索器のつまみを重ねただけの版——を
    測るための口である。差分は `PlannerAgent` の引数名で書く。
    """
    from meicho.drlnet import resolve_model
    kw = {**champion.kwargs_for(deck), **diff}
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in kw:
            kw[key] = resolve_model(kw[key])
            rs.net_forget(kw[key])
    return PLANNER(pool, **kw)


def audit_spec(pool: list, diff: dict, deck: str):
    """覗き見監査用の Python 版エージェント生成器（`--challenger-json` の挑戦者）。"""
    from meicho.planner import PlannerAgent
    kw = {**champion.kwargs_for(deck), **diff}
    return lambda sd: PlannerAgent(sd, opp_decklist=pool, **kw)


def challenger_spec(deck: str, pool: list, k: int) -> dict:
    from meicho.drlnet import resolve_model
    kw = vbmod.kwargs_for(deck, k)
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in kw:
            kw[key] = resolve_model(kw[key])
            rs.net_forget(kw[key])
    return PLANNER(pool, **kw)


def audit(deck: str, pool: list, k: int, config, n_games: int = 3) -> dict:
    """覗き見監査（`meicho/audit.py`）。実対局をリプレイし、**すべての実決定ノード**で
    隠蔽情報（相手の手札の中身・両者のデッキ順序）を差し替え、選択が変わらないことを見る。

    地平を延ばす AI は**相手のターンを想像で進める**ので、そこで本物の手札を覗けば
    強くなって当然であり、上の勝率はすべて無意味になる。**新しい AI は必ずここを通す。**
    """
    from meicho.audit import replay_audit
    from meicho.heuristic import HeuristicAgent
    return replay_audit(lambda sd: vbmod.make(deck, pool, k, sd),
                        lambda sd: HeuristicAgent(sd),
                        config, pool, n_games=n_games, variants=2, node_cap=120,
                        seed0=BAND + OFFSETS["audit"])


class OutOfBudget(Exception):
    """持ち時間を使い切った。塊の切れ目で投げる（途中経過は保存済み）。"""


class Budget:
    """持ち時間を数え、塊の切れ目でだけ止める係（`eval_vb.py` D-068 と同じ型）。"""

    def __init__(self, sec: float | None):
        self.sec, self.t0 = sec, time.time()

    def check(self) -> None:
        if self.sec is not None and time.time() - self.t0 >= self.sec:
            raise OutOfBudget


def provenance_for(champ_kw: dict, chal_kw: dict, seed0: int, n: int,
                   workers: int = 1) -> dict:
    """現 champion と挑戦者の由来（D-2 / D-3）。**測定の開始時に作る**（§2.8 の V 凍結）。

    交代の判定は「どの V を積んだ版が勝ったか」で champion を書き換える決定なので、
    ここで積んだネットの sha256 を残しておかないと、後から検証できない。
    """
    import provenance
    band = provenance.band_of(seed0 + OFFSETS["challenge"], n)
    # D-072 判断 6: どの機械で・何並列で回したか（`COMPUTE_PLAN` §5-3）。既存の鍵は変えない。
    where = {"host": provenance.host_name(), "workers": int(workers)}
    return {"champion": provenance.block(champ_kw, "rust", band,
                                         extra={"role": "champion", **where}),
            "challenger": provenance.block(chal_kw, "rust", band,
                                           extra={"role": "challenger", **where})}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--vb", type=int, default=None, help="挑戦者（葉に V_{k-1} を積んだ版）")
    ap.add_argument("--challenger-json", default=None,
                    help="現 champion への差分（JSON）。--vb と排他（D-065 §3.4）")
    ap.add_argument("--budget-sec", type=float, default=None,
                    help="この秒数を超えたら途中経過を書いて戻る（作業環境の都合）")
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=None, help="既定は交代の判定用の帯")
    ap.add_argument("--skip-audit", action="store_true")
    ap.add_argument("--retest", action="store_true",
                    help="境界だったときの追試（n=2,400・同じ帯の別の区画）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--chunk", type=int, default=100,
                    help="何局ずつ回して途中経過を残すか（塊の切れ目でだけ止まる）")
    ap.add_argument("--resume", default=None,
                    help="途中経過の置き場（既定は --out に .resume.json を付けた名前）")
    args = ap.parse_args(argv)

    if (args.vb is None) == (args.challenger_json is None):
        raise SystemExit("--vb か --challenger-json のどちらか一方を指定すること")
    ensure_cards()
    deck = load_deck(args.deck)
    pool = deck["action_deck"]
    config = mirror_config(deck)
    base = args.seed0 if args.seed0 is not None else BAND
    champ = champion.spec(args.deck, pool)
    diff = json.loads(args.challenger_json) if args.challenger_json else None
    if diff is None:
        chal = challenger_spec(args.deck, pool, args.vb)
        chal_desc = vbmod.describe(args.deck, args.vb)
    else:
        chal = challenger_spec_json(args.deck, pool, diff)
        chal_desc = f"現 champion ＋ {diff}"

    print("■ champion 交代の判定（D-034）")
    print(f"  現 champion: {champion.describe(args.deck)}")
    print(f"  挑戦者　　 : {chal_desc}")
    print()

    out = {"deck": args.deck, "vb": args.vb, "challenger_diff": diff,
           "n": args.n, "seed0": base, "workers": args.workers,
           # 由来は測定の**開始時**に作る（D-2 / D-3・REPORTING_RULES.md §2.8）
           "provenance": provenance_for(
               {k: v for k, v in champ.items() if k != "opp_decklist"},
               {k: v for k, v in chal.items() if k != "opp_decklist"},
               base, args.n, args.workers),
           "champion": champion.describe(args.deck),
           "challenger": chal_desc,
           "champion_spec": {k: (os.path.basename(v) if isinstance(v, str) else v)
                             for k, v in champ.items() if k != "opp_decklist"},
           "challenger_spec": {k: (os.path.basename(v) if isinstance(v, str) else v)
                               for k, v in chal.items() if k != "opp_decklist"},
           "when": datetime.now(JST).isoformat(timespec="seconds"),
           "platform": platform.platform(), "runs": []}

    # --- 中断と再開（D-068 の型）。**条件が違う途中経過には足し込まない。** ---------
    path = args.out or os.path.join(_HERE, "..", "results", "vb",
                                    f"champion_challenge_"
                                    f"{('vb' + str(args.vb)) if diff is None else 'd065'}"
                                    f"{'_retest' if args.retest else ''}.json")
    rpath = args.resume or (os.path.splitext(path)[0] + ".resume.json")
    key = {"deck": args.deck, "vb": args.vb, "challenger_diff": diff,
           "seed0": base, "n": args.n, "retest": bool(args.retest)}
    st = {"key": key, "provenance": out["provenance"], "slots": {}}
    if os.path.exists(rpath):
        old_st = json.load(open(rpath, encoding="utf-8"))
        if old_st.get("key") != key:
            raise SystemExit(
                f"途中経過 {rpath} は**別の条件**のものである（挑戦者・帯・局数のどれかが違う）。\n"
                f"  貯まっている: {json.dumps(old_st.get('key'), ensure_ascii=False)}\n"
                f"  いま回そうとしている: {json.dumps(key, ensure_ascii=False)}\n"
                f"足し込むと混ざった数が出る。別の --resume を指すか、要らなければ消すこと。")
        st = old_st
        # 由来は**最初の塊の前に凍結したもの**を正とする（§2.8。再開のたびに作り直さない）。
        out["provenance"] = st.get("provenance", out["provenance"])
        print(f"  ※ 途中から再開する（{os.path.basename(rpath)}）\n")

    def save_state():
        os.makedirs(os.path.dirname(os.path.abspath(rpath)), exist_ok=True)
        tmp = rpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, rpath)                 # 書きかけを残さない

    save_state()          # 由来を最初の塊の前に残す（V 凍結の証拠・§1）
    budget = Budget(args.budget_sec)

    def run(slot, name, a, b, seed, n):
        """`--chunk` 局ずつ回し、切れ目ごとに途中経過を残す。

        各局はシードだけで決まるので、塊に割っても一括と同じ勝ち数・決着数になる
        （`tests/test_champion_vc4.py::T-C1` が固定している）。
        """
        acc = st["slots"].setdefault(slot, {"n_done": 0, "wins": 0, "decided": 0, "sec": 0.0})
        while acc["n_done"] < n:
            budget.check()
            c = min(max(1, args.chunk), n - acc["n_done"])
            tc = time.time()
            r = series_rs(a, b, c, config, workers=args.workers, seed0=seed + acc["n_done"])
            acc["sec"] += time.time() - tc     # 塊の実時間だけを足す（待ち時間は入れない）
            acc["wins"] += r.wins
            acc["decided"] += r.decided
            acc["n_done"] += c
            save_state()
            if acc["n_done"] < n:
                print(f"  … {name}: {acc['n_done']:>5}/{n} 局"
                      f"（暫定 {acc['wins']}/{acc['decided']}）", flush=True)
        # 一括で回したときと**同じ形**にする（`arena.Result` を通すので p・区間の式も同じ）
        from arena import Result
        r = Result(acc["wins"], acc["decided"], n)
        lo, hi = r.p - r.ci, r.p + r.ci
        rate = n / acc["sec"] if acc["sec"] else None
        row = {"name": name, "seed0": seed, "n": n, "wins": r.wins, "decided": r.decided,
               "p": r.p, "ci": r.ci, "lo": lo, "hi": hi,
               "rate": rate, "sec": round(acc["sec"], 1)}
        out["runs"].append(row)
        rt = f"{rate:.1f} 局/秒" if rate else "—"
        print(f"  {name:34s} {r}  下端 {lo:.3f} / 上端 {hi:.3f}  [{seed}.., {rt}]", flush=True)
        return row

    print("■ 1. 直接対決（D-034 の第 1 条件）")
    key = "retest" if args.retest else "challenge"
    n = 2400 if args.retest else args.n
    a = run("challenge", "挑戦者 vs 現champion", chal, champ, base + OFFSETS[key], n)
    border = abs(a["lo"] - 0.5) <= 0.01
    a["passes"] = bool(a["lo"] > 0.5)
    a["border"] = bool(border)

    print()
    print("■ 2. 対照（配管の検査。現 champion どうし。0.5 付近に出るのが正しい）")
    c = run("control", "現champion vs 現champion", champ, champ,
            base + OFFSETS["control"], args.n)
    plumbing_ok = bool(c["lo"] <= 0.5 <= c["hi"])
    out["plumbing_ok"] = plumbing_ok
    if not plumbing_ok:
        print("  ← **対照が 0.5 を外した。測り方が壊れている。上の数字を信用してはならない**")

    if not args.skip_audit:
        print()
        print("■ 3. 覗き見監査（D-026。地平を延ばす AI は相手のターンを想像で進めるので必須）")
        if diff is None:
            r = audit(args.deck, pool, args.vb, config)
        else:
            from meicho.audit import replay_audit
            from meicho.heuristic import HeuristicAgent
            r = replay_audit(audit_spec(pool, diff, args.deck),
                             lambda sd: HeuristicAgent(sd),
                             config, pool, n_games=3, variants=2, node_cap=120,
                             seed0=base + OFFSETS["audit"])
        out["audit"] = r
        print(f"  検査した決定ノード {r['checked']} 件／隠蔽情報を参照した回数 {r['violations']}")
        if r["violations"]:
            print(f"  ← **違反あり。ここが通らない限り上の勝率は読めない**: {r['examples']}")

    print()
    print("■ 4. fingerprint（あとから同じ AI を再現するための記録）")
    dig = [x[4] for x in series_rs_digest(chal, champ, 6, config, workers=1,
                                          seed0=base + OFFSETS["challenge"])]
    out["digest_6"] = dig
    out["digest_hash"] = hashlib.sha256(
        json.dumps(dig, sort_keys=True).encode()).hexdigest()[:16]
    print(f"  挑戦者 vs champion のシード {base}..{base+5} の digest: {out['digest_hash']}")
    ver, od, ad = rs.encoding_info()
    out["encoding"] = {"version": ver, "obs_dim": od, "act_dim": ad}
    print(f"  符号化: version {ver} / obs {od} / act {ad}")

    print()
    ok = a["passes"] and plumbing_ok and (args.skip_audit or not out["audit"]["violations"])
    if ok and border:
        print("→ **下端は 0.5 を超えたが境界である。`--retest` で n=2,400 を取り直すこと**（D-059 の型）")
    elif ok:
        print("→ **D-034 の 1・3・4 を満たした。** 残るは 2（ラダー core5 で 1 位相当）:")
        print("   python3 experiments/ladder.py core5 --workers 2")
        print("   **交代そのものはマスターが裁定する。この道具は `champion.py` を書き換えない。**")
    else:
        print("→ **条件を満たさない。champion は据え置き。**")
    out["verdict_1_3_4"] = bool(ok)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"→ {path}")
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
