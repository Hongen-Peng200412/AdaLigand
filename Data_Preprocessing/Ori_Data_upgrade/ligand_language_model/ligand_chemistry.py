"""把一个 AdaLigand 配体 occurrence 准备成语言模型实际接收的 SMILES。

本模块只负责 occurrence 级化学准备，不加载语言模型。普通 ``CCD`` occurrence
沿用 ``LigandObject.smiles``；``BRANCHED`` occurrence 优先从完整 PDB mmCIF
读取 pdbeccdutils CLC（Covalently Linked Component，共价连接组分），并按完整
残基身份多重集合精确对应。只有 CLC 不能唯一对应或不能产生非空 SMILES 时，
才从 ``LigandObject`` 中删去当前 occurrence 未出现的原子，构造透明的后备图。

RDKit 解析、sanitize、组分连接核对和 SMILES 生成都属于审计信息，不是发布门控。
只要任一路径得到非空 SMILES，后续模型入口就仍可尝试编码；失败事实完整保存在
``prepared_smiles.jsonl``，由使用者在分析时决定如何筛选。
"""

from __future__ import annotations

import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from pdbeccdutils.core import clc_reader
from pdbeccdutils.helpers import cif_tools
from rdkit import Chem

from ligand_language_common import clean_exception


# 原子序数集合只用于报告 ``has_metal``，不会改变分子，也不会阻止模型编码。
# 这里覆盖碱金属、碱土金属、过渡金属、镧系、锕系和常见后过渡金属。
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

# ``LigandObject.bonds['type']`` 是 bool ``(E,5)``：第 0..4 维依次表示
# SINGLE、DOUBLE、TRIPLE、DATIVE、AROMATIC。这里的顺序必须与 Stage C 完全一致。
BOND_TYPES = (
    Chem.BondType.SINGLE,
    Chem.BondType.DOUBLE,
    Chem.BondType.TRIPLE,
    Chem.BondType.DATIVE,
    Chem.BondType.AROMATIC,
)

# ``LigandObject.atoms['chirality']`` 是 bool ``(N,7)``：第 0..6 维依次表示
# CHI_OTHER、CHI_OCTAHEDRAL、CHI_TETRAHEDRAL_CW、CHI_TRIGONALBIPYRAMIDAL、
# CHI_UNSPECIFIED、CHI_TETRAHEDRAL_CCW、CHI_SQUAREPLANAR。
CHIRAL_TAGS = (
    Chem.ChiralType.CHI_OTHER,
    Chem.ChiralType.CHI_OCTAHEDRAL,
    Chem.ChiralType.CHI_TETRAHEDRAL_CW,
    Chem.ChiralType.CHI_TRIGONALBIPYRAMIDAL,
    Chem.ChiralType.CHI_UNSPECIFIED,
    Chem.ChiralType.CHI_TETRAHEDRAL_CCW,
    Chem.ChiralType.CHI_SQUAREPLANAR,
)


def clean_identity_value(value: object) -> str:
    """把 mmCIF 的空标记统一为空字符串，其余身份字段统一成文本。"""

    if value is None or value is False:
        return ""
    text = str(value).strip()
    return "" if text in {"", ".", "?"} else text


def component_identity(component: dict[str, object]) -> tuple[str, str, str, str]:
    """读取 occurrence component 的完整作者残基身份。

    返回顺序固定为 ``(ccd_id, auth_asym_id, auth_seq_id, insertion_code)``。
    插入码兼容当前 occurrence 字段 ``icode`` 和更直观的
    ``insertion_code``；二者的空标记都会归一为空字符串。
    """

    insertion_code = component.get("insertion_code", component.get("icode", ""))
    return (
        clean_identity_value(component.get("ccd_id", "")).upper(),
        clean_identity_value(component.get("auth_asym_id", "")),
        clean_identity_value(component.get("auth_seq_id", "")),
        clean_identity_value(insertion_code),
    )


def clc_node_identity(node: Any) -> tuple[str, str, str, str]:
    """把 pdbeccdutils CLC 节点转换为同一套完整作者残基身份。"""

    return (
        clean_identity_value(node.name).upper(),
        clean_identity_value(node.chain),
        clean_identity_value(node.res_id),
        clean_identity_value(node.ins_code),
    )


def identity_to_json(identity: tuple[str, str, str, str]) -> dict[str, str]:
    """把内部 tuple 身份转换成字段自解释的 JSON 对象。"""

    return {
        "ccd_id": identity[0],
        "auth_asym_id": identity[1],
        "auth_seq_id": identity[2],
        "insertion_code": identity[3],
    }


def safe_object_filename(object_key: str) -> str:
    """复现现有 Stage C 的 object_key 文件名转义规则。"""

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", object_key)


def load_ligand_object(data_root: Path, object_key: str) -> dict[str, np.ndarray]:
    """读取一个去重 LigandObject，并在关闭 NPZ 后保留所需数组。"""

    path = data_root / "ligand_objects" / f"{safe_object_filename(object_key)}.npz"
    with np.load(path, allow_pickle=True) as archive:
        return {name: archive[name] for name in archive.files}


def _exception_or_none(error: BaseException | None) -> str | None:
    """把可选异常转换成可直接写入 JSON 的单行文本。"""

    return None if error is None else clean_exception(error)


def molecule_facts(mol: Chem.Mol) -> dict[str, object]:
    """提取不改变分子的宽口径化学事实。

    这些字段只用于分析报告。金属、形式电荷、断开组分和单原子离子都原样保留，
    不触发去盐、中和、取最大组分或拒绝编码。

    返回字典包含原子数、片段数及其异常、是否断开、是否含金属、带电原子数、
    是否带电和总形式电荷。未 sanitize 的图无法枚举片段时，``fragment_count`` 与
    ``has_disconnected_components`` 为 ``None``，具体异常写入
    ``fragment_count_error``。
    """

    atoms = list(mol.GetAtoms())
    fragment_count_error: BaseException | None = None
    try:
        fragment_count: int | None = len(Chem.GetMolFrags(mol))
    except Exception as exc:  # 未 sanitize 的图也可能无法枚举片段，保留事实即可。
        fragment_count = None
        fragment_count_error = exc
    charged_atom_count = sum(atom.GetFormalCharge() != 0 for atom in atoms)
    return {
        "atom_count": len(atoms),
        "fragment_count": fragment_count,
        "fragment_count_error": _exception_or_none(fragment_count_error),
        "has_disconnected_components": (
            fragment_count > 1 if fragment_count is not None else None
        ),
        "has_metal": any(atom.GetAtomicNum() in METAL_ATOMIC_NUMBERS for atom in atoms),
        "charged_atom_count": charged_atom_count,
        "has_charged_atoms": charged_atom_count > 0,
        "total_formal_charge": sum(atom.GetFormalCharge() for atom in atoms),
    }


def smiles_from_mol(mol: Chem.Mol) -> dict[str, object]:
    """独立尝试 sanitize、异构 SMILES 和非异构 SMILES。

    三个操作分别捕获异常。尤其是 sanitize 失败后，``MolToSmiles`` 仍可能成功，
    也可能再次抛错；本函数不会把前一个结果暗自替代成后一个结果。

    返回 ``assembled_isomeric_smiles``、``model_input_smiles``、``chemistry`` 和
    ``rdkit``。两种 SMILES 生成失败时对应字段为 ``None``；``rdkit`` 分别保存
    sanitize、异构 SMILES 和非异构 SMILES 的成功状态或异常。
    """

    working = Chem.Mol(mol)
    sanitize_error: BaseException | None = None
    try:
        Chem.SanitizeMol(working)
    except Exception as exc:
        sanitize_error = exc

    isomeric_smiles: str | None = None
    isomeric_error: BaseException | None = None
    try:
        value = Chem.MolToSmiles(working, canonical=True, isomericSmiles=True)
        isomeric_smiles = value if value else None
    except Exception as exc:
        isomeric_error = exc

    model_input_smiles: str | None = None
    model_input_error: BaseException | None = None
    try:
        value = Chem.MolToSmiles(working, canonical=True, isomericSmiles=False)
        model_input_smiles = value if value else None
    except Exception as exc:
        model_input_error = exc

    facts = molecule_facts(working)
    facts["stereo_removed"] = (
        isomeric_smiles != model_input_smiles
        if isomeric_smiles is not None and model_input_smiles is not None
        else None
    )
    return {
        "assembled_isomeric_smiles": isomeric_smiles,
        "model_input_smiles": model_input_smiles,
        "chemistry": facts,
        "rdkit": {
            "sanitize_success": sanitize_error is None,
            "sanitize_error": _exception_or_none(sanitize_error),
            "isomeric_smiles_error": _exception_or_none(isomeric_error),
            "model_input_smiles_error": _exception_or_none(model_input_error),
        },
    }


def prepare_ccd_smiles(ligand_object: dict[str, np.ndarray]) -> dict[str, object]:
    """准备普通 CCD 的模型输入，并保留 RDKit 失败后的原始 SMILES。

    ``LigandObject.smiles`` 非空时，即使 RDKit 无法解析或规范化，也仍把原始文本
    交给语言模型。这样“RDKit 校验失败”和“模型没有输入”不会被错误地合并。
    """

    raw_smiles = clean_identity_value(ligand_object["smiles"].item())
    audit: dict[str, object] = {
        "rdkit_parse_success": False,
        "rdkit_parse_error": None,
    }
    if not raw_smiles:
        return {
            "preparation_source": "ligand_object_smiles",
            "source_smiles": raw_smiles,
            "assembled_isomeric_smiles": None,
            "model_input_smiles": None,
            "chemistry": {},
            "preparation_audit": audit,
        }

    try:
        mol = Chem.MolFromSmiles(raw_smiles, sanitize=False)
    except Exception as exc:
        mol = None
        audit["rdkit_parse_error"] = clean_exception(exc)
    if mol is None:
        if audit["rdkit_parse_error"] is None:
            audit["rdkit_parse_error"] = "RDKit returned None"
        return {
            "preparation_source": "ligand_object_smiles",
            "source_smiles": raw_smiles,
            "assembled_isomeric_smiles": None,
            "model_input_smiles": raw_smiles,
            "chemistry": {},
            "preparation_audit": audit,
        }

    audit["rdkit_parse_success"] = True
    generated = smiles_from_mol(mol)
    audit.update(generated.pop("rdkit"))
    # 规范化失败时保留 LigandObject 原文；这不是声称原文正确，而是保留模型尝试机会。
    generated["model_input_smiles"] = generated["model_input_smiles"] or raw_smiles
    return {
        "preparation_source": "ligand_object_smiles",
        "source_smiles": raw_smiles,
        **generated,
        "preparation_audit": audit,
    }


def _clc_edge_records(result: Any) -> list[dict[str, object]]:
    """保留 CLC 图中的 residue 身份、连接原子名和包提供的键属性。"""

    records: list[dict[str, object]] = []
    for left, right, edge in result.bound_molecule.graph.edges(data=True):
        records.append(
            {
                "left": identity_to_json(clc_node_identity(left)),
                "left_atom": clean_identity_value(edge.get("atom_id_1", "")),
                "right": identity_to_json(clc_node_identity(right)),
                "right_atom": clean_identity_value(edge.get("atom_id_2", "")),
                "bond_order": clean_identity_value(
                    edge.get("value_order", edge.get("bond_order", ""))
                ),
            }
        )
    return records


def read_clc_candidates(
    raw_mmcif_path: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """用 pdbeccdutils 官方预处理读取一个 PDB 的全部 CLC 候选。

    返回的 ``candidates`` 每项保留 CLC 序号、完整残基身份多重集合、原始
    pdbeccdutils result、包报告的 sanitize/warnings/errors 和连接边；原始 RDKit Mol
    只在当前进程使用，不写进 JSON。``audit`` 保存 mmCIF 路径、官方预处理、CLC
    读取、候选数量及“电荷/连接键级不视为权威”的事实。预处理或读取失败时返回
    空候选和异常文本，调用者随后走 occurrence 回退。
    """

    audit: dict[str, object] = {
        "raw_mmcif_path": str(raw_mmcif_path),
        "official_preprocess_success": False,
        "official_preprocess_error": None,
        "clc_reader_success": False,
        "clc_reader_error": None,
        "clc_candidate_count": 0,
        "package_formal_charge_and_connection_bond_order_treated_as_authoritative": False,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="adaligand_clc_") as temporary_dir:
            processed_path = Path(temporary_dir) / raw_mmcif_path.name
            try:
                cif_tools.fix_updated_mmcif(str(raw_mmcif_path), str(processed_path))
                audit["official_preprocess_success"] = True
            except Exception as exc:
                audit["official_preprocess_error"] = clean_exception(exc)
                return [], audit
            try:
                results = clc_reader.read_pdb_cif_file(
                    str(processed_path), sanitize=True
                )
                audit["clc_reader_success"] = True
            except Exception as exc:
                audit["clc_reader_error"] = clean_exception(exc)
                return [], audit
    except Exception as exc:
        audit["clc_reader_error"] = clean_exception(exc)
        return [], audit

    candidates: list[dict[str, object]] = []
    for index, result in enumerate(results):
        identities = [
            clc_node_identity(node) for node in result.bound_molecule.graph.nodes
        ]
        candidates.append(
            {
                "index": index,
                "identity_multiset": Counter(identities),
                "identities": identities,
                "result": result,
                "reported_sanitized": bool(result.sanitized),
                "warnings": [str(value) for value in (result.warnings or [])],
                "errors": [str(value) for value in (result.errors or [])],
                "edges": _clc_edge_records(result),
            }
        )
    audit["clc_candidate_count"] = len(candidates)
    return candidates, audit


def _candidate_audit(candidate: dict[str, object]) -> dict[str, object]:
    """移除不可序列化 RDKit 对象，形成可落盘的 CLC 候选摘要。"""

    identities = candidate["identities"]
    return {
        "clc_index": candidate["index"],
        "component_identities": [identity_to_json(value) for value in identities],
        "reported_sanitized": candidate["reported_sanitized"],
        "warnings": candidate["warnings"],
        "errors": candidate["errors"],
        "graph_edge_count": len(candidate["edges"]),
        "edges": candidate["edges"],
        "smiles_generation_attempted": False,
    }


def _canonical_connection(
    left_identity: tuple[str, str, str, str],
    left_atom: object,
    right_identity: tuple[str, str, str, str],
    right_atom: object,
) -> tuple[str, ...]:
    """构造忽略边方向、保留两端完整残基身份和原子名的连接签名。"""

    left = (*left_identity, clean_identity_value(left_atom))
    right = (*right_identity, clean_identity_value(right_atom))
    return (*left, *right) if left <= right else (*right, *left)


def _connection_to_json(signature: tuple[str, ...]) -> dict[str, object]:
    """把十段连接签名转换成字段自解释的 JSON 对象。"""

    return {
        "left": identity_to_json(tuple(signature[0:4])),
        "left_atom": signature[4],
        "right": identity_to_json(tuple(signature[5:9])),
        "right_atom": signature[9],
    }


def _expanded_connection_counter(
    counter: Counter[tuple[str, ...]],
) -> list[dict[str, object]]:
    """展开连接多重集合，使重复连接不会在 JSON 审计中丢失。"""

    return [
        _connection_to_json(signature)
        for signature in sorted(counter)
        for _ in range(counter[signature])
    ]


def connection_audit(
    occurrence: dict[str, object],
    selected: dict[str, object],
) -> dict[str, object]:
    """比较 occurrence 与唯一 CLC 的残基身份—原子名连接多重集合。

    occurrence 没有保存原始 mmCIF 连接键级，因此这里只比较端点，不把比较结果
    用作 CLC 选择或模型输入门控。重复的完整残基身份会被标记；此时身份级比较
    不能区分两个身份完全相同的 residue 实例，但仍保留连接数量差异。
    """

    components = occurrence.get("components", [])
    component_by_index: dict[int, tuple[str, str, str, str]] = {}
    expected_errors: list[str] = []
    if isinstance(components, list):
        for position, component in enumerate(components, start=1):
            try:
                component_index = int(component.get("index", position))
                component_by_index[component_index] = component_identity(component)
            except Exception as exc:
                expected_errors.append(clean_exception(exc))

    expected: Counter[tuple[str, ...]] = Counter()
    inter_bonds = occurrence.get("inter_bonds", [])
    if isinstance(inter_bonds, list):
        for bond in inter_bonds:
            try:
                left_index, left_atom, right_index, right_atom = bond
                expected[
                    _canonical_connection(
                        component_by_index[int(left_index)],
                        left_atom,
                        component_by_index[int(right_index)],
                        right_atom,
                    )
                ] += 1
            except Exception as exc:
                expected_errors.append(clean_exception(exc))

    observed: Counter[tuple[str, ...]] = Counter()
    for edge in selected["edges"]:
        observed[
            _canonical_connection(
                component_identity(edge["left"]),
                edge["left_atom"],
                component_identity(edge["right"]),
                edge["right_atom"],
            )
        ] += 1

    identities = [component_identity(value) for value in components]
    return {
        "comparison_level": "residue_identity_and_atom_name_multiset",
        "comparison_is_model_input_gate": False,
        "duplicate_residue_identity_present": len(identities) != len(set(identities)),
        "bond_order_comparison_available": False,
        "expected_connection_count": sum(expected.values()),
        "observed_connection_count": sum(observed.values()),
        "expected_connection_parse_errors": expected_errors,
        "identity_atom_multiset_matches": expected == observed and not expected_errors,
        "expected_connections": _expanded_connection_counter(expected),
        "observed_connections": _expanded_connection_counter(observed),
        "missing_from_clc": _expanded_connection_counter(expected - observed),
        "extra_in_clc": _expanded_connection_counter(observed - expected),
    }


def prepare_exact_clc(
    occurrence: dict[str, object],
    clc_candidates: list[dict[str, object]],
    pdb_clc_audit: dict[str, object],
) -> dict[str, object] | None:
    """按完整残基身份多重集合选择唯一 CLC，并尝试产生 SMILES。

    返回 ``None`` 只表示没有唯一候选。唯一候选即使没有生成非空模型输入，也会
    返回完整尝试记录，供调用者在走 present 图回退时一并保存。没有最高重合、
    并列任选或其他模糊对应分支。

    非空返回值包含准备来源、两种 SMILES、化学事实和 ``preparation_audit``。
    ``selected_clc.connection_audit`` 只比较“完整残基身份—原子名”连接多重集合；
    比较失败或比较代码异常都不改变唯一 CLC 的模型输入资格。
    """

    components = occurrence.get("components", [])
    if not isinstance(components, list):
        components = []
    identities = [component_identity(value) for value in components]
    identity_multiset = Counter(identities)
    exact = [
        value
        for value in clc_candidates
        if value["identity_multiset"] == identity_multiset
    ]
    assembly_audit: dict[str, object] = {
        **pdb_clc_audit,
        "occurrence_component_identities": [
            identity_to_json(value) for value in identities
        ],
        "occurrence_component_identity_multiset_size": len(identities),
        "exact_clc_match_count": len(exact),
        "clc_candidates": [_candidate_audit(value) for value in clc_candidates],
        "occurrence_inter_bonds": occurrence.get("inter_bonds", []),
        "occurrence_inter_bond_count": len(occurrence.get("inter_bonds", [])),
        "selected_clc": None,
    }
    if len(exact) != 1:
        return None

    selected = exact[0]
    selected_audit = _candidate_audit(selected)
    selected_audit["smiles_generation_attempted"] = True
    try:
        selected_audit["connection_audit"] = connection_audit(occurrence, selected)
    except Exception as exc:
        # 连接比较只是诊断；它自身失败时仍继续使用唯一精确 CLC 生成模型输入。
        selected_audit["connection_audit"] = {
            "comparison_is_model_input_gate": False,
            "audit_error": clean_exception(exc),
        }
    assembly_audit["selected_clc"] = selected_audit
    result = selected["result"]
    remove_h_error: BaseException | None = None
    try:
        mol = Chem.RemoveHs(Chem.Mol(result.component.mol), sanitize=False)
    except Exception as exc:
        remove_h_error = exc
        mol = Chem.Mol(result.component.mol)
    generated = smiles_from_mol(mol)
    rdkit_audit = generated.pop("rdkit")
    assembly_audit["remove_explicit_hydrogen_success"] = remove_h_error is None
    assembly_audit["remove_explicit_hydrogen_error"] = _exception_or_none(
        remove_h_error
    )
    assembly_audit["rdkit"] = rdkit_audit
    selected_audit["assembled_isomeric_smiles"] = generated["assembled_isomeric_smiles"]
    selected_audit["model_input_smiles"] = generated["model_input_smiles"]
    return {
        "preparation_source": "pdbeccdutils_clc",
        "source_smiles": None,
        **generated,
        "preparation_audit": assembly_audit,
    }


def _bond_type_from_array(type_flags: np.ndarray) -> tuple[Chem.BondType, int]:
    """解码 ``bool (5,)`` 键类型，并返回活跃位置数供后备图审计。

    恰好一个 True 时按 Stage C 固定顺序解码；全 False 时确定性使用单键；多个 True
    时确定性使用顺序最前的类别。后两种字段漂移不会在这里停止宽口径后备表示，
    调用者会分别计数并记录所采用的回退规则。
    """

    active = np.flatnonzero(np.asarray(type_flags, dtype=bool))
    index = int(active[0]) if len(active) else 0
    bond_type = BOND_TYPES[index] if index < len(BOND_TYPES) else Chem.BondType.SINGLE
    return bond_type, len(active)


def build_present_graph(
    ligand_object: dict[str, np.ndarray],
    present: np.ndarray,
) -> tuple[Chem.Mol | None, dict[str, object]]:
    """按 occurrence 的 present 掩码过滤 LigandObject 原子和已有键。

    输入 ``atoms`` 是长度 N 的 LigandObject 结构化数组，``bonds`` 是长度 E 的
    结构化数组，``present``/``present_mask`` 是与 N 个模板原子逐项对齐的
    ``bool (N,)``：True 表示该原子出现在当前 PDB occurrence 中。False 可能是缩合
    离去原子，也可能只是普通缺失原子；本函数只记录删除数量，不推断原因。

    ``old_to_new`` 把 LigandObject 旧原子编号映射到过滤后 RDKit 原子编号。只保留
    两端旧编号都在映射中的键；组分间键沿用当前 LigandObject 已存的单键，不补写
    键级。返回 ``(mol, audit)``：成功时 ``mol`` 是未强制 sanitize 的 RDKit Mol；
    失败时为 ``None``。``audit`` 保存 N、present 长度/数量、删除数、E、保留键数、
    单键限制和图构造异常。
    """

    atoms = ligand_object["atoms"]
    bonds = ligand_object["bonds"]
    present_mask = np.asarray(present, dtype=bool)
    audit: dict[str, object] = {
        "template_atom_count": len(atoms),
        "present_mask_length": len(present_mask),
        "present_atom_count": int(present_mask.sum()),
        "removed_template_atom_count": int((~present_mask).sum()),
        "template_bond_count": len(bonds),
        "retained_bond_count": 0,
        "empty_chirality_one_hot_count": 0,
        "multiple_chirality_one_hot_count": 0,
        "chirality_drift_fallback": (
            "empty_keeps_rdkit_default_multiple_uses_first_stage_c_position"
        ),
        "empty_bond_type_one_hot_count": 0,
        "multiple_bond_type_one_hot_count": 0,
        "bond_type_drift_fallback": (
            "empty_uses_single_multiple_uses_first_stage_c_position"
        ),
        "inter_component_bond_types_in_ligand_object_are_single": True,
        "graph_build_error": None,
    }
    if len(present_mask) != len(atoms):
        audit["graph_build_error"] = (
            f"present length {len(present_mask)} != LigandObject atom count {len(atoms)}"
        )
        return None, audit
    if not present_mask.any():
        audit["graph_build_error"] = "occurrence contains no present ligand atom"
        return None, audit

    editable = Chem.RWMol()
    old_to_new: dict[int, int] = {}
    try:
        for old_index, atom_row in enumerate(atoms):
            if not present_mask[old_index]:
                continue
            atom = Chem.Atom(int(atom_row["element"]))
            atom.SetFormalCharge(int(atom_row["charge"]))
            chirality = np.flatnonzero(np.asarray(atom_row["chirality"], dtype=bool))
            if len(chirality) == 0:
                audit["empty_chirality_one_hot_count"] += 1
            elif len(chirality) > 1:
                audit["multiple_chirality_one_hot_count"] += 1
            if len(chirality) and int(chirality[0]) < len(CHIRAL_TAGS):
                atom.SetChiralTag(CHIRAL_TAGS[int(chirality[0])])
            old_to_new[old_index] = editable.AddAtom(atom)

        retained_bonds = 0
        for bond_row in bonds:
            left = int(bond_row["atom_1"])
            right = int(bond_row["atom_2"])
            if left not in old_to_new or right not in old_to_new:
                continue
            bond_type, active_bond_type_count = _bond_type_from_array(bond_row["type"])
            if active_bond_type_count == 0:
                audit["empty_bond_type_one_hot_count"] += 1
            elif active_bond_type_count > 1:
                audit["multiple_bond_type_one_hot_count"] += 1
            editable.AddBond(old_to_new[left], old_to_new[right], bond_type)
            if bond_type == Chem.BondType.AROMATIC:
                editable.GetAtomWithIdx(old_to_new[left]).SetIsAromatic(True)
                editable.GetAtomWithIdx(old_to_new[right]).SetIsAromatic(True)
                editable.GetBondBetweenAtoms(
                    old_to_new[left], old_to_new[right]
                ).SetIsAromatic(True)
            retained_bonds += 1
        audit["retained_bond_count"] = retained_bonds
        mol = editable.GetMol()
        mol.UpdatePropertyCache(strict=False)
        return mol, audit
    except Exception as exc:
        audit["graph_build_error"] = clean_exception(exc)
        return None, audit


def prepare_present_graph_fallback(
    ligand_object: dict[str, np.ndarray],
    present: np.ndarray,
    inherited_audit: dict[str, object],
) -> dict[str, object]:
    """把 present 图后备表示转换成 SMILES；失败时仍返回完整审计记录。"""

    mol, graph_audit = build_present_graph(ligand_object, present)
    audit = {**inherited_audit, "present_graph": graph_audit}
    if mol is None:
        return {
            "preparation_source": "ligand_object_present_graph_fallback",
            "source_smiles": None,
            "assembled_isomeric_smiles": None,
            "model_input_smiles": None,
            "chemistry": {},
            "preparation_audit": audit,
        }

    generated = smiles_from_mol(mol)
    audit["present_graph"]["rdkit"] = generated.pop("rdkit")
    return {
        "preparation_source": "ligand_object_present_graph_fallback",
        "source_smiles": None,
        **generated,
        "preparation_audit": audit,
    }


def base_prepared_record(
    occurrence: dict[str, object],
    output_pdb_id: str,
) -> dict[str, object]:
    """复制 occurrence 身份，并区分目录 PDB 与源记录 PDB。

    正式 ``pdb_id`` 使用当前正在处理的目录名；源 occurrence 中的字段单独保留，
    即使两者不一致也只记录事实，不阻止该 occurrence 继续准备。
    """

    components = occurrence.get("components", [])
    source_pdb_id = clean_identity_value(occurrence.get("pdb_id", "")).lower()
    pdb_id = output_pdb_id.lower()
    return {
        "schema_version": 1,
        "pdb_id": pdb_id,
        "source_occurrence_pdb_id": source_pdb_id,
        "pdb_id_matches_source_occurrence": pdb_id == source_pdb_id,
        "candidate_id": int(occurrence["candidate_id"]),
        "object_key": str(occurrence["object_key"]),
        "kind": str(occurrence.get("kind", "")),
        "type_tag": str(occurrence.get("type_tag", "")),
        "is_covalent": bool(occurrence.get("is_covalent", False)),
        "components": components if isinstance(components, list) else [],
        "inter_bonds": occurrence.get("inter_bonds", []),
        "preparation_warnings": [],
        "preparation_errors": [],
    }


def prepare_occurrence(
    output_pdb_id: str,
    occurrence: dict[str, object],
    present: np.ndarray,
    ligand_object: dict[str, np.ndarray],
    clc_candidates: list[dict[str, object]],
    pdb_clc_audit: dict[str, object],
) -> dict[str, object]:
    """准备一个正式配体 occurrence，并返回可直接写入 JSONL 的自包含记录。

    ``output_pdb_id`` 是当前 ``parse/{pdb_id}`` 目录身份；``present`` 是与该
    LigandObject N 个模板原子逐项对齐的 ``bool (N,)``。返回记录固定包含 occurrence
    身份、源 PDB 一致性、准备来源、两种 SMILES、``has_model_input``、化学事实和
    准备审计。CCD、唯一 CLC、present 图后备和异常记录的条件字段由 README 定义。
    """

    record = base_prepared_record(occurrence, output_pdb_id)
    kind = str(occurrence.get("kind", ""))
    if kind == "CCD":
        prepared = prepare_ccd_smiles(ligand_object)
    elif kind == "BRANCHED":
        clc_preparation_error: str | None = None
        try:
            clc_prepared = prepare_exact_clc(
                occurrence,
                clc_candidates,
                pdb_clc_audit,
            )
        except Exception as exc:
            clc_prepared = None
            clc_preparation_error = clean_exception(exc)
        if clc_prepared is not None and clc_prepared["model_input_smiles"]:
            prepared = clc_prepared
        else:
            components = occurrence.get("components", [])
            identities = (
                [component_identity(value) for value in components]
                if isinstance(components, list)
                else []
            )
            exact_count = sum(
                value["identity_multiset"] == Counter(identities)
                for value in clc_candidates
            )
            fallback_audit = {
                **pdb_clc_audit,
                "occurrence_component_identities": [
                    identity_to_json(value) for value in identities
                ],
                "exact_clc_match_count": exact_count,
                "occurrence_inter_bonds": occurrence.get("inter_bonds", []),
                "occurrence_inter_bond_count": len(occurrence.get("inter_bonds", [])),
                "clc_candidates": [_candidate_audit(value) for value in clc_candidates],
                "unique_exact_clc_preparation_attempt": clc_prepared,
                "unique_exact_clc_preparation_error": clc_preparation_error,
            }
            prepared = prepare_present_graph_fallback(
                ligand_object,
                present,
                fallback_audit,
            )
    else:
        prepared = {
            "preparation_source": "unsupported_occurrence_kind",
            "source_smiles": None,
            "assembled_isomeric_smiles": None,
            "model_input_smiles": None,
            "chemistry": {},
            "preparation_audit": {"unsupported_kind": kind},
        }

    record.update(prepared)
    record["has_model_input"] = bool(record.get("model_input_smiles"))
    return record
