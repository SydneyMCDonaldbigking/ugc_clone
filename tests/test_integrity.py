from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from ugc_pipeline.integrity import INTEGRITY_SCHEMA, compare_integrity, compare_sealed_snapshot


class IntegrityTests(unittest.TestCase):
    def test_changed_file_is_reported(self) -> None:
        expected = {
            "schema": INTEGRITY_SCHEMA,
            "digest": "old",
            "files": {"work/job/keyframes/seg01.png": "a"},
        }
        current = {
            "schema": INTEGRITY_SCHEMA,
            "digest": "new",
            "files": {"work/job/keyframes/seg01.png": "b"},
        }
        changes = compare_integrity(expected, current)
        self.assertEqual(changes[0]["path"], "work/job/keyframes/seg01.png")
        self.assertEqual(changes[0]["status"], "changed")

    def test_missing_snapshot_is_reported(self) -> None:
        current = {"schema": INTEGRITY_SCHEMA, "digest": "new", "files": {}}
        changes = compare_integrity(None, current)
        self.assertEqual(changes[0]["path"], "<snapshot>")

    def test_deleted_sealed_file_is_reported_without_loading_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = {
                "schema": INTEGRITY_SCHEMA,
                "digest": "old",
                "files": {"work/demo/missing.json": "a" * 64},
            }
            changes = compare_sealed_snapshot(Path(temp_dir), expected)
            self.assertEqual(changes[0]["path"], "work/demo/missing.json")
            self.assertEqual(changes[0]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
