"""从已落盘 LigandObject 生成去重配体描述子。

描述子只依赖 `LigandObject.atoms/bonds/ref_pos`，因此旧服务器上的 3,833 个去重对象
可以直接升级，不必重新下载 CCD 或重复解析 22,386 个 PDB。图距离、Wiener 指数和图能量
都使用无权化学邻接图；回转半径使用非质量加权参考坐标；无环分子的最近环距离固定为 -1。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

from io_utils import atomic_save_npz, file_lock, safe_object_filename


# 仅关闭 RDKit property-cache 的严格价态检查；芳香性、成环和 kekulize 等错误仍须阻断。
_SANITIZE_WITHOUT_STRICT_VALENCE = (
    Chem.SanitizeFlags.SANITIZE_ALL ^ Chem.SanitizeFlags.SANITIZE_PROPERTIES
)


def compute_ligand_descriptors(atoms: np.ndarray, bonds: np.ndarray) -> dict[str, np.ndarray]:
    """
    计算一个 LigandObject 的全局和逐原子图描述子。

    输入参数:
        - atoms: np.ndarray, (M,), LigandObject `Atom` 结构化数组，含 element/charge/ref_pos
        - bonds: np.ndarray, (E,), LigandObject `Bond` 结构化数组，含端点和五类键 one-hot

    输出:
        - descriptors: dict[str,np.ndarray], 包含:
            - `mol_weight`: () float32, 重原子质量之和
            - `n_heavy`: () int32, 重原子数
            - `n_rings`: () int32, RDKit 对重建化学图识别的环数
            - `n_rotatable`: () int32, RDKit strict 可旋转键数
            - `wiener_index`: () float32, 所有无序原子对最短路之和
            - `graph_energy`: () float32, 无权邻接矩阵特征值绝对值之和
            - `radius_gyration`: () float32, `ref_pos` 非质量加权回转半径
            - `atom_local`: (M,5) float32, 偏心率、1/2/3-hop 数、到最近环原子的跳数
    """
    n_atoms = int(len(atoms))
    adjacency = np.zeros((n_atoms, n_atoms), dtype=np.float64)
    for bond in bonds:
        left = int(bond["atom_1"])
        right = int(bond["atom_2"])
        adjacency[left, right] = 1.0
        adjacency[right, left] = 1.0

    distances = _all_pairs_shortest_paths(adjacency)
    if n_atoms > 1 and np.any(distances < 0):
        raise ValueError("LigandObject chemical graph is disconnected")

    mol = _build_rdkit_mol(atoms, bonds)
    ring_info = mol.GetRingInfo()
    ring_atoms = {atom_index for ring in ring_info.AtomRings() for atom_index in ring}

    # np.ndarray, (M,5), 各行严格对齐 LigandObject 原子行序。
    atom_local = np.empty((n_atoms, 5), dtype=np.float32)
    for atom_index in range(n_atoms):
        atom_distances = distances[atom_index]
        atom_local[atom_index, 0] = float(atom_distances.max(initial=0))
        atom_local[atom_index, 1] = float(np.count_nonzero(atom_distances == 1))
        atom_local[atom_index, 2] = float(np.count_nonzero(atom_distances == 2))
        atom_local[atom_index, 3] = float(np.count_nonzero(atom_distances == 3))
        atom_local[atom_index, 4] = (
            float(min(atom_distances[ring_atom] for ring_atom in ring_atoms))
            if ring_atoms else -1.0
        )

    periodic_table = Chem.GetPeriodicTable()
    mol_weight = sum(periodic_table.GetAtomicWeight(int(atom["element"])) for atom in atoms)
    upper_triangle = np.triu_indices(n_atoms, k=1)
    wiener_index = float(distances[upper_triangle].sum()) if n_atoms > 1 else 0.0
    graph_energy = float(np.abs(np.linalg.eigvalsh(adjacency)).sum()) if n_atoms else 0.0

    ref_pos = np.asarray(atoms["ref_pos"], dtype=np.float64).reshape((-1, 3))
    if n_atoms:
        centered = ref_pos - ref_pos.mean(axis=0, keepdims=True)
        radius_gyration = float(np.sqrt(np.mean(np.sum(centered * centered, axis=1))))
    else:
        radius_gyration = 0.0

    return {
        "mol_weight": np.asarray(mol_weight, dtype=np.float32),
        "n_heavy": np.asarray(n_atoms, dtype=np.int32),
        "n_rings": np.asarray(ring_info.NumRings(), dtype=np.int32),
        "n_rotatable": np.asarray(
            rdMolDescriptors.CalcNumRotatableBonds(
                mol,
                rdMolDescriptors.NumRotatableBondsOptions.Strict,
            ),
            dtype=np.int32,
        ),
        "wiener_index": np.asarray(wiener_index, dtype=np.float32),
        "graph_energy": np.asarray(graph_energy, dtype=np.float32),
        "radius_gyration": np.asarray(radius_gyration, dtype=np.float32),
        "atom_local": atom_local,
    }


def materialize_ligand_descriptor(root: Path, object_key: str, overwrite: bool) -> Path:
    """
    按 object_key 并发安全地物化一份去重描述子文件。

    输入参数:
        - root: Path, Stage root，内含 `ligand_objects/`
        - object_key: str, `CCD:*` 或 `BRANCHED:*` 去重键
        - overwrite: bool, 是否重新计算已有且 schema 正确的描述子

    输出:
        - output_path: Path, `ligand_descriptors/{safe_object_key}.npz`
    """
    safe_key = safe_object_filename(object_key)
    object_path = root / "ligand_objects" / f"{safe_key}.npz"
    output_path = root / "ligand_descriptors" / f"{safe_key}.npz"
    lock_path = root / "reports" / "locks" / "ligand_descriptors" / f"{safe_key}.lock"

    with file_lock(lock_path):
        if output_path.exists() and not overwrite and ligand_descriptor_is_valid(output_path):
            return output_path
        with np.load(object_path, allow_pickle=True) as ligand_object:
            descriptors = compute_ligand_descriptors(
                ligand_object["atoms"],
                ligand_object["bonds"],
            )
        atomic_save_npz(output_path, **descriptors)
    return output_path


def ligand_descriptor_is_valid(path: Path) -> bool:
    """
    检查配体描述子是否满足最小稳定 schema。

    输入参数:
        - path: Path, `ligand_descriptors/*.npz`

    输出:
        - valid: bool, key、dtype、shape 和有限性均正确时为 True
    """
    required_scalars: dict[str, np.dtype[Any]] = {
        "mol_weight": np.dtype(np.float32),
        "n_heavy": np.dtype(np.int32),
        "n_rings": np.dtype(np.int32),
        "n_rotatable": np.dtype(np.int32),
        "wiener_index": np.dtype(np.float32),
        "graph_energy": np.dtype(np.float32),
        "radius_gyration": np.dtype(np.float32),
    }
    try:
        with np.load(path, allow_pickle=False) as data:
            if not set(required_scalars).union({"atom_local"}).issubset(data.files):
                return False
            for key, dtype in required_scalars.items():
                if data[key].shape != () or data[key].dtype != dtype:
                    return False
            atom_local = data["atom_local"]
            if atom_local.dtype != np.float32 or atom_local.ndim != 2 or atom_local.shape[1] != 5:
                return False
            if int(data["n_heavy"]) != atom_local.shape[0]:
                return False
            float_values = [
                data["mol_weight"], data["wiener_index"], data["graph_energy"],
                data["radius_gyration"], atom_local,
            ]
            return all(np.isfinite(value).all() for value in float_values)
    except (OSError, ValueError, KeyError):
        return False


def _all_pairs_shortest_paths(adjacency: np.ndarray) -> np.ndarray:
    """用 BFS 计算无权图的全体原子对最短路，断开点保持 -1。"""
    n_atoms = adjacency.shape[0]
    distances = np.full((n_atoms, n_atoms), -1, dtype=np.int32)
    neighbor_lists = [np.flatnonzero(adjacency[index]).tolist() for index in range(n_atoms)]
    for source in range(n_atoms):
        distances[source, source] = 0
        queue: deque[int] = deque([source])
        while queue:
            current = queue.popleft()
            for neighbor in neighbor_lists[current]:
                if distances[source, neighbor] >= 0:
                    continue
                distances[source, neighbor] = distances[source, current] + 1
                queue.append(neighbor)
    return distances


def _build_rdkit_mol(atoms: np.ndarray, bonds: np.ndarray) -> Chem.Mol:
    """从 LigandObject 结构化数组重建仅供环数/可旋转键统计的 RDKit Mol。"""
    editable = Chem.RWMol()
    for atom_record in atoms:
        atom = Chem.Atom(int(atom_record["element"]))
        atom.SetFormalCharge(int(atom_record["charge"]))
        editable.AddAtom(atom)

    bond_types = (
        Chem.BondType.SINGLE,
        Chem.BondType.DOUBLE,
        Chem.BondType.TRIPLE,
        Chem.BondType.DATIVE,
        Chem.BondType.AROMATIC,
    )
    aromatic_atoms: set[int] = set()
    for bond_record in bonds:
        active_types = np.flatnonzero(np.asarray(bond_record["type"], dtype=bool))
        if len(active_types) != 1:
            raise ValueError("LigandObject bond type must be one-hot")
        type_index = int(active_types[0])
        left = int(bond_record["atom_1"])
        right = int(bond_record["atom_2"])
        editable.AddBond(left, right, bond_types[type_index])
        if type_index == 4:
            aromatic_atoms.update((left, right))

    mol = editable.GetMol()
    for atom_index in aromatic_atoms:
        mol.GetAtomWithIdx(atom_index).SetIsAromatic(True)
    # LigandObject 按契约保留完整 CCD 模板和未出现的 leaving atom，临时图可能有表观高价态。
    mol.UpdatePropertyCache(strict=False)
    failed_op = Chem.SanitizeMol(
        mol,
        sanitizeOps=_SANITIZE_WITHOUT_STRICT_VALENCE,
        catchErrors=True,
    )
    if failed_op != Chem.SanitizeFlags.SANITIZE_NONE:
        raise ValueError(f"LigandObject RDKit sanitization failed at {failed_op}")
    return mol
