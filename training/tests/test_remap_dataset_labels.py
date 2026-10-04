import json
from pathlib import Path

import numpy as np

from training.remap_dataset_labels import remap_dataset


def write_dataset(path: Path) -> None:
    path.mkdir()
    np.save(path / "x.npy", np.zeros((4, 2, 17, 3), dtype=np.float32))
    np.save(path / "y.npy", np.asarray([0, 1, 2, 1], dtype=np.int64))
    np.save(path / "subjects.npy", np.asarray(["a", "b", "c", "d"]))
    np.save(path / "clips.npy", np.asarray(["ca", "cb", "cc", "cd"]))
    (path / "metadata.json").write_text(
        json.dumps({"labels": ["situp", "crunch", "burpee"]}),
        encoding="utf-8",
    )


def test_remap_dataset_merges_labels_and_targets(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    write_dataset(source)

    metadata = remap_dataset(source, output, {"crunch": "situp"}, chunk_size=1)

    assert metadata["labels"] == ["situp", "burpee"]
    assert np.load(output / "y.npy").tolist() == [0, 0, 1, 0]
    assert np.load(output / "subjects.npy").tolist() == ["a", "b", "c", "d"]


def test_remap_dataset_rejects_missing_source_label(tmp_path):
    source = tmp_path / "source"
    write_dataset(source)

    try:
        remap_dataset(source, tmp_path / "output", {"missing": "situp"})
    except ValueError as error:
        assert "absent" in str(error)
    else:
        raise AssertionError("Expected a missing source label to be rejected")
