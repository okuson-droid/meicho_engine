@echo off
chcp 65001 >nul
rem MeichoSim（非公式）を手元で起動する（APP-031）。この PC の中からだけ届く形で立てるので、CPU 対戦と「記録を見る」が使える。
rem ダブルクリックで起動し、少し待つとブラウザで開く。止めるときはこの窓で Ctrl+C（「バッチ ジョブを終了しますか」には Y）。
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

set "DATA=%LOCALAPPDATA%\MeichoSim\data"
echo MeichoSim を起動する（手元）。保存先: %DATA%
echo ブラウザが開かなければ http://127.0.0.1:8765/ を開く。止めるときは Ctrl+C。
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8765/'"
%PY% -m app.server --data "%DATA%"
echo.
echo サーバが止まった。上に赤い字やエラーがあれば、窓の中身をクロエに見せてほしい。
pause
