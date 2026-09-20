from __future__ import annotations

import unittest

from scripts.build_shot_map import build_shot_map


class ShotMapTests(unittest.TestCase):
    def test_preserves_every_cut_and_exact_duration(self) -> None:
        document = build_shot_map(
            reference_video="references/demo/source.mp4",
            duration_seconds=2.233,
            cuts=[{"t": 0.1}, {"t": 0.967}],
            words=[],
        )

        self.assertEqual(document["cut_times_seconds"], [0.1, 0.967])
        self.assertEqual(len(document["shots"]), 3)
        self.assertAlmostEqual(
            sum(shot["source_edit_duration_seconds"] for shot in document["shots"]),
            2.233,
            places=3,
        )

    def test_deduplicates_and_sorts_cut_times(self) -> None:
        document = build_shot_map(
            reference_video="references/demo/source.mp4",
            duration_seconds=3,
            cuts=[{"t": 2}, {"t": 1}, {"t": 1}, {"t": 0}, {"t": 3}],
        )

        self.assertEqual(document["cut_times_seconds"], [1.0, 2.0])
        self.assertEqual([shot["id"] for shot in document["shots"]], ["SH001", "SH002", "SH003"])

    def test_rejects_invalid_duration(self) -> None:
        with self.assertRaises(ValueError):
            build_shot_map(reference_video="demo.mp4", duration_seconds=0, cuts=[])


if __name__ == "__main__":
    unittest.main()
