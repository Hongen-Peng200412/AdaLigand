"""归一化预测读取与排序契约测试."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


_STAGE1_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_STAGE1_DIR))

from prediction_sources import load_predictions  # noqa: E402


class PredictionSourcesTest(unittest.TestCase):
    """验证两类源产物归一化、稳定排序与 Emap2lig 截断."""

    def setUp(self) -> None:
        """创建具有排序分歧和 102 个官方候选的最小产物树."""
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.pdb_id = "1abc"

        pocket_pdb_root = (
            self.root / "pocket" / "Find_1" / "held_out_test_0" / self.pdb_id
        )
        (pocket_pdb_root / "blobs").mkdir(parents=True)
        (pocket_pdb_root / "evaluation").mkdir()
        np.savez(
            pocket_pdb_root / "blobs" / "F2_blobs.npz",
            blob_index=np.asarray([1, 2, 3], dtype=np.int32),
            source_probability_mean=np.asarray([0.2, 0.9, 0.9], dtype=np.float32),
            voxel_offsets=np.asarray([0, 1, 2, 3], dtype=np.int64),
            voxel_index_global_zyx=np.asarray(
                [[0, 0, 0], [0, 0, 1], [0, 0, 2]], dtype=np.int32
            ),
        )
        np.savez(
            pocket_pdb_root / "evaluation" / "f2_gaussian.npz",
            source_blob_index=np.asarray([1, 2, 3], dtype=np.int32),
            candidate_score=np.asarray([0.99, 0.1, 0.8], dtype=np.float32),
            candidate_selected=np.asarray([True, False, True]),
        )
        self.pocket_mode = {
            "id": "find_gaussian",
            "contract": "pocket_plus",
            "artifact_root": str(self.root / "pocket"),
            "producer": "Find_1",
            "split": "held_out_test_0",
            "alpha": 2,
            "evaluation_name": "f2_gaussian",
            "gaussian_rank": True,
        }

        emap_root = self.root / "emap"
        (emap_root / "mapped" / self.pdb_id).mkdir(parents=True)
        (emap_root / "evaluation" / "per_pdb").mkdir(parents=True)
        candidate_count = 102
        source_indices = np.arange(candidate_count, dtype=np.int32)
        np.savez(
            emap_root / "mapped" / self.pdb_id / "official_blobs.npz",
            source_blob_index=source_indices,
            source_probability_mean=np.arange(candidate_count, dtype=np.float32),
            voxel_offsets=np.arange(candidate_count + 1, dtype=np.int64),
            voxel_index_global_zyx=np.column_stack(
                (
                    np.zeros(candidate_count, dtype=np.int32),
                    np.zeros(candidate_count, dtype=np.int32),
                    source_indices,
                )
            ),
        )
        np.savez(
            emap_root / "evaluation" / "per_pdb" / f"{self.pdb_id}.npz",
            source_blob_index=source_indices,
            candidate_score=np.linspace(1.0, 0.0, candidate_count, dtype=np.float32),
            candidate_selected=np.ones(candidate_count, dtype=bool),
        )
        self.emap_mode = {
            "id": "emap",
            "contract": "emap2lig",
            "result_root": str(emap_root),
            "gaussian_rank": False,
        }

    def tearDown(self) -> None:
        """删除临时产物树."""
        self._temporary_directory.cleanup()

    def test_rank_switch_preserves_candidates_and_selection(self) -> None:
        """Gaussian 仅改变允许模式的 rank，不改变候选与正式入选状态."""
        probability = load_predictions(
            self.pocket_mode, self.pdb_id, rank_by="probability_mean"
        )
        gaussian = load_predictions(self.pocket_mode, self.pdb_id, rank_by="gaussian")
        self.assertEqual(
            [candidate.source_blob_index for candidate in probability.candidates],
            [2, 3, 1],
        )
        self.assertEqual(
            [candidate.source_blob_index for candidate in gaussian.candidates],
            [1, 3, 2],
        )
        probability_facts = {
            (candidate.source_blob_index, candidate.candidate_selected)
            for candidate in probability.candidates
        }
        gaussian_facts = {
            (candidate.source_blob_index, candidate.candidate_selected)
            for candidate in gaussian.candidates
        }
        self.assertEqual(probability_facts, gaussian_facts)

        basic_mode = dict(self.pocket_mode, gaussian_rank=False)
        basic_gaussian_request = load_predictions(
            basic_mode, self.pdb_id, rank_by="gaussian"
        )
        self.assertEqual(
            [
                candidate.source_blob_index
                for candidate in basic_gaussian_request.candidates
            ],
            [2, 3, 1],
        )
        self.assertEqual(basic_gaussian_request.effective_rank_by, "probability_mean")

    def test_emap2lig_top_100_and_all_are_stable(self) -> None:
        """Emap2lig 默认稳定截取前 100，显式 all 保留全部候选."""
        top_100 = load_predictions(
            self.emap_mode,
            self.pdb_id,
            rank_by="probability_mean",
            emap_limit=100,
        )
        all_candidates = load_predictions(
            self.emap_mode,
            self.pdb_id,
            rank_by="probability_mean",
            emap_limit=None,
        )
        self.assertEqual(top_100.source_candidate_count, 102)
        self.assertEqual(top_100.loaded_candidate_count, 100)
        self.assertEqual(all_candidates.loaded_candidate_count, 102)
        self.assertEqual(top_100.candidates[0].source_blob_index, 101)
        self.assertEqual(top_100.candidates[-1].source_blob_index, 2)

    def test_empty_pocket_evaluation_is_a_valid_collection(self) -> None:
        """空 evaluation 仍生成字段完整的零候选集合，不伪造对象."""
        pocket_pdb_root = (
            self.root / "pocket" / "Find_1" / "held_out_test_0" / self.pdb_id
        )
        np.savez(
            pocket_pdb_root / "blobs" / "F1_blobs.npz",
            blob_index=np.empty(0, dtype=np.int32),
            source_probability_mean=np.empty(0, dtype=np.float32),
            voxel_offsets=np.asarray([0], dtype=np.int64),
            voxel_index_global_zyx=np.empty((0, 3), dtype=np.int32),
        )
        np.savez(
            pocket_pdb_root / "evaluation" / "f1_empty.npz",
            source_blob_index=np.empty(0, dtype=np.int32),
            candidate_score=np.empty(0, dtype=np.float32),
            candidate_selected=np.empty(0, dtype=bool),
        )
        empty_mode = dict(
            self.pocket_mode,
            alpha=1,
            evaluation_name="f1_empty",
            gaussian_rank=False,
        )
        collection = load_predictions(empty_mode, self.pdb_id)
        self.assertEqual(collection.source_candidate_count, 0)
        self.assertEqual(collection.loaded_candidate_count, 0)
        self.assertEqual(collection.candidates, ())


if __name__ == "__main__":
    unittest.main()
