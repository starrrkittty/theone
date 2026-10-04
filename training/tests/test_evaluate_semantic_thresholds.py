import json
import tempfile
import unittest
from pathlib import Path

from training.evaluate_semantic_thresholds import (
    apply_threshold_overrides,
    load_threshold_configuration,
    select_threshold_labels,
)


class EvaluateSemanticThresholdsTests(unittest.TestCase):
    def write_json(self, directory: str, payload: dict) -> Path:
        path = Path(directory) / "thresholds.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_loads_calibration_report_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            thresholds, source = load_threshold_configuration(
                self.write_json(directory, {"per_class_thresholds": {"lunge": 0.87}})
            )
        self.assertEqual(thresholds, {"lunge": 0.87})
        self.assertEqual(source, "per_class_thresholds")

    def test_loads_model_card_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            thresholds, source = load_threshold_configuration(
                self.write_json(directory, {"semantic_thresholds": {"situp": 0.99}})
            )
        self.assertEqual(thresholds, {"situp": 0.99})
        self.assertEqual(source, "semantic_thresholds")

    def test_rejects_out_of_range_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(
                directory, {"semantic_thresholds": {"situp": 1.01}}
            )
            with self.assertRaisesRegex(ValueError, "outside"):
                load_threshold_configuration(path)

    def test_applies_named_override_without_mutating_original(self):
        original = {"lunge": 0.8, "situp": 0.82}
        result = apply_threshold_overrides(original, ["situp=0.99"])
        self.assertEqual(result, {"lunge": 0.8, "situp": 0.99})
        self.assertEqual(original["situp"], 0.82)

    def test_rejects_unknown_override_label(self):
        with self.assertRaisesRegex(ValueError, "not configured"):
            apply_threshold_overrides({"lunge": 0.8}, ["situp=0.99"])

    def test_selects_explicit_cross_domain_subset_in_requested_order(self):
        result = select_threshold_labels(
            {"lunge": 0.8, "situp": 0.82, "burpee": 0.9},
            ["situp", "lunge"],
        )
        self.assertEqual(result, {"situp": 0.82, "lunge": 0.8})

    def test_rejects_unconfigured_cross_domain_label(self):
        with self.assertRaisesRegex(ValueError, "not configured"):
            select_threshold_labels({"lunge": 0.8}, ["burpee"])


if __name__ == "__main__":
    unittest.main()
