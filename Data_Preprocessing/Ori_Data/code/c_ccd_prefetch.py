# 学习导航：功能分区=数据契约与质量验证；生命周期=一次性恢复/补足工具。
# 主要输入：冻结的 CCD ID 清单、现有 cache 与 source rebuild 证据目录。
# 主要输出：可复核的 CCD cache 命中/缺失审计，不直接生成 Stage C 主产物。
# 关键边界：只补足明确列出的依赖，不能把网络下载结果默认为科学成功。
"""Stage C source 迁移前的显式 CCD cache 补足与只读复核。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from io_utils import sha256_file
from ligand_object import get_ccd_mol
from receptor import validated_ccd_atom_name_to_element


CCD_PREFETCH_SCHEMA_VERSION = 1


def prefetch_and_audit_ccd(root: Path, ccd_id: str) -> dict[str, Any]:
    """
    显式补足一个 CCD cache，并立即用 cache-only 路径复核其身份和 atom-name 表。

    输入参数:
        - root: Path, Stage root
        - ccd_id: str, 待补足的 CCD id，大小写不敏感

    输出:
        - record: dict[str,Any], 包含:
            - `ccd_id`: str, 规范化大写 CCD id
            - `action`: str, `downloaded` 或 `reused`
            - `cache_path`: str, 相对 Stage root 的 cache 路径
            - `cache_sha256`: str, 最终 pickle 的 SHA-256
            - `n_atoms`: int, CCD 原子数
            - `n_unique_atom_names`: int, 非空唯一 atom name 数
            - `schema_version`: int, 记录 schema 版本
    """
    normalized_id = ccd_id.strip().upper()
    if not normalized_id:
        raise ValueError("CCD id must not be empty")
    cache_path = root / "raw" / "ccd_cache" / f"{normalized_id}.pkl"
    existed_before = cache_path.is_file()
    get_ccd_mol(normalized_id, cache_path.parent, allow_fetch=True)

    # 最终记录必须来自一次独立的 cache-only 读取，防止下载返回值掩盖落盘问题。
    cached = get_ccd_mol(normalized_id, cache_path.parent, allow_fetch=False)
    name_to_element = validated_ccd_atom_name_to_element(cached, normalized_id)
    return {
        "ccd_id": normalized_id,
        "action": "reused" if existed_before else "downloaded",
        "cache_path": cache_path.relative_to(root).as_posix(),
        "cache_sha256": sha256_file(cache_path),
        "n_atoms": int(cached.GetNumAtoms()),
        "n_unique_atom_names": len(name_to_element),
        "schema_version": CCD_PREFETCH_SCHEMA_VERSION,
    }
