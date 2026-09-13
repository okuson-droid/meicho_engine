"""proxy_pi（代打ちを π に）の本測定: 門番 n=1,200（別帯）＋錨 3 種（同シード対・n=300）。

`probe_strength_candidates.py` の下見（n=600・0.623 ±0.039）を受けて、D-034 の 1 と
設計書 §7.1 の錨を、同じ帯 430000.. の未使用部分で取る（`seed_bands.json` に登録済み）。
ラダー・覗き見監査・fingerprint は含まない（12 倍遅いのでラダーは別途）。
"""
from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import load_deck, mirror_config                    # noqa: E402
from arena_rs import GREEDY, HEURISTIC, PLANNER, ensure_cards, series_rs   # noqa: E402
from eval_vb import paired_diff                               # noqa: E402
from meicho.drlnet import resolve_model                       # noqa: E402
import champion as chmod                                      # noqa: E402


def _resolve(kw: dict) -> dict:
    out = dict(kw)
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in out:
            out[key] = resolve_model(out[key])
    return out


def main() -> int:
    workers = 2
    ensure_cards()
    deck = load_deck("SD001")
    config = mirror_config(deck)
    pool = deck["action_deck"]
    base = _resolve(chmod.CHAMPIONS["SD001"])
    cand = _resolve({**chmod.CHAMPIONS["SD001"], "policy_net": "drl_sd001_vb3.json"})
    new, old = PLANNER(pool, **cand), PLANNER(pool, **base)
    out = {"cand": "proxy_pi", "runs": [], "anchors": []}
    t0 = time.time()
    r = series_rs(new, old, 1200, config, workers=workers, seed0=437100)
    out["runs"].append({"name": "門番: proxy_pi vs 現champion", "seed0": 437100, "n": 1200,
                        "wins": r.wins, "decided": r.decided, "p": r.p, "ci": r.ci,
                        "lo": r.p - r.ci, "hi": r.p + r.ci, "sec": time.time() - t0})
    print(f"門番 {r}  下端 {r.p - r.ci:.3f}  {time.time() - t0:.0f}s", flush=True)
    with open(os.path.join(_HERE, "..", "results", "vb", "probe_proxy_pi_full.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for name, opp, seed0 in (("H", HEURISTIC(), 438300), ("貪欲", GREEDY(pool), 438600),
                             ("素planner", PLANNER(pool), 439200)):
        t1 = time.time()
        d = paired_diff(config, new, old, opp, seed0, 300, workers)
        d.update({"opponent": name, "seed0": seed0, "sec": time.time() - t1})
        out["anchors"].append(d)
        print(f"錨 vs {name}: 新 {d['new_p']:.3f} / 前 {d['old_p']:.3f}  差 {d['diff']:+.3f} ±{d['ci']:.3f}"
              f"  新だけ勝ち {d['new_only']} / 前だけ勝ち {d['old_only']}  {d['sec']:.0f}s", flush=True)
        with open(os.path.join(_HERE, "..", "results", "vb", "probe_proxy_pi_full.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
