"""報告に載せる数字を**結果ファイルから組み立て直して**印字する（マスター指示 2026-09-10）。

## なぜ要るか

便 M の照合（`HANDOFF_20260910_LIT_C.md` §2）で、報告の数字そのものは全部合っていたのに
**読みが 1 件間違っていた**（`mean_W_ratio = 0.743` を「候補が 4 分の 3 に縮む」と読んだが、
実際は情報の無い決定 70.8% を含めた全体平均で、情報がある決定に限れば 0.121 だった）。
数字を人が書き写す限り、この種の取り違えは必ず起きる。

そこで **報告に出す数字は、この道具の出力に無いものを書かない** ことにする。
出力は 1 行 1 数字で、

    名前 | どのファイルのどの鍵から | 再計算した値 | 保存されている値 | 一致/不一致

の形をとる。「再計算」は**生の記録（`.jsonl`）から数え直した値**、「保存されている値」は
結果 JSON の集計欄である。両者がずれていれば集計の書き出しが壊れている。
生の記録が無い数字は「再計算」欄が `―` になる（＝保存値をそのまま信じるしかない数字）。

## 使い方

    python3 experiments/verify_report.py C          # 便 C
    python3 experiments/verify_report.py C --json   # 機械可読

便が増えるたびに `CHECKS` に節を足す（既存の節は動かさない）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)

RESULTS = os.path.join(_ROOT, "results")
TOL = 5e-4          # 表示は小数 3 桁なので、それより細かいずれは「一致」とみなす


def _load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_jsonl(path: str) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def _dig(obj, path: str):
    """`a.b.0.c` の形で入れ子をたどる。無ければ None。"""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def row(name: str, source: str, recomputed, stored) -> dict:
    """1 行ぶん。`recomputed` が None なら「再計算できない数字」。"""
    ok = None
    if recomputed is not None and stored is not None:
        try:
            ok = math.isclose(float(recomputed), float(stored),
                              rel_tol=0.0, abs_tol=TOL)
        except (TypeError, ValueError):
            ok = (recomputed == stored)
    return {"name": name, "source": source,
            "recomputed": recomputed, "stored": stored, "match": ok}


# ============================================================ 便 C の節
def checks_C() -> list:
    out: list = []

    # ---- 段 C-0 (1) 被覆率の基準値（生の `.jsonl` から数え直す） -------------
    base = _load_json(os.path.join(RESULTS, "lit", "c_cov_baseline.json"))
    rows = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_baseline.jsonl"))
    games = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_baseline.games.jsonl"))
    src = "results/lit/c_cov_baseline"
    if base is not None:
        agg = base["agg"]
        seeds = {g["seed"] for g in games}
        rows = [r for r in rows if r["seed"] in seeds]
        out.append(row("被覆率ハーネス 局数", f"{src}.games.jsonl", len(games),
                       agg.get("games")))
        out.append(row("被覆率ハーネス 決定数", f"{src}.jsonl", len(rows),
                       agg.get("decisions")))
        out.append(row("スキャンで見た札がある決定の割合", f"{src}.jsonl:known_n>0",
                       (sum(1 for r in rows if r["known_n"] > 0) / len(rows))
                       if rows else None,
                       _dig(agg, "known_rate.rate")))
        for k in agg.get("K_list", []):
            key = str(k)
            hh = [r for r in rows if key in r["K"]
                  and r["K"][key]["hit_hand"] is not None]
            nx = [r for r in rows if key in r["K"]
                  and r["K"][key]["hit_next"] is not None]
            ts = [r["K"][key]["tssr"] for r in rows if key in r["K"]
                  and r["K"][key]["tssr"] is not None]
            kn = [r for r in hh if r["known_n"] > 0]
            out.append(row(f"cov_hand K={k}", f"{src}.jsonl:K.{k}.hit_hand",
                           (sum(1 for r in hh if r["K"][key]["hit_hand"]) / len(hh))
                           if hh else None,
                           _dig(agg, f"by_K.{k}.cov_hand.rate")))
            out.append(row(f"cov_hand K={k}（見えている札がある決定に限る）",
                           f"{src}.jsonl:K.{k}.hit_hand|known_n>0",
                           (sum(1 for r in kn if r["K"][key]["hit_hand"]) / len(kn))
                           if kn else None,
                           _dig(agg, f"by_K.{k}.cov_hand_known.rate")))
            out.append(row(f"cov_next K={k}", f"{src}.jsonl:K.{k}.hit_next",
                           (sum(1 for r in nx if r["K"][key]["hit_next"]) / len(nx))
                           if nx else None,
                           _dig(agg, f"by_K.{k}.cov_next.rate")))
            out.append(row(f"TSSR 平均 K={k}", f"{src}.jsonl:K.{k}.tssr",
                           (sum(ts) / len(ts)) if ts else None,
                           _dig(agg, f"by_K.{k}.tssr.mean")))
            wt = [r["K"][key]["w_true"] for r in rows if key in r["K"]
                  and r["K"][key]["w_true"] is not None and r["W"]]
            inv = [1.0 / r["W"] for r in rows if key in r["K"]
                   and r["K"][key]["w_true"] is not None and r["W"]]
            out.append(row(f"TSSR プール比 K={k}", f"{src}.jsonl:K.{k}.w_true/W",
                           (sum(wt) / sum(inv)) if inv and sum(inv) > 0 else None,
                           _dig(agg, f"by_K.{k}.tssr_pooled")))

    # ---- 段 C-1 (1) 候補の被覆率（同じ 100 局・つまみだけ違う） -------------
    kh = _load_json(os.path.join(RESULTS, "lit", "c_cov_kh.json"))
    krows = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_kh.jsonl"))
    kgames = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_kh.games.jsonl"))
    ksrc = "results/lit/c_cov_kh"
    if kh is not None:
        agg = kh["agg"]
        seeds = {g["seed"] for g in kgames}
        krows = [r for r in krows if r["seed"] in seeds]
        out.append(row("C-1 被覆率ハーネス 決定数（基準と同じ 100 局）",
                       f"{ksrc}.jsonl", len(krows), agg.get("decisions")))
        for k in agg.get("K_list", []):
            key = str(k)
            hh = [r for r in krows if key in r["K"]
                  and r["K"][key]["hit_hand"] is not None]
            kn = [r for r in hh if r["known_n"] > 0]
            nx = [r for r in krows if key in r["K"]
                  and r["K"][key]["hit_next"] is not None]
            out.append(row(f"C-1 cov_hand K={k}", f"{ksrc}.jsonl:K.{k}.hit_hand",
                           (sum(1 for r in hh if r["K"][key]["hit_hand"]) / len(hh))
                           if hh else None,
                           _dig(agg, f"by_K.{k}.cov_hand.rate")))
            out.append(row(f"C-1 cov_hand K={k}（見えている札がある決定に限る）",
                           f"{ksrc}.jsonl:K.{k}.hit_hand|known_n>0",
                           (sum(1 for r in kn if r["K"][key]["hit_hand"]) / len(kn))
                           if kn else None,
                           _dig(agg, f"by_K.{k}.cov_hand_known.rate")))
            out.append(row(f"C-1 cov_next K={k}", f"{ksrc}.jsonl:K.{k}.hit_next",
                           (sum(1 for r in nx if r["K"][key]["hit_next"]) / len(nx))
                           if nx else None,
                           _dig(agg, f"by_K.{k}.cov_next.rate")))
            wt = [r["K"][key]["w_true"] for r in krows if key in r["K"]
                  and r["K"][key]["w_true"] is not None and r["W"]]
            inv = [1.0 / r["W"] for r in krows if key in r["K"]
                   and r["K"][key]["w_true"] is not None and r["W"]]
            out.append(row(f"C-1 TSSR プール比 K={k}", f"{ksrc}.jsonl:K.{k}.w_true/W",
                           (sum(wt) / sum(inv)) if inv and sum(inv) > 0 else None,
                           _dig(agg, f"by_K.{k}.tssr_pooled")))

    # ---- 段 C-2 (1) 候補の被覆率（同じ 100 局・つまみだけ違う） -------------
    khw = _load_json(os.path.join(RESULTS, "lit", "c_cov_khw.json"))
    wrows = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_khw.jsonl"))
    wgames = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_khw.games.jsonl"))
    wsrc = "results/lit/c_cov_khw"
    if khw is not None:
        agg = khw["agg"]
        seeds = {g["seed"] for g in wgames}
        wrows = [r for r in wrows if r["seed"] in seeds]
        out.append(row("C-2 被覆率ハーネス 決定数（基準と同じ 100 局）",
                       f"{wsrc}.jsonl", len(wrows), agg.get("decisions")))
        for k in agg.get("K_list", []):
            key = str(k)
            hh = [r for r in wrows if key in r["K"]
                  and r["K"][key]["hit_hand"] is not None]
            out.append(row(f"C-2 cov_hand K={k}", f"{wsrc}.jsonl:K.{k}.hit_hand",
                           (sum(1 for r in hh if r["K"][key]["hit_hand"]) / len(hh))
                           if hh else None,
                           _dig(agg, f"by_K.{k}.cov_hand.rate")))
            wt = [r["K"][key]["w_true"] for r in wrows if key in r["K"]
                  and r["K"][key]["w_true"] is not None and r["W"]]
            inv = [1.0 / r["W"] for r in wrows if key in r["K"]
                   and r["K"][key]["w_true"] is not None and r["W"]]
            out.append(row(f"C-2 TSSR プール比 K={k}", f"{wsrc}.jsonl:K.{k}.w_true/W",
                           (sum(wt) / sum(inv)) if inv and sum(inv) > 0 else None,
                           _dig(agg, f"by_K.{k}.tssr_pooled")))

    # ---- 段 C-2 (2) 錨・門番 -----------------------------------------------
    anc2 = _load_json(os.path.join(RESULTS, "vb", "c2_khw_anchor.json"))
    if anc2:
        for name, a in (anc2.get("anchors") or {}).items():
            pairs = [(x, y) for x, y in zip(a.get("new") or [], a.get("old") or [])
                     if x is not None and y is not None]
            n = len(pairs)
            ds = [float(x) - float(y) for x, y in pairs]
            diff = (sum(ds) / n) if n else None
            ci = None
            if n > 1:
                mu = sum(ds) / n
                var = sum((v - mu) ** 2 for v in ds) / (n - 1)
                ci = 1.959963985 * math.sqrt(var / n)
            out.append(row(f"C-2 錨 vs {name} 対にできた局数",
                           "results/vb/c2_khw_anchor.json:anchors", n, None))
            out.append(row(f"C-2 錨 vs {name} 対差",
                           "results/vb/c2_khw_anchor.json:anchors", diff, None))
            out.append(row(f"C-2 錨 vs {name} 対差の 95% 幅（±）",
                           "results/vb/c2_khw_anchor.json:anchors", ci, None))
            out.append(row(f"C-2 錨 vs {name} 対差の上端",
                           "results/vb/c2_khw_anchor.json:anchors",
                           (diff + ci) if ci is not None else None, None))
    for label, fn in (("GSPRT", "c2_khw_gsprt.json"), ("固定 n", "c2_khw_fixedn.json")):
        g = _load_json(os.path.join(RESULTS, "vb", fn))
        if not g:
            continue
        src = f"results/vb/{fn}"
        out.append(row(f"C-2 門番 {label} 判定", src, None, g.get("verdict")))
        out.append(row(f"C-2 門番 {label} 局数", src, None, g.get("games")))
        out.append(row(f"C-2 門番 {label} 勝率", src, None, _dig(g, "winrate.p")))
        out.append(row(f"C-2 門番 {label} 区間下端", src, None, _dig(g, "winrate.lo")))
        out.append(row(f"C-2 門番 {label} 区間上端", src, None, _dig(g, "winrate.hi")))
        if g.get("llr") is not None:
            out.append(row(f"C-2 門番 {label} LLR", src, None, g.get("llr")))
            out.append(row(f"C-2 門番 {label} ペア平均得点", src, None,
                           g.get("mean_score")))
    cost2 = _load_json(os.path.join(RESULTS, "vb", "c2_khw_cost.json"))
    if cost2:
        out.append(row("C-2 費用比（候補 ÷ champion）", "results/vb/c2_khw_cost.json",
                       None, cost2.get("ratio")))
    aud2 = _load_json(os.path.join(RESULTS, "vb", "c2_khw_audit.json"))
    if aud2:
        out.append(row("C-2 覗き見監査 調べた決定ノード",
                       "results/vb/c2_khw_audit.json", None, aud2.get("checked")))
        out.append(row("C-2 覗き見監査 違反", "results/vb/c2_khw_audit.json",
                       None, aud2.get("violations")))
    sweep = _load_json(os.path.join(RESULTS, "vb", "c2_sweep.json"))
    if sweep:
        for cell in sweep.get("cells", []):
            out.append(row(f"C-2 掃引 本数={cell['samples']} 重み={cell['weight']} 勝率",
                           "results/vb/c2_sweep.json:cells", None, cell.get("p")))
            out.append(row(f"C-2 掃引 本数={cell['samples']} 重み={cell['weight']} 秒/局",
                           "results/vb/c2_sweep.json:cells", None,
                           cell.get("sec_per_game")))

    # ---- 段 C-3 (1) 候補の被覆率（同じ 100 局・つまみだけ違う） -------------
    khe = _load_json(os.path.join(RESULTS, "lit", "c_cov_khe.json"))
    erows = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_khe.jsonl"))
    egames = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_khe.games.jsonl"))
    esrc = "results/lit/c_cov_khe"
    if khe is not None:
        agg = khe["agg"]
        seeds = {g["seed"] for g in egames}
        erows = [r for r in erows if r["seed"] in seeds]
        out.append(row("C-3 被覆率ハーネス 決定数（基準と同じ 100 局）",
                       f"{esrc}.jsonl", len(erows), agg.get("decisions")))
        for k in agg.get("K_list", []):
            key = str(k)
            have = [r for r in erows if key in r["K"]]
            hh = [r for r in have if r["K"][key]["hit_hand"] is not None]
            en = [r for r in hh if r["K"][key].get("enumerated")]
            out.append(row(f"C-3 cov_hand K={k}", f"{esrc}.jsonl:K.{k}.hit_hand",
                           (sum(1 for r in hh if r["K"][key]["hit_hand"]) / len(hh))
                           if hh else None,
                           _dig(agg, f"by_K.{k}.cov_hand.rate")))
            out.append(row(f"C-3 列挙に入った決定の割合 K={k}",
                           f"{esrc}.jsonl:K.{k}.enumerated",
                           (sum(1 for r in have if r["K"][key].get("enumerated"))
                            / len(have)) if have else None,
                           _dig(agg, f"by_K.{k}.enum_rate.rate")))
            out.append(row(f"C-3 列挙に入った決定の cov_hand K={k}",
                           f"{esrc}.jsonl:K.{k}.hit_hand|enumerated",
                           (sum(1 for r in en if r["K"][key]["hit_hand"]) / len(en))
                           if en else None,
                           _dig(agg, f"by_K.{k}.cov_hand_enum.rate")))
            wt = [r["K"][key]["w_true"] for r in have
                  if r["K"][key]["w_true"] is not None and r["W"]]
            inv = [1.0 / r["W"] for r in have
                   if r["K"][key]["w_true"] is not None and r["W"]]
            out.append(row(f"C-3 TSSR プール比 K={k}", f"{esrc}.jsonl:K.{k}.w_true/W",
                           (sum(wt) / sum(inv)) if inv and sum(inv) > 0 else None,
                           _dig(agg, f"by_K.{k}.tssr_pooled")))

    # ---- 段 C-3 (1a) 列挙の内訳（厳密な決定と、上位 16 本で切った決定） ------
    if khe is not None and erows:
        key = "6"
        en = [r for r in erows if key in r["K"] and r["K"][key].get("enumerated")
              and r["K"][key]["hit_hand"] is not None]
        le = [r for r in en if r["W"] <= 16]
        gt = [r for r in en if r["W"] > 16]
        out.append(row("C-3 列挙 W ≤ 16（厳密）の決定数", f"{esrc}.jsonl", len(le), None))
        out.append(row("C-3 列挙 W ≤ 16（厳密）の cov_hand", f"{esrc}.jsonl",
                       (sum(1 for r in le if r["K"][key]["hit_hand"]) / len(le))
                       if le else None, None))
        out.append(row("C-3 列挙 16 < W ≤ 64（上位 16 本で切った）の決定数",
                       f"{esrc}.jsonl", len(gt), None))
        out.append(row("C-3 列挙 16 < W ≤ 64 の cov_hand", f"{esrc}.jsonl",
                       (sum(1 for r in gt if r["K"][key]["hit_hand"]) / len(gt))
                       if gt else None, None))
        # 同じ決定を段 C-1（引いて当てる）で見たときの cov_hand。
        # 2 つの記録は**同じ 100 局・同じ決定の並び**なので、局ごとに順番で対応させる
        # （(seed, seat, turn, phase) は 1 ターンに複数の決定があると重なる）。
        by_e, by_k = {}, {}
        for r in erows:
            by_e.setdefault(r["seed"], []).append(r)
        for r in krows:
            by_k.setdefault(r["seed"], []).append(r)
        same = []
        for sd, lst in by_e.items():
            other = by_k.get(sd, [])
            if len(other) != len(lst):
                continue
            for a, b in zip(lst, other):
                if (a["seat"], a["turn"], a["phase"]) != (b["seat"], b["turn"], b["phase"]):
                    same = []
                    break
                if (key in a["K"] and a["K"][key].get("enumerated")
                        and key in b["K"] and b["K"][key]["hit_hand"] is not None):
                    same.append(b)
        out.append(row("C-3 同じ決定を段 C-1 で見たときの cov_hand（K=6）",
                       f"{ksrc}.jsonl", 
                       (sum(1 for r in same if r["K"][key]["hit_hand"]) / len(same))
                       if same else None, None))
        out.append(row("C-3 その決定数（段 C-1 側）", f"{ksrc}.jsonl", len(same), None))

    # ---- 段 C-3 (1b) 投票の診断（列挙が実際に手を変えた割合） ---------------
    vd = _load_json(os.path.join(RESULTS, "lit", "c3_vote_diag.json"))
    vrows = _load_jsonl(os.path.join(RESULTS, "lit", "c3_vote_diag.jsonl"))
    if vd is not None:
        agg = vd["agg"]
        src = "results/lit/c3_vote_diag.jsonl"
        en = [r for r in vrows if r["enumerated"]]
        out.append(row("C-3 投票診断 計画探索の決定", src, len(vrows),
                       agg.get("plan_decisions")))
        out.append(row("C-3 投票診断 列挙に入った決定", src, len(en),
                       agg.get("enumerated")))
        out.append(row("C-3 投票診断 列挙の割合", src,
                       (len(en) / len(vrows)) if vrows else None,
                       agg.get("enum_rate")))
        cs = [r["C"] for r in en if r["C"] is not None]
        out.append(row("C-3 投票診断 信頼度 C 平均", src,
                       (sum(cs) / len(cs)) if cs else None,
                       _dig(agg, "C.mean")))
        out.append(row("C-3 投票診断 C がしきい値を越えた割合", src,
                       (sum(1 for r in en if r["used"]) / len(en)) if en else None,
                       agg.get("conf_pass")))
        out.append(row("C-3 投票診断 投票の手と加重平均の手が違った割合", src,
                       (sum(1 for r in en if r["differs"]) / len(en)) if en else None,
                       agg.get("differs")))
        out.append(row("C-3 投票診断 実際に手が変わった割合", src,
                       (sum(1 for r in en if r["used"] and r["differs"]) / len(en))
                       if en else None, agg.get("changed")))

    # ---- 段 C-3 (2) 錨・門番・費用・監査 -----------------------------------
    anc3 = _load_json(os.path.join(RESULTS, "vb", "c3_khe_anchor.json"))
    if anc3:
        for name, a in (anc3.get("anchors") or {}).items():
            pairs = [(x, y) for x, y in zip(a.get("new") or [], a.get("old") or [])
                     if x is not None and y is not None]
            n = len(pairs)
            ds = [float(x) - float(y) for x, y in pairs]
            diff = (sum(ds) / n) if n else None
            ci = None
            if n > 1:
                mu = sum(ds) / n
                var = sum((v - mu) ** 2 for v in ds) / (n - 1)
                ci = 1.959963985 * math.sqrt(var / n)
            out.append(row(f"C-3 錨 vs {name} 対にできた局数",
                           "results/vb/c3_khe_anchor.json:anchors", n, None))
            out.append(row(f"C-3 錨 vs {name} 対差",
                           "results/vb/c3_khe_anchor.json:anchors", diff, None))
            out.append(row(f"C-3 錨 vs {name} 対差の 95% 幅（±）",
                           "results/vb/c3_khe_anchor.json:anchors", ci, None))
            out.append(row(f"C-3 錨 vs {name} 対差の上端",
                           "results/vb/c3_khe_anchor.json:anchors",
                           (diff + ci) if ci is not None else None, None))
    for label, fn in (("GSPRT", "c3_khe_gsprt.json"), ("固定 n", "c3_khe_fixedn.json")):
        g = _load_json(os.path.join(RESULTS, "vb", fn))
        if not g:
            continue
        src = f"results/vb/{fn}"
        out.append(row(f"C-3 門番 {label} 判定", src, None, g.get("verdict")))
        out.append(row(f"C-3 門番 {label} 局数", src, None, g.get("games")))
        out.append(row(f"C-3 門番 {label} 勝率", src, None, _dig(g, "winrate.p")))
        out.append(row(f"C-3 門番 {label} 区間下端", src, None, _dig(g, "winrate.lo")))
        out.append(row(f"C-3 門番 {label} 区間上端", src, None, _dig(g, "winrate.hi")))
        if g.get("llr") is not None:
            out.append(row(f"C-3 門番 {label} LLR", src, None, g.get("llr")))
            out.append(row(f"C-3 門番 {label} ペア平均得点", src, None,
                           g.get("mean_score")))
    cost3 = _load_json(os.path.join(RESULTS, "vb", "c3_khe_cost.json"))
    if cost3:
        out.append(row("C-3 秒/局（現 champion ミラー）", "results/vb/c3_khe_cost.json",
                       None, _dig(cost3, "champion.sec_per_game")))
        out.append(row("C-3 秒/局（候補ミラー）", "results/vb/c3_khe_cost.json",
                       None, _dig(cost3, "khe.sec_per_game")))
        out.append(row("C-3 費用比（候補 ÷ champion）", "results/vb/c3_khe_cost.json",
                       (_dig(cost3, "khe.sec_per_game")
                        / _dig(cost3, "champion.sec_per_game"))
                       if _dig(cost3, "champion.sec_per_game") else None,
                       cost3.get("ratio")))
    aud3 = _load_json(os.path.join(RESULTS, "vb", "c3_khe_audit.json"))
    if aud3:
        out.append(row("C-3 覗き見監査 調べた決定ノード",
                       "results/vb/c3_khe_audit.json", None, aud3.get("checked")))
        out.append(row("C-3 覗き見監査 違反", "results/vb/c3_khe_audit.json",
                       None, aud3.get("violations")))

    # ---- 段 C-4 (1) 候補の被覆率（同じ 100 局・つまみだけ違う） -------------
    # 段 C-4 は**山札の並び**を変えるつまみなので、相手の手札の被覆率（cov_hand・TSSR）は
    # 動かないのが設計どおりである。動いていないことを数字で残す（「効かない」ではなく
    # 「この物差しの外にある」——強さは門番と錨で測る・§1）。
    kheb = _load_json(os.path.join(RESULTS, "lit", "c_cov_kheb.json"))
    brows = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_kheb.jsonl"))
    bgames = _load_jsonl(os.path.join(RESULTS, "lit", "c_cov_kheb.games.jsonl"))
    bsrc = "results/lit/c_cov_kheb"
    if kheb is not None:
        agg = kheb["agg"]
        seeds = {g["seed"] for g in bgames}
        brows = [r for r in brows if r["seed"] in seeds]
        out.append(row("C-4 被覆率ハーネス 決定数（基準と同じ 100 局）",
                       f"{bsrc}.jsonl", len(brows), agg.get("decisions")))
        for k in agg.get("K_list", []):
            key = str(k)
            have = [r for r in brows if key in r["K"]]
            hh = [r for r in have if r["K"][key]["hit_hand"] is not None]
            out.append(row(f"C-4 cov_hand K={k}", f"{bsrc}.jsonl:K.{k}.hit_hand",
                           (sum(1 for r in hh if r["K"][key]["hit_hand"]) / len(hh))
                           if hh else None,
                           _dig(agg, f"by_K.{k}.cov_hand.rate")))
            out.append(row(f"C-4 cov_next K={k}", f"{bsrc}.jsonl:K.{k}.hit_next",
                           None, _dig(agg, f"by_K.{k}.cov_next.rate")))
            wt = [r["K"][key]["w_true"] for r in have
                  if r["K"][key]["w_true"] is not None and r["W"]]
            inv = [1.0 / r["W"] for r in have
                   if r["K"][key]["w_true"] is not None and r["W"]]
            out.append(row(f"C-4 TSSR プール比 K={k}", f"{bsrc}.jsonl:K.{k}.w_true/W",
                           (sum(wt) / sum(inv)) if inv and sum(inv) > 0 else None,
                           _dig(agg, f"by_K.{k}.tssr_pooled")))
            # 段 C-3 の同じ K の値を並べる（同じ 100 局・同じ帯なので直接比べてよい）
            if khe is not None:
                out.append(row(f"C-4 参考: 段 C-3 の cov_hand K={k}",
                               "results/lit/c_cov_khe.json", None,
                               _dig(khe["agg"], f"by_K.{k}.cov_hand.rate")))
                out.append(row(f"C-4 参考: 段 C-3 の TSSR プール比 K={k}",
                               "results/lit/c_cov_khe.json", None,
                               _dig(khe["agg"], f"by_K.{k}.tssr_pooled")))

    # ---- 段 C-4 (2) 錨・門番・費用・監査 -----------------------------------
    anc4 = _load_json(os.path.join(RESULTS, "vb", "c4_kheb_anchor.json"))
    if anc4:
        for name, a in (anc4.get("anchors") or {}).items():
            pairs = [(x, y) for x, y in zip(a.get("new") or [], a.get("old") or [])
                     if x is not None and y is not None]
            n = len(pairs)
            ds = [float(x) - float(y) for x, y in pairs]
            diff = (sum(ds) / n) if n else None
            ci = None
            if n > 1:
                mu = sum(ds) / n
                var = sum((v - mu) ** 2 for v in ds) / (n - 1)
                ci = 1.959963985 * math.sqrt(var / n)
            out.append(row(f"C-4 錨 vs {name} 対にできた局数",
                           "results/vb/c4_kheb_anchor.json:anchors", n, None))
            out.append(row(f"C-4 錨 vs {name} 対差",
                           "results/vb/c4_kheb_anchor.json:anchors", diff, None))
            out.append(row(f"C-4 錨 vs {name} 対差の 95% 幅（±）",
                           "results/vb/c4_kheb_anchor.json:anchors", ci, None))
            out.append(row(f"C-4 錨 vs {name} 対差の上端",
                           "results/vb/c4_kheb_anchor.json:anchors",
                           (diff + ci) if ci is not None else None, None))
    for label, fn in (("GSPRT", "c4_kheb_gsprt.json"),
                      ("固定 n", "c4_kheb_fixedn.json")):
        g = _load_json(os.path.join(RESULTS, "vb", fn))
        if not g:
            continue
        src = f"results/vb/{fn}"
        out.append(row(f"C-4 門番 {label} 判定", src, None, g.get("verdict")))
        out.append(row(f"C-4 門番 {label} 局数", src, None, g.get("games")))
        out.append(row(f"C-4 門番 {label} 勝率", src, None, _dig(g, "winrate.p")))
        out.append(row(f"C-4 門番 {label} 区間下端", src, None, _dig(g, "winrate.lo")))
        out.append(row(f"C-4 門番 {label} 区間上端", src, None, _dig(g, "winrate.hi")))
        if g.get("llr") is not None:
            out.append(row(f"C-4 門番 {label} LLR", src, None, g.get("llr")))
            out.append(row(f"C-4 門番 {label} ペア平均得点", src, None,
                           g.get("mean_score")))
    cost4 = _load_json(os.path.join(RESULTS, "vb", "c4_kheb_cost.json"))
    if cost4:
        out.append(row("C-4 秒/局（現 champion ミラー）", "results/vb/c4_kheb_cost.json",
                       None, _dig(cost4, "champion.sec_per_game")))
        out.append(row("C-4 秒/局（候補ミラー）", "results/vb/c4_kheb_cost.json",
                       None, _dig(cost4, "kheb.sec_per_game")))
        out.append(row("C-4 費用比（候補 ÷ champion）", "results/vb/c4_kheb_cost.json",
                       (_dig(cost4, "kheb.sec_per_game")
                        / _dig(cost4, "champion.sec_per_game"))
                       if _dig(cost4, "champion.sec_per_game") else None,
                       cost4.get("ratio")))
    aud4 = _load_json(os.path.join(RESULTS, "vb", "c4_kheb_audit.json"))
    if aud4:
        out.append(row("C-4 覗き見監査 調べた決定ノード",
                       "results/vb/c4_kheb_audit.json", None, aud4.get("checked")))
        out.append(row("C-4 覗き見監査 違反", "results/vb/c4_kheb_audit.json",
                       None, aud4.get("violations")))

    # ---- 交代判定（D-081 の 5 条件・別帯 700000..705999） -------------------
    # **門番は「n≥300・95% 下端 > 0.5」である**（2026-09-11 のマスター裁定で
    # D-034 改訂 1＝GSPRT・p₁=0.55 を撤回した・D-081）。GSPRT の行はそのまま残す
    # ——診断として回した記録であり、**不合格側で止まったこと自体は事実だから消さない**。
    # 判定に使うのは固定 n の行である。
    # **大きさに使えるのは固定 n だけ**（GSPRT が止まった点の勝率は勝者の呪いで歪む・D-075）。
    # 段 C-4 の帯（697200）と交代判定の帯（701200）は**別の帯**なので、
    # 同じ比較（`kheb` 対 現 champion）の独立な 2 本として**合算してよい**。
    # ——便 C で禁じた「別帯の勝率の引き算」とは別の話である。あちらは
    # **違う候補**どうしを引き算する話で、こちらは**同じ候補**の 2 本を足す話。
    for label, fn in (("GSPRT", "swap_kheb_gsprt.json"),
                      ("固定 n", "swap_kheb_fixedn.json"),
                      ("対照 null", "swap_null.json")):
        g = _load_json(os.path.join(RESULTS, "vb", fn))
        if not g:
            continue
        src = f"results/vb/{fn}"
        out.append(row(f"交代判定 {label} 判定", src, None, g.get("verdict")))
        out.append(row(f"交代判定 {label} 局数", src, None, g.get("games")))
        out.append(row(f"交代判定 {label} 勝率", src, None, _dig(g, "winrate.p")))
        out.append(row(f"交代判定 {label} 区間下端", src, None, _dig(g, "winrate.lo")))
        out.append(row(f"交代判定 {label} 区間上端", src, None, _dig(g, "winrate.hi")))
        if g.get("llr") is not None:
            out.append(row(f"交代判定 {label} LLR", src, None, g.get("llr")))
    f4 = _load_json(os.path.join(RESULTS, "vb", "c4_kheb_fixedn.json"))
    fs = _load_json(os.path.join(RESULTS, "vb", "swap_kheb_fixedn.json"))
    if f4 and fs:
        w = _dig(f4, "winrate.wins") + _dig(fs, "winrate.wins")
        n = _dig(f4, "winrate.decided") + _dig(fs, "winrate.decided")
        p = w / n
        ci = 1.959963985 * math.sqrt(p * (1 - p) / n)
        elo = 400.0 * math.log10(p / (1 - p))
        s = "results/vb/c4_kheb_fixedn.json + swap_kheb_fixedn.json"
        out.append(row("交代判定 固定 n 合算 局数（別帯 2 本）", s, n, None))
        out.append(row("交代判定 固定 n 合算 勝率", s, p, None))
        out.append(row("交代判定 固定 n 合算 区間下端", s, p - ci, None))
        out.append(row("交代判定 固定 n 合算 区間上端", s, p + ci, None))
        out.append(row("交代判定 固定 n 合算 Elo 換算", s, elo, None))
    auds = _load_json(os.path.join(RESULTS, "vb", "swap_kheb_audit.json"))
    if auds:
        out.append(row("交代判定 覗き見監査 調べた決定ノード",
                       "results/vb/swap_kheb_audit.json", None, auds.get("checked")))
        out.append(row("交代判定 覗き見監査 違反", "results/vb/swap_kheb_audit.json",
                       None, auds.get("violations")))

    # ---- 交代判定 第 2 条件（ラダー core5 v11・D-081 追記 1） ---------------
    # **この解析は交代**前**に回したものである**（`champion` 欄は当時の `planner_vc4cps`）。
    # 交代後に回し直せば `champion` は新 champion になるが、**均衡ウェイトも nA も
    # 名前の付け方には依らない**ので、判定の根拠として読める。回し直して上書きしない
    # ——判断に使った成果物は残す。
    lad = _load_json(os.path.join(RESULTS, "ladder_analysis_core5_v11.json"))
    if lad:
        s = "results/ladder_analysis_core5_v11.json"
        w = (lad.get("nash") or {}).get("weights") or {}
        out.append(row("ラダー v11 解析時の champion 欄", s, None, lad.get("champion")))
        out.append(row("ラダー v11 Nash ウェイト planner_vc4cps_kheb", s,
                       w.get("planner_vc4cps_kheb"), None))
        out.append(row("ラダー v11 Nash ウェイト planner_vc4cps", s,
                       w.get("planner_vc4cps"), None))
        out.append(row("ラダー v11 台に乗った体の数", s,
                       sum(1 for v in w.values() if v is not None and v > 1e-4), None))
        out.append(row("ラダー v11 nA（解析時の champion）", s,
                       lad.get("champion_nA"), None))
        out.append(row("ラダー v11 有効多様性", s, lad.get("effective_diversity"), None))
        for tau, v in sorted((lad.get("cycles_by_tau") or {}).items()):
            out.append(row(f"ラダー v11 3 巡回 τ={tau}", s, None,
                           v.get("count") if isinstance(v, dict) else v))
        elo = lad.get("elo") or {}
        for name in ("planner_vc4cps_kheb", "planner_vc4cps"):
            e = elo.get(name)
            if isinstance(e, dict):
                out.append(row(f"ラダー v11 Elo {name}", s, e.get("elo"), None))
                out.append(row(f"ラダー v11 Elo {name} 下端", s, _dig(e, "lo"), None))
                out.append(row(f"ラダー v11 Elo {name} 上端", s, _dig(e, "hi"), None))
    engchk = _load_json(os.path.join(RESULTS, "ladder_engine_check_core5_v11.json"))
    if engchk:
        s = "results/ladder_engine_check_core5_v11.json"
        out.append(row("ラダー v11 Python↔Rust 確認 組数", s, None,
                       len(engchk.get("rows") or [])))
        out.append(row("ラダー v11 Python↔Rust 確認 全一致", s, None,
                       engchk.get("all_same")))

    # ---- 段 C-1 (2) 錨 3 種（局ごとに対にした差） ---------------------------
    anc = _load_json(os.path.join(RESULTS, "vb", "c1_kh_anchor.json"))
    if anc:
        for name, a in (anc.get("anchors") or {}).items():
            pairs = [(x, y) for x, y in zip(a.get("new") or [], a.get("old") or [])
                     if x is not None and y is not None]
            n = len(pairs)
            diff = (sum(float(x) - float(y) for x, y in pairs) / n) if n else None
            ds = [float(x) - float(y) for x, y in pairs]
            ci = None
            if n > 1:
                mu = sum(ds) / n
                var = sum((v - mu) ** 2 for v in ds) / (n - 1)
                ci = 1.959963985 * math.sqrt(var / n)
            out.append(row(f"C-1 錨 vs {name} 対にできた局数",
                           "results/vb/c1_kh_anchor.json:anchors", n, None))
            out.append(row(f"C-1 錨 vs {name} 対差",
                           "results/vb/c1_kh_anchor.json:anchors", diff, None))
            out.append(row(f"C-1 錨 vs {name} 対差の 95% 幅（±）",
                           "results/vb/c1_kh_anchor.json:anchors", ci, None))
            out.append(row(f"C-1 錨 vs {name} 対差の上端",
                           "results/vb/c1_kh_anchor.json:anchors",
                           (diff + ci) if ci is not None else None, None))

    # ---- 段 C-1 (3) 門番（GSPRT と固定 n） ---------------------------------
    for label, fn in (("GSPRT", "c1_kh_gsprt.json"), ("固定 n", "c1_kh_fixedn.json")):
        g = _load_json(os.path.join(RESULTS, "vb", fn))
        if not g:
            continue
        src = f"results/vb/{fn}"
        out.append(row(f"C-1 門番 {label} 判定", src, None, g.get("verdict")))
        out.append(row(f"C-1 門番 {label} 局数", src, None, g.get("games")))
        out.append(row(f"C-1 門番 {label} 勝率", src, None,
                       _dig(g, "winrate.p")))
        out.append(row(f"C-1 門番 {label} 区間下端", src, None, _dig(g, "winrate.lo")))
        out.append(row(f"C-1 門番 {label} 区間上端", src, None, _dig(g, "winrate.hi")))
        if g.get("llr") is not None:
            out.append(row(f"C-1 門番 {label} LLR", src, None, g.get("llr")))
            out.append(row(f"C-1 門番 {label} ペア平均得点", src, None,
                           g.get("mean_score")))

    # ---- 段 C-1 (4) 費用・覗き見監査・回帰局面 -----------------------------
    cost = _load_json(os.path.join(RESULTS, "vb", "c1_kh_cost.json"))
    if cost:
        out.append(row("C-1 秒/局（現 champion ミラー）",
                       "results/vb/c1_kh_cost.json", None,
                       _dig(cost, "champion.sec_per_game")))
        out.append(row("C-1 秒/局（候補ミラー）", "results/vb/c1_kh_cost.json",
                       None, _dig(cost, "kh.sec_per_game")))
        out.append(row("C-1 費用比（候補 ÷ champion）",
                       "results/vb/c1_kh_cost.json",
                       (cost["kh"]["sec_per_game"] / cost["champion"]["sec_per_game"])
                       if _dig(cost, "champion.sec_per_game") else None,
                       cost.get("ratio")))
    aud = _load_json(os.path.join(RESULTS, "vb", "c1_kh_audit.json"))
    if aud:
        out.append(row("C-1 覗き見監査 調べた決定ノード",
                       "results/vb/c1_kh_audit.json", None, aud.get("checked")))
        out.append(row("C-1 覗き見監査 違反", "results/vb/c1_kh_audit.json",
                       None, aud.get("violations")))
        out.append(row("C-1 覗き見監査 情報集合の外で作り直せず飛ばした差し替え",
                       "results/vb/c1_kh_audit.json", None,
                       aud.get("skipped_variants")))
    for stage, tag, fn in (("C-1", "基準", "c_cov_regression.json"),
                           ("C-1", "候補", "c_cov_regression_kh.json"),
                           ("C-3", "候補", "c_cov_regression_khe.json")):
        reg2 = _load_json(os.path.join(RESULTS, "lit", fn))
        if not reg2:
            continue
        for r in reg2["positions"]:
            for k in reg2["K_list"]:
                b = r["K"][str(k)]
                out.append(row(f"{stage} 回帰 {tag} {r['tag']} K={k} 真の手札を含む割合",
                               f"results/lit/{fn}", None, b.get("hit_hand_rate")))
                if stage == "C-3":
                    out.append(row(f"C-3 回帰 候補 {r['tag']} K={k} 列挙に入ったか",
                                   f"results/lit/{fn}", None, b.get("enumerated")))

    # ---- 段 C-0 (2) 便 M からの訂正（§2.3・分母を添える） -------------------
    m = _load_json(os.path.join(RESULTS, "lit", "m5m1_pimc.json"))
    mrows = _load_jsonl(os.path.join(RESULTS, "lit", "m5m1_pimc.jsonl"))
    msrc = "results/lit/m5m1_pimc"
    if mrows:
        rat_all = [r["W"] / r["W_nokwn"] for r in mrows if r["W_nokwn"]]
        kn = [r for r in mrows if r["known_n"] > 0 and r["W_nokwn"]]
        rat_kn = [r["W"] / r["W_nokwn"] for r in kn]
        out.append(row("W の縮み比 全体平均（分母 = 全決定）",
                       f"{msrc}.jsonl", sum(rat_all) / len(rat_all),
                       _dig(m, "agg.known_used.mean_W_ratio")))
        out.append(row("W の縮み比 平均（分母 = 見えている札がある決定）",
                       f"{msrc}.jsonl:known_n>0", sum(rat_kn) / len(rat_kn), None))
        out.append(row("W の縮み比 中央値（同上）",
                       f"{msrc}.jsonl:known_n>0", statistics.median(rat_kn), None))
        out.append(row("見えている札がある決定の割合",
                       f"{msrc}.jsonl:known_n>0",
                       sum(1 for r in mrows if r["known_n"] > 0) / len(mrows),
                       _dig(m, "agg.known_used.rate")))
        out.append(row("W ≤ 64 の決定の割合（II-9 が働く範囲）",
                       f"{msrc}.jsonl:W<=64",
                       sum(1 for r in mrows if r["W"] <= 64) / len(mrows), None))
        out.append(row("W ≤ 64 の割合（対抗の提出に限る）",
                       f"{msrc}.jsonl:W<=64|CLASH_SUBMIT",
                       (sum(1 for r in mrows
                            if r["phase"] == "CLASH_SUBMIT" and r["W"] <= 64)
                        / max(1, sum(1 for r in mrows
                                     if r["phase"] == "CLASH_SUBMIT"))), None))

    # ---- 段 C-0 (3) 帯 -----------------------------------------------------
    led = _load_json(os.path.join(_HERE, "seed_bands.json"))
    if led:
        out.append(row("台帳の next_free", "experiments/seed_bands.json:next_free",
                       None, led.get("next_free")))
        have = {(b["start"], b["end"]) for b in led["bands"]}
        out.append(row("便 C の帯が 5 本とも登録済み", "experiments/seed_bands.json:bands",
                       sum(1 for w in [(676000, 681999), (682000, 687999),
                                       (688000, 693999), (694000, 699999),
                                       (700000, 705999)] if w in have), 5))

    # ---- 段 C-0 (4) 回帰局面の診断 -----------------------------------------
    reg = _load_json(os.path.join(RESULTS, "lit", "c_cov_regression.json"))
    if reg:
        out.append(row("回帰局面の数", "results/lit/c_cov_regression.json:positions",
                       len(reg["positions"]), 4))
        for r in reg["positions"]:
            for k in reg["K_list"]:
                b = r["K"][str(k)]
                out.append(row(f"{r['tag']} K={k} 真の手札を含むか",
                               "results/lit/c_cov_regression.json",
                               None, int(bool(b["hit_hand"]))))

    return out


# ============================================================ 便 A 後半の節
def checks_A2() -> list:
    """便 A 後半（A-2 束ねたソルバ・D-082）の報告の数字を、結果 JSON から組み立て直す。

    **報告に書く数字はこの出力にあるものだけ**（`HANDOFF_CONVENTIONS.md` の効率化 1）。
    生の記録（`.jsonl` / `gate` の真偽値の列）から数え直せるものは数え直し、
    保存されている集計と突き合わせる。
    """
    out: list = []

    # ---- 段 A2-0 (b) 被搾取の基準・(A2-4) 候補の被搾取 ----------------------
    for name, cand in (("基準（現 champion）", "a2_peek_baseline"),
                       ("b90", "a2_peek_b90"), ("b75", "a2_peek_b75"),
                       ("b50", "a2_peek_b50")):
        d = _load_json(os.path.join(RESULTS, "lit", f"{cand}.json"))
        if d is None:
            continue
        agg = d["agg"]
        rows = _load_jsonl(os.path.join(RESULTS, "lit", f"{cand}.jsonl"))
        src = f"results/lit/{cand}"
        # 1 行 1 局の記録（`champ_won` / `peek_changed` / `peek_total`）から数え直す
        dec = rows or []
        out.append(row(f"被搾取 {name} 局数", f"{src}.jsonl", len(dec) or None,
                       agg.get("n")))
        wins = sum(1 for r in dec if r.get("champ_won")) if dec else None
        out.append(row(f"被搾取 {name} 勝ち数", f"{src}.jsonl:champ_won", wins,
                       agg.get("wins_champion")))
        out.append(row(f"被搾取 {name} 勝率", f"{src}.jsonl",
                       (wins / len(dec)) if dec else None, agg.get("p")))
        out.append(row(f"被搾取 {name} 95% 半幅", "±1.96√(p(1-p)/n)",
                       _ci(agg.get("p"), agg.get("n")), agg.get("ci")))
        out.append(row(f"被搾取 {name} 透視した対抗", f"{src}.jsonl:peek_total",
                       sum(r.get("peek_total", 0) for r in dec) or None,
                       agg.get("peek_clashes")))
        out.append(row(f"被搾取 {name} 手を変えた数", f"{src}.jsonl:peek_changed",
                       sum(r.get("peek_changed", 0) for r in dec) or None,
                       agg.get("peek_changed")))
        out.append(row(f"被搾取 {name} 手を変えた割合", f"{src}.jsonl",
                       (sum(r.get("peek_changed", 0) for r in dec)
                        / sum(r.get("peek_total", 0) for r in dec))
                       if dec and sum(r.get("peek_total", 0) for r in dec) else None,
                       agg.get("changed_rate")))

    # ---- 段 A2-0 (c) 混合率の測り直し --------------------------------------
    d = _load_json(os.path.join(RESULTS, "lit", "a2_clash_mix_rate.json"))
    if d is not None:
        agg = d["agg"]
        src = "results/lit/a2_clash_mix_rate"
        out.append(row("混合率 決定化の件数", f"{src}.json:agg", agg.get("n"), 1000))
        for key, label in (("mix_rate_ai", "AI 側の混合率"),
                           ("mix_rate_opp", "相手側の混合率")):
            blk = agg.get(key) or {}
            out.append(row(label, f"{src}.json:agg.{key}",
                           (blk.get("k") / agg["n"]) if agg.get("n") else None,
                           blk.get("p")))
        g = (agg.get("mix_rate_by_gain") or {}).get("0.02") or {}
        out.append(row("混合率（得している量 > 0.02）", f"{src}.json",
                       (g.get("k") / agg["n"]) if agg.get("n") and g else None,
                       g.get("p")))
        a = agg.get("agree_with_argmax") or {}
        out.append(row("均衡の最良手と現行の一致", f"{src}.json",
                       (a.get("k") / a["n"]) if a.get("n") else None, a.get("p")))

    # ---- 段 A2-3 錨 3 種（局ごとに対にした差） ------------------------------
    for cand in ("b90", "b75", "b50"):
        d = _load_json(os.path.join(RESULTS, "lit", f"a2_anchor_{cand}.json"))
        if d is None:
            continue
        src = f"results/lit/a2_anchor_{cand}.json:anchors"
        for who, blk in (d.get("anchors") or {}).items():
            new, old = blk.get("new") or [], blk.get("old") or []
            n = min(len(new), len(old))
            if not n:
                continue
            diff = sum(1 for i in range(n) if new[i] and not old[i]) \
                - sum(1 for i in range(n) if old[i] and not new[i])
            out.append(row(f"錨 {cand} 対 {who} 局数", src, n, 600))
            out.append(row(f"錨 {cand} 対 {who} 差", src, diff / n, None))

    # ---- 段 A2-6 門番と対照 -------------------------------------------------
    for name, f in (("門番 b75", "a2_gate_b75"), ("対照 null", "a2_gate_null")):
        d = _load_json(os.path.join(RESULTS, "lit", f"{f}.json"))
        if d is None:
            continue
        g = d.get("gate") or []
        src = f"results/lit/{f}.json:gate"
        out.append(row(f"{name} 局数", src, len(g), d.get("n_gate")))
        p = (sum(1 for x in g if x) / len(g)) if g else None
        out.append(row(f"{name} 勝率", src, p, None))
        out.append(row(f"{name} 95% 下端", "p − 1.96√(p(1-p)/n)",
                       (p - _ci(p, len(g))) if p is not None else None, None))

    # ---- 費用（A2-5） -------------------------------------------------------
    for cand in ("b90", "b75", "b50"):
        d = _load_json(os.path.join(RESULTS, "vb", f"c4_{cand}_cost.json"))
        if d is None:
            continue
        src = f"results/vb/c4_{cand}_cost.json"
        ch, cd = d.get("champion") or {}, d.get(cand) or {}
        if ch.get("sec_per_game") and cd.get("sec_per_game"):
            out.append(row(f"費用 {cand} 比", src,
                           cd["sec_per_game"] / ch["sec_per_game"], d.get("ratio")))

    # ---- 覗き見監査 ---------------------------------------------------------
    d = _load_json(os.path.join(RESULTS, "vb", "c4_b75_audit.json"))
    if d is not None:
        out.append(row("覗き見監査 決定ノード", "results/vb/c4_b75_audit.json",
                       d.get("checked"), 120))
        out.append(row("覗き見監査 違反", "results/vb/c4_b75_audit.json",
                       d.get("violations"), 0))

    # ---- ラダー v13 ---------------------------------------------------------
    d = _load_json(os.path.join(RESULTS, "ladder_analysis_core5_v13.json"))
    if d is not None:
        src = "results/ladder_analysis_core5_v13.json"
        nash = d.get("nash") or {}
        w, na = nash.get("weights") or {}, nash.get("nA") or {}
        out.append(row("ラダー 台のサイズ", src, nash.get("support_size"),
                       len(nash.get("support") or [])))
        for nm in ("planner_vc4cps_kheb_b75", "planner_vc4cps_kheb"):
            out.append(row(f"ラダー {nm} p*", src, w.get(nm), None))
            out.append(row(f"ラダー {nm} nA", src, na.get(nm), None))
        # `champion_in_support` は v13 を回した**当時の** champion（`planner_vc4cps_kheb`）
        # について記録された値である。2026-09-13 の交代（D-082 追記 2）で champion は
        # `planner_vc4cps_kheb_b75` に替わったので、**この行の「champion」は現 champion ではない**。
        # 記録の値は動かない（動いたら記録のほうが壊れている）。
        out.append(row("ラダー v13 当時の champion が台に乗るか", src,
                       d.get("champion_in_support"), False))
        out.append(row("ラダー 非推移性（τ=0.60）", src,
                       len((d.get("cycles_by_tau") or {}).get("0.6") or []), 0))
        out.append(row("ラダー 有効多様性", src, d.get("effective_diversity"), None))
    return out


def _ci(p, n):
    if p is None or not n:
        return None
    return 1.96 * math.sqrt(p * (1 - p) / n)


def checks_K() -> list:
    """便 K（BP01 のカードデータ投入）。

    便 C までと違い、**測定ではなく構造の事実**を照合する（勝率の区間は出ない）。
    「保存されている値」は `results/k/manifest_K.json`、「再計算」は**実物から数え直した値**である:
    登録簿・`encode` の次元・`reconcile_cards` の突き合わせ・台帳の顔ぶれ・
    digest（`tests/test_bp01.py` と同じ作り方で n=500）・仮デッキのスモーク（1,000 局）。

    したがってこの節は「報告の数字が結果ファイルと合っているか」だけでなく、
    **いまのコードがその数字を再現するか**まで見る。合わなければ実装が動いたということである。
    """
    import hashlib

    sys.path.insert(0, os.path.join(_ROOT, "scripts"))
    import reconcile_cards                                          # noqa: E402
    from meicho.agents import RandomAgent                           # noqa: E402
    from meicho.cards import ACTION_CARDS, CHARA_CARDS              # noqa: E402
    from meicho.encode import ACT_DIM, ENCODING_VERSION, NA, NC, OBS_DIM  # noqa: E402
    from meicho.engine import (GameConfig, apply, decision_players,  # noqa: E402
                               initial_state, outcome)
    from meicho.heuristic import HeuristicAgent                     # noqa: E402
    from meicho.runner import play_game                             # noqa: E402
    import arena                                                    # noqa: E402

    src = "results/k/manifest_K.json"
    m = _load_json(os.path.join(RESULTS, "k", "manifest_K.json")) or {}
    out: list = []
    reg = {**CHARA_CARDS, **ACTION_CARDS}

    # --- 登録簿と符号化 ---
    out.append(row("登録簿 アクション", src, len(ACTION_CARDS), _dig(m, "registry.action")))
    out.append(row("登録簿 キャラ", src, len(CHARA_CARDS), _dig(m, "registry.chara")))
    out.append(row("符号化の版", src, ENCODING_VERSION, _dig(m, "encoding_version")))
    for k, v in (("NA", NA), ("NC", NC), ("OBS_DIM", OBS_DIM), ("ACT_DIM", ACT_DIM)):
        out.append(row(f"次元 {k}", src, v, _dig(m, f"dims.{k}")))

    # --- cards/ との突き合わせ ---
    problems = reconcile_cards.check(quiet=True)
    unreg = [c for c in reconcile_cards.load_cards_csv() if c not in reg]
    out.append(row("reconcile の食い違い", src, len(problems), _dig(m, "reconcile.problems")))
    out.append(row("未登録のカード", src, len(unreg), _dig(m, "reconcile.unregistered")))
    out.append(row("未掲載の枠", src, len(reconcile_cards.unlisted_codes()),
                   len(_dig(m, "unlisted_slots") or [])))

    # --- 台帳の顔ぶれ ---
    ledger_path = os.path.normpath(os.path.join(_ROOT, "..", "cards", "BP01_MECHANICS.md"))
    ledger = []
    if os.path.exists(ledger_path):
        with open(ledger_path, encoding="utf-8") as f:
            ledger = sorted({ln.split("`")[1] for ln in f if ln.startswith("| `BP01-")})
    out.append(row("台帳の番号", src, len(ledger) or None, _dig(m, "ledger.numbers")))
    out.append(row("うち効果あり", src,
                   sum(1 for c in ledger if reg[c].skills) if ledger else None,
                   _dig(m, "ledger.with_skills")))
    out.append(row("うちバニラ", src,
                   sum(1 for c in ledger if not reg[c].skills) if ledger else None,
                   _dig(m, "ledger.vanilla")))
    out.append(row("unverified のスキル", src,
                   sum(1 for c in reg.values() for sk in c.skills if sk.unverified),
                   _dig(m, "unverified_skills")))

    # --- digest（打ち方が動いていないこと）---
    def _key(a):
        return tuple(sorted((str(k), str(v)) for k, v in a.items()))

    def digest(deck, n, make):
        config = arena.mirror_config(arena.load_deck(deck))
        h = hashlib.sha256()
        for seed in range(n):
            ags = [make(seed * 2), make(seed * 2 + 1)]
            st = initial_state(config, seed)
            while outcome(st) is None and st.turn_no <= 200:
                need = decision_players(st)
                acts = {pi: ags[pi].act(st, pi) for pi in need}
                h.update(repr(sorted((pi, _key(a)) for pi, a in acts.items())).encode())
                st = apply(st, acts)
            h.update(f"|{outcome(st)}|{st.turn_no}|"
                     f"{st.players[0].life}|{st.players[1].life}|".encode())
        return h.hexdigest()[:16]

    for who, make in (("heuristic", HeuristicAgent), ("random", RandomAgent)):
        for deck in ("SD001", "SD02"):
            key = f"{who}/{deck}"
            out.append(row(f"digest n=500 {key}", src, digest(deck, 500, make),
                           _dig(m, f"digests_n500.{key}")))

    # --- 仮デッキのスモーク（Python・1,000 局）---
    # シードは帯 706000..708999（`experiments/seed_bands.json` に登録済み）。デッキごとの
    # 先頭は結果ファイルの `seed0` に書いてある。`scripts/smoke_bp01.py` と同じ並べ方でなければ
    # 同じ数字にならないので、ここで帯を決め打ちにしない。
    for name in sorted((_dig(m, "smoke") or {})):
        path = os.path.join(_ROOT, "decklists", f"{name}.json")
        if not os.path.exists(path):
            out.append(row(f"スモーク {name}", src, None, "デッキが無い"))
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        config = GameConfig(chara_decks=[d["chara_deck"]] * 2,
                            action_decks=[d["action_deck"]] * 2)
        base = _dig(m, f"smoke.{name}.seed0") or 0
        n = _dig(m, f"smoke.{name}.python.games") or 1000
        ab = dr = turns = 0
        for i in range(n):
            seed = base + i
            r = play_game(config, [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)], seed)
            ab += int(r["aborted"]); dr += int(r["draw"]); turns += r["turns"]
        out.append(row(f"スモーク {name} 打ち切り", src, ab,
                       _dig(m, f"smoke.{name}.python.aborted")))
        out.append(row(f"スモーク {name} 引き分け", src, dr,
                       _dig(m, f"smoke.{name}.python.draws")))
        out.append(row(f"スモーク {name} 平均ターン", src, round(turns / n, 2),
                       _dig(m, f"smoke.{name}.python.mean_turns")))
        # Python と Rust が同じ数字を出しているか（保存値どうしの照合）
        out.append(row(f"スモーク {name} 平均ターン Rust", src,
                       _dig(m, f"smoke.{name}.rust.mean_turns"),
                       _dig(m, f"smoke.{name}.python.mean_turns")))
    return out


CHECKS = {"C": checks_C, "A2": checks_A2, "K": checks_K}


def _fmt(x):
    if x is None:
        return "―"
    if isinstance(x, float):
        return f"{x:.6f}".rstrip("0").rstrip(".")
    return str(x)


def render(rows: list, name: str) -> str:
    if not rows:
        return f"（便 {name} の結果ファイルがまだ無い）"
    w = max(len(r["name"]) for r in rows)
    L = [f"■ 報告の数字の照合（便 {name}）",
         "  名前 | 出どころ | 再計算 | 保存値 | 判定", ""]
    bad = 0
    for r in rows:
        mark = {True: "一致", False: "**不一致**", None: "―"}[r["match"]]
        if r["match"] is False:
            bad += 1
        L.append(f"  {r['name'].ljust(w)} | {r['source']} | "
                 f"{_fmt(r['recomputed'])} | {_fmt(r['stored'])} | {mark}")
    L += ["", f"  行 {len(rows)}／不一致 {bad}"
              f"／再計算できない行 {sum(1 for r in rows if r['match'] is None)}"]
    if bad:
        L.append("  **不一致がある。報告を書く前に直すこと。**")
    return "\n".join(L)


def main(argv=None) -> int:
    # D-082 追記 1: この道具は**マスターの PC でも回す**（`TASKS.md` の展開手順）。
    # 出力には `≥` や `₁` が入っていて cp932 では書けないので、パイプやファイルに
    # 向けると日本語 Windows で落ちる。表示だけ UTF-8 に寄せる（数字は変えない）。
    from console import use_utf8_console
    use_utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("bin", nargs="?", default="C", help="便の名前（C など）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.bin not in CHECKS:
        raise SystemExit(f"知らない便: {args.bin}（{sorted(CHECKS)}）")
    rows = CHECKS[args.bin]()
    if args.json:
        print(json.dumps({"bin": args.bin, "rows": rows}, ensure_ascii=False, indent=1))
    else:
        print(render(rows, args.bin))
    return 1 if any(r["match"] is False for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
