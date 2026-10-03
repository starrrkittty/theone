import unittest

from training.extend_numeric_suffix_split import extend_split


class ExtendNumericSuffixSplitTests(unittest.TestCase):
    def test_extends_without_moving_existing_subjects(self):
        result = extend_split(
            {"train": ["p05"], "validation": ["p06"], "test": ["p08"]},
            ["arm_wave_000", "arm_wave_016", "arm_wave_017", "p05"],
            15,
            {16},
            {17, 18, 19},
        )
        self.assertEqual(result["train"], ["arm_wave_000", "p05"])
        self.assertEqual(result["validation"], ["arm_wave_016", "p06"])
        self.assertEqual(result["test"], ["arm_wave_017", "p08"])

    def test_rejects_unassigned_suffix(self):
        with self.assertRaisesRegex(ValueError, "No split rule"):
            extend_split(
                {"train": [], "validation": [], "test": []},
                ["arm_wave_020"],
                15,
                {16},
                {17, 18, 19},
            )


if __name__ == "__main__":
    unittest.main()
