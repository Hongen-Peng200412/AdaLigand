# 按固定清单预取 Stage C CCD 依赖的命令入口。
# 实际逻辑：调用 Stage C 化学组分字典缓存维护模块执行检查并写入报告。
# 输入/输出：冻结 CCD 清单 → cache 命中/缺失审计；不直接替代 c_parse。
# 关键边界：入口负责参数和退出码，依赖是否足够由后续 gate 判定。
"""按冻结 CCD ID 清单执行显式 cache prefetch，并写 run-scoped 审计证据。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from pathlib import Path
import re

from joblib import Parallel, delayed



from adaligand_preprocessing.ops.stage_c_ccd import CCD_PREFETCH_SCHEMA_VERSION, prefetch_and_audit_ccd
from adaligand_preprocessing.utils.io import sha256_file, write_jsonl
from adaligand_preprocessing.artifacts.reports import resolve_run_id, write_report


def main() -> None:
    """补足冻结清单中的 CCD cache；任何单项失败都阻断后续 source audit。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ccd_ids_file", type=Path, required=True)
    parser.add_argument("--ids_sha256", required=True)
    parser.add_argument("--expected_count", type=int, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--n_jobs", type=int, required=True)
    args = parser.parse_args()
    args.run_id = resolve_run_id(args.run_id)

    payload = args.ccd_ids_file.read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != args.ids_sha256.lower():
        raise RuntimeError(f"CCD ids sha256 {actual_hash} != expected {args.ids_sha256}")
    ccd_ids = _parse_ccd_ids(payload, args.ccd_ids_file)
    if len(ccd_ids) != args.expected_count:
        raise RuntimeError(f"CCD ids count {len(ccd_ids)} != expected {args.expected_count}")

    report_dir = args.root / "reports" / "runs" / args.run_id / "stage_c_ccd_prefetch"
    records = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(_prefetch_one)(args.root, ccd_id) for ccd_id in ccd_ids
    )
    records_path = report_dir / "records.jsonl"
    write_jsonl(records_path, records)
    counts = Counter(str(record["status"]) for record in records)
    summary = {
        "status": "success" if not counts.get("failed", 0) else "failed",
        "schema_version": CCD_PREFETCH_SCHEMA_VERSION,
        "run_id": args.run_id,
        "ccd_ids_path": str(args.ccd_ids_file),
        "ccd_ids_sha256": actual_hash,
        "n_records": len(records),
        "counts": dict(sorted(counts.items())),
        "records_sha256": sha256_file(records_path),
        "policy": "prefetch is the only network-enabled step; subsequent audit/apply are cache-only",
    }
    write_report(report_dir / "summary.json", summary)
    if counts.get("failed", 0):
        raise RuntimeError(f"CCD prefetch failed: {dict(sorted(counts.items()))}")


def _parse_ccd_ids(payload: bytes, source: Path) -> list[str]:
    """从同一份已哈希字节解析排序、去重且仅含字母数字的 CCD id。"""
    raw_ids = [line.strip().upper() for line in payload.decode("utf-8").splitlines()]
    ccd_ids = [value for value in raw_ids if value]
    invalid = [value for value in ccd_ids if re.fullmatch(r"[A-Z0-9]{1,8}", value) is None]
    if invalid:
        raise ValueError(f"invalid CCD ids in {source}: {invalid[:10]}")
    if len(ccd_ids) != len(set(ccd_ids)):
        raise ValueError(f"duplicate CCD ids in {source}")
    return sorted(ccd_ids)


def _prefetch_one(root: Path, ccd_id: str) -> dict:
    """把单 CCD 异常转成完整 failed record，保留批次级诊断证据。"""
    try:
        return {"status": "success", **prefetch_and_audit_ccd(root, ccd_id)}
    except Exception as exc:
        return {
            "status": "failed",
            "ccd_id": ccd_id,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "schema_version": CCD_PREFETCH_SCHEMA_VERSION,
        }


if __name__ == "__main__":
    main()
