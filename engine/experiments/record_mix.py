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
  `"champion"`（そのプールの現 champion。**ネットが SD001 専用なので SD001 のミラーだけ**許す）／
  `"netfree_v"`（段階3・D-138: `NETFREE` の葉を `value_net` にしたもの。`value_net` は engine/ からの
  相対パスか絶対パス。`value_net_sha16`（sha256 の先頭 16 桁）を書けば、回す前にファイルと照合する）
- `teacher.tau`: 記録の温度（既定 0）。manifest には「argmax 以外を選んだ決定の割合」（`nonargmax`・
  D-064 §6.2 の τ の下見の尺度）をブロックごとと全体で書く
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


def resolve_value_net(teacher: dict) -> str:
    """教師 `netfree_v` の葉の V のパスを絶対パスに直し、有無と指紋を確かめる（D-138）。"""
    rel = teacher.get("value_net")
    if not rel:
        raise SystemExit("教師 netfree_v には value_net（葉の V のパス）が要る")
    path = rel if os.path.isabs(rel) else os.path.join(_HERE, "..", rel)
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise SystemExit(f"教師 netfree_v の value_net が無い: {rel}")
    want = teacher.get("value_net_sha16")
    if want:
        with open(path, "rb") as f:
            got = hashlib.sha256(f.read()).hexdigest()[:16]
        if got != want:
            raise SystemExit(f"教師 netfree_v の value_net の指紋が組み合わせ表と違う（{want} → {got}）: {rel}")
    return path


def teacher_spec(teacher: dict, pool: list, deck_a: str, deck_b: str) -> dict:
    name = teacher.get("name", "netfree")
    tau = float(teacher.get("tau", 0.0))
    extra = {"tau": tau} if tau else {}
    # 選んだ手を別の決定化で採点し直した値（記録の fresh 欄）を取る本数（D-148 (b)・既定 0 = 取らない）。
    # 取り直しは別の乱数を使うので打ち方は変わらない（D-065 便 4 の案 C・検査 R-1）
    reeval = int(teacher.get("reeval_samples", 0))
    if reeval < 0:
        raise SystemExit("reeval_samples は 0 以上")
    if reeval:
        extra["reeval_samples"] = reeval
    if name == "netfree":
        return PLANNER(pool, **NETFREE, **extra)
    if name == "netfree_v":
        return PLANNER(pool, **NETFREE, value_net=resolve_value_net(teacher), **extra)
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


def nonargmax_stats(files) -> dict:
    """記録から「argmax 以外を選んだ決定の割合」を数える（D-064 §6.2 の τ の下見の尺度・D-138）。

    合法手が 2 つ以上の決定だけを分母にする（`multi`）。選んだ手の点数が最大点より小さい決定を `off` と数える
    （同点の最大が複数あるとき、そのどれを選んでも argmax とみなす）。点数の NaN（評価していない手）は最大点から除き、
    選んだ手の点数が NaN なら `off` と数える。
    **τ = 0 でも 0 にはならない**: 終盤の総当たり（`endgame_enum`）の投票が勝つと、平均点の最大ではない手を指す
    （`rust/src/agents.rs` の `vote_pick`・段 C-3）。下見では τ = 0 の値を基準として並べて読む。
    """
    multi = off = 0
    for path in files:
        with open(path, "rb") as f:
            magic, ver, obs_dim, acl = struct.unpack("<4sIII", f.read(16))
            if magic != b"MCDR" or ver != 3:
                raise SystemExit(f"{path}: 想定外の記録（{magic!r} 版 {ver}）")
            while True:
                h = f.read(REC_HEAD_V3.size)
                if not h:
                    break
                n_acts, ch = REC_HEAD_V3.unpack(h)[5:7]
                f.seek(obs_dim + n_acts * acl, 1)
                sc = struct.unpack(f"<{n_acts}f", f.read(4 * n_acts))
                if n_acts > 1:
                    multi += 1
                    fin = [x for x in sc if x == x]
                    off += (sc[ch] != sc[ch]) or (bool(fin) and sc[ch] < max(fin))
    return {"multi": multi, "off": off, "rate": (off / multi if multi else None)}


def _sum_nonargmax(stats) -> dict:
    stats = list(stats)
    multi = sum(s["multi"] for s in stats)
    off = sum(s["off"] for s in stats)
    return {"multi": multi, "off": off, "rate": (off / multi if multi else None)}


def check_schedule(sch: dict) -> None:
    blocks = sch.get("blocks") or []
    if not blocks:
        raise SystemExit("blocks が空")
    for t in [sch.get("teacher") or {}] + [b.get("teacher") or {} for b in blocks]:
        if dict(sch.get("teacher") or {}, **t).get("name") == "netfree_v":
            resolve_value_net(dict(sch.get("teacher") or {}, **t))
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
        if rec not in ("both", "a", "b", "deck_a"):
            raise SystemExit(f"blocks[{i}]: record は both / a / b / deck_a")
        if rec == "deck_a" and opp != "teacher":
            raise SystemExit(f"blocks[{i}]: record=deck_a は教師どうしのブロックだけ（錨は教師の席を a で記録する）")
        if opp != "teacher" and rec != "a":
            raise SystemExit(f"blocks[{i}]: 教師以外が相手のブロックは record を a にすること"
                             "（記録する席を教師に固定・VALUE_BOOTSTRAP_DESIGN.md §6.3）")
        lo, hi = int(b["seed0"]), int(b["seed0"]) + int(b["n"]) - 1
        for j, (l2, h2) in enumerate(used):
            if lo <= h2 and l2 <= hi:
                raise SystemExit(f"blocks[{i}] のシード {lo}..{hi} が blocks[{j}] と重なる")
        used.append((lo, hi))


def run_block(i: int, b: dict, sch: dict, out: str, workers: int, max_turns: int, deck_cache: dict,
              leaf_cap: int = 0) -> dict:
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
    # 葉の書き出し（段階3 項目 4・D-151）: 記録する決定ごとに探索が V を呼んだ局面を最大 leaf_cap 個。
    # 打ち方は変わらない（検査 L-2）。0 なら従来と同じ呼び方
    kw = {"leaf_dump": f"{out}.b{i}.leaf", "leaf_cap": leaf_cap} if leaf_cap else {}
    # 段階4（D-154）: record=deck_a は deck_a の席（席 0）だけを記録する。エージェントは奇数シードで席を
    # 入れ替えるので、a（エージェント A の席）では半分の局で deck_b 側を記録してしまう
    if rec == "deck_a":
        if "record_seats" not in rs.features():
            raise SystemExit("入っている meicho_rs が古い（record_seats が無い）。再ビルドすること（D-154）")
        kw["record_seats"] = (True, False)
    res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, spec_a, spec_b, seed0, n,
                                  f"{out}.b{i}", workers, max_turns, rec in ("both", "a"), rec in ("both", "b"),
                                  opp_from_seat=True, **kw)
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
    extra = {"leaf_files": [f"{out}.b{i}.leaf.{w}" for w in range(max(1, workers))]} if leaf_cap else {}
    return {
        "i": i, "deck_a": b["deck_a"], "deck_b": b["deck_b"], "mirror": b["deck_a"] == b["deck_b"],
        "seed0": seed0, "n": n, "p_planned": b.get("p_planned"), "record": rec, "opponent": opp,
        "teacher": teacher, "spec_a": strip_paths(spec_a), "spec_b": strip_paths(spec_b),
        "nets": {**net_fingerprints(spec_a), **net_fingerprints(spec_b)},
        "games": games, "decisions": decisions, "decisions_total": sum(dec.values()),
        "a_won": (sum(decided) / len(decided) if decided else None), "decided": len(decided),
        "mean_turns": sum(r[1] for r in res) / len(res), "seconds": sec,
        "nonargmax": nonargmax_stats(files),
        "format": record_format(files), "files": files, **extra,
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
    ap.add_argument("--leaf-cap", type=int, default=0,
                    help="葉の書き出し（D-151）: 記録する決定ごとに V を呼んだ局面を最大この数だけ <out>.b<i>.leaf.<w> に。0 = 書かない")
    args = ap.parse_args(argv)
    with open(args.schedule, "rb") as f:
        sch_raw = f.read()
    sch = json.loads(sch_raw.decode("utf-8"))
    check_schedule(sch)
    ensure_cards()
    if "opp_from_seat" not in rs.features():
        raise SystemExit("入っている meicho_rs が古い（opp_from_seat が無い）。再ビルドすること（D-123）")
    if args.leaf_cap and "leaf_dump" not in rs.features():
        raise SystemExit("入っている meicho_rs が古い（leaf_dump が無い）。再ビルドすること（D-151）")
    if args.leaf_cap < 0:
        raise SystemExit("--leaf-cap は 0 以上")
    deck_cache: dict = {}
    t = time.time()
    blocks = [run_block(i, b, sch, args.out, args.workers, args.max_turns, deck_cache, args.leaf_cap)
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
        "nonargmax": _sum_nonargmax(b["nonargmax"] for b in blocks),
        "blocks": blocks, "files": files, "seconds": time.time() - t,
        **({"leaf_cap": args.leaf_cap} if args.leaf_cap else {}),
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
