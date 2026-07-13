# 学习导航：功能分区=数据契约与质量验证；生命周期=审计/测试辅助入口。
# 实际逻辑：调用 code/mrc.py、density.py、chimera.py，对真实样本做局部几何 smoke。
# 输入/输出：小规模结构/map → shape、origin、voxel、三维内容和 Chimera 几何报告。
# 关键边界：smoke 不替代 Stage E 全量，也不写正式全量产物或改变主流程。
"""用真实 Chimera 验证 Pocket canonical grid 与 generated MRC 的几何闭环。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import mrcfile
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from chimera import ChimeraRunner
from contracts import load_npz_arrays
from io_utils import read_jsonl, sha256_file
from model_cif import write_normalized_model_cif
from mrc import (
    POCKET_RESAMPLE_MIXED_COMPAT,
    MapGrid,
    canonicalization_info,
    load_map,
    make_canonical_grid,
    write_canonical_mrc,
)
from parallel import filter_pair_records, read_pdb_id_filter
from qc import density_pair_errors
from reports import write_report


def _header_snapshot(path: Path) -> dict[str, Any]:
    """
    读取 MRC header 中影响世界坐标映射的字段。

    输入参数:
        - path: Path, 待核验的未压缩 MRC 文件

    输出:
        - header: dict[str, Any], 包含:
            - ``storage_shape_zyx``: list[int], 文件数组 shape
            - ``voxel_size_xyz``: list[float], XYZ 实际体素大小
            - ``origin_xyz``: list[float], header.origin 的 XYZ 值
            - ``nstart_crs``: list[int], nxstart/nystart/nzstart
            - ``mapc_mapr_maps``: list[int], column/row/section 物理轴编号
    """
    with mrcfile.open(str(path), mode="r") as handle:
        return {
            "storage_shape_zyx": [int(value) for value in handle.data.shape],
            "voxel_size_xyz": [
                float(handle.voxel_size.x),
                float(handle.voxel_size.y),
                float(handle.voxel_size.z),
            ],
            "origin_xyz": [
                float(handle.header.origin.x),
                float(handle.header.origin.y),
                float(handle.header.origin.z),
            ],
            "nstart_crs": [
                int(handle.header.nxstart),
                int(handle.header.nystart),
                int(handle.header.nzstart),
            ],
            "mapc_mapr_maps": [
                int(handle.header.mapc),
                int(handle.header.mapr),
                int(handle.header.maps),
            ],
        }


def _geometry_errors(
    canonical: MapGrid,
    simulated: MapGrid,
    canonical_header: dict[str, Any],
    simulated_header: dict[str, Any],
    receptor_coords: np.ndarray,
) -> list[str]:
    """
    验证 canonical MRC、Chimera 输出和重新加载结果使用同一世界坐标网格。

    输入参数:
        - canonical: MapGrid, Pocket canonical 实验图
        - simulated: MapGrid, Chimera generated 模拟图
        - canonical_header: dict[str, Any], canonical MRC header 快照
        - simulated_header: dict[str, Any], generated MRC header 快照
        - receptor_coords: np.ndarray, (N,3), Stage C 受体世界 XYZ 坐标 Å

    输出:
        - errors: list[str], 空列表表示全部几何与三维内容门禁通过
    """
    exp_arrays = {
        "grid": canonical.grid[None],
        "voxel_size": canonical.voxel_size,
        "origin": canonical.origin,
    }
    sim_arrays = {
        "grid": simulated.grid[None],
        "voxel_size": simulated.voxel_size,
        "origin": simulated.origin,
    }
    errors = density_pair_errors(exp_arrays, sim_arrays, receptor_coords)
    for name, header in (
        ("canonical", canonical_header),
        ("simulated", simulated_header),
    ):
        if header["mapc_mapr_maps"] != [1, 2, 3]:
            errors.append(f"{name}_header:axis_mapping")
        if header["nstart_crs"] != [0, 0, 0]:
            errors.append(f"{name}_header:nstart")
        if not np.allclose(
            header["origin_xyz"],
            canonical.origin,
            rtol=0,
            atol=1e-5,
        ):
            errors.append(f"{name}_header:origin")
        if not np.allclose(
            header["voxel_size_xyz"],
            canonical.voxel_size,
            rtol=0,
            atol=1e-6,
        ):
            errors.append(f"{name}_header:voxel_size")
    return errors


def _markdown_report(summary: dict[str, Any]) -> str:
    """
    把机器 summary 写成无上下文工程师可阅读的 Markdown 验收报告。

    输入参数:
        - summary: dict[str, Any], 本次真实 smoke 的完整机器证据

    输出:
        - markdown: str, 自包含 Markdown 文本
    """
    lines = [
        "# AdaLigand 真实 MRC 几何 smoke 报告",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "## 目的",
        "",
        "本 smoke 不写正式 Stage E 产物。它直接读取正式 native EMDB map 和 Stage C 受体，",
        "用 Pocket Plus 祖传六函数的 AdaLigand 薄适配生成 canonical grid，再调用真实 Chimera",
        "`molmap onGrid`。验收重点是 actual voxel、非零 origin、shape、标准轴、`nstart=0`",
        "和重新加载后的三维世界坐标是否严格闭合。",
        "",
        "## 结论",
        "",
        f"总体状态：`{summary['status']}`。",
        "",
        "## 样本证据",
        "",
        "| PDB | EMDB | 模式 | native shape ZYX | canonical/sim shape ZYX | actual voxel XYZ | origin XYZ | 错误 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in summary["records"]:
        lines.append(
            "| {pdb} | {emdb} | {mode} | {native} | {shape} | {voxel} | {origin} | {errors} |".format(
                pdb=record["pdb_id"],
                emdb=record["emdb_id"],
                mode=record["resample_mode"],
                native="×".join(str(value) for value in record["native_shape_zyx"]),
                shape="×".join(str(value) for value in record["canonical_shape_zyx"]),
                voxel=", ".join(f"{value:.9g}" for value in record["voxel_size_xyz"]),
                origin=", ".join(f"{value:.9g}" for value in record["origin_xyz"]),
                errors=", ".join(record["errors"]) or "none",
            )
        )
    lines.extend(
        [
            "",
            "每个样本目录保留 `canonical_exp.mrc`、`sim.mrc`、ATOM-only CIF、Chimera 脚本和日志。",
            "机器可读的完整 header、SHA-256 与工具版本见同目录 `summary.json`。",
            "",
            "## 判定口径",
            "",
            "- canonical 和 simulated MRC 都必须为 `mapc/mapr/maps=1/2/3`。",
            "- 两者 `nxstart/nystart/nzstart` 都必须为 0，header.origin 直接保存世界 XYZ Å。",
            "- Chimera 输出重新加载后必须与 canonical 图 shape、actual voxel、origin 逐轴一致。",
            "- 数组必须是真三维、有限、非零且有方差，受体包围盒必须与网格相交。",
            "- 使用 `--require_mixed` 时，每个样本还必须命中已审计的 mixed-axis 薄兼容分支。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    """运行真实 MRC/Chimera 几何 smoke，并原子写 JSON 与 Markdown 证据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--chimera", type=Path, required=True)
    parser.add_argument("--pdb_ids_file", type=Path, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--require_mixed", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        raise FileExistsError(f"smoke output already exists: {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    requested_ids = read_pdb_id_filter(args.pdb_ids_file)
    records = filter_pair_records(read_jsonl(args.root / "raw" / "pair_list.jsonl"), requested_ids)
    found_ids = {str(record["pdb_id"]).lower() for record in records}
    if found_ids != requested_ids:
        raise ValueError(
            f"pdb id filter mismatch: missing={sorted(requested_ids - found_ids)}, "
            f"extra={sorted(found_ids - requested_ids)}"
        )

    runner = ChimeraRunner([str(args.chimera)], timeout_seconds=3600.0)
    chimera_version = runner.probe(args.output_dir / "_probe")
    result_records: list[dict[str, Any]] = []
    for record in records:
        pdb_id = str(record["pdb_id"]).lower()
        emdb_id = str(record["emdb_id"]).upper()
        sample_dir = args.output_dir / pdb_id
        sample_dir.mkdir()
        map_path = args.root / "raw" / "emdb_maps" / f"emd_{emdb_id.replace('EMD-', '')}.map.gz"
        cif_path = args.root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"
        receptor_path = args.root / "parse" / pdb_id / "receptor_tokens.npz"

        native = load_map(map_path, multiply_global_origin=True)
        canonical = make_canonical_grid(native, target_voxel_size=1.0)
        canonical_info = canonicalization_info(native.grid.shape, canonical.grid.shape)
        canonical_path = sample_dir / "canonical_exp.mrc"
        simulated_path = sample_dir / "sim.mrc"
        model_path = sample_dir / "receptor_atom_only.cif"
        model_stats = write_normalized_model_cif(cif_path, model_path, atom_only=True)
        write_canonical_mrc(canonical_path, canonical)
        tool_result = runner.molmap_on_grid(
            model_path,
            canonical_path,
            simulated_path,
            resolution=float(record["resolution"]),
            scratch_dir=sample_dir,
        )
        simulated = load_map(simulated_path, multiply_global_origin=False)
        canonical_header = _header_snapshot(canonical_path)
        simulated_header = _header_snapshot(simulated_path)
        receptor_coords = load_npz_arrays(receptor_path, allow_pickle=False)["coords"]
        errors = _geometry_errors(
            canonical,
            simulated,
            canonical_header,
            simulated_header,
            receptor_coords,
        )
        if args.require_mixed and canonical_info.resample_mode != POCKET_RESAMPLE_MIXED_COMPAT:
            errors.append("resample_mode:not_mixed")
        result_records.append(
            {
                "pdb_id": pdb_id,
                "emdb_id": emdb_id,
                "resolution": float(record["resolution"]),
                "native_shape_zyx": list(native.grid.shape),
                "even_input_shape_zyx": list(canonical_info.even_input_shape_zyx),
                "canonical_shape_zyx": list(canonical.grid.shape),
                "simulated_shape_zyx": list(simulated.grid.shape),
                "voxel_size_xyz": [float(value) for value in canonical.voxel_size],
                "origin_xyz": [float(value) for value in canonical.origin],
                "resample_mode": canonical_info.resample_mode,
                "contour_scale_to_canonical": canonical_info.contour_scale_to_canonical,
                "canonical_header": canonical_header,
                "simulated_header": simulated_header,
                "normalized_model_n_atoms": model_stats["n_atoms"],
                "sha256": {
                    "native_map": sha256_file(map_path),
                    "source_cif": sha256_file(cif_path),
                    "canonical_mrc": sha256_file(canonical_path),
                    "simulated_mrc": sha256_file(simulated_path),
                    "normalized_model": sha256_file(model_path),
                    "chimera_script": sha256_file(sample_dir / "molmap.py"),
                },
                "chimera_elapsed_seconds": tool_result.elapsed_seconds,
                "errors": errors,
            }
        )

    summary = {
        "schema_version": 1,
        "run_id": args.run_id,
        "status": (
            "success"
            if result_records and not any(record["errors"] for record in result_records)
            else "failed"
        ),
        "implementation_sha256": sha256_file(Path(__file__)),
        "chimera_version": chimera_version,
        "pdb_ids_file": str(args.pdb_ids_file),
        "pdb_ids_file_sha256": sha256_file(args.pdb_ids_file),
        "records": result_records,
    }
    write_report(args.output_dir / "summary.json", summary)
    (args.output_dir / "report.md").write_text(_markdown_report(summary), encoding="utf-8")
    if summary["status"] != "success":
        raise RuntimeError("real MRC geometry smoke failed; inspect summary.json")


if __name__ == "__main__":
    main()
