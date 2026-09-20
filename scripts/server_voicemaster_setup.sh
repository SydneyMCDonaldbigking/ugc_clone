#!/bin/bash
# Lift the per-segment duration cap for voice-master jobs, then bring the render
# services back up. Safe to run more than once.
#
#   scp scripts/server_voicemaster_setup.sh h3-5090:/tmp/
#   ssh h3-5090 "bash /tmp/server_voicemaster_setup.sh"
#
# Default behaviour is unchanged: the cap stays 15 s unless a process sets
# H3_MAX_SEGMENT_SECONDS. Only the worker started here gets the raised value.
# Roll back with:
#   cp src/workflow.py.bak-voicemaster src/workflow.py
#   cp src/rerun.py.bak-voicemaster    src/rerun.py

set -u
ROOT=/opt/MINIMAXH3_2PASS_Autoworkflow
CONDA=/root/miniconda3/bin/conda
MAX_SECONDS=${H3_MAX_SEGMENT_SECONDS:-22}

cd "$ROOT" || { echo "FATAL: $ROOT not found"; exit 1; }

echo "== backing up =="
cp -n src/workflow.py src/workflow.py.bak-voicemaster 2>/dev/null
cp -n src/rerun.py    src/rerun.py.bak-voicemaster    2>/dev/null
ls -la src/*.bak-voicemaster

echo
echo "== patching the duration cap =="
python3 - <<'PY'
import io, re

for path in ("src/workflow.py", "src/rerun.py"):
    s = io.open(path, encoding="utf-8").read()
    if "H3_MAX_SEGMENT_SECONDS" in s:
        print(path, "- already patched, skipped")
        continue
    m = re.search(r"([ \t]*)if not 2 <= duration <= 15:", s)
    if not m:
        print(path, "- PATTERN NOT FOUND, skipped")
        continue
    ind = m.group(1)
    s = s[:m.start()] + (
        ind + '_max = float(__import__("os").environ.get("H3_MAX_SEGMENT_SECONDS", "15"))\n'
        + ind + "if not 2 <= duration <= _max:"
    ) + s[m.end():]
    # the error text hard-codes 15; make it report the value actually in force
    s = s.replace("2-15 秒", "2-{_max:g} 秒")
    io.open(path, "w", encoding="utf-8").write(s)
    print(path, "- patched")
PY

echo
echo "== restarting the worker with the raised cap =="
for sig in TERM KILL; do
  pids=$(ps aux | grep "[s]rc.worker" | awk '{print $2}')
  [ -n "$pids" ] && kill -$sig $pids 2>/dev/null
  sleep 3
done

H3_MAX_SEGMENT_SECONDS="$MAX_SECONDS" setsid nohup "$CONDA" run --no-capture-output \
  -n h3director python -m src.worker > /tmp/worker.log 2>&1 < /dev/null &
sleep 8

echo
echo "== starting ComfyUI if it is down =="
if curl -s -o /dev/null --max-time 5 http://127.0.0.1:8188/; then
  echo "ComfyUI already up"
else
  cd /opt/ComfyUI
  setsid nohup "$CONDA" run --no-capture-output -n h3director \
    python main.py --listen 127.0.0.1 --port 8188 > /tmp/comfy.log 2>&1 < /dev/null &
  echo "ComfyUI starting, waiting up to 90 s..."
  for i in $(seq 1 18); do
    sleep 5
    curl -s -o /dev/null --max-time 5 http://127.0.0.1:8188/ && break
  done
  cd "$ROOT"
fi

echo
echo "== status =="
echo "worker pid : $(ps aux | grep '[s]rc.worker' | awk '{print $2}' | head -1)"
echo "cap in use : $MAX_SECONDS s"
echo -n "comfy http : "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://127.0.0.1:8188/
echo "ffmpeg     : $("$CONDA" run -n h3director which ffmpeg 2>/dev/null | tail -1)"
grep -n "H3_MAX_SEGMENT_SECONDS" src/workflow.py src/rerun.py
