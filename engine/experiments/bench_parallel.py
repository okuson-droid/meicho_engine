"""プロセス並列のスケーリング測定（標準ライブラリのみ）。

対局は完全に独立なので、シードで分割してプロセスに配るだけで並列化できる。
決定性は「どのシードをどのプロセスが担当しても結果が同じ」ことで保たれる
（fingerprint で確認）。

実行: python3 experiments/bench_parallel.py [workers]
"""
import sys, os, json, time, hashlib
from multiprocessing import Pool
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from meicho.engine import GameConfig
from meicho.heuristic import HeuristicAgent
from meicho.runner import play_game

DECK = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                   "decklists", "SD001.json"), encoding="utf-8"))


def one_game(seed):
    config = GameConfig(chara_decks=[DECK["chara_deck"]] * 2,
                        action_decks=[DECK["action_deck"]] * 2)
    r = play_game(config, [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)],
                  seed=seed)
    return (seed, r["winner"], r["turns"], tuple(r["life"]))


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else (os.cpu_count() or 1)
    N = 600

    t0 = time.time()
    serial = [one_game(s) for s in range(N)]
    dt_s = time.time() - t0
    print(f"直列: {N/dt_s:.0f} 局/秒")

    t0 = time.time()
    with Pool(workers) as pool:
        par = pool.map(one_game, range(N), chunksize=25)
    dt_p = time.time() - t0
    print(f"並列({workers}プロセス): {N/dt_p:.0f} 局/秒  (スケール {dt_s/dt_p:.2f}x)")

    fp_s = hashlib.sha256(repr(sorted(serial)).encode()).hexdigest()[:16]
    fp_p = hashlib.sha256(repr(sorted(par)).encode()).hexdigest()[:16]
    print(f"fingerprint 直列={fp_s} 並列={fp_p} 一致={fp_s == fp_p}")
