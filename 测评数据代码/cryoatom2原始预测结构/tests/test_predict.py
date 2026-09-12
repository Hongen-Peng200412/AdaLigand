"""用真实 JSON/FASTA/gzip/mmCIF 和替身子进程验证批处理契约, 不加载模型或申请 GPU."""

import gzip
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


spec = importlib.util.spec_from_file_location("cryoatom_batch", Path(__file__).parents[1] / "predict.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)

CIF = """data_prediction
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
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_asym_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA A 1 1 ? 1.0 2.0 3.0 1.0 85.0 1 A 1
#
"""


@pytest.fixture
def example(tmp_path, monkeypatch):
    data = tmp_path / "Ori_Data"
    (data / "raw/emdb_maps").mkdir(parents=True)
    ids = ["1aaa", "2bbb", "3ccc", "4ddd", "5eee"]
    kinds = ["protein", "rna", "dna", "protein", "rna"]
    sequences = ["ACD", "AUXG", "ACGT", "AXCD", "AUG"]
    pairs = []
    entities = []
    for i, (pdb, kind, sequence) in enumerate(zip(ids, kinds, sequences)):
        pairs.append({"pdb_id": pdb, "emdb_id": f"EMD-{i}"})
        entities.append({"pdb_id": pdb, "sequence_id": f"{pdb.upper()}_1", "sequence_class": kind, "sequence": sequence, "label_asym_ids": ["A", "B"], "comparable": False})
        with gzip.open(data / f"raw/emdb_maps/emd_{i}.map.gz", "wb") as handle:
            handle.write(b"unchanged native map header and voxels")
    (data / "raw/pair_list.jsonl").write_text("\n".join(json.dumps(x) for x in pairs), encoding="utf-8")
    catalog = tmp_path / "sequence_catalog.jsonl"
    catalog.write_text("\n".join(json.dumps(x) for x in entities), encoding="utf-8")
    split = tmp_path / "test_0.json"
    split.write_text(json.dumps({"pdb_ids": ids}), encoding="utf-8")
    package = tmp_path / "site-packages/CryoAtom2"
    (package / "checkpoint").mkdir(parents=True)
    (package / "config.json").write_text('{"CryoNet_args":{"filter_threshold":50}}')
    (package / "checkpoint/CryoNet.pth").write_bytes(b"model")
    cache = tmp_path / "hub/checkpoints"
    cache.mkdir(parents=True)
    for name in ["esm2_t33_650M_UR50D.pt", "esm2_t33_650M_UR50D-contact-regression.pt", "RNA-FM_pretrained.pth"]:
        (cache / name).write_bytes(b"cached model")
    monkeypatch.setattr(batch.importlib.metadata, "distribution", lambda _: SimpleNamespace(version="2.1.1", locate_file=lambda _: package))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(hub=SimpleNamespace(get_dir=lambda: str(cache.parent))))
    calls = []
    fail_ids = set()
    malformed_ids = set()

    def fake_run(command, **kwargs):
        calls.append(command)
        unpacked = Path(command[command.index("--map-path") + 1])
        assert unpacked.read_bytes() == b"unchanged native map header and voxels"
        output = Path(command[command.index("--output-dir") + 1])
        pdb = output.parent.name
        assert command[command.index("--device") + 1] == "cuda:0"
        assert kwargs["check"] is False
        kwargs["stdout"].write("official output\n")
        output.mkdir(parents=True)
        text = "not a CIF" if pdb in malformed_ids else CIF
        (output / f"{output.name}.cif").write_text(text)
        (output / f"{output.name}_raw.cif").write_text(CIF)
        (output / "see_alpha_output").mkdir()
        (output / "see_alpha_output/temp.log").write_text("getp diagnostic")
        return SimpleNamespace(returncode=17 if pdb in fail_ids else 0)

    monkeypatch.setattr(batch.subprocess, "run", fake_run)
    return SimpleNamespace(data=data, ids=ids, catalog=catalog, split=split, output=tmp_path / "results", scratch=tmp_path / "scratch", calls=calls, fail_ids=fail_ids, malformed_ids=malformed_ids)


@pytest.mark.parametrize("list_split,shard_count,expected_order", [(False, 3, ["1aaa", "4ddd", "2bbb", "5eee", "3ccc"]), (True, 2, ["1aaa", "3ccc", "5eee", "2bbb", "4ddd"])])
def test_shards_preserve_full_sequences_and_native_maps(example, list_split, shard_count, expected_order):
    if list_split:
        example.split.write_text(json.dumps(example.ids), encoding="utf-8")
    original_maps = {p: p.read_bytes() for p in (example.data / "raw/emdb_maps").iterdir()}
    for index in range(shard_count):
        assert batch.run_shard(example.split, example.data, example.catalog, example.output, example.scratch, index, shard_count, f"run_{index}") == 0
    observed = [Path(command[command.index("--output-dir") + 1]).parent.name for command in example.calls]
    assert observed == expected_order
    assert len(set(observed)) == 5
    log = example.output / "运行日志与统计/pdb/2bbb/run_1"
    assert (log / "rna.fasta").read_text(encoding="utf-8") == ">2BBB_1|Chains A, B\nAUXG\n"
    assert not (log / "protein.fasta").exists()
    source = json.loads((log / "inputs.json").read_text(encoding="utf-8"))
    assert source["ignored_characters"] == [{"sequence_id": "2BBB_1", "index": 2, "character": "X"}]
    assert source["entities"][0]["comparable"] is False
    assert batch.summarize(example.split, example.output)["counts"] == {"pending": 0, "running": 0, "success": 5, "failed": 0}
    assert all(path.read_bytes() == original for path, original in original_maps.items())
    assert not list(example.scratch.iterdir())
    assert all(path.suffix == ".cif" for path in (example.output / "cryoatom2_artifact").rglob("*") if path.is_file())


def test_failure_continues_and_retry_preserves_old_artifacts(example):
    example.fail_ids.add("1aaa")
    assert batch.run_shard(example.split, example.data, example.catalog, example.output, example.scratch, 0, 3, "first") == 1
    summary = batch.summarize(example.split, example.output)
    assert summary["counts"] == {"pending": 3, "running": 0, "success": 1, "failed": 1}
    assert "退出码 17" in summary["pdbs"][0]["error"]
    example.fail_ids.clear()
    assert batch.run_shard(example.split, example.data, example.catalog, example.output, example.scratch, 0, 3, "retry") == 0
    assert len(example.calls) == 3
    assert (example.output / "cryoatom2_artifact/1aaa/first/first.cif").exists()
    assert (example.output / "cryoatom2_artifact/1aaa/retry/retry.cif").exists()
    first = json.loads((example.output / "运行日志与统计/pdb/1aaa/first/status.json").read_text(encoding="utf-8"))
    latest = json.loads((example.output / "运行日志与统计/pdb/1aaa/latest.json").read_text(encoding="utf-8"))
    assert first["status"] == "failed" and latest["status"] == "success"
    assert (example.output / "运行日志与统计/pdb/1aaa/first/official_logs/see_alpha_output/temp.log").read_text() == "getp diagnostic"
    assert not list((example.output / "cryoatom2_artifact").rglob("*.log"))


def test_invalid_cif_is_failure_even_when_process_succeeds(example):
    example.malformed_ids.add("1aaa")
    assert batch.run_shard(example.split, example.data, example.catalog, example.output, example.scratch, 0, 3, "malformed") == 1
    status = json.loads((example.output / "运行日志与统计/pdb/1aaa/latest.json").read_text(encoding="utf-8"))
    assert status["returncode"] == 0 and status["status"] == "failed"
    assert len(example.calls) == 2


def test_missing_map_does_not_skip_remaining_pdbs(example):
    (example.data / "raw/emdb_maps/emd_0.map.gz").unlink()
    assert batch.run_shard(example.split, example.data, example.catalog, example.output, example.scratch, 0, 3, "missing") == 1
    assert len(example.calls) == 1
    assert batch.summarize(example.split, example.output)["counts"]["failed"] == 1


def test_duplicate_split_rejected_before_work(example):
    example.split.write_text('{"pdb_ids":["1aaa","1aaa"]}')
    with pytest.raises(ValueError, match="重复"):
        batch.run_shard(example.split, example.data, example.catalog, example.output, example.scratch, 0, 3, "duplicate")
    assert not example.calls


def test_mixed_complex_passes_all_entity_sequences(example):
    with example.catalog.open("a", encoding="utf-8") as handle:
        for kind, sequence in [("rna", "AUXG"), ("dna", "ACGT")]:
            handle.write("\n" + json.dumps({"pdb_id": "1aaa", "sequence_id": f"1AAA_{kind}", "sequence_class": kind, "sequence": sequence, "label_asym_ids": ["C"], "comparable": False}))
    batch.run_shard(example.split, example.data, example.catalog, example.output, example.scratch, 0, 3, "mixed")
    command = example.calls[0]
    assert all(f"--{kind}-sequence-path" in command for kind in ("protein", "rna", "dna"))
    inputs = json.loads((example.output / "运行日志与统计/pdb/1aaa/mixed/inputs.json").read_text(encoding="utf-8"))
    assert len(inputs["entities"]) == 3


def test_summary_rechecks_outputs_without_rewriting_success_status(example):
    batch.run_shard(example.split, example.data, example.catalog, example.output, example.scratch, 0, 3, "complete")
    latest_path = example.output / "运行日志与统计/pdb/1aaa/latest.json"
    before = latest_path.read_bytes()
    (example.output / "cryoatom2_artifact/1aaa/complete/complete_raw.cif").write_text("broken")
    assert batch.summarize(example.split, example.output)["pdbs"][0]["status"] == "failed"
    assert latest_path.read_bytes() == before
