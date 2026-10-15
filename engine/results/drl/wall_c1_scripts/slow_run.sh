#!/bin/bash
# 使い方: slow_run.sh <出力先>。全体の --run-slow をファイルごとに別のプロセスで（容器の回収に強いように・済んだファイルは飛ばす）
cd /home/user/meicho_engine/engine
OUT=${1:?出力先のフォルダを渡す（例: scratchpad/slow_<HEAD>）}; mkdir -p $OUT
for f in tests/test_*.py; do
  n=$(basename $f .py)
  [ -f $OUT/$n.xml ] && continue
  PYTHONPATH=$PWD timeout 3000 python3 -m pytest $f -q -rfs --run-slow --junitxml=$OUT/$n.xml.tmp > $OUT/$n.log 2>&1
  mv $OUT/$n.xml.tmp $OUT/$n.xml 2>/dev/null
done
echo SLOWDONE
