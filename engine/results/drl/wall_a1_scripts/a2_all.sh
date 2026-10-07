#!/bin/bash
# 腕 A（A-2・D-166）: AI_A を教師に 528 局（16 塊）を記録 → 教師の門 u_A。足し継ぎ: manifest のある塊は飛ばす
S=/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad
E=/home/user/meicho_engine/engine; R=$E/results/drl/wall_a2; W=$S/a2rec
cd $E; mkdir -p $W
export PYTHONPATH=$PWD MEICHO_HOST=cc-cloud-4
push() { cd /home/user/meicho_engine; git add engine/results/drl/wall_a2 engine/results/drl/wall_a2_gate.json 2>/dev/null
  git commit -q -m "[skip ci] 腕 A（A-2）: $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y" || true
  for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done; cd $E; }
for k in $(seq 0 15); do
  [ -e /home/user/meicho_engine/AGENT_STOP ] && exit 0
  K=$(printf "%03d" $k)
  [ -f $R/a2.c$K.manifest.json ] && continue
  rm -f $W/a2.c$K.*
  T0=$(date +%s)
  python3 experiments/record_mix.py --schedule results/drl/wall_a2/wall_a2_schedule.p${k}of16.json --out $W/a2.c$K --workers 4 > $S/s4/wa/a2_rec.c$K.log 2>&1 || { echo "FAIL c$K"; exit 1; }
  for f in $W/a2.c$K.b*; do xz -k -T2 -c $f > $R/$(basename $f).xz; done
  cp $W/a2.c$K.manifest.json $R/
  echo "c$K $(( $(date +%s) - T0 ))s"
  push "記録 塊 $K"
done
FILES=$(python3 -c "print(','.join(f'$W/a2.c{k:03d}' for k in range(16)))")
python3 experiments/diag_s3_desk.py --a2 $FILES --a2-man "$R/a2.c*.manifest.json" --work $S/rec_raw --out results/drl/wall_a2_gate.json
push "教師の門 u_A"
echo ALLDONE
