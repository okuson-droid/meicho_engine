"""`tests/test_lit_c.py::test_worlds_module_matches_diag_pimc` の基準記録を、いまのエンジンで作り直す（D-115）。

**元の記録 `results/lit/m5m1_pimc.jsonl`（便 M・D-076）は消さない・書き換えない。**便 M の結果の出典だからである。
いまのエンジンで回した**別名の記録** `results/lit/m5m1_pimc_v018.jsonl` を作り、検査はそちらを見る。

なぜ作り直すか: 元の記録は rules v0.14 より前のエンジンで回した対局である。ルールの直し（A-2・A-6 ほか）で
同じシードでも**対局そのものが変わった**ので、59 行目（1 局目の途中）で phase が食い違う。
**0〜58 行目は W・W_nokwn・H_w まで元の記録と一致する**＝W の数え方は変わっていない（D-115 に記録）。

回すのは検査が読む範囲だけ（帯の頭の 2 局 673600・673601）。探索器は検査と同じ「便 C 以前の探索器」
（`tests/test_lit_c.py::_pre_bin_c_kwargs`）を**その関数から**取る（定義を 2 か所に写さない・D-098 §5）。
Python 版・学習済みネット 3 本（`drl_sd001_vc4`・`drl_sd001_s1`・`pi_small64_e10`）が要る。所要は約 30 秒。

    python experiments/regen_m5m1_pimc.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from meicho.version import RULES_VERSION                          # noqa: E402  D-117

SEEDS = (673600, 673601)
OUT = os.path.join(ROOT, "results", "lit", "m5m1_pimc_v018.jsonl")


def main() -> int:
    import diag_pimc
    from test_lit_c import _pre_bin_c_kwargs
    kw = _pre_bin_c_kwargs()
    rows = []
    for sd in SEEDS:
        r, _ = diag_pimc._one(("SD001", kw, sd, 200))
        rows.extend(r)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    meta = {"made_by": "experiments/regen_m5m1_pimc.py", "decision": "D-115",
            "seeds": list(SEEDS), "rows": len(rows), "engine": "python",
            "rules": RULES_VERSION, "searcher": "tests/test_lit_c.py::_pre_bin_c_kwargs()",
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "note": "元の記録 m5m1_pimc.jsonl（便 M）は残す。これは検査の基準の作り直しである"}
    with open(os.path.splitext(OUT)[0] + ".meta.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"{len(rows)} 行 → {OUT}")
    print("sha256", meta["sha256"][:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
