"""G-lr の確かめ 2 本（D-172）。途中で止まっても同じコマンドで続きから。
R4: G-lr 対 S@3,000（対象デッキ ENV_SANGE_RM_TSUBAKI のミラー・挑戦 2,800 局＋null 400 局）
R5: 別の調整デッキ ENV_YANG_RF_TSUBAKI で G-lr と同じ学び方（netfree の教材 3,000 局・lr 1e-4・V_0 から）→ 対 G@0
2 本を 1 つの家族として 97.5%・直接の得点（D-170）。"""
import json, os, subprocess, sys, time
E = "/home/user/meicho_engine/engine"; R = "results/drl"; M = "results/models"
SP = "/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad"
SM = f"{SP}/s4/models"; REC = f"{SP}/s4/rec"; G2 = f"{SP}/s4/g2"
V0 = f"{M}/s2v_id_ens3.json"
T5 = "ENV_YANG_RF_TSUBAKI"
LEVEL = 0.975
env = dict(os.environ, PYTHONPATH=E, MEICHO_HOST="cc-cloud-4")
LOG = open(f"{G2}/g2.log", "a")
STOP = "/home/user/meicho_engine/AGENT_STOP"

def sh(cmd, **kw):
    kw.setdefault("stdout", LOG); kw.setdefault("stderr", subprocess.STDOUT)
    return subprocess.run(cmd, cwd=E, env=env, **kw)

def push(msg, paths):
    subprocess.run(f"cd /home/user/meicho_engine && git add {' '.join('engine/' + p for p in paths)} && git commit -q -m '[skip ci] G-lr の確かめ（D-172）: {msg}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y' ; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def stopcheck():
    if os.path.exists(STOP): print("AGENT_STOP", flush=True); sys.exit(0)

# ---- R5 の教材（記録）・学習・束ね ----
SCHED = {"g2_train": ("mirror:1200,cross:72,anchor:216", 965200, 968199),
         "g2_val": ("mirror:80,cross:4,anchor:20", 968200, 968499)}

def records():
    for name, (pb, s0, s1) in SCHED.items():
        sched = f"{R}/s4/{name}_schedule.json"
        if not os.path.exists(f"{E}/{sched}"):
            sh([sys.executable, "experiments/make_s2_schedule.py", "--target", T5, "--per-block", pb, "--purpose", "stage4_finetune",
                "--seed0", str(s0), "--band-end", str(s1), "--out", sched], check=True)
        chunks = f"{R}/s4/{name}_chunks.json"
        if not os.path.exists(f"{E}/{chunks}"):
            sh([sys.executable, "experiments/plan_chunks.py", "plan", "--schedule", sched, "--out", chunks, "--budget-sec", "30000"], check=True)
        nk = len(json.load(open(f"{E}/{chunks}"))["chunks"])
        for k in range(nk):
            man = f"{REC}/{name}.c{k:03d}.manifest.json"
            if os.path.exists(man): continue
            stopcheck()
            cs = f"{REC}/{name}.c{k:03d}.schedule.json"
            sh([sys.executable, "experiments/plan_chunks.py", "emit", "--schedule", sched, "--chunks", chunks, "--k", str(k), "--out", cs], check=True)
            sh([sys.executable, "experiments/record_mix.py", "--schedule", cs, "--out", f"{REC}/{name}.c{k:03d}", "--workers", "4"],
               check=True, stdout=open(f"{G2}/{name}.record.log", "a"))
            os.makedirs(f"{E}/{R}/s4/rec", exist_ok=True)
            subprocess.run(["cp", man, f"{E}/{R}/s4/rec/"], check=True)
            push(f"{name} の記録 塊 {k}", [f"{R}/s4/{name}_schedule.json", chunks, f"{R}/s4/rec/{name}.c{k:03d}.manifest.json"])

def chunk_dirs(name):
    nk = len(json.load(open(f"{E}/{R}/s4/{name}_chunks.json"))["chunks"])
    return ",".join(f"{REC}/{name}.c{k:03d}" for k in range(nk))

def train():
    for K in (0, 1, 2):
        out = f"{SM}/s4YGlr3000_s{K}.json"
        if os.path.exists(f"{SM}/s4YGlr3000_s{K}.meta.json"): continue
        stopcheck()
        sh([sys.executable, "experiments/drl_train.py", "--train", chunk_dirs("g2_train"), "--valid", chunk_dirs("g2_val"),
            "--out", out, "--init", f"results/models/s2v_id_s{K}.json", "--epochs", "6", "--hidden", "256", "--depth", "2",
            "--phead", "128", "--lr", "1e-4", "--bs", "1024", "--lam", "0.7", "--vtarget", "max", "--calib-scale", "bulk",
            "--select", "best_v", "--threads", "2", "--seed", str(K)], check=True, stdout=open(f"{SM}/s4YGlr3000_s{K}.log", "w"))
        os.makedirs(f"{E}/{R}/s4/models", exist_ok=True)
        subprocess.run(f"cp {SM}/s4YGlr3000_s{K}.meta.json {SM}/s4YGlr3000_s{K}.log {E}/{R}/s4/models/", shell=True, check=True)
        push(f"YANG_RF の G-lr 乱数 {K}", [f"{R}/s4/models/s4YGlr3000_s{K}.meta.json", f"{R}/s4/models/s4YGlr3000_s{K}.log"])
    ens = f"{SM}/s4YGlr3000_ens3.json"
    if not os.path.exists(ens):
        sh([sys.executable, "experiments/ensemble_net.py"] + [f"{SM}/s4YGlr3000_s{K}.json" for K in (0, 1, 2)] + ["--out", ens], check=True)
        if os.path.exists(f"{SM}/s4YGlr3000_ens3.meta.json"):
            subprocess.run(f"cp {SM}/s4YGlr3000_ens3.meta.json {E}/{R}/s4/models/", shell=True, check=True)
            push("YANG_RF の G-lr を束ねた", [f"{R}/s4/models/s4YGlr3000_ens3.meta.json"])

# ---- 直接対決（D-170 の物差し）----
JOBS = {
    "R4": {"ch": f"{SM}/s4Glr3000_ens3.json:{M}/s4S3000_ens3.json", "null": f"{M}/s4S3000_ens3.json:{M}/s4S3000_ens3.json",
           "target": "ENV_SANGE_RM_TSUBAKI", "n": 2800, "nn": 400, "seed0": 961800, "null_seed0": 964800},
    "R5": {"ch": f"{SM}/s4YGlr3000_ens3.json:{V0}", "null": f"{V0}:{V0}",
           "target": T5, "n": 2800, "nn": 400, "seed0": 968500, "null_seed0": 971500},
}

def have_n(path, name):
    if not os.path.exists(f"{E}/{path}"): return 0
    d = json.load(open(f"{E}/{path}"))
    got = [len(v) for k, v in d["results"].items() if k.startswith(name + "|")]
    return min(got) if got else 0

def run(job, name, pair, n, seed0, path):
    while have_n(path, name) < n:
        stopcheck()
        step = min(n, have_n(path, name) + 200)   # 1 ブロックなので 200 局ずつ足し継ぐ
        sh([sys.executable, "experiments/eval_s3_h2h.py", "run", "--pair", f"{name}={pair}", "--n", str(step),
            "--seed0", str(seed0), "--out", path, "--workers", "4", "--budget-sec", "480", "--target", job["target"]])
        push(f"{path.split('/')[-1]} の途中", [path])

STATE = f"{R}/g2_state.json"
st = json.load(open(f"{E}/{STATE}")) if os.path.exists(f"{E}/{STATE}") else {"done": {}, "last": {}, "rule": "D-172", "level": LEVEL}

def judge(key):
    job = JOBS[key]; out = f"{R}/g2_{key}_report.json"
    sh([sys.executable, "experiments/eval_s3_h2h.py", "report", "--in", f"{R}/g2_{key}_r01.json", "--direct", "ch",
        "--null-in", f"{R}/g2_{key}_null.json", "--level", str(LEVEL), "--out", out], stdout=subprocess.DEVNULL, check=True)
    rep = json.load(open(f"{E}/{out}")); m = rep["main"]
    st["last"][key] = {"diff": m["diff"], "lo": m["lo"], "hi": m["hi"], "verdict": m["verdict"], "null": rep.get("null")}
    st["done"][key] = m["verdict"]
    json.dump(st, open(f"{E}/{STATE}", "w"), ensure_ascii=False, indent=1)
    print(f"{key}: {m['diff']:+.4f} [{m['lo']:+.4f}, {m['hi']:+.4f}] {m['verdict']} null {rep.get('null', {}).get('diff')} {time.strftime('%H:%M:%S')}", flush=True)
    push(f"{key} の集計", [out, STATE])

# R4 は教材が要らないので先に回し、R5 の教材と学習はその前に済ませる（短い）
records(); train()
for key, job in JOBS.items():
    if key in st["done"]: continue
    run(job, "null", job["null"], job["nn"], job["null_seed0"], f"{R}/g2_{key}_null.json")
    run(job, "ch", job["ch"], job["n"], job["seed0"], f"{R}/g2_{key}_r01.json")
    judge(key)
print("ALLDONE", flush=True)
