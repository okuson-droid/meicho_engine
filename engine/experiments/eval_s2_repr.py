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

## 局数の足し継ぎと取り込み（段階3・D-138・設計書 §3.7）

- 同じ `--out` に大きい `--n` で打ち直すと、各ブロックの足りない局（seed0+既存の局数 から）だけを回して後ろに足す。
  局はシードだけで決まるので、足し継いだ結果は最初から大きい n で回したのと同じになる（検査 T-7）
- `--import 元.json:候補名` は、別ファイルで回した同じ候補の結果を取り込む（V_0 の 150 局を 300 局の課題に使う）。
  シード（seed0）・デッキ・ネットの指紋のどれかが違えば落とす。取り込み元の局数が取り込み先より多くても落とす。
  取り込んだ元は `imported` に残す

## 読み方（事前に固定）

- 主比較: 候補 new と old の**同じ（ブロック・シード）の局どうしの得点差**を、デッキの中で局ごとに再標本化して
  デッキ等重みで平均する（計画書 §7.3 の対ブートストラップ・10,000 回）。**95% 区間の下端 > 0 なら new を採る**。
  0 をまたげば未判定（通るまで追試しない）
- 各候補の対 素 planner の得点（デッキ等重み）も区間つきで出す（診断）

## 課題 s4（段階4・D-154・設計書 `GENERALIST_STAGE4_DESIGN_20261001.md` §5）

    python3 experiments/eval_s2_repr.py run --task s4 --target ENV_SANGE_RM_TSUBAKI --arm G1000=<束ねた V> \
        --n 400 --seed0 <validate の帯> --out results/drl/s4/eval_1000.json
    python3 experiments/eval_s2_repr.py report --in results/drl/s4/eval_1000.json --new G1000 --old S1000 --also G1000:R1000

- 候補も相手も対象デッキ D だけを使う（ミラー）。相手は素 planner・H・貪欲の 3 ブロック（`--opponents`）
- 全候補・全ブロックで同じシード列。候補ごとに局数（`--n`）を変えてよい（300・0 局の時点は先頭 200 シード）
- 差は同じ（ブロック・シード）の局どうし。**ブロックの中で席を入れ替えた 2 局の組 (2k, 2k+1) を単位に**
  10,000 回再標本化し、ブロックを等しい重みで平均する（計画書 §7.3）。局数が違う候補どうしは、両方にある先頭の組だけで対にする
- 帯は既定で kind=validate。門 S-0（設計書 §3.1）は `--band-kind diag` で診断の帯に回す
- 課題 s2（既定）の結果ファイルと報告は従来とバイト単位で同じ（検査 S4-4）
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


def ci_percentiles(level: float = 0.95) -> list:
    """両側 level の区間の分位（%）。既定 0.95 は従来どおり [2.5, 97.5]（丸めでバイト単位に同じ）。

    D-148 §4.3: 腕を k 本回すときは level = 1 − 0.05/k（Bonferroni）にする。
    """
    if not 0.5 < level < 1:
        raise SystemExit(f"--level は 0.5 と 1 の間: {level}")
    lo = round(50 * (1 - level), 10)
    return [lo, round(100 - lo, 10)]


def paired_diff(games: list, new: list, old: list, n_boot: int = 10000, seed: int = 0,
                level: float = 0.95) -> dict:
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
    lo, hi = np.percentile(boots, ci_percentiles(level))
    by_deck = {k: {"n": int(len(idx[k])), "diff": float(d[idx[k]].mean()),
                   "new_only": int((d[idx[k]] > 0).sum()), "old_only": int((d[idx[k]] < 0).sum())}
               for k in decks}
    return {"diff": diff, "lo": float(lo), "hi": float(hi), "n_games": int(len(d)), "by_deck": by_deck}


def score_ci(games: list, s: list, n_boot: int = 10000, seed: int = 0, level: float = 0.95) -> dict:
    """デッキ等重みの平均得点と区間（既定 95%・局を再標本化）。"""
    zero = [0.0] * len(s)
    r = paired_diff(games, s, zero, n_boot, seed, level)
    return {"score": r["diff"], "lo": r["lo"], "hi": r["hi"],
            "by_deck": {k: v["diff"] for k, v in r["by_deck"].items()}}


def _arm_spec(arm: str, path: str | None, pool: list) -> dict:
    from arena_rs import PLANNER
    from record_mix import NETFREE
    extra = {"value_net": os.path.abspath(path)} if path else {}
    return PLANNER(pool, **NETFREE, **extra)


S4_OPPONENTS = ("planner", "heuristic", "greedy")


def resolve_deck(name: str) -> str:
    """`ENV_…` は `env/ENV_…`、それ以外（SD001 など）はそのまま。decklists にあることを確かめる。"""
    for cand in ((name if name.startswith("env/") else f"env/{name}"), name):
        if os.path.isfile(os.path.join(_HERE, "..", "decklists", f"{cand}.json")):
            return cand
    raise SystemExit(f"デッキ {name} が decklists に無い")


def check_band_kind(seed0: int, n: int, kind: str) -> None:
    with open(os.path.join(_HERE, "seed_bands.json"), encoding="utf-8") as f:
        led = json.load(f)
    for s in (seed0, seed0 + n - 1):
        hit = [b for b in led["bands"] if b["start"] <= s <= b["end"]]
        if not hit:
            raise SystemExit(f"帯 {s} は seed_bands.json に未登録。台帳に追記してから使うこと（D-028）")
        if hit[0].get("kind") != kind:
            raise SystemExit(f"帯 {hit[0]['start']}..{hit[0]['end']} は kind={hit[0].get('kind')}。"
                             f"この課題は kind={kind} の帯で回す")


def _opp_spec(kind: str, pool: list) -> dict:
    from arena_rs import GREEDY, HEURISTIC, PLANNER
    return {"planner": lambda: PLANNER(pool), "heuristic": HEURISTIC, "greedy": lambda: GREEDY(pool)}[kind]()


def run_s4(args) -> dict:
    """課題 s4（D-154 §5.1）。候補は A 席・デッキは D どうし・相手は opponents のブロック。"""
    import hashlib
    import meicho_rs as rs
    from arena import load_deck, matchup_config
    from arena_rs import ensure_cards
    if not args.target:
        raise SystemExit("--task s4 には --target が要る")
    target = resolve_deck(args.target)
    opps = [o.strip() for o in args.opponents.split(",")] if args.opponents else list(S4_OPPONENTS)
    for o in opps:
        if o not in S4_OPPONENTS:
            raise SystemExit(f"--opponents は {S4_OPPONENTS} から: {o}")
    if args.n % 2:
        raise SystemExit("--n は偶数（席を入れ替えた 2 局の組で数える）")
    check_band_kind(args.seed0, args.n, args.band_kind)
    ensure_cards()
    data = {"version": TOOL_VERSION, "task": "s4", "decision": "D-154", "target": target, "opponents": opps,
            "seed0": args.seed0, "band_kind": args.band_kind, "arms": {}, "results": {}}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            data = json.load(f)
        if (data.get("task"), data["target"], data["opponents"], data["seed0"]) != ("s4", target, opps, args.seed0):
            raise SystemExit("条件（課題・対象デッキ・相手・シード）が前回と違う。別の --out に")
    arms = {}
    for a in args.arm:
        name, _, path = a.partition("=")
        arms[name] = path or None
        fp = hashlib.sha256(open(path, "rb").read()).hexdigest()[:16] if path else None
        prev = data["arms"].get(name)
        if prev is not None and prev["sha"] != fp:
            raise SystemExit(f"候補 {name} のネットが前回と違う（{prev['sha']} → {fp}）。別の名前にすること")
        data["arms"][name] = {"path": path, "sha": fp, "n": max(args.n, (prev or {}).get("n", 0))}
    d = load_deck(target)
    cfg = matchup_config(d, d)
    cfg.validate()
    t0 = time.time()
    for name, path in arms.items():
        for o in opps:
            key = f"{name}|{o}"
            have = len(data["results"].get(key, []))
            if have >= args.n:
                continue
            if time.time() - t0 > args.budget_sec:
                print(f"予算 {args.budget_sec} 秒を超えたので止める（続きは同じコマンドで再開）")
                return data
            t = time.time()
            res = rs.series(cfg.chara_decks, cfg.action_decks, _arm_spec(name, path, d["action_deck"]),
                            _opp_spec(o, d["action_deck"]), args.seed0 + have, args.n - have, args.workers, 200, True)
            data["results"][key] = data["results"].get(key, []) + \
                [[(0.5 if r[0] is None else float(bool(r[0]))), int(r[1])] for r in res]
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"{key}: {time.time() - t:.0f} 秒・得点 {np.mean([x[0] for x in data['results'][key]]):.3f}",
                  flush=True)
    return data


def _s4_pairs(data: dict, arm: str, opp: str, n: int) -> np.ndarray:
    """(組の数, 2) の得点。先頭 n 局（偶数）だけ。"""
    r = data["results"][f"{arm}|{opp}"][:n]
    return np.array([x[0] for x in r], float).reshape(-1, 2)


def s4_common_n(data: dict, arms: list) -> int:
    n = min(len(data["results"].get(f"{a}|{o}", [])) for a in arms for o in data["opponents"])
    return n - n % 2


def s4_paired(data: dict, new: str, old: str | None, n_boot: int = 10000, seed: int = 0,
              level: float = 0.95) -> dict:
    """組を単位にブロックの中で再標本化・ブロック等重みの平均（old が None なら new の得点そのもの）。"""
    arms = [new] + ([old] if old else [])
    n = s4_common_n(data, arms)
    if n < 2:
        raise SystemExit(f"{arms} に共通の局が無い")
    rng = np.random.RandomState(seed)
    per, boots = {}, np.zeros(n_boot)
    for o in data["opponents"]:
        d = _s4_pairs(data, new, o, n).mean(1)
        if old:
            d = d - _s4_pairs(data, old, o, n).mean(1)
        per[o] = float(d.mean())
        boots += d[rng.randint(0, len(d), size=(n_boot, len(d)))].mean(1)
    boots /= len(data["opponents"])
    lo, hi = np.percentile(boots, ci_percentiles(level))
    return {"diff": float(np.mean(list(per.values()))), "lo": float(lo), "hi": float(hi), "n_per_block": n,
            "by_block": per}


def s4_wdl(data: dict, arm: str) -> dict:
    out = {}
    for o in data["opponents"]:
        r = [x[0] for x in data["results"].get(f"{arm}|{o}", [])]
        out[o] = {"n": len(r), "W": r.count(1.0), "D": r.count(0.5), "L": r.count(0.0)}
    return out


def report_s4(args, data: dict) -> dict:
    level = getattr(args, "level", 0.95)
    arms = [a for a in data["arms"] if all(f"{a}|{o}" in data["results"] for o in data["opponents"])]
    out = {"version": TOOL_VERSION, "task": "s4", "target": data["target"], "opponents": data["opponents"],
           "seed0": data["seed0"], "level": level,
           "scores": {a: s4_paired(data, a, None, level=level) for a in arms},
           "wdl": {a: s4_wdl(data, a) for a in arms}, "compare": {}}
    pairs = [(args.new, args.old)] + [tuple(p.split(":")) for p in (args.also or [])]
    for new, old in pairs:
        if new in arms and old in arms:
            out["compare"][f"{new}-{old}"] = s4_paired(data, new, old, level=level)
    path = args.out or args.inp.replace(".json", "_report.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"scores": {a: [round(v["diff"], 4), round(v["lo"], 4), round(v["hi"], 4), v["n_per_block"]]
                                 for a, v in out["scores"].items()},
                      "compare": {k: [round(v["diff"], 4), round(v["lo"], 4), round(v["hi"], 4), v["n_per_block"]]
                                  for k, v in out["compare"].items()}}, ensure_ascii=False))
    return out


def run(args) -> dict:
    if getattr(args, "task", "s2") == "s4":
        return run_s4(args)
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
        assert (data["seed0"], data["decks"]) == (args.seed0, decks), "条件が違う（別の --out に）"
        assert data["n"] <= args.n, "局数を減らして打ち直さない（別の --out に）"
        data["n"] = args.n                       # 局数を増やすのは足し継ぎ（D-138）
    import hashlib
    for name, path in arms.items():
        fp = hashlib.sha256(open(path, "rb").read()).hexdigest()[:16] if path else None
        prev = data["arms"].get(name)
        if prev is not None and prev["sha"] != fp:
            raise SystemExit(f"候補 {name} のネットが前回と違う（{prev['sha']} → {fp}）。別の名前にすること")
        data["arms"][name] = {"path": path, "sha": fp}
    for spec in args.imports or []:
        import_arm(data, spec, decks)
    t0 = time.time()
    for name, path in arms.items():
        for a, b in blocks(decks):
            key = f"{name}|{a}|{b}"
            have = len(data["results"].get(key, []))
            if have >= args.n:
                continue
            if time.time() - t0 > args.budget_sec:
                print(f"予算 {args.budget_sec} 秒を超えたので止める（続きは同じコマンドで再開）")
                return data
            da, db = load_deck(a), load_deck(b)
            cfg = matchup_config(da, db)
            cfg.validate()
            t = time.time()
            res = rs.series(cfg.chara_decks, cfg.action_decks, _arm_spec(name, path, db["action_deck"]),
                            PLANNER(da["action_deck"]), args.seed0 + have, args.n - have, args.workers, 200, True)
            data["results"][key] = data["results"].get(key, []) + \
                [[(0.5 if r[0] is None else float(bool(r[0]))), int(r[1])] for r in res]
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"{key}: {time.time() - t:.0f} 秒・得点 {np.mean([x[0] for x in data['results'][key]]):.3f}",
                  flush=True)
    return data


def import_arm(data: dict, spec: str, decks: list) -> None:
    """別ファイルの同じ候補の結果を取り込む（D-138）。シード・デッキ・指紋・局数を確かめる。"""
    src_path, _, arm = spec.rpartition(":")
    with open(src_path, encoding="utf-8") as f:
        src = json.load(f)
    if (src["seed0"], src["decks"]) != (data["seed0"], decks):
        raise SystemExit(f"取り込み元 {src_path} のシード・デッキが違う（seed0 {src['seed0']} → {data['seed0']}）")
    if src["n"] > data["n"]:
        raise SystemExit(f"取り込み元 {src_path} の局数 {src['n']} が取り込み先 {data['n']} より多い")
    if arm not in src["arms"] or arm not in data["arms"]:
        raise SystemExit(f"候補 {arm} が取り込み元か --arm に無い（取り込む候補も --arm で指定する）")
    if src["arms"][arm]["sha"] != data["arms"][arm]["sha"]:
        raise SystemExit(f"候補 {arm} のネットの指紋が取り込み元と違う"
                         f"（{src['arms'][arm]['sha']} → {data['arms'][arm]['sha']}）")
    for a, b in blocks(decks):
        key = f"{arm}|{a}|{b}"
        got, have = src["results"].get(key, []), data["results"].get(key, [])
        if len(got) > len(have):
            if got[:len(have)] != have:
                raise SystemExit(f"{key}: 取り込み元と既存の結果が食い違う")
            data["results"][key] = got
    rec = {"from": src_path, "arm": arm, "n": src["n"]}
    if rec not in data.setdefault("imported", []):
        data["imported"].append(rec)


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
    if data.get("task") == "s4":
        return report_s4(args, data)
    games = games_of(data)
    # 全ブロックが n 局そろった候補だけを報告する。足し継ぎの途中（D-138）の候補は飛ばし、
    # 足りないブロックの数を `incomplete` に残す（前はキーの有無だけを見ていて IndexError で落ちた）。
    short = {a: sum(len(data["results"].get(f"{a}|{x}|{y}", [])) < data["n"] for x, y in blocks(data["decks"]))
             for a in data["arms"]}
    arms = [a for a in data["arms"] if short[a] == 0]
    level = getattr(args, "level", 0.95)
    out = {"version": TOOL_VERSION, "n_per_block": data["n"], "decks": data["decks"],
           "scores": {a: score_ci(games, scores_of(data, a), level=level) for a in arms}, "compare": {},
           "incomplete": {a: k for a, k in short.items() if k}}
    if level != 0.95:
        out["level"] = level            # 既定の報告は従来とバイト単位で同じにする
    pairs = [(args.new, args.old)] + [tuple(p.split(":")) for p in (args.also or [])]
    for new, old in pairs:
        if new in arms and old in arms:
            out["compare"][f"{new}-{old}"] = paired_diff(games, scores_of(data, new), scores_of(data, old),
                                                         level=level)
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
    r.add_argument("--import", dest="imports", action="append", default=None,
                   help="元.json:候補名 — 別ファイルの同じ候補の結果を取り込む（D-138）")
    r.add_argument("--task", choices=["s2", "s4"], default="s2", help="s4 = 段階4 の課題（D-154 §5.1）")
    r.add_argument("--target", default=None, help="--task s4: 対象デッキ（候補も相手もこのデッキ）")
    r.add_argument("--opponents", default=None, help="--task s4: 相手（既定 planner,heuristic,greedy）")
    r.add_argument("--band-kind", choices=["validate", "diag"], default="validate",
                   help="--task s4: 帯の種類（門 S-0 だけ diag）")
    q = sub.add_parser("report")
    q.add_argument("--in", dest="inp", required=True)
    q.add_argument("--new", default="v_pf")
    q.add_argument("--old", default="v_id")
    q.add_argument("--also", nargs="*", default=None, help="追加の比較 new:old（診断）")
    q.add_argument("--out", default=None)
    q.add_argument("--level", type=float, default=0.95,
                   help="区間の水準（既定 0.95）。腕を k 本回すときは 1 − 0.05/k（D-148 §4.3・Bonferroni）")
    args = ap.parse_args(argv)
    return run(args) if args.cmd == "run" else report(args)


if __name__ == "__main__":
    main()
