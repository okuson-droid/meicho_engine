"""進行盤の切り出し道具の検査（`PROGRESS_BOARD_DESIGN_20260929.md` §9）。

PC の資材（`cards/`・Rust）は要らない。小さな作り物のリポジトリで通る側と壊す側を見る。
本物の `main` の写しがあれば（環境変数 `BOARD_REPO`）、それでも 1 回回す。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import extract_board as eb  # noqa: E402

TASKS = """# Tasks

> 前置き

## Active

- [x] ~~**済んだもの**~~ (2026-09-28)
- [ ] **★マスター: 再ビルドの確認（D-134）** - 依頼は `engine/REBUILD_REQUEST_20260925.md`。推し: 今週中／ほか: 来週
- [ ] **開発の流れの組み替え（D-136）** - GitHub が正本
  - [x] 段 1
  - [ ] 段 6 進行盤の設計 `engine/PROGRESS_BOARD_DESIGN_20260929.md` — 裁定待ち
- [ ] **`test_d065.py` が落ちる** - 小さい

## Waiting On

- [ ] **次の champion 交代は新エンジンで** - D-097 §5
- [ ] **★輪 2 の探索器を揃えるか（マスターの裁定・便 E の前に）** - 推し: 揃える
- [ ] **計画外の気づき** - 本文にマスターの裁定という語があっても題に無ければ普通の項目

## Someday

- [ ] **便 E 反復 7'** - 急がない

## Done

- [x] ~~**Kaggle**~~
"""

DECISIONS = """# decisions

## D-001 最初の判断（2026-08-20）

本文。

## D-144 段階3 反復 1 の選択の評価: **V_1 − V_0 = −0.0035**（2026-09-28）

本文。

### D-144 追記 1 裁定
"""

VERSION_PY = 'RULES_VERSION = "v0.19"\nENGINE_VERSION = "v0.1"\n'

CLAUDE_MD = """# Memory

## Terms
| Term | Meaning |
|------|---------|
| champion | そのカードプールでいちばん強い AI。現在 **`planner_vc4cps_kheb_b75`**（SD001） |
| 符号化 | 観測・行動の符号化の版。**現在 v6**（D-124）。`meicho_rs.encoding_info()` = **`(6, 1923, 317)`** |
"""

FINGERPRINT_PY = '''"""EXPECTED の説明（ここは辞書ではない・旧値 e1662edb32b144a9）"""
EXPECTED = {"planner_vc4cps_kheb_b75": "f4b80b25c35cfa77",
            "planner_vc4cps_kheb": "b4d3b2a1986b71b9"}
'''

SEED_BANDS = '{"_comment": "x", "bands": [], "next_free": 859000}\n'

REPORT = """# 段階3 反復 1 セッション (6)（2026-09-28）

前置き。

## 結論

**V_1 − V_0 = −0.0035 [−0.0215, +0.0138]**（各 4,800 局）。区間が 0 をまたぐので V_1 は採らない。
設計書 §3.8 の止める規則により、反復はここで止まる。

## 1. 回したもの
"""

DESIGN = """# 進行盤（段 6）— 設計書

## 10. 判断が要る点（推しを先に）

1. **データの経路**
   - **推し: 定期実行のクロエが `main` を読んで db に書く**
   - ほか: Actions
2. **更新の頻度** — **裁定: 1 日 3 回**
   - 推し（採られず）: 1 日 2 回
"""


def make_repo(tmp_path, *, tasks=TASKS, decisions=DECISIONS, design=DESIGN, git=True):
    root = tmp_path / "repo"
    (root / "engine" / "meicho").mkdir(parents=True)
    (root / "engine" / "experiments").mkdir()
    (root / "engine" / "scripts").mkdir()
    (root / "TASKS.md").write_text(tasks, encoding="utf-8")
    (root / "CLAUDE.md").write_text(CLAUDE_MD, encoding="utf-8")
    (root / "engine" / "decisions.md").write_text(decisions, encoding="utf-8")
    (root / "engine" / "meicho" / "version.py").write_text(VERSION_PY, encoding="utf-8")
    (root / "engine" / "scripts" / "check_champion_fingerprint.py").write_text(FINGERPRINT_PY, encoding="utf-8")
    (root / "engine" / "experiments" / "seed_bands.json").write_text(SEED_BANDS, encoding="utf-8")
    (root / "engine" / "CC_STAGE3_IT1_S6_20260928.md").write_text(REPORT, encoding="utf-8")
    (root / "engine" / "PROGRESS_BOARD_DESIGN_20260929.md").write_text(design, encoding="utf-8")
    if git:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
        subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True, env=env)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "作り物の commit"], check=True, env=env)
    return str(root)


# ---------------------------------------------------------------- 通る側

def test_counts_and_split(tmp_path):
    doc = eb.build(make_repo(tmp_path))
    assert doc["status"] == "ok", doc["error"]
    # Active の `- [ ]` 4 件（★マスター 1・字下げの小項目 1 を含む）＋ Waiting On 3 件 ＝ 7。Someday・Done は数えない
    assert doc["unchecked_total"] == 7
    # ★マスター と、題に「マスターの裁定」がある項目は裁定待ちへ。残りは active／waiting へ
    engine_rulings = [r for r in doc["rulings_pending"] if r["lane"] == "engine"]
    assert [r["line"] for r in engine_rulings] == [8, 17]
    assert engine_rulings[0]["push"] == "今週中" and engine_rulings[1]["push"] == "揃える"
    assert [(a["line"], a["sub"]) for a in doc["active"]] == [(9, False), (11, True), (12, False)]
    assert [w["line"] for w in doc["waiting_on"]] == [16, 18]


def test_verbatim_without_markup(tmp_path):
    doc = eb.build(make_repo(tmp_path))
    r = [r for r in doc["rulings_pending"] if r["lane"] == "engine"][0]
    # 装飾（**・`）を落としただけで、文は元の行そのまま
    assert r["text"].startswith("★マスター: 再ビルドの確認（D-134） - 依頼は engine/REBUILD_REQUEST_20260925.md。")
    assert "**" not in r["text"] and "`" not in r["text"]
    assert r["url"].endswith("/TASKS.md#L8") and doc["commit"]["sha"] in r["url"]


def test_versions_and_sources(tmp_path):
    doc = eb.build(make_repo(tmp_path))
    v = doc["versions"]
    assert v["rules"] == "v0.19"
    assert v["encoding"] == "v6 (6, 1923, 317)"
    assert v["champion"] == "planner_vc4cps_kheb_b75"
    assert v["fingerprint"] == "f4b80b25c35cfa77"       # 旧値 e1662edb… を拾わない
    assert v["next_free_seed"] == 859000
    assert set(v["_source"]) == {"rules", "encoding", "champion", "fingerprint", "next_free_seed"}
    assert v["_source"]["fingerprint"].endswith("check_champion_fingerprint.py#L2")


def test_decisions_tail_and_next_d(tmp_path):
    doc = eb.build(make_repo(tmp_path))
    assert [d["id"] for d in doc["recent_decisions"]] == ["D-144", "D-001"]
    assert doc["recent_decisions"][0]["title"] == "段階3 反復 1 の選択の評価: V_1 − V_0 = −0.0035（2026-09-28）"
    assert doc["next_d"] == "D-145"


def test_report_excerpt_is_conclusion_paragraph(tmp_path):
    doc = eb.build(make_repo(tmp_path))
    rep = doc["recent_reports"]
    assert len(rep) == 1 and rep[0]["file"] == "engine/CC_STAGE3_IT1_S6_20260928.md"
    assert rep[0]["excerpt"].startswith("V_1 − V_0 = −0.0035 [−0.0215, +0.0138]（各 4,800 局）。")
    assert "止まる。" in rep[0]["excerpt"] and "回したもの" not in rep[0]["excerpt"]
    assert rep[0]["line"] == 7


def test_design_rulings_follow_the_ledger(tmp_path):
    # 台帳が「裁定待ち」と言う設計書だけ拾い、行に「裁定」の印がある項目は除く
    doc = eb.build(make_repo(tmp_path))
    design = [r for r in doc["rulings_pending"] if r["lane"] == "design"]
    assert [d["text"] for d in design] == ["データの経路"]
    assert design[0]["push"] == "推し: 定期実行のクロエが main を読んで db に書く".replace("推し: ", "")
    # 台帳が裁定待ちと言わなくなれば、設計書の中身が同じでも出さない
    tasks2 = TASKS.replace("— 裁定待ち", "— 裁定済み")
    doc2 = eb.build(make_repo(tmp_path / "b", tasks=tasks2))
    assert [r for r in doc2["rulings_pending"] if r["lane"] == "design"] == []


def test_json_roundtrip_and_schema(tmp_path):
    doc = eb.build(make_repo(tmp_path))
    s = json.dumps(doc, ensure_ascii=False)
    back = json.loads(s)
    for key in ("schema", "taken_at", "commit", "status", "error", "rulings_pending", "active",
                "waiting_on", "versions", "recent_reports", "recent_decisions", "next_d", "ci"):
        assert key in back, key
    assert back["ci"] == {"tests": "unknown", "wheel": "unknown", "checked_at": ""}


def test_ci_status_passed_in(tmp_path):
    doc = eb.build(make_repo(tmp_path), ci_tests="Success", ci_wheel="failure")
    assert doc["ci"]["tests"] == "passing" and doc["ci"]["wheel"] == "failing"
    assert doc["ci"]["checked_at"]
    assert eb.norm_ci("in progress") == "running" and eb.norm_ci("なにこれ") == "unknown"


# ---------------------------------------------------------------- 壊す側

def test_malformed_checkbox_fails_loudly(tmp_path):
    bad = TASKS.replace("- [ ] **`test_d065.py`", "-[ ] **`test_d065.py`")  # 空白が抜けた
    doc = eb.build(make_repo(tmp_path, tasks=bad))
    assert doc["status"] == "failed"
    assert "7 件のうち切り出せたのは 6 件" in doc["error"]


def test_missing_sections_fail(tmp_path):
    doc = eb.build(make_repo(tmp_path, tasks="# Tasks\n\n## Someday\n\n- [ ] x\n"))
    assert doc["status"] == "failed"
    assert "## Active" in doc["error"] and "## Waiting On" in doc["error"]


def test_no_decision_headings_fail(tmp_path):
    doc = eb.build(make_repo(tmp_path, decisions="# decisions\n\n本文だけ。\n"))
    assert doc["status"] == "failed"
    assert doc["next_d"] == "" and doc["recent_decisions"] == []
    assert "D-番号" in doc["error"]


def test_without_git_still_builds_but_fails(tmp_path):
    doc = eb.build(make_repo(tmp_path, git=False))
    assert doc["status"] == "failed" and "HEAD" in doc["error"]
    # commit が無くても URL は main で張る（前回の内容を消さないため文書は作る）
    assert doc["active"][0]["url"].startswith(eb.REPO_URL + "/blob/main/")


def test_plain_strips_only_markup():
    assert eb.plain("**太字** と ~~消し~~ と `code`。") == "太字 と 消し と code。"
    assert eb.clip("あいうえお", 5) == "あいうえお"
    assert eb.clip("あいうえおか", 5) == "あいうえ…"


# ---------------------------------------------------------------- 本物の写しがあれば

@pytest.mark.skipif(not os.environ.get("BOARD_REPO"), reason="BOARD_REPO（main の写し）が無い")
def test_real_main_snapshot():
    doc = eb.build(os.environ["BOARD_REPO"])
    assert doc["status"] == "ok", doc["error"]
    assert doc["versions"]["champion"] == "planner_vc4cps_kheb_b75"
    assert doc["next_d"].startswith("D-")
    assert doc["unchecked_total"] == (len([r for r in doc["rulings_pending"] if r["lane"] == "engine"])
                                      + len(doc["active"]) + len(doc["waiting_on"]))
