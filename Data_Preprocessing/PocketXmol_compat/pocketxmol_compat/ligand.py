"""A–G 配体对象的资格审计和 PocketXMol 原生字段转换。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pickle
from typing import Any

import numpy as np
from rdkit import Chem

from pocketxmol_compat.constants import (
    AA_TO_INDEX,
    AA_TO_ONE_LETTER,
    AG_BOND_TO_POCKETXMOL,
    AMINO_ACIDS,
    BACKBONE_ATOM_NAMES,
    LIGAND_ATOMIC_NUMBERS,
)


@dataclass(frozen=True)
class LigandAudit:
    """配体审计结果；`reasons` 为空时才允许生成两套受体产物。"""

    reasons: tuple[str, ...]
    atoms: np.ndarray
    bonds: np.ndarray
    atom_names: tuple[str, ...]
    residue_names: tuple[str, ...]
    smiles: str
    coords: np.ndarray
    present: np.ndarray


def load_and_audit_ligand(
    stage_c_root: Path,
    occurrence: dict[str, Any],
    coords_archive: np.lib.npyio.NpzFile,
) -> LigandAudit:
    """加载一个 occurrence，并执行 Phase 1 已冻结的配体过滤规则。"""

    from adaligand_preprocessing.utils.io import safe_object_filename

    candidate_id = int(occurrence["candidate_id"])
    object_key = str(occurrence["object_key"])
    object_path = stage_c_root / "ligand_objects" / f"{safe_object_filename(object_key)}.npz"
    with np.load(object_path, allow_pickle=True) as archive:
        atoms = np.array(archive["atoms"], copy=True)
        bonds = np.array(archive["bonds"], copy=True)
        atom_names = tuple(str(value) for value in archive["atom_names"].tolist())
        residue_names = tuple(str(value).upper() for value in archive["residue_names"].tolist())
        smiles = str(archive["smiles"].item())

    coords = np.asarray(coords_archive[f"coords_{candidate_id}"], dtype=np.float32)
    present = np.asarray(coords_archive[f"present_{candidate_id}"], dtype=bool)
    reasons: list[str] = []

    if str(occurrence.get("type_tag", "")) == "ion":
        reasons.append("excluded_type_tag_ion")
    elif str(occurrence.get("type_tag", "")) not in {"small_molecule", "peptide_like"}:
        reasons.append("unsupported_type_tag")
    if bool(occurrence.get("is_covalent", False)):
        reasons.append("covalent_ligand_without_attachment_condition")
    if atoms.shape[0] != coords.shape[0] or present.shape != (atoms.shape[0],):
        reasons.append("ligand_atom_alignment_mismatch")
    elif not bool(present.all()) or not np.isfinite(coords).all():
        reasons.append("incomplete_heavy_atom_coordinates")

    elements = np.asarray(atoms["element"], dtype=np.int64)
    if not np.isin(elements, np.asarray(LIGAND_ATOMIC_NUMBERS)).all():
        reasons.append("unsupported_element")

    for bond in bonds:
        selected = np.flatnonzero(np.asarray(bond["type"], dtype=bool))
        if selected.size != 1 or int(selected[0]) not in AG_BOND_TO_POCKETXMOL:
            reasons.append("unsupported_bond_type")
            break

    if not source_bond_types_are_supported(stage_c_root, occurrence):
        reasons.append("unsupported_bond_type")

    if str(occurrence.get("type_tag", "")) == "peptide_like":
        peptide_reason = audit_peptide_fields(
            atoms, bonds, atom_names, residue_names, occurrence.get("components", [])
        )
        if peptide_reason is not None:
            reasons.append(peptide_reason)

    return LigandAudit(
        tuple(dict.fromkeys(reasons)), atoms, bonds, atom_names, residue_names, smiles, coords, present
    )


def audit_peptide_fields(
    atoms: np.ndarray,
    bonds: np.ndarray,
    atom_names: tuple[str, ...],
    residue_names: tuple[str, ...],
    components: list[dict[str, Any]],
) -> str | None:
    """判断 A–G peptide_like 能否无歧义重建官方肽字段。"""

    if len(atom_names) != len(atoms) or not residue_names:
        return "peptide_contract_not_lossless"
    residue_ids = np.asarray(atoms["residue_id"], dtype=np.int64)
    if residue_ids.size == 0 or set(residue_ids.tolist()) != set(range(1, len(residue_names) + 1)):
        return "peptide_contract_not_lossless"
    if any(name not in AMINO_ACIDS for name in residue_names):
        return "peptide_contract_not_lossless"
    component_names = tuple(str(item.get("ccd_id", "")).upper() for item in components)
    if component_names != residue_names:
        return "peptide_contract_not_lossless"
    chains = {
        (str(item.get("label_asym_id", "")), str(item.get("auth_asym_id", "")))
        for item in components
    }
    if len(chains) != 1:
        return "peptide_contract_not_lossless"
    for residue_id in range(1, len(residue_names) + 1):
        names = [atom_names[index] for index in np.flatnonzero(residue_ids == residue_id)]
        if (
            not names
            or any(not name for name in names)
            or len(names) != len(set(names))
            or not BACKBONE_ATOM_NAMES.issubset(names)
        ):
            return "peptide_contract_not_lossless"

    inter_residue_edges: list[tuple[int, str, int, str]] = []
    for bond in bonds:
        left, right = int(bond["atom_1"]), int(bond["atom_2"])
        left_res, right_res = int(residue_ids[left]), int(residue_ids[right])
        if left_res != right_res:
            inter_residue_edges.append((left_res, atom_names[left], right_res, atom_names[right]))
    normalized_edges = {
        (left_res, left_name, right_res, right_name)
        if left_res < right_res
        else (right_res, right_name, left_res, left_name)
        for left_res, left_name, right_res, right_name in inter_residue_edges
    }
    expected_edges = {
        (residue_id, "C", residue_id + 1, "N")
        for residue_id in range(1, len(residue_names))
    }
    if normalized_edges != expected_edges or len(inter_residue_edges) != len(expected_edges):
        return "peptide_contract_not_lossless"
    return None


def source_bond_types_are_supported(stage_c_root: Path, occurrence: dict[str, Any]) -> bool:
    """回读 CCD RDKit 模板，避免既有对象把未知键型静默压成 single。"""

    allowed = {"SINGLE", "DOUBLE", "TRIPLE", "AROMATIC"}
    components = occurrence.get("components", [])
    if not isinstance(components, list) or not components:
        return False
    for component in components:
        ccd_id = str(component.get("ccd_id", "")).upper()
        cache_path = stage_c_root / "raw" / "ccd_cache" / f"{ccd_id}.pkl"
        try:
            with cache_path.open("rb") as stream:
                mol = pickle.load(stream)
        except (OSError, pickle.PickleError, AttributeError, EOFError):
            return False
        heavy_mol = Chem.RemoveHs(mol, sanitize=False)
        if any(bond.GetBondType().name.upper() not in allowed for bond in heavy_mol.GetBonds()):
            return False
    return True


def ligand_native_arrays(audit: LigandAudit) -> dict[str, np.ndarray]:
    """把已通过审计的配体转换为 `parse_conf_list` 的数值字段。"""

    n_atoms = len(audit.atoms)
    directed: list[tuple[int, int, int]] = []
    for bond in audit.bonds:
        bond_code = AG_BOND_TO_POCKETXMOL[int(np.flatnonzero(bond["type"])[0])]
        left = int(bond["atom_1"])
        right = int(bond["atom_2"])
        directed.extend(((left, right, bond_code), (right, left, bond_code)))
    directed.sort(key=lambda item: item[0] * n_atoms + item[1])
    if directed:
        bond_index = np.asarray([(left, right) for left, right, _ in directed], dtype=np.int64).T
        bond_type = np.asarray([code for _, _, code in directed], dtype=np.int64)
    else:
        bond_index = np.empty((2, 0), dtype=np.int64)
        bond_type = np.empty((0,), dtype=np.int64)
    return {
        "element": np.asarray(audit.atoms["element"], dtype=np.int64),
        "bond_index": bond_index,
        "bond_type": bond_type,
        "pos_all_confs": audit.coords[None].astype(np.float32, copy=False),
    }


def peptide_native_fields(audit: LigandAudit) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """重建官方肽原子名、残基编号、主链标记、氨基酸类型和序列。"""

    residue_ids = np.asarray(audit.atoms["residue_id"], dtype=np.int64)
    residue_index = residue_ids - 1
    residue_types = np.asarray(
        [AA_TO_INDEX[audit.residue_names[index]] for index in residue_index], dtype=np.int64
    )
    arrays = {
        "peptide_pos": audit.coords.astype(np.float32, copy=False),
        "peptide_res_index": residue_index.astype(np.int64, copy=False),
        "peptide_is_backbone": np.asarray(
            [name in BACKBONE_ATOM_NAMES for name in audit.atom_names], dtype=bool
        ),
        "peptide_atom_to_aa_type": residue_types,
    }
    metadata = {
        "peptide_atom_name": list(audit.atom_names),
        "peptide_seq": "".join(AA_TO_ONE_LETTER[name] for name in audit.residue_names),
        "peptide_pep_len": len(audit.residue_names),
    }
    return arrays, metadata


def ligand_to_rdkit(audit: LigandAudit) -> Chem.Mol:
    """按 A–G 原子顺序重建重原子 RDKit Mol，供官方运动学代码使用。"""

    editable = Chem.RWMol()
    chiral_names = (
        "CHI_OTHER", "CHI_OCTAHEDRAL", "CHI_TETRAHEDRAL_CW",
        "CHI_TRIGONALBIPYRAMIDAL", "CHI_UNSPECIFIED", "CHI_TETRAHEDRAL_CCW",
        "CHI_SQUAREPLANAR",
    )
    for row in audit.atoms:
        atom = Chem.Atom(int(row["element"]))
        atom.SetFormalCharge(int(row["charge"]))
        chiral = np.flatnonzero(np.asarray(row["chirality"], dtype=bool))
        if chiral.size == 1:
            atom.SetChiralTag(getattr(Chem.ChiralType, chiral_names[int(chiral[0])]))
        editable.AddAtom(atom)

    bond_types = {
        0: Chem.BondType.SINGLE,
        1: Chem.BondType.DOUBLE,
        2: Chem.BondType.TRIPLE,
        4: Chem.BondType.AROMATIC,
    }
    aromatic_atoms: set[int] = set()
    for row in audit.bonds:
        code = int(np.flatnonzero(row["type"])[0])
        left, right = int(row["atom_1"]), int(row["atom_2"])
        editable.AddBond(left, right, bond_types[code])
        if code == 4:
            aromatic_atoms.update((left, right))
    mol = editable.GetMol()
    for atom_index in aromatic_atoms:
        mol.GetAtomWithIdx(atom_index).SetIsAromatic(True)
    conformer = Chem.Conformer(len(audit.atoms))
    for atom_index, position in enumerate(audit.coords):
        conformer.SetAtomPosition(atom_index, tuple(float(value) for value in position))
    mol.AddConformer(conformer, assignId=True)
    Chem.SanitizeMol(mol)
    return mol
