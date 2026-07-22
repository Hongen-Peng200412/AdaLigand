# 按指定阶段校验状态、排除和受控失败的发布门禁。
# 实际逻辑：调用 code/contracts.py、failures.py、reports.py 汇总阶段终态。
# 输入/输出：run-scoped 状态、产物索引与期约 → gate summary、release marker、退出码。
# 关键边界：known 可按契约排除；unknown、重复、静默缺失和 schema 漂移不得放行下游。
"""通用 run-scoped stage gate：允许 known failure，阻塞 unknown/重复/静默缺失。"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path


from adaligand_preprocessing.execution.controlled_failures import CONTROLLED_FAILURE_WAIVER_STAGE, load_stage_status_view
from adaligand_preprocessing.execution.exclusions import (
    ALLOWED_EXCLUSION_STAGES,
    exclusion_status_fields,
    load_run_exclusions,
)
from adaligand_preprocessing.artifacts.failures import KnownFailureCode
from adaligand_preprocessing.utils.io import read_jsonl
from adaligand_preprocessing.execution.parallel import read_pdb_id_filter
from adaligand_preprocessing.artifacts.reports import StageStatus, resolve_run_id, write_report


def main() -> None:
    """检查逗号分隔 stage 的目标 PDB 全覆盖，并写 gate summary。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--stages", required=True)
    parser.add_argument("--gate_name", required=True)
    parser.add_argument("--pdb_ids_file", type=Path)
    parser.add_argument("--controlled_failure_waiver", type=Path)
    parser.add_argument("--controlled_failure_waiver_sha256")
    parser.add_argument(
        "--require_success",
        action="store_true",
        help="smoke gate 专用：把任何 known_failed 也视为 gate 失败",
    )
    args = parser.parse_args()
    run_id = resolve_run_id(args.run_id)
    stages = [item.strip() for item in args.stages.split(",") if item.strip()]
    if not stages:
        raise ValueError("--stages cannot be empty")
    if (args.controlled_failure_waiver is None) != (
        args.controlled_failure_waiver_sha256 is None
    ):
        raise ValueError("waiver path and SHA-256 must be provided together")
    if args.controlled_failure_waiver is not None:
        if args.require_success:
            raise RuntimeError("strict smoke gate does not accept controlled-failure waiver")
        if stages != [CONTROLLED_FAILURE_WAIVER_STAGE]:
            raise RuntimeError("controlled-failure waiver gate must target only stage_f")
    pairs = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    requested = read_pdb_id_filter(args.pdb_ids_file)
    expected = {
        str(record["pdb_id"]).lower()
        for record in pairs
        if requested is None or str(record["pdb_id"]).lower() in requested
    }
    if requested is not None and expected != requested:
        raise RuntimeError(f"PDB filter mismatch: missing={sorted(requested.difference(expected))}")
    status_counts: dict[str, dict[str, int]] = {}
    known_reason_counts: Counter[str] = Counter()
    exclusion_manifest_sha256: dict[str, str] = {}
    raw_unknown_counts: dict[str, int] = {}
    waived_controlled_failures: dict[str, list[dict[str, str | None]]] = {}
    controlled_failure_waiver: dict[str, object] | None = None
    for stage in stages:
        view = load_stage_status_view(
            args.root,
            run_id,
            stage,
            expected,
            controlled_failure_waiver_path=(
                args.controlled_failure_waiver
                if stage == CONTROLLED_FAILURE_WAIVER_STAGE
                else None
            ),
            controlled_failure_waiver_sha256=(
                args.controlled_failure_waiver_sha256
                if stage == CONTROLLED_FAILURE_WAIVER_STAGE
                else None
            ),
        )
        statuses = view.records_by_pdb
        status_counts[stage] = dict(sorted(Counter(item["status"] for item in statuses.values()).items()))
        raw_unknown_counts[stage] = len(view.raw_unknown_by_pdb)
        waived_controlled_failures[stage] = [
            {
                "pdb_id": pdb_id,
                "raw_reason": statuses[pdb_id].get("reason"),
                "classification": record["classification"],
            }
            for pdb_id, record in sorted(view.waived_by_pdb.items())
        ]
        if view.waiver is not None:
            controlled_failure_waiver = {
                "path": view.waiver.path.relative_to(args.root.resolve()).as_posix(),
                "sha256": view.waiver.sha256,
                "authorized_cap": view.waiver.authorized_cap,
                "n_waived": len(view.waived_by_pdb),
                "cumulative_controlled_failure_count": (
                    view.waiver.cumulative_controlled_failure_count
                ),
            }
        for record in statuses.values():
            if record["status"] == StageStatus.KNOWN_FAILED.value:
                known_reason_counts[f"{stage}:{record.get('reason', 'known_failed')}"] += 1
        if stage in ALLOWED_EXCLUSION_STAGES:
            exclusions, manifest_sha256 = load_run_exclusions(args.root, run_id, stage)
            expected_exclusion_ids = set(exclusions).intersection(expected)
            actual_exclusion_ids = {
                pdb_id
                for pdb_id, record in statuses.items()
                if record.get("reason") == KnownFailureCode.RUN_POLICY_EXCLUDED.value
            }
            if actual_exclusion_ids != expected_exclusion_ids:
                raise RuntimeError(
                    f"{stage} run exclusion status mismatch: "
                    f"missing={sorted(expected_exclusion_ids.difference(actual_exclusion_ids))}, "
                    f"unexpected={sorted(actual_exclusion_ids.difference(expected_exclusion_ids))}"
                )
            if manifest_sha256 is not None:
                exclusion_manifest_sha256[stage] = manifest_sha256
            for pdb_id in sorted(expected_exclusion_ids):
                record = statuses[pdb_id]
                exclusion = exclusions[pdb_id]
                if manifest_sha256 is None:
                    raise RuntimeError(f"{stage} exclusion manifest identity is missing")
                expected_fields = exclusion_status_fields(
                    exclusion,
                    manifest_sha256=manifest_sha256,
                )
                if record.get("status") != StageStatus.KNOWN_FAILED.value or any(
                    record.get(field) != value
                    for field, value in expected_fields.items()
                ):
                    raise RuntimeError(f"{stage} exclusion provenance mismatch for {pdb_id}")
    if args.require_success and known_reason_counts:
        raise RuntimeError(
            "strict smoke gate rejects known failures: "
            f"{dict(sorted(known_reason_counts.items()))}"
        )
    write_report(
        args.root / "reports" / "runs" / run_id / args.gate_name / "summary.json",
        {
            "status": "success",
            "run_id": run_id,
            "gate_name": args.gate_name,
            "stages": stages,
            "n_expected_pdb": len(expected),
            "status_counts": status_counts,
            "known_failure_reasons": dict(sorted(known_reason_counts.items())),
            "raw_unknown_counts": raw_unknown_counts,
            "waived_controlled_failures": waived_controlled_failures,
            "controlled_failure_waiver": controlled_failure_waiver,
            "exclusion_manifest_sha256": exclusion_manifest_sha256,
            "policy": (
                "success/skipped only; known/unknown/duplicate/silent missing blocks"
                if args.require_success
                else (
                    "known_failed and exact manifest-bound waived unknown continue; "
                    "unlisted unknown/duplicate/silent missing blocks"
                    if controlled_failure_waiver is not None
                    else "known_failed continues explicitly; unknown/duplicate/silent missing blocks"
                )
            ),
        },
    )


if __name__ == "__main__":
    main()
