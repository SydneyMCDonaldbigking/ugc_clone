from __future__ import annotations

import unittest

from scripts.check_shot_rhythm import expected_cut_times, match_cut_times


class ShotRhythmTests(unittest.TestCase):
    def test_extracts_internal_cut_times_only(self) -> None:
        segment = {
            "timed_shots": [
                {"clip_start_seconds": 0.0},
                {"clip_start_seconds": 0.967},
                {"clip_start_seconds": 2.233},
            ]
        }
        self.assertEqual(expected_cut_times(segment), [0.967, 2.233])

    def test_matches_nearby_cuts_and_reports_signed_delta(self) -> None:
        result = match_cut_times([0.967, 2.233], [0.94, 2.3], 0.1)

        self.assertEqual(result["missed"], [])
        self.assertEqual(result["extra"], [])
        self.assertEqual(result["matches"][0]["delta_seconds"], -0.027)
        self.assertEqual(result["matches"][1]["delta_seconds"], 0.067)

    def test_reports_missing_and_unplanned_cuts(self) -> None:
        result = match_cut_times([1.0, 2.0], [1.04, 2.5], 0.1)

        self.assertEqual(result["missed"], [2.0])
        self.assertEqual(result["extra"], [2.5])


if __name__ == "__main__":
    unittest.main()
