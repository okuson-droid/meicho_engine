"""起動用の bat（`start_local.bat`・`start_friends.bat`・APP-031）の静的な検査。

作業環境（Linux）では cmd を動かせないので、Windows の cmd で転びやすいところと、公開のリポジトリに置いてよいかを見る。
実際にダブルクリックで立つことは、マスターの PC で確かめる。
"""
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
BATS = ["start_local.bat", "start_friends.bat"]


@pytest.mark.parametrize("name", BATS)
def test_bat_is_crlf_utf8_and_switches_the_console_to_utf8(name):
    raw = (APP / name).read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n") > 0            # LF だけだと cmd が行を読み違えることがある
    lines = raw.decode("utf-8").split("\r\n")
    assert lines[0] == "@echo off" and lines[1] == "chcp 65001 >nul"   # 日本語の表示は chcp のあと


@pytest.mark.parametrize("name", BATS)
def test_bat_blocks_do_not_close_early(name):
    """`( ... )` のブロックの中の echo に半角の `)` があると、そこでブロックが閉じてしまう。"""
    depth = 0
    for n, line in enumerate((APP / name).read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if s.lower().startswith("rem "):
            continue
        if depth and s.lower().startswith("echo") and ")" in s.replace("^)", ""):
            pytest.fail(f"{name}:{n} ブロックの中の echo に半角の ) がある: {s}")
        if s.endswith("("):
            depth += 1
        elif s == ")":
            depth -= 1
    assert depth == 0


@pytest.mark.parametrize("name", BATS)
def test_bat_starts_the_app_from_its_own_folder_and_keeps_secrets_out(name):
    text = (APP / name).read_text(encoding="utf-8")
    assert 'cd /d "%~dp0.."' in text and "-m app.server" in text     # 置き場所に依らない（作業ツリーの経路を書かない）
    assert "C:\\Users" not in text and "OneDrive" not in text          # 本名を含む経路を書かない（CLAUDE.md §4）
    assert not re.search(r"https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net", text)   # 固定の URL を書かない（PC に覚える）


def test_only_the_friends_bat_opens_to_the_outside():
    local = (APP / "start_local.bat").read_text(encoding="utf-8")
    friends = (APP / "start_friends.bat").read_text(encoding="utf-8")
    assert "--allow-origin" not in local and "--host" not in local    # 手元起動: CPU 対戦と記録が出る形（APP-012）
    assert "--allow-origin %URL%" in friends and "tailscale funnel --https=443 127.0.0.1:8765" in friends
    commands = [x for x in friends.splitlines() if not x.strip().lower().startswith(("rem ", "echo"))]
    assert not any("--bg" in x for x in commands)                     # 遊び終わったら窓を閉じて止める（APP-020）


def test_bats_are_not_shipped_in_the_release():
    from app.release import publish
    assert not any(pat.endswith(".bat") or pat == "app/*" for pat in publish.APP_ALLOW)
