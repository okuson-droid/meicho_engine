"""デッキ類似度（`engine/DECK_SIMILARITY_DESIGN.md` §11・D-126）の検査。**実装より先に書いた。**

道具 `experiments/deck_similarity.py` の口（§9）を、ここで具体的に決める:

- `load_decks(paths) -> (decks, rejected)`: `decks = {名前: デッキの dict}`、`rejected = {名前: 理由}`。
  フォルダを渡すと中の `*.json` を全部読む。デッキメーカーの余分な欄（`id`・`art` など）は読み飛ばす
- `compute_idf(decks) -> {カード番号: 重み}`: idf(x) = ln((N+1)/(df(x)+1)) + 1
- `layer1(a, b, idf=None) -> (raw, idf_sim, common)`: 重みつき Jaccard。`idf` を渡さなければ `idf_sim` は None。
  `common` は専用札を除いた Jaccard（どちらかに共通札が無ければ None）
- `layer2(a, b) -> (trio, deck)`: キャラ名の一致数（0〜3）と、キャラデッキの番号の集合の Jaccard
- `deck_profile(deck) -> Counter` / `normalize(counter) -> dict`（族ごとに合計 1）/
  `build_vocab(decks) -> list` / `build_mean(decks, vocab) -> list`（族ごと正規化ベクトルの平均）/
  `layer3(a, b, vocab, mean=None) -> float`（**中心化コサイン**: 平均を引いてからのコサイン・[-1, 1]。
  mean を渡さなければ引かない。まったく同じ動きのデッキどうしは 1）
- `similarities(decks, idf, vocab, mean=None) -> {(a, b): {...}}`（a < b の組だけ。`s3` と、平均を引かない `s3_raw`）
- **idf と平均は候補だけで計算する**（錨は数に入れない・D-127 の裁定）。錨だけで回すときは錨で計算し、そう記録する
- `groups(names, sims, thresholds) -> (グループの list, つないだ組の list)`
- `farthest_order(names, sims) -> list`
- `assign(names, grouping, sims, sizes=(12, 4, 4), thresholds) -> {名前: split}`
- `decks_block(assignment, grouping) -> {名前: {lineage, group, split}}`（`record_mix.py` の組み合わせ表の `decks`）
- `main(argv) -> dict`（`--out` で JSON、`--md` で要約）

対局は回さない。帯も使わない。
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter

import pytest

from experiments import deck_similarity as DS
from experiments.arena import load_deck
from meicho import cards as C

SD001 = load_deck("SD001")
SD02 = load_deck("SD02")
ANCHORS = ("SD001", "SD02", "K_smoke_ANKO", "K_smoke_SANGE", "K_smoke_TSUBAKI")
_DECKDIR = os.path.join(os.path.dirname(__file__), "..", "decklists")


def _deck(name, action, chara=None):
    return {"name": name, "chara_deck": list(chara or SD001["chara_deck"]), "action_deck": list(action)}


def _swap(deck_actions, old, new):
    """`old` を 1 枚だけ `new` に替える（多重集合の 1 枚替え）。"""
    out = list(deck_actions)
    out[out.index(old)] = new
    return out


def _anchors():
    decks, rejected = DS.load_decks([os.path.join(_DECKDIR, f"{n}.json") for n in ANCHORS])
    assert not rejected, rejected
    return decks


# ---------------------------------------------------------------- 1. 基本の性質

def test_self_similarity_is_one_and_pairs_are_symmetric_and_bounded():
    decks = _anchors()
    idf = DS.compute_idf(decks)
    vocab = DS.build_vocab(decks)
    mean = DS.build_mean(decks, vocab)
    names = sorted(decks)
    for a in names:
        raw, s_idf, common = DS.layer1(decks[a], decks[a], idf)
        assert raw == 1.0 and s_idf == pytest.approx(1.0)
        assert common in (None, 1.0)
        assert DS.layer2(decks[a], decks[a]) == (3, 1.0)
        assert DS.layer3(decks[a], decks[a], vocab) == pytest.approx(1.0)
        assert DS.layer3(decks[a], decks[a], vocab, mean) == pytest.approx(1.0)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            x = DS.layer1(decks[a], decks[b], idf)
            y = DS.layer1(decks[b], decks[a], idf)
            assert x == y
            assert DS.layer2(decks[a], decks[b]) == DS.layer2(decks[b], decks[a])
            s3 = DS.layer3(decks[a], decks[b], vocab)
            assert s3 == pytest.approx(DS.layer3(decks[b], decks[a], vocab))
            c3 = DS.layer3(decks[a], decks[b], vocab, mean)
            assert c3 == pytest.approx(DS.layer3(decks[b], decks[a], vocab, mean))
            for v in (x[0], x[1], s3):
                assert 0.0 <= v <= 1.0 + 1e-12
            assert -1.0 - 1e-12 <= c3 <= 1.0 + 1e-12


def test_sd001_and_sd02_share_no_card_numbers():
    """D-061: ID で数えると共通 0。"""
    raw, _, _ = DS.layer1(SD001, SD02)
    assert raw == 0.0


def test_one_and_two_card_swaps_have_exact_raw_similarity():
    """1 枚替え = 39/41・2 枚替え = 38/42（重みつき Jaccard の定義から厳密に決まる）。"""
    one = _deck("one", _swap(SD001["action_deck"], "SD01-017", "SD01-019"))
    two = _deck("two", _swap(one["action_deck"], "SD01-022", "SD01-023"))
    assert DS.layer1(SD001, one)[0] == pytest.approx(39 / 41, abs=0)
    assert DS.layer1(SD001, two)[0] == pytest.approx(38 / 42, abs=0)
    assert DS.layer2(SD001, one) == (3, 1.0)


# ---------------------------------------------------------------- 2. idf

def test_idf_is_smallest_for_everywhere_cards_and_largest_for_unique_cards():
    decks = {"A": _deck("A", SD001["action_deck"]), "B": _deck("B", SD001["action_deck"]),
             "C": _deck("C", _swap(SD001["action_deck"], "SD01-017", "SD01-019")),
             "D": _deck("D", SD02["action_deck"], SD02["chara_deck"])}
    idf = DS.compute_idf(decks)
    n = len(decks)
    # SD01-018 は A・B・C の 3 デッキ、SD02 の札は D の 1 デッキだけ
    assert idf["SD01-018"] == pytest.approx(math.log((n + 1) / (3 + 1)) + 1)
    assert idf["SD02-017"] == pytest.approx(math.log((n + 1) / (1 + 1)) + 1)
    assert min(idf.values()) > 0, "平滑化（+1）が外れると、全デッキにある札の重みが 0 になる"
    df = {c: sum(c in d["action_deck"] for d in decks.values()) for c in idf}
    most = [c for c in idf if df[c] == max(df.values())]          # いちばん多くのデッキにある札
    unique = [c for c in idf if df[c] == 1]                       # 1 デッキにしか無い札
    assert most and unique
    assert max(idf[c] for c in most) <= min(idf.values()) + 1e-12
    assert min(idf[c] for c in unique) >= max(idf.values()) - 1e-12


def test_idf_and_all_matrices_do_not_depend_on_candidate_order():
    decks = _anchors()
    rev = dict(reversed(list(decks.items())))
    idf1, idf2 = DS.compute_idf(decks), DS.compute_idf(rev)
    assert idf1 == idf2
    v1, v2 = DS.build_vocab(decks), DS.build_vocab(rev)
    assert v1 == v2
    m1, m2 = DS.build_mean(decks, v1), DS.build_mean(rev, v2)
    assert m1 == m2
    assert DS.similarities(decks, idf1, v1, m1) == DS.similarities(rev, idf2, v2, m2)


# ---------------------------------------------------------------- 3. 層 3（動き）

def test_layer3_is_blind_to_the_dedicated_character():
    """専用キャラだけが違う同じカード（SD01-017 ↔ SD02-017）に差し替えても S3 = 1。"""
    a = C.ACTION_CARDS["SD01-017"]
    b = C.ACTION_CARDS["SD02-017"]
    assert a.dedicated_to != b.dedicated_to
    swapped = [("SD02-017" if c == "SD01-017" else c) for c in SD001["action_deck"]]
    other = _deck("x", swapped)
    decks = {"SD001": SD001, "x": other}
    vocab = DS.build_vocab(decks)
    assert DS.layer3(SD001, other, vocab) == pytest.approx(1.0)
    assert DS.layer3(SD001, other, vocab, DS.build_mean(decks, vocab)) == pytest.approx(1.0)
    assert DS.layer1(SD001, other)[0] < 1.0         # 番号では違うデッキ


def test_breaking_layer3_with_card_names_is_caught(monkeypatch):
    """**わざと壊す**: 素性にカード番号を混ぜる版に差し替えると、上の検査が捕まえる。"""
    real = DS.card_profile

    def leaky(card):
        f = real(card)
        f[f"id={card.card_id}"] += 1
        return f

    monkeypatch.setattr(DS, "card_profile", leaky)
    swapped = [("SD02-017" if c == "SD01-017" else c) for c in SD001["action_deck"]]
    other = _deck("x", swapped)
    decks = {"SD001": SD001, "x": other}
    vocab = DS.build_vocab(decks)
    assert DS.layer3(SD001, other, vocab) < 1.0 - 1e-9
    assert DS.layer3(SD001, other, vocab, DS.build_mean(decks, vocab)) < 1.0 - 1e-9


def test_family_normalisation_ignores_how_many_features_a_family_has():
    """1 つの族の素性を全部 2 倍しても、正規化したベクトルは変わらない。"""
    prof = DS.deck_profile(SD001)
    doubled = Counter({k: (v * 2 if k.startswith("color=") else v) for k, v in prof.items()})
    assert DS.normalize(prof) == pytest.approx(DS.normalize(doubled))
    fam_sums = Counter()
    for k, v in DS.normalize(prof).items():
        fam_sums[DS.family_of(k)] += v
    assert all(s == pytest.approx(1.0) for s in fam_sums.values())


def test_cost_is_folded_into_the_four_bands():
    """コストの素性は `buckets.cost_band` の 4 帯に畳む（§5 の 2）。"""
    fams = {k for k in DS.deck_profile(SD02) if k.startswith("cost=")}
    assert fams <= {"cost=0-1", "cost=2", "cost=3", "cost=4+"}


# ---------------------------------------------------------------- 4. グループ

def _sims(pairs):
    """合成の類似度: {(a, b): (s1_idf, trio, s3)}（a < b）。"""
    out = {}
    for (a, b), (s1, trio, s3) in pairs.items():
        out[tuple(sorted((a, b)))] = {"s1_raw": s1, "s1_idf": s1, "s1_common": None,
                                     "s2_trio": trio, "s2_deck": 0.0, "s3": s3}
    return out


def test_groups_use_ge_thresholds_and_close_transitively_and_report_links():
    th = DS.DEFAULT_THRESHOLDS
    names = ["A", "B", "C", "D", "E"]
    sims = _sims({("A", "B"): (th["s1_idf"], 0, 0.0),          # ちょうど閾値 → 入る
                  ("B", "C"): (0.0, 3, 0.0),                   # 同じ 3 人組 → 入る
                  ("C", "D"): (0.0, 2, th["s3"] - 1e-9),       # わずかに下 → 入らない
                  ("D", "E"): (0.0, 0, th["s3"]),              # ちょうど → 入る
                  ("A", "C"): (0.1, 0, 0.1), ("A", "D"): (0.1, 0, 0.1), ("A", "E"): (0.1, 0, 0.1),
                  ("B", "D"): (0.1, 0, 0.1), ("B", "E"): (0.1, 0, 0.1), ("C", "E"): (0.1, 0, 0.1)})
    grouping, links = DS.groups(names, sims, th)
    assert grouping == [["A", "B", "C"], ["D", "E"]]
    reasons = {(l["a"], l["b"]): l["why"] for l in links}
    assert reasons[("A", "B")] == ["s1_idf"] and reasons[("B", "C")] == ["s2_trio"]
    assert reasons[("D", "E")] == ["s3"] and ("C", "D") not in reasons


# ---------------------------------------------------------------- 5. 最遠点の並び

def test_farthest_order_puts_a_duplicate_last_and_breaks_ties_by_name():
    names = ["A", "A2", "B", "C"]
    far = (0.0, 0, 0.0)
    sims = _sims({("A", "A2"): (1.0, 3, 1.0), ("A", "B"): far, ("A", "C"): far,
                  ("A2", "B"): far, ("A2", "C"): far, ("B", "C"): far})
    order = DS.farthest_order(names, sims)
    assert order[-1] == "A2"
    # 最初は他との平均距離が最大のもの（B と C が同点 → 辞書順で B）。次は B から最も遠いもの（A・C 同点 → A）
    assert order[:3] == ["B", "A", "C"]


# ---------------------------------------------------------------- 6. 割り振り

def _world():
    """合成の 22 系統（うち 1 つは 2 デッキの姉妹）。系統どうしは十分遠い。"""
    names = [f"d{i:02d}" for i in range(22)] + ["d00v"]
    pairs = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pairs[(a, b)] = (0.05, 0, 0.1)
    pairs[("d00", "d00v")] = (0.7, 3, 0.95)                       # d00 の変種
    return names, _sims(pairs)


def test_assign_keeps_groups_together_and_keeps_final_apart_from_training():
    names, sims = _world()
    th = DS.DEFAULT_THRESHOLDS
    grouping, _ = DS.groups(names, sims, th)
    split = DS.assign(names, grouping, sims, sizes=(12, 4, 4), thresholds=th)
    assert sum(v == "train" for v in split.values()) >= 12
    assert sum(v == "tune" for v in split.values()) == 4
    finals = [n for n, v in split.items() if v == "final"]
    variants = [n for n, v in split.items() if v == "final_variant"]
    assert len(finals) == 3 and len(variants) == 1
    # グループを割らない（変種枠だけが例外）
    for g in grouping:
        kinds = {split[n] for n in g if n in split and split[n] != "final_variant"}
        assert len(kinds) <= 1, g
    # 最終評価の 3 つは、学習・調整のどれとも 7.1 の関係に無い
    seen = [n for n, v in split.items() if v in ("train", "tune")]
    for f in finals:
        for s in seen:
            assert not DS.linked(sims[tuple(sorted((f, s)))], th)
    # 変種枠は、学習デッキのどれかの変種（S1_idf 0.5〜0.8・同じ 3 人組）
    v = variants[0]
    trains = [n for n, k in split.items() if k == "train"]
    assert any(0.5 <= sims[tuple(sorted((v, t)))]["s1_idf"] <= 0.8
               and sims[tuple(sorted((v, t)))]["s2_trio"] == 3 for t in trains)


def test_decks_block_is_accepted_by_record_mix():
    from experiments import record_mix
    names, sims = _world()
    grouping, _ = DS.groups(names, sims, DS.DEFAULT_THRESHOLDS)
    split = DS.assign(names, grouping, sims, sizes=(12, 4, 4), thresholds=DS.DEFAULT_THRESHOLDS)
    block = DS.decks_block(split, grouping)
    assert set(block) == set(split)
    for meta in block.values():
        assert set(meta) == {"lineage", "group", "split"}
        assert meta["split"] in ("train", "tune", "final", "final_variant", None)
    json.dumps(block, ensure_ascii=False)
    record_mix.check_schedule({"decks": block, "blocks": [
        {"deck_a": "SD001", "deck_b": "SD02", "seed0": 824000, "n": 1}]})


# ---------------------------------------------------------------- 7. 読み込みと決定性

def test_reads_deckmaker_exports_and_rejects_illegal_decks_with_a_reason(tmp_path):
    ok = dict(SD001, id="abc123", art={"x": 1}, description="deckmaker")
    ok["name"] = "maker_ok"
    bad = dict(SD001, name="maker_bad", action_deck=SD001["action_deck"][:39])
    four = dict(SD001, name="maker_four", action_deck=_swap(SD001["action_deck"], "SD01-017", "SD01-018"))
    for d in (ok, bad, four):
        (tmp_path / f"{d['name']}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    decks, rejected = DS.load_decks([str(tmp_path)])
    assert set(decks) == {"maker_ok"}
    assert set(rejected) == {"maker_bad", "maker_four"}
    assert "40" in rejected["maker_bad"] and "3" in rejected["maker_four"]


def test_output_is_byte_identical_across_runs(tmp_path):
    outs = []
    for k in range(2):
        path = tmp_path / f"o{k}.json"
        md = tmp_path / f"o{k}.md"
        DS.main([os.path.join(_DECKDIR, f"{n}.json") for n in ANCHORS] + ["--out", str(path), "--md", str(md)])
        outs.append((path.read_bytes(), md.read_bytes()))
    assert outs[0] == outs[1]
    data = json.loads(outs[0][0])
    for key in ("decks", "matrices", "idf", "vocab", "thresholds", "groups", "links", "order", "version"):
        assert key in data, key
    assert data["decks"]["SD001"]["chara_trio"] == sorted({C.CHARA_CARDS[c].name for c in SD001["chara_deck"]})


# ---------------------------------------------------------------- 8. 裁定（D-127）: 中心化と、候補だけで計算

def test_centering_widens_the_gap_between_sisters_and_other_lineages():
    """錨で実測した「S3 の幅が狭い」問題（設計書 §6.1）が、平均を引くと解消する。

    姉妹（1 枚替え）と別系統（SD001 対 SD02）の差が、平均を引かないと 0.03 しかない。平均を引くと 0.3 以上開く。
    """
    one = _deck("one", _swap(SD001["action_deck"], "SD01-017", "SD01-019"))
    decks = dict(_anchors(), one=one)
    vocab = DS.build_vocab(decks)
    mean = DS.build_mean(decks, vocab)
    raw_gap = DS.layer3(SD001, one, vocab) - DS.layer3(SD001, SD02, vocab)
    cen_gap = DS.layer3(SD001, one, vocab, mean) - DS.layer3(SD001, SD02, vocab, mean)
    assert raw_gap < 0.05
    assert cen_gap > 0.3


def test_anchors_do_not_change_candidate_pairs(tmp_path):
    """**idf と平均は候補だけで計算する**: `--anchors` を付けても、候補どうしの値は 1 ビットも変わらない。"""
    one = dict(_deck("cand_one", _swap(SD001["action_deck"], "SD01-017", "SD01-019")))
    two = dict(SD02, name="cand_sd02")
    three = dict(load_deck("K_smoke_ANKO"), name="cand_anko")
    for d in (one, two, three):
        (tmp_path / f"{d['name']}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    a = DS.run([str(tmp_path)], anchors=False)
    b = DS.run([str(tmp_path)], anchors=True)
    assert a["basis"] == b["basis"] == ["cand_anko", "cand_one", "cand_sd02"]
    for k, v in a["matrices"].items():
        assert b["matrices"][k] == v, k
    assert set(b["idf"]) == set(a["idf"]) and b["idf"] == a["idf"]


def test_anchor_only_run_uses_the_anchors_as_the_basis():
    res = DS.run([], anchors=True)
    assert res["basis"] == sorted(ANCHORS)
    assert res["basis_note"].startswith("錨だけ")


# ---------------------------------------------------------------- 9. 手割り（D-128・§7.3-5）

def _three(tmp_path):
    """候補 3 つを書いて、その場所を返す。"""
    one = dict(_deck("cand_one", _swap(SD001["action_deck"], "SD01-017", "SD01-019")))
    two = dict(SD02, name="cand_sd02")
    three = dict(load_deck("K_smoke_ANKO"), name="cand_anko")
    for d in (one, two, three):
        (tmp_path / f"{d['name']}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return str(tmp_path)


def test_split_override_replaces_the_assignment_and_keeps_the_automatic_one(tmp_path):
    """手割りを渡すと `assignment` が置き換わり、規則が出した案は `assignment_auto` に残る。"""
    path = _three(tmp_path)
    ov = {"reason": "検査用", "split": {"cand_one": "train", "cand_sd02": "tune", "cand_anko": "final"}}
    res = DS.run([path], split_override=ov)
    assert res["assignment"] == ov["split"]
    assert res["assignment_source"] == "手割り（§7.3-5）"
    assert res["split_override_reason"] == "検査用"
    assert res["assignment_auto"] == DS.run([path])["assignment"]
    assert {v["split"] for v in res["decks_block"].values()} == {"train", "tune", "final"}


def test_split_override_rejects_unknown_names_and_values(tmp_path):
    path = _three(tmp_path)
    with pytest.raises(SystemExit):
        DS.run([path], split_override={"reason": "x", "split": {"no_such_deck": "train"}})
    with pytest.raises(SystemExit):
        DS.run([path], split_override={"reason": "x", "split": {"cand_one": "TRAIN"}})
    with pytest.raises(SystemExit):
        DS.run([path], split_override={"split": {"cand_one": "train"}})       # 理由が要る


def test_split_override_must_not_cut_a_group_in_half(tmp_path):
    """§7.3 の「グループを割らない」は手割りでも守る（`final_variant` だけが例外）。"""
    one = dict(_deck("cand_one", list(SD001["action_deck"])))
    two = dict(_deck("cand_two", list(SD001["action_deck"])))          # 同じ中身＝必ず同じグループ
    three = dict(load_deck("K_smoke_ANKO"), name="cand_anko")
    for d in (one, two, three):
        (tmp_path / f"{d['name']}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    base = {"reason": "検査用", "split": {"cand_one": "train", "cand_two": "final", "cand_anko": "tune"}}
    with pytest.raises(SystemExit):
        DS.run([str(tmp_path)], split_override=base)
    ok = {"reason": "検査用", "split": {"cand_one": "train", "cand_two": "final_variant", "cand_anko": "tune"}}
    assert DS.run([str(tmp_path)], split_override=ok)["assignment"] == ok["split"]


def test_split_override_appears_in_the_markdown(tmp_path):
    path = _three(tmp_path)
    ov = {"reason": "最終評価の枠が自動で決まらないため", "split": {"cand_one": "train", "cand_sd02": "tune", "cand_anko": "final"}}
    md = DS.to_markdown(DS.run([path], split_override=ov))
    assert "手割り" in md and ov["reason"] in md
    assert "## 規則が出した案（参考）" in md
