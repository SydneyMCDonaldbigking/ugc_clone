"""Register a three-angle generated scene pack for keyframe background continuity.

Codex first studies the reference-video evidence, writes one scene_lock, and
generates three empty-background images from that text only. The source frames
are never ImageGen inputs. Each keyframe then binds the view matching its camera:
eye_level, oblique_45, or overhead_90.

Usage:
  python scripts/set_scene_pack.py inputs/demo/job.en.json pale-tabletop-daylight \
      --eye-level work/demo/scene_pack/eye_level.png \
      --oblique-45 work/demo/scene_pack/oblique_45.png \
      --overhead-90 work/demo/scene_pack/overhead_90.png \
      --note "best coherent three-view set"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ugc_pipeline.io import load_json, repo_relative, resolve_repo_path, sha256_file, write_json_atomic


def _ordered_references(references: list[str], roles: dict[str, str]) -> list[str]:
    priority = {
        "presenter_identity": 0,
        "presenter_and_scene_identity": 0,
        "scene_identity": 1,
        "product_identity": 2,
    }
    return sorted(references, key=lambda path: priority.get(roles.get(path, ""), 3))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job")
    parser.add_argument("scene_id")
    parser.add_argument("--eye-level", required=True)
    parser.add_argument("--oblique-45", required=True)
    parser.add_argument("--overhead-90", required=True)
    parser.add_argument("--approved-by", default="codex")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    job_path = resolve_repo_path(REPO_ROOT, args.job)
    raw_views = {
        "eye_level": args.eye_level,
        "oblique_45": args.oblique_45,
        "overhead_90": args.overhead_90,
    }
    views: dict[str, dict[str, str]] = {}
    seen_hashes: set[str] = set()
    for view, raw_path in raw_views.items():
        path = resolve_repo_path(REPO_ROOT, raw_path)
        relative = repo_relative(REPO_ROOT, path)
        normalized = "/" + relative.replace("\\", "/")
        if "/video_analysis/" in normalized or "/keyframes/" in normalized:
            raise SystemExit(f"{view} must be a separate generated scene asset, not a source frame or keyframe")
        digest = sha256_file(path)
        if digest in seen_hashes:
            raise SystemExit("the three scene-pack views must be distinct images")
        seen_hashes.add(digest)
        views[view] = {"master_image": relative, "sha256": digest}

    job = load_json(job_path)
    request_path = resolve_repo_path(REPO_ROOT, job["keyframe_request"])
    request = load_json(request_path)
    requirement = request.get("scene_pack_requirements", {}).get(args.scene_id)
    required_views = requirement.get("views") if isinstance(requirement, dict) else None
    if not isinstance(required_views, dict):
        raise SystemExit(f"keyframe request has no scene-pack requirement for {args.scene_id!r}")
    for view, registered in views.items():
        expected = required_views.get(view, {}).get("output")
        if registered["master_image"] != expected:
            raise SystemExit(f"{view} must use planned scene-pack output {expected!r}")
    shot_plan_path = resolve_repo_path(REPO_ROOT, job["shot_plan"])
    plan = load_json(shot_plan_path)
    matching_segments = [
        segment for segment in plan.get("segments", [])
        if isinstance(segment, dict) and segment.get("scene_id") == args.scene_id
    ]
    if not matching_segments:
        raise SystemExit(f"scene_id {args.scene_id!r} is not used by the shot plan")
    scene_locks = [segment.get("scene_lock") for segment in matching_segments]
    if not isinstance(scene_locks[0], dict) or any(value != scene_locks[0] for value in scene_locks[1:]):
        raise SystemExit(f"scene_id {args.scene_id!r} must have one identical structured scene_lock")

    old_entry = job.get("scene_packs", {}).get(args.scene_id)
    old_paths = {
        item.get("master_image")
        for item in (old_entry.get("views", {}).values() if isinstance(old_entry, dict) else [])
        if isinstance(item, dict)
    }
    approval = {
        "approved_by": args.approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "note": args.note,
        "content": "empty_background_only",
    }
    job.setdefault("scene_packs", {})[args.scene_id] = {
        "scene_lock": scene_locks[0],
        "views": views,
        "approval": approval,
    }
    write_json_atomic(job_path, job)

    frame_by_keyframe: dict[str, dict[str, object]] = {}
    for segment in matching_segments:
        segment["scene_pack_id"] = args.scene_id
        for frame in segment.get("reference_frames", []):
            if not isinstance(frame, dict):
                continue
            view = frame.get("scene_view")
            if view not in views:
                raise SystemExit(f"keyframe {frame.get('keyframe_id')} needs a valid scene_view")
            frame["scene_master"] = views[str(view)]["master_image"]
            frame_by_keyframe[str(frame.get("keyframe_id"))] = frame
    write_json_atomic(shot_plan_path, plan)

    request["background_lock_policy"] = "scene_pack_v1"
    stale: list[str] = []
    for keyframe_id, segment in request.get("segments", {}).items():
        if not isinstance(segment, dict) or segment.get("scene_id") != args.scene_id:
            continue
        view = segment.get("scene_view")
        if view not in views:
            raise SystemExit(f"keyframe {keyframe_id} needs a valid scene_view")
        scene_master = views[str(view)]["master_image"]
        roles = segment.get("reference_roles", {})
        references = segment.get("references", [])
        if not isinstance(roles, dict) or not isinstance(references, list):
            raise SystemExit(f"keyframe {keyframe_id} has invalid references")
        retained = [
            path for path in references
            if roles.get(path) != "scene_identity" and path not in old_paths
        ]
        retained.append(scene_master)
        next_roles = {
            path: role for path, role in roles.items()
            if role != "scene_identity" and path not in old_paths
        }
        next_roles[scene_master] = "scene_identity"
        segment["references"] = _ordered_references(list(dict.fromkeys(retained)), next_roles)
        segment["reference_roles"] = {path: next_roles[path] for path in segment["references"]}
        stale.append(str(keyframe_id))
    write_json_atomic(request_path, request)

    print(json.dumps({
        "scene_id": args.scene_id,
        "views": views,
        "keyframes_to_regenerate": stale,
    }, indent=2))


if __name__ == "__main__":
    main()
