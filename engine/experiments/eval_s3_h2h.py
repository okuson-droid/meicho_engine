"""段階3 反復 1 の診断の直接対決（0 番・1-b・5-b・D-144 追記 3・比較書 §4 の 2・Cowork 版 §4）。

    python3 experiments/eval_s3_h2h.py run --pair ch=results/models/s3v1_id_ens3.json:results/models/s2v_id_ens3.json \
        --pair null=results/models/s2v_id_ens3.json:results/models/s2v_id_ens3.json \
        --n 75 --seed0 859000 --out results/drl/s3_diag_h2h.json
    python3 experiments/eval_s3_h2h.py report --in results/drl/s3_diag_h2h.json --challenge ch --null null

## 課題（回す前に固定・Cowork 版 §4）

- デッキは調整（tune）の 4 つ。順序つきの組 16 ブロック（ミラー 4＋異種 12）。各ブロック n 局・全ブロック・全組で同じシード
- 組（pair）は「A 席の V : B 席の V」。両席とも探索器は `record_mix.NETFREE`（τ = 0）に葉の V を挿したもの
- `series` は奇数シードで A/B の席を入れ替え、デッキは席に固定なので、A は偶数シードで deck_a、奇数シードで deck_b を持つ
- 挑戦（V_1 : V_0）と null（V_0 : V_0）を同じシードで回し、局ごとに対にする
- 得点は A 席から見て勝 1・引き分け 0.5・負 0

## 判定の規則（回す前に固定・Cowork 版 §4）

- 主比較: 局ごとの差 d = 挑戦の A の得点 − null の A の得点（同じブロック・同じシード）。ブロックの中で局を再標本化
  （10,000 回）し、**16 ブロック等重み**で平均した 95% 区間
- 下端 > +0.01 → 「伸びていた」（物差しの問題が主因の候補・止めて相談）／−0.01 ≤ 下端 ≤ +0.01 → 「境界」（別帯で追試）／
  下端 < −0.01 → 「伸びていない」（項目 1 へ）
- 0 番で物差しを替えることになっても、使うのは次の反復からで、使う前に新しい帯で確かめの測定を 1 回挟む（比較書 §7-3）
- 添えるもの: 挑戦と null の生の勝率と区間（null の区間が 0.5 を含まなければ配線を疑って止める）、A のデッキ別の d、
  「挑戦だけ勝った／null だけ勝った」の局数

## 門 T（段階4 便 4-A4・D-161）

- `--target D` を付けると、そのデッキのミラー 1 ブロックだけを回す（既定は調整デッキ 4 つの 16 ブロック）。
  最終評価のデッキは落とす
- 組の片側に `netfree` と書くと、その席は葉の V を持たない `record_mix.NETFREE` そのものになる。
  `netfree_b` は予算を増やした netfree（`solo_samples` 4 → 16・`endgame_enum` 64 → 256・設計書 §2.2 の T-b）
- `report --gate 組` は、その組の A 席の得点と 95% 区間（局の組 (2k, 2k+1) を単位に 10,000 回）と、
  「下端 > 0.5 → 門を越える」を出す（挑戦と null の対は作らない）

## 壁を越える案（D-163・設計書 `GENERALIST_WALL_DESIGN_20261006.md` §5.1）

- `report --rule wall --level 0.983` は、主比較の区間を 98.3%（V の腕の家族・1 − 0.05/3）で出し、0 を基準に判定する:
  下端 > 0 → 伸びた／上端 < 0 → 悪くなった／点推定 > 0 で 0 をまたぐ → 境界（新しい帯で 16 × 150 を 1 回だけ追試）／
  それ以外 → 伸びていない。生の得点と null の 0.5 の確かめは 95% のまま。既定（`--rule s3`）は従来とバイトで同じ

- 腕 A（D-163 §2.1）: 席を `葉の V のパス+pi=代打ちの π のパス` と書くと、その席は `record_mix.NETFREE_VP`
  （代打ちだけ π・`policy_belief` オン・π₀ は H）を足した探索器になる。指紋は `V の指紋+pi=π の指紋`

## 局数の足し継ぎ

- 同じ `--out` に大きい `--n` で打ち直すと、各ブロックの足りない局だけを回して後ろに足す（`eval_s2_repr.py` と同じ作法）
- **挑戦と null は同じ `--out` に入れる**（別の `--out` の組を取り込む口は無い）。0 番の null を 1-b・5-b で使い回すときは、
  同じ `--out` に別名の `--pair` で足す（同じシード・同じデッキなので、既にある組は回し直さない）。同じファイルの中なので
  シードとデッキは構造上そろい、`report` は B 席の V の指紋と局数を確かめる
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from eval_s2_repr import DEFAULT_ENV, blocks, cand_deck, check_eval_band, ci_percentiles, load_env, tune_decks   # noqa: E402

TOOL_VERSION = "s3h2h-1"
RULE = {"up": 0.01, "down": -0.01}


def sha16(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


NETFREE_SIDE = "netfree"               # 組の片側に書くと葉の V なしの NETFREE（D-161）
NETFREE_B_SIDE = "netfree_b"           # 予算を増やした netfree（設計書 §2.2 の T-b・D-161）
NETFREE_B = {"solo_samples": 16, "endgame_enum": 256}


PI_SEP = "+pi="                         # 腕 A（D-163 §2.1）: 「葉の V のパス+pi=代打ちの π のパス」


def split_side(text: str) -> tuple:
    """席の指定を (葉の V, 代打ちの π または None) に分ける。π は `record_mix.NETFREE_VP`（proxy・policy_belief）。"""
    v, sep, pi = text.partition(PI_SEP)
    if sep and (not pi or v in (NETFREE_SIDE, NETFREE_B_SIDE)):
        raise SystemExit(f"代打ちの π は葉の V のある席にだけ付ける（V のパス{PI_SEP}π のパス）: {text!r}")
    return v, (pi or None)


def side_sha(path: str):
    v, pi = split_side(path)
    if v in (NETFREE_SIDE, NETFREE_B_SIDE):
        return None
    return sha16(v) if pi is None else f"{sha16(v)}+pi={sha16(pi)}"


def parse_pair(text: str) -> tuple:
    name, _, rest = text.partition("=")
    a, sep, b = rest.partition(":")
    if not (name and sep and a and b):
        raise SystemExit(f"--pair は 名前=A席のV:B席のV の形: {text!r}")
    return name, a, b


def _spec(path: str, pool: list) -> dict:
    from arena_rs import PLANNER
    from record_mix import NETFREE
    if path == NETFREE_SIDE:
        return PLANNER(pool, **NETFREE)
    if path == NETFREE_B_SIDE:
        return PLANNER(pool, **dict(NETFREE, **NETFREE_B))
    from record_mix import NETFREE_VP
    v, pi = split_side(path)
    extra = NETFREE_VP(os.path.abspath(pi)) if pi else {}
    return PLANNER(pool, **NETFREE, value_net=os.path.abspath(v), **extra)


def target_decks(target: str, env: dict) -> list:
    """門 T の 1 ブロック（そのデッキのミラー）。最終評価のデッキは開けない（D-153 追記 1）。"""
    from eval_s2_repr import resolve_deck
    full = resolve_deck(target)
    key = full[len("env/"):] if full.startswith("env/") else full
    if env["decks_block"].get(key, {}).get("split") == "final":
        raise SystemExit(f"--target {target} は最終評価のデッキ（開けない）")
    return [full]


def run(args, decks: list | None = None) -> dict:
    """`decks` は検査だけが渡す（既定は調整デッキ 4 つ）。"""
    import meicho_rs as rs
    from arena import load_deck, matchup_config
    from arena_rs import ensure_cards
    check_eval_band(args.seed0, args.n)
    ensure_cards()
    if decks is None and getattr(args, "target", None):
        decks = target_decks(args.target, load_env(args.env))
    decks = decks or tune_decks(load_env(args.env))
    data = {"version": TOOL_VERSION, "decision": "D-144 追記 3", "decks": decks, "n": args.n, "seed0": args.seed0,
            "pairs": {}, "results": {}}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            data = json.load(f)
        if (data["seed0"], data["decks"]) != (args.seed0, decks):
            raise SystemExit(f"条件が違う（seed0 {data['seed0']} → {args.seed0}・decks {data['decks']} → {decks}）。"
                             f"別の --out に")
        if data["n"] > args.n:
            raise SystemExit("局数を減らして打ち直さない（別の --out に）")
        data["n"] = args.n
    pairs = {}
    for text in args.pair:
        name, a, b = parse_pair(text)
        rec = {"a": {"path": a, "sha": side_sha(a)}, "b": {"path": b, "sha": side_sha(b)}}
        prev = data["pairs"].get(name)
        if prev is not None and (prev["a"]["sha"], prev["b"]["sha"]) != (rec["a"]["sha"], rec["b"]["sha"]):
            raise SystemExit(f"組 {name} のネットが前回と違う。別の名前にすること")
        data["pairs"][name] = rec
        pairs[name] = (a, b)
    t0 = time.time()
    for name, (pa, pb) in pairs.items():
        for da_name, db_name in blocks(decks):
            key = f"{name}|{da_name}|{db_name}"
            have = len(data["results"].get(key, []))
            if have >= args.n:
                continue
            if time.time() - t0 > args.budget_sec:
                print(f"予算 {args.budget_sec} 秒を超えたので止める（続きは同じコマンドで再開）")
                return data
            da, db = load_deck(da_name), load_deck(db_name)
            cfg = matchup_config(da, db)
            cfg.validate()
            t = time.time()
            # A の相手のデッキ表は席で決まる（opp_from_seat=True が局ごとに差し替える・D-123）
            res = rs.series(cfg.chara_decks, cfg.action_decks, _spec(pa, db["action_deck"]),
                            _spec(pb, da["action_deck"]), args.seed0 + have, args.n - have, args.workers, 200, True)
            data["results"][key] = data["results"].get(key, []) + \
                [[(0.5 if r[0] is None else float(bool(r[0]))), int(r[1])] for r in res]
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"{key}: {time.time() - t:.0f} 秒・A の得点 {np.mean([x[0] for x in data['results'][key]]):.3f}",
                  flush=True)
    return data


def check_paired(data: dict, ch: str, nl: str) -> None:
    """挑戦と null を対にしてよいかを確かめる。同じシード・デッキ・局数で、B 席の V が同じであること。"""
    for p in (ch, nl):
        if p not in data["pairs"]:
            raise SystemExit(f"組 {p} が無い")
    if data["pairs"][ch]["b"]["sha"] != data["pairs"][nl]["b"]["sha"]:
        raise SystemExit(f"挑戦 {ch} と null {nl} で B 席の V が違う"
                         f"（{data['pairs'][ch]['b']['sha']} / {data['pairs'][nl]['b']['sha']}）")
    for a, b in blocks(data["decks"]):
        for p in (ch, nl):
            got = len(data["results"].get(f"{p}|{a}|{b}", []))
            if got != data["n"]:
                raise SystemExit(f"{p}|{a}|{b} の局数 {got} が n = {data['n']} と違う（足し継ぎの途中）")


def paired_blocks(d_by_block: list, n_boot: int = 10000, seed: int = 0, level: float = 0.95) -> dict:
    """ブロックごとの局の差の列から、ブロック内で局を再標本化・ブロック等重みで平均した差と区間（既定 95%）。"""
    rng = np.random.RandomState(seed)
    boots = np.zeros(n_boot)
    for d in d_by_block:
        d = np.asarray(d, float)
        boots += d[rng.randint(0, len(d), size=(n_boot, len(d)))].mean(1)
    boots /= len(d_by_block)
    lo, hi = np.percentile(boots, ci_percentiles(level))
    return {"diff": float(np.mean([np.mean(d) for d in d_by_block])), "lo": float(lo), "hi": float(hi)}


def verdict(lo: float) -> str:
    if lo > RULE["up"]:
        return "伸びていた（止めて相談）"
    if lo < RULE["down"]:
        return "伸びていない（項目 1 へ）"
    return "境界（別帯で追試）"


def verdict_wall(diff: float, lo: float, hi: float, retest: bool = False) -> str:
    """壁を越える案（D-163・設計書 §5.1）の判定。0 を基準に、下端・上端・点推定で読む。
    `retest`（境界のあとの追試）は追試だけで判定する: 下端 > 0 で伸びた・それ以外は伸びていない。"""
    if retest:
        return "伸びた" if lo > 0 else "伸びていない"
    if lo > 0:
        return "伸びた"
    if hi < 0:
        return "悪くなった"
    if diff > 0:
        return "境界（新しい帯で 16 × 150 を 1 回だけ追試し、追試だけで判定）"
    return "伸びていない"


def report(data: dict, ch: str, nl: str, n_boot: int = 10000, rule: str = "s3", level: float = 0.95,
           retest: bool = False) -> dict:
    """`rule="s3"`（既定）は段階3 の判定（±0.01・95%）。`rule="wall"` は D-163 §5.1 の判定で、
    主比較の区間だけを `level`（V の腕は 98.3%）で出す（生の得点と null の 0.5 の確かめは 95% のまま）。"""
    if rule not in ("s3", "wall"):
        raise SystemExit(f"未対応の --rule: {rule!r}")
    if rule == "s3" and (level != 0.95 or retest):
        raise SystemExit("--level と --retest は --rule wall のときだけ使う")
    check_paired(data, ch, nl)
    seeds = data.get("seeds") or [data["seed0"] + i for i in range(data["n"])]
    d_blocks, rows = [], []
    for a, b in blocks(data["decks"]):
        sc = np.array([x[0] for x in data["results"][f"{ch}|{a}|{b}"]])
        sn = np.array([x[0] for x in data["results"][f"{nl}|{a}|{b}"]])
        d_blocks.append(sc - sn)
        for i in range(data["n"]):
            deck, seat = cand_deck(a, b, seeds[i])
            rows.append((deck, seat, sc[i], sn[i]))
    main = paired_blocks(d_blocks, n_boot, level=level)
    v = verdict(main["lo"]) if rule == "s3" else verdict_wall(main["diff"], main["lo"], main["hi"], retest)
    out = {"version": TOOL_VERSION, "challenge": ch, "null": nl, "n_per_block": data["n"],
           "n_games": len(rows), "main": dict(main, verdict=v), "raw": {}, "by_deck": {}}
    if rule == "wall":
        out["rule"], out["level"] = "wall", level
        if retest:
            out["retest"] = True
    for p, col in ((ch, 2), (nl, 3)):
        r = paired_blocks([[x[col] for x in rows[k * data["n"]:(k + 1) * data["n"]]] for k in range(len(d_blocks))],
                          n_boot)
        out["raw"][p] = {"score": r["diff"], "lo": r["lo"], "hi": r["hi"]}
    out["raw"][nl]["contains_half"] = out["raw"][nl]["lo"] <= 0.5 <= out["raw"][nl]["hi"]
    for deck in sorted({x[0] for x in rows}):
        sub = [x for x in rows if x[0] == deck]
        d = np.array([x[2] - x[3] for x in sub])
        out["by_deck"][deck] = {"n": len(sub), "diff": float(d.mean()),
                                "challenge_only": int((d > 0).sum()), "null_only": int((d < 0).sum())}
    return out


def merge_runs(datas: list, ch: str, nl: str | None) -> dict:
    """足し継ぎの追試（D-169）: 別々の帯で回した同じ組の結果を 1 つにまとめる。デッキ・組の指紋が同じで、
    シードが重ならないことを確かめ、ブロックごとに局を後ろへつなぐ（`seeds` に局ごとのシードを持つ）。"""
    if len(datas) == 1:
        return datas[0]
    base = datas[0]
    seeds = []
    out = {"version": TOOL_VERSION, "decks": base["decks"], "pairs": {}, "results": {}, "n": 0,
           "seed0": None, "merged_from": []}
    names = [ch] if nl is None else [ch, nl]
    for d in datas:
        if nl is not None:
            check_paired(d, ch, nl)
        if d["decks"] != base["decks"]:
            raise SystemExit("足し継ぐ結果のデッキが違う")
        for p in names:
            if (d["pairs"][p]["a"]["sha"], d["pairs"][p]["b"]["sha"]) != \
                    (base["pairs"][p]["a"]["sha"], base["pairs"][p]["b"]["sha"]):
                raise SystemExit(f"足し継ぐ結果で組 {p} のネットが違う")
            out["pairs"][p] = base["pairs"][p]
        s = [d["seed0"] + i for i in range(d["n"])]
        if set(s) & set(seeds):
            raise SystemExit("足し継ぐ結果のシードが重なる")
        seeds += s
        for a, b in blocks(d["decks"]):
            for p in names:
                got = d["results"].get(f"{p}|{a}|{b}", [])
                if len(got) != d["n"]:
                    raise SystemExit(f"{p}|{a}|{b} の局数 {len(got)} が n = {d['n']} と違う（足し継ぎの途中）")
                out["results"].setdefault(f"{p}|{a}|{b}", []).extend(got)
        out["n"] += d["n"]
        out["merged_from"].append({"seed0": d["seed0"], "n": d["n"]})
    out["seeds"] = seeds
    return out


def direct_score(data: dict, ch: str, level: float = 0.95, n_boot: int = 10000, seed: int = 0) -> dict:
    """添える（D-169・判定には使わない）: 挑戦の A 席の得点 − 0.5（null を引かない）。局の組 (2k, 2k+1) を単位に
    ブロックの中で再標本化・ブロック等重み。"""
    rng = np.random.RandomState(seed)
    boots, means = np.zeros(n_boot), []
    for a, b in blocks(data["decks"]):
        sc = np.array([x[0] for x in data["results"][f"{ch}|{a}|{b}"]], float)
        pairs = sc[:len(sc) - len(sc) % 2].reshape(-1, 2).mean(1)
        boots += pairs[rng.randint(0, len(pairs), size=(n_boot, len(pairs)))].mean(1)
        means.append(sc.mean())
    boots /= len(means)
    lo, hi = np.percentile(boots, ci_percentiles(level))
    return {"diff": float(np.mean(means) - 0.5), "lo": float(lo - 0.5), "hi": float(hi - 0.5), "level": level}


RULE_DIRECT = {"futility": 0.02}


def verdict_direct(diff: float, lo: float, hi: float) -> str:
    """D-170 の判定: 下端 > 0 → 伸びた／上端 < 0 → 悪くなった／上端 < +0.02 → 区別できない（+2% 以上は否定）／
    それ以外 → 区別できない（上端 … は否定できない・D-169 の足し継ぎを続ける）。"""
    if lo > 0:
        return "伸びた"
    if hi < 0:
        return "悪くなった"
    if hi < RULE_DIRECT["futility"]:
        return "区別できない（+2% 以上の改善は否定）"
    return f"区別できない（上端 {hi:+.3f} は否定できない・足し継ぐ）"


def report_direct(data: dict, ch: str, level: float, null_data: dict | None = None, nl: str = "null") -> dict:
    """D-170 の主比較: 挑戦の A 席の得点 − 0.5（null を引かない）。null は配線の確かめ（95% 区間が 0.5 を含むか）。"""
    for a, b in blocks(data["decks"]):
        if len(data["results"].get(f"{ch}|{a}|{b}", [])) != data["n"]:
            raise SystemExit(f"{ch}|{a}|{b} の局数が n = {data['n']} と違う（足し継ぎの途中）")
    m = direct_score(data, ch, level=level)
    out = {"version": TOOL_VERSION, "rule": "direct", "decision": "D-170", "challenge": ch, "level": level,
           "n_per_block": data["n"], "n_games": data["n"] * len(blocks(data["decks"])),
           "pair": data["pairs"][ch], "main": dict(m, verdict=verdict_direct(m["diff"], m["lo"], m["hi"])),
           "by_block": {f"{a}|{b}": float(np.mean([x[0] for x in data["results"][f"{ch}|{a}|{b}"]]) - 0.5)
                        for a, b in blocks(data["decks"])}}
    if data.get("merged_from"):
        out["merged_from"] = data["merged_from"]
    if null_data is not None:
        w = direct_score(null_data, nl, level=0.95)
        if null_data["pairs"][nl]["b"]["sha"] != data["pairs"][ch]["b"]["sha"]:
            raise SystemExit("null の B 席の V が挑戦と違う")
        out["null"] = dict(w, n_games=null_data["n"] * len(blocks(null_data["decks"])),
                           contains_half=bool(w["lo"] <= 0 <= w["hi"]))
    return out


def gate(data: dict, name: str, n_boot: int = 10000, seed: int = 0) -> dict:
    """門 T: 組 `name` の A 席の得点と 95% 区間（局の組を単位・ブロック等重み）。下端 > 0.5 → 門を越える。"""
    if name not in data["pairs"]:
        raise SystemExit(f"組 {name} が無い")
    rng = np.random.RandomState(seed)
    boots, means, n_games = np.zeros(n_boot), [], 0
    for a, b in blocks(data["decks"]):
        sc = np.array([x[0] for x in data["results"].get(f"{name}|{a}|{b}", [])], float)
        if len(sc) != data["n"]:
            raise SystemExit(f"{name}|{a}|{b} の局数 {len(sc)} が n = {data['n']} と違う（足し継ぎの途中）")
        pairs = sc[:len(sc) - len(sc) % 2].reshape(-1, 2).mean(1)
        boots += pairs[rng.randint(0, len(pairs), size=(n_boot, len(pairs)))].mean(1)
        means.append(sc.mean())
        n_games += len(sc)
    boots /= len(means)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"version": TOOL_VERSION, "gate": name, "pair": data["pairs"][name], "n_games": n_games,
            "score": float(np.mean(means)), "lo": float(lo), "hi": float(hi),
            "verdict": "門を越える" if lo > 0.5 else "門を越えない（止めて相談）"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--pair", action="append", required=True)
    r.add_argument("--n", type=int, required=True)
    r.add_argument("--seed0", type=int, required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--budget-sec", type=float, default=480.0)
    r.add_argument("--env", default=DEFAULT_ENV)
    r.add_argument("--target", default=None, help="門 T（D-161）: このデッキのミラー 1 ブロックだけを回す")
    p = sub.add_parser("report")
    p.add_argument("--in", dest="inp", required=True, action="append",
                   help="結果のファイル。2 つ以上渡すと足し継ぎの追試として合わせる（D-169）")
    p.add_argument("--challenge", default=None)
    p.add_argument("--null", default=None)
    p.add_argument("--gate", default=None, help="門 T（D-161）: この組の A 席の得点と「下端 > 0.5」")
    p.add_argument("--out", default=None)
    p.add_argument("--rule", default="s3", choices=["s3", "wall"],
                   help="wall = 壁を越える案（D-163 §5.1）の判定（0 を基準・主比較の区間は --level）")
    p.add_argument("--level", type=float, default=0.95, help="--rule wall の主比較の区間の水準（V の腕は 0.983）")
    p.add_argument("--retest", action="store_true", help="--rule wall: 境界のあとの追試（追試だけで判定・§5.1）")
    p.add_argument("--direct", default=None,
                   help="D-170: この組の挑戦の得点 − 0.5 で判定（null を引かない）。--in を複数渡すと足し継ぐ")
    p.add_argument("--null-in", default=None, help="--direct: 配線の確かめの null の結果（組 null・0.5 を含むか）")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return run(args)
    datas = []
    for path in args.inp:
        with open(path, encoding="utf-8") as f:
            datas.append(json.load(f))
    data = datas[0]
    if args.direct:
        data = merge_runs(datas, args.direct, None) if len(datas) > 1 else data
        nd = json.load(open(args.null_in, encoding="utf-8")) if args.null_in else None
        out = report_direct(data, args.direct, args.level, nd)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
        return out
    if args.gate:
        out = gate(data, args.gate)
    else:
        if not (args.challenge and args.null):
            raise SystemExit("report には --challenge と --null（または --gate）が要る")
        if len(datas) > 1:
            data = merge_runs(datas, args.challenge, args.null)
        out = report(data, args.challenge, args.null, rule=args.rule, level=args.level, retest=args.retest)
        if len(datas) > 1:
            out["merged_from"] = data["merged_from"]
            out["direct"] = direct_score(data, args.challenge, level=args.level)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    main()
