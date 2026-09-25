"""TE-6（engine/app/TO_ENGINE.md）: SD02 ミラーで heuristic・mcts160・planner_lh の総当たり。

定義は gauntlets/core5.json の H / mcts160 / planner_lh と同じ（factory と kwargs）。デッキだけ SD02。
帯 715000..715999（seed_bands.json に登録済み・評価用）。3 組とも同じシード 715000..715000+n-1 を使う。
Python 版（arena.series_detail）で回す。mcts には Rust 版が無いため。
結果は results/te6/<組>.jsonl に 1 局 1 行（seed, a_win）で追記し、中断・再開できる。
"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))
from arena import load_deck, mirror_config, series_detail
from registry import make

SEED0 = 715000
PAIRS = [("planner_lh", "H"), ("mcts160", "H"), ("planner_lh", "mcts160")]
SPEC = {"H": ("heuristic", None), "mcts160": ("mcts", {"iterations": 160}),
        "planner_lh": ("planner", {"extra_turns": 1})}
OUT = os.path.join(os.path.dirname(__file__), '..', 'results', 'te6')


def done(path):
    if not os.path.exists(path):
        return {}
    return {json.loads(l)["seed"]: json.loads(l)["a_win"] for l in open(path)}


def main(n, budget, workers=2, chunk=20):
    d = load_deck("SD02"); cfg = mirror_config(d); pool = d["action_deck"]
    mk = {k: make(f, kw, pool) for k, (f, kw) in SPEC.items()}
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    for a, b in PAIRS:
        path = os.path.join(OUT, f"{a}__vs__{b}.jsonl")
        have = done(path)
        todo = [s for s in range(SEED0, SEED0 + n) if s not in have]
        while todo:
            if time.time() - t0 > budget:
                print("budget", flush=True); return
            batch = todo[:chunk]; todo = todo[chunk:]
            # series_detail は連続シードを取るので、連続した塊で回す
            s0 = batch[0]; k = len(batch)
            assert batch == list(range(s0, s0 + k))
            res = series_detail(mk[a], mk[b], k, cfg, workers=workers, seed0=s0)
            with open(path, "a") as f:
                for s, r in zip(batch, res):
                    f.write(json.dumps({"seed": s, "a_win": r}) + "\n")
            print(a, b, s0 + k - SEED0, "/", n, round(time.time() - t0), flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), float(sys.argv[2]))
