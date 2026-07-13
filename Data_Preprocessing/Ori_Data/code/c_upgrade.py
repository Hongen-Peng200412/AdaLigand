# 学习导航：功能分区=数据契约与质量验证；生命周期=一次性兼容迁移工具。
# 主要输入：旧版 Stage C 三件套及当前 schema/字段要求。
# 主要输出：升级后的可读产物与迁移报告。
# 关键边界：只做明确字段兼容，不把旧快照未经审计地当作当前主路径输入。
"""Stage C 旧三件套到当前契约的增量升级。

升级路径只补缺失组件：由旧 `coords/present` 派生 centroid；由去重 LigandObject 生成
descriptors；重新读取 mmCIF 只为受体 bond/feat，并在替换前验证旧 7 个基础数组逐项不变。
任何基础数组差异都停止该样本，禁止把语义变化伪装成一次普通 schema 迁移。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gemmi
import numpy as np

from contracts import (
    CArtifactState,
    compare_receptor_base_arrays,
    inspect_stage_c,
    load_npz_arrays,
    validate_receptor_arrays,
)
from io_utils import atomic_save_npz
from ligand_descriptors import materialize_ligand_descriptor
from receptor import build_receptor_arrays


class ReceptorBaseMismatch(RuntimeError):
    """mmCIF 重建结果与旧 receptor_tokens 基础数组不一致时抛出的错误。"""


def add_ligand_centroids(
    coords_path: Path,
    occurrences: list[dict[str, Any]],
) -> bool:
    """
    在保留原数组的前提下补齐/修复 `centroid_atom_{cid}`。

    输入参数:
        - coords_path: Path, `parse/{pdb_id}/ligand_coords.npz`
        - occurrences: list[dict[str,Any]], 当前成功 occurrence 列表

    输出:
        - changed: bool, 是否原子替换了 NPZ
    """
    arrays = load_npz_arrays(coords_path, allow_pickle=False)
    changed = False
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        coords = arrays[f"coords_{candidate_id}"]
        present = arrays[f"present_{candidate_id}"]
        if not present.any():
            raise ValueError(f"candidate {candidate_id} has no present atom for centroid")
        centroid = coords[present].mean(axis=0, dtype=np.float64).astype(np.float32)
        key = f"centroid_atom_{candidate_id}"
        if key not in arrays or not np.array_equal(arrays[key], centroid):
            arrays[key] = centroid
            changed = True
    if changed:
        atomic_save_npz(coords_path, **arrays)
    return changed


def materialize_occurrence_descriptors(
    root: Path,
    occurrences: list[dict[str, Any]],
    overwrite: bool,
) -> int:
    """
    为 occurrence 引用的 distinct object_key 物化描述子。

    输入参数:
        - root: Path, Stage root
        - occurrences: list[dict[str,Any]], 当前成功 occurrence 列表
        - overwrite: bool, 是否重算已有且有效的描述子

    输出:
        - n_objects: int, 本次检查的 distinct object_key 数
    """
    object_keys = sorted({str(occurrence["object_key"]) for occurrence in occurrences})
    for object_key in object_keys:
        materialize_ligand_descriptor(root, object_key, overwrite)
    return len(object_keys)


def upgrade_receptor_tokens(root: Path, pdb_id: str) -> bool:
    """
    重新读取 mmCIF 补受体 bond/feat，并保证旧 7 个数组完全不变。

    输入参数:
        - root: Path, Stage root
        - pdb_id: str, PDB id

    输出:
        - changed: bool, 新字段已存在且有效时 False，否则原子替换后 True
    """
    # 延迟导入避免 parse.py 在运行时选择 UPGRADE 路径时形成模块循环。
    from parse import category_rows, optional_category_rows, selected_atom_rows, split_candidate_atoms

    normalized_id = pdb_id.lower()
    receptor_path = root / "parse" / normalized_id / "receptor_tokens.npz"
    old_arrays = load_npz_arrays(receptor_path, allow_pickle=False)
    if not validate_receptor_arrays(old_arrays, require_new=True):
        return False

    cif_path = root / "raw" / "rcsb_mmcif" / f"{normalized_id}.cif"
    block = gemmi.cif.read(str(cif_path)).sole_block()
    atom_rows = selected_atom_rows(category_rows(block, "_atom_site."))
    entity_types = {row["id"]: row["type"].lower() for row in category_rows(block, "_entity.")}
    struct_conns = optional_category_rows(block, "_struct_conn.")
    _het_atoms, receptor_atoms = split_candidate_atoms(atom_rows, entity_types)
    rebuilt_arrays = build_receptor_arrays(
        receptor_atoms,
        struct_conns,
        root / "raw" / "ccd_cache",
    )
    mismatch_reasons = compare_receptor_base_arrays(old_arrays, rebuilt_arrays)
    if mismatch_reasons:
        raise ReceptorBaseMismatch(";".join(mismatch_reasons))

    # 旧基础数组原样复用，只从重建结果追加新契约字段。
    upgraded_arrays = dict(old_arrays)
    for key in ("bond_index", "bond_type", "feat"):
        upgraded_arrays[key] = rebuilt_arrays[key]
    atomic_save_npz(receptor_path, **upgraded_arrays)
    return True


def upgrade_stage_c(root: Path, pdb_id: str) -> dict[str, Any]:
    """
    把一个旧 C 样本增量升级到当前完整契约并执行闭环复验。

    输入参数:
        - root: Path, Stage root
        - pdb_id: str, PDB id

    输出:
        - report: dict[str,Any], 包含:
            - `pdb_id`: str, 小写 PDB id
            - `status`: str, `upgraded` 或 `skipped`
            - `centroids_changed`: bool, 是否更新 ligand_coords
            - `receptor_changed`: bool, 是否更新 receptor_tokens
            - `descriptor_objects`: int, 检查的去重对象数
    """
    normalized_id = pdb_id.lower()
    inspection = inspect_stage_c(root, normalized_id)
    if inspection.state == CArtifactState.COMPLETE:
        return {"pdb_id": normalized_id, "status": "skipped"}
    if inspection.state != CArtifactState.UPGRADE:
        raise ValueError(
            f"Stage C core requires rebuild for {normalized_id}: {';'.join(inspection.reasons)}"
        )

    occurrences = list(inspection.occurrences)
    parse_dir = root / "parse" / normalized_id
    centroids_changed = add_ligand_centroids(parse_dir / "ligand_coords.npz", occurrences)
    descriptor_objects = materialize_occurrence_descriptors(root, occurrences, overwrite=False)
    receptor_changed = upgrade_receptor_tokens(root, normalized_id)

    final_inspection = inspect_stage_c(root, normalized_id)
    if final_inspection.state != CArtifactState.COMPLETE:
        raise ValueError(
            f"Stage C upgrade did not reach COMPLETE for {normalized_id}: "
            f"{';'.join(final_inspection.reasons)}"
        )
    return {
        "pdb_id": normalized_id,
        "status": "upgraded",
        "centroids_changed": centroids_changed,
        "receptor_changed": receptor_changed,
        "descriptor_objects": descriptor_objects,
    }
