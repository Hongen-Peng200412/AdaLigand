#!/usr/bin/env bash
# 仅用于 Job 316114 的阶段感知 Stage C source 恢复；B 不在本脚本中运行。

set -euo pipefail

FORMAL="adaligand_ag_20260711T154658"
REPAIR="adaligand_ag_20260711T154658_csrc_v4"
POST="adaligand_ag_20260711T154658_csrc_v4_post_exact"
ROOT="/storage/penghongen/AdaLigand/Ori_Data"
CODE="/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data"
PY="/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python"
DIRTY="$ROOT/reports/runs/$FORMAL/source_dirty/mmcif_refreshed_ids.txt"
AUTH="$ROOT/reports/runs/$REPAIR/inputs/authorized_full_rebuild_ids.txt"
CCD="$ROOT/reports/runs/$REPAIR/inputs/required_ccd_ids.txt"
DESCRIPTOR_KEYS="$ROOT/reports/runs/$REPAIR/inputs/required_descriptor_object_keys.txt"
RBS="$ROOT/reports/runs/$REPAIR/stage_c_source_rebuild/audit.summary.json"
GATE="$ROOT/reports/runs/$REPAIR/stage_c_source_repair/audit.summary.json"
RBA="$ROOT/reports/runs/$REPAIR/stage_c_source_rebuild/apply.summary.json"
POSTS="$ROOT/reports/runs/$POST/stage_c_source_repair/audit.summary.json"

DIRTY_SHA="fc6f0068a1cd1529346e90e265c7d5844df38b69d3087bde19b0237d5b135349"
AUTH_SHA="cc61c6709a0bf8210ce2e126d77370482ff90aba20574ac43813f7b192082bf2"
CCD_SHA="1d60b86b1b9415dbdaa8d9f06013c3d5436cb30da8b74d23cf4227d7b853dc68"
DESCRIPTOR_KEYS_SHA="033c5e7ac4d8f023fd34a8b49941f72ce02858d321de7e83598817b5aec1a41c"

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
cd "$CODE"

freeze_inputs() {
    mkdir -p "$(dirname "$AUTH")"
    if [[ ! -e "$AUTH" ]]; then
        local auth_tmp="${AUTH}.tmp.$$"
        printf '%s\n' \
            6gaw 6gb2 6ydp 6ydw 7nqh 7nql 7nsh 7nsi 7nsj 7tql \
            8vvp 8vvq 8vvr 8vvs > "$auth_tmp"
        chmod 0444 "$auth_tmp"
        mv -T "$auth_tmp" "$AUTH"
    fi
    if [[ ! -e "$CCD" ]]; then
        local ccd_tmp="${CCD}.tmp.$$"
        printf '%s\n' 0UO BB9 CH > "$ccd_tmp"
        chmod 0444 "$ccd_tmp"
        mv -T "$ccd_tmp" "$CCD"
    fi
    if [[ ! -e "$DESCRIPTOR_KEYS" ]]; then
        local descriptor_tmp="${DESCRIPTOR_KEYS}.tmp.$$"
        printf '%s\n' 'CCD:5GP' > "$descriptor_tmp"
        chmod 0444 "$descriptor_tmp"
        mv -T "$descriptor_tmp" "$DESCRIPTOR_KEYS"
    fi
    verify_frozen_file "$DIRTY" "$DIRTY_SHA" 2156
    verify_frozen_file "$AUTH" "$AUTH_SHA" 14
    verify_frozen_file "$CCD" "$CCD_SHA" 3
    verify_frozen_file "$DESCRIPTOR_KEYS" "$DESCRIPTOR_KEYS_SHA" 1
}

verify_frozen_file() {
    local path="$1"
    local expected_sha="$2"
    local expected_count="$3"
    [[ -f "$path" && ! -L "$path" ]]
    [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected_sha" ]]
    [[ "$(wc -l < "$path" | tr -d ' ')" == "$expected_count" ]]
}

summary_gate() {
    local path="$1"
    local kind="$2"
    "$PY" - "$path" "$kind" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
kind = sys.argv[2]
summary = json.loads(path.read_text(encoding="utf-8"))
if summary.get("status") != "success":
    raise SystemExit(f"{kind} summary is not successful: {path}")

if kind == "prefetch":
    if summary.get("n_records") != 3 or summary.get("counts") != {"success": 3}:
        raise SystemExit(f"unexpected prefetch summary: {summary}")
elif kind == "descriptor_prefetch":
    if (
        summary.get("object_key_count") != 1
        or summary.get("n_records") != 1
        or summary.get("counts") != {"success": 1}
        or summary.get("implementation_stable") is not True
    ):
        raise SystemExit(f"unexpected descriptor prefetch summary: {summary}")
elif kind == "rebuild_audit":
    if summary.get("authorized_count") != 14:
        raise SystemExit(f"unexpected rebuild authorized count: {summary}")
    if summary.get("classification_counts") != {"full_rebuild_ready": 14}:
        raise SystemExit(f"unexpected rebuild classifications: {summary}")
    expected = {"added": 20, "removed": 0, "reassigned": 1995}
    if summary.get("expected_migration_counts") != expected:
        raise SystemExit(f"unexpected rebuild migration expectations: {summary}")
    actual = summary.get("migration_counts", {})
    if any(actual.get(key, 0) != value for key, value in expected.items()):
        raise SystemExit(f"unexpected rebuild migration counts: {summary}")
elif kind == "preapply":
    counts = summary.get("counts", {})
    allowed = {"exact", "atom_name_only", "delegated_full_rebuild_ready"}
    if (
        summary.get("n_records") != 2156
        or set(counts).difference(allowed)
        or sum(counts.values()) != 2156
        or counts.get("delegated_full_rebuild_ready", 0) != 14
        or counts.get("blocked", 0)
        or counts.get("failed", 0)
    ):
        raise SystemExit(f"unexpected preapply gate: {summary}")
elif kind == "rebuild_apply":
    actions = summary.get("actions", {})
    allowed = {"committed", "already_committed", "committed_after_receipt_recovery"}
    if summary.get("n_records") != 14 or set(actions).difference(allowed) or sum(actions.values()) != 14:
        raise SystemExit(f"unexpected rebuild apply summary: {summary}")
elif kind == "generic_audit":
    counts = summary.get("counts", {})
    if (
        summary.get("n_records") != 2156
        or set(counts).difference({"exact", "atom_name_only"})
        or sum(counts.values()) != 2156
    ):
        raise SystemExit(f"unexpected generic audit summary: {summary}")
elif kind == "generic_apply":
    counts = summary.get("counts", {})
    if (
        summary.get("n_records") != 2156
        or set(counts).difference({"unchanged", "repaired"})
        or sum(counts.values()) != 2156
    ):
        raise SystemExit(f"unexpected generic apply summary: {summary}")
elif kind == "post_exact":
    if summary.get("n_records") != 2156 or summary.get("counts") != {"exact": 2156}:
        raise SystemExit(f"post audit is not all exact: {summary}")
else:
    raise SystemExit(f"unknown summary gate kind: {kind}")
PY
}

run_prefetch() {
    local summary="$ROOT/reports/runs/$REPAIR/stage_c_ccd_prefetch/summary.json"
    if [[ -e "$summary" ]]; then
        summary_gate "$summary" prefetch
        return
    fi
    "$PY" scripts/c_ccd_prefetch.py \
        --root "$ROOT" \
        --ccd_ids_file "$CCD" \
        --ids_sha256 "$CCD_SHA" \
        --expected_count 3 \
        --run_id "$REPAIR" \
        --n_jobs 3
    summary_gate "$summary" prefetch
}

run_descriptor_prefetch() {
    local summary="$ROOT/reports/runs/$REPAIR/stage_c_descriptor_prefetch/summary.json"
    # 每次都调用 CLI；其成功证据复用路径会重新核对清单、实现、源对象和 descriptor 哈希。
    "$PY" scripts/c_descriptor_prefetch.py \
        --root "$ROOT" \
        --object_keys_file "$DESCRIPTOR_KEYS" \
        --keys_sha256 "$DESCRIPTOR_KEYS_SHA" \
        --expected_count 1 \
        --run_id "$REPAIR" \
        --n_jobs 1
    summary_gate "$summary" descriptor_prefetch
}

run_rebuild_audit_once() {
    if [[ -e "$RBS" ]]; then
        summary_gate "$RBS" rebuild_audit
        return
    fi
    "$PY" scripts/c_source_rebuild.py \
        --root "$ROOT" \
        --pdb_ids_file "$AUTH" \
        --ids_sha256 "$AUTH_SHA" \
        --expected_count 14 \
        --dirty_ids_file "$DIRTY" \
        --dirty_ids_sha256 "$DIRTY_SHA" \
        --dirty_expected_count 2156 \
        --repair_run_id "$REPAIR" \
        --mode audit \
        --n_jobs 14 \
        --expected_added 20 \
        --expected_removed 0 \
        --expected_reassigned 1995
    summary_gate "$RBS" rebuild_audit
}

run_preapply_audit_once() {
    local rebuild_sha
    rebuild_sha="$(sha256sum "$RBS" | awk '{print $1}')"
    if [[ -e "$GATE" ]]; then
        summary_gate "$GATE" preapply
        return
    fi
    "$PY" scripts/c_source_repair.py \
        --root "$ROOT" \
        --pdb_ids_file "$DIRTY" \
        --ids_sha256 "$DIRTY_SHA" \
        --expected_count 2156 \
        --repair_run_id "$REPAIR" \
        --mode audit \
        --n_jobs 90 \
        --delegated_rebuild_summary "$RBS" \
        --delegated_rebuild_summary_sha256 "$rebuild_sha"
    summary_gate "$GATE" preapply
}

run_rebuild_apply_idempotent() {
    local gate_sha
    gate_sha="$(sha256sum "$GATE" | awk '{print $1}')"
    if [[ -e "$RBA" ]] && summary_gate "$RBA" rebuild_apply; then
        return
    fi
    "$PY" scripts/c_source_rebuild.py \
        --root "$ROOT" \
        --pdb_ids_file "$AUTH" \
        --ids_sha256 "$AUTH_SHA" \
        --expected_count 14 \
        --dirty_ids_file "$DIRTY" \
        --dirty_ids_sha256 "$DIRTY_SHA" \
        --dirty_expected_count 2156 \
        --repair_run_id "$REPAIR" \
        --mode apply \
        --n_jobs 90 \
        --expected_added 20 \
        --expected_removed 0 \
        --expected_reassigned 1995 \
        --preapply_gate_summary "$GATE" \
        --preapply_gate_sha256 "$gate_sha"
    summary_gate "$RBA" rebuild_apply
}

run_generic_repair_attempts() {
    local attempt run_id audit_summary apply_summary
    for attempt in $(seq 1 10); do
        run_id="${REPAIR}_generic_attempt_${attempt}"
        audit_summary="$ROOT/reports/runs/$run_id/stage_c_source_repair/audit.summary.json"
        apply_summary="$ROOT/reports/runs/$run_id/stage_c_source_repair/apply.summary.json"
        if [[ -e "$apply_summary" ]] && summary_gate "$apply_summary" generic_apply; then
            return
        fi
        # 任何旧 attempt 的不完整/失败证据都保持只读；下一 attempt 从当前 canonical 重新 audit。
        if [[ -e "$audit_summary" || -e "$apply_summary" ]]; then
            continue
        fi
        "$PY" scripts/c_source_repair.py \
            --root "$ROOT" \
            --pdb_ids_file "$DIRTY" \
            --ids_sha256 "$DIRTY_SHA" \
            --expected_count 2156 \
            --repair_run_id "$run_id" \
            --mode audit \
            --n_jobs 90
        summary_gate "$audit_summary" generic_audit
        if "$PY" scripts/c_source_repair.py \
            --root "$ROOT" \
            --pdb_ids_file "$DIRTY" \
            --ids_sha256 "$DIRTY_SHA" \
            --expected_count 2156 \
            --repair_run_id "$run_id" \
            --mode apply \
            --n_jobs 90; then
            summary_gate "$apply_summary" generic_apply
            return
        fi
    done
    echo "No generic source-repair attempt completed successfully" >&2
    return 1
}

run_post_exact_audit() {
    if [[ -e "$POSTS" ]]; then
        summary_gate "$POSTS" post_exact
        return
    fi
    "$PY" scripts/c_source_repair.py \
        --root "$ROOT" \
        --pdb_ids_file "$DIRTY" \
        --ids_sha256 "$DIRTY_SHA" \
        --expected_count 2156 \
        --repair_run_id "$POST" \
        --mode audit \
        --n_jobs 90 \
        --require_all_exact
    summary_gate "$POSTS" post_exact
}

freeze_inputs
"$PY" -m pytest tests -q
run_prefetch
run_descriptor_prefetch
run_rebuild_audit_once
run_preapply_audit_once
run_rebuild_apply_idempotent
run_generic_repair_attempts
run_post_exact_audit

# 只能用原正式 run id 全量刷新 C status；禁止 filter、overwrite 和 Stage B。
"$PY" scripts/c_parse.py \
    --root "$ROOT" \
    --n_jobs 90 \
    --run_id "$FORMAL"
"$PY" scripts/abc_release_gate.py --root "$ROOT" --run_id "$FORMAL"
