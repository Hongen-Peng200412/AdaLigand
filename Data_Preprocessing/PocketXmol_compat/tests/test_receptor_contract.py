from __future__ import annotations

import numpy as np

from pocketxmol_compat.receptor import _classify_residue, _select_residues, _slice_extended


def _atom(x: float, residue: str = "ALA", entity: str = "1") -> dict[str, object]:
    return {
        "x": x,
        "y": 0.0,
        "z": 0.0,
        "element": "C",
        "label_comp_id": residue,
        "label_entity_id": entity,
    }


def test_training_pocket_uses_strict_less_than_ten_angstrom() -> None:
    receptor = [_atom(10.0), _atom(9.999, "GLY", "2")]
    keys = [("A", "ALA", "1", ""), ("B", "GLY", "1", "")]
    selected = _select_residues(receptor, {keys[0]: [0], keys[1]: [1]}, np.zeros((1, 3)))
    assert selected == [keys[1]]


def test_raw_residue_classification_does_not_map_modified_to_parent() -> None:
    assert _classify_residue(_atom(0, "ALA"), {}, {}) == "standard"
    assert _classify_residue(_atom(0, "MSE"), {"MSE": {"type": "L-PEPTIDE LINKING"}}, {}) == "modified"
    assert _classify_residue(_atom(0, "DA"), {}, {"1": "polydeoxyribonucleotide"}) == "nucleic"
    assert _classify_residue(_atom(0, "UNX"), {}, {"1": "other"}) == "nonstandard"


def test_extended_features_are_sliced_not_recomputed_and_bonds_are_reindexed() -> None:
    stored = {
        "coords": np.arange(12, dtype=np.float32).reshape(4, 3),
        "element": np.asarray([6, 7, 8, 16], dtype=np.uint8),
        "res_type": np.asarray([0, 1, 2, 3], dtype=np.uint8),
        "is_backbone": np.asarray([1, 0, 1, 0], dtype=bool),
        "atom_name": np.asarray([b"N", b"CA", b"C", b"O"], dtype="S4"),
        "res_index": np.asarray([0, 0, 1, 1], dtype=np.int32),
        "chain_index": np.zeros(4, dtype=np.int32),
        "feat": np.arange(196, dtype=np.float32).reshape(4, 49),
        "bond_index": np.asarray([[0, 1, 2], [1, 2, 3]], dtype=np.int32),
        "bond_type": np.asarray([0, 3, 0], dtype=np.uint8),
    }
    actual = _slice_extended(stored, np.asarray([1, 2], dtype=np.int64))
    np.testing.assert_array_equal(actual["feat"], stored["feat"][[1, 2]])
    np.testing.assert_array_equal(actual["bond_index"], [[0], [1]])
    np.testing.assert_array_equal(actual["bond_type"], [3])
