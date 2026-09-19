#!/bin/bash
# S1 取素材:探测、抽音频、1fps 抽帧 + 拼图、镜头切点。只用 ffmpeg。
# 用法: prep.sh <ref_video.mp4> <work_dir> [scene_threshold]
set -euo pipefail
SRC="$1"
WORK="$2"
TH="${3:-0.3}"
mkdir -p "$WORK/frames"

ffprobe -v error -show_entries format=duration:stream=codec_type,width,height,r_frame_rate \
    -of json "$SRC" > "$WORK/probe.json"

ffmpeg -v error -y -i "$SRC" -vn -ac 1 -ar 16000 "$WORK/audio.wav"
ffmpeg -v error -y -i "$SRC" -vf fps=1 "$WORK/frames/%03d.jpg"
ffmpeg -v error -y -i "$SRC" -vf "fps=1,scale=360:-1,tile=6x3" -frames:v 1 "$WORK/contact.jpg"

# 切点:scene 分数 > 阈值的帧时间
ffmpeg -hide_banner -i "$SRC" -vf "select='gt(scene,$TH)',metadata=print" -an -f null - 2>&1 \
    | awk -F'pts_time:' '/pts_time/{split($2,a," "); t=a[1]} /lavfi.scene_score/{split($0,b,"="); printf "{\"t\": %.3f, \"score\": %.3f}\n", t, b[2]}' \
    | python3 -c 'import sys,json; json.dump([json.loads(l) for l in sys.stdin], open(sys.argv[1],"w"), indent=1)' "$WORK/cuts.json"

echo "cuts: $(cat "$WORK/cuts.json" | tr -d '\n ')"
