from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ugc_pipeline.io import load_json, write_json_atomic
from ugc_pipeline.preflight import quarantine_ready, validate_render_preflight


ROOT = Path(__file__).resolve().parents[1]


class PreflightTests(unittest.TestCase):
    def test_current_render_queue_passes_without_integrity_drift(self) -> None:
        for relative_job in (
            "inputs/crown_almond_bis/job.en.json",
            "inputs/fish_glass/job.en.json",
        ):
            with self.subTest(job=relative_job):
                result, report, changes = validate_render_preflight(
                    ROOT / relative_job,
                    ROOT,
                    actor="test",
                )
                self.assertTrue(result.ok, result.issues)
                self.assertEqual(report["status"], "pass")
                self.assertEqual(changes, [])

    def test_quarantine_is_recoverable_and_records_actor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            keyframe_dir = repo_root / "work/demo/keyframes"
            keyframe_dir.mkdir(parents=True)
            write_json_atomic(keyframe_dir / "REQUEST.json", {"segments": {}})
            ready_path = keyframe_dir / "READY.json"
            write_json_atomic(ready_path, {"schema": "keyframe-ready/v1"})
            state_path = repo_root / "work/demo/state.en.json"
            write_json_atomic(
                state_path,
                {
                    "schema": "job-state/v1",
                    "job_id": "demo",
                    "state": "keyframes_ready",
                    "revision": 2,
                    "stages": {"keyframes": {"status": "passed"}},
                },
            )
            job = {
                "job_id": "demo",
                "keyframe_request": "work/demo/keyframes/REQUEST.json",
                "state_file": "work/demo/state.en.json",
                "events_file": "work/demo/events.en.jsonl",
            }
            changes = [{"path": "work/demo/keyframes/seg01.png", "status": "changed"}]

            backup = quarantine_ready(
                repo_root,
                job,
                actor="claude",
                changes=changes,
                reason="test drift",
            )

            self.assertIsNotNone(backup)
            self.assertFalse(ready_path.exists())
            self.assertTrue(backup.is_file())
            state = load_json(state_path)
            self.assertEqual(state["state"], "awaiting_keyframes")
            self.assertEqual(state["stages"]["keyframes"]["status"], "invalidated")
            event = json.loads((repo_root / "work/demo/events.en.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(event["actor"], "claude")
            self.assertEqual(event["changed_artifacts"], changes)

    def test_missing_ready_still_rolls_state_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            keyframe_dir = repo_root / "work/demo/keyframes"
            keyframe_dir.mkdir(parents=True)
            write_json_atomic(keyframe_dir / "REQUEST.json", {"segments": {}})
            state_path = repo_root / "work/demo/state.en.json"
            write_json_atomic(
                state_path,
                {
                    "schema": "job-state/v1",
                    "job_id": "demo",
                    "state": "keyframes_ready",
                    "revision": 2,
                    "stages": {"keyframes": {"status": "passed"}},
                },
            )
            job = {
                "job_id": "demo",
                "keyframe_request": "work/demo/keyframes/REQUEST.json",
                "state_file": "work/demo/state.en.json",
                "events_file": "work/demo/events.en.jsonl",
            }

            backup = quarantine_ready(
                repo_root,
                job,
                actor="codex",
                changes=[{"path": "work/demo/keyframes/READY.json", "status": "missing"}],
                reason="READY deleted",
            )

            self.assertIsNone(backup)
            self.assertEqual(load_json(state_path)["state"], "awaiting_keyframes")


if __name__ == "__main__":
    unittest.main()
