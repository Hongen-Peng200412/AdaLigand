from __future__ import annotations

import json
from pathlib import Path

import pytest

from pocketxmol_compat.adapter import _finish_result, _load_cached_result
from pocketxmol_compat.records import AdaptRequest, AdaptResult


def _request(tmp_path: Path, overwrite: bool = False) -> AdaptRequest:
    return AdaptRequest(
        stage_c_root=tmp_path / "source",
        output_root=tmp_path / "output",
        pocketxmol_root=tmp_path / "official",
        ccd_audit_path=tmp_path / "source_chemistry_audit.json",
        pdb_id="1ABC",
        candidate_id=7,
        split="train",
        overwrite=overwrite,
    )


def _result(native_path: str | None = None) -> AdaptResult:
    return AdaptResult(
        pdb_id="1abc",
        candidate_id=7,
        split="train",
        object_key="CCD:LIG",
        type_tag="small_molecule",
        pocketxmol_eligible=native_path is not None,
        extended_contract_eligible=False,
        active_for_stage3=native_path is not None,
        reasons=(),
        native_path=native_path,
    )


def test_filtered_result_is_resumable_without_artifact_directory(tmp_path: Path) -> None:
    request = _request(tmp_path)
    expected = _finish_result(request, _result())
    assert _load_cached_result(request, "1abc") == expected


def test_eligible_cache_requires_complete_marker(tmp_path: Path) -> None:
    request = _request(tmp_path)
    _finish_result(request, _result("pocketxmol_native/train/1abc_7"))
    with pytest.raises(ValueError, match="incomplete"):
        _load_cached_result(request, "1abc")

    artifact = request.output_root / "pocketxmol_native/train/1abc_7"
    artifact.mkdir(parents=True)
    (artifact / "complete.json").write_text('{"complete": true}\n', encoding="utf-8")
    assert _load_cached_result(request, "1abc").pocketxmol_eligible


def test_overwrite_ignores_existing_record(tmp_path: Path) -> None:
    request = _request(tmp_path)
    _finish_result(request, _result())
    assert _load_cached_result(_request(tmp_path, overwrite=True), "1abc") is None


def test_record_before_external_ccd_audit_is_not_reused(tmp_path: Path) -> None:
    request = _request(tmp_path)
    path = request.output_root / "records" / "train" / "1abc_7.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_result().to_json()), encoding="utf-8")
    assert _load_cached_result(request, "1abc") is None
