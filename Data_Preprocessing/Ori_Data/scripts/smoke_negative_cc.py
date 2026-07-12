"""用真实 Chimera 验证正确配对 CC 显著优于 12 Å 错位模拟图。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

import numpy as np


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from chimera import ChimeraRunner
from contracts import load_npz_arrays
from io_utils import read_jsonl
from model_cif import write_normalized_model_cif
from mrc import MapGrid, load_map, write_canonical_mrc
from reports import write_report
from smoke_checks import NEGATIVE_CC_FIELDS, negative_cc_errors, shift_grid_x_no_wrap


CC_FIELDS = (
    "cc_contour",
    "cc_contour_about_mean",
    "cc_all",
    "cc_all_about_mean",
)


def main() -> None:
    """重建匹配 full-model sim，构造不环绕错位图并写可审计报告。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pdb_id", default="5mkf")
    parser.add_argument("--chimera", type=Path, required=True)
    parser.add_argument("--scratch_root", type=Path, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--shift_voxels", type=int, default=12)
    parser.add_argument("--minimum_drop", type=float, default=0.05)
    args = parser.parse_args()

    pdb_id = args.pdb_id.lower()
    exp = load_npz_arrays(args.root / "density" / pdb_id / "exp.npz", allow_pickle=False)
    quality_records = read_jsonl(args.root / "quality" / f"{pdb_id}.jsonl")
    if not quality_records:
        raise RuntimeError(f"quality records are missing for {pdb_id}")
    first_record = quality_records[0]
    resolution = float(first_record["map_resolution"])
    contour = float(exp["contour"]) if bool(exp["contour_present"]) else None

    scratch_dir = (
        args.scratch_root
        / args.run_id
        / "smoke_negative_cc"
        / pdb_id
        / uuid4().hex
    )
    scratch_dir.mkdir(parents=True, exist_ok=False)
    model_path = scratch_dir / "full_model.cif"
    exp_mrc_path = scratch_dir / "canonical_exp.mrc"
    matched_mrc_path = scratch_dir / "matched_sim.mrc"
    shifted_mrc_path = scratch_dir / "shifted_sim.mrc"

    write_normalized_model_cif(
        args.root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif",
        model_path,
        atom_only=False,
    )
    exp_grid = MapGrid(exp["grid"][0], exp["voxel_size"], exp["origin"])
    write_canonical_mrc(exp_mrc_path, exp_grid)
    runner = ChimeraRunner([str(args.chimera)])
    runner.molmap_on_grid(
        model_path,
        exp_mrc_path,
        matched_mrc_path,
        resolution=resolution,
        scratch_dir=scratch_dir,
    )
    matched_values, matched_result = runner.measure_correlations(
        exp_mrc_path,
        matched_mrc_path,
        contour=contour,
        scratch_dir=scratch_dir / "matched_cc",
    )

    matched_grid = load_map(matched_mrc_path, multiply_global_origin=False)
    shifted_grid = shift_grid_x_no_wrap(matched_grid.grid, args.shift_voxels)
    write_canonical_mrc(
        shifted_mrc_path,
        MapGrid(shifted_grid, matched_grid.voxel_size, matched_grid.origin),
    )
    shifted_values, shifted_result = runner.measure_correlations(
        exp_mrc_path,
        shifted_mrc_path,
        contour=contour,
        scratch_dir=scratch_dir / "shifted_cc",
    )

    stored_values = {field: first_record[field] for field in CC_FIELDS}
    errors = negative_cc_errors(
        matched_values,
        shifted_values,
        minimum_drop=args.minimum_drop,
    )
    for field in CC_FIELDS:
        stored = stored_values[field]
        matched = matched_values[field]
        if stored is None or matched is None:
            if stored is not matched:
                errors.append(f"negative_cc:{field}:stored_mismatch")
        elif not np.isclose(float(stored), float(matched), rtol=0, atol=1e-6):
            errors.append(f"negative_cc:{field}:stored_mismatch")
    if errors:
        raise RuntimeError(f"real negative CC smoke failed: {errors}")

    report_path = (
        args.root
        / "reports"
        / "runs"
        / args.run_id
        / "smoke_negative_cc.json"
    )
    write_report(
        report_path,
        {
            "pdb_id": pdb_id,
            "shift_axis": "world_x",
            "shift_voxels": args.shift_voxels,
            "shift_angstrom": float(args.shift_voxels * matched_grid.voxel_size[0]),
            "minimum_required_drop": args.minimum_drop,
            "stored_cc": stored_values,
            "matched_cc": matched_values,
            "shifted_cc": shifted_values,
            "observed_drop": {
                field: float(matched_values[field] - shifted_values[field])
                for field in NEGATIVE_CC_FIELDS
            },
            "logs": {
                "matched_stdout": str(matched_result.stdout_path.relative_to(args.scratch_root)),
                "matched_stderr": str(matched_result.stderr_path.relative_to(args.scratch_root)),
                "shifted_stdout": str(shifted_result.stdout_path.relative_to(args.scratch_root)),
                "shifted_stderr": str(shifted_result.stderr_path.relative_to(args.scratch_root)),
            },
        },
    )
    for path in (model_path, exp_mrc_path, matched_mrc_path, shifted_mrc_path):
        path.unlink(missing_ok=True)
    print(report_path)


if __name__ == "__main__":
    main()
