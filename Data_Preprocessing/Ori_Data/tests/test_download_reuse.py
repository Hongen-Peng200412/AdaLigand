"""Stage B 原始下载件的低 I/O 复用判据测试。"""

from __future__ import annotations

import sys
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from download import resource_path_is_reusable


def test_large_mmcif_is_reusable_when_atom_site_starts_after_first_mib(tmp_path: Path) -> None:
    """合法大 mmCIF 不应因 `_atom_site.` 位于 1 MiB 窗口之后而被重新下载。"""
    path = tmp_path / "large.cif"
    prefix = b"data_TEST\n#\n_entry.id TEST\n#\n"
    path.write_bytes(prefix + b"# padding\n" * 120_000 + b"_atom_site.id\n1\n")

    assert path.stat().st_size > 1024 * 1024
    assert resource_path_is_reusable(path, "mmcif")


def test_mmcif_reuse_rejects_missing_data_block_or_entry_id(tmp_path: Path) -> None:
    """低 I/O 判据仍须拒绝缺少 data block 或 entry 标识的伪 mmCIF。"""
    missing_data = tmp_path / "missing_data.cif"
    missing_entry = tmp_path / "missing_entry.cif"
    missing_data.write_text("_entry.id TEST\n", encoding="utf-8")
    missing_entry.write_text("data_TEST\n_atom_site.id\n1\n", encoding="utf-8")

    assert not resource_path_is_reusable(missing_data, "mmcif")
    assert not resource_path_is_reusable(missing_entry, "mmcif")
