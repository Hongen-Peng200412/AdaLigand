# 读取并应用运行级结构排除清单。
# 主要输入：reports/runs/{run_id}/exclusions.jsonl 中经用户授权的逐样本决策。
# 主要输出：Stage E/F 可直接写入完整状态清单的 known_failed 字段与 manifest 身份。
# 关键边界：不改 pair_list、不删除样本；排除只在声明的 run/stage 生效，并始终进入分母和审计日志。
"""加载并验证 run-scoped 样本排除清单。"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from adaligand_preprocessing.artifacts.failures import KnownFailureCode
from adaligand_preprocessing.utils.io import read_jsonl, sha256_file


RUN_EXCLUSIONS_FILENAME = "exclusions.jsonl"
STAGE_F_EXCLUSIONS_FILENAME = "exclusions.stage_f.jsonl"
RUN_EXCLUSION_SCHEMA_VERSION = 1
ALLOWED_EXCLUSION_STAGES = frozenset({"stage_e", "stage_f"})
EXCLUSION_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "pdb_id",
        "run_id",
        "stages",
        "reason",
        "detail",
        "authorization",
        "decision_scope",
        "downstream_policy",
        "evidence",
    }
)


def load_run_exclusions(
    root: Path,
    run_id: str,
    stage: str,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """
    加载当前 run 对指定 stage 的显式排除项。
    输入参数:
        - root: Path，数据处理根目录
        - run_id: str，正式或独立 smoke/repair run 标识
        - stage: str，当前只允许 ``stage_e`` 或 ``stage_f``

    输出:
        - exclusions: dict[pdb_id, record]，仅含声明覆盖当前 stage 的条目
        - manifest_sha256: str | None，清单存在时为文件 SHA-256，否则为 None

    说明:
        清单不存在表示没有排除策略。存在时必须是普通文件、逐条唯一、run-only，并明确训练/推理排除；
        任何 schema、授权或证据缺失均 fail-fast，不能把临时文本名单静默当作科学状态。
    """
    if stage not in ALLOWED_EXCLUSION_STAGES:
        raise ValueError(f"run exclusions do not support stage: {stage}")
    run_dir = root / "reports" / "runs" / run_id
    manifest_path = run_dir / RUN_EXCLUSIONS_FILENAME
    stage_f_path = run_dir / STAGE_F_EXCLUSIONS_FILENAME
    if not manifest_path.exists():
        if manifest_path.is_symlink():
            raise ValueError(f"run exclusion manifest must be a regular file: {manifest_path}")
        if stage == "stage_f" and (stage_f_path.exists() or stage_f_path.is_symlink()):
            raise ValueError("Stage F exclusion view requires the shared base manifest")
        return {}, None
    base_by_pdb_id = _load_manifest_records(manifest_path, run_id=run_id)
    selected = {
        pdb_id: record
        for pdb_id, record in base_by_pdb_id.items()
        if stage in record["stages"]
    }

    # Stage E 已完成后新增 F-only 人工超时，不能改写共享 manifest 的 SHA 并使 E provenance 失效。
    # 可选的 Stage F 视图必须完整包含且逐字段保留共享清单中的所有 F 决策，只允许追加 F-only 行。
    if stage == "stage_f" and (stage_f_path.exists() or stage_f_path.is_symlink()):
        stage_f_by_pdb_id = _load_manifest_records(stage_f_path, run_id=run_id)
        for pdb_id, record in stage_f_by_pdb_id.items():
            if "stage_f" not in record["stages"]:
                raise ValueError(f"Stage F exclusion view contains a non-F record: {pdb_id}")
        for pdb_id, record in selected.items():
            if stage_f_by_pdb_id.get(pdb_id) != record:
                raise ValueError(f"Stage F exclusion view changed or omitted base record: {pdb_id}")
        for pdb_id in set(stage_f_by_pdb_id).difference(selected):
            if pdb_id in base_by_pdb_id:
                raise ValueError(f"Stage F supplemental exclusion shadows a base record: {pdb_id}")
            if stage_f_by_pdb_id[pdb_id]["stages"] != ["stage_f"]:
                raise ValueError(f"Stage F supplemental exclusion must be F-only: {pdb_id}")
        return stage_f_by_pdb_id, sha256_file(stage_f_path)

    return selected, sha256_file(manifest_path)


def exclusion_status_fields(
    record: dict[str, Any],
    *,
    manifest_sha256: str,
) -> dict[str, Any]:
    """
    构造写入 Stage E/F 状态行的稳定排除字段。
    输入参数:
        - record: dict，已通过 ``load_run_exclusions`` 验证的单条记录
        - manifest_sha256: str，完整 run-scoped 清单的内容身份

    输出:
        - fields: dict，包含 known reason、授权、证据与下游策略
    """
    return {
        "reason": KnownFailureCode.RUN_POLICY_EXCLUDED.value,
        "error": str(record["detail"]),
        "exclusion_reason": str(record["reason"]),
        "exclusion_run_id": str(record["run_id"]),
        "exclusion_authorization": str(record["authorization"]),
        "exclusion_decision_scope": str(record["decision_scope"]),
        "exclusion_downstream_policy": str(record["downstream_policy"]),
        "exclusion_evidence": dict(record["evidence"]),
        "exclusion_manifest_sha256": manifest_sha256,
    }


def _validate_exclusion_record(record: dict[str, Any], *, index: int, run_id: str) -> None:
    """验证一条排除决策的完整性，不提供隐式默认值。"""
    if not isinstance(record, dict):
        raise ValueError(f"run exclusion row {index} must be an object")
    actual_fields = set(record)
    if actual_fields != EXCLUSION_RECORD_FIELDS:
        raise ValueError(
            f"run exclusion row {index} fields mismatch: "
            f"missing={sorted(EXCLUSION_RECORD_FIELDS.difference(actual_fields))}, "
            f"extra={sorted(actual_fields.difference(EXCLUSION_RECORD_FIELDS))}"
        )
    if record.get("schema_version") != RUN_EXCLUSION_SCHEMA_VERSION:
        raise ValueError(f"run exclusion row {index} has unsupported schema_version")
    if record.get("run_id") != run_id:
        raise ValueError(f"run exclusion row {index} does not belong to run_id {run_id}")
    pdb_id = str(record.get("pdb_id", "")).lower()
    if not re.fullmatch(r"[0-9a-z]{4}", pdb_id):
        raise ValueError(f"run exclusion row {index} has invalid pdb_id")
    stages = record.get("stages")
    if (
        not isinstance(stages, list)
        or not stages
        or len(stages) != len(set(stages))
        or not set(stages).issubset(ALLOWED_EXCLUSION_STAGES)
    ):
        raise ValueError(f"run exclusion row {index} has invalid stages")
    for field in ("reason", "detail", "authorization"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError(f"run exclusion row {index} has empty {field}")
    if record.get("decision_scope") != "current_run_only":
        raise ValueError(f"run exclusion row {index} must use current_run_only")
    if record.get("downstream_policy") != "exclude_from_training_and_inference":
        raise ValueError(f"run exclusion row {index} has invalid downstream_policy")
    evidence = record.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError(f"run exclusion row {index} must contain evidence")


def _load_manifest_records(path: Path, *, run_id: str) -> dict[str, dict[str, Any]]:
    """
    读取并验证一份完整 exclusion manifest。

    输入参数:
        - path: Path，待验证的共享清单或 Stage F 专用视图
        - run_id: str，清单必须归属的正式 run

    输出:
        - records: dict[pdb_id, record]，按小写 PDB ID 唯一索引的原始记录
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"run exclusion manifest must be a regular file: {path}")
    records = read_jsonl(path)
    if not records:
        raise ValueError("run exclusion manifest must not be empty")
    by_pdb_id: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        _validate_exclusion_record(record, index=index, run_id=run_id)
        pdb_id = str(record["pdb_id"]).lower()
        if pdb_id in by_pdb_id:
            raise ValueError(f"duplicate run exclusion pdb_id: {pdb_id}")
        by_pdb_id[pdb_id] = record
    return by_pdb_id
