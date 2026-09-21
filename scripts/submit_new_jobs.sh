#!/bin/bash
# Stage 7 for chill_noodle_sfs_en and rice_sfs_en: upload the sealed assets and
# submit both as one H3 job each. Run from the repo root after preflight passes.
#
#   bash scripts/submit_new_jobs.sh
#
# Uploads come from work/<job>/upload_map.json, which is generated alongside
# segments.server.json so the local path -> server path mapping is auditable.

set -eu
HOST=h3-5090
REMOTE=/opt/MINIMAXH3_2PASS_Autoworkflow
PY=/root/miniconda3/envs/h3director/bin/python
SEED=20260921

push () {            # $1 = work dir, $2 = server job dir
  local base=$1 srv=$2
  echo "== $base -> $srv"
  ssh -o BatchMode=yes "$HOST" "mkdir -p $srv/keyframes $srv/inputs $srv/scene_pack $srv/prompts"
  D:/anaconda/envs/ugc_asr/python.exe -B -c "
import json,io,subprocess,sys
m=json.load(io.open(r'$base/upload_map.json',encoding='utf-8'))
for local,remote in m.items():
    subprocess.run(['scp','-o','BatchMode=yes',local,'$HOST:'+remote],check=True)
print(len(m),'files uploaded')
"
  scp -o BatchMode=yes "$base/segments.server.json" "$HOST:$srv/prompts/segments.json"
}

push work/chill_noodle_shot_for_shot /opt/ugc_clone/jobs/chill_noodle_sfs
push work/rice_shot_for_shot         /opt/ugc_clone/jobs/rice_sfs

echo
echo "== submitting chill_noodle =="
ssh -o BatchMode=yes "$HOST" "cd $REMOTE && $PY scripts/cc_submit.py \
  --job-id chill-noodle-sfs-en \
  --segments-file /opt/ugc_clone/jobs/chill_noodle_sfs/prompts/segments.json \
  --profile ref2va_4step --orientation portrait --seed $SEED"

echo
echo "== submitting rice =="
ssh -o BatchMode=yes "$HOST" "cd $REMOTE && $PY scripts/cc_submit.py \
  --job-id rice-sfs-en \
  --segments-file /opt/ugc_clone/jobs/rice_sfs/prompts/segments.json \
  --profile ref2va_4step --orientation portrait --seed $SEED"
