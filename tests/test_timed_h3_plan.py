from __future__ import annotations

import unittest

from scripts.build_timed_h3_plan import build_h3_clip_plan, materialize
from scripts.build_timed_h3_prompts import render_prompt


class TimedH3PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shot_map = {
            "shots": [
                {"id": "SH001", "source_start_seconds": 0.0, "source_end_seconds": 0.5},
                {"id": "SH002", "source_start_seconds": 0.5, "source_end_seconds": 1.5},
            ]
        }
        self.script = {
            "language": "en-AU",
            "variant_id": "v001",
            "lines": [{"segment": 1, "text": "A fitted English line."}],
        }
        frame = {
            "keyframe_id": "1a",
            "role": "opening",
            "product_reference": "inputs/demo/product.jpg",
            "first_frame": "A hand holds the target packet above a plate.",
            "camera": "close-up | high angle | handheld | packet centred",
            "performance": "A natural hand prepares to move.",
            "checks": ["The target packet is visible."],
        }
        self.spec = {
            "schema": "timed-h3-spec/v1",
            "job": "demo",
            "pipeline_job_id": "demo_en",
            "shot_map": "work/demo/shot_map.json",
            "output_dir": "work/demo/keyframes",
            "prompt_template": "templates/keyframe_prompt.hands-only.en.txt",
            "scene_locks": {
                "pale-tabletop-daylight": {
                    "setting": "A bright home snack table.",
                    "surface": "Pale matte natural wood with fine straight grain.",
                    "backdrop": "A softly blurred warm-white home background.",
                    "lighting": "Soft daylight from camera left.",
                    "palette": "Pale wood, warm ivory and clean white.",
                    "fixed_props": "One shallow warm-ivory plate when tableware is visible.",
                }
            },
            "clips": [{
                "segment": 1,
                "scene_id": "pale-tabletop-daylight",
                "render_duration_seconds": 2,
                "subject": "The target product.",
                "action": "Show two fast views.",
                "performance": "Natural hands-only motion.",
                "intention": "Preserve the source rhythm.",
                "reference_frames": [frame],
                "timed_shots": [
                    {"source_shot_id": "SH001", "picture_keyframe_id": "1a", "shot_type": "flash", "direction": "show the packet"},
                    {"source_shot_id": "SH002", "picture_keyframe_id": "1a", "shot_type": "plate", "direction": "hard cut to the plate"},
                ],
            }],
        }

    def test_groups_microshots_into_one_h3_clip(self) -> None:
        plan, request = materialize(self.shot_map, self.script, self.spec)

        self.assertEqual(len(plan["segments"]), 1)
        self.assertEqual(len(plan["segments"][0]["timed_shots"]), 2)
        self.assertEqual(list(request["segments"]), ["1a"])
        self.assertEqual(plan["segments"][0]["source_edit_duration_seconds"], 1.5)
        self.assertEqual(plan["segments"][0]["timed_shots"][1]["clip_start_seconds"], 0.5)
        self.assertEqual(request["background_lock_policy"], "scene_pack_v1")
        self.assertEqual(request["segments"]["1a"]["scene_view"], "oblique_45")
        self.assertEqual(
            set(request["scene_pack_requirements"]["pale-tabletop-daylight"]["views"]),
            {"eye_level", "oblique_45", "overhead_90"},
        )

    def test_rejects_incomplete_background_contract(self) -> None:
        del self.spec["scene_locks"]["pale-tabletop-daylight"]["lighting"]
        with self.assertRaisesRegex(ValueError, "lighting"):
            materialize(self.shot_map, self.script, self.spec)

    def test_rejects_missing_source_microshot(self) -> None:
        self.spec["clips"][0]["timed_shots"] = self.spec["clips"][0]["timed_shots"][:1]
        with self.assertRaises(ValueError):
            materialize(self.shot_map, self.script, self.spec)

    def test_builds_one_canonical_h3_clip_with_all_internal_cuts(self) -> None:
        plan, _ = materialize(self.shot_map, self.script, self.spec)
        h3_plan = build_h3_clip_plan(plan, self.spec)

        self.assertEqual(len(h3_plan["clips"]), 1)
        self.assertEqual(h3_plan["clips"][0]["scene_id"], "pale-tabletop-daylight")
        self.assertEqual(h3_plan["background_lock_policy"], "scene_pack_v1")
        self.assertEqual(
            h3_plan["clips"][0]["scene_lock"],
            self.spec["scene_locks"]["pale-tabletop-daylight"],
        )
        self.assertTrue(
            all(
                cue["scene_id"] == "pale-tabletop-daylight"
                for cue in h3_plan["clips"][0]["cues"]
            )
        )
        self.assertEqual(len(h3_plan["clips"][0]["keyframe_ids"]), 1)
        self.assertEqual(len(h3_plan["clips"][0]["timed_shots"]), 2)
        self.assertEqual(h3_plan["clips"][0]["timed_shots"][1]["start_seconds"], 0.5)

    def test_accepts_current_fifteen_second_server_limit(self) -> None:
        self.spec["clips"][0]["render_duration_seconds"] = 15

        plan, _ = materialize(self.shot_map, self.script, self.spec)

        self.assertEqual(plan["segments"][0]["duration_seconds"], 15)

    def test_h3_prompt_contains_internal_timing_and_cuts(self) -> None:
        plan, _ = materialize(self.shot_map, self.script, self.spec)
        prompt = render_prompt(
            plan["segments"][0], ["1a"], 2, None, {"1a": "present"}
        )

        self.assertIn("0-0.5 seconds — start on <Picture 1>", prompt)
        self.assertIn("0.5-1.5 seconds — hard cut to a new shot based on <Picture 1>", prompt)
        self.assertIn("Hard cuts occur only at the listed times", prompt)
        self.assertNotIn("No cuts, no scene change", prompt)

    def test_three_generated_pictures_need_no_fourth_product_picture(self) -> None:
        segment = {
            "scene_id": "pale-tabletop-daylight",
            "scene_lock": self.spec["scene_locks"]["pale-tabletop-daylight"],
            "action": "Show three deliberate compositions in one clip.",
            "performance": "Natural hands-only motion.",
            "intention": "Preserve the source rhythm.",
            "source_edit_duration_seconds": 5,
            "duration_seconds": 5,
            "timed_shots": [
                {
                    "picture_keyframe_id": "a",
                    "clip_start_seconds": 0,
                    "clip_end_seconds": 1.6,
                    "shot_type": "opening",
                    "direction": "establish the product",
                },
                {
                    "picture_keyframe_id": "b",
                    "clip_start_seconds": 1.6,
                    "clip_end_seconds": 3.4,
                    "shot_type": "insert",
                    "direction": "show the use action",
                },
                {
                    "picture_keyframe_id": "c",
                    "clip_start_seconds": 3.4,
                    "clip_end_seconds": 5,
                    "shot_type": "hero",
                    "direction": "finish on the result",
                },
            ],
        }

        prompt = render_prompt(
            segment,
            ["a", "b", "c"],
            None,
            None,
            {"a": "present", "b": "present", "c": "present"},
        )

        self.assertIn("<Picture 3>", prompt)
        self.assertIn("scene_id pale-tabletop-daylight", prompt)
        self.assertIn("surface: Pale matte natural wood", prompt)
        self.assertIn("background bokeh may vary", prompt)
        self.assertNotIn("<Picture 4>", prompt)
        self.assertNotIn("original product identity authority", prompt)

    def test_product_appears_only_in_its_source_timed_window(self) -> None:
        segment = {
            "scene_id": "pale-tabletop-daylight",
            "scene_lock": self.spec["scene_locks"]["pale-tabletop-daylight"],
            "action": "Start on food, then reveal the pack.",
            "performance": "Natural hands-only motion.",
            "intention": "Match the source reveal timing.",
            "source_edit_duration_seconds": 2,
            "duration_seconds": 2,
            "timed_shots": [
                {"picture": 1, "start_seconds": 0, "end_seconds": 1.2, "action": "food macro"},
                {"picture": 2, "start_seconds": 1.2, "end_seconds": 2, "action": "pack reveal"},
            ],
        }

        prompt = render_prompt(
            segment,
            ["food", "pack"],
            3,
            None,
            {"food": "absent", "pack": "present"},
        )

        self.assertIn("no retail package in its assigned source shots", prompt)
        self.assertIn("1.2-2 seconds", prompt)
        self.assertIn("All other windows contain only", prompt)


if __name__ == "__main__":
    unittest.main()
