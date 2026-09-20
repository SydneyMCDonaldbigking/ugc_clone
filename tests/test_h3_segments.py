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


if __name__ == "__main__":
    unittest.main()
