"""C-1 §4.1-1 学習データ生成（自己対戦 → 局面列 ＋ 最終勝敗ラベル）。

rules_draft.md v0.10 準拠 / engine v0.1。

## 何を作るか

自己対戦を回し、**各ターン開始時（アクションフェイズに入った瞬間）の
両プレイヤーの観測**を1件ずつ記録し、その対局の最終勝敗をラベルにする。
出力は gzip 圧縮された JSON Lines と、再現に必要な条件を書いたマニフェスト。

## 設計の要点

**記録するのは `engine.observe(s, pi)` であり、`GameState` ではない。**
`observe` はこのプロジェクトにおける「pi に見えてよい情報」の定義そのもの
（§4 / §10、スキャン効果の `hand_known` を含む）なので、これを保存単位にすると
**覗き見の禁止 (D-026) が保存形式のレベルで構造的に保証される**。
学習側がうっかり隠蔽情報を触ることが原理的にできない。
特徴設計を後から変えても、観測が残っていれば再抽出できる。

**ラベルは最終勝敗（勝ち1.0 / 引き分け0.5 / 負け0.0）を pi 視点で付ける。**
まず最も単純な形にする（§4.1-1）。TD 系の目標値に替えたくなったら、
同じ観測列から後で作れるように `turn_no` と `turns_total` を併記してある。

**分割は対局単位ではなくシード帯単位で行う。** 同一対局から採った局面は
強く相関するので対局単位の分割は必須だが、帯を分ければそれより強い分離になる
（D-028 の探索と検証の分離をデータ生成にも適用する）。
train = 90000..、valid = 100000..（`seed_bands.json` に登録済み）。

**相手構成は planner 中心**（マスターの判断, 2026-08-24）。champion が実際に
到達する局面に密度を寄せ、多様性のために H / 貪欲 / 摂動H を混ぜる。
定義は `experiments/datasets/*.json` にデータとして持つ（C-4 と同じ流儀。
スクリプトにベタ書きすると生成のたびに条件がずれる）。

**シードは重複させない。** 対戦組ごとに定義の順序で決定的に連番を割り当て、
マニフェストに記録する。同じ定義・同じ帯なら何度回しても同じデータになる。

実行:
    python3 experiments/gendata.py c1_v1 --workers 2
    python3 experiments/gendata.py c1_v1 --split valid --workers 2
    python3 experiments/gendata.py c1_v1 --dry-run       # 割り当てと見積りだけ
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from arena import load_deck, mirror_config                       # noqa: E402
from meicho.version import ENGINE_VERSION, RULES_VERSION         # noqa: E402  D-117
from registry import make                                        # noqa: E402
from meicho.engine import (apply, decision_players, initial_state,  # noqa: E402
                           observe, outcome)
from meicho.state import DRAW, Phase                             # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFS = os.path.join(_HERE, "datasets")
OUT = os.path.join(_HERE, "..", "results", "datasets")

WIN, LOSS, TIE = 1.0, 0.0, 0.5


# --------------------------------------------------------------- 定義の読み込み
def load_def(name: str) -> dict:
    with open(os.path.join(DEFS, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def def_hash(d: dict) -> str:
    """定義の正規化ハッシュ。1文字でも変われば別のデータセットとして記録される。"""
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def plan(d: dict, split: str) -> list:
    """対戦組へのシード割り当て。定義の順序で決定的に連番を配る。

    戻り値 [{"a","b","games","seed0"}]。帯をまたがないことを検査する。
    """
    sp = d["splits"][split]
    base, scale = sp["seed_band"], sp.get("scale", 1.0)
    out, cur = [], base
    for m in d["matchups"]:
        n = max(1, int(round(m["games"] * scale)))
        out.append({"a": m["a"], "b": m["b"], "games": n, "seed0": cur})
        cur += n
    span = cur - base
    if span > 10_000:
        raise ValueError(f"シード帯 {base}.. をはみ出す（{span} 局）。帯を足すこと")
    return out


def check_band(split_band: int) -> None:
    """`seed_bands.json` の台帳に登録済みで、評価専用帯でないことを確かめる。

    D-028/D-034: 未登録帯や ladder 帯（80000..）での生成は事故なので止める。
    """
    with open(os.path.join(_HERE, "seed_bands.json"), encoding="utf-8") as f:
        led = json.load(f)
    for b in led["bands"]:
        if b["start"] <= split_band <= b["end"]:
            if b["kind"] == "ladder":
                raise ValueError(
                    f"帯 {split_band} は評価専用（{b['purpose']}）。学習に使ってはならない")
            return
    raise ValueError(
        f"帯 {split_band} は seed_bands.json に未登録。台帳に追記してから使うこと")


# --------------------------------------------------------------- 1局ぶんの収集
def _record_game(config, agents, seed, agent_names, max_turns=200) -> dict:
    """1局を回し、各ターン開始時の両者の観測を集める。

    `runner.play_game` を写した形だが、**観測の採取のためだけに**分岐を足してある。
    採取は `observe`（純粋関数）を呼ぶだけで、状態にもエージェントの乱数にも
    触れない。したがって同じシードなら play_game と同一の対局になる。
    """
    s = initial_state(config, seed)
    rows, seen_turn = [], -1
    steps = 0
    while outcome(s) is None:
        if s.turn_no > max_turns:
            return {"aborted": True, "rows": [], "turns": s.turn_no}
        # ターン開始（アクションフェイズに入った最初の時点）で両者ぶん採る。
        # 対抗や選択の途中は同一ターン内で強く相関するので採らない（§4.1-1）。
        if s.phase == Phase.ACTION and s.turn_no != seen_turn:
            seen_turn = s.turn_no
            for pi in (0, 1):
                rows.append({"turn_no": s.turn_no, "seat": pi,
                             "turn_player": s.turn_player,
                             "agent": agent_names[pi],
                             "obs": observe(s, pi)})
        need = decision_players(s)
        s = apply(s, {pi: agents[pi].act(s, pi) for pi in need})
        steps += 1
    res = outcome(s)
    is_draw = (res == DRAW)
    for r in rows:
        r["z"] = TIE if is_draw else (WIN if res == r["seat"] else LOSS)
        r["turns_total"] = s.turn_no
    return {"aborted": False, "rows": rows, "turns": s.turn_no,
            "winner": None if is_draw else res, "draw": is_draw}


def _one(job):
    """ワーカ本体。pickle 可能な引数だけを受ける（`registry.Mk` を使う）。"""
    mk_a, mk_b, name_a, name_b, config, seed = job
    flip = seed % 2                    # 奇数シードで a が後攻。席の偏りを消す
    if flip:
        agents = [mk_b(seed * 2), mk_a(seed * 2 + 1)]
        names = [name_b, name_a]
    else:
        agents = [mk_a(seed * 2), mk_b(seed * 2 + 1)]
        names = [name_a, name_b]
    r = _record_game(config, agents, seed, names)
    matchup = f"{name_a}_vs_{name_b}"
    for row in r["rows"]:
        row["seed"] = seed
        row["matchup"] = matchup
    # 集計はワーカ側で畳んでおく（親には小さな要約だけ返し、行はストリーム書き出し）
    seat_a = 1 if flip else 0
    summary = {"matchup": matchup, "aborted": r["aborted"],
               "draw": r.get("draw", False), "rows": len(r["rows"]),
               "turns": r["turns"],
               "a_won": (not r["aborted"] and not r.get("draw", False)
                         and r.get("winner") == seat_a)}
    return {"rows": r["rows"], "summary": summary}


# --------------------------------------------------------------- 生成
def generate(name: str, split: str, workers: int, dry: bool = False) -> dict:
    d = load_def(name)
    h = def_hash(d)
    band = d["splits"][split]["seed_band"]
    check_band(band)
    jobs_by_matchup = plan(d, split)

    deck = load_deck(d["deck"])
    if d.get("mode", "mirror") != "mirror":
        raise NotImplementedError("現状は同型戦（mirror）のみ")
    config = mirror_config(deck)
    pool = deck["action_deck"]
    mks = {k: make(v["factory"], v.get("kwargs"), pool)
           for k, v in d["agents"].items()}

    total_games = sum(m["games"] for m in jobs_by_matchup)
    print(f"定義 {name} (hash {h}) / split={split} / 帯 {band}.. / "
          f"{total_games} 局 / workers={workers}")
    for m in jobs_by_matchup:
        print(f"  {m['a']:>8} vs {m['b']:<8} {m['games']:>4} 局  "
              f"seed {m['seed0']}..{m['seed0'] + m['games'] - 1}")
    if dry:
        return {"dry_run": True, "games": total_games}

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{name}_{split}.jsonl.gz")
    jobs = []
    for m in jobs_by_matchup:
        for seed in range(m["seed0"], m["seed0"] + m["games"]):
            jobs.append((mks[m["a"]], mks[m["b"]], m["a"], m["b"], config, seed))

    t0 = time.perf_counter()
    n_rows = n_games = n_abort = n_draw = 0
    per_matchup, wins_a = {}, {}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                summaries = list(_stream(ex.map(_one, jobs, chunksize=2), f))
        else:
            summaries = list(_stream((_one(j) for j in jobs), f))
    for sm in summaries:
        n_games += 1
        if sm["aborted"]:
            n_abort += 1
            continue
        n_draw += bool(sm["draw"])
        n_rows += sm["rows"]
        mu = sm["matchup"]
        per_matchup[mu] = per_matchup.get(mu, 0) + sm["rows"]
        if not sm["draw"]:
            w, n = wins_a.get(mu, (0, 0))
            wins_a[mu] = (w + bool(sm["a_won"]), n + 1)
    dt = time.perf_counter() - t0

    man = {
        "dataset": name, "split": split, "def_hash": h,
        "definition": d, "seed_band": band,
        "assignment": jobs_by_matchup,
        "rules_version": RULES_VERSION, "engine_version": ENGINE_VERSION,   # D-117
        "games": n_games, "aborted": n_abort, "draws": n_draw,
        "rows": n_rows, "rows_per_matchup": per_matchup,
        "win_rate_a": {k: {"wins": w, "n": n, "p": (w / n if n else None)}
                       for k, (w, n) in sorted(wins_a.items())},
        "seconds": round(dt, 1),
        "bytes": os.path.getsize(path),
        "path": os.path.relpath(path, os.path.join(_HERE, "..")),
    }
    mpath = os.path.join(OUT, f"{name}_{split}.manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)

    print(f"\n{n_rows} 件 / {n_games} 局（打ち切り {n_abort}・引き分け {n_draw}）"
          f" / {dt:.1f} 秒 / {man['bytes'] / 1e6:.1f} MB")
    print(f"  {path}")
    print(f"  {mpath}")
    return man


def _stream(results, f):
    """行は届いた順に書き出し、親には小さな要約だけ渡す（全件を溜めない）。"""
    for r in results:
        for row in r["rows"]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        yield r["summary"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--split", default="train")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    generate(a.dataset, a.split, a.workers, a.dry_run)


if __name__ == "__main__":
    main()
