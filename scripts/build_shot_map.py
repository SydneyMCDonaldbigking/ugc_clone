"""Build an exact source-shot timeline for shot-for-shot visual remixes.

The source frames remain local analysis evidence.  This script records only
timestamps, transcript overlap and render/trim instructions; none of the
source-derived images are generation references.

Example:
    python scripts/build_shot_map.py references/crown_almond_bis \
        work/crown_almond_bis_shot_for_shot/shot_map.json \
        --storyboard work/crown_almond_bis_shot_for_shot/source_shots.jpg
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import media  # noqa: E402


def _round(value: float) -> float:
    return round(float(value), 3)


def _source_text(words: list[dict[str, Any]], start: float, end: float) -> str:
    selected = [
        str(word.get("word", ""))
        for word in words
        if float(word.get("end", 0)) > start and float(word.get("start", 0)) < end
    ]
    return "".join(selected).strip()


def build_shot_map(
    *,
    reference_video: str,
    duration_seconds: float,
    cuts: list[dict[str, Any]],
    words: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one analysis row for every source interval, without compression."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    cut_times = sorted(
        {
            _round(float(cut["t"]))
            for cut in cuts
            if 0 < float(cut.get("t", 0)) < duration_seconds
        }
    )
    boundaries = [0.0, *cut_times, _round(duration_seconds)]
    transcript_words = words or []
    shots: list[dict[str, Any]] = []

    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
        source_duration = _round(end - start)
        if source_duration <= 0:
            raise ValueError(f"non-positive shot interval at {start}-{end}")
        shots.append(
            {
                "id": f"SH{index:03d}",
                "source_start_seconds": _round(start),
                "source_end_seconds": _round(end),
                "source_edit_duration_seconds": source_duration,
                "analysis_frame_time_seconds": _round(start + source_duration / 2),
                "source_dialogue": _source_text(transcript_words, start, end),
                "cut_in": "start" if index == 1 else "hard_cut",
                "cut_out": "end" if index == len(boundaries) - 1 else "hard_cut",
            }
        )

    return {
        "schema": "shot-map/v1",
        "visual_mode": "shot_for_shot",
        "reference_video": Path(reference_video).as_posix(),
        "source_duration_seconds": _round(duration_seconds),
        "cut_times_seconds": cut_times,
        "shots": shots,
    }


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Reference archive containing probe.json and cuts.json")
    parser.add_argument("output", type=Path, help="Destination shot_map.json")
    parser.add_argument(
        "--reference-video",
        help="Repository-relative original video path recorded in the job (defaults to archive/source.mp4)",
    )
    parser.add_argument("--storyboard", type=Path, help="Optional local-only midpoint contact sheet")
    args = parser.parse_args()

    archive = args.archive.resolve()
    probe = json.loads((archive / "probe.json").read_text(encoding="utf-8"))
    cuts = json.loads((archive / "cuts.json").read_text(encoding="utf-8"))
    transcript = archive / "transcript.json"
    words = media.load_words(str(transcript)) if transcript.is_file() else []
    video = archive / "source.mp4"
    if not video.is_file():
        raise SystemExit(f"Missing reference video: {video}")

    document = build_shot_map(
        reference_video=args.reference_video or _repo_relative(video),
        duration_seconds=float(probe["duration"]),
        cuts=cuts,
        words=words,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.storyboard:
        times = [shot["analysis_frame_time_seconds"] for shot in document["shots"]]
        args.storyboard.parent.mkdir(parents=True, exist_ok=True)
        media.build_grid(str(video), times, 240, 4, words or None, args.storyboard)

    print(
        json.dumps(
            {
                "shot_map": _repo_relative(args.output),
                "shots": len(document["shots"]),
                "source_duration_seconds": document["source_duration_seconds"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
