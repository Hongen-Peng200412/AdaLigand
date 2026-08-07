"""批量生成两套 Stage3 兼容缓存和两份资格清单。"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pocketxmol_compat.adapter import adapt_occurrence
from pocketxmol_compat.io import atomic_write_json, read_jsonl, write_jsonl
from pocketxmol_compat.records import AdaptRequest, AdaptResult


def build_parser() -> argparse.ArgumentParser:
    """构造正式批量适配命令行。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-c-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pocketxmol-root", type=Path, required=True)
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
    selections = _load_selections(args.split)
    workers = args.workers or (os.cpu_count() or 1)
    requests = [
        AdaptRequest(
            stage_c_root=args.stage_c_root,
            output_root=args.output_root,
            pocketxmol_root=args.pocketxmol_root,
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


def _load_selections(specifications: list[str]) -> list[dict[str, Any]]:
    """读取 `NAME=PATH` 清单并只保留实例身份与既有划分。"""

    output: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for specification in specifications:
        if "=" not in specification:
            raise ValueError(f"invalid --split value: {specification!r}")
        split, raw_path = specification.split("=", 1)
        if split not in {"train", "validation", "calibration"}:
            raise ValueError(f"unsupported split: {split!r}")
        path = Path(raw_path)
        if path.suffix.lower() == ".jsonl":
            rows = read_jsonl(path)
        else:
            with path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if not isinstance(payload, list):
                raise ValueError(f"split JSON must contain a list: {path}")
            rows = payload
        for row in rows:
            key = (str(row["pdb_id"]).lower(), int(row["candidate_id"]))
            if key in seen:
                raise ValueError(f"duplicate or cross-split instance: {key[0]}:{key[1]}")
            seen.add(key)
            output.append({"pdb_id": key[0], "candidate_id": key[1], "split": split})
    return output


if __name__ == "__main__":
    raise SystemExit(main())
