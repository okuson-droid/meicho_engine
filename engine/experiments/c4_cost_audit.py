"""段 C-4 の**費用（秒/局）と覗き見監査**を 1 本で回す（文献計画 便 C・D-077 追記 4）。

段 C-3 では実行スクリプトを `/tmp` に置いたのでセッションと一緒に揮発した
（`WORKER_HANDOFF_LIT_C.md` §3「揮発したもの」）。同じことを繰り返さないため、
今回は `experiments/` に**残る形**で置く。出力の形は段 C-3 の
`results/vb/c3_khe_cost.json` / `c3_khe_audit.json` と同じにしてあるので、
`verify_report.py` から同じ読み方ができる。

- 費用: 現 champion ミラーと候補ミラーを同じ局数だけ Rust で回し、秒/局の比を出す。
- 監査: `meicho.audit.replay_audit` を **n_games=6, variants=2, node_cap=120** で回す。
  `node_cap` は「1 局あたり」ではなく**全局の合計**の上限である（段 C-1・C-2 と
  同じ 120 件にそろえるためにこの 3 つの値でなければならない・§落とし穴 4）。

使い方:
    python3 experiments/c4_cost_audit.py --cand kheb \\
        --cost-seed0 698500 --cost-n 40 --audit-seed0 698600
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, ".."), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import provenance                                                  # noqa: E402
from arena import load_deck, mirror_config                         # noqa: E402
from arena_rs import PLANNER, series_rs                            # noqa: E402
from meicho.audit import replay_audit                              # noqa: E402
from meicho.planner import PlannerAgent                            # noqa: E402
from peek_counter import resolved_kwargs                           # noqa: E402
from probe_d065 import CANDIDATES                                  # noqa: E402

RESULTS = os.path.join(_HERE, "..", "results")


def _write(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print(f"書いた: {path}")


def measure_cost(deck: str, cand: str, n: int, seed0: int, workers: int) -> dict:
    """現 champion ミラーと候補ミラーの秒/局。**同じシード帯・同じ局数**で測る。"""
    cfg = mirror_config(load_deck(deck))
    pool = load_deck(deck)["action_deck"]
    base_kw = resolved_kwargs(deck)
    cand_kw = resolved_kwargs(deck, cand)
    out = {}
    for name, kw in (("champion", base_kw), (cand, cand_kw)):
        spec = PLANNER(pool, **{k: v for k, v in kw.items() if k != "opp_decklist"})
        t0 = time.time()
        series_rs(spec, spec, n, cfg, workers=workers, seed0=seed0)
        sec = round(time.time() - t0, 1)
        out[name] = {"games": n, "sec": sec, "sec_per_game": round(sec / n, 4)}
    out["ratio"] = round(out[cand]["sec_per_game"]
                         / out["champion"]["sec_per_game"], 4)
    return out


def run_audit(deck: str, cand: str, seed0: int) -> dict:
    """覗き見監査（D-026）。候補の探索が `observe` の外を見ていないこと。

    「隠蔽情報」の定義は段 C-1 で **`observe` が返さないもの**に直してある
    （`hand_known` まで差し替えると情報集合の外に出るため・D-077 追記 1）。
    """
    cfg = mirror_config(load_deck(deck))
    pool = load_deck(deck)["action_deck"]
    # `resolved_kwargs` は champion の kwargs で、`opp_decklist` を含まない
    # （`champion.kwargs_for` はプールを別に渡す作りである）。`endgame_enum` は
    # 相手のデッキリストと組でしか使えないので、ここで足す。
    kw = dict(resolved_kwargs(deck, cand))
    kw.setdefault("opp_decklist", pool)
    t0 = time.time()
    r = replay_audit(lambda sd: PlannerAgent(sd, **kw),
                     lambda sd: PlannerAgent(sd, **kw),
                     cfg, pool, n_games=6, variants=2, node_cap=120,
                     seed0=seed0)
    r = dict(r)
    r["sec"] = round(time.time() - t0, 1)
    r["provenance"] = provenance.block(kw, "python", (seed0, seed0 + 5),
                                       extra={"tool": "audit",
                                              "host": provenance.host_name()})
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--cand", required=True, choices=sorted(CANDIDATES))
    ap.add_argument("--cost-n", type=int, default=40)
    ap.add_argument("--cost-seed0", type=int, required=True)
    ap.add_argument("--audit-seed0", type=int, required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--prefix", default=None,
                    help="出力名の頭（既定は c4_<cand>）")
    ap.add_argument("--skip-cost", action="store_true")
    ap.add_argument("--skip-audit", action="store_true")
    a = ap.parse_args()
    pre = a.prefix or f"c4_{a.cand}"
    if not a.skip_cost:
        cost = measure_cost(a.deck, a.cand, a.cost_n, a.cost_seed0, a.workers)
        print(json.dumps(cost, ensure_ascii=False))
        _write(os.path.join(RESULTS, "vb", f"{pre}_cost.json"), cost)
    if not a.skip_audit:
        aud = run_audit(a.deck, a.cand, a.audit_seed0)
        print(f"監査: checked={aud['checked']} violations={aud['violations']}")
        _write(os.path.join(RESULTS, "vb", f"{pre}_audit.json"), aud)


if __name__ == "__main__":
    main()
