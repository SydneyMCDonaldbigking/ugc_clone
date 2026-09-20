"""Compare rendered H3 hard cuts with the exact Hypit source-shot rhythm.

Example after fetching four rendered clips:
    python scripts/check_shot_rhythm.py inputs/demo/job.shot-for-shot.en.json \
        --clip S01=output/seg01.mp4 --clip S02=output/seg02.mp4 \
        --clip S03=output/seg03.mp4 --clip S04=output/seg04.mp4 \
        --report work/demo/RHYTHM_QC.json

The report is a technical gate, not a visual-quality verdict.  It checks that
every planned internal hard cut appears near its Hypit-derived timestamp and
that the detector finds no unplanned hard cuts.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.analyze_reference_video import detect_cuts, probe_video  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_clip_assignment(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ValueError(f"Expected SEGMENT=VIDEO, got {raw!r}")
    segment_id, video = raw.split("=", 1)
    if not segment_id or not video:
        raise ValueError(f"Expected SEGMENT=VIDEO, got {raw!r}")
    return segment_id, Path(video).resolve()


def expected_cut_times(segment: dict[str, Any]) -> list[float]:
    shots = [shot for shot in segment.get("timed_shots", []) if isinstance(shot, dict)]
    return [round(float(shot["clip_start_seconds"]), 3) for shot in shots[1:]]


def match_cut_times(
    expected: list[float],
    detected: list[float],
    tolerance: float,
) -> dict[str, Any]:
    """Match cuts one-to-one in order, preferring the nearest in-tolerance cut."""

    available = set(range(len(detected)))
    matches: list[dict[str, float]] = []
    missed: list[float] = []
    for wanted in expected:
        candidates = [
            index for index in available
            if abs(float(detected[index]) - float(wanted)) <= tolerance
        ]
        if not candidates:
            missed.append(round(float(wanted), 3))
            continue
        best = min(candidates, key=lambda index: abs(float(detected[index]) - float(wanted)))
        available.remove(best)
        actual = float(detected[best])
        matches.append({
            "expected_seconds": round(float(wanted), 3),
            "detected_seconds": round(actual, 3),
            "delta_seconds": round(actual - float(wanted), 3),
        })
    extras = [round(float(detected[index]), 3) for index in sorted(available)]
    return {"matches": matches, "missed": missed, "extra": extras}


def check_clip(
    segment: dict[str, Any],
    video: Path,
    *,
    ffmpeg: str,
    ffprobe: str,
    threshold: float,
    tolerance: float,
    max_extra: int,
) -> dict[str, Any]:
    expected = expected_cut_times(segment)
    detected_rows = detect_cuts(ffmpeg, video, threshold)
    detected = [float(row["time_seconds"]) for row in detected_rows]
    matched = match_cut_times(expected, detected, tolerance)
    info = probe_video(ffprobe, video)
    render_duration = float(segment["duration_seconds"])
    duration_delta = round(float(info["duration_seconds"]) - render_duration, 3)
    duration_ok = abs(duration_delta) <= max(0.08, 1 / max(float(info.get("fps") or 30), 1) * 2)
    status = "pass" if not matched["missed"] and len(matched["extra"]) <= max_extra and duration_ok else "fail"
    return {
        "segment": segment["id"],
        "video": video.as_posix(),
        "status": status,
        "scene_threshold": threshold,
        "tolerance_seconds": tolerance,
        "expected_cut_times_seconds": expected,
        "detected_cut_times_seconds": [round(value, 3) for value in detected],
        **matched,
        "expected_render_duration_seconds": render_duration,
        "actual_render_duration_seconds": info["duration_seconds"],
        "duration_delta_seconds": duration_delta,
        "duration_ok": duration_ok,
        "trim_to_seconds": segment["source_edit_duration_seconds"],
    }


def build_report(
    shot_plan: dict[str, Any],
    clips: dict[str, Path],
    *,
    ffmpeg: str,
    ffprobe: str,
    threshold: float,
    tolerance: float,
    max_extra: int,
) -> dict[str, Any]:
    segments = [segment for segment in shot_plan.get("segments", []) if isinstance(segment, dict)]
    expected_ids = [str(segment["id"]) for segment in segments]
    if list(clips) != expected_ids:
        raise ValueError(f"clip order {list(clips)} must exactly equal {expected_ids}")
    results = [
        check_clip(
            segment,
            clips[str(segment["id"])],
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            threshold=threshold,
            tolerance=tolerance,
            max_extra=max_extra,
        )
        for segment in segments
    ]
    return {
        "schema": "shot-rhythm-qc/v1",
        "visual_mode": "shot_for_shot",
        "status": "pass" if all(result["status"] == "pass" for result in results) else "fail",
        "detector": "ffmpeg_scene",
        "scene_threshold": threshold,
        "tolerance_seconds": tolerance,
        "max_unplanned_cuts_per_clip": max_extra,
        "clips": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--clip", action="append", required=True, help="Repeat in shot-plan order: S01=path/to/video.mp4")
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--tolerance", type=float, default=0.13)
    parser.add_argument("--max-extra", type=int, default=0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if not 0 < args.threshold <= 1:
        raise SystemExit("--threshold must be within (0, 1]")
    if not 0 <= args.tolerance <= 0.5:
        raise SystemExit("--tolerance must be within [0, 0.5]")
    if args.max_extra < 0:
        raise SystemExit("--max-extra must be non-negative")

    job_path = args.job if args.job.is_absolute() else REPO_ROOT / args.job
    job = _load(job_path.resolve())
    if job.get("visual_mode") != "shot_for_shot":
        raise SystemExit("Rhythm QC requires visual_mode=shot_for_shot.")
    shot_plan = _load((REPO_ROOT / job["shot_plan"]).resolve())
    clips = dict(parse_clip_assignment(raw) for raw in args.clip)
    for segment_id, video in clips.items():
        if not video.is_file():
            raise SystemExit(f"Missing rendered clip for {segment_id}: {video}")

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SystemExit("ffmpeg and ffprobe are required")
    report = build_report(
        shot_plan,
        clips,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        threshold=args.threshold,
        tolerance=args.tolerance,
        max_extra=args.max_extra,
    )
    if args.report:
        report_path = args.report if args.report.is_absolute() else REPO_ROOT / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
