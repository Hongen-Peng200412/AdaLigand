"""定义配体语言模型 occurrence 级产物的最小跨阶段契约。

CPU 准备阶段负责写出完整 ``prepared_smiles.jsonl``；GPU 模型阶段只消费其中
识别 occurrence 和取得模型输入所必需的字段。本模块集中保存五个正式配体类别，
并在 GPU 阶段读取前核对 schema、必要字段类型、模型输入一致性和同一 PDB 内
``candidate_id`` 唯一性。

这些检查防止重复编号覆盖同名 NPZ 或字段漂移被静默解释，不判断化学结果是否可用，
也不修改 ``all_valid.json``、``info.json`` 或任何 prepared 记录。
"""

from __future__ import annotations


PREPARED_SCHEMA_VERSION = 1

FORMAL_TYPE_TAGS = (
    "ion",
    "nucleotide_like",
    "peptide_like",
    "small_molecule",
    "sugar",
)


def _require_exact_type(
    record: dict[str, object],
    field: str,
    expected_type: type,
    location: str,
) -> object:
    """读取必要字段，并拒绝 Python 中 ``bool`` 冒充 ``int`` 等隐式类型兼容。"""

    if field not in record:
        raise ValueError(f"{location} 缺少必要字段 {field}")
    value = record[field]
    if type(value) is not expected_type:
        raise ValueError(
            f"{location}::{field} 必须是 {expected_type.__name__}，"
            f"实际是 {type(value).__name__}"
        )
    return value


def validate_prepared_records(
    records: list[dict[str, object]],
    output_pdb_id: str,
) -> None:
    """核对一个 PDB 的 prepared 记录能否安全进入逐 candidate 模型落盘。

    每条记录必须使用 schema 1，并明确给出 ``pdb_id``、``candidate_id``、
    ``object_key``、``kind``、``type_tag``、``is_covalent``、准备来源、模型输入和
    ``has_model_input``。目录 PDB 与记录 PDB 不一致仍由既有审计字段宽口径保留，
    不在这里拒绝；但同一目录内重复 ``candidate_id`` 会写向同一个 NPZ，因此必须
    在调用模型前报告为 prepared 源不可用。

    ``has_model_input=true`` 时，``model_input_smiles`` 必须是非空字符串；为 false
    时该字段可以是 ``None`` 或字符串。函数只校验、不修改输入，无返回值。
    """

    candidate_ids: set[int] = set()
    duplicate_ids: set[int] = set()
    for record_index, record in enumerate(records):
        location = f"{output_pdb_id} prepared record {record_index}"
        schema_version = _require_exact_type(
            record,
            "schema_version",
            int,
            location,
        )
        if schema_version != PREPARED_SCHEMA_VERSION:
            raise ValueError(
                f"{location}::schema_version={schema_version}，"
                f"当前只支持 {PREPARED_SCHEMA_VERSION}"
            )

        _require_exact_type(record, "pdb_id", str, location)
        candidate_id = _require_exact_type(record, "candidate_id", int, location)
        _require_exact_type(record, "object_key", str, location)
        _require_exact_type(record, "kind", str, location)
        _require_exact_type(record, "type_tag", str, location)
        _require_exact_type(record, "is_covalent", bool, location)
        _require_exact_type(record, "preparation_source", str, location)
        has_model_input = _require_exact_type(
            record,
            "has_model_input",
            bool,
            location,
        )
        if "model_input_smiles" not in record:
            raise ValueError(f"{location} 缺少必要字段 model_input_smiles")
        model_input_smiles = record["model_input_smiles"]
        if model_input_smiles is not None and type(model_input_smiles) is not str:
            raise ValueError(
                f"{location}::model_input_smiles 必须是 str 或 null，"
                f"实际是 {type(model_input_smiles).__name__}"
            )
        if has_model_input and not model_input_smiles:
            raise ValueError(
                f"{location} 的 has_model_input=true，但 model_input_smiles 为空"
            )
        if candidate_id in candidate_ids:
            duplicate_ids.add(candidate_id)
        candidate_ids.add(candidate_id)

    if duplicate_ids:
        raise ValueError(
            f"{output_pdb_id} prepared records contain duplicate candidate_id: "
            f"{sorted(duplicate_ids)}"
        )
