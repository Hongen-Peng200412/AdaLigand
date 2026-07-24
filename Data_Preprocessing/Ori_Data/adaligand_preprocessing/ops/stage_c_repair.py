# 按固定结构清单审计或应用 Stage C 来源修复。
# 主要输入：source-dirty mmCIF、旧 Stage C token/occurrence 产物和迁移规则。
# 主要输出：exact/atom-name-only/blocked/failed 分类与受检 receptor-only 迁移证据。
# 关键边界：默认保留既有 ligand 坐标与 occurrence；任何 ligand-side rebuild 必须显式授权。
"""Stage C 当前 mmCIF 与既有核心产物的只读审计和 receptor-only 受检迁移。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from adaligand_preprocessing.stages.stage_c.contracts import (
    compare_receptor_base_arrays,
    load_npz_arrays,
    validate_receptor_arrays,
)
from adaligand_preprocessing.utils.io import (
    atomic_save_npz,
    file_lock,
    read_jsonl,
    safe_object_filename,
    sha256_file,
)
from adaligand_preprocessing.stages.stage_c.pipeline import StageCSourceView, build_stage_c_source_view
from adaligand_preprocessing.stages.stage_c.receptor import build_receptor_arrays, receptor_residue_key


SOURCE_AUDIT_SCHEMA_VERSION = 2
_FROZEN_INPUT_HASH_KEYS = (
    "mmcif_sha256",
    "receptor_before_sha256",
    "occurrences_sha256",
    "ligand_coords_sha256",
    "report_sha256",
)
_NON_RECEPTOR_HASH_KEYS = tuple(
    key for key in _FROZEN_INPUT_HASH_KEYS if key != "receptor_before_sha256"
)
_UNCHANGED_RECEPTOR_KEYS = (
    "coords",
    "element",
    "res_type",
    "is_backbone",
    "res_index",
    "chain_index",
)
_RECEPTOR_DERIVED_KEYS = ("bond_index", "bond_type", "feat")


class SourceRepairError(RuntimeError):
    """source audit 或 apply 不满足严格原子迁移策略时抛出的错误。"""


def audit_stage_c_source(root: Path, pdb_id: str) -> dict[str, Any]:
    """
    对一个当前 mmCIF 与既有 Stage C 核心做无落盘深比较。

    输入参数:
        - root: Path, Stage root
        - pdb_id: str, PDB id，大小写不敏感

    输出:
        - record: dict[str,Any], 包含:
            - `pdb_id`: str, 小写 PDB id
            - `classification`: str, `exact`、`atom_name_only` 或 `blocked`
            - `reasons`: list[str], 阻断或差异原因
            - `receptor_mismatch_reasons`: list[str], 七个基础数组的差异
            - `atom_name_diff_count`: int, 名称变化行数
            - `n_receptor_atoms`: int, 当前受体原子数
            - `n_occurrences`: int, 当前成功 occurrence 数
            - `mmcif_sha256`: str, 当前 raw mmCIF 哈希
            - `receptor_before_sha256`: str, 既有 receptor_tokens 哈希
            - `occurrences_sha256`: str, 既有 occurrences 哈希
            - `ligand_coords_sha256`: str, 既有 ligand_coords 哈希
            - `report_sha256`: str, 既有单样本报告哈希
            - `dependency_files`: dict[str,str], LigandObject/CCD 相对路径与哈希
            - `dependency_manifest_sha256`: str, 完整依赖闭包清单哈希
            - `schema_version`: int, 审计报告 schema 版本
    """
    normalized_id = pdb_id.lower()
    paths = _stage_c_paths(root, normalized_id)
    input_hashes = _input_hashes(paths)
    view = build_stage_c_source_view(root, normalized_id, materialize_objects=False)
    old_receptor = load_npz_arrays(paths["receptor"], allow_pickle=False)
    old_occurrences = read_jsonl(paths["occurrences"])
    old_coords = load_npz_arrays(paths["ligand_coords"], allow_pickle=False)
    old_report = json.loads(paths["report"].read_text(encoding="utf-8"))

    reasons = []
    reasons.extend(f"old_{item}" for item in validate_receptor_arrays(old_receptor, False))
    reasons.extend(f"current_{item}" for item in validate_receptor_arrays(view.receptor_base, False))
    if old_occurrences != view.occurrences:
        reasons.append("occurrences_changed")
    reasons.extend(_compare_ligand_coords(old_coords, view.ligand_coords))
    if old_report.get("failed_occurrences", []) != view.report.get("failed_occurrences", []):
        reasons.append("failed_occurrences_changed")
    receptor_mismatch = compare_receptor_base_arrays(old_receptor, view.receptor_base)
    coverage_residues = _changed_atom_name_residue_keys(
        old_receptor,
        view,
        receptor_mismatch,
    )
    receptor_derived_mismatch: list[str] = []
    receptor_derived_delta_reasons: list[str] = []
    try:
        rebuilt_full = build_receptor_arrays(
            view.receptor_atoms,
            view.struct_conns,
            root / "raw" / "ccd_cache",
            allow_ccd_fetch=False,
            required_atom_name_coverage_residues=coverage_residues,
        )
        reasons.extend(
            f"current_{item}"
            for item in validate_receptor_arrays(rebuilt_full, require_new=True)
        )
        # 旧 schema 不完整时只执行 base/ligand 门禁；派生数组由受检 apply 补齐。
        old_complete = not validate_receptor_arrays(old_receptor, require_new=True)
        if old_complete and not receptor_mismatch:
            receptor_derived_mismatch = [
                f"receptor_derived_changed:{key}"
                for key in _RECEPTOR_DERIVED_KEYS
                if not _arrays_equal(old_receptor[key], rebuilt_full[key])
            ]
            reasons.extend(receptor_derived_mismatch)
        elif (
            old_complete
            and receptor_mismatch == ["receptor_base_changed:atom_name"]
        ):
            changed_atom_indices = _changed_atom_indices(
                old_receptor,
                view.receptor_base,
            )
            receptor_derived_delta_reasons = _atom_name_derived_delta_reasons(
                old_receptor,
                rebuilt_full,
                changed_atom_indices,
            )
            reasons.extend(receptor_derived_delta_reasons)
    except Exception as exc:
        reasons.append(
            f"receptor_derived_invalid:{type(exc).__name__}:{exc}"
        )

    atom_name_reasons = _validate_current_atom_names(view.receptor_base)
    reasons.extend(atom_name_reasons)
    if not reasons and not receptor_mismatch:
        classification = "exact"
    elif not reasons and receptor_mismatch == ["receptor_base_changed:atom_name"]:
        classification = "atom_name_only"
    else:
        classification = "blocked"
        reasons.extend(receptor_mismatch)

    atom_name_diff_count = 0
    if (
        "atom_name" in old_receptor
        and old_receptor["atom_name"].shape == view.receptor_base["atom_name"].shape
    ):
        atom_name_diff_count = int(
            np.count_nonzero(old_receptor["atom_name"] != view.receptor_base["atom_name"])
        )
    dependency_files = _dependency_file_hashes(root, view, old_occurrences)
    final_input_hashes = _input_hashes(paths)
    if final_input_hashes != input_hashes:
        changed = sorted(
            key for key in input_hashes if input_hashes[key] != final_input_hashes[key]
        )
        raise SourceRepairError(
            f"source inputs changed during audit for {normalized_id}: {','.join(changed)}"
        )
    return {
        "pdb_id": normalized_id,
        "classification": classification,
        "reasons": sorted(set(reasons)),
        "receptor_mismatch_reasons": receptor_mismatch,
        "receptor_derived_mismatch_reasons": receptor_derived_mismatch,
        "receptor_derived_delta_reasons": receptor_derived_delta_reasons,
        "atom_name_diff_count": atom_name_diff_count,
        "strict_atom_name_residue_keys": [list(key) for key in sorted(coverage_residues)],
        "n_receptor_atoms": len(view.receptor_atoms),
        "n_occurrences": len(view.occurrences),
        **input_hashes,
        "dependency_files": dependency_files,
        "dependency_manifest_sha256": _dependency_manifest_sha256(dependency_files),
        "schema_version": SOURCE_AUDIT_SCHEMA_VERSION,
    }


def verify_audit_inputs_unchanged(root: Path, record: dict[str, Any]) -> None:
    """
    在任何 apply 写入前复核五个直接输入及完整依赖闭包。

    输入参数:
        - root: Path, Stage root
        - record: dict[str,Any], `audit_stage_c_source` 返回记录

    输出:
        - None: 直接输入和依赖闭包均与 audit 一致；否则抛出 SourceRepairError
    """
    paths = _stage_c_paths(root, str(record["pdb_id"]))
    current = _input_hashes(paths)
    changed = [key for key, value in current.items() if value != record.get(key)]
    dependency_files = record.get("dependency_files")
    if not isinstance(dependency_files, dict):
        raise SourceRepairError(f"missing dependency manifest for {record['pdb_id']}")
    expected_manifest_hash = _dependency_manifest_sha256(dependency_files)
    if expected_manifest_hash != record.get("dependency_manifest_sha256"):
        changed.append("dependency_manifest_sha256")
    changed.extend(_changed_dependency_files(root, dependency_files))
    if changed:
        raise SourceRepairError(
            f"source audit inputs changed for {record['pdb_id']}: "
            f"{','.join(sorted(set(changed)))}"
        )


def apply_receptor_source_repair(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    """
    对 audit 证明为 atom-name-only 的样本原子替换 receptor_tokens。

    输入参数:
        - root: Path, Stage root
        - record: dict[str,Any], 已冻结且通过全局 preflight 的 audit 记录

    输出:
        - result: dict[str,Any], 包含:
            - `pdb_id`: str, 小写 PDB id
            - `action`: str, `unchanged` 或 `repaired`
            - `receptor_before_sha256`: str, 写入前哈希
            - `receptor_after_sha256`: str, 写入后哈希
            - `atom_name_diff_count`: int, 更新名称行数
    """
    normalized_id = str(record["pdb_id"])
    classification = str(record["classification"])
    verify_audit_inputs_unchanged(root, record)
    if classification == "exact":
        return {
            "pdb_id": normalized_id,
            "action": "unchanged",
            "receptor_before_sha256": record["receptor_before_sha256"],
            "receptor_after_sha256": record["receptor_before_sha256"],
            "atom_name_diff_count": 0,
        }
    if classification != "atom_name_only":
        raise SourceRepairError(f"refusing blocked source repair for {normalized_id}")

    lock_path = (
        root / "reports" / "locks" / "stage_c_source_repair" / f"{normalized_id}.lock"
    )
    with file_lock(lock_path):
        return _apply_atom_name_repair_locked(root, record)


def _apply_atom_name_repair_locked(
    root: Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    """在单 PDB 独占 artifact lock 内完成复核、构建、CAS 与原子替换。"""
    normalized_id = str(record["pdb_id"])
    verify_audit_inputs_unchanged(root, record)
    fresh_record = audit_stage_c_source(root, normalized_id)
    changed_audit = [
        key
        for key in (
            *_FROZEN_INPUT_HASH_KEYS,
            "dependency_manifest_sha256",
            "strict_atom_name_residue_keys",
            "schema_version",
        )
        if fresh_record.get(key) != record.get(key)
    ]
    if changed_audit:
        raise SourceRepairError(
            f"fresh source audit changed for {normalized_id}: {','.join(changed_audit)}"
        )
    if fresh_record["classification"] != "atom_name_only":
        raise SourceRepairError(
            f"source classification changed for {normalized_id}: "
            f"{fresh_record['classification']}"
        )

    paths = _stage_c_paths(root, normalized_id)
    old_arrays = load_npz_arrays(paths["receptor"], allow_pickle=False)
    view = build_stage_c_source_view(root, normalized_id, materialize_objects=False)
    mismatch = compare_receptor_base_arrays(old_arrays, view.receptor_base)
    if mismatch != ["receptor_base_changed:atom_name"]:
        raise SourceRepairError(f"unsafe receptor mismatch for {normalized_id}: {mismatch}")
    rebuilt = build_receptor_arrays(
        view.receptor_atoms,
        view.struct_conns,
        root / "raw" / "ccd_cache",
        allow_ccd_fetch=False,
        required_atom_name_coverage_residues=_changed_atom_name_residue_keys(
            old_arrays,
            view,
            mismatch,
        ),
    )
    rebuilt_mismatch = compare_receptor_base_arrays(old_arrays, rebuilt)
    if rebuilt_mismatch != ["receptor_base_changed:atom_name"]:
        raise SourceRepairError(
            f"unsafe rebuilt receptor mismatch for {normalized_id}: {rebuilt_mismatch}"
        )
    old_complete = not validate_receptor_arrays(old_arrays, require_new=True)
    if old_complete:
        derived_delta_reasons = _atom_name_derived_delta_reasons(
            old_arrays,
            rebuilt,
            _changed_atom_indices(old_arrays, view.receptor_base),
        )
        if derived_delta_reasons:
            raise SourceRepairError(
                f"unsafe receptor derived delta for {normalized_id}: {derived_delta_reasons}"
            )

    repaired = dict(old_arrays)
    # 旧 schema 不完整时，当前 cache-only 重建结果负责一次性补齐三个派生数组。
    replacement_keys = (
        ("atom_name", "bond_index", "bond_type")
        if old_complete
        else ("atom_name", *_RECEPTOR_DERIVED_KEYS)
    )
    for key in replacement_keys:
        repaired[key] = rebuilt[key]
    validation = validate_receptor_arrays(repaired, require_new=True)
    if validation:
        raise SourceRepairError(f"invalid repaired receptor for {normalized_id}: {validation}")

    # commit 前的最后一次 CAS；此后只有 receptor_tokens 一个原子替换写入。
    verify_audit_inputs_unchanged(root, record)
    atomic_save_npz(paths["receptor"], **repaired)

    saved = load_npz_arrays(paths["receptor"], allow_pickle=False)
    post_validation = validate_receptor_arrays(saved, require_new=True)
    if post_validation:
        raise SourceRepairError(f"invalid saved receptor for {normalized_id}: {post_validation}")
    changed_base = [
        key
        for key in _UNCHANGED_RECEPTOR_KEYS
        if not _arrays_equal(old_arrays[key], saved[key])
    ]
    if changed_base or not _arrays_equal(saved["atom_name"], rebuilt["atom_name"]):
        raise SourceRepairError(
            f"receptor-only invariant failed for {normalized_id}: changed={changed_base}"
        )
    _verify_non_receptor_inputs(root, record)
    return {
        "pdb_id": normalized_id,
        "action": "repaired",
        "receptor_before_sha256": record["receptor_before_sha256"],
        "receptor_after_sha256": sha256_file(paths["receptor"]),
        "atom_name_diff_count": int(record["atom_name_diff_count"]),
    }


def _input_hashes(paths: dict[str, Path]) -> dict[str, str]:
    """读取 source audit 五个直接输入文件的 SHA-256。"""
    return {
        "mmcif_sha256": sha256_file(paths["mmcif"]),
        "receptor_before_sha256": sha256_file(paths["receptor"]),
        "occurrences_sha256": sha256_file(paths["occurrences"]),
        "ligand_coords_sha256": sha256_file(paths["ligand_coords"]),
        "report_sha256": sha256_file(paths["report"]),
    }


def _dependency_file_hashes(
    root: Path,
    view: StageCSourceView,
    old_occurrences: list[dict[str, Any]],
) -> dict[str, str]:
    """冻结 dry-build 使用的 LigandObject 与 CCD cache 依赖闭包。"""
    object_keys = set(view.object_keys)
    object_keys.update(str(item["object_key"]) for item in old_occurrences)
    paths = {
        root / "ligand_objects" / f"{safe_object_filename(object_key)}.npz"
        for object_key in object_keys
    }
    paths.update(
        root / "raw" / "ccd_cache" / f"{ccd_id.upper()}.pkl"
        for ccd_id in view.ccd_ids
    )
    missing = sorted(str(path) for path in paths if not path.is_file())
    if missing:
        raise SourceRepairError(f"source audit dependency missing: {missing[:10]}")
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(paths, key=lambda item: item.as_posix())
    }


def _dependency_manifest_sha256(dependency_files: dict[str, str]) -> str:
    """对排序后的相对路径→文件哈希映射计算稳定清单哈希。"""
    payload = json.dumps(
        dependency_files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _changed_dependency_files(root: Path, dependency_files: dict[str, str]) -> list[str]:
    """返回 audit 后缺失、越界或哈希变化的依赖文件诊断键。"""
    root_resolved = root.resolve()
    changed = []
    for relative, expected_hash in dependency_files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            changed.append(f"dependency_outside_root:{relative}")
            continue
        if not path.is_file():
            changed.append(f"dependency_missing:{relative}")
        elif sha256_file(path) != expected_hash:
            changed.append(f"dependency_changed:{relative}")
    return changed


def _verify_non_receptor_inputs(root: Path, record: dict[str, Any]) -> None:
    """receptor commit 后复核其余直接输入与完整依赖闭包未变化。"""
    paths = _stage_c_paths(root, str(record["pdb_id"]))
    current = _input_hashes(paths)
    changed = [key for key in _NON_RECEPTOR_HASH_KEYS if current[key] != record.get(key)]
    changed.extend(_changed_dependency_files(root, record["dependency_files"]))
    if changed:
        raise SourceRepairError(
            f"non-receptor inputs changed during repair for {record['pdb_id']}: "
            f"{','.join(sorted(set(changed)))}"
        )


def _stage_c_paths(root: Path, pdb_id: str) -> dict[str, Path]:
    """集中构造 source audit 使用的正式输入路径。"""
    parse_dir = root / "parse" / pdb_id
    return {
        "mmcif": root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif",
        "occurrences": parse_dir / "occurrences.jsonl",
        "ligand_coords": parse_dir / "ligand_coords.npz",
        "receptor": parse_dir / "receptor_tokens.npz",
        "report": root / "reports" / f"{pdb_id}.json",
    }


def _compare_ligand_coords(
    old_arrays: dict[str, np.ndarray],
    rebuilt_arrays: dict[str, np.ndarray],
) -> list[str]:
    """比较旧 ligand_coords 的核心 coords/present 与当前 mmCIF dry-build 结果。"""
    old_core_keys = {
        key for key in old_arrays if key.startswith("coords_") or key.startswith("present_")
    }
    rebuilt_core_keys = {
        key
        for key in rebuilt_arrays
        if key.startswith("coords_") or key.startswith("present_")
    }
    if old_core_keys != rebuilt_core_keys:
        return ["ligand_coords_keys_changed"]
    reasons = []
    for key in sorted(old_core_keys):
        if not _arrays_equal(old_arrays[key], rebuilt_arrays[key]):
            reasons.append(f"ligand_coords_changed:{key}")
    return reasons


def _validate_current_atom_names(arrays: dict[str, np.ndarray]) -> list[str]:
    """确保当前 S4 atom_name 在每个 receptor residue 内非空且唯一。"""
    names_by_residue: dict[tuple[int, int], set[bytes]] = {}
    for chain_index, res_index, raw_name in zip(
        arrays["chain_index"],
        arrays["res_index"],
        arrays["atom_name"],
        strict=True,
    ):
        name = bytes(raw_name).rstrip(b"\x00")
        if not name:
            return ["current_atom_name_empty"]
        key = (int(chain_index), int(res_index))
        names = names_by_residue.setdefault(key, set())
        if name in names:
            return ["current_atom_name_duplicate"]
        names.add(name)
    return []


def _changed_atom_name_residue_keys(
    old_arrays: dict[str, np.ndarray],
    view: StageCSourceView,
    receptor_mismatch: list[str],
) -> frozenset[tuple[str, str, str, str]]:
    """
    返回当前 source 中实际发生 atom-name 变化的 receptor residue 键。

    输入参数:
        - old_arrays: dict[str,np.ndarray], 迁移前 `receptor_tokens.npz` 数组
        - view: StageCSourceView, 当前冻结 mmCIF 的无落盘重建视图
        - receptor_mismatch: list[str], 七个 receptor 基础数组的逐项差异

    输出:
        - residue_keys: frozenset[tuple[str,str,str,str]], 仅包含至少一个
          `atom_name` 逐位变化的 residue；shape 不一致时返回空集并由基础数组
          mismatch 门禁阻断，不扩大严格覆盖范围
    """
    if receptor_mismatch != ["receptor_base_changed:atom_name"]:
        return frozenset()
    old_names = old_arrays.get("atom_name")
    current_names = view.receptor_base.get("atom_name")
    if (
        old_names is None
        or current_names is None
        or old_names.shape != current_names.shape
        or len(view.receptor_atoms) != len(current_names)
    ):
        return frozenset()
    changed_indices = np.flatnonzero(old_names != current_names)
    return frozenset(
        receptor_residue_key(view.receptor_atoms[int(index)])
        for index in changed_indices
    )


def _changed_atom_indices(
    old_arrays: dict[str, np.ndarray],
    current_arrays: dict[str, np.ndarray],
) -> frozenset[int]:
    """返回 `atom_name` 逐位变化的 receptor 行号集合。"""
    old_names = old_arrays.get("atom_name")
    current_names = current_arrays.get("atom_name")
    if old_names is None or current_names is None or old_names.shape != current_names.shape:
        return frozenset()
    return frozenset(int(index) for index in np.flatnonzero(old_names != current_names))


def _atom_name_derived_delta_reasons(
    old_arrays: dict[str, np.ndarray],
    rebuilt_arrays: dict[str, np.ndarray],
    changed_atom_indices: frozenset[int],
) -> list[str]:
    """
    限制 atom-name-only 迁移可改变的受体派生量范围。

    输入参数:
        - old_arrays: dict[str,np.ndarray], 迁移前完整 receptor 数组
        - rebuilt_arrays: dict[str,np.ndarray], 当前 source cache-only 重建数组
        - changed_atom_indices: frozenset[int], 实际发生 atom name 变化的行号

    输出:
        - reasons: list[str], 空列表表示 `feat` 全图不变，且所有 bond 差异至少
          接触一个改名原子；未改名子图没有被 cache/映射/实现漂移改写
    """
    reasons = []
    if not _arrays_equal(old_arrays["feat"], rebuilt_arrays["feat"]):
        reasons.append("receptor_derived_delta:feat_changed")
    old_edges = _bond_records(old_arrays)
    rebuilt_edges = _bond_records(rebuilt_arrays)
    unsafe_edges = sorted(
        edge
        for edge in old_edges.symmetric_difference(rebuilt_edges)
        if edge[0] not in changed_atom_indices and edge[1] not in changed_atom_indices
    )
    if unsafe_edges:
        reasons.append(
            "receptor_derived_delta:unchanged_subgraph_bond_changed:"
            f"{unsafe_edges[:10]}"
        )
    return reasons


def _bond_records(arrays: dict[str, np.ndarray]) -> set[tuple[int, int, int]]:
    """把 receptor COO 与 bond_type 规范为无向 `(min,max,type)` 集合。"""
    bond_index = arrays["bond_index"]
    bond_type = arrays["bond_type"]
    return {
        (min(int(left), int(right)), max(int(left), int(right)), int(kind))
        for (left, right), kind in zip(bond_index.T, bond_type, strict=True)
    }


def _arrays_equal(left: np.ndarray, right: np.ndarray) -> bool:
    """按 dtype/shape/value 比较数组，浮点 NaN 只在同位置时视为相等。"""
    if left.dtype != right.dtype or left.shape != right.shape:
        return False
    if np.issubdtype(left.dtype, np.floating):
        return bool(np.array_equal(left, right, equal_nan=True))
    return bool(np.array_equal(left, right))
