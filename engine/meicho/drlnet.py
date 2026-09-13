"""DRL のネット（学習は torch・推論の参照実装は numpy・書き出しは JSON）。`DRL_PLAN.md` §3。

- `Net`（numpy）: Rust 版 `net.rs` と同じ計算の**参照実装**。一致テストと、学習後の検算に使う。
- `to_json` / `from_json`: Rust が読む形式。行列は [out][in]・f32。
- 学習本体は `experiments/drl_train.py`（torch）。ここには torch を置かない
  （エンジン側の import を軽く保つため）。

構造: 幹 = 全結合+ReLU × n → 価値の頭（1 出力・sigmoid）／方策の頭 = [幹の出力 ⊕ 行動特徴] →
全結合+ReLU → 1 出力（合法手の中で softmax）。
"""
from __future__ import annotations

import json
import os

import numpy as np

from .encode import ACT_DIM, ENCODING_VERSION, OBS_DIM, expand_action

# normpath で `..` を畳んでおく（D-074）: PyInstaller で固めると `meicho/` は物理フォルダとして
# 存在せず、Linux では `.../meicho/../results` の途中の `meicho` が無いだけで open が落ちる。
# 指す先のファイルは同じなので、挙動は変わらない。
_MODELS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                        "results", "models"))


def resolve_model(path: str) -> str:
    """モデルのパスを解決する。名前だけなら `results/models/` から探す。

    ガントレット JSON や champion の定義にはファイル名だけを書けるようにしておく
    （**絶対パスを書くと環境をまたいで再現できない**——C-1 の教訓）。
    """
    if os.path.isabs(path) or os.path.exists(path):
        return path
    cand = os.path.join(_MODELS, path)
    if not path.endswith(".json"):
        cand += ".json"
    return cand


class Net:
    def __init__(self, trunk, value, policy, obs_dim=OBS_DIM, act_dim=ACT_DIM,
                 encoding_version=ENCODING_VERSION):
        # 各層は (W[out,in] float32, b[out] float32)
        self.trunk = [(np.asarray(w, np.float32), np.asarray(b, np.float32)) for w, b in trunk]
        self.value = None if value is None else (np.asarray(value[0], np.float32), np.asarray(value[1], np.float32))
        self.policy = [(np.asarray(w, np.float32), np.asarray(b, np.float32)) for w, b in policy]
        self.obs_dim, self.act_dim, self.encoding_version = obs_dim, act_dim, encoding_version

    # --- 推論（Rust と同じ順序・f32） ---
    def trunk_out(self, x) -> np.ndarray:
        h = np.asarray(x, np.float32)
        for w, b in self.trunk:
            h = np.maximum(w @ h + b, 0.0).astype(np.float32)
        return h

    def value_of(self, x) -> float:
        h = self.trunk_out(x)
        w, b = self.value
        z = float((w @ h + b)[0])
        return 1.0 / (1.0 + np.exp(-z))

    def policy_scores(self, x, codes) -> list:
        h = self.trunk_out(x)
        out = []
        for code in codes:
            v = np.concatenate([h, np.asarray(expand_action(code), np.float32)])
            n = len(self.policy)
            for i, (w, b) in enumerate(self.policy):
                v = (w @ v + b).astype(np.float32)
                if i + 1 < n:
                    v = np.maximum(v, 0.0)
            out.append(float(v[0]))
        return out

    # --- 直列化 ---
    def to_dict(self) -> dict:
        dense = lambda wb: {"w": wb[0].astype(np.float32).tolist(), "b": wb[1].astype(np.float32).tolist()}
        return {
            "encoding_version": self.encoding_version, "obs_dim": self.obs_dim, "act_dim": self.act_dim,
            "hidden": int(self.trunk[-1][0].shape[0]) if self.trunk else 0,
            "trunk": [dense(l) for l in self.trunk],
            "value": None if self.value is None else dense(self.value),
            "policy": [dense(l) for l in self.policy],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)

    @staticmethod
    def load(path: str, strict: bool = True) -> "Net":
        """保存済みネットを読む。

        D-062: 既定で**現在の符号化と形が合っているか**を検査する。
        カードが増減すると入力の長さが変わるため、形の合わないネットを黙って
        読むと「別のカードの枠を読む」壊れ方をする。合わなければここで落とす。
        古い版を意図的に読む場合だけ strict=False にする。
        """
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if strict:
            if (d["obs_dim"], d["act_dim"]) != (OBS_DIM, ACT_DIM):
                raise ValueError(
                    f"{path}: 符号化の形が合わない "
                    f"(保存 obs={d['obs_dim']} act={d['act_dim']} / "
                    f"現在 obs={OBS_DIM} act={ACT_DIM})。"
                    f"カード登録簿が変わっている。scripts/migrate_nets_d062.py 等で移行するか、"
                    f"学習し直すこと。")
            if d["encoding_version"] != ENCODING_VERSION:
                raise ValueError(
                    f"{path}: encoding_version が違う "
                    f"(保存 {d['encoding_version']} / 現在 {ENCODING_VERSION})")
        return Net([(l["w"], l["b"]) for l in d["trunk"]],
                   None if d.get("value") is None else (d["value"]["w"], d["value"]["b"]),
                   [(l["w"], l["b"]) for l in d.get("policy", [])],
                   d["obs_dim"], d["act_dim"], d["encoding_version"])


def random_net(seed: int = 0, hidden: int = 32, obs_dim: int = OBS_DIM, act_dim: int = ACT_DIM) -> Net:
    """テスト用の乱数ネット（一致テストは重みの中身を問わない）。"""
    r = np.random.RandomState(seed)
    s = 0.1
    trunk = [(r.randn(hidden, obs_dim) * s, r.randn(hidden) * s),
             (r.randn(hidden, hidden) * s, r.randn(hidden) * s)]
    value = (r.randn(1, hidden) * s, r.randn(1) * s)
    policy = [(r.randn(hidden, hidden + act_dim) * s, r.randn(hidden) * s),
              (r.randn(1, hidden) * s, r.randn(1) * s)]
    return Net(trunk, value, policy, obs_dim, act_dim)
