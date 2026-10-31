"""E-3a（D-181・CC_E3A_20261029.md §0）: netfree_vb＋履歴（V_0＋bundle_p=0.75＋hist=8）対 netfree_vb（V_0＋bundle_p=0.75）・調整デッキ 16 ブロック。
null（netfree_vb どうし）16 × 26（988900..）→ 主比較 16 × 176（ROUNDS の帯）→ 直接の得点・95% の集計。途中で止まっても同じコマンドで続きから。
足し継ぎの回 2 以降は帯を登録してから ROUNDS に足す（上限は回 3・M-4）。合わせた区間の下端 > 0 は「候補」で止める（M-3）。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1_loop_common as C                      # noqa: E402
E = C.E; R = "results/drl"
V0 = "results/models/s2v_id_ens3.json"
VB = f"{V0}+bundle_p=0.75"
NULL = ("null", f"{VB}:{VB}", 26, 988900, f"{R}/e3/e3a_null.json")
CH = ("e3a", f"{VB}+hist=8:{VB}", 176)
ROUNDS = {1: 988700}
STATE = f"{R}/e3/e3a_state.json"
os.makedirs(f"{E}/{R}/e3", exist_ok=True)
st = json.load(open(f"{E}/{STATE}")) if os.path.exists(f"{E}/{STATE}") else {"rounds": 1}
C.play(*NULL, tag="E-3a（D-181）")
while True:
    k = st["rounds"]
    if k not in ROUNDS: print(f"回 {k} の帯が未登録（登録してから ROUNDS に足す）", flush=True); sys.exit(2)
    C.play(*CH, ROUNDS[k], f"{R}/e3/e3a_h2h_r{k:02d}.json", tag="E-3a（D-181）")
    out = f"{R}/e3/e3a_report_r{k:02d}.json"
    ins = sum([["--in", f"{R}/e3/e3a_h2h_r{j:02d}.json"] for j in range(1, k + 1)], [])
    C.sh([sys.executable, "experiments/eval_s3_h2h.py", "report"] + ins + ["--direct", "e3a",
          "--null-in", NULL[4], "--level", "0.95", "--out", out], check=True)
    rep = json.load(open(f"{E}/{out}")); m = rep["main"]
    print(f"E-3a 回 1〜{k}: {m['diff']:+.4f} [{m['lo']:+.4f}, {m['hi']:+.4f}] {m['verdict']} null {rep.get('null')}", flush=True)
    st[f"r{k}"] = {"diff": m["diff"], "lo": m["lo"], "hi": m["hi"], "verdict": m["verdict"]}
    more = "足し継ぐ" in m["verdict"] and m["lo"] <= 0 and k < 3
    if more: st["rounds"] = k + 1
    json.dump(st, open(f"{E}/{STATE}", "w"), ensure_ascii=False, indent=1)
    C.push(f"回 1〜{k} の集計", [out, STATE], tag="E-3a（D-181）")
    if not more: break
print("ALLDONE", flush=True)
