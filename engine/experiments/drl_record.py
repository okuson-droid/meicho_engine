"""記録つき自己対戦を回す CLI（DRL 段階 0 の道具・`DRL_PLAN.md` §4.1 の 0-2）。

    python3 experiments/drl_record.py --deck SD001 --seed0 231000 --n 9000 \
        --out results/drl/sd001_s1_train.bin --workers 2

既定は**素の**計画探索どうし（planner vs planner・両席を記録）。`--value-net` / `--policy-net` / `--tau` で
A 側の planner にネットと温度を付ける。`--spec-b` で相手を変えられる
（`heuristic` / `greedy` / `planner` / `policy:<path>`）。

**`--champion` を付けると、両席がそのプールの現 champion（`experiments/champion.py`）になる**（段階 2）。
段階 2 の「教師が新 champion になったので記録を取り直す」はこれで行う。`--policy-net` は
planner の**代打ち**を差し替える別の口であり、champion（相手モデル = π・根だけ）とは中身が違う。

**`--vb <k>` を付けると、席が V の反復ブートストラップ（D-064）の反復 k のエージェントになる**
（中身の定義は `experiments/vb.py` が唯一の真実源）。教材のレシピは
`VALUE_BOOTSTRAP_DESIGN.md` §6 の 3 種で、同じ `--vb` に 3 通りの付け方をする:

    # 自己対戦（ミラー・両席を記録）— 主食
    --vb 1 --record both
    # リーグ局（相手を H / 貪欲に変える・**A 席だけ記録**）
    --vb 1 --spec-b heuristic --record a
    # δ 介入局（A 席に「強いる」型を重ねる・**A 席だけ記録**）
    --vb 1 --delta-gens A --record a

§6.3 の規則により、**記録する席は常にループのエージェント（またはその δ 版）に固定する**。
H・貪欲の席の決定は記録しない（証拠 B の Simpson の罠を席の固定で防ぐ）。
`--vb` のときこの規則は引数の検査として強制される。

出力は `<out>.<worker>` に分かれる。同時に `<out>.manifest.json` に条件を書く（再生成できるように）。
δ 介入では δ 1 つにつき 1 本の列を回すので出力は `<out>.g<j>.<worker>` になり、
manifest は `<out>.manifest.json` にまとめて 1 つ書く（`drl_train.py --train <out>` で
まとめて読める。`files_of` は `.json` で終わるファイルを除くため manifest は混ざらない）。
**シード帯は `seed_bands.json` に登録してから使うこと**（80000.. の評価専用帯では回せない）。

## manifest は必ずマスターの PC に持ち帰ること（D-065 便 3・2026-09-05）

記録の生バイト（`.bin`）は 1 反復で 1.8 GB あり、作業コンテナが回収されると一緒に消える。
**それは想定どおりの運用である**——`.bin` は捨ててよい。捨ててよい理由は、manifest（数 KB）に
「どのエージェントで・どのシード帯を・何局回したか」が全部書いてあり、**そこから作り直せる**からである。

ところが D-064 の vb ループでは manifest を持ち帰っておらず、反復 1〜4 の記録が**作り直せない形で**
失われた（引継ぎ書 §2.1）。同じことを繰り返さないため、この CLI は最後に
「manifest を書き戻せ」と促す。**`.bin` は持ち帰らなくてよい。manifest だけは必ず持ち帰る。**
manifest には `regenerate`（打ち直すコマンド）と `format`（記録の版）が入る。
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

import meicho_rs as rs                                          # noqa: E402

import champion                                                 # noqa: E402
import vb as vbmod                                              # noqa: E402

from arena import load_deck, mirror_config                      # noqa: E402
from arena_rs import GREEDY, HEURISTIC, PLANNER, ensure_cards   # noqa: E402
from meicho.encode import ENCODING_VERSION                      # noqa: E402


def record_format(files) -> str:
    """書けた記録の版をファイルの先頭から読む（D-065 便 3）。

    以前は manifest に `"MCDR v2"` と**決め打ち**していた。`reeval_samples>0` で回すと
    中身は版 3 になるので、決め打ちだと manifest が嘘をつく。実際に書けたものを見る。
    """
    import struct
    vers = set()
    for path in files:
        try:
            with open(path, "rb") as f:
                magic, ver, _od, _acl = struct.unpack("<4sIII", f.read(16))
        except (OSError, struct.error):
            continue
        if magic == b"MCDR":
            vers.add(int(ver))
    if not vers:
        return "unknown"
    return "MCDR v" + "/".join(str(v) for v in sorted(vers))


def regenerate_command(argv=None) -> str:
    """この記録を作り直すコマンド（D-065 便 3・引継ぎ書 §2.1 の課題）。

    `.bin` は大きすぎて持ち帰らない。持ち帰るのは manifest だけで、そこから作り直す。
    **そのためには「何を打ったか」がそのまま残っている必要がある。**
    """
    import shlex
    argv = list(sys.argv if argv is None else argv)
    return "python3 experiments/drl_record.py " + " ".join(shlex.quote(a) for a in argv[1:])


def strip_paths(spec: dict) -> dict:
    """manifest に書く用。ネットのパスをファイル名だけにする（絶対パスを残さない・C-1 の教訓）。"""
    out = dict(spec)
    for k in ("value_net", "policy_net", "opp_policy_net", "net"):
        if isinstance(out.get(k), str):
            out[k] = os.path.basename(out[k])
    return out


def check_record_band(seed0: int) -> dict:
    """記録に使ってよいシード帯かを台帳（`seed_bands.json`）で確かめる。

    落とすのは 2 種類。
    - `ladder`（80000..89999）: ラダー評価専用（D-034）。
    - `validate`: 何かの**評価**に使った帯。ここで学習データを作ると、
      あとでその帯で測ったときに「学習に使った局で試験する」ことになる
      （D-058 の SD02 で実際に起きた汚染。`seed_bands.json` の 270000.. の注記）。
    未登録の帯も落とす（D-028: 台帳に追記してから使う）。
    """
    with open(os.path.join(_HERE, "seed_bands.json"), encoding="utf-8") as f:
        led = json.load(f)
    for b in led["bands"]:
        if b["start"] <= seed0 <= b["end"]:
            if b.get("kind") in ("ladder", "validate"):
                raise SystemExit(
                    f"帯 {b['start']}..{b['end']} は評価専用（{b['purpose']}）。"
                    f"学習データの生成には使えない")
            return b
    raise SystemExit(f"帯 {seed0} は seed_bands.json に未登録。"
                     f"台帳に追記してから使うこと（D-028）")


def _delta_label(d: dict) -> str:
    """δ の人が読める一文（発見ループの `discovery.label` をそのまま使う）。"""
    import discovery
    return discovery.label(d)


def spec_of(kind: str, pool: list, **kw) -> dict:
    if kind == "heuristic":
        return HEURISTIC()
    if kind == "greedy":
        return GREEDY(pool)
    if kind.startswith("policy:"):
        return {"kind": "policy", "net": kind.split(":", 1)[1], "tau": kw.get("tau", 0.0)}
    return PLANNER(pool, **kw)


def split_seeds(seed0: int, n: int, k: int) -> list:
    """n 局を k 本の**連なったシード帯**に割る。返り値は [(seed0_i, n_i), ...]。

    δ 1 つにつき 1 本の列を回すため。余りは先頭から 1 局ずつ配る（決定的）。
    帯を重ねないので、あとから「どの δ の局か」をシードだけで引ける。
    """
    assert k >= 1 and n >= k, f"局数が δ の種類数より少ない（n={n}, k={k}）"
    base, rem = divmod(n, k)
    out, s = [], seed0
    for i in range(k):
        m = base + (1 if i < rem else 0)
        out.append((s, m))
        s += m
    return out


def run_series(cfg, spec_a, spec_b, seed0, n, out, workers, rec_a, rec_b):
    """1 本の記録つき対局列。戻り値は (結果の行, 書いたファイル, 秒数)。"""
    t = time.time()
    res, files = rs.series_record(cfg.chara_decks, cfg.action_decks, spec_a, spec_b,
                                  seed0, n, out, workers, 200, rec_a, rec_b)
    return res, files, time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--spec-b", default="planner")
    ap.add_argument("--value-net", default=None)
    ap.add_argument("--policy-net", default=None)
    ap.add_argument("--tau", type=float, default=0.0)
    ap.add_argument("--record", choices=["both", "a", "b"], default="both")
    ap.add_argument("--champion", action="store_true",
                    help="両席をそのプールの現 champion にする（段階 2 の記録）")
    ap.add_argument("--loop", type=int, default=1,
                    help="輪の番号（既定 1 = D-064 の輪。2 = D-065 便 4 の輪）。--vb と一緒に使う")
    ap.add_argument("--vb", type=int, default=None,
                    help="V の反復ブートストラップ（D-064）の反復番号 k。"
                         "席を vb.py が定義する反復 k のエージェントにする")
    ap.add_argument("--delta-gens", default=None,
                    help="δ 介入局にする（--vb と併用）。発見ループの語彙（例 A）。"
                         "持続効果に関わる「強いる」型に絞って δ 1 つにつき 1 本の列を回す")
    args = ap.parse_args()
    check_record_band(args.seed0)
    ensure_cards()
    deck = load_deck(args.deck)
    pool = deck["action_deck"]
    cfg = mirror_config(deck)
    cfg.validate()
    a_kw = {}
    if args.value_net:
        a_kw["value_net"] = args.value_net
    if args.policy_net:
        a_kw["policy_net"] = args.policy_net
    if args.tau:
        a_kw["tau"] = args.tau
    deltas = None
    if args.vb is not None:
        if args.champion:
            raise SystemExit("--vb と --champion は同時に使えない（席の定義が 2 つになる）")
        if args.value_net or args.policy_net:
            raise SystemExit("--vb と --value-net/--policy-net は同時に使えない"
                             "（反復 k の中身は experiments/vb.py が唯一の真実源）")
        # §6.3: 記録する席は常にループのエージェント（またはその δ 版）に固定する。
        if (args.spec_b != "planner" or args.delta_gens) and args.record != "a":
            raise SystemExit("リーグ局・δ 介入局では --record a を指定すること"
                             "（記録する席をループのエージェントに固定する・"
                             "VALUE_BOOTSTRAP_DESIGN.md §6.3）")
        # **記録なので `recording=True`**（その輪の取り直しなどが付く。評価には付かない）
        spec_a = vbmod.spec(args.deck, pool, args.vb, loop=args.loop, recording=True, **a_kw)
        spec_b = vbmod.spec(args.deck, pool, args.vb, loop=args.loop, recording=True, **a_kw) \
            if args.spec_b == "planner" \
            else spec_of(args.spec_b, pool)
        if args.delta_gens:
            deltas = vbmod.delta_candidates(args.deck, args.delta_gens)
        print(f"ループのエージェント: {vbmod.describe(args.deck, args.vb, args.loop)}"
              + (f"  tau={args.tau}" if args.tau else ""))
        if deltas:
            print(f"δ 介入: 語彙 {args.delta_gens} から {len(deltas)} 種"
                  f"（1 局につき 1 つ・{args.n} 局を種類ごとの連なったシード帯に割る）")
    elif args.champion:
        if args.value_net or args.policy_net:
            raise SystemExit("--champion と --value-net/--policy-net は同時に使えない"
                             "（champion の中身は experiments/champion.py が唯一の真実源）")
        spec_a = champion.spec(args.deck, pool, **a_kw)
        spec_b = champion.spec(args.deck, pool, **a_kw) if args.spec_b == "planner" \
            else spec_of(args.spec_b, pool)
        print(f"教師: {champion.describe(args.deck)}" + (f"  tau={args.tau}" if args.tau else ""))
    else:
        if args.delta_gens:
            raise SystemExit("--delta-gens は --vb と一緒に使うこと（D-064 の教材レシピ §6）")
        spec_a = PLANNER(pool, **a_kw)
        spec_b = spec_of(args.spec_b, pool)

    rec_a, rec_b = args.record in ("both", "a"), args.record in ("both", "b")
    res, files, dt, blocks = [], [], 0.0, []
    if deltas:
        # δ 1 つにつき 1 本の列。出力の接頭辞を分けて `<out>.g<j>.<worker>` に書く。
        for j, ((s0, m), d) in enumerate(zip(split_seeds(args.seed0, args.n, len(deltas)), deltas)):
            sa = dict(spec_a, delta=[d])
            r, fs, sec = run_series(cfg, sa, spec_b, s0, m, f"{args.out}.g{j}",
                                    args.workers, rec_a, rec_b)
            res += r; files += fs; dt += sec
            blocks.append({"i": j, "delta": d, "label": _delta_label(d),
                           "seed0": s0, "n": m, "files": fs})
    else:
        res, files, dt = run_series(cfg, spec_a, spec_b, args.seed0, args.n, args.out,
                                    args.workers, rec_a, rec_b)

    dec = [r[0] for r in res if r[0] is not None]
    summary = {
        "deck": args.deck, "config": "mirror", "spec_a": strip_paths(spec_a), "spec_b": strip_paths(spec_b),
        "champion": bool(args.champion), "teacher": champion.describe(args.deck) if args.champion else None,
        "vb": args.vb, "loop": args.loop,
        "vb_agent": vbmod.describe(args.deck, args.vb, args.loop) if args.vb is not None else None,
        # §4.5: δ 局は manifest に語彙を必ず書く（あとから π の学習でこの局を除外できるように）。
        "delta": args.delta_gens, "delta_blocks": blocks or None,
        "seed0": args.seed0, "n": args.n,
        "workers": args.workers, "record": args.record,
        "format": record_format(files), "encoding_version": ENCODING_VERSION,
        "files": files, "a_won": (sum(dec) / len(dec) if dec else None), "decided": len(dec),
        "mean_turns": sum(r[1] for r in res) / len(res), "seconds": dt,
        "regenerate": regenerate_command(),
    }
    manifest = args.out + ".manifest.json"
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("spec_a", "spec_b")}, ensure_ascii=False))
    print(f"\n★ {manifest} を**マスターの PC に書き戻すこと**（D-065 便 3・引継ぎ書 §2.1）。"
          f"\n  記録の本体（{len(files)} ファイル）は持ち帰らなくてよい。作業環境が回収されれば消えるが、"
          f"\n  この manifest の regenerate 行を打てば作り直せる。**manifest を落とすと作り直せなくなる。**")


if __name__ == "__main__":
    main()
