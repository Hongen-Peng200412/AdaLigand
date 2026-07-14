#!/usr/bin/env bash
set -euo pipefail

# 本入口只处理正式 F 的单个已取证长尾 6kgx：追加 run-scoped Stage F exclusion，
# 再用原 run id、无 overwrite 复用已完成质量三件套。它不改变通用 Q-score 科学契约。
FORMAL="adaligand_ag_20260711T154658"
FORMAL_JOB="316116"
DATA_ROOT="${DATA_ROOT:-/storage/penghongen/AdaLigand/Ori_Data}"
CODE_ROOT="${CODE_ROOT:-/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data}"
PYTHON="${PYTHON:-/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python}"
CHIMERA="${CHIMERA:-/home/penghongen/.local/opt/UCSF-Chimera64-1.19/bin/chimera}"
CHIMERA_ROOT="${CHIMERA_ROOT:-/home/penghongen/.local/opt/UCSF-Chimera64-1.19}"
MAPQ_CMD="${MAPQ_CMD:-/home/penghongen/.local/opt/mapq-2.9.7-c3bdf305/mapq/mapq_cmd.py}"
MAPQ_ZIP="${MAPQ_ZIP:-/home/penghongen/.local/opt/downloads/mapq_v2.9.7.zip}"
SCRATCH_ROOT="${SCRATCH_ROOT:-${DATA_ROOT}/scratch}"

BASE_EXCLUSIONS="${DATA_ROOT}/reports/runs/${FORMAL}/exclusions.jsonl"
F_EXCLUSIONS="${DATA_ROOT}/reports/runs/${FORMAL}/exclusions.stage_f.jsonl"
EVIDENCE_DIR="${DATA_ROOT}/reports/runs/${FORMAL}/stage_f_long_tail_cutoff_20260714T2213"
EXPECTED_BEFORE_SHA="380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f"
AUTHORIZATION="user_explicit_2026-07-14_mark_current_f_long_tail_as_timeout"
AFTER_LOCK="/home/penghongen/after_lock_${FORMAL_JOB}"
TRY_LOCK="/home/penghongen/try_lock_${FORMAL_JOB}"
KILL_LOCK="/home/penghongen/kill_lock_${FORMAL_JOB}"
RUN_CMD="/home/penghongen/run_cmd_${FORMAL_JOB}.sh"
RELEASE_MARKER="/home/penghongen/f_long_tail_cutoff_release_${FORMAL_JOB}"

[[ "${ADALIGAND_RUN_ID:-}" == "${FORMAL}" ]]
[[ "${SLURM_JOB_ID:-}" == "${FORMAL_JOB}" ]]
[[ -f "${AFTER_LOCK}" && ! -L "${AFTER_LOCK}" ]]
[[ ! -e "${KILL_LOCK}" ]]
if [[ "${APPLY_CUTOFF:-0}" == "1" ]]; then
    [[ "${VALIDATE_ONLY:-0}" == "0" ]]
    [[ -f "${TRY_LOCK}" && ! -L "${TRY_LOCK}" ]]
    transition_mode="apply"
elif [[ "${APPLY_CUTOFF:-0}" != "0" ]]; then
    echo "APPLY_CUTOFF must be 0 or 1" >&2
    exit 1
elif [[ "${VALIDATE_ONLY:-0}" == "1" ]]; then
    [[ -f "${TRY_LOCK}" && ! -L "${TRY_LOCK}" ]]
    transition_mode="validate"
elif [[ "${VALIDATE_ONLY:-0}" == "0" ]]; then
    [[ ! -e "${TRY_LOCK}" ]]
    transition_mode="validate"
else
    echo "VALIDATE_ONLY must be 0 or 1" >&2
    exit 1
fi

# 6kgx 的外部工具 scratch 保留作证据；正式质量三件套尚未提升，不能冒充成功。
[[ ! -e "${DATA_ROOT}/quality/6kgx.jsonl" ]]
[[ ! -e "${DATA_ROOT}/quality/6kgx.provenance.json" ]]
[[ ! -e "${DATA_ROOT}/quality_atoms/6kgx.npz" ]]

cd "${CODE_ROOT}"
PYTHONPATH="${CODE_ROOT}/code" "${PYTHON}" - \
    "${DATA_ROOT}" "${FORMAL}" "${EVIDENCE_DIR}" \
    "${EXPECTED_BEFORE_SHA}" "${AUTHORIZATION}" "${transition_mode}" \
    "${BASH_SOURCE[0]}" "${RUN_CMD}" "${RELEASE_MARKER}" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

from exclusions import load_run_exclusions
from io_utils import read_jsonl, sha256_file


root = Path(sys.argv[1])
run_id = sys.argv[2]
evidence_dir = Path(sys.argv[3])
expected_before_sha = sys.argv[4]
authorization = sys.argv[5]
transition_mode = sys.argv[6]
resume_script = Path(sys.argv[7]).resolve()
run_cmd = Path(sys.argv[8])
release_marker = Path(sys.argv[9])
allow_create = transition_mode == "apply"
if transition_mode not in {"apply", "validate"}:
    raise RuntimeError(f"unsupported Stage F cutoff transition mode: {transition_mode}")
base_manifest = root / "reports" / "runs" / run_id / "exclusions.jsonl"
stage_f_manifest = root / "reports" / "runs" / run_id / "exclusions.stage_f.jsonl"
before_path = evidence_dir / "exclusions.before.jsonl"
after_path = evidence_dir / "exclusions.after.jsonl"
predecision_path = evidence_dir / "predecision.json"
posttermination_path = evidence_dir / "posttermination.json"
summary_path = evidence_dir / "summary.json"
raw_evidence_sha256 = {
    "artifact_snapshot.txt": "109de6d20e0623db381761104d550e43f60ffb8b5b4ea993a362206529c0fc6a",
    "interactive_diagnostic.json": "abc498757a294a603f5021a165a9785801472edb3b6c3dfcca3aa0ef7db93589",
    "job.stderr.cutoff.log": "e6f587b7cac38f9312377430eee4df98f311b0a21e62268354f04dbb340e0c86",
    "job.stdout.cutoff.log": "0874d3ad3783c552d0efa5ad5b9fbbc7de37407cf9384f22b200e2430eb24ad2",
    "scheduler_process_snapshot.txt": "12173f071d3ae96584363319b72b73db81cdfbdd2252cab82820076523fbc120",
    "source_small_files.sha256": "a2d60e80e135469053a9528442856bc770b2dd3b42e4fd009f80b2ea4b372fb2",
}


def encode_json(value: dict) -> bytes:
    """按稳定格式编码单个审计对象。"""
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def encode_jsonl(values: list[dict]) -> bytes:
    """按稳定键序编码 exclusion manifest。"""
    return b"".join(
        (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        for value in values
    )


def sha256_bytes(payload: bytes) -> str:
    """计算内存证据的 SHA-256。"""
    return hashlib.sha256(payload).hexdigest()


def write_immutable(path: Path, payload: bytes, *, create: bool) -> None:
    """apply 首次原子写入；validate 只接受已存在且逐字节一致的证据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise RuntimeError(f"immutable Stage F cutoff evidence drift: {path}")
        return
    if not create:
        raise RuntimeError(f"required Stage F cutoff evidence is missing: {path}")
    temporary = path.with_name(f"{path.name}.tmp.{uuid4().hex}")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


if base_manifest.is_symlink() or not base_manifest.is_file():
    raise RuntimeError("formal exclusion manifest must be a regular file")
if sha256_file(base_manifest) != expected_before_sha:
    raise RuntimeError("shared Stage E/F exclusion manifest drifted after Stage E release")
before_bytes = base_manifest.read_bytes()
for name, expected_sha in raw_evidence_sha256.items():
    path = evidence_dir / name
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected_sha:
        raise RuntimeError(f"raw Stage F cutoff evidence drift: {path}")

if release_marker.is_symlink() or not release_marker.is_file():
    raise RuntimeError("Stage F cutoff release marker must be a regular file")
if run_cmd.is_symlink() or not run_cmd.is_file():
    raise RuntimeError("Stage F run_cmd must be a regular file")
if resume_script.is_symlink() or not resume_script.is_file():
    raise RuntimeError("Stage F resume script must be a regular file")
code_paths = {
    "exclusions_code_sha256": resume_script.parents[1] / "code" / "exclusions.py",
    "f_quality_sha256": resume_script.parents[1] / "scripts" / "f_quality.py",
    "stage_release_gate_sha256": resume_script.parents[1] / "scripts" / "stage_release_gate.py",
    "resume_script_sha256": resume_script,
    "run_cmd_sha256": run_cmd,
}
code_sha256 = {name: sha256_file(path) for name, path in code_paths.items()}
release_fields: dict[str, str] = {}
for raw_line in release_marker.read_text(encoding="utf-8").splitlines():
    if not raw_line or "=" not in raw_line:
        raise RuntimeError("Stage F cutoff release marker contains an invalid line")
    key, value = raw_line.split("=", 1)
    if not key or not value or key in release_fields:
        raise RuntimeError("Stage F cutoff release marker contains an empty or duplicate field")
    release_fields[key] = value
expected_release_fields = {
    "schema_version": "1",
    "event": "stage_f_long_tail_cutoff_release",
    "formal_job": "316116",
    "run_id": run_id,
    "authorization": authorization,
    **code_sha256,
}
if set(release_fields) != set(expected_release_fields) | {
    "remote_tests",
    "remote_test_exit_code",
    "remote_test_log_sha256",
}:
    raise RuntimeError("Stage F cutoff release marker field set drift")
for field, value in expected_release_fields.items():
    if release_fields.get(field) != value:
        raise RuntimeError(f"Stage F cutoff release marker mismatch: {field}")
remote_test_log = evidence_dir / "remote_tests.log"
if remote_test_log.is_symlink() or not remote_test_log.is_file():
    raise RuntimeError("Stage F cutoff remote test log is missing")
if sha256_file(remote_test_log) != release_fields["remote_test_log_sha256"]:
    raise RuntimeError("Stage F cutoff remote test log SHA mismatch")
remote_test_text = remote_test_log.read_text(encoding="utf-8")
passed_summaries = re.findall(r"(?m)^(\d+) passed in [0-9.]+s$", remote_test_text)
if (
    release_fields["remote_test_exit_code"] != "0"
    or len(passed_summaries) != 1
    or release_fields["remote_tests"] != f"{passed_summaries[0]}_passed"
    or re.search(r"(?im)(\d+ failed|\d+ error|errors during collection)", remote_test_text)
):
    raise RuntimeError("Stage F cutoff remote tests did not end in a unique clean pass summary")

write_immutable(before_path, before_bytes, create=allow_create)

predecision = {
    "schema_version": 1,
    "event": "stage_f_user_authorized_long_tail_timeout_predecision",
    "run_id": run_id,
    "job_id": 316116,
    "observed_at": "2026-07-14T22:12:51+08:00",
    "job_state": "RUNNING",
    "job_elapsed_at_snapshot": "20:44:12",
    "parallel_progress": {"completed": 22363, "total": 22386, "last_progress_elapsed_minutes": 635.4},
    "pdb_id": "6kgx",
    "occurrence_count": 1588,
    "selected_model_atom_count": 1011574,
    "public_quality_trio": {
        "quality/6kgx.jsonl": False,
        "quality/6kgx.provenance.json": False,
        "quality_atoms/6kgx.npz": False,
    },
    "scratch_attempt": "scratch/adaligand_ag_20260711T154658/stage_f/6kgx/12ae270fc3c1460aa318dd8f73306a4c",
    "external_tools_completed": True,
    "active_hotspot": {
        "inspection": "read_only_py_spy_dump",
        "worker_pid": 261293,
        "function": "quality.project_occurrence_qscores/_row_matches_component",
        "finding": "each present ligand slot repeatedly scanned the full selected_atom_rows list",
    },
    "raw_evidence_sha256": raw_evidence_sha256,
}
posttermination = {
    "schema_version": 1,
    "event": "stage_f_user_authorized_long_tail_timeout_posttermination",
    "run_id": run_id,
    "job_id": 316116,
    "observed_at": "2026-07-14T22:13:00+08:00",
    "termination": "kill_lock_316116_detected; run_cmd_exit_137; try_lock_316116_created",
    "after_lock_preserved": True,
    "kill_lock_absent_after_watcher": True,
    "f_quality_or_loky_processes_remaining": False,
    "g_job": {"job_id": 316117, "state": "PENDING", "reason": "Dependency"},
    "public_quality_trio_complete": False,
    "raw_evidence_sha256": raw_evidence_sha256,
}
pre_bytes = encode_json(predecision)
post_bytes = encode_json(posttermination)
write_immutable(predecision_path, pre_bytes, create=allow_create)
write_immutable(posttermination_path, post_bytes, create=allow_create)
pre_sha = sha256_bytes(pre_bytes)
post_sha = sha256_bytes(post_bytes)

base_records = {str(row["pdb_id"]).lower(): row for row in read_jsonl(before_path)}
if set(base_records) != {"8ckb", "8glv", "9e5c", "9fqr"}:
    raise RuntimeError(f"unexpected pre-cutoff exclusion IDs: {sorted(base_records)}")
record = {
    "schema_version": 1,
    "pdb_id": "6kgx",
    "run_id": run_id,
    "stages": ["stage_f"],
    "reason": "user_authorized_stage_f_engineering_long_tail_timeout",
    "detail": "6kgx received a user-authorized manual timeout after post-MapQ occurrence projection became an engineering performance long tail",
    "authorization": authorization,
    "decision_scope": "current_run_only",
    "downstream_policy": "exclude_from_training_and_inference",
    "evidence": {
        "formal_job_id": 316116,
        "stage": "stage_f",
        "parallel_progress": "22363/22386",
        "occurrence_count": 1588,
        "selected_model_atom_count": 1011574,
        "active_hotspot": "quality.project_occurrence_qscores/_row_matches_component",
        "public_quality_trio_complete": False,
        "termination": posttermination["termination"],
        "predecision_path": str(predecision_path),
        "predecision_sha256": pre_sha,
        "posttermination_path": str(posttermination_path),
        "posttermination_sha256": post_sha,
    },
}
final_records = {**base_records, "6kgx": record}
after_bytes = encode_jsonl([final_records[pdb_id] for pdb_id in sorted(final_records)])
after_sha = sha256_bytes(after_bytes)
write_immutable(after_path, after_bytes, create=allow_create)
if not stage_f_manifest.exists():
    if not allow_create:
        raise RuntimeError("formal Stage F exclusion view is missing")
    temporary = stage_f_manifest.with_name(f"{stage_f_manifest.name}.tmp.{uuid4().hex}")
    temporary.write_bytes(after_bytes)
    os.replace(temporary, stage_f_manifest)
elif stage_f_manifest.is_symlink() or not stage_f_manifest.is_file() or sha256_file(stage_f_manifest) != after_sha:
    raise RuntimeError("formal Stage F exclusion view changed outside the audited transition")

stage_e, stage_e_sha = load_run_exclusions(root, run_id, "stage_e")
stage_f, stage_f_sha = load_run_exclusions(root, run_id, "stage_f")
if set(stage_e) != set(base_records) or stage_e_sha != expected_before_sha:
    raise RuntimeError("Stage E exclusion scope changed during Stage F-only cutoff")
if set(stage_f) != set(final_records) or stage_f_sha != after_sha:
    raise RuntimeError("Stage F exclusion manifest verification failed")

summary = {
    "schema_version": 1,
    "status": "success",
    "event": "stage_f_user_authorized_long_tail_timeout_release",
    "run_id": run_id,
    "job_id": 316116,
    "authorization": authorization,
    "decision_scope": "current_run_only",
    "before_manifest_path": str(before_path),
    "before_manifest_sha256": expected_before_sha,
    "after_manifest_path": str(after_path),
    "after_manifest_sha256": after_sha,
    "predecision_path": str(predecision_path),
    "predecision_sha256": pre_sha,
    "posttermination_path": str(posttermination_path),
    "posttermination_sha256": post_sha,
    "existing_exclusion_ids": sorted(base_records),
    "added_exclusion_ids": ["6kgx"],
    "final_stage_f_exclusion_ids": sorted(final_records),
    "stage_e_exclusion_ids": sorted(stage_e),
    "stage_e_manifest_sha256": stage_e_sha,
    "stage_f_manifest_path": str(stage_f_manifest),
    "stage_f_manifest_sha256": stage_f_sha,
    "release_marker_path": str(release_marker),
    "release_marker_sha256": sha256_file(release_marker),
    "remote_tests": release_fields["remote_tests"],
    "remote_test_exit_code": release_fields["remote_test_exit_code"],
    "remote_test_log_sha256": release_fields["remote_test_log_sha256"],
    **code_sha256,
    "policy": "run-only Stage F timeout; keep sample in universe and status denominator",
}
summary_bytes = encode_json(summary)
write_immutable(summary_path, summary_bytes, create=allow_create)
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
PY

if [[ "${APPLY_CUTOFF:-0}" == "1" ]]; then
    echo "[ResumeFLongTail] apply-only transition succeeded"
    exit 0
elif [[ "${VALIDATE_ONLY:-0}" == "1" ]]; then
    echo "[ResumeFLongTail] read-only validation succeeded"
    exit 0
fi

"${PYTHON}" scripts/f_quality.py \
    --root "${DATA_ROOT}" \
    --chimera "${CHIMERA}" \
    --chimera_root "${CHIMERA_ROOT}" \
    --mapq_python "${PYTHON}" \
    --mapq_cmd "${MAPQ_CMD}" \
    --mapq_zip "${MAPQ_ZIP}" \
    --scratch_root "${SCRATCH_ROOT}" \
    --n_jobs 12 \
    --run_id "${FORMAL}"

"${PYTHON}" scripts/stage_release_gate.py \
    --root "${DATA_ROOT}" \
    --run_id "${FORMAL}" \
    --stages stage_f \
    --gate_name f_release
