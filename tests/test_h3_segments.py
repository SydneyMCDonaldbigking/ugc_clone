from __future__ import annotations

import copy
import unittest
from pathlib import Path

from ugc_pipeline.h3_plan import load_h3_clip_plan
from ugc_pipeline.h3_segments import validate_h3_segments
from ugc_pipeline.io import load_json, resolve_repo_path


ROOT = Path(__file__).resolve().parents[1]


class H3SegmentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = load_json(ROOT / "inputs/crown_almond_bis/job.shot-for-shot.en.json")
        self.shot_plan = load_json(ROOT / self.job["shot_plan"])
        self.request_path = resolve_repo_path(ROOT, self.job["keyframe_request"])
        self.request = load_json(self.request_path)
        self.ready = load_json(self.request_path.parent / "READY.json")
        self.h3_plan = load_h3_clip_plan(ROOT, self.job, self.request)
        self.segments = load_json(ROOT / self.job["h3_segments"])

    def validate(self, segments: object) -> None:
        validate_h3_segments(
            segments,
            ROOT,
            self.job,
            self.shot_plan,
            self.request,
            self.request_path,
            self.ready,
            self.h3_plan,
        )

    def test_current_segments_match_deterministic_compiler(self) -> None:
        self.validate(self.segments)

    def test_changed_prompt_is_rejected(self) -> None:
        segments = copy.deepcopy(self.segments)
        segments[0]["prompt"] += " changed"

        with self.assertRaisesRegex(ValueError, r"segments\[0\]\.prompt"):
            self.validate(segments)

    def test_changed_picture_order_is_rejected(self) -> None:
        segments = copy.deepcopy(self.segments)
        segments[0]["images"][0], segments[0]["images"][1] = (
            segments[0]["images"][1],
            segments[0]["images"][0],
        )

        with self.assertRaisesRegex(ValueError, r"segments\[0\]\.images\[0\]"):
            self.validate(segments)

    def test_fish_grouped_segments_match_scene_locked_compiler(self) -> None:
        job = load_json(ROOT / "inputs/fish_glass/job.en.json")
        shot_plan = load_json(ROOT / job["shot_plan"])
        request_path = resolve_repo_path(ROOT, job["keyframe_request"])
        request = load_json(request_path)
        ready = load_json(request_path.parent / "READY.json")
        h3_plan = load_h3_clip_plan(ROOT, job, request)
        segments = load_json(ROOT / job["h3_segments"])

        validate_h3_segments(
            segments,
            ROOT,
            job,
            shot_plan,
            request,
            request_path,
            ready,
            h3_plan,
        )
        self.assertEqual(len(segments), 10)
        self.assertNotEqual(segments[3]["id"], segments[4]["id"])
        self.assertNotEqual(segments[7]["id"], segments[8]["id"])


if __name__ == "__main__":
    unittest.main()
