from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import load_json, resolve_repo_path


def load_h3_clip_plan(
    repo_root: Path,
    job: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any] | None:
    raw_path = job.get("h3_clip_plan")
    if not isinstance(raw_path, str):
        return None
    plan = load_json(resolve_repo_path(repo_root, raw_path))
    validate_h3_clip_plan(plan, job, request, repo_root)
    return plan


def validate_h3_clip_plan(
    plan: Any,
    job: dict[str, Any],
    request: dict[str, Any],
    repo_root: Path,
) -> None:
    """Reject plans that confuse ImageGen frames with independently rendered H3 clips."""
    if not isinstance(plan, dict) or plan.get("schema") != "h3-clip-plan/v1":
        raise ValueError("h3_clip_plan must use schema h3-clip-plan/v1")
    if plan.get("job_id") != job.get("job_id"):
        raise ValueError("h3_clip_plan.job_id must match job.job_id")
    if plan.get("variant_id") != request.get("variant_id"):
        raise ValueError("h3_clip_plan.variant_id must match the keyframe request")
    if plan.get("max_reference_images") != 3:
        raise ValueError("h3_clip_plan.max_reference_images must be 3")
    require_scene_lock = plan.get("require_scene_lock", False)
    if not isinstance(require_scene_lock, bool):
        raise ValueError("h3_clip_plan.require_scene_lock must be boolean")

    request_segments = request.get("segments")
    if not isinstance(request_segments, dict):
        raise ValueError("keyframe request segments are missing")
    expected_keyframes = [str(value) for value in request_segments]
    shot_for_shot = job.get("visual_mode") == "shot_for_shot"
    approved_by_id: dict[str, dict[str, Any]] = {}
    approved_clip_ids: list[str] = []
    if shot_for_shot:
        raw_shot_plan = job.get("shot_plan")
        if not isinstance(raw_shot_plan, str):
            raise ValueError("shot_for_shot h3_clip_plan requires job.shot_plan")
        shot_plan = load_json(resolve_repo_path(repo_root, raw_shot_plan))
        approved_segments = [
            segment for segment in shot_plan.get("segments", []) if isinstance(segment, dict)
        ]
        approved_clip_ids = [str(segment.get("id")) for segment in approved_segments]
        approved_by_id = {str(segment.get("id")): segment for segment in approved_segments}
    allowed_product_refs = {
        raw_path
        for segment in request_segments.values()
        if isinstance(segment, dict)
        for raw_path, role in (
            segment.get("reference_roles", {}).items()
            if isinstance(segment.get("reference_roles"), dict)
            else []
        )
        if role == "product_identity"
    }

    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("h3_clip_plan.clips must be a non-empty list")
    flattened: list[str] = []
    flattened_source_shots: list[str] = []
    trim_total = 0.0
    seen_clip_ids: set[str] = set()
    actual_clip_ids: list[str] = []
    for index, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            raise ValueError(f"h3 clip {index} must be an object")
        clip_id = clip.get("id")
        if not isinstance(clip_id, str) or not clip_id or clip_id in seen_clip_ids:
            raise ValueError(f"h3 clip {index} needs a unique id")
        seen_clip_ids.add(clip_id)
        scene_id = clip.get("scene_id")
        if require_scene_lock and (not isinstance(scene_id, str) or not scene_id.strip()):
            raise ValueError(f"{clip_id} needs a scene_id")
        actual_clip_ids.append(clip_id)

        duration = clip.get("duration_seconds")
        trim_duration = clip.get("trim_duration_seconds")
        if not isinstance(duration, (int, float)) or not 2 <= float(duration) <= 15:
            raise ValueError(f"{clip_id} duration_seconds must be 2-15")
        if (
            not isinstance(trim_duration, (int, float))
            or float(trim_duration) <= 0
            or float(trim_duration) > float(duration) + 0.001
        ):
            raise ValueError(f"{clip_id} trim_duration_seconds must be positive and no longer than the render")
        trim_total += float(trim_duration)

        keyframe_ids = clip.get("keyframe_ids")
        if (
            not isinstance(keyframe_ids, list)
            or not 1 <= len(keyframe_ids) <= 3
            or len(set(keyframe_ids)) != len(keyframe_ids)
        ):
            raise ValueError(f"{clip_id} must use one to three unique keyframes")
        keyframe_ids = [str(value) for value in keyframe_ids]
        flattened.extend(keyframe_ids)

        approved = approved_by_id.get(clip_id) if shot_for_shot else None
        if shot_for_shot and approved is None:
            raise ValueError(f"{clip_id} has no matching approved shot-plan clip")
        if approved is not None:
            if approved.get("scene_id") != scene_id:
                raise ValueError(f"{clip_id} scene_id differs from the approved shot plan")
            approved_frames = [
                frame for frame in approved.get("reference_frames", []) if isinstance(frame, dict)
            ]
            if any(frame.get("scene_id") != scene_id for frame in approved_frames):
                raise ValueError(f"{clip_id} approved reference frames do not share one scene_id")
            approved_duration = approved.get("duration_seconds")
            approved_trim = approved.get("source_edit_duration_seconds")
            if not isinstance(approved_duration, (int, float)) or abs(float(duration) - float(approved_duration)) > 0.001:
                raise ValueError(f"{clip_id} duration_seconds differs from the approved shot plan")
            if not isinstance(approved_trim, (int, float)) or abs(float(trim_duration) - float(approved_trim)) > 0.001:
                raise ValueError(f"{clip_id} trim_duration_seconds differs from the approved shot plan")
            approved_keyframes = [str(value) for value in approved.get("keyframe_ids", [])]
            if keyframe_ids != approved_keyframes:
                raise ValueError(f"{clip_id} keyframe_ids differ from the approved shot plan")
            for keyframe_id in keyframe_ids:
                request_segment = request_segments.get(keyframe_id)
                if not isinstance(request_segment, dict) or request_segment.get("scene_id") != scene_id:
                    raise ValueError(f"{clip_id} keyframe {keyframe_id} does not share the approved scene_id")

        product_reference = clip.get("product_reference")
        reference_count = len(keyframe_ids) + (1 if isinstance(product_reference, str) else 0)
        if not 2 <= reference_count <= 3:
            raise ValueError(f"{clip_id} must bind two or three total Picture references")
        if product_reference is not None:
            if not isinstance(product_reference, str) or product_reference not in allowed_product_refs:
                raise ValueError(f"{clip_id} product_reference is not an approved product_identity reference")
            resolve_repo_path(repo_root, product_reference)
        if approved is not None:
            approved_refs = [str(value) for value in approved.get("references", [])]
            expected_product_reference = approved_refs[0] if approved_refs and len(keyframe_ids) < 3 else None
            if product_reference != expected_product_reference:
                raise ValueError(f"{clip_id} product_reference differs from the approved shot plan")

        cues = clip.get("cues")
        if not isinstance(cues, list) or len(cues) != len(keyframe_ids):
            raise ValueError(f"{clip_id} needs one timed cue per keyframe")
        previous_end = 0.0
        cue_ids: list[str] = []
        for cue_index, cue in enumerate(cues, start=1):
            if not isinstance(cue, dict):
                raise ValueError(f"{clip_id} cue {cue_index} must be an object")
            cue_id = str(cue.get("keyframe_id", ""))
            cue_ids.append(cue_id)
            if require_scene_lock and cue.get("scene_id") != scene_id:
                raise ValueError(f"{clip_id} cannot mix different tabletop or scene anchors")
            if cue.get("picture") != cue_index:
                raise ValueError(f"{clip_id} cue {cue_index} must address Picture {cue_index}")
            start = cue.get("start_seconds")
            end = cue.get("end_seconds")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                raise ValueError(f"{clip_id} cue {cue_index} needs numeric times")
            if abs(float(start) - previous_end) > 0.001 or float(end) <= float(start):
                raise ValueError(f"{clip_id} Picture cues must be positive and contiguous from 0 seconds")
            previous_end = float(end)
            if not clip.get("timed_shots"):
                request_segment = request_segments.get(cue_id)
                approved_duration = (
                    request_segment.get("source_edit_duration_seconds")
                    if isinstance(request_segment, dict)
                    else None
                )
                if (
                    not isinstance(approved_duration, (int, float))
                    or abs((float(end) - float(start)) - float(approved_duration)) > 0.001
                ):
                    raise ValueError(f"{clip_id} cue {cue_index} does not match its approved source edit duration")
            transition = cue.get("transition")
            if cue_index == 1 and transition != "start":
                raise ValueError(f"{clip_id} first cue must use transition=start")
            if cue_index > 1 and transition not in {"hard_cut", "foreground_wipe_cut"}:
                raise ValueError(f"{clip_id} later cues need an explicit cut type")
            if not isinstance(cue.get("action"), str) or not cue["action"].strip():
                raise ValueError(f"{clip_id} cue {cue_index} needs an action")
            if approved is not None:
                approved_timed = [
                    item for item in approved.get("timed_shots", []) if isinstance(item, dict)
                ]
                owned = [
                    item for item in approved_timed
                    if str(item.get("picture_keyframe_id")) == cue_id
                ]
                if not owned:
                    raise ValueError(f"{clip_id} cue {cue_index} has no approved timed shots")
                expected_start = owned[0].get("clip_start_seconds")
                expected_end = owned[-1].get("clip_end_seconds")
                expected_action = " Then ".join(
                    str(item.get("direction", "")).rstrip(".") for item in owned
                ) + "."
                if abs(float(start) - float(expected_start)) > 0.001 or abs(float(end) - float(expected_end)) > 0.001:
                    raise ValueError(f"{clip_id} cue {cue_index} timing differs from the approved shot plan")
                if cue.get("action") != expected_action:
                    raise ValueError(f"{clip_id} cue {cue_index} action differs from the approved shot plan")
        if cue_ids != keyframe_ids:
            raise ValueError(f"{clip_id} cue order must match keyframe_ids")
        if abs(previous_end - float(trim_duration)) > 0.001:
            raise ValueError(f"{clip_id} cues must end at trim_duration_seconds")

        timed_shots = clip.get("timed_shots")
        if timed_shots is not None:
            if not isinstance(timed_shots, list) or not timed_shots:
                raise ValueError(f"{clip_id} timed_shots must be a non-empty list")
            previous_shot_end = 0.0
            approved_timed = (
                [item for item in approved.get("timed_shots", []) if isinstance(item, dict)]
                if approved is not None
                else []
            )
            if approved is not None and len(timed_shots) != len(approved_timed):
                raise ValueError(f"{clip_id} timed shot count differs from the approved shot plan")
            for shot_index, shot in enumerate(timed_shots, start=1):
                if not isinstance(shot, dict):
                    raise ValueError(f"{clip_id} timed shot {shot_index} must be an object")
                source_shot_id = shot.get("source_shot_id")
                if not isinstance(source_shot_id, str) or not source_shot_id:
                    raise ValueError(f"{clip_id} timed shot {shot_index} needs source_shot_id")
                flattened_source_shots.append(source_shot_id)
                start = shot.get("start_seconds")
                end = shot.get("end_seconds")
                if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                    raise ValueError(f"{clip_id} timed shot {shot_index} needs numeric times")
                if abs(float(start) - previous_shot_end) > 0.001 or float(end) <= float(start):
                    raise ValueError(f"{clip_id} timed shots must be positive and contiguous from 0 seconds")
                previous_shot_end = float(end)
                picture = shot.get("picture")
                if not isinstance(picture, int) or not 1 <= picture <= len(keyframe_ids):
                    raise ValueError(f"{clip_id} timed shot {shot_index} addresses an unavailable Picture")
                transition = shot.get("transition")
                if shot_index == 1 and transition != "start":
                    raise ValueError(f"{clip_id} first timed shot must use transition=start")
                if shot_index > 1 and transition not in {"hard_cut", "foreground_wipe_cut"}:
                    raise ValueError(f"{clip_id} later timed shots need an explicit cut type")
                if not isinstance(shot.get("action"), str) or not shot["action"].strip():
                    raise ValueError(f"{clip_id} timed shot {shot_index} needs an action")
                if approved is not None:
                    approved_shot = approved_timed[shot_index - 1]
                    expected_picture_id = str(approved_shot.get("picture_keyframe_id"))
                    expected_picture = keyframe_ids.index(expected_picture_id) + 1
                    expected_transition = "start" if shot_index == 1 else "hard_cut"
                    expected_action = f"{approved_shot.get('shot_type')}: {approved_shot.get('direction')}"
                    if source_shot_id != str(approved_shot.get("source_shot_id")):
                        raise ValueError(f"{clip_id} timed shot {shot_index} source differs from the approved shot plan")
                    if (
                        abs(float(start) - float(approved_shot.get("clip_start_seconds"))) > 0.001
                        or abs(float(end) - float(approved_shot.get("clip_end_seconds"))) > 0.001
                    ):
                        raise ValueError(f"{clip_id} timed shot {shot_index} timing differs from the approved shot plan")
                    if picture != expected_picture:
                        raise ValueError(f"{clip_id} timed shot {shot_index} Picture differs from the approved shot plan")
                    if transition != expected_transition:
                        raise ValueError(f"{clip_id} timed shot {shot_index} transition differs from the approved shot plan")
                    if shot.get("action") != expected_action:
                        raise ValueError(f"{clip_id} timed shot {shot_index} action differs from the approved shot plan")
            if abs(previous_shot_end - float(trim_duration)) > 0.001:
                raise ValueError(f"{clip_id} timed shots must end at trim_duration_seconds")

    if flattened != expected_keyframes:
        raise ValueError("h3 clips must cover every approved keyframe exactly once and in request order")
    if shot_for_shot and actual_clip_ids != approved_clip_ids:
        raise ValueError("h3 clip order must exactly match the approved shot plan")
    if flattened_source_shots:
        raw_shot_map = job.get("shot_map")
        if not isinstance(raw_shot_map, str):
            raise ValueError("timed_shots require job.shot_map")
        shot_map = load_json(resolve_repo_path(repo_root, raw_shot_map))
        expected_source_shots = [
            str(shot.get("id"))
            for shot in shot_map.get("shots", [])
            if isinstance(shot, dict)
        ]
        if flattened_source_shots != expected_source_shots:
            raise ValueError("h3 timed_shots must cover every source shot exactly once and in order")
        source_duration = shot_map.get("source_duration_seconds")
        if shot_for_shot and (
            not isinstance(source_duration, (int, float))
            or abs(trim_total - float(source_duration)) > 0.001
        ):
            raise ValueError("h3 clip trim total must exactly match the source shot map duration")
    total = plan.get("total_edit_duration_seconds")
    if not isinstance(total, (int, float)) or abs(trim_total - float(total)) > 0.001:
        raise ValueError(f"h3_clip_plan total must equal {trim_total:.3f}")

    render_plan = job.get("render_plan") if isinstance(job.get("render_plan"), dict) else {}
    batch_size = int(job.get("max_segments_per_render", 20))
    expected_batches = (len(clips) + batch_size - 1) // batch_size
    expected = {
        "keyframe_count": len(expected_keyframes),
        "h3_clip_count": len(clips),
        "expected_h3_batches": expected_batches,
        "edit_to_source_duration_seconds": trim_total,
    }
    for field, value in expected.items():
        actual = render_plan.get(field)
        if not isinstance(actual, (int, float)) or abs(float(actual) - float(value)) > 0.001:
            raise ValueError(f"job.render_plan.{field} must equal {value}")
