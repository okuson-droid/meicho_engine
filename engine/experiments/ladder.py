"""恒久評価インフラ: ガントレット総当たり → Bradley-Terry/Elo → ladder.json 追記（C-4 / D-034）。

使い方:
    python3 experiments/ladder.py core5 [--workers 2] [--n-scale 1.0] [--dry-run]

- ガントレット定義は experiments/gauntlets/<name>.json（データ。コードに書かない）。
- シード帯は experiments/seed_bands.json に「ladder」として登録済みでなければ拒否する。
- 結果は results/ladder.json に追記し、results/ladder.md に最新ランの表を書く。
- 同じ定義・同じコードなら workers に依らず同じ pairs が得られる（arena.py の不変条件）。

不変条件（作業規約6 / D-006 / D-028）:
- 全ペアが同じシード列 seed_band..seed_band+n-1 を使う（共通乱数）。
- 勝率・Elo は必ず対戦数と 95% 区間を伴う。
- champion は自動では更新しない。候補を表示するだけ（判断は人が行う）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import (Result, load_deck, mirror_config, matchup_config,        # noqa: E402
                   series, series_detail)
from registry import make                                            # noqa: E402
import rating                                                        # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
GAUNTLET_DIR = os.path.join(_HERE, "gauntlets")
SEED_BANDS = os.path.join(_HERE, "seed_bands.json")
RESULTS_JSON = os.path.join(_HERE, "..", "results", "ladder.json")
RESULTS_MD = os.path.join(_HERE, "..", "results", "ladder.md")
RULES_VERSION = "v0.10"
ENGINE_VERSION = "0.1"
JST = timezone(timedelta(hours=9))


# --- 定義の読み込みと検査 ---------------------------------------------------

def load_gauntlet(name: str) -> dict:
    with open(os.path.join(GAUNTLET_DIR, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def gauntlet_hash(g: dict) -> str:
    """定義の正規化ハッシュ。キー順に依らず、値が 1 つでも違えば変わる。"""
    s = json.dumps(g, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def load_seed_bands(path: str = SEED_BANDS) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_seed_band(seed0: int, bands: dict) -> dict:
    """seed0 を含む帯が ladder 用として登録済みであることを検査し、その帯を返す。"""
    for b in bands["bands"]:
        if b["start"] <= seed0 <= b["end"]:
            if b.get("kind") != "ladder":
                raise ValueError(
                    f"シード {seed0} は帯 {b['start']}..{b['end']}（{b['purpose']}）に"
                    f"属し、ラダー用ではない（D-028）")
            return b
    raise ValueError(f"シード {seed0} はどの帯にも登録されていない。"
                     f"seed_bands.json に追記してから使うこと（D-028）")


def pair_n(g: dict, a: str, b: str, scale: float = 1.0) -> int:
    ag = g["agents"]
    n = min(g["n_default"], ag[a].get("n_cap", g["n_default"]),
            ag[b].get("n_cap", g["n_default"]))
    return max(1, int(round(n * scale)))


def build_config(g: dict):
    if g["mode"] == "mirror":
        return mirror_config(load_deck(g["deck"]))
    if g["mode"] == "matchup":
        d0, d1 = g["deck"]
        return matchup_config(load_deck(d0), load_deck(d1))
    raise ValueError(f"未対応の mode: {g['mode']}")


# --- Rust 版で回すための仕様（D-065 便 4・マスター裁定 2026-09-06） ----------
#
# ラダーは Python 版のエージェントで回っていた。Rust 移植（D-049）より前に作られたからである。
# **実装は毎手一致で固定されている**（`tests/test_rust_agents.py` / `tests/test_rust_engine.py`）ので、
# Rust 版で回しても出る数字は同じで、ずっと速い（重い組で約 4 倍）。
#
# ただし **`mcts` には Rust 版が無い**。その組だけ Python 版で回す（`engine="auto"`）。
# **どちらで測った組かは 1 組ずつ記録する**（あとから素性を追えるように）。
#
# なお「同じ数字が出る」は信じるのではなく**確かめて使う**こと。
# `experiments/check_ladder_engines.py` が、済んだ組を両方の実装で測り直して突き合わせる。
_RUST_KIND = {
    "random": "random", "heuristic": "heuristic", "greedy": "greedy",
    "planner": "planner", "planner_pi": "planner", "planner_vb": "planner",
    "planner_v": None, "mcts": None, "mcts_v": None,     # Rust 版が無いもの
}
_NET_KEYS = ("value_net", "policy_net", "opp_policy_net", "net")


def rust_spec(factory: str, kwargs: dict | None, pool: list) -> dict | None:
    """factory ＋ kwargs を Rust 版の spec に写す。写せないものは None。"""
    kind = _RUST_KIND.get(factory)
    if kind is None:
        return None
    from meicho.drlnet import resolve_model
    kw = dict(kwargs or {})
    for k in _NET_KEYS:
        if isinstance(kw.get(k), str):
            kw[k] = resolve_model(kw[k])       # Rust 側はファイルの置き場所を知らない
    sp = {"kind": kind, **kw}
    if kind in ("greedy", "planner"):
        sp["opp_decklist"] = pool
    return sp


def build_rust_specs(g: dict) -> dict:
    """名前 → Rust 版の spec（写せないものは None）。"""
    deck = load_deck(g["deck"] if g["mode"] == "mirror" else g["deck"][0])
    pool = deck["action_deck"]
    return {name: rust_spec(sp["factory"], sp.get("kwargs"), pool)
            for name, sp in g["agents"].items()}


def build_agents(g: dict) -> dict:
    deck = load_deck(g["deck"] if g["mode"] == "mirror" else g["deck"][0])
    pool = deck["action_deck"]
    return {name: make(spec["factory"], spec.get("kwargs"), pool)
            for name, spec in g["agents"].items()}


def provenance_for(g: dict, engine: str, seed0: int, n_scale: float = 1.0,
                   workers: int = 1) -> dict:
    """ガントレットの各体の由来（D-2 / D-3）。**回す前に作る**（`REPORTING_RULES.md` §2.8）。

    ラダーは「誰がいちばん強いか」を決める道具なので、**各体が何を積んでいたか**が
    後から検証できないと順位に意味が無くなる。名前だけでは足りない
    ——同じ `drl_sd001_vb3.json` でも中身が違えば別の体である。
    """
    import provenance
    names = list(g["agents"])
    n = max(pair_n(g, a, b, n_scale) for a in names for b in names if a != b)
    band = provenance.band_of(seed0, n)
    eng = "python" if engine == "python" else "rust"
    # D-072 判断 6: どの機械で・何並列で回したかを由来に残す（`COMPUTE_PLAN` §5-3）。
    # 結果は機械によらない（シードごとに決定的）が、**速さの数字は機械と workers とセット**。
    return {name: provenance.block(sp.get("kwargs") or {}, eng, band,
                                   extra={"factory": sp["factory"], "agent": name,
                                          "host": provenance.host_name(),
                                          "workers": int(workers)})
            for name, sp in g["agents"].items()}


# --- 実行 -------------------------------------------------------------------

def _load_resume(path: str, g: dict, n_scale: float) -> dict:
    """途中経過を読む（無ければ空で作る）。**定義が違うファイルには混ぜない。**

    混ぜると「別物の寄せ集め」になり、しかもそれが表に出ない種類の事故になる。
    """
    want = {"gauntlet": g["name"], "hash": gauntlet_hash(g), "n_scale": n_scale}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
        for k, v in want.items():
            if st.get(k) != v:
                raise SystemExit(
                    f"途中経過 {path} は今の定義と食い違う（{k}: {st.get(k)!r} ≠ {v!r}）。"
                    f"別のラダーの途中経過に混ぜてはいけない。続きから回すなら定義を戻すか、"
                    f"やり直すならこのファイルを消すこと")
        return st
    return dict(want, pairs=[], sec=0.0)


def load_reusable(path: str, run_ref: str, g: dict, n_scale: float,
                  seed0: int) -> tuple[list, dict]:
    """前の記録から**そのまま使い回せる組**を拾う（便 C の交代判定・D-077 追記 5）。

    なぜ使い回せるか: どの組も同じ `seed0` から始め、**同じシードは同じ対局**である。
    体の定義（factory と kwargs）が 1 文字も変わっておらず、デッキ・モード・局数・
    シードが同じなら、回し直しても 1 局も違わない。実際に 4 組（いちばん軽い組から
    ネットを 3 本使う重い組まで）を回し直して**勝敗が完全に一致する**ことを確かめてある。

    **だから使い回してよいのは「体が 1 文字も変わっていない組」だけである。**
    ここが緩むと「別物の寄せ集め」になり、しかも表に出ない種類の事故になる
    （`_load_resume` が守っているのと同じ線）。次のどれか 1 つでも違えば拾わない:

    - その体が新しいガントレットに居ない／`factory` か `kwargs` が違う
    - デッキかモードが違う
    - その組の局数（`pair_n`）か `seed0` が違う

    `run_ref` は記録の `run_id`、または `results/ladder.json` の添字（`-1` で最新）。
    戻り値は `(使い回せる組のリスト, 由来のメモ)`。組には `reused_from` を足してある
    （記録に残すため。**足すだけで既存の鍵は変えない**）。
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    try:
        old = data[int(run_ref)]
    except (ValueError, TypeError):
        hits = [d for d in data if d.get("run_id") == run_ref]
        if not hits:
            raise SystemExit(f"run_id {run_ref!r} の記録が {path} に無い")
        old = hits[-1]
    why: dict = {}
    def spec_same(name: str) -> bool:
        o = (old.get("agents") or {}).get(name)
        n_ = (g.get("agents") or {}).get(name)
        if o is None or n_ is None:
            return False
        return (o.get("factory") == n_.get("factory")
                and (o.get("kwargs") or {}) == (n_.get("kwargs") or {}))
    same_deck = (old.get("deck") == g.get("deck") and old.get("mode") == g.get("mode"))
    ok, skipped = [], []
    for p in old.get("pairs", []):
        a, b = p["a"], p["b"]
        if not same_deck:
            skipped.append((a, b, "デッキかモードが違う")); continue
        if not (spec_same(a) and spec_same(b)):
            skipped.append((a, b, "体の定義が違う（または居ない）")); continue
        if p.get("seed0") != seed0:
            skipped.append((a, b, f"seed0 が違う（{p.get('seed0')} ≠ {seed0}）")); continue
        if p.get("n") != pair_n(g, a, b, n_scale):
            skipped.append((a, b, "局数が違う")); continue
        q = dict(p)
        q["reused_from"] = old.get("run_id")
        ok.append(q)
    why = {"run_id": old.get("run_id"),
           "gauntlet_version": old.get("gauntlet_version"),
           "rules_version": old.get("rules_version"),
           "reused": len(ok), "skipped": len(skipped),
           "skipped_reasons": sorted({r for _, _, r in skipped})}
    return ok, why


def run_gauntlet(g: dict, workers: int = 1, n_scale: float = 1.0,
                 bands: dict | None = None, verbose: bool = True,
                 resume_path: str | None = None, budget_sec: float | None = None,
                 block: int = 50, engine: str = "python",
                 reuse: list | None = None, reuse_meta: dict | None = None,
                 reuse_verify: set | None = None):
    """総当たりを回し、記録 1 件（dict）を返す。ファイルには書かない。

    `resume_path` を渡すと**途中経過を保存し、次に呼んだとき続きから回す**（D-065 便 4）。
    `budget_sec` を渡すとその秒数を超えた時点で戻る。
    **まだ全部そろっていなければ `None` を返す**（半端な結果で Elo を出さないため）。

    `reuse` に前の記録から拾った組（`load_reusable`）を渡すと、**その組は回さない**。
    `reuse_verify` に `(a, b)` を入れると、使い回せる組でも**わざと回し直して
    記録と突き合わせ、1 局でも違えばそこで止める**（抜き取り検査）。

    止まれる粒度は `block` 局ごと——**組の途中でも止まれる**。組の切れ目でしか止まれないと、
    1 組で 20 分かかる組（重い探索器どうし・300 局）が作業環境の上限に収まらない。

    途中で止めても答えが変わらないのは、`series` が**シードごとに独立な対局の合計**であり、
    どの組も同じ `seed0` から始めるからである（同じシードは同じ対局）。
    `tests/test_ladder.py` の 2 つの検査がこれを固定する。
    """
    bands = bands or load_seed_bands()
    band = check_seed_band(g["seed_band"], bands)
    names = list(g["agents"])
    seed0 = g["seed_band"]
    max_n = max(pair_n(g, a, b, n_scale) for a in names for b in names if a != b)
    if seed0 + max_n - 1 > band["end"]:
        raise ValueError("対戦数がシード帯の幅を超える")
    if engine not in ("python", "rust", "auto"):
        raise SystemExit(f"未対応の --engine: {engine!r}（python / rust / auto）")
    config = build_config(g)
    # 由来は**回す前**に作る（D-2 / D-3）。終わってから作ると、途中で差し替えても分からない。
    prov = provenance_for(g, engine, seed0, n_scale, workers)
    mk = build_agents(g)
    rspec = build_rust_specs(g) if engine in ("rust", "auto") else {}
    if engine == "rust":
        missing = [n for n, v in rspec.items() if v is None]
        if missing:
            raise SystemExit(f"Rust 版が無いエージェントがいる: {missing}（--engine auto を使うこと）")
    t0 = time.time()
    st = _load_resume(resume_path, g, n_scale) if resume_path else {"pairs": [], "sec": 0.0}
    pairs = list(st["pairs"])
    done = {(p["a"], p["b"]) for p in pairs}
    # 使い回し（D-077 追記 5）。抜き取り検査に指定した組は**拾わずに回し直す**。
    verify = {tuple(sorted(t)) for t in (reuse_verify or set())}
    want = {}
    for p in (reuse or []):
        key = (p["a"], p["b"])
        if key in done:
            continue
        if tuple(sorted(key)) in verify:
            want[key] = (p["wins_a"], p["decided"])     # 回し直して突き合わせる
            continue
        pairs.append(p)
        done.add(key)
    todo = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if (a, b) not in done]
    if verbose and reuse:
        print(f"  （使い回し: {len(reuse)} 組のうち {len(pairs) - len(st['pairs'])} 組を採用・"
              f"抜き取り検査 {len(want)} 組は回し直す）", flush=True)
    if verbose and resume_path and st["pairs"]:
        print(f"  （続きから: 済み {len(st['pairs'])} 組）", flush=True)
    if verbose:
        print(f"  （回す組: {len(todo)}）", flush=True)
    total_pairs = len(names) * (len(names) - 1) // 2
    # **予算はこの呼び出しの経過時間で数える**（`t0` は保存のたびに動かさないこと。
    #  一度そう書いて「いつまでも止まらない」不具合を作った）。
    t_call = time.time()
    def _save():
        if not resume_path:
            return
        nonlocal t_call
        st["pairs"] = pairs
        st["sec"] = st.get("sec", 0.0) + (time.time() - t_call)
        t_call = time.time()
        os.makedirs(os.path.dirname(os.path.abspath(resume_path)) or ".", exist_ok=True)
        with open(resume_path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)

    out_of_time = False
    for a, b in todo:
        n = pair_n(g, a, b, n_scale)
        pt = st.get("partial")
        if pt and (pt["a"], pt["b"]) == (a, b) and pt["n"] == n:
            wins, dec, games = pt["wins"], pt["decided"], pt["games"]
            seats = pt.get("seats") or [0, 0, 0, 0]
        else:
            wins, dec, games = 0.0, 0, 0
            # [席 0 での a の勝ち, 席 0 での決着数, 席 1 での a の勝ち, 席 1 での決着数]
            seats = [0, 0, 0, 0]
        use_rust = engine != "python" and rspec.get(a) is not None and rspec.get(b) is not None
        while games < n:
            k = min(max(1, block), n - games)
            # **席別に数えるため各局の結果を受け取る**（D-5・便 D 後半）。
            # 回す対局は従来と 1 局も変わらない（`series` は合計を返すだけの版である）。
            if use_rust:
                from arena_rs import ensure_cards, series_rs_detail
                ensure_cards()
                det = [x[0] for x in series_rs_detail(rspec[a], rspec[b], k, config,
                                                      workers, seed0 + games)]
            else:
                det = series_detail(mk[a], mk[b], k, config, workers, seed0 + games)
            for i, v in enumerate(det):
                if v is None:
                    continue
                won = bool(v)
                wins += 1 if won else 0
                dec += 1
                # a の席はシードの偶奇（偶数なら a が席 0）
                off = 0 if (seed0 + games + i) % 2 == 0 else 2
                seats[off] += 1 if won else 0
                seats[off + 1] += 1
            games += k
            if games < n:
                st["partial"] = {"a": a, "b": b, "n": n,
                                 "wins": wins, "decided": dec, "games": games,
                                 "seats": seats}
                _save()
                if budget_sec is not None and time.time() - t0 > budget_sec:
                    out_of_time = True
                    break
        if out_of_time:
            break
        r = Result(wins, dec, n)
        rec = {"a": a, "b": b, "n": n, "wins_a": r.wins, "decided": r.decided,
               "p": r.p, "ci": r.ci, "seed0": seed0,
               "engine": "rust" if use_rust else "python",
               # 席別（D-5）。既存の鍵は変えず、**足すだけ**にしてある。
               "wins_a_seat0": seats[0], "decided_a_seat0": seats[1],
               "wins_a_seat1": seats[2], "decided_a_seat1": seats[3]}
        if (a, b) in want:
            w0, d0 = want[(a, b)]
            if (r.wins, r.decided) != (w0, d0):
                # **ここで止める。** 使い回しの前提（同じシードは同じ対局）が崩れている以上、
                # 拾ってきた組も信用できない。黙って進めると「別物の寄せ集め」になる。
                raise SystemExit(
                    f"抜き取り検査が合わない: {a} vs {b} は記録が {w0:.0f}/{d0} なのに "
                    f"回し直すと {r.wins:.0f}/{r.decided} になった。"
                    f"体の定義かルールかエンジンが変わっている。"
                    f"使い回しをやめて（--reuse-from を外して）全部回し直すこと")
            rec["reuse_verified"] = True
            if verbose:
                print(f"    抜き取り検査 一致: {a} vs {b} = {r.wins:.0f}/{r.decided}", flush=True)
        pairs.append(rec)
        st.pop("partial", None)
        _save()
        if verbose:
            print(f"  {a:>14} vs {b:<14} {r}   [{len(pairs)}/{total_pairs}]", flush=True)
        if budget_sec is not None and time.time() - t0 > budget_sec:
            break
    if len(pairs) < total_pairs:
        if verbose:
            print(f"  → 途中（{len(pairs)}/{total_pairs} 組）。同じコマンドで続きから回せる", flush=True)
        return None
    t0 = t0 - st.get("sec", 0.0)          # 経過時間は再開ぶんも足す
    anchor = g["anchor"]
    ratings = rating.bootstrap_elo(names, pairs, anchor["agent"], anchor["elo"])
    cycles = rating.find_cycles(names, pairs)
    cands = rating.champion_candidates(pairs, g["champion"])
    now = datetime.now(JST)
    return {
        "run_id": f"{now.strftime('%Y-%m-%dT%H:%M:%S%z')}/{g['name']}",
        "date": now.isoformat(),
        "gauntlet": g["name"], "gauntlet_version": g.get("version"),
        "gauntlet_hash": gauntlet_hash(g),
        "provenance": prov,
        "rules_version": RULES_VERSION, "engine_version": ENGINE_VERSION,
        "python": platform.python_version(), "implementation": sys.implementation.name,
        "workers": workers, "n_scale": n_scale, "engine": engine,
        "seed_band": seed0, "deck": g["deck"], "mode": g["mode"],
        "agents": {n: {"factory": g["agents"][n]["factory"],
                       "kwargs": g["agents"][n].get("kwargs", {}),
                       "repr": mk[n].describe()} for n in names},
        "anchor": anchor,
        "pairs": pairs,
        "ratings": ratings,
        "cycles": cycles,
        "champion": g["champion"],
        "champion_candidates": cands,
        # 使い回し（D-077 追記 5）。**足すだけ**で既存の鍵は変えていない。
        # `wall_time_sec` は**この回で実際に回した時間**であって、
        # 使い回した組の時間は入っていない（v9 の 4 時間 38 分とは足せない）。
        "reuse": reuse_meta,
        "reused_pairs": sum(1 for p in pairs if p.get("reused_from")),
        "reuse_verified_pairs": sorted(f"{p['a']}|{p['b']}" for p in pairs
                                       if p.get("reuse_verified")),
        "wall_time_sec": round(time.time() - t0, 1),
    }


# --- 永続化 -----------------------------------------------------------------

def append_result(rec: dict, path: str = RESULTS_JSON) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    data.append(rec)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def render_md(rec: dict) -> str:
    names = list(rec["agents"])
    order = sorted(names, key=lambda n: -rec["ratings"][n]["elo"])
    L = [f"# ラダー: {rec['gauntlet']}（{rec['date'][:19]}）", "",
         f"定義ハッシュ `{rec['gauntlet_hash']}` / rules {rec['rules_version']} / "
         f"engine {rec['engine_version']} / シード帯 {rec['seed_band']}.. / "
         f"{rec['python']} / workers={rec['workers']} / {rec['wall_time_sec']}s", "",
         f"錨: {rec['anchor']['agent']} = {rec['anchor']['elo']}。"
         "Elo は Bradley-Terry の一括推定、区間はブートストラップ 95%。", "",
         "## レーティング", "", "| 順位 | エージェント | Elo | 95%区間 | 定義 |", "|---|---|---|---|---|"]
    for i, n in enumerate(order, 1):
        r = rec["ratings"][n]
        tag = " ★champion" if n == rec["champion"] else ""
        L.append(f"| {i} | {n}{tag} | {r['elo']:.0f} | [{r['lo']:.0f}, {r['hi']:.0f}] | "
                 f"`{rec['agents'][n]['repr']}` |")
    L += ["", "## 勝率行列（行が列に勝つ確率 ± 95%CI, n）", "",
          "| | " + " | ".join(order) + " |", "|---|" + "---|" * len(order)]
    cell = {}
    for p in rec["pairs"]:
        n = p["decided"]
        cell[(p["a"], p["b"])] = f"{p['p']:.3f} ±{p['ci']:.3f} (n={n})"
        cell[(p["b"], p["a"])] = f"{1 - p['p']:.3f} ±{p['ci']:.3f} (n={n})"
    for a in order:
        L.append(f"| **{a}** | " + " | ".join(cell.get((a, b), "—") for b in order) + " |")
    L += ["", "## 非推移性", ""]
    L.append("検出なし" if not rec["cycles"] else
             "**警告**: " + "; ".join(" > ".join(c) + " > " + c[0] for c in rec["cycles"]))
    L += ["", f"## champion 候補（現 champion: {rec['champion']}）", ""]
    if rec["champion_candidates"]:
        for c in rec["champion_candidates"]:
            L.append(f"- {c['agent']}: 直接対決 {c['p']:.3f} ±{c['ci']:.3f} (n={c['n']}) "
                     "— 別シード帯での追試と覗き見監査（D-026）を経て人が更新する")
    else:
        L.append("なし（直接対決で 95% 下限が 0.5 を上回る挑戦者はいない）")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("gauntlet")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--n-scale", type=float, default=1.0,
                    help="局数の倍率（動作確認用。1.0 未満の結果は本記録に混ぜないこと）")
    ap.add_argument("--dry-run", action="store_true", help="結果を保存しない")
    ap.add_argument("--resume", default=None,
                    help="途中経過のファイル。**組み合わせごとに保存し、同じコマンドで続きから回す**"
                         "（D-065 便 4。作業環境は一度に回しきれないため）。"
                         "既定 results/ladder_resume_<gauntlet>.json")
    ap.add_argument("--budget-sec", type=float, default=None,
                    help="この秒数を超えたら戻る（--resume と一緒に使う）。組の途中でも止まれる")
    ap.add_argument("--block", type=int, default=50,
                    help="止まれる粒度（局数）。重い組ほど小さくする")
    ap.add_argument("--engine", default="python", choices=["python", "rust", "auto"],
                    help="どの実装で回すか（既定 python = 従来どおり）。"
                         "auto = Rust 版がある組は Rust・無い組（mcts）は Python。"
                         "**実装は毎手一致で固定されているので出る数字は同じ**（D-049）。"
                         "使う前に experiments/check_ladder_engines.py で確かめること")
    ap.add_argument("--reuse-from", default=None,
                    help="前の記録（run_id か results/ladder.json の添字・-1 で最新）から"
                         "**体の定義が 1 文字も変わっていない組をそのまま使い回す**（D-077 追記 5）。"
                         "同じシードは同じ対局なので回し直しても 1 局も違わない。"
                         "**--reuse-verify と必ず一緒に使うこと**")
    ap.add_argument("--reuse-verify", default=None,
                    help="使い回せる組でも**わざと回し直して記録と突き合わせる**組"
                         "（`a|b,c|d` の形）。1 局でも違えばそこで止まる。"
                         "体ごとに最低 1 組は入れること")
    a = ap.parse_args(argv)
    g = load_gauntlet(a.gauntlet)
    print(f"ガントレット {g['name']} (hash {gauntlet_hash(g)}) / シード帯 {g['seed_band']}.. "
          f"/ workers={a.workers} / n_scale={a.n_scale}")
    reuse = reuse_meta = None
    verify = set()
    if a.reuse_verify:
        verify = {tuple(sorted(t.split("|"))) for t in a.reuse_verify.split(",") if t.strip()}
    if a.reuse_from:
        reuse, reuse_meta = load_reusable(RESULTS_JSON, a.reuse_from, g,
                                          a.n_scale, g["seed_band"])
        reuse_meta["verify"] = sorted("|".join(t) for t in verify)
        print(f"使い回し元 {reuse_meta['run_id']}: 拾えた {reuse_meta['reused']} 組 / "
              f"見送り {reuse_meta['skipped']} 組 {reuse_meta['skipped_reasons']}")
        if not verify:
            raise SystemExit("--reuse-from は --reuse-verify と一緒に使うこと"
                             "（抜き取り検査なしの使い回しは禁止・D-077 追記 5）")
    elif a.reuse_verify:
        raise SystemExit("--reuse-verify は --reuse-from と一緒にしか使えない")
    resume = a.resume
    if resume is None and a.budget_sec is not None:
        resume = os.path.join(_HERE, "..", "results", f"ladder_resume_{a.gauntlet}.json")
    rec = run_gauntlet(g, a.workers, a.n_scale, resume_path=resume,
                       budget_sec=a.budget_sec, block=a.block, engine=a.engine,
                       reuse=reuse, reuse_meta=reuse_meta, reuse_verify=verify)
    if rec is None:
        print(f"（途中経過: {os.path.normpath(resume)}）")
        return None
    md = render_md(rec)
    print(md)
    if a.dry_run or a.n_scale != 1.0:
        print("(保存しない: dry-run または n_scale≠1)")
        return rec
    append_result(rec)
    with open(RESULTS_MD, "w", encoding="utf-8") as f:
        f.write(md)
    if resume and os.path.exists(resume):
        os.remove(resume)          # 完走したら途中経過は要らない（次のラダーと混ざる元になる）
    print(f"保存: {os.path.normpath(RESULTS_JSON)} / {os.path.normpath(RESULTS_MD)}")
    return rec


if __name__ == "__main__":
    main()
