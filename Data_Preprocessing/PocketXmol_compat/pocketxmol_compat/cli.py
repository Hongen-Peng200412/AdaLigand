"""批量生成两套 Stage3 兼容缓存和两份资格清单。"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pocketxmol_compat.adapter import adapt_occurrence
from pocketxmol_compat.ccd_audit import load_ccd_audit
from pocketxmol_compat.io import atomic_write_json, write_jsonl
from pocketxmol_compat.records import AdaptRequest, AdaptResult
from pocketxmol_compat.selection import load_selections


def build_parser() -> argparse.ArgumentParser:
    """构造正式批量适配命令行。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-c-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pocketxmol-root", type=Path, required=True)
    parser.add_argument(
        "--ccd-audit",
        type=Path,
        required=True,
        help="由 A–G 环境生成的 source_chemistry_audit.json。",
    )
    parser.add_argument(
        "--split",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="可重复传入 train/validation/calibration 的官方 Stage1 JSON 或 JSONL 清单。",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="0 表示使用节点全部逻辑 CPU；服务器可直接使用最多192核。",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行批量适配；未知内部错误进入审计文件并令进程返回非零。"""

    args = build_parser().parse_args(argv)
    selections = load_selections(args.split, args.stage_c_root)
    load_ccd_audit(args.ccd_audit.resolve())
    workers = args.workers or (os.cpu_count() or 1)
    requests = [
        AdaptRequest(
            stage_c_root=args.stage_c_root,
            output_root=args.output_root,
            pocketxmol_root=args.pocketxmol_root,
            ccd_audit_path=args.ccd_audit,
            pdb_id=str(row["pdb_id"]),
            candidate_id=int(row["candidate_id"]),
            split=str(row["split"]),
            overwrite=args.overwrite,
        )
        for row in selections
    ]

    results: list[AdaptResult] = []
    errors: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(adapt_occurrence, request): request for request in requests}
        for future in as_completed(futures):
            request = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append(
                    {
                        "pdb_id": request.pdb_id.lower(),
                        "candidate_id": request.candidate_id,
                        "split": request.split,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )

    results.sort(key=lambda item: (item.split, item.pdb_id, item.candidate_id))
    errors.sort(key=lambda item: (item["split"], item["pdb_id"], item["candidate_id"]))
    audit_rows = [result.to_json() for result in results]
    audit_rows.extend({**row, "status": "internal_error"} for row in errors)
    write_jsonl(args.output_root / "reports" / "adaptation_audit.jsonl", audit_rows)
    write_jsonl(
        args.output_root / "manifests" / "pocketxmol_eligible.jsonl",
        [result.to_json() for result in results if result.pocketxmol_eligible],
    )
    write_jsonl(
        args.output_root / "manifests" / "extended_contract_eligible.jsonl",
        [
            {**result.to_json(), "active_for_stage3": False}
            for result in results
            if result.extended_contract_eligible
        ],
    )
    reason_counts = Counter(reason for result in results for reason in result.reasons)
    atomic_write_json(
        args.output_root / "reports" / "summary.json",
        {
            "requested": len(requests),
            "completed": len(results),
            "internal_errors": len(errors),
            "pocketxmol_eligible": sum(result.pocketxmol_eligible for result in results),
            "extended_contract_eligible": sum(
                result.extended_contract_eligible for result in results
            ),
            "filter_reason_counts": dict(sorted(reason_counts.items())),
            "workers": workers,
        },
    )
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
