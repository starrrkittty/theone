import unittest

import numpy as np
import torch

from training.train_stgcn import (
    BrowserSTGCN,
    adjacency,
    initialize_from_checkpoint,
    requested_subject_split,
)


class TrainInitializationTests(unittest.TestCase):
    def test_shared_mode_copies_backbone_and_matching_classifier_rows(self):
        old_labels = ["squat", "unknown"]
        new_labels = ["squat", "unknown", "plank"]
        old_model = BrowserSTGCN(len(old_labels), adjacency())
        with torch.no_grad():
            old_model.gc1_w.fill_(0.25)
            old_model.fc.weight[0].fill_(1.0)
            old_model.fc.weight[1].fill_(2.0)
            old_model.fc.bias.copy_(torch.tensor([3.0, 4.0]))
        checkpoint = {"labels": old_labels, "state_dict": old_model.state_dict()}
        new_model = BrowserSTGCN(len(new_labels), adjacency())
        fresh_plank_row = new_model.fc.weight[2].detach().clone()

        result = initialize_from_checkpoint(new_model, checkpoint, new_labels, "shared")

        self.assertEqual(result["new_labels"], ["plank"])
        self.assertTrue(torch.all(new_model.gc1_w == 0.25))
        self.assertTrue(torch.all(new_model.fc.weight[0] == 1.0))
        self.assertTrue(torch.all(new_model.fc.weight[1] == 2.0))
        self.assertTrue(torch.equal(new_model.fc.weight[2], fresh_plank_row))
        self.assertEqual(new_model.fc.bias[:2].tolist(), [3.0, 4.0])

    def test_exact_mode_rejects_label_change(self):
        model = BrowserSTGCN(2, adjacency())
        checkpoint = {"labels": ["squat"], "state_dict": BrowserSTGCN(1, adjacency()).state_dict()}
        with self.assertRaisesRegex(ValueError, "label order differs"):
            initialize_from_checkpoint(model, checkpoint, ["squat", "plank"], "exact")

    def test_explicit_split_must_cover_every_available_subject(self):
        subjects = np.asarray(["p01", "p02", "p03", "p04"])
        with self.assertRaisesRegex(ValueError, "omits available subjects"):
            requested_subject_split(subjects, ["p01"], ["p02"], ["p03"])


if __name__ == "__main__":
    unittest.main()
