#!/bin/bash
# 腕 A（A-1・D-166）の評価。主比較（AI_A 対 AI_0＋null・16 × 75）→ 錨（素 planner 1,600・H 400・貪欲 400）。
# 1 回 8 分以内・回ごとに push（[skip ci]）。途中で止まっても同じコマンドで続きから
set -e
S=/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad
cd /home/user/meicho_engine/engine
export PYTHONPATH=$PWD MEICHO_HOST=cc-cloud-4
V0=results/models/s2v_id_ens3.json; VA="$V0+pi=results/models/s5piA_s0.json"
H2H=results/drl/wall_a1_h2h.json
push() { cd /home/user/meicho_engine; git add engine/results/drl/wall_a1_* 2>/dev/null || true
  git commit -q -m "[skip ci] 腕 A（A-1）の評価: 途中経過（$1）

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NjB1DJb2rDTbqAuJT5UA3y" || true
  for i in 1 2 3 4; do git push -q origin claude/charming-mendel-yzlmua && break || sleep $((2**i)); done; cd engine; }
complete() { python3 - "$@" <<'PY'
import json,sys,os
p,n,pref=sys.argv[1],int(sys.argv[2]),sys.argv[3:]
if not os.path.exists(p): sys.exit(1)
d=json.load(open(p))
for a in pref:
    ks=[k for k in d['results'] if k.startswith(a+'|')]
    if len(ks)!=16 or any(len(d['results'][k])<n for k in ks): sys.exit(1)
PY
}
for r in $(seq 1 80); do
  complete $H2H 75 ch null && break
  [ -f ../AGENT_STOP ] && { echo AGENT_STOP; exit 0; }
  echo "== h2h $r $(date -u +%H:%M:%S)"
  python3 experiments/eval_s3_h2h.py run --pair "ch=$VA:$V0" --pair null=$V0:$V0 --n 75 --seed0 936500 --out $H2H --workers 4 --budget-sec 480 >> $S/s4/wa/a1_eval.log 2>&1
  push "主比較・回 $r"
done
for spec in "planner 100 936600" "heuristic 25 936700" "greedy 25 936800"; do
  set -- $spec; O=results/drl/wall_a1_anchor_$1.json
  for r in $(seq 1 80); do
    complete $O $2 vA v0 && break
    [ -f ../AGENT_STOP ] && { echo AGENT_STOP; exit 0; }
    echo "== anchor $1 $r $(date -u +%H:%M:%S)"
    python3 experiments/eval_s2_repr.py run --opponent $1 --arm "vA=$VA" --arm v0=$V0 --n $2 --seed0 $3 --out $O --workers 4 --budget-sec 480 >> $S/s4/wa/a1_eval.log 2>&1
    push "錨 $1・回 $r"
  done
done
echo "== eval done $(date -u +%H:%M:%S)"
