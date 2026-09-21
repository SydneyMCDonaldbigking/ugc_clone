"""Build a few time-coded H3 clips from an exact Hypit source-shot map.

The source shot map owns edit rhythm.  The product-specific spec groups those
microshots into 2-15 second H3 clips, assigns one of up to three generated
keyframes to each microshot, and describes the replacement action.  This script
copies all timing mechanically so prose changes cannot silently retime the edit.
"""

from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


SCENE_LOCK_FIELDS = (
    "setting",
    "surface",
    "backdrop",
    "lighting",
    "palette",
    "fixed_props",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _round(value: float) -> float:
    return round(float(value), 3)


def _scene_lock(spec: dict[str, Any], scene_id: str) -> dict[str, str]:
    scene_locks = spec.get("scene_locks")
    if not isinstance(scene_locks, dict):
        raise ValueError("timed H3 spec needs a scene_locks object")
    raw = scene_locks.get(scene_id)
    if not isinstance(raw, dict):
        raise ValueError(f"scene_id {scene_id!r} needs one canonical scene_lock")
    missing = [field for field in SCENE_LOCK_FIELDS if not isinstance(raw.get(field), str) or not raw[field].strip()]
    if missing:
        raise ValueError(f"scene_lock {scene_id!r} needs non-empty fields {missing}")
    return {field: raw[field].strip() for field in SCENE_LOCK_FIELDS}


def _scene_view(frame: dict[str, Any]) -> str:
    declared = frame.get("scene_view")
    if declared in {"eye_level", "oblique_45", "overhead_90"}:
        return str(declared)
    camera = str(frame.get("camera", "")).lower()
    if "overhead" in camera or "90 degree" in camera or "90 degrees" in camera:
        return "overhead_90"
    if "high angle" in camera or any(token in camera for token in ("25 degree", "45 degree", "50 degree")):
        return "oblique_45"
    return "eye_level"


def materialize(
    shot_map: dict[str, Any],
    script: dict[str, Any],
    spec: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if spec.get("schema") != "timed-h3-spec/v1":
        raise ValueError("expected timed-h3-spec/v1")

    source_shots = [shot for shot in shot_map.get("shots", []) if isinstance(shot, dict)]
    source_by_id = {str(shot["id"]): shot for shot in source_shots}
    expected_source_ids = list(source_by_id)
    lines_by_segment = {
        int(line["segment"]): line for line in script.get("lines", []) if isinstance(line, dict)
    }
    output_dir = str(spec["output_dir"]).rstrip("/")
    plan_segments: list[dict[str, Any]] = []
    request_segments: OrderedDict[str, dict[str, Any]] = OrderedDict()
    scene_pack_requirements: OrderedDict[str, dict[str, Any]] = OrderedDict()
    used_source_ids: list[str] = []

    for clip_index, clip in enumerate(spec.get("clips", []), start=1):
        segment_number = int(clip["segment"])
        scene_id = clip.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id.strip():
            raise ValueError(f"clip {clip_index} needs a non-empty scene_id")
        scene_lock = _scene_lock(spec, scene_id)
        if scene_id not in scene_pack_requirements:
            scene_pack_dir = (Path(output_dir).parent / "scene_pack" / scene_id).as_posix()
            scene_pack_requirements[scene_id] = {
                "scene_lock": scene_lock,
                "base_view": "eye_level",
                "views": {
                    view: {
                        "prompt_file": f"{scene_pack_dir}/{view}_prompt.txt",
                        "output": f"{scene_pack_dir}/{view}.png",
                    }
                    for view in ("eye_level", "oblique_45", "overhead_90")
                },
            }
        line = lines_by_segment.get(segment_number)
        if line is None:
            raise ValueError(f"clip {clip_index} references missing script segment {segment_number}")

        frames = clip.get("reference_frames", [])
        if not 1 <= len(frames) <= 3:
            raise ValueError(f"clip {clip_index} must define one to three reference_frames")
        frame_ids = [str(frame["keyframe_id"]) for frame in frames]
        if len(set(frame_ids)) != len(frame_ids):
            raise ValueError(f"clip {clip_index} has duplicate keyframe IDs")

        microshots = clip.get("timed_shots", [])
        if not microshots:
            raise ValueError(f"clip {clip_index} has no timed_shots")
        source_ids = [str(row["source_shot_id"]) for row in microshots]
        if any(source_id not in source_by_id for source_id in source_ids):
            missing = [source_id for source_id in source_ids if source_id not in source_by_id]
            raise ValueError(f"clip {clip_index} has unknown source shots {missing}")
        used_source_ids.extend(source_ids)

        first_source = source_by_id[source_ids[0]]
        last_source = source_by_id[source_ids[-1]]
        source_start = _round(first_source["source_start_seconds"])
        source_end = _round(last_source["source_end_seconds"])
        source_edit_duration = _round(source_end - source_start)
        render_duration = _round(clip["render_duration_seconds"])
        if not 2 <= render_duration <= 15:
            raise ValueError(f"clip {clip_index} render duration must be 2-15 seconds")
        if render_duration + 0.001 < source_edit_duration:
            raise ValueError(f"clip {clip_index} is shorter than its source edit window")

        timed_shots: list[dict[str, Any]] = []
        for row in microshots:
            source = source_by_id[str(row["source_shot_id"])]
            picture_id = str(row["picture_keyframe_id"])
            if picture_id not in frame_ids:
                raise ValueError(
                    f"{source['id']} uses keyframe {picture_id}, outside clip {clip_index}"
                )
            timed_shots.append({
                "source_shot_id": source["id"],
                "source_start_seconds": _round(source["source_start_seconds"]),
                "source_end_seconds": _round(source["source_end_seconds"]),
                "clip_start_seconds": _round(float(source["source_start_seconds"]) - source_start),
                "clip_end_seconds": _round(float(source["source_end_seconds"]) - source_start),
                "picture_keyframe_id": picture_id,
                "shot_type": row["shot_type"],
                "direction": row["direction"],
            })

        product_references = list(dict.fromkeys(
            str(frame["product_reference"])
            for frame in frames
            if isinstance(frame.get("product_reference"), str)
        ))
        if len(product_references) > 1:
            raise ValueError(f"clip {clip_index} may use only one shared original product reference")

        plan_frames: list[dict[str, Any]] = []
        for frame in frames:
            keyframe_id = str(frame["keyframe_id"])
            scene_view = _scene_view(frame)
            plan_frame = {
                "keyframe_id": keyframe_id,
                "scene_id": scene_id,
                "scene_lock": scene_lock,
                "scene_view": scene_view,
                "role": frame["role"],
                "first_frame": frame["first_frame"],
                "camera": frame["camera"],
                "performance": frame["performance"],
                "product_presence": frame.get("product_presence", "present"),
            }
            plan_frame["scene_master"] = scene_pack_requirements[scene_id]["views"][scene_view]["output"]
            plan_frames.append(plan_frame)
            product_presence = frame.get("product_presence", "present")
            if product_presence not in {"present", "absent"}:
                raise ValueError(f"keyframe {keyframe_id} product_presence must be present or absent")
            references: list[str] = []
            reference_roles: dict[str, str] = {}
            if product_presence == "present":
                if not isinstance(frame.get("product_reference"), str):
                    raise ValueError(f"keyframe {keyframe_id} needs product_reference when product is present")
                product_reference = str(frame["product_reference"])
                references.append(product_reference)
                reference_roles[product_reference] = "product_identity"
                fidelity = frame.get("product_fidelity_mode", "reference_lock")
                pose_source = "product_identity_reference" if fidelity == "pixel_preserve" else "shot_plan"
            else:
                fidelity = "not_applicable"
                pose_source = None
            request_segments[keyframe_id] = {
                "script_segment": segment_number,
                "scene_id": scene_id,
                "scene_lock": scene_lock,
                "scene_view": scene_view,
                "role": frame["role"],
                "prompt_file": f"{output_dir}/seg{keyframe_id}_prompt.txt",
                "references": references,
                "reference_roles": reference_roles,
                "product_presence": product_presence,
                "product_fidelity_mode": fidelity,
                "output": f"seg{keyframe_id}.png",
                "checks": frame["checks"],
            }
            if product_presence == "present":
                request_segments[keyframe_id]["product_placement"] = {
                    "pose_source": pose_source,
                    "orientation": "unchanged_from_reference",
                    "occlusion": frame.get("occlusion", "hands_keep_product_identity_visible"),
                    "fallback": frame.get("fallback", "static_product_shot"),
                }

        plan_segments.append({
            "id": f"S{segment_number:02d}",
            "scene_id": scene_id,
            "scene_lock": scene_lock,
            "segment": segment_number,
            "duration_seconds": render_duration,
            "source_start_seconds": source_start,
            "source_end_seconds": source_end,
            "source_edit_duration_seconds": source_edit_duration,
            "dialogue": line["text"],
            "shot_type": clip.get("shot_type", "timed_shot_for_shot_montage"),
            "subject": clip["subject"],
            "action": clip["action"],
            "performance": clip["performance"],
            "intention": clip["intention"],
            "accents": clip.get("accents", []),
            "keyframe_ids": frame_ids,
            "reference_frames": plan_frames,
            "timed_shots": timed_shots,
            "continuity": "hard_cut",
            "keyframe_strategy": "codex-imagegen-edit",
            "references": product_references,
            "preserve": clip.get("preserve", ["exact source cut timing", "exact source shot order"]),
            "exclude": clip.get("exclude", ["visible face", "source product", "source captions", "watermark"]),
            "label_policy": clip.get("label_policy", "original_pixels_or_fully_preserved"),
            "h3_prompt_file": clip.get(
                "h3_prompt_file", f"{Path(output_dir).parent.as_posix()}/h3/seg{segment_number:02d}_prompt.txt"
            ),
        })

    if used_source_ids != expected_source_ids:
        raise ValueError(
            f"timed source shot order {used_source_ids} does not exactly equal {expected_source_ids}"
        )
    if list(lines_by_segment) != [segment["segment"] for segment in plan_segments]:
        raise ValueError("clips must cover every script segment exactly once and in order")

    plan = {
        "schema": "shot-plan/v1",
        "language": script["language"],
        "variant_id": script["variant_id"],
        "audio_mode": script.get("audio_mode", "dialogue"),
        "visual_mode": "shot_for_shot",
        "shot_map": spec["shot_map"],
        "segments": plan_segments,
    }
    request = {
        "schema": "keyframe-request/v1",
        "job": spec["job"],
        "pipeline_job_id": spec["pipeline_job_id"],
        "variant_id": script["variant_id"],
        "source_job_id": None,
        "output_aspect_ratio": "9:16",
        "prompt_template": spec["prompt_template"],
        "background_lock_policy": "scene_pack_v1",
        "scene_pack_requirements": scene_pack_requirements,
        "visual_mode": "shot_for_shot",
        "shot_map": spec["shot_map"],
        "segments": request_segments,
    }
    return plan, request


def build_h3_clip_plan(plan: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Create the canonical H3 grouping contract from the timed shot plan."""

    clips: list[dict[str, Any]] = []
    total_edit_duration = 0.0
    for segment in plan.get("segments", []):
        keyframe_ids = [str(value) for value in segment["keyframe_ids"]]
        scene_id = segment.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id.strip():
            raise ValueError(f"{segment.get('id')} needs a non-empty scene_id")
        scene_lock = segment.get("scene_lock")
        if not isinstance(scene_lock, dict):
            raise ValueError(f"{segment.get('id')} needs a structured scene_lock")
        picture_by_keyframe = {
            keyframe_id: index for index, keyframe_id in enumerate(keyframe_ids, start=1)
        }
        timed_shots = segment["timed_shots"]
        cues: list[dict[str, Any]] = []
        for keyframe_id in keyframe_ids:
            owned = [
                shot for shot in timed_shots
                if str(shot["picture_keyframe_id"]) == keyframe_id
            ]
            if not owned:
                raise ValueError(f"keyframe {keyframe_id} owns no timed shots")
            indexes = [timed_shots.index(shot) for shot in owned]
            if indexes != list(range(min(indexes), max(indexes) + 1)):
                raise ValueError(f"keyframe {keyframe_id} must own one contiguous time window")
            picture = picture_by_keyframe[keyframe_id]
            cues.append({
                "keyframe_id": keyframe_id,
                "picture": picture,
                "scene_id": scene_id,
                "start_seconds": owned[0]["clip_start_seconds"],
                "end_seconds": owned[-1]["clip_end_seconds"],
                "transition": "start" if picture == 1 else "hard_cut",
                "action": " Then ".join(str(shot["direction"]).rstrip(".") for shot in owned) + ".",
            })
        canonical_timed_shots = []
        for index, shot in enumerate(timed_shots):
            canonical_timed_shots.append({
                "source_shot_id": shot["source_shot_id"],
                "picture": picture_by_keyframe[str(shot["picture_keyframe_id"])],
                "start_seconds": shot["clip_start_seconds"],
                "end_seconds": shot["clip_end_seconds"],
                "transition": "start" if index == 0 else "hard_cut",
                "action": f"{shot['shot_type']}: {shot['direction']}",
            })
        product_refs = segment.get("references", [])
        product_is_visible = any(
            frame.get("product_presence", "present") == "present"
            for frame in segment.get("reference_frames", [])
            if isinstance(frame, dict)
        )
        product_reference = product_refs[0] if product_is_visible and product_refs and len(keyframe_ids) < 3 else None
        scene_reference = None
        if product_reference is None and len(keyframe_ids) == 1:
            frames = [frame for frame in segment.get("reference_frames", []) if isinstance(frame, dict)]
            if frames and isinstance(frames[0].get("scene_master"), str):
                scene_reference = frames[0]["scene_master"]
        total_edit_duration += float(segment["source_edit_duration_seconds"])
        clips.append({
            "id": segment["id"],
            "scene_id": scene_id,
            "scene_lock": scene_lock,
            "duration_seconds": segment["duration_seconds"],
            "trim_duration_seconds": segment["source_edit_duration_seconds"],
            "keyframe_ids": keyframe_ids,
            "product_reference": product_reference,
            "scene_reference": scene_reference,
            "cues": cues,
            "timed_shots": canonical_timed_shots,
        })
    return {
        "schema": "h3-clip-plan/v1",
        "job_id": spec["pipeline_job_id"],
        "variant_id": plan["variant_id"],
        "max_reference_images": 3,
        "background_lock_policy": "scene_pack_v1",
        "total_edit_duration_seconds": _round(total_edit_duration),
        "clips": clips,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shot_map", type=Path)
    parser.add_argument("script", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("shot_plan_output", type=Path)
    parser.add_argument("request_output", type=Path)
    parser.add_argument("--h3-clip-plan-output", type=Path)
    args = parser.parse_args()

    plan, request = materialize(_load(args.shot_map), _load(args.script), _load(args.spec))
    _write(args.shot_plan_output, plan)
    _write(args.request_output, request)
    h3_clip_plan = build_h3_clip_plan(plan, _load(args.spec))
    if args.h3_clip_plan_output:
        _write(args.h3_clip_plan_output, h3_clip_plan)
    print(json.dumps({
        "shot_plan": args.shot_plan_output.as_posix(),
        "request": args.request_output.as_posix(),
        "h3_clips": len(plan["segments"]),
        "keyframes": len(request["segments"]),
        "timed_microshots": sum(len(segment["timed_shots"]) for segment in plan["segments"]),
        "h3_clip_plan": args.h3_clip_plan_output.as_posix() if args.h3_clip_plan_output else None,
    }, indent=2))


if __name__ == "__main__":
    main()
