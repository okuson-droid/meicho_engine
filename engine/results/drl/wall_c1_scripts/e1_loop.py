"""E-1（D-177・CC_E1_20261021.md §0）: netfree_v(value_views=2) 対 netfree_v（V はどちらも V_0）・調整デッキ 16 ブロック。
null 16 × 26（986600..）→ 主比較 16 × 176（986400..）→ 直接の得点・95% の集計。途中で止まっても同じコマンドで続きから。
足し継ぎ（回 2 以降）は帯を登録してから足すので、ここでは回 1 まで（集計の判定が「足し継ぐ」なら止まる）。"""
import json, os, subprocess, sys, time
E = "/home/user/meicho_engine/engine"; R = "results/drl"
V0 = "results/models/s2v_id_ens3.json"
LEVEL = 0.95
env = dict(os.environ, PYTHONPATH=E, MEICHO_HOST="cc-cloud-4")
SP = "/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad"
os.makedirs(f"{SP}/e1", exist_ok=True)
LOG = open(f"{SP}/e1/e1.log", "a")
STOP = "/home/user/meicho_engine/AGENT_STOP"
JOBS = [("null", f"{V0}:{V0}", 26, 986600, f"{R}/e1/e1_null.json"),
        ("e1", f"{V0}+views=2:{V0}", 176, 986400, f"{R}/e1/e1_h2h_r01.json")]


def sh(cmd, **kw):
    kw.setdefault("stdout", LOG); kw.setdefault("stderr", subprocess.STDOUT)
    return subprocess.run(cmd, cwd=E, env=env, **kw)


def push(msg, paths):
    subprocess.run(f"cd /home/user/meicho_engine && git add {' '.join('engine/' + p for p in paths)} && git commit -q -m '[skip ci] E-1（D-177）: {msg}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y' ; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || {{ git pull -q --no-rebase origin claude/charming-mendel-yzlmua; sleep $((2**i)); }}; done", shell=True, executable="/bin/bash", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def counts(path, name):
    if not os.path.exists(f"{E}/{path}"): return []
    d = json.load(open(f"{E}/{path}"))
    return [len(v) for k, v in d["results"].items() if k.startswith(name + "|")]


for name, pair, n, seed0, path in JOBS:
    while True:
        got = counts(path, name)
        if len(got) == 16 and min(got) >= n: break
        if os.path.exists(STOP): print("AGENT_STOP", flush=True); sys.exit(0)
        t0 = time.time()
        r = sh([sys.executable, "experiments/eval_s3_h2h.py", "run", "--pair", f"{name}={pair}", "--n", str(n),
                "--seed0", str(seed0), "--out", path, "--workers", "4", "--budget-sec", "480"])
        now = counts(path, name)
        if now == got: print(f"進まない: {path} rc={r.returncode}", flush=True); sys.exit(1)
        print(f"{name}: {sum(now)} 局 {time.time() - t0:.0f}s {time.strftime('%H:%M:%S')}", flush=True)
        push(f"{path.split('/')[-1]} {sum(now)} 局", [path])

out = f"{R}/e1/e1_report.json"
sh([sys.executable, "experiments/eval_s3_h2h.py", "report", "--in", JOBS[1][4], "--direct", "e1",
    "--null-in", JOBS[0][4], "--level", str(LEVEL), "--out", out], check=True)
rep = json.load(open(f"{E}/{out}")); m = rep["main"]
print(f"E-1 回 1: {m['diff']:+.4f} [{m['lo']:+.4f}, {m['hi']:+.4f}] {m['verdict']} null {rep.get('null')}", flush=True)
push("回 1 の集計", [out])
print("ALLDONE", flush=True)
