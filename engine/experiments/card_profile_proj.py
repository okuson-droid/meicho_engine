"""カードの効果表現を V の第 1 層に足す射影（段階2 の表現比較・D-132）。

計画書 `GENERALIST_AI_REVIEW_D086.md` §4.2・§4.4。検査 `tests/test_card_profile_proj.py`（C-1〜C-5）。

観測（符号化 v6）の中には「カード 1 種 = 1 列」の枚数ベクトルの塊がある——アクションカードの塊が 15
（自分の手札・協奏・トラッシュ・アクションエリア／相手のスキャン既知・協奏・トラッシュ・アクションエリア／
対抗の札 2・前回の対抗の札 2／最後に使った札 2／統一した既知の手札）、キャラカードの塊が 13（自分と相手の
キャラ枠の最上段 6・キャラ山札 1・キャラ枠の下 6）。

各塊 b の枚数ベクトル x_b（カード種の数だけの長さ）に、カード種 × 素性の 0/1 行列 P を掛けた
x_b @ P（「この塊に、この素性を持つカードが何枚あるか」）を**学習のときだけ**入力に足す。
素性は `analyse_card_space.profile`（色・コスト・速度・打点・タグ・スキルのタイミング・条件・作用…）で、
**カード ID・カード名・専用キャラ名を使わない**（同じ素性のカードは区別しない）。

足す列はすべて観測の線形写像なので、学習後に第 1 層へ畳み込める:
    W_id · x + W_pf · (x @ M) = (W_id + W_pf · Mᵀ) · x
書き出したネットは射影なしのネットと**同じ形**（第 1 層の入力は OBS_DIM）で、Rust も符号化も変えない。
したがって「射影つき」と「射影なし」は**表せる関数の集合が同じ**であり、違いは学び方（同じ素性の
カードに同じ重みの成分が乗る＝素性の共有）だけである。容量の差ではない（計画書 §6 段階2 の懸念への答え）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from analyse_card_space import profile                                 # noqa: E402
from meicho import encode as E                                          # noqa: E402
from meicho.cards import ACTION_CARDS, CHARA_CARDS                       # noqa: E402

VERSION = "cardprof-1"


def blocks() -> tuple[list, list]:
    """観測の中の枚数ベクトルの塊の先頭位置（`meicho/encode.py::encode_obs` の並びをそのまま写す）。"""
    na, nc = E.NA, E.NC
    s = E.N_SCALAR
    a = [s + k * na for k in range(12)]            # 自分 4・相手 4・対抗 2・前回の対抗 2
    s += 12 * na
    c = [s + k * nc for k in range(13)]            # キャラ枠の最上段 6・キャラ山札 1・枠の下 6
    s += 13 * nc
    s += 2 * len(E.ACTION_TAGS)                    # タグの使用回数（枚数ベクトルではない）
    a += [s, s + na]                               # 最後に使った札 2
    s += 2 * na
    assert s == E.OBS_DIM_V5, (s, E.OBS_DIM_V5)
    s += E.N_BELIEF                                # 信念の要約（枚数ベクトルではない）
    a.append(s)                                    # 統一した既知の手札（v6）
    s += na
    assert s == E.OBS_DIM, (s, E.OBS_DIM)
    return a, c


def build_projection():
    """(M, info)。M は OBS_DIM × 特徴数の float32（0/1）。"""
    va = sorted({k for cid in E.ACTION_IDS for k in profile(ACTION_CARDS[cid])})
    vc = sorted({k for cid in E.CHARA_IDS for k in profile(CHARA_CARDS[cid])})
    ia = {k: j for j, k in enumerate(va)}
    ic = {k: j for j, k in enumerate(vc)}
    Pa = np.zeros((E.NA, len(va)), np.float32)
    for i, cid in enumerate(E.ACTION_IDS):
        for k in profile(ACTION_CARDS[cid]):
            Pa[i, ia[k]] = 1.0
    Pc = np.zeros((E.NC, len(vc)), np.float32)
    for i, cid in enumerate(E.CHARA_IDS):
        for k in profile(CHARA_CARDS[cid]):
            Pc[i, ic[k]] = 1.0
    a_blocks, c_blocks = blocks()
    n_feat = len(a_blocks) * len(va) + len(c_blocks) * len(vc)
    M = np.zeros((E.OBS_DIM, n_feat), np.float32)
    col = 0
    for st in a_blocks:
        M[st:st + E.NA, col:col + len(va)] = Pa
        col += len(va)
    for st in c_blocks:
        M[st:st + E.NC, col:col + len(vc)] = Pc
        col += len(vc)
    assert col == n_feat
    sha = hashlib.sha256(json.dumps([va, vc], ensure_ascii=False).encode()).hexdigest()[:16]
    info = {"version": VERSION, "n_features": n_feat, "vocab_action": len(va), "vocab_chara": len(vc),
            "a_blocks": a_blocks, "c_blocks": c_blocks, "vocab_sha": sha,
            "encoding_version": E.ENCODING_VERSION, "obs_dim": E.OBS_DIM}
    return M, info
