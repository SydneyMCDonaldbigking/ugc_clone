from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .integrity import build_integrity_snapshot, compare_sealed_snapshot
from .io import load_json, repo_relative, resolve_repo_path, write_json_atomic
from .state import append_event, has_reached, initial_state, invalidate_to, transition, utc_now, write_state
from .validation import (
    ValidationResult,
    validate_bundle,
    validate_keyframe_qc,
    validate_ready,
    validate_ready_against_request,
)


PREFLIGHT_SCHEMA = "render-preflight/v1"


def _finish_report(
    result: ValidationResult,
    report: dict[str, Any],
    changes: list[dict[str, str]],
) -> tuple[ValidationResult, dict[str, Any], list[dict[str, str]]]:
    report["changed_artifacts"] = changes
    report["status"] = "pass" if result.ok else "failed"
    report["issues"] = [issue.__dict__ for issue in result.issues]
    return result, report, changes


def _artifact_paths(repo_root: Path, job: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    request_path = resolve_repo_path(repo_root, job["keyframe_request"], must_exist=False)
    keyframe_dir = request_path.parent
    return request_path, keyframe_dir / "QC.json", keyframe_dir / "READY.json", resolve_repo_path(
        repo_root, job["state_file"], must_exist=False
    )


def validate_render_preflight(
    job_path: Path,
    repo_root: Path,
    *,
    actor: str,
) -> tuple[ValidationResult, dict[str, Any], list[dict[str, str]]]:
    result, bundle = validate_bundle(job_path, repo_root)
    job = bundle.get("job") if isinstance(bundle, dict) else None
    report: dict[str, Any] = {
        "schema": PREFLIGHT_SCHEMA,
        "job": job.get("job_id") if isinstance(job, dict) else str(job_path),
        "status": "failed",
        "actor": actor,
        "checked_at": utc_now(),
        "changed_artifacts": [],
        "issues": [],
    }
    if not isinstance(job, dict):
        return _finish_report(result, report, [])

    state_path = resolve_repo_path(repo_root, job["state_file"], must_exist=False)
    state = None
    expected_integrity = None
    if not state_path.is_file():
        result.error("preflight.state_missing", repo_relative(repo_root, state_path), "Job state is missing.")
    else:
        state = load_json(state_path)
        if state.get("state") != "keyframes_ready":
            result.error("preflight.state", "state.state", "Job must be keyframes_ready before rendering.")
        keyframe_stage = state.get("stages", {}).get("keyframes", {})
        expected_integrity = keyframe_stage.get("integrity") if isinstance(keyframe_stage, dict) else None
    changes = compare_sealed_snapshot(repo_root, expected_integrity)
    if changes:
        changed_paths = ", ".join(change["path"] for change in changes[:5])
        suffix = "" if len(changes) <= 5 else f" (+{len(changes) - 5} more)"
        result.error(
            "preflight.integrity_drift",
            "state.stages.keyframes.integrity",
            f"Approved render inputs changed after READY: {changed_paths}{suffix}.",
        )
    if not result.ok:
        return _finish_report(result, report, changes)

    request = bundle["request"]
    request_path, qc_path, ready_path, _ = _artifact_paths(repo_root, job)
    if not qc_path.is_file():
        result.error("preflight.qc_missing", repo_relative(repo_root, qc_path), "QC.json is required before rendering.")
    if not ready_path.is_file():
        result.error("preflight.ready_missing", repo_relative(repo_root, ready_path), "READY.json is required before rendering.")
    if not qc_path.is_file() or not ready_path.is_file():
        return _finish_report(result, report, changes)

    try:
        qc = load_json(qc_path)
        ready = load_json(ready_path)
    except Exception as exc:
        result.error("preflight.load", "keyframes", str(exc))
        return _finish_report(result, report, changes)

    result.extend(validate_keyframe_qc(qc, qc_path, request))
    result.extend(validate_ready(ready, ready_path, repo_root))
    result.extend(validate_ready_against_request(ready, request, job))

    if qc.get("job") != request.get("job"):
        result.error("qc.job", "qc.job", "QC job must match the keyframe request job.")
    if qc.get("pipeline_job_id") != job.get("job_id"):
        result.error("qc.pipeline_job", "qc.pipeline_job_id", "QC pipeline_job_id must match job.job_id.")
    if qc.get("variant_id") != request.get("variant_id"):
        result.error("qc.variant", "qc.variant_id", "QC variant must match the keyframe request.")
    if qc.get("reviewed_by") != "codex":
        result.error("qc.reviewer", "qc.reviewed_by", "Visual keyframe QC must be reviewed by codex.")

    request_segments = request.get("segments") if isinstance(request.get("segments"), dict) else {}
    keyframe_count = len(request_segments)
    max_per_batch = int(job.get("max_segments_per_render", 4))
    expected_batches = math.ceil(keyframe_count / max_per_batch) if keyframe_count else 0
    durations = [
        segment.get("duration_seconds") for segment in request_segments.values()
        if isinstance(segment, dict)
    ]
    if len(durations) != keyframe_count or not all(isinstance(value, (int, float)) for value in durations):
        result.error("preflight.duration", "request.segments", "Every keyframe request needs a numeric duration_seconds.")
    else:
        for segment_id, segment in request_segments.items():
            duration = segment.get("duration_seconds")
            if not 2 <= float(duration) <= 10:
                result.error(
                    "preflight.h3_duration",
                    f"request.segments.{segment_id}.duration_seconds",
                    "Each independently rendered H3 clip must be 2-10 seconds.",
                )

    source_durations = [
        segment.get("source_edit_duration_seconds") for segment in request_segments.values()
        if isinstance(segment, dict)
    ]
    exact_edit_duration = None
    if source_durations and all(isinstance(value, (int, float)) for value in source_durations):
        exact_edit_duration = round(sum(float(value) for value in source_durations), 3)

    render_plan = job.get("render_plan")
    if isinstance(render_plan, dict):
        if render_plan.get("keyframe_count") != keyframe_count:
            result.error("preflight.render_count", "job.render_plan.keyframe_count", "Render plan keyframe_count is stale.")
        if render_plan.get("expected_h3_batches") != expected_batches:
            result.error("preflight.batch_count", "job.render_plan.expected_h3_batches", "Render plan batch count is stale.")
        planned_duration = render_plan.get("edit_to_source_duration_seconds")
        if exact_edit_duration is not None and (
            not isinstance(planned_duration, (int, float))
            or abs(float(planned_duration) - exact_edit_duration) > 0.01
        ):
            result.error(
                "preflight.edit_duration",
                "job.render_plan.edit_to_source_duration_seconds",
                f"Render plan duration must equal the summed source edit duration ({exact_edit_duration}s).",
            )

    current_integrity: dict[str, Any] | None = None
    changes: list[dict[str, str]] = []
    try:
        current_integrity = build_integrity_snapshot(
            job_path, repo_root, job, request, ready, qc_path, ready_path
        )
    except Exception as exc:
        result.error("preflight.integrity", "integrity", str(exc))

    report.update({
        "pipeline_job_id": job.get("job_id"),
        "variant_id": request.get("variant_id"),
        "audio_mode": job.get("audio_mode", "dialogue"),
        "keyframe_count": keyframe_count,
        "max_segments_per_h3_batch": max_per_batch,
        "expected_h3_batches": expected_batches,
        "exact_edit_duration_seconds": exact_edit_duration,
        "visual_qc": {
            "result": qc.get("result"),
            "reviewed_by": qc.get("reviewed_by"),
            "segments": len(qc.get("segments", {})) if isinstance(qc.get("segments"), dict) else 0,
        },
        "integrity": current_integrity,
    })
    return _finish_report(result, report, changes)


def preflight_report_path(repo_root: Path, job: dict[str, Any]) -> Path:
    state_path = resolve_repo_path(repo_root, job["state_file"], must_exist=False)
    return state_path.parent / "PREFLIGHT.json"


def quarantine_ready(
    repo_root: Path,
    job: dict[str, Any],
    *,
    actor: str,
    changes: list[dict[str, str]],
    reason: str,
) -> Path | None:
    _, _, ready_path, state_path = _artifact_paths(repo_root, job)
    backup_path = None
    if ready_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = ready_path.with_name(f"READY.invalidated.{stamp}.json")
        suffix = 2
        while backup_path.exists():
            backup_path = ready_path.with_name(f"READY.invalidated.{stamp}.{suffix}.json")
            suffix += 1
        ready_path.replace(backup_path)

    state = load_json(state_path) if state_path.exists() else initial_state(job["job_id"])
    if not has_reached(str(state.get("state")), "awaiting_keyframes"):
        state = transition(state, "awaiting_keyframes")
    state = invalidate_to(
        state,
        "awaiting_keyframes",
        stage="keyframes",
        reason=reason,
        artifact=repo_relative(repo_root, backup_path) if backup_path else None,
    )
    write_state(state_path, state)
    events_path = resolve_repo_path(repo_root, job["events_file"], must_exist=False)
    append_event(events_path, {
        "event": "keyframes_invalidated",
        "state": "awaiting_keyframes",
        "actor": actor,
        "reason": reason,
        "changed_artifacts": changes,
        "ready_backup": repo_relative(repo_root, backup_path) if backup_path else None,
    })
    return backup_path


def write_preflight_report(path: Path, report: dict[str, Any]) -> None:
    write_json_atomic(path, report)
