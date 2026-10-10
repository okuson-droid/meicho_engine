#!/bin/bash
while pgrep -f "wb/b1_train.sh" >/dev/null; do sleep 30; done
/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wb/b1_train.sh >> /tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wb/b1_train.out 2>&1
/tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wb/b1_eval.sh >> /tmp/claude-0/-home-user-meicho-engine/5a1cecc8-5654-5b64-aefb-2e111d273f31/scratchpad/s4/wb/b1_eval.out 2>&1
