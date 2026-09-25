"""デッキ類似度（環境デッキ群の選定用・D-126）。設計の正本は `engine/DECK_SIMILARITY_DESIGN.md`。

    python3 experiments/deck_similarity.py decklists/env --anchors \
        --out results/decksim/env_v1.json --md results/decksim/env_v1.md

3 つの層を**別々に**測る（1 つの数字に潰さない）:

- 層 1 構成: 行動デッキ 40 枚の多重集合の重みつき Jaccard。S1_raw（重み 1）・S1_idf（idf 重み）・
  S1_common（専用札を除く・どちらかに共通札が無ければ None）
- 層 2 キャラ: 3 人組のキャラ名の一致数 S2_trio（0〜3）と、キャラデッキの番号の集合の Jaccard S2_deck
- 層 3 動き: `analyse_card_space.profile()` を合算し、族ごとに合計 1 に正規化したベクトルを作り、
  **候補の平均を引いてからのコサイン** S3（[-1, 1]・D-127 裁定）。平均を引かない値は S3_raw として併記する。
  平均を引かないと、どのデッキにもある族（色・コスト帯・速度）の分布が似ているぶんだけどの組も近く見え、
  錨では姉妹 0.999 と別系統 0.971 の差が 0.03 しかなかった（設計書 §6.1）

**idf と平均は候補だけで計算する**（錨は数に入れない・D-127 裁定）。錨を加えても候補どうしの値は変わらない。
錨だけで回したときは錨を基準にし、出力の `basis_note` にそう書く。

対局は回さない。乱数も使わない（同点はデッキ名の辞書順）。同じ入力なら出力のバイト列が一致する。
エンジン本体・Rust・符号化・champion には触れない。

**閾値（`DEFAULT_THRESHOLDS`）は仮置きである**（設計書 §7.1・§10-5）。錨で尺度を見てからマスターが決め、
`results/decksim/thresholds.json` に固定して `--thresholds` で渡す。候補デッキを見たあとには動かさない。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from analyse_card_space import profile as _card_profile      # noqa: E402  写さずに呼ぶ（設計書 §2）
from meicho import cards as C                                # noqa: E402
from meicho.buckets import cost_band                         # noqa: E402

VERSION = "decksim-3"          # 2: S3 を中心化コサインに・idf と平均を候補だけで（D-127）
                               # 3: 手割り（`--split-override`・§7.3-5・D-128）
ANCHORS = ("SD001", "SD02", "K_smoke_ANKO", "K_smoke_SANGE", "K_smoke_TSUBAKI")
DECKLIST_DIR = os.path.join(_HERE, "..", "decklists")

# 仮置き（設計書 §7.1・§7.3）。錨を見てから決める。
DEFAULT_THRESHOLDS = {
    "s2_trio": 3,          # 同じ 3 人組 → 同じグループ
    "s1_idf": 0.5,         # 構成が近い → 同じグループ
    "s3": 0.9,             # 動きが近い → 同じグループ
    "variant_s1_idf": [0.5, 0.8],   # 最終評価の変種枠: 学習デッキと S1_idf がこの範囲・同じ 3 人組
    "family_weights": {},  # 層 3 の族の重み（空 = 全部 1・§10-4）
}
FAMILIES = ("color", "cost", "speed", "damage", "level", "tag", "timing", "cond", "op", "op_param", "misc")


# ------------------------------------------------------------------ 読み込み

def _deck_files(paths) -> list:
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(glob.glob(os.path.join(p, "*.json")))
        else:
            out.append(p)
    return out


def check_legal(deck: dict) -> str | None:
    """`GameConfig.validate` と同じ条件（§3.1・§3.2）。通れば None、通らなければ理由の文。"""
    cd, ad = deck.get("chara_deck"), deck.get("action_deck")
    if not isinstance(cd, list) or not isinstance(ad, list):
        return "chara_deck / action_deck が無い"
    unknown = [c for c in cd if c not in C.CHARA_CARDS] + [c for c in ad if c not in C.ACTION_CARDS]
    if unknown:
        return f"登録簿に無いカード番号: {sorted(set(unknown))}"
    names = {C.CHARA_CARDS[c].name for c in cd}
    if len(names) != 3:
        return f"キャラは 3 種類ちょうど（いま {len(names)} 種類）"
    if not 3 <= len(cd) <= 15:
        return f"キャラデッキは 3〜15 枚（いま {len(cd)} 枚）"
    if len(cd) != len(set(cd)):
        return "キャラデッキに同じ番号が 2 枚以上ある"
    for n in names:
        lv0 = sum(1 for c in cd if C.CHARA_CARDS[c].name == n and C.CHARA_CARDS[c].level == 0)
        if lv0 != 1:
            return f"{n} の Lv.0 はちょうど 1 枚（いま {lv0} 枚）"
    if len(ad) != 40:
        return f"アクションデッキは 40 枚ちょうど（いま {len(ad)} 枚）"
    for cid, k in sorted(Counter(ad).items()):
        if k > 3:
            return f"{cid} は 3 枚まで（いま {k} 枚）"
        ded = C.ACTION_CARDS[cid].dedicated_to
        if ded is not None and ded not in names:
            return f"専用カード {cid} に対応するキャラ（{ded}）がいない"
    return None


def load_decks(paths) -> tuple[dict, dict]:
    """デッキの JSON（またはフォルダ）を読む。戻り値は (decks, rejected)。

    `decks = {名前: {"name", "chara_deck", "action_deck", "sha256", "path"}}`。名前は JSON の `name`
    （無ければファイル名）。デッキメーカーの余分な欄は読み飛ばす。合法でないものは `rejected = {名前: 理由}`。
    """
    decks, rejected = {}, {}
    for path in _deck_files(paths):
        with open(path, "rb") as f:
            raw = f.read()
        d = json.loads(raw.decode("utf-8"))
        name = d.get("name") or os.path.splitext(os.path.basename(path))[0]
        if name in decks or name in rejected:
            raise SystemExit(f"デッキ名が重なっている: {name}（{path}）")
        why = check_legal(d)
        if why:
            rejected[name] = why
            continue
        decks[name] = {"name": name, "chara_deck": list(d["chara_deck"]), "action_deck": list(d["action_deck"]),
                       "sha256": hashlib.sha256(raw).hexdigest(), "path": os.path.relpath(path, os.path.join(_HERE, ".."))}
    return decks, rejected


# ------------------------------------------------------------------ 層 1

def compute_idf(decks: dict) -> dict:
    """idf(x) = ln((N+1)/(df(x)+1)) + 1。N はデッキ数、df はその番号を 1 枚以上入れているデッキ数。"""
    n = len(decks)
    df = Counter()
    for d in decks.values():
        for cid in set(d["action_deck"]):
            df[cid] += 1
    return {cid: math.log((n + 1) / (df[cid] + 1)) + 1 for cid in sorted(df)}


def _wjaccard(ca: Counter, cb: Counter, w=None):
    keys = sorted(set(ca) | set(cb))           # 足す順を固定する（a と b を入れ替えても同じ浮動小数点になるように）
    if not keys:
        return None
    num = sum((w[k] if w else 1.0) * min(ca[k], cb[k]) for k in keys)
    den = sum((w[k] if w else 1.0) * max(ca[k], cb[k]) for k in keys)
    return num / den


def layer1(a: dict, b: dict, idf: dict | None = None):
    ca, cb = Counter(a["action_deck"]), Counter(b["action_deck"])
    raw = _wjaccard(ca, cb)
    s_idf = None
    if idf is not None:
        w = {k: idf.get(k, max(idf.values()) if idf else 1.0) for k in set(ca) | set(cb)}
        s_idf = _wjaccard(ca, cb, w)
    ded = lambda c: C.ACTION_CARDS[c].dedicated_to is not None       # noqa: E731
    cca = Counter({k: v for k, v in ca.items() if not ded(k)})
    ccb = Counter({k: v for k, v in cb.items() if not ded(k)})
    common = _wjaccard(cca, ccb) if (cca and ccb) else None
    return raw, s_idf, common


# ------------------------------------------------------------------ 層 2

def trio(deck: dict) -> list:
    return sorted({C.CHARA_CARDS[c].name for c in deck["chara_deck"]})


def layer2(a: dict, b: dict):
    t = len(set(trio(a)) & set(trio(b)))
    sa, sb = set(a["chara_deck"]), set(b["chara_deck"])
    return t, (len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0)


# ------------------------------------------------------------------ 層 3

def card_profile(card) -> Counter:
    """1 枚の素性。`analyse_card_space.profile()` を呼び、コストだけ 4 帯に畳む（§5 の 2）。"""
    out = Counter()
    for k, v in _card_profile(card).items():
        if k.startswith("cost="):
            band = cost_band(int(k[5:]))
            k = "cost=" + ("0-1", "2", "3", "4+")[band]
        out[k] += v
    return out


def deck_profile(deck: dict) -> Counter:
    f = Counter()
    for cid in deck["action_deck"]:
        f.update(card_profile(C.ACTION_CARDS[cid]))
    for cid in deck["chara_deck"]:
        f.update(card_profile(C.CHARA_CARDS[cid]))
    return f


def family_of(feat: str) -> str:
    if feat.startswith("op=") and "/" in feat:
        return "op_param"
    head = feat.split("=", 1)[0]
    return head if head in FAMILIES else "misc"


def normalize(counter: Counter, weights: dict | None = None) -> dict:
    """族ごとに合計 1（に族の重み）へ正規化する。"""
    tot = Counter()
    for k, v in counter.items():
        tot[family_of(k)] += v
    w = weights or {}
    return {k: (v / tot[family_of(k)]) * float(w.get(family_of(k), 1.0))
            for k, v in sorted(counter.items()) if tot[family_of(k)] > 0}


def build_vocab(decks: dict) -> list:
    vocab = set()
    for d in decks.values():
        vocab |= set(deck_profile(d))
    return sorted(vocab)


def _vector(deck: dict, vocab: list, weights=None) -> list:
    nv = normalize(deck_profile(deck), weights)
    return [nv.get(k, 0.0) for k in vocab]


def build_mean(decks: dict, vocab: list, weights=None) -> list:
    """族ごと正規化ベクトルの平均（中心化の基準・候補集合で 1 回だけ計算して保存する）。"""
    vs = [_vector(decks[n], vocab, weights) for n in sorted(decks)]
    if not vs:
        return [0.0] * len(vocab)
    return [sum(v[i] for v in vs) / len(vs) for i in range(len(vocab))]


def layer3(a: dict, b: dict, vocab: list, mean: list | None = None, weights=None) -> float:
    """コサイン。`mean` を渡すと平均を引いてから（中心化・[-1, 1]）。同じ動きのデッキどうしは 1。"""
    u, v = _vector(a, vocab, weights), _vector(b, vocab, weights)
    if u == v:
        return 1.0
    if mean is not None:
        u = [x - m for x, m in zip(u, mean)]
        v = [x - m for x, m in zip(v, mean)]
    nu, nvv = math.sqrt(sum(x * x for x in u)), math.sqrt(sum(x * x for x in v))
    if nu == 0 or nvv == 0:
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(u, v)) / (nu * nvv)))


# ------------------------------------------------------------------ 対行列・グループ・並び・割り振り

def similarities(decks: dict, idf: dict, vocab: list, mean: list | None = None, weights=None) -> dict:
    names = sorted(decks)
    out = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            raw, s_idf, common = layer1(decks[a], decks[b], idf)
            t, sd = layer2(decks[a], decks[b])
            out[(a, b)] = {"s1_raw": raw, "s1_idf": s_idf, "s1_common": common,
                           "s2_trio": t, "s2_deck": sd,
                           "s3": layer3(decks[a], decks[b], vocab, mean, weights),
                           "s3_raw": layer3(decks[a], decks[b], vocab, None, weights)}
    return out


def _sim(sims, a, b):
    return sims[tuple(sorted((a, b)))]


def link_reasons(s: dict, th: dict) -> list:
    why = []
    if s["s1_idf"] is not None and s["s1_idf"] >= th["s1_idf"]:
        why.append("s1_idf")
    if s["s2_trio"] >= th["s2_trio"]:
        why.append("s2_trio")
    if s["s3"] >= th["s3"]:
        why.append("s3")
    return why


def linked(s: dict, th: dict) -> bool:
    return bool(link_reasons(s, th))


def groups(names, sims: dict, th: dict):
    """7.1 の関係の連結成分。戻り値は (グループの list（各グループは名前の辞書順・グループは先頭名の順）, つないだ組)。"""
    names = sorted(names)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            why = link_reasons(_sim(sims, a, b), th)
            if why:
                links.append({"a": a, "b": b, "why": why})
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    comp = {}
    for n in names:
        comp.setdefault(find(n), []).append(n)
    return sorted(comp.values(), key=lambda g: g[0]), links


def distance(s: dict) -> float:
    """並べる用途だけの距離（§7.2）。採否には使わない。"""
    return ((1 - (s["s1_idf"] if s["s1_idf"] is not None else s["s1_raw"]))
            + (1 - s["s2_trio"] / 3) + (1 - s["s3"])) / 3


def farthest_order(names, sims: dict) -> list:
    names = sorted(names)
    if len(names) <= 1:
        return names
    d = lambda a, b: distance(_sim(sims, a, b))       # noqa: E731
    # 同点は辞書順: 名前の順に回し、max は最初に見つけた最大を返すので辞書順で先のものが残る
    first = max(names, key=lambda a: round(sum(d(a, b) for b in names if b != a) / (len(names) - 1), 12))
    order, rest = [first], [n for n in names if n != first]
    while rest:
        nxt = max(rest, key=lambda a: round(min(d(a, s) for s in order), 12))
        order.append(nxt)
        rest.remove(nxt)
    return order


def assign(names, grouping, sims: dict, sizes=(12, 4, 4), thresholds=None) -> dict:
    """学習・調整・最終評価に割り振る（§7.3）。グループを割らない（変種枠だけが例外）。

    手順（決定的）:
    1. 変種枠: 2 デッキ以上のグループの中で、S1_idf が `variant_s1_idf` の範囲・同じ 3 人組の組を探し、
       並びの後ろ（既にある系統の変種）にある側を変種、もう一方の属するグループを学習に固定する
    2. 最終評価 3: 残りのグループのうち単独のものを、最遠点の並びの前から取る。学習に固定したグループと
       7.1 の関係に無いことを確かめる
    3. 調整 4: 残りから並びの前の系統を取る
    4. 学習: 残りを並びの順にデッキ数が `sizes[0]` に届くまで
    余ったデッキは None（使わない）。
    """
    th = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
    n_train, n_tune, n_final = sizes
    order = farthest_order(names, sims)
    rank = {n: i for i, n in enumerate(order)}
    gid = {n: i for i, g in enumerate(grouping) for n in g}
    split = {n: None for n in names}
    lo, hi = th["variant_s1_idf"]

    variant, variant_home = None, None
    for g in sorted(grouping, key=lambda g: min(rank[n] for n in g)):
        if len(g) < 2:
            continue
        cands = []
        for i, a in enumerate(g):
            for b in g[i + 1:]:
                s = _sim(sims, a, b)
                if s["s2_trio"] == 3 and s["s1_idf"] is not None and lo <= s["s1_idf"] <= hi:
                    v, home = (a, b) if rank[a] > rank[b] else (b, a)
                    cands.append((rank[v], v, home))
        if cands:
            _, variant, variant_home = max(cands)
            break

    used = set()
    if variant is not None:
        for n in grouping[gid[variant_home]]:
            split[n] = "train"
        split[variant] = "final_variant"
        used.add(gid[variant_home])

    def free_groups():
        return sorted((i for i in range(len(grouping)) if i not in used),
                      key=lambda i: min(rank[n] for n in grouping[i]))

    finals = 0
    for i in free_groups():
        if finals >= n_final - (1 if variant else 0):
            break
        g = grouping[i]
        if len(g) != 1:
            continue
        trains = [n for n, s in split.items() if s == "train"]
        if any(linked(_sim(sims, g[0], t), th) for t in trains):
            continue
        split[g[0]] = "final"
        used.add(i)
        finals += 1
    tunes = 0
    for i in free_groups():
        if tunes >= n_tune:
            break
        for n in grouping[i]:
            split[n] = "tune"
        tunes += len(grouping[i])
        used.add(i)
    for i in free_groups():
        if sum(1 for s in split.values() if s == "train") >= n_train:
            break
        for n in grouping[i]:
            split[n] = "train"
        used.add(i)
    return split


SPLITS = ("train", "tune", "final", "final_variant")


def check_override(ov: dict, names, grouping) -> dict:
    """手割り（§7.3-5）を検算して `split` の辞書を返す。おかしければ `SystemExit`。

    規則そのものは変えない。**規則が出した案を人が置き換えたことを記録に残す**ための口である。
    - `reason`（なぜ手で割ったか）が要る。これが出力と Markdown に残る
    - 名前は候補にあるものだけ・値は `SPLITS` のどれか（`None` = 使わない、も可）
    - §7.3 の「グループを割らない」は手割りでも守る。ただし `final_variant` は例外
      （変種枠は定義からして同じグループの 1 枚を切り出す枠なので）
    """
    if not isinstance(ov, dict) or not str(ov.get("reason") or "").strip():
        raise SystemExit("手割りには reason（なぜ手で割ったか）が要る")
    split = ov.get("split")
    if not isinstance(split, dict) or not split:
        raise SystemExit("手割りの split が無い")
    known = set(names)
    for n, v in sorted(split.items()):
        if n not in known:
            raise SystemExit(f"手割りに候補でない名前がある: {n}")
        if v is not None and v not in SPLITS:
            raise SystemExit(f"手割りの値が {SPLITS} のどれでもない: {n} = {v!r}")
    out = {n: split.get(n) for n in names}
    for g in grouping:
        kinds = {out[n] for n in g if out[n] != "final_variant"}
        if len(kinds) > 1:
            raise SystemExit(f"手割りが 1 つのグループを割っている（§7.3）: {'・'.join(g)} → "
                             + "・".join(f"{n}={out[n]}" for n in g))
    return out


def decks_block(split: dict, grouping) -> dict:
    """`record_mix.py` の組み合わせ表の `decks` ブロック。lineage はグループの代表（辞書順の先頭）。"""
    out = {}
    for i, g in enumerate(grouping):
        for n in g:
            out[n] = {"lineage": g[0], "group": i, "split": split.get(n)}
    return {k: out[k] for k in sorted(out)}


# ------------------------------------------------------------------ 出力

def _r(x):
    return None if x is None else round(float(x), 12)


def run(paths, anchors=False, thresholds=None, extra_anchors=(), split_override=None) -> dict:
    """`extra_anchors` は錨として扱う追加のデッキ（例: SD001 の 1 枚替え）。候補にも基準にも入れない。

    `split_override` は手割り（§7.3-5・D-128）。`{"reason": …, "split": {名前: 区分}}`。
    渡すと `assignment` を置き換え、規則が出した案は `assignment_auto` に残す。
    """
    th = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
    decks, rejected = load_decks(paths)
    anchor_names = []
    extra = []
    if anchors:
        extra += [os.path.join(DECKLIST_DIR, f"{n}.json") for n in ANCHORS]
    extra += list(extra_anchors)
    if extra:
        ad, arej = load_decks(extra)
        rejected.update({f"{k}（錨）": v for k, v in arej.items()})
        for n, d in ad.items():
            if n not in decks:
                decks[n] = d
                anchor_names.append(n)
    # D-127: idf と平均は候補だけで。錨だけのときは錨で（そう記録する）
    basis = sorted(n for n in decks if n not in anchor_names)
    basis_note = "候補だけで計算（錨は数に入れない・D-127）"
    if not basis:
        basis = sorted(decks)
        basis_note = "錨だけで回したので、錨を基準にした（候補を読んだら候補だけで計算し直す）"
    elif len(basis) < 3:
        basis_note += "。★基準が 3 デッキ未満で、平均を引いた S3 は当てにならない"
    bdecks = {n: decks[n] for n in basis}
    idf = compute_idf(bdecks)
    vocab = build_vocab(decks)
    mean = build_mean(bdecks, vocab, th.get("family_weights"))
    sims = similarities(decks, idf, vocab, mean, th.get("family_weights"))
    names = sorted(decks)
    grouping, links = groups(names, sims, th)
    order = farthest_order(names, sims)
    cand = [n for n in names if n not in anchor_names and n not in ANCHORS]   # 錨は割り振らない（§2）
    cand_groups = [[n for n in g if n in cand] for g in grouping]
    cand_groups = [g for g in cand_groups if g]
    split = assign(cand, cand_groups, sims, thresholds=th) if len(cand) >= 2 else {}
    auto, src, why = None, "規則（§7.3）", None
    if split_override is not None:
        auto, src = dict(split), "手割り（§7.3-5）"
        why = str(split_override["reason"]).strip() if str(split_override.get("reason") or "").strip() else None
        split = check_override(split_override, cand, cand_groups)
    info = {}
    for n in names:
        d = decks[n]
        ac = Counter(d["action_deck"])
        colors = Counter(C.ACTION_CARDS[c].color.value for c in d["action_deck"])
        info[n] = {"sha256": d["sha256"], "path": d["path"].replace("\\", "/"), "chara_trio": trio(d),
                   "anchor": n in anchor_names, "dedicated_ratio": _r(sum(v for k, v in ac.items()
                                                                     if C.ACTION_CARDS[k].dedicated_to) / 40),
                   "colors": dict(sorted(colors.items()))}
    mats = {f"{a}|{b}": {k: (_r(v) if isinstance(v, float) else v) for k, v in s.items()}
            for (a, b), s in sorted(sims.items())}
    return {"version": VERSION, "thresholds": th, "basis": basis, "basis_note": basis_note,
            "decks": info, "rejected": rejected,
            "idf": {k: _r(v) for k, v in idf.items()}, "vocab": vocab, "matrices": mats,
            "groups": grouping, "links": links, "order": order,
            "assignment": split, "assignment_source": src, "assignment_auto": auto,
            "split_override_reason": why,
            "decks_block": decks_block(split, cand_groups) if split else {}}


def to_markdown(res: dict) -> str:
    L = [f"# デッキ類似度（{res['version']}）", "",
         "閾値: " + ", ".join(f"{k}={v}" for k, v in res["thresholds"].items() if k != "family_weights" and not k.startswith("_")),
         "", f"idf と平均の基準: {res['basis_note']}（{'・'.join(res['basis'])}）", ""]
    if res["rejected"]:
        L += ["## 読まなかったデッキ", ""] + [f"- {k}: {v}" for k, v in sorted(res["rejected"].items())] + [""]
    L += ["## デッキ", ""]
    for n, d in res["decks"].items():
        L.append(f"- {n}{'（錨）' if d['anchor'] else ''}: {'・'.join(d['chara_trio'])}／専用札 "
                 f"{d['dedicated_ratio']:.2f}／色 {d['colors']}")
    L += ["", "## 組ごとの値（S1_raw・S1_idf・S1_common・S2_trio・S2_deck・S3〔平均を引いた値〕・S3_raw〔引かない値〕）", ""]
    fmt = lambda x: "—" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))     # noqa: E731
    for k, s in res["matrices"].items():
        L.append(f"- {k.replace('|', ' 対 ')}: " + "・".join(fmt(s[c]) for c in
                 ("s1_raw", "s1_idf", "s1_common", "s2_trio", "s2_deck", "s3", "s3_raw")))
    L += ["", "## グループ", ""]
    for i, g in enumerate(res["groups"]):
        L.append(f"- {i}: {'・'.join(g)}")
    for l in res["links"]:
        L.append(f"  - {l['a']} 〜 {l['b']}（{'・'.join(l['why'])}）")
    L += ["", "## 最遠点の並び（後ろほど既にある系統の変種）", "", "- " + " → ".join(res["order"]), ""]
    if res["assignment"]:
        head = f"## 割り振りの案（{res.get('assignment_source', '規則（§7.3）')}）"
        L += [head, ""]
        if res.get("split_override_reason"):
            L += [f"手で割った理由: {res['split_override_reason']}", ""]
        L += [f"- {n}: {s}" for n, s in sorted(res["assignment"].items())] + [""]
        if res.get("assignment_auto") is not None:
            L += ["## 規則が出した案（参考）", ""] + \
                 [f"- {n}: {s}" for n, s in sorted(res["assignment_auto"].items())] + [""]
    return "\n".join(L) + "\n"


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--anchors", action="store_true")
    ap.add_argument("--extra-anchor", action="append", default=[],
                    help="錨として扱う追加のデッキ（候補にも基準にも入れない）")
    ap.add_argument("--thresholds", default=None)
    ap.add_argument("--split-override", default=None,
                    help="手割りの JSON（{\"reason\": …, \"split\": {名前: train|tune|final|final_variant}}・§7.3-5）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", default=None)
    a = ap.parse_args(argv)
    th = None
    if a.thresholds:
        with open(a.thresholds, encoding="utf-8") as f:
            th = json.load(f)
    ov = None
    if a.split_override:
        with open(a.split_override, encoding="utf-8") as f:
            ov = json.load(f)
    res = run(a.paths, anchors=a.anchors, thresholds=th, extra_anchors=a.extra_anchor, split_override=ov)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
            f.write("\n")
    md = to_markdown(res)
    if a.md:
        with open(a.md, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
    if not a.out and not a.md:
        sys.stdout.write(md)
    return res


if __name__ == "__main__":
    main()
