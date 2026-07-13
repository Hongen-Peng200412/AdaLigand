# 学习导航：功能分区=外部工具与格式适配；生命周期=正式主路径 Stage B。
# 主要输入：Stage A pair_list、RCSB/EMDB URL、下载分片与重试配置。
# 主要输出：原始 mmCIF/map 文件、下载状态和显式 download_failed 记录。
# 关键边界：网络成功不等于结构科学有效；失败必须进入可审计状态，不能静默缺失。
"""Stage B 下载实现。

download_one_pair：按 --resources 下载一个样本的 mmCIF(RCSB)、EMDB map(EBI FTP)、EMDB meta(EMDB API)，
3 次重试 + gzip 完整性校验 + 原子写；mmcif/map 落 `raw/`，meta 落 `reports/meta/`。
write_failed_downloads：把本分片的最终失败原子覆盖到 `reports/_failed_download.part_*`，空结果也清除旧污染。
"""

from __future__ import annotations

import gzip
import io
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from io_utils import atomic_replace, write_jsonl
from rcsb import EMDB_META_URL, PDB_CIF_URL, emdb_map_url
from reports import sharded_report_path


def download_bytes(url: str) -> bytes:
    """
    下载 URL 内容。

    输入参数:
        - url: str, HTTP(S) 地址

    输出:
        - content: bytes, 响应体字节
    """
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            content = response.content
            if not content:
                raise RuntimeError(f"empty response from {url}")
            return content
        except Exception as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"failed to download {url}: {last_error}")


def write_bytes(path: Path, content: bytes) -> None:
    """
    原子写二进制文件。

    输入参数:
        - path: Path, 输出路径
        - content: bytes, 文件内容

    输出:
        - None: 文件写入完成
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_bytes(content)
    atomic_replace(tmp_path, path)


def validate_gzip_bytes(content: bytes) -> None:
    """
    校验 gzip 字节可完整解压。

    输入参数:
        - content: bytes, gzip 文件内容

    输出:
        - None: gzip 可正常读取
    """
    with gzip.GzipFile(fileobj=io.BytesIO(content)) as handle:
        while handle.read(1024 * 1024):
            pass


def download_one_pair(
    root: Path,
    record: dict[str, Any],
    overwrite: bool,
    resources: set[str],
) -> dict[str, Any]:
    """
    下载一个 PDB/EMDB pair 的 mmCIF、map 和 meta。

    输入参数:
        - root: Path, Stage root, 内含 raw 目录
        - record: dict[str, Any], pair_list 中的一条记录
        - overwrite: bool, 是否覆盖已有文件
        - resources: set[str], 要下载的资源名集合, 可选 mmcif/meta/map

    输出:
        - result: dict[str, Any], 当前 pair 的下载状态摘要
    """
    pdb_id = str(record["pdb_id"]).lower()
    emdb_id = str(record["emdb_id"]).upper()
    result = {"pdb_id": pdb_id, "emdb_id": emdb_id, "ok": True, "failures": []}
    result["resources"] = {}

    targets = [
        ("mmcif", PDB_CIF_URL.format(pdb_id=pdb_id.upper()), root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"),
        ("meta", EMDB_META_URL.format(emdb_id=emdb_id), root / "reports" / "meta" / f"{pdb_id}.meta.json"),
        ("map", emdb_map_url(emdb_id), root / "raw" / "emdb_maps" / f"emd_{emdb_id.replace('EMD-', '')}.map.gz"),
    ]

    for resource, url, path in targets:
        if resource not in resources:
            continue
        if path.exists() and not overwrite and resource_path_is_reusable(path, resource):
            result["resources"][resource] = "skipped"
            continue
        try:
            content = download_bytes(url)
            if resource == "map":
                validate_gzip_bytes(content)
            elif resource == "meta":
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError("EMDB metadata root is not a JSON object")
            elif resource == "mmcif" and b"data_" not in content[:1024]:
                raise ValueError("downloaded mmCIF has no data_ block")
            write_bytes(path, content)
            result["resources"][resource] = "downloaded"
        except Exception as exc:
            result["ok"] = False
            result["failures"].append({"resource": resource, "error": str(exc)})
            result["resources"][resource] = "failed"
    return result


def resource_targets(root: Path, record: dict[str, Any]) -> dict[str, Path]:
    """返回一个 pair 的 mmCIF/meta/map 最终路径。"""
    pdb_id = str(record["pdb_id"]).lower()
    emdb_id = str(record["emdb_id"]).upper()
    return {
        "mmcif": root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif",
        "meta": root / "reports" / "meta" / f"{pdb_id}.meta.json",
        "map": root / "raw" / "emdb_maps" / f"emd_{emdb_id.replace('EMD-', '')}.map.gz",
    }


def resource_path_is_reusable(path: Path, resource: str) -> bool:
    """
    以低 I/O 判据判断既有下载件是否可复用。

    map 只检查非空与 gzip magic；mmCIF 只检查文件头的 data block 与 entry 标识。完整
    mmCIF/CRC/MRC/三维内容由 Stage C/E 实际读取时验证，避免为了跳过 22k 份大文件而
    扫描全部正文。尤其不能假设 `_atom_site.` 必定位于前 1 MiB。
    """
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        if resource == "map":
            if path.stat().st_size < 18:
                return False
            with path.open("rb") as handle:
                return handle.read(2) == b"\x1f\x8b"
        if resource == "meta":
            value = json.loads(path.read_text(encoding="utf-8"))
            return isinstance(value, dict)
        if resource == "mmcif":
            with path.open("rb") as handle:
                prefix = handle.read(1024 * 1024)
            return prefix.lstrip().startswith(b"data_") and b"_entry.id" in prefix
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    raise ValueError(f"unknown download resource: {resource}")


def write_failed_downloads(
    root: Path,
    results: list[dict[str, Any]],
    part_id: int = 0,
    total_parts: int = 1,
) -> None:
    """
    汇总写入下载失败记录。

    输入参数:
        - root: Path, Stage root
        - results: list[dict[str, Any]], `download_one_pair` 返回列表

    输出:
        - None: 原子覆盖 `reports/_failed_download.jsonl`；无失败时写空文件
    """
    failed: list[dict[str, Any]] = []
    for result in results:
        for failure in result["failures"]:
            failed.append(
                {
                    "pdb_id": result["pdb_id"],
                    "emdb_id": result["emdb_id"],
                    "resource": failure["resource"],
                    "error": failure["error"],
                }
            )
    failed_path = sharded_report_path(root, "_failed_download.jsonl", part_id, total_parts)
    # 每个分片以本次最终结果原子覆盖自己的 legacy 诊断文件，空列表也写空文件，清除旧污染。
    write_jsonl(failed_path, failed)
