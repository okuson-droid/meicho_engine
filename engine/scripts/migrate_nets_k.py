# -*- coding: utf-8 -*-
"""便 K 段 K-1: BP01 のカード登録にともなう学習済みネットの移行（ENCODING_VERSION 3 → 4）。

## なぜ移行が要るか

`meicho/encode.py` は観測を「カード1種につき1つの枠」を並べた固定長の数列にする。
カードが増えると枠の数が変わり、**保存済みのネットの入力の形が合わなくなる**。
形が合わないまま読ませると、うまくいけば例外で落ちるが、最悪の場合は
別のカードの枠を読んでしまい、**黙って壊れた判断をする**。

`scripts/migrate_nets_d062.py` は「使われなくなった列を**削る**」道具だった。
本ファイルはその**逆向き**で、「まだ誰も使っていない列を **0 として挿す**」。

## なぜ「値は変わらない」と言えるか

足した BP01 の 71 枠（アクション 41＋未掲載 3、キャラ 27）は、SD001/SD02 の
どのデッキリストにも入っていない。したがって

- 枚数ベクトルの新しい枠は**常に 0**
- one-hot の新しい枠も**常に 0**
- 行動符号のカード枠が新カードを指すこともない

入力が常に 0 の枠は、そこに掛かる重みが何であっても出力に寄与しない。
新しい重みは 0 で初期化するので、**列を挿すだけでネットの出力は完全に同じ**になる
（数学的に厳密）。これは「学習し直し」ではなく「使われていない列の挿し込み」である。

BP01 のデッキで対局させるときは話が別で、そのときは新しい列の重みが 0 のまま＝
「新カードを見ていない」ネットになる。**便 K の完了条件に強さは入らない**
（引継ぎ書 §0.2。BP01 環境の champion 選び直しは D-047 の枠で別便）。

## 挿す位置

観測の並びは `[N_SCALAR=62][NA×12][NC×7]`、行動の並びは
`[種類 19][NA][NC][枠 3][バック 2][数 1][マリガンの捨て札 NA]`（`meicho/encode.py`）。
**新カードは末尾追記**なので、各ブロックの**後ろ**に足りない列を挿せばよい。
既存 52 枚の添字が動いていないことは `tests/test_bp01.py` T-K-2 が守る。

    旧 NA=34 / NC=18 → 新 NA=78 / NC=45
    観測 596 → 1313 = 62 + 12×78 + 7×45
    行動 111 → 226  = 19 + 78 + 45 + 3 + 2 + 1 + 78

方策の第1層の入力は `[幹の出力 hidden ⊕ 行動]` なので、行動側の位置に hidden を足す。

使い方:
    python3 scripts/migrate_nets_k.py results/models/*.json
    python3 scripts/migrate_nets_k.py --check results/models/drl_sd001_vc4.json

- **原本は消さない**。書き換える前に `*.enc3.bak.json` を並べて残す（作業規約: ファイルは消さない）。
- **冪等**である。すでに版4のファイルは「移行済み」と言って何もしない。
- `--check` は書き換えずに検算だけ行う。
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys

import numpy as np

OLD_NA, NEW_NA = 34, 78
OLD_NC, NEW_NC = 18, 45
N_SCALAR = 62
N_TYPES = 19
N_TAIL = 3 + 2 + 1                      # 枠・バック・数

OLD_OBS = N_SCALAR + OLD_NA * 12 + OLD_NC * 7          # 596
NEW_OBS = N_SCALAR + NEW_NA * 12 + NEW_NC * 7          # 1313
OLD_ACT = N_TYPES + OLD_NA + OLD_NC + N_TAIL + OLD_NA  # 111
NEW_ACT = N_TYPES + NEW_NA + NEW_NC + N_TAIL + NEW_NA  # 226

# 検算の関門は float64 の一致。ここが緩んだら列の対応が誤っている。
EXACT_TOL = 1e-12
# float32 の丸めはこの目安を超えたら知らせるだけ（関門にしない。上の migrate() の注記を参照）。
ROUND_REPORT = 1e-6


def obs_map() -> list:
    """旧の観測の添字 i → 新の添字。新しい枠はここに現れない（＝重み 0 のまま）。"""
    m = list(range(N_SCALAR))
    for b in range(12):                              # アクションの 12 ブロック
        base_old, base_new = N_SCALAR + b * OLD_NA, N_SCALAR + b * NEW_NA
        m += [base_new + j for j in range(OLD_NA)]
        assert len(m) == base_old + OLD_NA
    off_old = N_SCALAR + 12 * OLD_NA
    off_new = N_SCALAR + 12 * NEW_NA
    for c in range(7):                               # キャラの 7 ブロック
        m += [off_new + c * NEW_NC + j for j in range(OLD_NC)]
    assert len(m) == OLD_OBS, (len(m), OLD_OBS)
    return m


def act_map() -> list:
    """旧の行動の添字 i → 新の添字。"""
    m = list(range(N_TYPES))
    m += [N_TYPES + j for j in range(OLD_NA)]                       # カード one-hot
    m += [N_TYPES + NEW_NA + j for j in range(OLD_NC)]              # キャラ one-hot
    base_new = N_TYPES + NEW_NA + NEW_NC
    m += [base_new + k for k in range(N_TAIL)]                      # 枠・バック・数
    m += [base_new + N_TAIL + j for j in range(OLD_NA)]             # マリガンの捨て札
    assert len(m) == OLD_ACT, (len(m), OLD_ACT)
    return m


OBS_MAP = obs_map()
ACT_MAP = act_map()


def _widen(w: list, mapping: list, new_cols: int, col_offset: int = 0) -> list:
    """列を増やす。旧の列 j を新の列 `col_offset + mapping[j]` に置き、残りは 0。"""
    a = np.asarray(w, dtype=np.float64)
    out = np.zeros((a.shape[0], a.shape[1] - len(mapping) + new_cols), dtype=np.float64)
    # mapping の対象外（幹の出力など）は先頭にそのまま残す
    keep = a.shape[1] - len(mapping)
    assert keep == col_offset, (keep, col_offset)
    out[:, :keep] = a[:, :keep]
    for j, dst in enumerate(mapping):
        out[:, keep + dst] = a[:, keep + j]
    return out.tolist()


NET_KEYS = ("obs_dim", "act_dim", "encoding_version")


def _is_net(d) -> bool:
    """移行の対象（`drlnet.Net.save` が書いたネット）かどうか。

    `results/models/` には他の形式の JSON も同居している（D-083 追記 2）:

    - `*.meta.json` … 学習の由来（`lr` `epochs` `vtarget` など）。符号化の欄を持たない
    - `c1_*.json` … 便 C1 の線形・ロジット模型（`kind` `feature_names` `w`）。
      手作りの特徴を使うのでカードの枠には依らず、符号化の版上げの影響を受けない

    どちらも移行してはならないし、移行の必要もない。
    """
    return isinstance(d, dict) and all(k in d for k in NET_KEYS)


def migrate(path: str, check_only: bool = False, from_glob: bool = False) -> str:
    """1 ファイルを移行する。戻り値は "migrated" / "already" / "skipped"。"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    if not _is_net(d):
        # **ワイルドカードで拾ったものは黙って飛ばさず、理由を言って飛ばす。**
        # **名指しされたものは飛ばさない**——マスターがそのファイルを移行したくて
        # 打った以上、「何もしませんでした」で終わるほうが危ない。
        missing = ", ".join(k for k in NET_KEYS if k not in d)
        if from_glob:
            print(f"  {os.path.basename(path)}: 対象外（ネットではない。{missing} がない）")
            return "skipped"
        raise SystemExit(
            f"ネットの形式ではない: {path}（{missing} がない）\n"
            f"移行してよいのは `drlnet.Net.save` が書いたネットだけである。"
        )

    if d["obs_dim"] == NEW_OBS and d["act_dim"] == NEW_ACT:
        print(f"  {os.path.basename(path)}: 既に移行済み（obs={NEW_OBS} act={NEW_ACT}）")
        return "already"
    assert d["obs_dim"] == OLD_OBS, f"想定外の obs_dim: {d['obs_dim']}"
    assert d["act_dim"] == OLD_ACT, f"想定外の act_dim: {d['act_dim']}"
    assert d["encoding_version"] == 3, f"想定外の encoding_version: {d['encoding_version']}"

    hidden = len(d["trunk"][-1]["w"])
    assert np.asarray(d["trunk"][0]["w"]).shape[1] == OLD_OBS
    assert np.asarray(d["policy"][0]["w"]).shape[1] == hidden + OLD_ACT

    new = json.loads(json.dumps(d))                 # 深いコピー
    new["trunk"][0]["w"] = _widen(d["trunk"][0]["w"], OBS_MAP, NEW_OBS, col_offset=0)
    new["policy"][0]["w"] = _widen(d["policy"][0]["w"], ACT_MAP, NEW_ACT, col_offset=hidden)
    new["obs_dim"] = NEW_OBS
    new["act_dim"] = NEW_ACT
    new["encoding_version"] = 4

    # --- 検算 ---
    #
    # **主の検算は float64 で行う**（EXACT_TOL）。挿した列に掛かる重みは 0 なので、
    # 実数の計算としては**完全に**一致するはずで、実際 float64 では 1e-15 台に収まる。
    # ここが緩んだら「列の対応（OBS_MAP / ACT_MAP）が間違っている」ということである。
    #
    # **float32 は報告するだけで関門にしない**（ROUND_REPORT を超えたら知らせる）。
    # 理由: 挿した 0 の列そのものは float32 でも厳密に 0 を足すだけで誤差を生まないが、
    # 行が長くなると BLAS の区切り方が変わり、**もともと在る非零項の足し算の順序**が変わる。
    # D-062 の移行は 12 列を削るだけだったので 1e-6 台に収まったが、本移行は
    # 観測に 717 列・行動に 115 列を挿すため、幅の狭い頭（hidden=64 の `pi_small64_e10`）で
    # 1e-5 台まで出る。これは移行の誤りではなく再結合の丸めである。
    #
    # 「打ち方が変わらないか」はここでは決められない。それは digest と fingerprint の仕事で、
    # `tests/test_bp01.py` T-K-1（ネット無しの digest）と K-5 の三者一致・fingerprint が担う。
    rng = np.random.RandomState(20260910)
    worst_h = worst_p = 0.0
    worst_h64 = worst_p64 = 0.0
    for trial in range(200):
        x_old = rng.randint(-8, 9, size=OLD_OBS).astype(np.float64)
        x_new = np.zeros(NEW_OBS, dtype=np.float64)
        x_new[OBS_MAP] = x_old
        a_old = rng.randint(0, 2, size=OLD_ACT).astype(np.float64)
        a_new = np.zeros(NEW_ACT, dtype=np.float64)
        a_new[ACT_MAP] = a_old

        # 主: float64（数学的な一致）
        h_old64, h_new64 = _forward_trunk(d, x_old, np.float64), _forward_trunk(new, x_new, np.float64)
        worst_h64 = max(worst_h64, _rel(h_old64, h_new64))
        assert worst_h64 < EXACT_TOL, (
            f"幹の出力が float64 で一致しない＝列の対応が誤っている "
            f"(trial={trial}, rel={worst_h64:.3g})")
        worst_p64 = max(worst_p64, _rel(_forward_policy(d, h_old64, a_old, np.float64),
                                        _forward_policy(new, h_new64, a_new, np.float64)))
        assert worst_p64 < EXACT_TOL, (
            f"方策の出力が float64 で一致しない＝列の対応が誤っている "
            f"(trial={trial}, rel={worst_p64:.3g})")

        # 従: float32（実際に走らせる精度での丸め。報告のみ）
        h_old, h_new = _forward_trunk(d, x_old), _forward_trunk(new, x_new)
        worst_h = max(worst_h, _rel(h_old, h_new))
        worst_p = max(worst_p, _rel(_forward_policy(d, h_old, a_old),
                                    _forward_policy(new, h_new, a_new)))

    note = ""
    if max(worst_h, worst_p) > ROUND_REPORT:
        note = (f"  ※ float32 の丸めが {max(worst_h, worst_p):.2e}（目安 {ROUND_REPORT:.0e} 超）。"
                f"float64 では {max(worst_h64, worst_p64):.2e} なので移行は厳密。"
                f"幅の狭い頭ほど大きく出る")

    if check_only:
        print(f"  {os.path.basename(path)}: 検算のみ（書き換えなし・"
              f"float64 幹 {worst_h64:.2e} / 方策 {worst_p64:.2e}・"
              f"float32 幹 {worst_h:.2e} / 方策 {worst_p:.2e}）")
        if note:
            print(note)
        return "migrated"

    bak = path[:-len(".json")] + ".enc3.bak.json" if path.endswith(".json") else path + ".enc3.bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(new, f)
    print(f"  {os.path.basename(path)}: 移行完了 "
          f"obs {OLD_OBS}→{NEW_OBS} / act {OLD_ACT}→{NEW_ACT} / enc 3→4"
          f"（200 例で float64 の相対差 幹 {worst_h64:.2e} / 方策 {worst_p64:.2e}＝厳密。"
          f"float32 は 幹 {worst_h:.2e} / 方策 {worst_p:.2e}。原本 {os.path.basename(bak)}）")
    if note:
        print(note)
    return "migrated"


def _rel(a, b) -> float:
    """相対差（分母は値の大きさ。ゼロ近傍で暴れないよう 1.0 を下限に取る）。"""
    a = np.asarray(a, np.float64); b = np.asarray(b, np.float64)
    scale = np.maximum(np.maximum(np.abs(a), np.abs(b)), 1.0)
    return float(np.max(np.abs(a - b) / scale))


def _dense(layer, dt):
    return (np.asarray(layer["w"], dt), np.asarray(layer["b"], dt))


def _forward_trunk(d, x, dt=np.float32):
    h = np.asarray(x, dt)
    for l in d["trunk"]:
        w, b = _dense(l, dt)
        h = np.maximum(w @ h + b, 0.0).astype(dt)
    return h


def _forward_policy(d, h, a, dt=np.float32):
    v = np.concatenate([np.asarray(h, dt), np.asarray(a, dt)])
    n = len(d["policy"])
    for i, l in enumerate(d["policy"]):
        w, b = _dense(l, dt)
        v = (w @ v + b).astype(dt)
        if i + 1 < n:
            v = np.maximum(v, 0.0)
    return v


BAK_SUFFIX = ".enc3.bak.json"


def _expand(args: list) -> list:
    """引数のワイルドカードをこの道具の側で開く（D-083 追記 1）。

    Linux のシェルは `results/models/*.json` をファイル名の並びに展開してから
    渡すが、**Windows の `cmd` は展開せず文字列のまま渡す**。そのままだと
    `open()` が `OSError: [Errno 22] Invalid argument` で落ちる——「ファイルが無い」
    とも言わないので原因が分かりにくい。**この道具はマスターの PC でも回すので、
    展開は道具の側で行う。**

    展開ずみの引数（`*` や `?` を含まない普通のパス）はそのまま通す。
    並び順はシェルに依らないよう毎回ソートする。
    """
    out = []
    for a in args:
        if any(c in a for c in "*?[") and not os.path.exists(a):
            hits = sorted(glob.glob(a))
            if not hits:
                raise SystemExit(f"一致するファイルがない: {a}")
            # **原本（`*.enc3.bak.json`）はワイルドカードから外す**（D-083 追記 2）。
            # 原本は enc 3 の正しいネットなので、外さないと 2 回目の実行で
            # 原本まで移行され、その原本の原本（`.enc3.bak.enc3.bak.json`）が
            # できてしまう。**「冪等」はファイル 1 つごとの話でしかない。**
            # 名指しされたときは外さない（原本を検算したいことがある）。
            hits = [h for h in hits if not h.endswith(BAK_SUFFIX)]
            if not hits:
                raise SystemExit(f"原本（{BAK_SUFFIX}）しか一致しない: {a}")
            out.extend((h, True) for h in hits)
        else:
            out.append((a, False))
    return out


def main(argv: list) -> int:
    check = "--check" in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    paths = _expand(args)
    print("便 K 段 K-1 ネット移行（BP01 の列を 0 として挿す・enc 3→4）")
    print(f"引数が指すファイル {len(paths)} 件"
          + ("（検算のみ・書き換えなし）" if check else ""))
    tally = {"migrated": 0, "already": 0, "skipped": 0}
    for p, from_glob in paths:
        tally[migrate(p, check_only=check, from_glob=from_glob)] += 1
    print(f"合計: 移行 {tally['migrated']} / 既に移行済み {tally['already']} "
          f"/ 対象外 {tally['skipped']}")
    if tally["migrated"] == 0 and tally["already"] == 0:
        print("★ ネットが 1 つも見つからなかった。引数が正しいか確かめること")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
