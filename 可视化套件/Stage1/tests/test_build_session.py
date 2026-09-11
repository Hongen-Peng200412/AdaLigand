"""Synthetic contract tests for the Stage1 PyMOL session builder."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import numpy as np
from pymol import cmd


_MODULE_PATH = Path(__file__).resolve().parents[1] / "build_session.py"
_SPEC = importlib.util.spec_from_file_location("stage1_build_session", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class BuildSessionTest(unittest.TestCase):
    """Verify object separation, visibility and coordinate alignment."""

    def setUp(self) -> None:
        """Create a minimal source tree and common Stage1 result tree."""
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.data_root = self.root / "Ori_Data"
        self.inference_root = self.root / "inference"
        self.pdb_id = "1abc"
        parse_dir = self.data_root / "parse" / self.pdb_id
        density_dir = self.data_root / "density" / self.pdb_id
        ligand_object_dir = self.data_root / "ligand_objects"
        evaluation_dir = (
            self.inference_root
            / "unet_c1"
            / "held_out_test_0"
            / self.pdb_id
            / "evaluation"
        )
        blobs_dir = evaluation_dir.parent / "blobs"
        for directory in (
            parse_dir,
            density_dir,
            ligand_object_dir,
            evaluation_dir,
            blobs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        np.save(
            density_dir / "exp.npy", np.arange(24, dtype=np.float32).reshape(1, 2, 3, 4)
        )
        np.savez(
            density_dir / "exp.npz",
            origin=np.asarray([10.0, 20.0, 30.0], dtype=np.float32),
            voxel_size=np.asarray([2.0, 3.0, 4.0], dtype=np.float32),
            contour_canonical=np.asarray(7.5, dtype=np.float32),
        )
        np.savez(
            parse_dir / "receptor_tokens.npz",
            coords=np.asarray(
                [[11.0, 21.0, 31.0], [13.0, 21.0, 31.0]], dtype=np.float32
            ),
            element=np.asarray([6, 8], dtype=np.uint8),
            res_type=np.asarray([0, 0], dtype=np.uint8),
            atom_name=np.asarray([b"CA", b"O"], dtype="S4"),
            res_index=np.asarray([0, 0], dtype=np.int32),
            chain_index=np.asarray([0, 0], dtype=np.int32),
            bond_index=np.asarray([[0], [1]], dtype=np.int32),
            bond_type=np.asarray([0], dtype=np.uint8),
        )

        occurrence = {
            "candidate_id": 0,
            "object_key": "CCD:LIG",
            "type_tag": "small_molecule",
            "components": [
                {
                    "index": 1,
                    "ccd_id": "LIG",
                    "auth_asym_id": "A",
                    "auth_seq_id": "501",
                    "icode": "",
                }
            ],
        }
        (parse_dir / "occurrences.jsonl").write_text(
            json.dumps(occurrence) + "\n", encoding="utf-8"
        )
        np.savez(
            parse_dir / "ligand_coords.npz",
            coords_0=np.asarray(
                [[15.0, 26.0, 38.0], [16.0, 26.0, 38.0]], dtype=np.float32
            ),
            present_0=np.asarray([True, True]),
        )
        atom_dtype = np.dtype(
            [
                ("name", "i1", (4,)),
                ("element", "i1"),
                ("charge", "i1"),
                ("coords", "f4", (3,)),
                ("ref_pos", "f4", (3,)),
                ("is_present", "?"),
                ("chirality", "?", (7,)),
                ("in_ring", "?", (4,)),
                ("residue_id", "i4"),
            ]
        )
        atoms = np.zeros(2, dtype=atom_dtype)
        atoms["element"] = [6, 8]
        atoms["residue_id"] = 1
        bond_dtype = np.dtype(
            [
                ("atom_1", "i4"),
                ("atom_2", "i4"),
                ("type", "?", (5,)),
                ("in_ring", "?", (4,)),
            ]
        )
        bonds = np.zeros(1, dtype=bond_dtype)
        bonds["atom_1"] = 0
        bonds["atom_2"] = 1
        bonds["type"][0, 0] = True
        np.savez(
            ligand_object_dir / "CCD_LIG.npz",
            atoms=atoms,
            atom_names=np.asarray(["C1", "O1"]),
            bonds=bonds,
            residue_names=np.asarray(["LIG"]),
            blobs=np.asarray(None, dtype=object),
        )
        np.savez(
            blobs_dir / "F1_blobs.npz",
            blob_index=np.asarray([4, 9], dtype=np.int32),
            voxel_offsets=np.asarray([0, 2, 3], dtype=np.int64),
            voxel_index_global_zyx=np.asarray(
                [[0, 0, 0], [1, 2, 3], [0, 1, 2]], dtype=np.int32
            ),
        )
        np.savez(
            evaluation_dir / "f1_basic.npz",
            source_blob_index=np.asarray([9, 4], dtype=np.int32),
            candidate_score=np.asarray([0.8, 0.2], dtype=np.float32),
            candidate_selected=np.asarray([True, False]),
        )

    def tearDown(self) -> None:
        """Discard PyMOL state and the synthetic artifact tree."""
        cmd.reinitialize()
        self._temporary_directory.cleanup()

    def test_session_preserves_objects_visibility_and_world_coordinates(self) -> None:
        """Build, reload and inspect a complete synthetic ``.pse`` session."""
        output = self.root / "session.pse"
        args = Namespace(
            data_root=self.data_root,
            inference_root=self.inference_root,
            producer="unet_c1",
            split="held_out_test_0",
            pdb_id=self.pdb_id,
            alpha=1.0,
            evaluation_name="f1_basic",
            output=output,
        )
        _MODULE.build_session(args)
        self.assertTrue(output.is_file())

        cmd.reinitialize()
        cmd.load(str(output))
        object_names = set(cmd.get_names("objects"))
        self.assertIn("density_exp_map", object_names)
        self.assertIn("density_exp_mesh", object_names)
        self.assertIn("receptor", object_names)
        self.assertIn("gt_occ_0000_CCD_LIG", object_names)
        self.assertIn("pred_r0001_b000009_s0p800000_selected", object_names)
        self.assertIn("pred_r0002_b000004_s0p200000_unselected", object_names)
        all_names = set(cmd.get_names("all"))
        self.assertTrue(
            {"stage1", "density", "ground_truth", "predictions"}.issubset(all_names)
        )

        density_extent = np.asarray(cmd.get_extent("density_exp_map"))
        np.testing.assert_allclose(
            density_extent,
            np.asarray([[11.0, 21.5, 32.0], [17.0, 27.5, 36.0]]),
        )

        enabled_names = set(cmd.get_names("objects", enabled_only=1))
        self.assertIn("pred_r0001_b000009_s0p800000_selected", enabled_names)
        self.assertNotIn("pred_r0002_b000004_s0p200000_unselected", enabled_names)
        receptor_coordinates = np.asarray(cmd.get_coords("receptor", state=1))
        np.testing.assert_allclose(
            receptor_coordinates,
            np.asarray([[11.0, 21.0, 31.0], [13.0, 21.0, 31.0]]),
        )
        gt_coordinates = np.asarray(cmd.get_coords("gt_occ_0000_CCD_LIG", state=1))
        np.testing.assert_allclose(
            gt_coordinates,
            np.asarray([[15.0, 26.0, 38.0], [16.0, 26.0, 38.0]]),
        )
        selected_coordinates = np.asarray(
            cmd.get_coords("pred_r0001_b000009_s0p800000_selected", state=1)
        )
        np.testing.assert_allclose(
            selected_coordinates, np.asarray([[15.0, 24.5, 32.0]])
        )

        cmd.isolevel("density_exp_mesh", 9.0)
        cmd.isomesh(
            "density_near_gt",
            "density_exp_map",
            9.0,
            "gt_occ_0000_CCD_LIG",
            carve=4.0,
        )
        cmd.isomesh(
            "density_near_prediction",
            "density_exp_map",
            9.0,
            "pred_r0001_b000009_s0p800000_selected",
            carve=4.0,
        )
        self.assertIn("density_near_gt", cmd.get_names("objects"))
        self.assertIn("density_near_prediction", cmd.get_names("objects"))


if __name__ == "__main__":
    unittest.main()
