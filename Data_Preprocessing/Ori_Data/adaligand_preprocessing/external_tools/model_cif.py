# 为 Chimera 和 MapQ 写入保留原子身份的模型 mmCIF。
# 主要输入：Stage C receptor/ligand token、真实 XYZ Å 坐标和 ATOM/HETATM 选择。
# 主要输出：标准化 mmCIF、atom_site.id↔内部身份映射和 provenance。
# 关键边界：E2 的 ATOM-only 与 F 的 ATOM+HETATM 是不同模型；模板坐标不能替代沉积坐标。
"""为 Chimera/MapQ 生成身份可追溯的标准化 mmCIF 模型。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import gemmi

from adaligand_preprocessing.utils.io import atomic_replace
from adaligand_preprocessing.stages.stage_c.pipeline import category_rows, clean_value, selected_raw_atom_rows


def write_normalized_model_cif(
    source_path: Path,
    output_path: Path,
    *,
    atom_only: bool,
) -> dict[str, Any]:
    """
    写只含受检 atom_site 的最小标准化模型，并保留原始字段值与行序。

    输入参数:
        - source_path: Path, RCSB 原始完整 mmCIF
        - output_path: Path, per-PDB scratch 中的输出路径
        - atom_only: bool, True 时严格仅保留 ``group_PDB==ATOM``；仅供 E2 receptor-only map

    输出:
        - stats: dict[str, Any], 包含:
            - "n_atoms": int, 选中的重原子总数
            - "n_atom": int, 选中的 ``group_PDB=ATOM`` 原子数
            - "n_hetatm": int, 选中的 ``group_PDB=HETATM`` 原子数
            - "model_num": str, 源 mmCIF 中被选中的首 model 编号

    说明:
        ``atom_only=False`` 用于 F 的 full-model CC/Q-score，保留选中 model 的全部 ATOM/HETATM
        重原子。``atom_only=True`` 只用于 E2；所有 HETATM（含共价修饰）一律删除。
    """
    source_document = gemmi.cif.read(str(source_path))
    source_block = source_document.sole_block()
    raw_rows = category_rows(source_block, "_atom_site.")
    selected = selected_raw_atom_rows(raw_rows, include_hydrogen=False)
    if atom_only:
        selected = [row for row in selected if clean_value(row.get("group_PDB", "")).upper() == "ATOM"]
    if not selected:
        model_kind = "ATOM-only" if atom_only else "full"
        raise ValueError(f"normalized {model_kind} model contains no heavy atom")

    category = source_block.get_mmcif_category("_atom_site.")
    if not category:
        raise ValueError("source mmCIF has no _atom_site category")
    # category_rows 构造了新字典，不能按对象 id 回索；以 atom_site.id 精确选择原列。
    raw_ids = category.get("id")
    if raw_ids is None or len(raw_ids) != len(set(str(value) for value in raw_ids)):
        raise ValueError("source _atom_site.id is missing or non-unique")
    raw_index_by_id = {str(value): index for index, value in enumerate(raw_ids)}
    keep_indices = [raw_index_by_id[str(row["id"])] for row in selected]
    filtered = {
        key: [values[index] for index in keep_indices]
        for key, values in category.items()
    }
    filtered_ids = [str(value) for value in filtered["id"]]
    selected_ids = [str(row["id"]) for row in selected]
    if filtered_ids != selected_ids:
        raise RuntimeError("normalized atom_site ids changed during selection")

    # 外部工具只消费所选原子的 Cartesian atom_site。复制整个源 document 会让已删除的
    # model/altloc/HETATM/H 原子继续被 anisotrop、struct_conn 等类别引用，Classic Chimera
    # 会花数小时打印悬挂引用 warning。最小独立 document 保留每个 atom_site 字段原值，
    # 同时从结构上消除这些无效跨类别引用。
    normalized_document = gemmi.cif.Document()
    normalized_block = normalized_document.add_new_block(source_block.name)
    entry_id = source_block.find_value("_entry.id")
    if entry_id and clean_value(str(entry_id)):
        normalized_block.set_pair("_entry.id", str(entry_id))
    normalized_block.set_mmcif_category("_atom_site.", filtered)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(normalized_document.as_string(), encoding="utf-8", newline="\n")
    atomic_replace(tmp_path, output_path)
    groups = [clean_value(row.get("group_PDB", "")).upper() for row in selected]
    model_num = clean_value(selected[0].get("pdbx_PDB_model_num", "1")) or "1"
    return {
        "n_atoms": len(selected),
        "n_atom": groups.count("ATOM"),
        "n_hetatm": groups.count("HETATM"),
        "model_num": model_num,
    }
