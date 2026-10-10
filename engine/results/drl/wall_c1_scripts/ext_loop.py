"""追試の足し継ぎ（D-169）。腕 C → B → A の順に 1 回（16 × 150・挑戦＋null）ずつ足し、合わせた区間で止める条件を見る。
途中で止まっても同じコマンドで続きから（1 回の中も eval_s3_h2h の足し継ぎで続きから）。1 回 8 分以内の塊ごとに push。"""
import json, os, subprocess, sys, time
E = "/home/user/meicho_engine/engine"; R = "results/drl"; M = "results/models"
V0 = f"{M}/s2v_id_ens3.json"
ARMS = {
    "C": {"ch": f"{M}/s5vC_id_ens3.json:{V0}", "base": 939700, "level": 0.983, "prior": [f"{R}/wall_c1_retest_h2h.json"]},
    "B": {"ch": f"{M}/s5vB_id_ens3.json:{V0}", "base": 944700, "level": 0.983, "prior": []},
    "A": {"ch": f"{V0}+pi={M}/s5piA_s0.json:{V0}", "base": 949700, "level": 0.95, "prior": [f"{R}/wall_a1_retest_h2h.json"]},
}
CAP = 33
env = dict(os.environ, PYTHONPATH=E, MEICHO_HOST="cc-cloud-4")
STATE = f"{R}/wall_ext_state.json"

def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=E, env=env, **kw)

def push(msg):
    subprocess.run(f"cd /home/user/meicho_engine && git add engine/{R}/wall_ext_* && git commit -q -m '[skip ci] 追試の足し継ぎ（D-169）: {msg}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y' ; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done", shell=True)

def complete(path, n):
    if not os.path.exists(f"{E}/{path}"): return False
    d = json.load(open(f"{E}/{path}"))
    ks = [k for k in d["results"] if k.startswith(("ch|", "null|"))]
    return len(ks) == 32 and all(len(d["results"][k]) >= n for k in ks)

def files(arm, st):
    return ARMS[arm]["prior"] + [f"{R}/wall_ext_{arm}_r{r:02d}.json" for r in range(1, st["rounds"][arm] + 1)]

def judge(arm, st):
    fs = files(arm, st)
    out = f"{R}/wall_ext_{arm}_report.json"
    sh([sys.executable, "experiments/eval_s3_h2h.py", "report"] + sum([["--in", f] for f in fs], []) +
       ["--challenge", "ch", "--null", "null", "--rule", "wall", "--level", str(ARMS[arm]["level"]), "--retest", "--out", out],
       stdout=subprocess.DEVNULL, check=True)
    rep = json.load(open(f"{E}/{out}"))
    m = rep["main"]
    stop = "伸びた（下端 > 0）" if m["lo"] > 0 else ("+2% 以上を否定（上端 < +0.02）" if m["hi"] < 0.02 else None)
    st["last"][arm] = {"n_per_block": rep["n_per_block"], "diff": m["diff"], "lo": m["lo"], "hi": m["hi"],
                       "direct": rep.get("direct"), "stop": stop}
    if stop: st["stopped"][arm] = stop
    return stop

st = json.load(open(f"{E}/{STATE}")) if os.path.exists(f"{E}/{STATE}") else \
    {"rounds": {a: 0 for a in ARMS}, "stopped": {}, "last": {}, "rule": "D-169"}
for arm in ARMS:
    if arm not in st["last"] and ARMS[arm]["prior"] and st["rounds"][arm] == 0:
        judge(arm, st)          # 既存の追試だけで、もう止まっているか
json.dump(st, open(f"{E}/{STATE}", "w"), ensure_ascii=False, indent=1)
while True:
    if os.path.exists("/home/user/meicho_engine/AGENT_STOP"): print("AGENT_STOP"); break
    open_arms = [a for a in ARMS if a not in st["stopped"] and st["rounds"][a] < CAP]
    if not open_arms: print("ALLDONE"); break
    for arm in open_arms:
        r = st["rounds"][arm] + 1
        path = f"{R}/wall_ext_{arm}_r{r:02d}.json"
        seed0 = ARMS[arm]["base"] + 150 * (r - 1)
        while not complete(path, 150):
            if os.path.exists("/home/user/meicho_engine/AGENT_STOP"): sys.exit(0)
            sh([sys.executable, "experiments/eval_s3_h2h.py", "run", "--pair", f"ch={ARMS[arm]['ch']}",
                "--pair", f"null={V0}:{V0}", "--n", "150", "--seed0", str(seed0), "--out", path,
                "--workers", "4", "--budget-sec", "480"], stdout=open(f"/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/ext/{arm}.log", "a"), stderr=subprocess.STDOUT)
            push(f"腕 {arm} 回 {r} の途中")
        st["rounds"][arm] = r
        stop = judge(arm, st)
        json.dump(st, open(f"{E}/{STATE}", "w"), ensure_ascii=False, indent=1)
        L = st["last"][arm]
        print(f"腕 {arm} 回 {r}: n/ブロック {L['n_per_block']} d {L['diff']:+.4f} [{L['lo']:+.4f}, {L['hi']:+.4f}] {stop or '続ける'} {time.strftime('%H:%M:%S')}", flush=True)
        push(f"腕 {arm} 回 {r} の集計（{stop or '続ける'}）")
