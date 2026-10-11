#!/bin/bash
/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wc/c1_train.sh >> /tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wc/c1_train.out 2>&1 || exit 1
grep -q "train done" /tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wc/c1_train.out || exit 1
/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wc/c1_eval.sh >> /tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wc/c1_eval.out 2>&1 || exit 1
grep -q "eval done" /tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wc/c1_eval.out || exit 1
/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wc/c1_retest.sh >> /tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wc/c1_retest.out 2>&1
