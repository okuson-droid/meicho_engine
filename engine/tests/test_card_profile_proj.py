"""段階2 の表現比較（D-132）: カードの効果表現を V の第 1 層に足す射影の検査。

計画書 `GENERALIST_AI_REVIEW_D086.md` §4.2・§4.4・§6 段階2。符号化（v6）もエンジンも Rust も変えない。
観測の中の「カード 1 種 = 1 列」の枚数ベクトル（アクション 15 塊・キャラ 13 塊）に、カードの機構の素性
（`analyse_card_space.profile`・カード ID と名前を使わない）を掛けた列を**学習のときだけ**足し、
書き出すときに第 1 層の重みへ畳み込む（`count @ P @ W = count @ (P @ W)`）。

守らせる条項:

C-1 塊の位置: 射影が見る列は観測の中の枚数ベクトルの塊と一致する（実際の観測から作った列で確かめる）
C-2 ID を使わない: 素性が同じ 2 枚のカードは射影の行が完全に同じ
C-3 畳み込みが正確: 学習時の形（観測＋射影の列）と、書き出した重み（観測だけ）の値が一致する
C-4 既定は不変: 射影を渡さないモデルは従来どおり（第 1 層の入力は OBS_DIM）
C-5 関数の集合が同じ: 書き出したネットの形は射影なしのネットと同じ（Rust はそのまま読める）
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

torch = pytest.importorskip("torch")

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import card_profile_proj as CP                                        # noqa: E402
import drl_train as T                                                 # noqa: E402
from meicho import encode as E                                        # noqa: E402
from meicho.cards import ACTION_CARDS, CHARA_CARDS                     # noqa: E402


@pytest.fixture(scope="module")
def proj():
    return CP.build_projection()


def test_blocks_match_real_observation(proj):
    """C-1: 実際の観測の、手札・協奏・トラッシュ・キャラ枠の列が、射影が見る塊の中にある。"""
    from arena import load_deck, mirror_config
    from meicho.engine import initial_state, legal_actions, apply, observe, decision_players
    M, info = proj
    cfg = mirror_config(load_deck("SD001"))
    s = initial_state(cfg, seed=826950)
    rng = np.random.RandomState(0)
    for _ in range(60):                                                 # 手札・トラッシュが埋まるまで進める
        ps = decision_players(s)
        if not ps:
            break
        acts = {p: legal_actions(s, p) for p in ps}
        s = apply(s, {p: a[rng.randint(len(a))] for p, a in acts.items()})
    ob = observe(s, 0)
    x = np.array(E.encode(ob, 0), dtype=np.float32)
    a_cols = sorted(c for st in info["a_blocks"] for c in range(st, st + E.NA))
    c_cols = sorted(c for st in info["c_blocks"] for c in range(st, st + E.NC))
    # 手札の塊は a_blocks の先頭、キャラ山札の塊は c_blocks の 7 番目（encode.py の並び）
    h0 = info["a_blocks"][0]
    assert list(x[h0:h0 + E.NA]) == E._counts(ob["me"]["hand"], E.A_INDEX, E.NA)
    cd = info["c_blocks"][6]
    assert list(x[cd:cd + E.NC]) == E._counts(ob["me"]["chara_deck"], E.C_INDEX, E.NC)
    assert len(info["a_blocks"]) == 15 and len(info["c_blocks"]) == 13
    assert len(set(a_cols)) == 15 * E.NA and len(set(c_cols)) == 13 * E.NC
    assert not set(a_cols) & set(c_cols)
    # 射影が触る行は塊の列だけ
    touched = set(np.nonzero(np.abs(M).sum(1))[0].tolist())
    assert touched <= set(a_cols) | set(c_cols)
    assert M.shape == (E.OBS_DIM, info["n_features"])


def test_same_profile_same_row(proj):
    """C-2: 素性が同じカード（ID・名前だけ違う）は、同じ塊の中で射影の行が同じ。"""
    M, info = proj
    from analyse_card_space import profile
    groups = {}
    for i, cid in enumerate(E.ACTION_IDS):
        groups.setdefault(tuple(sorted(profile(ACTION_CARDS[cid]).items())), []).append(i)
    dup = [g for g in groups.values() if len(g) > 1]
    assert dup, "素性の重なるカードが無いと検査にならない"
    st = info["a_blocks"][0]
    for g in dup:
        rows = [M[st + i] for i in g]
        assert all(np.array_equal(rows[0], r) for r in rows[1:])
    # キャラも
    groups = {}
    for i, cid in enumerate(E.CHARA_IDS):
        groups.setdefault(tuple(sorted(profile(CHARA_CARDS[cid]).items())), []).append(i)
    st = info["c_blocks"][0]
    for g in (g for g in groups.values() if len(g) > 1):
        assert all(np.array_equal(M[st + g[0]], M[st + i]) for i in g[1:])


def test_fold_is_exact(proj):
    """C-3・C-5: 射影つきで学んだモデルを書き出すと、形は従来どおりで値は一致する。"""
    M, info = proj
    torch.manual_seed(0)
    rng = np.random.RandomState(1)
    scale = np.maximum(1.0, rng.randint(1, 5, size=E.OBS_DIM)).astype(np.float32)
    pscale = np.maximum(1.0, rng.randint(1, 9, size=info["n_features"])).astype(np.float32)
    m = T.TwoHead(32, 2, 16, scale, proj=M, proj_scale=pscale)
    obs = torch.from_numpy(rng.randint(0, 3, size=(8, E.OBS_DIM)).astype(np.float32))
    codes = torch.full((8, 3, E.ACT_CODE_LEN), -1, dtype=torch.long)
    codes[..., 0] = 6
    n_acts = torch.full((8,), 3, dtype=torch.long)
    with torch.no_grad():
        v_t = torch.sigmoid(m(obs, codes, n_acts)[0]).numpy()
    net = m.export()
    assert net.trunk[0][0].shape == (32, E.OBS_DIM)                     # C-5: Rust が読む形は同じ
    v_n = np.array([net.value_of(obs[i].numpy()) for i in range(8)])
    assert np.abs(v_t - v_n).max() < 1e-4


def test_default_model_unchanged():
    """C-4: 射影を渡さなければ第 1 層の入力は OBS_DIM のまま。"""
    m = T.TwoHead(16, 2, 8, np.ones(E.OBS_DIM, np.float32))
    assert m.trunk[0].in_features == E.OBS_DIM
    assert getattr(m, "proj", None) is None


def test_fold_breaks_if_projection_ignored(proj):
    """C-3 をわざと壊す側: 射影の列を畳み込まずに捨てると値がずれる（検査が効いていることの確認）。"""
    M, info = proj
    torch.manual_seed(0)
    m = T.TwoHead(16, 1, 8, np.ones(E.OBS_DIM, np.float32), proj=M,
                  proj_scale=np.ones(info["n_features"], np.float32))
    with torch.no_grad():
        m.trunk[0].weight[:, E.OBS_DIM:] += 0.5                         # 射影の列に重みを持たせる
    obs = torch.ones((1, E.OBS_DIM))
    lin = m.trunk[0]
    w_drop = lin.weight[:, :E.OBS_DIM]
    h_drop = torch.relu(obs @ w_drop.T + lin.bias)
    h_full = torch.relu(torch.cat([obs, obs @ m.proj / m.proj_scale], 1) @ lin.weight.T + lin.bias)
    assert not torch.allclose(h_drop, h_full)
