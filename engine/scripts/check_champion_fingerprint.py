"""現 champion の fingerprint を 1 コマンドで取る（Rust 版・ミラー 10 局）。

**何のための道具か**: wheel を作り直したあと、あるいは champion を交代させたあとに、
「いまこの環境で動く champion は、記録に残っている指紋と同じ打ち方をするか」を確かめる。
ここが合わないまま測ると、そのあとの勝率はすべて意味を失う。

手順は `tests/test_champion_vc4.py` §1 と同じである——
Rust 版・同型ミラー 10 局・seeds 471500..471509・workers=2・
各局の digest 列を `sha256(repr(digests))` して先頭 16 桁（便 D §8.2）。

実行:

    python scripts/check_champion_fingerprint.py

期待される値（2026-09-13 現在・`planner_vc4cps_kheb_b75`）:

    champion   planner_vc4cps_kheb_b75
    期待       e1662edb32b144a9
    実測       e1662edb32b144a9
    → 一致

**一致しなかったら、そこで止めて原因を突き止めること。**測り直しではない。
よくある原因は (a) wheel が古い（`features()` につまみの札が無い）
(b) `results/models/` のネットが別物 (c) `champion.py` を直したのに期待値を直していない。
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # engine/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from experiments.console import use_utf8_console    # noqa: E402

# 交代のたびにここを書き換える（`champion.py` と同時に）。
EXPECTED = {"planner_vc4cps_kheb_b75": "e1662edb32b144a9",
            "planner_vc4cps_kheb": "e82b796960e04c4a",
            "planner_vc4cps": "9b5ad48d2de6a7e0",
            "planner_vb3cps": "7251a931d252a57a"}

MODEL_KEYS = ("value_net", "opp_policy_net", "policy_net")


def main() -> int:
    use_utf8_console()
    from arena import load_deck, mirror_config
    from meicho.drlnet import resolve_model
    from experiments.arena_rs import ensure_cards, series_rs_digest
    import champion as chmod

    try:
        import meicho_rs
    except ImportError:
        print("meicho_rs が入っていない。`engine\\rust` で maturin build してから。")
        return 2
    feats = set(meicho_rs.features()) if hasattr(meicho_rs, "features") else set()
    print("wheel の札      ", sorted(feats) or "（features() が無い＝かなり古い wheel）")

    deck = load_deck("SD001")
    config = mirror_config(deck)
    name = chmod.name_for("SD001")
    kw = {k: (resolve_model(v) if k in MODEL_KEYS else v)
          for k, v in chmod.kwargs_for("SD001").items()}

    missing = [k for k in kw if k not in feats and k in
               ("lethal_uniform", "known_hand", "world_weight",
                "endgame_enum", "draw_buckets", "bundle_p")]
    if missing:
        print("★ wheel が古い。champion が使うつまみ", missing, "を知らない。")
        print("  `engine\\rust` で作り直すこと（README／RUST_PORT_NOTES.md）。")
        return 2

    ensure_cards()
    sp = {"kind": "planner", "opp_decklist": deck["action_deck"], **kw}
    out = series_rs_digest(sp, sp, 10, config, workers=2, seed0=471500)
    got = hashlib.sha256(repr([r[4] for r in out]).encode()).hexdigest()[:16]

    want = EXPECTED.get(name)
    print("champion        ", name)
    print("期待            ", want or "（この名前の期待値が登録されていない）")
    print("実測            ", got)
    if want is None:
        print("→ 判定できない。`EXPECTED` に足すこと。")
        return 1
    print("→ 一致" if got == want else "→ ★不一致。止まって原因を突き止めること。")
    return 0 if got == want else 1


if __name__ == "__main__":
    raise SystemExit(main())
