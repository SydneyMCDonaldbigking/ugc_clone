"""Register (and approve) the presenter master image for a job.

The presenter master is one image of the fictional presenter in the job's scene with no product in it.
It is the only generated image allowed as a keyframe reference: every segment binds it for person and
scene continuity, and the product always comes from the original product photos.

Usage:
  python scripts/set_presenter_master.py inputs/a2_test/job.en.json inputs/a2_test/presenter_master.png \
      --approved-by operator --note "chosen from 3 candidates"

It updates job.presenter (master_image + approval with sha256), then points every presenter reference in
the shot plan and keyframe request at the new master. Existing keyframes that used the old master are
listed so they can be regenerated.
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

PRESENTER_ROLES = {"presenter_identity", "presenter_and_scene_identity"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job")
    parser.add_argument("master")
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    job_path = resolve_repo_path(REPO_ROOT, args.job)
    master_path = resolve_repo_path(REPO_ROOT, args.master)
    master = repo_relative(REPO_ROOT, master_path)
    job = load_json(job_path)
    old_master = job.get("presenter", {}).get("master_image")

    job.setdefault("presenter", {})
    job["presenter"]["master_image"] = master
    job["presenter"]["approval"] = {
        "sha256": sha256_file(master_path),
        "approved_by": args.approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "note": args.note,
    }
    write_json_atomic(job_path, job)

    shot_plan_path = resolve_repo_path(REPO_ROOT, job["shot_plan"])
    plan = load_json(shot_plan_path)
    for segment in plan.get("segments", []):
        segment["references"] = [master if ref == old_master else ref for ref in segment.get("references", [])]
    write_json_atomic(shot_plan_path, plan)

    request_path = resolve_repo_path(REPO_ROOT, job["keyframe_request"])
    request = load_json(request_path)
    stale = []
    for keyframe_id, segment in request.get("segments", {}).items():
        roles = segment.get("reference_roles", {})
        if not any(role in PRESENTER_ROLES for role in roles.values()):
            continue
        segment["references"] = [master if roles.get(ref) in PRESENTER_ROLES else ref for ref in segment["references"]]
        segment["reference_roles"] = {
            (master if role in PRESENTER_ROLES else ref): role for ref, role in roles.items()
        }
        if old_master != master:
            stale.append(keyframe_id)
    write_json_atomic(request_path, request)

    print(json.dumps({"master_image": master, "sha256": job["presenter"]["approval"]["sha256"],
                      "keyframes_to_regenerate": stale}, indent=2))


if __name__ == "__main__":
    main()
