"""配布版（D-074・案 B: Windows 実行ファイル）の検査。

守るべきことは 3 つ。

1. **配布版に権利物を入れない**: `cards/` の画像・`cards_structured`（公式文の転記）・
   `results/human_games/`（マスターの棋譜）が組み立て結果に**構造的に**入らない。
   入れるものは allowlist で列挙し、それ以外は入らない。
2. **既定では一手も変わらない**: `dist.json` が無ければサーバの応答・記録の置き場・
   相手の一覧は従来どおり。配布モードは**マーカーがあるときだけ**効く。
3. **公式文の転記が紛れ込んだら落ちる**: 組み立て結果を走査し、公式カード文の印
   （`■【`）や転記ファイル名が 1 つでもあれば組み立てを失敗にする。

配布モードの中身は `webapp/distribution.py`、組み立ては `scripts/make_dist.py`。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest

from webapp import agents, distribution, images, server

ENGINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def no_dist(monkeypatch):
    """配布モードを確実に切る（作業環境に dist.json が置かれていても検査が揺れない）。"""
    monkeypatch.setattr(distribution, "_INFO", None)
    monkeypatch.setattr(distribution, "marker_path", lambda: os.path.join(ENGINE, "__no_such_dist.json"))
    yield
    monkeypatch.setattr(distribution, "_INFO", None)


@pytest.fixture
def dist_on(tmp_path, monkeypatch):
    """配布モードを入れる。マーカーは tmp に置き、記録の置き場も tmp にする。"""
    marker = tmp_path / "dist.json"
    marker.write_text(json.dumps({
        "name": "対決シミュレータ（非公式）",
        "notice": "非公式のファンツールです。",
        "opponents": [agents.DEFAULT_OPPONENT, "planner", "heuristic"],
        "labels": {agents.DEFAULT_OPPONENT: "最強 AI"},
        "version": "test",
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(distribution, "_INFO", None)
    monkeypatch.setattr(distribution, "marker_path", lambda: str(marker))
    yield str(marker)
    monkeypatch.setattr(distribution, "_INFO", None)


# --- 2. 既定では一手も変わらない ---------------------------------------------

def test_default_is_not_distribution_mode(no_dist):
    assert distribution.is_dist() is False
    assert distribution.info() is None
    # 記録の置き場は従来どおり engine/results
    assert os.path.normpath(distribution.results_dir()) == os.path.normpath(os.path.join(ENGINE, "results"))
    # 相手の一覧も従来どおり（allowlist は効かない）
    assert set(agents.available("SD001")) == {k for k, v in agents.OPPONENTS.items()
                                              if "decks" not in v or "SD001" in v["decks"]}


def test_config_has_no_dist_block_by_default(no_dist):
    cfg = server.config_payload(server.App("SD001"))
    assert "dist" not in cfg
    assert cfg["images"] == images.status()


# --- 配布モード ---------------------------------------------------------------

def test_distribution_mode_is_driven_by_the_marker(dist_on, tmp_path):
    assert distribution.is_dist() is True
    inf = distribution.info()
    assert inf["name"] == "対決シミュレータ（非公式）"
    # 記録はマーカーの隣の results/ に書く（実行ファイルの隣＝利用者が見つけられる場所）
    assert os.path.normpath(distribution.results_dir()) == os.path.normpath(str(tmp_path / "results"))


def test_distribution_mode_filters_opponents_by_allowlist(dist_on):
    champ = agents.DEFAULT_OPPONENT          # champion は替わるので名前を決め打ちしない
    assert set(agents.available("SD001")) == {champ, "planner", "heuristic"}
    # 表示名だけ差し替わり、中身（factory・kwargs）は元のまま
    av = agents.available("SD001")
    assert av[champ]["label"] == "最強 AI"
    assert av[champ]["kwargs"] == agents.OPPONENTS[champ]["kwargs"]
    assert av["planner"]["label"] == agents.OPPONENTS["planner"]["label"]
    assert agents.OPPONENTS[champ]["label"] != "最強 AI"     # 元の辞書は汚さない
    # 既定の相手は allowlist の中にあるので変わらない
    assert agents.default_for("SD001") == champ
    # SD02 では π 系が外れ、allowlist との積になる
    assert set(agents.available("SD02")) == {"planner", "heuristic"}


def test_distribution_mode_default_falls_back_inside_allowlist(tmp_path, monkeypatch):
    marker = tmp_path / "dist.json"
    marker.write_text(json.dumps({"name": "x", "opponents": ["heuristic"]}), encoding="utf-8")
    monkeypatch.setattr(distribution, "_INFO", None)
    monkeypatch.setattr(distribution, "marker_path", lambda: str(marker))
    try:
        assert agents.default_for("SD001") == "heuristic"
    finally:
        monkeypatch.setattr(distribution, "_INFO", None)


def test_config_carries_dist_block_and_marks_images_as_intentionally_absent(dist_on):
    cfg = server.config_payload(server.App("SD001"))
    assert cfg["dist"]["name"] == "対決シミュレータ（非公式）"
    assert cfg["dist"]["notice"] == "非公式のファンツールです。"
    # 画像が無いのは配布版の仕様。画面は警告ではなく説明を出す
    assert cfg["images"]["intentionally_absent"] is True


def test_records_go_next_to_the_marker_in_distribution_mode(dist_on, tmp_path, monkeypatch):
    """記録の置き場が配布モードで切り替わり、従来のフォルダには書かれない。"""
    from webapp import record
    app = server.App("SD001")
    s = app.new_game("heuristic")
    # 疑似人間で最後まで進める
    import random
    rng = random.Random(1)
    while not s.finished:
        acts = s.legal()
        s.play(rng.randrange(len(acts)), s.ply)
    out = app.finish()
    assert out["saved"].startswith(os.path.normpath(str(tmp_path / "results")))
    assert record.load_all(str(tmp_path / "results"))


# --- 1・3. 組み立て（allowlist と権利物の排除） -----------------------------------

def _fake_repo(root):
    """組み立ての検査用に、リポジトリの形をした偽物を作る。

    権利物（画像・転記・棋譜）をわざと置き、組み立て結果に**入らない**ことを確かめる。
    """
    eng = root / "engine"
    for d in ("meicho", "webapp/static", "experiments", "decklists", "results/models",
              "results/human_games", "tests", "scripts"):
        (eng / d).mkdir(parents=True, exist_ok=True)
    (eng / "meicho" / "__init__.py").write_text("", encoding="utf-8")
    (eng / "meicho" / "engine.py").write_text("# engine\n", encoding="utf-8")
    (eng / "webapp" / "__init__.py").write_text("", encoding="utf-8")
    (eng / "webapp" / "server.py").write_text("# server\n", encoding="utf-8")
    (eng / "webapp" / "static" / "index.html").write_text("<html></html>", encoding="utf-8")
    (eng / "experiments" / "registry.py").write_text("# registry\n", encoding="utf-8")
    (eng / "experiments" / "champion.py").write_text("# champion\n", encoding="utf-8")
    (eng / "experiments" / "arena.py").write_text("# arena\n", encoding="utf-8")
    (eng / "experiments" / "drl_train.py").write_text("# 学習側は配らない\n", encoding="utf-8")
    (eng / "decklists" / "SD001.json").write_text("{}", encoding="utf-8")
    (eng / "decklists" / "SD001.md").write_text("# 文書は配らない\n", encoding="utf-8")
    for m in ("drl_sd001_vb3.json", "drl_sd001_s1.json", "pi_small64_e10.json", "drl_sd001_vb2.json"):
        (eng / "results" / "models" / m).write_text("{}", encoding="utf-8")
    (eng / "results" / "human_games" / "2026-09.jsonl").write_text("{}\n", encoding="utf-8")
    (eng / "tests" / "test_x.py").write_text("", encoding="utf-8")
    (eng / "decisions.md").write_text("# 内部文書\n", encoding="utf-8")
    cards = root / "cards"
    cards.mkdir()
    (cards / "SD01-011_燃える烈火.png").write_bytes(b"\x89PNG fake")
    (cards / "cards_structured.csv").write_text("code,effect\nSD01-001,■【自分のターン開始時】カード1枚を引く。\n", encoding="utf-8")
    (cards / "cards_structured.json").write_text("[]", encoding="utf-8")
    return eng


def test_assemble_includes_only_the_allowlist(tmp_path):
    import make_dist
    eng = _fake_repo(tmp_path)
    out = tmp_path / "build"
    files = make_dist.assemble(str(eng), str(out), models=["drl_sd001_vb3.json", "drl_sd001_s1.json", "pi_small64_e10.json"],
                               dist_info={"name": "x", "notice": "y", "opponents": ["heuristic"]})
    rel = sorted(os.path.relpath(f, out).replace(os.sep, "/") for f in files)
    assert "engine/meicho/engine.py" in rel
    assert "engine/webapp/static/index.html" in rel
    assert "engine/experiments/registry.py" in rel
    assert "engine/results/models/drl_sd001_vb3.json" in rel
    assert "engine/decklists/SD001.json" in rel
    assert "dist.json" in rel and "run_app.py" in rel
    # 入ってはいけないもの
    for bad in ("engine/experiments/drl_train.py", "engine/decklists/SD001.md", "engine/decisions.md",
                "engine/results/models/drl_sd001_vb2.json", "engine/tests/test_x.py"):
        assert bad not in rel, bad
    assert not any("human_games" in r for r in rel)
    assert not any(r.startswith("cards/") or r.endswith((".png", ".jpg", ".jpeg", ".webp")) for r in rel)
    assert not any("cards_structured" in r for r in rel)


def test_verify_rejects_official_text_and_forbidden_files(tmp_path):
    import make_dist
    eng = _fake_repo(tmp_path)
    out = tmp_path / "build"
    make_dist.assemble(str(eng), str(out), models=["drl_sd001_vb3.json"], dist_info={"name": "x"})
    assert make_dist.verify(str(out)) == []
    # 公式文の転記が紛れ込んだら落ちる
    (out / "engine" / "meicho" / "leak.py").write_text('TEXT = "■【自分のターン開始時】カード1枚を引く。"\n', encoding="utf-8")
    problems = make_dist.verify(str(out))
    assert any("leak.py" in p for p in problems)
    os.remove(out / "engine" / "meicho" / "leak.py")
    # 画像・転記ファイル・棋譜が置かれても落ちる
    (out / "engine" / "x.png").write_bytes(b"\x89PNG")
    (out / "cards_structured.json").write_text("[]", encoding="utf-8")
    (out / "engine" / "results" / "human_games").mkdir(parents=True)
    (out / "engine" / "results" / "human_games" / "a.jsonl").write_text("{}", encoding="utf-8")
    problems = make_dist.verify(str(out))
    assert any("x.png" in p for p in problems)
    assert any("cards_structured" in p for p in problems)
    assert any("human_games" in p for p in problems)


def test_real_tree_assembles_and_passes_verify(tmp_path):
    """本物のリポジトリで組み立て、権利物が入らず、検査も通ること。"""
    import make_dist
    out = tmp_path / "build"
    make_dist.assemble(ENGINE, str(out), models=make_dist.champion_models(),
                       dist_info=make_dist.default_dist_info())
    assert make_dist.verify(str(out)) == []
    # champion が読むモデルはすべて入っている
    for m in make_dist.champion_models():
        assert (out / "engine" / "results" / "models" / m).is_file(), m


def test_champion_models_follow_champion_py():
    """配るモデルは champion.py の定義から引く（手で列挙しない・D-058 の一元化）。"""
    import make_dist
    from champion import CHAMPIONS
    kw = CHAMPIONS["SD001"]
    for key in ("value_net", "opp_policy_net", "policy_net"):
        assert kw[key] in make_dist.champion_models()
