#!/bin/bash
# 保底插入镜头:商品原图做慢推,标签字 100% 清晰。H3 画不好密集小字时用。
# 用法: packshot_clip.sh <image> <out.mp4> [秒数=5.2] [推向的纵向位置 0-1=0.62]
set -euo pipefail
IMG="$1"; OUT="$2"; DUR="${3:-5.2}"; FOCUS_Y="${4:-0.62}"
FRAMES=$(python3 -c "print(round($DUR*24))")
VF="scale=1440:2560:force_original_aspect_ratio=decrease,pad=1440:2560:(ow-iw)/2:(oh-ih)/2:color=white,scale=2880:5120"
VF="$VF,zoompan=z='min(1+0.0018*on,1.22)':x='iw/2-(iw/zoom/2)':y='ih*${FOCUS_Y}-(ih/zoom/2)':d=${FRAMES}:s=1440x2560:fps=24"
ffmpeg -v error -y -loop 1 -i "$IMG" -vf "$VF" -frames:v "$FRAMES" -c:v libx264 -pix_fmt yuv420p -crf 16 "$OUT"
ffprobe -v error -show_entries stream=width,height,r_frame_rate:format=duration -of compact "$OUT"
