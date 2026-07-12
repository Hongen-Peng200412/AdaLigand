#!/usr/bin/env bash
# AdaLigand 只读 map 抽样：只打开至多 128 个 gzip 头，避免 Lustre 全目录随机读。
set -u

MAP_DIR=/storage/penghongen/AdaLigand/Ori_Data/raw/emdb_maps
PYTHON=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python

echo '[node_capacity]'
sinfo -N -h -p cpu -o '%N|%t|cpus=%c|memory_mb=%m|free_mb=%e|cpu_state=%C'
sinfo -N -h -p a100 -o '%N|%t|cpus=%c|memory_mb=%m|free_mb=%e|gres=%G|cpu_state=%C'

echo '[map_sample]'
"$PYTHON" - "$MAP_DIR" <<'PY'
import gzip
import math
import statistics
import struct
import sys
from pathlib import Path

paths = sorted(Path(sys.argv[1]).glob('*.map.gz'))
if len(paths) <= 128:
    sample = paths
else:
    stride = (len(paths) - 1) / 127
    sample = [paths[round(index * stride)] for index in range(128)]
records = []
errors = []
for path in sample:
    try:
        with gzip.open(path, 'rb') as handle:
            header = handle.read(1024)
        nx, ny, nz = struct.unpack_from('<3i', header, 0)
        mx, my, mz = struct.unpack_from('<3i', header, 28)
        xlen, ylen, zlen = struct.unpack_from('<3f', header, 40)
        mapc, mapr, maps = struct.unpack_from('<3i', header, 64)
        voxel = (xlen / mx, ylen / my, zlen / mz)
        physical = [0, 0, 0]
        physical[mapc - 1] = nx
        physical[mapr - 1] = ny
        physical[maps - 1] = nz
        canonical = tuple(max(2, math.ceil(n * v - 1e-6)) for n, v in zip(physical, voxel))
        records.append((path.name, math.prod(canonical), canonical, voxel))
    except Exception as exc:
        errors.append((path.name, str(exc)))

values = sorted(item[1] for item in records)
def q(fraction):
    return values[min(len(values) - 1, round((len(values) - 1) * fraction))]

print(f'n_total={len(paths)}')
print(f'n_sampled={len(sample)}')
print(f'n_valid={len(records)}')
print(f'n_errors={len(errors)}')
for fraction in (0.5, 0.9, 0.95, 0.99, 1.0):
    print(f'p{round(fraction*100):02d}_canonical_voxels={q(fraction)}')
mean_voxels = statistics.fmean(values)
estimated_total = round(mean_voxels * len(paths))
print(f'mean_canonical_voxels={mean_voxels:.6g}')
print(f'estimated_total_canonical_voxels={estimated_total}')
print(f'estimated_exp_sim_union_bytes={estimated_total * 9}')
print('sample_largest=' + repr(max(records, key=lambda item: item[1])))
if errors:
    print('error_examples=' + repr(errors[:10]))
PY
