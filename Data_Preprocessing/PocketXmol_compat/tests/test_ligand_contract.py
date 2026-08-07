from __future__ import annotations

import numpy as np

from adaligand_preprocessing.stages.stage_c.ligand_objects import Atom, Bond
from pocketxmol_compat.ligand import (
    LigandAudit,
    audit_peptide_fields,
    ligand_native_arrays,
    peptide_native_fields,
)


def _linear_dipeptide() -> tuple[np.ndarray, np.ndarray, tuple[str, ...], tuple[str, ...]]:
    names = ("N", "CA", "C", "O", "N", "CA", "C", "O")
    atoms = np.zeros((8,), dtype=Atom)
    atoms["element"] = np.asarray([7, 6, 6, 8] * 2, dtype=np.int8)
    atoms["residue_id"] = np.asarray([1] * 4 + [2] * 4, dtype=np.int32)
    edges = [(0, 1), (1, 2), (2, 3), (2, 4), (4, 5), (5, 6), (6, 7)]
    bonds = np.zeros((len(edges),), dtype=Bond)
    bonds["atom_1"] = [edge[0] for edge in edges]
    bonds["atom_2"] = [edge[1] for edge in edges]
    bonds["type"][:, 0] = True
    return atoms, bonds, names, ("ALA", "GLY")


def test_peptide_requires_linear_standard_backbone() -> None:
    atoms, bonds, names, residues = _linear_dipeptide()
    components = [
        {"ccd_id": "ALA", "label_asym_id": "L", "auth_asym_id": "L"},
        {"ccd_id": "GLY", "label_asym_id": "L", "auth_asym_id": "L"},
    ]
    assert audit_peptide_fields(atoms, bonds, names, residues, components) is None

    cyclic = np.concatenate([bonds, bonds[:1]])
    cyclic[-1]["atom_1"], cyclic[-1]["atom_2"] = 6, 0
    assert (
        audit_peptide_fields(atoms, cyclic, names, residues, components)
        == "peptide_contract_not_lossless"
    )


def test_native_bonds_are_bidirectional_sorted_and_num_bonds_stays_undirected() -> None:
    atoms, bonds, names, residues = _linear_dipeptide()
    coords = np.arange(24, dtype=np.float32).reshape(8, 3)
    audit = LigandAudit((), atoms, bonds, names, residues, "", coords, np.ones(8, dtype=bool))
    arrays = ligand_native_arrays(audit)
    assert arrays["bond_index"].shape == (2, 2 * len(bonds))
    linear_key = arrays["bond_index"][0] * len(atoms) + arrays["bond_index"][1]
    assert np.all(linear_key[:-1] <= linear_key[1:])
    assert np.all(arrays["bond_type"] == 1)


def test_peptide_uses_official_amino_acid_order() -> None:
    atoms, bonds, names, residues = _linear_dipeptide()
    coords = np.zeros((8, 3), dtype=np.float32)
    audit = LigandAudit((), atoms, bonds, names, residues, "", coords, np.ones(8, dtype=bool))
    arrays, metadata = peptide_native_fields(audit)
    np.testing.assert_array_equal(arrays["peptide_atom_to_aa_type"], [0] * 4 + [5] * 4)
    assert metadata["peptide_seq"] == "AG"
    assert metadata["peptide_pep_len"] == 2
