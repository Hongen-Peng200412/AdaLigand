"""从完整 PDB mmCIF 读取 CLC，并与一个 BRANCHED occurrence 精确对应。

CLC（Covalently Linked Component，共价连接组分）由 pdbeccdutils 从完整 mmCIF
组装。本模块只做两件事：读取该包给出的候选；按完整残基身份多重集合选择唯一候选。
它不生成最终 SMILES，也不决定何时改用 LigandObject 的 present 图。

先看 ``read_clc_candidates`` 如何把一个 mmCIF 转成内存候选，再看 ``select_exact_clc``
如何选择一个 occurrence。两个入口只返回候选和诊断字典，不直接写正式文件。
"""

from __future__ import annotations

import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pdbeccdutils.core import clc_reader
from pdbeccdutils.helpers import cif_tools
from rdkit import Chem

from run_context import format_error


# 一个残基实例的完整身份，依次是 CCD 名、作者链、作者残基编号和插入码。
ResidueIdentity = tuple[str, str, str, str]

# 一条无向连接的十段签名：左侧残基四元组、左原子名、右侧残基四元组、右原子名。
Connection = tuple[str, str, str, str, str, str, str, str, str, str]


@dataclass(frozen=True)
class CLCCandidate:
    """pdbeccdutils 从一个 PDB 中组装出的一个共价连接组分。

    属性:
        identities: 长度为 M 的残基身份元组；M 是该 CLC 包含的残基实例数。重复身份保留，顺序不参与匹配。
        molecule: pdbeccdutils 组装出的 RDKit 分子。后续代码复制该对象，不修改候选自身。
        connections: 跨残基连接的多重集合。连接忽略左右方向，但重复连接分别计数。
        warnings: pdbeccdutils 对该候选给出的原始警告文字；警告不自动排除候选。
        errors: pdbeccdutils 对该候选给出的原始错误文字；错误文字也只作为事实保存。
    """

    identities: tuple[ResidueIdentity, ...]
    molecule: Chem.Mol
    connections: Counter[Connection]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


def _clean(value: object) -> str:
    """把一种已知身份值转换成可比较字符串，并统一 mmCIF 的空值写法。

    PDB 作者残基编号在 Stage C 中可能是 ``int`` 或 ``str``；pdbeccdutils 的空插入码
    还可能是 ``None`` 或 ``False``。除此以外的类型表示来源契约漂移，不能静默转成文字。
    """

    if value is None or value is False:
        return ""
    if type(value) not in {str, int}:
        raise TypeError(
            f"残基身份值必须是 str、int、None 或 False，实际为 {type(value).__name__}"
        )
    text = str(value).strip()
    return "" if text in {"", ".", "?"} else text


def _identity_dict(identity: ResidueIdentity) -> dict[str, str]:
    """把内部四元组转换成字段名明确、可直接写入 JSON 的残基身份。"""

    return {
        "ccd_id": identity[0],
        "auth_asym_id": identity[1],
        "auth_seq_id": identity[2],
        "insertion_code": identity[3],
    }


def _connection(
    left_identity: ResidueIdentity,
    left_atom: object,
    right_identity: ResidueIdentity,
    right_atom: object,
) -> Connection:
    """建立忽略左右方向的连接签名，使同一条无向边只有一种表示。

    原子名必须是非空字符串。该签名不包含键级，因为现有 ``occurrences.jsonl`` 的
    ``inter_bonds`` 只保存组分编号和原子名，没有保留原始 mmCIF 的连接键级。
    """

    if type(left_atom) is not str or not left_atom.strip():
        raise TypeError("连接左端原子名必须是非空字符串")
    if type(right_atom) is not str or not right_atom.strip():
        raise TypeError("连接右端原子名必须是非空字符串")
    left = (*left_identity, left_atom.strip())
    right = (*right_identity, right_atom.strip())
    return (*left, *right) if left <= right else (*right, *left)


# ================================================================================================


def read_clc_candidates(
    mmcif_path: Path,
) -> tuple[list[CLCCandidate], dict[str, object]]:
    """用 pdbeccdutils 的官方流程读取一个 PDB 的全部 CLC 候选。

    参数:
        mmcif_path: 当前 PDB 的完整 ``raw/rcsb_mmcif/{pdb_id}.cif`` 文件。

    返回:
        第一个值是成功转换为 RDKit 分子的 CLC 候选列表。
        第二个值是读取事实，字段如下：

        candidate_count: 成功转换的候选数。
        package_result_count: pdbeccdutils 原始返回数；整个读取失败时为 ``None``。
        error: mmCIF 预处理或整体读取异常；成功时为 ``None``。
        candidate_warnings: 若干对象；每个对象的 ``candidate_index: int`` 是包返回列表中的零基序号，``messages: list[str]`` 保存该候选的原始警告。
        candidate_errors: 若干对象；字段与 candidate_warnings 相同，messages 保存包错误或候选转换异常。
        package_charge_and_bond_order_are_not_treated_as_authoritative: 固定为 ``True``，表示本项目不会把包产物的形式电荷和连接键级宣称为唯一化学真值。

    整体读取失败时返回空候选和完整诊断，而不抛出普通解析异常。调用者因此仍能尝试
    present 图。单个候选转换失败只跳过该候选，并保留其原始序号和异常。
    """

    base_diagnostics: dict[str, object] = {
        "candidate_count": 0,
        "package_result_count": None,
        "error": None,
        "candidate_warnings": [],
        "candidate_errors": [],
        "package_charge_and_bond_order_are_not_treated_as_authoritative": True,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="adaligand_clc_") as temporary_dir:
            # pdbeccdutils 要求先用同一项目提供的工具规范化新版 mmCIF。
            processed_path = Path(temporary_dir) / mmcif_path.name
            cif_tools.fix_updated_mmcif(str(mmcif_path), str(processed_path))
            results = clc_reader.read_pdb_cif_file(str(processed_path), sanitize=True)
            if results is None:
                raise TypeError("pdbeccdutils CLC 读取器返回 None")
            # 固定为列表后，候选数量和后续单次遍历不会依赖外部包是否返回生成器。
            results = list(results)
    except Exception as error:
        base_diagnostics["error"] = format_error(error)
        return [], base_diagnostics

    candidates: list[CLCCandidate] = []
    candidate_warnings: list[dict[str, object]] = []
    candidate_errors: list[dict[str, object]] = []
    for candidate_index, result in enumerate(results):
        try:
            graph = result.bound_molecule.graph

            # identity_by_node 与图节点一一对应；后续按节点顺序生成 identities，因此重复身份不会被字典折叠。
            identity_by_node: dict[object, ResidueIdentity] = {}
            for node in graph.nodes:
                identity_by_node[node] = (
                    _clean(node.name).upper(),
                    _clean(node.chain),
                    _clean(node.res_id),
                    _clean(node.ins_code),
                )
            identities = tuple(identity_by_node[node] for node in graph.nodes)

            # connections 保存跨残基图边及其重复次数；原子名缺失时记录候选错误，不用空字符串伪造连接。
            connections: Counter[Connection] = Counter()
            for left_node, right_node, edge in graph.edges(data=True):
                connections[
                    _connection(
                        identity_by_node[left_node],
                        edge["atom_id_1"],
                        identity_by_node[right_node],
                        edge["atom_id_2"],
                    )
                ] += 1

            candidate = CLCCandidate(
                identities=identities,
                molecule=Chem.Mol(result.component.mol),
                connections=connections,
                warnings=tuple(str(value) for value in (result.warnings or [])),
                errors=tuple(str(value) for value in (result.errors or [])),
            )
        except Exception as error:
            candidate_errors.append(
                {"candidate_index": candidate_index, "messages": [format_error(error)]}
            )
            continue

        candidates.append(candidate)
        if candidate.warnings:
            candidate_warnings.append(
                {
                    "candidate_index": candidate_index,
                    "messages": list(candidate.warnings),
                }
            )
        if candidate.errors:
            candidate_errors.append(
                {"candidate_index": candidate_index, "messages": list(candidate.errors)}
            )

    return candidates, {
        **base_diagnostics,
        "candidate_count": len(candidates),
        "package_result_count": len(results),
        "candidate_warnings": candidate_warnings,
        "candidate_errors": candidate_errors,
    }


def select_exact_clc(
    occurrence: dict[str, object],
    candidates: list[CLCCandidate],
) -> tuple[CLCCandidate | None, dict[str, object]]:
    """按完整残基身份多重集合选择唯一 CLC，并单独记录连接核验事实。

    ``components`` 中每个残基的身份是
    ``(ccd_id, auth_asym_id, auth_seq_id, insertion_code)``。Stage C 当前写入的插入码
    字段名是 ``icode``；函数也接受语义更直白的 ``insertion_code``。若两者同时存在则
    使用 ``insertion_code``；若两者都不存在则报告字段缺失。比较使用 ``Counter``，所以
    相同身份重复两次不会被普通集合折叠。

    只有恰好一个 CLC 的身份多重集合完全相同才返回该候选。不会做最高重合、并列任选，
    也不会用连接比较改变这个选择。连接核验只记录 occurrence 与 CLC 的端点是否一致。

    返回诊断字段:
        occurrence_component_count: occurrence 中的残基实例数。
        exact_match_count: 身份多重集合完全相同的 CLC 数。
        occurrence_identities: 无法唯一匹配时保存的完整残基身份对象列表；每个对象包含字符串字段 ``ccd_id``、``auth_asym_id``、``auth_seq_id`` 和 ``insertion_code``。
        connection_check.matches: 连接端点多重集合相同且没有解析异常时为 ``True``。
        connection_check.expected_count: occurrence 成功解析的组分间连接数。
        connection_check.declared_count: occurrence 原文声明的组分间连接数；字段类型错误时为 ``None``。
        connection_check.observed_count: 选中 CLC 图中的跨残基连接数。
        connection_check.parse_errors: component.index 或 inter_bond 的解析异常。
        connection_check.used_for_smiles_selection: 固定为 ``False``。
        connection_check.missing_connections: occurrence 声明但 CLC 未出现的连接对象列表；仅两侧多重集合不同时出现。
        connection_check.extra_connections: CLC 出现但 occurrence 未声明的连接对象列表；仅两侧多重集合不同时出现。

        connection_check.missing_connections[*].left: occurrence 连接左端的四字段残基身份对象。
        connection_check.missing_connections[*].left_atom: occurrence 连接左端的非空原子名。
        connection_check.missing_connections[*].right: occurrence 连接右端的四字段残基身份对象。
        connection_check.missing_connections[*].right_atom: occurrence 连接右端的非空原子名。
        connection_check.extra_connections[*].left: CLC 额外连接左端的四字段残基身份对象。
        connection_check.extra_connections[*].left_atom: CLC 额外连接左端的非空原子名。
        connection_check.extra_connections[*].right: CLC 额外连接右端的四字段残基身份对象。
        connection_check.extra_connections[*].right_atom: CLC 额外连接右端的非空原子名；重复连接保留相同数量的对象。
    """

    components = occurrence.get("components")
    if not isinstance(components, list):
        raise TypeError("BRANCHED occurrence 的 components 必须是列表")

    expected_identities_list: list[ResidueIdentity] = []
    for component_position, component in enumerate(components):
        if not isinstance(component, dict):
            raise TypeError(f"components[{component_position}] 必须是字典")
        for field in ("ccd_id", "auth_asym_id", "auth_seq_id"):
            if field not in component:
                raise KeyError(f"components[{component_position}] 缺少 {field}")
        if "insertion_code" in component:
            insertion_code = component["insertion_code"]
        elif "icode" in component:
            insertion_code = component["icode"]
        else:
            raise KeyError(
                f"components[{component_position}] 缺少 insertion_code 或 icode"
            )
        expected_identities_list.append(
            (
                _clean(component["ccd_id"]).upper(),
                _clean(component["auth_asym_id"]),
                _clean(component["auth_seq_id"]),
                _clean(insertion_code),
            )
        )
    expected_identities = tuple(expected_identities_list)
    expected_multiset = Counter(expected_identities)

    exact_matches = [
        candidate
        for candidate in candidates
        if Counter(candidate.identities) == expected_multiset
    ]
    diagnostics: dict[str, object] = {
        "occurrence_component_count": len(expected_identities),
        "exact_match_count": len(exact_matches),
    }
    if len(exact_matches) != 1:
        diagnostics["occurrence_identities"] = [
            _identity_dict(identity) for identity in expected_identities
        ]
        return None, diagnostics

    selected = exact_matches[0]

    # component_by_index 把 Stage C 的一基组分编号映射到已核实的残基身份；编号缺失、非整数或重复只使连接核验失败，不撤销唯一身份匹配。
    component_by_index: dict[int, ResidueIdentity] = {}
    connection_parse_errors: list[str] = []
    for component_position, (component, identity) in enumerate(
        zip(components, expected_identities, strict=True)
    ):
        try:
            component_index = component["index"]
            if type(component_index) is not int or component_index < 1:
                raise TypeError("component.index 必须是正整数")
            if component_index in component_by_index:
                raise ValueError(f"component.index={component_index} 重复")
            component_by_index[component_index] = identity
        except Exception as error:
            connection_parse_errors.append(
                f"components[{component_position}]: {format_error(error)}"
            )

    inter_bonds = occurrence.get("inter_bonds")
    if isinstance(inter_bonds, list):
        declared_count: int | None = len(inter_bonds)
    else:
        declared_count = None
        inter_bonds = []
        connection_parse_errors.append(
            "TypeError: occurrence 的 inter_bonds 必须是列表"
        )

    expected_connections: Counter[Connection] = Counter()
    for bond_position, inter_bond in enumerate(inter_bonds):
        try:
            if not isinstance(inter_bond, list) or len(inter_bond) != 4:
                raise TypeError("inter_bond 必须是四元素列表")
            left_index, left_atom, right_index, right_atom = inter_bond
            if type(left_index) is not int or type(right_index) is not int:
                raise TypeError("inter_bond 两端组分编号必须是整数")
            expected_connections[
                _connection(
                    component_by_index[left_index],
                    left_atom,
                    component_by_index[right_index],
                    right_atom,
                )
            ] += 1
        except Exception as error:
            connection_parse_errors.append(
                f"inter_bonds[{bond_position}]: {format_error(error)}"
            )

    observed_connections = selected.connections
    connection_check: dict[str, object] = {
        "matches": (
            expected_connections == observed_connections and not connection_parse_errors
        ),
        "declared_count": declared_count,
        "expected_count": sum(expected_connections.values()),
        "observed_count": sum(observed_connections.values()),
        "parse_errors": connection_parse_errors,
        "used_for_smiles_selection": False,
    }
    if expected_connections != observed_connections:
        missing_counter = expected_connections - observed_connections
        missing_connections: list[dict[str, object]] = []
        for connection in sorted(missing_counter):
            value = {
                "left": _identity_dict(connection[0:4]),
                "left_atom": connection[4],
                "right": _identity_dict(connection[5:9]),
                "right_atom": connection[9],
            }
            missing_connections.extend([value] * missing_counter[connection])

        extra_counter = observed_connections - expected_connections
        extra_connections: list[dict[str, object]] = []
        for connection in sorted(extra_counter):
            value = {
                "left": _identity_dict(connection[0:4]),
                "left_atom": connection[4],
                "right": _identity_dict(connection[5:9]),
                "right_atom": connection[9],
            }
            extra_connections.extend([value] * extra_counter[connection])
        connection_check["missing_connections"] = missing_connections
        connection_check["extra_connections"] = extra_connections

    diagnostics["connection_check"] = connection_check
    return selected, diagnostics
