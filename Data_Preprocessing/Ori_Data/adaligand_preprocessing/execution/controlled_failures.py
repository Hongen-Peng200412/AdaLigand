# 受控 unknown 清单、证据哈希和默认严格门禁。
# 主要输入：冻结的 stage status、逐行/逐文件 SHA、用户授权、进程与诊断证据、公开产物 0/3 快照。
# 主要输出：保留 raw unknown 的有效状态视图，以及 gate/G 共用的 waiver 身份。
# 关键边界：不修改 raw status、不生成占位产物、不改变科学契约；无显式 waiver 时仍严格阻断 unknown。
"""验证 run-scoped controlled-failure waiver 并构造下游有效状态视图。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from adaligand_preprocessing.utils.io import sha256_file
from adaligand_preprocessing.artifacts.reports import StageStatus
from adaligand_preprocessing.ops.stage_f_process_contract import validate_process_audit


CONTROLLED_FAILURE_WAIVER_SCHEMA_VERSION = 1
CONTROLLED_FAILURE_WAIVER_STAGE = "stage_f"
CONTROLLED_FAILURE_DOWNSTREAM_POLICY = "exclude_from_training_inference_and_stage_g"
_CODE_ROOT = Path(__file__).resolve().parents[2]
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "batch_id",
        "run_id",
        "stage",
        "generated_at_utc",
        "authorization",
        "decision_scope",
        "authorized_cap",
        "existing_run_policy_excluded_count",
        "n_waived",
        "cumulative_controlled_failure_count",
        "scientific_contract_unchanged",
        "no_placeholder_artifacts",
        "downstream_policy",
        "pair_list",
        "status_files",
        "process_audit",
        "code_files",
        "exit_condition",
        "records",
    }
)
_WAIVER_RECORD_FIELDS = frozenset(
    {
        "pdb_id",
        "status_file",
        "status_file_sha256",
        "status_row_sha256",
        "raw_status",
        "raw_reason",
        "raw_error",
        "raw_error_type",
        "classification",
        "attempt",
        "diagnostic_evidence",
        "required_artifacts",
        "scientific_contract_unchanged",
        "no_placeholder_artifacts",
        "downstream_policy",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {"attempt_path", "job_id", "node", "tool_phase", "code_identity"}
)
_FILE_IDENTITY_FIELDS = frozenset({"path", "sha256"})
_PROCESS_AUDIT_FIELDS = frozenset({"path", "sha256", "nodes", "no_active_writers"})
_ARTIFACT_FIELDS = frozenset({"path", "state"})
_REQUIRED_CODE_PATHS = frozenset(
    {
        "adaligand_preprocessing/execution/controlled_failures.py",
        "adaligand_preprocessing/stages/stage_g.py",
        "adaligand_preprocessing/cli/stage_release.py",
        "adaligand_preprocessing/cli/stage_g.py",
        "adaligand_preprocessing/ops/stage_f_processes.py",
        "adaligand_preprocessing/ops/stage_f_process_contract.py",
    }
)


@dataclass(frozen=True)
class ControlledFailureWaiver:
    """
    表示一份已经完整验证的当前 run 受控失败授权。

    输入参数:
        - path: Path, waiver manifest 的正式路径
        - sha256: str, manifest 文件 SHA-256
        - authorized_cap: int, 用户授权的当前 run 累计硬上限
        - cumulative_controlled_failure_count: int, 既有 run-only 排除与本批 waiver 的累计数量
        - records_by_pdb: dict[str,dict[str,Any]], 逐 PDB waiver 原始记录

    输出:
        - 本 dataclass 不执行额外计算；字段供 gate 与 G 报告同一份已验证身份
    """

    path: Path
    sha256: str
    authorized_cap: int
    cumulative_controlled_failure_count: int
    records_by_pdb: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class StageStatusView:
    """
    表示结构完整的 raw stage status 与可选受控失败 overlay。

    输入参数:
        - records_by_pdb: dict[str,dict[str,Any]], 未被修改的 raw status 记录
        - status_paths: list[Path], 被加载的全部 status 分片
        - raw_unknown_by_pdb: dict[str,dict[str,Any]], raw unknown 原始记录
        - waived_by_pdb: dict[str,dict[str,Any]], 本次显式放行且仍从下游排除的记录
        - waiver: ControlledFailureWaiver | None, 已验证 manifest；严格模式为 None

    输出:
        - 本 dataclass 不修改状态；调用方据此分别报告 raw unknown 与 waived 集合
    """

    records_by_pdb: dict[str, dict[str, Any]]
    status_paths: list[Path]
    raw_unknown_by_pdb: dict[str, dict[str, Any]]
    waived_by_pdb: dict[str, dict[str, Any]]
    waiver: ControlledFailureWaiver | None


def canonical_status_row_sha256(record: dict[str, Any]) -> str:
    """
    计算 status JSON 对象的跨文件格式稳定 SHA-256。

    输入参数:
        - record: dict[str,Any], 一条已解析的 status JSON 对象

    输出:
        - digest: str, 按 key 排序、无多余空白且禁止 NaN/Infinity 的 64 位摘要
    """
    payload = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_stage_status_view(
    root: Path,
    run_id: str,
    stage: str,
    expected_pdb_ids: set[str],
    *,
    controlled_failure_waiver_path: Path | None,
    controlled_failure_waiver_sha256: str | None,
    require_fresh_process_audit: bool = True,
) -> StageStatusView:
    """
    读取 stage status，并在显式提供时验证 current-run-only waiver。

    输入参数:
        - root: Path, 数据处理根目录
        - run_id: str, status 与 waiver 必须归属的 run 标识
        - stage: str, 当前 stage 名
        - expected_pdb_ids: set[str], pair_list 或显式子集中的完整 PDB 集合
        - controlled_failure_waiver_path: Path | None, waiver manifest 路径；None 表示严格模式
        - controlled_failure_waiver_sha256: str | None, 调用命令冻结的 manifest SHA；须与路径同时提供
        - require_fresh_process_audit: bool, gate 要求 15 分钟内证据；G 由 f_release 绑定后可重验历史证据

    输出:
        - view: StageStatusView, raw 状态、unknown、waived 与 manifest 身份

    说明:
        结构错误、未列 unknown、额外 waiver、SHA 漂移或公开产物不再为 0/3 都直接失败。
        本函数永远不改写 status，也不会把 waived 项变为 success/known_failed。
    """
    records_by_pdb, status_paths, source_by_pdb = _load_raw_stage_statuses(
        root,
        run_id,
        stage,
        expected_pdb_ids,
    )
    raw_unknown_by_pdb = {
        pdb_id: record
        for pdb_id, record in records_by_pdb.items()
        if record["status"] == StageStatus.UNKNOWN_FAILED.value
    }
    if controlled_failure_waiver_path is None and controlled_failure_waiver_sha256 is None:
        if raw_unknown_by_pdb:
            _raise_unknown_failures(stage, raw_unknown_by_pdb)
        return StageStatusView(
            records_by_pdb=records_by_pdb,
            status_paths=status_paths,
            raw_unknown_by_pdb=raw_unknown_by_pdb,
            waived_by_pdb={},
            waiver=None,
        )
    if controlled_failure_waiver_path is None or controlled_failure_waiver_sha256 is None:
        raise RuntimeError("waiver path and expected SHA-256 must be provided together")
    waiver = _load_controlled_failure_waiver(
        root,
        run_id,
        stage,
        expected_pdb_ids,
        records_by_pdb,
        status_paths,
        source_by_pdb,
        raw_unknown_by_pdb,
        controlled_failure_waiver_path,
        controlled_failure_waiver_sha256,
        require_fresh_process_audit,
    )
    return StageStatusView(
        records_by_pdb=records_by_pdb,
        status_paths=status_paths,
        raw_unknown_by_pdb=raw_unknown_by_pdb,
        waived_by_pdb=waiver.records_by_pdb,
        waiver=waiver,
    )


def _load_raw_stage_statuses(
    root: Path,
    run_id: str,
    stage: str,
    expected_pdb_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], list[Path], dict[str, dict[str, str]]]:
    """加载 raw status 的结构与逐行来源，但暂不决定 unknown 是否可继续。"""
    stage_dir = root / "reports" / "runs" / run_id / stage
    paths = sorted(stage_dir.glob("status.part_*_of_*.jsonl"))
    if not paths:
        raise RuntimeError(f"no run-scoped status files for {run_id}/{stage}")
    records_by_pdb: dict[str, dict[str, Any]] = {}
    source_by_pdb: dict[str, dict[str, str]] = {}
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"status path must be a regular file: {path}")
        relative_path = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        file_sha256 = hashlib.sha256(payload).hexdigest()
        for record in _parse_jsonl_payload(payload, label=f"status file {relative_path}"):
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
            source_by_pdb[pdb_id] = {
                "path": relative_path,
                "file_sha256": file_sha256,
                "row_sha256": canonical_status_row_sha256(record),
            }
    actual = set(records_by_pdb)
    if actual != expected_pdb_ids:
        missing = sorted(expected_pdb_ids.difference(actual))
        extra = sorted(actual.difference(expected_pdb_ids))
        raise RuntimeError(
            f"silent/extra samples in {stage}: missing={missing[:20]}, extra={extra[:20]}"
        )
    return records_by_pdb, paths, source_by_pdb


def _load_controlled_failure_waiver(
    root: Path,
    run_id: str,
    stage: str,
    expected_pdb_ids: set[str],
    records_by_pdb: dict[str, dict[str, Any]],
    status_paths: list[Path],
    source_by_pdb: dict[str, dict[str, str]],
    raw_unknown_by_pdb: dict[str, dict[str, Any]],
    waiver_path: Path,
    expected_waiver_sha256: str,
    require_fresh_process_audit: bool,
) -> ControlledFailureWaiver:
    """验证 manifest 的全局身份、逐行证据和当前文件系统快照。"""
    if stage != CONTROLLED_FAILURE_WAIVER_STAGE:
        raise RuntimeError(f"controlled-failure waiver does not support stage: {stage}")
    waiver_path = _require_path_within_root(root, waiver_path, label="waiver manifest")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_waiver_sha256):
        raise RuntimeError("expected waiver SHA-256 must be 64 lowercase hex characters")
    waiver_payload = waiver_path.read_bytes()
    actual_waiver_sha256 = hashlib.sha256(waiver_payload).hexdigest()
    if actual_waiver_sha256 != expected_waiver_sha256:
        raise RuntimeError(
            f"controlled-failure waiver SHA mismatch: "
            f"expected={expected_waiver_sha256}, actual={actual_waiver_sha256}"
        )
    manifest = _parse_json_object_payload(waiver_payload, label="waiver manifest")
    if not isinstance(manifest, dict) or set(manifest) != _TOP_LEVEL_FIELDS:
        actual_fields = set(manifest) if isinstance(manifest, dict) else set()
        raise RuntimeError(
            "controlled-failure waiver fields mismatch: "
            f"missing={sorted(_TOP_LEVEL_FIELDS.difference(actual_fields))}, "
            f"extra={sorted(actual_fields.difference(_TOP_LEVEL_FIELDS))}"
        )
    _validate_manifest_header(manifest, run_id=run_id, stage=stage)
    _validate_file_identity(
        root,
        manifest["pair_list"],
        expected_path="raw/pair_list.jsonl",
        label="pair_list",
    )
    pair_path = root / "raw" / "pair_list.jsonl"
    pair_payload = pair_path.read_bytes()
    if hashlib.sha256(pair_payload).hexdigest() != manifest["pair_list"]["sha256"]:
        raise RuntimeError("pair_list changed between identity validation and parsing")
    pair_records = _parse_jsonl_payload(pair_payload, label="pair_list")
    pair_id_list = [str(record["pdb_id"]).lower() for record in pair_records]
    pair_ids = set(pair_id_list)
    if len(pair_id_list) != len(pair_ids) or pair_ids != expected_pdb_ids:
        raise RuntimeError("waiver pair_list identity does not match the gate expected PDB set")
    _validate_status_file_identities(root, manifest["status_files"], status_paths)
    process_job_nodes = _validate_process_audit(
        root,
        manifest["process_audit"],
        require_fresh=require_fresh_process_audit,
    )
    _validate_code_files(manifest["code_files"])

    rows = manifest["records"]
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("controlled-failure waiver records must be a non-empty list")
    if (
        not isinstance(manifest["n_waived"], int)
        or isinstance(manifest["n_waived"], bool)
        or manifest["n_waived"] != len(rows)
    ):
        raise RuntimeError("controlled-failure waiver n_waived disagrees with records")
    authorized_cap = manifest["authorized_cap"]
    if not isinstance(authorized_cap, int) or isinstance(authorized_cap, bool) or authorized_cap <= 0:
        raise RuntimeError("controlled-failure waiver authorized_cap must be a positive integer")
    actual_existing_exclusions = sum(
        record["status"] == StageStatus.KNOWN_FAILED.value
        and record.get("reason") == "run_policy_excluded"
        for record in records_by_pdb.values()
    )
    existing_count = manifest["existing_run_policy_excluded_count"]
    if (
        not isinstance(existing_count, int)
        or isinstance(existing_count, bool)
        or existing_count != actual_existing_exclusions
    ):
        raise RuntimeError("existing run_policy_excluded count drifted after waiver authorization")
    expected_cumulative = actual_existing_exclusions + len(rows)
    cumulative_count = manifest["cumulative_controlled_failure_count"]
    if (
        not isinstance(cumulative_count, int)
        or isinstance(cumulative_count, bool)
        or cumulative_count != expected_cumulative
    ):
        raise RuntimeError("controlled-failure waiver cumulative count is inconsistent")
    if expected_cumulative > authorized_cap:
        raise RuntimeError(
            f"controlled-failure waiver exceeds authorized cap: {expected_cumulative}>{authorized_cap}"
        )

    records_by_waived_pdb: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        pdb_id = _validate_waiver_record(
            root,
            row,
            index=index,
            records_by_pdb=records_by_pdb,
            source_by_pdb=source_by_pdb,
            process_job_nodes=process_job_nodes,
        )
        if pdb_id in records_by_waived_pdb:
            raise RuntimeError(f"duplicate controlled-failure waiver PDB id: {pdb_id}")
        records_by_waived_pdb[pdb_id] = row
    if set(records_by_waived_pdb) != set(raw_unknown_by_pdb):
        missing = sorted(set(raw_unknown_by_pdb).difference(records_by_waived_pdb))
        extra = sorted(set(records_by_waived_pdb).difference(raw_unknown_by_pdb))
        raise RuntimeError(
            f"controlled-failure waiver/raw unknown mismatch: missing={missing}, extra={extra}"
        )
    return ControlledFailureWaiver(
        path=waiver_path,
        sha256=actual_waiver_sha256,
        authorized_cap=authorized_cap,
        cumulative_controlled_failure_count=expected_cumulative,
        records_by_pdb=records_by_waived_pdb,
    )


def _validate_manifest_header(manifest: dict[str, Any], *, run_id: str, stage: str) -> None:
    """验证不依赖逐样本内容的 manifest 固定策略字段。"""
    if manifest["schema_version"] != CONTROLLED_FAILURE_WAIVER_SCHEMA_VERSION:
        raise RuntimeError("unsupported controlled-failure waiver schema_version")
    if manifest["run_id"] != run_id or manifest["stage"] != stage:
        raise RuntimeError("controlled-failure waiver run/stage mismatch")
    for field in ("batch_id", "generated_at_utc", "authorization", "exit_condition"):
        if not isinstance(manifest[field], str) or not manifest[field].strip():
            raise RuntimeError(f"controlled-failure waiver {field} must be a non-empty string")
    if manifest["decision_scope"] != "current_run_only":
        raise RuntimeError("controlled-failure waiver must use current_run_only scope")
    if manifest["scientific_contract_unchanged"] is not True:
        raise RuntimeError("controlled-failure waiver cannot change the scientific contract")
    if manifest["no_placeholder_artifacts"] is not True:
        raise RuntimeError("controlled-failure waiver cannot authorize placeholder artifacts")
    if manifest["downstream_policy"] != CONTROLLED_FAILURE_DOWNSTREAM_POLICY:
        raise RuntimeError("controlled-failure waiver downstream policy mismatch")


def _validate_waiver_record(
    root: Path,
    row: Any,
    *,
    index: int,
    records_by_pdb: dict[str, dict[str, Any]],
    source_by_pdb: dict[str, dict[str, str]],
    process_job_nodes: dict[str, str],
) -> str:
    """验证一条 waiver 与 raw status、日志和公开产物快照完全一致。"""
    if not isinstance(row, dict) or set(row) != _WAIVER_RECORD_FIELDS:
        actual_fields = set(row) if isinstance(row, dict) else set()
        raise RuntimeError(
            f"controlled-failure waiver row {index} fields mismatch: "
            f"missing={sorted(_WAIVER_RECORD_FIELDS.difference(actual_fields))}, "
            f"extra={sorted(actual_fields.difference(_WAIVER_RECORD_FIELDS))}"
        )
    pdb_id = str(row["pdb_id"]).lower()
    if not re.fullmatch(r"[0-9a-z]{4}", pdb_id) or pdb_id not in records_by_pdb:
        raise RuntimeError(f"controlled-failure waiver row {index} has invalid pdb_id")
    raw_record = records_by_pdb[pdb_id]
    source = source_by_pdb[pdb_id]
    expected_raw_fields = {
        "raw_status": raw_record["status"],
        "raw_reason": raw_record.get("reason"),
        "raw_error": raw_record.get("error"),
        "raw_error_type": raw_record.get("error_type"),
    }
    if raw_record["status"] != StageStatus.UNKNOWN_FAILED.value or any(
        row[field] != value for field, value in expected_raw_fields.items()
    ):
        raise RuntimeError(f"controlled-failure waiver raw status mismatch for {pdb_id}")
    if (
        row["status_file"] != source["path"]
        or row["status_file_sha256"] != source["file_sha256"]
        or row["status_row_sha256"] != source["row_sha256"]
    ):
        raise RuntimeError(f"controlled-failure waiver status identity mismatch for {pdb_id}")
    if not isinstance(row["classification"], str) or not row["classification"].strip():
        raise RuntimeError(f"controlled-failure waiver classification is empty for {pdb_id}")
    attempt = row["attempt"]
    if not isinstance(attempt, dict) or set(attempt) != _ATTEMPT_FIELDS or any(
        not isinstance(attempt[field], str) or not attempt[field].strip()
        for field in _ATTEMPT_FIELDS
    ):
        raise RuntimeError(f"controlled-failure waiver attempt identity is invalid for {pdb_id}")
    attempt_path = _resolve_relative_path(
        root,
        attempt["attempt_path"],
        label=f"attempt path for {pdb_id}",
    )
    if (root / attempt["attempt_path"]).is_symlink() or not attempt_path.is_dir():
        raise RuntimeError(f"controlled-failure waiver attempt path is invalid for {pdb_id}")
    if process_job_nodes.get(attempt["job_id"]) != attempt["node"]:
        raise RuntimeError(
            f"controlled-failure waiver attempt job/node is not bound to process audit for {pdb_id}"
        )
    evidence = row["diagnostic_evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise RuntimeError(f"controlled-failure waiver evidence is empty for {pdb_id}")
    for item in evidence:
        _validate_file_identity(root, item, expected_path=None, label=f"evidence for {pdb_id}")
    _validate_required_artifacts(root, pdb_id, row["required_artifacts"])
    if row["scientific_contract_unchanged"] is not True:
        raise RuntimeError(f"waiver row changes scientific contract for {pdb_id}")
    if row["no_placeholder_artifacts"] is not True:
        raise RuntimeError(f"waiver row permits placeholder artifacts for {pdb_id}")
    if row["downstream_policy"] != CONTROLLED_FAILURE_DOWNSTREAM_POLICY:
        raise RuntimeError(f"waiver row downstream policy mismatch for {pdb_id}")
    return pdb_id


def _validate_required_artifacts(root: Path, pdb_id: str, snapshot: Any) -> None:
    """要求 Stage F 三件套精确记录为 absent，且当前仍不存在。"""
    if not isinstance(snapshot, list):
        raise RuntimeError(f"required artifact snapshot is not a list for {pdb_id}")
    expected_paths = {
        f"quality/{pdb_id}.jsonl",
        f"quality/{pdb_id}.provenance.json",
        f"quality_atoms/{pdb_id}.npz",
    }
    actual_paths: set[str] = set()
    for item in snapshot:
        if not isinstance(item, dict) or set(item) != _ARTIFACT_FIELDS:
            raise RuntimeError(f"required artifact snapshot fields are invalid for {pdb_id}")
        path = str(item["path"])
        if path in actual_paths or item["state"] != "absent":
            raise RuntimeError(f"required artifact snapshot is not exact absent 0/3 for {pdb_id}")
        actual_paths.add(path)
        artifact_path = _resolve_relative_path(root, path, label=f"required artifact for {pdb_id}")
        if artifact_path.exists() or artifact_path.is_symlink():
            raise RuntimeError(f"waived required artifact is no longer absent: {artifact_path}")
    if actual_paths != expected_paths:
        raise RuntimeError(f"required artifact snapshot does not equal Stage F trio for {pdb_id}")


def _validate_status_file_identities(root: Path, items: Any, status_paths: list[Path]) -> None:
    """验证 manifest 精确覆盖当前 stage 的全部 status 分片。"""
    if not isinstance(items, list) or not items:
        raise RuntimeError("controlled-failure waiver status_files must be non-empty")
    expected = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in status_paths
    }
    actual: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != _FILE_IDENTITY_FIELDS:
            raise RuntimeError("controlled-failure waiver status file identity is invalid")
        path = str(item["path"])
        if path in actual:
            raise RuntimeError(f"duplicate controlled-failure status file identity: {path}")
        _validate_file_identity(root, item, expected_path=path, label="status file")
        actual[path] = str(item["sha256"])
    if actual != expected:
        raise RuntimeError("controlled-failure waiver status file set or SHA drifted")


def _validate_process_audit(
    root: Path,
    item: Any,
    *,
    require_fresh: bool,
) -> dict[str, str]:
    """验证零 writer 进程证据的文件身份和声明节点。"""
    if not isinstance(item, dict) or set(item) != _PROCESS_AUDIT_FIELDS:
        raise RuntimeError("controlled-failure waiver process_audit fields are invalid")
    if item["no_active_writers"] is not True:
        raise RuntimeError("controlled-failure waiver requires a zero-writer process audit")
    nodes = item["nodes"]
    if not isinstance(nodes, list) or not nodes or any(
        not isinstance(node, str) or not node.strip() for node in nodes
    ) or len(nodes) != len(set(nodes)):
        raise RuntimeError("controlled-failure waiver process_audit nodes are invalid")
    audit_path = _require_regular_relative_file(root, item["path"], label="process audit")
    audit_payload = audit_path.read_bytes()
    audit = _parse_json_object_payload(audit_payload, label="process audit")
    raw_job_ids = audit.get("job_ids")
    if not isinstance(raw_job_ids, list) or any(
        not isinstance(job_id, int) or isinstance(job_id, bool)
        for job_id in raw_job_ids
    ):
        raise RuntimeError("controlled-failure waiver process audit job_ids are invalid")
    audit = validate_process_audit(
        audit_path,
        str(item["sha256"]),
        raw_job_ids,
        max_age_seconds=900 if require_fresh else None,
    )
    observed_nodes = {audit["controller_node"], *audit["job_nodes"].values()}
    if observed_nodes != set(nodes):
        raise RuntimeError("controlled-failure waiver process audit node set drifted")
    if any(
        not isinstance(job_id, str)
        or not job_id.strip()
        or not isinstance(node, str)
        or not node.strip()
        for job_id, node in audit["job_nodes"].items()
    ):
        raise RuntimeError("controlled-failure waiver process audit job/node map is invalid")
    return dict(audit["job_nodes"])


def _parse_jsonl_payload(payload: bytes, *, label: str) -> list[dict[str, Any]]:
    """从同一份冻结字节解析 JSONL，供 SHA 与内容共享单次读取。"""
    try:
        text = payload.decode("utf-8")
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is not valid UTF-8 JSONL") from exc
    if any(not isinstance(record, dict) for record in records):
        raise RuntimeError(f"{label} must contain JSON objects only")
    return records


def _parse_json_object_payload(payload: bytes, *, label: str) -> dict[str, Any]:
    """从同一份冻结字节解析单个 JSON 对象。"""
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _validate_code_files(items: Any) -> None:
    """验证 gate 与 G 当前实现仍与授权时冻结的代码完全一致。"""
    if not isinstance(items, list) or not items:
        raise RuntimeError("controlled-failure waiver code_files must be non-empty")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != _FILE_IDENTITY_FIELDS:
            raise RuntimeError("controlled-failure waiver code file identity is invalid")
        relative_path = str(item["path"])
        if relative_path in seen:
            raise RuntimeError(f"duplicate controlled-failure code file identity: {relative_path}")
        seen.add(relative_path)
        path = _require_regular_relative_file(_CODE_ROOT, relative_path, label="code file")
        if sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"controlled-failure waiver code file SHA drifted: {relative_path}")
    if not _REQUIRED_CODE_PATHS.issubset(seen):
        raise RuntimeError(
            "controlled-failure waiver code identity omits gate/G implementation files: "
            f"{sorted(_REQUIRED_CODE_PATHS.difference(seen))}"
        )


def _validate_file_identity(
    root: Path,
    item: Any,
    *,
    expected_path: str | None,
    label: str,
) -> None:
    """验证一个 root-relative 普通文件的路径与 SHA。"""
    if not isinstance(item, dict) or set(item) != _FILE_IDENTITY_FIELDS:
        raise RuntimeError(f"{label} identity fields are invalid")
    relative_path = str(item["path"])
    if expected_path is not None and relative_path != expected_path:
        raise RuntimeError(f"{label} path mismatch: {relative_path}")
    path = _require_regular_relative_file(root, relative_path, label=label)
    digest = str(item["sha256"])
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256_file(path) != digest:
        raise RuntimeError(f"{label} SHA mismatch: {relative_path}")


def _require_path_within_root(root: Path, path: Path, *, label: str) -> Path:
    """要求显式路径位于数据根目录内，且为普通非 symlink 文件。"""
    resolved_root = root.resolve()
    candidate = path if path.is_absolute() else resolved_root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"{label} must stay within data root: {path}") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise RuntimeError(f"{label} must be a regular non-symlink file: {path}")
    return resolved


def _resolve_relative_path(root: Path, relative_path: str, *, label: str) -> Path:
    """把不含目录逃逸的 POSIX 相对路径解析到给定根目录。"""
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"{label} must use a root-relative path: {relative_path}")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"{label} escapes its root: {relative_path}") from exc
    return resolved


def _require_regular_relative_file(root: Path, relative_path: str, *, label: str) -> Path:
    """要求相对路径指向根目录内普通非 symlink 文件。"""
    raw_path = root / Path(relative_path)
    resolved = _resolve_relative_path(root, relative_path, label=label)
    if raw_path.is_symlink() or not resolved.is_file():
        raise RuntimeError(f"{label} must be a regular non-symlink file: {relative_path}")
    return resolved


def _raise_unknown_failures(stage: str, unknown_by_pdb: dict[str, dict[str, Any]]) -> None:
    """保持历史严格错误语义，报告最多二十条 raw unknown 示例。"""
    examples = [
        {
            "pdb_id": item["pdb_id"],
            "reason": item.get("reason"),
            "error": item.get("error"),
        }
        for item in list(unknown_by_pdb.values())[:20]
    ]
    raise RuntimeError(f"{stage} has {len(unknown_by_pdb)} unknown failures: {examples}")
