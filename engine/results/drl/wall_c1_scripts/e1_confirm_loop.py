"""E-1 の確かめ（D-177・CC_E1_20261021.md §0.2・M-3）: 新しい帯で 1 回だけ・足し継がない。
null 16 × 26（987750..）→ 挑戦 16 × 424（987300..）→ 直接の得点・95%。途中で止まっても同じコマンドで続きから。"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
E = "/home/user/meicho_engine/engine"; R = "results/drl"
V0 = "results/models/s2v_id_ens3.json"
import e1_loop_common as C                      # noqa: E402
JOBS = [("null", f"{V0}:{V0}", 26, 987750, f"{R}/e1/e1_confirm_null.json"),
        ("e1", f"{V0}+views=2:{V0}", 424, 987300, f"{R}/e1/e1_confirm_h2h.json")]
for job in JOBS:
    C.play(*job, tag="確かめ")
out = f"{R}/e1/e1_confirm_report.json"
C.sh([sys.executable, "experiments/eval_s3_h2h.py", "report", "--in", JOBS[1][4], "--direct", "e1",
      "--null-in", JOBS[0][4], "--level", "0.95", "--out", out], check=True)
rep = json.load(open(f"{E}/{out}")); m = rep["main"]
print(f"E-1 確かめ: {m['diff']:+.4f} [{m['lo']:+.4f}, {m['hi']:+.4f}] {m['verdict']} null {rep.get('null')}", flush=True)
C.push("確かめの集計", [out], tag="確かめ")
print("ALLDONE", flush=True)
