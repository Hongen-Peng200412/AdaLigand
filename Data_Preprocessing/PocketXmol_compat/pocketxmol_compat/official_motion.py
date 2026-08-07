"""调用官方 PocketXMol 运动学预处理，并把结果拆成安全的数值/JSON 字段。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
from rdkit import Chem


def get_official_torsional_info(
    pocketxmol_root: Path,
    mol: Chem.Mol,
    bond_index: np.ndarray,
    data_id: str,
) -> dict[str, Any]:
    """直接调用官方 `process.process_torsional_info.get_torsional_info_mol`。"""

    module = _load_official_module(pocketxmol_root.resolve())
    return module.get_torsional_info_mol(mol, bond_index, data_id)


def split_torsional_info(
    payload: dict[str, Any],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """把官方返回值分成 NPZ 数值数组和无 tuple-key 的 JSON 元数据。"""

    array_keys = (
        "bond_rotatable",
        "fixed_dist_torsion",
        "tor_bond_mat",
        "path_mat",
        "matches_graph",
        "matches_iso",
    )
    arrays = {key: np.asarray(payload[key]) for key in array_keys}
    metadata = {
        "nbh_dict": {
            str(int(node)): [int(neighbor) for neighbor in neighbors]
            for node, neighbors in payload["nbh_dict"].items()
        },
        "tor_twisted_pairs": [
            {
                "bond": [int(left), int(right)],
                "left_nodes": sorted(int(node) for node in sides[0]),
                "right_nodes": sorted(int(node) for node in sides[1]),
            }
            for (left, right), sides in sorted(payload["tor_twisted_pairs"].items())
        ],
    }
    return arrays, metadata


def _load_official_module(pocketxmol_root: Path) -> ModuleType:
    """按文件位置加载固定官方模块；不复制或改写其运动学算法。"""

    module_path = pocketxmol_root / "process" / "process_torsional_info.py"
    if not module_path.is_file():
        raise FileNotFoundError(f"PocketXMol official module is missing: {module_path}")
    module_name = "_adaligand_pocketxmol_official_process_torsional_info"
    loaded = sys.modules.get(module_name)
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load PocketXMol official module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(pocketxmol_root))
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        try:
            sys.path.remove(str(pocketxmol_root))
        except ValueError:
            pass
    return module
