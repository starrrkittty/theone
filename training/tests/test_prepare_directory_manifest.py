import json
import tempfile
import unittest
from pathlib import Path

from training.prepare_directory_manifest import (
    build_manifest,
    load_label_map,
    validate_subject_coverage,
)


class PrepareDirectoryManifestTests(unittest.TestCase):
    def test_parent_layout_maps_labels_and_preserves_subjects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for subject in ("p01", "p02", "p03"):
                path = root / "gym_plank" / subject / f"{subject}.mp4"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            ignored = root / "other" / "p04" / "clip.mp4"
            ignored.parent.mkdir(parents=True)
            ignored.touch()

            entries, audit = build_manifest(root, {"gym_plank": "plank"})

            self.assertEqual(len(entries), 3)
            self.assertEqual({entry["subject"] for entry in entries}, {"p01", "p02", "p03"})
            self.assertEqual(audit["label_counts"], {"plank": 3})
            self.assertEqual(audit["ignored"], {"unmapped:other": 1})
            validate_subject_coverage(entries, 3)

    def test_file_layout_treats_curated_clips_as_independent_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "gym_plank"
            folder.mkdir()
            for name in ("youtube_a.mp4", "youtube_b.mp4", "youtube_c.mp4"):
                (folder / name).touch()

            entries, audit = build_manifest(
                root, {"gym_plank": "plank"}, subject_mode="file"
            )

            self.assertEqual([entry["subject"] for entry in entries], [
                "youtube_a", "youtube_b", "youtube_c"
            ])
            self.assertEqual(audit["subjects_per_label"], {"plank": 3})

    def test_sparse_subjects_are_rejected(self):
        entries = [{"label": "plank", "subject": "same"}]
        with self.assertRaisesRegex(ValueError, "independent subjects"):
            validate_subject_coverage(entries, 3)

    def test_invalid_target_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.json"
            path.write_text(json.dumps({"curl": "made_up"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported target label"):
                load_label_map(path)

    def test_semantic_expansion_target_label_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.json"
            path.write_text(json.dumps({"burpee": "burpee"}), encoding="utf-8")
            self.assertEqual(load_label_map(path), {"burpee": "burpee"})


if __name__ == "__main__":
    unittest.main()
