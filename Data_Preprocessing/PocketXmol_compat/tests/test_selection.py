from __future__ import annotations

import json
from pathlib import Path

import pytest

from pocketxmol_compat.selection import load_selections


def test_pdb_level_split_expands_all_occurrences(tmp_path: Path) -> None:
    parse_dir = tmp_path / "source" / "parse" / "1abc"
    parse_dir.mkdir(parents=True)
    (parse_dir / "occurrences.jsonl").write_text(
        "".join(
            json.dumps({"candidate_id": candidate_id}) + "\n"
            for candidate_id in (2, 5, 9)
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "train.json"
    manifest.write_text(json.dumps([{"pdb_id": "1ABC"}]), encoding="utf-8")

    assert load_selections([f"train={manifest}"], tmp_path / "source") == [
        {"pdb_id": "1abc", "candidate_id": 2, "split": "train"},
        {"pdb_id": "1abc", "candidate_id": 5, "split": "train"},
        {"pdb_id": "1abc", "candidate_id": 9, "split": "train"},
    ]


def test_explicit_instance_manifest_does_not_require_source_root(tmp_path: Path) -> None:
    manifest = tmp_path / "calibration.json"
    manifest.write_text(
        json.dumps([{"pdb_id": "1ABC", "candidate_id": 7}]),
        encoding="utf-8",
    )
    assert load_selections([f"calibration={manifest}"]) == [
        {"pdb_id": "1abc", "candidate_id": 7, "split": "calibration"}
    ]


def test_pdb_level_manifest_requires_source_root(tmp_path: Path) -> None:
    manifest = tmp_path / "validation.json"
    manifest.write_text(json.dumps([{"pdb_id": "1ABC"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="requires stage_c_root"):
        load_selections([f"validation={manifest}"])
