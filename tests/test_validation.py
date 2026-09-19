from __future__ import annotations

import copy
import unittest
from pathlib import Path

from ugc_pipeline.io import load_json
from ugc_pipeline.validation import (
    contains_cjk,
    count_words,
    validate_bundle,
    validate_keyframe_coverage,
    validate_keyframe_request,
    validate_keyframe_qc,
    validate_product,
    validate_script,
    validate_shot_plan,
    validate_source_alignment,
)


ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "inputs/a2_test/job.en.json"


class EnglishValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.product = load_json(ROOT / "inputs/a2_test/product.en.json")
        self.beats = load_json(ROOT / "work/a2_test/beats.json")
        self.script = load_json(ROOT / "work/a2_test/variants/v001/script.en.json")
        self.job = load_json(ROOT / "inputs/a2_test/job.en.json")
        self.shot_plan = load_json(ROOT / "work/a2_test/variants/v001/shot_plan.json")
        self.request = load_json(ROOT / "work/a2_test/keyframes/REQUEST.json")

    def test_sample_bundle_passes(self) -> None:
        result, _ = validate_bundle(JOB, ROOT)
        self.assertTrue(result.ok, result.issues)

    def test_cjk_detection(self) -> None:
        self.assertTrue(contains_cjk("English text with 中文"))
        self.assertFalse(contains_cjk("English only"))

    def test_word_count_handles_contractions_and_hyphens(self) -> None:
        self.assertEqual(count_words("I'd buy a two-litre bottle."), 5)

    def test_chinese_target_line_fails(self) -> None:
        script = copy.deepcopy(self.script)
        script["lines"][0]["text"] = "This line contains 中文 text."
        result = validate_script(script, self.beats, self.product)
        self.assertIn("language.cjk", {issue.code for issue in result.errors})

    def test_unknown_claim_fails(self) -> None:
        script = copy.deepcopy(self.script)
        script["lines"][0]["claims"] = ["F404"]
        result = validate_script(script, self.beats, self.product)
        self.assertIn("claims.unknown", {issue.code for issue in result.errors})

    def test_missing_beat_fails(self) -> None:
        script = copy.deepcopy(self.script)
        script["lines"][0]["beats"] = ["B1", "B2"]
        result = validate_script(script, self.beats, self.product)
        self.assertIn("script.coverage", {issue.code for issue in result.errors})

    def test_overlong_line_fails(self) -> None:
        script = copy.deepcopy(self.script)
        script["lines"][0]["text"] = " ".join(["word"] * 30)
        result = validate_script(script, self.beats, self.product)
        self.assertIn("script.word_budget", {issue.code for issue in result.errors})

    def test_source_video_mismatch_fails(self) -> None:
        beats = copy.deepcopy(self.beats)
        beats["source"]["file"] = "wrong-video.mp4"
        result = validate_source_alignment(self.job, beats)
        self.assertIn("source.mismatch", {issue.code for issue in result.errors})

    def test_incomplete_keyframe_request_fails(self) -> None:
        request = copy.deepcopy(self.request)
        del request["segments"]["1"]
        result = validate_keyframe_coverage(request, self.shot_plan, self.job)
        self.assertIn("request.coverage", {issue.code for issue in result.errors})

    def test_missing_performance_direction_fails(self) -> None:
        shot_plan = copy.deepcopy(self.shot_plan)
        del shot_plan["segments"][0]["performance"]
        result = validate_shot_plan(shot_plan, self.script)
        self.assertIn("required.string", {issue.code for issue in result.errors})

    def test_product_handle_mismatch_fails(self) -> None:
        product = copy.deepcopy(self.product)
        product["visual_identity"]["handle"] = "built-in"
        result = validate_product(product)
        self.assertIn("visual_identity.handle", {issue.code for issue in result.errors})

    def test_handle_is_allowed_for_a_product_that_declares_it_consistently(self) -> None:
        product = copy.deepcopy(self.product)
        product["visual_identity"]["handle"] = "integrated side handle"
        product["visual_identity"]["forbidden_features"] = ["paper carton", "pump dispenser"]
        result = validate_product(product)
        self.assertNotIn("visual_identity.handle", {issue.code for issue in result.errors})

    def test_reference_roles_must_match_references(self) -> None:
        request = copy.deepcopy(self.request)
        del request["segments"]["4"]["reference_roles"]["target_A2_1.png"]
        result = validate_keyframe_request(request, ROOT, self.product)
        self.assertIn("request.reference_roles", {issue.code for issue in result.errors})

    def test_failed_keyframe_qc_blocks_ready(self) -> None:
        qc_path = ROOT / "work/a2_test/keyframes/QC.json"
        qc = load_json(qc_path)
        qc["result"] = "failed"
        result = validate_keyframe_qc(qc, qc_path, self.request)
        self.assertIn("qc.result", {issue.code for issue in result.errors})


if __name__ == "__main__":
    unittest.main()
