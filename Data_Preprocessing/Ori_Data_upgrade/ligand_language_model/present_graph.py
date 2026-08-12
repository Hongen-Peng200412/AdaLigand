"""从 LigandObject 模板图和 occurrence 的 present 掩码构造 BRANCHED 后备分子。

该后备方法只删除当前 PDB 中未出现的模板原子，并保留两端原子都存在的原有键。
它不猜测离去反应、不新增键，也不宣称所得分子是唯一化学真值。

``build_present_molecule`` 是唯一正式入口；它接收内存中的 LigandObject 数组和
``bool (N,)`` present 掩码，返回 RDKit 分子与诊断字典，不直接写文件。
"""

from __future__ import annotations

import numpy as np
from rdkit import Chem

from run_context import format_error


# ``bonds['type']`` 的五列依次对应单键、双键、三键、配位键和芳香键。
BOND_TYPES = (
    Chem.BondType.SINGLE,
    Chem.BondType.DOUBLE,
    Chem.BondType.TRIPLE,
    Chem.BondType.DATIVE,
    Chem.BondType.AROMATIC,
)

# ``atoms['chirality']`` 的七列顺序与 Stage C 写入 LigandObject 时的顺序完全相同。
CHIRAL_TAGS = (
    Chem.ChiralType.CHI_OTHER,
    Chem.ChiralType.CHI_OCTAHEDRAL,
    Chem.ChiralType.CHI_TETRAHEDRAL_CW,
    Chem.ChiralType.CHI_TRIGONALBIPYRAMIDAL,
    Chem.ChiralType.CHI_UNSPECIFIED,
    Chem.ChiralType.CHI_TETRAHEDRAL_CCW,
    Chem.ChiralType.CHI_SQUAREPLANAR,
)


# ================================================================================================


def build_present_molecule(
    ligand_object: dict[str, np.ndarray],
    present: np.ndarray | None,
) -> tuple[Chem.Mol | None, dict[str, object]]:
    """删除 ``present=False`` 的模板原子，并重建保留原子的 RDKit 图。

    形状符号:
        N: LigandObject 模板原子数。
        E: LigandObject 模板键数。
        N_present: ``present=True`` 的原子数。
        E_present: 两端原子都满足 ``present=True`` 的模板键数。

    输入:
        ligand_object["atoms"]: 结构化数组 ``(N,)``。使用 ``element``、``charge`` 和 ``chirality`` 字段。
        atoms["element"]: 整数 ``(N,)``，每个模板原子的原子序数。
        atoms["charge"]: 整数 ``(N,)``，每个模板原子的形式电荷。
        atoms["chirality"]: 布尔数组 ``(N, 7)``，七列顺序由 ``CHIRAL_TAGS`` 定义。
        ligand_object["bonds"]: 结构化数组 ``(E,)``。使用 ``atom_1``、``atom_2`` 和 ``type`` 字段。
        bonds["atom_1"]: 整数 ``(E,)``，每条键左端在模板原子数组中的零基编号。
        bonds["atom_2"]: 整数 ``(E,)``，每条键右端在模板原子数组中的零基编号。
        bonds["type"]: 布尔数组 ``(E, 5)``，五列顺序由 ``BOND_TYPES`` 定义。
        present: 布尔数组 ``(N,)``；``present[i]`` 与 ``ligand_object["atoms"][i]`` 指向同一个模板原子，True 保留它，False 删除它。

    返回:
        第一个值是含 N_present 个原子和 E_present 条键的 RDKit 分子；无法建图时为 ``None``。
        第二个值始终是诊断字典，字段如下：

        template_atom_count: 模板原子数 N；连模板数组都无法读取时为 ``None``。
        template_bond_count: 模板键数 E；连模板数组都无法读取时为 ``None``。
        present_atom_count: 掩码中 True 的数量；掩码不可用时为 ``None``。
        removed_atom_count: 掩码中 False 的数量；掩码不可用时为 ``None``。
        retained_bond_count: 实际加入后备图的模板键数；建图失败前尚未完成时为 ``None``。
        empty_chirality_one_hot_count: 保留原子中七列全为 False 的数量。
        multiple_chirality_one_hot_count: 保留原子中超过一列为 True 的数量。
        empty_bond_type_one_hot_count: 保留键中五列全为 False 的数量。
        multiple_bond_type_one_hot_count: 保留键中超过一列为 True 的数量。
        chirality_fallback: 全空时保留 RDKit 的 CHI_UNSPECIFIED，多列为真时取 Stage C 顺序第一列。
        bond_type_fallback: 全空时使用单键，多列为真时取 Stage C 顺序第一列。
        error: 掩码或建图异常；成功时为 ``None``。

    ``present=False`` 可能表示离去原子，也可能表示普通缺失原子。此处只保存删除数量，
    不把这种机械后备表示包装成经反应规则证明的化学结构。
    """

    diagnostics: dict[str, object] = {
        "template_atom_count": None,
        "template_bond_count": None,
        "present_atom_count": None,
        "removed_atom_count": None,
        "retained_bond_count": None,
        "empty_chirality_one_hot_count": 0,
        "multiple_chirality_one_hot_count": 0,
        "empty_bond_type_one_hot_count": 0,
        "multiple_bond_type_one_hot_count": 0,
        "chirality_fallback": (
            "七列全为 False 时保留 CHI_UNSPECIFIED；多列为 True 时取 Stage C 顺序第一列"
        ),
        "bond_type_fallback": (
            "五列全为 False 时使用 SINGLE；多列为 True 时取 Stage C 顺序第一列"
        ),
        "error": None,
    }

    try:
        atoms = ligand_object["atoms"]
        bonds = ligand_object["bonds"]
        if not isinstance(atoms, np.ndarray) or atoms.ndim != 1:
            raise TypeError("ligand_object['atoms'] 必须是一维 NumPy 结构化数组")
        if not isinstance(bonds, np.ndarray) or bonds.ndim != 1:
            raise TypeError("ligand_object['bonds'] 必须是一维 NumPy 结构化数组")
        atom_fields = set(atoms.dtype.names or ())
        bond_fields = set(bonds.dtype.names or ())
        if not {"element", "charge", "chirality"}.issubset(atom_fields):
            raise ValueError("atoms 缺少 element、charge 或 chirality 字段")
        if not {"atom_1", "atom_2", "type"}.issubset(bond_fields):
            raise ValueError("bonds 缺少 atom_1、atom_2 或 type 字段")
    except Exception as error:
        diagnostics["error"] = format_error(error)
        return None, diagnostics

    atom_count = len(atoms)
    diagnostics["template_atom_count"] = atom_count
    diagnostics["template_bond_count"] = len(bonds)
    if present is None:
        diagnostics["error"] = "ValueError: present 掩码缺失"
        return None, diagnostics
    if not isinstance(present, np.ndarray) or present.dtype != np.bool_:
        diagnostics["error"] = "TypeError: present 必须是 bool NumPy 数组"
        return None, diagnostics
    if present.shape != (atom_count,):
        diagnostics["error"] = (
            f"ValueError: present 形状为 {present.shape}，预期为 ({atom_count},)"
        )
        return None, diagnostics

    present_atom_count = int(present.sum())
    diagnostics["present_atom_count"] = present_atom_count
    diagnostics["removed_atom_count"] = atom_count - present_atom_count
    if present_atom_count == 0:
        diagnostics["error"] = "ValueError: present 掩码没有任何 True 原子"
        return None, diagnostics

    molecule = Chem.RWMol()
    # old_to_new 将模板数组的零基原子编号映射到删原子后分子的零基紧凑编号。
    old_to_new: dict[int, int] = {}
    retained_bond_count = 0
    try:
        for old_index, atom_row in enumerate(atoms):
            if not present[old_index]:
                continue

            chirality = atom_row["chirality"]
            if not isinstance(chirality, np.ndarray):
                chirality = np.asarray(chirality)
            if chirality.dtype != np.bool_ or chirality.shape != (len(CHIRAL_TAGS),):
                raise TypeError(
                    f"atoms[{old_index}].chirality 必须是 bool ({len(CHIRAL_TAGS)},)"
                )

            atom = Chem.Atom(int(atom_row["element"]))
            atom.SetFormalCharge(int(atom_row["charge"]))
            # active_chirality 是 int64 (K,) 的真值列编号；第一个编号索引 CHIRAL_TAGS，K 是当前原子七列 one-hot 中 True 的数量。
            active_chirality = np.flatnonzero(chirality)
            if len(active_chirality) == 0:
                diagnostics["empty_chirality_one_hot_count"] += 1
            else:
                if len(active_chirality) > 1:
                    diagnostics["multiple_chirality_one_hot_count"] += 1
                atom.SetChiralTag(CHIRAL_TAGS[int(active_chirality[0])])
            old_to_new[old_index] = molecule.AddAtom(atom)

        for bond_index, bond_row in enumerate(bonds):
            left = int(bond_row["atom_1"])
            right = int(bond_row["atom_2"])
            if not 0 <= left < atom_count or not 0 <= right < atom_count:
                raise IndexError(
                    f"bonds[{bond_index}] 端点 ({left}, {right}) 超出 [0, {atom_count})"
                )
            if not present[left] or not present[right]:
                continue

            bond_types = bond_row["type"]
            if not isinstance(bond_types, np.ndarray):
                bond_types = np.asarray(bond_types)
            if bond_types.dtype != np.bool_ or bond_types.shape != (len(BOND_TYPES),):
                raise TypeError(
                    f"bonds[{bond_index}].type 必须是 bool ({len(BOND_TYPES)},)"
                )
            # active_types 是 int64 (K,) 的真值列编号；第一个编号索引 BOND_TYPES，K 是当前键五列 one-hot 中 True 的数量。
            active_types = np.flatnonzero(bond_types)
            if len(active_types) == 0:
                diagnostics["empty_bond_type_one_hot_count"] += 1
                bond_type = Chem.BondType.SINGLE
            else:
                if len(active_types) > 1:
                    diagnostics["multiple_bond_type_one_hot_count"] += 1
                bond_type = BOND_TYPES[int(active_types[0])]

            new_left = old_to_new[left]
            new_right = old_to_new[right]
            molecule.AddBond(new_left, new_right, bond_type)
            if bond_type == Chem.BondType.AROMATIC:
                # RDKit 需要同时标记芳香键与两端原子，后续 SMILES 才能保留芳香性。
                molecule.GetAtomWithIdx(new_left).SetIsAromatic(True)
                molecule.GetAtomWithIdx(new_right).SetIsAromatic(True)
                molecule.GetBondBetweenAtoms(new_left, new_right).SetIsAromatic(True)
            retained_bond_count += 1

        result = molecule.GetMol()
        result.UpdatePropertyCache(strict=False)
    except Exception as error:
        diagnostics["error"] = format_error(error)
        return None, diagnostics

    diagnostics["retained_bond_count"] = retained_bond_count
    return result, diagnostics
