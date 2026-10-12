#!/bin/bash
# 全体の --run-slow をファイルごとに別のプロセスで（容器の回収に強いように・済んだファイルは飛ばす）
cd /home/user/meicho_engine/engine
OUT=/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/slow_cdff8d3
for f in tests/test_*.py; do
  n=$(basename $f .py)
  [ -f $OUT/$n.xml ] && continue
  PYTHONPATH=$PWD timeout 3000 python3 -m pytest $f -q -rfs --run-slow --junitxml=$OUT/$n.xml.tmp > $OUT/$n.log 2>&1
  mv $OUT/$n.xml.tmp $OUT/$n.xml 2>/dev/null
done
echo SLOWDONE
