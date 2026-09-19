#!/bin/bash
# Claude Code 端:等 Codex 写出 work/<job>/keyframes/READY.json。出现后打印内容并退出,
# 用 Bash 后台任务跑,退出时会唤醒 Claude 接手。
# 用法: wait_handoff.sh <job> [最长等待小时数=12]
JOB="$1"; HOURS="${2:-12}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
F="$ROOT/work/$JOB/keyframes/READY.json"
END=$(( $(date +%s) + HOURS * 3600 ))
while [ "$(date +%s)" -lt "$END" ]; do
  if [ -s "$F" ]; then
    sleep 3   # 等写完
    echo "READY $(date +%T) $F"
    cat "$F"
    ls -la "$(dirname "$F")"
    exit 0
  fi
  sleep 20
done
echo "TIMEOUT waiting for $F"
exit 1
