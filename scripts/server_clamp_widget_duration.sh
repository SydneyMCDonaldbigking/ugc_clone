#!/bin/bash
# ComfyUI validates the H3DirectorStudio "时长秒" widget against its schema max of
# 15.0, and src/workflow.py feeds it the first segment's duration. A 19 s segment
# is therefore rejected before it ever reaches the model.
#
# The node's own comment says 时长秒 is only the per-segment default and every
# segment carries an explicit duration, so clamping the widget to 15 leaves the
# real durations untouched. Jobs of 15 s or less are completely unaffected.
#
#   scp scripts/server_clamp_widget_duration.sh h3-5090:/tmp/
#   ssh h3-5090 "bash /tmp/server_clamp_widget_duration.sh"
#
# Roll back: cp src/workflow.py.bak-voicemaster src/workflow.py  (then restart worker)

set -u
ROOT=/opt/MINIMAXH3_2PASS_Autoworkflow
CONDA=/root/miniconda3/bin/conda
MAX_SECONDS=${H3_MAX_SEGMENT_SECONDS:-22}

cd "$ROOT" || { echo "FATAL: $ROOT not found"; exit 1; }

echo "== patching the widget default =="
python3 - <<'PY'
import io
path = "src/workflow.py"
s = io.open(path, encoding="utf-8").read()
old = '"时长秒": float(segments[0]["duration"])'
new = '"时长秒": min(float(segments[0]["duration"]), 15.0)'
if new in s:
    print(path, "- already clamped, skipped")
elif old in s:
    io.open(path, "w", encoding="utf-8").write(s.replace(old, new))
    print(path, "- clamped to 15.0")
else:
    print(path, "- PATTERN NOT FOUND, skipped")
PY

echo
echo "== restarting the worker =="
for sig in TERM KILL; do
  pids=$(ps aux | grep "[s]rc.worker" | awk '{print $2}')
  [ -n "$pids" ] && kill -$sig $pids 2>/dev/null
  sleep 3
done
H3_MAX_SEGMENT_SECONDS="$MAX_SECONDS" setsid nohup "$CONDA" run --no-capture-output \
  -n h3director python -m src.worker > /tmp/worker.log 2>&1 < /dev/null &
sleep 8

echo
echo "worker pid : $(ps aux | grep '[s]rc.worker' | awk '{print $2}' | head -1)"
echo "cap in use : $MAX_SECONDS s"
grep -n '时长秒' src/workflow.py
