"""Compile time-coded multi-reference prompts for shot-for-shot H3 clips."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ugc_pipeline.h3_plan import load_h3_clip_plan  # noqa: E402
from ugc_pipeline.h3_segments import compile_h3_segments, render_prompt  # noqa: E402
from ugc_pipeline.io import load_json, resolve_repo_path  # noqa: E402


def compile_segments(
    job: dict[str, Any],
    shot_plan: dict[str, Any],
    request: dict[str, Any],
    request_path: Path,
    ready: dict[str, Any] | None,
    h3_clip_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Compatibility wrapper used by tests and older local callers."""
    return compile_h3_segments(
        REPO_ROOT, job, shot_plan, request, request_path, ready, h3_clip_plan
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--planned", action="store_true", help="Use requested output paths before READY.json exists.")
    parser.add_argument("--output", type=Path, help="Defaults to segments.planned.json or segments.json beside state.en.json.")
    args = parser.parse_args()

    job_path = resolve_repo_path(REPO_ROOT, args.job.as_posix())
    job = load_json(job_path)
    shot_plan = load_json(resolve_repo_path(REPO_ROOT, job["shot_plan"]))
    request_path = resolve_repo_path(REPO_ROOT, job["keyframe_request"])
    request = load_json(request_path)
    ready = None
    if not args.planned:
        ready_path = request_path.parent / "READY.json"
        if not ready_path.is_file():
            raise SystemExit(f"Missing {ready_path}; use --planned only for pre-keyframe inspection.")
        ready = load_json(ready_path)

    h3_clip_plan = load_h3_clip_plan(REPO_ROOT, job, request)
    compiled = compile_segments(job, shot_plan, request, request_path, ready, h3_clip_plan)
    default_name = "segments.planned.json" if args.planned else "segments.json"
    output = args.output or resolve_repo_path(REPO_ROOT, job["state_file"], must_exist=False).parent / default_name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(compiled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for segment, compiled_segment in zip(shot_plan["segments"], compiled):
        prompt_path = resolve_repo_path(REPO_ROOT, segment["h3_prompt_file"], must_exist=False)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(compiled_segment["prompt"] + "\n", encoding="utf-8")
    print(json.dumps({"output": output.as_posix(), "h3_clips": len(compiled)}, indent=2))


if __name__ == "__main__":
    main()
