"""記録つき自己対戦（`meicho_rs.series_record`）の読み戻し（DRL 段階 0）。

ファイル形式（`rust/src/lib.rs::run_one_record`・リトルエンディアン）:
  ヘッダ: b"MCDR" / version u32 / obs_dim u32 / act_code_len u32
  レコード（決定 1 つ・**版 2**）:
    seed i64 / step u32 / turn u16 / pi u8 / phase u8 / n_acts u8 / chosen u8 / z f32 /
    obs i8[obs_dim] / acts i8[n_acts*ACT_CODE_LEN] / scores f32[n_acts]
  レコード（決定 1 つ・**版 3**・D-065 A-3 (i)）: 版 2 の `z` の直後に `fresh f32` が入る。

記録されるのは**合法手が 2 つ以上あった決定**だけ（1 つしかない決定は学ぶものがない）。
`z` は決定者から見た最終結果（勝 1 / 負 0 / 引き分け 0.5 / 打ち切り NaN）。
`scores` は探索が採点した各合法手の値（探索していない手・探索しなかった決定は NaN）。
`fresh` は**選んだ手を別の決定化で取り直した値**（二重推定・`reeval_samples>0` のときだけ。
それ以外と版 2 の記録では NaN）。根の探索値の最大値は決定化の揺れを最大で拾うぶん
楽観するので（レビュー §2.3・+0.17）、その偏りを持たない教師を並べて記録する。

**版 2 の記録（vb1_*〜vb4_*）はそのまま読める**（`tests/test_d065.py::
test_record_v2_is_still_readable`）。読み側は版で構造体を切り替えるだけである。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from .encode import ACT_CODE_LEN

HEADER = struct.Struct("<4sIII")
REC_HEAD = struct.Struct("<qIHBBBBf")          # 版 2
REC_HEAD_V3 = struct.Struct("<qIHBBBBff")      # 版 3（`fresh` を足した・D-065 §2.5）
SUPPORTED_VERSIONS = (2, 3)

# `series_rs_digest(PLANNER(pool), PLANNER(pool), 6, mirror_config(SD001), workers=2, seed0=230000)` を
# ネットの差し替え口を入れる前の Rust 版（D-054 時点の wheel）で取った各局の digest。
# `tests/test_drl.py::test_planner_without_nets_is_unchanged` が「既定の planner は一手も変わっていない」ことに使う。
#
# D-062 (2026-08-31) で値が変わった。原因は **2 つあり、性質がまったく違う**。
#
# (1) カードIDを公式番号に付け替えたこと（6局すべての値が変わる）。
#     planner は先読みのために「相手の手札にありうるカード」を並べて混ぜる。
#     その並べる順が **card_id の文字列順** である（`rust/src/agents.rs::sort_by_id`。
#     順序を固定しないと情報が漏れるため・determinization_leak.md）。
#     IDの綴りが変われば並び順が変わり、同じ乱数でも別の並びが出る。
#     **これは「別のシードで回した」のと同じで、AI の強さは変わっていない。**
#     ただし **改名をまたいで同じシードの結果を比べることはできない**。
# (2) 秧秧Lv2の発動条件の訂正（この 6 局のうち 1 局だけ値が変わる）。
#     (1) だけを適用した木で digest を取り、そこからさらに (2) を適用して
#     6 局中 1 局（seed0+3）だけが変わることを確認した。**カードのルールが
#     変わったことによる意図した変化**であり、探索側は一切変えていない。
#
# なお同日の他の 2 つの修正（躍動する炎のタグ追加・AC-001 の削除）では
# 6 局とも digest が変わらないことを確認済みである（＝挙動に影響しない修正）。
#
# 旧値（D-062 以前・旧ID体系。**現在の値と直接は比較できない**）:
#   [3207956217848188898, 6258334730558123478, 17510286256128158187,
#    18280626054432347844, 9419423906054568560, 10148867776317603708]
# (1) のみ適用した中間値（参考。秧秧Lv2 未修正）:
#   [7275559978076803677, 11749350498370779981, 4298370481803233947,
#    17983142086817364878, 5895518031443260061, 1981973080909425922]
# D-091（2026-09-16・マスター裁定）: 段階1A（D-088）が自動選択を合法手にしたため、
# 決定列に新しい選択行動が現れる。digest は決定列を丸ごと取るので、**打ち方を変えなくても
# 動く**（`STAGE1A_NOTES.md` §3 が「全決定列には新しい選択行動が現れる」と認め、T-K-1 の
# digest はそこで更新済み。この定数は更新し忘れていた）。
# 打ち方が変わっていないと判断した根拠は、Python と Rust の毎手一致の検査が通っていること
# （`test_rust_engine.py` / `test_rust_agents.py` / `test_opp_policy_net_python_matches_rust`）。
# **勝敗そのものを突き合わせた直接の測定はしていない**——疑いが出たら実測すること。
# 旧値（D-054 時点・D-088 より前。**現在の値と直接は比較できない**）:
#   [7275559978076803677, 11749350498370779981, 4298370481803233947,
#    17601092096101737152, 5895518031443260061, 1981973080909425922]
# D-104（2026-09-19・マスター裁定）: **A-6（回復にライフの上限は無い・公式 101.6・rules v0.18）で動いた。**
#   D-011（2026-08-21 のマスター裁定「上限 20 でクリップ」）を覆したため、`SD01-023`「奏鳴」(+5) が
#   **序盤から本当に +5 回復する**ようになり、SD001 の対局が変わった。SD02 と BP01 の仮デッキは
#   回復カードを持たないので**1 手も動いていない**。
#   実測（A-6 の前後・ミラー 200 局）: SD001/random 手順 4・勝敗 1／SD001/heuristic 手順 8・勝敗 1／
#   **planner/SD001 手順 80・勝敗 37**／champion の指紋の帯 471500..471509 は手順 4/10・勝敗 4/10。
#   **これは AI の打ち方の変化ではなく、ゲームのルールが公式に合ったことによる変化である。**
#   旧値（v0.17 以前）: seed 230001 が 6452662970305802937。他の 5 局は不変である。
BASELINE_DIGESTS_230000 = [
    3883421622943331980, 6668190221415650951, 12799890403010092276,
    6891336813256004936, 2710111376256602586, 11064977964443866600,
]


@dataclass
class Records:
    n: int
    seed: np.ndarray        # int64 [n]
    step: np.ndarray        # int32 [n]
    turn: np.ndarray        # int16 [n]
    pi: np.ndarray          # int8 [n]
    phase: np.ndarray       # int8 [n]
    n_acts: np.ndarray      # int16 [n]
    chosen: np.ndarray      # int16 [n]
    z: np.ndarray           # float32 [n]
    fresh: np.ndarray       # float32 [n]  選んだ手を別の決定化で取り直した値（版 2 は NaN）
    obs: np.ndarray         # int8 [n, obs_dim]
    act_off: np.ndarray     # int64 [n+1]  行動列の先頭（acts_flat / scores_flat の添字）
    acts_flat: np.ndarray   # int8 [sum n_acts, ACT_CODE_LEN]
    scores_flat: np.ndarray # float32 [sum n_acts]

    def actions_of(self, i: int) -> np.ndarray:
        return self.acts_flat[self.act_off[i]:self.act_off[i + 1]]

    def scores_of(self, i: int) -> np.ndarray:
        return self.scores_flat[self.act_off[i]:self.act_off[i + 1]]


def read_records(paths, max_records: int | None = None) -> Records:
    """複数ファイルを読み、1 つの `Records` にまとめる。

    **2 回読む**（D-132）: 1 回目で決定の数と行動の総数だけを数え、2 回目で先に確保した配列へ
    直接書き込む。1 決定ずつ小さな配列を作って最後に `np.stack` する旧方式（`_read_records_listwise`）は、
    100 万決定（段階2 の教材・D-131）で「小さな配列の山＋積み上げた配列」の両方がメモリに乗り、
    作業環境（約 6 GB）で落ちた。結果は旧方式と 1 ビットも違わない（`tests/test_drl.py` で固定）。
    """
    total, total_acts, obs_dim, layout = 0, 0, None, []
    for path in paths:
        with open(path, "rb") as f:
            data = f.read()
        magic, ver, od, acl = HEADER.unpack_from(data, 0)
        assert magic == b"MCDR" and ver in SUPPORTED_VERSIONS and acl == ACT_CODE_LEN, \
            (magic, ver, acl)
        if obs_dim is None:
            obs_dim = od
        assert od == obs_dim
        head = REC_HEAD_V3 if ver >= 3 else REC_HEAD
        pos, L, cnt = HEADER.size, len(data), 0
        while pos < L:
            na = head.unpack_from(data, pos)[5]
            pos += head.size + obs_dim + na * acl + na * 4
            cnt += 1
            total_acts += na
            total += 1
            if max_records is not None and total >= max_records:
                break
        layout.append((path, ver, cnt))
        del data
        if max_records is not None and total >= max_records:
            break
    n = total
    od = obs_dim or 0
    seed = np.zeros(n, np.int64); step = np.zeros(n, np.int32); turn = np.zeros(n, np.int16)
    pis = np.zeros(n, np.int8); phase = np.zeros(n, np.int8); nacts = np.zeros(n, np.int16)
    chosen = np.zeros(n, np.int16); zs = np.zeros(n, np.float32); fresh = np.zeros(n, np.float32)
    obs = np.zeros((n, od), np.int8)
    acts_flat = np.zeros((total_acts, ACT_CODE_LEN), np.int8)
    scores_flat = np.zeros(total_acts, np.float32)
    i = k = 0
    for path, ver, cnt in layout:
        with open(path, "rb") as f:
            data = f.read()
        head = REC_HEAD_V3 if ver >= 3 else REC_HEAD
        pos = HEADER.size
        for _ in range(cnt):
            if ver >= 3:
                sd, st, tu, pi, ph, na, ch, z, fr = head.unpack_from(data, pos)
            else:
                sd, st, tu, pi, ph, na, ch, z = head.unpack_from(data, pos)
                fr = float("nan")
            pos += head.size
            obs[i] = np.frombuffer(data, np.int8, od, pos)
            pos += od
            acts_flat[k:k + na] = np.frombuffer(data, np.int8, na * ACT_CODE_LEN, pos).reshape(na, ACT_CODE_LEN)
            pos += na * ACT_CODE_LEN
            scores_flat[k:k + na] = np.frombuffer(data, "<f4", na, pos)
            pos += na * 4
            seed[i], step[i], turn[i], pis[i], phase[i] = sd, st, tu, pi, ph
            nacts[i], chosen[i], zs[i], fresh[i] = na, ch, z, fr
            i += 1
            k += na
        del data
    assert i == n and k == total_acts
    act_off = np.zeros(n + 1, np.int64)
    if n:
        act_off[1:] = np.cumsum(nacts.astype(np.int64))
    return Records(n=n, seed=seed, step=step, turn=turn, pi=pis, phase=phase, n_acts=nacts, chosen=chosen,
                   z=zs, fresh=fresh, obs=obs, act_off=act_off, acts_flat=acts_flat, scores_flat=scores_flat)


def _read_records_listwise(paths, max_records: int | None = None) -> Records:
    """複数ファイルを読み、1 つの `Records` にまとめる。"""
    seeds, steps, turns, pis, phases, nacts, chosen, zs = [], [], [], [], [], [], [], []
    freshes = []
    obs_chunks, act_chunks, sc_chunks = [], [], []
    obs_dim = None
    total = 0
    for path in paths:
        with open(path, "rb") as f:
            data = f.read()
        # **各ファイルの中身は読み終わったら手放す。** `np.frombuffer` は元の bytes への
        # 参照を残すので、そのまま溜めると「全ファイルの生バイト」＋「積み上げた配列」の
        # 両方がメモリに乗る。データ窓（複数反復ぶん）を読むとこれで落ちる（実測・D-064）。
        # 下で `.copy()` して自前の領域に移し、`data` を解放できるようにしている。
        magic, ver, od, acl = HEADER.unpack_from(data, 0)
        assert magic == b"MCDR" and ver in SUPPORTED_VERSIONS and acl == ACT_CODE_LEN, \
            (magic, ver, acl)
        if obs_dim is None:
            obs_dim = od
        assert od == obs_dim
        head = REC_HEAD_V3 if ver >= 3 else REC_HEAD
        pos = HEADER.size
        L = len(data)
        while pos < L:
            if ver >= 3:
                seed, step, turn, pi, phase, na, ch, z, fr = head.unpack_from(data, pos)
            else:
                seed, step, turn, pi, phase, na, ch, z = head.unpack_from(data, pos)
                fr = float("nan")
            pos += head.size
            obs_chunks.append(np.frombuffer(data, np.int8, obs_dim, pos).copy())
            pos += obs_dim
            act_chunks.append(np.frombuffer(data, np.int8, na * acl, pos).reshape(na, acl).copy())
            pos += na * acl
            sc_chunks.append(np.frombuffer(data, "<f4", na, pos).copy())
            pos += na * 4
            seeds.append(seed); steps.append(step); turns.append(turn); pis.append(pi)
            phases.append(phase); nacts.append(na); chosen.append(ch); zs.append(z)
            freshes.append(fr)
            total += 1
            if max_records is not None and total >= max_records:
                break
        if max_records is not None and total >= max_records:
            break
        del data                      # このファイルの生バイトを手放す（上の注記）
    n = total
    nacts_arr = np.asarray(nacts, np.int16)
    act_off = np.zeros(n + 1, np.int64)
    if n:
        act_off[1:] = np.cumsum(nacts_arr.astype(np.int64))
    return Records(
        n=n,
        seed=np.asarray(seeds, np.int64), step=np.asarray(steps, np.int32), turn=np.asarray(turns, np.int16),
        pi=np.asarray(pis, np.int8), phase=np.asarray(phases, np.int8), n_acts=nacts_arr,
        chosen=np.asarray(chosen, np.int16), z=np.asarray(zs, np.float32),
        fresh=np.asarray(freshes, np.float32),
        obs=(np.stack(obs_chunks) if n else np.zeros((0, obs_dim or 0), np.int8)),
        act_off=act_off,
        acts_flat=(np.concatenate(act_chunks) if n else np.zeros((0, ACT_CODE_LEN), np.int8)),
        scores_flat=(np.concatenate(sc_chunks) if n else np.zeros(0, np.float32)),
    )
