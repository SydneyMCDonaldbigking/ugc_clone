from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ugc_pipeline.io import load_json, resolve_repo_path, write_json_atomic


class IoTests(unittest.TestCase):
    def test_atomic_json_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested/state.json"
            write_json_atomic(path, {"state": "created"})
            self.assertEqual(load_json(path), {"state": "created"})

    def test_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                resolve_repo_path(root, "../outside.json", must_exist=False)


if __name__ == "__main__":
    unittest.main()
