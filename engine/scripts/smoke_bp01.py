"""便 K の仮デッキのスモーク（乱択自己対戦）を Python と Rust の両方で回す（引継ぎ書 §3.5・§5）。

**これは強さの測定ではない。** 乱択どうしを回して「例外で落ちないか」「ターン上限に当たらないか」
だけを見る検査である。したがって勝率も区間も出さない。見るのは次の 3 つ:

- **打ち切り** … `max_turns`（既定 200）を超えた局の数。0 でなければ効果の循環を疑う
- **引き分け** … §9-5 の進行不能。0 でなくてよいが、数が多ければデッキの構成を疑う
- **平均ターン** … Python と Rust が**同じ値**になること。違えば実装がずれている

シードは `experiments/seed_bands.json` に登録した **706000..708999**（便 K 段 K-5 専用）から取る。
デッキごとに 1,000 シードずつで、割り当ては `SEED0` のとおり。
帯を分けるのは、他の測定とシードを共有すると「同じ局を二度数えた」状態になるためである（D-028）。

使い方:

    python3 scripts/smoke_bp01.py                 # 3 デッキ・Python と Rust
    python3 scripts/smoke_bp01.py --n 60          # 短く回す（開発中）
    python3 scripts/smoke_bp01.py --no-rust       # Rust をビルドしていない環境
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, _ROOT)

from meicho.agents import RandomAgent          # noqa: E402
from meicho.engine import GameConfig           # noqa: E402
from meicho.runner import play_game            # noqa: E402

# デッキ → そのデッキに割り当てたシードの先頭（帯 706000..708999）
SEED0 = {
    "K_smoke_ANKO": 706000,
    "K_smoke_SANGE": 707000,
    "K_smoke_TSUBAKI": 708000,
}


def load_config(name: str) -> GameConfig:
    with open(os.path.join(_ROOT, "decklists", f"{name}.json"), encoding="utf-8") as f:
        d = json.load(f)
    return GameConfig(chara_decks=[d["chara_deck"]] * 2,
                      action_decks=[d["action_deck"]] * 2)


def run_python(name: str, n: int) -> dict:
    config = load_config(name)
    base = SEED0[name]
    ab = dr = turns = 0
    t0 = time.time()
    for i in range(n):
        seed = base + i
        r = play_game(config, [RandomAgent(seed * 2), RandomAgent(seed * 2 + 1)], seed)
        ab += int(r["aborted"])
        dr += int(r["draw"])
        turns += r["turns"]
    return {"games": n, "aborted": ab, "draws": dr,
            "mean_turns": round(turns / n, 2), "sec": round(time.time() - t0, 1)}


def run_rust(name: str, n: int, workers: int = 2, max_turns: int = 200) -> dict:
    """Rust 側は `series`（Rust 内で対局が完結する道）で回す。

    Rust に `RandomAgent` の型は無いので、仕様 `{"kind": "random"}` を両側に渡す。
    `series` は「シードが奇数なら A が後攻」という約束だが、両側が同じ乱択なので
    **席に座る乱数（先攻 seed*2・後攻 seed*2+1）は Python 版と同じ**になり、
    局そのものは `runner.play_game` と 1 手も違わない。
    戻り値は (A の勝ち or None, ターン数, 手数, δ の関与回数) で、
    引き分けも打ち切りも `None` になるため、**ターン数が上限を超えたか**で両者を分ける。"""
    import meicho_rs as rs
    from meicho.cards_export import cards_json
    rs.load_cards(cards_json())
    config = load_config(name)
    t0 = time.time()
    out = rs.series(config.chara_decks, config.action_decks,
                    {"kind": "random"}, {"kind": "random"},
                    SEED0[name], n, workers, max_turns)
    ab = sum(1 for r in out if r[1] > max_turns)
    dr = sum(1 for r in out if r[0] is None and r[1] <= max_turns)
    turns = sum(r[1] for r in out)
    return {"games": n, "aborted": ab, "draws": dr,
            "mean_turns": round(turns / n, 2), "sec": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--no-rust", action="store_true")
    ap.add_argument("--out", default=None, help="結果を JSON で書き出す先")
    args = ap.parse_args()

    out = {}
    bad = 0
    for name in sorted(SEED0):
        rec = {"seed0": SEED0[name], "python": run_python(name, args.n)}
        line = (f"{name:16s} seed0={SEED0[name]}  "
                f"Python 打ち切り {rec['python']['aborted']} / 引き分け {rec['python']['draws']}"
                f" / 平均 {rec['python']['mean_turns']} ターン ({rec['python']['sec']}s)")
        if not args.no_rust:
            rec["rust"] = run_rust(name, args.n)
            line += (f"  |  Rust 打ち切り {rec['rust']['aborted']} / 引き分け {rec['rust']['draws']}"
                     f" / 平均 {rec['rust']['mean_turns']} ターン ({rec['rust']['sec']}s)")
            if rec["rust"]["mean_turns"] != rec["python"]["mean_turns"] \
                    or rec["rust"]["aborted"] != rec["python"]["aborted"] \
                    or rec["rust"]["draws"] != rec["python"]["draws"]:
                line += "   ← ★不一致"
                bad += 1
        bad += rec["python"]["aborted"]
        out[name] = rec
        print(line, flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    print("打ち切り・不一致なし" if bad == 0 else f"★ 要調査 {bad} 件")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
