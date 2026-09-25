"""SD02 の中段を決める測定（マスター裁定 2026-09-20: 段階は APP-005 の推し「heuristic／素の planner か greedy／planner_lh」）。

5 組とも SD02 ミラー・帯 720000..720599（n=600）・Python 版。定義は core5 の H / planner / greedy / planner_lh と同じ（デッキだけ SD02）。
**選び方は回す前に決めておく**: 中段の資格 = 対 H の 95% 下端 > 0.5 かつ 対 planner_lh の 95% 上端 < 0.5。
両方が資格を持てば、両側の余白 min(下端(対H) − 0.5, 0.5 − 上端(対 planner_lh)) が大きいほうを推す。どちらも無ければそう報告する。
結果は results/te6/middle_<A>__vs__<B>.jsonl（1 局 1 行・再開できる）。
"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))
from arena import load_deck, mirror_config, series_detail
from registry import make

SEED0, N = 720000, 600
SPEC = {"H": ("heuristic", None), "planner": ("planner", None), "greedy": ("greedy", None),
        "planner_lh": ("planner", {"extra_turns": 1})}
PAIRS = [("planner", "H"), ("greedy", "H"), ("planner", "planner_lh"), ("greedy", "planner_lh"), ("planner", "greedy")]
OUT = os.path.join(os.path.dirname(__file__), '..', 'results', 'te6')


def main(budget, workers=2, chunk=20):
    d = load_deck("SD02"); cfg = mirror_config(d); pool = d["action_deck"]
    mk = {k: make(f, kw, pool) for k, (f, kw) in SPEC.items()}
    os.makedirs(OUT, exist_ok=True); t0 = time.time()
    for a, b in PAIRS:
        path = os.path.join(OUT, f"middle_{a}__vs__{b}.jsonl")
        have = {json.loads(l)["seed"] for l in open(path)} if os.path.exists(path) else set()
        todo = [s for s in range(SEED0, SEED0 + N) if s not in have]
        while todo:
            if time.time() - t0 > budget:
                print("budget", flush=True); return
            batch = todo[:chunk]; todo = todo[chunk:]
            s0 = batch[0]; assert batch == list(range(s0, s0 + len(batch)))
            res = series_detail(mk[a], mk[b], len(batch), cfg, workers=workers, seed0=s0)
            with open(path, "a") as fh:
                for s, r in zip(batch, res):
                    fh.write(json.dumps({"seed": s, "a_win": r}) + "\n")
            print(a, b, s0 + len(batch) - SEED0, "/", N, round(time.time() - t0), flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]))
