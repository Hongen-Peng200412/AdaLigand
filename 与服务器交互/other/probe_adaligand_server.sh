#!/usr/bin/env bash
# AdaLigand 只读服务器探测：不得创建目录、安装依赖或提交/取消作业。
set -u

CODE_ROOT=/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data
DATA_ROOT=/storage/penghongen/AdaLigand/Ori_Data
PYTHON=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python

echo '[identity]'
hostname
date --iso-8601=seconds
id

echo '[slurm_partitions]'
sinfo -h -o '%P|%a|%l|%D|%C|%G'

echo '[slurm_qos]'
sacctmgr -n -P show qos format=Name,MaxTRESPU,MaxJobsPU,MaxSubmitPU,GrpTRES 2>&1 || true

echo '[current_jobs]'
squeue -u penghongen -h -o '%i|%P|%j|%T|%M|%D|%C|%R'

echo '[disk]'
df -h /home/penghongen "$DATA_ROOT" 2>&1
df -ih /home/penghongen "$DATA_ROOT" 2>&1

echo '[code_and_data]'
test -d "$CODE_ROOT" && printf 'code_root=present\n' || printf 'code_root=missing\n'
test -d "$DATA_ROOT" && printf 'data_root=present\n' || printf 'data_root=missing\n'
test -f "$DATA_ROOT/raw/pair_list.jsonl" && wc -l "$DATA_ROOT/raw/pair_list.jsonl"
test -f "$DATA_ROOT/raw/pair_list.jsonl" && sha256sum "$DATA_ROOT/raw/pair_list.jsonl"
for path in \
  "$DATA_ROOT/raw/rcsb_mmcif" \
  "$DATA_ROOT/raw/emdb_maps" \
  "$DATA_ROOT/reports/meta" \
  "$DATA_ROOT/parse" \
  "$DATA_ROOT/ligand_objects"; do
  if test -d "$path"; then
    printf '%s|' "$path"
    find "$path" -maxdepth 1 -type f | wc -l
  fi
done

echo '[python]'
"$PYTHON" - <<'PY'
import importlib
import importlib.metadata
import platform
import sys

print('python=' + sys.version.replace('\n', ' '))
print('platform=' + platform.platform())
for name in ('numpy', 'scipy', 'gemmi', 'rdkit', 'joblib', 'requests', 'mrcfile', 'pdbeccdutils', 'pytest'):
    try:
        module = importlib.import_module(name)
        version = getattr(module, '__version__', None)
        if version is None:
            version = importlib.metadata.version(name)
        print(f'{name}={version}')
    except Exception as exc:
        print(f'{name}=MISSING:{type(exc).__name__}:{exc}')
PY

echo '[chimera_mapq_candidates]'
for path in \
  /home/penghongen/chimera \
  /home/penghongen/Chimera \
  /home/penghongen/.local/chimera \
  /home/penghongen/.local/opt/chimera \
  /home/penghongen/My_Project/tools/chimera \
  /home/penghongen/My_Project/tools/mapq \
  /home/penghongen/My_Project/tmp; do
  if test -e "$path"; then
    ls -ld "$path"
  fi
done
command -v chimera 2>/dev/null || true
find /home/penghongen/.local /home/penghongen/My_Project/tools -maxdepth 4 \
  \( -type f -o -type l \) \
  \( -name chimera -o -name mapq_cmd.py -o -name 'mapq_v2.9.7.zip' \) \
  -print 2>/dev/null || true

echo '[runtime]'
ldd --version 2>&1 | head -n 1
uname -a
