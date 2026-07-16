"""合成 MRC/mmCIF + fake Chimera/MapQ 的 A–G（阈值显式）端到端 smoke。"""

from __future__ import annotations

import gzip
import json
import pickle
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from rdkit import Chem


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from atom_labels import build_atom_labels
from chimera import ChimeraRunner
from contracts import CArtifactState, inspect_stage_c, load_npz_arrays
from density import build_experimental_density, build_ligand_area, build_simulated_density
from filtering import run_stage_g
from failures import KnownFailureCode, KnownSampleFailure
from io_utils import atomic_save_npz, read_jsonl, write_jsonl
from mapq import MapQRunner
from mrc import MapGrid, write_canonical_mrc
from parse import parse_one_pdb
from quality import build_quality
from reports import stage_report_path, stage_result, write_stage_results


def _ccd_mol(names: list[str], atomic_numbers: list[int], positions: list[tuple[float, float, float]]) -> Chem.Mol:
    """构造带 CCD atom name、单键和 conformer 的最小连通 RDKit Mol。"""
    editable = Chem.RWMol()
    for name, atomic_number in zip(names, atomic_numbers, strict=True):
        atom = Chem.Atom(atomic_number)
        atom.SetProp("name", name)
        editable.AddAtom(atom)
    for index in range(len(names) - 1):
        editable.AddBond(index, index + 1, Chem.BondType.SINGLE)
    mol = editable.GetMol()
    conformer = Chem.Conformer(len(names))
    for index, position in enumerate(positions):
        conformer.SetAtomPosition(index, position)
    mol.AddConformer(conformer)
    return mol


def _write_inputs(root: Path, contour_level: float | None = 0.02) -> dict:
    """写一个蛋白残基、一个双原子 ligand、native map 和可选主 contour metadata。"""
    record = {
        "pdb_id": "1abc",
        "emdb_id": "EMD-1",
        "resolution": 2.8,
        "resolution_info": {"selected": 2.8, "status": "single_unique"},
    }
    write_jsonl(root / "raw" / "pair_list.jsonl", [record])
    cif_path = root / "raw" / "rcsb_mmcif" / "1abc.cif"
    cif_path.parent.mkdir(parents=True, exist_ok=True)
    cif_path.write_text(
        """data_1abc
loop_
_entity.id
_entity.type
1 polymer
2 non-polymer
loop_
_chem_comp.id
_chem_comp.type
ALA 'L-PEPTIDE LINKING'
LIG NON-POLYMER
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.auth_atom_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_model_num
ATOM 1 N N . ALA A 1 1 ? 1 1 1 1.0 N ALA A 1 1
ATOM 2 C CA . ALA A 1 1 ? 2 1 1 1.0 CA ALA A 1 1
ATOM 3 C C . ALA A 1 1 ? 2 2 1 1.0 C ALA A 1 1
ATOM 4 O O . ALA A 1 1 ? 2 2 2 1.0 O ALA A 1 1
HETATM 5 C C1 . LIG B 2 . ? 4 4 4 1.0 C1 LIG Z 9 1
HETATM 6 O O1 . LIG B 2 . ? 5 4 4 1.0 O1 LIG Z 9 1
""",
        encoding="utf-8",
    )
    cache = root / "raw" / "ccd_cache"
    cache.mkdir(parents=True, exist_ok=True)
    ala = _ccd_mol(
        ["N", "CA", "C", "O"],
        [7, 6, 6, 8],
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
    )
    lig = _ccd_mol(["C1", "O1"], [6, 8], [(0, 0, 0), (1, 0, 0)])
    ala.SetProp("PDB_NAME", "ALA")
    lig.SetProp("PDB_NAME", "LIG")
    with (cache / "ALA.pkl").open("wb") as handle:
        pickle.dump(ala, handle)
    with (cache / "LIG.pkl").open("wb") as handle:
        pickle.dump(lig, handle)

    z, y, x = np.indices((7, 8, 9), dtype=np.float32)
    volume = np.exp(-((x - 4.0) ** 2 + (y - 3.5) ** 2 + (z - 3.0) ** 2) / 5.0).astype(
        np.float32
    )
    native_mrc = root / "native.mrc"
    # 此 fixture 按 Pocket native-map 契约把 header.origin 写成体素坐标；默认 loader 会乘 voxel。
    write_canonical_mrc(
        native_mrc,
        MapGrid(
            volume,
            np.asarray([1.2, 1.3, 1.4], dtype=np.float32),
            np.asarray([-2.0, -2.0, -2.0], dtype=np.float32),
        ),
    )
    map_path = root / "raw" / "emdb_maps" / "emd_1.map.gz"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    with native_mrc.open("rb") as source, gzip.open(map_path, "wb") as target:
        shutil.copyfileobj(source, target)
    native_mrc.unlink()
    meta_path = root / "reports" / "meta" / "1abc.meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    contours = (
        [{"level": contour_level, "primary": True, "source": "AUTHOR"}]
        if contour_level is not None
        else []
    )
    meta_path.write_text(
        json.dumps({"map": {"contour_list": {"contour": contours}}}),
        encoding="utf-8",
    )
    return record


def _write_fake_chimera(path: Path) -> None:
    """fake Chimera：molmap 复制 canonical MRC，CC 返回固定四量。"""
    path.write_text(
        """from pathlib import Path
import re
import shutil
import sys

if '--version' in sys.argv:
    print('UCSF Chimera fake 1.19')
    raise SystemExit(0)
script = Path(sys.argv[sys.argv.index('--script') + 1])
text = script.read_text(encoding='utf-8')
if 'saveStep 1 saveRegion all' in text:
    opened = re.findall(r"rc\\('open ([^']+)'\\)", text)
    output = re.search(r'volume #2 save \\\"([^\\\"]+)\\\"', text).group(1)
    shutil.copyfile(opened[1], output)
if 'ADALIGAND_CC_CONTOUR_BEGIN' in text:
    print('ADALIGAND_CC_CONTOUR_BEGIN')
    print('correlation = 0.91, correlation about mean = 0.81')
    print('ADALIGAND_CC_CONTOUR_END')
if 'ADALIGAND_CC_ALL_BEGIN' in text:
    print('ADALIGAND_CC_ALL_BEGIN')
    print('correlation = 0.71, correlation about mean = 0.61')
    print('ADALIGAND_CC_ALL_END')
""",
        encoding="utf-8",
    )


def _write_fake_mapq(path: Path) -> None:
    """fake MapQ：为全部标准化 full-model 原子添加有限 Q-score 并反转行序。"""
    path.write_text(
        """from pathlib import Path
import gemmi
import sys

def _upstream_cif_anchor(fp, mod):
    fp.write ( "mol = mmcif.ReadMol ( '%s' )[0]\\n" % mod )

args = dict(item.split('=', 1) for item in sys.argv if '=' in item)
cif = Path(args['cif'])
native = Path(args['map'])
document = gemmi.cif.read(str(cif))
block = document.sole_block()
category = block.get_mmcif_category('_atom_site.')
category['Q-score'] = [str(0.2 + 0.05 * i) for i in range(len(category['id']))]
category = {key: list(reversed(values)) for key, values in category.items()}
block.set_mmcif_category('_atom_site.', category)
output = Path(str(cif) + '__Q__' + native.name + '.cif')
output.write_text(document.as_string(), encoding='utf-8')
print('MapQ CLI 1.9.12')
""",
        encoding="utf-8",
    )


def test_synthetic_pipeline_smoke_reaches_g_analysis_and_explicit_filter(tmp_path: Path) -> None:
    """一次调用完成 C→D→E→F→G，期间不复制日志或人工续跑。"""
    root = tmp_path / "data"
    scratch = tmp_path / "scratch"
    record = _write_inputs(root)
    parse_result = parse_one_pdb(root, "1abc", overwrite=True)
    assert parse_result["status"] == "ok"
    assert inspect_stage_c(root, "1abc").state is CArtifactState.COMPLETE

    d_result = build_atom_labels(root, "1abc")
    assert d_result["status"] == "success"
    e1_result = build_experimental_density(root, record)
    assert e1_result["status"] == "success"
    with np.load(root / "density" / "1abc" / "exp.npz", allow_pickle=False) as exp:
        assert not np.array_equal(exp["voxel_size"], np.ones((3,), dtype=np.float32))
        assert np.any(exp["origin"] != 0)
        contour_native = float(exp["contour_native"])
        contour_canonical = float(exp["contour_canonical"])
        contour_scale = float(exp["contour_scale_to_canonical"])
        assert contour_scale > 0
        assert np.isclose(
            contour_canonical,
            np.float32(contour_native * contour_scale),
            rtol=0,
            atol=0,
        )
    assert build_experimental_density(root, record)["status"] == "skipped"

    fake_chimera = tmp_path / "fake_chimera.py"
    _write_fake_chimera(fake_chimera)
    chimera_runner = ChimeraRunner([sys.executable, str(fake_chimera)], timeout_seconds=10)
    chimera_version = chimera_runner.probe(scratch / "probe")
    e2_result = build_simulated_density(
        root,
        record,
        runner=chimera_runner,
        chimera_version=chimera_version,
        run_id="smoke",
        scratch_root=scratch,
    )
    e3_result = build_ligand_area(root, "1abc")
    assert e2_result["status"] == e3_result["status"] == "success"

    fake_mapq = tmp_path / "mapq_cmd.py"
    _write_fake_mapq(fake_mapq)
    chimera_root = tmp_path / "chimera"
    chimera_root.mkdir()
    mapq_runner = MapQRunner([sys.executable], fake_mapq, chimera_root, timeout_seconds=10)
    f_result = build_quality(
        root,
        record,
        chimera_runner=chimera_runner,
        mapq_runner=mapq_runner,
        chimera_version=chimera_version,
        run_id="smoke",
        scratch_root=scratch,
    )
    assert f_result["status"] == "success"
    quality = read_jsonl(root / "quality" / "1abc.jsonl")
    assert len(quality) == 1
    assert quality[0]["n_valid"] == quality[0]["n_present"] == 2
    assert quality[0]["pocket_n_atoms"] == 4
    assert np.isclose(quality[0]["pocket_q_score"], 0.275, rtol=0, atol=1e-6)
    assert quality[0]["cc_contour"] == 0.91
    provenance = json.loads((root / "quality" / "1abc.provenance.json").read_text(encoding="utf-8"))
    assert provenance["contour"]["native_value"] == contour_native
    assert provenance["contour"]["canonical_value"] == contour_canonical
    assert provenance["contour"]["scale_to_canonical"] == contour_scale
    correlation_script = (scratch / f_result["scratch"] / "correlation.py").read_text(
        encoding="utf-8"
    )
    assert (
        f"experimental_map.set_parameters(surface_levels=[{contour_canonical:.9g}])"
        in correlation_script
    )
    assert "volume #0 level" not in correlation_script

    # 单独破坏人类可读 provenance 后，F 必须拒绝复用并从当前 E1 重新生成。
    provenance["contour"]["scale_to_canonical"] = contour_scale * 2.0
    provenance_path = root / "quality" / "1abc.provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    repaired_f = build_quality(
        root,
        record,
        chimera_runner=chimera_runner,
        mapq_runner=mapq_runner,
        chimera_version=chimera_version,
        run_id="smoke_provenance_repair",
        scratch_root=scratch,
    )
    assert repaired_f["status"] == "success"
    repaired_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert repaired_provenance["contour"]["scale_to_canonical"] == contour_scale
    assert (
        build_quality(
            root,
            record,
            chimera_runner=chimera_runner,
            mapq_runner=mapq_runner,
            chimera_version=chimera_version,
            run_id="smoke_provenance_skip",
            scratch_root=scratch,
        )["status"]
        == "skipped"
    )

    for stage in ("stage_d", "stage_e", "stage_f"):
        write_stage_results(
            stage_report_path(root, "smoke", stage, 0, 1),
            [stage_result("1abc", stage, "success")],
        )
    analysis = run_stage_g(root, "smoke", mode="analyze")
    assert analysis["status"] == "analysis_complete_filter_pending"
    assert not (root / "keep_list.jsonl").exists()

    config_path = root / "filter_config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "cc_field": "cc_all_about_mean",
                "cc_min": -1.0,
                "resolution_max": 3.0,
                "resolution_comparison": "inclusive",
                "ligand_q_min": -1.0,
                "pocket_q_min": -1.0,
                "qualified_pair_fraction_min": 0.0,
                "empty_pocket": "fail_and_count_denominator",
                "keep_only_maps_that_pass": True,
                "keep_all_occurrences_in_passing_map": True,
            }
        ),
        encoding="utf-8",
    )
    filtered = run_stage_g(root, "smoke", mode="filter", config_path=config_path)
    assert filtered["n_kept_occurrences"] == 1
    assert read_jsonl(root / "keep_list.jsonl") == [{"candidate_id": 0, "pdb_id": "1abc"}]


def test_model_map_frame_mismatch_is_known_in_e_and_f_before_external_tools(
    tmp_path: Path,
) -> None:
    """E/F 对同一完全分离的世界坐标帧返回同一 known failure。"""
    root = tmp_path / "data"
    scratch = tmp_path / "scratch"
    record = _write_inputs(root)
    assert parse_one_pdb(root, "1abc", overwrite=True)["status"] == "ok"
    assert build_experimental_density(root, record)["status"] == "success"

    receptor_path = root / "parse" / "1abc" / "receptor_tokens.npz"
    receptor = load_npz_arrays(receptor_path, allow_pickle=False)
    receptor["coords"] = receptor["coords"] + np.asarray(
        [1000.0, 1000.0, 1000.0],
        dtype=np.float32,
    )
    atomic_save_npz(receptor_path, **receptor)
    assert inspect_stage_c(root, "1abc").state is CArtifactState.COMPLETE

    with pytest.raises(KnownSampleFailure) as e_error:
        build_simulated_density(
            root,
            record,
            runner=object(),
            chimera_version="must-not-run",
            run_id="frame_mismatch_e",
            scratch_root=scratch,
        )
    with pytest.raises(KnownSampleFailure) as f_error:
        build_quality(
            root,
            record,
            chimera_runner=object(),
            mapq_runner=object(),
            chimera_version="must-not-run",
            run_id="frame_mismatch_f",
            scratch_root=scratch,
        )
    assert e_error.value.code is KnownFailureCode.MODEL_MAP_FRAME_MISMATCH
    assert f_error.value.code is KnownFailureCode.MODEL_MAP_FRAME_MISMATCH
    assert not (root / "density" / "1abc" / "sim.npz").exists()
    assert not (root / "quality" / "1abc.jsonl").exists()
    assert not (scratch / "frame_mismatch_e" / "stage_e" / "1abc").exists()
    assert not (scratch / "frame_mismatch_f" / "stage_f" / "1abc").exists()


def test_missing_contour_reaches_f_with_three_null_provenance_values(tmp_path: Path) -> None:
    """缺 recommended contour 时，E1 三个 NaN 必须在 F 转成三个 JSON null。"""
    root = tmp_path / "data"
    scratch = tmp_path / "scratch"
    record = _write_inputs(root, contour_level=None)
    assert parse_one_pdb(root, "1abc", overwrite=True)["status"] == "ok"
    assert build_experimental_density(root, record)["status"] == "success"

    with np.load(root / "density" / "1abc" / "exp.npz", allow_pickle=False) as exp:
        assert not bool(exp["contour_present"])
        assert all(
            np.isnan(float(exp[key]))
            for key in ("contour", "contour_native", "contour_canonical")
        )

    fake_chimera = tmp_path / "fake_chimera.py"
    fake_mapq = tmp_path / "mapq_cmd.py"
    chimera_root = tmp_path / "chimera"
    _write_fake_chimera(fake_chimera)
    _write_fake_mapq(fake_mapq)
    chimera_root.mkdir()
    chimera_runner = ChimeraRunner([sys.executable, str(fake_chimera)], timeout_seconds=10)
    chimera_version = chimera_runner.probe(scratch / "probe")
    mapq_runner = MapQRunner([sys.executable], fake_mapq, chimera_root, timeout_seconds=10)

    result = build_quality(
        root,
        record,
        chimera_runner=chimera_runner,
        mapq_runner=mapq_runner,
        chimera_version=chimera_version,
        run_id="missing_contour",
        scratch_root=scratch,
    )
    assert result["status"] == "success"
    provenance = json.loads(
        (root / "quality" / "1abc.provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["contour"]["value"] is None
    assert provenance["contour"]["native_value"] is None
    assert provenance["contour"]["canonical_value"] is None
    records = read_jsonl(root / "quality" / "1abc.jsonl")
    assert records[0]["cc_contour"] is None
    assert records[0]["cc_contour_about_mean"] is None
