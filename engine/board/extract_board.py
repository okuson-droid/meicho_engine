"""進行盤（段 6）の切り出し道具。

GitHub `main` の作業ツリー（sparse clone でよい）を読み、進行盤の db に置く 1 文書
（`PROGRESS_BOARD_DESIGN_20260929.md` §6 の形）を JSON で出す。

原則（設計書 §2「取り方の原則」・§7）:
- 台帳の文は要約しない。行そのものを装飾を落として切り出し、行番号と commit 固定の URL を添える。
- 切り出せなかった項目は空にし、`status` を `failed` にする（推測で埋めない）。
- `TASKS.md` の Active・Waiting On にある `- [ ]` の総数と、切り出した件数が合わないときも `failed`。
- 対局・学習・検査は回さない。ネットワークは `--ci` を付けたときのバッジ 1 本だけ。

使い方:
    python extract_board.py <repo_root> [--out board.json] [--ci] [--ci-tests passing] [--ci-wheel failing]

CI の状態: バッジ SVG は作業環境の代理サーバに拒まれる（2026-09-29 実測・403）ので、
定期実行のクロエが Actions のページを読んで `--ci-tests`・`--ci-wheel` で渡す。`--ci` は
バッジを取る試み（取れなければ unknown）。どちらも無ければ unknown。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys

REPO_URL = "https://github.com/okuson-droid/meicho_engine"
JST = _dt.timezone(_dt.timedelta(hours=9))
SCHEMA = 1

# 表示の切り方（設計書 §2）
RULING_CHARS = 200
ACTIVE_CHARS = 160
EXCERPT_CHARS = 600
RECENT_REPORTS = 3
RECENT_DECISIONS = 5
DESIGN_DOCS = 3


# ---------------------------------------------------------------- 文字の掃除

_MD_STRIP = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),   # 太字
    (re.compile(r"~~(.+?)~~"), r"\1"),       # 取り消し
    (re.compile(r"`([^`]*)`"), r"\1"),       # コード
]


def plain(text: str) -> str:
    """Markdown の装飾を落として素の文にする（中身は変えない）。"""
    for pat, rep in _MD_STRIP:
        text = pat.sub(rep, text)
    return text.strip()


def clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def blob_url(sha: str, path: str, line: int | None = None) -> str:
    url = f"{REPO_URL}/blob/{sha}/{path}"
    return f"{url}#L{line}" if line else url


def read_text(root: str, rel: str) -> str | None:
    p = os.path.join(root, rel)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------- git

def git_head(root: str) -> dict | None:
    try:
        out = subprocess.run(
            ["git", "-C", root, "log", "-1", "--format=%H%n%cI%n%s"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.splitlines()
    except Exception:  # noqa: BLE001 — git が無い・リポジトリでない
        return None
    if len(out) < 3:
        return None
    sha, date, subject = out[0], out[1], out[2]
    return {"sha": sha, "short": sha[:7], "date": date, "subject": subject,
            "url": f"{REPO_URL}/commit/{sha}"}


# ---------------------------------------------------------------- TASKS.md

_SECTION = re.compile(r"^## (.+?)\s*$")
# 字下げした小項目（親の段の途中）も拾い、`sub` の印を付ける
_UNCHECKED = re.compile(r"^(\s*)- \[ \] (.*)$")
# 数えるときはゆるく（`-[ ]`・`* [ ]` も拾う）。切り出しは厳しく。差があれば failed
_UNCHECKED_LOOSE = re.compile(r"^\s*[-*]\s*\[ \]")
_MASTER = "★マスター"
# 題（" - " より前）に「マスターの裁定」とある項目も裁定待ち（例: 「★輪 2 の探索器を…（マスターの裁定・便 E の前に）」）
_MASTER_TITLE = "マスターの裁定"
_PUSH = re.compile(r"推し[:：]\s*([^／/。]+)")


def split_sections(text: str) -> dict[str, list[tuple[int, str]]]:
    """`## 見出し` ごとに (行番号, 行) の列へ。"""
    sections: dict[str, list[tuple[int, str]]] = {}
    cur = None
    for i, line in enumerate(text.splitlines(), start=1):
        m = _SECTION.match(line)
        if m:
            cur = m.group(1)
            sections.setdefault(cur, [])
            continue
        if cur is not None:
            sections[cur].append((i, line))
    return sections


def extract_tasks(text: str, sha: str, errors: list[str]) -> dict:
    sections = split_sections(text)
    for need in ("Active", "Waiting On"):
        if need not in sections:
            errors.append(f"TASKS.md に `## {need}` が無い")
    rulings, active, waiting = [], [], []
    total_unchecked = 0
    for sec, lane_list, chars in (("Active", active, ACTIVE_CHARS),
                                  ("Waiting On", waiting, ACTIVE_CHARS)):
        for ln, line in sections.get(sec, []):
            if _UNCHECKED_LOOSE.match(line):
                total_unchecked += 1
            m = _UNCHECKED.match(line)
            if not m:
                continue
            body = plain(m.group(2))
            item = {"lane": "engine", "section": sec, "file": "TASKS.md", "line": ln,
                    "sub": bool(m.group(1)), "url": blob_url(sha, "TASKS.md", ln)}
            title = body.split(" - ", 1)[0]
            if _MASTER in body or _MASTER_TITLE in title:
                pm = _PUSH.search(body)
                item["text"] = clip(body, RULING_CHARS)
                item["push"] = pm.group(1).strip() if pm else ""
                rulings.append(item)
            else:
                item["text"] = clip(body, chars)
                lane_list.append(item)
    got = len(rulings) + len(active) + len(waiting)
    if got != total_unchecked:
        errors.append(f"TASKS.md の `- [ ]` {total_unchecked} 件のうち切り出せたのは {got} 件")
    if total_unchecked == 0 and ("Active" in sections):
        # Active があるのに未着手が 0 件なのは、書き方が変わった疑いが強い
        errors.append("TASKS.md の Active・Waiting On に `- [ ]` が 1 件も無い")
    return {"rulings_pending": rulings, "active": active, "waiting_on": waiting,
            "unchecked_total": total_unchecked}


# ---------------------------------------------------------------- decisions.md

_DHEAD = re.compile(r"^## (D-(\d+))\s+(.*?)\s*$")


def extract_decisions(text: str, sha: str, errors: list[str]) -> dict:
    heads = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = _DHEAD.match(line)
        if m:
            heads.append({"id": m.group(1), "num": int(m.group(2)),
                          "title": plain(m.group(3)), "line": i,
                          "url": blob_url(sha, "engine/decisions.md", i)})
    if not heads:
        errors.append("decisions.md に `## D-番号` の見出しが無い")
        return {"recent_decisions": [], "next_d": ""}
    max_num = max(h["num"] for h in heads)
    last = [{k: v for k, v in h.items() if k != "num"} for h in heads[-RECENT_DECISIONS:][::-1]]
    return {"recent_decisions": last, "next_d": f"D-{max_num + 1}"}


# ---------------------------------------------------------------- 版と champion

_RULES = re.compile(r'^RULES_VERSION\s*=\s*"([^"]+)"', re.M)
_ENC_ROW = re.compile(r"^\| 符号化 \|(.*)$", re.M)
_ENC_VER = re.compile(r"現在 v(\d+)")
_ENC_DIMS = re.compile(r"\((\d+), (\d+), (\d+)\)")
_CHAMP_ROW = re.compile(r"^\| champion \|(.*)$", re.M)
_CHAMP_NAME = re.compile(r"現在 \*\*`([^`]+)`\*\*")
_EXPECTED = re.compile(r'"([A-Za-z0-9_]+)":\s*"([0-9a-f]{16})"')


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def extract_versions(root: str, sha: str, errors: list[str]) -> dict:
    v: dict = {}
    src: dict = {}

    t = read_text(root, "engine/meicho/version.py")
    m = _RULES.search(t) if t else None
    if m:
        v["rules"] = m.group(1)
        src["rules"] = blob_url(sha, "engine/meicho/version.py", _line_of(t, m.start()))
    else:
        errors.append("version.py の RULES_VERSION が取れない")

    c = read_text(root, "CLAUDE.md")
    row = _ENC_ROW.search(c) if c else None
    if row:
        ver = _ENC_VER.search(row.group(1))
        dims = _ENC_DIMS.search(row.group(1))
        if ver and dims:
            v["encoding"] = f"v{ver.group(1)} ({dims.group(1)}, {dims.group(2)}, {dims.group(3)})"
            src["encoding"] = blob_url(sha, "CLAUDE.md", _line_of(c, row.start()))
    if "encoding" not in v:
        errors.append("CLAUDE.md の符号化の行から版が取れない")

    crow = _CHAMP_ROW.search(c) if c else None
    name = _CHAMP_NAME.search(crow.group(1)) if crow else None
    if name:
        v["champion"] = name.group(1)
        src["champion"] = blob_url(sha, "CLAUDE.md", _line_of(c, crow.start()))
    else:
        errors.append("CLAUDE.md の champion の行から名前が取れない")

    f = read_text(root, "engine/scripts/check_champion_fingerprint.py")
    if f:
        # `EXPECTED = {...}` の中だけを見る
        i = f.find("EXPECTED = {")
        block = f[i:f.find("}", i) + 1] if i >= 0 else ""
        pairs = dict(_EXPECTED.findall(block))
        if v.get("champion") in pairs:
            v["fingerprint"] = pairs[v["champion"]]
            pos = f.find(v["fingerprint"], i)
            src["fingerprint"] = blob_url(sha, "engine/scripts/check_champion_fingerprint.py",
                                          _line_of(f, pos))
        elif pairs:
            errors.append("check_champion_fingerprint.py の EXPECTED に champion の名前が無い")
    if "fingerprint" not in v:
        errors.append("champion の指紋が取れない")

    s = read_text(root, "engine/experiments/seed_bands.json")
    try:
        nf = json.loads(s)["next_free"] if s else None
    except (ValueError, KeyError, TypeError):
        nf = None
    if isinstance(nf, int):
        v["next_free_seed"] = nf
        src["next_free_seed"] = blob_url(sha, "engine/experiments/seed_bands.json")
    else:
        errors.append("seed_bands.json の next_free が取れない")

    v["_source"] = src
    return v


# ---------------------------------------------------------------- 報告書と設計書

_DATE_IN_NAME = re.compile(r"(20\d{6})")
_CONCLUSION = re.compile(r"^#{2,3}\s+(?:\d+\.\s*)?(結論|要約|0\. 結論)")
_H = re.compile(r"^#{1,3}\s")


def _dated_md(root: str, pattern: re.Pattern | None = None) -> list[tuple[str, str]]:
    """engine/*.md のうち名前に日付を含むものを (日付, 相対パス) で新しい順に。"""
    out = []
    d = os.path.join(root, "engine")
    if not os.path.isdir(d):
        return out
    for name in os.listdir(d):
        if not name.endswith(".md"):
            continue
        if pattern and not pattern.search(name):
            continue
        m = _DATE_IN_NAME.search(name)
        if not m:
            continue
        out.append((m.group(1), f"engine/{name}"))
    out.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return out


def first_paragraph_after(lines: list[str], start: int) -> tuple[str, int]:
    """見出しの次の空でない段落（連続する行）を返す。(本文, 開始行番号 1-based)"""
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    buf, first = [], i + 1
    while i < len(lines) and lines[i].strip() and not _H.match(lines[i]):
        buf.append(plain(lines[i]))
        i += 1
    return " ".join(buf), first


def extract_reports(root: str, sha: str) -> list[dict]:
    reports = []
    skip = re.compile(r"(DESIGN|COMPARE|REQUEST|PLAN)", re.I)
    for date, rel in _dated_md(root):
        if skip.search(rel):
            continue
        text = read_text(root, rel)
        if text is None:
            continue
        lines = text.splitlines()
        excerpt, ln = "", 1
        for i, line in enumerate(lines):
            if _CONCLUSION.match(line):
                excerpt, ln = first_paragraph_after(lines, i + 1)
                break
        if not excerpt:
            # 結論の節が無ければ、題の次の段落
            for i, line in enumerate(lines):
                if line.startswith("# "):
                    excerpt, ln = first_paragraph_after(lines, i + 1)
                    break
        reports.append({"file": rel, "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
                        "excerpt": clip(excerpt, EXCERPT_CHARS), "note": "",
                        "line": ln, "url": blob_url(sha, rel, ln)})
        if len(reports) >= RECENT_REPORTS:
            break
    return reports


_NUM_ITEM = re.compile(r"^(\d+)\.\s+\*\*(.+?)\*\*(.*)$")
_PUSH_LINE = re.compile(r"^\s*-\s+\*\*推し[:：]\s*(.+?)\*\*|^\s*-\s+推し[:：]\s*(.+)$")


def extract_design_rulings(root: str, sha: str, ledger_text: str = "") -> list[dict]:
    """最新の設計書・比較書の「判断が要る点」節から、裁定待ちの項目を切り出す。

    「裁定待ちか」は文書の自己申告ではなく台帳（`TASKS.md` の未着手の行）で決める:
    そのファイル名を含む `- [ ]` の行に「裁定待ち」と書かれている文書だけを対象にする。
    項目の行に「裁定」の語があれば個別に済んだものとして除く。
    """
    pending_docs = set()
    for line in ledger_text.splitlines():
        if _UNCHECKED_LOOSE.match(line) and "裁定待ち" in line:
            for name in re.findall(r"engine/([A-Za-z0-9_\-]+\.md)", line):
                pending_docs.add(f"engine/{name}")
    out = []
    for _date, rel in _dated_md(root, re.compile(r"(DESIGN|COMPARE)", re.I))[:DESIGN_DOCS]:
        if rel not in pending_docs:
            continue
        text = read_text(root, rel)
        if text is None:
            continue
        lines = text.splitlines()
        in_sec = False
        cur = None
        for i, line in enumerate(lines, start=1):
            if _H.match(line):
                in_sec = "判断が要る点" in line
                cur = None
                continue
            if not in_sec:
                continue
            m = _NUM_ITEM.match(line)
            if m:
                rest = m.group(3)
                cur = {"lane": "design", "section": rel.split("/")[-1], "file": rel,
                       "line": i, "url": blob_url(sha, rel, i),
                       "text": clip(plain(m.group(2) + rest), RULING_CHARS), "push": "",
                       "decided": "裁定" in rest}
                out.append(cur)
                continue
            if cur is not None and not cur["push"]:
                pm = _PUSH_LINE.match(line)
                if pm:
                    cur["push"] = plain(pm.group(1) or pm.group(2) or "")
    return [x for x in out if not x.pop("decided")]


# ---------------------------------------------------------------- CI（任意・ネットワーク）

_BADGE_TITLE = re.compile(r"<title>([^<]*)</title>")


def fetch_badge(workflow: str, timeout: float = 10.0) -> str:
    url = f"{REPO_URL}/actions/workflows/{workflow}/badge.svg"
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            svg = r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return "unknown"
    m = _BADGE_TITLE.search(svg)
    txt = (m.group(1) if m else svg).lower()
    if "passing" in txt:
        return "passing"
    if "failing" in txt:
        return "failing"
    return "unknown"


# ---------------------------------------------------------------- 組み立て

_CI_WORDS = {"passing": "passing", "success": "passing", "failing": "failing", "failure": "failing",
             "in progress": "running", "running": "running", "queued": "running"}


def norm_ci(word: str | None) -> str:
    if not word:
        return "unknown"
    return _CI_WORDS.get(word.strip().lower(), "unknown")


def build(root: str, with_ci: bool = False, now: _dt.datetime | None = None,
          ci_tests: str | None = None, ci_wheel: str | None = None) -> dict:
    errors: list[str] = []
    now = now or _dt.datetime.now(JST)
    head = git_head(root)
    if head is None:
        errors.append("git の HEAD が読めない")
        head = {"sha": "", "short": "", "date": "", "subject": "", "url": ""}
    sha = head["sha"] or "main"

    doc: dict = {"schema": SCHEMA, "taken_at": now.isoformat(timespec="seconds"),
                 "commit": head}

    tasks_text = read_text(root, "TASKS.md")
    if tasks_text is None:
        errors.append("TASKS.md が無い")
        doc.update({"rulings_pending": [], "active": [], "waiting_on": [], "unchecked_total": 0})
    else:
        doc.update(extract_tasks(tasks_text, sha, errors))

    dec_text = read_text(root, "engine/decisions.md")
    if dec_text is None:
        errors.append("engine/decisions.md が無い")
        doc.update({"recent_decisions": [], "next_d": ""})
    else:
        doc.update(extract_decisions(dec_text, sha, errors))

    doc["versions"] = extract_versions(root, sha, errors)
    doc["recent_reports"] = extract_reports(root, sha)
    doc["rulings_pending"] = doc.get("rulings_pending", []) + extract_design_rulings(root, sha, tasks_text or "")

    tests = norm_ci(ci_tests)
    wheel = norm_ci(ci_wheel)
    if with_ci:
        tests = tests if tests != "unknown" else fetch_badge("tests.yml")
        wheel = wheel if wheel != "unknown" else fetch_badge("wheel-windows.yml")
    checked = now.isoformat(timespec="seconds") if (with_ci or ci_tests or ci_wheel) else ""
    doc["ci"] = {"tests": tests, "wheel": wheel, "checked_at": checked}

    doc["status"] = "failed" if errors else "ok"
    doc["error"] = "／".join(errors)
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", help="main の作業ツリー（sparse clone でよい）")
    ap.add_argument("--out", help="書き出す JSON（省略時は標準出力）")
    ap.add_argument("--ci", action="store_true", help="Actions のバッジを取る試み（ネットワーク 2 本・拒まれれば unknown）")
    ap.add_argument("--ci-tests", help="Tests の状態（passing/failing/success/failure/in progress）")
    ap.add_argument("--ci-wheel", help="Windows wheel の状態（同上）")
    a = ap.parse_args(argv)
    doc = build(a.root, with_ci=a.ci, ci_tests=a.ci_tests, ci_wheel=a.ci_wheel)
    s = json.dumps(doc, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(s + "\n")
    else:
        sys.stdout.write(s + "\n")
    print(f"[extract_board] status={doc['status']} rulings={len(doc['rulings_pending'])} "
          f"active={len(doc['active'])} waiting={len(doc['waiting_on'])} "
          f"next_d={doc.get('next_d')} error={doc['error'] or '-'}", file=sys.stderr)
    return 0 if doc["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
