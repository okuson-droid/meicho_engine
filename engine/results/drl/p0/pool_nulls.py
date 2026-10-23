"""P-0 (1)（D-177・設計書 GENERALIST_STAGE4_SUMMARY_DESIGN_20261020 §5.3 の 1）: 既存の null（基準どうし・A と B が同じネット）を
種類ごと（調整デッキ 16 ブロック／対象デッキ 1 ブロック）にまとめ、A 席の得点の 95% 区間を出す。新しい対局なし。
区間: 各ファイルの各ブロックを層とし、層の中で局の組 (2k, 2k+1) を 10,000 回再標本化、局数で重みづけして合わせる。
対象: results/drl（と E-1 の results/drl/e1）の結果ファイルのうち、組 "null" を持ち A と B の指紋が同じもの（報告・状態のファイルは除く）。"""
import glob, json, os, sys
import numpy as np
D = os.path.dirname(os.path.abspath(__file__)) + "/.."
rows = {}
for p in sorted(glob.glob(f"{D}/*.json")) + sorted(glob.glob(f"{D}/e1/*.json")):   # e1/ は E-1（D-177）の null・M-6 で足す
    if p.endswith(("_report.json", "_state.json")): continue
    try: d = json.load(open(p))
    except Exception: continue
    if not isinstance(d, dict) or "results" not in d or "null" not in d.get("pairs", {}): continue
    pr = d["pairs"]["null"]
    if pr["a"]["sha"] != pr["b"]["sha"]: continue
    strata = [np.array([x[0] for x in v], float) for k, v in d["results"].items() if k.startswith("null|")]
    if not strata: continue
    kind = "tune16" if len(strata) == 16 else ("target1" if len(strata) == 1 else f"other{len(strata)}")
    rows.setdefault(kind, []).append((os.path.basename(p), d.get("seed0"), strata, pr["a"]["path"]))
rng = np.random.RandomState(0); B = 10000; out = {}
for kind, lst in rows.items():
    tot_n = sum(len(s) for _, _, ss, _ in lst for s in ss); boots = np.zeros(B); mean = 0.0
    for _, _, ss, _ in lst:
        for s in ss:
            s = s[:len(s) - len(s) % 2]; pairs = s.reshape(-1, 2).mean(1); w = len(s) / tot_n
            boots += w * pairs[rng.randint(0, len(pairs), size=(B, len(pairs)))].mean(1); mean += w * s.mean()
    lo, hi = np.percentile(boots, [2.5, 97.5])
    out[kind] = {"files": [{"file": f, "seed0": s0, "n": int(sum(len(s) for s in ss)), "base": base,
                            "a_seat": float(np.mean(np.concatenate(ss)))} for f, s0, ss, base in lst],
                 "n_games": int(tot_n), "a_seat": float(mean), "lo": float(lo), "hi": float(hi), "level": 0.95,
                 "contains_half": bool(lo <= 0.5 <= hi)}
json.dump(out, open(f"{D}/p0_pool_nulls.json", "w"), ensure_ascii=False, indent=1)
for k, v in out.items():
    print(k, v["n_games"], round(v["a_seat"], 4), [round(v["lo"], 4), round(v["hi"], 4)], v["contains_half"])
    for f in v["files"]: print("   ", f["file"], f["seed0"], f["n"], round(f["a_seat"], 4), f["base"].split("/")[-1])
