import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class SchemaContractTests(unittest.TestCase):
    def test_new_english_keyframe_request_allows_no_source_render(self):
        schema = json.loads(
            (REPO_ROOT / "schemas" / "keyframe-request.schema.json").read_text(encoding="utf-8")
        )
        alternatives = schema["properties"]["source_job_id"]["oneOf"]
        self.assertEqual({item["type"] for item in alternatives}, {"string", "null"})

    def test_source_video_composition_role_is_not_declared(self):
        schema = json.loads(
            (REPO_ROOT / "schemas" / "keyframe-request.schema.json").read_text(encoding="utf-8")
        )
        roles = schema["properties"]["segments"]["additionalProperties"]["properties"][
            "reference_roles"
        ]["additionalProperties"]["enum"]
        self.assertNotIn("composition_only", roles)

    def test_scene_pack_contract_declares_three_canonical_views(self):
        schema = json.loads(
            (REPO_ROOT / "schemas" / "keyframe-request.schema.json").read_text(encoding="utf-8")
        )
        requirement = schema["properties"]["scene_pack_requirements"]["additionalProperties"]
        self.assertEqual(
            set(requirement["properties"]["views"]["required"]),
            {"eye_level", "oblique_45", "overhead_90"},
        )

    def test_scene_qc_hard_locks_only_the_table_surface(self):
        schema = json.loads(
            (REPO_ROOT / "schemas" / "keyframe-qc.schema.json").read_text(encoding="utf-8")
        )
        review = schema["properties"]["scene_consistency"]["additionalProperties"]["properties"]
        self.assertEqual(review["hard_match_fields"]["const"], ["surface"])
        self.assertEqual(review["variation_policy"]["const"], "closeup_flexible")

    def test_integrity_snapshot_schema_pins_sha256_values(self):
        schema = json.loads(
            (REPO_ROOT / "schemas" / "artifact-integrity.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["properties"]["schema"]["const"], "artifact-integrity/v1")
        self.assertEqual(
            schema["properties"]["files"]["additionalProperties"]["pattern"],
            "^[0-9a-f]{64}$",
        )

    def test_preflight_report_schema_has_explicit_pass_fail_status(self):
        schema = json.loads(
            (REPO_ROOT / "schemas" / "preflight-report.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["properties"]["schema"]["const"], "render-preflight/v1")
        self.assertEqual(set(schema["properties"]["status"]["enum"]), {"pass", "failed"})


if __name__ == "__main__":
    unittest.main()
