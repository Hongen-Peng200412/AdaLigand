"""Stage C source rebuild 前的显式 ligand descriptor 依赖补足。"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from io_utils import safe_object_filename, sha256_file
from ligand_descriptors import (
    ligand_descriptor_is_valid,
    materialize_ligand_descriptor,
)
from ligand_object import ligand_object_is_valid


DESCRIPTOR_PREFETCH_SCHEMA_VERSION = 1
_OBJECT_KEY_PATTERN = re.compile(
    r"(?:CCD:[A-Z0-9]{1,8}|BRANCHED:[A-Z0-9]{1,8}(?:-[A-Z0-9]{1,8})+:[0-9a-f]{6})"
)


def validate_descriptor_object_key(object_key: str) -> str:
    """
    验证冻结清单中的 LigandObject 键，并保持其科学身份不变。

    输入参数:
        - object_key: str, `CCD:*` 或当前 Stage C 生成的 `BRANCHED:*` 去重键

    输出:
        - validated_key: str, 与输入逐字符相同的合法 object key
    """
    if _OBJECT_KEY_PATTERN.fullmatch(object_key) is None:
        raise ValueError(f"invalid Stage C descriptor object key: {object_key!r}")
    return object_key


def materialize_and_audit_descriptor(
    root: Path,
    object_key: str,
) -> dict[str, Any]:
    """
    以非覆盖模式补足一个 descriptor，并冻结其源对象与最终文件哈希。

    输入参数:
        - root: Path, Stage root，内含 `ligand_objects/` 与 `ligand_descriptors/`
        - object_key: str, 已由冻结输入清单授权的 LigandObject 去重键

    输出:
        - record: dict[str, Any], 包含:
            - `status`: str, 成功时固定为 `success`
            - `object_key`: str, 原样保留的 LigandObject 去重键
            - `action`: str, `materialized` 或 `reused`
            - `ligand_object_path`: str, 相对 Stage root 的源对象路径
            - `ligand_object_sha256`: str, 源 LigandObject 的 SHA-256
            - `descriptor_path`: str, 相对 Stage root 的 descriptor 路径
            - `descriptor_sha256`: str, 最终有效 descriptor 的 SHA-256
            - `schema_version`: int, 本记录的证据 schema 版本
    """
    validated_key = validate_descriptor_object_key(object_key)
    safe_key = safe_object_filename(validated_key)
    object_path = root / "ligand_objects" / f"{safe_key}.npz"
    descriptor_path = root / "ligand_descriptors" / f"{safe_key}.npz"

    if not ligand_object_is_valid(object_path, validated_key):
        raise RuntimeError(
            f"invalid or missing LigandObject for descriptor supplement: {validated_key}"
        )
    object_sha256 = sha256_file(object_path)
    valid_before = ligand_descriptor_is_valid(descriptor_path)

    written_path = materialize_ligand_descriptor(
        root,
        validated_key,
        overwrite=False,
    )
    if written_path.resolve() != descriptor_path.resolve():
        raise RuntimeError(
            f"descriptor materializer returned unexpected path for {validated_key}: "
            f"{written_path}"
        )
    if not ligand_descriptor_is_valid(descriptor_path):
        raise RuntimeError(
            f"invalid descriptor after materialization: {validated_key}"
        )
    if sha256_file(object_path) != object_sha256:
        raise RuntimeError(
            f"LigandObject changed during descriptor materialization: {validated_key}"
        )

    return {
        "status": "success",
        "object_key": validated_key,
        "action": "reused" if valid_before else "materialized",
        "ligand_object_path": object_path.relative_to(root).as_posix(),
        "ligand_object_sha256": object_sha256,
        "descriptor_path": descriptor_path.relative_to(root).as_posix(),
        "descriptor_sha256": sha256_file(descriptor_path),
        "schema_version": DESCRIPTOR_PREFETCH_SCHEMA_VERSION,
    }
