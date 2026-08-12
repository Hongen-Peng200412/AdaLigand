"""为一个正式配体 occurrence 选择交给语言模型的分子级 SMILES。

主流程只有三条清晰路径：普通 CCD 使用 LigandObject 已保存的 SMILES；BRANCHED
先尝试与完整残基身份精确对应的 CLC；CLC 没有给出非空字符串时，再使用 present 图。
本模块不读写正式文件、不分配任务，也不因诊断异常自动排除已有非空字符串。

``prepare_ligand`` 是唯一正式入口；它接收一个 occurrence、内存中的 LigandObject、
present 掩码和 CLC 候选，返回一个 ``PreparedLigand``，不直接落盘。
"""

from __future__ import annotations

import numpy as np
from rdkit import Chem

from artifacts import FORMAL_TYPE_TAGS, PreparedLigand
from clc_assembly import CLCCandidate, select_exact_clc
from present_graph import build_present_molecule
from run_context import format_error


# 该集合只用于记录 has_metal；代码不会据此删除金属、筛除分子或改变 SMILES。
METAL_ATOMIC_NUMBERS = frozenset(
    [3, 4, 11, 12, 13, 19, 20]
    + list(range(21, 32))
    + [37, 38]
    + list(range(39, 51))
    + [55, 56]
    + list(range(57, 84))
    + [87, 88]
    + list(range(89, 113))
)


def _molecule_to_smiles(
    molecule: Chem.Mol,
) -> tuple[str | None, dict[str, object]]:
    """生成 canonical non-isomeric SMILES，并完整记录 RDKit 转换事实。

    函数先复制输入分子，所以 ``Chem.SanitizeMol`` 不会修改调用者持有的对象。
    sanitize 失败后仍分别尝试 isomeric 与 non-isomeric 两次 ``MolToSmiles``；两次调用
    各自捕获异常。只要 non-isomeric 调用得到非空字符串，该字符串仍可进入语言模型。

    返回值:
        第一个位置是 ``model_smiles: str | None``；成功得到非空 canonical non-isomeric SMILES 时为字符串，否则为 ``None``。
        第二个位置是 ``diagnostics: dict[str, object]``，包含以下只记录事实、不参与筛选的字段：

        sanitize_error: sanitize 异常；成功时为 ``None``。
        isomeric_smiles: canonical isomeric SMILES；生成失败或为空时为 ``None``。
        isomeric_smiles_error: isomeric ``MolToSmiles`` 异常；成功时为 ``None``。
        model_smiles_error: non-isomeric ``MolToSmiles`` 异常；成功时为 ``None``。
        stereo_removed: 两种非空 SMILES 是否不同；任一缺失时为 ``None``。
        chemistry.atom_count: 当前 RDKit 分子的原子数。
        chemistry.fragment_count: RDKit 识别的断开片段数；统计失败时为 ``None``。
        chemistry.fragment_count_error: 片段统计异常；成功时为 ``None``。
        chemistry.has_disconnected_components: 片段数大于一时为 ``True``；片段数未知时为 ``None``。
        chemistry.has_metal: 是否含 ``METAL_ATOMIC_NUMBERS`` 中的原子。
        chemistry.charged_atom_count: 形式电荷不为零的原子数。
        chemistry.total_formal_charge: 所有原子形式电荷的代数和。
    """

    working = Chem.Mol(molecule)
    try:
        Chem.SanitizeMol(working)
        sanitize_error = None
    except Exception as error:
        sanitize_error = format_error(error)

    # isomeric_smiles 只用于记录立体信息是否会改变字符串，不作为本项目模型输入。
    try:
        isomeric_smiles = Chem.MolToSmiles(
            working,
            canonical=True,
            isomericSmiles=True,
        )
    except Exception as error:
        isomeric_smiles = None
        isomeric_error = format_error(error)
    else:
        isomeric_smiles = isomeric_smiles or None
        isomeric_error = None

    # model_smiles 是 CPU 阶段统一提供给两个模型公开接口的 non-isomeric 字符串。
    try:
        model_smiles = Chem.MolToSmiles(
            working,
            canonical=True,
            isomericSmiles=False,
        )
    except Exception as error:
        model_smiles = None
        model_error = format_error(error)
    else:
        model_smiles = model_smiles or None
        model_error = None

    atoms = list(working.GetAtoms())
    try:
        fragment_count = len(Chem.GetMolFrags(working))
        fragment_error = None
    except Exception as error:
        fragment_count = None
        fragment_error = format_error(error)

    diagnostics: dict[str, object] = {
        "sanitize_error": sanitize_error,
        "isomeric_smiles": isomeric_smiles,
        "isomeric_smiles_error": isomeric_error,
        "model_smiles_error": model_error,
        "stereo_removed": (
            isomeric_smiles != model_smiles
            if isomeric_smiles is not None and model_smiles is not None
            else None
        ),
        "chemistry": {
            "atom_count": len(atoms),
            "fragment_count": fragment_count,
            "fragment_count_error": fragment_error,
            "has_disconnected_components": (
                fragment_count > 1 if fragment_count is not None else None
            ),
            "has_metal": any(
                atom.GetAtomicNum() in METAL_ATOMIC_NUMBERS for atom in atoms
            ),
            "charged_atom_count": sum(atom.GetFormalCharge() != 0 for atom in atoms),
            "total_formal_charge": sum(atom.GetFormalCharge() for atom in atoms),
        },
    }
    return model_smiles, diagnostics


# ================================================================================================


def prepare_ligand(
    pdb_id: str,
    occurrence: dict[str, object],
    ligand_object: dict[str, np.ndarray],
    present: np.ndarray | None,
    clc_candidates: list[CLCCandidate],
    clc_read_diagnostics: dict[str, object],
) -> PreparedLigand:
    """为一个 ``(pdb_id, candidate_id)`` 选择最终模型输入 SMILES。

    输入:
        pdb_id: 当前 ``parse/{pdb_id}`` 目录的小写 PDB 标识。
        occurrence: ``occurrences.jsonl`` 中一个完整 JSON 对象。
        ligand_object: ``ligand_objects/{safe_object_key}.npz`` 的全部数组。
        present: ``ligand_coords.npz::present_{candidate_id}``，应为 bool ``(N,)``；仅 BRANCHED 后备路径使用。
        clc_candidates: pdbeccdutils 从当前 PDB 完整 mmCIF 得到的全部可用 CLC。
        clc_read_diagnostics: ``read_clc_candidates`` 对当前 PDB 的读取事实。

    occurrence 顶层契约:
        pdb_id: 非空字符串，应与目录 PDB 标识相同；不同时只记录事实。
        candidate_id: 非负整数，是当前 PDB 内的 occurrence 编号。
        object_key: 非空字符串，指向一个 LigandObject NPZ。
        kind: 非空字符串；正式路径是 ``CCD`` 或 ``BRANCHED``。
        type_tag: 五类正式标签之一，不接受 ``other``。
        is_covalent: 布尔值，只记录 Stage C 事实，不改变 SMILES 选择。

    SMILES 选择:
        ``CCD`` 读取 LigandObject 的标量字符串。RDKit 无法解析或生成规范字符串时，
        仍保留非空原文。``BRANCHED`` 先尝试唯一精确 CLC；选择、复制、删氢或转字符串
        任一步失败，都会记录异常并继续 present 图。present 图只要生成非空字符串也会
        保留。连接差异、sanitize 失败、断开片段、金属和电荷均不是自动门控。
    """

    if type(pdb_id) is not str or not pdb_id or pdb_id != pdb_id.lower():
        raise ValueError("pdb_id 必须是非空小写字符串")
    if not isinstance(occurrence, dict):
        raise TypeError("occurrence 必须是字典")

    required_types: dict[str, type] = {
        "pdb_id": str,
        "candidate_id": int,
        "object_key": str,
        "kind": str,
        "type_tag": str,
        "is_covalent": bool,
    }
    for field, expected_type in required_types.items():
        if field not in occurrence or type(occurrence[field]) is not expected_type:
            raise TypeError(f"occurrence.{field} 必须是 {expected_type.__name__}")

    source_pdb_id = occurrence["pdb_id"].strip().lower()
    candidate_id = occurrence["candidate_id"]
    object_key = occurrence["object_key"].strip()
    kind = occurrence["kind"].strip()
    type_tag = occurrence["type_tag"]
    is_covalent = occurrence["is_covalent"]
    if not source_pdb_id or not object_key or not kind:
        raise ValueError("occurrence 的 pdb_id、object_key 和 kind 必须是非空字符串")
    if candidate_id < 0:
        raise ValueError("occurrence.candidate_id 必须是非负整数")
    if type_tag not in FORMAL_TYPE_TAGS:
        raise ValueError(f"occurrence.type_tag 不是五类正式标签: {type_tag!r}")

    if kind == "CCD":
        # CCD 不读取 present，也不调用 CLC；模型输入只来自 LigandObject 已保存的 SMILES。
        raw_smiles_array = ligand_object["smiles"]
        if not isinstance(raw_smiles_array, np.ndarray) or raw_smiles_array.shape != ():
            raise TypeError("CCD LigandObject.smiles 必须是标量 NumPy 数组")
        raw_smiles_value = raw_smiles_array.item()
        if type(raw_smiles_value) is not str:
            raise TypeError("CCD LigandObject.smiles 标量必须是字符串")
        raw_smiles = raw_smiles_value.strip()
        smiles_source = "ccd"
        if not raw_smiles:
            smiles = None
            diagnostics: dict[str, object] = {
                "raw_smiles": "",
                "rdkit_parse_error": None,
                "error": "ValueError: LigandObject.smiles 是空字符串",
            }
        else:
            try:
                ccd_molecule = Chem.MolFromSmiles(raw_smiles, sanitize=False)
            except Exception as error:
                ccd_molecule = None
                parse_error = format_error(error)
            else:
                parse_error = (
                    None if ccd_molecule is not None else "RDKit returned None"
                )

            if ccd_molecule is None:
                # 宽口径：RDKit 没有建图时，官方 tokenizer 仍可自行尝试这个非空原文。
                smiles = raw_smiles
                diagnostics = {
                    "raw_smiles": raw_smiles,
                    "rdkit_parse_error": parse_error,
                    "used_raw_smiles": True,
                }
            else:
                smiles, diagnostics = _molecule_to_smiles(ccd_molecule)
                diagnostics["raw_smiles"] = raw_smiles
                diagnostics["rdkit_parse_error"] = parse_error
                if smiles is None:
                    smiles = raw_smiles
                    diagnostics["used_raw_smiles"] = True

    elif kind == "BRANCHED":
        # CLC 的读取诊断属于 PDB 级事实；每个 BRANCHED occurrence 都原样引用这份内容。
        clc_diagnostics: dict[str, object] = {
            "read": clc_read_diagnostics,
            "selection": None,
            "remove_h_error": None,
            "preparation_error": None,
        }
        try:
            selected_clc, selection_diagnostics = select_exact_clc(
                occurrence,
                clc_candidates,
            )
            clc_diagnostics["selection"] = selection_diagnostics
        except Exception as error:
            selected_clc = None
            clc_diagnostics["selection"] = {"error": format_error(error)}

        smiles = None
        if selected_clc is not None:
            try:
                # 仅对 CLC 包产物删除显式氢；若删除失败，则复制未删氢分子继续尝试。
                try:
                    clc_molecule = Chem.RemoveHs(
                        selected_clc.molecule,
                        sanitize=False,
                    )
                except Exception as error:
                    clc_diagnostics["remove_h_error"] = format_error(error)
                    clc_molecule = Chem.Mol(selected_clc.molecule)
                smiles, molecule_diagnostics = _molecule_to_smiles(clc_molecule)
                clc_diagnostics["molecule"] = molecule_diagnostics
            except Exception as error:
                # 包对象复制或转换的意外异常不能截断后面的 present 图尝试。
                clc_diagnostics["preparation_error"] = format_error(error)

        if smiles:
            smiles_source = "clc"
            diagnostics = {"clc": clc_diagnostics}
        else:
            present_molecule, present_diagnostics = build_present_molecule(
                ligand_object,
                present,
            )
            if present_molecule is not None:
                try:
                    smiles, molecule_diagnostics = _molecule_to_smiles(present_molecule)
                    present_diagnostics["molecule"] = molecule_diagnostics
                except Exception as error:
                    smiles = None
                    present_diagnostics["molecule_error"] = format_error(error)
            smiles_source = "present_graph"
            diagnostics = {
                "clc": clc_diagnostics,
                "present_graph": present_diagnostics,
            }

    else:
        smiles = None
        smiles_source = "unsupported"
        diagnostics = {"error": f"ValueError: 不支持 occurrence.kind={kind!r}"}

    if source_pdb_id != pdb_id:
        diagnostics["source_pdb_id_mismatch"] = source_pdb_id

    return PreparedLigand(
        pdb_id=pdb_id,
        candidate_id=candidate_id,
        object_key=object_key,
        kind=kind,
        type_tag=type_tag,
        is_covalent=is_covalent,
        smiles=smiles,
        smiles_source=smiles_source,
        diagnostics=diagnostics,
    )
