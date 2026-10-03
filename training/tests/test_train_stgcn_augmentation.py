import unittest

import numpy as np

from training.train_stgcn import LEFT_RIGHT_PAIRS, augment_window


class TrainAugmentationTests(unittest.TestCase):
    def test_augmentation_preserves_shape_and_float_type(self):
        sample = np.zeros((30, 17, 3), dtype=np.float32)
        result = augment_window(sample, np.random.default_rng(7))
        self.assertEqual(result.shape, sample.shape)
        self.assertEqual(result.dtype, np.float32)
        self.assertTrue(np.isfinite(result).all())

    def test_forced_mirror_swaps_joint_identity_and_x_direction(self):
        class MirrorOnlyRng:
            def random(self):
                return 0.0

            def uniform(self, low, high):
                return 0.0 if low < 0 else 1.0

            def normal(self, loc, scale, size):
                return np.zeros(size, dtype=np.float32)

        sample = np.zeros((30, 17, 3), dtype=np.float32)
        sample[:, 0, 0] = -2.0
        sample[:, 1, 0] = 3.0
        result = augment_window(sample, MirrorOnlyRng())
        self.assertTrue(np.allclose(result[:, 0, 0], -3.0))
        self.assertTrue(np.allclose(result[:, 1, 0], 2.0))
        self.assertIn((0, 1), LEFT_RIGHT_PAIRS)


if __name__ == "__main__":
    unittest.main()
