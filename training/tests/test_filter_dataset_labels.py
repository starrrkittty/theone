import json
from pathlib import Path

import numpy as np

from training.filter_dataset_labels import filter_dataset


def write_dataset(path: Path) -> None:
    path.mkdir()
    np.save(path / "x.npy", np.arange(5 * 2 * 17 * 3, dtype=np.float32).reshape(5, 2, 17, 3))
    np.save(path / "y.npy", np.asarray([0, 1, 2, 1, 0], dtype=np.int64))
    np.save(path / "subjects.npy", np.asarray(["a", "b", "c", "d", "e"]))
    np.save(path / "clips.npy", np.asarray(["ca", "cb", "cc", "cd", "ce"]))
    (path / "metadata.json").write_text(
        json.dumps({"labels": ["squat", "battle_rope", "burpee"]}),
        encoding="utf-8",
    )


def test_filter_dataset_removes_samples_and_remaps_targets(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    write_dataset(source)

    metadata = filter_dataset(source, output, {"battle_rope"}, chunk_size=1)

    assert metadata["labels"] == ["squat", "burpee"]
    assert metadata["samples"] == 3
    assert np.load(output / "y.npy").tolist() == [0, 1, 0]
    assert np.load(output / "subjects.npy").tolist() == ["a", "c", "e"]
    assert np.load(output / "x.npy").shape == (3, 2, 17, 3)


def test_filter_dataset_rejects_unknown_exclusion(tmp_path):
    source = tmp_path / "source"
    write_dataset(source)

    try:
        filter_dataset(source, tmp_path / "output", {"missing"})
    except ValueError as error:
        assert "absent" in str(error)
    else:
        raise AssertionError("Expected an absent label to be rejected")
