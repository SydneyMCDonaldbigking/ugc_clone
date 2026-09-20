from __future__ import annotations

import copy
import unittest
from pathlib import Path

from ugc_pipeline.io import load_json
from ugc_pipeline.validation import (
    validate_job,
    contains_cjk,
    count_words,
    validate_bundle,
    validate_keyframe_coverage,
    validate_keyframe_request,
    validate_keyframe_qc,
    validate_product,
    validate_ready_against_request,
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

    def test_silent_script_accepts_empty_dialogue_with_visual_direction(self) -> None:
        script = copy.deepcopy(self.script)
        script["audio_mode"] = "silent"
        for line in script["lines"]:
            line["text"] = ""
            line["claims"] = []
            line["visual_direction"] = "Replicate the approved camera and product action without spoken dialogue."
        result = validate_script(script, self.beats, self.product)
        self.assertTrue(result.ok, result.issues)

    def test_silent_script_rejects_spoken_text(self) -> None:
        script = copy.deepcopy(self.script)
        script["audio_mode"] = "silent"
        for line in script["lines"]:
            line["visual_direction"] = "Replicate the approved camera and product action."
        result = validate_script(script, self.beats, self.product)
        self.assertIn("script.silent_text", {issue.code for issue in result.errors})

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

    def test_qc_dimensions_must_match_png(self) -> None:
        qc_path = ROOT / "work/a2_test/keyframes/QC.json"
        qc = copy.deepcopy(load_json(qc_path))
        qc["segments"]["1"]["width"] += 1
        result = validate_keyframe_qc(qc, qc_path, self.request)
        self.assertIn("qc.dimensions", {issue.code for issue in result.errors})

    def test_ready_output_must_match_request(self) -> None:
        ready = {
            "job": self.request["job"],
            "variant_id": self.request["variant_id"],
            "source_job_id": self.request["source_job_id"],
            "segments": {
                segment_id: {
                    "keyframe": requested["output"],
                    "extra_refs": [
                        path
                        for path, role in requested["reference_roles"].items()
                        if role == "product_identity"
                    ],
                }
                for segment_id, requested in self.request["segments"].items()
            },
        }
        ready["segments"]["1"]["keyframe"] = "seg02.png"
        result = validate_ready_against_request(ready, self.request, self.job)
        self.assertIn("ready.output", {issue.code for issue in result.errors})

    def test_source_video_frame_reference_fails(self) -> None:
        request = copy.deepcopy(self.request)
        anchor = "work/a2_test/video_analysis/anchor_s01.jpg"
        request["segments"]["1"]["references"].append(anchor)
        request["segments"]["1"]["reference_roles"][anchor] = "composition_only"
        codes = {issue.code for issue in validate_keyframe_request(request, ROOT, self.product).errors}
        self.assertIn("reference.source_frame", codes)
        self.assertIn("reference.role_forbidden", codes)

    def test_source_video_frame_in_shot_plan_fails(self) -> None:
        plan = copy.deepcopy(self.shot_plan)
        plan["segments"][0]["references"].append("work/a2_test/video_analysis/anchor_s01.jpg")
        codes = {issue.code for issue in validate_shot_plan(plan, self.script).errors}
        self.assertIn("reference.source_frame", codes)

    def test_timed_subshot_may_be_shorter_than_h3_clip_minimum(self) -> None:
        plan = copy.deepcopy(self.shot_plan)
        segment = next(s for s in plan["segments"] if s.get("subshots"))
        segment["subshots"][0]["duration_seconds"] = 3.5
        segment["subshots"][1]["duration_seconds"] = 1.5
        codes = {issue.code for issue in validate_shot_plan(plan, self.script).errors}
        self.assertNotIn("shots.subshot_duration", codes)

    def test_subshot_durations_must_fill_segment(self) -> None:
        plan = copy.deepcopy(self.shot_plan)
        segment = next(s for s in plan["segments"] if s.get("subshots"))
        segment["subshots"][0]["duration_seconds"] = 2
        codes = {issue.code for issue in validate_shot_plan(plan, self.script).errors}
        self.assertIn("shots.subshot_total", codes)

    def test_generated_keyframe_reference_fails(self) -> None:
        request = copy.deepcopy(self.request)
        seg = request["segments"]["2"]
        generated = "work/a2_test/keyframes/seg01.png"
        seg["references"][0] = generated
        seg["reference_roles"] = {generated: "presenter_identity", seg["references"][1]: "product_identity"}
        codes = {issue.code for issue in validate_keyframe_request(request, ROOT, self.product).errors}
        self.assertIn("reference.generated", codes)

    def test_missing_first_frame_fails(self) -> None:
        plan = copy.deepcopy(self.shot_plan)
        segment = next(s for s in plan["segments"] if not s.get("subshots"))
        segment.pop("first_frame")
        codes = {issue.code for issue in validate_shot_plan(plan, self.script).errors}
        self.assertIn("shots.first_frame", codes)

    def test_product_must_keep_reference_view(self) -> None:
        request = copy.deepcopy(self.request)
        request["segments"]["4"]["product_placement"]["orientation"] = "tilted_for_pour"
        codes = {issue.code for issue in validate_keyframe_request(request, ROOT, self.product).errors}
        self.assertIn("request.product_orientation", codes)

    def test_presenter_reference_must_be_job_master(self) -> None:
        request = copy.deepcopy(self.request)
        seg = request["segments"]["1"]
        other = "target_A2_2.png"
        seg["references"] = [other, "target_A2_1.png"]
        seg["reference_roles"] = {other: "presenter_identity", "target_A2_1.png": "product_identity"}
        result = validate_keyframe_coverage(request, self.shot_plan, self.job, ROOT)
        self.assertIn("request.presenter_master", {issue.code for issue in result.errors})

    def test_changed_master_after_registration_fails(self) -> None:
        job = copy.deepcopy(self.job)
        job["presenter"]["approval"] = {"sha256": "0" * 64, "approved_by": "codex"}
        failed = validate_keyframe_coverage(self.request, self.shot_plan, job, ROOT)
        self.assertIn("presenter.approval", {issue.code for issue in failed.errors})
    def test_accent_must_anchor_to_dialogue(self) -> None:
        plan = copy.deepcopy(self.shot_plan)
        plan["segments"][0]["accents"] = [{"at": "not in the line", "reaction": "nods"}]
        codes = {issue.code for issue in validate_shot_plan(plan, self.script).errors}
        self.assertIn("shots.accent_anchor", codes)

    def test_intention_is_required(self) -> None:
        plan = copy.deepcopy(self.shot_plan)
        del plan["segments"][0]["intention"]
        result = validate_shot_plan(plan, self.script)
        self.assertIn("required.string", {issue.code for issue in result.errors})

    def test_job_needs_a_finished_reference_archive(self) -> None:
        job = copy.deepcopy(self.job)
        job["reference_archive"] = "work/a2_test/keyframes"  # exists, but holds no ANALYSIS/TIMELINE
        codes = {issue.code for issue in validate_job(job, ROOT).errors}
        self.assertIn("reference.archive_incomplete", codes)
        del job["reference_archive"]
        self.assertIn("reference.archive", {issue.code for issue in validate_job(job, ROOT).errors})

    def test_presenter_mode_is_required(self) -> None:
        job = copy.deepcopy(self.job)
        job["presenter"].pop("mode")
        codes = {issue.code for issue in validate_keyframe_coverage(self.request, self.shot_plan, job, ROOT).errors}
        self.assertIn("presenter.mode", codes)

    def test_hands_only_forbids_presenter_references_and_template(self) -> None:
        job = copy.deepcopy(self.job)
        job["presenter"] = {"mode": "hands_only"}
        codes = {issue.code for issue in validate_keyframe_coverage(self.request, self.shot_plan, job, ROOT).errors}
        self.assertIn("request.presenter_forbidden", codes)  # the a2 sample binds a presenter master
        self.assertIn("request.template_mode", codes)        # and uses the on-camera template

    def test_camera_is_required_per_keyframe(self) -> None:
        plan = copy.deepcopy(self.shot_plan)
        segment = next(s for s in plan["segments"] if not s.get("subshots"))
        segment["camera"] = "close-up"
        codes = {issue.code for issue in validate_shot_plan(plan, self.script).errors}
        self.assertIn("shots.camera", codes)


if __name__ == "__main__":
    unittest.main()
