#!/bin/bash
# One command for the live checks in Colab (avoids quoting mistakes when typing into a cell):
#   !bash scripts/run_live.sh 4        -> voice round trip + full 36-ticket eval, log in eval/run4.log
#   !bash scripts/run_live.sh 4 voice  -> voice round trip only
cd "$(dirname "$0")/.." || exit 1
RUN="${1:-4}"
echo "== voice round trip"
python -u scripts/test_voice.py 2>&1 | grep -v -i "key=" | grep -E "^\[|said|heard"
[ "$2" = "voice" ] && exit 0
echo "== full eval (run $RUN), log: eval/run$RUN.log"
python -u eval/run_eval.py > "eval/run$RUN.log" 2>&1
grep -v -i "key=" "eval/run$RUN.log" | grep -E "^\||correct=False|Meko call|run tag"
