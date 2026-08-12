"""确定任务范围、数组分片和运行报告位置，并记录与运行环境有关的事实。

本模块只回答“本次任务处理哪些 PDB、当前数组任务拿到哪一片、报告写到哪里”。
配体化学组装、模型输入准备和向量产物分别由其他模块负责。

范围处理依次使用 ``load_pdb_ids`` 和 ``select_shard``；环境事实由具名查询函数返回；
只有 ``write_report`` 会把调用者给出的 JSON 对象原子写入指定报告路径。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Iterable


def load_pdb_ids(
    data_root: Path,
    all_valid_path: Path,
    sample_scope: str,
) -> list[str]:
    """按用户指定的样本范围返回排序、去重的小写 PDB 标识列表。

    参数:
        data_root: 原始数据根目录；``sample_scope="all_existing"`` 时扫描 ``data_root/parse/{pdb_id}/occurrences.jsonl``。
        all_valid_path: ``all_valid.json`` 路径。``sample_scope="all_valid"`` 时读取该文件。
        sample_scope: ``all_existing`` 表示处理所有已有 occurrence 文件；``all_valid`` 表示只处理 ``all_valid.json`` 明确列出的 PDB。

    返回:
        小写 PDB 标识列表。列表按字典序排列且不重复，供所有 Slurm 数组任务共同切片。

    本函数不会取两种范围的交集，也不会修改 ``all_valid.json``、``info.json``、数据划分或 BOX pool。
    ``all_valid.json`` 中的元素必须本来就是非空字符串；数字或其他 JSON 类型不会被静默转换成 PDB 标识。
    """

    if sample_scope == "all_existing":
        # 每个标识都来自真实存在的 parse/{pdb_id}/occurrences.jsonl 的父目录名。
        pdb_id_set = {
            occurrence_path.parent.name.lower()
            for occurrence_path in (data_root / "parse").glob("*/occurrences.jsonl")
            if occurrence_path.is_file()
        }
        return sorted(pdb_id_set)

    if sample_scope != "all_valid":
        raise ValueError("sample_scope 必须是 all_valid 或 all_existing")

    raw_values = json.loads(all_valid_path.read_text(encoding="utf-8"))
    if not isinstance(raw_values, list):
        raise ValueError("all_valid.json 顶层必须是 PDB 字符串数组")

    pdb_id_set: set[str] = set()
    for index, raw_value in enumerate(raw_values):
        if type(raw_value) is not str or not raw_value.strip():
            raise ValueError(f"all_valid.json[{index}] 必须是非空字符串")
        pdb_id_set.add(raw_value.strip().lower())
    return sorted(pdb_id_set)


def select_shard(
    pdb_ids: list[str],
    shard_index: int,
    num_shards: int,
) -> list[str]:
    """按 ``pdb_ids[shard_index::num_shards]`` 选择一个零基数组分片。

    参数:
        pdb_ids: 已排序的全局 PDB 列表。所有数组任务必须使用相同内容和顺序。
        shard_index: 当前 Slurm array 的零基任务编号，范围为 ``[0, num_shards)``。
        num_shards: Slurm array 的任务总数，必须是正整数。

    返回:
        当前任务独占的 PDB 子序列。合法分片互不重叠，按分片编号合并后可恢复输入列表。
    """

    if type(shard_index) is not int or type(num_shards) is not int:
        raise TypeError("shard_index 和 num_shards 必须是整数")
    if num_shards < 1:
        raise ValueError("num_shards 必须为正整数")
    if shard_index < 0 or shard_index >= num_shards:
        raise ValueError("shard_index 必须位于 [0, num_shards) 范围内")
    return pdb_ids[shard_index::num_shards]


def shard_report_path(stage_root: Path, shard_index: int, num_shards: int) -> Path:
    """返回当前分片报告的固定路径，不创建目录或文件。"""

    return stage_root / "reports" / f"shard_{shard_index:03d}_of_{num_shards:03d}.json"


def utc_now() -> str:
    """返回带 UTC 时区的 ISO 8601 时间字符串，供运行报告记录开始和结束时刻。"""

    return datetime.now(timezone.utc).isoformat()


def format_error(error: BaseException) -> str:
    """把异常压成适合 JSONL 与普通日志的单行文字，同时保留异常类型。"""

    detail = str(error).replace("\r", " ").replace("\n", " ").strip()
    return f"{type(error).__name__}: {detail}"


def dependency_versions(distributions: Iterable[str]) -> dict[str, str | None]:
    """读取指定 Python 分发包的已安装版本，缺失的包记录为 ``None``。

    返回字典保持 ``distributions`` 的迭代顺序。版本事实只进入运行报告，不参与样本筛选，
    也不会把缺失依赖伪装成某个默认版本。
    """

    versions: dict[str, str | None] = {}
    for distribution in distributions:
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions


def cuda_facts(torch_module: object) -> dict[str, object]:
    """读取当前 Python 进程实际看到的 CUDA 设备与运行库事实。

    参数:
        torch_module: 已导入的官方 ``torch`` 模块。显式传入可避免 CPU 准备阶段导入 torch。

    返回字段:
        cuda_available: ``bool``，当前 torch 是否能使用 CUDA。
        cuda_version: ``str | None``，当前 torch 构建记录的 CUDA 版本。
        cudnn_version: ``int | None``，torch 后端报告的 cuDNN 版本。
        device_count: ``int``，当前进程可见的 CUDA 设备数。
        device_name: ``str | None``，第一张可见设备名称；CUDA 不可用时为 ``None``。

    这些字段只用于报告运行环境，不影响任何 occurrence 是否被编码。
    """

    torch = torch_module
    available = bool(torch.cuda.is_available())
    return {
        "cuda_available": available,
        "cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version(),
        "device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0) if available else None,
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    """把一个完整 JSON 报告原子写入 ``path``。

    正式报告先写入同目录的 ``.{文件名}.tmp``，再用 ``Path.replace`` 覆盖目标文件。
    因此进程若在序列化或写入中途失败，不会留下看似完整但内容被截断的正式报告。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
