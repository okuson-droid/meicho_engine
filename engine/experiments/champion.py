"""champion（そのカードプールでいちばん強い AI）の定義。**ここが唯一の真実源**（D-058）。

## なぜ 1 か所に集めるか

champion はラダー（`gauntlets/*.json`）・発見ループ（`discovery.py`）・
対人検証アプリ（`webapp/agents.py`）・各種実験から参照される。定義が散らばっていると
「名前は同じで中身が違う」事故が起きる。**champion を変えるときはこのファイルだけを変える。**

## champion はプールごとに選ぶもの（D-047）

カードの総数は 35 種で、SD001 が使うのは 17 種、SD02 が使うのも 17 種、**共通は 0 種**である。
学習した方策 π は「見たことのあるカードの枠」にしか意味のある値を返さないので、
**SD001 で学習した π を SD02 に持ち込むと相手モデルとして悪化する**
（実測 0.449 ±0.028・D-058）。したがってプールごとに別の π を持つ。

## 現在の champion

| プール | 中身 | 根拠 |
|---|---|---|
| SD001 | 計画探索 ＋ **地平の延長**（`extra_turns=1`）＋ **葉 = 学習した価値 V_4'**（`drl_sd001_vc4.json`）＋ 相手モデル = π（`drl_sd001_s1.json`・根だけ）＋ **選択フェイズも探索**（a1）＋ **代打ち = 蒸留した小さい π**（`pi_small64_e10.json`・a5）＋ **スキャンで見えた札を決定化に必ず入れる**（`known_hand`）＋ **終盤は整合世界を全列挙して投票**（`endgame_enum=64`）＋ **決定化した山札の上位 3 枚をコスト帯 × 色の層で散らす**（`draw_buckets=1`）＋ **対抗は束ねたゲームを解いて平均戦略から選ぶ**（`bundle_p=0.75`） | **便 A 後半（2026-09-13 交代・`planner_vc4cps_kheb_b75`・D-082 追記 2）**。前 champion `planner_vc4cps` に**勝ち越した**（別帯 701200 で 0.542 [0.513, 0.570]・n=1,200／段 C-4 の帯 697200 と合算して 0.534 [0.514, 0.554]・n=2,400）。ラダー core5 v11 で **Nash の台に単独で乗り nA = 0.0000**（前 champion は台から落ちて nA = −0.2141）・Elo 1542 [1521, 1565] の 1 位（2 位 1522 [1500, 1546] と**区間は重なる**）。非推移性なし |
| SD001（一つ前） | 上から `bundle_p` を除いたもの＝`planner_vc4cps_kheb` | 便 C（2026-09-11 交代・D-081 追記 1）。ラダー core5 v11 で Nash の台に単独で乗った |
| SD001（二つ前） | さらに `known_hand` / `endgame_enum` / `draw_buckets` を除いたもの＝`planner_vc4cps` | 便 E-0（2026-09-08 交代・D-073）。ラダー core5 v9 で Elo 1522 [1500, 1546] の単独 1 位 |
| SD02 | 計画探索（据え置き） | SD02 用の π は D-058 で判定する。V の横展開は SD001 の成否を見てから（D-064 の裁定 3） |

`opp_policy_root_only=True` は「相手モデルを π にする範囲を、根の対抗の決定だけに絞る」意味である
（葉のロールアウトにも効かせると強さは +0.02 だが 15 倍遅い。D-057 の裁定でこちらを採った）。

`extra_turns=1` は葉の採点を「次に自分の手番が始まるところ」まで延ばす（D-046 対策 A）。
`value_net` はその葉の採点を学習した価値関数（勝率）に差し替える。**この 2 つは組で効く**——
葉の局面が記録した決定局面と同じ種類になることが、学習がうまくいく条件だった（D-064 §3.1）。
反復の中身と手順は `experiments/vb.py` と `VALUE_BOOTSTRAP_DESIGN.md` を見ること。

**なお `vb.py` は π₀ を自分で持っている**（D-064 §3.6 の「π₀ は据え置き」）。したがって
ここを変えても反復の輪の相手モデルは変わらない。**それが意図した分離である。**

## 便 C の交代で生じた「輪 2 の探索器とのずれ」（2026-09-11・D-081 追記 1）

便 C までは `champion.kwargs_for("SD001") == vb.kwargs_for("SD001", 5, loop=2)` が成り立っていた
（学習の輪 2 は champion と同じ探索器で回す、という設計）。便 C の交代で champion に
`known_hand` / `endgame_enum` / `draw_buckets` の 3 つが増えたが、**`vb.py` は変えていない**
（1 便で変える要素は 1 つ・便 C は探索の世界の作り方だけを触る便である）。したがって
**いまは輪 2 の探索器が「一つ前の champion」である**。

これは意図したずれであって不整合ではない。ただし**次に輪 2 を回すときは、揃えるかどうかを
先に決めること**——揃えずに回すと「champion とは違う探索器が作った記録で champion の葉を学ぶ」
ことになる。判断が要る点として `TASKS.md` に載せてある。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

# プール名 → PlannerAgent / planner spec に足す引数。空 dict は「素の計画探索」。
# モデルは**ファイル名だけ**を書く（絶対パスを書くと環境をまたいで再現できない・C-1 の教訓）。
CHAMPIONS: dict = {
    # 【一つ前の champion の記録・そのまま残す】
    # 便 E-0（2026-09-08 交代・`planner_vc4cps`・D-073）。前の champion `planner_vb3cps` から
    # **葉の価値関数 V だけ**を、学習の輪 2 の反復 4' の成果（`drl_sd001_vc4.json`）に替えたもの。
    # 探索器・π₀・代打ち・選択フェイズは**一切動かしていない**（1 便で変える要素は 1 つ）。
    #
    # **これは「勝ち越したから交代」である**（D-065 便 4 の「同じ強さで速いから交代」ではない）。
    # したがって D-034 の 5 条件をそのまま当てた:
    #   1 直接対決  0.569 ±0.028（下端 0.541・上端 0.597・n=1,200・**別帯** 660000..661199・
    #               引き分け 0）。対照（現 champion どうし）0.502 ±0.028 で 0.5 を含む＝配管は健全
    #   2 ラダー    core5 v9 で Elo **1522 [1500, 1546] の単独 1 位**。2 位 `planner_vb3cp`
    #               1474 [1452, 1499] と**区間が重ならない**。非推移性なし
    #   3 監査      覗き見監査 決定ノード 120 件・違反 0
    #   4 fingerprint  `9b5ad48d2de6a7e0`（§1 の手順: Rust・ミラー 10 局・seeds 471500..471509・
    #               workers=2・digest 列の sha256 先頭 16 桁）。旧 champion は `7251a931d252a57a`
    #   5 判断は人  マスターの包括方針（D-069）のもとで実施
    #
    # **モデルの中身の指紋**: `drl_sd001_vc4.json` = sha256 f050f22ee0a38993…（5,848,050 バイト）。
    # 測定の開始時に凍結してある（`results/vb/champion_challenge_vc4.json` の由来ブロック）。
    #
    #   choice_phases / solo_samples … 選択フェイズと手札上限の捨て札も探索の担当にする（a1）
    #   policy_net / policy_scope    … 先読みの**代打ち**を学習した π にする（a5・蒸留した小さい版）
    #
    # **注意**: V を替えても 2026-09-03 の対人 2 局の負け（詰みの烈火を持ちながらパス／青で受ける）
    # は直らない（便 E-0 §4.3 の診断: V_4' の既定は当時と同じ手を選ぶ）。あれは葉の採点ではなく
    # **対抗の相手モデル π₀ の決めつけ**の問題である（`lethal_uniform` はそこに効く別のつまみ）。
    #
    # 一つ前（`planner_vb3cps`・2026-09-06 交代・葉が `drl_sd001_vb3.json`）は
    # 旧 champion としてラダーとアプリに残してある。旧々 champion は `planner_vb3cp`。
    #
    # ------------------------------------------------------------------
    # 便 C（2026-09-11 交代・`planner_vc4cps_kheb`・D-081 追記 1）
    # ------------------------------------------------------------------
    # 上の `planner_vc4cps` に、便 C の階段で残った 3 つのつまみを積んだもの。
    # **葉の価値関数 V も π₀ も代打ちも変えていない**——変えたのは
    # 「決定化でどんな世界を作るか」だけである。
    #
    #   known_hand    … スキャンで見えた相手の札を決定化の手札に**必ず**入れる（段 C-1）
    #   endgame_enum  … 残り枚数が少ない終盤は、整合する世界を**全列挙**して投票（段 C-3）
    #   draw_buckets  … 決定化した山札の上位 3 枚を「コスト帯 × 色」の層で散らす（段 C-4）
    #
    # **これは「勝ち越したから交代」である。** D-081（＝元の D-034 裁定 4 に戻した門番）の
    # 5 条件を当てた:
    #   1 直接対決  **別帯 701200..702399 で 0.542 [0.513, 0.570]**（n=1,200・下端 > 0.5）。
    #               段 C-4 の帯 697200 の 0.526 と合算して **0.534 [0.514, 0.554]**（n=2,400）。
    #               対照（現 champion どうし・帯 702400）0.506 [0.478, 0.534] で 0.5 を含む
    #               ＝配管は健全。**ラダー内の n=300 の組は 0.553 [0.497, 0.609] で
    #               下端がわずかに 0.5 を割る**（門番はあくまで別帯の n=1,200 のほう）
    #   2 ラダー    core5 v11 で **Nash の台に単独で乗り nA = 0.0000**。
    #               前 champion は台から落ちた（nA = −0.2141）。Elo 1542 [1521, 1565] の 1 位
    #               （2 位 1522 [1500, 1546] と**区間は重なる**）。非推移性 0 組
    #   3 監査      覗き見監査 決定ノード 120 件・違反 0（帯 703600）
    #   4 fingerprint  新 champion `e82b796960e04c4a`。前 champion `9b5ad48d2de6a7e0` は不変
    #   5 判断は人  **マスター裁定（2026-09-11）**。この交代は「規則に照らして自動的に通った」
    #               のではなく「**マスターが D-034 改訂 1 を撤回したうえで通した**」ものである。
    #               経緯と、それが事後の閾値変更であることは D-081 に書いてある
    #
    # **`endgame_enum` は `opp_decklist` と組でしか使えない**（`greedy.py` が起動時に弾く）。
    # `registry.make` は先読み系に `opp_decklist` を既定で入れるので通常は意識しなくてよいが、
    # `PlannerAgent(**champion.kwargs_for("SD001"))` を**直に**呼ぶ道具は `opp_decklist=pool` を
    # 一緒に渡すこと。
    #
    # ------------------------------------------------------------------
    # 便 A 後半（2026-09-13 交代・`planner_vc4cps_kheb_b75`・D-082 追記 2）
    # ------------------------------------------------------------------
    # 上の `planner_vc4cps_kheb` に、**対抗の集約規則**を 1 つだけ積んだもの。
    # **世界の作り方も葉の V も π₀ も代打ちも変えていない。**
    #
    #   bundle_p=0.75 … AI の提出分布 x を決定化 K 本に**共通**に置いて
    #                   `max_x Σ_k w_k min_{y_k} xᵀA_k y_k` を解き、**平均戦略**の最大の手を出す。
    #                   従来は K 本の**それぞれ**で相手の最尤 1 手を当てていた（strategy fusion）。
    #                   `p` は「π₀ の最尤 1 手に対する値」と「相手の手 j に対する値」の混ぜ方で、
    #                   **p=1.0 は現行と一手一点まで同じ**、**p=0 は候補にしない**。
    #
    # **これは「勝ち越したから交代」である。** D-081 の 5 条件:
    #   1 直接対決  **別帯 712000..713199 で 0.530 [0.502, 0.558]**（n=1,200）。
    #               **下端が 0.5 を 0.002 上回っただけ**で、便 C の交代（0.542・下端 0.513）より
    #               ずっと薄い証拠である。対照（現 champion どうし・帯 713200）0.503 [0.475, 0.532]
    #               で 0.5 を含む＝配管は健全。**ラダー内の n=300 の組は 0.520 [0.463, 0.577] で
    #               下端が 0.5 を割る**（門番はあくまで別帯の n=1,200 のほう）
    #   2 ラダー    core5 v13 で **Nash の台に単独で乗り nA = 0.0000**。
    #               前 champion は台から落ちた（nA = −0.0800）。Elo 1555 [1532, 1578] の 1 位
    #               （2 位 1542 [1519, 1564] と**区間は重なる**）。非推移性 0 組
    #   3 監査      覗き見監査 決定ノード 120 件・違反 0（帯 714400）
    #   4 fingerprint  新 champion `e1662edb32b144a9`。前 champion `e82b796960e04c4a` は不変
    #   5 判断は人  **マスター裁定（2026-09-13）**。閾値は測る前に固定し、測ったあとに
    #               動かしていない（D-081 の撤回を前例にしない、を守った）
    #
    # **効いたのは被搾取の側だけである。** 透視カウンターで 0.145 ±0.028 → **0.180 ±0.031**
    # （+0.035・0.025 の線を越えた唯一の候補）。**錨 3 種では champion と区別がつかない。**
    # 混ぜること自体を目的にした改良なので、効くはずの物差しでだけ効いている。
    # **費用 +27.0%**（Rust・2 並列・ミラー 40 局）。
    #
    # **★ T-14（対人で負けた 4 局面）は 1 手も直っていない。** 葉の V・世界の作り方・
    # 対抗の集約規則の 3 便続けて、自己対戦では前進して対人の 2 敗は動かない。
    # **残る穴は相手モデル π₀ そのものである**（便 F の枠）。
    #
    # **SD001 専用である。** `known_hand` と `endgame_enum` は相手のデッキリストを前提にするので、
    # SD02 には持ち込まない（SD02 の champion は素の計画探索のまま）。
    "SD001": {"extra_turns": 1,
              "value_net": "drl_sd001_vc4.json",
              "opp_policy_net": "drl_sd001_s1.json",
              "opp_policy_root_only": True,
              "choice_phases": True,
              "solo_samples": 4,
              "policy_net": "pi_small64_e10.json",
              "policy_scope": "proxy",
              "known_hand": True,
              "endgame_enum": 64,
              "draw_buckets": 1,
              "bundle_p": 0.75},
    "SD02": {},
}


def kwargs_for(deck: str) -> dict:
    """そのプールの champion を作るための追加引数。未登録のプールは素の計画探索。"""
    return dict(CHAMPIONS.get(deck, {}))


def name_for(deck: str, gauntlet: str = "core5") -> str | None:
    """そのプールの現 champion の**登録名**（ラダーやアプリで使う名前）。

    便 M（D-076）で足した口である。**既存の関数は 1 つも変えていない。**

    なぜ要るか: ラダー解析（`experiments/ladder_analysis.py`）は「champion が Nash の台に
    乗っているか」を出す。ところが champion の名前を**ラダーの記録の欄**から取っていたため、
    交代前に回した記録を解析すると**旧 champion についての文**が出ていた（D-075 の食い違い 1）。
    D-034 の改訂で「台に乗り nA ≥ 0」を交代の条件にする以上、道具が**いまの** champion を
    見ていないのは危ない。そこで「中身（kwargs）から名前を引く」口をここに置く。

    引き方は**中身の一致**である（名前が中身を表すという `factory_for` の考え方と同じ）:
    ガントレット定義の `agents` のうち、`factory` と `kwargs` が `CHAMPIONS[deck]` と
    一致するものの名前を返す。一致が無ければガントレットの `champion` 欄に落とす
    （それも無ければ None）。モデルはファイル名だけで比べる（絶対パス禁止・C-1 の教訓）。
    """
    import json

    kw_want = kwargs_for(deck)
    fac_want = factory_for(deck)
    path = os.path.join(_HERE, "gauntlets", f"{gauntlet}.json")
    try:
        with open(path, encoding="utf-8") as f:
            g = json.load(f)
    except OSError:
        return None
    if g.get("deck") != deck:
        # そのプール用のガントレットではない。中身での一致は取れないので欄も使わない。
        return None

    def norm(kw: dict) -> dict:
        keys = ("value_net", "opp_policy_net", "policy_net")
        return {k: (os.path.basename(v) if k in keys and isinstance(v, str) else v)
                for k, v in kw.items() if k != "opp_decklist"}

    want = norm(kw_want)
    hits = [name for name, a in (g.get("agents") or {}).items()
            if a.get("factory") == fac_want and norm(a.get("kwargs") or {}) == want]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ValueError(f"{gauntlet}.json に同じ中身の体が {len(hits)} 体ある: {sorted(hits)}"
                         "（名前と中身の対応が壊れている）")
    return g.get("champion")


def factory_for(deck: str) -> str:
    """`registry.make` に渡す登録名。中身から決める（引数の有無の 2 択では足りなくなった）。

    どれも実体は `PlannerAgent` だが、**ラダーとアプリで名前が中身を表す**ようにしておく。
    名前と中身がずれると「同じ名前で別のもの」を測る事故になる（D-058 でこの分離を作った理由）。
    """
    kw = kwargs_for(deck)
    if kw.get("value_net"):
        return "planner_vb"
    if kw.get("opp_policy_net"):
        return "planner_pi"
    return "planner"


def spec(deck: str, pool: list, **extra) -> dict:
    """Rust 版（`arena_rs.series_rs`）に渡す spec。

    ネットのパスはここで解決してから渡す（Rust 側はファイル配置を知らない）。
    """
    kw = kwargs_for(deck)
    from meicho.drlnet import resolve_model
    # `policy_net`（代打ちを π にする・D-065 A-5'）もここで解決する。
    for key in ("opp_policy_net", "value_net", "policy_net"):
        if key in kw:
            kw[key] = resolve_model(kw[key])
    return {"kind": "planner", "opp_decklist": pool, **kw, **extra}


def make(deck: str, pool: list, seed: int):
    """Python 版のエージェントを 1 体作る（アプリ・ラダー用）。"""
    from meicho.planner import PlannerAgent
    return PlannerAgent(seed, opp_decklist=pool, **kwargs_for(deck))


def describe(deck: str) -> str:
    """記録・表示用の一行。"""
    kw = kwargs_for(deck)
    if not kw:
        return "計画探索（素）"
    parts = ["計画探索"]
    if kw.get("extra_turns"):
        parts.append(f"地平+{kw['extra_turns']}ターン")
    if kw.get("value_net"):
        parts.append(f"葉=V（{kw['value_net']}）")
    if kw.get("opp_policy_net"):
        parts.append(f"相手モデル=π（{kw['opp_policy_net']}・"
                     f"{'根だけ' if kw.get('opp_policy_root_only') else '葉の中も'}）")
    # D-065 便 1 のつまみ（便 2 で採ったものだけが champion に入る）
    if kw.get("policy_net"):
        scope = {"all": "代打ちと担当外", "proxy": "代打ちだけ",
                 "fallback": "担当外だけ"}.get(kw.get("policy_scope", "all"))
        parts.append(f"代打ち=π（{kw['policy_net']}・{scope}）")
    if kw.get("choice_phases"):
        parts.append(f"選択フェイズも探索（決定化 {kw.get('solo_samples', 1)} 本）")
    if kw.get("align_leaves"):
        parts.append("葉=次の自分のターン開始に整列")
    if kw.get("samples", 6) != 6:
        parts.append(f"対抗の決定化 {kw['samples']} 本")
    return parts[0] + "＋" + "／".join(parts[1:])
