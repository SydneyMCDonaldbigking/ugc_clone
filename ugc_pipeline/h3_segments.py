from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import load_json, repo_relative, resolve_repo_path


def _time(value: float) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _product_reference(request: dict[str, Any], keyframe_ids: list[str]) -> str:
    paths: list[str] = []
    for keyframe_id in keyframe_ids:
        segment = request["segments"][keyframe_id]
        roles = segment.get("reference_roles", {})
        paths.extend(path for path, role in roles.items() if role == "product_identity")
    unique = list(dict.fromkeys(paths))
    if len(unique) != 1:
        raise ValueError(f"H3 clip keyframes must share one product identity reference, got {unique}")
    return unique[0]


def _keyframe_paths(
    repo_root: Path,
    request: dict[str, Any],
    request_path: Path,
    keyframe_ids: list[str],
    ready: dict[str, Any] | None,
) -> list[str]:
    paths: list[str] = []
    for keyframe_id in keyframe_ids:
        if ready is None:
            filename = request["segments"][keyframe_id]["output"]
        else:
            completed = ready.get("segments", {}).get(keyframe_id)
            if not isinstance(completed, dict):
                raise ValueError(f"READY.json is missing keyframe {keyframe_id}")
            filename = completed.get("keyframe")
            if not isinstance(filename, str):
                raise ValueError(f"READY keyframe {keyframe_id} has no filename")
        paths.append(repo_relative(repo_root, request_path.parent / filename))
    return paths


def render_prompt(
    segment: dict[str, Any],
    keyframe_ids: list[str],
    product_picture_number: int | None,
) -> str:
    picture_by_keyframe = {
        keyframe_id: index for index, keyframe_id in enumerate(keyframe_ids, start=1)
    }
    subject_lines = [
        f"<Picture {index}> is a generated target-product composition keyframe for the timed montage."
        for index in range(1, len(keyframe_ids) + 1)
    ]
    if product_picture_number is not None:
        subject_lines.append(
            f"<Picture {product_picture_number}> is the original product identity authority for package, shape, colour and branding."
        )

    retention_lines = [
        f"<Picture {index}>: composition_reference. Use its hands-only framing, scale, camera angle, setting and product placement for the microshots assigned to it."
        for index in range(1, len(keyframe_ids) + 1)
    ]
    if product_picture_number is not None:
        retention_lines.append(
            f"<Picture {product_picture_number}>: attribute_transfer. Preserve the original product identity throughout every cut."
        )

    timeline: list[str] = []
    for timed_index, timed in enumerate(segment["timed_shots"]):
        if isinstance(timed.get("picture"), int):
            picture_number = int(timed["picture"])
        else:
            picture_number = picture_by_keyframe[str(timed["picture_keyframe_id"])]
        transition = "start on" if timed_index == 0 else "hard cut to a new shot based on"
        start = timed.get("start_seconds", timed.get("clip_start_seconds"))
        end = timed.get("end_seconds", timed.get("clip_end_seconds"))
        shot_type = timed.get("shot_type", "scheduled microshot")
        direction = timed.get("direction", timed.get("action", ""))
        timeline.append(
            f"{_time(start)}-{_time(end)} seconds — "
            f"{transition} <Picture {picture_number}>; {shot_type}: {direction}"
        )
    source_edit_duration = float(segment["source_edit_duration_seconds"])
    render_duration = float(segment["duration_seconds"])
    if render_duration - source_edit_duration > 0.001:
        timeline.append(
            f"{_time(source_edit_duration)}-{_time(render_duration)} seconds — hold the final composition steady as disposable trim padding."
        )

    return (
        "subject_definitions:\n"
        + "\n".join(subject_lines)
        + "\n\nretention_analysis:\n"
        + "\n".join(retention_lines)
        + "\n\ndetailed_description:\n"
        + str(segment["action"])
        + " Preserve the exact listed order and timing. Hard cuts occur only at the listed times. "
          "Each cut is an intentional jump to a distinct camera setup, not a morph or continuous camera move.\n\n"
        + "timed_shot_timeline:\n"
        + "\n".join(timeline)
        + "\n\nperformance_and_camera:\n"
        + str(segment["performance"])
        + " "
        + str(segment["intention"])
        + "\n\nsoundscape: no generated audio; the final English voice-over, handling sounds and music are added after exact trimming."
        + "\n\nOnly hands and forearms appear. Keep the original target product identity stable across every hard cut. "
          "Do not add subtitles, captions, watermarks, price badges or extra brands. Packaging text comes only from the product reference."
    )


def compile_h3_segments(
    repo_root: Path,
    job: dict[str, Any],
    shot_plan: dict[str, Any],
    request: dict[str, Any],
    request_path: Path,
    ready: dict[str, Any] | None,
    h3_clip_plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if job.get("visual_mode") != "shot_for_shot":
        raise ValueError("timed H3 compilation requires visual_mode=shot_for_shot")
    if job.get("render_plan", {}).get("h3_audio_mode") != "silent":
        raise ValueError("exact-timing H3 clips must render silent; add the approved master voice-over after trimming")
    if h3_clip_plan is None:
        raise ValueError("shot_for_shot compilation requires a validated h3_clip_plan")

    plan_segments = [segment for segment in shot_plan.get("segments", []) if isinstance(segment, dict)]
    segment_by_id = {str(segment["id"]): segment for segment in plan_segments}
    normalized_segments: list[dict[str, Any]] = []
    for clip in h3_clip_plan.get("clips", []):
        base = segment_by_id.get(str(clip.get("id")))
        if base is None:
            raise ValueError(f"H3 clip {clip.get('id')} has no matching shot-plan segment")
        normalized_segments.append({
            **base,
            "duration_seconds": clip["duration_seconds"],
            "source_edit_duration_seconds": clip["trim_duration_seconds"],
            "keyframe_ids": clip["keyframe_ids"],
            "timed_shots": clip.get("timed_shots", []),
        })

    compiled: list[dict[str, Any]] = []
    for segment in normalized_segments:
        keyframe_ids = [str(value) for value in segment["keyframe_ids"]]
        keyframe_paths = _keyframe_paths(repo_root, request, request_path, keyframe_ids, ready)
        product_reference = _product_reference(request, keyframe_ids) if len(keyframe_ids) < 3 else None
        images = [*keyframe_paths, *([product_reference] if product_reference else [])]
        if not 2 <= len(images) <= 3:
            raise ValueError(f"segment {segment['segment']} must have 2-3 total H3 references")
        prompt = render_prompt(segment, keyframe_ids, len(images) if product_reference else None)
        compiled.append({
            "id": segment["id"],
            "duration": segment["duration_seconds"],
            "source_start_seconds": segment["source_start_seconds"],
            "source_end_seconds": segment["source_end_seconds"],
            "trim_to_seconds": segment["source_edit_duration_seconds"],
            "prompt": prompt,
            "images": images,
        })
    return compiled


def _first_difference(actual: Any, expected: Any, path: str = "segments") -> str | None:
    if type(actual) is not type(expected):
        return f"{path} has type {type(actual).__name__}; expected {type(expected).__name__}"
    if isinstance(actual, dict):
        if list(actual) != list(expected):
            return f"{path} keys differ; expected {list(expected)}"
        for key in expected:
            difference = _first_difference(actual[key], expected[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path} has {len(actual)} items; expected {len(expected)}"
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            difference = _first_difference(actual_item, expected_item, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if actual != expected:
        return f"{path} differs from the deterministic compiler output"
    return None


def validate_h3_segments(
    segments: Any,
    repo_root: Path,
    job: dict[str, Any],
    shot_plan: dict[str, Any],
    request: dict[str, Any],
    request_path: Path,
    ready: dict[str, Any],
    h3_clip_plan: dict[str, Any],
) -> None:
    expected = compile_h3_segments(
        repo_root, job, shot_plan, request, request_path, ready, h3_clip_plan
    )
    difference = _first_difference(segments, expected)
    if difference:
        raise ValueError(f"h3_segments do not match approved inputs: {difference}")
    for segment in expected:
        for raw_path in segment["images"]:
            resolve_repo_path(repo_root, raw_path)


def load_h3_segments(
    repo_root: Path,
    job: dict[str, Any],
    shot_plan: dict[str, Any],
    request: dict[str, Any],
    request_path: Path,
    ready: dict[str, Any],
    h3_clip_plan: dict[str, Any],
) -> list[dict[str, Any]] | None:
    raw_path = job.get("h3_segments")
    if not isinstance(raw_path, str):
        return None
    segments = load_json(resolve_repo_path(repo_root, raw_path))
    validate_h3_segments(
        segments, repo_root, job, shot_plan, request, request_path, ready, h3_clip_plan
    )
    return segments
