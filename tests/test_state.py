from __future__ import annotations

import unittest

from ugc_pipeline.state import can_transition, has_reached, initial_state, invalidate_to, record_stage, transition


class StateTests(unittest.TestCase):
    def test_forward_transition(self) -> None:
        state = initial_state("job-1")
        updated = transition(state, "awaiting_keyframes", stage="request", artifact="REQUEST.json")
        self.assertEqual(updated["state"], "awaiting_keyframes")
        self.assertEqual(updated["revision"], 2)

    def test_backward_transition_is_rejected(self) -> None:
        state = initial_state("job-1")
        state = transition(state, "awaiting_keyframes")
        with self.assertRaises(ValueError):
            transition(state, "scripts_ready")

    def test_has_reached_supports_idempotence(self) -> None:
        self.assertTrue(has_reached("awaiting_keyframes", "scripts_ready"))
        self.assertFalse(has_reached("scripts_ready", "awaiting_keyframes"))

    def test_terminal_state_cannot_advance(self) -> None:
        self.assertFalse(can_transition("blocked", "approved"))

    def test_record_stage_refreshes_artifact_without_changing_state(self) -> None:
        state = transition(initial_state("job-1"), "awaiting_keyframes")
        updated = record_stage(state, "keyframe_request", "work/job/keyframes/REQUEST.json")
        self.assertEqual(updated["state"], "awaiting_keyframes")
        self.assertEqual(
            updated["stages"]["keyframe_request"]["artifact"],
            "work/job/keyframes/REQUEST.json",
        )

    def test_explicit_invalidation_can_roll_ready_job_back(self) -> None:
        state = transition(
            initial_state("job-1"),
            "keyframes_ready",
            stage="keyframes",
            artifact="work/job/keyframes/READY.json",
            metadata={"integrity": {"schema": "artifact-integrity/v1", "files": {}}},
        )
        updated = invalidate_to(
            state,
            "awaiting_keyframes",
            stage="keyframes",
            reason="keyframe hash changed",
        )
        self.assertEqual(updated["state"], "awaiting_keyframes")
        self.assertEqual(updated["stages"]["keyframes"]["status"], "invalidated")
        self.assertEqual(updated["stages"]["keyframes"]["reason"], "keyframe hash changed")
        self.assertIn("integrity", updated["stages"]["keyframes"])


if __name__ == "__main__":
    unittest.main()
