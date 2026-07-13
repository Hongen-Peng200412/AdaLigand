#!/usr/bin/env bash
set -euo pipefail

# 316415 已按用户授权的绝对截止点结束；本入口只消费冻结的 cutoff 证据链。
# 它不伪造 316415 的 6/6 success，也不重跑 D，只以正式 run 无过滤复核 Stage E。
FORMAL="adaligand_ag_20260711T154658"
DATA_ROOT="${DATA_ROOT:-/storage/penghongen/AdaLigand/Ori_Data}"
CODE_ROOT="${CODE_ROOT:-/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data}"
PYTHON="${PYTHON:-/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python}"
CHIMERA="${CHIMERA:-/home/penghongen/.local/opt/UCSF-Chimera64-1.19/bin/chimera}"
SCRATCH_ROOT="${SCRATCH_ROOT:-${DATA_ROOT}/scratch}"

FORMAL_STAGE_D_STATUS="${DATA_ROOT}/reports/runs/${FORMAL}/stage_d/status.part_0000_of_0001.jsonl"
FORMAL_STAGE_E_DIR="${DATA_ROOT}/reports/runs/${FORMAL}/stage_e"
FORMAL_STAGE_E_STATUS="${FORMAL_STAGE_E_DIR}/status.part_0000_of_0001.jsonl"
EXCLUSIONS="${DATA_ROOT}/reports/runs/${FORMAL}/exclusions.jsonl"
CUTOFF_DIR="${DATA_ROOT}/reports/runs/${FORMAL}/stage_e_long_tail_cutoff_20260713T195419"
PREDECISION="${CUTOFF_DIR}/predecision.json"
POSTTERMINATION="${CUTOFF_DIR}/posttermination.json"
BEFORE_MANIFEST="${CUTOFF_DIR}/exclusions.before.jsonl"
AFTER_MANIFEST="${CUTOFF_DIR}/exclusions.after.jsonl"
CUTOFF_SUMMARY="${CUTOFF_DIR}/summary.json"
CUTOFF_RELEASE="/home/penghongen/e_long_tail_cutoff_release_316115"
RUN_CMD="/home/penghongen/run_cmd_316115.sh"

EXPECTED_STAGE_D_SHA="263fa2af81198e686616d2c8b1022a32668a689a6a74438d72c6e294662d5e9f"
INITIAL_STAGE_E_SHA="b03b7c72a00730f5fc0bb56b718f0f7f5a7313f11212fbc034fc74f4a6a6c7b0"
EXPECTED_PRE_SHA="40e7c949df528b81e1c4a8ee8bbd60daec5ec4d06089037e64958f08fd5458a8"
EXPECTED_POST_SHA="0f20f20cae3b9958cfe3fd3085233782b2e2e5533144cec704fa22dec2d97397"
EXPECTED_BEFORE_SHA="b586cab20644c3cc8fb1f4e0eaa7eead4cff0d496a862c2313b5e0c1847257fe"
EXPECTED_AFTER_SHA="380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f"
EXPECTED_SUMMARY_SHA="f4a26a9359519e4b94b9f28ecdb21645929c018a014729feadb44b29eadf4761"
EXPECTED_CUTOFF_CODE_SHA="509672275f61e84a22b5e56c4842a3904769736dddeafe98802f9d19f7197b54"
EXPECTED_CUTOFF_CLI_SHA="bb600c7bf5632af2fc575cd6f1f992a38210aaecbdc55ca568dd1895d26c490e"

require_regular_file() {
    local path="$1"
    [[ -f "${path}" && ! -L "${path}" ]]
}

require_sha256() {
    local path="$1"
    local expected="$2"
    require_regular_file "${path}"
    [[ "$(sha256sum "${path}" | awk '{print $1}')" == "${expected}" ]]
}

cd "${CODE_ROOT}"

# 数据、代码和一次性 cutoff 证据均须保持冻结身份。
require_sha256 "${FORMAL_STAGE_D_STATUS}" "${EXPECTED_STAGE_D_SHA}"
require_regular_file "${FORMAL_STAGE_E_STATUS}"
formal_stage_e_sha="$(sha256sum "${FORMAL_STAGE_E_STATUS}" | awk '{print $1}')"
require_sha256 "${PREDECISION}" "${EXPECTED_PRE_SHA}"
require_sha256 "${POSTTERMINATION}" "${EXPECTED_POST_SHA}"
require_sha256 "${BEFORE_MANIFEST}" "${EXPECTED_BEFORE_SHA}"
require_sha256 "${AFTER_MANIFEST}" "${EXPECTED_AFTER_SHA}"
require_sha256 "${EXCLUSIONS}" "${EXPECTED_AFTER_SHA}"
require_sha256 "${CUTOFF_SUMMARY}" "${EXPECTED_SUMMARY_SHA}"
require_sha256 "${CODE_ROOT}/code/long_tail_cutoff.py" "${EXPECTED_CUTOFF_CODE_SHA}"
require_sha256 "${CODE_ROOT}/scripts/stage_e_long_tail_cutoff.py" "${EXPECTED_CUTOFF_CLI_SHA}"

# release marker 双向绑定本脚本与 core 即将执行的当前 run_cmd，不形成自哈希循环。
require_regular_file "${CUTOFF_RELEASE}"
require_regular_file "${RUN_CMD}"
resume_v3_sha="$(sha256sum "${BASH_SOURCE[0]}" | awk '{print $1}')"
run_cmd_sha="$(sha256sum "${RUN_CMD}" | awk '{print $1}')"
"${PYTHON}" - "${CUTOFF_RELEASE}" "${resume_v3_sha}" "${run_cmd_sha}" <<'PY'
from datetime import datetime
from pathlib import Path
import sys

path = Path(sys.argv[1])
expected_resume_sha = sys.argv[2]
expected_run_cmd_sha = sys.argv[3]
records: dict[str, str] = {}
for raw_line in path.read_text(encoding="utf-8").splitlines():
    if not raw_line or "=" not in raw_line:
        raise RuntimeError("cutoff release contains an invalid line")
    key, value = raw_line.split("=", 1)
    if not key or not value or key in records:
        raise RuntimeError("cutoff release contains an empty or duplicate field")
    records[key] = value
expected = {
    "schema_version": "1",
    "event": "stage_e_long_tail_cutoff_release",
    "formal_job": "316115",
    "supplement_job": "316415",
    "supplement_final_state": "FAILED_expected_user_cutoff",
    "supplement_elapsed": "06:04:02",
    "run_id": "adaligand_ag_20260711T154658",
    "authorization": "user_explicit_2026-07-13_four_hour_long_tail_cutoff",
    "deadline": "2026-07-13T19:54:19+08:00",
    "predecision_sha256": "40e7c949df528b81e1c4a8ee8bbd60daec5ec4d06089037e64958f08fd5458a8",
    "posttermination_sha256": "0f20f20cae3b9958cfe3fd3085233782b2e2e5533144cec704fa22dec2d97397",
    "before_manifest_sha256": "b586cab20644c3cc8fb1f4e0eaa7eead4cff0d496a862c2313b5e0c1847257fe",
    "after_manifest_sha256": "380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f",
    "summary_sha256": "f4a26a9359519e4b94b9f28ecdb21645929c018a014729feadb44b29eadf4761",
    "cutoff_code_sha256": "509672275f61e84a22b5e56c4842a3904769736dddeafe98802f9d19f7197b54",
    "cutoff_cli_sha256": "bb600c7bf5632af2fc575cd6f1f992a38210aaecbdc55ca568dd1895d26c490e",
    "remote_tests": "207_passed",
    "resume_v3_sha256": expected_resume_sha,
    "run_cmd_sha256": expected_run_cmd_sha,
}
if set(records) != set(expected) | {"released_at"}:
    raise RuntimeError("cutoff release field set drift")
for field, value in expected.items():
    if records.get(field) != value:
        raise RuntimeError(f"cutoff release field mismatch: {field}")
released_at = datetime.fromisoformat(records["released_at"])
if released_at.tzinfo is None:
    raise RuntimeError("cutoff release timestamp lacks timezone")
PY

# 独立验证 summary、四条 run-only exclusion、标准 Chimera 证据与当前公共产物状态。
PYTHONPATH="${CODE_ROOT}/code" "${PYTHON}" - \
    "${DATA_ROOT}" "${FORMAL}" "${CUTOFF_SUMMARY}" "${CUTOFF_DIR}" "${EXPECTED_AFTER_SHA}" <<'PY'
import json
from pathlib import Path
import sys

from exclusions import load_run_exclusions

root = Path(sys.argv[1])
run_id = sys.argv[2]
summary_path = Path(sys.argv[3])
cutoff_dir = Path(sys.argv[4])
after_sha = sys.argv[5]
summary = json.loads(summary_path.read_text(encoding="utf-8"))
expected_fields = {
    "schema_version": 1,
    "status": "success",
    "event": "stage_e_user_authorized_long_tail_cutoff_release",
    "run_id": run_id,
    "authorization": "user_explicit_2026-07-13_four_hour_long_tail_cutoff",
    "decision_scope": "current_run_only",
    "supplement_job_id": 316415,
    "supplement_run_id": "adaligand_ag_20260711T154658_eeng_supp48_v2",
    "execution_method": "standard_chimera_molmap_on_canonical_grid",
    "configured_timeout_seconds": 21600,
    "supplement_elapsed_at_predecision": "05:53:56",
    "supplement_elapsed_at_posttermination": "06:03:46",
    "deadline": "2026-07-13T19:54:19+08:00",
    "predecision_sha256": "40e7c949df528b81e1c4a8ee8bbd60daec5ec4d06089037e64958f08fd5458a8",
    "posttermination_sha256": "0f20f20cae3b9958cfe3fd3085233782b2e2e5533144cec704fa22dec2d97397",
    "before_manifest_sha256": "b586cab20644c3cc8fb1f4e0eaa7eead4cff0d496a862c2313b5e0c1847257fe",
    "after_manifest_sha256": after_sha,
    "existing_exclusion_ids": ["8ckb"],
    "candidate_completed_ids": ["8j07", "9dp7", "9qwt"],
    "added_exclusion_ids": ["8glv", "9e5c", "9fqr"],
    "final_exclusion_ids": ["8ckb", "8glv", "9e5c", "9fqr"],
    "policy": "run-only E/F exclusion; formal Stage E revalidates all non-excluded artifacts",
}
for field, value in expected_fields.items():
    if summary.get(field) != value:
        raise RuntimeError(f"cutoff summary field mismatch: {field}")
expected_paths = {
    "predecision_path": cutoff_dir / "predecision.json",
    "posttermination_path": cutoff_dir / "posttermination.json",
    "before_manifest_path": cutoff_dir / "exclusions.before.jsonl",
    "after_manifest_path": cutoff_dir / "exclusions.after.jsonl",
}
for field, path in expected_paths.items():
    if summary.get(field) != str(path):
        raise RuntimeError(f"cutoff summary path mismatch: {field}")

final_ids = {"8ckb", "8glv", "9e5c", "9fqr"}
added_ids = {"8glv", "9e5c", "9fqr"}
for stage in ("stage_e", "stage_f"):
    records, digest = load_run_exclusions(root, run_id, stage)
    if set(records) != final_ids or digest != after_sha:
        raise RuntimeError(f"unexpected {stage} run exclusion identity")
    for pdb_id, record in records.items():
        if record["downstream_policy"] != "exclude_from_training_and_inference":
            raise RuntimeError(f"unexpected downstream policy: {pdb_id}")
    for pdb_id in added_ids:
        record = records[pdb_id]
        evidence = record["evidence"]
        if record["reason"] != "user_authorized_stage_e_long_tail_cutoff":
            raise RuntimeError(f"unexpected cutoff reason: {pdb_id}")
        checks = {
            "deadline": "2026-07-13T19:54:19+08:00",
            "supplement_job_id": 316415,
            "supplement_run_id": "adaligand_ag_20260711T154658_eeng_supp48_v2",
            "execution_method": "standard_chimera_molmap_on_canonical_grid",
            "standard_chimera_timeout_seconds": 21600,
            "supplement_elapsed_at_predecision": "05:53:56",
            "supplement_elapsed_at_posttermination": "06:03:46",
            "complete_artifact_trio": False,
            "predecision_sha256": "40e7c949df528b81e1c4a8ee8bbd60daec5ec4d06089037e64958f08fd5458a8",
            "posttermination_sha256": "0f20f20cae3b9958cfe3fd3085233782b2e2e5533144cec704fa22dec2d97397",
        }
        for field, value in checks.items():
            if evidence.get(field) != value:
                raise RuntimeError(f"cutoff evidence mismatch for {pdb_id}: {field}")
        scratch_names = {Path(item["path"]).name for item in evidence["scratch_molmap_evidence_at_cutoff"]}
        if scratch_names != {
            "canonical_exp.mrc",
            "molmap.py",
            "molmap.stderr.log",
            "molmap.stdout.log",
            "receptor_atom_only.cif",
        }:
            raise RuntimeError(f"cutoff scratch evidence mismatch: {pdb_id}")

for pdb_id in ("8j07", "9dp7", "9qwt"):
    for name in ("exp.npz", "sim.npz", "ligand_area.npz"):
        path = root / "density" / pdb_id / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"completed cutoff candidate lost artifact: {pdb_id}/{name}")
for pdb_id in added_ids:
    for name in ("sim.npz", "ligand_area.npz"):
        if (root / "density" / pdb_id / name).exists():
            raise RuntimeError(f"cutoff exclusion gained an unaudited artifact: {pdb_id}/{name}")
if (root / "density" / "8ckb" / "sim.npz").exists():
    raise RuntimeError("8ckb gained an unaudited simulated map")
PY

# 分类当前正式 E 状态：unknown 或旧 manifest provenance 需要重跑；完整当前状态只重跑 gate。
need_formal_e="$(
    PYTHONPATH="${CODE_ROOT}/code" "${PYTHON}" - \
        "${DATA_ROOT}" "${FORMAL}" "${EXPECTED_AFTER_SHA}" <<'PY'
from pathlib import Path
import sys

from exclusions import load_run_exclusions
from io_utils import read_jsonl
from reports import StageStatus

root = Path(sys.argv[1])
run_id = sys.argv[2]
manifest_sha = sys.argv[3]
expected = {str(row["pdb_id"]).lower() for row in read_jsonl(root / "raw" / "pair_list.jsonl")}
paths = sorted((root / "reports" / "runs" / run_id / "stage_e").glob("status.part_*_of_*.jsonl"))
if not paths:
    raise RuntimeError("formal Stage E status is missing")
valid_statuses = {item.value for item in StageStatus}
statuses: dict[str, dict] = {}
for path in paths:
    for record in read_jsonl(path):
        pdb_id = str(record.get("pdb_id", "")).lower()
        if record.get("stage") != "stage_e" or record.get("status") not in valid_statuses:
            raise RuntimeError(f"invalid formal Stage E status row: {pdb_id}")
        if not pdb_id or pdb_id in statuses:
            raise RuntimeError(f"duplicate/empty formal Stage E status: {pdb_id}")
        statuses[pdb_id] = record
if set(statuses) != expected:
    missing = sorted(expected.difference(statuses))
    extra = sorted(set(statuses).difference(expected))
    raise RuntimeError(f"formal Stage E coverage drift: missing={missing[:20]}, extra={extra[:20]}")

exclusions, digest = load_run_exclusions(root, run_id, "stage_e")
if digest != manifest_sha or set(exclusions) != {"8ckb", "8glv", "9e5c", "9fqr"}:
    raise RuntimeError("formal Stage E exclusion manifest drift")
outside = [
    pdb_id
    for pdb_id, record in statuses.items()
    if record.get("reason") == "run_policy_excluded" and pdb_id not in exclusions
]
if outside:
    raise RuntimeError(f"run_policy_excluded leaked outside the manifest: {outside[:20]}")

unknown = any(record["status"] == StageStatus.UNKNOWN_FAILED.value for record in statuses.values())
provenance_current = True
for pdb_id, exclusion in exclusions.items():
    record = statuses[pdb_id]
    expected_fields = {
        "status": StageStatus.KNOWN_FAILED.value,
        "reason": "run_policy_excluded",
        "exclusion_reason": exclusion["reason"],
        "exclusion_run_id": run_id,
        "exclusion_authorization": exclusion["authorization"],
        "exclusion_decision_scope": "current_run_only",
        "exclusion_downstream_policy": "exclude_from_training_and_inference",
        "exclusion_evidence": exclusion["evidence"],
        "exclusion_manifest_sha256": manifest_sha,
    }
    if any(record.get(field) != value for field, value in expected_fields.items()):
        provenance_current = False
if unknown or not provenance_current:
    print("run")
else:
    print("skip")
PY
)"
if [[ "${formal_stage_e_sha}" == "${INITIAL_STAGE_E_SHA}" ]]; then
    echo "[ResumeV3] formal Stage E starts from the frozen initial status"
fi

# try_lock 仍存在时允许只跑完整证据/状态预检；正式 core 不设置该变量。
if [[ "${VALIDATE_ONLY:-0}" == "1" ]]; then
    echo "[ResumeV3] validation-only decision=${need_formal_e}"
    exit 0
elif [[ "${VALIDATE_ONLY:-0}" != "0" ]]; then
    echo "VALIDATE_ONLY must be 0 or 1" >&2
    exit 1
fi

if [[ "${need_formal_e}" == "run" ]]; then
    "${PYTHON}" scripts/e_density.py \
        --root "${DATA_ROOT}" \
        --chimera "${CHIMERA}" \
        --scratch_root "${SCRATCH_ROOT}" \
        --n_jobs 24 \
        --timeout_seconds 21600 \
        --run_id "${FORMAL}"
elif [[ "${need_formal_e}" == "skip" ]]; then
    echo "[ResumeV3] formal Stage E already has complete current-manifest provenance; rerunning gate only"
else
    echo "unexpected Stage E resume decision: ${need_formal_e}" >&2
    exit 1
fi

"${PYTHON}" scripts/stage_release_gate.py \
    --root "${DATA_ROOT}" \
    --run_id "${FORMAL}" \
    --stages stage_d,stage_e \
    --gate_name de_release
