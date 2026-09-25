"""TE-6 追加（マスター裁定 C）: SD02 で `planner_lh` より強い版を探す。

候補（学習したネットを使わない。SD02 には学習済みのネットが無いため）:
  C1_kheb    … planner_lh ＋ 現 SD001 champion のうちネットを使わないつまみ全部
               （choice_phases / solo_samples=4 / known_hand / endgame_enum=64 / draw_buckets=1 / bundle_p=0.75）
  C2_s12     … planner_lh ＋ 対抗の決定化 6→12 本（STRENGTH_REVIEW_20260902 で SD001 では勝った）
  C3_mcts640 … mcts の反復 160→640
段 1 ふるい: 各候補 対 planner_lh・帯 716000..716299（n=300）。
段 2 確かめ: 勝ち残り 対 planner_lh・別帯 717000..717599（n=600）。
使い方: python te6_sd02_stronger.py <stage:1|2> <budget_sec> [候補名...]
結果は results/te6/stronger_<段>_<候補>.jsonl（1 局 1 行・再開できる）。
"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))
from arena import load_deck, mirror_config, series_detail
from registry import make

LH = {"extra_turns": 1}
CAND = {
    "C1_kheb": ("planner", {**LH, "choice_phases": True, "solo_samples": 4, "known_hand": True,
                            "endgame_enum": 64, "draw_buckets": 1, "bundle_p": 0.75}),
    "C2_s12": ("planner", {**LH, "samples": 12}),
    "C3_mcts640": ("mcts", {"iterations": 640}),
}
STAGE = {1: (716000, 300), 2: (717000, 600)}
OUT = os.path.join(os.path.dirname(__file__), '..', 'results', 'te6')


def main(stage, budget, names, workers=2, chunk=10):
    seed0, n = STAGE[stage]
    d = load_deck("SD02"); cfg = mirror_config(d); pool = d["action_deck"]
    base = make("planner", LH, pool)
    os.makedirs(OUT, exist_ok=True); t0 = time.time()
    for name in names:
        f, kw = CAND[name]; a = make(f, kw, pool)
        path = os.path.join(OUT, f"stronger_{stage}_{name}.jsonl")
        have = set()
        if os.path.exists(path):
            have = {json.loads(l)["seed"] for l in open(path)}
        todo = [s for s in range(seed0, seed0 + n) if s not in have]
        while todo:
            if time.time() - t0 > budget:
                print("budget", flush=True); return
            batch = todo[:chunk]; todo = todo[chunk:]
            s0 = batch[0]; assert batch == list(range(s0, s0 + len(batch)))
            res = series_detail(a, base, len(batch), cfg, workers=workers, seed0=s0)
            with open(path, "a") as fh:
                for s, r in zip(batch, res):
                    fh.write(json.dumps({"seed": s, "a_win": r}) + "\n")
            print(stage, name, s0 + len(batch) - seed0, "/", n, round(time.time() - t0), flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), float(sys.argv[2]), sys.argv[3:] or list(CAND))
