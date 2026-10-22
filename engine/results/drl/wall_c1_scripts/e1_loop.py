"""E-1（D-177・CC_E1_20261021.md §0）: netfree_v(value_views=2) 対 netfree_v（V はどちらも V_0）・調整デッキ 16 ブロック。
null 16 × 26（986600..）→ 主比較 16 × 176（986400..）→ 直接の得点・95% の集計。途中で止まっても同じコマンドで続きから。
足し継ぎは回 2・回 3（帯を登録済み・上限は回 3・M-4）。合わせた区間の下端 > 0 は「候補」で止める（M-3）。"""
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


ROUNDS = {1: 986400, 2: 986900, 3: 987100}   # 足し継ぎの帯（回 2・3 は 2026-10-22 に登録・上限は回 3・M-4）
STATE = f"{R}/e1/e1_state.json"
st = json.load(open(f"{E}/{STATE}")) if os.path.exists(f"{E}/{STATE}") else {"rounds": 1}


def play(name, pair, n, seed0, path):
    while True:
        got = counts(path, name)
        if len(got) == 16 and min(got) >= n: return
        if os.path.exists(STOP): print("AGENT_STOP", flush=True); sys.exit(0)
        t0 = time.time()
        r = sh([sys.executable, "experiments/eval_s3_h2h.py", "run", "--pair", f"{name}={pair}", "--n", str(n),
                "--seed0", str(seed0), "--out", path, "--workers", "4", "--budget-sec", "480"])
        now = counts(path, name)
        if now == got: print(f"進まない: {path} rc={r.returncode}", flush=True); sys.exit(1)
        print(f"{name}: {sum(now)} 局 {time.time() - t0:.0f}s {time.strftime('%H:%M:%S')}", flush=True)
        push(f"{path.split('/')[-1]} {sum(now)} 局", [path])


play(*JOBS[0])
while True:
    k = st["rounds"]
    name, pair, n, _, _ = JOBS[1]
    play(name, pair, n, ROUNDS[k], f"{R}/e1/e1_h2h_r{k:02d}.json")
    out = f"{R}/e1/e1_report.json" if k == 1 else f"{R}/e1/e1_report_r{k:02d}.json"
    ins = sum([["--in", f"{R}/e1/e1_h2h_r{j:02d}.json"] for j in range(1, k + 1)], [])
    sh([sys.executable, "experiments/eval_s3_h2h.py", "report"] + ins + ["--direct", "e1",
        "--null-in", JOBS[0][4], "--level", str(LEVEL), "--out", out], check=True)
    rep = json.load(open(f"{E}/{out}")); m = rep["main"]
    print(f"E-1 回 1〜{k}: {m['diff']:+.4f} [{m['lo']:+.4f}, {m['hi']:+.4f}] {m['verdict']} null {rep.get('null')}", flush=True)
    st[f"r{k}"] = {"diff": m["diff"], "lo": m["lo"], "hi": m["hi"], "verdict": m["verdict"]}
    # 二段構え（M-3）: 足し継ぎから出すのは「否定・悪くなった・候補」だけ。下端 > 0 は「候補」で止める（確かめは別の便）
    more = "足し継ぐ" in m["verdict"] and m["lo"] <= 0 and k < max(ROUNDS)
    if more: st["rounds"] = k + 1
    json.dump(st, open(f"{E}/{STATE}", "w"), ensure_ascii=False, indent=1)
    push(f"回 1〜{k} の集計", [out, STATE])
    if not more: break
print("ALLDONE", flush=True)
