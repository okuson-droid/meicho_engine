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
- 教師（段階3・D-138）: 既定は `netfree`・τ = 0（D-131 と同じ表をバイトまで同じに作る）。
  `--teacher netfree_v --value-net <パス>` で葉を V にし、V の指紋（sha256 先頭 16 桁）を表の教師に書く
  （`record_mix.py` が回す前にファイルと照合する）。`--tau` は記録の温度。
  `--merge` は教師（名前・τ・葉の V の指紋）の違う部分を混ぜると落とす。

## 段階4（D-154・設計書 `GENERALIST_STAGE4_DESIGN_20261001.md` §3.1・§4.2・§8 の 1）

- `--target D --per-block mirror:M,cross:C,anchor:A`: 対象デッキ D（調整デッキ）の追加学習の教材。
  ミラー D 対 D 1 ブロック（M 局・両席を記録）／異種 D 対 学習デッキ 16 個（各 C 局・**D の席だけ**記録
  `record: deck_a`）／錨 D 対 D で相手が H・貪欲・素 planner（各 A 局・教師の席だけ）。
  調整デッキの残りと最終評価のデッキは出さない（検査 S4-1）
- `--pool-only NAME --per-block mirror:M,anchor:A`: そのデッキだけの教材（S の事前学習・SD001）。ミラー 1 ブロック＋錨 3 ブロック。
  NAME は `decklists/NAME.json`（環境デッキ群の外のデッキ・前置き無し）
- 局数は `--per-block` でブロックごとにそのまま指定する（設計書に書いた数を写す。偶数でなければ落とす）
- `--purpose` は表に `purpose` 欄を足す（例 `stage4_finetune`・manifest に写る）
- どちらも付けなければ従来と同じ（D-131 の表とバイト単位で同じ・検査 S4-4）
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ENV = os.path.join(_HERE, "..", "results", "decksim", "env_v1.json")
PREFIX = "env/"
SHARES = {"mirror": 0.4, "cross": 0.4, "anchor": 0.2}
ANCHOR_OPPONENTS = ("heuristic", "greedy", "planner")
CROSS_OPPONENTS = ("teacher", "netfree")         # --target の異種のブロックの相手の席（D-161）
TOOL_VERSION = "s2sched-1"
TEACHERS = ("netfree", "netfree_v", "netfree_vp")


def _even(x: float) -> int:
    """偶数に丸める（最も近い偶数・ちょうど中間は上へ）。最小 2。"""
    return max(2, 2 * int(x / 2 + 0.5))


def _net_entry(out: dict, key: str, rel: str, flag: str) -> None:
    path = rel if os.path.isabs(rel) else os.path.join(_HERE, "..", rel)
    if not os.path.isfile(path):
        raise SystemExit(f"{flag} のファイルが無い: {rel}")
    with open(path, "rb") as f:
        out[key] = rel
        out[f"{key}_sha16"] = hashlib.sha256(f.read()).hexdigest()[:16]


def teacher_def(teacher: str = "netfree", value_net: str | None = None, tau: float = 0.0,
                reeval_samples: int = 0, policy_net: str | None = None) -> dict:
    """組み合わせ表の教師の定義（D-138）。既定は D-131 と同じ `{"name": "netfree", "tau": 0.0}`。

    `netfree_vp`（壁を越える案 腕 A・D-163 §2.1）は `netfree_v` の代打ちを `policy_net` の π にしたもの。"""
    if teacher not in TEACHERS:
        raise SystemExit(f"--teacher は {TEACHERS} のどれか")
    if teacher in ("netfree_v", "netfree_vp") and not value_net:
        raise SystemExit(f"--teacher {teacher} には --value-net（葉の V のパス）が要る")
    if teacher not in ("netfree_v", "netfree_vp") and value_net:
        raise SystemExit("--value-net は --teacher netfree_v / netfree_vp のときだけ使う")
    if (teacher == "netfree_vp") != bool(policy_net):
        raise SystemExit("--policy-net は --teacher netfree_vp のときだけ使い、そのときは必ず要る")
    out = {"name": teacher, "tau": float(tau)}
    if reeval_samples:
        # 既定（0）は欄を足さない＝従来の組み合わせ表とバイト単位で同じ（D-148 (b)）
        out["reeval_samples"] = int(reeval_samples)
    if value_net:
        _net_entry(out, "value_net", value_net, "--value-net")
    if policy_net:
        _net_entry(out, "policy_net", policy_net, "--policy-net")
    return out


def build(decks_block: dict, *, n_total: int, seed0: int, band_end: int, only: str | None,
          pilot_n: int | None, name: str, teacher: dict | None = None) -> dict:
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
        "teacher": teacher or teacher_def(),
        "decks": decks,
        "blocks": blocks,
    }


def parse_per_block(text: str, kinds: tuple) -> dict:
    """`mirror:400,cross:24,anchor:72` を {種類: 局数} に。種類がそろわない・偶数でない・2 未満は落とす。"""
    out = {}
    for part in text.split(","):
        k, _, v = part.partition(":")
        try:
            out[k.strip()] = int(v)
        except ValueError:
            raise SystemExit(f"--per-block は 種類:局数 をカンマで並べる: {text!r}")
    if sorted(out) != sorted(kinds):
        raise SystemExit(f"--per-block の種類は {kinds} ちょうど: {text!r}")
    for k, v in out.items():
        if v < 2 or v % 2:
            raise SystemExit(f"--per-block の {k} は 2 以上の偶数（席を半々にする）: {v}")
    return out


def build_target(decks_block: dict, *, target: str, per: dict, seed0: int, band_end: int, name: str,
                 teacher: dict | None = None, purpose: str | None = None, cross_opponent: str = "teacher") -> dict:
    """段階4 の対象デッキの教材（設計書 §4.2）。相手の学習デッキは 16 個すべて・調整と最終評価は出さない。"""
    if target not in decks_block:
        raise SystemExit(f"--target {target} は環境デッキ群に無い")
    if decks_block[target].get("split") == "final":
        raise SystemExit(f"--target {target} は最終評価のデッキ（開けない・D-153 追記 1）")
    if decks_block[target].get("split") == "train":
        raise SystemExit(f"--target {target} は学習デッキ（汎用 V が学んだデッキは対象にしない）")
    train = sorted(k for k, v in decks_block.items() if v.get("split") == "train")
    if cross_opponent not in CROSS_OPPONENTS:
        raise SystemExit(f"--cross-opponent は {CROSS_OPPONENTS} のどれか")
    raw = [("mirror", target, target, "teacher", "both")]
    for d in train:
        # 段階4 便 4-A4（D-161）: --cross-opponent netfree では異種の相手の席だけ netfree にし、教師の席（deck_a）を記録する
        raw.append(("cross", target, d, "teacher", "deck_a") if cross_opponent == "teacher"
                   else ("cross", target, d, cross_opponent, "a"))
    for opp in ANCHOR_OPPONENTS:
        raw.append(("anchor", target, target, opp, "a"))
    gen = {"target": target, "per_block": per}
    if cross_opponent != "teacher":
        gen["cross_opponent"] = cross_opponent      # 既定は欄を足さない＝従来の表とバイト単位で同じ
    return _assemble(raw, per, decks_block, seed0=seed0, band_end=band_end, name=name, teacher=teacher,
                     purpose=purpose, gen=gen)


def build_pool_only(deck: str, *, per: dict, seed0: int, band_end: int, name: str,
                    teacher: dict | None = None, purpose: str | None = None) -> dict:
    """1 つのデッキだけの教材（設計書 §3.1・S の事前学習）。ミラー 1 ブロック＋錨 3 ブロック。"""
    path = os.path.join(_HERE, "..", "decklists", f"{deck}.json")
    if not os.path.isfile(path):
        raise SystemExit(f"--pool-only {deck}: decklists/{deck}.json が無い")
    raw = [("mirror", deck, deck, "teacher", "both")] + \
          [("anchor", deck, deck, opp, "a") for opp in ANCHOR_OPPONENTS]
    return _assemble(raw, per, None, seed0=seed0, band_end=band_end, name=name, teacher=teacher,
                     purpose=purpose, gen={"pool_only": deck, "per_block": per}, prefix="")


def _assemble(raw: list, per: dict, decks_block: dict | None, *, seed0: int, band_end: int, name: str,
              teacher: dict | None, purpose: str | None, gen: dict, prefix: str = PREFIX) -> dict:
    blocks, s = [], seed0
    for kind, a, b, opp, rec in raw:
        n = per[kind]
        blk = {"kind": kind, "deck_a": prefix + a, "deck_b": prefix + b, "seed0": s, "n": n, "record": rec}
        if opp != "teacher":
            blk["opponent"] = opp
            if a != b:
                # 教師以外が相手の異種のブロック: 教師（A）が常に deck_a を打つ（D-161・record_mix の規則）
                blk["agents_follow_decks"] = True
        blocks.append(blk)
        s += n
    total = s - seed0
    if s - 1 > band_end:
        raise SystemExit(f"シード {seed0}..{s - 1}（{total} 局）が帯の終わり {band_end} を越える")
    for blk in blocks:
        blk["p_planned"] = blk["n"] / total
    decks = {}
    for full in sorted({d for blk in blocks for d in (blk["deck_a"], blk["deck_b"])}):
        if decks_block is None:
            decks[full] = {"lineage": None, "group": None, "split": None}
        else:
            src = decks_block[full[len(prefix):]]
            decks[full] = {"lineage": src["lineage"], "group": src["group"], "split": src["split"]}
    out = {
        "name": name,
        "generator": {"tool": "experiments/make_s2_schedule.py", "version": TOOL_VERSION,
                      "decision": "D-154", "anchor_opponents": list(ANCHOR_OPPONENTS), **gen,
                      "band": [seed0, band_end]},
        "n_total_actual": total,
        "teacher": teacher or teacher_def(),
        "decks": decks,
        "blocks": blocks,
    }
    if purpose:
        out["purpose"] = purpose
    return out


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
    # 教師（名前・τ・葉の V の指紋）も揃える（D-138）。ブロックの `nets` は実際に読んだファイルの指紋
    teachers = {json.dumps([(m.get("schedule") or {}).get("teacher"),
                            sorted({(k, v) for b in m["blocks"] for k, v in (b.get("nets") or {}).items()})],
                           sort_keys=True) for m in ms}
    if len(teachers) != 1:
        raise SystemExit(f"教師が部分ごとに違う（{sorted(teachers)}）。教師の違う記録を混ぜない")
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
    ap.add_argument("--teacher", default="netfree",
                    help="netfree（既定）／netfree_v（葉を V に・D-138）／netfree_vp（＋代打ち π・D-163）")
    ap.add_argument("--value-net", default=None, help="--teacher netfree_v の葉の V（engine/ からの相対パス）")
    ap.add_argument("--policy-net", default=None, help="--teacher netfree_vp の代打ちの π（腕 A・D-163）")
    ap.add_argument("--tau", type=float, default=0.0, help="記録の温度（D-064 §6.2 の下見で決める）")
    ap.add_argument("--reeval-samples", type=int, default=0,
                    help="選んだ手を別の決定化で取り直す本数（記録の fresh 欄・既定 0 = 取らない・D-148 (b)）")
    ap.add_argument("--parts", type=int, default=1, help="k 個に分けて <out>.p<i>of<k>.json にも書く（D-131）")
    ap.add_argument("--merge", nargs="+", default=None, help="manifest をまとめて --out に書く（D-131）")
    ap.add_argument("--target", default=None, help="段階4: 対象デッキ（調整デッキ）の追加学習の教材（D-154 §4.2）")
    ap.add_argument("--pool-only", default=None, help="段階4: このデッキだけの教材（S の事前学習・D-154 §3.1）")
    ap.add_argument("--per-block", default=None, help="--target / --pool-only のブロックごとの局数（種類:局数,…）")
    ap.add_argument("--cross-opponent", default="teacher", choices=list(CROSS_OPPONENTS),
                    help="--target: 異種のブロックの相手の席（既定 teacher＝従来どおり／netfree＝教師を替えた教材で相手だけ netfree・D-161）")
    ap.add_argument("--purpose", default=None, help="表に purpose 欄を足す（例 stage4_finetune）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.target and args.pool_only:
        ap.error("--target と --pool-only は同時に使わない")
    if (args.target or args.pool_only) and not args.per_block:
        ap.error("--target / --pool-only には --per-block が要る")
    if not args.merge and (args.seed0 is None or args.band_end is None):
        ap.error("--seed0 と --band-end が要る")
    if args.merge:
        idx = merge_manifests(args.merge)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(idx))
        print(json.dumps({"out": args.out, "games": idx["games"], "decisions": idx["decisions_recorded"],
                          "parts": len(idx["parts"])}, ensure_ascii=False))
        return idx
    teacher = teacher_def(args.teacher, args.value_net, args.tau, args.reeval_samples, args.policy_net)
    with open(args.env, encoding="utf-8") as f:
        env = json.load(f)
    if args.target:
        sch = build_target(env["decks_block"], target=args.target,
                           per=parse_per_block(args.per_block, ("mirror", "cross", "anchor")),
                           seed0=args.seed0, band_end=args.band_end, name=args.name, teacher=teacher,
                           purpose=args.purpose, cross_opponent=args.cross_opponent)
    elif args.pool_only:
        sch = build_pool_only(args.pool_only, per=parse_per_block(args.per_block, ("mirror", "anchor")),
                              seed0=args.seed0, band_end=args.band_end, name=args.name, teacher=teacher,
                              purpose=args.purpose)
    else:
        sch = build(env["decks_block"], n_total=args.n_total, seed0=args.seed0, band_end=args.band_end,
                    only=args.only, pilot_n=args.pilot_n, name=args.name, teacher=teacher)
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
