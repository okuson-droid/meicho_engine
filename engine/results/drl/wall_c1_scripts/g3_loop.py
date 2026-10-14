"""腕 C の確かめ R6 と少ない教材での比較 R7（D-174）。途中で止まっても同じコマンドで続きから。
R6: V_C 対 V_0（調整デッキ 16 ブロック × 400＋null 16 × 25）・直接の得点・95%・足し継がない
R7: G-lr@1,000（対象デッキの教材 1,000 局・lr 1e-4・V_0 から）対 S@1,000（ミラー 2,800＋null 400）・直接の得点・95%"""
import json, os, subprocess, sys, time
E = "/home/user/meicho_engine/engine"; R = "results/drl"; M = "results/models"
SP = "/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad"
SM = f"{SP}/s4/models"; REC = f"{SP}/s4/rec"; G3 = f"{SP}/s4/g3"
V0 = f"{M}/s2v_id_ens3.json"
LEVEL = 0.95
env = dict(os.environ, PYTHONPATH=E, MEICHO_HOST="cc-cloud-4")
LOG = open(f"{G3}/g3.log", "a")
STOP = "/home/user/meicho_engine/AGENT_STOP"

def sh(cmd, **kw):
    kw.setdefault("stdout", LOG); kw.setdefault("stderr", subprocess.STDOUT)
    return subprocess.run(cmd, cwd=E, env=env, **kw)

def push(msg, paths):
    subprocess.run(f"cd /home/user/meicho_engine && git add {' '.join('engine/' + p for p in paths)} && git commit -q -m '[skip ci] 確かめ R6・R7（D-174）: {msg}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y' ; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || {{ git pull -q --no-rebase origin claude/charming-mendel-yzlmua; sleep $((2**i)); }}; done", shell=True, executable="/bin/bash", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def stopcheck():
    if os.path.exists(STOP): print("AGENT_STOP", flush=True); sys.exit(0)

def train():
    """G-lr@1,000: G-lr（s4Glr3000）と同じ引数で、教材だけ便 4-A の target_train（1,000 局）"""
    for K in (0, 1, 2):
        if os.path.exists(f"{SM}/s4Glr1000_s{K}.meta.json"): continue
        stopcheck()
        sh([sys.executable, "experiments/drl_train.py", "--train", f"{REC}/target_train.c000", "--valid", f"{REC}/target_val.c000",
            "--out", f"{SM}/s4Glr1000_s{K}.json", "--init", f"results/models/s2v_id_s{K}.json", "--epochs", "6", "--hidden", "256",
            "--depth", "2", "--phead", "128", "--lr", "1e-4", "--bs", "1024", "--lam", "0.7", "--vtarget", "max", "--calib-scale", "bulk",
            "--select", "best_v", "--threads", "2", "--seed", str(K)], check=True, stdout=open(f"{SM}/s4Glr1000_s{K}.log", "w"))
        subprocess.run(f"cp {SM}/s4Glr1000_s{K}.meta.json {SM}/s4Glr1000_s{K}.log {E}/{R}/s4/models/", shell=True, check=True)
        push(f"G-lr@1,000 乱数 {K}", [f"{R}/s4/models/s4Glr1000_s{K}.meta.json", f"{R}/s4/models/s4Glr1000_s{K}.log"])
    ens = f"{SM}/s4Glr1000_ens3.json"
    if not os.path.exists(ens):
        sh([sys.executable, "experiments/ensemble_net.py"] + [f"{SM}/s4Glr1000_s{K}.json" for K in (0, 1, 2)] + ["--out", ens], check=True)
        subprocess.run(f"cp {SM}/s4Glr1000_ens3.meta.json {E}/{R}/s4/models/", shell=True, check=True)
        push("G-lr@1,000 を束ねた", [f"{R}/s4/models/s4Glr1000_ens3.meta.json"])

JOBS = {
    "R6": {"ch": f"{M}/s5vC_id_ens3.json:{V0}", "null": f"{V0}:{V0}", "target": None, "n": 400, "nn": 25,
           "seed0": 971900, "null_seed0": 972400},
    "R7": {"ch": f"{SM}/s4Glr1000_ens3.json:{SM}/s4S1000_ens3.json", "null": f"{SM}/s4S1000_ens3.json:{SM}/s4S1000_ens3.json",
           "target": "ENV_SANGE_RM_TSUBAKI", "n": 2800, "nn": 400, "seed0": 972500, "null_seed0": 975500},
}

def counts(path, name):
    if not os.path.exists(f"{E}/{path}"): return []
    d = json.load(open(f"{E}/{path}"))
    return [len(v) for k, v in d["results"].items() if k.startswith(name + "|")]

def run(job, name, pair, n, seed0, path):
    nb = 1 if job["target"] else 16
    while True:
        got = counts(path, name)
        if len(got) == nb and min(got) >= n: return
        stopcheck()
        # 1 回の呼び出しは 1 ブロックを打ち切るまで止まらないので、どのブロックも 200 局ずつ足し継ぐ
        # （シードは seed0 + 済んだ局数から続くので、一度に打つのと同じ局になる）
        step = min(n, (min(got) if len(got) == nb else 0) + 200)
        cmd = [sys.executable, "experiments/eval_s3_h2h.py", "run", "--pair", f"{name}={pair}", "--n", str(step),
               "--seed0", str(seed0), "--out", path, "--workers", "4", "--budget-sec", "480"]
        if job["target"]: cmd += ["--target", job["target"]]
        r = sh(cmd)
        if counts(path, name) == got:      # 進まなかった（道具が断った）なら空回りせずに止める
            print(f"進まない: {path} {name} rc={r.returncode}", flush=True); sys.exit(1)
        push(f"{path.split('/')[-1]} の途中", [path])

STATE = f"{R}/g3_state.json"
st = json.load(open(f"{E}/{STATE}")) if os.path.exists(f"{E}/{STATE}") else {"done": {}, "last": {}, "rule": "D-174", "level": LEVEL}

EXTRA = {"R7": [975900]}   # 足し継ぎの回 2 以降の seed0（帯を登録してから足す・D-174 §2）

def rounds_of(key):
    return st.setdefault("rounds", {}).get(key, 1)

def judge(key):
    out = f"{R}/g3_{key}_report.json"
    ins = sum([["--in", f"{R}/g3_{key}_r{k:02d}.json"] for k in range(1, rounds_of(key) + 1)], [])
    sh([sys.executable, "experiments/eval_s3_h2h.py", "report"] + ins + ["--direct", "ch",
        "--null-in", f"{R}/g3_{key}_null.json", "--level", str(LEVEL), "--out", out], stdout=subprocess.DEVNULL, check=True)
    rep = json.load(open(f"{E}/{out}")); m = rep["main"]
    st["last"][key] = {"diff": m["diff"], "lo": m["lo"], "hi": m["hi"], "verdict": m["verdict"], "null": rep.get("null")}
    st["last"][key]["rounds"] = rounds_of(key)
    if "足し継ぐ" in m["verdict"]:
        st["done"].pop(key, None)
        if rounds_of(key) - 1 < len(EXTRA.get(key, [])):
            st["rounds"][key] = rounds_of(key) + 1
        else:
            st["need_band"] = key            # 次の帯が未登録なので止める
    else:
        st["done"][key] = m["verdict"]
    json.dump(st, open(f"{E}/{STATE}", "w"), ensure_ascii=False, indent=1)
    print(f"{key}: {m['diff']:+.4f} [{m['lo']:+.4f}, {m['hi']:+.4f}] {m['verdict']} null {rep.get('null', {}).get('diff')} {time.strftime('%H:%M:%S')}", flush=True)
    push(f"{key} の集計", [out, STATE])

train()
for key, job in JOBS.items():
    while key not in st["done"]:
        if st.get("need_band") == key: print(f"{key}: 足し継ぎの帯が未登録", flush=True); sys.exit(0)
        run(job, "null", job["null"], job["nn"], job["null_seed0"], f"{R}/g3_{key}_null.json")
        for k in range(1, rounds_of(key) + 1):
            s0 = job["seed0"] if k == 1 else EXTRA[key][k - 2]
            run(job, "ch", job["ch"], job["n"], s0, f"{R}/g3_{key}_r{k:02d}.json")
        judge(key)
print("ALLDONE", flush=True)
