#!/usr/bin/env bash
# AdaLigand 只读容量探测：估算 1 Å canonical 永久产物与单样本峰值，不写服务器。
set -u

DATA_ROOT=/storage/penghongen/AdaLigand/Ori_Data
PYTHON=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python

echo '[node_capacity]'
sinfo -N -h -p cpu -o '%N|%t|cpus=%c|memory_mb=%m|free_mb=%e|cpu_state=%C'
sinfo -N -h -p a100 -o '%N|%t|cpus=%c|memory_mb=%m|free_mb=%e|gres=%G|cpu_state=%C'

echo '[data_sizes]'
for path in \
  "$DATA_ROOT/raw/emdb_maps" \
  "$DATA_ROOT/raw/rcsb_mmcif" \
  "$DATA_ROOT/reports/meta" \
  "$DATA_ROOT/parse" \
  "$DATA_ROOT/ligand_objects"; do
  "$PYTHON" - "$path" <<'PY'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
total = 0
count = 0
for directory, _, filenames in os.walk(root):
    for filename in filenames:
        try:
            total += (Path(directory) / filename).stat().st_size
            count += 1
        except OSError:
            pass
print(f'{root}|files={count}|bytes={total}')
PY
done
printf 'parse_pdb_dirs|'
find "$DATA_ROOT/parse" -mindepth 1 -maxdepth 1 -type d | wc -l

echo '[mrc_header_capacity_estimate]'
"$PYTHON" - "$DATA_ROOT/raw/emdb_maps" <<'PY'
import gzip
import math
import statistics
import struct
import sys
from pathlib import Path

map_dir = Path(sys.argv[1])
records = []
errors = []
all_paths = sorted(map_dir.glob('*.map.gz'))
if len(all_paths) <= 512:
    sample_paths = all_paths
else:
    # 文件名分层抽样 384 个，再加入压缩体积最大的 128 个；去重后不超过 512。
    stride = (len(all_paths) - 1) / 383
    stratified = [all_paths[round(index * stride)] for index in range(384)]
    largest = sorted(all_paths, key=lambda path: path.stat().st_size, reverse=True)[:128]
    sample_paths = sorted(set(stratified + largest))
for path in sample_paths:
    try:
        with gzip.open(path, 'rb') as handle:
            header = handle.read(1024)
        if len(header) < 1024:
            raise ValueError('short header')
        nx, ny, nz = struct.unpack_from('<3i', header, 0)
        mx, my, mz = struct.unpack_from('<3i', header, 28)
        xlen, ylen, zlen = struct.unpack_from('<3f', header, 40)
        mapc, mapr, maps = struct.unpack_from('<3i', header, 64)
        if sorted((mapc, mapr, maps)) != [1, 2, 3]:
            raise ValueError(f'axis={mapc,mapr,maps}')
        if min(nx, ny, nz, mx, my, mz) <= 0:
            raise ValueError('nonpositive dimensions')
        voxel_xyz = (xlen / mx, ylen / my, zlen / mz)
        data_counts = (nx, ny, nz)
        physical_counts = [0, 0, 0]
        physical_counts[mapc - 1] = data_counts[0]
        physical_counts[mapr - 1] = data_counts[1]
        physical_counts[maps - 1] = data_counts[2]
        canonical_xyz = tuple(max(2, math.ceil(n * v - 1e-6)) for n, v in zip(physical_counts, voxel_xyz))
        input_voxels = nx * ny * nz
        canonical_voxels = math.prod(canonical_xyz)
        records.append((path.name, path.stat().st_size, input_voxels, canonical_voxels, canonical_xyz, voxel_xyz))
    except Exception as exc:
        errors.append((path.name, str(exc)))

def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))]

canonical = [item[3] for item in records]
ratios = [item[3] / item[2] for item in records]
sizes = [item[1] for item in records]
print(f'n_total_maps={len(all_paths)}')
print(f'n_sampled={len(sample_paths)}')
print(f'n_valid={len(records)}')
print(f'n_header_errors={len(errors)}')
for fraction in (0.5, 0.9, 0.95, 0.99, 1.0):
    voxels = percentile(canonical, fraction)
    ratio = percentile(ratios, fraction)
    compressed = percentile(sizes, fraction)
    print(f'p{int(fraction*100):02d}:canonical_voxels={voxels}|ratio={ratio:.4g}|compressed_bytes={compressed}')
sample_mean_voxels = statistics.fmean(canonical) if canonical else 0
estimated_total_voxels = round(sample_mean_voxels * len(all_paths))
print(f'sample_mean_canonical_voxels={sample_mean_voxels:.6g}')
print(f'estimated_total_canonical_voxels={estimated_total_voxels}')
print(f'estimated_exp_sim_union_bytes={estimated_total_voxels * 9}')
if records:
    largest = max(records, key=lambda item: item[3])
    print('largest=' + '|'.join(map(str, largest)))
if errors:
    print('header_error_examples=' + repr(errors[:10]))
PY
