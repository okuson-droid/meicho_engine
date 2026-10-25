"""E-2（D-179・CC_E2_20261023.md §0.3・§0.2）: 回 1 で候補 → 錨（確かめの前に）→ 新しい帯で 1 回だけの確かめ。
錨: netfree_vb と netfree_v（V_0）を同じシードで、調整デッキ 16 ブロック・素 planner 16 × 100（988100..）・H と貪欲 各 16 × 26（988200..）。
確かめ: null 16 × 26（988500..）→ 挑戦 16 × 176（988300..）→ 直接の得点・95%。途中で止まっても同じコマンドで続きから。"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1_loop_common as C                      # noqa: E402
E = C.E; R = "results/drl"; TAG = "E-2（D-179）"
V0 = "results/models/s2v_id_ens3.json"
ANCHORS = [("planner", 100, 988100), ("heuristic", 26, 988200), ("greedy", 26, 988200)]


def arm_games(path, arm):
    if not os.path.exists(f"{E}/{path}"): return []
    d = json.load(open(f"{E}/{path}"))
    return [len(v) for k, v in d["results"].items() if k.startswith(arm + "|")]


summary_path = f"{R}/e2/e2_anchor_summary.json"
summary = json.load(open(f"{E}/{summary_path}")) if os.path.exists(f"{E}/{summary_path}") else {}
for opp, n, s0 in ANCHORS:
    if opp in summary: continue
    path = f"{R}/e2/e2_anchor_{opp}.json"
    longest = None
    while True:
        a, b = arm_games(path, "e2"), arm_games(path, "v0")
        if len(a) == 16 and len(b) == 16 and min(a + b) >= n: break
        if os.path.exists(C.STOP): print("AGENT_STOP", flush=True); sys.exit(0)
        if time.time() - C.START + 1.3 * (longest or C.FIRST) > C.LIMIT:
            print("時間切れの前に抜ける（同じコマンドで続きから）", flush=True); sys.exit(3)
        t0 = time.time(); before = sum(a + b)
        C.sh([sys.executable, "experiments/eval_s2_repr.py", "run", "--opponent", opp,
              "--arm", f"e2={V0}+bundle_p=0.75", "--arm", f"v0={V0}", "--n", str(n), "--seed0", str(s0),
              "--out", path, "--workers", "4", "--budget-sec", "480"])
        longest = max(longest or 0.0, time.time() - t0)
        now = sum(arm_games(path, "e2") + arm_games(path, "v0"))
        if now == before: print(f"進まない: {path}", flush=True); sys.exit(1)
        print(f"錨 {opp}: {now} 局（両方の腕） {time.time() - t0:.0f}s {time.strftime('%H:%M:%S')}", flush=True)
        C.push(f"錨 {opp} {now} 局", [path], TAG)
    rep = f"{R}/e2/e2_anchor_{opp}_report.json"
    C.sh([sys.executable, "experiments/eval_s2_repr.py", "report", "--in", path, "--new", "e2", "--old", "v0",
          "--level", "0.95", "--out", rep], check=True)
    c = json.load(open(f"{E}/{rep}"))["compare"]["e2-v0"]
    summary[opp] = {"diff": c["diff"], "lo": c["lo"], "hi": c["hi"], "n_per_block": c.get("n_per_block")}
    print(f"錨 {opp}: e2 − v0 = {c['diff']:+.4f} [{c['lo']:+.4f}, {c['hi']:+.4f}]", flush=True)
    summary["any_worse"] = any(v["hi"] < 0 for k, v in summary.items() if isinstance(v, dict))
    json.dump(summary, open(f"{E}/{summary_path}", "w"), ensure_ascii=False, indent=1)
    C.push(f"錨 {opp} の集計", [rep, summary_path], TAG)
if summary.get("any_worse"):
    print("錨の 95% 上端 < 0 がある → 止めて相談（§0.4）", flush=True); sys.exit(4)

NULL = ("null", f"{V0}:{V0}", 26, 988500, f"{R}/e2/e2_confirm_null.json")
CH = ("e2", f"{V0}+bundle_p=0.75:{V0}", 176, 988300, f"{R}/e2/e2_confirm_h2h.json")
C.play(*NULL, tag=TAG)
C.play(*CH, tag=TAG)
out = f"{R}/e2/e2_confirm_report.json"
C.sh([sys.executable, "experiments/eval_s3_h2h.py", "report", "--in", CH[4], "--direct", "e2",
      "--null-in", NULL[4], "--level", "0.95", "--out", out], check=True)
rep = json.load(open(f"{E}/{out}")); m = rep["main"]
print(f"E-2 確かめ: {m['diff']:+.4f} [{m['lo']:+.4f}, {m['hi']:+.4f}] {m['verdict']} null {rep.get('null')}", flush=True)
C.push("確かめの集計", [out], TAG)
print("ALLDONE", flush=True)
