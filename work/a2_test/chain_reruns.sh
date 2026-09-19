#!/bin/bash
# a2_test 串联重跑:002(第3/4段)完成 → 003(第2段改词) → 004(第3段只绑背面图)
set -u
cd /opt/MINIMAXH3_2PASS_Autoworkflow
PY=/home/node/anaconda3/envs/h3director/bin/python
P=/opt/ugc_clone/jobs/a2_test/prompts
wait_job() { $PY scripts/cc_status.py --job-id "$1" --wait --timeout 4000 | grep -m1 '"status"'; }
echo "$(date +%T) wait 002"; wait_job a2-replica-002
echo "$(date +%T) submit 003"
$PY scripts/cc_rerun.py --source-job-id a2-replica-002 --job-id a2-replica-003 --segment 2 --prompt-file $P/seg2_v2_prompt.txt
wait_job a2-replica-003
echo "$(date +%T) submit 004"
$PY scripts/cc_rerun.py --source-job-id a2-replica-003 --job-id a2-replica-004 --segment 3 --prompt-file $P/seg3_v3_prompt.txt --reference /opt/ugc_clone/jobs/a2_test/inputs/target_A2_2.png
wait_job a2-replica-004
$PY scripts/cc_status.py --job-id a2-replica-004 --deliver > /dev/null
echo "$(date +%T) all done"
