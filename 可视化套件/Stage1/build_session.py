"""为单个 Stage1 推理样本生成自包含 PyMOL 会话.

主入口是 ``build_session``. 它只读 AdaLigand 源产物和 Pocket Plus Stage1
推理产物, 并向 ``--output`` 写入一个 ``.pse`` 文件. 会话包含完整
实验密度 map 与 mesh、受体分子对象、逐 occurrence GT 配体对象和逐候选
预测 blob 对象. 本模块不修改任一输入目录或 Stage1 产物契约.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Sequence

import numpy as np

import pymol
from chempy import Atom, Bond
from chempy.brick import Brick
from chempy.models import Indexed
from pymol import cmd


# 长度 29 的受体残基词表; 元素位置是 receptor_tokens.res_type 的 uint8 类别编号.
_RESIDUE_NAMES = (
    "ALA",
    "ARG",
    "ASN",
    "ASP",
    "CYS",
    "GLN",
    "GLU",
    "GLY",
    "HIS",
    "ILE",
    "LEU",
    "LYS",
    "MET",
    "PHE",
    "PRO",
    "SER",
    "THR",
    "TRP",
    "TYR",
    "VAL",
    "A",
    "C",
    "G",
    "U",
    "DA",
    "DC",
    "DG",
    "DT",
    "UNK",
)
# 长度 119 的原子序数到元素符号词表; 元素位置 0 保留给未知元素 X.
_ELEMENT_SYMBOLS = (
    "X",
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
    "Np",
    "Pu",
    "Am",
    "Cm",
    "Bk",
    "Cf",
    "Es",
    "Fm",
    "Md",
    "No",
    "Lr",
    "Rf",
    "Db",
    "Sg",
    "Bh",
    "Hs",
    "Mt",
    "Ds",
    "Rg",
    "Cn",
    "Nh",
    "Fl",
    "Mc",
    "Lv",
    "Ts",
    "Og",
)
# 受体 bond_type 0:6 到 PyMOL order 的映射; 芳香键用 PyMOL order=4, 主链、二硫键和共价连接按单键显示.
_RECEPTOR_BOND_ORDERS = {0: 1, 1: 2, 2: 4, 3: 1, 4: 1, 5: 1, 6: 3}
# 长度 5 的 ligand_objects.bonds.type 到 PyMOL order 的映射; 位置依次是单键、双键、三键、配位键和芳香键.
_LIGAND_BOND_ORDERS = (1, 2, 3, 1, 4)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析稳定的单 PDB 会话生成入口.

    输入参数:
        - argv: 不含可执行文件名的命令行 token 序列; ``None`` 表示读取当前进程命令行.

    返回值:
        - args: argparse.Namespace; 包含两个输入根、producer、split、PDB 编号、F-alpha、evaluation 名和输出 ``.pse`` 路径.
    """
    parser = argparse.ArgumentParser(
        description="Create one self-contained Stage1 PyMOL .pse session."
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--inference-root", type=Path, required=True)
    parser.add_argument("--producer", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--pdb-id", required=True)
    parser.add_argument("--alpha", type=float, required=True)
    parser.add_argument("--evaluation-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _element_symbol(atomic_number: int) -> str:
    """把原子序数转为元素符号; 未知序数返回 ``X``."""
    if 0 < atomic_number < len(_ELEMENT_SYMBOLS):
        return _ELEMENT_SYMBOLS[atomic_number]
    return "X"


def _require_arrays(arrays: Any, names: Sequence[str], path: Path) -> None:
    """在产物写入前拒绝缺少必需契约字段的 NPZ."""
    missing = [name for name in names if name not in arrays.files]
    if missing:
        raise KeyError(f"{path} is missing required arrays: {', '.join(missing)}")


def _new_atom(
    *,
    coord_xyz: Sequence[float],
    symbol: str,
    name: str,
    residue_name: str,
    residue_id: str,
    chain_id: str,
    formal_charge: int,
    insertion_code: str,
) -> Atom:
    """用明确的世界坐标与原子标识创建一个 PyMOL 原子.

    输入参数:
        - coord_xyz: (3,), 原子的世界 XYZ 坐标, 单位 Å.
        - symbol: str, 标准元素符号或预测伪原子使用的 ``C``.
        - name: str, PyMOL 原子名.
        - residue_name: str, PyMOL 残基名.
        - residue_id: str, PyMOL 残基编号.
        - chain_id: str, PyMOL 链标识.
        - formal_charge: int, 形式电荷; 预测伪原子和受体使用 0.
        - insertion_code: str, 沉积 GT 配体的插入码; 受体和预测伪原子使用空字符串.

    返回值:
        - atom: chempy.Atom; ``coord`` 保留世界 XYZ 坐标, 其他字段可供 PyMOL 选区和分子显示使用.
    """
    atom = Atom()
    atom.coord = [float(value) for value in coord_xyz]
    atom.symbol = symbol
    atom.name = name
    atom.resn = residue_name
    atom.resi = residue_id
    atom.chain = chain_id
    atom.formal_charge = int(formal_charge)
    atom.ins_code = insertion_code
    return atom


# ================================================================================================


def _load_density(data_root: Path, pdb_id: str) -> tuple[np.ndarray, np.ndarray, float]:
    """把完整归一化实验密度加载到当前 PyMOL 状态.

    输入参数:
        - data_root: Path, AdaLigand 数据根; 内部读取 ``density/{pdb_id}/exp.npy`` 和 ``exp.npz``.
        - pdb_id: str, 小写 PDB 编号, 如 ``9ter``.

    PyMOL 副作用:
        - density_exp_map: PyMOL map; 完整实验密度, 首个采样点是首个体素中心的世界 XYZ 坐标.
        - density_exp_mesh: PyMOL mesh; 使用 ``contour_canonical`` 从 ``density_exp_map`` 创建.
        - density: PyMOL group; 包含上述 map 和 mesh.

    返回值:
        - origin_center_xyz: float64, (3,), 首个体素中心的世界 XYZ 坐标, 单位 Å.
        - voxel_size_xyz: float64, (3,), 密度网格沿 XYZ 三轴的体素间距, 单位 Å.
        - contour_canonical: float, 经 AdaLigand 强度归一化的默认等值面阈值.
    """
    density_dir = data_root / "density" / pdb_id
    array_path = density_dir / "exp.npy"
    metadata_path = density_dir / "exp.npz"
    # float32, (1, Z, Y, X), 强度归一化后的完整实验密度; 只用 mmap 读取, 不改写源数组.
    density_czyx = np.load(array_path, mmap_mode="r", allow_pickle=False)
    if density_czyx.ndim != 4 or density_czyx.shape[0] != 1:
        raise ValueError(f"{array_path} must have shape (1,Z,Y,X)")

    with np.load(metadata_path, allow_pickle=False) as metadata:
        _require_arrays(
            metadata, ("origin", "voxel_size", "contour_canonical"), metadata_path
        )
        # float64, (3,), 第一个密度体素边界下角的世界 XYZ 坐标, 单位 Å.
        origin_boundary_xyz = np.asarray(metadata["origin"], dtype=np.float64)
        # float64, (3,), 密度网格沿 XYZ 三轴的体素间距, 单位 Å.
        voxel_size_xyz = np.asarray(metadata["voxel_size"], dtype=np.float64)
        # 标量, AdaLigand 密度强度归一化后的默认等值面阈值.
        contour_canonical = float(np.asarray(metadata["contour_canonical"]))
    if origin_boundary_xyz.shape != (3,) or voxel_size_xyz.shape != (3,):
        raise ValueError(f"{metadata_path} origin and voxel_size must have shape (3,)")
    if np.any(voxel_size_xyz <= 0.0) or not np.all(np.isfinite(voxel_size_xyz)):
        raise ValueError(f"{metadata_path} voxel_size must be finite and positive")
    if not math.isfinite(contour_canonical):
        raise ValueError(f"{metadata_path} contour_canonical must be finite")

    # float32, (X, Y, Z), 同一完整实验密度; exp.npy 采用 ZYX 数组轴, PyMOL Brick 采用 XYZ 数组轴.
    density_xyz = np.transpose(density_czyx[0], (2, 1, 0))
    # float64, (3,), 首个体素中心的世界 XYZ 坐标; Stage1 origin 是体素边界下角, PyMOL Brick origin 是首个采样点中心.
    origin_center_xyz = origin_boundary_xyz + 0.5 * voxel_size_xyz
    # Brick 保留 float32 (X, Y, Z) 数组和世界几何; 避免 from_numpy 把完整密度额外扩大为 float64.
    brick = Brick()
    brick.lvl = np.asarray(density_xyz, dtype=np.float32)
    brick.grid = voxel_size_xyz.tolist()
    brick.origin = origin_center_xyz.tolist()
    brick.dim = list(density_xyz.shape)
    brick.range = [
        float(grid * (dimension - 1))
        for grid, dimension in zip(brick.grid, brick.dim, strict=True)
    ]
    cmd.load_brick(brick, "density_exp_map")
    cmd.isomesh("density_exp_mesh", "density_exp_map", contour_canonical)
    cmd.color("gray70", "density_exp_mesh")
    cmd.group("density", "density_exp_map density_exp_mesh")
    return origin_center_xyz, voxel_size_xyz, contour_canonical


def _load_receptor(data_root: Path, pdb_id: str) -> None:
    """从 ``receptor_tokens.npz`` 加载受体原子和化学键.

    输入参数:
        - data_root: Path, AdaLigand 数据根; 内部读取 ``parse/{pdb_id}/receptor_tokens.npz``.
        - pdb_id: str, 小写 PDB 编号.

    PyMOL 副作用:
        - receptor: PyMOL molecular object; 原子坐标是世界 XYZ, 元素和键型来自受体产物, 链与残基使用稳定合成标识.
    """
    receptor_path = data_root / "parse" / pdb_id / "receptor_tokens.npz"
    with np.load(receptor_path, allow_pickle=False) as arrays:
        required = (
            "coords",
            "element",
            "res_type",
            "atom_name",
            "res_index",
            "chain_index",
            "bond_index",
            "bond_type",
        )
        _require_arrays(arrays, required, receptor_path)
        # float32, (N_atom, 3), 受体重原子的世界 XYZ 坐标, 单位 Å.
        coords_xyz = np.asarray(arrays["coords"])
        # uint8, (N_atom,), 与 coords_xyz 第一维逐原子对齐的原子序数.
        elements = np.asarray(arrays["element"])
        # uint8, (N_atom,), 与 coords_xyz 逐原子对齐的 _RESIDUE_NAMES 类别编号.
        residue_types = np.asarray(arrays["res_type"])
        # S4, (N_atom,), 与 coords_xyz 逐原子对齐的 ASCII 原子名.
        atom_names = np.asarray(arrays["atom_name"])
        # int32, (N_atom,), 每个受体原子所属的 PDB 内全局零基残基编号.
        residue_indices = np.asarray(arrays["res_index"])
        # int32, (N_atom,), 每个受体原子所属的 PDB 内全局零基链编号.
        chain_indices = np.asarray(arrays["chain_index"])
        # int32, (2, N_bond), 受体无向键的端点; 数值索引 coords_xyz 的第一维.
        bond_indices = np.asarray(arrays["bond_index"])
        # uint8, (N_bond,), 与 bond_indices 第二维逐键对齐的受体键型编号.
        bond_types = np.asarray(arrays["bond_type"])

    # Indexed 模型按 receptor_tokens 原子顺序累积; bond_indices 因此可直接作为 PyMOL 零基原子索引.
    model = Indexed()
    for coord_xyz, element, residue_type, atom_name, residue_index, chain_index in zip(
        coords_xyz,
        elements,
        residue_types,
        atom_names,
        residue_indices,
        chain_indices,
        strict=True,
    ):
        residue_type_int = int(residue_type)
        residue_name = (
            _RESIDUE_NAMES[residue_type_int]
            if 0 <= residue_type_int < len(_RESIDUE_NAMES)
            else "UNK"
        )
        decoded_name = bytes(atom_name).decode("ascii", errors="replace").strip() or "X"
        model.atom.append(
            _new_atom(
                coord_xyz=coord_xyz,
                symbol=_element_symbol(int(element)),
                name=decoded_name,
                residue_name=residue_name,
                residue_id=str(int(residue_index) + 1),
                chain_id=f"C{int(chain_index)}",
                formal_charge=0,
                insertion_code="",
            )
        )
    if bond_indices.ndim != 2 or bond_indices.shape[0] != 2:
        raise ValueError(f"{receptor_path} bond_index must have shape (2,E)")
    for endpoints, bond_type in zip(bond_indices.T, bond_types, strict=True):
        # endpoints 是长度 2 的零基受体原子索引; order=4 表示芳香键.
        bond = Bond()
        bond.index = [int(endpoints[0]), int(endpoints[1])]
        bond.order = _RECEPTOR_BOND_ORDERS[int(bond_type)]
        model.bond.append(bond)
    cmd.load_model(model, "receptor")
    cmd.show("cartoon", "receptor")
    cmd.show("sticks", "receptor")
    cmd.set_title(
        "receptor", 1, "AdaLigand receptor_tokens; synthetic chain/residue IDs"
    )


def _load_ground_truth(data_root: Path, pdb_id: str) -> list[str]:
    """把每个沉积配体 occurrence 加载为独立分子对象.

    输入参数:
        - data_root: Path, AdaLigand 数据根; 读取 occurrence 记录、沉积坐标和去重 ligand object.
        - pdb_id: str, 小写 PDB 编号.

    PyMOL 副作用:
        - gt_occ_{candidate_id}_{object_key}: PyMOL molecular object; 每个 occurrence 一个对象, 只包含 ``present_{candidate_id}=True`` 的沉积原子和它们之间的化学键.
        - ground_truth: PyMOL group; 包含当前 PDB 的全部 GT occurrence 对象.

    返回值:
        - object_names: list[str], 按 ``occurrences.jsonl`` 顺序排列的 GT PyMOL 对象名.
    """
    parse_dir = data_root / "parse" / pdb_id
    occurrences_path = parse_dir / "occurrences.jsonl"
    coords_path = parse_dir / "ligand_coords.npz"
    with occurrences_path.open("r", encoding="utf-8") as handle:
        # 长度 N_occ 的记录列表, 每项描述一个沉积配体 occurrence; 保留 occurrences.jsonl 的稳定顺序.
        occurrences = [json.loads(line) for line in handle if line.strip()]
    # 长度 N_occ 的 PyMOL 对象名列表; 与 occurrences 逐 occurrence 对齐.
    object_names: list[str] = []
    with np.load(coords_path, allow_pickle=False) as coordinate_arrays:
        for occurrence in occurrences:
            candidate_id = int(occurrence["candidate_id"])
            object_key = str(occurrence["object_key"])
            object_path = (
                data_root
                / "ligand_objects"
                / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', object_key)}.npz"
            )
            coord_key = f"coords_{candidate_id}"
            present_key = f"present_{candidate_id}"
            _require_arrays(coordinate_arrays, (coord_key, present_key), coords_path)
            # float32, (N_template_atom, 3), 当前 occurrence 的沉积世界 XYZ 坐标, 单位 Å; 缺失模板原子是 NaN.
            coords_xyz = np.asarray(coordinate_arrays[coord_key])
            # bool, (N_template_atom,), 遮盖 coords_xyz 第一维; True 表示该模板原子实际出现在沉积结构中.
            present = np.asarray(coordinate_arrays[present_key], dtype=bool)
            with np.load(object_path, allow_pickle=True) as ligand:
                _require_arrays(
                    ligand,
                    ("atoms", "atom_names", "bonds", "residue_names"),
                    object_path,
                )
                # (N_template_atom,), 配体模板的结构化原子属性; 与 coords_xyz 第一维对齐.
                atoms = np.asarray(ligand["atoms"])
                # Unicode, (N_template_atom,), 与 atoms 逐模板原子对齐的沉积原子名.
                atom_names = np.asarray(ligand["atom_names"])
                # (N_ligand_bond,), 配体模板键记录; atom_1/atom_2 索引 atoms, type 是长度 5 的键型独热编码.
                bonds = np.asarray(ligand["bonds"])
                # Unicode, (N_residue,), 配体模板的一基 residue_id 对应 residue_names[residue_id - 1].
                residue_names = np.asarray(ligand["residue_names"])
            if len(atoms) != len(coords_xyz) or present.shape != (len(atoms),):
                raise ValueError(
                    f"ligand template and deposited coordinates differ: {object_path}"
                )

            # 当前 occurrence 的 PyMOL 分子; 只追加 present=True 的沉积原子.
            model = Indexed()
            # dict[int,int], 配体模板原子索引到 PyMOL 紧凑原子索引的映射; 用于剔除缺失原子后重建键端点.
            template_to_model: dict[int, int] = {}
            for template_index in np.flatnonzero(present):
                atom = atoms[template_index]
                residue_id = int(atom["residue_id"])
                # 长度必须为 1 的 component 列表; component.index 与 atoms.residue_id 同为一基编号.
                components = [
                    item
                    for item in occurrence["components"]
                    if int(item["index"]) == residue_id
                ]
                if len(components) != 1:
                    raise KeyError(
                        f"occurrence {candidate_id} has {len(components)} components with index {residue_id}"
                    )
                component = components[0]
                if not 1 <= residue_id <= len(residue_names):
                    raise IndexError(
                        f"ligand residue_id={residue_id} is outside residue_names: {object_path}"
                    )
                residue_name = str(residue_names[residue_id - 1])
                model_index = len(model.atom)
                template_to_model[int(template_index)] = model_index
                model.atom.append(
                    _new_atom(
                        coord_xyz=coords_xyz[template_index],
                        symbol=_element_symbol(int(atom["element"])),
                        name=str(atom_names[template_index]),
                        residue_name=residue_name,
                        residue_id=str(component["auth_seq_id"]),
                        chain_id=str(component["auth_asym_id"]),
                        formal_charge=int(atom["charge"]),
                        insertion_code=str(component["icode"]),
                    )
                )
            for bond_record in bonds:
                # 两个整数是 atoms 第一维上的模板原子索引, 并非 PyMOL 紧凑原子索引.
                left_template = int(bond_record["atom_1"])
                right_template = int(bond_record["atom_2"])
                if (
                    left_template not in template_to_model
                    or right_template not in template_to_model
                ):
                    continue
                # int64, (N_active_type,), 当前键独热编码中的 True 位置; 合法契约下长度为 1.
                type_flags = np.flatnonzero(np.asarray(bond_record["type"], dtype=bool))
                type_index = int(type_flags[0]) if len(type_flags) else 0
                bond = Bond()
                bond.index = [
                    template_to_model[left_template],
                    template_to_model[right_template],
                ]
                bond.order = _LIGAND_BOND_ORDERS[type_index]
                model.bond.append(bond)

            safe_object_key = re.sub(r"[^A-Za-z0-9_]+", "_", object_key).strip("_")
            object_name = f"gt_occ_{candidate_id:04d}_{safe_object_key[:40]}"
            cmd.load_model(model, object_name)
            cmd.show("sticks", object_name)
            cmd.show("spheres", object_name)
            cmd.set("sphere_scale", 0.28, object_name)
            cmd.set_title(
                object_name,
                1,
                f"candidate_id={candidate_id}; object_key={object_key}; type={occurrence['type_tag']}",
            )
            object_names.append(object_name)
    if object_names:
        cmd.group("ground_truth", " ".join(object_names))
    else:
        cmd.group("ground_truth")
    return object_names


def _load_predictions(
    inference_root: Path,
    producer: str,
    split: str,
    pdb_id: str,
    alpha: float,
    evaluation_name: str,
    origin_center_xyz: np.ndarray,
    voxel_size_xyz: np.ndarray,
) -> tuple[list[str], list[str]]:
    """把每个评估 blob 加载为独立的体素中心伪原子对象.

    输入参数:
        - inference_root: Path, Stage1 推理根.
        - producer: str, 推理生产者目录名, 如 ``unet_c1-mainchain-ligand_PRAUC_0.602950`` 或 ``Find_0``.
        - split: str, 数据划分目录名, 如 ``held_out_test_0``.
        - pdb_id: str, 小写 PDB 编号.
        - alpha: float, 选择 ``blobs/F{alpha}_blobs.npz`` 的 F-alpha.
        - evaluation_name: str, 不带 ``.npz`` 的评估文件名.
        - origin_center_xyz: float64, (3,), 第一个密度体素中心的世界 XYZ 坐标, 单位 Å.
        - voxel_size_xyz: float64, (3,), 密度网格沿 XYZ 三轴的体素间距, 单位 Å.

    PyMOL 副作用:
        - pred_r*_b*_s*_{selected|unselected}: PyMOL molecular object; 每个评估候选一个对象, 每个 blob 体素中心是一个无键伪原子.
        - predictions_selected: PyMOL group; 包含 ``candidate_selected=True`` 的候选并默认可见.
        - predictions_unselected: PyMOL group; 包含 ``candidate_selected=False`` 的候选并默认隐藏.
        - predictions: PyMOL group; 包含上述两个状态组.

    返回值:
        - selected_names: list[str], 按 evaluation 冻结分数稳定降序排列的默认入选对象名.
        - unselected_names: list[str], 按同一候选轴排列的未入选对象名.
    """
    pdb_root = inference_root / producer / split / pdb_id
    if not math.isfinite(alpha) or alpha <= 0.0:
        raise ValueError("--alpha must be a finite positive number")
    alpha_tag = format(alpha, ".15g").replace(".", "p")
    blobs_path = pdb_root / "blobs" / f"F{alpha_tag}_blobs.npz"
    evaluation_path = pdb_root / "evaluation" / f"{evaluation_name}.npz"
    with np.load(blobs_path, allow_pickle=False) as blobs:
        _require_arrays(
            blobs,
            ("blob_index", "voxel_offsets", "voxel_index_global_zyx"),
            blobs_path,
        )
        # int32, (N_blob,), blobs 候选轴上的稳定 blob 标识.
        blob_indices = np.asarray(blobs["blob_index"])
        # 整数, (N_blob + 1,), 把 voxel_indices_global_zyx 切成 N_blob 个 blob; 首值为 0, 末值是所有 blob 体素总数.
        voxel_offsets = np.asarray(blobs["voxel_offsets"])
        # 整数, (N_blob_voxel, 3), 所有 blob 串接后的全图体素 ZYX 索引; voxel_offsets 定义每个 blob 的区间.
        voxel_indices_global_zyx = np.asarray(blobs["voxel_index_global_zyx"])
    with np.load(evaluation_path, allow_pickle=False) as evaluation:
        _require_arrays(
            evaluation,
            ("source_blob_index", "candidate_score", "candidate_selected"),
            evaluation_path,
        )
        # int32, (N_candidate,), 按冻结分数稳定降序排列的源 blob 标识; 数值对应 blob_indices 中的某一项.
        source_blob_indices = np.asarray(evaluation["source_blob_index"])
        # float32, (N_candidate,), 与 source_blob_indices 逐候选对齐的冻结评估分数.
        candidate_scores = np.asarray(evaluation["candidate_score"])
        # bool, (N_candidate,), 与 source_blob_indices 逐候选对齐; True 表示该 blob 进入最终评估集合.
        candidate_selected = np.asarray(evaluation["candidate_selected"], dtype=bool)
    if not (
        source_blob_indices.shape == candidate_scores.shape == candidate_selected.shape
    ):
        raise ValueError(
            f"candidate arrays must have identical shapes: {evaluation_path}"
        )
    if voxel_offsets.shape != (len(blob_indices) + 1,):
        raise ValueError(
            f"voxel_offsets length does not match blob_index: {blobs_path}"
        )

    # dict[int,int], 稳定 blob_index 到 blobs 候选轴零基位置的映射; 用于解析 evaluation.source_blob_index.
    blob_position = {
        int(blob_index): position for position, blob_index in enumerate(blob_indices)
    }
    # 两个列表共同覆盖 N_candidate 个预测对象名, 且按 candidate_selected 互斥分组.
    selected_names: list[str] = []
    unselected_names: list[str] = []
    # 半径是三轴最小体素间距的一半, 使伪原子球表示对应体素中心而不越过最窄体素边界.
    sphere_radius = 0.5 * float(np.min(voxel_size_xyz))
    for rank_zero, (blob_index_value, score_value, selected_value) in enumerate(
        zip(source_blob_indices, candidate_scores, candidate_selected, strict=True)
    ):
        blob_index = int(blob_index_value)
        score = float(score_value)
        selected = bool(selected_value)
        if blob_index not in blob_position:
            raise KeyError(
                f"evaluation references missing source_blob_index={blob_index}"
            )
        position = blob_position[blob_index]
        # [start:stop] 是当前 source_blob_index 在串接体素数组中的半开区间.
        start = int(voxel_offsets[position])
        stop = int(voxel_offsets[position + 1])
        # 整数, (N_voxel, 3), 当前 blob 的全图 ZYX 体素索引.
        voxel_zyx = voxel_indices_global_zyx[start:stop]
        # 整数, (N_voxel, 3), 换轴后的全图 XYZ 体素索引; 与密度 Brick 共用体素中心几何.
        voxel_xyz = voxel_zyx[:, ::-1]
        # float64, (N_voxel, 3), 当前 blob 每个体素中心的世界 XYZ 坐标, 单位 Å.
        centers_xyz = origin_center_xyz + voxel_xyz * voxel_size_xyz

        # 当前 blob 的 PyMOL 分子对象; 包含 N_voxel 个无键伪原子以保留可选择性.
        model = Indexed()
        for center_xyz in centers_xyz:
            atom = _new_atom(
                coord_xyz=center_xyz,
                symbol="C",
                name="V",
                residue_name="BLB",
                residue_id=str(rank_zero + 1),
                chain_id="P",
                formal_charge=0,
                insertion_code="",
            )
            atom.b = score
            atom.q = 1.0 if selected else 0.0
            atom.vdw = sphere_radius
            model.atom.append(atom)
        score_text = f"{score:.6f}".replace("-", "m").replace(".", "p")
        state = "selected" if selected else "unselected"
        object_name = (
            f"pred_r{rank_zero + 1:04d}_b{blob_index:06d}_s{score_text}_{state}"
        )
        cmd.load_model(model, object_name)
        cmd.show("spheres", object_name)
        cmd.set("sphere_scale", 1.0, object_name)
        cmd.set_title(
            object_name,
            1,
            f"rank={rank_zero + 1}; source_blob_index={blob_index}; score={score:.9g}; candidate_selected={selected}",
        )
        if selected:
            selected_names.append(object_name)
        else:
            unselected_names.append(object_name)
            cmd.disable(object_name)

    cmd.group("predictions_selected", " ".join(selected_names))
    cmd.group("predictions_unselected", " ".join(unselected_names))
    cmd.group("predictions", "predictions_selected predictions_unselected")
    return selected_names, unselected_names


def build_session(args: argparse.Namespace) -> None:
    """生成一个完整 Stage1 PyMOL 会话并原子落盘.

    输入参数:
        - args: argparse.Namespace; 字段由 ``parse_args`` 定义, 其中 ``output`` 决定唯一写入路径.

    文件产物:
        - args.output: PyMOL ``.pse``; 包含 ``stage1`` 顶层组、完整实验密度 map 与 mesh、受体、逐 occurrence GT 配体与逐 evaluation 候选 blob.

    写入边界:
        - 输出先写到 ``args.output`` 同目录临时 `.pse`, 只有 ``cmd.save`` 成功后才用 ``os.replace`` 原子替换目标.
        - 输入数据根和推理根始终只读; 本函数不生成 probability、blobs 或 evaluation 产物.
    """
    data_root = args.data_root.resolve()
    inference_root = args.inference_root.resolve()
    pdb_id = str(args.pdb_id).lower()
    output_path = args.output.resolve()
    if output_path.suffix.lower() != ".pse":
        raise ValueError("--output must end with .pse")

    pymol.finish_launching(["pymol", "-cq"])
    cmd.reinitialize()
    cmd.set("retain_order", 1)
    origin_center_xyz, voxel_size_xyz, _contour = _load_density(data_root, pdb_id)
    _load_receptor(data_root, pdb_id)
    _load_ground_truth(data_root, pdb_id)
    _load_predictions(
        inference_root,
        args.producer,
        args.split,
        pdb_id,
        args.alpha,
        args.evaluation_name,
        origin_center_xyz,
        voxel_size_xyz,
    )
    cmd.group("stage1", "density receptor ground_truth predictions")
    cmd.orient("receptor or ground_truth or predictions_selected")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.stem}.tmp-{os.getpid()}{output_path.suffix}"
    )
    try:
        cmd.save(str(temporary_path))
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    """执行命令行会话生成器, 成功保存后返回退出码 0."""
    args = parse_args(argv)
    build_session(args)
    print(f"[stage1_pymol] session={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
