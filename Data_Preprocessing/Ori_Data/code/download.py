"""Stage B 下载实现。

download_one_pair：按 --resources 下载一个样本的 mmCIF(RCSB)、EMDB map(EBI FTP)、EMDB meta(EMDB API)，
3 次重试 + gzip 完整性校验 + 原子写；mmcif/map 落 `raw/`，meta 落 `reports/meta/`。
write_failed_downloads：把本分片的下载失败汇总到 `reports/_failed_download.part_*`（并发安全追加）。
"""

from __future__ import annotations

import gzip
import io
import time
from pathlib import Path
from typing import Any

import requests

from io_utils import append_jsonl
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
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_bytes(content)
    tmp_path.replace(path)


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

    targets = [
        ("mmcif", PDB_CIF_URL.format(pdb_id=pdb_id.upper()), root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"),
        ("meta", EMDB_META_URL.format(emdb_id=emdb_id), root / "reports" / "meta" / f"{pdb_id}.meta.json"),
        ("map", emdb_map_url(emdb_id), root / "raw" / "emdb_maps" / f"emd_{emdb_id.replace('EMD-', '')}.map.gz"),
    ]

    for resource, url, path in targets:
        if resource not in resources:
            continue
        if path.exists() and not overwrite:
            continue
        try:
            content = download_bytes(url)
            if resource == "map":
                validate_gzip_bytes(content)
            write_bytes(path, content)
        except Exception as exc:
            result["ok"] = False
            result["failures"].append({"resource": resource, "error": str(exc)})
    return result


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
        - None: 若存在失败则写入 `reports/_failed_download.jsonl`
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
    if failed:
        for record in failed:
            append_jsonl(failed_path, record)
