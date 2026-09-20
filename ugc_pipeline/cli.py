from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .io import load_json, resolve_repo_path
from .integrity import build_integrity_snapshot
from .preflight import (
    preflight_report_path,
    quarantine_ready,
    validate_render_preflight,
    write_preflight_report,
)
from .state import append_event, has_reached, initial_state, record_stage, transition, write_state
from .validation import (
    ValidationResult,
    validate_bundle,
    validate_keyframe_qc,
    validate_ready,
    validate_ready_against_request,
)


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "WORKFLOW.md").exists():
            return candidate
    raise SystemExit("Could not locate repository root containing AGENTS.md and WORKFLOW.md.")


def print_result(result: ValidationResult) -> None:
    for issue in result.issues:
        print(f"{issue.level.upper():7} {issue.code:28} {issue.path}: {issue.message}")
    print(f"RESULT  {'PASS' if result.ok else 'FAIL'}  errors={len(result.errors)} warnings={len(result.warnings)}")


def job_path_from_arg(repo_root: Path, raw_path: str) -> Path:
    return resolve_repo_path(repo_root, raw_path)


def state_paths(repo_root: Path, job: dict[str, Any]) -> tuple[Path, Path]:
    return (
        resolve_repo_path(repo_root, job["state_file"], must_exist=False),
        resolve_repo_path(repo_root, job["events_file"], must_exist=False),
    )


def command_validate(args: argparse.Namespace, repo_root: Path) -> int:
    job_path = job_path_from_arg(repo_root, args.job)
    result, _ = validate_bundle(job_path, repo_root)
    print_result(result)
    return 0 if result.ok else 1


def command_init(args: argparse.Namespace, repo_root: Path) -> int:
    job_path = job_path_from_arg(repo_root, args.job)
    job = load_json(job_path)
    state_path, events_path = state_paths(repo_root, job)
    if state_path.exists() and not args.force:
        raise SystemExit(f"State already exists: {state_path}. Use --force to recreate it.")
    state = initial_state(job["job_id"])
    write_state(state_path, state)
    append_event(events_path, {"event": "job_initialized", "state": "created", "actor": args.actor})
    print(state_path)
    return 0


def command_advance(args: argparse.Namespace, repo_root: Path) -> int:
    if args.until != "awaiting_keyframes":
        raise SystemExit("The current implementation supports only --until awaiting_keyframes.")
    job_path = job_path_from_arg(repo_root, args.job)
    result, bundle = validate_bundle(job_path, repo_root)
    print_result(result)
    if not result.ok:
        return 1
    job = bundle["job"]
    state_path, events_path = state_paths(repo_root, job)
    state = load_json(state_path) if state_path.exists() else initial_state(job["job_id"])
    for target, stage, artifact_key in (
        ("beats_ready", "beats", "beats"),
        ("facts_ready", "facts", "product"),
        ("scripts_ready", "scripts", "script"),
        ("shots_ready", "shots", "shot_plan"),
        ("awaiting_keyframes", "keyframe_request", "keyframe_request"),
    ):
        artifact = job[artifact_key]
        if has_reached(state["state"], target):
            recorded = state.get("stages", {}).get(stage, {}).get("artifact")
            if recorded != artifact:
                state = record_stage(state, stage, artifact)
                append_event(events_path, {
                    "event": "artifact_updated",
                    "state": state["state"],
                    "artifact": artifact,
                    "actor": args.actor,
                })
            continue
        state = transition(state, target, stage=stage, artifact=artifact)
        append_event(events_path, {
            "event": "state_advanced",
            "state": target,
            "artifact": artifact,
            "actor": args.actor,
        })
    write_state(state_path, state)
    print(json.dumps({"job_id": job["job_id"], "state": state["state"], "state_file": job["state_file"]}, indent=2))
    return 0


def command_status(args: argparse.Namespace, repo_root: Path) -> int:
    job_path = job_path_from_arg(repo_root, args.job)
    job = load_json(job_path)
    state_path, _ = state_paths(repo_root, job)
    if not state_path.exists():
        print(json.dumps({"job_id": job["job_id"], "state": "not_initialized"}, indent=2))
        return 0
    print(json.dumps(load_json(state_path), indent=2))
    return 0


def command_keyframe_status(args: argparse.Namespace, repo_root: Path) -> int:
    job_path = job_path_from_arg(repo_root, args.job)
    bundle_result, bundle = validate_bundle(job_path, repo_root)
    if not bundle_result.ok:
        print_result(bundle_result)
        return 1
    job = bundle["job"]
    request_path = resolve_repo_path(repo_root, job["keyframe_request"])
    ready_path = request_path.parent / "READY.json"
    qc_path = request_path.parent / "QC.json"
    request = bundle["request"]
    if not qc_path.exists():
        print(json.dumps({"job_id": job["job_id"], "state": "awaiting_keyframes", "ready": False, "qc": "missing"}, indent=2))
        return 1
    qc = load_json(qc_path)
    result = validate_keyframe_qc(qc, qc_path, request)
    if not ready_path.exists():
        print_result(result)
        print(json.dumps({"job_id": job["job_id"], "state": "awaiting_keyframes", "ready": False, "qc": "pass" if result.ok else "failed"}, indent=2))
        return 2 if result.ok else 1
    ready = load_json(ready_path)
    result.extend(validate_ready(ready, ready_path, repo_root))
    result.extend(validate_ready_against_request(ready, request, job))
    print_result(result)
    if not result.ok:
        return 1
    integrity = build_integrity_snapshot(job_path, repo_root, job, request, ready, qc_path, ready_path)
    attempts = {
        segment_id: segment.get("attempt")
        for segment_id, segment in (qc.get("segments", {}).items() if isinstance(qc.get("segments"), dict) else [])
        if isinstance(segment, dict) and isinstance(segment.get("attempt"), int)
    }
    state_path, events_path = state_paths(repo_root, job)
    state = load_json(state_path) if state_path.exists() else initial_state(job["job_id"])
    state = transition(
        state,
        "keyframes_ready",
        stage="keyframes",
        artifact=ready_path.relative_to(repo_root).as_posix(),
        metadata={
            "integrity": integrity,
            "reviewed_by": qc.get("reviewed_by"),
            "attempts": attempts,
        },
    )
    write_state(state_path, state)
    append_event(events_path, {
        "event": "keyframes_ready",
        "state": "keyframes_ready",
        "actor": args.actor,
        "artifact": ready_path.relative_to(repo_root).as_posix(),
        "integrity_digest": integrity["digest"],
        "attempts": attempts,
    })
    return 0


def command_preflight(args: argparse.Namespace, repo_root: Path) -> int:
    job_path = job_path_from_arg(repo_root, args.job)
    job = load_json(job_path)
    result, report, changes = validate_render_preflight(job_path, repo_root, actor=args.actor)
    report_path = preflight_report_path(repo_root, job)
    invalidated = None
    if not result.ok and changes and not args.check_only:
        reason = "Approved render inputs changed after keyframe approval."
        invalidated = quarantine_ready(
            repo_root,
            job,
            actor=args.actor,
            changes=changes,
            reason=reason,
        )
        if invalidated is not None:
            report["ready_invalidated_to"] = invalidated.relative_to(repo_root).as_posix()
    if not args.check_only:
        write_preflight_report(report_path, report)
        if result.ok:
            _, events_path = state_paths(repo_root, job)
            append_event(events_path, {
                "event": "preflight_passed",
                "state": "keyframes_ready",
                "actor": args.actor,
                "artifact": report_path.relative_to(repo_root).as_posix(),
                "integrity_digest": report.get("integrity", {}).get("digest"),
            })
    print_result(result)
    print(json.dumps({
        "job_id": job.get("job_id"),
        "preflight": report.get("status"),
        "report": None if args.check_only else report_path.relative_to(repo_root).as_posix(),
        "ready_invalidated_to": report.get("ready_invalidated_to"),
    }, indent=2))
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ugc-pipeline", description="English-first UGC pipeline orchestration.")
    parser.add_argument("--repo-root", help="Repository root. Defaults to auto-detection.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate the full planning bundle.")
    validate_parser.add_argument("job")
    validate_parser.set_defaults(handler=command_validate)

    init_parser = subparsers.add_parser("init", help="Create job state and event log.")
    init_parser.add_argument("job")
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--actor", default=os.environ.get("UGC_PIPELINE_ACTOR", "codex"))
    init_parser.set_defaults(handler=command_init)

    advance_parser = subparsers.add_parser("advance", help="Validate planning artifacts and advance state.")
    advance_parser.add_argument("job")
    advance_parser.add_argument("--until", default="awaiting_keyframes")
    advance_parser.add_argument("--actor", default=os.environ.get("UGC_PIPELINE_ACTOR", "codex"))
    advance_parser.set_defaults(handler=command_advance)

    status_parser = subparsers.add_parser("status", help="Show persisted job state.")
    status_parser.add_argument("job")
    status_parser.set_defaults(handler=command_status)

    keyframe_parser = subparsers.add_parser("keyframe-status", help="Validate READY.json and advance the job.")
    keyframe_parser.add_argument("job")
    keyframe_parser.add_argument("--actor", default=os.environ.get("UGC_PIPELINE_ACTOR", "codex"))
    keyframe_parser.set_defaults(handler=command_keyframe_status)

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Verify the sealed render bundle and invalidate stale READY files.",
    )
    preflight_parser.add_argument("job")
    preflight_parser.add_argument("--actor", default=os.environ.get("UGC_PIPELINE_ACTOR", "codex"))
    preflight_parser.add_argument(
        "--check-only",
        action="store_true",
        help="Report without writing PREFLIGHT.json or invalidating stale readiness.",
    )
    preflight_parser.set_defaults(handler=command_preflight)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else find_repo_root(Path.cwd())
    try:
        exit_code = args.handler(args, repo_root)
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)
