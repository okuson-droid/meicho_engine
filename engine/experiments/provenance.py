"""測定結果に添える「由来」（文献計画 便 D・D-2 / D-3）。

## なぜ要るか

このプロジェクトの勝率はすべて**条件つき**である。「0.606」という数字は
「どの探索器で・どの価値関数を積んで・どの実装で・どのシード帯で」測ったかが決まって
はじめて意味を持つ。ところが結果の JSON にはこれまで「新」「前」といった**人が書いた
ラベル**しか入っておらず、後から機械で突き合わせられなかった。

実際に起きた事故がその証拠である。同じ `drl_sd001_vc4.json` という名前のファイルが
学習のやり直しで中身だけ変わっていても、結果の JSON からは見分けが付かない。
**名前ではなく中身の指紋（sha256）を残す**のがこの道具の役目である。

## 何を残すか

    provenance = {
      "label":  "champion:planner_vb3cps",   # champion と一致するときはその名前
      "kwargs": {...},                        # 探索器の引数（モデルは**名前のまま**）
      "models": {"value_net": {"file":..., "sha256":..., "bytes":...}, ...},
      "engine": "rust" | "python",
      "rust_features": [...],                 # Rust 側が持っている機能の一覧
      "band":   [seed0, seed_last],
      "rules_version": "v0.11",
      "written_at": "2026-09-07T12:34:56+09:00",
      "extra":  {...},
    }

`sha256` は「ファイルの中身から作る 64 桁の 16 進数」である。中身が 1 バイトでも違えば
まったく違う値になり、同じなら必ず同じ値になる。**同じ名前で中身が違うファイル**を
見分けるのに使う。

## V 凍結の規約（`REPORTING_RULES.md` §2.8）

由来は**測定の開始時**に作って書き出す。終了時に作ると「測っている途中で V を差し替える」
という抜け道が残る。門番の結果を見てから V を差し替えるのは、答えを見てから問題を
選び直すのと同じで、勝率が意味を失う。
"""
from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

JST = timezone(timedelta(hours=9))
RULES_VERSION = "v0.11"
ENGINE_VERSION = "v0.1"
MODEL_KEYS = ("value_net", "opp_policy_net", "policy_net")
ENGINES = ("rust", "python")
# 測定を回した機械の名前として認める値（D-072 判断 6・D-076 判断 5）。
# `cowork-2` は 2026-09-10（便 C・D-077）に足した「クラウドの作業機」である。
HOSTS = ("workenv-2", "cowork-2", "kaggle-cpu-4", "gcp-c3d-16")


def sha256_of(path: str) -> str:
    """ファイルの中身の sha256（64 桁の 16 進）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_info(name: str) -> dict:
    """モデル 1 つぶんの指紋。**見つからなくても落とさず、その旨を残す。**

    測定の記録を残すのが仕事なので、ここで例外を投げて測定を止めるのは本末転倒である。
    ただし黙って空にすると「指紋を取ったのに一致した」と読めてしまうので、
    `sha256: null` と `error` を必ず残す。
    """
    from meicho.drlnet import resolve_model
    try:
        path = resolve_model(name)
    except Exception as e:                                    # noqa: BLE001
        return {"file": os.path.basename(str(name)), "sha256": None,
                "bytes": None, "error": f"{type(e).__name__}: {e}"}
    try:
        return {"file": os.path.basename(path), "sha256": sha256_of(path),
                "bytes": os.path.getsize(path)}
    except OSError as e:
        return {"file": os.path.basename(path), "sha256": None, "bytes": None,
                "error": f"{type(e).__name__}: {e}"}


def _champion_label(kwargs: dict) -> str | None:
    """kwargs が `champion.py` のどれかと一致すれば `champion:<名前>` を返す。"""
    try:
        import champion as chmod
    except Exception:                                         # noqa: BLE001
        return None
    # champion を替えたら**ここも直す**（`champion.py` の定義そのものではなく、
    # 由来ブロックに載せる**表示名**の対応表である。直し忘れると新 champion の由来に
    # 旧 champion の札が付く。便 E-0 で `planner_vb3cps` → `planner_vc4cps`、
    # 便 C で `planner_vc4cps` → `planner_vc4cps_kheb`、
    # 便 A 後半で `planner_vc4cps_kheb` → `planner_vc4cps_kheb_b75`）。
    names = {"SD001": "planner_vc4cps_kheb_b75", "SD02": "planner"}
    for deck, kw in chmod.CHAMPIONS.items():
        want = {k: (os.path.basename(v) if k in MODEL_KEYS and isinstance(v, str) else v)
                for k, v in kw.items()}
        got = {k: (os.path.basename(v) if k in MODEL_KEYS and isinstance(v, str) else v)
               for k, v in kwargs.items() if k != "opp_decklist"}
        if want == got:
            return f"champion:{names.get(deck, deck)}"
    return None


def block(kwargs: dict, engine: str, band, label: str | None = None,
          extra: dict | None = None) -> dict:
    """測定結果に添える由来。`kwargs` はモデルの**名前**のまま渡してよい（パスでも可）。

    `band` は `(seed0, seed_last)` か None。`engine` は "rust" か "python" だけ。
    """
    if engine not in ENGINES:
        raise ValueError(f"engine は {ENGINES} のどちらか（もらった値: {engine!r}）")
    kw = {k: v for k, v in kwargs.items() if k != "opp_decklist"}
    models = {k: model_info(v) for k, v in kw.items()
              if k in MODEL_KEYS and isinstance(v, str)}
    feats = None
    if engine == "rust":
        try:
            import meicho_rs
            feats = sorted(meicho_rs.features())
        except Exception:                                     # noqa: BLE001
            feats = []
    return {
        "label": label if label is not None else _champion_label(kw),
        "kwargs": {k: (os.path.basename(v) if k in MODEL_KEYS and isinstance(v, str) else v)
                   for k, v in kw.items()},
        "models": models,
        "engine": engine,
        "rust_features": feats,
        "band": [int(band[0]), int(band[1])] if band else None,
        "rules_version": RULES_VERSION,
        "engine_version": ENGINE_VERSION,
        "written_at": datetime.now(JST).isoformat(timespec="seconds"),
        "extra": extra or {},
    }


def host_name() -> str:
    """測定を回した機械の名前（D-072 判断 6・`COMPUTE_PLAN_20260908.md` §5-3）。

    認める値は `HOSTS`——`workenv-2`（マスターの PC の作業環境・既定）／
    **`cowork-2`（クラウドの作業機。2026-09-10・D-076 判断 5 で追加）**／
    `kaggle-cpu-4`（D-072 の裏実行）／`gcp-c3d-16`（有料 VM）。
    環境変数 `MEICHO_HOST` で渡す。

    **由来に入れるのは、どの機械で取った記録かを後から見分けるためだけ**で、
    結果そのものは機械によらない（シードごとに決定的）。速さの数字だけが
    機械と `workers` で変わる。

    知らない値は**その場で拒否する**。host は測定を始める前に 1 回だけ読むので、
    ここで落ちても失うものは無い。黙って通すと「打ち間違えた名前の機械」で
    取った記録が台帳に残り、後から見分けられなくなる（この欄の存在理由が消える）。
    """
    h = os.environ.get("MEICHO_HOST", "workenv-2")
    if h not in HOSTS:
        raise ValueError(f"MEICHO_HOST が知らない値: {h!r}（{list(HOSTS)} のどれか）")
    return h


def band_of(seed0: int, n: int):
    """`(seed0, seed0 + n − 1)`。n=0 なら None。"""
    return (int(seed0), int(seed0 + n - 1)) if n else None
