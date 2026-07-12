"""Stage G：run-scoped release gate、质量分布分析和显式配置过滤。"""

from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from io_utils import read_jsonl, sha256_file, sha256_manifest, write_jsonl
from qc import cc_value_errors
from reports import StageStatus, stage_report_path, stage_result, write_report, write_stage_results


FILTER_CONFIG_SCHEMA_VERSION = 1
UPSTREAM_STAGES = ("stage_d", "stage_e", "stage_f")
_DISTRIBUTION_FIELDS = (
    "q_score",
    "q_score_median",
    "q_score_min",
    "pocket_q_score",
    "pocket_q_score_median",
    "pocket_q_score_min",
    "pocket_n_atoms",
    "map_resolution",
    "cc_contour",
    "cc_contour_about_mean",
    "cc_all",
    "cc_all_about_mean",
)
_QUANTILES = (0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0)
_REQUIRED_QUALITY_FIELDS = {
    *_DISTRIBUTION_FIELDS,
    "n_valid",
    "n_present",
    "pocket_n_valid",
    "pocket_status",
    "pocket_radius_angstrom",
    "contour_status",
}


def load_stage_statuses(
    root: Path,
    run_id: str,
    stage: str,
    expected_pdb_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    """
    读取一个 stage 的全部 array 分片，要求每个 A 样本恰好一个互斥终态。

    缺分片、重复样本、silent missing、额外样本、错误 stage/status 都直接阻塞 release。
    """
    stage_dir = root / "reports" / "runs" / run_id / stage
    paths = sorted(stage_dir.glob("status.part_*_of_*.jsonl"))
    if not paths:
        raise RuntimeError(f"no run-scoped status files for {run_id}/{stage}")
    records_by_pdb: dict[str, dict[str, Any]] = {}
    for path in paths:
        for record in read_jsonl(path):
            pdb_id = str(record.get("pdb_id", "")).lower()
            if record.get("stage") != stage:
                raise RuntimeError(f"wrong stage in {path}: {record.get('stage')!r}")
            try:
                StageStatus(str(record.get("status")))
            except ValueError as exc:
                raise RuntimeError(f"invalid status in {path}: {record.get('status')!r}") from exc
            if not pdb_id or pdb_id in records_by_pdb:
                raise RuntimeError(f"duplicate/empty PDB status for {stage}: {pdb_id!r}")
            records_by_pdb[pdb_id] = record
    actual = set(records_by_pdb)
    if actual != expected_pdb_ids:
        missing = sorted(expected_pdb_ids.difference(actual))
        extra = sorted(actual.difference(expected_pdb_ids))
        raise RuntimeError(
            f"silent/extra samples in {stage}: missing={missing[:20]}, extra={extra[:20]}"
        )
    unknown = [
        record
        for record in records_by_pdb.values()
        if record["status"] == StageStatus.UNKNOWN_FAILED.value
    ]
    if unknown:
        examples = [
            {"pdb_id": item["pdb_id"], "reason": item.get("reason"), "error": item.get("error")}
            for item in unknown[:20]
        ]
        raise RuntimeError(f"{stage} has {len(unknown)} unknown failures: {examples}")
    return records_by_pdb, paths


def load_filter_config(path: Path) -> dict[str, Any]:
    """读取并验证 Stage G 显式 JSON 配置；不提供隐式科学阈值。"""
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("filter config must be a JSON object")
    if config.get("schema_version") != FILTER_CONFIG_SCHEMA_VERSION:
        raise ValueError(f"filter config schema_version must be {FILTER_CONFIG_SCHEMA_VERSION}")
    if "q_score_min" not in config:
        raise ValueError("filter config must explicitly set q_score_min")
    q_score_min = float(config["q_score_min"])
    if not np.isfinite(q_score_min) or q_score_min < -1 or q_score_min > 1:
        raise ValueError("q_score_min must be finite in [-1,1]")
    resolution_max = config.get("resolution_max")
    if resolution_max is not None:
        resolution_max = float(resolution_max)
        if not np.isfinite(resolution_max) or resolution_max <= 0:
            raise ValueError("resolution_max must be null or a positive finite number")
    resolution_policy = config.get("resolution_policy")
    if resolution_policy not in {"exclude", "flag_only"}:
        raise ValueError("resolution_policy must be explicitly 'exclude' or 'flag_only'")
    if config.get("comparison") != "inclusive":
        raise ValueError("comparison must explicitly be 'inclusive' (>= Q and <= resolution)")
    return {
        "schema_version": FILTER_CONFIG_SCHEMA_VERSION,
        "q_score_min": q_score_min,
        "resolution_max": resolution_max,
        "resolution_policy": resolution_policy,
        "comparison": "inclusive",
    }


def apply_filter_config(
    quality_records: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """按显式含等号边界应用硬 Q 门和配置化 resolution exclude/flag-only。"""
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    flagged: list[dict[str, Any]] = []
    for record in sorted(
        quality_records,
        key=lambda item: (str(item["pdb_id"]), int(item["candidate_id"])),
    ):
        q_score = float(record["q_score"])
        resolution = float(record["map_resolution"])
        if not np.isfinite(q_score) or not np.isfinite(resolution):
            raise RuntimeError(f"non-finite Stage F quality record: {record}")
        reasons: list[str] = []
        flags: list[str] = []
        if q_score < config["q_score_min"]:
            reasons.append("q_score_below_min")
        resolution_max = config["resolution_max"]
        if resolution_max is not None and resolution > resolution_max:
            if config["resolution_policy"] == "exclude":
                reasons.append("resolution_above_max")
            else:
                flags.append("resolution_above_max")
        key = {"pdb_id": str(record["pdb_id"]).lower(), "candidate_id": int(record["candidate_id"])}
        if reasons:
            excluded.append({**key, "reasons": reasons})
        else:
            kept.append(key)
            if flags:
                flagged.append({**key, "flags": flags})
    return kept, excluded, flagged


def run_stage_g(
    root: Path,
    run_id: str,
    *,
    mode: str,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """
    执行质量分布分析或正式过滤。

    ``mode=analyze`` 只写 run-scoped 分布和 ``candidates.pending.jsonl``，绝不写正式
    ``keep_list.jsonl``。``mode=filter`` 必须提供显式配置，且所有 D/E/F unknown/silent
    missing 已清零后才原子写正式 keep list。
    """
    if mode not in {"analyze", "filter"}:
        raise ValueError("mode must be analyze or filter")
    pair_path = root / "raw" / "pair_list.jsonl"
    pairs = read_jsonl(pair_path)
    pdb_ids = [str(item["pdb_id"]).lower() for item in pairs]
    if len(pdb_ids) != len(set(pdb_ids)):
        raise RuntimeError("pair_list contains duplicate PDB ids")
    expected = set(pdb_ids)
    status_by_stage: dict[str, dict[str, dict[str, Any]]] = {}
    manifest_paths = [pair_path]
    for stage in UPSTREAM_STAGES:
        statuses, paths = load_stage_statuses(root, run_id, stage, expected)
        status_by_stage[stage] = statuses
        manifest_paths.extend(paths)

    known_failures: dict[str, list[str]] = {}
    eligible_pdb_ids: list[str] = []
    for pdb_id in sorted(expected):
        reasons = []
        for stage in UPSTREAM_STAGES:
            record = status_by_stage[stage][pdb_id]
            if record["status"] == StageStatus.KNOWN_FAILED.value:
                reasons.append(f"{stage}:{record.get('reason', 'known_failed')}")
        if reasons:
            known_failures[pdb_id] = reasons
        else:
            eligible_pdb_ids.append(pdb_id)

    quality_records: list[dict[str, Any]] = []
    occurrence_types: dict[tuple[str, int], str] = {}
    for pdb_id in eligible_pdb_ids:
        quality_path = root / "quality" / f"{pdb_id}.jsonl"
        occurrence_path = root / "parse" / pdb_id / "occurrences.jsonl"
        provenance_path = root / "quality" / f"{pdb_id}.provenance.json"
        for required_path in (quality_path, occurrence_path, provenance_path):
            if not required_path.exists():
                raise RuntimeError(f"upstream status succeeded but artifact is missing: {required_path}")
        manifest_paths.extend((quality_path, occurrence_path, provenance_path))
        pdb_quality = read_jsonl(quality_path)
        occurrences = read_jsonl(occurrence_path)
        occurrence_ids = {int(item["candidate_id"]) for item in occurrences}
        quality_ids = {int(item["candidate_id"]) for item in pdb_quality}
        if occurrence_ids != quality_ids or len(quality_ids) != len(pdb_quality):
            raise RuntimeError(f"quality/occurrence candidate mismatch for {pdb_id}")
        for occurrence in occurrences:
            occurrence_types[(pdb_id, int(occurrence["candidate_id"]))] = str(occurrence["type_tag"])
        for quality_record in pdb_quality:
            if str(quality_record.get("pdb_id", "")).lower() != pdb_id:
                raise RuntimeError(f"quality PDB id mismatch in {quality_path}")
            missing_fields = sorted(_REQUIRED_QUALITY_FIELDS.difference(quality_record))
            if missing_fields:
                raise RuntimeError(f"quality fields are missing in {quality_path}: {missing_fields}")
            if int(quality_record["n_valid"]) != int(quality_record["n_present"]):
                raise RuntimeError(f"ligand Q counts disagree in {quality_path}")
            pocket_count = int(quality_record["pocket_n_atoms"])
            if pocket_count < 0 or int(quality_record["pocket_n_valid"]) != pocket_count:
                raise RuntimeError(f"pocket Q counts disagree in {quality_path}")
            if pocket_count == 0:
                if quality_record["pocket_status"] != "no_receptor_atoms_within_radius" or any(
                    quality_record[field] is not None
                    for field in ("pocket_q_score", "pocket_q_score_median", "pocket_q_score_min")
                ):
                    raise RuntimeError(f"empty pocket semantics disagree in {quality_path}")
            elif quality_record["pocket_status"] != "ok":
                raise RuntimeError(f"non-empty pocket status disagrees in {quality_path}")
            pocket_radius = float(quality_record["pocket_radius_angstrom"])
            if not np.isfinite(pocket_radius) or pocket_radius <= 0:
                raise RuntimeError(f"pocket radius is invalid in {quality_path}")
            cc_values = {key: quality_record[key] for key in _DISTRIBUTION_FIELDS if key.startswith("cc_")}
            cc_errors = cc_value_errors(
                cc_values,
                contour_available=quality_record["contour_status"] == "ok",
            )
            if cc_errors:
                raise RuntimeError(f"CC fields are invalid in {quality_path}: {cc_errors}")
        quality_records.extend(pdb_quality)

    input_manifest = sha256_manifest(manifest_paths, base=root)
    analysis_dir = root / "reports" / "runs" / run_id / "stage_g_analysis"
    pending_records = [
        {
            "pdb_id": str(record["pdb_id"]).lower(),
            "candidate_id": int(record["candidate_id"]),
            "type_tag": occurrence_types[(str(record["pdb_id"]).lower(), int(record["candidate_id"]))],
            "pocket_status": record["pocket_status"],
            **{field: record.get(field) for field in _DISTRIBUTION_FIELDS},
        }
        for record in sorted(
            quality_records,
            key=lambda item: (str(item["pdb_id"]), int(item["candidate_id"])),
        )
    ]
    distribution = {
        "run_id": run_id,
        "input_manifest_sha256": input_manifest,
        "n_pair_pdb": len(pdb_ids),
        "n_eligible_pdb": len(eligible_pdb_ids),
        "n_known_failed_pdb": len(known_failures),
        "n_candidate_occurrences": len(quality_records),
        "known_failure_reasons": dict(
            sorted(Counter(reason for reasons in known_failures.values() for reason in reasons).items())
        ),
        "type_tag_counts": dict(sorted(Counter(item["type_tag"] for item in pending_records).items())),
        "pocket_status_counts": dict(
            sorted(Counter(item["pocket_status"] for item in pending_records).items())
        ),
        "fields": {
            field: _numeric_distribution([record.get(field) for record in quality_records])
            for field in _DISTRIBUTION_FIELDS
        },
        "threshold_status": "pending_user_approved_config",
    }
    write_jsonl(analysis_dir / "candidates.pending.jsonl", pending_records)
    write_report(analysis_dir / "quality_distribution.json", distribution)
    if mode == "analyze":
        stage_records = []
        for pdb_id in sorted(expected):
            if pdb_id in known_failures:
                stage_records.append(
                    stage_result(
                        pdb_id,
                        "stage_g_analysis",
                        StageStatus.KNOWN_FAILED,
                        reason=";".join(known_failures[pdb_id]),
                    )
                )
            else:
                stage_records.append(stage_result(pdb_id, "stage_g_analysis", StageStatus.SUCCESS))
        write_stage_results(
            stage_report_path(root, run_id, "stage_g_analysis", 0, 1),
            stage_records,
        )
        return {
            "status": "analysis_complete_threshold_pending",
            "distribution": str((analysis_dir / "quality_distribution.json").relative_to(root)),
            "n_candidates": len(pending_records),
        }

    if config_path is None:
        raise ValueError("mode=filter requires --config")
    config = load_filter_config(config_path)
    kept, excluded, flagged = apply_filter_config(quality_records, config)
    filter_dir = root / "reports" / "runs" / run_id / "stage_g"
    config_sha256 = sha256_file(config_path)
    filter_manifest = hashlib.sha256(
        f"{input_manifest}\n{config_sha256}\n".encode("ascii")
    ).hexdigest()
    summary = {
        "run_id": run_id,
        "input_manifest_sha256": input_manifest,
        "filter_manifest_sha256": filter_manifest,
        "config_path": str(config_path),
        "config_sha256": config_sha256,
        "config": config,
        "n_kept": len(kept),
        "n_excluded_by_threshold": len(excluded),
        "n_flagged_but_kept": len(flagged),
        "n_known_failed_pdb": len(known_failures),
        "exclusion_reason_counts": dict(
            sorted(Counter(reason for item in excluded for reason in item["reasons"]).items())
        ),
    }
    write_jsonl(filter_dir / "excluded.jsonl", excluded)
    write_jsonl(filter_dir / "flagged.jsonl", flagged)
    write_report(filter_dir / "summary.json", summary)
    # keep_list 是最终 completion marker；只在所有检查/报告成功后原子提升。
    write_jsonl(root / "keep_list.jsonl", kept)
    stage_records = []
    for pdb_id in sorted(expected):
        if pdb_id in known_failures:
            stage_records.append(
                stage_result(
                    pdb_id,
                    "stage_g",
                    StageStatus.KNOWN_FAILED,
                    reason=";".join(known_failures[pdb_id]),
                )
            )
        else:
            stage_records.append(stage_result(pdb_id, "stage_g", StageStatus.SUCCESS))
    write_stage_results(stage_report_path(root, run_id, "stage_g", 0, 1), stage_records)
    return {"status": "success", "n_kept": len(kept), "n_excluded": len(excluded)}


def _numeric_distribution(values: list[Any]) -> dict[str, Any]:
    """汇总 JSON number|null 字段的有限值计数和固定 quantile。"""
    finite = []
    n_null = 0
    for value in values:
        if value is None:
            n_null += 1
            continue
        number = float(value)
        if not np.isfinite(number):
            raise RuntimeError(f"non-finite quality value in distribution: {value!r}")
        finite.append(number)
    array = np.asarray(finite, dtype=np.float64)
    quantiles = (
        {f"{quantile:g}": float(np.quantile(array, quantile)) for quantile in _QUANTILES}
        if len(array)
        else {}
    )
    return {"n_finite": len(finite), "n_null": n_null, "quantiles": quantiles}
