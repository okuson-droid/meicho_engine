"""E-1 の回し方の共通部分（e1_confirm_loop.py が使う）。"""
import json, os, subprocess, sys, time
E = "/home/user/meicho_engine/engine"
env = dict(os.environ, PYTHONPATH=E, MEICHO_HOST="cc-cloud-4")
SP = "/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad"
os.makedirs(f"{SP}/e1", exist_ok=True)
LOG = open(f"{SP}/e1/e1.log", "a")
STOP = "/home/user/meicho_engine/AGENT_STOP"
START = time.time()
# 外側の timeout（7,100 秒）で 1 ブロックの途中を捨てないよう、残りが 1 ブロックぶん（約 70 分）を切ったら新しい呼び出しを始めずに抜ける
STOP_AFTER = 7100 - 4200


def sh(cmd, **kw):
    kw.setdefault("stdout", LOG); kw.setdefault("stderr", subprocess.STDOUT)
    return subprocess.run(cmd, cwd=E, env=env, **kw)


def push(msg, paths, tag=""):
    subprocess.run(f"cd /home/user/meicho_engine && git add {' '.join('engine/' + p for p in paths)} && git commit -q -m '[skip ci] E-1{tag}（D-177）: {msg}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y' ; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || {{ git pull -q --no-rebase origin claude/charming-mendel-yzlmua; sleep $((2**i)); }}; done", shell=True, executable="/bin/bash", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def counts(path, name):
    if not os.path.exists(f"{E}/{path}"): return []
    d = json.load(open(f"{E}/{path}"))
    return [len(v) for k, v in d["results"].items() if k.startswith(name + "|")]


def play(name, pair, n, seed0, path, tag=""):
    while True:
        got = counts(path, name)
        if len(got) == 16 and min(got) >= n: return
        if os.path.exists(STOP): print("AGENT_STOP", flush=True); sys.exit(0)
        if time.time() - START > STOP_AFTER: print("時間切れの前に抜ける（同じコマンドで続きから）", flush=True); sys.exit(3)
        t0 = time.time()
        r = sh([sys.executable, "experiments/eval_s3_h2h.py", "run", "--pair", f"{name}={pair}", "--n", str(n),
                "--seed0", str(seed0), "--out", path, "--workers", "4", "--budget-sec", "480"])
        now = counts(path, name)
        if now == got: print(f"進まない: {path} rc={r.returncode}", flush=True); sys.exit(1)
        print(f"{name}: {sum(now)} 局 {time.time() - t0:.0f}s {time.strftime('%H:%M:%S')}", flush=True)
        push(f"{path.split('/')[-1]} {sum(now)} 局", [path], tag)
