from __future__ import annotations

import csv

import pytest

from training.create_runtime_evaluation_plan import build_plan, write_plan


PARTICIPANTS = ["p01", "p02", "p03", "p04", "p05"]


def test_core_plan_has_six_labels_for_each_of_five_people(tmp_path) -> None:
    rows = build_plan("core-v1", PARTICIPANTS)

    assert len(rows) == 30
    assert len({row["clip_id"] for row in rows}) == 30
    assert {row["participant_id"] for row in rows} == set(PARTICIPANTS)
    assert {row["required_model_id"] for row in rows} == {
        "mmfit-mediapipe-semantic-v1"
    }
    output = tmp_path / "core.csv"
    write_plan(rows, output)
    with output.open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 30


def test_v9_plan_covers_all_nineteen_labels() -> None:
    rows = build_plan("semantic-v9", PARTICIPANTS)

    assert len(rows) == 95
    assert len({row["expected_exercise"] for row in rows}) == 19
    assert {row["required_model_id"] for row in rows} == {
        "mmfit-haa500-semantic-pose-families-v9"
    }


def test_plan_rejects_too_few_or_identifying_style_ids() -> None:
    with pytest.raises(ValueError, match="at least 5"):
        build_plan("core-v1", PARTICIPANTS[:4])
    with pytest.raises(ValueError, match="invalid anonymous"):
        build_plan("core-v1", ["张三", "p02", "p03", "p04", "p05"])
    with pytest.raises(ValueError, match="unique"):
        build_plan("core-v1", ["p01", "p01", "p03", "p04", "p05"])
