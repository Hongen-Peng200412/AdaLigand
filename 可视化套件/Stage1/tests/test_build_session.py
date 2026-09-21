"""Synthetic contract tests for the Stage1 PyMOL session builder."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import numpy as np
from pymol import cmd


_MODULE_PATH = Path(__file__).resolve().parents[1] / "build_session.py"
sys.path.insert(0, str(_MODULE_PATH.parent))
_SPEC = importlib.util.spec_from_file_location("stage1_build_session", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

import build_comparison_sessions as _COMPARISON  # noqa: E402


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

        occurrences = [
            {
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
            },
            {
                "candidate_id": 1,
                "object_key": "CCD:LIG",
                "type_tag": "small_molecule",
                "components": [
                    {
                        "index": 1,
                        "ccd_id": "LIG",
                        "auth_asym_id": "B",
                        "auth_seq_id": "502",
                        "icode": "",
                    }
                ],
            },
        ]
        (parse_dir / "occurrences.jsonl").write_text(
            "".join(json.dumps(occurrence) + "\n" for occurrence in occurrences),
            encoding="utf-8",
        )
        np.savez(
            parse_dir / "ligand_coords.npz",
            coords_0=np.asarray(
                [[15.0, 26.0, 38.0], [16.0, 26.0, 38.0]], dtype=np.float32
            ),
            present_0=np.asarray([True, True]),
            coords_1=np.asarray(
                [[17.0, 26.0, 38.0], [18.0, 26.0, 38.0]], dtype=np.float32
            ),
            present_1=np.asarray([True, True]),
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
            source_probability_mean=np.asarray([0.2, 0.8], dtype=np.float32),
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
        self.assertIn("gt_occ_0001_CCD_LIG", object_names)
        self.assertIn("pred_r0001_b000009_s0p800000_selected", object_names)
        self.assertIn("pred_r0002_b000004_s0p200000_unselected", object_names)
        self.assertEqual(
            set(cmd.get_names_of_type("object:group")),
            {"density", "ground_truth", "predictions"},
        )
        self.assertEqual(
            set(cmd.get_object_list("(ground_truth)")),
            {"gt_occ_0000_CCD_LIG", "gt_occ_0001_CCD_LIG"},
        )
        self.assertEqual(
            set(cmd.get_object_list("(predictions)")),
            {
                "pred_r0001_b000009_s0p800000_selected",
                "pred_r0002_b000004_s0p200000_unselected",
            },
        )

        density_extent = np.asarray(cmd.get_extent("density_exp_map"))
        np.testing.assert_allclose(
            density_extent,
            np.asarray([[11.0, 21.5, 32.0], [17.0, 27.5, 36.0]]),
        )

        enabled_names = set(cmd.get_names("objects", enabled_only=1))
        self.assertIn("pred_r0001_b000009_s0p800000_selected", enabled_names)
        self.assertNotIn("pred_r0002_b000004_s0p200000_unselected", enabled_names)
        cmd.disable("gt_occ_0000_CCD_LIG")
        self.assertNotIn(
            "gt_occ_0000_CCD_LIG", set(cmd.get_names("objects", enabled_only=1))
        )
        self.assertIn(
            "gt_occ_0001_CCD_LIG", set(cmd.get_names("objects", enabled_only=1))
        )
        cmd.disable("pred_r0001_b000009_s0p800000_selected")
        cmd.enable("pred_r0002_b000004_s0p200000_unselected")
        enabled_names = set(cmd.get_names("objects", enabled_only=1))
        self.assertNotIn("pred_r0001_b000009_s0p800000_selected", enabled_names)
        self.assertIn("pred_r0002_b000004_s0p200000_unselected", enabled_names)
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
        second_gt_coordinates = np.asarray(
            cmd.get_coords("gt_occ_0001_CCD_LIG", state=1)
        )
        np.testing.assert_allclose(
            second_gt_coordinates,
            np.asarray([[17.0, 26.0, 38.0], [18.0, 26.0, 38.0]]),
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

    def test_oversized_density_is_split_without_losing_world_extent(self) -> None:
        """验证超限密度分块的轴顺序、重叠采样层和世界坐标范围."""
        density_dir = self.data_root / "density" / self.pdb_id
        density_zyx = np.fromfunction(
            lambda z, y, x: 100 * z + 10 * y + x,
            (5, 2, 3),
            dtype=np.float32,
        ).astype(np.float32)
        np.save(
            density_dir / "exp.npy",
            density_zyx[np.newaxis],
        )
        previous_limit = _MODULE._PYMOL_DENSITY_TILE_MAX_BYTES
        _MODULE._PYMOL_DENSITY_TILE_MAX_BYTES = 50
        try:
            _MODULE.pymol.finish_launching(["pymol", "-cq"])
            cmd.reinitialize()
            _MODULE.load_density(self.data_root, self.pdb_id)
        finally:
            _MODULE._PYMOL_DENSITY_TILE_MAX_BYTES = previous_limit

        density_objects = {
            object_name
            for object_name in cmd.get_names("objects")
            if object_name.startswith("density_exp_")
        }
        self.assertIn("density", cmd.get_names_of_type("object:group"))
        self.assertEqual(
            density_objects,
            {
                "density_exp_map_0000",
                "density_exp_mesh_0000",
                "density_exp_map_0001",
                "density_exp_mesh_0001",
                "density_exp_map_0002",
                "density_exp_mesh_0002",
                "density_exp_map_0003",
                "density_exp_mesh_0003",
            },
        )
        first_extent = np.asarray(cmd.get_extent("density_exp_map_0000"))
        last_extent = np.asarray(cmd.get_extent("density_exp_map_0003"))
        np.testing.assert_allclose(
            first_extent,
            np.asarray([[11.0, 21.5, 32.0], [15.0, 24.5, 36.0]]),
        )
        np.testing.assert_allclose(
            last_extent,
            np.asarray([[11.0, 21.5, 44.0], [15.0, 24.5, 48.0]]),
        )
        for tile_index, start_z in enumerate(range(4)):
            np.testing.assert_allclose(
                np.asarray(cmd.get_volume_field(f"density_exp_map_{tile_index:04d}")),
                np.transpose(density_zyx[start_z : start_z + 2], (2, 1, 0)),
            )

    def test_combined_session_has_flat_groups_scenes_and_default_view(self) -> None:
        """七模式会话保留单层组、两种受体、scene 与默认无预测画面."""
        cryo_root = self.root / "cryo"
        (cryo_root / "parse" / self.pdb_id).mkdir(parents=True)
        source_receptor = self.data_root / "parse" / self.pdb_id / "receptor_tokens.npz"
        cryo_receptor = cryo_root / "parse" / self.pdb_id / "receptor_tokens.npz"
        cryo_receptor.write_bytes(source_receptor.read_bytes())
        np.savez(
            self.inference_root
            / "unet_c1"
            / "held_out_test_0"
            / self.pdb_id
            / "evaluation"
            / "f1_empty.npz",
            source_blob_index=np.empty(0, dtype=np.int32),
            candidate_score=np.empty(0, dtype=np.float32),
            candidate_selected=np.empty(0, dtype=bool),
        )

        mode_definitions = []
        for index in range(6):
            mode_definitions.append(
                {
                    "id": f"mode_{index}",
                    "group": f"pred_mode_{index}",
                    "scene": f"scene_mode_{index}",
                    "contract": "pocket_plus",
                    "artifact_root": str(self.inference_root),
                    "producer": "unet_c1",
                    "split": "held_out_test_0",
                    "alpha": 1,
                    "evaluation_name": "f1_empty" if index == 0 else "f1_basic",
                    "gaussian_rank": index in {3, 5},
                    "receptor": (
                        "real"
                        if index in {2, 3}
                        else "cryoatom2" if index in {4, 5} else "none"
                    ),
                }
            )

        emap_root = self.root / "emap"
        (emap_root / "mapped" / self.pdb_id).mkdir(parents=True)
        (emap_root / "evaluation" / "per_pdb").mkdir(parents=True)
        np.savez(
            emap_root / "mapped" / self.pdb_id / "official_blobs.npz",
            source_blob_index=np.asarray([4, 9], dtype=np.int32),
            source_probability_mean=np.asarray([0.2, 0.8], dtype=np.float32),
            voxel_offsets=np.asarray([0, 2, 3], dtype=np.int64),
            voxel_index_global_zyx=np.asarray(
                [[0, 0, 0], [1, 2, 3], [0, 1, 2]], dtype=np.int32
            ),
        )
        np.savez(
            emap_root / "evaluation" / "per_pdb" / f"{self.pdb_id}.npz",
            source_blob_index=np.asarray([9, 4], dtype=np.int32),
            candidate_score=np.asarray([0.7, 0.3], dtype=np.float32),
            candidate_selected=np.asarray([True, False]),
        )
        mode_definitions.append(
            {
                "id": "emap",
                "group": "pred_emap",
                "scene": "scene_emap",
                "contract": "emap2lig",
                "result_root": str(emap_root),
                "gaussian_rank": False,
                "receptor": "none",
            }
        )
        profile = {
            "data_root": str(self.data_root),
            "receptor_roots": {
                "real": str(self.data_root),
                "cryoatom2": str(cryo_root),
            },
            "modes": mode_definitions,
        }
        density_dir = self.data_root / "density" / self.pdb_id
        np.save(
            density_dir / "exp.npy",
            np.arange(48, dtype=np.float32).reshape(1, 4, 3, 4),
        )
        output = self.root / "combined.pse"
        density_globals = _COMPARISON.load_density.__globals__
        previous_limit = density_globals["_PYMOL_DENSITY_TILE_MAX_BYTES"]
        density_globals["_PYMOL_DENSITY_TILE_MAX_BYTES"] = 150
        try:
            record = _COMPARISON.build_comparison_session(
                profile,
                self.pdb_id,
                output,
                rank_by="probability_mean",
                emap_limit=100,
            )
        finally:
            density_globals["_PYMOL_DENSITY_TILE_MAX_BYTES"] = previous_limit
        self.assertEqual(len(record["modes"]), 7)

        cmd.reinitialize()
        cmd.load(str(output))
        prediction_groups = {f"pred_mode_{index}" for index in range(6)} | {"pred_emap"}
        self.assertEqual(
            set(cmd.get_names_of_type("object:group")),
            {"density", "receptors", "ground_truth", *prediction_groups},
        )
        self.assertEqual(
            set(cmd.get_object_list("(receptors)")),
            {"receptor_real", "receptor_cryoatom2"},
        )
        self.assertEqual(
            set(cmd.get_scene_list()),
            {f"scene_mode_{index}" for index in range(6)} | {"scene_emap"},
        )
        enabled_names = set(cmd.get_names("objects", enabled_only=1))
        enabled_all = set(cmd.get_names("all", enabled_only=1))
        self.assertTrue(
            {"density_exp_mesh_0000", "density_exp_mesh_0001"}.issubset(enabled_names)
        )
        self.assertTrue(
            {"density_exp_map_0000", "density_exp_map_0001"}.isdisjoint(enabled_names)
        )
        self.assertIn("receptor_real", enabled_names)
        self.assertNotIn("receptor_cryoatom2", enabled_names)
        self.assertTrue(prediction_groups.isdisjoint(enabled_all))

        cmd.scene("scene_mode_4", "recall", animate=0)
        scene_enabled = set(cmd.get_names("objects", enabled_only=1))
        scene_enabled_all = set(cmd.get_names("all", enabled_only=1))
        self.assertIn("receptor_cryoatom2", scene_enabled)
        self.assertNotIn("receptor_real", scene_enabled)
        self.assertTrue(
            {"density_exp_mesh_0000", "density_exp_mesh_0001"}.issubset(scene_enabled)
        )
        self.assertTrue(
            {"density_exp_map_0000", "density_exp_map_0001"}.isdisjoint(scene_enabled)
        )
        self.assertIn("pred_mode_4", scene_enabled_all)
        self.assertNotIn("pred_mode_3", scene_enabled_all)


if __name__ == "__main__":
    unittest.main()
