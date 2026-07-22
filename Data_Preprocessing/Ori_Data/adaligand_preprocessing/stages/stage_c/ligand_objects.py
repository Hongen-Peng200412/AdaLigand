# Stage C 配体对象的构造、缓存、编号和 NPZ 契约。
# 主要输入：CCD 残基定义、mmCIF occurrence 原子和键类型。
# 主要输出：可序列化 LigandObject、原子名/元素/键/坐标等配体化学字段。
# 关键边界：模板化学对象与真实 occurrence 坐标分离；candidate_id 不是永久身份。
"""配体化学对象 LigandObject 的生成（沿用 Emap2lig 血统）。

把一个 CCD 或一条 BRANCHED 糖链变成可复用的参考化学对象：
- get_ccd_mol：从本地 pkl 缓存或 RCSB ligand-CIF 取 CCD 的 RDKit 分子。
- Atom / Bond：Emap2lig 的结构化 dtype（element/charge/ref_pos/chirality/in_ring/residue_id 等）。
- process_molecule / process_branched_ligand：物化为 LigandObject 并以不压缩 npz 落盘（按 object_key 去重）。
注意：这里只产出参考构象 ref_pos，不含沉积态真实坐标（真实坐标由 parse 单独抽取）。
"""

from __future__ import annotations

import os
import pickle
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import requests
from pdbeccdutils.core import ccd_reader
from rdkit import Chem
from rdkit.Chem.rdchem import Mol

from adaligand_preprocessing.utils.io import atomic_replace, atomic_save_npz, file_lock, safe_object_filename

Chem.SetDefaultPickleProperties(Chem.PropertyPickleOptions.AllProps)

chirality_types = [
    "CHI_OTHER",
    "CHI_OCTAHEDRAL",
    "CHI_TETRAHEDRAL_CW",
    "CHI_TRIGONALBIPYRAMIDAL",
    "CHI_UNSPECIFIED",
    "CHI_TETRAHEDRAL_CCW",
    "CHI_SQUAREPLANAR",
]
chirality_type_ids = {chirality: i for i, chirality in enumerate(chirality_types)}

bond_types = [
    "SINGLE",
    "DOUBLE",
    "TRIPLE",
    "DATIVE",
    "AROMATIC",
]
bond_type_ids = {bond: i for i, bond in enumerate(bond_types)}

Atom = [
    ("name", np.dtype("4i1")),
    ("element", np.dtype("i1")),
    ("charge", np.dtype("i1")),
    ("coords", np.dtype("3f4")),
    ("ref_pos", np.dtype("3f4")),
    ("is_present", np.dtype("?")),
    ("chirality", np.dtype("7?")),
    ("in_ring", np.dtype("4?")),
    ("residue_id", np.dtype("i4")),
]

Bond = [
    ("atom_1", np.dtype("i4")),
    ("atom_2", np.dtype("i4")),
    ("type", np.dtype("5?")),
    ("in_ring", np.dtype("4?")),
]

_RCSB_CIF_URL = "https://files.rcsb.org/ligands/download/{code}.cif"


class CCDFetchError(RuntimeError):
    """CCD 组件无法下载或解析时抛出的错误。"""


class BranchedBondError(RuntimeError):
    """BRANCHED 跨残基键无法解析到 LigandObject 原子时抛出的错误。"""


@dataclass(frozen=True)
class LigandObject:
    """
    Emap2lig 血统的参考配体对象。

    输入参数:
        - smiles: str, 配体 SMILES; BRANCHED 对象为空字符串
        - atom_names: list[str], 长度 M, LigandObject 原子名
        - atoms: np.ndarray, (M,), dtype=Atom, 原子参考特征
        - bonds: np.ndarray, (E,), dtype=Bond, 配体内部键
        - name: str, 当前对象名, AdaLigand 中使用 object_key
        - residue_names: list[str], 长度 R, 组分 CCD 名称
        - symmetries: list, 对称性列表; 当前 Stage1 保留空列表
        - blobs: list[int] 或 None, 推理期字段; Stage1 训练数据写 None
    """

    smiles: str
    atom_names: list[str]
    atoms: np.ndarray
    bonds: np.ndarray
    name: str
    residue_names: list[str]
    symmetries: list
    blobs: list[int] | None = None

    def dump(self, path: Path) -> None:
        """
        保存为不压缩 npz。

        输入参数:
            - path: Path, 输出 `.npz` 文件路径

        输出:
            - None: 文件写入完成
        """
        atomic_save_npz(path, **asdict(self))


@dataclass(frozen=True)
class LigandRecord:
    """
    已知配体输入记录。

    输入参数:
        - type: Literal["SMILES", "BRANCHED", "CCD"], 配体输入类型
        - name: str, 配体名称; CCD 为三字母代码, BRANCHED 为 object_key
        - blobs: list[int] 或 None, 推理期字段; Stage1 写 None
        - smiles: str 或 None, SMILES 输入
        - residues: dict[int, str] 或 None, BRANCHED 的 residue index 到 CCD 名称映射
        - bonds: list[tuple[int, str, int, str]] 或 None, BRANCHED 残基间键
    """

    type: Literal["SMILES", "BRANCHED", "CCD"]
    name: str
    blobs: list[int] | None = None
    smiles: str | None = None
    residues: dict[int, str] | None = None
    bonds: list[tuple[int, str, int, str]] | None = None


def get_ccd_mol(
    code: str,
    ccd_cache_dir: Path,
    *,
    allow_fetch: bool = True,
) -> Mol:
    """
    从本地缓存或 RCSB CCD CIF 解析 RDKit Mol。

    输入参数:
        - code: str, CCD 三字母代码, 大小写不敏感
        - ccd_cache_dir: Path, `raw/ccd_cache` 目录
        - allow_fetch: bool, 缓存缺失时是否允许访问 RCSB；只读审计必须传 False

    输出:
        - mol: rdkit.Chem.rdchem.Mol, 带 CCD atom name 和 conformer 的分子对象
    """
    normalized_code = code.strip().upper()
    if not normalized_code:
        raise CCDFetchError("empty CCD code")

    ccd_pickle = ccd_cache_dir / f"{normalized_code}.pkl"
    if not allow_fetch:
        if not ccd_pickle.exists():
            raise CCDFetchError(
                f"CCD cache is missing during read-only audit: {normalized_code}"
            )
        with ccd_pickle.open("rb") as handle:
            return pickle.load(handle)

    ccd_cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = ccd_cache_dir / ".locks" / f"{normalized_code}.lock"
    with file_lock(lock_path):
        if ccd_pickle.exists():
            with ccd_pickle.open("rb") as handle:
                return pickle.load(handle)

        url = _RCSB_CIF_URL.format(code=normalized_code)
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CCDFetchError(f"failed to fetch CCD {normalized_code}: {exc}") from exc

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cif", delete=False) as tmp:
                tmp.write(response.text)
                tmp_path = tmp.name
            result = ccd_reader.read_pdb_cif_file(tmp_path, sanitize=False)
            mol = result.component.mol
        except Exception as exc:
            raise CCDFetchError(f"failed to parse CCD {normalized_code}: {exc}") from exc
        finally:
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)

        if mol.GetNumAtoms() == 0:
            raise CCDFetchError(f"CCD {normalized_code} contains no atoms")
        mol.SetProp("PDB_NAME", normalized_code)
        pickle_tmp = ccd_pickle.with_name(f"{ccd_pickle.name}.tmp.{os.getpid()}")
        with pickle_tmp.open("wb") as handle:
            pickle.dump(mol, handle)
        atomic_replace(pickle_tmp, ccd_pickle)
        return mol


def ligand_object_is_valid(path: Path, object_key: str) -> bool:
    """
    检查去重 LigandObject 是否满足当前稳定 schema。

    输入参数:
        - path: Path, `ligand_objects/*.npz`
        - object_key: str, 期望写入 `name` 的去重键

    输出:
        - valid: bool, 必需字段、dtype、行数和 name 均正确时为 True
    """
    required = {
        "atoms", "bonds", "atom_names", "residue_names", "smiles", "name", "symmetries", "blobs",
    }
    try:
        with np.load(path, allow_pickle=True) as data:
            if not required.issubset(data.files):
                return False
            atoms = data["atoms"]
            bonds = data["bonds"]
            atom_names = data["atom_names"]
            if atoms.dtype != np.dtype(Atom) or bonds.dtype != np.dtype(Bond):
                return False
            if atoms.ndim != 1 or bonds.ndim != 1 or len(atom_names) != len(atoms):
                return False
            if str(data["name"].item()) != object_key:
                return False
            if bonds.size:
                endpoints = np.concatenate((bonds["atom_1"], bonds["atom_2"]))
                if endpoints.min() < 0 or endpoints.max() >= len(atoms):
                    return False
            return True
    except (OSError, ValueError, KeyError):
        return False


def convert_atom_name(name: str) -> tuple[int, int, int, int]:
    """
    将 PDB/CCD 原子名编码为 Emap2lig 的 4 字符整数格式。

    输入参数:
        - name: str, 长度不超过 4 的原子名

    输出:
        - name_code: tuple[int, int, int, int], 每个字符为 `ord(c)-32`, 右侧补 0
    """
    name = name.strip()
    name_code = [ord(c) - 32 for c in name]
    if len(name_code) > 4:
        raise ValueError(f"Atom name {name!r} exceeds 4 characters")
    name_code = name_code + [0] * (4 - len(name_code))
    return tuple(name_code)  # type: ignore[return-value]


def _extract_atom_features(
    mol: Chem.Mol,
    residue_id: int = 1,
    auto_name: bool = False,
) -> tuple[list[tuple], list[str]]:
    """
    从 RDKit Mol 提取 LigandObject 原子特征。

    输入参数:
        - mol: Chem.Mol, 已有 CCD atom name 和 conformer 的重原子分子
        - residue_id: int, BRANCHED 对象中的 residue 编号, 从 1 开始
        - auto_name: bool, 缺少 atom name 时是否按元素和索引生成名称

    输出:
        - result: tuple[list[tuple], list[str]], 包含:
            - atom_tuples: list[tuple], 长度 M, 可转为 dtype=Atom 的记录
            - atom_names: list[str], 长度 M, 原子名列表
    """
    atom_tuples: list[tuple] = []
    atom_names: list[str] = []

    for atom_idx, atom in enumerate(mol.GetAtoms()):
        if atom.HasProp("name"):
            atom_name = atom.GetProp("name")
        elif auto_name:
            atom_name = f"{atom.GetSymbol()}{atom_idx + 1}"
        else:
            atom_name = ""

        atom_names.append(atom_name)
        name_code = convert_atom_name(atom_name)
        atomic_num = atom.GetAtomicNum()
        formal_charge = atom.GetFormalCharge()

        chirality_type = atom.GetChiralTag().name
        chirality_type_id = chirality_type_ids.get(chirality_type, 0)
        chirality_one_hot = [False] * 7
        chirality_one_hot[chirality_type_id] = True

        in_ring = [
            atom.IsInRingSize(3),
            atom.IsInRingSize(4),
            atom.IsInRingSize(5),
            atom.IsInRingSize(6),
        ]

        try:
            conformer = mol.GetConformer()
            pos = conformer.GetAtomPosition(atom.GetIdx())
            ref_pos = (pos.x, pos.y, pos.z)
        except ValueError:
            ref_pos = (0.0, 0.0, 0.0)

        atom_tuples.append(
            (
                name_code,
                atomic_num,
                formal_charge,
                (0.0, 0.0, 0.0),
                ref_pos,
                False,
                tuple(chirality_one_hot),
                tuple(in_ring),
                residue_id,
            )
        )

    return atom_tuples, atom_names


def _extract_bond_features(
    mol: Chem.Mol,
    atom_offset: int = 0,
) -> list[tuple]:
    """
    从 RDKit Mol 提取 LigandObject 键特征。

    输入参数:
        - mol: Chem.Mol, 输入分子
        - atom_offset: int, BRANCHED 拼接时加到局部 atom index 上的偏移

    输出:
        - bond_tuples: list[tuple], 长度 E, 可转为 dtype=Bond 的记录
    """
    bond_tuples: list[tuple] = []

    for bond in mol.GetBonds():
        begin_idx = bond.GetBeginAtomIdx() + atom_offset
        end_idx = bond.GetEndAtomIdx() + atom_offset
        bond_type = bond.GetBondType().name
        bond_type_id = bond_type_ids.get(bond_type, 0)
        bond_type_one_hot = [False] * 5
        if bond_type_id < 5:
            bond_type_one_hot[bond_type_id] = True

        in_ring = [
            bond.IsInRingSize(3),
            bond.IsInRingSize(4),
            bond.IsInRingSize(5),
            bond.IsInRingSize(6),
        ]

        bond_tuples.append((begin_idx, end_idx, tuple(bond_type_one_hot), tuple(in_ring)))

    return bond_tuples


def process_branched_ligand(
    branched_config: dict,
    ligand_name: str,
    ligands_dir: Path,
    ccd_cache_dir: Path,
    blobs: list[int] | None = None,
) -> None:
    """
    处理 BRANCHED 配体配置并保存 LigandObject。

    输入参数:
        - branched_config: dict, 包含 `residues` 和 `bonds` 的配置
        - ligand_name: str, 输出对象名, AdaLigand 中为 object_key
        - ligands_dir: Path, ligand_objects 输出目录
        - ccd_cache_dir: Path, CCD pkl 缓存目录
        - blobs: list[int] 或 None, 推理期字段; Stage1 传 None

    输出:
        - None: 写入 `{ligand_name}.npz`
    """
    residue_list = branched_config.get("residues", [])
    inter_bonds = branched_config.get("bonds", [])

    residue_names = []
    for res_entry in residue_list:
        parts = res_entry.strip().split(".")
        if len(parts) >= 2:
            res_name = parts[1].strip()
            residue_names.append(res_name)

    all_atoms: list[tuple] = []
    all_bonds: list[tuple] = []
    atom_names: list[str] = []
    atom_offset = 0
    residue_atom_counts: list[int] = []

    for residue_idx, res_name in enumerate(residue_names, start=1):
        ref_mol = get_ccd_mol(res_name, ccd_cache_dir)
        ref_mol = Chem.RemoveHs(ref_mol, sanitize=False)

        residue_atoms, residue_atom_names = _extract_atom_features(
            ref_mol, residue_id=residue_idx, auto_name=True
        )
        all_atoms.extend(residue_atoms)
        atom_names.extend(residue_atom_names)
        residue_atom_counts.append(len(residue_atoms))

        residue_bonds = _extract_bond_features(ref_mol, atom_offset=atom_offset)
        all_bonds.extend(residue_bonds)

        atom_offset += len(residue_atoms)

    for bond_info in inter_bonds:
        if len(bond_info) != 4:
            raise BranchedBondError(f"invalid bond format for {ligand_name}: {bond_info}")
        res1_idx, atom1_name, res2_idx, atom2_name = bond_info
        res1_idx -= 1
        res2_idx -= 1
        if (
            res1_idx < 0
            or res2_idx < 0
            or res1_idx >= len(residue_atom_counts)
            or res2_idx >= len(residue_atom_counts)
        ):
            raise BranchedBondError(f"invalid residue index for {ligand_name}: {bond_info}")

        res1_offset = sum(residue_atom_counts[:res1_idx])
        res2_offset = sum(residue_atom_counts[:res2_idx])

        atom1_idx = None
        atom2_idx = None

        for i in range(residue_atom_counts[res1_idx]):
            if atom_names[res1_offset + i] == atom1_name:
                atom1_idx = res1_offset + i
                break

        for i in range(residue_atom_counts[res2_idx]):
            if atom_names[res2_offset + i] == atom2_name:
                atom2_idx = res2_offset + i
                break

        if atom1_idx is not None and atom2_idx is not None:
            bond_type_one_hot = [True, False, False, False, False]
            in_ring = [False, False, False, False]
            all_bonds.append((atom1_idx, atom2_idx, tuple(bond_type_one_hot), tuple(in_ring)))
        else:
            raise BranchedBondError(f"could not find atoms for {ligand_name} bond: {bond_info}")

    atoms = np.array(all_atoms, dtype=Atom)
    bonds = np.array(all_bonds, dtype=Bond)

    ref_mol_object = LigandObject(
        smiles="",
        atom_names=atom_names,
        atoms=atoms,
        bonds=bonds,
        name=ligand_name,
        residue_names=residue_names,
        symmetries=[],
        blobs=blobs,
    )

    output_path = ligands_dir / f"{safe_object_filename(ligand_name)}.npz"
    ref_mol_object.dump(output_path)


def process_molecule(
    ref_mol: Chem.Mol,
    ligand_name: str,
    smiles: str,
    ligands_dir: Path,
    blobs: list[int] | None = None,
    residue_name: str | None = None,
) -> None:
    """
    处理单分子配体并保存 LigandObject。

    输入参数:
        - ref_mol: Chem.Mol, 已去氢的 CCD/RDKit 分子
        - ligand_name: str, 输出对象名, AdaLigand 中为 object_key
        - smiles: str, 分子 SMILES
        - ligands_dir: Path, ligand_objects 输出目录
        - blobs: list[int] 或 None, 推理期字段; Stage1 传 None
        - residue_name: str 或 None, 单 residue 的真实 CCD 名; None 时沿用 ligand_name

    输出:
        - None: 写入 `{ligand_name}.npz`
    """
    atoms_list, atom_names = _extract_atom_features(ref_mol, residue_id=1)
    bonds_list = _extract_bond_features(ref_mol)

    atoms = np.array(atoms_list, dtype=Atom)
    bonds = np.array(bonds_list, dtype=Bond)

    ref_mol_object = LigandObject(
        smiles=smiles,
        atom_names=atom_names,
        atoms=atoms,
        bonds=bonds,
        name=ligand_name,
        residue_names=[residue_name or ligand_name],
        symmetries=[],
        blobs=blobs,
    )

    output_path = ligands_dir / f"{safe_object_filename(ligand_name)}.npz"
    ref_mol_object.dump(output_path)


def materialize_ccd_ligand(
    ccd_id: str,
    object_key: str,
    ligands_dir: Path,
    ccd_cache_dir: Path,
    overwrite: bool = False,
) -> None:
    """
    按 CCD 编号物化单 residue LigandObject。

    输入参数:
        - ccd_id: str, CCD 三字母代码
        - object_key: str, AdaLigand 对象键
        - ligands_dir: Path, ligand_objects 输出目录
        - ccd_cache_dir: Path, CCD pkl 缓存目录
        - overwrite: bool, 是否覆盖已存在的 LigandObject 文件

    输出:
        - None: 目标对象已存在时跳过, 否则写入 npz
    """
    output_path = ligands_dir / f"{safe_object_filename(object_key)}.npz"
    if output_path.exists() and not overwrite:
        return
    ref_mol = get_ccd_mol(ccd_id, ccd_cache_dir)
    smiles = Chem.MolToSmiles(ref_mol)
    ref_mol = Chem.RemoveHs(ref_mol, sanitize=False)
    process_molecule(ref_mol, object_key, smiles, ligands_dir, None, ccd_id)
