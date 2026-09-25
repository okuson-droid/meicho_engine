"""汎用 AI 計画（D-086）段階1B後「観測・符号化の費用分離」の測定（D-120）。勝率は採否に使わない。

2 つの部分から成る。

1. **時計の測定**（この道具の `eval` と、`drl_record.py` の記録）
   - 記録 200 局: `drl_record.py --deck SD001 --seed0 823000 --n 200 --champion --record both --workers 2`
   - 評価 200 局: `python experiments/g1_cost_split.py eval --seed0 823200 --n 200 --workers 2`
     champion 同士・SD001 同型を `rs.series_digest` で回し、局/秒・ターン数・決定数（steps）を出す。
     続けて先頭 20 局（823200..823219）を**もう一度**回し、digest が全局一致することを確かめる（決定性）。
   - 環境 step の定義: `apply` 1 回（＝決定者が揃った 1 回の解決）。`steps` はこの数。
2. **内訳の測定**（`callgrind`・命令数）: 作業環境で 1 局ずつ（記録 823400・評価 823401）。
   `python experiments/g1_cost_split.py profile --mode eval --seed 823401` を
   `valgrind --tool=callgrind` の下で回す。命令数は時間そのものではないが、時計で測れない内側の比率を出す。

3. **時計での裏づけ**（`variant`）: 内訳で最大だった部品を外した変種を少しだけ回し、時計でも同じ順になるかを見る。
   打ち方が変わるので勝率は読まない。`variant no_proxy_pi --seed0 823420 --n 10`／`variant netfree --seed0 823430 --n 20`。
   `profile --variant netfree` で、ネットを使わない構成の内訳も取れる。

出力: `results/g1/g1_eval_<seed0>.json`・`results/g1/g1_variant_<名前>_<seed0>.json`。記録は `results/drl/g1_speed_record.bin.manifest.json`（manifest だけ持ち帰る）。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                            # noqa: E402

import champion                                                   # noqa: E402
from arena import load_deck, mirror_config                        # noqa: E402
from arena_rs import ensure_cards                                 # noqa: E402
from meicho.version import RULES_VERSION                          # noqa: E402


def _machine() -> dict:
    cpu = platform.processor() or ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return {"platform": platform.platform(), "cpu": cpu, "cores": os.cpu_count(),
            "python": platform.python_version(), "encoding_info": list(rs.encoding_info()),
            "rules_version": RULES_VERSION}


def _setup():
    ensure_cards()
    deck = load_deck("SD001")
    pool = deck["action_deck"]
    cfg = mirror_config(deck)
    cfg.validate()
    return cfg, champion.spec("SD001", pool), champion.spec("SD001", pool)


def cmd_eval(a):
    cfg, sa, sb = _setup()
    t = time.perf_counter()
    rows = rs.series_digest(cfg.chara_decks, cfg.action_decks, sa, sb, a.seed0, a.n, a.workers, 200)
    sec = time.perf_counter() - t
    t2 = time.perf_counter()
    again = rs.series_digest(cfg.chara_decks, cfg.action_decks, sa, sb, a.seed0, a.recheck, a.workers, 200)
    sec2 = time.perf_counter() - t2
    same = [r[4] for r in rows[:a.recheck]] == [r[4] for r in again]
    turns = [r[1] for r in rows]
    steps = [r[2] for r in rows]
    out = {
        "what": "g1 評価 200 局（champion 同士・SD001 同型・rs.series_digest）",
        "champion": champion.describe("SD001"), "seed0": a.seed0, "n": a.n, "workers": a.workers,
        "seconds": sec, "games_per_sec": a.n / sec, "sec_per_game_per_worker": sec * a.workers / a.n,
        "mean_turns": sum(turns) / len(turns), "mean_steps": sum(steps) / len(steps),
        "steps_per_sec": sum(steps) / sec, "aborted": sum(1 for r in rows if r[0] is None and r[1] > 200),
        "recheck_n": a.recheck, "recheck_seconds": sec2, "digest_recheck_identical": same,
        "machine": _machine(),
    }
    os.makedirs(os.path.join(_HERE, "..", "results", "g1"), exist_ok=True)
    path = os.path.join(_HERE, "..", "results", "g1", f"g1_eval_{a.seed0}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n書いた: {path}")


VARIANTS = {
    # 時間だけを見る比較（打ち方が変わるので勝率は読まない）。
    "no_proxy_pi": "champion から代打ち π（`policy_net`）だけを外す——内訳で最大だった π の推論の重さを時計で確かめる",
    "netfree": "ネットを 1 本も使わない計画探索（champion から V・π₀・代打ち π・束ねた解を外す）——"
               "SD001 専用のネットを他のデッキに使えない汎用 AI の段階2 の教師の、いちばん素直な候補",
}


def _variant_spec(name, spec):
    s = dict(spec)
    if name == "no_proxy_pi":
        s.pop("policy_net", None); s.pop("policy_scope", None)
    elif name == "netfree":
        for k in ("value_net", "opp_policy_net", "opp_policy_root_only", "policy_net", "policy_scope", "bundle_p"):
            s.pop(k, None)
    else:
        raise SystemExit(f"未知の変種: {name}")
    return s


def cmd_variant(a):
    cfg, sa, sb = _setup()
    sa, sb = _variant_spec(a.name, sa), _variant_spec(a.name, sb)
    t = time.perf_counter()
    rows = rs.series_digest(cfg.chara_decks, cfg.action_decks, sa, sb, a.seed0, a.n, a.workers, 200)
    sec = time.perf_counter() - t
    steps = [r[2] for r in rows]
    out = {"variant": a.name, "why": VARIANTS[a.name], "seed0": a.seed0, "n": a.n, "workers": a.workers,
           "seconds": sec, "games_per_sec": a.n / sec, "sec_per_game_per_worker": sec * a.workers / a.n,
           "mean_turns": sum(r[1] for r in rows) / len(rows), "mean_steps": sum(steps) / len(steps),
           "steps_per_sec": sum(steps) / sec, "machine": _machine()}
    os.makedirs(os.path.join(_HERE, "..", "results", "g1"), exist_ok=True)
    path = os.path.join(_HERE, "..", "results", "g1", f"g1_variant_{a.name}_{a.seed0}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_profile(a):
    """callgrind の下で 1 局だけ回す（内訳の測定用）。"""
    cfg, sa, sb = _setup()
    if a.variant:
        sa, sb = _variant_spec(a.variant, sa), _variant_spec(a.variant, sb)
    if a.mode == "record":
        rs.series_record(cfg.chara_decks, cfg.action_decks, sa, sb, a.seed, 1,
                         os.path.join(_HERE, "..", "results", "g1", "g1_profile.bin"), 1, 200, True, True)
    else:
        rs.series_digest(cfg.chara_decks, cfg.action_decks, sa, sb, a.seed, 1, 1, 200)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eval")
    e.add_argument("--seed0", type=int, default=823200)
    e.add_argument("--n", type=int, default=200)
    e.add_argument("--workers", type=int, default=2)
    e.add_argument("--recheck", type=int, default=20)
    p = sub.add_parser("profile")
    p.add_argument("--mode", choices=["eval", "record"], required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--variant", default=None)
    v = sub.add_parser("variant")
    v.add_argument("name", choices=sorted(VARIANTS))
    v.add_argument("--seed0", type=int, required=True)
    v.add_argument("--n", type=int, default=10)
    v.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    {"eval": cmd_eval, "profile": cmd_profile, "variant": cmd_variant}[a.cmd](a)


if __name__ == "__main__":
    main()
