"""Stage C 显式 CCD cache prefetch 与 cache-only 复核测试。"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

from rdkit import Chem
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"

from adaligand_preprocessing.ops.stage_c_ccd import prefetch_and_audit_ccd
from adaligand_preprocessing.stages.stage_c.receptor import ReceptorAtomNameCoverageError


def _ccd_mol(ccd_id: str) -> Chem.Mol:
    """构造带合法 CCD 身份和唯一 atom name 的单原子测试分子。"""
    editable = Chem.RWMol()
    atom = Chem.Atom(6)
    atom.SetProp("name", "C1")
    editable.AddAtom(atom)
    mol = editable.GetMol()
    mol.SetProp("PDB_NAME", ccd_id)
    return mol


def test_prefetch_writes_then_reloads_cache_only(monkeypatch, tmp_path):
    """缺失 cache 必须显式落盘，记录哈希来自随后独立的 cache-only 读取。"""
    calls: list[bool] = []

    def _fake_get(code, cache_dir, *, allow_fetch):
        calls.append(allow_fetch)
        path = cache_dir / f"{code}.pkl"
        if allow_fetch and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                pickle.dump(_ccd_mol(code), handle)
        with path.open("rb") as handle:
            return pickle.load(handle)

    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_ccd.get_ccd_mol", _fake_get)

    record = prefetch_and_audit_ccd(tmp_path, "ch")

    assert calls == [True, False]
    assert record["ccd_id"] == "CH"
    assert record["action"] == "downloaded"
    assert record["n_atoms"] == 1
    assert record["n_unique_atom_names"] == 1
    assert len(record["cache_sha256"]) == 64


def test_prefetch_rejects_wrong_cached_identity(monkeypatch, tmp_path):
    """下载返回或 cache 串档时必须在最终只读复核阶段阻断。"""
    path = tmp_path / "raw" / "ccd_cache" / "CH.pkl"
    path.parent.mkdir(parents=True)
    with path.open("wb") as handle:
        pickle.dump(_ccd_mol("OTHER"), handle)

    def _fake_get(_code, _cache_dir, *, allow_fetch):
        with path.open("rb") as handle:
            return pickle.load(handle)

    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_ccd.get_ccd_mol", _fake_get)

    with pytest.raises(ReceptorAtomNameCoverageError, match="identity mismatch"):
        prefetch_and_audit_ccd(tmp_path, "CH")

