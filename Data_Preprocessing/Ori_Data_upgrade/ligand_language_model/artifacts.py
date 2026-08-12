"""定义、校验并读写配体语言模型管线的正式 occurrence 产物。

``PreparedLigand`` 定义 CPU 准备记录，``ModelResult`` 定义一套模型的 occurrence
状态，``write_embedding`` 定义分子向量 NPZ。调用者传入每个输出路径；本模块不选择
PDB、不准备 SMILES、不调用语言模型，也不写数组任务报告。

``prepared_smiles.jsonl`` 的每个 JSON 对象对应一个 ``(pdb_id, candidate_id)``。
``results.jsonl`` 的每个 JSON 对象对应同一 occurrence 在一套模型中的状态。
``candidate_{candidate_id}.npz`` 保存身份、两种 SMILES 事实和一个 ``float32 (768,)``
分子向量。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from uuid import uuid4

import numpy as np


# ``other`` 只在 CPU 分片报告中计数，不得进入 prepared 文件或模型工作列表。
FORMAL_TYPE_TAGS = (
    "ion",
    "nucleotide_like",
    "peptide_like",
    "small_molecule",
    "sugar",
)

PREPARATION_SOURCES = (
    "ccd",
    "clc",
    "present_graph",
    "unsupported",
    "occurrence_error",
)

MODEL_STATUSES = (
    "encoded",
    "model_failed",
    "no_smiles",
)


@dataclass(frozen=True)
class PreparedLigand:
    """
    一个 PDB 中一个候选配体的 CPU 准备结果。

    顶层字段:
        - pdb_id: str, 当前 ``parse/{pdb_id}`` 目录的小写 PDB 标识。
        - candidate_id: int, 当前 PDB 内的 occurrence 编号；与 ``ligand_coords.npz::present_{candidate_id}`` 的后缀相同。
        - object_key: str, occurrence 引用的 LigandObject 化学模板键；多个 occurrence 可以共享同一模板键。
        - kind: str, ``CCD``、``BRANCHED`` 或源文件中的其他非空值；其他值对应 ``smiles_source=unsupported``。
        - type_tag: str, ``ion``、``nucleotide_like``、``peptide_like``、``small_molecule`` 或 ``sugar``。
        - is_covalent: bool, Stage C 是否把该 occurrence 标记为与受体共价连接；该值不改变 SMILES 选择。
        - smiles: str 或 None, 交给模型公开接口的非空字符串；所有准备方式都没有得到字符串时为 None。
        - smiles_source: str, ``ccd``、``clc``、``present_graph``、``unsupported`` 或 ``occurrence_error``。
        - diagnostics: dict[str, object], 只记录化学转换与异常事实；本字段不自动筛除 occurrence。

    ``smiles_source=ccd`` 的 diagnostics:
        - raw_smiles: str, LigandObject NPZ 中的原始 SMILES；始终出现，允许为空字符串。
        - rdkit_parse_error: str 或 None, ``Chem.MolFromSmiles(..., sanitize=False)`` 的异常或 ``RDKit returned None``；成功建图时为 None。
        - used_raw_smiles: bool, 仅在 RDKit 没有生成非空 canonical SMILES、因而继续采用 raw_smiles 时出现并为 True。
        - sanitize_error: str 或 None, ``Chem.SanitizeMol`` 的单行异常；没有异常时为 None。
        - isomeric_smiles: str 或 None, 同一 RDKit 分子的 canonical isomeric SMILES；生成失败或为空时为 None。
        - isomeric_smiles_error: str 或 None, 生成 isomeric SMILES 的单行异常。
        - model_smiles_error: str 或 None, 生成 canonical non-isomeric SMILES 的单行异常。
        - stereo_removed: bool 或 None, isomeric 与 non-isomeric 两个非空字符串是否不同；任一缺失时为 None。
        - chemistry.atom_count: int, 当前 RDKit 分子的原子数。
        - chemistry.fragment_count: int 或 None, 断开片段数；统计失败时为 None。
        - chemistry.fragment_count_error: str 或 None, 片段统计异常；成功时为 None。
        - chemistry.has_disconnected_components: bool 或 None, 片段数是否大于一；片段数未知时为 None。
        - chemistry.has_metal: bool, 是否含项目用于报告的金属原子。
        - chemistry.charged_atom_count: int, 形式电荷不为零的原子数。
        - chemistry.total_formal_charge: int, 全部分子原子形式电荷的代数和。

    ``smiles_source=clc`` 或 ``present_graph`` 的 diagnostics:
        - clc.read.candidate_count: int, 成功转换成项目候选的 CLC 数量。
        - clc.read.package_result_count: int 或 None, pdbeccdutils 原始返回数；整体读取失败时为 None。
        - clc.read.error: str 或 None, mmCIF 预处理或整体读取异常。
        - clc.read.candidate_warnings: list[dict[str, object]], 有警告的包候选列表；允许为空。
        - clc.read.candidate_warnings[*].candidate_index: int, 该候选在包返回列表中的零基序号。
        - clc.read.candidate_warnings[*].messages: list[str], 该候选的全部包警告；非空。
        - clc.read.candidate_warnings[*].messages[*]: str, 一条包警告。
        - clc.read.candidate_errors: list[dict[str, object]], 有错误或转换异常的包候选列表；允许为空。
        - clc.read.candidate_errors[*].candidate_index: int, 该候选在包返回列表中的零基序号。
        - clc.read.candidate_errors[*].messages: list[str], 该候选的全部包错误或转换异常；非空。
        - clc.read.candidate_errors[*].messages[*]: str, 一条包错误或转换异常。
        - clc.read.package_charge_and_bond_order_are_not_treated_as_authoritative: bool, 固定为 True。
        - clc.selection.occurrence_component_count: int, occurrence 中的残基实例数。
        - clc.selection.exact_match_count: int, 残基身份多重集合完全相同的候选数。
        - clc.selection.occurrence_identities: list[dict[str, str]], 无法唯一匹配时保存重复项不折叠的身份。
        - clc.selection.occurrence_identities[*].ccd_id: str, 一个残基实例的 CCD 名称。
        - clc.selection.occurrence_identities[*].auth_asym_id: str, 一个残基实例的作者链标识。
        - clc.selection.occurrence_identities[*].auth_seq_id: str, 一个残基实例的作者残基编号。
        - clc.selection.occurrence_identities[*].insertion_code: str, 一个残基实例的统一插入码；空值为 ""。
        - clc.selection.error: str, occurrence 残基身份无法解释时出现。
        - clc.selection.connection_check.matches: bool, 仅唯一精确匹配时出现；连接多重集合相同且没有解析异常时为 True。
        - clc.selection.connection_check.declared_count: int 或 None, 仅唯一精确匹配时出现；inter_bonds 原文条数，类型错误时为 None。
        - clc.selection.connection_check.expected_count: int, 仅唯一精确匹配时出现；成功解析的 occurrence 连接数。
        - clc.selection.connection_check.observed_count: int, 仅唯一精确匹配时出现；唯一 CLC 的跨残基图边数。
        - clc.selection.connection_check.parse_errors: list[str], 仅唯一精确匹配时出现；组分编号或 inter_bond 解析异常。
        - clc.selection.connection_check.used_for_smiles_selection: bool, 仅唯一精确匹配时出现并固定为 False。
        - clc.selection.connection_check.missing_connections: list[dict[str, object]], 仅唯一精确匹配且连接不一致时出现；保存 occurrence 声明但 CLC 未观察到的连接。
        - clc.selection.connection_check.missing_connections[*].left.ccd_id: str, 缺失连接左端残基的 CCD 名称。
        - clc.selection.connection_check.missing_connections[*].left.auth_asym_id: str, 缺失连接左端残基的作者链标识。
        - clc.selection.connection_check.missing_connections[*].left.auth_seq_id: str, 缺失连接左端残基的作者残基编号。
        - clc.selection.connection_check.missing_connections[*].left.insertion_code: str, 缺失连接左端残基的统一插入码。
        - clc.selection.connection_check.missing_connections[*].left_atom: str, 缺失连接左端的非空原子名。
        - clc.selection.connection_check.missing_connections[*].right.ccd_id: str, 缺失连接右端残基的 CCD 名称。
        - clc.selection.connection_check.missing_connections[*].right.auth_asym_id: str, 缺失连接右端残基的作者链标识。
        - clc.selection.connection_check.missing_connections[*].right.auth_seq_id: str, 缺失连接右端残基的作者残基编号。
        - clc.selection.connection_check.missing_connections[*].right.insertion_code: str, 缺失连接右端残基的统一插入码。
        - clc.selection.connection_check.missing_connections[*].right_atom: str, 缺失连接右端的非空原子名。
        - clc.selection.connection_check.extra_connections: list[dict[str, object]], 仅唯一精确匹配且连接不一致时出现；保存 CLC 观察到但 occurrence 未声明的连接。
        - clc.selection.connection_check.extra_connections[*].left.ccd_id: str, 额外连接左端残基的 CCD 名称。
        - clc.selection.connection_check.extra_connections[*].left.auth_asym_id: str, 额外连接左端残基的作者链标识。
        - clc.selection.connection_check.extra_connections[*].left.auth_seq_id: str, 额外连接左端残基的作者残基编号。
        - clc.selection.connection_check.extra_connections[*].left.insertion_code: str, 额外连接左端残基的统一插入码。
        - clc.selection.connection_check.extra_connections[*].left_atom: str, 额外连接左端的非空原子名。
        - clc.selection.connection_check.extra_connections[*].right.ccd_id: str, 额外连接右端残基的 CCD 名称。
        - clc.selection.connection_check.extra_connections[*].right.auth_asym_id: str, 额外连接右端残基的作者链标识。
        - clc.selection.connection_check.extra_connections[*].right.auth_seq_id: str, 额外连接右端残基的作者残基编号。
        - clc.selection.connection_check.extra_connections[*].right.insertion_code: str, 额外连接右端残基的统一插入码。
        - clc.selection.connection_check.extra_connections[*].right_atom: str, 额外连接右端的非空原子名。
        - clc.remove_h_error: str 或 None, 对唯一 CLC 删除显式氢时的异常；未尝试或没有异常时为 None。
        - clc.preparation_error: str 或 None, 唯一 CLC 复制或分子转换在外层抛出的异常；未尝试或没有异常时为 None。
        - clc.molecule.sanitize_error: str 或 None, 仅唯一 CLC 进入分子转换后出现；保存 sanitize 异常。
        - clc.molecule.isomeric_smiles: str 或 None, 仅唯一 CLC 进入分子转换后出现；保存 canonical isomeric SMILES。
        - clc.molecule.isomeric_smiles_error: str 或 None, 仅唯一 CLC 进入分子转换后出现；保存 isomeric MolToSmiles 异常。
        - clc.molecule.model_smiles_error: str 或 None, 仅唯一 CLC 进入分子转换后出现；保存 non-isomeric MolToSmiles 异常。
        - clc.molecule.stereo_removed: bool 或 None, 仅唯一 CLC 进入分子转换后出现；表示两种非空 SMILES 是否不同。
        - clc.molecule.chemistry.atom_count: int, 仅唯一 CLC 进入分子转换后出现；分子原子数。
        - clc.molecule.chemistry.fragment_count: int 或 None, 仅唯一 CLC 进入分子转换后出现；断开片段数。
        - clc.molecule.chemistry.fragment_count_error: str 或 None, 仅唯一 CLC 进入分子转换后出现；片段统计异常。
        - clc.molecule.chemistry.has_disconnected_components: bool 或 None, 仅唯一 CLC 进入分子转换后出现；片段是否多于一个。
        - clc.molecule.chemistry.has_metal: bool, 仅唯一 CLC 进入分子转换后出现；是否含报告集合中的金属原子。
        - clc.molecule.chemistry.charged_atom_count: int, 仅唯一 CLC 进入分子转换后出现；带形式电荷原子数。
        - clc.molecule.chemistry.total_formal_charge: int, 仅唯一 CLC 进入分子转换后出现；总形式电荷。
        - present_graph.template_atom_count: int 或 None, LigandObject 模板原子数。
        - present_graph.template_bond_count: int 或 None, LigandObject 模板键数。
        - present_graph.present_atom_count: int 或 None, present=True 的模板原子数。
        - present_graph.removed_atom_count: int 或 None, present=False 的模板原子数。
        - present_graph.retained_bond_count: int 或 None, 两端原子都保留的模板键数。
        - present_graph.empty_chirality_one_hot_count: int, 保留原子中手性七列全 False 的数量。
        - present_graph.multiple_chirality_one_hot_count: int, 保留原子中手性多列 True 的数量。
        - present_graph.empty_bond_type_one_hot_count: int, 保留键中键型五列全 False 的数量。
        - present_graph.multiple_bond_type_one_hot_count: int, 保留键中键型多列 True 的数量。
        - present_graph.chirality_fallback: str, 空手性与多手性 one-hot 的确定性回退说明。
        - present_graph.bond_type_fallback: str, 空键型与多键型 one-hot 的确定性回退说明。
        - present_graph.error: str 或 None, present 掩码、模板字段或建图异常。
        - present_graph.molecule.sanitize_error: str 或 None, 后备图进入分子转换后出现；保存 sanitize 异常。
        - present_graph.molecule.isomeric_smiles: str 或 None, 后备图进入分子转换后出现；保存 canonical isomeric SMILES。
        - present_graph.molecule.isomeric_smiles_error: str 或 None, 后备图进入分子转换后出现；保存 isomeric MolToSmiles 异常。
        - present_graph.molecule.model_smiles_error: str 或 None, 后备图进入分子转换后出现；保存 non-isomeric MolToSmiles 异常。
        - present_graph.molecule.stereo_removed: bool 或 None, 后备图进入分子转换后出现；表示两种非空 SMILES 是否不同。
        - present_graph.molecule.chemistry.atom_count: int, 后备图进入分子转换后出现；分子原子数。
        - present_graph.molecule.chemistry.fragment_count: int 或 None, 后备图进入分子转换后出现；断开片段数。
        - present_graph.molecule.chemistry.fragment_count_error: str 或 None, 后备图进入分子转换后出现；片段统计异常。
        - present_graph.molecule.chemistry.has_disconnected_components: bool 或 None, 后备图进入分子转换后出现；片段是否多于一个。
        - present_graph.molecule.chemistry.has_metal: bool, 后备图进入分子转换后出现；是否含报告集合中的金属原子。
        - present_graph.molecule.chemistry.charged_atom_count: int, 后备图进入分子转换后出现；带形式电荷原子数。
        - present_graph.molecule.chemistry.total_formal_charge: int, 后备图进入分子转换后出现；总形式电荷。
        - present_graph.molecule_error: str, 后备图分子转换的外层异常；仅异常时出现。

    其他条件字段:
        - diagnostics.error: str, CCD 原文为空、``unsupported`` 或 ``occurrence_error`` 的单行原因；普通成功路径不出现。
        - diagnostics.source_pdb_id_mismatch: str, ``prepare_ligand`` 正常返回且源 PDB 标识与当前目录不同时出现；外层改写的 occurrence_error 不保证保留该差异。
        - diagnostics.ligand_object_error: str, ``smiles_source=present_graph`` 且 BRANCHED 后备模板读取失败时出现。
        - diagnostics.ligand_coords_error: str, ``smiles_source=present_graph`` 且 ``ligand_coords.npz`` 容器或对应 present 成员读取失败时出现。
    """

    pdb_id: str
    candidate_id: int
    object_key: str
    kind: str
    type_tag: str
    is_covalent: bool
    smiles: str | None
    smiles_source: str
    diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """按 dataclass 字段顺序生成可直接写入 prepared JSONL 的 JSON 对象。"""

        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "PreparedLigand":
        """从一个 JSON 对象恢复记录；字段缺失、额外字段或类型漂移均直接报错。"""

        required = {
            "pdb_id",
            "candidate_id",
            "object_key",
            "kind",
            "type_tag",
            "is_covalent",
            "smiles",
            "smiles_source",
            "diagnostics",
        }
        missing = sorted(required - value.keys())
        extra = sorted(value.keys() - required)
        if missing or extra:
            raise ValueError(f"prepared 字段漂移: missing={missing}, extra={extra}")

        if type(value["pdb_id"]) is not str or not value["pdb_id"].strip():
            raise ValueError("prepared pdb_id 必须是非空字符串")
        if value["pdb_id"] != value["pdb_id"].lower():
            raise ValueError("prepared pdb_id 必须使用小写")
        if type(value["candidate_id"]) is not int:
            raise ValueError("prepared candidate_id 必须是整数")
        if value["candidate_id"] < 0:
            raise ValueError("prepared candidate_id 必须是非负整数")
        if type(value["object_key"]) is not str or not value["object_key"].strip():
            raise ValueError("prepared object_key 必须是非空字符串")
        if type(value["kind"]) is not str or not value["kind"].strip():
            raise ValueError("prepared kind 必须是非空字符串")
        if value["type_tag"] not in FORMAL_TYPE_TAGS:
            raise ValueError(
                f"prepared type_tag 不是五类正式配体: {value['type_tag']!r}"
            )
        if type(value["is_covalent"]) is not bool:
            raise ValueError("prepared is_covalent 必须是布尔值")
        if value["smiles"] is not None and (
            type(value["smiles"]) is not str or not value["smiles"].strip()
        ):
            raise ValueError("prepared smiles 必须是非空字符串或 null")
        if value["smiles_source"] not in PREPARATION_SOURCES:
            raise ValueError(f"prepared smiles_source 非法: {value['smiles_source']!r}")
        if type(value["diagnostics"]) is not dict:
            raise ValueError("prepared diagnostics 必须是 JSON 对象")

        return cls(
            pdb_id=value["pdb_id"],
            candidate_id=value["candidate_id"],
            object_key=value["object_key"],
            kind=value["kind"],
            type_tag=value["type_tag"],
            is_covalent=value["is_covalent"],
            smiles=value["smiles"],
            smiles_source=value["smiles_source"],
            diagnostics=value["diagnostics"],
        )


@dataclass(frozen=True)
class ModelResult:
    """
    一个候选配体在一套语言模型中的处理状态。

    顶层字段:
        - pdb_id: str, 与 PreparedLigand.pdb_id 相同的小写 PDB 标识。
        - candidate_id: int, 与 PreparedLigand.candidate_id 相同的 PDB 内 occurrence 编号。
        - type_tag: str, 与 PreparedLigand.type_tag 相同的五类正式配体标签。
        - status: str, ``encoded`` 表示已写向量，``model_failed`` 表示模型调用或向量写入失败，``no_smiles`` 表示 CPU 阶段没有非空 SMILES。
        - prepared_smiles: str 或 None, 传给模型公开接口的 PreparedLigand.smiles；``no_smiles`` 时为 None。
        - model_smiles: str 或 None, 已确认送入 tokenizer 的字符串；SMI-TED 官方规范化没有产生 tokenizer 输入或诊断无法确认时为 None。
        - output_file: str 或 None, ``encoded`` 对应的 ``candidate_{candidate_id}.npz`` 绝对路径；其他状态为 None。
        - error: str 或 None, ``model_failed`` 的非空单行异常；其他状态为 None。
        - diagnostics: dict[str, object], 模型输入、tokenizer、截断和向量有限性事实。

    ``status=no_smiles`` 的 diagnostics 是空对象。MoLFormer diagnostics:
        - token_count_without_special_tokens: int, tokenizer 从 prepared_smiles 拆出的化学 token 数量 T；诊断成功时出现。
        - token_count_with_special_tokens: int, 加入起止 token 后的总长度；诊断成功时出现。
        - unsupported_tokens: list[str], 不在精确词表中的 token 去重列表；诊断成功时出现。
        - token_roundtrip_text: str, 按原顺序拼接 T 个化学 token 得到的文本；诊断成功时出现。
        - token_roundtrip_matches_input: bool, token_roundtrip_text 是否与 prepared_smiles 完全相同；诊断成功时出现。
        - exceeds_pretraining_length_reference: bool, 总长度是否超过 202 token 参考长度；诊断成功时出现。
        - truncation_requested: bool, 固定为 False，诊断成功或失败时都出现。
        - diagnostic_error: str 或 None, tokenizer 诊断异常；诊断成功时为 None，异常不阻止正式模型调用。

    SMI-TED diagnostics:
        - public_api_input_smiles: str, 传给官方公开 ``model.encode`` 的 PreparedLigand.smiles；始终出现。
        - official_normalized_smiles: str 或 None, 独立调用官方 ``normalize_smiles`` 得到的字符串。
        - official_tokenizer_input_smiles: str 或 None, 已确认会进入官方 tokenizer 的规范化字符串；无法确认时为 None。
        - official_normalization_success: bool, 独立规范化是否得到非空字符串。
        - official_normalization_error: str 或 None, 独立规范化异常或未返回非空字符串的原因。
        - token_count_without_special_tokens: int, 规范化字符串的化学 token 数量；tokenizer 诊断成功时出现。
        - token_count_with_special_tokens_before_truncation: int, 加入特殊 token 后、官方截断前的总长度；tokenizer 诊断成功时出现。
        - official_max_length: int, 官方模型对象报告的最大 token 长度；tokenizer 诊断成功时出现。
        - official_default_will_truncate: bool, 截断前总长度是否超过 official_max_length；tokenizer 诊断成功时出现。
        - diagnostic_token_prefix_within_length: str, 按长度规则截取的诊断 token 前缀；tokenizer 诊断成功时出现，不声称这是官方内部张量。
        - unsupported_tokens: list[str], 不在精确词表中的 token 去重列表；tokenizer 诊断成功时出现。
        - unknown_token: str 或 None, 当前官方 tokenizer 配置的未知 token；tokenizer 诊断成功时出现。
        - pad_token: str 或 None, 当前官方 tokenizer 配置的 padding token；tokenizer 诊断成功时出现。
        - unknown_token_equals_pad_token: bool, 两种特殊 token 是否相同；tokenizer 诊断成功时出现。
        - token_roundtrip_text: str, 截断前按原顺序拼接化学 token 得到的文本；tokenizer 诊断成功时出现。
        - token_roundtrip_matches_normalized_smiles: bool, token_roundtrip_text 是否等于 official_normalized_smiles；tokenizer 诊断成功时出现。
        - token_diagnostic_error: str 或 None, 规范化失败时为 None，规范化成功但 tokenizer 诊断失败时保存异常，诊断成功时也为 None。

    ``status=encoded`` 追加的 diagnostics:
        - all_finite: bool, 768 个向量值是否全部有限。
        - nan_count: int, 向量中 NaN 的数量。
        - positive_inf_count: int, 向量中正无穷的数量。
        - negative_inf_count: int, 向量中负无穷的数量。
    """

    pdb_id: str
    candidate_id: int
    type_tag: str
    status: str
    prepared_smiles: str | None
    model_smiles: str | None
    output_file: str | None
    error: str | None
    diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """按 dataclass 字段顺序生成可直接写入 results JSONL 的 JSON 对象。"""

        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ModelResult":
        """从一个 JSON 对象恢复记录，并核对状态相关字段的类型与空值语义。"""

        required = {
            "pdb_id",
            "candidate_id",
            "type_tag",
            "status",
            "prepared_smiles",
            "model_smiles",
            "output_file",
            "error",
            "diagnostics",
        }
        missing = sorted(required - value.keys())
        extra = sorted(value.keys() - required)
        if missing or extra:
            raise ValueError(f"模型结果字段漂移: missing={missing}, extra={extra}")

        if type(value["pdb_id"]) is not str or not value["pdb_id"].strip():
            raise ValueError("模型结果 pdb_id 必须是非空字符串")
        if value["pdb_id"] != value["pdb_id"].lower():
            raise ValueError("模型结果 pdb_id 必须使用小写")
        if type(value["candidate_id"]) is not int:
            raise ValueError("模型结果 candidate_id 必须是整数")
        if value["candidate_id"] < 0:
            raise ValueError("模型结果 candidate_id 必须是非负整数")
        if value["type_tag"] not in FORMAL_TYPE_TAGS:
            raise ValueError(
                f"模型结果 type_tag 不是五类正式配体: {value['type_tag']!r}"
            )
        if value["status"] not in MODEL_STATUSES:
            raise ValueError(f"模型结果 status 非法: {value['status']!r}")
        for field_name in ("prepared_smiles", "model_smiles", "output_file", "error"):
            field_value = value[field_name]
            if field_value is not None and (
                type(field_value) is not str or not field_value.strip()
            ):
                raise ValueError(f"模型结果 {field_name} 必须是非空字符串或 null")
        if type(value["diagnostics"]) is not dict:
            raise ValueError("模型结果 diagnostics 必须是 JSON 对象")

        if value["status"] == "encoded":
            if value["prepared_smiles"] is None or value["output_file"] is None:
                raise ValueError("encoded 必须保存 prepared_smiles 和 output_file")
            if value["error"] is not None:
                raise ValueError("encoded 的 error 必须是 null")
            # 正式写入函数总会写这四项；读取已有 results.jsonl 时允许缺项，使汇总能区分“有限性未知”与“包含非有限值”。
            finite_fields = {
                "all_finite": bool,
                "nan_count": int,
                "positive_inf_count": int,
                "negative_inf_count": int,
            }
            for field_name, expected_type in finite_fields.items():
                if (
                    field_name in value["diagnostics"]
                    and type(value["diagnostics"][field_name]) is not expected_type
                ):
                    raise ValueError(
                        f"encoded diagnostics.{field_name} 类型不符合正式契约"
                    )
        elif value["status"] == "model_failed":
            if value["prepared_smiles"] is None or value["error"] is None:
                raise ValueError("model_failed 必须保存 prepared_smiles 和 error")
            if value["output_file"] is not None:
                raise ValueError("model_failed 的 output_file 必须是 null")
        else:
            if any(
                value[field_name] is not None
                for field_name in (
                    "prepared_smiles",
                    "model_smiles",
                    "output_file",
                    "error",
                )
            ):
                raise ValueError("no_smiles 的四个可空顶层字段必须全部是 null")

        return cls(
            pdb_id=value["pdb_id"],
            candidate_id=value["candidate_id"],
            type_tag=value["type_tag"],
            status=value["status"],
            prepared_smiles=value["prepared_smiles"],
            model_smiles=value["model_smiles"],
            output_file=value["output_file"],
            error=value["error"],
            diagnostics=value["diagnostics"],
        )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    """读取 UTF-8 JSONL；返回顺序与非空物理行一致，每行顶层必须是 JSON 对象。"""

    # values 长度 R；第 i 个元素对应 path 中第 i 个非空物理行，不在此处解释具体产物字段。
    values: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if type(value) is not dict:
                raise ValueError(f"{path}:{line_number} 必须是 JSON 对象")
            values.append(value)
    return values


def _write_jsonl(path: Path, values: Iterable[dict[str, object]]) -> None:
    """把 JSON 对象逐行写入同目录临时文件，全部成功后原子替换正式路径。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for value in values:
                handle.write(json.dumps(value, ensure_ascii=False))
                handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# ================================================================================================


def read_prepared(path: Path, expected_pdb_id: str) -> list[PreparedLigand]:
    """
    读取并校验一个 PDB 的 ``prepared_smiles.jsonl``。

    输入参数:
        - path: Path, ``prepared/{pdb_id}/prepared_smiles.jsonl``；每个非空物理行必须是一个完整 PreparedLigand JSON 对象。
        - expected_pdb_id: str, path 所属目录代表的小写 PDB 标识。

    返回值:
        - records: list[PreparedLigand], 与 JSONL 非空物理行逐位置对应；每条 pdb_id 等于 expected_pdb_id，candidate_id 在当前文件中唯一。
    """

    records = [PreparedLigand.from_dict(value) for value in _read_jsonl(path)]
    candidate_ids: set[int] = set()
    for record in records:
        if record.pdb_id != expected_pdb_id:
            raise ValueError(
                f"{path}: 记录 pdb_id={record.pdb_id}，目录为 {expected_pdb_id}"
            )
        if record.candidate_id in candidate_ids:
            raise ValueError(f"{path}: candidate_id={record.candidate_id} 重复")
        candidate_ids.add(record.candidate_id)
    return records


def write_prepared(path: Path, records: Iterable[PreparedLigand]) -> None:
    """
    一次写出一个 PDB 的全部五类正式 occurrence 准备记录。

    输入参数:
        - path: Path, 目标 ``prepared/{pdb_id}/prepared_smiles.jsonl``；函数自动创建父目录。
        - records: Iterable[PreparedLigand], 当前 PDB 的全部正式 occurrence；空列表表示该 PDB 没有五类正式配体。

    文件内容:
        - prepared_smiles.jsonl: JSONL, 每个非空物理行对应一个 ``(pdb_id, candidate_id)``；顶层字段和条件 diagnostics 由 PreparedLigand 定义。

    完成语义:
        - 函数先核对非空记录只属于一个 PDB 且 candidate_id 唯一，再完整写入同目录临时文件并替换 path；path 存在不表示每条记录都有 SMILES。
    """

    materialized = [PreparedLigand.from_dict(record.to_dict()) for record in records]
    pdb_ids = {record.pdb_id for record in materialized}
    candidate_ids = [record.candidate_id for record in materialized]
    if len(pdb_ids) > 1:
        raise ValueError(f"prepared 写入混入多个 PDB: {sorted(pdb_ids)}")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("prepared 写入存在重复 candidate_id")
    _write_jsonl(path, (record.to_dict() for record in materialized))


def read_model_results(path: Path, expected_pdb_id: str) -> list[ModelResult]:
    """
    读取并校验一套模型对一个 PDB 写出的 ``results.jsonl``。

    输入参数:
        - path: Path, ``{model_stage}/{pdb_id}/results.jsonl``；每个非空物理行必须是一个完整 ModelResult JSON 对象。
        - expected_pdb_id: str, path 所属目录代表的小写 PDB 标识。

    返回值:
        - records: list[ModelResult], 与 JSONL 非空物理行逐位置对应；每条 pdb_id 等于 expected_pdb_id，candidate_id 在当前文件中唯一。
    """

    records = [ModelResult.from_dict(value) for value in _read_jsonl(path)]
    candidate_ids: set[int] = set()
    for record in records:
        if record.pdb_id != expected_pdb_id:
            raise ValueError(
                f"{path}: 记录 pdb_id={record.pdb_id}，目录为 {expected_pdb_id}"
            )
        if record.candidate_id in candidate_ids:
            raise ValueError(f"{path}: candidate_id={record.candidate_id} 重复")
        candidate_ids.add(record.candidate_id)
    return records


def write_model_results(path: Path, records: Iterable[ModelResult]) -> None:
    """
    一次写出一套模型对一个 PDB 的全部 occurrence 状态。

    输入参数:
        - path: Path, 目标 ``{model_stage}/{pdb_id}/results.jsonl``；函数自动创建父目录。
        - records: Iterable[ModelResult], 与该 PDB prepared 记录逐 candidate_id 对应的全部状态；空列表表示 prepared 文件为空。

    文件内容:
        - results.jsonl: JSONL, 每个非空物理行对应一个 ``(pdb_id, candidate_id)``；顶层字段、状态空值与 diagnostics 由 ModelResult 定义。

    完成语义:
        - 函数先核对非空记录只属于一个 PDB 且 candidate_id 唯一，再原子替换 path；单独存在 candidate NPZ 不代表整个 PDB 已完成。
    """

    materialized = [ModelResult.from_dict(record.to_dict()) for record in records]
    pdb_ids = {record.pdb_id for record in materialized}
    candidate_ids = [record.candidate_id for record in materialized]
    if len(pdb_ids) > 1:
        raise ValueError(f"模型结果写入混入多个 PDB: {sorted(pdb_ids)}")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("模型结果写入存在重复 candidate_id")
    _write_jsonl(path, (record.to_dict() for record in materialized))


def write_embedding(
    path: Path,
    prepared: PreparedLigand,
    model_name: str,
    model_smiles: str | None,
    embedding: np.ndarray,
) -> dict[str, object]:
    """
    写出一个 occurrence 的分子级语言模型向量，并返回数值有限性事实。

    输入参数:
        - path: Path, 目标 ``{model_stage}/{pdb_id}/candidate_{candidate_id}.npz``；函数自动创建父目录。
        - prepared: PreparedLigand, 提供 pdb_id、candidate_id、object_key 和非空 prepared.smiles。
        - model_name: str, 当前模型的固定非空名称。
        - model_smiles: str 或 None, 已确认送入 tokenizer 的非空字符串；官方返回向量但没有 tokenizer 输入时为 None。
        - embedding: 数值数组, ``(768,)``；当前 occurrence 的分子级向量，不接受 token 级或原子级矩阵。

    NPZ 字段:
        - pdb_id: 标量字符串, 与 prepared.pdb_id 相同。
        - candidate_id: int32 标量, 与 prepared.candidate_id 相同。
        - object_key: 标量字符串, 与 prepared.object_key 相同。
        - model_name: 标量字符串, 与输入 model_name 相同。
        - prepared_smiles: 标量字符串, 与 prepared.smiles 相同。
        - model_smiles: 标量字符串, 与输入 model_smiles 相同；输入为 None 时保存空字符串，表示没有已确认的 tokenizer 输入。
        - embedding: float32, ``(768,)``；模型返回的分子级向量，NaN 和正负无穷不替换。

    返回字段:
        - all_finite: bool, embedding 的 768 个数是否全部有限。
        - nan_count: int, embedding 中 NaN 的数量。
        - positive_inf_count: int, embedding 中正无穷的数量。
        - negative_inf_count: int, embedding 中负无穷的数量。
    """

    if prepared.smiles is None:
        raise ValueError("只有 prepared.smiles 非空的 occurrence 才能写向量")
    if type(model_name) is not str or not model_name:
        raise ValueError("model_name 必须是非空字符串")
    if model_smiles is not None and (type(model_smiles) is not str or not model_smiles):
        raise ValueError("model_smiles 必须是非空字符串或 None")

    # vector 先保留模型返回的数据类型，只在确认它是数值且形状为 (768,) 后转换成正式 float32。
    vector = np.asarray(embedding)
    if not np.issubdtype(vector.dtype, np.number):
        raise ValueError(f"模型输出不是数值数组: {vector.dtype}")
    if vector.shape != (768,):
        raise ValueError(f"模型输出形状 {vector.shape} != (768,)")
    vector = vector.astype(np.float32, copy=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}.npz")
    try:
        np.savez_compressed(
            temporary,
            pdb_id=np.asarray(prepared.pdb_id),
            candidate_id=np.asarray(prepared.candidate_id, dtype=np.int32),
            object_key=np.asarray(prepared.object_key),
            model_name=np.asarray(model_name),
            prepared_smiles=np.asarray(prepared.smiles),
            model_smiles=np.asarray(model_smiles if model_smiles is not None else ""),
            embedding=vector,
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "all_finite": bool(np.isfinite(vector).all()),
        "nan_count": int(np.isnan(vector).sum()),
        "positive_inf_count": int(np.isposinf(vector).sum()),
        "negative_inf_count": int(np.isneginf(vector).sum()),
    }
