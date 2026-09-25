"""段階2 の表現比較の評価（計画書 `GENERALIST_AI_REVIEW_D086.md` §6 段階2・§7・D-132）。

    python3 experiments/eval_s2_repr.py run --arm v_id=/path/s2v_id_s0.json --arm v_pf=/path/s2v_pf_s0.json \
        --arm netfree --n 300 --seed0 841000 --out results/drl/s2_repr_eval_v1.json
    python3 experiments/eval_s2_repr.py report --in results/drl/s2_repr_eval_v1.json --new v_pf --old v_id

## 課題（回す前に固定・D-132）

- デッキは**調整（tune）の 4 つだけ**（`env_v1.json`）。最終評価の 4 つはここでは開けない（計画書 §6 段階3）
- 順序つきの組 16 ブロック（ミラー 4＋異種 12）。各ブロック n 局・**全ブロック・全候補で同じシード**
- 候補は A 席、相手は**素の計画探索（素 planner）**。`series` は奇数シードで A/B の席を入れ替え、デッキは席に
  固定なので、候補は偶数シードで deck_a（席 0）、奇数シードで deck_b（席 1）を持つ。16 ブロックで
  **どのデッキも 4n 局ずつ・席 0 と席 1 を半分ずつ**持つ（E-1）
- 候補の探索器は教師と同じ `record_mix.NETFREE`。V の候補はそこに `value_net` を足しただけ（葉を V にする）
- 得点は勝 1・引き分け 0.5・負 0（計画書 §7.1）

## 読み方（事前に固定）

- 主比較: 候補 new と old の**同じ（ブロック・シード）の局どうしの得点差**を、デッキの中で局ごとに再標本化して
  デッキ等重みで平均する（計画書 §7.3 の対ブートストラップ・10,000 回）。**95% 区間の下端 > 0 なら new を採る**。
  0 をまたげば未判定（通るまで追試しない）
- 各候補の対 素 planner の得点（デッキ等重み）も区間つきで出す（診断）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

DEFAULT_ENV = os.path.join(_HERE, "..", "results", "decksim", "env_v1.json")
TOOL_VERSION = "s2eval-1"


def load_env(path: str = DEFAULT_ENV) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def tune_decks(env: dict | None = None) -> list:
    env = env or load_env()
    return sorted(f"env/{k}" for k, v in env["decks_block"].items() if v["split"] == "tune")


def blocks(decks: list) -> list:
    return [(a, b) for a in decks for b in decks]


def cand_deck(deck_a: str, deck_b: str, seed: int) -> tuple:
    """候補（A）がその局で持つデッキと席。席 0 = deck_a。偶数シードは A が席 0。"""
    return (deck_a, 0) if seed % 2 == 0 else (deck_b, 1)


def check_eval_band(seed0: int, n: int) -> None:
    """評価の帯（kind=validate）の中だけで回す。未登録・学習の帯は落とす（D-028・D-058）。"""
    with open(os.path.join(_HERE, "seed_bands.json"), encoding="utf-8") as f:
        led = json.load(f)
    for s in (seed0, seed0 + n - 1):
        hit = [b for b in led["bands"] if b["start"] <= s <= b["end"]]
        if not hit:
            raise SystemExit(f"帯 {s} は seed_bands.json に未登録。台帳に追記してから使うこと（D-028）")
        if hit[0].get("kind") != "validate":
            raise SystemExit(f"帯 {hit[0]['start']}..{hit[0]['end']} は kind={hit[0].get('kind')}。"
                             f"評価には kind=validate の帯を使う")


def paired_diff(games: list, new: list, old: list, n_boot: int = 10000, seed: int = 0) -> dict:
    """同じ局どうしの得点差を、デッキ内で局を再標本化・デッキ等重みで平均した差と 95% 区間。"""
    d = np.asarray(new, float) - np.asarray(old, float)
    decks = sorted({g["deck"] for g in games})
    idx = {k: np.array([i for i, g in enumerate(games) if g["deck"] == k]) for k in decks}
    diff = float(np.mean([d[idx[k]].mean() for k in decks]))
    rng = np.random.RandomState(seed)
    boots = np.zeros(n_boot)
    for k in decks:
        dk = d[idx[k]]
        boots += dk[rng.randint(0, len(dk), size=(n_boot, len(dk)))].mean(1)
    boots /= len(decks)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    by_deck = {k: {"n": int(len(idx[k])), "diff": float(d[idx[k]].mean()),
                   "new_only": int((d[idx[k]] > 0).sum()), "old_only": int((d[idx[k]] < 0).sum())}
               for k in decks}
    return {"diff": diff, "lo": float(lo), "hi": float(hi), "n_games": int(len(d)), "by_deck": by_deck}


def score_ci(games: list, s: list, n_boot: int = 10000, seed: int = 0) -> dict:
    """デッキ等重みの平均得点と 95% 区間（局を再標本化）。"""
    zero = [0.0] * len(s)
    r = paired_diff(games, s, zero, n_boot, seed)
    return {"score": r["diff"], "lo": r["lo"], "hi": r["hi"],
            "by_deck": {k: v["diff"] for k, v in r["by_deck"].items()}}


def _arm_spec(arm: str, path: str | None, pool: list) -> dict:
    from arena_rs import PLANNER
    from record_mix import NETFREE
    extra = {"value_net": os.path.abspath(path)} if path else {}
    return PLANNER(pool, **NETFREE, **extra)


def run(args) -> dict:
    import meicho_rs as rs
    from arena import load_deck, matchup_config
    from arena_rs import PLANNER, ensure_cards
    check_eval_band(args.seed0, args.n)
    ensure_cards()
    env = load_env(args.env)
    decks = tune_decks(env)
    arms = {}
    for a in args.arm:
        name, _, path = a.partition("=")
        arms[name] = path or None
    data = {"version": TOOL_VERSION, "decision": "D-132", "decks": decks, "n": args.n, "seed0": args.seed0,
            "opponent": "planner", "arms": {}, "results": {}}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            data = json.load(f)
        assert (data["n"], data["seed0"], data["decks"]) == (args.n, args.seed0, decks), "条件が違う（別の --out に）"
    import hashlib
    for name, path in arms.items():
        fp = hashlib.sha256(open(path, "rb").read()).hexdigest()[:16] if path else None
        prev = data["arms"].get(name)
        if prev is not None and prev["sha"] != fp:
            raise SystemExit(f"候補 {name} のネットが前回と違う（{prev['sha']} → {fp}）。別の名前にすること")
        data["arms"][name] = {"path": path, "sha": fp}
    t0 = time.time()
    for name, path in arms.items():
        for a, b in blocks(decks):
            key = f"{name}|{a}|{b}"
            if key in data["results"]:
                continue
            if time.time() - t0 > args.budget_sec:
                print(f"予算 {args.budget_sec} 秒を超えたので止める（続きは同じコマンドで再開）")
                return data
            da, db = load_deck(a), load_deck(b)
            cfg = matchup_config(da, db)
            cfg.validate()
            t = time.time()
            res = rs.series(cfg.chara_decks, cfg.action_decks, _arm_spec(name, path, db["action_deck"]),
                            PLANNER(da["action_deck"]), args.seed0, args.n, args.workers, 200, True)
            data["results"][key] = [[(0.5 if r[0] is None else float(bool(r[0]))), int(r[1])] for r in res]
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"{key}: {time.time() - t:.0f} 秒・得点 {np.mean([x[0] for x in data['results'][key]]):.3f}",
                  flush=True)
    return data


def games_of(data: dict) -> list:
    out = []
    for a, b in blocks(data["decks"]):
        for i in range(data["n"]):
            s = data["seed0"] + i
            deck, seat = cand_deck(a, b, s)
            out.append({"block": f"{a}|{b}", "seed": s, "deck": deck, "seat": seat, "i": i})
    return out


def scores_of(data: dict, arm: str) -> list:
    return [data["results"][f"{arm}|{g['block']}"][g["i"]][0] for g in games_of(data)]


def report(args) -> dict:
    with open(args.inp, encoding="utf-8") as f:
        data = json.load(f)
    games = games_of(data)
    arms = [a for a in data["arms"] if all(f"{a}|{x}|{y}" in data["results"] for x, y in blocks(data["decks"]))]
    out = {"version": TOOL_VERSION, "n_per_block": data["n"], "decks": data["decks"],
           "scores": {a: score_ci(games, scores_of(data, a)) for a in arms}, "compare": {}}
    pairs = [(args.new, args.old)] + [tuple(p.split(":")) for p in (args.also or [])]
    for new, old in pairs:
        if new in arms and old in arms:
            out["compare"][f"{new}-{old}"] = paired_diff(games, scores_of(data, new), scores_of(data, old))
    path = args.out or args.inp.replace(".json", "_report.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"scores": {a: [round(v["score"], 4), round(v["lo"], 4), round(v["hi"], 4)]
                                 for a, v in out["scores"].items()},
                      "compare": {k: [round(v["diff"], 4), round(v["lo"], 4), round(v["hi"], 4)]
                                  for k, v in out["compare"].items()}}, ensure_ascii=False))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--env", default=DEFAULT_ENV)
    r.add_argument("--arm", action="append", required=True, help="名前=ネットのパス（パス無しは netfree）")
    r.add_argument("--n", type=int, default=300)
    r.add_argument("--seed0", type=int, required=True)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--budget-sec", type=float, default=450.0)
    r.add_argument("--out", required=True)
    q = sub.add_parser("report")
    q.add_argument("--in", dest="inp", required=True)
    q.add_argument("--new", default="v_pf")
    q.add_argument("--old", default="v_id")
    q.add_argument("--also", nargs="*", default=None, help="追加の比較 new:old（診断）")
    q.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    return run(args) if args.cmd == "run" else report(args)


if __name__ == "__main__":
    main()
