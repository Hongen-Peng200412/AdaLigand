# 学习导航：功能分区=run-scoped 运维迁移；生命周期=仅服务 2026-07-17/18 正式 Stage F 收口。
# 主要输入：已闭合的六条 signal-11 决策、补算 v2 八条真实 unknown 及只读状态证据。
# 主要输出：保留历史 v1 六条不变，正式 Stage F 视图增至 19 条，补算 v2 增至 14 条。
# 关键边界：不写质量三件套、不改共享 Stage E manifest、不伪造 timeout、signal 11 或 success。
"""为当前正式 run 原子登记祖传 Chimera 外部工具边界的 run-only 排除项。"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from exclusions import exclusion_status_fields, load_run_exclusions
from filtering import load_stage_statuses
from io_utils import sha256_file
from reports import StageStatus
from stage_f_process_audit import PROCESS_AUDIT_SCHEMA_VERSION, implementation_identity


SIGNAL11_IDS = ("9bw7", "9c1k", "9dgr", "9fkb", "9mxv", "9nw3")
PHASE2_SIGNAL11_IDS = ("7ju4", "7kzm", "7z8f", "7z8i", "8olb")
PHASE2_MOLMAP_TIMEOUT_DETAILS = (
    ("7yiu", "missing_ccd_template_fetch"),
    ("8e45", "missing_ccd_template_fetch"),
    ("8j07", "large_grid_and_model"),
)
PHASE2_ATTEMPT_IDS = (
    ("7ju4", "c985822080fc4ee7b0ea327c6933cfe1"),
    ("7kzm", "7414ace7c8d74fc9914c5a67640459a4"),
    ("7yiu", "281a1291f85d4afca8c5ab1cd434cf0b"),
    ("7z8f", "31613197d46b47eb93e0d68df00b5e4d"),
    ("7z8i", "15451e1c48b54576ae78cd2c969937fe"),
    ("8e45", "245e6281398f4ed6821530797fa7b148"),
    ("8j07", "d533b855bdf94aed88b8fbe346c787a2"),
    ("8olb", "87213d95168a435480851df85fe81190"),
)
PHASE2_MOLMAP_TIMEOUT_IDS = tuple(
    pdb_id for pdb_id, _detail in PHASE2_MOLMAP_TIMEOUT_DETAILS
)
PHASE2_IDS = (*PHASE2_SIGNAL11_IDS, *PHASE2_MOLMAP_TIMEOUT_IDS)
PHASE2_ALL_EXCLUSION_IDS = (*SIGNAL11_IDS, *PHASE2_IDS)


@dataclass(frozen=True)
class Signal11TransitionContract:
    """冻结一次 run-only 迁移所需的 run 身份与只读证据身份。"""

    formal_run_id: str
    supplement_run_ids: tuple[str, str]
    authorization: str
    exclusion_cap: int
    expected_base_sha256: str
    expected_formal_before_sha256: str
    status_before_relative_path: str
    expected_status_before_sha256: str
    n_jobs1_acceptance_relative_path: str
    expected_n_jobs1_acceptance_sha256: str
    all_only_acceptance_relative_path: str
    expected_all_only_acceptance_sha256: str
    supplement_ids_relative_paths: tuple[str, str]
    expected_supplement_ids_sha256: tuple[str, str]
    expected_supplement_counts: tuple[int, int]


@dataclass(frozen=True)
class ExtendedExclusionTransitionContract:
    """冻结第二阶段迁移所需的旧 manifest、补算状态及用户授权身份。"""

    phase1_contract: Signal11TransitionContract
    authorization: str
    exclusion_cap: int
    expected_formal_before_sha256: str
    expected_supplement_v1_sha256: str
    expected_supplement_v2_before_sha256: str
    status_before_relative_path: str
    expected_status_before_sha256: str
    timeout_details: tuple[tuple[str, str], ...]
    evidence_identities: tuple[tuple[str, int, str, str, str, str, str], ...]


DEFAULT_CONTRACT = Signal11TransitionContract(
    formal_run_id="adaligand_ag_20260711T154658",
    supplement_run_ids=(
        "adaligand_ag_20260711T154658_fsupp96_v1",
        "adaligand_ag_20260711T154658_fsupp96_v2",
    ),
    authorization=(
        "user_explicit_2026-07-17_exclude_six_chimera_full_grid_cc_signal11_"
        "and_raise_current_run_cap_to_30"
    ),
    exclusion_cap=30,
    expected_base_sha256=(
        "380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f"
    ),
    expected_formal_before_sha256=(
        "3b10abb5cc69bca0689cb89cdb6e0bde21620504c11479edcbfb51c83ec68ee8"
    ),
    status_before_relative_path=(
        "reports/runs/adaligand_ag_20260711T154658_fsupp96_v1/"
        "stage_f/status.part_0000_of_0001.jsonl"
    ),
    expected_status_before_sha256=(
        "7938aea615c19029265587d556622c8f2d6aea5acff59a94baa85813698496b6"
    ),
    n_jobs1_acceptance_relative_path=(
        "reports/runs/adaligand_ag_20260711T154658/"
        "stage_f_cc_sigsegv_shadow_20260717_v1/shadow_acceptance.json"
    ),
    expected_n_jobs1_acceptance_sha256=(
        "67cc083c94efbb72648db07e5d62ec8fee195bbf3a3dc59eecb5dcbf0ed868b2"
    ),
    all_only_acceptance_relative_path=(
        "reports/runs/adaligand_ag_20260711T154658/"
        "stage_f_cc_all_fresh_process_shadow_20260717_v2/acceptance.json"
    ),
    expected_all_only_acceptance_sha256=(
        "e0bef08c6a4da804d0173ccc920e3e58316912ee4fea303bf9045ad4f50032e9"
    ),
    supplement_ids_relative_paths=(
        (
            "reports/runs/adaligand_ag_20260711T154658/"
            "stage_f_tail_supplement_20260715_v1/pdb_ids.txt"
        ),
        (
            "reports/runs/adaligand_ag_20260711T154658_fsupp96_v2/"
            "stage_f_tail_supplement_20260716_v2/pdb_ids.txt"
        ),
    ),
    expected_supplement_ids_sha256=(
        "acacde79c2a5a8727949cdc0a986930aa8404419a8edaabfb264f4f05dacea80",
        "7f427993c3a2e8c2e147e8c40b9b83423b932e2275066ccd010efbbf79617c6c",
    ),
    expected_supplement_counts=(2990, 5984),
)


DEFAULT_EXTENDED_CONTRACT = ExtendedExclusionTransitionContract(
    phase1_contract=DEFAULT_CONTRACT,
    authorization=(
        "user_explicit_2026-07-18_current_run_exclusion_cap_100_with_"
        "evidence_bound_tool_boundary_application_2026-07-18"
    ),
    exclusion_cap=100,
    expected_formal_before_sha256=(
        "10c5d923779645a6eeeeb5d277722e6f487593557c095cfcdef641553613c8ac"
    ),
    expected_supplement_v1_sha256=(
        "6f3a0a880e6e38768e1e096b2bcb776087372be56987b4a930c88306b5527f35"
    ),
    expected_supplement_v2_before_sha256=(
        "43da55a71885730458cab546f6eb96e38722b726445eaf3613873f23e74b7d40"
    ),
    status_before_relative_path=(
        "reports/runs/adaligand_ag_20260711T154658_fsupp96_v2/"
        "stage_f/status.part_0000_of_0001.jsonl"
    ),
    expected_status_before_sha256=(
        "3231dfe56403444c37ac962835c7ced2b97b13eb49cde5a934ad74b2330bb23e"
    ),
    timeout_details=PHASE2_MOLMAP_TIMEOUT_DETAILS,
    evidence_identities=(
        (
            "7ju4",
            963,
            "c8d7cfbfaf16ae574a520b817c288a9eb42ad9f2877c4c11c7c5337275b21a8a",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7ju4/"
            "c985822080fc4ee7b0ea327c6933cfe1/correlation.stdout.log",
            "cb1d7bba2bc94ec736109cc414dd38544a4e548687095bc95520790482105a38",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7ju4/"
            "c985822080fc4ee7b0ea327c6933cfe1/correlation.stderr.log",
            "274f3df6a8474ad9f9b4b6abebb7650c8af199a895e50b4e059a9a950c9888e2",
        ),
        (
            "7kzm",
            1015,
            "2859c510812a90363e2633931902a56e4d3ca893a2f2ddb3882601dc166ad01b",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7kzm/"
            "7414ace7c8d74fc9914c5a67640459a4/correlation.stdout.log",
            "5ef70512574334bf2b9c5f9467d126e397182e93fafe681e3549974f30604314",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7kzm/"
            "7414ace7c8d74fc9914c5a67640459a4/correlation.stderr.log",
            "274f3df6a8474ad9f9b4b6abebb7650c8af199a895e50b4e059a9a950c9888e2",
        ),
        (
            "7yiu",
            1893,
            "a9757cefed19bf42d2a864ea9e465041cdeab989baaa81a0f27642578f828c2d",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7yiu/"
            "281a1291f85d4afca8c5ab1cd434cf0b/molmap.stdout.log",
            "19d2c8a4683916e82d108b128836b00a652c4bc2998da9e41ad0907f6881538d",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7yiu/"
            "281a1291f85d4afca8c5ab1cd434cf0b/molmap.stderr.log",
            "eaf7d8b9a6a1122e3be1d27874184e45c157e9d4fe6c503c24fb50aa64901df4",
        ),
        (
            "7z8f",
            1942,
            "9b9e0ef47fc9effb1450bb371e724f04f96c403476f96b7a7dc4f45ba4ea4881",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7z8f/"
            "31613197d46b47eb93e0d68df00b5e4d/correlation.stdout.log",
            "79ebaa70bbcdfe1d923362e5ddfb2f0a32561a26e3e6066b12e132ef03114f70",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7z8f/"
            "31613197d46b47eb93e0d68df00b5e4d/correlation.stderr.log",
            "274f3df6a8474ad9f9b4b6abebb7650c8af199a895e50b4e059a9a950c9888e2",
        ),
        (
            "7z8i",
            1945,
            "b7ab6eb121bdd3a74eb7744fa4bbd55d4e533d330be7aed4b88f355b37eaf22f",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7z8i/"
            "15451e1c48b54576ae78cd2c969937fe/correlation.stdout.log",
            "b57edc1f003f53901ee0ca2e8698e5111f4127d44616062a287fc5ec37f48c8a",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/7z8i/"
            "15451e1c48b54576ae78cd2c969937fe/correlation.stderr.log",
            "274f3df6a8474ad9f9b4b6abebb7650c8af199a895e50b4e059a9a950c9888e2",
        ),
        (
            "8e45",
            2280,
            "1dfad492e557fcdc919eaa24754583b6167d83fd90ccba55b82b3f719c893cde",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/8e45/"
            "245e6281398f4ed6821530797fa7b148/molmap.stdout.log",
            "29e3195495ee3a025dab6fea42d98c64c3e2a28d52115c4a732dd5dbe570fe6c",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/8e45/"
            "245e6281398f4ed6821530797fa7b148/molmap.stderr.log",
            "703b436feffa7c5c311a811dd0af923efad7f496ac605e3ee6820ce8fe5fd608",
        ),
        (
            "8j07",
            2714,
            "4435e139d4ec6668c5899425a42735be0451c4bba7851eabb273e3aa0bfadcc3",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/8j07/"
            "d533b855bdf94aed88b8fbe346c787a2/molmap.stdout.log",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/8j07/"
            "d533b855bdf94aed88b8fbe346c787a2/molmap.stderr.log",
            "d3998c3a41ef07322ec80e198e6628042ad796a56e72e318892f4a09b05d56b5",
        ),
        (
            "8olb",
            2883,
            "902c5645fade90b429cb172de3561d8f8e556ed2a53e9aedf0b8e2fa5627edd2",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/8olb/"
            "87213d95168a435480851df85fe81190/correlation.stdout.log",
            "8b7c09705f1689e74dbf26d25124e00145dba778e224587da4bf25cc4918eca4",
            "scratch/adaligand_ag_20260711T154658_fsupp96_v2/stage_f/8olb/"
            "87213d95168a435480851df85fe81190/correlation.stderr.log",
            "274f3df6a8474ad9f9b4b6abebb7650c8af199a895e50b4e059a9a950c9888e2",
        ),
    ),
)


SchedulerStateQuery = Callable[[int], str]


@dataclass(frozen=True)
class _LiveReplacement:
    """描述一个已冻结顺序、允许旧态和目标字节的 live manifest 替换。"""

    path: Path
    payload: bytes
    allowed_before_sha256: str | None
    allow_absent: bool


def apply_or_validate_signal11_transition(
    root: Path,
    *,
    mode: str,
    contract: Signal11TransitionContract = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    """
    应用或复核本轮 signal-11 排除迁移。

    ``apply`` 只在全部旧身份与 0/3 三件套前置条件通过后原子写入；``validate``
    要求迁移账本和三个 run 的 manifest 已逐字节闭合。两种模式都不会创建或修改
    ``quality``、``quality_atoms`` 下的任何文件。
    """
    if mode not in {"apply", "validate"}:
        raise ValueError(f"unsupported signal-11 transition mode: {mode}")
    root = root.resolve()
    formal_run_dir = root / "reports" / "runs" / contract.formal_run_id
    evidence_dir = formal_run_dir / "stage_f_signal11_exclusion_20260717_v1"
    base_manifest = formal_run_dir / "exclusions.jsonl"
    formal_manifest = formal_run_dir / "exclusions.stage_f.jsonl"
    status_source = root / contract.status_before_relative_path
    n_jobs1_acceptance = root / contract.n_jobs1_acceptance_relative_path
    all_only_acceptance = root / contract.all_only_acceptance_relative_path
    status_evidence = evidence_dir / "supplement_v1_status.before.jsonl"
    formal_before_evidence = evidence_dir / "formal_stage_f.before.jsonl"

    _require_sha(base_manifest, contract.expected_base_sha256, "formal base manifest")
    _require_sha(
        n_jobs1_acceptance,
        contract.expected_n_jobs1_acceptance_sha256,
        "n_jobs=1 shadow acceptance",
    )
    _require_sha(
        all_only_acceptance,
        contract.expected_all_only_acceptance_sha256,
        "fresh ALL-only acceptance",
    )
    before_bytes = _resolve_before_bytes(
        formal_manifest,
        formal_before_evidence,
        expected_sha256=contract.expected_formal_before_sha256,
    )
    status_before_bytes = _resolve_before_bytes(
        status_source,
        status_evidence,
        expected_sha256=contract.expected_status_before_sha256,
    )
    _validate_signal11_status(status_before_bytes)
    trio_snapshot = _require_zero_public_trios(root)

    base_records = _records_by_id(base_manifest.read_bytes())
    before_records = _records_by_id(before_bytes)
    if set(base_records) != {"8ckb", "8glv", "9e5c", "9fqr"}:
        raise RuntimeError(f"formal base exclusion IDs drifted: {sorted(base_records)}")
    if set(before_records) != {*base_records, "6kgx"}:
        raise RuntimeError(
            f"formal Stage F pre-transition IDs drifted: {sorted(before_records)}"
        )
    for pdb_id, record in base_records.items():
        if before_records.get(pdb_id) != record:
            raise RuntimeError(f"formal Stage F view changed base record: {pdb_id}")

    formal_records = dict(before_records)
    for pdb_id in SIGNAL11_IDS:
        formal_records[pdb_id] = _signal11_record(
            pdb_id,
            run_id=contract.formal_run_id,
            root=root,
            contract=contract,
        )
    if len(formal_records) != 11 or len(formal_records) > contract.exclusion_cap:
        raise RuntimeError("formal Stage F exclusion count violates the authorized run cap")

    formal_after_bytes = _encode_jsonl(formal_records)
    supplement_payloads = {
        run_id: _encode_jsonl(
            {
                pdb_id: _signal11_record(
                    pdb_id,
                    run_id=run_id,
                    root=root,
                    contract=contract,
                )
                for pdb_id in SIGNAL11_IDS
            }
        )
        for run_id in contract.supplement_run_ids
    }
    formal_after_path = evidence_dir / "formal_stage_f.after.jsonl"
    supplement_after_paths = {
        run_id: evidence_dir / f"{run_id}.exclusions.after.jsonl"
        for run_id in contract.supplement_run_ids
    }
    formal_sha = _sha256_bytes(formal_after_bytes)
    supplement_sha = {
        run_id: _sha256_bytes(payload)
        for run_id, payload in supplement_payloads.items()
    }
    summary = {
        "schema_version": 1,
        "status": "success",
        "event": "stage_f_signal11_run_policy_exclusion_transition",
        "decision_scope": "current_run_only",
        "scientific_contract_changed": False,
        "formal_run_id": contract.formal_run_id,
        "supplement_run_ids": list(contract.supplement_run_ids),
        "authorization": contract.authorization,
        "authorized_exclusion_cap": contract.exclusion_cap,
        "base_manifest_path": str(base_manifest),
        "base_manifest_sha256": contract.expected_base_sha256,
        "formal_before_sha256": contract.expected_formal_before_sha256,
        "supplement_plan_exclusion_snapshot_sha256": (
            contract.expected_formal_before_sha256
        ),
        "supplement_plan_overlay": (
            "the five-entry Stage F SHA remains immutable historical plan evidence; "
            "the six signal-11 decisions are a post-plan run-scoped overlay"
        ),
        "formal_after_sha256": formal_sha,
        "formal_exclusion_ids": sorted(formal_records),
        "added_exclusion_ids": list(SIGNAL11_IDS),
        "supplement_manifest_sha256": supplement_sha,
        "status_before_sha256": contract.expected_status_before_sha256,
        "n_jobs1_acceptance_sha256": contract.expected_n_jobs1_acceptance_sha256,
        "all_only_acceptance_sha256": contract.expected_all_only_acceptance_sha256,
        "public_quality_trios": trio_snapshot,
        "policy": (
            "write real known_failed:run_policy_excluded with exclusion_reason="
            "chimera_full_grid_cc_signal11; never create placeholder quality artifacts"
        ),
    }
    summary_bytes = _encode_json(summary)
    summary_path = evidence_dir / "summary.json"
    replacement_plan_path = evidence_dir / "apply_journal.plan.json"
    supplement_run_dirs = {
        run_id: root / "reports" / "runs" / run_id
        for run_id in contract.supplement_run_ids
    }
    replacements = [
        _LiveReplacement(
            path=formal_manifest,
            payload=formal_after_bytes,
            allowed_before_sha256=contract.expected_formal_before_sha256,
            allow_absent=False,
        ),
        *(
            _LiveReplacement(
                path=supplement_run_dirs[run_id] / "exclusions.jsonl",
                payload=supplement_payloads[run_id],
                allowed_before_sha256=None,
                allow_absent=True,
            )
            for run_id in contract.supplement_run_ids
        ),
    ]
    replacement_plan_bytes = _encode_json(
        {
            "schema_version": 1,
            "status": "prepared",
            "event": "stage_f_signal11_manifest_replacement_plan",
            "replay_policy": (
                "all targets are preflighted and all replacement temp files are fsynced "
                "before the first os.replace; interrupted commits replay idempotently"
            ),
            "replacement_order": [
                {
                    "sequence": index,
                    "path": str(replacement.path),
                    "target_sha256": _sha256_bytes(replacement.payload),
                    "allow_absent": replacement.allow_absent,
                    "allowed_before_sha256": replacement.allowed_before_sha256,
                }
                for index, replacement in enumerate(replacements, start=1)
            ],
        }
    )
    evidence_payloads = [
        (formal_before_evidence, before_bytes, "formal before evidence"),
        (status_evidence, status_before_bytes, "status before evidence"),
        (formal_after_path, formal_after_bytes, "formal after evidence"),
        *(
            (
                supplement_after_paths[run_id],
                supplement_payloads[run_id],
                f"{run_id} after evidence",
            )
            for run_id in contract.supplement_run_ids
        ),
        (replacement_plan_path, replacement_plan_bytes, "replacement plan evidence"),
        (summary_path, summary_bytes, "transition summary"),
    ]

    if mode == "apply":
        _preflight_signal11_apply(
            replacements,
            supplement_run_dirs=supplement_run_dirs,
            evidence_payloads=evidence_payloads,
        )
        # 所有 evidence 目标与 live 目标已一起只读预检；先冻结可重放证据，再准备全部 live temp。
        for path, payload, _label in evidence_payloads[:-1]:
            _write_immutable(path, payload)
        prepared = _prepare_live_replacement_temps(replacements)
        try:
            _commit_live_replacements(replacements, prepared)
        finally:
            for temporary in prepared.values():
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    else:
        for path, payload, label in evidence_payloads:
            _require_bytes(path, payload, label)
        _require_bytes(formal_manifest, formal_after_bytes, "formal Stage F manifest")
        for run_id, payload in supplement_payloads.items():
            _require_bytes(
                supplement_run_dirs[run_id] / "exclusions.jsonl",
                payload,
                f"{run_id} exclusion manifest",
            )

    formal_loaded, observed_formal_sha = load_run_exclusions(
        root, contract.formal_run_id, "stage_f"
    )
    if (
        set(formal_loaded) != set(formal_records)
        or observed_formal_sha != formal_sha
    ):
        raise RuntimeError("formal Stage F loader does not expose exactly 11 exclusions")
    for run_id, expected_sha in supplement_sha.items():
        loaded, observed_sha = load_run_exclusions(root, run_id, "stage_f")
        if set(loaded) != set(SIGNAL11_IDS) or observed_sha != expected_sha:
            raise RuntimeError(f"supplement exclusion loader mismatch: {run_id}")

    if mode == "apply":
        _write_immutable(summary_path, summary_bytes)
    return summary


def apply_or_validate_extended_exclusion_transition(
    root: Path,
    *,
    mode: str,
    contract: ExtendedExclusionTransitionContract = DEFAULT_EXTENDED_CONTRACT,
) -> dict[str, Any]:
    """
    应用或复核第二阶段八例 run-only 排除迁移。

    本迁移只替换正式 Stage F 视图与补算 v2 manifest。补算 v1 六条 manifest
    仅按旧 SHA-256 做只读门，绝不进入写入 journal。
    """
    if mode not in {"apply", "validate"}:
        raise ValueError(f"unsupported extended exclusion transition mode: {mode}")
    root = root.resolve()
    phase1 = contract.phase1_contract
    formal_run_dir = root / "reports" / "runs" / phase1.formal_run_id
    evidence_dir = formal_run_dir / "stage_f_extended_exclusion_20260718_v2"
    base_manifest = formal_run_dir / "exclusions.jsonl"
    formal_manifest = formal_run_dir / "exclusions.stage_f.jsonl"
    supplement_v1_dir = root / "reports" / "runs" / phase1.supplement_run_ids[0]
    supplement_v2_dir = root / "reports" / "runs" / phase1.supplement_run_ids[1]
    supplement_v1_manifest = supplement_v1_dir / "exclusions.jsonl"
    supplement_v2_manifest = supplement_v2_dir / "exclusions.jsonl"
    status_source = root / contract.status_before_relative_path

    if contract.exclusion_cap < 19 or contract.exclusion_cap < phase1.exclusion_cap:
        raise RuntimeError("extended transition exclusion cap is below the frozen counts")
    if dict(contract.timeout_details) != dict(PHASE2_MOLMAP_TIMEOUT_DETAILS):
        raise RuntimeError("extended transition timeout details drifted")
    _require_sha(base_manifest, phase1.expected_base_sha256, "formal base manifest")
    _require_sha(
        supplement_v1_manifest,
        contract.expected_supplement_v1_sha256,
        "immutable supplement v1 manifest",
    )
    supplement_v1_overlay = supplement_v1_dir / "exclusions.stage_f.jsonl"
    if supplement_v1_overlay.exists() or supplement_v1_overlay.is_symlink():
        raise RuntimeError("supplement v1 must not introduce a Stage F overlay")

    formal_before_path = evidence_dir / "formal_stage_f.before_11.jsonl"
    supplement_v1_evidence = evidence_dir / "supplement_v1.immutable_6.jsonl"
    supplement_v2_before_path = evidence_dir / "supplement_v2.before_6.jsonl"
    status_before_path = evidence_dir / "supplement_v2_status.before.jsonl"
    formal_before_bytes = _resolve_before_bytes(
        formal_manifest,
        formal_before_path,
        expected_sha256=contract.expected_formal_before_sha256,
    )
    supplement_v1_bytes = supplement_v1_manifest.read_bytes()
    supplement_v2_before_bytes = _resolve_before_bytes(
        supplement_v2_manifest,
        supplement_v2_before_path,
        expected_sha256=contract.expected_supplement_v2_before_sha256,
    )
    status_before_bytes = _resolve_before_bytes(
        status_source,
        status_before_path,
        expected_sha256=contract.expected_status_before_sha256,
    )
    phase2_statuses = _validate_phase2_status(status_before_bytes)
    phase2_evidence, phase2_log_payloads = _validate_phase2_evidence_identities(
        root,
        status_before_bytes,
        contract,
        evidence_dir=evidence_dir,
    )
    trio_snapshot = _require_zero_public_trios_for(root, PHASE2_IDS)

    base_records = _records_by_id(base_manifest.read_bytes())
    formal_before_records = _records_by_id(formal_before_bytes)
    supplement_v1_records = _records_by_id(supplement_v1_bytes)
    supplement_v2_before_records = _records_by_id(supplement_v2_before_bytes)
    _validate_closed_phase1_records(
        base_records=base_records,
        formal_records=formal_before_records,
        supplement_v1_records=supplement_v1_records,
        supplement_v2_records=supplement_v2_before_records,
        phase1=phase1,
    )

    formal_after_records = dict(formal_before_records)
    supplement_v2_after_records = dict(supplement_v2_before_records)
    for pdb_id in PHASE2_IDS:
        formal_after_records[pdb_id] = _extended_exclusion_record(
            pdb_id,
            run_id=phase1.formal_run_id,
            status_record=phase2_statuses[pdb_id],
            evidence_identity=phase2_evidence[pdb_id],
            root=root,
            contract=contract,
        )
        supplement_v2_after_records[pdb_id] = _extended_exclusion_record(
            pdb_id,
            run_id=phase1.supplement_run_ids[1],
            status_record=phase2_statuses[pdb_id],
            evidence_identity=phase2_evidence[pdb_id],
            root=root,
            contract=contract,
        )
    if (
        len(formal_after_records) != 19
        or len(formal_after_records) > contract.exclusion_cap
        or len(supplement_v2_after_records) != 14
    ):
        raise RuntimeError("extended exclusion counts violate the frozen contract")

    formal_after_bytes = _encode_jsonl(formal_after_records)
    supplement_v2_after_bytes = _encode_jsonl(supplement_v2_after_records)
    formal_after_path = evidence_dir / "formal_stage_f.after_19.jsonl"
    supplement_v2_after_path = evidence_dir / "supplement_v2.after_14.jsonl"
    replacements = [
        _LiveReplacement(
            path=formal_manifest,
            payload=formal_after_bytes,
            allowed_before_sha256=contract.expected_formal_before_sha256,
            allow_absent=False,
        ),
        _LiveReplacement(
            path=supplement_v2_manifest,
            payload=supplement_v2_after_bytes,
            allowed_before_sha256=contract.expected_supplement_v2_before_sha256,
            allow_absent=False,
        ),
    ]
    replacement_plan_path = evidence_dir / "apply_journal.plan.json"
    replacement_plan_bytes = _encode_json(
        {
            "schema_version": 2,
            "status": "prepared",
            "event": "stage_f_extended_exclusion_manifest_replacement_plan",
            "immutable_live_paths": [
                {
                    "path": str(base_manifest),
                    "sha256": phase1.expected_base_sha256,
                },
                {
                    "path": str(supplement_v1_manifest),
                    "sha256": contract.expected_supplement_v1_sha256,
                },
            ],
            "replacement_order": [
                {
                    "sequence": index,
                    "path": str(replacement.path),
                    "allowed_before_sha256": replacement.allowed_before_sha256,
                    "target_sha256": _sha256_bytes(replacement.payload),
                }
                for index, replacement in enumerate(replacements, start=1)
            ],
            "replay_policy": (
                "all target temps are fsynced before the first os.replace; either old or "
                "target bytes are accepted during deterministic partial replay"
            ),
        }
    )
    summary = {
        "schema_version": 2,
        "status": "success",
        "event": "stage_f_extended_run_policy_exclusion_transition",
        "decision_scope": "current_run_only",
        "scientific_contract_changed": False,
        "formal_run_id": phase1.formal_run_id,
        "supplement_v1_run_id": phase1.supplement_run_ids[0],
        "supplement_v2_run_id": phase1.supplement_run_ids[1],
        "authorization": contract.authorization,
        "authorized_exclusion_cap": contract.exclusion_cap,
        "base_manifest_sha256": phase1.expected_base_sha256,
        "formal_before_sha256": contract.expected_formal_before_sha256,
        "formal_after_sha256": _sha256_bytes(formal_after_bytes),
        "supplement_v1_immutable_sha256": contract.expected_supplement_v1_sha256,
        "supplement_v2_before_sha256": contract.expected_supplement_v2_before_sha256,
        "supplement_v2_after_sha256": _sha256_bytes(supplement_v2_after_bytes),
        "status_before_sha256": contract.expected_status_before_sha256,
        "added_signal11_ids": list(PHASE2_SIGNAL11_IDS),
        "added_molmap_timeout_ids": list(PHASE2_MOLMAP_TIMEOUT_IDS),
        "formal_exclusion_ids": sorted(formal_after_records),
        "supplement_v2_exclusion_ids": sorted(supplement_v2_after_records),
        "public_quality_trios": trio_snapshot,
        "policy": (
            "write real known_failed:run_policy_excluded statuses on rerun; never create "
            "placeholder quality artifacts and never alter the four-CC algorithm"
        ),
    }
    summary_path = evidence_dir / "summary.json"
    summary_bytes = _encode_json(summary)
    evidence_payloads = [
        (formal_before_path, formal_before_bytes, "formal 11-entry before evidence"),
        (supplement_v1_evidence, supplement_v1_bytes, "supplement v1 immutable evidence"),
        (
            supplement_v2_before_path,
            supplement_v2_before_bytes,
            "supplement v2 six-entry before evidence",
        ),
        (status_before_path, status_before_bytes, "supplement v2 status evidence"),
        *phase2_log_payloads,
        (formal_after_path, formal_after_bytes, "formal 19-entry after evidence"),
        (
            supplement_v2_after_path,
            supplement_v2_after_bytes,
            "supplement v2 14-entry after evidence",
        ),
        (replacement_plan_path, replacement_plan_bytes, "extended replacement plan"),
        (summary_path, summary_bytes, "extended transition summary"),
    ]

    if mode == "apply":
        _preflight_signal11_apply(
            replacements,
            supplement_run_dirs={phase1.supplement_run_ids[1]: supplement_v2_dir},
            evidence_payloads=evidence_payloads,
        )
        for path, payload, _label in evidence_payloads[:-1]:
            _write_immutable(path, payload)
        _require_sha(base_manifest, phase1.expected_base_sha256, "formal base manifest")
        _require_sha(
            supplement_v1_manifest,
            contract.expected_supplement_v1_sha256,
            "immutable supplement v1 manifest",
        )
        prepared = _prepare_live_replacement_temps(replacements)
        try:
            _require_sha(
                base_manifest,
                phase1.expected_base_sha256,
                "formal base manifest",
            )
            _require_sha(
                supplement_v1_manifest,
                contract.expected_supplement_v1_sha256,
                "immutable supplement v1 manifest",
            )
            _commit_live_replacements(replacements, prepared)
        finally:
            for temporary in prepared.values():
                temporary.unlink(missing_ok=True)
        _write_immutable(summary_path, summary_bytes)
    else:
        for path, payload, label in evidence_payloads:
            _require_bytes(path, payload, label)
        _require_bytes(formal_manifest, formal_after_bytes, "formal Stage F manifest")
        _require_bytes(
            supplement_v2_manifest,
            supplement_v2_after_bytes,
            "supplement v2 exclusion manifest",
        )

    _require_bytes(
        supplement_v1_manifest,
        supplement_v1_bytes,
        "immutable supplement v1 manifest",
    )
    _require_sha(base_manifest, phase1.expected_base_sha256, "formal base manifest")
    _require_sha(
        supplement_v1_manifest,
        contract.expected_supplement_v1_sha256,
        "immutable supplement v1 manifest",
    )
    formal_loaded, formal_sha = load_run_exclusions(root, phase1.formal_run_id, "stage_f")
    v2_loaded, v2_sha = load_run_exclusions(root, phase1.supplement_run_ids[1], "stage_f")
    if set(formal_loaded) != set(formal_after_records) or formal_sha != summary["formal_after_sha256"]:
        raise RuntimeError("formal Stage F loader does not expose exactly 19 exclusions")
    if set(v2_loaded) != set(supplement_v2_after_records) or v2_sha != summary["supplement_v2_after_sha256"]:
        raise RuntimeError("supplement v2 loader does not expose exactly 14 exclusions")
    return summary


def validate_formal_signal11_readiness(
    root: Path,
    *,
    expected_supplement_run_cmd_sha256: str,
    contract: Signal11TransitionContract = DEFAULT_CONTRACT,
    lock_root: Path = Path("/home/penghongen"),
    scheduler_state_query: SchedulerStateQuery | None = None,
) -> dict[str, Any]:
    """
    在正式 Stage F 启动前验证补算 v1 已闭合，且 v2 已闭合或仍由受信进程运行。

    输入参数:
        - root: Path, 服务器数据根目录
        - expected_supplement_run_cmd_sha256: str, 当前 job 318350 ``run_cmd`` 的受信 SHA-256
        - contract: Signal11TransitionContract, 本次 run-only 决策的冻结身份
        - lock_root: Path, Slurm 四锁与 ``run_cmd`` 所在目录
        - scheduler_state_query: Callable[[int], str] | None, 测试可注入的 Slurm 状态查询器

    输出:
        - summary: dict[str, Any], 包含:
            - ``status``: str, 固定为 ``success``
            - ``supplement_v1``: dict, v1 全覆盖状态与 release 身份
            - ``supplement_v2``: dict, v2 完整 release 或受信活动进程身份
    """
    if re.fullmatch(r"[0-9a-f]{64}", expected_supplement_run_cmd_sha256) is None:
        raise ValueError("expected supplement run_cmd SHA-256 must be lowercase hex")
    apply_or_validate_signal11_transition(root, mode="validate", contract=contract)
    v1 = _validate_supplement_release(root, contract, supplement_index=0)

    v2_run_id = contract.supplement_run_ids[1]
    v2_release = (
        root
        / "reports"
        / "runs"
        / v2_run_id
        / "f_supplement_release"
        / "summary.json"
    )
    if v2_release.exists() or v2_release.is_symlink():
        v2 = _validate_supplement_release(root, contract, supplement_index=1)
        v2["readiness_mode"] = "release_complete"
    else:
        child_pgid_path = lock_root / "child_pgid_318350"
        if child_pgid_path.is_symlink() or not child_pgid_path.is_file():
            raise RuntimeError("v2 is not released and child_pgid_318350 is not regular")
        child_pgid_text = child_pgid_path.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[1-9][0-9]*", child_pgid_text) is None:
            raise RuntimeError("v2 child PGID must be one positive integer")
        run_cmd_path = lock_root / "run_cmd_318350.sh"
        _require_sha(
            run_cmd_path,
            expected_supplement_run_cmd_sha256,
            "active supplement run_cmd",
        )
        query = scheduler_state_query or _query_slurm_job_state
        scheduler_state = query(318350)
        if scheduler_state != "RUNNING":
            raise RuntimeError(
                f"v2 supplement is not a trusted active RUNNING job: {scheduler_state!r}"
            )
        v2 = {
            "status": "success",
            "run_id": v2_run_id,
            "readiness_mode": "trusted_active_process",
            "job_id": 318350,
            "scheduler_state": scheduler_state,
            "child_pgid": int(child_pgid_text),
            "run_cmd_path": str(run_cmd_path),
            "run_cmd_sha256": expected_supplement_run_cmd_sha256,
        }
    return {
        "schema_version": 1,
        "status": "success",
        "event": "formal_stage_f_signal11_readiness",
        "formal_run_id": contract.formal_run_id,
        "supplement_v1": v1,
        "supplement_v2": v2,
    }


def validate_formal_extended_readiness(
    root: Path,
    *,
    contract: ExtendedExclusionTransitionContract = DEFAULT_EXTENDED_CONTRACT,
) -> dict[str, Any]:
    """要求 v1 旧六条与 v2 新十四条均完成真实 release 后才放行正式 F。"""
    apply_or_validate_extended_exclusion_transition(
        root,
        mode="validate",
        contract=contract,
    )
    phase1 = contract.phase1_contract
    v1 = _validate_supplement_release(
        root,
        phase1,
        supplement_index=0,
        expected_exclusion_ids=SIGNAL11_IDS,
    )
    v2 = _validate_supplement_release(
        root,
        phase1,
        supplement_index=1,
        expected_exclusion_ids=PHASE2_ALL_EXCLUSION_IDS,
    )
    return {
        "schema_version": 2,
        "status": "success",
        "event": "formal_stage_f_extended_exclusion_readiness",
        "formal_run_id": phase1.formal_run_id,
        "supplement_v1": v1,
        "supplement_v2": v2,
    }


def validate_signal11_apply_preconditions(
    process_audit_path: Path,
    *,
    expected_process_audit_sha256: str,
    lock_root: Path,
    now: datetime | None = None,
    max_age_seconds: float = 900.0,
) -> dict[str, Any]:
    """
    绑定 apply 前的跨节点零进程快照与两组精确 try/after 锁。

    输入参数:
        - process_audit_path: Path, canonical process-audit ``capture`` 生成的 JSON
        - expected_process_audit_sha256: str, 本次快照的受信 SHA-256
        - lock_root: Path, job 316116/318350 精确锁所在目录
        - now: datetime | None, 测试注入的当前 UTC 时间；生产环境省略
        - max_age_seconds: float, 快照允许的最大年龄

    输出:
        - summary: dict[str, Any], 包含审计身份、年龄和当前锁快照
    """
    if re.fullmatch(r"[0-9a-f]{64}", expected_process_audit_sha256) is None:
        raise ValueError("expected process-audit SHA-256 must be lowercase hex")
    _require_sha(process_audit_path, expected_process_audit_sha256, "process audit")
    audit = json.loads(process_audit_path.read_text(encoding="utf-8"))
    if not isinstance(audit, dict):
        raise RuntimeError("process audit must be one JSON object")
    expected_jobs = [316116, 318350]
    expected_nodes = {"316116": "cnode04", "318350": "cnode01"}
    process_audit_script = Path(__file__).resolve().with_name("stage_f_process_audit.py")
    expected_implementation = implementation_identity(process_audit_script)
    if (
        audit.get("schema_version") != PROCESS_AUDIT_SCHEMA_VERSION
        or audit.get("status") != "success"
        or audit.get("job_ids") != expected_jobs
        or audit.get("job_nodes") != expected_nodes
        or str(audit.get("controller_node", "")).split(".", 1)[0].lower() != "master"
        or any(
            audit.get(field) != value
            for field, value in expected_implementation.items()
        )
    ):
        raise RuntimeError("process audit identity/status does not match the frozen jobs")
    for field in (
        "active_stage_f_processes",
        "active_inventory_or_cleanup_processes",
        "active_opaque_stdin_python_processes",
        "scan_error_count",
        "scheduler_exit_code",
    ):
        if type(audit.get(field)) is not int or audit[field] != 0:
            raise RuntimeError(f"process audit is not quiescent: {field}={audit.get(field)!r}")
    if audit.get("blocking_controller_opaque_processes") != []:
        raise RuntimeError("process audit contains a blocking controller opaque process")
    job_checks = audit.get("job_checks")
    if not isinstance(job_checks, dict) or set(job_checks) != {"316116", "318350"}:
        raise RuntimeError("process audit must contain the two exact job checks")
    controller_check = audit.get("controller_check")
    checks = [controller_check, *job_checks.values()]
    if len(checks) != 3 or any(not isinstance(check, dict) for check in checks):
        raise RuntimeError("process audit must contain controller plus two job checks")
    for check in checks:
        if (
            check.get("probe_exit_code") != 0
            or check.get("scan_error_count") != 0
            or check.get("probe_stderr") != ""
            or check.get("active_stage_f_processes") != 0
            or check.get("active_inventory_or_cleanup_processes") != 0
        ):
            raise RuntimeError(f"process audit contains a non-quiescent probe: {check}")
    if (
        controller_check.get("node") != "master"
        or controller_check.get("reported_node") != "master"
        or controller_check.get("job_id") is not None
    ):
        raise RuntimeError("process audit controller probe identity drifted")
    for job_id, node in expected_nodes.items():
        check = job_checks[job_id]
        if (
            check.get("job_id") != int(job_id)
            or check.get("node") != node
            or check.get("reported_node") != node
        ):
            raise RuntimeError(f"process audit job probe identity drifted: {job_id}")
    captured_at_raw = audit.get("captured_at")
    if not isinstance(captured_at_raw, str):
        raise RuntimeError("process audit lacks captured_at")
    try:
        captured_at = datetime.fromisoformat(captured_at_raw)
    except ValueError as exc:
        raise RuntimeError("process audit captured_at is not ISO-8601") from exc
    if captured_at.tzinfo is None:
        raise RuntimeError("process audit captured_at must be timezone-aware")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_seconds = (current - captured_at.astimezone(timezone.utc)).total_seconds()
    if age_seconds < -30 or age_seconds > max_age_seconds:
        raise RuntimeError(f"process audit freshness window failed: age={age_seconds:.3f}s")

    lock_snapshot: dict[str, dict[str, str]] = {}
    for job_id in expected_jobs:
        lock_snapshot[str(job_id)] = {}
        for kind in ("after", "try"):
            path = lock_root / f"{kind}_lock_{job_id}"
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"required {kind} lock is not regular: {path}")
            lock_snapshot[str(job_id)][kind] = "regular"
        for kind in ("kill", "pre"):
            path = lock_root / f"{kind}_lock_{job_id}"
            if path.exists() or path.is_symlink():
                raise RuntimeError(f"forbidden {kind} lock exists: {path}")
            lock_snapshot[str(job_id)][kind] = "absent"
        child_pgid_path = lock_root / f"child_pgid_{job_id}"
        if child_pgid_path.exists() or child_pgid_path.is_symlink():
            raise RuntimeError(f"child PGID registration must be absent: {child_pgid_path}")
        lock_snapshot[str(job_id)]["child_pgid"] = "absent"
    return {
        "schema_version": 1,
        "status": "success",
        "process_audit_path": str(process_audit_path),
        "process_audit_sha256": expected_process_audit_sha256,
        "process_audit_captured_at": captured_at_raw,
        "process_audit_age_seconds": age_seconds,
        "lock_snapshot": lock_snapshot,
    }


def apply_signal11_transition_with_preconditions(
    root: Path,
    *,
    process_audit_path: Path,
    expected_process_audit_sha256: str,
    lock_root: Path,
    contract: Signal11TransitionContract = DEFAULT_CONTRACT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    以 audit SHA 短前缀命名的稳定证据授权一次可幂等重放的 signal-11 apply。

    同一 audit 的实时 ``age_seconds`` 只进入控制台返回值，不进入 immutable evidence；fresh
    audit 通常使用新短名；若短前缀碰撞，完整 SHA 所在的 payload 不同会在 live commit 前
    fail closed。因此同 audit 重试与 fresh audit 复核都不会被动态年龄或静默覆盖阻断。
    """
    preconditions = validate_signal11_apply_preconditions(
        process_audit_path,
        expected_process_audit_sha256=expected_process_audit_sha256,
        lock_root=lock_root,
        now=now,
    )
    stable_preconditions = {
        "schema_version": 1,
        "status": "success",
        "event": "stage_f_signal11_apply_preconditions",
        "process_audit_sha256": preconditions["process_audit_sha256"],
        "process_audit_captured_at": preconditions["process_audit_captured_at"],
        "lock_snapshot": preconditions["lock_snapshot"],
    }
    # 文件名只携带足够短的审计摘要前缀，完整 SHA 仍由不可变 payload 绑定；
    # 若前缀碰撞，_preflight_immutable 会在任何 live manifest 写入前拒绝覆盖。
    evidence_path = (
        root
        / "reports"
        / "runs"
        / contract.formal_run_id
        / "stage_f_signal11_exclusion_20260717_v1"
        / f"apply.{expected_process_audit_sha256[:16]}.json"
    )
    evidence_payload = _encode_json(stable_preconditions)
    _preflight_immutable(
        evidence_path,
        evidence_payload,
        "process-audit-bound apply preconditions",
    )
    _write_immutable(evidence_path, evidence_payload)
    transition = apply_or_validate_signal11_transition(
        root,
        mode="apply",
        contract=contract,
    )
    return {
        "status": "success",
        "transition": transition,
        "apply_preconditions": preconditions,
        "apply_preconditions_path": str(evidence_path),
        "apply_preconditions_sha256": sha256_file(evidence_path),
    }


def apply_extended_transition_with_preconditions(
    root: Path,
    *,
    process_audit_path: Path,
    expected_process_audit_sha256: str,
    lock_root: Path,
    contract: ExtendedExclusionTransitionContract = DEFAULT_EXTENDED_CONTRACT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """以同一跨节点零进程门授权一次可重放的第二阶段双目标迁移。"""
    preconditions = validate_signal11_apply_preconditions(
        process_audit_path,
        expected_process_audit_sha256=expected_process_audit_sha256,
        lock_root=lock_root,
        now=now,
    )
    stable_preconditions = {
        "schema_version": 2,
        "status": "success",
        "event": "stage_f_extended_exclusion_apply_preconditions",
        "process_audit_sha256": preconditions["process_audit_sha256"],
        "process_audit_captured_at": preconditions["process_audit_captured_at"],
        "lock_snapshot": preconditions["lock_snapshot"],
    }
    evidence_path = (
        root
        / "reports"
        / "runs"
        / contract.phase1_contract.formal_run_id
        / "stage_f_extended_exclusion_20260718_v2"
        / f"apply.{expected_process_audit_sha256[:16]}.json"
    )
    evidence_payload = _encode_json(stable_preconditions)
    _preflight_immutable(
        evidence_path,
        evidence_payload,
        "extended process-audit-bound apply preconditions",
    )
    _write_immutable(evidence_path, evidence_payload)
    transition = apply_or_validate_extended_exclusion_transition(
        root,
        mode="apply",
        contract=contract,
    )
    return {
        "status": "success",
        "transition": transition,
        "apply_preconditions": preconditions,
        "apply_preconditions_path": str(evidence_path),
        "apply_preconditions_sha256": sha256_file(evidence_path),
    }


def _validate_supplement_release(
    root: Path,
    contract: Signal11TransitionContract,
    *,
    supplement_index: int,
    expected_exclusion_ids: tuple[str, ...] = SIGNAL11_IDS,
) -> dict[str, Any]:
    """验证一轮 supplement 的冻结 IDs、唯一终态、排除 provenance 与 release。"""
    run_id = contract.supplement_run_ids[supplement_index]
    ids_path = root / contract.supplement_ids_relative_paths[supplement_index]
    expected_ids_sha = contract.expected_supplement_ids_sha256[supplement_index]
    expected_count = contract.expected_supplement_counts[supplement_index]
    _require_sha(ids_path, expected_ids_sha, f"{run_id} frozen IDs")
    ids = [line.strip().lower() for line in ids_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if (
        len(ids) != expected_count
        or len(ids) != len(set(ids))
        or any(re.fullmatch(r"[0-9a-z]{4}", pdb_id) is None for pdb_id in ids)
        or not set(expected_exclusion_ids).issubset(ids)
    ):
        raise RuntimeError(f"{run_id} frozen IDs are not the expected unique universe")
    expected_ids = set(ids)
    statuses, status_paths = load_stage_statuses(root, run_id, "stage_f", expected_ids)
    known_ids = {
        pdb_id
        for pdb_id, record in statuses.items()
        if record["status"] == StageStatus.KNOWN_FAILED.value
    }
    if known_ids != set(expected_exclusion_ids):
        raise RuntimeError(f"{run_id} known IDs mismatch: {sorted(known_ids)}")
    if any(
        record["status"] not in {StageStatus.SUCCESS.value, StageStatus.SKIPPED.value}
        for pdb_id, record in statuses.items()
        if pdb_id not in expected_exclusion_ids
    ):
        raise RuntimeError(f"{run_id} contains a nonterminal/noneligible status")
    exclusions, manifest_sha = load_run_exclusions(root, run_id, "stage_f")
    if set(exclusions) != set(expected_exclusion_ids) or manifest_sha is None:
        raise RuntimeError(f"{run_id} exclusion manifest IDs mismatch")
    for pdb_id in expected_exclusion_ids:
        expected_fields = exclusion_status_fields(
            exclusions[pdb_id],
            manifest_sha256=manifest_sha,
        )
        record = statuses[pdb_id]
        if (
            record.get("status") != StageStatus.KNOWN_FAILED.value
            or any(record.get(field) != value for field, value in expected_fields.items())
        ):
            raise RuntimeError(f"{run_id} exclusion status provenance mismatch: {pdb_id}")

    release_path = (
        root / "reports" / "runs" / run_id / "f_supplement_release" / "summary.json"
    )
    if release_path.is_symlink() or not release_path.is_file():
        raise RuntimeError(f"{run_id} release summary is missing or not regular")
    release = json.loads(release_path.read_text(encoding="utf-8"))
    status_counts = dict(sorted(Counter(row["status"] for row in statuses.values()).items()))
    if (
        not isinstance(release, dict)
        or release.get("status") != "success"
        or release.get("run_id") != run_id
        or release.get("gate_name") != "f_supplement_release"
        or release.get("stages") != ["stage_f"]
        or release.get("n_expected_pdb") != expected_count
        or release.get("status_counts") != {"stage_f": status_counts}
        or release.get("known_failure_reasons")
        != {"stage_f:run_policy_excluded": len(expected_exclusion_ids)}
        or release.get("exclusion_manifest_sha256") != {"stage_f": manifest_sha}
    ):
        raise RuntimeError(f"{run_id} release summary disagrees with statuses/manifests")
    return {
        "status": "success",
        "run_id": run_id,
        "n_expected_pdb": expected_count,
        "n_signal11_known": len(set(expected_exclusion_ids) & set(SIGNAL11_IDS)),
        "n_run_policy_known": len(expected_exclusion_ids),
        "ids_path": str(ids_path),
        "ids_sha256": expected_ids_sha,
        "status_paths": [str(path) for path in status_paths],
        "status_sha256": {str(path): sha256_file(path) for path in status_paths},
        "release_path": str(release_path),
        "release_sha256": sha256_file(release_path),
        "exclusion_manifest_sha256": manifest_sha,
    }


def _query_slurm_job_state(job_id: int) -> str:
    """查询一个既有 Slurm job 的唯一当前状态，供 formal readiness 使用。"""
    completed = subprocess.run(
        ["squeue", "-h", "-j", str(job_id), "-o", "%T"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    states = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or completed.stderr or len(states) != 1:
        raise RuntimeError(
            f"failed to obtain one scheduler state for job {job_id}: "
            f"exit={completed.returncode} states={states} stderr={completed.stderr!r}"
        )
    return states[0]


def _signal11_record(
    pdb_id: str,
    *,
    run_id: str,
    root: Path,
    contract: Signal11TransitionContract,
) -> dict[str, Any]:
    """构造一个不含 timeout/success 伪语义的 Stage F-only 决策。"""
    formal_evidence_dir = (
        root
        / "reports"
        / "runs"
        / contract.formal_run_id
        / "stage_f_signal11_exclusion_20260717_v1"
    )
    evidence = {
        "stage": "stage_f",
        "failure_mode": "external_tool_signal_11",
        "legacy_operation": (
            "FitMap.map_overlap_and_correlation(experimental_map,simulated_map,False)"
        ),
        "supplement_v1_status_before_path": str(
            formal_evidence_dir / "supplement_v1_status.before.jsonl"
        ),
        "supplement_v1_status_before_sha256": contract.expected_status_before_sha256,
        "n_jobs1_shadow_acceptance_path": str(
            root / contract.n_jobs1_acceptance_relative_path
        ),
        "n_jobs1_shadow_acceptance_sha256": (
            contract.expected_n_jobs1_acceptance_sha256
        ),
        "fresh_all_only_acceptance_path": str(
            root / contract.all_only_acceptance_relative_path
        ),
        "fresh_all_only_acceptance_sha256": (
            contract.expected_all_only_acceptance_sha256
        ),
        "fresh_all_only_reproduced_pdb_id": "9fkb",
        "public_quality_trio_complete": False,
        "public_quality_artifacts_created_by_decision": False,
    }
    if run_id == contract.formal_run_id:
        evidence["authorized_exclusion_cap"] = contract.exclusion_cap
    else:
        evidence.update(
            source_formal_run_id=contract.formal_run_id,
            formal_run_authorized_exclusion_cap=contract.exclusion_cap,
            supplement_manifest_role="propagate_formal_run_decision_for_real_rerun_gate",
        )
    return {
        "schema_version": 1,
        "pdb_id": pdb_id,
        "run_id": run_id,
        "stages": ["stage_f"],
        "reason": "chimera_full_grid_cc_signal11",
        "detail": (
            f"{pdb_id} reproducibly exited by signal 11 in the legacy UCSF Chimera "
            "full-grid ALL correlation path; the user authorized a current-run-only "
            "exclusion without placeholder quality artifacts"
        ),
        "authorization": contract.authorization,
        "decision_scope": "current_run_only",
        "downstream_policy": "exclude_from_training_and_inference",
        "evidence": evidence,
    }


def _validate_phase2_status(payload: bytes) -> dict[str, dict[str, Any]]:
    """验证补算 v2 的八条 unknown 仍按真实 signal-11/3600 秒超时分组。"""
    rows = _records_by_id(payload)
    unknown = {
        pdb_id
        for pdb_id, row in rows.items()
        if row.get("status") == StageStatus.UNKNOWN_FAILED.value
    }
    if unknown != set(PHASE2_IDS):
        raise RuntimeError(f"unexpected phase-2 unknown IDs: {sorted(unknown)}")
    for pdb_id in PHASE2_SIGNAL11_IDS:
        row = rows[pdb_id]
        error = str(row.get("error", ""))
        if (
            row.get("stage") != "stage_f"
            or row.get("reason") != "nonzero_exit"
            or row.get("error_type") != "ExternalToolError"
            or "external tool returned -11" not in error
            or "correlation.stdout.log" not in error
            or "correlation.stderr.log" not in error
        ):
            raise RuntimeError(f"phase-2 signal-11 evidence drift: {pdb_id}")
    for pdb_id in PHASE2_MOLMAP_TIMEOUT_IDS:
        row = rows[pdb_id]
        if (
            row.get("stage") != "stage_f"
            or row.get("reason") != "timeout"
            or row.get("error_type") != "ExternalToolError"
            or row.get("error") != "external tool timed out after 3600.0s"
        ):
            raise RuntimeError(f"phase-2 molmap timeout evidence drift: {pdb_id}")
    return {pdb_id: rows[pdb_id] for pdb_id in PHASE2_IDS}


def _validate_phase2_evidence_identities(
    root: Path,
    status_payload: bytes,
    contract: ExtendedExclusionTransitionContract,
    *,
    evidence_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[tuple[Path, bytes, str]]]:
    """绑定八条 raw status 行和十六份小日志的精确内容身份。"""
    identities: dict[str, dict[str, Any]] = {}
    for item in contract.evidence_identities:
        (
            pdb_id,
            line_number,
            raw_line_sha256,
            stdout_relative_path,
            stdout_sha256,
            stderr_relative_path,
            stderr_sha256,
        ) = item
        if pdb_id in identities:
            raise RuntimeError(f"duplicate phase-2 evidence identity: {pdb_id}")
        identities[pdb_id] = {
            "status_line_number": line_number,
            "status_raw_line_sha256": raw_line_sha256,
            "stdout_relative_path": stdout_relative_path,
            "stdout_sha256": stdout_sha256,
            "stderr_relative_path": stderr_relative_path,
            "stderr_sha256": stderr_sha256,
        }
    if set(identities) != set(PHASE2_IDS):
        raise RuntimeError("phase-2 evidence identity IDs drifted")

    raw_lines = status_payload.splitlines(keepends=True)
    attempt_ids = dict(PHASE2_ATTEMPT_IDS)
    log_payloads: list[tuple[Path, bytes, str]] = []
    for pdb_id, identity in identities.items():
        line_number = identity["status_line_number"]
        if type(line_number) is not int or not 1 <= line_number <= len(raw_lines):
            raise RuntimeError(f"phase-2 status line number drifted: {pdb_id}")
        raw_line = raw_lines[line_number - 1]
        status_record = json.loads(raw_line)
        if (
            _sha256_bytes(raw_line) != identity["status_raw_line_sha256"]
            or str(status_record.get("pdb_id", "")).lower() != pdb_id
        ):
            raise RuntimeError(f"phase-2 raw status line identity drifted: {pdb_id}")
        expected_attempt_dir = (
            Path("scratch")
            / contract.phase1_contract.supplement_run_ids[1]
            / "stage_f"
            / pdb_id
            / attempt_ids[pdb_id]
        )
        expected_prefix = expected_attempt_dir.as_posix() + "/"
        for stream in ("stdout", "stderr"):
            relative_path = identity[f"{stream}_relative_path"]
            expected_sha256 = identity[f"{stream}_sha256"]
            if (
                not isinstance(relative_path, str)
                or not relative_path.startswith(expected_prefix)
                or re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256)) is None
            ):
                raise RuntimeError(f"phase-2 {stream} evidence path/SHA drifted: {pdb_id}")
            if pdb_id in PHASE2_SIGNAL11_IDS:
                status_path = f"{stream}={(root / relative_path).resolve()}"
                if status_path not in str(status_record.get("error", "")):
                    raise RuntimeError(
                        f"phase-2 {stream} status path drifted: {pdb_id}"
                    )
            frozen_path = evidence_dir / "small_logs" / pdb_id / f"{stream}.log"
            payload = _resolve_before_bytes(
                root / relative_path,
                frozen_path,
                expected_sha256=str(expected_sha256),
            )
            identity[f"{stream}_frozen_path"] = str(frozen_path)
            log_payloads.append(
                (frozen_path, payload, f"phase-2 {pdb_id} {stream} evidence")
            )
    return identities, log_payloads


def _validate_closed_phase1_records(
    *,
    base_records: dict[str, dict[str, Any]],
    formal_records: dict[str, dict[str, Any]],
    supplement_v1_records: dict[str, dict[str, Any]],
    supplement_v2_records: dict[str, dict[str, Any]],
    phase1: Signal11TransitionContract,
) -> None:
    """证明第二阶段确实从已闭合的 base4、正式11和补算旧六条出发。"""
    if set(base_records) != {"8ckb", "8glv", "9e5c", "9fqr"}:
        raise RuntimeError("formal base exclusion IDs drifted before phase-2")
    if set(formal_records) != {*base_records, "6kgx", *SIGNAL11_IDS}:
        raise RuntimeError("formal 11-entry phase-1 manifest drifted")
    if set(supplement_v1_records) != set(SIGNAL11_IDS):
        raise RuntimeError("supplement v1 immutable six-entry manifest drifted")
    if set(supplement_v2_records) != set(SIGNAL11_IDS):
        raise RuntimeError("supplement v2 six-entry phase-1 manifest drifted")
    for pdb_id, record in base_records.items():
        if formal_records.get(pdb_id) != record:
            raise RuntimeError(f"formal phase-1 view changed base record: {pdb_id}")
    run_records = (
        (phase1.formal_run_id, formal_records),
        (phase1.supplement_run_ids[0], supplement_v1_records),
        (phase1.supplement_run_ids[1], supplement_v2_records),
    )
    for run_id, records in run_records:
        for pdb_id in SIGNAL11_IDS:
            record = records[pdb_id]
            if (
                record.get("run_id") != run_id
                or record.get("stages") != ["stage_f"]
                or record.get("reason") != "chimera_full_grid_cc_signal11"
            ):
                raise RuntimeError(f"closed phase-1 record drifted: {run_id}/{pdb_id}")


def _extended_exclusion_record(
    pdb_id: str,
    *,
    run_id: str,
    status_record: dict[str, Any],
    evidence_identity: dict[str, Any],
    root: Path,
    contract: ExtendedExclusionTransitionContract,
) -> dict[str, Any]:
    """按真实失败类型构造一条不含占位产物的第二阶段 run-only 决策。"""
    phase1 = contract.phase1_contract
    attempt_id = dict(PHASE2_ATTEMPT_IDS)[pdb_id]
    attempt_dir = Path(evidence_identity["stdout_relative_path"]).parent
    status_evidence_path = (
        root
        / "reports"
        / "runs"
        / phase1.formal_run_id
        / "stage_f_extended_exclusion_20260718_v2"
        / "supplement_v2_status.before.jsonl"
    )
    evidence: dict[str, Any] = {
        "stage": "stage_f",
        "source_status_path": str(status_evidence_path),
        "source_status_sha256": contract.expected_status_before_sha256,
        "source_status_observation": {
            field: status_record.get(field)
            for field in ("stage", "status", "reason", "error_type", "error")
        },
        "source_status_record_canonical_sha256": _sha256_bytes(
            _encode_json(status_record)
        ),
        "source_status_line_number": evidence_identity["status_line_number"],
        "source_status_raw_line_sha256": evidence_identity[
            "status_raw_line_sha256"
        ],
        "scratch_attempt_relative_path": attempt_dir.as_posix(),
        "scratch_attempt_id": attempt_id,
        "frozen_small_log_paths": [
            evidence_identity["stdout_frozen_path"],
            evidence_identity["stderr_frozen_path"],
        ],
        "public_quality_trio_complete": False,
        "public_quality_artifacts_created_by_decision": False,
    }
    if pdb_id in PHASE2_SIGNAL11_IDS:
        reason = "chimera_full_grid_cc_signal11"
        detail = (
            f"{pdb_id} exited by signal 11 in the legacy UCSF Chimera full-grid ALL "
            "correlation path; the user authorized a current-run-only exclusion without "
            "placeholder quality artifacts"
        )
        evidence.update(
            failure_mode="external_tool_signal_11",
            legacy_operation=(
                "FitMap.map_overlap_and_correlation(experimental_map,simulated_map,False)"
            ),
            scratch_log_sha256={
                evidence_identity["stdout_relative_path"]: evidence_identity[
                    "stdout_sha256"
                ],
                evidence_identity["stderr_relative_path"]: evidence_identity[
                    "stderr_sha256"
                ],
            },
        )
    else:
        diagnostic_detail = dict(contract.timeout_details)[pdb_id]
        reason = "chimera_molmap_timeout_3600s"
        detail = (
            f"{pdb_id} exceeded the frozen 3600-second Chimera molmap limit "
            f"({diagnostic_detail}); the user authorized a current-run-only exclusion "
            "without placeholder quality artifacts"
        )
        evidence.update(
            failure_mode="external_tool_timeout",
            legacy_operation="UCSF_Chimera_molmap",
            timeout_seconds=3600.0,
            diagnostic_detail=diagnostic_detail,
            scratch_log_sha256={
                evidence_identity["stdout_relative_path"]: evidence_identity[
                    "stdout_sha256"
                ],
                evidence_identity["stderr_relative_path"]: evidence_identity[
                    "stderr_sha256"
                ],
            },
        )
    if run_id == phase1.formal_run_id:
        evidence["authorized_exclusion_cap"] = contract.exclusion_cap
    else:
        evidence.update(
            source_formal_run_id=phase1.formal_run_id,
            formal_run_authorized_exclusion_cap=contract.exclusion_cap,
            supplement_manifest_role="propagate_formal_run_decision_for_real_rerun_gate",
        )
    return {
        "schema_version": 1,
        "pdb_id": pdb_id,
        "run_id": run_id,
        "stages": ["stage_f"],
        "reason": reason,
        "detail": detail,
        "authorization": contract.authorization,
        "decision_scope": "current_run_only",
        "downstream_policy": "exclude_from_training_and_inference",
        "evidence": evidence,
    }


def _resolve_before_bytes(
    live_path: Path,
    evidence_path: Path,
    *,
    expected_sha256: str,
) -> bytes:
    """首次从 live 路径取旧字节；迁移后只允许复用冻结的 before 证据。"""
    for path in (live_path, evidence_path):
        if path.is_symlink() or not path.is_file():
            continue
        payload = path.read_bytes()
        if _sha256_bytes(payload) == expected_sha256:
            return payload
    raise RuntimeError(
        f"missing immutable pre-transition bytes with SHA-256 {expected_sha256}"
    )


def _validate_signal11_status(payload: bytes) -> None:
    """要求旧补算状态恰有六条真实 ExternalToolError/-11 unknown。"""
    rows = _records_by_id(payload)
    unknown = {
        pdb_id
        for pdb_id, row in rows.items()
        if row.get("status") == "unknown_failed"
    }
    if unknown != set(SIGNAL11_IDS):
        raise RuntimeError(f"unexpected supplement unknown IDs: {sorted(unknown)}")
    for pdb_id in SIGNAL11_IDS:
        row = rows[pdb_id]
        if (
            row.get("stage") != "stage_f"
            or row.get("reason") != "nonzero_exit"
            or row.get("error_type") != "ExternalToolError"
            or "external tool returned -11" not in str(row.get("error", ""))
        ):
            raise RuntimeError(f"supplement signal-11 evidence drift: {pdb_id}")


def _require_zero_public_trios(root: Path) -> dict[str, dict[str, bool]]:
    """确认六例仍为 0/3；本函数和整个迁移都不会创建这些路径。"""
    return _require_zero_public_trios_for(root, SIGNAL11_IDS)


def _require_zero_public_trios_for(
    root: Path,
    pdb_ids: tuple[str, ...],
) -> dict[str, dict[str, bool]]:
    """确认指定样本的公开质量三件套均不存在，不创建或删除任何路径。"""
    snapshot: dict[str, dict[str, bool]] = {}
    for pdb_id in pdb_ids:
        paths = {
            f"quality/{pdb_id}.jsonl": root / "quality" / f"{pdb_id}.jsonl",
            f"quality/{pdb_id}.provenance.json": (
                root / "quality" / f"{pdb_id}.provenance.json"
            ),
            f"quality_atoms/{pdb_id}.npz": (
                root / "quality_atoms" / f"{pdb_id}.npz"
            ),
        }
        snapshot[pdb_id] = {}
        for name, path in paths.items():
            exists = path.exists() or path.is_symlink()
            snapshot[pdb_id][name] = exists
            if exists:
                raise RuntimeError(
                    f"run-only exclusion refuses an existing public quality artifact: {path}"
                )
    return snapshot


def _records_by_id(payload: bytes) -> dict[str, dict[str, Any]]:
    """读取 JSONL 字节并按唯一小写 PDB ID 建索引。"""
    records: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(payload.decode("utf-8").splitlines()):
        if not line.strip():
            continue
        record = json.loads(line)
        pdb_id = str(record.get("pdb_id", "")).lower()
        if not pdb_id or pdb_id in records:
            raise RuntimeError(f"duplicate or empty PDB ID at JSONL row {index}")
        records[pdb_id] = record
    if not records:
        raise RuntimeError("JSONL evidence must not be empty")
    return records


def _encode_jsonl(records: dict[str, dict[str, Any]]) -> bytes:
    """按 PDB ID 排序并用稳定紧凑格式编码 manifest。"""
    return b"".join(
        (
            json.dumps(
                records[pdb_id],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        for pdb_id in sorted(records)
    )


def _encode_json(value: dict[str, Any]) -> bytes:
    """编码稳定、面向人工审计的 JSON。"""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    """计算内存字节的 SHA-256。"""
    return hashlib.sha256(payload).hexdigest()


def _require_sha(path: Path, expected: str, label: str) -> None:
    """要求只读证据为普通文件且内容身份匹配。"""
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected:
        raise RuntimeError(f"{label} SHA-256 drift: {path}")


def _write_immutable(path: Path, payload: bytes) -> None:
    """首次同目录原子写入；重放只接受逐字节相同内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _require_bytes(path, payload, "immutable evidence")
        return
    _atomic_write(path, payload)


def _preflight_signal11_apply(
    replacements: list[_LiveReplacement],
    *,
    supplement_run_dirs: dict[str, Path],
    evidence_payloads: list[tuple[Path, bytes, str]],
) -> None:
    """
    在首个 live replace 前一次性验证三目标、两份 overlay 和全部 evidence 目的地。

    该预检不创建目录或文件。任何 symlink、漂移、缺失父目录或不可接受旧态都在
    formal/supplement manifest 发生首个变更前失败。
    """
    for run_id, run_dir in supplement_run_dirs.items():
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise RuntimeError(f"supplement run directory is not regular: {run_dir}")
        stage_f_view = run_dir / "exclusions.stage_f.jsonl"
        if stage_f_view.exists() or stage_f_view.is_symlink():
            raise RuntimeError(
                f"supplement run must not introduce a Stage F overlay: {run_id}"
            )
    for replacement in replacements:
        _preflight_live_replacement(replacement)
    for path, payload, label in evidence_payloads:
        _preflight_immutable(path, payload, label)


def _preflight_live_replacement(replacement: _LiveReplacement) -> None:
    """验证一个 live manifest 当前为允许旧态、目标字节或允许的 absent。"""
    path = replacement.path
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise RuntimeError(f"live manifest parent is not a regular directory: {path.parent}")
    if path.is_symlink():
        raise RuntimeError(f"live manifest must not be a symlink: {path}")
    if not path.exists():
        if replacement.allow_absent:
            return
        raise RuntimeError(f"required live manifest is absent: {path}")
    if not path.is_file():
        raise RuntimeError(f"live manifest must be a regular file: {path}")
    current = path.read_bytes()
    if current == replacement.payload:
        return
    if (
        replacement.allowed_before_sha256 is not None
        and _sha256_bytes(current) == replacement.allowed_before_sha256
    ):
        return
    raise RuntimeError(f"live manifest drift before signal-11 transition: {path}")


def _preflight_immutable(path: Path, payload: bytes, label: str) -> None:
    """只读验证 immutable evidence 可新建，或已逐字节等于本次冻结内容。"""
    _require_safe_parent_chain(path)
    if path.exists() or path.is_symlink():
        _require_bytes(path, payload, label)


def _require_safe_parent_chain(path: Path) -> None:
    """要求目标父链不存在 symlink 或非目录节点；允许 evidence 的末级目录尚未创建。"""
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink():
            raise RuntimeError(f"target parent chain contains a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise RuntimeError(f"target parent chain contains a non-directory: {parent}")


def _prepare_live_replacement_temps(
    replacements: list[_LiveReplacement],
) -> dict[Path, Path]:
    """在任何 replace 前，为全部 live 目标同目录写入并 fsync 当前进程独占 temp。"""
    prepared: dict[Path, Path] = {}
    try:
        for replacement in replacements:
            _preflight_live_replacement(replacement)
            temporary = replacement.path.with_name(
                f"{replacement.path.name}.tmp.{os.getpid()}.{uuid4().hex}"
            )
            with temporary.open("xb") as stream:
                stream.write(replacement.payload)
                stream.flush()
                os.fsync(stream.fileno())
            prepared[replacement.path] = temporary
    except Exception:
        for temporary in prepared.values():
            temporary.unlink(missing_ok=True)
        raise
    return prepared


def _commit_live_replacements(
    replacements: list[_LiveReplacement],
    prepared: dict[Path, Path],
) -> None:
    """按冻结 journal 顺序提交已 fsync 的 temp；每步前再次拒绝并发漂移。"""
    if set(prepared) != {replacement.path for replacement in replacements}:
        raise RuntimeError("prepared replacement set does not match the frozen journal")
    for replacement in replacements:
        _preflight_live_replacement(replacement)
        if (
            replacement.path.is_file()
            and not replacement.path.is_symlink()
            and replacement.path.read_bytes() == replacement.payload
        ):
            prepared[replacement.path].unlink(missing_ok=True)
            continue
        os.replace(prepared[replacement.path], replacement.path)


def _require_bytes(path: Path, expected: bytes, label: str) -> None:
    """要求普通文件逐字节等于冻结内容。"""
    if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
        raise RuntimeError(f"{label} drift: {path}")


def _atomic_write(path: Path, payload: bytes) -> None:
    """在目标目录内写当前进程独占临时文件，再原子替换目标。"""
    # 临时名不复制长目标名，避免 Windows 测试路径在 audit SHA 文件上超过 MAX_PATH。
    temporary = path.with_name(f".tmp.{os.getpid()}.{uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """解析窄入口参数并输出确定性迁移摘要。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=(
            "apply",
            "validate",
            "readiness",
            "apply-extended",
            "validate-extended",
            "readiness-extended",
        ),
        required=True,
    )
    parser.add_argument("--process_audit", type=Path)
    parser.add_argument("--process_audit_sha256")
    parser.add_argument("--lock_root", type=Path, default=Path("/home/penghongen"))
    parser.add_argument("--expected_supplement_run_cmd_sha256")
    args = parser.parse_args()
    if args.mode in {"apply", "apply-extended"}:
        if args.process_audit is None or args.process_audit_sha256 is None:
            parser.error("apply modes require --process_audit and --process_audit_sha256")
        if args.mode == "apply":
            summary = apply_signal11_transition_with_preconditions(
                args.root,
                process_audit_path=args.process_audit,
                expected_process_audit_sha256=args.process_audit_sha256,
                lock_root=args.lock_root,
            )
        else:
            summary = apply_extended_transition_with_preconditions(
                args.root,
                process_audit_path=args.process_audit,
                expected_process_audit_sha256=args.process_audit_sha256,
                lock_root=args.lock_root,
            )
    elif args.mode == "readiness":
        if args.expected_supplement_run_cmd_sha256 is None:
            parser.error(
                "readiness requires --expected_supplement_run_cmd_sha256"
            )
        summary = validate_formal_signal11_readiness(
            args.root,
            expected_supplement_run_cmd_sha256=(
                args.expected_supplement_run_cmd_sha256
            ),
            lock_root=args.lock_root,
        )
    elif args.mode == "readiness-extended":
        summary = validate_formal_extended_readiness(args.root)
    elif args.mode == "validate-extended":
        summary = apply_or_validate_extended_exclusion_transition(
            args.root,
            mode="validate",
        )
    else:
        summary = apply_or_validate_signal11_transition(args.root, mode="validate")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
