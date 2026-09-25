"""版の定数と、対人検証アプリの記録の思考時間（D-117・送り箱 TE-3／TE-4）。

TE-3: `webapp/record.py` に `RULES_VERSION = "v0.10"` が直書きされ、rules が v0.18 まで上がるあいだ
取り残されていた。版は `meicho/version.py` の 1 か所で持ち、`rules_draft.md` の見出しと食い違えば
ここが落ちる。

TE-4: 記録の `ms` は「前のステップが終わってから」の時間なので、人間の入力を待つステップでは
AI の行にも人間の操作時間が混ざる。AI の行には `think_ms`（`ai.act` の中だけ）を足す。`ms` は変えない。
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from arena import load_deck, mirror_config          # noqa: E402
from meicho import version                          # noqa: E402
from meicho.state import Phase                      # noqa: E402
from webapp import agents, record                   # noqa: E402
from webapp.session import Session                  # noqa: E402

_RULES = os.path.join(os.path.dirname(__file__), "..", "rules_draft.md")

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
POOL = DECK["action_deck"]
SEED0 = 130000        # test_webapp.py と同じ登録済みの帯（アプリの検査用）


def _session(seed=SEED0, opponent="heuristic"):
    ai_seed = seed * 2 + 1
    return Session(f"v{seed}", CONFIG, POOL, seed, 0, opponent,
                   agents.build(opponent, POOL, ai_seed), ai_seed)


# --- TE-3 ------------------------------------------------------------------

def test_rules_version_constant_matches_rules_draft_heading():
    """番人: rules の版を上げたら `meicho/version.py` も上げる。忘れるとここが落ちる。"""
    with open(_RULES, encoding="utf-8") as f:
        m = re.search(r"v\d+\.\d+", f.readline())
    assert m, "rules_draft.md の 1 行目に版が無い"
    assert version.RULES_VERSION == m.group(0)


_ROOT = os.path.join(os.path.dirname(__file__), "..")
# `rules_version` / `RULES_VERSION` / `"rules":` に版の文字列を直に書いている行
_LITERAL = re.compile(r"""(RULES_VERSION\s*=\s*|["']rules(?:_version)?["']\s*:\s*)["']v\d+\.\d+["']""")


def test_no_rules_version_is_written_by_hand_anywhere_else():
    """番人: 版の直書きは `meicho/version.py` だけ。

    TE-3 を調べたら同じ取り残しが 5 か所あった（`webapp/record.py` "v0.10"・`experiments/provenance.py` "v0.11"・
    `experiments/ladder.py`・`gendata.py`・`train_linear.py` の "v0.10"）。名前ではなく書き方で探す。
    """
    hits = []
    for sub in ("meicho", "webapp", "experiments", "scripts"):
        for dirpath, dirs, files in os.walk(os.path.join(_ROOT, sub)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                if os.path.normpath(path) == os.path.normpath(os.path.join(_ROOT, "meicho", "version.py")):
                    continue
                with open(path, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if _LITERAL.search(line):
                            hits.append(f"{os.path.relpath(path, _ROOT)}:{i}: {line.strip()}")
    assert not hits, "rules の版を直書きしている行がある（meicho/version.py から import する）:\n" + "\n".join(hits)


def test_record_takes_the_versions_from_the_one_place():
    assert record.RULES_VERSION is version.RULES_VERSION
    assert record.ENGINE_VERSION is version.ENGINE_VERSION
    s = _session()
    rec = record.to_record(s)
    assert rec["rules_version"] == version.RULES_VERSION
    assert rec["app_version"] == "2"       # 3 以上は新アプリが使う（R-DATA-6）ので上げない


# --- TE-4 ------------------------------------------------------------------

def test_ai_rows_carry_think_ms_and_human_rows_do_not():
    import random
    s = _session()
    rng = random.Random(3)
    for _ in range(400):
        if s.finished:
            break
        acts = s.legal()
        s.play(rng.randrange(len(acts)), s.ply)
    ai_rows = [r for r in s.actions if r["by"] == "ai"]
    hu_rows = [r for r in s.actions if r["by"] == "human"]
    assert ai_rows and hu_rows
    assert all(isinstance(r["think_ms"], int) and r["think_ms"] >= 0 for r in ai_rows)
    assert all("think_ms" not in r for r in hu_rows)
    # 足したのはキー 1 つだけ。再生は `action` しか読まないので、記録はそのまま照合できる
    if s.finished:
        record.verify(record.to_record(s), CONFIG)


def test_think_ms_excludes_the_time_the_human_spent():
    """人間が 0.65 秒考えた対抗で、AI の行の `ms` は 0.6 秒以上・`think_ms` はそれより十分小さい。"""
    import random
    s = _session()
    rng = random.Random(5)
    for _ in range(2000):
        assert not s.finished, "対抗に届かないまま終わった"
        if s.state.phase == Phase.CLASH_SUBMIT:
            break
        acts = s.legal()
        s.play(rng.randrange(len(acts)), s.ply)
    n_before = len(s.actions)
    # 人間が考えている時間。0.6 秒ではなく 0.65 秒寝る——Windows の `time.monotonic` は刻みが約 16 ms なので、
    # 0.6 秒寝ても 592 ms と測れることがある（2026-09-22 に PC で実際に落ちた・D-123 追記 1）。
    time.sleep(0.65)
    s.play(0, s.ply)
    rows = [r for r in s.actions[n_before:] if r["by"] == "ai" and r["phase"] == "clash_submit"]
    assert rows, "対抗で AI の行が書かれていない"
    r = rows[0]
    assert r["ms"] >= 600                             # `ms` の意味は変えていない（人間の時間が混ざる）
    assert r["think_ms"] < 300                        # heuristic の思考は数ミリ秒。人間の 0.6 秒は入らない
