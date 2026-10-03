import unittest

import numpy as np

from training.merge_datasets import merged_label_order, remap_targets


class MergeDatasetsTests(unittest.TestCase):
    def test_union_preserves_first_dataset_order(self):
        datasets = [
            {"labels": np.asarray(["squat", "unknown"])},
            {"labels": np.asarray(["plank", "unknown"])},
        ]
        self.assertEqual(
            merged_label_order(datasets), ["squat", "unknown", "plank"]
        )

    def test_targets_are_remapped_by_label_name(self):
        remapped = remap_targets(
            np.asarray([0, 1, 0]),
            ["plank", "unknown"],
            ["squat", "unknown", "plank"],
        )
        np.testing.assert_array_equal(remapped, np.asarray([2, 1, 2]))

    def test_invalid_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside its label table"):
            remap_targets(np.asarray([2]), ["plank"], ["plank"])


if __name__ == "__main__":
    unittest.main()
