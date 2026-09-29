@echo off
chcp 65001 >nul
rem MeichoSim（非公式）を知人と遊ぶ形で起動する（APP-031・APP-020）。Tailscale Funnel の固定の URL から入れる。
rem Funnel は別の窓で立てる。遊び終わったら、この窓で Ctrl+C を押し、Funnel の窓も閉じる（--bg は使わない）。
rem 固定の URL はリポジトリに書かない（公開のため）。最初の 1 回だけ尋ね、%USERPROFILE%\.meichosim\funnel_url.txt に覚える。
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%"

rem --- 使う Python を決める（aiohttp が入っているもの）。py -3.11 → py -3 → python の順に試す
set "PY="
py -3.11 -c "import aiohttp" >nul 2>nul && set "PY=py -3.11"
if not defined PY py -3 -c "import aiohttp" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import aiohttp" >nul 2>nul && set "PY=python"
if not defined PY (
  echo.
  echo [止まった] aiohttp の入った Python が見つからない。
  echo engine フォルダで次を 1 回打ってから、もう一度この bat を開いてほしい:
  echo     py -3.11 -m pip install -r app\requirements.txt
  echo.
  pause
  exit /b 1
)

where tailscale >nul 2>nul
if errorlevel 1 (
  echo.
  echo [止まった] tailscale が見つからない。Tailscale を入れてログインしてから、もう一度開いてほしい。
  pause
  exit /b 1
)
set "CONF=%USERPROFILE%\.meichosim\funnel_url.txt"
set "URL="
if exist "%CONF%" set /p URL=<"%CONF%"
if not defined URL (
  echo 固定の URL がまだ覚えられていない。
  echo tailscale funnel status で出る https://^<マシン名^>.^<tailnet名^>.ts.net の形を、そのまま入れてほしい（最後の / は無し）。
  set /p "URL=URL: "
)
if not defined URL (
  echo URL が空だったので止めた。
  pause
  exit /b 1
)
set "BAD="
if /i not "%URL:~0,8%"=="https://" set "BAD=1"
if /i not "%URL:~-7%"==".ts.net" set "BAD=1"
if defined BAD (
  echo [止まった] URL の形が違う: %URL%
  echo https://^<マシン名^>.^<tailnet名^>.ts.net の形で入れてほしい。覚えた URL を消すには次のファイルを消す:
  echo     %CONF%
  pause
  exit /b 1
)
if not exist "%USERPROFILE%\.meichosim" mkdir "%USERPROFILE%\.meichosim"
if not exist "%CONF%" (echo %URL%)>"%CONF%"
set "DATA=%LOCALAPPDATA%\MeichoSim\data"
echo MeichoSim を起動する（知人と遊ぶ形）。URL: %URL%
echo 知人にもこの URL から招待リンクを渡す。CPU 対戦はこの形では出ない。止めるときは Ctrl+C。
start "MeichoSim Funnel（遊び終わったら閉じる）" tailscale funnel --https=443 127.0.0.1:8765
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process '%URL%/'"
%PY% -m app.server --data "%DATA%" --allow-origin %URL%
echo.
echo サーバが止まった。Funnel の窓も閉じてほしい。上にエラーがあれば、窓の中身をクロエに見せてほしい。
pause
