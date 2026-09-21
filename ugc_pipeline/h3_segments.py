from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import load_json, repo_relative, resolve_repo_path


def _time(value: float) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _scene_lock_text(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    labels = (
        ("setting", "setting"),
        ("surface", "surface"),
        ("backdrop", "backdrop"),
        ("lighting", "lighting"),
        ("palette", "palette"),
        ("fixed_props", "fixed props"),
    )
    if not all(isinstance(value.get(key), str) and value[key].strip() for key, _ in labels):
        return None
    hard = f"surface: {value['surface'].strip()}"
    soft = "; ".join(
        f"{label}: {value[key].strip()}" for key, label in labels if key != "surface"
    )
    return hard, soft


def _product_reference(request: dict[str, Any], keyframe_ids: list[str]) -> str | None:
    paths: list[str] = []
    for keyframe_id in keyframe_ids:
        segment = request["segments"][keyframe_id]
        roles = segment.get("reference_roles", {})
        paths.extend(path for path, role in roles.items() if role == "product_identity")
    unique = list(dict.fromkeys(paths))
    if len(unique) > 1:
        raise ValueError(f"H3 clip keyframes must share one product identity reference, got {unique}")
    return unique[0] if unique else None


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
    scene_picture_number: int | None,
    product_presence_by_keyframe: dict[str, str],
) -> str:
    scene_id = segment.get("scene_id")
    if not isinstance(scene_id, str) or not scene_id.strip():
        raise ValueError(f"{segment.get('id', 'H3 segment')} needs a scene_id")
    scene_lock = _scene_lock_text(segment.get("scene_lock"))
    picture_by_keyframe = {
        keyframe_id: index for index, keyframe_id in enumerate(keyframe_ids, start=1)
    }
    has_product_absent_keyframe = any(
        product_presence_by_keyframe.get(keyframe_id, "present") != "present"
        for keyframe_id in keyframe_ids
    )
    subject_lines = []
    for index, keyframe_id in enumerate(keyframe_ids, start=1):
        if not has_product_absent_keyframe:
            subject_lines.append(
                f"<Picture {index}> is a generated target-product composition keyframe for the timed montage."
            )
        elif product_presence_by_keyframe.get(keyframe_id, "present") == "present":
            subject_lines.append(
                f"<Picture {index}> is a generated product-present composition keyframe for its assigned source shots."
            )
        else:
            subject_lines.append(
                f"<Picture {index}> is a generated food-and-hands composition keyframe with no retail package in its assigned source shots."
            )
    if product_picture_number is not None:
        subject_lines.append(
            f"<Picture {product_picture_number}> is the original product identity authority for package, shape, colour and branding."
        )
    if scene_picture_number is not None:
        subject_lines.append(
            f"<Picture {scene_picture_number}> is the approved empty scene identity authority for the same physical table, light and prop family; it is not a scheduled shot."
        )

    placement_term = "subject placement" if has_product_absent_keyframe else "product placement"
    retention_lines = [
        f"<Picture {index}>: composition_reference. Use its hands-only framing, scale, camera angle, setting and {placement_term} for the microshots assigned to it."
        for index in range(1, len(keyframe_ids) + 1)
    ]
    if product_picture_number is not None:
        retention_lines.append(
            f"<Picture {product_picture_number}>: attribute_transfer. Preserve the original product identity throughout every cut."
        )
    if scene_picture_number is not None:
        retention_lines.append(
            f"<Picture {scene_picture_number}>: scene_identity only. Preserve its table and atmosphere without turning the empty master into an extra shot."
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

    product_windows = [
        timed for timed in segment["timed_shots"]
        if product_presence_by_keyframe.get(
            str(timed.get("picture_keyframe_id", keyframe_ids[int(timed.get("picture", 1)) - 1])),
            "present",
        ) == "present"
    ]
    if product_windows:
        windows = ", ".join(
            f"{_time(timed.get('start_seconds', timed.get('clip_start_seconds')))}-{_time(timed.get('end_seconds', timed.get('clip_end_seconds')))} seconds"
            for timed in product_windows
        )
        product_timing = (
            f"The retail package appears only in the scheduled product window(s): {windows}. "
            "All other windows contain only their assigned food, hands, cookware and scene."
        )
    else:
        product_timing = "The complete clip contains only the scheduled food, hands, cookware and scene; no retail package appears."

    product_timing_block = (
        "\n\nproduct_timing:\n" + product_timing
        if has_product_absent_keyframe
        else ""
    )
    final_identity_rule = (
        "When the package is scheduled, keep the original target product identity stable."
        if has_product_absent_keyframe
        else "Keep the original target product identity stable across every hard cut."
    )

    return (
        "subject_definitions:\n"
        + "\n".join(subject_lines)
        + "\n\nretention_analysis:\n"
        + "\n".join(retention_lines)
        + "\n\nscene_continuity:\n"
        + (
            f"All generated Pictures share scene_id {scene_id}. Hard-lock the same physical tabletop across every cut ({scene_lock[0]}). "
            f"Treat the remaining scene description as a soft guide ({scene_lock[1]}). Close-ups keep the product sharp while crop, lens distance, parallax, visible props, slight local exposure and shallow-depth background bokeh may vary."
            if scene_lock
            else f"All generated Pictures share scene_id {scene_id}. Preserve one compatible tabletop material, principal setting and lighting period across every cut."
        )
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
        + product_timing_block
        + "\n\nsoundscape: no generated audio; the final English voice-over, handling sounds and music are added after exact trimming."
        + "\n\nOnly hands and forearms appear. "
        + final_identity_rule
        + " "
          "Do not add subtitles, captions, watermarks, price badges or extra brands. Packaging text comes only from the product reference."
    )


def render_grouped_prompt(
    clip: dict[str, Any],
    product_picture_number: int | None,
) -> str:
    """Compile an explicit Picture/time plan while keeping one scene anchor."""
    scene = str(clip["scene_id"]).replace("-", " ")
    subject_lines = [f"The complete clip uses one locked scene anchor: {scene}."]
    retention_lines: list[str] = []
    for cue in clip["cues"]:
        picture = int(cue["picture"])
        subject_lines.append(
            f"<Picture {picture}> is the composition authority for "
            f"{_time(cue['start_seconds'])}-{_time(cue['end_seconds'])} seconds: {cue['action']}"
        )
        retention_lines.append(
            f"<Picture {picture}>: fully_preserved only during its assigned time window; preserve its "
            "camera angle, framing, glass proportions, fish pattern, hands, props, scene surface and light."
        )
    if product_picture_number is not None:
        subject_lines.append(
            f"<Picture {product_picture_number}> is the product identity authority for the target glass throughout the clip."
        )
        retention_lines.append(
            f"<Picture {product_picture_number}>: attribute_transfer throughout; preserve the double-wall silhouette, "
            "open rim, thick clear base and repeated frosted fish motifs, but ignore its original background."
        )

    timeline: list[str] = []
    for cue in clip["cues"]:
        transition = cue["transition"]
        transition_text = "start on" if transition == "start" else (
            "use the foreground glass wipe to cut to"
            if transition == "foreground_wipe_cut"
            else "hard cut to"
        )
        timeline.append(
            f"{_time(cue['start_seconds'])}-{_time(cue['end_seconds'])} seconds - "
            f"{transition_text} <Picture {cue['picture']}>; {cue['action']}"
        )
    trim_duration = float(clip["trim_duration_seconds"])
    render_duration = float(clip["duration_seconds"])
    if render_duration - trim_duration > 0.001:
        timeline.append(
            f"{_time(trim_duration)}-{_time(render_duration)} seconds - hold the final composition steady as "
            "disposable trim padding; introduce no new action or cut."
        )
    cut_count = max(0, len(clip["cues"]) - 1)
    cut_verb = "happens" if cut_count == 1 else "happen"
    duration_text = int(render_duration) if render_duration.is_integer() else render_duration
    return (
        "subject_definitions:\n"
        + "\n".join(subject_lines)
        + "\n\nretention_analysis:\n"
        + "\n".join(retention_lines)
        + "\n\ndetailed_description:\n"
        + f"Generate one vertical {duration_text}-second video. Follow this Picture timeline literally. "
          f"The {cut_count} scheduled internal cut{'s' if cut_count != 1 else ''} {cut_verb} only at the named times; "
          "every cut is a clean edit into the next Picture composition, never a morph or an invented camera move. "
          f"Keep the {scene} scene anchor unchanged for the complete clip.\n\n"
        + "timed_picture_timeline:\n"
        + "\n".join(timeline)
        + "\n\nsoundscape: quiet room tone with the natural sounds of ice, liquid, glass and handling only. "
          "No speech, singing, voice-over or music.\n\n"
        + "Only the scheduled hands and short forearms appear; no face, head or torso. No subtitles, captions, "
          "watermarks, price labels or extra brands. Preserve the target glass shape and fish pattern across every "
          "scheduled cut. Use exactly the listed cuts and no others. Do not morph one Picture into another."
    )


def _compile_grouped_h3_segments(
    repo_root: Path,
    job: dict[str, Any],
    request: dict[str, Any],
    request_path: Path,
    ready: dict[str, Any] | None,
    h3_clip_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    if job.get("audio_mode") != "silent":
        raise ValueError("explicit grouped H3 compilation currently requires audio_mode=silent")
    compiled: list[dict[str, Any]] = []
    source_start = 0.0
    for clip in h3_clip_plan.get("clips", []):
        keyframe_ids = [str(value) for value in clip["keyframe_ids"]]
        images = _keyframe_paths(repo_root, request, request_path, keyframe_ids, ready)
        product_reference = clip.get("product_reference")
        if isinstance(product_reference, str):
            images.append(product_reference)
        if not 2 <= len(images) <= 3:
            raise ValueError(f"H3 clip {clip['id']} must have 2-3 total references")
        trim_duration = float(clip["trim_duration_seconds"])
        source_end = round(source_start + trim_duration, 3)
        compiled.append({
            "id": clip["id"],
            "scene_id": clip["scene_id"],
            "duration": clip["duration_seconds"],
            "source_start_seconds": source_start,
            "source_end_seconds": source_end,
            "trim_to_seconds": clip["trim_duration_seconds"],
            "prompt": render_grouped_prompt(
                clip,
                len(images) if isinstance(product_reference, str) else None,
            ),
            "images": images,
        })
        source_start = source_end
    return compiled


def compile_h3_segments(
    repo_root: Path,
    job: dict[str, Any],
    shot_plan: dict[str, Any],
    request: dict[str, Any],
    request_path: Path,
    ready: dict[str, Any] | None,
    h3_clip_plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if h3_clip_plan is None:
        raise ValueError("timed H3 compilation requires a validated h3_clip_plan")
    if job.get("visual_mode") != "shot_for_shot":
        return _compile_grouped_h3_segments(
            repo_root, job, request, request_path, ready, h3_clip_plan
        )
    if job.get("render_plan", {}).get("h3_audio_mode") != "silent":
        raise ValueError("exact-timing H3 clips must render silent; add the approved master voice-over after trimming")

    plan_segments = [segment for segment in shot_plan.get("segments", []) if isinstance(segment, dict)]
    segment_by_id = {str(segment["id"]): segment for segment in plan_segments}
    normalized_segments: list[dict[str, Any]] = []
    for clip in h3_clip_plan.get("clips", []):
        base = segment_by_id.get(str(clip.get("id")))
        if base is None:
            raise ValueError(f"H3 clip {clip.get('id')} has no matching shot-plan segment")
        normalized_segments.append({
            **base,
            "scene_id": clip["scene_id"],
            "scene_lock": clip.get("scene_lock", base.get("scene_lock")),
            "duration_seconds": clip["duration_seconds"],
            "source_edit_duration_seconds": clip["trim_duration_seconds"],
            "keyframe_ids": clip["keyframe_ids"],
            "timed_shots": clip.get("timed_shots", []),
        })

    compiled: list[dict[str, Any]] = []
    for segment in normalized_segments:
        keyframe_ids = [str(value) for value in segment["keyframe_ids"]]
        keyframe_paths = _keyframe_paths(repo_root, request, request_path, keyframe_ids, ready)
        matching_clip = next(
            (clip for clip in h3_clip_plan.get("clips", []) if str(clip.get("id")) == str(segment["id"])),
            None,
        )
        if not isinstance(matching_clip, dict):
            raise ValueError(f"segment {segment['segment']} has no matching H3 clip")
        product_reference = matching_clip.get("product_reference")
        scene_reference = matching_clip.get("scene_reference")
        images = [
            *keyframe_paths,
            *([product_reference] if isinstance(product_reference, str) else []),
            *([scene_reference] if isinstance(scene_reference, str) else []),
        ]
        if not 2 <= len(images) <= 3:
            raise ValueError(f"segment {segment['segment']} must have 2-3 total H3 references")
        product_presence_by_keyframe = {
            keyframe_id: str(request["segments"][keyframe_id].get("product_presence", "present"))
            for keyframe_id in keyframe_ids
        }
        prompt = render_prompt(
            segment,
            keyframe_ids,
            len(keyframe_paths) + 1 if isinstance(product_reference, str) else None,
            len(keyframe_paths) + 1 if isinstance(scene_reference, str) else None,
            product_presence_by_keyframe,
        )
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
