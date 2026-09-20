from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .io import repo_relative, resolve_repo_path, sha256_file


INTEGRITY_SCHEMA = "artifact-integrity/v1"


def _add_repo_path(paths: set[Path], repo_root: Path, raw_path: Any) -> None:
    if isinstance(raw_path, str) and raw_path:
        paths.add(resolve_repo_path(repo_root, raw_path))


def collect_preflight_paths(
    job_path: Path,
    repo_root: Path,
    job: dict[str, Any],
    request: dict[str, Any],
    ready: dict[str, Any],
    qc_path: Path,
    ready_path: Path,
) -> list[Path]:
    """Return every local artifact whose bytes authorize an H3 submission."""
    paths: set[Path] = {job_path.resolve(), qc_path.resolve(), ready_path.resolve()}
    for key in ("product", "beats", "script", "shot_plan", "keyframe_request", "h3_clip_plan", "h3_segments"):
        _add_repo_path(paths, repo_root, job.get(key))

    presenter = job.get("presenter")
    if isinstance(presenter, dict):
        _add_repo_path(paths, repo_root, presenter.get("master_image"))

    request_segments = request.get("segments")
    for segment in request_segments.values() if isinstance(request_segments, dict) else []:
        if not isinstance(segment, dict):
            continue
        for raw_path in segment.get("references", []):
            _add_repo_path(paths, repo_root, raw_path)

    ready_segments = ready.get("segments")
    for segment in ready_segments.values() if isinstance(ready_segments, dict) else []:
        if not isinstance(segment, dict):
            continue
        keyframe = segment.get("keyframe")
        if isinstance(keyframe, str):
            paths.add((ready_path.parent / keyframe).resolve())
        for raw_path in segment.get("extra_refs", []):
            _add_repo_path(paths, repo_root, raw_path)

    return sorted(paths, key=lambda path: repo_relative(repo_root, path))


def build_integrity_snapshot(
    job_path: Path,
    repo_root: Path,
    job: dict[str, Any],
    request: dict[str, Any],
    ready: dict[str, Any],
    qc_path: Path,
    ready_path: Path,
) -> dict[str, Any]:
    files = {
        repo_relative(repo_root, path): sha256_file(path)
        for path in collect_preflight_paths(job_path, repo_root, job, request, ready, qc_path, ready_path)
    }
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": INTEGRITY_SCHEMA,
        "digest": hashlib.sha256(canonical).hexdigest(),
        "files": files,
    }


def compare_integrity(expected: Any, current: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(expected, dict) or expected.get("schema") != INTEGRITY_SCHEMA:
        return [{"path": "<snapshot>", "status": "missing", "expected": INTEGRITY_SCHEMA, "actual": "none"}]
    expected_files = expected.get("files")
    current_files = current.get("files")
    if not isinstance(expected_files, dict) or not isinstance(current_files, dict):
        return [{"path": "<snapshot>", "status": "invalid", "expected": "files map", "actual": "invalid"}]
    changes: list[dict[str, str]] = []
    for path in sorted(set(expected_files) | set(current_files)):
        before = expected_files.get(path)
        after = current_files.get(path)
        if before == after:
            continue
        status = "changed"
        if before is None:
            status = "added"
        elif after is None:
            status = "missing"
        changes.append({
            "path": path,
            "status": status,
            "expected": str(before or ""),
            "actual": str(after or ""),
        })
    return changes


def compare_sealed_snapshot(repo_root: Path, expected: Any) -> list[dict[str, str]]:
    """Compare a sealed file map without needing the current bundle to load successfully."""
    if not isinstance(expected, dict) or expected.get("schema") != INTEGRITY_SCHEMA:
        return [{"path": "<snapshot>", "status": "missing", "expected": INTEGRITY_SCHEMA, "actual": "none"}]
    expected_files = expected.get("files")
    if not isinstance(expected_files, dict):
        return [{"path": "<snapshot>", "status": "invalid", "expected": "files map", "actual": "invalid"}]
    current_files: dict[str, str] = {}
    for raw_path in expected_files:
        if not isinstance(raw_path, str):
            continue
        candidate = resolve_repo_path(repo_root, raw_path, must_exist=False)
        if candidate.is_file():
            current_files[raw_path] = sha256_file(candidate)
    current = {"schema": INTEGRITY_SCHEMA, "digest": "", "files": current_files}
    return compare_integrity(expected, current)
