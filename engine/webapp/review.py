"""対局後レビューの土台（APP_DESIGN.md §5・段階2）。

## なぜ「対局後」なのか

対局中に見えるのは `observe()` が返す情報だけである（＝AI と同じ情報）。
その状態では、AI の手が悪いのか、こちらに見えていないだけなのかを区別できない。
**両者の手札と山札まで見えて初めて、AI の手を正確に批判できる。**

## 安全装置（§5.7）

ここが返すものには**両者の手札も山札の順序も入っている**。
対局中の画面に渡したら不正になる。したがって:

- この関数は**記録（`record`）からしか作れない**。進行中の `Session` は受け取らない。
- 記録は対局が終わったときにしか書かれない。
- サーバ側は「終了した対局の記録」に対してのみこの API を開ける。

構造として、進行中の対局のレビューは作れない。
"""
from __future__ import annotations

from meicho.engine import decision_players, legal_actions, observe
from meicho.state import Phase

from . import record as record_mod
from . import view

PHASE_JA = view.PHASE_JA


def _hand(cids) -> list:
    return [view.action_card(c) for c in cids]


def _side(st, pi: int) -> dict:
    """**全情報**の片側。対局中の画面に渡してはならない。"""
    p = st.players[pi]
    return {
        "life": p.life,
        "hand": _hand(p.hand),
        "concerto": _hand(p.concerto),
        "action_area": _hand(p.action_area),
        "trash_count": len(p.trash),
        "deck_count": len(p.action_deck),
        "deck_top": _hand(p.action_deck[:5]),   # 次に何を引くか（レビュー限定）
        "slots": [view._slot(list(sl.stack)) for sl in p.slots],
        "chara_deck": [view.chara_card(c) for c in p.chara_deck],
    }


def build(rec: dict, config) -> dict:
    """記録から、1 手ごとの全情報レビューを組み立てる。

    各手について「その手を決めた時点の局面」「選べた手の一覧」「実際に選んだ手」を
    並べる。**選べた手の一覧はエンジンの `legal_actions` をそのまま呼んで得る**
    ので、レビュー画面が独自にルールを解釈することはない。
    """
    rep = record_mod.replay(rec, config, keep_states=True)
    states = rep["states"]
    human = rec["human_seat"]

    # 記録は 1 手 1 行だが、同時提出（対抗ステップ）は 1 回の `apply` で
    # 2 行ぶん進む。そこで「局面を進めながら、その局面の決定者ぶんだけ
    # 記録を読む」方式で対応づける。`replay` が返す局面列と、記録の行が
    # 同じ順で並んでいることが前提であり、それは `verify` が保証している。
    steps = []
    idx = 0
    rows = list(rec["actions"])
    for k, st in enumerate(states):
        if st.outcome is not None:
            break
        need = decision_players(st)
        if not need:
            break
        here = []
        for pi in need:
            if idx >= len(rows):
                break
            # 記録は席の昇順で書かれている（session._step が sorted で回す）
            row = next((r for r in rows[idx:idx + len(need)]
                        if r["seat"] == pi), None)
            if row is None:
                continue
            acts = legal_actions(st, pi)
            ob = observe(st, pi)
            here.append({
                "seat": pi,
                "by": "human" if pi == human else "ai",
                "ply": row["ply"],
                "auto": bool(row.get("auto")),
                "ms": row.get("ms"),
                "action": row["action"],
                "label": view.action_label(ob, row["action"]),
                "n_legal": len(acts),
                # 選べた他の手。**その席から見た観測**で言い換える（表現の一貫性）
                "alternatives": [view.action_label(ob, a) for a in acts],
            })
        idx += len(need)
        if not here:
            break
        steps.append({
            "step": k,
            "turn": st.turn_no,
            "turn_player": st.turn_player,
            "phase": st.phase.value,
            "phase_ja": PHASE_JA.get(st.phase.value, st.phase.value),
            "me": _side(st, human),
            "opp": _side(st, 1 - human),
            "decisions": here,
        })

    return {
        "game_id": rec.get("game_id"),
        "seed": rec.get("seed"),
        "human_seat": human,
        "opponent": rec.get("opponent"),
        "played_at": rec.get("played_at"),
        "result": rec.get("result"),
        "flags": rec.get("flags", []),
        "steps": steps,
        "final": {"me": _side(rep["final"], human),
                  "opp": _side(rep["final"], 1 - human)},
    }


# ------------------------------------------------------------------ 文字出力
def _cards(lst) -> str:
    return "、".join(c["label"] for c in lst) if lst else "—"


def to_text(rv: dict) -> list:
    """レビューを人が読める行の列にする（段階2 の画面ができるまでの当座）。"""
    out = []
    r = rv["result"] or {}
    opp = rv["opponent"] or {}
    out.append(f"# 対局 {rv['game_id']}（{rv.get('played_at')}）")
    out.append(f"相手 {opp.get('name')}／シード {rv['seed']}／"
               f"あなたは{'先攻' if rv['human_seat'] == 0 else '後攻'}")
    out.append(f"結果: {r.get('winner')}／{r.get('turns')} ターン／"
               f"ライフ {r.get('life')}")
    out.append("")
    last_turn = None
    for s in rv["steps"]:
        if s["turn"] != last_turn:
            last_turn = s["turn"]
            tp = "あなた" if s["turn_player"] == rv["human_seat"] else "CPU"
            out.append("")
            out.append(f"════ ターン {s['turn']}（{tp} の番）════")
        me, op = s["me"], s["opp"]
        out.append(f"-- [{s['phase_ja']}] ライフ あなた{me['life']} / CPU {op['life']}")
        out.append(f"   あなたの手札: {_cards(me['hand'])}")
        out.append(f"   CPU の手札  : {_cards(op['hand'])}")
        if me["concerto"] or op["concerto"]:
            out.append(f"   協奏 あなた{len(me['concerto'])} / CPU {len(op['concerto'])}")
        for d in s["decisions"]:
            who = "あなた" if d["by"] == "human" else "CPU"
            tag = "（自動・他に手が無い）" if d["n_legal"] == 1 else \
                  f"（{d['n_legal']} 通りから）"
            out.append(f"   {who}: {d['label']} {tag}")
    return out


# ------------------------------------------------------------------ HTML 出力
_CSS = """
body{margin:0;padding:16px;background:#f6f7f9;color:#1c2128;
 font:14px/1.65 "Segoe UI","Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif}
h1{font-size:19px;margin:0 0 4px} .sub{color:#6b7480;font-size:13px;margin-bottom:14px}
.turn{margin:18px 0 8px;padding:5px 10px;background:#1c2128;color:#fff;border-radius:6px;font-weight:700}
.step{background:#fff;border:1px solid #d6dae0;border-radius:8px;padding:9px 12px;margin-bottom:7px}
.ph{font-size:11px;color:#6b7480;margin-bottom:4px}
.hands{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;margin-bottom:5px}
.hands div{flex:1 1 320px}
.hands b{display:block;font-size:11px;color:#6b7480}
.me b{color:#2258b8} .op b{color:#b06a6a}
.d{margin-top:4px;padding:3px 8px;border-left:3px solid #cbd5e0;font-size:13px}
.d.ai{border-left-color:#b06a6a;background:#fdf6f6}
.d.hu{border-left-color:#4a7fb5;background:#f4f8fd}
.d .n{color:#6b7480;font-size:11px;margin-left:6px}
.d.mark{background:#fff6cc;border-left-color:#e0b400}
.note{font-size:12px;color:#8a6b00;margin-top:3px}
details{margin-top:3px} summary{font-size:11px;color:#6b7480;cursor:pointer}
details ul{margin:3px 0 0;padding-left:18px;font-size:12px;color:#48505a}
.res{background:#fff;border:1px solid #d6dae0;border-radius:8px;padding:12px;margin-bottom:14px}
.warn{background:#fffaf0;border:1px solid #e6d9b8;border-radius:8px;padding:10px 12px;
 font-size:12px;margin-bottom:14px}
"""


def _esc(t: str) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def to_html(rv: dict, marks: dict | None = None) -> str:
    """レビューを 1 枚の HTML にする。

    `marks` は {(turn, phase, by): "注記"} の形で、注目したい手に印を付ける。
    **これは対局後にしか作れない**（全情報が入っている）。他人に見せる想定はしない。
    """
    marks = marks or {}
    r = rv["result"] or {}
    opp = rv["opponent"] or {}
    seat = "先攻" if rv["human_seat"] == 0 else "後攻"
    win = {"human": "あなたの勝ち", "ai": "CPU の勝ち"}.get(r.get("winner"), "引き分け")

    h = ["<!doctype html><html lang='ja'><head><meta charset='utf-8'>",
         f"<title>対局レビュー {_esc(rv['game_id'])}</title><style>{_CSS}</style>",
         "</head><body>",
         f"<h1>対局レビュー {_esc(rv['game_id'])}</h1>",
         f"<div class='sub'>{_esc(rv.get('played_at'))}／相手 {_esc(opp.get('name'))}"
         f"／シード {rv['seed']}／あなたは{seat}</div>",
         f"<div class='res'><b>{win}</b>　{r.get('turns')} ターン／"
         f"ライフ あなた {(r.get('life') or [0, 0])[rv['human_seat']]}"
         f" ・ CPU {(r.get('life') or [0, 0])[1 - rv['human_seat']]}</div>",
         "<div class='warn'>この画面は<b>両者の手札と山札まで見えている</b>。"
         "対局中には見えなかった情報が含まれるので、"
         "「そのとき自分に見えていたか」と混同しないこと。"
         "選択肢の数は<b>エンジンの合法手</b>そのままである。</div>"]

    last = None
    for s in rv["steps"]:
        if s["turn"] != last:
            last = s["turn"]
            tp = "あなた" if s["turn_player"] == rv["human_seat"] else "CPU"
            h.append(f"<div class='turn'>ターン {s['turn']}（{tp} の番）"
                     f"　ライフ あなた {s['me']['life']} ・ CPU {s['opp']['life']}</div>")
        h.append("<div class='step'>")
        h.append(f"<div class='ph'>{_esc(s['phase_ja'])}"
                 f"　協奏 あなた{len(s['me']['concerto'])}・CPU{len(s['opp']['concerto'])}</div>")
        h.append("<div class='hands'>"
                 f"<div class='me'><b>あなたの手札</b>{_esc(_cards(s['me']['hand']))}</div>"
                 f"<div class='op'><b>CPU の手札</b>{_esc(_cards(s['opp']['hand']))}</div>"
                 "</div>")
        for d in s["decisions"]:
            who = "あなた" if d["by"] == "human" else "CPU"
            cls = "hu" if d["by"] == "human" else "ai"
            key = (s["turn"], s["phase"], d["by"])
            note = marks.get(key)
            if note:
                cls += " mark"
            n = ("（他に手が無い）" if d["n_legal"] == 1
                 else f"（{d['n_legal']} 通りから）")
            h.append(f"<div class='d {cls}'>{who}: {_esc(d['label'])}"
                     f"<span class='n'>{n}</span>")
            if note:
                h.append(f"<div class='note'>▲ {_esc(note)}</div>")
            if d["n_legal"] > 1:
                h.append("<details><summary>選べた手 "
                         f"{d['n_legal']} 通りを見る</summary><ul>"
                         + "".join(f"<li>{_esc(a)}</li>" for a in d["alternatives"])
                         + "</ul></details>")
            h.append("</div>")
        h.append("</div>")
    h.append("</body></html>")
    return "\n".join(h)
