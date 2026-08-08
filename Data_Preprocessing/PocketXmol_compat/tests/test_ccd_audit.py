from __future__ import annotations

import json
from pathlib import Path
import pickle

from pocketxmol_compat.ccd_audit import build_ccd_audit, source_chemistry_reasons


class _FakeBondType:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeBond:
    def __init__(self, name: str) -> None:
        self._bond_type = _FakeBondType(name)

    def GetBondType(self) -> _FakeBondType:
        return self._bond_type


class _FakeMol:
    def __init__(self, names: list[str]) -> None:
        self._bonds = [_FakeBond(name) for name in names]

    def GetBonds(self) -> list[_FakeBond]:
        return self._bonds


def _write_selected_source(tmp_path: Path) -> tuple[Path, str]:
    stage_c_root = tmp_path / "source"
    parse_dir = stage_c_root / "parse" / "1abc"
    parse_dir.mkdir(parents=True)
    occurrence = {
        "candidate_id": 7,
        "components": [
            {"ccd_id": "SUP"},
            {"ccd_id": "SUP"},
            {"ccd_id": "DAT"},
            {"ccd_id": "UNK"},
            {"ccd_id": "MISS"},
        ],
    }
    (parse_dir / "occurrences.jsonl").write_text(
        json.dumps(occurrence) + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "selection.json"
    manifest.write_text(
        json.dumps([{"pdb_id": "1ABC", "candidate_id": 7}]),
        encoding="utf-8",
    )
    cache_dir = stage_c_root / "raw" / "ccd_cache"
    cache_dir.mkdir(parents=True)
    for ccd_id, names in {
        "SUP": ["SINGLE", "DOUBLE", "AROMATIC"],
        "DAT": ["DATIVE"],
        "UNK": ["UNSPECIFIED"],
    }.items():
        with (cache_dir / f"{ccd_id}.pkl").open("wb") as stream:
            pickle.dump(_FakeMol(names), stream)
    return stage_c_root, f"train={manifest}"


def _records_by_id(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    records = payload["ccd_records"]
    assert isinstance(records, list)
    return {str(record["ccd_id"]): record for record in records}


def test_ccd_audit_records_supported_dative_unknown_and_missing(tmp_path: Path) -> None:
    stage_c_root, split_specification = _write_selected_source(tmp_path)
    payload = build_ccd_audit(stage_c_root, [split_specification])
    records = _records_by_id(payload)

    assert payload["ccd_count"] == 4
    assert records["SUP"]["supported"] is True
    assert records["SUP"]["bond_type_names"] == ["AROMATIC", "DOUBLE", "SINGLE"]
    assert records["DAT"] == {
        "ccd_id": "DAT",
        "bond_type_names": ["DATIVE"],
        "supported": False,
        "error": None,
    }
    assert records["UNK"]["supported"] is False
    assert records["UNK"]["error"] is None
    assert records["MISS"]["supported"] is False
    assert str(records["MISS"]["error"]).startswith("FileNotFoundError:")


def test_adapter_chemistry_gate_reads_only_audit_json(tmp_path: Path, monkeypatch) -> None:
    audit_path = tmp_path / "source_chemistry_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "schema": "adaligand.pocketxmol.source_chemistry_audit",
                "schema_version": 1,
                "ccd_records": [
                    {
                        "ccd_id": "SUP",
                        "bond_type_names": ["SINGLE"],
                        "supported": True,
                        "error": None,
                    },
                    {
                        "ccd_id": "DAT",
                        "bond_type_names": ["DATIVE"],
                        "supported": False,
                        "error": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    def _forbidden_pickle_load(*args, **kwargs):
        raise AssertionError("主适配阶段不得读取 CCD pickle")

    monkeypatch.setattr("pocketxmol_compat.ccd_audit.pickle.load", _forbidden_pickle_load)
    assert source_chemistry_reasons([{"ccd_id": "SUP"}], audit_path) == ()
    assert source_chemistry_reasons([{"ccd_id": "DAT"}], audit_path) == (
        "unsupported_bond_type",
    )
    assert source_chemistry_reasons([{"ccd_id": "MISSING_RECORD"}], audit_path) == (
        "source_chemistry_unverifiable",
    )
