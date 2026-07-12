"""为 Chimera/MapQ 生成身份可追溯的标准化 mmCIF 模型。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import gemmi

from io_utils import atomic_replace
from parse import category_rows, clean_value, selected_raw_atom_rows


def write_normalized_model_cif(
    source_path: Path,
    output_path: Path,
    *,
    atom_only: bool,
) -> dict[str, Any]:
    """
    写首 model、规范 altloc、重原子的标准化模型，并保留原始 atom_site.id。

    输入参数:
        - source_path: Path, RCSB 原始完整 mmCIF
        - output_path: Path, per-PDB scratch 中的输出路径
        - atom_only: bool, True 时严格仅保留 ``group_PDB==ATOM``；仅供 E2 receptor-only map

    输出:
        - stats: dict, 选中原子数、ATOM/HETATM 数和源 model 编号

    说明:
        ``atom_only=False`` 用于 F 的 full-model CC/Q-score，保留选中 model 的全部 ATOM/HETATM
        重原子。``atom_only=True`` 只用于 E2；所有 HETATM（含共价修饰）一律删除。
    """
    document = gemmi.cif.read(str(source_path))
    block = document.sole_block()
    raw_rows = category_rows(block, "_atom_site.")
    selected = selected_raw_atom_rows(raw_rows, include_hydrogen=False)
    if atom_only:
        selected = [row for row in selected if clean_value(row.get("group_PDB", "")).upper() == "ATOM"]
    if not selected:
        model_kind = "ATOM-only" if atom_only else "full"
        raise ValueError(f"normalized {model_kind} model contains no heavy atom")

    category = block.get_mmcif_category("_atom_site.")
    if not category:
        raise ValueError("source mmCIF has no _atom_site category")
    # category_rows 构造了新字典，不能按对象 id 回索；以 atom_site.id 精确选择原列。
    selected_atom_ids = {str(row["id"]) for row in selected}
    raw_ids = category.get("id")
    if raw_ids is None or len(raw_ids) != len(set(str(value) for value in raw_ids)):
        raise ValueError("source _atom_site.id is missing or non-unique")
    keep_indices = [index for index, value in enumerate(raw_ids) if str(value) in selected_atom_ids]
    filtered = {
        key: [values[index] for index in keep_indices]
        for key, values in category.items()
    }
    block.set_mmcif_category("_atom_site.", filtered)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(document.as_string(), encoding="utf-8", newline="\n")
    atomic_replace(tmp_path, output_path)
    groups = [clean_value(row.get("group_PDB", "")).upper() for row in selected]
    model_num = clean_value(selected[0].get("pdbx_PDB_model_num", "1")) or "1"
    return {
        "n_atoms": len(selected),
        "n_atom": groups.count("ATOM"),
        "n_hetatm": groups.count("HETATM"),
        "model_num": model_num,
    }
