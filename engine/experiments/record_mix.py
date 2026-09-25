"""異種デッキの記録つき対局を組み合わせ表から回す CLI（汎用 AI 段階1C-b・D-123）。

    python3 experiments/record_mix.py --schedule plan.json --out results/drl/mix_s2 --workers 2

`drl_record.py` は 1 デッキのミラー専用である。段階2 の横断教材（計画書
`GENERALIST_AI_REVIEW_D086.md` §5.3）は「ミラー・学習デッキ同士・H／貪欲との局」を
配分どおりに混ぜる必要があるので、組み合わせ表（schedule）を読む別の入口として置いた。
`drl_record.py` は変えていない（既存の manifest の `regenerate` 行をそのまま打てるように）。

## 相手デッキ表（D-123 の落とし穴の修正）

`rs.series_record` は奇数シードで A/B の席を入れ替えるが、デッキは席に固定である。
この CLI は常に `opp_from_seat=True` で回すので、各局で各エージェントの相手デッキ表
（`opp_decklist`）は**その局の相手の席の行動デッキ**になる。spec の `opp_decklist` は使われない。
これは「相手のデッキ表を知っている」前提であり、manifest に `opp_decklist_known: true` を書く
（設計書 `GENERALIST_STAGE1C_DESIGN.md` §5 判断 4。実戦では公開されないので、いつか外す前提）。

## 組み合わせ表（JSON）

    {
      "name": "s2_pilot",
      "teacher": {"name": "netfree", "tau": 0.0},        # 既定の教師（ブロックで上書き可）
      "decks": {                                          # §5.4 の系統情報（任意・無ければ null）
        "SD001": {"lineage": "starter_fire", "group": "SD001", "split": "train"}
      },
      "blocks": [
        {"deck_a": "SD001", "deck_b": "SD02", "seed0": 824000, "n": 10,
         "p_planned": 0.4, "record": "both"},
        {"deck_a": "SD001", "deck_b": "SD001", "seed0": 824010, "n": 10,
         "opponent": "heuristic", "record": "a"}
      ]
    }

- `deck_a` / `deck_b`: `decklists/<名前>.json`（`env/xxx` のように下位フォルダも可）。
  **席 0 が deck_a・席 1 が deck_b**。エージェント A/B は奇数シードで席を入れ替えるので、
  A も B も両方のデッキを半分ずつ持つ（`arena.matchup_config` と同じ約束）
- `opponent`: B 側。既定は教師どうし（`"teacher"`）。`"heuristic"` / `"greedy"` / `"planner"`（素）も可。
  教師以外を相手にするブロックは `record` を `"a"` にすること（記録する席を教師に固定・
  `VALUE_BOOTSTRAP_DESIGN.md` §6.3 の規則）。違反は引数の検査で落とす
- `teacher.name`: `"netfree"`（既定・ネットを使わない計画探索・下の `NETFREE`）／`"planner"`（素）／
  `"champion"`（そのプールの現 champion。**ネットが SD001 専用なので SD001 のミラーだけ**許す）
- シード帯は各ブロックごとに `seed_bands.json` で検査する（評価帯・未登録の帯は落とす）。
  ブロック同士でシードが重なっても落とす

## manifest（§5.4）

`<out>.manifest.json` に、デッキの sha256・キャラ 3 人組・系統・近似重複のグループ・
予定の抽出確率・**実際の席別の局数と決定数**（記録を読んで数える）・教師の定義（ネットの指紋を含む）・
相手デッキ表既知の旗・記録の版・符号化の版・ルールの版・打ち直すコマンドを書く。
**manifest は必ずマスターの PC に持ち帰ること**（`.bin` は捨ててよい・D-065 便 3）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import struct
import sys
import time
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import meicho_rs as rs                                          # noqa: E402

import champion                                                 # noqa: E402
from arena import matchup_config                                # noqa: E402
from arena_rs import GREEDY, HEURISTIC, PLANNER, ensure_cards   # noqa: E402
from drl_record import check_record_band, record_format, strip_paths  # noqa: E402
from meicho.cards import CHARA_CARDS                            # noqa: E402
from meicho.encode import ENCODING_VERSION                      # noqa: E402
from meicho.version import RULES_VERSION                        # noqa: E402

# 段階2 の教師の既定（設計書 §2 の 3・G0 §5 の推し・D-120 の `g1_cost_split.py variant netfree` と同じ中身）。
# SD001 の champion から V・π₀・代打ち π・束ねた解（bundle_p）を外したもの。**ネットを 1 本も使わない**ので
# どのデッキにも使える。`endgame_enum=64` は D-120 の速度実測（1 局 0.1 秒）に含まれていたので残す。
# champion の定義から**引かずに書き下す**——champion が替わっても教師が黙って変わらないように。
NETFREE = {"extra_turns": 1, "choice_phases": True, "solo_samples": 4, "known_hand": True,
           "endgame_enum": 64, "draw_buckets": 1}

OPPONENTS = ("teacher", "heuristic", "greedy", "planner")
NET_KEYS = ("value_net", "opp_policy_net", "policy_net")
REC_HEAD_V3 = struct.Struct("<qIHBBBBff")


def deck_path(name: str) -> str:
    return os.path.join(_HERE, "..", "decklists", f"{name}.json")


def load_deck_file(name: str) -> tuple[dict, str]:
    """デッキ JSON と、その**ファイルのバイト列の** sha256（§4: 分割の定義に保存し、中身を変えない）。"""
    with open(deck_path(name), "rb") as f:
        raw = f.read()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def teacher_spec(teacher: dict, pool: list, deck_a: str, deck_b: str) -> dict:
    name = teacher.get("name", "netfree")
    tau = float(teacher.get("tau", 0.0))
    extra = {"tau": tau} if tau else {}
    if name == "netfree":
        return PLANNER(pool, **NETFREE, **extra)
    if name == "planner":
        return PLANNER(pool, **extra)
    if name == "champion":
        if not (deck_a == deck_b == "SD001"):
            raise SystemExit("教師 champion はネットが SD001 専用なので SD001 のミラーだけに使える"
                             f"（{deck_a} 対 {deck_b}）")
        return champion.spec("SD001", pool, **extra)
    raise SystemExit(f"未知の教師: {name}")


def opponent_spec(kind: str, teacher: dict, pool: list, deck_a: str, deck_b: str) -> dict:
    if kind == "teacher":
        return teacher_spec(teacher, pool, deck_a, deck_b)
    if kind == "heuristic":
        return HEURISTIC()
    if kind == "greedy":
        return GREEDY(pool)
    if kind == "planner":
        return PLANNER(pool)
    raise SystemExit(f"未知の相手: {kind}（{OPPONENTS} のどれか）")


def net_fingerprints(spec: dict) -> dict:
    """spec に入っているネットの指紋（ファイルの sha256 先頭 16 桁・§5.4「教師の定義」）。"""
    out = {}
    for k in NET_KEYS:
        p = spec.get(k)
        if isinstance(p, str):
            with open(p, "rb") as f:
                out[os.path.basename(p)] = hashlib.sha256(f.read()).hexdigest()[:16]
    return out


def count_decisions(files) -> Counter:
    """記録（MCDR 版 3）を頭だけ読んで、(seed の偶奇, 席) ごとの決定数を数える。"""
    c: Counter = Counter()
    for path in files:
        with open(path, "rb") as f:
            magic, ver, obs_dim, acl = struct.unpack("<4sIII", f.read(16))
            if magic != b"MCDR" or ver != 3:
                raise SystemExit(f"{path}: 想定外の記録（{magic!r} 版 {ver}）")
            while True:
                h = f.read(REC_HEAD_V3.size)
                if not h:
                    break
                seed, _step, _turn, pi, _ph, n_acts, _ch, _z, _fr = REC_HEAD_V3.unpack(h)
                f.seek(obs_dim + n_acts * acl + 4 * n_acts, 1)
                c[(seed % 2, pi)] += 1
    return c


def check_schedule(sch: dict) -> None:
    blocks = sch.get("blocks") or []
    if not blocks:
        raise SystemExit("blocks が空")
    used = []
    for i, b in enumerate(blocks):
        for k in ("deck_a", "deck_b", "seed0", "n"):
            if k not in b:
                raise SystemExit(f"blocks[{i}] に {k} が無い")
        if int(b["n"]) < 1:
            raise SystemExit(f"blocks[{i}]: n は 1 以上")
        check_record_band(int(b["seed0"]))
        check_record_band(int(b["seed0"]) + int(b["n"]) - 1)
        opp = b.get("opponent", "teacher")
        if opp not in OPPONENTS:
            raise SystemExit(f"blocks[{i}]: 未知の相手 {opp}")
        rec = b.get("record", "both" if opp == "teacher" else "a")
        if rec not in ("both", "a", "b"):
            raise SystemExit(f"blocks[{i}]: record は both / a / b")
        if opp != "teacher" and rec != "a":
            raise SystemExit(f"blocks[{i}]: 教師以外が相手のブロックは record を a にすること"
                             "（記録する席を教師に固定・VALUE_BOOTSTRAP_DESIGN.md §6.3）")
        lo, hi = int(b["seed0"]), int(b["seed0"]) + int(b["n"]) - 1
        for j, (l2, h2) in enumerate(used):
            if lo <= h2 and l2 <= hi:
                raise SystemExit(f"blocks[{i}] のシード {lo}..{hi} が blocks[{j}] と重なる")
        used.append((lo, hi))


def run_block(i: int, b: dict, sch: dict, out: str, workers: int, max_turns: int, deck_cache: dict) -> dict:
    for name in (b["deck_a"], b["deck_b"]):
        if name not in deck_cache:
            deck_cache[name] = load_deck_file(name)
    da, _ = deck_cache[b["deck_a"]]
    db_, _ = deck_cache[b["deck_b"]]
    cfg = matchup_config(da, db_)
    cfg.validate()
    teacher = dict(sch.get("teacher") or {"name": "netfree"}, **(b.get("teacher") or {}))
    opp = b.get("opponent", "teacher")
    rec = b.get("record", "both" if opp == "teacher" else "a")
    # spec の opp_decklist は `opp_from_seat=True` で局ごとに差し替わる。ここでは仮に席 1 のデッキを入れる
    # （manifest に書くため。**実際に使われるのは相手の席の行動デッキ**）。
    spec_a = teacher_spec(teacher, db_["action_deck"], b["deck_a"], b["deck_b"])
    spec_b = opponent_spec(opp, teacher, da["action_deck"], b["deck_a"], b["deck_b"])
    seed0, n = int(b["seed0"]), int(b["n"])
    t = time.time()
    res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, spec_a, spec_b, seed0, n,
                                  f"{out}.b{i}", workers, max_turns, rec in ("both", "a"), rec in ("both", "b"),
                                  opp_from_seat=True)
    sec = time.time() - t
    dec = count_decisions(files)
    # 席 0 = deck_a。偶数シードは A が席 0。
    games = {"a_seat0": sum(1 for s in range(seed0, seed0 + n) if s % 2 == 0)}
    games["a_seat1"] = n - games["a_seat0"]
    decisions = {
        "a_as_deck_a": dec[(0, 0)], "a_as_deck_b": dec[(1, 1)],
        "b_as_deck_a": dec[(1, 0)], "b_as_deck_b": dec[(0, 1)],
    }
    decided = [r[0] for r in res if r[0] is not None]
    return {
        "i": i, "deck_a": b["deck_a"], "deck_b": b["deck_b"], "mirror": b["deck_a"] == b["deck_b"],
        "seed0": seed0, "n": n, "p_planned": b.get("p_planned"), "record": rec, "opponent": opp,
        "teacher": teacher, "spec_a": strip_paths(spec_a), "spec_b": strip_paths(spec_b),
        "nets": {**net_fingerprints(spec_a), **net_fingerprints(spec_b)},
        "games": games, "decisions": decisions, "decisions_total": sum(dec.values()),
        "a_won": (sum(decided) / len(decided) if decided else None), "decided": len(decided),
        "mean_turns": sum(r[1] for r in res) / len(res), "seconds": sec,
        "format": record_format(files), "files": files,
    }


def summarize(blocks: list, sch: dict, deck_cache: dict) -> dict:
    """デッキ別（抽出率）と相手の種類別（相手 AI の抽出率）を**別に**まとめる（§5.4）。"""
    # D-129 追記 1: `games` は**そのデッキが出た局数**（ミラーでも 1 局は 1 と数える）。
    # 席ごとの数は別の欄に分けた——`seat_games` = 席 × 局（ミラーは 2 つ埋まる）、
    # `seat_games_teacher` = そのうち教師が座った席（H・貪欲・素 planner が座った席を除く）。
    # 以前は `games` に席 × 局を入れていたので、ミラーと錨のブロックを 2 回数えていた。
    per_deck: dict = {}
    for b in blocks:
        teacher_b = b["opponent"] == "teacher"
        for side, key_a, key_b, a_seats in (("deck_a", "a_as_deck_a", "b_as_deck_a", b["games"]["a_seat0"]),
                                            ("deck_b", "a_as_deck_b", "b_as_deck_b", b["games"]["a_seat1"])):
            d = per_deck.setdefault(b[side], {"games": 0, "seat_games": 0, "seat_games_teacher": 0,
                                              "decisions_recorded": 0})
            d["seat_games"] += b["n"]
            d["seat_games_teacher"] += b["n"] if teacher_b else a_seats
            d["decisions_recorded"] += b["decisions"][key_a] + b["decisions"][key_b]
        for name in {b["deck_a"], b["deck_b"]}:
            per_deck[name]["games"] += b["n"]
    per_opp = Counter()
    for b in blocks:
        per_opp[b["opponent"]] += b["n"]
    meta = sch.get("decks") or {}
    decks = {}
    for name, (deck, sha) in sorted(deck_cache.items()):
        m = meta.get(name) or {}
        trio = sorted({CHARA_CARDS[c].name for c in deck["chara_deck"]})
        decks[name] = {"sha256": sha, "chara_trio": trio,
                       "lineage": m.get("lineage"), "group": m.get("group"), "split": m.get("split"),
                       **per_deck.get(name, {})}
    return {"decks": decks, "games_by_opponent": dict(per_opp)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-turns", type=int, default=200)
    args = ap.parse_args(argv)
    with open(args.schedule, "rb") as f:
        sch_raw = f.read()
    sch = json.loads(sch_raw.decode("utf-8"))
    check_schedule(sch)
    ensure_cards()
    if "opp_from_seat" not in rs.features():
        raise SystemExit("入っている meicho_rs が古い（opp_from_seat が無い）。再ビルドすること（D-123）")
    deck_cache: dict = {}
    t = time.time()
    blocks = [run_block(i, b, sch, args.out, args.workers, args.max_turns, deck_cache)
              for i, b in enumerate(sch["blocks"])]
    files = [p for b in blocks for p in b["files"]]
    manifest = {
        "tool": "experiments/record_mix.py", "stage": "1C-b", "decision": "D-123",
        "schedule_name": sch.get("name"), "schedule": sch,
        "schedule_sha256": hashlib.sha256(sch_raw).hexdigest(),
        "opp_decklist_known": True, "opp_from_seat": True,
        "rules_version": RULES_VERSION, "encoding_version": ENCODING_VERSION,
        "format": record_format(files), "workers": args.workers, "max_turns": args.max_turns,
        **summarize(blocks, sch, deck_cache),
        "blocks": blocks, "files": files, "seconds": time.time() - t,
        "regenerate": "python3 experiments/record_mix.py "
                      + " ".join(shlex.quote(a) for a in (argv if argv is not None else sys.argv[1:])),
    }
    path = args.out + ".manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: manifest[k] for k in ("schedule_name", "decks", "games_by_opponent", "seconds")},
                     ensure_ascii=False))
    print(f"\n★ {path} を**マスターの PC に書き戻すこと**（D-065 便 3）。組み合わせ表も一緒に持ち帰る"
          "（manifest に全文と sha256 が入っている）。")
    return manifest


if __name__ == "__main__":
    main()
