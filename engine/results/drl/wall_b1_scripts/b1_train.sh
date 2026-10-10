#!/bin/bash
# 腕 B（D-163 §3.1・B-1）: V_1（s3v1_id_s*）と同じ引数から --vtarget next_turn --next-net s2v_id_ens3 だけ変える。1 本ごとに push
set -e
S=/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad
D=$S/rec_raw
cd /home/user/meicho_engine/engine
export PYTHONPATH=$PWD MEICHO_HOST=cc-cloud-4
TR=$(python3 -c "print(','.join(f'$D/train.c{k:03d}' for k in range(141)))")
VA=$(python3 -c "print(','.join(f'$D/val.c{k:03d}' for k in range(16)))")
for K in 0 1 2; do
  N=s5vB_id_s$K
  [ -f results/models/$N.meta.json ] && continue
  [ -f ../AGENT_STOP ] && { echo AGENT_STOP; exit 0; }
  echo "== $N $(date -u +%H:%M:%S)"
  python3 experiments/drl_train.py --train $TR --valid $VA --out results/models/$N.json \
    --init results/models/s2v_id_s$K.json --epochs 6 --hidden 256 --depth 2 --phead 128 --lr 1e-3 --bs 1024 \
    --seed $K --lam 0.7 --vtarget next_turn --next-net results/models/s2v_id_ens3.json \
    --calib-scale bulk --select best_v --threads 4 > $S/$N.log 2>&1
  cp $S/$N.log results/models/$N.log
  cd /home/user/meicho_engine
  git add engine/results/models/$N.json engine/results/models/$N.meta.json engine/results/models/$N.log
  git commit -q -m "[skip ci] 腕 B（B-1）の学び直し: $N

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y"
  for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done
  cd engine
done
echo "== train done $(date -u +%H:%M:%S)"
