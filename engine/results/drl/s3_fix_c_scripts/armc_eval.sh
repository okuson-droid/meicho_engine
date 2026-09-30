#!/bin/bash
# 腕 (c) の強さの評価（設計書 §4.3・k = 1）。1 回 10 分以内・回ごとに push。
# 1 段目: vc だけ 150 局／2 段目: 300 局に足し継ぎ・V_1 と V_0 は s3_it1_select.json から取り込む
set -e
S=/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad
cd /home/user/meicho_engine/engine
export PYTHONPATH=$PWD MEICHO_HOST=cc-cloud-4
OUT=results/drl/s3_fix_c_select.json
done_n() { python3 - "$1" <<'PY'
import json,sys,os
p='results/drl/s3_fix_c_select.json'
if not os.path.exists(p): sys.exit(1)
d=json.load(open(p)); n=int(sys.argv[1])
ks=[k for k in d['results'] if k.startswith('vc|')]
sys.exit(0 if len(ks)==16 and all(len(d['results'][k])>=n for k in ks) else 1)
PY
}
push() { cd /home/user/meicho_engine; git add engine/$OUT; git commit -q -m "腕 (c) の評価: 途中経過（$1）

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y" || true
  for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done; cd engine; }
for r in $(seq 1 40); do
  done_n 150 && break
  [ -f ../AGENT_STOP ] && { echo AGENT_STOP; exit 0; }
  echo "== 150 run $r $(date -u +%H:%M:%S)"
  python3 experiments/eval_s2_repr.py run --arm vc=results/models/s3vc_id_ens3.json --n 150 --seed0 841000 --out $OUT --workers 4 --budget-sec 300 >> $S/armc_eval.log 2>&1
  push "150 局・回 $r"
done
for r in $(seq 1 40); do
  done_n 300 && python3 -c "import json,sys;d=json.load(open('$OUT'));sys.exit(0 if 'v_ens3' in d['arms'] and 'v1' in d['arms'] else 1)" && break
  [ -f ../AGENT_STOP ] && { echo AGENT_STOP; exit 0; }
  echo "== 300 run $r $(date -u +%H:%M:%S)"
  python3 experiments/eval_s2_repr.py run --arm vc=results/models/s3vc_id_ens3.json --arm v1=results/models/s3v1_id_ens3.json --arm v_ens3=results/models/s2v_id_ens3.json --n 300 --seed0 841000 --import results/drl/s3_it1_select.json:v1 --import results/drl/s3_it1_select.json:v_ens3 --out $OUT --workers 4 --budget-sec 300 >> $S/armc_eval.log 2>&1
  push "300 局・回 $r"
done
python3 experiments/eval_s2_repr.py report --in $OUT --new vc --old v_ens3 --also vc:v1 --level 0.95 > $S/armc_report.txt 2>&1
cd /home/user/meicho_engine; git add engine/results/drl/s3_fix_c_select_report.json; git commit -q -m "腕 (c) の評価: 集計

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y"; for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done
echo "== eval done $(date -u +%H:%M:%S)"
