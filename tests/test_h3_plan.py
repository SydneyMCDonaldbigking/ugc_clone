from __future__ import annotations

import copy
import unittest
from pathlib import Path

from ugc_pipeline.h3_plan import validate_h3_clip_plan
from ugc_pipeline.io import load_json


ROOT = Path(__file__).resolve().parents[1]


class H3ClipPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = load_json(ROOT / "inputs/fish_glass/job.en.json")
        self.request = load_json(ROOT / self.job["keyframe_request"])
        self.plan = load_json(ROOT / self.job["h3_clip_plan"])

    def test_fish_keyframes_compile_to_six_multi_picture_clips(self) -> None:
        validate_h3_clip_plan(self.plan, self.job, self.request, ROOT)

        self.assertEqual(len(self.request["segments"]), 13)
        self.assertEqual(len(self.plan["clips"]), 6)
        self.assertEqual(
            [keyframe for clip in self.plan["clips"] for keyframe in clip["keyframe_ids"]],
            list(self.request["segments"]),
        )
        for clip in self.plan["clips"]:
            total_pictures = len(clip["keyframe_ids"]) + int(clip["product_reference"] is not None)
            self.assertIn(total_pictures, (2, 3))

    def test_picture_cues_must_be_contiguous(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["clips"][0]["cues"][1]["start_seconds"] += 0.1

        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_h3_clip_plan(plan, self.job, self.request, ROOT)

    def test_three_generated_keyframes_do_not_add_product_reference(self) -> None:
        three_frame_clips = [clip for clip in self.plan["clips"] if len(clip["keyframe_ids"]) == 3]

        self.assertTrue(three_frame_clips)
        self.assertTrue(all(clip["product_reference"] is None for clip in three_frame_clips))


class ShotForShotH3ClipPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = load_json(ROOT / "inputs/crown_almond_bis/job.shot-for-shot.en.json")
        self.request = load_json(ROOT / self.job["keyframe_request"])
        self.plan = load_json(ROOT / self.job["h3_clip_plan"])

    def test_current_plan_matches_every_approved_microshot(self) -> None:
        validate_h3_clip_plan(self.plan, self.job, self.request, ROOT)

    def test_shifted_internal_cut_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["clips"][0]["timed_shots"][0]["end_seconds"] += 0.1
        plan["clips"][0]["timed_shots"][1]["start_seconds"] += 0.1

        with self.assertRaisesRegex(ValueError, "timing differs from the approved shot plan"):
            validate_h3_clip_plan(plan, self.job, self.request, ROOT)

    def test_changed_picture_assignment_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["clips"][0]["timed_shots"][0]["picture"] = 2

        with self.assertRaisesRegex(ValueError, "Picture differs from the approved shot plan"):
            validate_h3_clip_plan(plan, self.job, self.request, ROOT)


if __name__ == "__main__":
    unittest.main()
