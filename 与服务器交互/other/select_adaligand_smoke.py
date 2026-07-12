"""从冻结 AdaLigand 样本宇宙中挑选小而有代表性的真实 C–F smoke 样本。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import mrcfile
import numpy as np


MAX_CANDIDATES_PER_FEATURE = 12
FEATURES = ("single_ccd", "branched", "missing_ligand_atom", "nondefault_map_geometry")


def main() -> None:
    """扫描小图候选、检查 MRC header，贪心覆盖四类 smoke 特征并原子写 id 清单。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max_map_bytes", type=int, default=100 * 1024 * 1024)
    parser.add_argument("--n_samples", type=int, default=4)
    args = parser.parse_args()
    pair_path = args.root / "raw" / "pair_list.jsonl"
    records = [json.loads(line) for line in pair_path.read_text(encoding="utf-8").splitlines() if line]
    candidates: dict[str, list[dict[str, Any]]] = {feature: [] for feature in FEATURES[:-1]}
    seen_pdb: set[str] = set()
    n_scanned = 0

    for record in records:
        n_scanned += 1
        pdb_id = str(record["pdb_id"]).lower()
        if pdb_id in seen_pdb:
            continue
        seen_pdb.add(pdb_id)
        try:
            resolution = float(record.get("resolution"))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(resolution) or resolution <= 0:
            continue
        emdb_number = str(record["emdb_id"]).upper().replace("EMD-", "")
        map_path = args.root / "raw" / "emdb_maps" / f"emd_{emdb_number}.map.gz"
        occurrence_path = args.root / "parse" / pdb_id / "occurrences.jsonl"
        coords_path = args.root / "parse" / pdb_id / "ligand_coords.npz"
        cif_path = args.root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"
        if not all(path.is_file() for path in (map_path, occurrence_path, coords_path, cif_path)):
            continue
        map_bytes = map_path.stat().st_size
        if map_bytes <= 0 or map_bytes > args.max_map_bytes:
            continue
        occurrences = [
            json.loads(line)
            for line in occurrence_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if not occurrences:
            continue
        base = {
            "pdb_id": pdb_id,
            "emdb_id": str(record["emdb_id"]).upper(),
            "resolution": resolution,
            "map_path": map_path,
            "map_bytes": map_bytes,
        }
        if any(item.get("kind") == "CCD" for item in occurrences):
            _keep_smallest(candidates["single_ccd"], {**base, "single_ccd": True})
        if any(item.get("kind") == "BRANCHED" for item in occurrences):
            _keep_smallest(candidates["branched"], {**base, "branched": True})
        if len(candidates["missing_ligand_atom"]) < MAX_CANDIDATES_PER_FEATURE:
            try:
                with np.load(coords_path, allow_pickle=False) as archive:
                    has_missing = any(
                        key.startswith("present_")
                        and int(np.count_nonzero(archive[key])) < int(archive[key].size)
                        for key in archive.files
                    )
            except (OSError, ValueError, KeyError):
                has_missing = False
            if has_missing:
                _keep_smallest(
                    candidates["missing_ligand_atom"],
                    {**base, "missing_ligand_atom": True},
                )
        if all(len(items) >= MAX_CANDIDATES_PER_FEATURE for items in candidates.values()):
            break

    by_pdb: dict[str, dict[str, Any]] = {}
    for feature_candidates in candidates.values():
        for candidate in feature_candidates:
            merged = by_pdb.setdefault(candidate["pdb_id"], dict(candidate))
            merged.update({key: value for key, value in candidate.items() if isinstance(value, bool)})
    # 非默认轴/origin 不需要再扫全宇宙；在各特征最小图候选的并集中检查即可。
    valid_candidates = []
    for candidate in sorted(by_pdb.values(), key=lambda item: (item["map_bytes"], item["pdb_id"])):
        try:
            geometry = _map_geometry(candidate.pop("map_path"))
        except (OSError, ValueError):
            continue
        candidate.update(geometry)
        candidate["nondefault_map_geometry"] = bool(
            tuple(geometry["axis_mapping"]) != (1, 2, 3)
            or any(value != 0 for value in geometry["nstart_raw"])
            or any(abs(value) > 1e-6 for value in geometry["header_origin_xyz"])
        )
        valid_candidates.append(candidate)

    selected: list[dict[str, Any]] = []
    uncovered = set(FEATURES)
    remaining = list(valid_candidates)
    while remaining and len(selected) < args.n_samples:
        remaining.sort(
            key=lambda item: (
                -sum(bool(item.get(feature)) for feature in uncovered),
                int(item["canonical_voxels_estimate"]),
                int(item["map_bytes"]),
                str(item["pdb_id"]),
            )
        )
        best = remaining.pop(0)
        gain = {feature for feature in uncovered if best.get(feature)}
        if not gain and uncovered:
            continue
        selected.append(best)
        uncovered.difference_update(gain)
        if not uncovered and len(selected) >= min(args.n_samples, 3):
            break
    if uncovered:
        raise RuntimeError(f"could not cover smoke features: {sorted(uncovered)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f"{args.output.name}.tmp.{os.getpid()}")
    temporary.write_text(
        "# AdaLigand real smoke: " + ",".join(FEATURES) + "\n"
        + "".join(f"{item['pdb_id']}\n" for item in selected),
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "selected": selected,
                "covered_features": sorted(set(FEATURES).difference(uncovered)),
                "n_pair_records_scanned": n_scanned,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def _keep_smallest(items: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    """每类只保留固定数量的最小压缩图候选，控制后续 header I/O。"""
    items.append(candidate)
    items.sort(key=lambda item: (int(item["map_bytes"]), str(item["pdb_id"])))
    del items[MAX_CANDIDATES_PER_FEATURE:]


def _map_geometry(path: Path) -> dict[str, Any]:
    """只读 MRC header，估算 1 Å canonical voxel 数并返回轴/origin 特征。"""
    with mrcfile.open(str(path), mode="r", permissive=True, header_only=True) as handle:
        axis_mapping = [int(handle.header.mapc), int(handle.header.mapr), int(handle.header.maps)]
        if sorted(axis_mapping) != [1, 2, 3]:
            raise ValueError(f"invalid axis mapping: {axis_mapping}")
        raw_shape = [int(handle.header.nx), int(handle.header.ny), int(handle.header.nz)]
        physical_shape = np.zeros((3,), dtype=np.int64)
        for raw_size, physical_axis in zip(raw_shape, axis_mapping, strict=True):
            physical_shape[physical_axis - 1] = raw_size
        voxel_xyz = np.asarray(
            [handle.voxel_size.x, handle.voxel_size.y, handle.voxel_size.z],
            dtype=np.float64,
        )
        canonical_shape_xyz = np.maximum(2, np.ceil(physical_shape * voxel_xyz).astype(np.int64))
        return {
            "axis_mapping": axis_mapping,
            "nstart_raw": [
                int(handle.header.nxstart),
                int(handle.header.nystart),
                int(handle.header.nzstart),
            ],
            "header_origin_xyz": [
                float(handle.header.origin.x),
                float(handle.header.origin.y),
                float(handle.header.origin.z),
            ],
            "native_shape_physical_xyz": physical_shape.tolist(),
            "native_voxel_xyz": voxel_xyz.tolist(),
            "canonical_shape_xyz_estimate": canonical_shape_xyz.tolist(),
            "canonical_voxels_estimate": int(np.prod(canonical_shape_xyz, dtype=np.int64)),
        }


if __name__ == "__main__":
    main()
