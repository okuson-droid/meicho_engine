"""自動発見ループ（`DISCOVERY_LOOP_DESIGN.md`・D-050）。

rules_draft.md v0.10 準拠 / engine v0.1 / Rust 版エンジン（D-049）で回す。

## 何をするか

champion（計画探索）の打ち方を機械的に少しだけ変えた挑戦者 δ を語彙から大量に作り、
champion と戦わせ、勝ち越したものを champion に取り込む。人手の方針を一切入れない。

    候補生成（生成器 A / B / C）
      → 0. 挙動確認（対 champion・30 局・同一シード。手の記録が全局一致＝一手も変えないなら測らない）
      → 1. 探索（対 champion・n=300・勝率 ≥ 0.52 で通す）
      → 2. 確認（別のシード帯・n=1200・95% 下端 > 0.5 で発見）
      → 3. 再確認（下端が 0.50〜0.52 の境界だったときだけ・さらに別の帯・合算で判定）
      → 取り込み（効果量最大の 1 つを champion に重ね、残りを新 champion に対して測り直す）

D-050 の裁定: 確認は n=1200、逐次打ち切りは入れない、事前選別は入れる。
D-053 の裁定: 段階 0 は「発火回数（合法手が減った決定の数）」ではなく
**「手の記録のハッシュが champion と全局一致するか」**で判定する。発火回数は上限であって
挙動が変わった証拠ではなく、選別として機能していなかった（D-052 裁定 3）。
「分岐点までの再生」（削減 2）は入れていない（§限界）。

## 台帳

`results/discoveries/<deck>.jsonl` に 1 候補 1 行。シード帯・n・勝率・区間・発火回数・判定・
そのときの champion の δ 列をすべて持つ。**シードの無い発見は発見でない**。

## 使い方

    python3 experiments/discovery.py --deck SD001 --workers 4            # 語彙 A+C（第 1 巡の既定）
    python3 experiments/discovery.py --deck SD001 --gens A,B,C --workers 4
    python3 experiments/discovery.py --deck SD02 --workers 4 --max-folds 3
    python3 experiments/discovery.py --deck SD001 --list                 # 候補を数えるだけ

## 限界

- 発見は「対 champion」で測った値である。対マスターで効く保証は無い（設計案 §7）。
- 「分岐点までの再生」は未実装。挑戦者の探索が消費する乱数の列が再生では再現できず、
  同一シードの直接対局と結果が一致しなくなるため。Rust 化で費用の問題が小さくなったので見送った。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from arena import Result, load_deck, mirror_config                    # noqa: E402
from arena_rs import PLANNER, series_rs_detail, series_rs_digest      # noqa: E402
import champion as champ                                             # noqa: E402
from meicho.cards import ACTION_CARDS, CHARA_CARDS                    # noqa: E402

# デッキごとの帯の**列**（D-053 裁定 3）。1 帯 10,000 シードに入るのは 2 巡分である:
# 挙動確認 +0..+999／探索 +1000..+2999（1 巡 300）／確認 +3000..+5999（1 巡 1200）／
# 再確認 +6000..+9999（1 巡 1200）。確認の領域に 1200 シードは 2 つしか入らない。
# 第 3 巡以降は列の次の帯に移る。**列の並びを変えないこと**（過去の巡のシードが変わる）。
BANDS = {"SD001": [180000, 210000], "SD02": [190000, 220000]}
ROUNDS_PER_BAND = 2
BEHAV_N = 30           # 挙動が変わったかの確認（対 champion・同一シード・digest 比較）
SCREEN_N = 300
SCREEN_PASS = 0.52
CONFIRM_N = 1200
BORDER = 0.52          # 確認の下端がこの値以下（かつ > 0.5）なら再確認
LEDGER_DIR = os.path.join(_HERE, "..", "results", "discoveries")


# ---------------------------------------------------------------------------
# 生成器（語彙）。カード名・キャラ名はデッキのデータから読む。コードには書かない。
# ---------------------------------------------------------------------------

def gen_A(deck: dict) -> list:
    """A: キャラの育て方。急ぐ（L∈{1,2}×T∈{1,4,7}）／禁じる（L）／リーダー固定。"""
    names = sorted({CHARA_CARDS[c].name for c in deck["chara_deck"]})
    levels = {}
    for c in deck["chara_deck"]:
        cc = CHARA_CARDS[c]
        if cc.level >= 1:
            levels.setdefault(cc.name, set()).add(cc.level)
    out = []
    for n in names:
        for L in sorted(levels.get(n, ())):
            for T in (1, 4, 7):
                out.append({"kind": "rush_chara", "name": n, "goal": L, "from_turn": T})
            out.append({"kind": "forbid_levelup", "name": n, "level": L})
        out.append({"kind": "fix_leader", "name": n})
    return out


def gen_B(deck: dict, full: bool = False) -> list:
    """B: アクションカードの使い方。同名は 1 つに畳む。full=False は第 1 巡の一部（対抗で優先／禁じる）。"""
    names = []
    for cid in deck["action_deck"]:
        nm = ACTION_CARDS[cid].name
        if nm not in names:
            names.append(nm)
    out = []
    for nm in sorted(names):
        out.append({"kind": "prefer_in_clash", "card": nm})
        out.append({"kind": "forbid_in_clash", "card": nm})
        if full:
            out.append({"kind": "forbid_in_rush", "card": nm})
            out.append({"kind": "reserve", "card": nm})
    return out


def gen_C(deck: dict) -> list:
    """C: 状況つきの行動規則（diag_behaviour の型を強制／禁止にしたもの）。"""
    return [
        {"kind": "always_free_rush"},
        {"kind": "never_free_rush"},
        {"kind": "charge_if_concerto_empty"},
        {"kind": "levelup_if_hand", "min_hand": 4},
        {"kind": "levelup_if_hand", "min_hand": 6},
        {"kind": "no_pass_if_behind", "margin": 3},
        {"kind": "no_pass_if_behind", "margin": 6},
        {"kind": "no_switch_until", "until_turn": 3},
    ]


GENERATORS = {"A": gen_A, "B": gen_B, "C": gen_C}


def label(delta: dict) -> str:
    """人が読める一文。"""
    k = delta["kind"]
    if k == "rush_chara":
        return f"{delta['name']} を {delta['from_turn']} ターン目から急いで Lv{delta['goal']} に"
    if k == "forbid_levelup":
        return f"{delta['name']} を Lv{delta['level']} にしない"
    if k == "fix_leader":
        return f"リーダーを {delta['name']} に固定"
    if k == "prefer_in_clash":
        return f"『{delta['card']}』を対抗で持っていれば必ず出す"
    if k == "forbid_in_clash":
        return f"『{delta['card']}』を対抗で出さない"
    if k == "forbid_in_rush":
        return f"『{delta['card']}』を連撃で使わない"
    if k == "reserve":
        return f"『{delta['card']}』は連撃まで温存"
    if k == "always_free_rush":
        return "コスト0でダメージのある連撃は必ず打つ"
    if k == "never_free_rush":
        return "コスト0でダメージのある連撃を必ずやめる"
    if k == "charge_if_concerto_empty":
        return "協奏が空なら必ずチャージ"
    if k == "levelup_if_hand":
        return f"手札 {delta['min_hand']} 枚以上ならレベルアップを必ずする"
    if k == "no_pass_if_behind":
        return f"ライフが {delta['margin']} 以上負けていたら対抗でパスしない"
    if k == "no_switch_until":
        return f"{delta['until_turn']} ターン目までは切り替えない"
    return json.dumps(delta, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 測定
# ---------------------------------------------------------------------------

def _summ(out: list) -> dict:
    dec = [r[0] for r in out if r[0] is not None]
    wins = sum(1 for w in dec if w)
    r = Result(wins, len(dec), len(out))
    return {"n": len(out), "decided": len(dec), "wins": wins, "p": r.p, "ci": r.ci,
            "lb": r.p - r.ci, "fired_games": sum(1 for x in out if x[3] > 0),
            "fired_total": int(sum(x[3] for x in out))}


class Loop:
    def __init__(self, deck_name: str, workers: int, screen_n: int = SCREEN_N,
                 confirm_n: int = CONFIRM_N, behav_n: int = BEHAV_N, quiet: bool = False):
        self.deck_name = deck_name
        self.deck = load_deck(deck_name)
        self.cfg = mirror_config(self.deck)
        self.pool = self.deck["action_deck"]
        self.workers = workers
        self.screen_n, self.confirm_n, self.behav_n = screen_n, confirm_n, behav_n
        self.bases = BANDS[deck_name]
        self.champion_deltas: list = []
        self.round = 0
        self.quiet = quiet
        self._baseline: dict = {}          # champion 自身の digest 列（巡ごとに 1 回だけ測る）
        os.makedirs(LEDGER_DIR, exist_ok=True)
        self.ledger_path = os.path.join(LEDGER_DIR, f"{deck_name}.jsonl")

    @property
    def max_rounds(self) -> int:
        return len(self.bases) * ROUNDS_PER_BAND

    # -- シード帯（巡ごとにずらす。2 巡で 1 帯・D-053 裁定 3）
    def band(self, stage: str, rnd: int) -> int:
        assert 1 <= rnd <= self.max_rounds, \
            f"帯の列が足りない（{self.deck_name} は第 {self.max_rounds} 巡まで）。seed_bands.json に帯を足し BANDS の列に append すること"
        base = self.bases[(rnd - 1) // ROUNDS_PER_BAND]
        k = (rnd - 1) % ROUNDS_PER_BAND                # 帯の中で何巡目か（0 始まり）
        if stage == "behaviour":
            # 巡ごとに別の 100 シードを使う。champion が変われば基準の digest も変わるので、
            # 帯を分けておかないと巡をまたいで基準を使い回してしまう。
            return base + k * 100
        if stage == "screen":
            return base + 1000 + k * self.screen_n
        if stage == "confirm":
            return base + 3000 + k * self.confirm_n
        if stage == "reconfirm":
            return base + 6000 + k * self.confirm_n
        raise ValueError(stage)

    def _base(self, **extra) -> dict:
        """champion の土台（プールごと・`experiments/champion.py` が真実源・D-058）。

        **土台が変わると基準の digest も勝率も変わる**ので、巡をまたいで比較するときは
        台帳の `champion_base` が同じであることを確かめること。
        """
        return champ.spec(self.deck_name, self.pool, **extra)

    def champion(self) -> dict:
        return self._base(delta=list(self.champion_deltas)) if self.champion_deltas else self._base()

    def challenger(self, delta: dict) -> dict:
        return self._base(delta=list(self.champion_deltas) + [delta])

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg, flush=True)

    def _record(self, rec: dict) -> None:
        rec["deck"] = self.deck_name
        rec["round"] = self.round
        # 帯の割り当て方式の版。d050 は「1 プール 1 帯・3 巡」（第 3 巡が再確認領域に食い込む欠陥あり）、
        # d053 は「2 巡で 1 帯・帯の列」。同じ巡番号でも版が違えばシードが違う（D-053 裁定 3）。
        rec["bands_scheme"] = "d053"
        rec["champion_deltas"] = list(self.champion_deltas)
        rec["champion_base"] = champ.describe(self.deck_name)
        rec["time"] = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # -- 段階
    def baseline_digests(self, rnd: int) -> list:
        """champion 自身を挑戦者の席に置いたときの digest 列。巡ごとに 1 回だけ測る。"""
        seed0 = self.band("behaviour", rnd)
        if seed0 not in self._baseline:
            out = series_rs_digest(self.champion(), self.champion(), self.behav_n, self.cfg,
                                   self.workers, seed0=seed0)
            self._baseline[seed0] = [r[4] for r in out]
        return self._baseline[seed0]

    def behaviour(self, delta: dict, rnd: int) -> dict:
        """δ が champion の手を変えたか（D-053 裁定 2）。

        挑戦者と champion を**同じシード・同じ相手（champion）**で `behav_n` 局回し、
        各局の手の記録のハッシュを champion 自身の列と比べる。全局一致なら
        「δ は一手も変えていない」＝測る価値が無い候補である。
        以前の発火判定（合法手が減った決定の数）は上限であって挙動変化の証拠ではなかった。"""
        seed0 = self.band("behaviour", rnd)
        base = self.baseline_digests(rnd)
        out = series_rs_digest(self.challenger(delta), self.champion(), self.behav_n, self.cfg,
                               self.workers, seed0=seed0)
        changed = [i for i, r in enumerate(out) if r[4] != base[i]]
        return {"n": self.behav_n, "seed0": seed0, "changed_games": len(changed),
                "first_changed_seed": (seed0 + changed[0]) if changed else None,
                "fired_total": int(sum(r[3] for r in out))}

    def vs_champion(self, delta: dict, n: int, seed0: int) -> dict:
        out = series_rs_detail(self.challenger(delta), self.champion(), n, self.cfg,
                               self.workers, seed0=seed0)
        d = _summ(out)
        d["seed0"] = seed0
        return d

    def evaluate(self, delta: dict, rnd: int, skip_screen: bool = False) -> dict:
        """1 候補を段階 0〜3 に通す。戻り値は台帳の 1 行。"""
        rec = {"delta": delta, "label": label(delta)}
        b = self.behaviour(delta, rnd)
        rec["behaviour"] = b
        if b["changed_games"] == 0:
            rec["verdict"] = "no_change"
            self._log(f"  - {rec['label']}: 挙動が変わらない（対 champion {self.behav_n} 局で一手も違わない）→ 測らない")
            return rec
        if not skip_screen:
            s = self.vs_champion(delta, self.screen_n, self.band("screen", rnd))
            rec["screen"] = s
            if s["p"] < SCREEN_PASS:
                rec["verdict"] = "screen_fail"
                self._log(f"  - {rec['label']}: 探索 {s['p']:.3f} (n={s['decided']}) → 落ちる")
                return rec
            self._log(f"  - {rec['label']}: 探索 {s['p']:.3f} (n={s['decided']}) → 確認へ")
        c = self.vs_champion(delta, self.confirm_n, self.band("confirm", rnd))
        rec["confirm"] = c
        p_all, lb_all = c["p"], c["lb"]
        if 0.5 < lb_all <= BORDER:
            r2 = self.vs_champion(delta, self.confirm_n, self.band("reconfirm", rnd))
            rec["reconfirm"] = r2
            wins = c["wins"] + r2["wins"]
            dec = c["decided"] + r2["decided"]
            rr = Result(wins, dec, c["n"] + r2["n"])
            rec["pooled"] = {"wins": wins, "decided": dec, "p": rr.p, "ci": rr.ci, "lb": rr.p - rr.ci}
            p_all, lb_all = rr.p, rr.p - rr.ci
        rec["effect"] = p_all
        rec["effect_lb"] = lb_all
        if lb_all > 0.5:
            rec["verdict"] = "accepted"
            self._log(f"  * {rec['label']}: 確認 {p_all:.3f} 下端 {lb_all:.4f} → **発見**")
        else:
            rec["verdict"] = "confirm_fail"
            self._log(f"  - {rec['label']}: 確認 {p_all:.3f} 下端 {lb_all:.4f} → 落ちる")
        return rec

    # -- 一巡
    def run(self, candidates: list, max_folds: int = 3) -> list:
        """候補を全部測り、勝ち越したものを効果量の大きい順に取り込む。台帳の行を返す。"""
        self.round += 1
        rnd = self.round
        self._log(f"■ {self.deck_name} 第 {rnd} 巡: 候補 {len(candidates)} 体／champion の δ: "
                  f"{[label(d) for d in self.champion_deltas] or 'なし'}")
        rows = []
        for i, delta in enumerate(candidates, 1):
            self._log(f"[{i}/{len(candidates)}]")
            if delta in self.champion_deltas:
                self._log(f"  - {label(delta)}: champion に取り込み済み → 飛ばす")
                continue
            rec = self.evaluate(delta, rnd)
            self._record(rec)
            rows.append(rec)
        accepted = [r for r in rows if r["verdict"] == "accepted"]
        folds = 0
        while accepted and folds < max_folds:
            accepted.sort(key=lambda r: -r["effect"])
            best = accepted.pop(0)
            self.champion_deltas.append(best["delta"])
            folds += 1
            self._record({"delta": best["delta"], "label": best["label"], "verdict": "folded",
                          "effect": best["effect"], "effect_lb": best["effect_lb"]})
            self._log(f"→ 取り込み: {best['label']}（{best['effect']:.3f}）。残り {len(accepted)} 体を新 champion に対して測り直す")
            if not accepted:
                break
            self.round += 1
            rnd = self.round
            if rnd > self.max_rounds:
                self._log("  帯の列が足りないので測り直しを打ち切る（seed_bands.json に帯を足し BANDS に append すること）")
                break
            remeasured = []
            for r in accepted:
                rec = self.evaluate(r["delta"], rnd, skip_screen=True)
                self._record(rec)
                rows.append(rec)
                if rec["verdict"] == "accepted":
                    remeasured.append(rec)
            accepted = remeasured
        return rows


# ---------------------------------------------------------------------------
# 報告
# ---------------------------------------------------------------------------

def report(rows: list, deck_name: str, champion_deltas: list) -> str:
    lines = [f"# 発見ループ {deck_name}（{_dt.date.today().isoformat()}）", ""]
    acc = [r for r in rows if r["verdict"] in ("accepted", "folded")]
    folded = len([r for r in rows if r["verdict"] == "folded"])
    lines.append(f"候補 {len([r for r in rows if r['verdict'] != 'folded'])} 体。発見 "
                 f"{len([r for r in rows if r['verdict'] == 'accepted'])} 件。"
                 f"**この巡で**取り込み {folded} 件（champion の δ は開始時の {len(champion_deltas) - folded} 件を含めて "
                 f"{len(champion_deltas)} 件）。")
    lines.append("")
    lines.append("| 判定 | δ | 挙動が変わった局 | 探索 | 確認 | 下端 |")
    lines.append("|---|---|---|---|---|---|")
    order = {"folded": 0, "accepted": 1, "confirm_fail": 2, "screen_fail": 3, "no_change": 4}
    for r in sorted(rows, key=lambda r: (order.get(r["verdict"], 9), -(r.get("effect") or r.get("screen", {}).get("p") or 0))):
        f = r.get("behaviour", {})
        s = r.get("screen")
        c = r.get("confirm")
        lines.append("| {} | {} | {}/{} | {} | {} | {} |".format(
            r["verdict"], r["label"],
            f.get("changed_games", "—"), f.get("n", "—"),
            f"{s['p']:.3f}" if s else "—",
            f"{r['effect']:.3f} (n={c['decided']}{'+' + str(r['reconfirm']['decided']) if 'reconfirm' in r else ''})" if c else "—",
            f"{r['effect_lb']:.4f}" if c else "—"))
    lines.append("")
    if champion_deltas:
        lines.append("新 champion の δ（重ねた順）: " + " → ".join(label(d) for d in champion_deltas))
    else:
        lines.append("取り込みなし（この語彙で champion に勝ち越す δ は無かった）")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--gens", default="A,C")
    ap.add_argument("--full-b", action="store_true", help="生成器 B を全部（連撃禁止・温存も）")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--screen-n", type=int, default=SCREEN_N)
    ap.add_argument("--confirm-n", type=int, default=CONFIRM_N)
    ap.add_argument("--max-folds", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="候補を先頭 N 体に絞る（試運転用）")
    ap.add_argument("--list", action="store_true", help="候補を数えるだけ")
    ap.add_argument("--out", default=None, help="報告の書き出し先（既定: results/discoveries/<deck>_report.md）")
    ap.add_argument("--champion", default=None,
                    help="開始時の champion に重ねる δ（JSON のリスト）。前の巡の取り込み結果から続けるとき")
    ap.add_argument("--round", type=int, default=0, help="開始時の巡番号（帯をずらすため。前の巡の続きなら前回の最終巡）")
    a = ap.parse_args(argv)

    deck = load_deck(a.deck)
    cands = []
    for g in a.gens.split(","):
        g = g.strip().upper()
        if g == "B":
            cands += gen_B(deck, full=a.full_b)
        else:
            cands += GENERATORS[g](deck)
    if a.limit:
        cands = cands[:a.limit]
    if a.list:
        for d in cands:
            print(label(d), "  ", json.dumps(d, ensure_ascii=False))
        print(f"候補 {len(cands)} 体")
        return 0

    loop = Loop(a.deck, a.workers, a.screen_n, a.confirm_n)
    if a.champion:
        loop.champion_deltas = json.loads(a.champion)
    loop.round = a.round
    rows = loop.run(cands, max_folds=a.max_folds)
    text = report(rows, a.deck, loop.champion_deltas)
    out = a.out or os.path.join(LEDGER_DIR, f"{a.deck}_report{'_r' + str(loop.round) if a.round else ''}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print()
    print(text)
    print(f"\n台帳: {loop.ledger_path}\n報告: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
