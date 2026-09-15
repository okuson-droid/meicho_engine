# -*- coding: utf-8 -*-
"""便 K（BP01 のカードデータ投入）の不変の検査。**本体より先に書く**（作業規約 5）。

## 何を守るか

便 K は登録簿（`meicho/cards.py`）を 52 枚から 78 枚に増やす。これは
`meicho/encode.py` の `NA` / `NC` を通じて **観測と行動の次元を動かす**ので、
保存済みのネットを移行しないと読めなくなる。移行が正しいことは
「**SD001/SD02 の対局が 1 手も変わらない**」で示す。ここはその物差しである。

## 段ごとの状態（K-1 の時点）

- T-K-1 `test_registry_growth_keeps_sd_games_identical` — **通る**。K-0 で
  現状（52 枚）の digest を凍結した。K-1 以降も通り続けなければならない。
- T-K-2 `test_new_card_indices_are_appended` — **通る**。既存 52 枚の添字が動かないこと。
- T-K-3 `test_unverified_placeholders_are_in_no_decklist` — **通る**（K-1 で 3 枠が入り、実効になった）。
- T-K-4 `test_every_bp01_number_is_registered` — K-0 では xfail(strict) だったが、
  K-1 で 68 番号＋3 枠を一度に登録したので**通るようになった**（旗は外した）。
- T-K-10 `test_the_two_published_cards_have_their_effects` — **xfail(strict)**。
  2026-09-12 に掲載された `BP01-057` `BP01-062` の効果がまだ入っていない
  （要る語彙が便 K に無い）。実装したら「予想外に通った」で落ちるので、そこで旗を外す。

## 使う相手

**ネットも Rust も使わない**。`HeuristicAgent` と `RandomAgent` はどちらも
`(seed)` だけで決まるので、環境（torch の有無・wheel の版）に依存しない。
乱択の方が規則の枝を広く踏むので両方を見る。fingerprint（champion の 4 種）は
別物で、扱いは引継ぎ書 §0.3 (4) による。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
for _p in (_ROOT, os.path.join(_ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import arena                                                    # noqa: E402
from meicho.agents import RandomAgent                           # noqa: E402
from meicho.engine import apply, decision_players, initial_state, outcome  # noqa: E402
from meicho.heuristic import HeuristicAgent                     # noqa: E402

CARDS_DIR = os.path.normpath(os.path.join(_ROOT, "..", "cards"))
UNLISTED_PATH = os.path.join(CARDS_DIR, "BP01_UNLISTED.json")

# --- K-0 で凍結し、段階1Aで選択行動を明示した後の値 -----------------------
# 局数は既定 500（1 プール 1 相手あたり約 2 秒）。`MEICHO_BP01_DIGEST_N=2000` を
# 立てると引継ぎ書 §0.4 の「digest 4,000 局」（2 プール × 2,000 局）になる。
# D-087 で支払い選択が行動列に現れるようになったため digest は更新した。
# 既定AIの打ち方が従来どおりであることは fingerprint 3種で別に守る。
DIGEST_N_DEFAULT = 500
FROZEN_DIGESTS = {
    ("heuristic", "SD001", 500): "4616b6b94466c72f",
    ("heuristic", "SD001", 2000): "ce2d068ed9fcc971",
    ("heuristic", "SD02", 500): "e9ccf236005d104d",
    ("heuristic", "SD02", 2000): "485262a8e44727d8",
    ("random", "SD001", 500): "66cbdec0d59dcdf8",
    ("random", "SD001", 2000): "5940939168189f69",
    ("random", "SD02", 500): "9dada41b872f6efa",
    ("random", "SD02", 2000): "7259b3dcd44e6f26",
}

# 登録簿 52 枚の添字（`encode.ACTION_IDS` / `CHARA_IDS` の順＝Rust の `CardDb` の順）。
# 新カードは**末尾に追記**するので、この並びは先頭からそのまま残らなければならない
# （引継ぎ書 §0.3 (1)）。
FROZEN_ACTION_PREFIX = [
    "SD02-017", "SD02-019", "SD02-022", "SD02-023", "SD02-018", "SD02-020", "SD02-021",
    "SD02-012", "SD02-014", "SD02-015", "SD02-016", "SD02-013", "SD02-007", "SD02-009",
    "SD02-011", "SD02-008", "SD02-010", "SD01-017", "SD01-019", "SD01-022", "SD01-023",
    "SD01-018", "SD01-020", "SD01-021", "SD01-012", "SD01-014", "SD01-016", "SD01-013",
    "SD01-015", "SD01-007", "SD01-009", "SD01-010", "SD01-011", "SD01-008",
]
FROZEN_CHARA_PREFIX = [
    "BP01-021", "SD02-002", "SD02-001", "BP01-033", "SD02-004", "SD02-003", "BP01-030",
    "SD02-006", "SD02-005", "BP01-018", "SD01-002", "SD01-001", "BP01-024", "SD01-004",
    "SD01-003", "BP01-027", "SD01-006", "SD01-005",
]

# K-0 の時点で未登録の BP01 68 番号（`cards/BP01_MECHANICS.md` の台帳と同じ顔ぶれ）。
# 段が進むごとにここから減り、K-4 で空になる。
EXPECTED_UNREGISTERED_68 = [
    "BP01-001", "BP01-002", "BP01-003", "BP01-004", "BP01-005", "BP01-006", "BP01-007",
    "BP01-008", "BP01-009", "BP01-010", "BP01-011", "BP01-012", "BP01-013", "BP01-014",
    "BP01-015", "BP01-016", "BP01-017", "BP01-019", "BP01-020", "BP01-022", "BP01-023",
    "BP01-025", "BP01-026", "BP01-028", "BP01-029", "BP01-031", "BP01-032", "BP01-034",
    "BP01-035", "BP01-036", "BP01-037", "BP01-038", "BP01-039", "BP01-040", "BP01-041",
    "BP01-042", "BP01-043", "BP01-044", "BP01-045", "BP01-046", "BP01-047", "BP01-048",
    "BP01-050", "BP01-051", "BP01-052", "BP01-053", "BP01-054", "BP01-055", "BP01-056",
    "BP01-058", "BP01-059", "BP01-060", "BP01-061", "BP01-063", "BP01-064", "BP01-065",
    "BP01-066", "BP01-067", "BP01-068", "BP01-069", "BP01-070", "BP01-071", "BP01-072",
    "BP01-073", "BP01-074", "BP01-075", "BP01-076", "BP01-077",
]


def _digest_n() -> int:
    return int(os.environ.get("MEICHO_BP01_DIGEST_N", DIGEST_N_DEFAULT))


def _action_key(a: dict) -> tuple:
    """行動 dict を並び順に依らない形にする（dict の順序で digest が動かないように）。"""
    return tuple(sorted((str(k), str(v)) for k, v in a.items()))


def series_digest(deck: str, n: int, make_agent) -> str:
    """ミラー n 局の**全決定と最終局面**の sha256 先頭 16 桁。

    1 手でも変われば値が変わる。カードを足しても SD のデッキに入っていない限り
    ここは動かない、というのが便 K の完了条件（引継ぎ書 §0.4）である。
    """
    config = arena.mirror_config(arena.load_deck(deck))
    h = hashlib.sha256()
    for seed in range(n):
        agents = [make_agent(seed * 2), make_agent(seed * 2 + 1)]
        s = initial_state(config, seed)
        while outcome(s) is None and s.turn_no <= 200:
            need = decision_players(s)
            acts = {pi: agents[pi].act(s, pi) for pi in need}
            h.update(repr(sorted((pi, _action_key(a)) for pi, a in acts.items())).encode())
            s = apply(s, acts)
        h.update(f"|{outcome(s)}|{s.turn_no}|{s.players[0].life}|{s.players[1].life}|".encode())
    return h.hexdigest()[:16]


# --- T-K-1 ------------------------------------------------------------------

@pytest.mark.parametrize("who,make", [("heuristic", HeuristicAgent), ("random", RandomAgent)])
@pytest.mark.parametrize("deck", ["SD001", "SD02"])
def test_registry_growth_keeps_sd_games_identical(deck, who, make):
    """SD001/SD02 の段階1A後の全決定列を凍結する（T-K-1・D-087）。

    落ちたときの読み方:
    - **K-1 で落ちた** → 追記したカードが打ち方に漏れている。よくある原因は
      `legal_actions` が登録簿を全走査していて、デッキに無いカードまで拾っていること。
    - **K-2 以降で落ちた** → 新しい状態欄の既定値が効いてしまっている
      （例: `damage_taken_mod` の既定が 0 になっていない）。
    - **段階1A以降で落ちた** → 選択の既定回答か、選択を挟む位置が変わった。
    - **凍結値の側を直したくなったら**、直す前に「なぜ手が変わってよいのか」を
      decisions.md に書く。値の書き換えは記録なしにやらない。
    """
    n = _digest_n()
    key = (who, deck, n)
    if key not in FROZEN_DIGESTS:
        pytest.skip(f"局数 {n} の凍結値が無い（{sorted({k[2] for k in FROZEN_DIGESTS})} のどれかにする）")
    got = series_digest(deck, n, make)
    assert got == FROZEN_DIGESTS[key], (
        f"{deck} の {who} ミラー {n} 局で手が変わった: 凍結 {FROZEN_DIGESTS[key]} / 実測 {got}")


# --- T-K-2 ------------------------------------------------------------------

def test_new_card_indices_are_appended():
    """既存 52 枚の添字が不変であること（T-K-2・引継ぎ書 §0.3 (1)）。

    `ACTION_IDS` / `CHARA_IDS` の順は Rust の `CardDb` の順であり、
    保存済みネットの入力の並びそのものである。ここが動くと移行が
    「0 の列を末尾に足す」で済まなくなる。
    """
    from meicho.encode import ACTION_IDS, CHARA_IDS
    assert ACTION_IDS[:len(FROZEN_ACTION_PREFIX)] == FROZEN_ACTION_PREFIX, \
        "アクションの添字が動いた（新カードは末尾に追記すること）"
    assert CHARA_IDS[:len(FROZEN_CHARA_PREFIX)] == FROZEN_CHARA_PREFIX, \
        "キャラの添字が動いた（新カードは末尾に追記すること）"


def test_encoding_dims_follow_the_registry():
    """`OBS_DIM` / `ACT_DIM` が登録簿の枚数から導かれていること。

    数値そのものは固定しない（カードが増えるたびに落ちる検査にしない）。
    固定するのは**式**であり、これが成り立っているかぎり移行スクリプトの
    「0 の列を挿す位置」は機械的に決まる。
    """
    from meicho.encode import (ACT_DIM, ACTION_TAGS, ACTION_TYPES, NA, NC,
                               N_SCALAR, OBS_DIM)
    assert OBS_DIM == N_SCALAR + 14 * NA + 13 * NC + 2 * len(ACTION_TAGS)
    assert ACT_DIM == len(ACTION_TYPES) + NA + 3 * NC + 3 + 2 + 1 + NA


# --- T-K-3 ------------------------------------------------------------------

def _unlisted_codes() -> list:
    if not os.path.exists(UNLISTED_PATH):
        return []
    with open(UNLISTED_PATH, encoding="utf-8") as f:
        return list(json.load(f)["codes"])


def test_unlisted_list_is_empty_because_the_three_were_published():
    """公式未掲載だった 3 番号が、掲載されて正本に入ったこと。

    2026-09-10 の時点では `BP01-049` `BP01-057` `BP01-062` の 3 つが
    公式サイトのカード検索に無かった（D-078）。**2026-09-12 に掲載され、
    3 枚とも取得して `cards/cards_structured.json` に入れた**ので、
    未掲載の一覧は空になる。`resolved` 欄に 3 番号が残っているのは経緯の記録である。

    ここが空でなくなったら、公式に新しい欠番が出たということなので、
    `cards/OFFICIAL_FETCH_*.md` に経緯を書いてから足すこと。
    """
    with open(UNLISTED_PATH, encoding="utf-8") as f:
        d = json.load(f)
    assert d["codes"] == []
    assert d["resolved"] == ["BP01-049", "BP01-057", "BP01-062"]

    # 正本にも登録簿にも在ること（枠ではなく実カードになった）。
    import reconcile_cards
    from meicho.cards import ACTION_CARDS
    has_csv = os.path.exists(reconcile_cards.CSV_PATH)
    src = set(reconcile_cards.load_cards_csv()) if has_csv else set()
    for cid in d["resolved"]:
        assert cid in ACTION_CARDS, f"{cid} が登録簿に無い"
        if has_csv:
            assert cid in src, f"{cid} が正本 CSV に無い"


def test_the_two_published_cards_have_their_effects():
    """掲載された 3 枚のうち、効果文を持つ 2 枚に効果が入っていること（T-K-10）。

    `BP01-049`（花の余燼）はカード画像に効果テキストの枠そのものが無いバニラなので、
    ここでは見ない。残る 2 枚には次の語彙が要る:

    - `BP01-057`「このターン中、自分が次に使用する2枚の＜変奏スキル＞は
      『【連撃】カード1枚を引く。』を得る」— **これから使う N 枚への付与**。
      数えを持つ状態欄と opcode が要る。
    - `BP01-062`「【優勢】このカードのコスト-1」— **コストを下げる opcode が無い**。
    - `BP01-062`「自分のキャラデッキからレベル2の「アンコ」1枚を…上に置く」—
      `levelup_by_effect` はキャラデッキの最上段を使うので、レベルを指定して探す形が要る。

    K-0〜便 K のあいだは `xfail(strict=True)` で置いてあった。2026-09-13 に
    3 つの語彙（`grant_rush_draw_to_variation_skills` / `cost_mod` /
    `levelup_by_effect` の `level`）を足して実装したところ、設計どおり
    「予想外に通った」で落ちたので旗を外した（T-K-4 と同じやり方）。

    以後この検査が守るのは「2 枚に効果が入っていること」と
    「`skills` が unverified のまま放置されていないこと」である。
    **解釈の不確かさは各 `Skill` の `unverified=True`（u19〜u21）が担う**ので、
    そちらは `tests/test_bp01_k4.py` の検査が見ている。
    """
    from meicho.cards import ACTION_CARDS
    for cid in ("BP01-057", "BP01-062"):
        assert ACTION_CARDS[cid].skills, f"{cid} に効果が入っていない"
        assert "skills" not in ACTION_CARDS[cid].unverified_fields, \
            f"{cid} の skills が unverified のまま"


def test_unverified_placeholders_are_in_no_decklist():
    """unverified の枠がどのデッキリストにも入っていないこと（T-K-3）。

    枠は添字を確保するためだけのもので、性能は仮値 0 である。
    対局に混ざると測定がまるごと嘘になる。
    """
    codes = set(_unlisted_codes())
    root = os.path.join(_ROOT, "decklists")
    bad = {}
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(root, fn), encoding="utf-8") as f:
            d = json.load(f)
        used = set(d.get("chara_deck", [])) | set(d.get("action_deck", []))
        if used & codes:
            bad[fn] = sorted(used & codes)
    assert not bad, f"unverified の枠がデッキリストに入っている: {bad}"


def test_placeholders_are_registered_as_unverified_once_they_exist():
    """枠が登録されたら、必ず `unverified_fields` が立っていること。

    旗が無いと「確認済みのカード」と混ざる（作業規約 4・引継ぎ書 §0.3 (5)）。
    K-1 より前は登録が無いので空振りする。
    """
    from meicho.cards import ACTION_CARDS
    for code in _unlisted_codes():
        card = ACTION_CARDS.get(code)
        if card is None:
            continue
        assert card.unverified_fields, f"{code} が unverified の旗なしで登録されている"
        assert card.dedicated_to is None, f"{code} は専用キャラを持たない仮値であること"


# --- T-K-4 ------------------------------------------------------------------

def test_every_bp01_number_is_registered():
    """`cards/` にある番号がすべて `cards.py` に在ること（T-K-4）。

    K-0 では `xfail(strict=True)` で置いた。K-1 で 68 番号＋3 枠を一度に登録した時点で
    「予想外に通った」で落ちたので、設計どおり旗を外した（D-079 追記 2）。

    **通る段が K-4 から K-1 に前倒しになったのは D-079 判断 1（登録を 1 回にまとめる）の
    帰結である。** 以後この検査が守るのは「登録簿が痩せていないこと」で、
    効果（`skills`）が埋まっているかは見ない。そちらは段ごとの検査が担う。
    """
    sys.path.insert(0, os.path.join(_ROOT, "scripts"))
    import reconcile_cards
    from meicho.cards import ACTION_CARDS, CHARA_CARDS
    known = set(ACTION_CARDS) | set(CHARA_CARDS)
    missing = sorted(c for c in reconcile_cards.load_cards_csv() if c not in known)
    assert missing == [], f"未登録が残っている: {len(missing)} 件 {missing}"


def test_unregistered_set_is_a_subset_of_the_k0_ledger():
    """未登録の顔ぶれが K-0 の台帳の 68 番号から**増えない**こと。

    減るのは正しい（段が進んだ）。増えたら `cards/` に新しい番号が入ったのに
    実装が追いついていない、という取りこぼしである。
    """
    sys.path.insert(0, os.path.join(_ROOT, "scripts"))
    import reconcile_cards
    from meicho.cards import ACTION_CARDS, CHARA_CARDS
    known = set(ACTION_CARDS) | set(CHARA_CARDS)
    missing = sorted(c for c in reconcile_cards.load_cards_csv() if c not in known)
    extra = sorted(set(missing) - set(EXPECTED_UNREGISTERED_68))
    assert not extra, f"台帳に無い未登録カードが増えた: {extra}"


# --- T-K-5（K-1 で追加）ネット移行の列の対応 ---------------------------------

def test_new_encoding_columns_are_never_used_in_sd_games():
    """SD001/SD02 の対局では、BP01 で増えた枠が**一度も非零にならない**こと。

    これが `scripts/migrate_nets_k.py` の正しさの土台である。移行は「新しい列を 0 として
    挿す」だけなので、**その列に入る値がいつも 0 でなければ**出力の不変が言えない。
    列の対応（`OBS_MAP` / `ACT_MAP`）が 1 つでもずれていれば、SD のカードの値が
    「新カードの枠」に落ちるので、ここで捕まる。

    ネットは読まない（重みに触れないので torch も wheel も要らない）。
    """
    sys.path.insert(0, os.path.join(_ROOT, "scripts"))
    import migrate_nets_k as M
    import migrate_nets_stage1b as B
    from meicho import encode as E
    from meicho.engine import legal_actions, observe

    # migrate_nets_k はv3→v4の履歴道具。現行v5の直前の次元を終点として保つ。
    assert (M.NEW_OBS, M.NEW_ACT) == (1313, 226)

    obs_new_only = sorted(set(range(M.NEW_OBS)) - set(M.OBS_MAP))
    act_new_only = sorted(set(range(M.NEW_ACT)) - set(M.ACT_MAP))
    assert len(obs_new_only) == M.NEW_OBS - M.OLD_OBS
    assert len(act_new_only) == M.NEW_ACT - M.OLD_ACT

    n_obs = n_act = 0
    for deck in ("SD001", "SD02"):
        config = arena.mirror_config(arena.load_deck(deck))
        for seed in range(4):
            agents = [HeuristicAgent(seed * 2), HeuristicAgent(seed * 2 + 1)]
            s = initial_state(config, seed)
            while outcome(s) is None and s.turn_no <= 200:
                need = decision_players(s)
                acts = {}
                for pi in need:
                    ob = observe(s, pi)
                    current = E.encode(ob, pi)
                    v = [0] * B.OLD_OBS
                    for old, new in enumerate(B.OBS_MAP):
                        v[old] = current[new]
                    n_obs += 1
                    hit = [c for c in obs_new_only if v[c] != 0]
                    assert not hit, f"{deck} seed={seed}: 観測の新枠 {hit[:5]} が非零になった"
                    for a in legal_actions(s, pi):
                        current_a = E.expand_action(E.action_code(ob, a))
                        av = [0.0] * B.OLD_ACT
                        for old, new in enumerate(B.ACT_MAP):
                            av[old] = current_a[new]
                        n_act += 1
                        hit = [c for c in act_new_only if av[c] != 0.0]
                        assert not hit, f"{deck} seed={seed}: 行動の新枠 {hit[:5]} が非零になった"
                    acts[pi] = agents[pi].act(s, pi)
                s = apply(s, acts)
    assert n_obs > 500 and n_act > 2000, f"見た数が少なすぎる（obs={n_obs} act={n_act}）"


def test_migration_is_exact_in_float64_on_a_synthetic_net():
    """移行が実数の計算として厳密であること（合成ネットで確かめる）。

    本物のネット（`results/models/*.json`）が無い環境でも回るように、
    小さな乱数のネットを作って確かめる。**float64 で一致することが移行の正しさ**であり、
    float32 の差（この移行では 1e-5 台まで出る）は BLAS の足し算の順序が変わることによる
    再結合の丸めで、移行の誤りではない（`scripts/migrate_nets_k.py` の注記）。
    """
    np = pytest.importorskip("numpy")
    sys.path.insert(0, os.path.join(_ROOT, "scripts"))
    import migrate_nets_k as M

    rng = np.random.RandomState(7)
    hidden = 32

    def dense(o, i):
        return {"w": (rng.randn(o, i) * 0.05).tolist(), "b": (rng.randn(o) * 0.05).tolist()}

    old = {"obs_dim": M.OLD_OBS, "act_dim": M.OLD_ACT, "encoding_version": 3,
           "trunk": [dense(hidden, M.OLD_OBS), dense(hidden, hidden)],
           "policy": [dense(16, hidden + M.OLD_ACT), dense(1, 16)]}
    new = {**old,
           "trunk": [{"w": M._widen(old["trunk"][0]["w"], M.OBS_MAP, M.NEW_OBS, 0),
                      "b": old["trunk"][0]["b"]}, old["trunk"][1]],
           "policy": [{"w": M._widen(old["policy"][0]["w"], M.ACT_MAP, M.NEW_ACT, hidden),
                       "b": old["policy"][0]["b"]}, old["policy"][1]]}

    worst = 0.0
    for _ in range(50):
        xo = rng.randn(M.OLD_OBS) * 3
        xn = np.zeros(M.NEW_OBS); xn[M.OBS_MAP] = xo
        ao = (rng.rand(M.OLD_ACT) < 0.3).astype(float)
        an = np.zeros(M.NEW_ACT); an[M.ACT_MAP] = ao
        ho = M._forward_trunk(old, xo, np.float64)
        hn = M._forward_trunk(new, xn, np.float64)
        worst = max(worst, M._rel(ho, hn),
                    M._rel(M._forward_policy(old, ho, ao, np.float64),
                           M._forward_policy(new, hn, an, np.float64)))
    assert worst < M.EXACT_TOL, f"float64 で一致しない（rel={worst:.3g}）＝列の対応が誤っている"


# --- K-1 の片付け（0.3 (6)(7)）------------------------------------------------

def test_leader_color_is_derived_from_the_registry_not_hardcoded():
    """`heuristic.LEADER_COLOR` が登録簿から導かれ、SD の 6 キャラで従来と一致すること。

    D-047 の監査で「高」が付いていたキャラ名の直書きを K-1 で導出に替えた（D-079 追記 2）。
    ここが守るのは 2 つ。**(1) 既存 6 キャラの値が 1 つも変わっていないこと**
    （変わったら H の打ち方が変わる。fingerprint `6e39c2aa4b35d876` も同じことを別の側から守る）。
    **(2) 直書きに戻っていないこと**——BP01 のショアキーパーが自動で入ることで確かめる。
    """
    from meicho.cards import Color
    from meicho.heuristic import LEADER_COLOR

    before = {
        "漂泊者（男）": Color.GREEN, "漂泊者（女）": Color.GREEN,
        "散華": Color.BLUE, "秧秧": Color.BLUE,
        "今汐": Color.RED, "熾霞": Color.RED,
    }
    for name, col in before.items():
        assert LEADER_COLOR.get(name) is col, \
            f"{name} の担当色が変わった: {before[name]} → {LEADER_COLOR.get(name)}"

    # 導出になっている証拠。BP01-010 ショアキーパー Lv0 の【対抗】は緑。
    assert LEADER_COLOR.get("ショアキーパー") is Color.GREEN, \
        "導出ではなく直書きに戻っている（BP01 のキャラが入っていない）"

    # Lv.0 に【対抗】スキルを持たないキャラは**入らない**のが正しい。
    # 参照側は .get() で受けるので、入っていなくても落ちない。
    for name in ("ツバキ", "アンコ"):
        assert name not in LEADER_COLOR, \
            f"{name} は Lv.0 に【対抗】スキルが無いのに担当色が付いている"


def test_no_image_allowlist_is_consistent():
    """画像の許容リストが、登録済みで画像を持たない番号だけを指していること。

    マスター裁定 2026-09-10 により BP01 の画像は取得しない。そこで
    「画像が無い」を**承知の分**と**取りこぼし**に分けた（引継ぎ書 §0.3 (6)）。
    リストが実態とずれると、その区別が意味を失う。

    画像が 1 枚も無い環境（エンジンだけ切り出した場合・作業環境）では
    `stale_allowlist` は必ず空になるので、そこは素通りする。
    """
    from meicho.cards import ACTION_CARDS, CHARA_CARDS
    from webapp import images

    # **「空でないこと」を読めた証拠にしてはいけない。** 2026-09-13 に全番号へ画像が
    # 揃って許容リストが空になった（D-084 追記 1）ため、`assert allow` は
    # 「読めているのに落ちる」検査になっていた。`no_image_allowlist()` は
    # ファイルが無くても空集合を返すので、**読めたかどうかはファイルを直に見て確かめる**。
    assert os.path.exists(images.NO_IMAGE_PATH), \
        f"cards/BP01_NO_IMAGE.json が無い: {images.NO_IMAGE_PATH}"
    with open(images.NO_IMAGE_PATH, encoding="utf-8") as f:
        assert isinstance(json.load(f)["codes"], list)
    allow = images.no_image_allowlist()
    known = set(ACTION_CARDS) | set(CHARA_CARDS)
    unknown = sorted(c for c in allow if c not in known)
    assert not unknown, f"許容リストに未登録の番号がある: {unknown}"

    st = images.status()
    assert st["stale_allowlist"] == [], \
        f"画像が在るのに許容リストに残っている: {st['stale_allowlist']}（リストから消すこと）"
    assert set(st["no_image"]) <= allow
    assert not (set(st["missing"]) & allow)
