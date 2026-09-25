"""現 champion の fingerprint を 1 コマンドで取る（Rust 版・ミラー 10 局）。

**何のための道具か**: wheel を作り直したあと、あるいは champion を交代させたあとに、
「いまこの環境で動く champion は、記録に残っている指紋と同じ打ち方をするか」を確かめる。
ここが合わないまま測ると、そのあとの勝率はすべて意味を失う。

手順は `tests/test_champion_vc4.py` §1 と同じである——
Rust 版・同型ミラー 10 局・seeds 471500..471509・workers=2・
各局の digest 列を `sha256(repr(digests))` して先頭 16 桁（便 D §8.2）。

実行:

    python scripts/check_champion_fingerprint.py

期待される値（2026-09-19 現在・`planner_vc4cps_kheb_b75`）:

    champion   planner_vc4cps_kheb_b75
    期待       f4b80b25c35cfa77
    実測       f4b80b25c35cfa77
    → 一致

（D-104 で貼り替えた。**この実行例の値は下の `EXPECTED` と必ず同時に直すこと。**
2026-09-17 まで旧値 `e1662edb32b144a9` が残っていて、読んだ人が古い値を期待値と誤読しうる状態だった。）

**★この道具は現 champion 1 体しか見ない。**歴代 3 体は `EXPECTED` に載っているが、
確かめるのは `tests/test_champion_vc4.py`・`test_lit_a2.py`・`test_lit_c.py` の節点である
（2026-09-18 に依頼書が「4 体とも一致する」と誤って書いていた・D-101 §4）。

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
# D-097（2026-09-17・マスター裁定）: A-2（公式 701.1.2 のリフレッシュを、ドローの中だけでなく
# 700.1.1 の処理待ちチェックの先頭でも行う）を直したため、**山札を切らす対局の打ち方が変わった**。
# champion は `extra_turns=1` と `endgame_enum=64` で終盤まで探索を伸ばすので、この帯では踏む。
#   実測（作業環境・Python エンジンに計数を割り込ませて数えた・D-097 §2）:
#     seed 471500..471509 を champion 相当の深さで回すと **10 局中 5 局**が
#     新設のリフレッシュ時点を踏む（471502・471505・471506・471507・471508）。
#     一方 `BASELINE_DIGESTS_230000` の帯（230000..230005）は **6 局ともリフレッシュ 0 件**。
#     だからあちらは不変で、こちらだけが動いた。**基準が不変でも、その基準が変更点を
#     踏んでいないだけかもしれない**——不変を根拠に他の帯の不変を推さないこと。
#   旧値 planner_vc4cps_kheb_b75 = 9d4ff39d024e4394（D-091〜D-096・v0.14 の A-1/A-2 より前）
#   さらに旧値 = e1662edb32b144a9（D-088 以前）
# D-101（2026-09-18・マスター裁定）: **B-9（公式 604.1.1.2 後段の手札公開・D-099）で動いた。**
#   6ca46b15dd151228 → 099a7f9382843ff2。
#   **原因は B-9 単独であると切り分け済み**——B-9 だけを外して（A-3・A-5・B-7 は入れたまま）
#   同じ帯を測ると 6ca46b15dd151228 がそのまま出る。Rust の写し間違いではない。
#   仕組み: B-9 は「対抗で置けないターンプレイヤーの手札を公開する」＝観測の `hand_known` が増える。
#   champion は `known_hand`（見えた札を決定化に必ず入れる）を持ち、価値ネットと相手モデルも
#   観測を読むので、公開が増えると評価が変わる。**`known_hand` を持たない素の planner は動かない**
#   ——だから `BASELINE_DIGESTS_230000` も、歴代 3 体の指紋も不変だった。
#   大きさ: この帯の 10 局のうち**手順が変わったのは 1 局（471508）だけ・勝敗は 0/10**（手数 100 → 98）。
#   **強くなったか弱くなったかは測っていない**（D-097 §5 のとおり、次の交代判定は新エンジンで測り直す）。
# D-098（2026-09-17）: **下の 3 体も実測して貼り替えた。「未再測」の札は外した。**
#   D-091 が付けた「D-088 以前の値・未再測」はこれで解消した。値は PC の全体検査
#   （tests/test_champion_vc4.py・test_lit_a2.py・test_lit_c.py）が出した実測である。
#   **動いた理由は (a) 段階1A（D-088）と (b) A-2（D-095／rules v0.14）が重なっており、
#   寄与は分けて測っていない。**
#   旧値 planner_vc4cps_kheb = e82b796960e04c4a
#        planner_vc4cps      = 9b5ad48d2de6a7e0
#        planner_vb3cps      = 7251a931d252a57a
# D-104（2026-09-19・マスター裁定）: **A-6（回復にライフの上限は無い・公式 101.6・rules v0.18）で動いた。**
#   D-011（2026-08-21 のマスター裁定「上限 20 でクリップ」）を覆したため、`SD01-023`「奏鳴」(+5) が
#   **序盤から本当に +5 回復する**ようになり、SD001 の対局が変わった。SD02 と BP01 の仮デッキは
#   回復カードを持たないので**1 手も動いていない**。
#   実測（A-6 の前後・ミラー 200 局）: SD001/random 手順 4・勝敗 1／SD001/heuristic 手順 8・勝敗 1／
#   **planner/SD001 手順 80・勝敗 37**／champion の指紋の帯 471500..471509 は手順 4/10・勝敗 4/10。
#   **これは AI の打ち方の変化ではなく、ゲームのルールが公式に合ったことによる変化である。**
#   **4 体とも動いた**（どれも SD001 を回すため）。旧値（D-101〜D-103・v0.17）:
#     b75 099a7f9382843ff2 / kheb f3d1b52aed0abdad / vc4cps 2d884df547ac6990 / vb3cps c84616b0d707a705
EXPECTED = {"planner_vc4cps_kheb_b75": "f4b80b25c35cfa77",
            "planner_vc4cps_kheb": "b4d3b2a1986b71b9",
            "planner_vc4cps": "ff72e98e303d87ae",
            "planner_vb3cps": "87988cc627c0b64e"}

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
