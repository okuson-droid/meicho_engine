"""V の反復ブートストラップ（D-064）のエージェント定義。**ここが唯一の真実源**。

正本の設計書は `VALUE_BOOTSTRAP_DESIGN.md`（rules_draft.md v0.11 準拠 / engine v0.1）。
`experiments/champion.py` と同じ役割分担で、「反復 k のループのエージェントとは何か」を
1 か所に閉じ込める。記録（`drl_record.py --vb`）・評価（`eval_vb.py`）・登録簿
（`registry.py` の `planner_vb`）はすべてここを読む。

## 反復 k のエージェント（設計書 §5.2(a)）

    planner(extra_turns=1, value_net=V_{k-1}, opp_policy_net=π₀, opp_policy_root_only=True)

- `extra_turns=1` — 葉を「次に自分の手番が始まるところ」にする（裁定 1・§3.1）。
  これにより**葉の局面が、記録している決定局面と同じ種類になる**。
  段階 1 の葉=V が負けた 3 つの敗因のうち (ii) がこれで消える。
- `value_net=V_{k-1}` — 前の反復で学習した価値ネット。k=1 では**まだ無い**ので
  葉は手作りの `greedy.evaluate` のまま（§3.5: だから反復 1 では判定しない）。
- `opp_policy_net=π₀` — 相手モデルの π。**この輪では反復させない**（§3.6・D-059/060）。

## π₀ を「据え置き」にするために、ここに直接書いてある

`champion.py` を読んで動的に決めると、将来 champion が交代したときに
**この輪の相手モデルが黙って変わる**。設計書 §3.6 の「π₀ は据え置き」はそれを禁じている。
なので D-064 開始時点の値をここに固定して書く。`champion.py` は触らない（§10）。
両者が食い違ったと気づいたら、勝手に追随せず**判断が要る点として報告すること**。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from meicho.cards import CHARA_CARDS, Timing                       # noqa: E402

# 「持続効果」とみなすタイミング／条件。定義は `measure_persistent_feature.py` と同じもので、
# **カード名を一つも知らずに**判定する（プールが増えても書き足さなくてよい・D-047）。
PERSISTENT = (Timing.TURN_START, Timing.STATIC)
ALWAYS_KEYS = {"is_turn_player"}

# 相手モデルの π₀（プールごと・**据え置き**・上の注意書きを読むこと）。
OPP_POLICY_NET = {
    "SD001": "drl_sd001_s1.json",
}
# 葉を「次に自分の手番が始まるところ」まで延ばす量（裁定 1）。
EXTRA_TURNS = 1


# ------------------------------------------------------------------ 輪（loop）
# D-065 便 4（計画書 §5）: 輪を 2 周目から回し直す。**loop 1 の定義は 1 文字も変えない**（T-12）。
#
# 各項目の意味:
#   search       … その輪の探索器（全部の反復で共通）。`kwargs_for` の土台になる
#   record_extra … **記録のときだけ**足す引数。取り直し（`reeval_samples`）はここ。
#                  案 C（便 4 の下ごしらえ）で取り直しは対局を変えなくなったので、
#                  評価に付けても結果は同じで**時間だけ損**する。だから記録の口にだけ足す
#   init         … 学習の初期重み（`drl_train.py --init`）。エージェントの定義ではない
#   prefix       … その輪が出す価値ネットのファイル名の頭。`{deck}` はデッキ名（小文字）
#   first_k      … その輪の最初の反復番号。これより前の k は**前の輪の版**を指す（輪のつなぎ目）
#   proxy_pi     … 代打ちに使う π のファイル名（D-065 a5）。None なら代打ちは H（従来）。
#                  **反復をまたいで固定である。** 計画書 §5.1 は「反復 k の代打ちに V_{k-1} の
#                  π 頭を使う」と書いていたが、2026-09-06 の裁定で固定にした。理由は 2 つ。
#                  (1) champion に揃えるため（champion は蒸留した固定の π を使う。輪の目的は
#                      「champion の探索器のための V を育てる」ことなので、違っては筋が通らない）
#                  (2) 探索器を反復間で動かさないため（代打ちが反復ごとに変わると、門番で見た差が
#                      「V が良くなった差」か「探索器が変わった差」か区別できなくなる）
#
# **loop 2 の `search` について（計画書 §5.1 の訂正・便 2 の測定に合わせた）**
# 計画書には `samples: 12` と `align_leaves: True` が書いてあるが、これは計画書を書いた
# 時点の予想であって、**便 2 の測定でどちらも却下された**（葉の整列は 0.441〜0.511 で有害・
# 決定化 12 本は 0.489 で効かない）。§5.1 のコメント自身が「便 2 で採った組み合わせに
# 合わせる」と書いているので、**字面ではなくその意図に従う**。採ったのは a1（選択フェイズも
# 探索する・solo を 4 本）と a5（代打ちを π に・範囲は proxy）で、これは新 champion
# `planner_vb3cp` の構成と同じである。
LOOPS = {
    1: {
        "search": {"extra_turns": EXTRA_TURNS},
        "record_extra": {},
        "init": "drl_{deck}_s1.json",
        "prefix": "drl_{deck}_vb",
        "first_k": 1,
        "proxy_pi": None,
        "label": "",
    },
    2: {
        "search": {"extra_turns": EXTRA_TURNS, "choice_phases": True, "solo_samples": 4},
        "record_extra": {"reeval_samples": 4},
        "init": "drl_{deck}_vb3.json",
        "prefix": "drl_{deck}_vc",
        "first_k": 4,
        # champion（`experiments/champion.py`）の `policy_net` と**同じもの**を書く。
        # 食い違ったら `tests/test_value_bootstrap.py::test_loop2_proxy_pi_is_fixed_across_iterations`
        # が見つける。**片方だけ変えないこと。**
        "proxy_pi": "pi_small64_e10.json",
        "label": "輪2",
    },
}


def loop_cfg(loop: int) -> dict:
    """輪の設定。知らない番号は**黙って 1 として動かさず**、はっきり止める。"""
    if loop not in LOOPS:
        raise SystemExit(f"未知の loop: {loop}（登録済: {sorted(LOOPS)}）")
    return LOOPS[loop]


def model_name(deck: str, k: int, loop: int = 1) -> str:
    """反復 k で学習した価値ネットのファイル名（`results/models/` 配下・§4.3）。

    **絶対パスを書かない**（環境をまたいで再現できなくなる・C-1 の教訓）。

    輪のつなぎ目: その輪の最初の反復より前の k は**前の輪の版**を指す。
    たとえば loop 2 は反復 4' から始まるので、`model_name(deck, 3, loop=2)` は
    loop 1 の V_3（`drl_sd001_vb3.json`）を返す（計画書 §5.1・T-12）。
    """
    assert k >= 1, f"反復は 1 から数える（k={k}）"
    cfg = loop_cfg(loop)
    if loop != 1 and k < cfg["first_k"]:
        return model_name(deck, k, loop=1)
    return cfg["prefix"].format(deck=deck.lower()) + f"{k}.json"


def train_init(deck: str, loop: int = 1) -> str:
    """その輪の学習の初期重み（`drl_train.py --init` に渡すファイル名）。"""
    return loop_cfg(loop)["init"].format(deck=deck.lower())


def kwargs_for(deck: str, k: int, loop: int = 1, recording: bool = False) -> dict:
    """反復 k のループのエージェントを作るための追加引数。

    `k` は**これから記録・学習する反復の番号**である。使う価値ネットは
    1 つ前の反復の出力 V_{k-1} であり、loop 1 の k=1 では価値ネットを積まない（§5.2）。

    `recording=True` のときだけ、その輪の `record_extra`（取り直しなど）を足す。
    **既定（`loop` も `recording` も渡さない）は loop 1 の従来どおりである**（T-12）。
    """
    assert k >= 1, f"反復は 1 から数える（k={k}）"
    cfg = loop_cfg(loop)
    kw: dict = dict(cfg["search"])
    pi0 = OPP_POLICY_NET.get(deck)
    if pi0:
        kw["opp_policy_net"] = pi0
        kw["opp_policy_root_only"] = True
    # 葉に積む V。loop 1 の反復 1 だけは「まだ無い」ので積まない（§3.5）。
    if k - 1 >= 1 and not (loop == 1 and k == 1):
        prev = model_name(deck, k - 1, loop)
        kw["value_net"] = prev
    if cfg["proxy_pi"]:
        # 代打ちの π は**反復をまたいで固定**（上の注記）。葉の V とは別のファイルである。
        kw["policy_net"] = cfg["proxy_pi"]
        kw["policy_scope"] = "proxy"
    if recording:
        kw.update(cfg["record_extra"])
    return kw


def spec(deck: str, pool: list, k: int, loop: int = 1, recording: bool = False, **extra) -> dict:
    """Rust 版（`arena_rs.series_rs` / `series_record`）に渡す spec。

    ネットのパスはここで解決してから渡す（Rust 側はファイル配置を知らない）。
    `delta=[...]` を渡せば発見ループと同じ形の**挑戦者**になる（§6・`discovery.py` と同形）。
    """
    from meicho.drlnet import resolve_model
    kw = kwargs_for(deck, k, loop, recording)
    # `policy_net`（代打ちを π にする・D-065 a5）もここで解決する。**解決し忘れると
    # Rust が「そんなファイルは無い」と言って止まる**（`test_loop2_spec_resolves_both_nets`）。
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in kw:
            kw[key] = resolve_model(kw[key])
    return {"kind": "planner", "opp_decklist": pool, **kw, **extra}


def make(deck: str, pool: list, k: int, seed: int, loop: int = 1):
    """Python 版のエージェントを 1 体作る（カナリア・監査・診断用）。"""
    from meicho.planner import PlannerAgent
    return PlannerAgent(seed, opp_decklist=pool, **kwargs_for(deck, k, loop))


def describe(deck: str, k: int, loop: int = 1) -> str:
    """記録・表示用の一行。**どの輪の反復かが分かるようにする**（報告で取り違えないため）。"""
    kw = kwargs_for(deck, k, loop)
    cfg = loop_cfg(loop)
    leaf = f"葉=V（{kw['value_net']}）" if "value_net" in kw else "葉=手作り評価"
    pi0 = f"／相手モデル=π₀（{kw['opp_policy_net']}・根だけ）" if "opp_policy_net" in kw else ""
    extra = ""
    if kw.get("choice_phases"):
        extra += f"・選択フェイズも探索（solo {kw.get('solo_samples', 1)} 本）"
    if kw.get("policy_scope") == "proxy":
        extra += f"・代打ち=π（{kw['policy_net']}）"
    head = f"{cfg['label']} " if cfg["label"] else ""
    return f"{head}反復{k} の計画探索（地平+{EXTRA_TURNS}ターン・{leaf}{pi0}{extra}）"


# ---------------------------------------------------------------- δ 介入（§6.1）
def _persistent_levels(deck_name: str) -> dict:
    """そのデッキで**持続効果を持つ**キャラ名 → そのレベルの集合。

    数える条件は `measure_persistent_feature.persistent_count` と同じ 3 つ:
    (1)【ターン開始時】か【常在】 (2) 条件が無いか実質いつでも真 (3) 任意でない。
    カード名は一つも書いていないので、プールが増えてもここは書き換えない。
    """
    from arena import load_deck
    deck = load_deck(deck_name)
    out: dict = {}
    for cid in deck["chara_deck"]:
        cc = CHARA_CARDS[cid]
        if cc.level < 1:
            continue
        for sk in cc.skills:
            if sk.timing not in PERSISTENT or sk.optional:
                continue
            cond = sk.condition or {}
            if cond and not set(cond) <= ALWAYS_KEYS:
                continue
            out.setdefault(cc.name, set()).add(cc.level)
    return out


def delta_candidates(deck_name: str, gens: str = "A") -> list:
    """δ 介入に使う「強いる」型の一覧（設計書 §6.1）。

    語彙は発見ループ（`discovery.py`）のものをそのまま使う。そのうち
    **持続効果に関わるキャラ**の「強いる」型（`rush_chara` / `fix_leader`）に絞る。
    「禁じる」型（`forbid_levelup`）は含めない——ここでの目的は
    「今の方策が行かない場所へ**行かせる**」ことであり、行き先を減らすことではない。

    返る δ は必ず `discovery` の生成器が出す候補の部分集合であり、
    `tests/test_value_bootstrap.py::test_vb_record_specs` がそれを固定する。
    """
    import discovery
    allowed = set()
    for g in gens.split(","):
        g = g.strip()
        if not g:
            continue
        if g not in discovery.GENERATORS:
            raise SystemExit(f"未知の語彙: {g!r}（登録済: {sorted(discovery.GENERATORS)}）")
        from arena import load_deck
        for d in discovery.GENERATORS[g](load_deck(deck_name)):
            allowed.add(_key(d))
    levels = _persistent_levels(deck_name)
    out = []
    for name in sorted(levels):
        for L in sorted(levels[name]):
            for T in (1, 4, 7):
                out.append({"kind": "rush_chara", "name": name, "goal": L, "from_turn": T})
        out.append({"kind": "fix_leader", "name": name})
    picked = [d for d in out if _key(d) in allowed]
    if not picked:
        raise SystemExit(f"{deck_name} に持続効果を持つキャラが見つからない"
                         f"（語彙 {gens} の範囲では δ を組めない）。判断が要る点として報告すること")
    return picked


def _key(d: dict) -> tuple:
    """δ を集合に入れるための正規化（辞書の並び順に依らない）。"""
    return tuple(sorted((k, str(v)) for k, v in d.items()))
