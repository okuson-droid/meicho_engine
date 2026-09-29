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

from eval_s2_repr import DEFAULT_ENV, blocks, cand_deck, check_eval_band, load_env, tune_decks   # noqa: E402

TOOL_VERSION = "s3h2h-1"
RULE = {"up": 0.01, "down": -0.01}


def sha16(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def parse_pair(text: str) -> tuple:
    name, _, rest = text.partition("=")
    a, sep, b = rest.partition(":")
    if not (name and sep and a and b):
        raise SystemExit(f"--pair は 名前=A席のV:B席のV の形: {text!r}")
    return name, a, b


def _spec(path: str, pool: list) -> dict:
    from arena_rs import PLANNER
    from record_mix import NETFREE
    return PLANNER(pool, **NETFREE, value_net=os.path.abspath(path))


def run(args, decks: list | None = None) -> dict:
    """`decks` は検査だけが渡す（既定は調整デッキ 4 つ）。"""
    import meicho_rs as rs
    from arena import load_deck, matchup_config
    from arena_rs import ensure_cards
    check_eval_band(args.seed0, args.n)
    ensure_cards()
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
        rec = {"a": {"path": a, "sha": sha16(a)}, "b": {"path": b, "sha": sha16(b)}}
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


def paired_blocks(d_by_block: list, n_boot: int = 10000, seed: int = 0) -> dict:
    """ブロックごとの局の差の列から、ブロック内で局を再標本化・ブロック等重みで平均した差と 95% 区間。"""
    rng = np.random.RandomState(seed)
    boots = np.zeros(n_boot)
    for d in d_by_block:
        d = np.asarray(d, float)
        boots += d[rng.randint(0, len(d), size=(n_boot, len(d)))].mean(1)
    boots /= len(d_by_block)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"diff": float(np.mean([np.mean(d) for d in d_by_block])), "lo": float(lo), "hi": float(hi)}


def verdict(lo: float) -> str:
    if lo > RULE["up"]:
        return "伸びていた（止めて相談）"
    if lo < RULE["down"]:
        return "伸びていない（項目 1 へ）"
    return "境界（別帯で追試）"


def report(data: dict, ch: str, nl: str, n_boot: int = 10000) -> dict:
    check_paired(data, ch, nl)
    d_blocks, rows = [], []
    for a, b in blocks(data["decks"]):
        sc = np.array([x[0] for x in data["results"][f"{ch}|{a}|{b}"]])
        sn = np.array([x[0] for x in data["results"][f"{nl}|{a}|{b}"]])
        d_blocks.append(sc - sn)
        for i in range(data["n"]):
            deck, seat = cand_deck(a, b, data["seed0"] + i)
            rows.append((deck, seat, sc[i], sn[i]))
    main = paired_blocks(d_blocks, n_boot)
    out = {"version": TOOL_VERSION, "challenge": ch, "null": nl, "n_per_block": data["n"],
           "n_games": len(rows), "main": dict(main, verdict=verdict(main["lo"])), "raw": {}, "by_deck": {}}
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
    p = sub.add_parser("report")
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--challenge", required=True)
    p.add_argument("--null", required=True)
    p.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return run(args)
    with open(args.inp, encoding="utf-8") as f:
        data = json.load(f)
    out = report(data, args.challenge, args.null)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    main()
