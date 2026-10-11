#!/bin/bash
# 腕 A（D-163 §2.2 A-0）: 反復 1 の教材から小さい π（幹 64・π 頭 32）を、探索の点数が最大の手を答えに学ぶ
set -e
S=/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad
D=$S/rec_raw
cd /home/user/meicho_engine/engine
export PYTHONPATH=$PWD MEICHO_HOST=cc-cloud-4
N=s5piA_s0
[ -f results/models/$N.meta.json ] && exit 0
[ -f ../AGENT_STOP ] && { echo AGENT_STOP; exit 0; }
TR=$(python3 -c "print(','.join(f'$D/train.c{k:03d}' for k in range(141)))")
VA=$(python3 -c "print(','.join(f'$D/val.c{k:03d}' for k in range(16)))")
echo "== $N $(date -u +%H:%M:%S)"
python3 experiments/drl_train.py --train $TR --valid $VA --out results/models/$N.json \
  --epochs 10 --hidden 64 --depth 2 --phead 32 --lr 1e-3 --bs 1024 --seed 0 --wv 0 --lam 0 \
  --policy-target argmax --select best_p --threads 4 > $S/$N.log 2>&1
cp $S/$N.log results/models/$N.log
cd /home/user/meicho_engine
git add engine/results/models/$N.json engine/results/models/$N.meta.json engine/results/models/$N.log
git commit -q -m "[skip ci] 腕 A（A-0）の小さい π: $N

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y"
for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done
