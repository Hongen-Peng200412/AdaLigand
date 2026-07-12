"""Stage C 受体 token 的化学键和 49 维特征。

本模块把受体侧稳定语义集中在一处：
- `build_receptor_arrays` 生成旧 7 个基础数组，并追加化学键表与 `feat(N,49)`。
- `build_receptor_bonds` 只生成化学键，不生成运行时 radius/KNN 边。
- `compute_receptor_features` 在完整受体上计算 Pocket Plus 血统的 49 维特征。

49 维语义参考 sibling Pocket Plus 的 `Make_Data/PDB_processor`，但实现和常量冻结在
AdaLigand 内，运行时不依赖另一个仓库。局部密度使用相同 0–2、2–4、…、16–18 Å
壳层定义，并用 KD-tree 的计数接口避免保存巨大邻居列表。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import AbstractSet, Any

import numpy as np
from rdkit import Chem
from scipy.spatial import cKDTree

from constants import (
    NUCLEIC_BACKBONE,
    PROTEIN_BACKBONE,
    RECEPTOR_BOND_TYPE_TO_ID,
    RES_TO_ID,
)
from ligand_object import get_ccd_mol


ELEMENT_TYPES = ("C", "N", "O", "S", "P", "X")
AMINO_ACIDS = (
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
)
NUCLEOTIDE_TYPES = ("A", "U", "C", "G")
RESIDUE_FEATURE_TYPES = AMINO_ACIDS + NUCLEOTIDE_TYPES + ("X",)
DENSITY_BIN_EDGES = np.arange(0.0, 20.0, 2.0, dtype=np.float32)

MODIFIED_RESIDUE_TO_PARENT = {
    "MSE": "MET", "SEP": "SER", "TPO": "THR", "PTR": "TYR", "MLY": "LYS",
    "M3L": "LYS", "KCX": "LYS", "HYP": "PRO", "FME": "MET", "CME": "CYS",
    "CSO": "CYS", "OCS": "CYS", "SEC": "CYS", "PYL": "LYS", "PCA": "GLU",
    "HID": "HIS", "HIE": "HIS", "HIP": "HIS", "CYX": "CYS", "PSU": "U",
    "5MC": "C", "5MU": "U", "1MA": "A", "2MG": "G", "7MG": "G", "M2G": "G",
    "OMG": "G", "OMC": "C", "DA": "A", "DT": "U", "DC": "C", "DG": "G",
}

# 8 维顺序固定为 [极性, 非极性, 酸性, 碱性, 中性, 正电, 负电, 无电]。
RESIDUE_PHYSIO = {
    "ALA": (0, 1, 0, 0, 1, 0, 0, 1), "ARG": (1, 0, 0, 1, 0, 1, 0, 0),
    "ASN": (1, 0, 0, 0, 1, 0, 0, 1), "ASP": (1, 0, 1, 0, 0, 0, 1, 0),
    "CYS": (1, 0, 1, 0, 0, 0, 0, 1), "GLN": (1, 0, 0, 0, 1, 0, 0, 1),
    "GLU": (1, 0, 1, 0, 0, 0, 1, 0), "GLY": (0, 1, 0, 0, 1, 0, 0, 1),
    "HIS": (1, 0, 0, 1, 0, 0, 0, 1), "ILE": (0, 1, 0, 0, 1, 0, 0, 1),
    "LEU": (0, 1, 0, 0, 1, 0, 0, 1), "LYS": (1, 0, 0, 1, 0, 1, 0, 0),
    "MET": (0, 1, 0, 0, 1, 0, 0, 1), "PHE": (0, 1, 0, 0, 1, 0, 0, 1),
    "PRO": (0, 1, 0, 0, 1, 0, 0, 1), "SER": (1, 0, 0, 0, 1, 0, 0, 1),
    "THR": (1, 0, 0, 0, 1, 0, 0, 1), "TRP": (0, 1, 0, 0, 1, 0, 0, 1),
    "TYR": (1, 0, 1, 0, 0, 0, 0, 1), "VAL": (0, 1, 0, 0, 1, 0, 0, 1),
    "A": (1, 0, 0, 1, 0, 0, 0, 1), "U": (1, 0, 0, 0, 1, 0, 0, 1),
    "C": (1, 0, 0, 0, 1, 0, 0, 1), "G": (1, 0, 0, 1, 0, 0, 0, 1),
    "X": (0, 0, 0, 0, 1, 0, 0, 1),
}

# 质量除以 32.0，保持 Pocket Plus 已有 49 维输入的数值尺度。
NORMALIZED_ATOM_MASS = {
    "C": 12.011 / 32.0,
    "N": 14.007 / 32.0,
    "O": 15.999 / 32.0,
    "S": 32.065 / 32.0,
    "P": 30.974 / 32.0,
    "X": 14.0 / 32.0,
}

# 保留原导入名，兼容既有代码；唯一权威枚举位于 constants.py。
BOND_TYPE_TO_ID = RECEPTOR_BOND_TYPE_TO_ID


class UnsupportedReceptorBondType(RuntimeError):
    """CCD 受体模板出现当前契约无法表达的键型时抛出的错误。"""


class ReceptorAtomNameCoverageError(RuntimeError):
    """当前受体原子名无法在对应 CCD 模板中逐个定位时抛出的错误。"""


def validated_ccd_atom_name_to_element(
    mol: Chem.Mol,
    expected_ccd: str,
) -> dict[str, int]:
    """
    验证缓存 CCD 身份与 atom-name 表，并返回名称到原子序数的映射。

    输入参数:
        - mol: Chem.Mol, 从 `raw/ccd_cache` 读取或刚下载的 CCD 分子
        - expected_ccd: str, 调用方期望的 CCD id，大小写不敏感

    输出:
        - name_to_element: dict[str,int], CCD atom name 到合法正原子序数的唯一映射
    """
    normalized_ccd = expected_ccd.upper()
    cached_ccd = mol.GetProp("PDB_NAME").upper() if mol.HasProp("PDB_NAME") else ""
    if cached_ccd != normalized_ccd:
        raise ReceptorAtomNameCoverageError(
            f"CCD cache identity mismatch: expected {normalized_ccd}, "
            f"got {cached_ccd or '<missing>'}"
        )
    name_to_element: dict[str, int] = {}
    for atom in mol.GetAtoms():
        name = atom.GetProp("name") if atom.HasProp("name") else ""
        atomic_number = atom.GetAtomicNum()
        if not name or name in name_to_element:
            raise ReceptorAtomNameCoverageError(
                f"CCD {normalized_ccd} has empty or duplicate atom name: {name!r}"
            )
        if atomic_number <= 0:
            raise ReceptorAtomNameCoverageError(
                f"CCD {normalized_ccd} has invalid atomic number for {name!r}: "
                f"{atomic_number}"
            )
        name_to_element[name] = atomic_number
    if not name_to_element:
        raise ReceptorAtomNameCoverageError(f"CCD {normalized_ccd} contains no atoms")
    return name_to_element


def normalize_residue_name(resname: str) -> str:
    """
    把修饰残基和 DNA 残基映射到 49 维特征的标准母体。

    输入参数:
        - resname: str, mmCIF `label_comp_id`

    输出:
        - normalized: str, 20 种氨基酸、A/U/C/G 或原大写名称
    """
    normalized = resname.strip().upper()
    return MODIFIED_RESIDUE_TO_PARENT.get(normalized, normalized)


def compute_local_density(
    coords: np.ndarray,
    bin_edges: np.ndarray,
) -> np.ndarray:
    """
    计算完整受体中每个原子的 9 维邻居壳层计数。

    输入参数:
        - coords: np.ndarray, (N,3), float32/float64, 世界坐标 Å
        - bin_edges: np.ndarray, (10,), float32/float64, 单调距离边界；正式值为 0..18 Å

    输出:
        - density: np.ndarray, (N,9), float32, 各半开壳层邻居数的 `log1p`；不计原子自身
    """
    n_atoms = coords.shape[0]
    n_bins = len(bin_edges) - 1
    if n_atoms == 0:
        return np.zeros((0, n_bins), dtype=np.float32)

    tree = cKDTree(np.asarray(coords, dtype=np.float64))
    cumulative = []
    for radius in bin_edges[1:]:
        # np.ndarray[int64], (N,), 半径内邻居数，包含查询原子自身。
        counts = tree.query_ball_point(coords, r=float(radius), workers=1, return_length=True)
        cumulative.append(np.asarray(counts, dtype=np.int64))

    cumulative_counts = np.stack(cumulative, axis=1)
    shell_counts = np.empty((n_atoms, n_bins), dtype=np.int64)
    shell_counts[:, 0] = cumulative_counts[:, 0] - 1
    shell_counts[:, 1:] = cumulative_counts[:, 1:] - cumulative_counts[:, :-1]
    return np.log1p(np.maximum(shell_counts, 0)).astype(np.float32, copy=False)


def compute_receptor_features(receptor_atoms: list[dict[str, Any]]) -> np.ndarray:
    """
    在完整受体上生成逐原子 49 维特征。

    输入参数:
        - receptor_atoms: list[dict[str, Any]], 长度 N, 已完成 model/altloc/重原子选择的 polymer 原子

    输出:
        - feat: np.ndarray, (N,49), float32，依次为元素 6、残基 25、理化 8、质量 1、局部密度 9
    """
    n_atoms = len(receptor_atoms)
    feat = np.zeros((n_atoms, 49), dtype=np.float32)
    element_to_index = {name: index for index, name in enumerate(ELEMENT_TYPES)}
    residue_to_index = {name: index for index, name in enumerate(RESIDUE_FEATURE_TYPES)}

    for atom_index, atom in enumerate(receptor_atoms):
        element = atom["element"].strip().upper()
        element_key = element if element in element_to_index else "X"
        residue = normalize_residue_name(atom["label_comp_id"])
        residue_key = residue if residue in residue_to_index else "X"

        feat[atom_index, element_to_index[element_key]] = 1.0
        feat[atom_index, 6 + residue_to_index[residue_key]] = 1.0
        feat[atom_index, 31:39] = np.asarray(RESIDUE_PHYSIO[residue_key], dtype=np.float32)
        feat[atom_index, 39] = NORMALIZED_ATOM_MASS[element_key]

    coords = np.asarray(
        [(atom["x"], atom["y"], atom["z"]) for atom in receptor_atoms],
        dtype=np.float32,
    )
    feat[:, 40:49] = compute_local_density(coords, DENSITY_BIN_EDGES)
    return feat


def build_receptor_bonds(
    receptor_atoms: list[dict[str, Any]],
    struct_conns: list[dict[str, str]],
    ccd_cache_dir: Path,
    *,
    allow_ccd_fetch: bool = True,
    require_atom_name_coverage: bool = False,
    required_atom_name_coverage_residues: AbstractSet[
        tuple[str, str, str, str]
    ] = frozenset(),
) -> tuple[np.ndarray, np.ndarray]:
    """
    生成受体化学键 COO，不包含任何几何 radius/KNN 边。

    输入参数:
        - receptor_atoms: list[dict[str, Any]], 长度 N, 行序即 receptor token 行序
        - struct_conns: list[dict[str,str]], `_struct_conn` 行
        - ccd_cache_dir: Path, CCD RDKit Mol 缓存目录
        - allow_ccd_fetch: bool, 缓存缺失时是否允许访问 RCSB
        - require_atom_name_coverage: bool, 是否要求每个沉积原子名存在于 CCD 模板
        - required_atom_name_coverage_residues: AbstractSet[tuple[str,str,str,str]],
          仅对列出的 `(label_asym_id,label_comp_id,seq_or_auth,icode)` residue
          执行 CCD 身份、atom name 唯一性、名称覆盖与元素一致性检查；用于
          source repair 只约束实际发生 atom-name 迁移的 residue

    输出:
        - bond_index: np.ndarray, (2,E), int32, 每条无向键只保存一次且端点升序
        - bond_type: np.ndarray, (E,), uint8, `single/double/aromatic/backbone/disulfide/covale/triple` 编码
    """
    residue_atoms: dict[tuple[str, str, str, str], dict[str, int]] = defaultdict(dict)
    residue_examples: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    partner_lookup: dict[tuple[str, ...], int] = {}

    for atom_index, atom in enumerate(receptor_atoms):
        rkey = receptor_residue_key(atom)
        residue_atoms[rkey][atom["label_atom_id"]] = atom_index
        residue_examples.setdefault(rkey, atom)
        if atom["label_seq_id"]:
            partner_lookup[(
                "label", atom["label_asym_id"], atom["label_comp_id"],
                atom["label_seq_id"], atom["label_atom_id"],
            )] = atom_index
        if atom["auth_seq_id"]:
            partner_lookup[(
                "auth", atom["auth_asym_id"], atom["auth_comp_id"],
                atom["auth_seq_id"], atom["auth_atom_id"],
            )] = atom_index
            partner_lookup[(
                "label_authseq", atom["label_asym_id"], atom["label_comp_id"],
                atom["auth_seq_id"], atom["label_atom_id"],
            )] = atom_index

    missing_required_residues = sorted(
        set(required_atom_name_coverage_residues).difference(residue_atoms)
    )
    if missing_required_residues:
        raise ReceptorAtomNameCoverageError(
            "required receptor residue keys are absent: "
            f"{missing_required_residues[:10]}"
        )

    # dict[(int,int), int], 同一端点若有显式 crosslink，后写的更具体类型覆盖模板键。
    edges: dict[tuple[int, int], int] = {}
    for rkey, atom_by_name in residue_atoms.items():
        mol = Chem.RemoveHs(
            get_ccd_mol(rkey[1], ccd_cache_dir, allow_fetch=allow_ccd_fetch),
            sanitize=False,
        )
        if require_atom_name_coverage or rkey in required_atom_name_coverage_residues:
            expected_ccd = rkey[1].upper()
            ccd_name_to_element = validated_ccd_atom_name_to_element(mol, expected_ccd)
            missing_names = sorted(set(atom_by_name).difference(ccd_name_to_element))
            if missing_names:
                raise ReceptorAtomNameCoverageError(
                    f"receptor atom names missing from CCD {rkey[1]}: {missing_names[:10]}"
                )
            periodic_table = Chem.GetPeriodicTable()
            element_mismatches = []
            for name, receptor_index in atom_by_name.items():
                observed = periodic_table.GetAtomicNumber(
                    receptor_atoms[receptor_index]["element"].title()
                )
                if observed != ccd_name_to_element[name]:
                    element_mismatches.append(name)
            if element_mismatches:
                raise ReceptorAtomNameCoverageError(
                    f"receptor element mismatch in CCD {expected_ccd}: {element_mismatches[:10]}"
                )
        for bond in mol.GetBonds():
            left_name = mol.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetProp("name")
            right_name = mol.GetAtomWithIdx(bond.GetEndAtomIdx()).GetProp("name")
            if left_name not in atom_by_name or right_name not in atom_by_name:
                continue
            bond_name = bond.GetBondType().name.upper()
            if bond_name == "SINGLE":
                bond_code = BOND_TYPE_TO_ID["single"]
            elif bond_name == "DOUBLE":
                bond_code = BOND_TYPE_TO_ID["double"]
            elif bond_name == "AROMATIC":
                bond_code = BOND_TYPE_TO_ID["aromatic"]
            elif bond_name == "TRIPLE":
                bond_code = BOND_TYPE_TO_ID["triple"]
            else:
                raise UnsupportedReceptorBondType(
                    f"unsupported receptor CCD bond type {bond_name} in {rkey[1]}"
                )
            _set_edge(edges, atom_by_name[left_name], atom_by_name[right_name], bond_code)

    residues_by_chain: dict[str, list[tuple[tuple[str, str, str, str], dict[str, Any]]]] = defaultdict(list)
    for rkey, example in residue_examples.items():
        residues_by_chain[example["label_asym_id"]].append((rkey, example))
    for chain_residues in residues_by_chain.values():
        chain_residues.sort(key=lambda item: _sequence_sort_key(item[1]))
        for (left_key, left), (right_key, right) in zip(chain_residues, chain_residues[1:], strict=False):
            if not _are_consecutive_label_residues(left, right):
                continue
            left_residue = normalize_residue_name(left["label_comp_id"])
            right_residue = normalize_residue_name(right["label_comp_id"])
            if left_residue in AMINO_ACIDS and right_residue in AMINO_ACIDS:
                _add_named_backbone_edge(edges, residue_atoms, left_key, "C", right_key, "N")
            elif left_residue in NUCLEOTIDE_TYPES and right_residue in NUCLEOTIDE_TYPES:
                _add_named_backbone_edge(edges, residue_atoms, left_key, "O3'", right_key, "P")

    for row in struct_conns:
        conn_type = _clean_value(row.get("conn_type_id", "")).lower()
        if conn_type.startswith("disulf"):
            bond_code = BOND_TYPE_TO_ID["disulfide"]
        elif conn_type == "covale":
            bond_code = BOND_TYPE_TO_ID["covale"]
        else:
            continue
        left_index = _lookup_struct_conn_partner(row, "ptnr1_", partner_lookup)
        right_index = _lookup_struct_conn_partner(row, "ptnr2_", partner_lookup)
        if left_index is not None and right_index is not None:
            _set_edge(edges, left_index, right_index, bond_code)

    sorted_edges = sorted(edges.items())
    if not sorted_edges:
        return np.empty((2, 0), dtype=np.int32), np.empty((0,), dtype=np.uint8)
    bond_index = np.asarray([edge for edge, _code in sorted_edges], dtype=np.int32).T
    bond_type = np.asarray([code for _edge, code in sorted_edges], dtype=np.uint8)
    return bond_index, bond_type


def build_receptor_base_arrays(
    receptor_atoms: list[dict[str, Any]],
) -> dict[str, np.ndarray]:
    """
    构造可与旧 Stage C 逐位比较的七个受体基础数组。

    输入参数:
        - receptor_atoms: list[dict[str,Any]], 长度 N, 已选择的 polymer 重原子

    输出:
        - arrays: dict[str,np.ndarray], 包含:
            - `coords`: (N,3) float32, 世界坐标 Å
            - `element`: (N,) uint8, 原子序数
            - `res_type`: (N,) uint8, AdaLigand 29 类残基 id
            - `is_backbone`: (N,) bool, 主链标记
            - `atom_name`: (N,) S4, label atom name
            - `res_index`: (N,) int32, 当前结构的连续残基索引
            - `chain_index`: (N,) int32, 当前结构的连续链索引
    """
    periodic_table = Chem.GetPeriodicTable()
    coords = np.asarray(
        [(atom["x"], atom["y"], atom["z"]) for atom in receptor_atoms],
        dtype=np.float32,
    ).reshape((-1, 3))
    element = np.asarray(
        [periodic_table.GetAtomicNumber(atom["element"].title()) for atom in receptor_atoms],
        dtype=np.uint8,
    )
    res_type = np.asarray(
        [RES_TO_ID.get(_normalize_for_token(atom["label_comp_id"]), RES_TO_ID["UNK"]) for atom in receptor_atoms],
        dtype=np.uint8,
    )
    is_backbone = np.asarray([_is_backbone_atom(atom) for atom in receptor_atoms], dtype=bool)
    atom_name = np.asarray(
        [atom["label_atom_id"].encode("ascii", errors="ignore")[:4] for atom in receptor_atoms],
        dtype="S4",
    )

    residue_to_index: dict[tuple[str, str, str, str], int] = {}
    chain_to_index: dict[str, int] = {}
    res_indices = []
    chain_indices = []
    for atom in receptor_atoms:
        rkey = receptor_residue_key(atom)
        residue_to_index.setdefault(rkey, len(residue_to_index))
        chain_to_index.setdefault(atom["label_asym_id"], len(chain_to_index))
        res_indices.append(residue_to_index[rkey])
        chain_indices.append(chain_to_index[atom["label_asym_id"]])

    return {
        "coords": coords,
        "element": element,
        "res_type": res_type,
        "is_backbone": is_backbone,
        "atom_name": atom_name,
        "res_index": np.asarray(res_indices, dtype=np.int32),
        "chain_index": np.asarray(chain_indices, dtype=np.int32),
    }


def build_receptor_arrays(
    receptor_atoms: list[dict[str, Any]],
    struct_conns: list[dict[str, str]],
    ccd_cache_dir: Path,
    *,
    allow_ccd_fetch: bool = True,
    require_atom_name_coverage: bool = False,
    required_atom_name_coverage_residues: AbstractSet[
        tuple[str, str, str, str]
    ] = frozenset(),
) -> dict[str, np.ndarray]:
    """
    构造新版 `receptor_tokens.npz` 的完整基础数组、化学键与 49 维特征。

    输入参数:
        - receptor_atoms: list[dict[str,Any]], 长度 N, 已选择的 polymer 重原子
        - struct_conns: list[dict[str,str]], `_struct_conn` 行
        - ccd_cache_dir: Path, `raw/ccd_cache` 目录
        - allow_ccd_fetch: bool, 缓存缺失时是否允许访问 RCSB
        - require_atom_name_coverage: bool, 是否要求沉积 atom_name 全部受 CCD 覆盖
        - required_atom_name_coverage_residues: AbstractSet[tuple[str,str,str,str]],
          仅对显式列出的 residue 执行严格 CCD/atom-name/元素覆盖检查

    输出:
        - arrays: dict[str,np.ndarray], 包含七个基础数组以及:
            - `bond_index`: np.ndarray, (2,E), int32, 受体化学键 COO
            - `bond_type`: np.ndarray, (E,), uint8, 稳定受体键类型枚举
            - `feat`: np.ndarray, (N,49), float32, 完整受体特征
    """
    arrays = build_receptor_base_arrays(receptor_atoms)
    bond_index, bond_type = build_receptor_bonds(
        receptor_atoms,
        struct_conns,
        ccd_cache_dir,
        allow_ccd_fetch=allow_ccd_fetch,
        require_atom_name_coverage=require_atom_name_coverage,
        required_atom_name_coverage_residues=required_atom_name_coverage_residues,
    )
    arrays.update({
        "bond_index": bond_index,
        "bond_type": bond_type,
        "feat": compute_receptor_features(receptor_atoms),
    })
    return arrays


def receptor_residue_key(atom: dict[str, Any]) -> tuple[str, str, str, str]:
    """返回 `(label_asym_id, label_comp_id, seq_or_auth, icode)` residue 键。"""
    seq = atom["label_seq_id"] or atom["auth_seq_id"]
    return (atom["label_asym_id"], atom["label_comp_id"], str(seq), atom["icode"])


def _clean_value(value: str) -> str:
    """清理 mmCIF 空值和成对引号。"""
    if value in {".", "?"}:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _set_edge(edges: dict[tuple[int, int], int], left: int, right: int, bond_code: int) -> None:
    """规范化无向端点并写入/覆盖一条化学键。"""
    if left == right:
        return
    edge = (min(left, right), max(left, right))
    edges[edge] = bond_code


def _sequence_sort_key(atom: dict[str, Any]) -> tuple[int, int, str]:
    """优先按数值 label_seq_id 排序；缺失编号放在末尾。"""
    seq = atom["label_seq_id"]
    if str(seq).lstrip("-").isdigit():
        return (0, int(seq), atom["label_comp_id"])
    return (1, int(atom["atom_site_id"]), atom["label_comp_id"])


def _are_consecutive_label_residues(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """仅在同链且数值 label_seq_id 连续时补主链键，避免跨缺失残基误连。"""
    if left["label_asym_id"] != right["label_asym_id"]:
        return False
    left_seq = str(left["label_seq_id"])
    right_seq = str(right["label_seq_id"])
    if not left_seq.lstrip("-").isdigit() or not right_seq.lstrip("-").isdigit():
        return False
    return int(right_seq) == int(left_seq) + 1


def _add_named_backbone_edge(
    edges: dict[tuple[int, int], int],
    residue_atoms: dict[tuple[str, str, str, str], dict[str, int]],
    left_key: tuple[str, str, str, str],
    left_name: str,
    right_key: tuple[str, str, str, str],
    right_name: str,
) -> None:
    """两端原子都存在时追加一条 backbone 键。"""
    left_index = residue_atoms[left_key].get(left_name)
    right_index = residue_atoms[right_key].get(right_name)
    if left_index is not None and right_index is not None:
        _set_edge(edges, left_index, right_index, BOND_TYPE_TO_ID["backbone"])


def _lookup_struct_conn_partner(
    row: dict[str, str],
    prefix: str,
    partner_lookup: dict[tuple[str, ...], int],
) -> int | None:
    """按 label/auth/label+auth_seq 三种身份查找受体 `_struct_conn` 原子。"""
    keys = (
        (
            "label", _clean_value(row.get(prefix + "label_asym_id", "")),
            _clean_value(row.get(prefix + "label_comp_id", "")).upper(),
            _clean_value(row.get(prefix + "label_seq_id", "")),
            _clean_value(row.get(prefix + "label_atom_id", "")),
        ),
        (
            "auth", _clean_value(row.get(prefix + "auth_asym_id", "")),
            _clean_value(row.get(prefix + "auth_comp_id", "")).upper(),
            _clean_value(row.get(prefix + "auth_seq_id", "")),
            _clean_value(row.get(prefix + "auth_atom_id", "")),
        ),
        (
            "label_authseq", _clean_value(row.get(prefix + "label_asym_id", "")),
            _clean_value(row.get(prefix + "label_comp_id", "")).upper(),
            _clean_value(row.get(prefix + "auth_seq_id", "")),
            _clean_value(row.get(prefix + "label_atom_id", "")),
        ),
    )
    for key in keys:
        if key in partner_lookup:
            return partner_lookup[key]
    return None


def _normalize_for_token(resname: str) -> str:
    """保持旧 C `res_type` 映射，确保增量升级不改写已有 7 个基础数组。"""
    normalized = resname.strip().upper()
    token_mapping = {
        "MSE": "MET", "SEP": "SER", "TPO": "THR", "PTR": "TYR", "HYP": "PRO",
        "SEC": "CYS", "PYL": "LYS", "HID": "HIS", "HIE": "HIS", "HIP": "HIS",
        "CYX": "CYS",
    }
    return token_mapping.get(normalized, normalized)


def _is_backbone_atom(atom: dict[str, Any]) -> bool:
    """按原始 DNA/RNA token 语义判断受体主链原子。"""
    resname = _normalize_for_token(atom["label_comp_id"])
    atom_name = atom["label_atom_id"]
    if resname in {"A", "C", "G", "U", "DA", "DC", "DG", "DT"}:
        return atom_name in NUCLEIC_BACKBONE
    return atom_name in PROTEIN_BACKBONE
