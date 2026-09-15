"""验证 CryoAtom2 受体 Adapter 的来源选择、产物布局和无哈希正式代码边界."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np


ADAPTER_ROOT = Path(__file__).resolve().parents[1]
ORI_DATA_ROOT = Path(__file__).resolve().parents[3] / "Data_Preprocessing" / "Ori_Data"
sys.path.insert(0, str(ADAPTER_ROOT))
sys.path.insert(0, str(ORI_DATA_ROOT))

import adapter  # noqa: E402


def _write_minimal_receptor_cif(path: Path) -> None:
    """写出一份不含 ``_entity`` 的单原子 CryoAtom2 风格 mmCIF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """data_test
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.auth_atom_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.label_alt_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA ALA A ? 1 CA ALA A 1 ? 1.0 2.0 3.0 1.0 . 1
""",
        encoding="utf-8",
        newline="\n",
    )


def _prepare_reference_root(root: Path, pdb_id: str) -> None:
    """建立单样本测试所需的主 ``Ori_Data`` 最小文件集合."""
    (root / "raw/ccd_cache").mkdir(parents=True)
    (root / "ligand_objects").mkdir()
    (root / "ligand_descriptors").mkdir()
    (root / "raw/pair_list.jsonl").write_text(
        json.dumps({"pdb_id": pdb_id, "resolution": 3.2, "resolution_info": {"source": "test"}}) + "\n",
        encoding="utf-8",
    )
    parse_root = root / "parse" / pdb_id
    parse_root.mkdir(parents=True)
    (parse_root / "occurrences.jsonl").write_text("", encoding="utf-8")
    np.savez(parse_root / "ligand_coords.npz")
    density_root = root / "density" / pdb_id
    density_root.mkdir(parents=True)
    np.save(density_root / "exp.npy", np.ones((1, 2, 3, 4), dtype=np.float32), allow_pickle=False)
    np.savez(
        density_root / "exp.npz",
        voxel_size=np.ones(3, dtype=np.float32),
        origin=np.asarray([-1.0, -2.0, -3.0], dtype=np.float32),
    )
    for name in ("ligand_area.npz", "union_mask.npy", "ligand_dist.npy", "ligand_dist.npz"):
        (density_root / name).write_bytes(b"test")


def test_prepare_receptor_dataset_uses_final_cif_and_writes_stage1_assets(tmp_path: Path, monkeypatch) -> None:
    """公共入口应使用 latest 最终 CIF, 并写出 Stage1 三件套和只读真值链接."""
    pdb_id = "1abc"
    reference_root = tmp_path / "reference"
    output_root = tmp_path / "adapted"
    source_cif = tmp_path / "cryo" / "final.cif"
    scratch_root = tmp_path / "scratch"
    _prepare_reference_root(reference_root, pdb_id)
    _write_minimal_receptor_cif(source_cif)
    split_file = tmp_path / "split.json"
    split_file.write_text(json.dumps({"pdb_ids": [pdb_id]}), encoding="utf-8")
    latest_path = tmp_path / "cryo" / "运行日志与统计" / "pdb" / pdb_id / "latest.json"
    latest_path.parent.mkdir(parents=True)
    latest_path.write_text(
        json.dumps({"pdb_id": pdb_id, "status": "success", "final_cif": str(source_cif)}),
        encoding="utf-8",
    )

    receptor_arrays = {
        "coords": np.asarray([[1.0, 2.0, 3.0]], dtype=np.float32),
        "element": np.asarray([6], dtype=np.uint8),
        "res_type": np.asarray([0], dtype=np.uint8),
        "is_backbone": np.asarray([True], dtype=bool),
        "atom_name": np.asarray([b"CA"], dtype="S4"),
        "res_index": np.asarray([0], dtype=np.int32),
        "chain_index": np.asarray([0], dtype=np.int32),
        "bond_index": np.empty((2, 0), dtype=np.int32),
        "bond_type": np.empty((0,), dtype=np.uint8),
        "feat": np.zeros((1, 49), dtype=np.float32),
    }
    monkeypatch.setattr(adapter, "build_receptor_arrays", lambda *args, **kwargs: receptor_arrays)

    def fake_write_normalized_model_cif(source, target, atom_only):
        """写出测试占位 CIF 并返回一个受体重原子计数."""
        target.write_text("data_x\n", encoding="utf-8")
        return {"n_atoms": 1}

    monkeypatch.setattr(adapter, "write_normalized_model_cif", fake_write_normalized_model_cif)
    monkeypatch.setattr(adapter, "write_canonical_mrc", lambda path, grid: path.write_bytes(b"mrc"))

    class FakeRunner:
        """以固定文件替代测试中的外部 Chimera 子进程."""

        def __init__(self, command, timeout_seconds):
            self.command = command
            self.timeout_seconds = timeout_seconds

        def probe(self, scratch_dir):
            return "UCSF Chimera test"

        def molmap_on_grid(self, model_cif, canonical_mrc, output_mrc, resolution, scratch_dir):
            output_mrc.write_bytes(b"sim")

    monkeypatch.setattr(adapter, "ChimeraRunner", FakeRunner)
    monkeypatch.setattr(
        adapter,
        "load_map",
        lambda path, multiply_global_origin: adapter.MapGrid(
            grid=np.ones((2, 3, 4), dtype=np.float32),
            voxel_size=np.ones(3, dtype=np.float32),
            origin=np.asarray([-1.0, -2.0, -3.0], dtype=np.float32),
        ),
    )

    results = adapter.prepare_receptor_dataset(
        split_file,
        tmp_path / "cryo",
        reference_root,
        output_root,
        scratch_root,
        ("chimera",),
        1,
        3600.0,
    )

    result = results[0]
    assert result["status"] == "success"
    assert result["receptor_atom_count"] == 1
    assert result["sim_shape_zyx"] == [2, 3, 4]
    assert (output_root / "raw/rcsb_mmcif/1abc.cif").resolve() == source_cif.resolve()
    assert (output_root / "density/1abc/exp.npy").is_symlink()
    assert not (output_root / "labels").exists()
    records = [json.loads(line) for line in (output_root / "受体适配记录.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [record["pdb_id"] for record in records] == [pdb_id]
    with np.load(output_root / "parse/1abc/receptor_tokens.npz", allow_pickle=False) as archive:
        assert set(archive.files) == set(receptor_arrays)
    with np.load(output_root / "density/1abc/sim.npz", allow_pickle=False) as archive:
        assert int(archive["schema_version"]) == 2
        assert np.array_equal(archive["voxel_size"], np.ones(3, dtype=np.float32))
        assert all("sha" not in key.lower() and "hash" not in key.lower() for key in archive.files)


def test_formal_adapter_source_does_not_implement_hashing() -> None:
    """正式 Python 与 shell 不应导入或调用哈希实现."""
    source = "\n".join(
        (ADAPTER_ROOT / name).read_text(encoding="utf-8")
        for name in ("adapter.py", "run.py")
    )
    shell = (ADAPTER_ROOT / "sh/prepare.sh").read_text(encoding="utf-8")
    assert "hashlib" not in source
    assert "sha256" not in source.lower()
    assert "sha256" not in shell.lower()
    assert "--overwrite" not in source
    assert "--overwrite" not in shell
    assert shell.count("--workers 32") == 2
    assert shell.count('"${PYTHON}" "${ADAPTER_ROOT}/run.py"') == 2
    assert "AdaLigand_stage1_py310/bin/python" in shell
