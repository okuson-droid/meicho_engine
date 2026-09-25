"""段階2 の横断教材の組み合わせ表を、環境デッキ群の割り振りから作る（汎用 AI 段階2・D-129）。

    python3 experiments/make_s2_schedule.py --n-total 10000 --seed0 <帯の先頭> --band-end <帯の終わり> \
        --out results/drl/s2_schedule.json
    python3 experiments/make_s2_schedule.py --only ENV_SANGE_RF_ANKO --pilot-n 2 \
        --seed0 825000 --band-end 825999 --out results/drl/s2_pilot_schedule.json      # 下見

入力は `results/decksim/env_v1.json` の `decks_block`（24 デッキの lineage／group／split・D-128）。
出力は `experiments/record_mix.py --schedule` にそのまま渡せる JSON（形は record_mix の docstring）。

## 規則（検査 `tests/test_s2_schedule.py` の S-1〜S-7）

- **学習（split=train）のデッキだけを使う。**調整・最終評価は自分側にも相手側にも出さない
  （計画書 `GENERALIST_AI_REVIEW_D086.md` §5.2）。
- 配分は §5.3 の出発点どおり: ミラー 40%・異なる学習デッキ同士 40%・H／貪欲／素 planner 20%。
  - ミラー: 学習デッキごとに 1 ブロック（両席を記録）
  - 異なる学習デッキ同士: 16C2 = 120 組すべてに 1 ブロック（名前の辞書順で deck_a < deck_b・両席を記録）
  - H／貪欲／素 planner: 学習デッキごとに 3 ブロック。**相手も同じデッキ**を使い、教師の席だけ記録する
- 局数はそれぞれ「その種類の総局数 ÷ ブロック数」を**偶数に丸めたもの**（最小 2）。
  偶数にするのは A/B が両方のデッキを半分ずつ持つため（`record_mix` の席の約束）。
  丸めのせいで総局数は `--n-total` からずれるので、実際の総数を `n_total_actual` に書き、
  `p_planned` はその実数で割った値にする（計画した抽出確率＝実際に回す割合）。
- シードは `--seed0` から隙間なく並べる。`--band-end` を越えるなら作らずに落ちる。
  **帯は台帳 `seed_bands.json` に登録してから回すこと**（D-028。この道具は台帳を読まない・書かない）。
- 乱数を使わない（同じ引数なら出力はバイトまで同じ）。
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ENV = os.path.join(_HERE, "..", "results", "decksim", "env_v1.json")
PREFIX = "env/"
SHARES = {"mirror": 0.4, "cross": 0.4, "anchor": 0.2}
ANCHOR_OPPONENTS = ("heuristic", "greedy", "planner")
TOOL_VERSION = "s2sched-1"


def _even(x: float) -> int:
    """偶数に丸める（最も近い偶数・ちょうど中間は上へ）。最小 2。"""
    return max(2, 2 * int(x / 2 + 0.5))


def build(decks_block: dict, *, n_total: int, seed0: int, band_end: int, only: str | None,
          pilot_n: int | None, name: str) -> dict:
    train = sorted(k for k, v in decks_block.items() if v.get("split") == "train")
    if len(train) < 2:
        raise SystemExit(f"学習デッキが {len(train)} 個しか無い")
    if only is not None and only not in train:
        why = "存在しない" if only not in decks_block else f"split={decks_block[only].get('split')}"
        raise SystemExit(f"--only {only} は学習デッキではない（{why}）。調整・最終評価は教材に出さない")
    if pilot_n is not None and (pilot_n < 2 or pilot_n % 2):
        raise SystemExit("--pilot-n は 2 以上の偶数")

    pairs = list(itertools.combinations(train, 2))
    per = {
        "mirror": _even(SHARES["mirror"] * n_total / len(train)),
        "cross": _even(SHARES["cross"] * n_total / len(pairs)),
        "anchor": _even(SHARES["anchor"] * n_total / (len(train) * len(ANCHOR_OPPONENTS))),
    }
    raw = []
    for d in train:
        raw.append(("mirror", d, d, "teacher", "both"))
    for a, b in pairs:
        raw.append(("cross", a, b, "teacher", "both"))
    for d in train:
        for opp in ANCHOR_OPPONENTS:
            raw.append(("anchor", d, d, opp, "a"))
    if only is not None:
        raw = [r for r in raw if only in (r[1], r[2])]

    blocks, s = [], seed0
    for kind, a, b, opp, rec in raw:
        n = pilot_n if pilot_n is not None else per[kind]
        blk = {"kind": kind, "deck_a": PREFIX + a, "deck_b": PREFIX + b, "seed0": s, "n": n, "record": rec}
        if opp != "teacher":
            blk["opponent"] = opp
        blocks.append(blk)
        s += n
    total = s - seed0
    if s - 1 > band_end:
        raise SystemExit(f"シード {seed0}..{s - 1}（{total} 局）が帯の終わり {band_end} を越える")
    for blk in blocks:
        blk["p_planned"] = blk["n"] / total

    used = sorted({d for blk in blocks for d in (blk["deck_a"], blk["deck_b"])})
    decks = {}
    for full in used:
        src = decks_block[full[len(PREFIX):]]
        decks[full] = {"lineage": src["lineage"], "group": src["group"], "split": src["split"]}
    return {
        "name": name,
        "generator": {"tool": "experiments/make_s2_schedule.py", "version": TOOL_VERSION,
                      "decision": "D-129", "shares": SHARES, "anchor_opponents": list(ANCHOR_OPPONENTS),
                      "n_total_requested": n_total, "per_block": per, "only": only, "pilot_n": pilot_n,
                      "band": [seed0, band_end]},
        "n_total_actual": total,
        "teacher": {"name": "netfree", "tau": 0.0},
        "decks": decks,
        "blocks": blocks,
    }


def split(sch: dict, k: int) -> list:
    """組み合わせ表をブロックの並びのまま k 個に分ける（D-131）。

    `record_mix.py` は 1 回の実行で全ブロックを回し、途中から再開できないので、作業環境の 1 回の
    実行の上限（600 秒）に収まるように分けて回す。ブロック・シード・`p_planned` は元の表のまま
    （`p_planned` は**全体に対する**割合）。局数がほぼ均等になるよう、各ブロックの真ん中の局の位置で部分を決める。
    """
    blocks = sch["blocks"]
    total = sum(b["n"] for b in blocks)
    parts, acc = [[] for _ in range(k)], 0
    for b in blocks:
        # ブロックの真ん中の局が全体のどこにあるかで部分を決める（並びは保つ・局数の差は最大 1 ブロック分）
        parts[min(k - 1, int((acc + b["n"] / 2) * k // total))].append(b)
        acc += b["n"]
    out = []
    for i, bl in enumerate(parts):
        used = sorted({d for b in bl for d in (b["deck_a"], b["deck_b"])})
        p = {key: val for key, val in sch.items() if key not in ("blocks", "decks", "name")}
        p["name"] = f"{sch['name']}.p{i}of{k}"
        p["part"] = {"index": i, "of": k, "games": sum(b["n"] for b in bl)}
        p["decks"] = {d: sch["decks"][d] for d in used}
        p["blocks"] = bl
        out.append(p)
    return out


_SUMMED = ("games", "seat_games", "seat_games_teacher", "decisions_recorded")
_SAME = ("encoding_version", "rules_version", "format")


def merge_manifests(paths: list) -> dict:
    """分けて回した manifest をまとめた索引（D-131）。デッキ別の数は部分の和。**版が違えば落とす**。"""
    ms = []
    for pth in paths:
        with open(pth, encoding="utf-8") as f:
            ms.append(json.load(f))
    for key in _SAME:
        vals = {json.dumps(m.get(key)) for m in ms}
        if len(vals) != 1:
            raise SystemExit(f"{key} が部分ごとに違う（{sorted(vals)}）。版の違う記録を混ぜない")
    decks: dict = {}
    for m in ms:
        for name, d in m["decks"].items():
            acc = decks.setdefault(name, {k: v for k, v in d.items() if k not in _SUMMED})
            if acc.get("sha256") != d.get("sha256"):
                raise SystemExit(f"{name} のデッキのハッシュが部分ごとに違う")
            for k in _SUMMED:
                acc[k] = acc.get(k, 0) + d.get(k, 0)
    by_opp: dict = {}
    for m in ms:
        for k, v in m["games_by_opponent"].items():
            by_opp[k] = by_opp.get(k, 0) + v
    return {
        "tool": "experiments/make_s2_schedule.py --merge", "decision": "D-131",
        **{k: ms[0][k] for k in _SAME},
        "parts": [{"path": os.path.basename(p), "schedule_name": m["schedule_name"],
                   "schedule_sha256": m["schedule_sha256"], "blocks": len(m["blocks"]),
                   "games": sum(b["n"] for b in m["blocks"]), "seconds": m["seconds"]}
                  for p, m in zip(paths, ms)],
        "games": sum(sum(b["n"] for b in m["blocks"]) for m in ms),
        "decisions_recorded": sum(d["decisions_recorded"] for d in decks.values()),
        "decks": dict(sorted(decks.items())), "games_by_opponent": by_opp,
    }


def dumps(sch: dict) -> str:
    return json.dumps(sch, ensure_ascii=False, indent=1) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=DEFAULT_ENV)
    ap.add_argument("--n-total", type=int, default=10000)
    ap.add_argument("--seed0", type=int, default=None)
    ap.add_argument("--band-end", type=int, default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--pilot-n", type=int, default=None)
    ap.add_argument("--name", default="s2")
    ap.add_argument("--parts", type=int, default=1, help="k 個に分けて <out>.p<i>of<k>.json にも書く（D-131）")
    ap.add_argument("--merge", nargs="+", default=None, help="manifest をまとめて --out に書く（D-131）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.merge and (args.seed0 is None or args.band_end is None):
        ap.error("--seed0 と --band-end が要る")
    if args.merge:
        idx = merge_manifests(args.merge)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(idx))
        print(json.dumps({"out": args.out, "games": idx["games"], "decisions": idx["decisions_recorded"],
                          "parts": len(idx["parts"])}, ensure_ascii=False))
        return idx
    with open(args.env, encoding="utf-8") as f:
        env = json.load(f)
    sch = build(env["decks_block"], n_total=args.n_total, seed0=args.seed0, band_end=args.band_end,
                only=args.only, pilot_n=args.pilot_n, name=args.name)
    sch["generator"]["env"] = {"path": os.path.relpath(args.env, os.path.join(_HERE, "..")).replace(os.sep, "/"),
                               "version": env.get("version")}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(sch))
    if args.parts > 1:
        stem = args.out[:-5] if args.out.endswith(".json") else args.out
        for p in split(sch, args.parts):
            with open(f"{stem}.p{p['part']['index']}of{args.parts}.json", "w", encoding="utf-8", newline="\n") as f:
                f.write(dumps(p))
    kinds = {}
    for b in sch["blocks"]:
        kinds[b["kind"]] = kinds.get(b["kind"], 0) + b["n"]
    print(json.dumps({"out": args.out, "blocks": len(sch["blocks"]), "games": sch["n_total_actual"],
                      "by_kind": kinds, "seeds": [args.seed0, args.seed0 + sch["n_total_actual"] - 1]},
                     ensure_ascii=False))
    return sch


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
