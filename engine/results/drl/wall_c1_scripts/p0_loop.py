"""P-0（D-177・設計書 GENERALIST_STAGE4_SUMMARY_DESIGN_20261020 §5.3 の 2）: V_0 どうしを対象デッキ ENV_SANGE_RM_TSUBAKI の
ミラーで 2,800 局（帯 981500..・95%・1 回だけ・足し継がない）。200 局ずつ足し継いで回し、終わったら A 席の得点の区間を出す。"""
import json, os, subprocess, sys, time
sys.path.insert(0, "/home/user/meicho_engine/engine/experiments")
E = "/home/user/meicho_engine/engine"; R = "results/drl"
V0 = "results/models/s2v_id_ens3.json"; OUT = f"{R}/p0_null_sange_rm.json"; N = 2800; SEED0 = 981500
env = dict(os.environ, PYTHONPATH=E, MEICHO_HOST="cc-cloud-4")
LOG = open("/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/p0/p0.log", "a")

def have():
    if not os.path.exists(f"{E}/{OUT}"): return 0
    d = json.load(open(f"{E}/{OUT}")); v = [len(x) for k, x in d["results"].items() if k.startswith("null|")]
    return min(v) if v else 0

def push(msg, paths):
    subprocess.run(f"cd /home/user/meicho_engine && git add {' '.join('engine/' + p for p in paths)} && git commit -q -m '[skip ci] P-0（D-177）: {msg}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y' ; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || {{ git pull -q --no-rebase origin claude/charming-mendel-yzlmua; sleep $((2**i)); }}; done", shell=True, executable="/bin/bash", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

while have() < N:
    if os.path.exists("/home/user/meicho_engine/AGENT_STOP"): sys.exit(0)
    h = have(); step = min(N, h + 200)
    subprocess.run([sys.executable, "experiments/eval_s3_h2h.py", "run", "--pair", f"null={V0}:{V0}", "--n", str(step),
                    "--seed0", str(SEED0), "--out", OUT, "--workers", "4", "--budget-sec", "480",
                    "--target", "ENV_SANGE_RM_TSUBAKI"], cwd=E, env=env, stdout=LOG, stderr=subprocess.STDOUT)
    if have() == h: print("進まない", flush=True); sys.exit(1)
    push(f"V_0 どうし {have()} 局", [OUT])
import eval_s3_h2h as T
d = json.load(open(f"{E}/{OUT}"))
m = T.direct_score(d, "null", level=0.95)
rep = {"decision": "D-177 P-0", "n_games": N, "a_seat": 0.5 + m["diff"], "lo": 0.5 + m["lo"], "hi": 0.5 + m["hi"],
       "level": 0.95, "contains_half": (0.5 + m["lo"]) <= 0.5 <= (0.5 + m["hi"])}
json.dump(rep, open(f"{E}/{R}/p0_null_sange_rm_report.json", "w"), ensure_ascii=False, indent=1)
print("P-0(2):", rep, time.strftime("%H:%M:%S"), flush=True)
push("V_0 どうし 2,800 局の集計", [f"{R}/p0_null_sange_rm_report.json", OUT])
print("ALLDONE", flush=True)
