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

from .game import Game
from .protocol import PROTOCOL_VERSION

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
        "applies": g["applies"], "resigned": g["resigned"], "flags": [],
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
