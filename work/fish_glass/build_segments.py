"""Deterministically compile the approved fish_glass Picture/time plan."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ugc_pipeline.h3_plan import load_h3_clip_plan  # noqa: E402
from ugc_pipeline.h3_segments import compile_h3_segments  # noqa: E402
from ugc_pipeline.io import load_json, resolve_repo_path  # noqa: E402


job = load_json(ROOT / "inputs/fish_glass/job.en.json")
shot_plan = load_json(resolve_repo_path(ROOT, job["shot_plan"]))
request_path = resolve_repo_path(ROOT, job["keyframe_request"])
request = load_json(request_path)
ready = load_json(request_path.parent / "READY.json")
h3_clip_plan = load_h3_clip_plan(ROOT, job, request)
segments = compile_h3_segments(
    ROOT,
    job,
    shot_plan,
    request,
    request_path,
    ready,
    h3_clip_plan,
)

output = Path(__file__).parent / "segments.json"
output.write_text(json.dumps(segments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({
    "output": output.as_posix(),
    "h3_clips": len(segments),
    "approved_keyframes": sum(len(clip["keyframe_ids"]) for clip in h3_clip_plan["clips"]),
    "total_edit_duration_seconds": h3_clip_plan["total_edit_duration_seconds"],
}, indent=2))
