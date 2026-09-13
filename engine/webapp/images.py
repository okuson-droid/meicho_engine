"""カード画像の索引（UI_DESIGN.md §4.1）。

**ファイル名の先頭のカードIDだけを見る。** 残り（キャラ名・レベル・誤字・異体字）は
一切見ない。したがって `cards/` の画像名が多少ずれていても正しく引ける
（誤字 `秋秋`・異体字 `鈎縄`・`_LV1` の欠落。UI_DESIGN.md §2.2・裁定 Q3）。

`-R` は**パラレル（別イラスト・同じカード）**である（UI_DESIGN.md §2.1）。
ゲーム上は完全に同じカードなので、**既定は `-R` の無い方**を使う（裁定 Q2）。

索引はプロセス起動時に 1 回だけ作り、対局中はフォルダを見に行かない
（対局の途中でファイルが増減しても表示が揺れない。決定性の方針と揃える）。

**ここはルールを持たない。** 画像は見た目でしかなく、合法手にも記録にも関わらない。
"""
from __future__ import annotations

import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))

# `cards/` は engine/ の**兄弟**である（リポジトリ直下）。D-062 でカードデータの
# 唯一の正本になったフォルダで、画像もそこにある。
CARDS_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "cards"))

# 公式のカード番号。例: SD01-009 / BP01-023
ID_RE = re.compile(r"^([A-Z]{2}[0-9]{2}-[0-9]{3})")

# 経路に使ってよい ID の書式（サーバの入口で必ずこれを通す・§4.2）
FULL_ID_RE = re.compile(r"^[A-Z]{2}[0-9]{2}-[0-9]{3}$")

URL_PREFIX = "/card/"

_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _is_parallel(stem: str) -> bool:
    """パラレル（`-R` 付き）かどうか。"""
    return stem.endswith("-R")


def build_index(cards_dir: str | None = None) -> dict[str, str]:
    """`{カードID: 画像の絶対パス}` を作る。

    同じ ID に複数のファイルが当たったら、**非パラレルを優先**し、
    それでも決まらなければファイル名の辞書順で先頭を採る（＝結果が決定的）。
    """
    d = cards_dir or CARDS_DIR
    if not os.path.isdir(d):
        return {}
    index: dict[str, str] = {}
    for name in sorted(os.listdir(d)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in _EXT:
            continue
        m = ID_RE.match(name)
        if not m:
            continue
        cid = m.group(1)
        cur = index.get(cid)
        if cur is None:
            index[cid] = os.path.join(d, name)
            continue
        cur_par = _is_parallel(os.path.splitext(os.path.basename(cur))[0])
        new_par = _is_parallel(stem)
        if cur_par and not new_par:          # 非パラレルが来たら差し替える
            index[cid] = os.path.join(d, name)
    return index


_INDEX: dict[str, str] | None = None


def get_index() -> dict[str, str]:
    """索引（起動時に 1 回だけ作る）。"""
    global _INDEX
    if _INDEX is None:
        _INDEX = build_index()
    return _INDEX


def reset_index() -> None:
    """検査用。次の `get_index()` で作り直す。"""
    global _INDEX
    _INDEX = None


def path_for(card_id: str) -> str | None:
    return get_index().get(card_id)


def url_for(card_id: str) -> str | None:
    """画面に渡す URL。**画像が無ければ None**（画面はテキストに落ちる・§P3）。"""
    return (URL_PREFIX + card_id + ".png") if card_id in get_index() else None


def id_from_url_path(path: str) -> str | None:
    """`/card/SD01-009.png` → `SD01-009`。書式に合わなければ None。

    **経路の文字列からファイルパスを組み立てない。** ここで ID を取り出し、
    索引の辞書から引くだけなので、フォルダ横断の危険が構造的に無い（§4.2）。
    """
    if not path.startswith(URL_PREFIX):
        return None
    tail = path[len(URL_PREFIX):]
    stem, ext = os.path.splitext(tail)
    if ext.lower() != ".png":
        return None
    return stem if FULL_ID_RE.match(stem) else None


def duplicate_groups(index: dict[str, str] | None = None) -> list[list[str]]:
    """**中身がまったく同じ画像を使っている別カード**を見つける。

    取り込みのときに 1 枚を別名で複製してしまう事故が実際にあった
    （`SD01-019_轟音.png` が `SD01-018_音の形回避.png` の複製で、
    **轟音の画像は一度も入っていなかった**。D-063 v3）。

    パラレル（`-R`）は別イラストなので中身が違う。したがって
    **別の ID が同じ中身を指していたら、必ずどちらかが間違い**である。
    どちらが正しいかは機械には分からないので、見つけて報告するだけにする。
    """
    import hashlib
    idx = index if index is not None else get_index()
    by_hash: dict[str, list[str]] = {}
    for cid, path in sorted(idx.items()):
        try:
            with open(path, "rb") as f:
                h = hashlib.md5(f.read()).hexdigest()
        except OSError:
            continue
        by_hash.setdefault(h, []).append(cid)
    return [v for v in by_hash.values() if len(v) > 1]


# 画像を持たないことを承知している実装カードの許容リスト（D-079 追記 2・便 K 段 K-1）。
# マスター裁定 2026-09-10 により BP01 のカード画像は取得しない。画面は名前と効果文で描く。
NO_IMAGE_PATH = os.path.join(CARDS_DIR, "BP01_NO_IMAGE.json")


def no_image_allowlist() -> set:
    """画像が無くてよい番号。ファイルが無ければ空集合（＝全部が「欠け」になる）。"""
    try:
        with open(NO_IMAGE_PATH, encoding="utf-8") as f:
            return set(json.load(f)["codes"])
    except OSError:
        return set()


def status() -> dict:
    """実装カードと画像の突き合わせ（画面のバーと点検スクリプトが使う・§7）。

    `missing` は「置くはずなのに無い画像」だけを指す。許容リストに載っている番号は
    **意図して画像が無い**ので `missing` から外し、`no_image` に分けて数だけ見せる
    （0 になるべき数と、承知のうえで 0 でない数を混ぜない）。
    """
    from meicho.cards import ACTION_CARDS, CHARA_CARDS
    index = get_index()
    implemented = set(ACTION_CARDS) | set(CHARA_CARDS)
    allow = no_image_allowlist()
    missing = sorted(cid for cid in implemented if cid not in index and cid not in allow)
    no_image = sorted(cid for cid in implemented if cid not in index and cid in allow)
    # 許容リストに載っているのに画像が在る＝リストの消し忘れ。黙って通さない。
    stale = sorted(cid for cid in allow if cid in index)
    unused = sorted(cid for cid in index if cid not in implemented)
    return {"indexed": len(index), "implemented": len(implemented),
            "missing": missing, "no_image": no_image, "stale_allowlist": stale,
            "unused": unused,
            # 中身が同じ＝どちらかが間違った画像（§7.1-4）
            "duplicates": duplicate_groups(index)}
