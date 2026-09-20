from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import repo_relative, sha256_file, write_json_atomic


STATES = [
    "created",
    "ingested",
    "transcribed",
    "beats_ready",
    "facts_ready",
    "scripts_ready",
    "shots_ready",
    "awaiting_keyframes",
    "keyframes_ready",
    "rendering",
    "rendered",
    "assembled",
    "qa_passed",
    "human_review",
    "approved",
]
TERMINAL_STATES = {"rejected", "blocked"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def initial_state(job_id: str) -> dict[str, Any]:
    return {
        "schema": "job-state/v1",
        "job_id": job_id,
        "state": "created",
        "revision": 1,
        "updated_at": utc_now(),
        "stages": {},
    }


def can_transition(current: str, target: str) -> bool:
    if current in TERMINAL_STATES:
        return False
    if target in TERMINAL_STATES:
        return True
    if current not in STATES or target not in STATES:
        return False
    return STATES.index(target) >= STATES.index(current)


def has_reached(current: str, target: str) -> bool:
    if current in TERMINAL_STATES:
        return False
    if current not in STATES or target not in STATES:
        return False
    return STATES.index(current) >= STATES.index(target)


def transition(
    state: dict[str, Any],
    target: str,
    *,
    stage: str | None = None,
    artifact: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = str(state.get("state"))
    if not can_transition(current, target):
        raise ValueError(f"Invalid state transition: {current} -> {target}")
    updated = json.loads(json.dumps(state))
    updated["state"] = target
    updated["revision"] = int(updated.get("revision", 0)) + 1
    updated["updated_at"] = utc_now()
    if stage:
        stage_entry: dict[str, Any] = {"status": "passed", "updated_at": updated["updated_at"]}
        if artifact:
            stage_entry["artifact"] = artifact
        if metadata:
            stage_entry.update(json.loads(json.dumps(metadata)))
        updated.setdefault("stages", {})[stage] = stage_entry
    return updated


def record_stage(state: dict[str, Any], stage: str, artifact: str) -> dict[str, Any]:
    updated = json.loads(json.dumps(state))
    updated["revision"] = int(updated.get("revision", 0)) + 1
    updated["updated_at"] = utc_now()
    updated.setdefault("stages", {})[stage] = {
        "status": "passed",
        "updated_at": updated["updated_at"],
        "artifact": artifact,
    }
    return updated


def invalidate_to(
    state: dict[str, Any],
    target: str,
    *,
    stage: str,
    reason: str,
    artifact: str | None = None,
) -> dict[str, Any]:
    """Roll a job back after an approved artifact becomes stale.

    Normal transitions remain forward-only. This explicit invalidation path preserves the
    previous stage metadata for audit while marking it unusable.
    """
    current = str(state.get("state"))
    if current in TERMINAL_STATES or current not in STATES or target not in STATES:
        raise ValueError(f"Invalid state invalidation: {current} -> {target}")
    if STATES.index(target) > STATES.index(current):
        raise ValueError(f"Invalid state invalidation: {current} -> {target}")
    updated = json.loads(json.dumps(state))
    updated["state"] = target
    updated["revision"] = int(updated.get("revision", 0)) + 1
    updated["updated_at"] = utc_now()
    previous = updated.setdefault("stages", {}).get(stage, {})
    stage_entry = json.loads(json.dumps(previous)) if isinstance(previous, dict) else {}
    stage_entry.update({
        "status": "invalidated",
        "updated_at": updated["updated_at"],
        "reason": reason,
    })
    if artifact:
        stage_entry["artifact"] = artifact
    updated["stages"][stage] = stage_entry
    return updated


def append_event(events_path: Path, event: dict[str, Any]) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": utc_now(), **event}
    with events_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def artifact_record(repo_root: Path, path: Path) -> dict[str, str]:
    return {"path": repo_relative(repo_root, path), "sha256": sha256_file(path)}


def write_state(path: Path, state: dict[str, Any]) -> None:
    write_json_atomic(path, state)
