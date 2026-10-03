import unittest

import numpy as np

from training.evaluate_stgcn import remap_evaluation_targets


class EvaluateStgcnRemapTests(unittest.TestCase):
    def test_shared_labels_are_filtered_and_remapped_by_name(self):
        targets = np.asarray([0, 1, 2, 0], dtype=np.int64)
        indices, remapped = remap_evaluation_targets(
            targets,
            ["unknown", "plank", "jumping_jack"],
            ["jumping_jack", "unknown"],
            np.arange(4, dtype=np.int64),
        )
        self.assertEqual(indices.tolist(), [0, 2, 3])
        self.assertEqual(remapped[indices].tolist(), [1, 0, 1])

    def test_requested_label_must_exist_in_both_tables(self):
        with self.assertRaisesRegex(ValueError, "missing from model"):
            remap_evaluation_targets(
                np.asarray([0]), ["plank"], ["unknown"], np.asarray([0]), ["plank"]
            )


if __name__ == "__main__":
    unittest.main()
