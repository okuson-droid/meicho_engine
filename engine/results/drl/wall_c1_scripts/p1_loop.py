"""P-1（D-177・設計書 GENERALIST_STAGE4_SUMMARY_DESIGN_20261020 §2.4）: G-lr の錨。G-lr（s4Glr3000_ens3）と G@0（s2v_id_ens3）を同じシードで、
対象デッキ ENV_SANGE_RM_TSUBAKI のミラー。相手 素 planner 1,600 局・H 400 局・貪欲 400 局（相手ごとに別のファイル）。
規則: 候補 − 基準の 95% 上端 < 0 がどれか 1 つでもあれば、G-lr を既定にしない（止めて相談）。200 局ずつ足し継ぐ。"""
import json, os, subprocess, sys, time
E = "/home/user/meicho_engine/engine"; R = "results/drl"
SP = "/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad"
GLR = f"{SP}/s4/models/s4Glr3000_ens3.json"; G0 = "results/models/s2v_id_ens3.json"
JOBS = [("planner", 1600, 984300), ("heuristic", 400, 985900), ("greedy", 400, 985900)]
env = dict(os.environ, PYTHONPATH=E, MEICHO_HOST="cc-cloud-4")
LOG = open(f"{SP}/s4/p1/p1.log", "a")

def push(msg, paths):
    subprocess.run(f"cd /home/user/meicho_engine && git add {' '.join('engine/' + p for p in paths)} && git commit -q -m '[skip ci] P-1（D-177）: {msg}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y' ; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || {{ git pull -q --no-rebase origin claude/charming-mendel-yzlmua; sleep $((2**i)); }}; done", shell=True, executable="/bin/bash", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def have(path, opp):
    if not os.path.exists(f"{E}/{path}"): return 0
    d = json.load(open(f"{E}/{path}"))
    return min([len(d["results"].get(f"{a}|{opp}", [])) for a in ("glr", "g0")])

summary = {}
for opp, n, s0 in JOBS:
    path = f"{R}/p1_anchor_{opp}.json"
    while have(path, opp) < n:
        if os.path.exists("/home/user/meicho_engine/AGENT_STOP"): sys.exit(0)
        h = have(path, opp); step = min(n, h + 200)
        subprocess.run([sys.executable, "experiments/eval_s2_repr.py", "run", "--task", "s4", "--target", "ENV_SANGE_RM_TSUBAKI",
                        "--opponents", opp, "--arm", f"glr={GLR}", "--arm", f"g0={G0}", "--n", str(step), "--seed0", str(s0),
                        "--out", path, "--workers", "4", "--budget-sec", "480"], cwd=E, env=env, stdout=LOG, stderr=subprocess.STDOUT)
        if have(path, opp) == h: print("進まない", path, flush=True); sys.exit(1)
        push(f"錨 {opp} {have(path, opp)} 局", [path])
    rep = f"{R}/p1_anchor_{opp}_report.json"
    subprocess.run([sys.executable, "experiments/eval_s2_repr.py", "report", "--in", path, "--new", "glr", "--old", "g0",
                    "--level", "0.95", "--out", rep], cwd=E, env=env, stdout=subprocess.DEVNULL, check=True)
    c = json.load(open(f"{E}/{rep}"))["compare"]["glr-g0"]
    summary[opp] = {"diff": c["diff"], "lo": c["lo"], "hi": c["hi"], "n": c["n_per_block"]}
    print(f"錨 {opp}: glr − g0 = {c['diff']:+.4f} [{c['lo']:+.4f}, {c['hi']:+.4f}]（{c['n_per_block']} 局）", flush=True)
    push(f"錨 {opp} の集計", [rep])
summary["rule"] = "95% 上端 < 0 がどれか 1 つでもあれば G-lr を既定にしない"
summary["any_worse"] = any(v["hi"] < 0 for k, v in summary.items() if isinstance(v, dict))
json.dump(summary, open(f"{E}/{R}/p1_anchor_summary.json", "w"), ensure_ascii=False, indent=1)
push("錨のまとめ", [f"{R}/p1_anchor_summary.json"])
print("ALLDONE", summary, flush=True)
