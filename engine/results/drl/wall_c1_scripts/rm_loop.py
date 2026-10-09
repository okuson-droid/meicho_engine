"""測り直し 3 本（D-170）。挑戦 2,800 局＋配線の確かめの null。足し継ぎは D-169 と同じ（上端 ≥ +0.02 かつ下端 ≤ 0 なら同じ大きさをもう 1 回）。
途中で止まっても同じコマンドで続きから。1 回 8 分以内の塊ごとに push。"""
import json, os, subprocess, sys, time
E = "/home/user/meicho_engine/engine"; R = "results/drl"; M = "results/models"
SP = "/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad"
V0 = f"{M}/s2v_id_ens3.json"
SM = f"{SP}/s4/models"
JOBS = {
    "R1": {"ch": f"{M}/s3v1_id_ens3.json:{V0}", "null": f"{V0}:{V0}", "target": None, "n": 175, "nn": 25,
           "seed0": 954700, "null_seed0": 954900},
    "R2": {"ch": f"{SM}/s4Glr3000_ens3.json:{V0}", "null": f"{V0}:{V0}", "target": "ENV_SANGE_RM_TSUBAKI",
           "n": 2800, "nn": 400, "seed0": 955000, "null_seed0": 958000},
    "R3": {"ch": f"{SM}/wlG12000_ens3.json:{SM}/w3G6000_ens3.json", "null": f"{SM}/w3G6000_ens3.json:{SM}/w3G6000_ens3.json",
           "target": "ENV_SANGE_RM_TSUBAKI", "n": 2800, "nn": 400, "seed0": 958400, "null_seed0": 961400},
}
LEVEL = 0.983
env = dict(os.environ, PYTHONPATH=E, MEICHO_HOST="cc-cloud-4")
LOG = open(f"{SP}/s4/rm/eval.log", "a")

def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=E, env=env, **kw)

def push(msg):
    subprocess.run(f"cd /home/user/meicho_engine && git add engine/{R}/wall_rm_* && git commit -q -m '[skip ci] 測り直し（D-170）: {msg}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y' ; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def complete(path, name, n, nblocks):
    if not os.path.exists(f"{E}/{path}"): return False
    d = json.load(open(f"{E}/{path}"))
    ks = [k for k in d["results"] if k.startswith(name + "|")]
    return len(ks) == nblocks and all(len(d["results"][k]) >= n for k in ks)

def run(job, name, pair, n, seed0, path):
    nb = 1 if job["target"] else 16
    while not complete(path, name, n, nb):
        if os.path.exists("/home/user/meicho_engine/AGENT_STOP"): sys.exit(0)
        # 1 ブロックだけ（対象デッキのミラー）のときは 1 回の呼び出しが 1 ブロックを打ち切るまで止まらないので、
        # 200 局ずつ足し継ぐ（eval_s3_h2h は --n を増やすと足りない局だけを後ろに足す）
        have = 0
        if os.path.exists(f"{E}/{path}"):
            d = json.load(open(f"{E}/{path}"))
            got = [len(v) for k, v in d["results"].items() if k.startswith(name + "|")]
            have = min(got) if len(got) == nb else 0
        step = min(n, have + 200) if job["target"] else n
        cmd = [sys.executable, "experiments/eval_s3_h2h.py", "run", "--pair", f"{name}={pair}", "--n", str(step),
               "--seed0", str(seed0), "--out", path, "--workers", "4", "--budget-sec", "480"]
        if job["target"]: cmd += ["--target", job["target"]]
        sh(cmd, stdout=LOG, stderr=subprocess.STDOUT)
        push(f"{path.split('/')[-1]} の途中")

STATE = f"{R}/wall_rm_state.json"
st = json.load(open(f"{E}/{STATE}")) if os.path.exists(f"{E}/{STATE}") else {"rounds": {k: 1 for k in JOBS}, "done": {}, "last": {}}
for key, job in JOBS.items():
    while key not in st["done"]:
        null_path = f"{R}/wall_rm_{key}_null.json"
        run(job, "null", job["null"], job["nn"], job["null_seed0"], null_path)
        r = st["rounds"][key]
        paths = []
        for k in range(1, r + 1):
            p = f"{R}/wall_rm_{key}_r{k:02d}.json"
            span = job["n"] if job["target"] else job["n"]
            seed0 = job["seed0"] if k == 1 else None
            if k > 1:
                seed0 = st["extra_seed0"][key][str(k)]
            run(job, "ch", job["ch"], job["n"], seed0, p)
            paths.append(p)
        out = f"{R}/wall_rm_{key}_report.json"
        sh([sys.executable, "experiments/eval_s3_h2h.py", "report"] + sum([["--in", p] for p in paths], []) +
           ["--direct", "ch", "--null-in", null_path, "--level", str(LEVEL), "--out", out], stdout=subprocess.DEVNULL, check=True)
        rep = json.load(open(f"{E}/{out}"))
        m = rep["main"]
        st["last"][key] = {"rounds": r, "diff": m["diff"], "lo": m["lo"], "hi": m["hi"], "verdict": m["verdict"],
                           "null": rep.get("null")}
        print(f"{key} 回 {r}: {m['diff']:+.4f} [{m['lo']:+.4f}, {m['hi']:+.4f}] {m['verdict']} null {rep.get('null',{}).get('diff')} {time.strftime('%H:%M:%S')}", flush=True)
        if m["lo"] > 0 or m["hi"] < 0.02:
            st["done"][key] = m["verdict"]
        else:
            st["rounds"][key] = r + 1          # 足し継ぎ（新しい帯は人が登録してから・帯が無ければ止める）
            ex = st.setdefault("extra_seed0", {}).setdefault(key, {})
            if str(r + 1) not in ex:
                json.dump(st, open(f"{E}/{STATE}", "w"), ensure_ascii=False, indent=1)
                push(f"{key} 回 {r} の集計（足し継ぎの帯待ち）")
                print(f"{key}: 足し継ぎの帯が未登録。止める", flush=True)
                sys.exit(3)
        json.dump(st, open(f"{E}/{STATE}", "w"), ensure_ascii=False, indent=1)
        push(f"{key} 回 {r} の集計")
print("ALLDONE")
