"""按测试清单运行 CryoAtom2, 保存逐 PDB 结构、输入来源和独立运行记录.

先读 run_shard: 它把 pdb_ids[shard_index::shard_count] 分给一张 GPU, 每次只运行一个 PDB.
原始 map.gz 只解压, 不重采样; 序列按 entity 导出, 不使用真实结构坐标.
主要产物由 output_root 决定:
    - cryoatom2_artifact/<pdb_id>/<run_stamp>/: 官方输出目录; <run_stamp>.cif 是默认最终结构, <run_stamp>_raw.cif 是官方 raw 结构.
    - 运行日志与统计/pdb/<pdb_id>/<run_stamp>/: inputs.json 保存原始图位置和完整序列 entity, *.fasta 是实际输入, command.json 是命令参数列表, stdout.log/stderr.log 是子进程文本输出, status.json 是本次状态.
    - 运行日志与统计/pdb/<pdb_id>/latest.json: JSON object, 指向最近一次实际运行的状态和结构路径.
    - 运行日志与统计/runs/<run_stamp>.json: JSON object, 保存完整测试清单、软件配置、权重位置与大小、分片和 release 身份.
    - 运行日志与统计/summary.json: summarize 生成的 JSON object, 汇总全清单状态并重新检查成功结构.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from Bio.PDB import MMCIFParser


def _write_json(path: Path, value: dict | list) -> None:
    """原子写入 UTF-8 JSON, 避免只读监视器看到写了一半的状态.

    输入参数:
        - path: Path, 正式 JSON 位置; 父目录必须存在.
        - value: dict 或 list, 由调用处定义字段; 不改变嵌套值, 如 {"status": "running"}.
    副作用:
        - 同目录 <文件名>.tmp: UTF-8 JSON 临时文件; 写完后替换 path, 不保留第二份状态.
    """
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def _inspect_cif(path: Path) -> dict:
    """读取一份预测 CIF, 检查非空原子及有限坐标, 返回规模统计.

    输入参数:
        - path: Path, 官方最终或 raw mmCIF 文件; 不改变原子、链编号或坐标.
    返回值:
        - statistics: dict, 一份结构的规模.
            - atom_count: int, 文件内原子数, 必须大于零.
            - residue_count: int, 文件内残基数; 按 Bio.PDB 的模型、链与残基身份计数.
    科学边界:
        - 坐标为 CIF 的 Cartn_x/y/z, XYZ 顺序, 单位 Å; 本检查不对齐真实受体, 不衡量结构精度.
    """
    structure = MMCIFParser(QUIET=True).get_structure(path.stem, str(path))
    # float32, (atom_count, 3), 预测原子的世界 XYZ 坐标, 单位 Å.
    coords = np.asarray([atom.coord for atom in structure.get_atoms()], dtype=np.float32)
    if coords.size == 0 or not np.isfinite(coords).all():
        raise ValueError(f"预测 CIF 无原子或含非有限坐标: {path}")
    return {"atom_count": len(coords), "residue_count": sum(1 for _ in structure.get_residues())}


# ================================================================================================


def run_shard(split_file: Path, data_root: Path, sequence_catalog: Path, output_root: Path, scratch_root: Path, shard_index: int, shard_count: int, run_stamp: str) -> int:
    """在一张已分配 GPU 上顺序重建一个 PDB 分片, 单个 PDB 失败后继续.

    输入参数:
        - split_file: Path, JSON object, pdb_ids 为按冻结顺序排列的小写 PDB 列表, 如 ["9ter", "30yu"].
        - data_root: Path, AdaLigand Ori_Data 根, 读取 raw/pair_list.jsonl 和 raw/emdb_maps/emd_<编号>.map.gz; 对应记录的 pdb_id 为小写 PDB, 如 "9ter", emdb_id 为图编号, 如 "EMD-52935".
        - sequence_catalog: Path, JSONL; 每个 entity 含 pdb_id、sequence_id、sequence_class、sequence、label_asym_ids, 保留 comparable=false 的短序列.
        - output_root: Path, 同时容纳 cryoatom2_artifact 和 运行日志与统计 的实验根.
        - scratch_root: Path, 本任务专属解压父目录; 只清理本次 TemporaryDirectory 创建的子目录.
        - shard_index: int, 从零开始的分片编号, 如 0.
        - shard_count: int, 固定分片总数, 如 3; pdb_ids[shard_index::shard_count] 决定当前 PDB 列表.
        - run_stamp: str, 提交系统 TASK_RUN_STAMP, 是本次执行的唯一名称; 同一名称不重复写产物.
    落盘字段:
        - runs/<run_stamp>.json: JSON object, 位于日志根, 保存当前运行身份.
            - split_file: str, 冻结测试清单绝对路径, 与同名参数一致.
            - data_root: str, 原始图及对应关系所在数据根, 与同名参数一致.
            - sequence_catalog: str, 完整 entity 序列目录绝对路径, 与同名参数一致.
            - pdb_ids: list[str], 完整测试清单, 如 ["9ter", "30yu"].
            - shard_index: int, 本次分片编号, 如 0.
            - shard_count: int, 分片总数, 如 3.
            - software: dict, 安装环境的身份和配置.
                - version: str, 包版本, 如 "2.1.1".
                - package_root: str, 包安装目录, 如环境内的 site-packages/CryoAtom2.
                - config: dict, 官方 config.json 完整内容, 包括 RUNet_args、CryoNet_args、HMM_search 三组原参数, 不改变数值.
                    - RUNet_args: dict, 初始蛋白 C-alpha 与核酸 P 原子预测参数.
                        - batch_size: int, 单设备同时处理的小图数量, 当前 4.
                        - stride: int, 小图滑动步幅, 当前 50 个模型网格体素.
                        - windows_size: int, 小图边长, 当前 65 个模型网格体素.
                        - ca_threshold: float, C-alpha 概率图的取点阈值, 当前 0.6.
                        - p_threshold: float, 核酸 P 概率图的取点阈值, 当前 0.465.
                    - CryoNet_args: dict, 全原子结构重建参数.
                        - num_rounds: int, 重建轮数, 当前 3.
                        - repeat_per_residue: int, 每轮每残基重复覆盖目标次数, 当前 3.
                        - crop_length: int, 单次局部重建所取的残基数量参数, 当前 300.
                        - aggressive_repeat: bool, 累计局部预测时是否提前使用末轮模式, 当前 true.
                        - raw_filter: bool, 是否额外过滤 raw 结构, 当前 false.
                        - filter_threshold: float, 最终蛋白链平均预测置信度门槛, 当前 50.
                        - mask_threshold: float, 预测残基存在概率的保留门槛, 当前 0.3.
                        - seq_attention_batch_size: int, 序列注意力批量参数, 当前 -1; 官方 build 对非正值使用 crop_length.
                    - HMM_search: dict, 可选序列库搜索参数; 本任务未提供数据库, 不执行该搜索.
                        - confidence_threshold: float, 序列库搜索的置信度筛选参数, 当前 25.
                        - Evalue: float, 搜索的 E-value 门槛, 当前 1.
                        - cpus: int, 搜索线程数, 当前 4.
                - weights: list[dict], 本次依赖的权重文件身份.
                    - path: str, 权重绝对路径, 如包内 checkpoint/RUNet.pth 的完整路径.
                    - size_bytes: int, 文件字节数, 如 151641598.
            - release_root: str, 当前实际运行的冻结项目根目录.
            - job_id: str 或 null, Slurm Job 编号, 如 "123"; 本地替身测试时为 null.
        - pdb/<pdb_id>/<run_stamp>/inputs.json: JSON object, 保存当前 PDB 的源图和序列.
            - map_path: str, 原始压缩图绝对路径.
            - map_size_bytes: int, 原始压缩图的文件字节数.
            - map_mtime_ns: int, 原始压缩图的 Unix 纳秒修改时间.
            - entities: list[dict], 完整保留该 PDB 的源 entity, 不按 comparable 过滤.
                - pdb_id: str, 小写 PDB 标识, 如 "9ter".
                - entity_id: str, 当前 PDB 内聚合物分子编号, 如 "1".
                - sequence_id: str, FASTA 身份, 如 "9TER_1".
                - polymer_type: str, 原沉积聚合物类别, 如 "polypeptide(L)".
                - sequence_class: str, 规范序列类别, 如 "protein".
                - sequence: str, 完整规范序列, 如 "ACD".
                - length: int, sequence 字符数, 如 "ACD" 对应 3.
                - label_asym_ids: list[str], 该分子的链副本名, 如 ["A", "B"].
                - comparable: bool, 原目录的序列比对资格, 如短蛋白质的 false; 本任务不以它筛选序列.
            - ignored_characters: list[dict], 官方统一序列读取器忽略的源字符, 不等于全部语言模型的内部编码变换.
                - sequence_id: str, 对应源 entity 的 FASTA 身份, 如 "9TER_1".
                - index: int, 源 sequence 中的零起始字符位置, 如 "AUXG" 中 X 的位置为 2.
                - character: str, 被忽略的单个字符, 如 "X".
        - pdb/<pdb_id>/<run_stamp>/{protein,rna,dna}.fasta: 文本, 每个存在的类别导出全部 entity; header 含 sequence_id 和链副本名, sequence 不改写.
        - pdb/<pdb_id>/<run_stamp>/command.json: list[str], 实际子进程参数, 可用 shlex.join 还原命令; map 指向本次解压临时文件, 结束后该临时文件删除.
        - pdb/<pdb_id>/<run_stamp>/status.json 和 pdb/<pdb_id>/latest.json: 相同 JSON object, 本次状态与 PDB 最新实际执行状态.
            - pdb_id: str, 当前 PDB, 如 "9ter".
            - run_stamp: str, 本次执行名, 与输入参数一致.
            - status: str, running/success/failed; running 表示尚未写结束记录, 不独立证明进程仍活着.
            - started_at_unix: float, 开始时间的 Unix 秒, 如 1788854400.0.
            - finished_at_unix: float 或 null, 结束时间的 Unix 秒; 尚未结束时为 null.
            - elapsed_seconds: float 或 null, 包含解压、子进程和结构验收的秒数; 尚未结束时为 null.
            - returncode: int 或 null, 官方进程退出码, 如 0 或 17; 尚未取得进程退出码时为 null.
            - error: str 或 null, 失败原因; 运行中或成功时为 null.
            - final_cif: str, 默认最终 CIF 的预期绝对路径; 失败时文件可能不存在.
            - raw_cif: str, 官方 raw CIF 的预期绝对路径; 失败时文件可能不存在.
            - cif_statistics: dict, 保存已完成的结构检查信息, 尚未检查时为 {}.
                - final: dict, 默认最终结构的规模, 通过相应检查后出现.
                    - atom_count: int, 最终结构原子数, 必须大于零.
                    - residue_count: int, 最终结构残基数.
                - raw: dict, 官方 raw 结构的规模, 通过相应检查后出现.
                    - atom_count: int, raw 结构原子数, 必须大于零.
                    - residue_count: int, raw 结构残基数.
        - pdb/<pdb_id>/<run_stamp>/official_logs/: 目录, 保存官方实际输出中残留的 .log, 如 see_alpha_output/temp.log; 每次尝试结束后归档, 不含原子结构.
    返回值:
        - int, 本分片全部成功或跳过已成功 PDB 时为 0, 存在失败时为 1.
    """
    # list[str], 全测试集 PDB 身份; 分片只取位置, 不改变或重新抽样测试集.
    pdb_ids = json.loads(split_file.read_text(encoding="utf-8"))["pdb_ids"]
    if len(set(pdb_ids)) != len(pdb_ids) or not 0 <= shard_index < shard_count:
        raise ValueError("PDB 清单重复或分片编号越界")
    selected_ids = pdb_ids[shard_index::shard_count]  # list[str], 当前 GPU 的 PDB 顺序, 三个分片互不重叠.
    # dict[str, list[dict]], 每个 PDB 的图对应记录与序列 entity; 保留列表以识别图对应歧义.
    pairs = {pdb_id: [] for pdb_id in selected_ids}
    entities = {pdb_id: [] for pdb_id in selected_ids}
    for source_file, records in [(data_root / "raw/pair_list.jsonl", pairs), (sequence_catalog, entities)]:
        with source_file.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record["pdb_id"] in records:
                    records[record["pdb_id"]].append(record)

    log_root = output_root / "运行日志与统计"
    (log_root / "runs").mkdir(parents=True, exist_ok=True)
    scratch_root.mkdir(parents=True, exist_ok=True)
    # 配置和权重来自当前 Python 环境实际安装包, 不从工作目录同名源码导入.
    distribution = importlib.metadata.distribution("CryoAtom2")
    package_root = Path(distribution.locate_file("CryoAtom2"))
    import torch

    # list[Path], 主模型与两类语言模型的本地权重位置; 只记文件大小, 不在批处理程序中计算摘要.
    weights = list(sorted((package_root / "checkpoint").glob("*.pth")))
    weights += [Path(torch.hub.get_dir()) / "checkpoints" / name for name in ("esm2_t33_650M_UR50D.pt", "esm2_t33_650M_UR50D-contact-regression.pt", "RNA-FM_pretrained.pth")]
    # dict, 本次安装包配置快照; 子进程仍使用同一环境的官方默认配置.
    software = {"version": distribution.version, "package_root": str(package_root), "config": json.loads((package_root / "config.json").read_text(encoding="utf-8")), "weights": [{"path": str(path), "size_bytes": path.stat().st_size} for path in weights]}
    _write_json(log_root / "runs" / f"{run_stamp}.json", {"split_file": str(split_file), "data_root": str(data_root), "sequence_catalog": str(sequence_catalog), "pdb_ids": pdb_ids, "shard_index": shard_index, "shard_count": shard_count, "software": software, "release_root": str(Path(__file__).resolve().parents[2]), "job_id": os.environ.get("SLURM_JOB_ID")})
    failed_count = 0
    # dict[str, set[str]], 与 CryoAtom2.utils.fasta_utils.load_sequence_from_fasta_dict 的字符集合一致; 只记录, 不自行过滤.
    alphabets = {"protein": set("LAGVSERTIDPKQNFYMHCXBUZO.-W"), "rna": set("ACGURYKMSWBDHVN-"), "dna": set("ACGTRYKMSWBDHVN-")}
    for pdb_id in selected_ids:
        pdb_log_root = log_root / "pdb" / pdb_id
        latest_path = pdb_log_root / "latest.json"
        if latest_path.exists():
            # dict, 当前 PDB 最近一次实际运行状态; 成功跳过时保留原 run_stamp, 不伪造新执行.
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
            if previous["status"] == "success":
                try:
                    _inspect_cif(Path(previous["final_cif"]))
                    _inspect_cif(Path(previous["raw_cif"]))
                except Exception as error:
                    print(f"RETRY {pdb_id}: 旧结构复核失败, 保留旧文件并重新预测: {error}", flush=True)
                else:
                    print(f"SKIP {pdb_id}: 已有通过验收的结果", flush=True)
                    continue
        attempt_log = pdb_log_root / run_stamp
        attempt_log.mkdir(parents=True, exist_ok=False)
        output_dir = output_root / "cryoatom2_artifact" / pdb_id / run_stamp
        # 文件名沿用官方规则: 输出目录 basename 决定最终 CIF 名, 不改写结构内容.
        final_cif = output_dir / f"{run_stamp}.cif"
        raw_cif = output_dir / f"{run_stamp}_raw.cif"
        started = time.time()
        # dict, 逐 PDB 状态机; 只有退出码为零且两份 CIF 均验收通过, 才从 running 变为 success.
        status = {"pdb_id": pdb_id, "run_stamp": run_stamp, "status": "running", "started_at_unix": started, "finished_at_unix": None, "elapsed_seconds": None, "returncode": None, "error": None, "final_cif": str(final_cif), "raw_cif": str(raw_cif), "cif_statistics": {}}
        _write_json(attempt_log / "status.json", status)
        _write_json(latest_path, status)
        try:
            if len(pairs[pdb_id]) != 1 or not entities[pdb_id]:
                raise ValueError(f"{pdb_id}: 必须有唯一原始图和非空完整序列")
            map_number = pairs[pdb_id][0]["emdb_id"].removeprefix("EMD-")
            map_path = data_root / "raw/emdb_maps" / f"emd_{map_number}.map.gz"
            # list[dict], 不被官方统一序列读取器接受的字符及其在源 entity 中的零起始位置.
            ignored = []
            # dict[str, Path], 只含当前 PDB 实际存在的类别, 如纯 RNA 样本仅有 rna 键.
            fasta_paths = {}
            for kind in ("protein", "rna", "dna"):
                # list[dict], 当前类别的全部 entity, 保留源目录顺序与短链.
                kind_entities = [entity for entity in entities[pdb_id] if entity["sequence_class"] == kind]
                if not kind_entities:
                    continue
                fasta_path = attempt_log / f"{kind}.fasta"
                with fasta_path.open("w", encoding="utf-8") as handle:
                    for entity in kind_entities:
                        chains = ", ".join(entity["label_asym_ids"])  # str, FASTA header 中的链副本标识, 如 "A, B".
                        handle.write(f'>{entity["sequence_id"]}|Chains {chains}\n{entity["sequence"]}\n')
                        for index, character in enumerate(entity["sequence"]):
                            if character not in alphabets[kind]:
                                ignored.append({"sequence_id": entity["sequence_id"], "index": index, "character": character})
                fasta_paths[kind] = fasta_path
            if any(entity["sequence_class"] not in alphabets for entity in entities[pdb_id]):
                raise ValueError(f"{pdb_id}: 存在未约定的序列类别, 不静默删除")
            _write_json(attempt_log / "inputs.json", {"map_path": str(map_path), "map_size_bytes": map_path.stat().st_size, "map_mtime_ns": map_path.stat().st_mtime_ns, "entities": entities[pdb_id], "ignored_characters": ignored})
            # 官方推理入口只接受 .map/.mrc 后缀; 解压保持原始 header 和体素值, 不经过 AdaLigand 重采样.
            with tempfile.TemporaryDirectory(prefix=f"{pdb_id}_", dir=scratch_root) as temporary_dir:
                unpacked_map = Path(temporary_dir) / f"emd_{map_number}.map"
                with gzip.open(map_path, "rb") as compressed, unpacked_map.open("wb") as unpacked:
                    shutil.copyfileobj(compressed, unpacked)
                # list[str], 每个参数保持独立边界; cuda:0 是 Slurm 分配后当前进程可见的第一张 GPU.
                command = [sys.executable, "-u", "-m", "CryoAtom2", "build", "--map-path", str(unpacked_map), "--output-dir", str(output_dir), "--device", "cuda:0"]
                for kind, fasta_path in fasta_paths.items():
                    command.extend([f"--{kind}-sequence-path", str(fasta_path)])
                _write_json(attempt_log / "command.json", command)
                print(f"RUN {pdb_id}: {output_dir}", flush=True)
                with (attempt_log / "stdout.log").open("w", encoding="utf-8") as stdout, (attempt_log / "stderr.log").open("w", encoding="utf-8") as stderr:
                    completed = subprocess.run(command, stdout=stdout, stderr=stderr, cwd=attempt_log, check=False)
                status["returncode"] = completed.returncode
                if completed.returncode != 0:
                    raise RuntimeError(f"CryoAtom2 退出码 {completed.returncode}; 详见本次 stderr.log/stdout.log")
            status["cif_statistics"]["final"] = _inspect_cif(final_cif)
            status["cif_statistics"]["raw"] = _inspect_cif(raw_cif)
            status["status"] = "success"
        except Exception as error:
            failed_count += 1
            status["status"] = "failed"
            status["error"] = f"{type(error).__name__}: {error}"
        finally:
            # 官方失败时可能保留 see_alpha_output/temp.log; 把残留日志迁入本次日志目录, 结构目录只保留计算产物.
            for official_log in output_dir.rglob("*.log"):
                archived_log = attempt_log / "official_logs" / official_log.relative_to(output_dir)
                archived_log.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(official_log), str(archived_log))
        status["finished_at_unix"] = time.time()
        status["elapsed_seconds"] = status["finished_at_unix"] - started
        _write_json(attempt_log / "status.json", status)
        _write_json(latest_path, status)
        print(f'{status["status"].upper()} {pdb_id}: {status["error"] or status["cif_statistics"]}', flush=True)
    return int(failed_count > 0)


def summarize(split_file: Path, output_root: Path) -> dict:
    """汇总全测试集并重读成功 CIF, 写出日志根下的 summary.json.

    输入参数:
        - split_file: Path, 与正式运行相同的测试清单 JSON, pdb_ids 定义统计分母.
        - output_root: Path, 与正式运行相同的实验根, 不扫描目录推断测试集.
    返回与落盘字段:
        - total: int, 测试 PDB 总数.
        - counts: dict[str, int], 全清单状态计数.
            - pending: int, 尚无 latest.json 的 PDB 数.
            - running: int, 已开始但尚无结束记录的 PDB 数.
            - success: int, 运行成功且本次结构复核通过的 PDB 数.
            - failed: int, 运行失败或本次结构复核失败的 PDB 数.
        - pdbs: list[dict], 与清单逐 PDB 同序对应.
            - pdb_id: str, 当前 PDB 标识.
            - status: str, pending/running/success/failed 之一.
            - error: str 或 null, 失败原因; 未失败时为 null.
            - final_cif: str 或 null, 默认最终 CIF 的绝对路径; pending 时为 null.
            - raw_cif: str 或 null, 官方 raw CIF 的绝对路径; pending 时为 null.
    副作用:
        - 只写 运行日志与统计/summary.json; 不修改逐 PDB 状态或结构. 原先成功但结构复核失败时仅在本汇总记 failed.
    """
    pdb_ids = json.loads(split_file.read_text(encoding="utf-8"))["pdb_ids"]
    log_root = output_root / "运行日志与统计"
    # dict, 全清单统计; pending 的 PDB 也保留, 不把成功子集误作测试集分母.
    summary = {"total": len(pdb_ids), "counts": {"pending": 0, "running": 0, "success": 0, "failed": 0}, "pdbs": []}
    for pdb_id in pdb_ids:
        latest_path = log_root / "pdb" / pdb_id / "latest.json"
        # dict, 当前 PDB 的汇总投影, 字段与逐 PDB latest 对应, 不包含耗时和软件身份.
        record = {"pdb_id": pdb_id, "status": "pending", "error": None, "final_cif": None, "raw_cif": None}
        if latest_path.exists():
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            record.update({key: latest[key] for key in record})
            if record["status"] == "success":
                try:
                    _inspect_cif(Path(record["final_cif"]))
                    _inspect_cif(Path(record["raw_cif"]))
                except Exception as error:
                    record.update(status="failed", error=f"结构复核失败: {error}")
        summary["counts"][record["status"]] += 1
        summary["pdbs"].append(record)
    log_root.mkdir(parents=True, exist_ok=True)
    _write_json(log_root / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行 CryoAtom2 测试集分片或汇总状态")
    parser.add_argument("action", choices=("run", "summarize"))
    parser.add_argument("--split-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--sequence-catalog", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int)
    args = parser.parse_args()
    if args.action == "summarize":
        print(json.dumps(summarize(args.split_file, args.output_root)["counts"], ensure_ascii=False))
    else:
        if any(value is None for value in (args.data_root, args.sequence_catalog, args.scratch_root, args.shard_index, args.shard_count)):
            parser.error("run 必须提供 data-root、sequence-catalog、scratch-root、shard-index 和 shard-count")
        sys.exit(run_shard(args.split_file, args.data_root, args.sequence_catalog, args.output_root, args.scratch_root, args.shard_index, args.shard_count, os.environ["TASK_RUN_STAMP"]))
