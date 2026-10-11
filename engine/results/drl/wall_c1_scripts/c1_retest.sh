#!/bin/bash
# 腕 C（C-1）の評価（D-163 §5.1・§5.2）。束ねて → 主比較（16 × 75＋null）→ 錨（素 planner 1,600・H 400・貪欲 400）。
# 1 回 8 分以内・回ごとに push（[skip ci]）。途中で止まっても同じコマンドで続きから
set -e
S=/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad
cd /home/user/meicho_engine/engine
export PYTHONPATH=$PWD MEICHO_HOST=cc-cloud-4
VB=results/models/s5vC_id_ens3.json; V0=results/models/s2v_id_ens3.json
H2H=results/drl/wall_c1_retest_h2h.json
push() { cd /home/user/meicho_engine; git add engine/results/drl/wall_c1_* engine/results/models/s5vC_id_ens3.meta.json 2>/dev/null || true
  git commit -q -m "[skip ci] 腕 C（C-1）の評価: 途中経過（$1）

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
for K in 0 1 2; do [ -f results/models/s5vC_id_s$K.meta.json ] || { echo "学習が済んでいない s$K"; exit 1; }; done
if [ ! -f $VB ]; then
  python3 experiments/ensemble_net.py --out $VB results/models/s5vC_id_s0.json results/models/s5vC_id_s1.json results/models/s5vC_id_s2.json
  sha256sum $VB | cut -c1-16
  push "束ね"
fi
for r in $(seq 1 60); do
  complete $H2H 150 ch null && break
  [ -f ../AGENT_STOP ] && { echo AGENT_STOP; exit 0; }
  echo "== h2h $r $(date -u +%H:%M:%S)"
  python3 experiments/eval_s3_h2h.py run --pair ch=$VB:$V0 --pair null=$V0:$V0 --n 150 --seed0 939500 --out $H2H --workers 4 --budget-sec 480 >> $S/s4/wc/c1_eval.log 2>&1
  push "追試・回 $r"
done
echo "== retest done $(date -u +%H:%M:%S)"
