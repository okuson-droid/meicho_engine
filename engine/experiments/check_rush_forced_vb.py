"""「強いる版」の優位が消えたかの検算（D-064・設計書 §7.4 の補助の検算）。

## 何を確かめる道具か

D-045 で分かったこと: 漂泊者（女）を**最短で Lv2 にするよう強制した**計画探索は、
通常の計画探索に勝ち越した。**AI が自分では行かない場所に、行かせると得をする**——
つまり評価関数がその価値を持っていない、という診断であった（D-046 の出発点）。

V の反復ブートストラップが効いているなら、**その優位は消えるはずである**。
V が「Lv2 は良い」を自分で覚えたなら、強制する意味がなくなるからである。
D-045 の使い方を逆向きにした検算であり、設計書 §7.4 が反復 2 と 4 のあとに 1 回ずつ回すと定めている。

## 測り方

同じ版どうしを当て、A 席にだけ δ（発見ループの「強いる」型）を重ねる。
δ の中身は発見ループの語彙 A そのままで、`experiments/vb.py` が組む挑戦者と同じ形である。

    強いる版（δ = 漂泊者を 1 ターン目から急いで Lv2 に） vs 同じ版（δ なし）

**0.5 付近に出れば「強いる意味が無くなった」**＝ V が自分で急げるようになった、と読む。
0.5 を明確に超えていれば、まだ評価がその価値を持てていない。

使い方:
    python3 experiments/check_rush_forced_vb.py --deck SD001 --vb 4 --n 400 --seed0 401600
`--vb k` は「葉に V_{k-1} を積んだ版」を指す（`vb.py` の数え方と同じ）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import vb as vbmod                                                       # noqa: E402
from arena import load_deck, mirror_config                               # noqa: E402
from arena_rs import ensure_cards, series_rs                             # noqa: E402

# D-045 の「強いる版」に相当する δ。**カード名はデッキのデータから引く**（コードに書かない）。
FORCED_KIND = "rush_chara"


def forced_delta(deck_name: str, name: str = None) -> dict:
    """漂泊者（＝持続効果を持つキャラのうち D-045 で調べたもの）を 1 ターン目から急ぐ δ。

    `name` を指定しなければ、`vb.delta_candidates` が出す「強いる」型のうち
    `from_turn=1` のものから最初の 1 つを使う（カナリアと同じキャラになるよう並びは名前順）。
    """
    cands = [d for d in vbmod.delta_candidates(deck_name, "A")
             if d["kind"] == FORCED_KIND and d.get("from_turn") == 1
             and (name is None or d["name"] == name)]
    if not cands:
        raise SystemExit(f"{deck_name} に「1 ターン目から急ぐ」δ が見つからない")
    return cands[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--vb", type=int, required=True, help="測る版（葉に V_{k-1} を積んだ版）")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed0", type=int, required=True, help="**登録済みの評価帯から取ること**")
    ap.add_argument("--name", default=None, help="急がせるキャラ名（既定は名前順で最初）")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    ensure_cards()
    deck = load_deck(args.deck)
    pool = deck["action_deck"]
    config = mirror_config(deck)
    d = forced_delta(args.deck, args.name)
    plain = vbmod.spec(args.deck, pool, args.vb)
    forced = vbmod.spec(args.deck, pool, args.vb, delta=[d])

    import discovery
    print("■ 「強いる版」の優位が消えたかの検算（設計書 §7.4）")
    print(f"  版　: {vbmod.describe(args.deck, args.vb)}")
    print(f"  δ　 : {discovery.label(d)}")
    print(f"  シード {args.seed0}..{args.seed0 + args.n - 1}・{args.n} 局")
    print()
    t0 = time.time()
    r = series_rs(forced, plain, args.n, config, workers=args.workers, seed0=args.seed0)
    dt = time.time() - t0
    lo, hi = r.p - r.ci, r.p + r.ci
    print(f"  強いる版 vs 同じ版（δ なし）: {r}  下端 {lo:.3f} / 上端 {hi:.3f}"
          f"  [{args.n / dt:.1f} 局/秒]")
    print()
    if lo > 0.5:
        note = "**まだ強いると得をする**＝評価が Lv2 の価値を持ちきれていない"
    elif hi < 0.5:
        note = "**強いると損をする**＝評価はもう自分で判断できており、強制は邪魔になっている"
    else:
        note = "**強いる意味が無くなった**（0.5 を区間が挟む）＝ V が自分で急げるようになった"
    print(f"  → {note}")
    print("  （D-045 の出発点: 素の計画探索に対して強いる版は勝ち越していた）")

    out = {"deck": args.deck, "vb": args.vb, "delta": d, "seed0": args.seed0, "n": args.n,
           "p": r.p, "ci": r.ci, "lo": lo, "hi": hi, "wins": r.wins, "decided": r.decided,
           "verdict": note}
    path = args.out or os.path.join(_HERE, "..", "results", "vb", f"rush_forced{args.vb}.json")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"→ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
