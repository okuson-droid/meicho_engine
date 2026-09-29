"""保存（要件 R-NET-6・R-DATA-1〜3）。置き場所は 1 つのフォルダで、中身は JSON のファイルだけである。

- `rooms/<部屋ID>.json`: 開いている部屋 1 つ。**盤面は入れない**——シード・デッキ・行動列から当て直す
- `games/<年-月>.jsonl`: 終局した対局の記録。1 行 1 局

書き込みは「一時ファイルに書いてから置き換える」。途中で落ちても、前の版か新しい版のどちらかが必ず残る。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .game import Game, check_deck
from . import protocol as P
from .protocol import PROTOCOL_VERSION, AppError

JST = timezone(timedelta(hours=9))
RECORD_VERSION = 3          # 現行 webapp の記録は app_version 1・2（R-DATA-6）。新アプリは 3 から
ENGINE_DIR = Path(__file__).resolve().parents[2]


def rules_version(engine_dir: Path = ENGINE_DIR) -> str:
    """rules の版を `rules_draft.md` の見出しから読む。版を書く場所はここ 1 か所（R-DATA-3）。"""
    try:
        with open(engine_dir / "rules_draft.md", encoding="utf-8") as f:
            m = re.search(r"v\d+\.\d+", f.readline())
        return m.group(0) if m else "unknown"
    except OSError:
        pass
    # 配布版には rules_draft.md を入れない（内部文書・R-LAW-1）。公開のときに読んだ版が目録に書いてある
    from .release import manifest
    m = manifest(engine_dir)
    return str(m.get("rules_version") or "unknown") if m else "unknown"


def cards_version(engine_dir: Path = ENGINE_DIR) -> str:
    """カードデータの版。`meicho/cards.py` の中身のハッシュの先頭 12 桁（改行の違いは無視する）。"""
    try:
        data = (engine_dir / "meicho" / "cards.py").read_bytes().replace(b"\r\n", b"\n")
        return hashlib.sha256(data).hexdigest()[:12]
    except OSError:
        return "unknown"


def make_record(fin: dict, *, kind: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """`Room.finished` の 1 件から、保存する記録を作る。保存の前に再生して照合する（R-DATA-1）。"""
    g = fin["game"]
    replayed = Game.load(g)
    res = replayed.result()
    rec = {
        "app_version": RECORD_VERSION, "protocol": PROTOCOL_VERSION,
        "rules_version": rules_version(), "cards_version": cards_version(),
        "played_at": (now or datetime.now(JST)).isoformat(timespec="seconds"),
        "kind": kind or fin.get("kind") or "pvp", "names": fin["names"], "first_mode": fin.get("first_mode"),
        "opponent": fin.get("opponent"),                   # CPU 対戦のときだけ: 登録名・段・AI のシード・AI の席
        "times": g.get("times") or [],                      # 席ごとの所要時間（ミリ秒）。applies と同じ並び（R-DATA-7）
        "seed": g["seed"], "decks": g["decks"],            # デッキは全体を残す（R-DATA-2）
        "applies": g["applies"], "resigned": g["resigned"], "flags": list(fin.get("flags") or []),
        "result": fin["result"], "verified": res == fin["result"],
    }
    return rec


class Store:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "rooms").mkdir(parents=True, exist_ok=True)
        (self.root / "games").mkdir(parents=True, exist_ok=True)

    def _room_path(self, rid: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", rid):
            raise ValueError("bad room id")
        return self.root / "rooms" / f"{rid}.json"

    def save_room(self, dump: dict) -> None:
        path = self._room_path(dump["id"])
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dump, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def delete_room(self, rid: str) -> None:
        try:
            self._room_path(rid).unlink()
        except FileNotFoundError:
            pass

    def load_rooms(self) -> list:
        """読めたものだけ返す。壊れたファイルは `.broken` に改名して残す（黙って消さない）。"""
        out = []
        for path in sorted((self.root / "rooms").glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                path.replace(path.with_suffix(".broken"))
        return out

    def list_records(self, limit: int = 200) -> list:
        """終局した対局の記録を新しい順に。`id` は「ファイル名:行番号」。壊れた行は飛ばす。"""
        out = []
        for path in sorted((self.root / "games").glob("*.jsonl"), reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for i in range(len(lines) - 1, -1, -1):
                try:
                    rec = json.loads(lines[i])
                except ValueError:
                    continue
                out.append((f"{path.stem}:{i + 1}", rec))
                if len(out) >= limit:
                    return out
        return out

    def get_record(self, rid: str) -> Optional[dict]:
        m = re.fullmatch(r"(\d{4}-\d{2}):(\d{1,7})", str(rid or ""))
        if not m:
            return None
        path = self.root / "games" / f"{m.group(1)}.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            return json.loads(lines[int(m.group(2)) - 1]) if 0 < int(m.group(2)) <= len(lines) else None
        except (OSError, ValueError):
            return None

    def update_record(self, rid: str, rec: dict) -> bool:
        """記録 1 件を置き換える（印とメモの直し・R-REP-5）。ファイルは一時ファイルに書いてから置き換える。"""
        m = re.fullmatch(r"(\d{4}-\d{2}):(\d{1,7})", str(rid or ""))
        if not m:
            return False
        path = self.root / "games" / f"{m.group(1)}.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
        k = int(m.group(2)) - 1
        if not 0 <= k < len(lines):
            return False
        lines[k] = json.dumps(rec, ensure_ascii=False)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True

    def append_record(self, rec: dict) -> Path:
        path = self.root / "games" / f"{rec['played_at'][:7]}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return path


def record_problem(rec: dict) -> Optional[str]:
    """この記録を、いまのアプリで再生できない理由（できるなら None）。版が違う記録は再生不可と明示する（計画書 10 章・R-KIF-2）。"""
    if rec.get("app_version") != RECORD_VERSION:
        return f"記録の形式の版が違う（{rec.get('app_version')}。いまは {RECORD_VERSION}）"
    if rec.get("rules_version") != rules_version():
        return f"ルールの版が違う（記録は {rec.get('rules_version')}、いまは {rules_version()}）"
    if rec.get("cards_version") != cards_version():
        return "カードデータの版が違う（カードの追加や訂正のあとの記録ではない）"
    return None


FILE_FORMAT = "meichosim-record"   # 書き出したファイルの目印（R-KIF-1・APP-028）
FILE_VERSION = 1                     # ファイルの包みの版。中の記録の版は `app_version`
MAX_FILE_BYTES = 1024 * 1024         # 取り込むファイルの上限。長い局（5,000 手）でも 300KB ほど


def export_file(rec: dict) -> dict:
    """記録 1 件を、書き出すファイルの中身にする（R-KIF-1）。記録そのものに公式テキストと画像は無い（番号と行動だけ）。"""
    return {"format": FILE_FORMAT, "format_version": FILE_VERSION, "record": rec}


def export_name(rec: dict) -> str:
    """書き出すファイルの名前。英数字だけにする（どの OS・どのブラウザでも崩れない）。"""
    when = re.sub(r"\D", "", str(rec.get("played_at") or ""))[:12]
    kind = rec.get("kind") if rec.get("kind") in ("cpu", "pvp", "practice") else "game"
    return f"meichosim_{when[:8]}-{when[8:12]}_{kind}.json" if len(when) == 12 else f"meichosim_{kind}.json"


def import_file(obj) -> dict:
    """読み込んだファイルの中身から記録を取り出す。形が違えば理由つきの `AppError("bad_file")`（R-KIF-2）。

    ここでは形だけを検める。版の照合は `record_problem`、行動列と結果の照合は `replay.build` が行う。
    """
    def bad(why: str):
        return AppError("bad_file", f"棋譜のファイルではない（{why}）")

    if not isinstance(obj, dict) or obj.get("format") != FILE_FORMAT:
        raise bad("目印が無い")
    if obj.get("format_version") != FILE_VERSION:
        raise AppError("bad_file", f"ファイルの形式の版が違う（{obj.get('format_version')}。いまは {FILE_VERSION}）")
    rec = obj.get("record")
    if not isinstance(rec, dict):
        raise bad("記録が無い")
    if not isinstance(rec.get("seed"), int) or isinstance(rec.get("seed"), bool):
        raise bad("シードが無い")
    decks = rec.get("decks")
    if not isinstance(decks, list) or len(decks) != 2:
        raise bad("デッキが 2 つない")
    for d in decks:
        try:
            check_deck(d)
        except AppError as e:
            raise bad(f"デッキ: {e.msg}") from None
    applies = rec.get("applies")
    if not isinstance(applies, list) or not all(isinstance(row, dict) for row in applies):
        raise bad("行動列の形が違う")
    if rec.get("resigned") not in (None, 0, 1) or isinstance(rec.get("resigned"), bool):
        raise bad("投了の欄の形が違う")
    res = rec.get("result")
    if not isinstance(res, dict) or res.get("winner") not in (None, 0, 1) or not isinstance(res.get("reason"), str):
        raise bad("結果の形が違う")
    names = rec.get("names")
    if not (isinstance(names, list) and len(names) == 2 and all(isinstance(n, str) for n in names)):
        raise bad("対局者の名前の形が違う")
    return rec


def record_last_pos(rec: dict) -> int:
    """リプレイの最後の位置（行動の数。投了で終わった局は 1 つ多い）。印の位置の上限。"""
    return len(rec.get("applies") or []) + (1 if rec.get("resigned") is not None else 0)


def clean_flags(flags, last: int, *, by: str) -> list:
    """画面から来た印の一覧を検める（R-REP-5・APP-030）。形が違えば理由つきの `AppError`。

    1 つの印は `{pos, turn, note, by, seat, when}`。`pos` は何手目のあとの局面か（0..last）。
    新しく付けた印（`by` が無いもの）は、付けた人の名前 `by` で埋める。位置の順に並べて返す。
    """
    if not isinstance(flags, list) or len(flags) > P.MAX_FLAGS:
        raise AppError("bad_flags", f"印は一覧で、{P.MAX_FLAGS} 個まで")
    out = []
    for f in flags:
        if not isinstance(f, dict):
            raise AppError("bad_flags", "印の形が違う")
        pos, turn, note = f.get("pos"), f.get("turn"), f.get("note", "")
        if not isinstance(pos, int) or isinstance(pos, bool) or not 0 <= pos <= last:
            raise AppError("bad_flags", "印の位置が記録の外にある")
        if turn is not None and (not isinstance(turn, int) or isinstance(turn, bool) or not 0 <= turn <= 999):
            raise AppError("bad_flags", "印のターンの形が違う")
        if not isinstance(note, str) or len(note) > P.MAX_NOTE:
            raise AppError("bad_flags", f"メモは {P.MAX_NOTE} 字まで")
        who = f.get("by") if isinstance(f.get("by"), str) and f.get("by") else by
        seat = f.get("seat") if f.get("seat") in (0, 1) and not isinstance(f.get("seat"), bool) else None
        when = f.get("when") if f.get("when") in ("live", "replay") else "replay"
        out.append({"pos": pos, "turn": turn, "note": note.strip(), "by": who[:P.MAX_NAME], "seat": seat, "when": when})
    return sorted(out, key=lambda x: x["pos"])


def legacy_view(rec: dict) -> dict:
    """CPU 対戦の記録を、現行 `webapp/record.py` の形（app_version 2）に直す。**写しではなく、向こうの `verify` にそのまま渡すための変換**である。

    これが通ることが、計画書 8.2 の M5 の完了条件「記録が `record.verify` で再生照合できる」にあたる。
    現行の形は「人間 1 人対 AI・同じデッキ」を前提にしているので、対人戦の記録は直せない（`ValueError`）。
    """
    opp = rec.get("opponent")
    if rec.get("kind") != "cpu" or not opp:
        raise ValueError("現行の記録の形に直せるのは CPU 対戦の記録だけ")
    human = 1 - opp["seat"]
    actions = [{"seat": int(p), "action": a} for row in rec["applies"] for p, a in sorted(row.items())]
    res = dict(rec["result"])
    w = res.get("winner")
    res["winner"] = None if w is None else ("human" if w == human else "ai")
    return {"app_version": "2", "rules_version": rec["rules_version"], "played_at": rec["played_at"],
            "seed": rec["seed"], "deck": opp["deck"], "mode": "mirror", "human_seat": human,
            "opponent": {"name": opp["name"], "seed": opp["seed"]}, "actions": actions, "flags": rec.get("flags", []),
            "result": res}


class SeedBand:
    """アプリ用のシード帯から、使っていないシードを順に渡す（APP-008）。どこまで使ったかは保存先に控える。

    CPU 対戦の帯は 722000..741999。対局のシードと AI のシードに 1 つずつ使う。使い切ったら先頭に戻る
    （2 万個＝1 万局ぶん。戻っても研究用の帯には出ない）。
    """

    def __init__(self, path, lo: int = 722000, hi: int = 741999):
        self.path, self.lo, self.hi = Path(path), lo, hi
        try:
            self.next = int(json.loads(self.path.read_text(encoding="utf-8"))["next"])
        except (OSError, ValueError, KeyError, TypeError):
            self.next = lo
        if not lo <= self.next <= hi:
            self.next = lo

    def __call__(self) -> int:
        seed = self.next
        self.next = self.lo if seed >= self.hi else seed + 1
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"next": self.next, "lo": self.lo, "hi": self.hi}), encoding="utf-8")
        os.replace(tmp, self.path)
        return seed
