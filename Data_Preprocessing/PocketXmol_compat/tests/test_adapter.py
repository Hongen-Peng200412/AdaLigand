from __future__ import annotations

import pytest
from rdkit import Chem

import pocketxmol_compat.adapter as adapter


def test_atom_valence_exception_becomes_explicit_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """RDKit 明确报告的原子价态错误应成为稳定过滤原因。"""

    def raise_atom_valence_error(_ligand: object) -> None:
        raise Chem.rdchem.AtomValenceException("invalid valence")

    monkeypatch.setattr(adapter, "ligand_to_rdkit", raise_atom_valence_error)
    mol, reason = adapter._ligand_to_rdkit_with_filter(object())

    assert mol is None
    assert reason == "invalid_ligand_valence"


def test_unexpected_rdkit_conversion_error_stays_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知转换异常不得伪装成数据过滤原因。"""

    def raise_unexpected_error(_ligand: object) -> None:
        raise RuntimeError("unexpected conversion failure")

    monkeypatch.setattr(adapter, "ligand_to_rdkit", raise_unexpected_error)

    with pytest.raises(RuntimeError, match="unexpected conversion failure"):
        adapter._ligand_to_rdkit_with_filter(object())
