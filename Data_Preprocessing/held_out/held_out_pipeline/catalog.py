"""构建 polymer entity 序列目录并审计 held-out 基础事实.

主要入口是 :func:`run_catalog_shard` 与 :func:`finalize_catalog`. 前者按 PDB 分片解析冻结 mmCIF, 并只对 held-out PDB 检查质量, 配体计数和 Stage1 资产; 后者合并完整目录, 生成自然 FASTA, MMseqs2 query/target FASTA 和 RCSB 官方 FASTA smoke.

本模块只建立序列身份和比对输入, 不运行 MMseqs2, 不判断 PDB 冗余, 也不选择测试集.

全部正式路径都相对于调用方传入的 `output_root`. JSONL 的一行对应一个 PDB 或一个 polymer entity; JSON 保存 smoke 和计数汇总; FASTA header 固定使用 `<PDB_ID>_<entity_id>`. 具体字段由 :func:`parse_mmcif_entities` 与 :func:`finalize_catalog` 的返回和落盘契约定义.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Iterable

import numpy as np


# int, protein chain 进入比对和 PDB coverage 分母的最短沉积序列长度, 单位 aa.
PROTEIN_MIN_LENGTH = 30
# int, RNA/DNA/hybrid chain 进入比对和 PDB coverage 分母的最短沉积序列长度, 单位 nt.
NUCLEIC_MIN_LENGTH = 20
# tuple[int, int, int], Stage1 完整图的最小 ZYX 形状; 三个轴都使用包含边界.
MIN_GRID_SHAPE_ZYX = (80, 80, 80)
# tuple[str, ...], occurrence 级配体计数的六个冻结 type_tag, 输出顺序固定.
LIGAND_TYPES = (
    "ion",
    "nucleotide_like",
    "other",
    "peptide_like",
    "small_molecule",
    "sugar",
)
# str, RCSB 官方 per-entry FASTA 下载端点模板.
RCSB_FASTA_URL = "https://www.rcsb.org/fasta/entry/{pdb_id}/download"
# str, 官方 smoke HTTP 请求的可识别客户端名称.
RCSB_USER_AGENT = "AdaLigand-held-out/0.1"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 UTF-8 JSONL 中的非空对象记录.

    输入参数:
        - path: Path, 每个非空物理行必须是一个 JSON object.

    返回值:
        - records: list[dict[str, Any]], 保持文件顺序, 不去重.
    """

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number} 必须是 JSON object.")
            records.append(value)
    return records


def _write_text(path: Path, text: str) -> None:
    """以同目录临时文件原子替换 UTF-8 文本."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary_path, path)


def _write_json(path: Path, value: Any) -> None:
    """按稳定键序写出一个可读 JSON 文件."""

    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """按传入顺序逐行写出对象序列, 再原子替换目标文件."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary_path, path)


def normalize_sequence(value: Any) -> str:
    """把 mmCIF 或 FASTA 序列只做去空白和大写规范化.

    输入参数:
        - value: Any, `_entity_poly.pdbx_seq_one_letter_code_can` 或 FASTA sequence 文本.

    返回值:
        - sequence: str, 删除全部 Unicode 空白并转为大写; 不删除或替换其他字符.
    """

    return "".join(str(value).split()).upper()


def classify_polymer_type(polymer_type: str) -> str:
    """把 mmCIF polymer type 映射为本轮五类序列身份.

    `polypeptide*` 统一为 `protein`; 三种核酸使用精确 mmCIF type; 其他 polymer 返回 `other`.
    """

    normalized_type = polymer_type.strip().lower()
    if normalized_type.startswith("polypeptide"):
        return "protein"
    if normalized_type == "polyribonucleotide":
        return "rna"
    if normalized_type == "polydeoxyribonucleotide":
        return "dna"
    if normalized_type == "polydeoxyribonucleotide/polyribonucleotide hybrid":
        return "hybrid"
    return "other"


def sequence_is_comparable(sequence_class: str, length: int) -> bool:
    """按 protein 30 aa 和核酸 20 nt 的包含边界判断是否进入比对.

    返回 False 的 entity 仍保存在自然目录, 但不进入 MMseqs2 FASTA 和 PDB coverage 分母.
    """

    if sequence_class == "protein":
        return length >= PROTEIN_MIN_LENGTH
    if sequence_class in {"rna", "dna", "hybrid"}:
        return length >= NUCLEIC_MIN_LENGTH
    return False


def parse_mmcif_entities(mmcif_path: Path, pdb_id: str) -> list[dict[str, Any]]:
    """从冻结 mmCIF 读取 polymer entity, 规范序列和 label asym chain.

    输入参数:
        - mmcif_path: Path, RCSB 完整 PDBx/mmCIF 文件.
        - pdb_id: str, 已规范化的小写 PDB identity.

    返回值:
        - entities: list[dict[str, Any]], 每个 `_entity_poly.entity_id` 一条, 按 entity_id 字典序排列.
            - entities[*].sequence_id: str, 大写 `<PDB_ID>_<entity_id>` 格式的 FASTA 序列标识, 如 `1ABC_1`.
            - entities[*].pdb_id: str, 小写 PDB 条目标识, 如 `1abc`.
            - entities[*].entity_id: str, 当前 PDB 内的 polymer entity 标识, 如 `1`.
            - entities[*].polymer_type: str, 原始 `_entity_poly.type`, 如 `polypeptide(L)`.
            - entities[*].sequence_class: str, 归一化后的序列类别, 如 `protein`; 可取 `protein`, `rna`, `dna`, `hybrid` 或 `other`.
            - entities[*].sequence: str, 仅删除空白并转为大写的沉积规范全长序列, 如原始 `"a c d"` 得到 `"ACD"`.
            - entities[*].length: int, sequence 字符数, 如 `sequence="ACD"` 时为 `3`.
            - entities[*].label_asym_ids: list[str], 指向当前 entity 的全部 label asym chain 标识, 如 `["A", "B"]` 表示该分子有 A 和 B 两个结构副本.
            - entities[*].comparable: bool, 是否达到类别长度边界并进入比对与 PDB coverage 分母, 如长度为 3 的 protein 为 `False`.

    例子:
        - 假设 `pdb_id="1abc"`, `_entity_poly` 含有蛋白质 `(entity_id=1, type=polypeptide(L), sequence="a c d")` 和 RNA `(entity_id=2, type=polyribonucleotide, sequence="A U G")`; `_struct_asym` 含有 `A -> 1`, `B -> 1`, `C -> 2` 和 `H -> 9`.
        - 返回的第一项为 `{"sequence_id": "1ABC_1", "pdb_id": "1abc", "entity_id": "1", "polymer_type": "polypeptide(L)", "sequence_class": "protein", "sequence": "ACD", "length": 3, "label_asym_ids": ["A", "B"], "comparable": False}`.
        - 返回的第二项为 `{"sequence_id": "1ABC_2", "pdb_id": "1abc", "entity_id": "2", "polymer_type": "polyribonucleotide", "sequence_class": "rna", "sequence": "AUG", "length": 3, "label_asym_ids": ["C"], "comparable": False}`.
        - entity 1 只定义一条完整序列; A 和 B 是该分子在沉积结构中的两个 chain 副本, 因此共用一条 `sequence_id="1ABC_1"`. H 指向的 entity 9 没有 `_entity_poly` 记录, 所以不返回. 两条示例序列都保留在目录中, 但长度没有达到 protein 30 aa 或核酸 20 nt 的比对边界, 所以 `comparable=False`.

    科学边界:
        - 序列只来自 `_entity_poly.pdbx_seq_one_letter_code_can`.
        - chain 只来自 `_struct_asym.entity_id -> _struct_asym.id`; 后者是 label_asym_id.
        - 不读取 `_atom_site` 或坐标残基补序列.
    """

    import gemmi

    # gemmi.cif.Document, 冻结 RCSB mmCIF 的语法树; 不访问网络或坐标派生序列.
    document = gemmi.cif.read_file(str(mmcif_path))
    # gemmi.cif.Block, 单个 PDB entry 的唯一 data block.
    block = document.sole_block()
    # dict[str, list[str]], entity_id 到 label_asym_id 列表; 每个列表元素是一条 chain instance.
    asym_ids_by_entity: dict[str, list[str]] = defaultdict(list)
    # gemmi.cif.Table (N_asym, 2), 列依次为 label_asym_id 和 entity_id.
    asym_table = block.find(["_struct_asym.id", "_struct_asym.entity_id"])
    for row in asym_table:
        # str, Gemmi row.str 解码 CIF 引号后的 label_asym_id; 未来残基-原子映射的 chain 身份.
        label_asym_id = row.str(0).strip()
        # str, `_entity_poly.entity_id` 的外键.
        entity_id = row.str(1).strip()
        if label_asym_id and entity_id:
            asym_ids_by_entity[entity_id].append(label_asym_id)

    # list[dict], 一个 PDB 的 polymer entity 记录; 序列在 entity 层只保存一次.
    entities: list[dict[str, Any]] = []
    # gemmi.cif.Table (N_entity, 3), entity identity, polymer type 和沉积规范全长序列.
    entity_table = block.find(
        [
            "_entity_poly.entity_id",
            "_entity_poly.type",
            "_entity_poly.pdbx_seq_one_letter_code_can",
        ]
    )
    for row in entity_table:
        # str, 当前 PDB 内的 polymer entity identity.
        entity_id = row.str(0).strip()
        # str, mmCIF 原始 `_entity_poly.type`; 用于区分 protein/RNA/DNA/hybrid.
        polymer_type = row.str(1).strip()
        # str (L,), 仅去空白并大写的 `_pdbx_seq_one_letter_code_can`; L 是沉积全长.
        sequence = normalize_sequence(row.str(2))
        # str, 本轮五类序列身份; other 只入目录, 不参与比对.
        sequence_class = classify_polymer_type(polymer_type)
        # list[str] (C,), 该 entity 的全部 label_asym chain, 去重后稳定排序.
        label_asym_ids = sorted(set(asym_ids_by_entity.get(entity_id, [])))
        entities.append(
            {
                "sequence_id": f"{pdb_id.upper()}_{entity_id}",
                "pdb_id": pdb_id,
                "entity_id": entity_id,
                "polymer_type": polymer_type,
                "sequence_class": sequence_class,
                "sequence": sequence,
                "length": len(sequence),
                "label_asym_ids": label_asym_ids,
                "comparable": sequence_is_comparable(sequence_class, len(sequence)),
            }
        )
    return sorted(entities, key=lambda record: str(record["entity_id"]))


def inspect_training_assets(data_root: Path, pdb_id: str) -> dict[str, Any]:
    """核对 held-out PDB 是否满足当前 Stage1 完整资产和最小图形状契约.

    输入参数:
        - data_root: Path, A-G 正式根目录.
        - pdb_id: str, 小写 PDB identity.

    返回字段:
        - status: str, `eligible`, `short_map`, `missing_file` 或 `invalid`.
        - passed: bool, 只有 status 为 `eligible` 时为 True.
        - shape_zyx: list[int] | None, 完整图 ZYX 三维长度.
        - detail: str, 失败路径或首个契约错误.

    数组契约:
        - 四个完整图数组 exp/sim/ligand_dist/union_mask 形状均为 `(1, Z, Y, X)`; dtype 依次为 float32, float32, float16, bool.
        - exp/sim/ligand_dist/ligand_area 元数据的体素尺寸与世界原点必须一致.
        - `receptor_tokens.npz::coords` 的原子数必须等于 `atom_labels.npz::binding_atom` 长度.
    """

    # Path, 当前 PDB 的完整实验图, 模拟图和体素监督目录.
    density_directory = data_root / "density" / pdb_id
    # tuple[Path, ...], 与当前 Stage1 Dataset 对齐的最小完整资产集合.
    required_paths = (
        density_directory / "exp.npz",
        density_directory / "exp.npy",
        density_directory / "sim.npz",
        density_directory / "sim.npy",
        density_directory / "ligand_dist.npz",
        density_directory / "ligand_dist.npy",
        density_directory / "ligand_area.npz",
        density_directory / "union_mask.npy",
        data_root / "parse" / pdb_id / "receptor_tokens.npz",
        data_root / "labels" / pdb_id / "atom_labels.npz",
    )
    # list[str], 不存在的必需文件; 缺文件与字段损坏分成两个稳定状态.
    missing_paths = [str(path) for path in required_paths if not path.is_file()]
    if missing_paths:
        return {
            "status": "missing_file",
            "passed": False,
            "shape_zyx": None,
            "detail": "; ".join(missing_paths),
        }

    try:
        with np.load(density_directory / "exp.npz", allow_pickle=False) as exp_metadata:
            # tuple[int, int, int], 实验完整图 ZYX 轴长度.
            shape_zyx = tuple(
                int(value) for value in np.asarray(exp_metadata["canonical_shape_zyx"]).tolist()
            )
            # ndarray float32 (3,), 世界坐标 XYZ 的体素尺寸, 单位 Å.
            voxel_size_xyz = np.asarray(exp_metadata["voxel_size"], dtype=np.float32)
            # ndarray float32 (3,), 世界坐标 XYZ 的网格原点, 单位 Å.
            origin_xyz = np.asarray(exp_metadata["origin"], dtype=np.float32)
        if len(shape_zyx) != 3 or any(length <= 0 for length in shape_zyx):
            raise ValueError(f"canonical_shape_zyx 非法: {shape_zyx}")

        # tuple[int, int, int, int], 单通道完整图的 `(1, Z, Y, X)` 盘上形状.
        expected_array_shape = (1, *shape_zyx)
        # tuple[(Path, dtype), ...], 四个 mmap 数组的正式 dtype 契约.
        array_contracts = (
            (density_directory / "exp.npy", np.dtype(np.float32)),
            (density_directory / "sim.npy", np.dtype(np.float32)),
            (density_directory / "ligand_dist.npy", np.dtype(np.float16)),
            (density_directory / "union_mask.npy", np.dtype(np.bool_)),
        )
        for array_path, expected_dtype in array_contracts:
            # memmap (1, Z, Y, X), 只读取 NPY header 和被访问的页, 不把完整体载入内存.
            array = np.load(array_path, mmap_mode="r", allow_pickle=False)
            if array.shape != expected_array_shape or array.dtype != expected_dtype:
                raise ValueError(
                    f"{array_path} 应为 {expected_dtype} {expected_array_shape}, "
                    f"实际 {array.dtype} {array.shape}"
                )

        with np.load(density_directory / "sim.npz", allow_pickle=False) as sim_metadata:
            if not np.array_equal(np.asarray(sim_metadata["voxel_size"]), voxel_size_xyz):
                raise ValueError("sim.npz::voxel_size 与 exp.npz 不一致")
            if not np.array_equal(np.asarray(sim_metadata["origin"]), origin_xyz):
                raise ValueError("sim.npz::origin 与 exp.npz 不一致")

        for metadata_name in ("ligand_dist.npz", "ligand_area.npz"):
            with np.load(density_directory / metadata_name, allow_pickle=False) as metadata:
                # tuple[int, int, int], 当前监督元数据声明的 ZYX 网格形状.
                target_shape = tuple(
                    int(value) for value in np.asarray(metadata["grid_shape_zyx"]).tolist()
                )
                if target_shape != shape_zyx:
                    raise ValueError(f"{metadata_name}::grid_shape_zyx 与 exp.npz 不一致")
                if not np.array_equal(np.asarray(metadata["voxel_size_xyz"]), voxel_size_xyz):
                    raise ValueError(f"{metadata_name}::voxel_size_xyz 与 exp.npz 不一致")
                if not np.array_equal(np.asarray(metadata["origin_xyz"]), origin_xyz):
                    raise ValueError(f"{metadata_name}::origin_xyz 与 exp.npz 不一致")

        # Path, 完整受体重原子表; `coords` 形状为 `(N_atom, 3)` 世界 XYZ.
        receptor_path = data_root / "parse" / pdb_id / "receptor_tokens.npz"
        # Path, 与受体原子逐项对齐的 Stage1 标签表.
        label_path = data_root / "labels" / pdb_id / "atom_labels.npz"
        with np.load(receptor_path, allow_pickle=False) as receptor:
            # int, 完整受体重原子数 N_atom.
            receptor_atom_count = int(np.asarray(receptor["coords"]).shape[0])
        with np.load(label_path, allow_pickle=False) as labels:
            if np.asarray(labels["binding_atom"]).shape != (receptor_atom_count,):
                raise ValueError("binding_atom 与 receptor coords 的原子数不一致")
    except (KeyError, OSError, TypeError, ValueError) as error:
        return {
            "status": "invalid",
            "passed": False,
            "shape_zyx": None,
            "detail": str(error),
        }

    # bool, Z/Y/X 三个轴是否都达到 80; 质量字段不参与资产布尔值.
    passed = all(
        actual_length >= minimum_length
        for actual_length, minimum_length in zip(shape_zyx, MIN_GRID_SHAPE_ZYX)
    )
    return {
        "status": "eligible" if passed else "short_map",
        "passed": passed,
        "shape_zyx": list(shape_zyx),
        "detail": "",
    }


def summarize_entities(entities: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """按 entity, chain instance 和沉积序列长度汇总一个 PDB 的 polymer 事实.

    输入参数:
        - entities: Iterable[dict[str, Any]], 同一 PDB 的 polymer entity 记录.

    返回值:
        - entity_count: int, 全部 polymer entity 数.
        - chain_count: int, 全部 label asym chain instance 数.
        - residue_count: int, 按 chain instance 重复计算的沉积序列长度总和.
        - comparable_entity_count: int, 达到类别长度边界的 entity 数.
        - comparable_chain_count: int, 达到类别长度边界的 chain instance 数.
        - comparable_residue_count: int, comparable chain 的沉积序列长度总和.
        - by_class: dict[str, dict[str, int]], 固定含 protein, rna, dna, hybrid, other 五类统计.
            - by_class[*].entity_count: int, 当前序列类别的 entity 数.
            - by_class[*].chain_count: int, 当前序列类别的 chain instance 数.
            - by_class[*].residue_count: int, 当前序列类别按 chain instance 计算的沉积序列长度总和.
            - by_class[*].comparable_entity_count: int, 当前序列类别达到长度边界的 entity 数.
            - by_class[*].comparable_chain_count: int, 当前序列类别达到长度边界的 chain instance 数.
            - by_class[*].comparable_residue_count: int, 当前序列类别 comparable chain 的沉积序列长度总和.

    residue 计数按 chain instance 计算, 即一个多 chain entity 的序列长度乘以 chain 数. 短链和 other 进入 total 统计, 但不进入 comparable 统计.
    """

    # dict[str, dict[str, int]], 五类序列的 entity/chain/residue 计数及可比子集计数.
    by_class: dict[str, dict[str, int]] = {}
    for sequence_class in ("protein", "rna", "dna", "hybrid", "other"):
        by_class[sequence_class] = {
            "entity_count": 0,
            "chain_count": 0,
            "residue_count": 0,
            "comparable_entity_count": 0,
            "comparable_chain_count": 0,
            "comparable_residue_count": 0,
        }
    for entity in entities:
        # str, protein/RNA/DNA/hybrid/other 中的一类.
        sequence_class = str(entity["sequence_class"])
        # int, 当前 entity 映射的 label_asym chain instance 数 C.
        chain_count = len(entity["label_asym_ids"])
        # int, 当前 entity 对 PDB residue 分母的总贡献 L*C; 短链仅进入 total.
        residue_count = int(entity["length"]) * chain_count
        # dict[str, int], 当前 sequence class 的可变累加器.
        class_summary = by_class[sequence_class]
        class_summary["entity_count"] += 1
        class_summary["chain_count"] += chain_count
        class_summary["residue_count"] += residue_count
        if bool(entity["comparable"]):
            class_summary["comparable_entity_count"] += 1
            class_summary["comparable_chain_count"] += chain_count
            class_summary["comparable_residue_count"] += residue_count
    return {
        "entity_count": sum(value["entity_count"] for value in by_class.values()),
        "chain_count": sum(value["chain_count"] for value in by_class.values()),
        "residue_count": sum(value["residue_count"] for value in by_class.values()),
        "comparable_entity_count": sum(
            value["comparable_entity_count"] for value in by_class.values()
        ),
        "comparable_chain_count": sum(
            value["comparable_chain_count"] for value in by_class.values()
        ),
        "comparable_residue_count": sum(
            value["comparable_residue_count"] for value in by_class.values()
        ),
        "by_class": by_class,
    }


def _process_pdb(argument: tuple[str, str, dict[str, Any] | None]) -> dict[str, Any]:
    """解析一个 PDB, 并在它属于 held-out 时附加资产审计.

    输入参数:
        - argument[0]: str, A-G 正式数据根路径.
        - argument[1]: str, 小写 PDB identity.
        - argument[2]: dict | None, held-out 的 EMDB, 日期, 质量和配体事实; 非 held-out PDB 为 None.

    返回字段:
        - pdb_id: str, 小写 PDB identity.
        - sequence_status: str, 取 ok, missing_mmcif 或 parse_error.
        - sequence_error: str | None, 成功时为 None; 失败时为缺失 mmCIF 路径或异常类型与文本.
        - entities: list[dict], 使用 :func:`parse_mmcif_entities` 的 entity 字段契约; 失败时为空列表.
        - held_out: dict, 只在 argument[2] 非空时存在; 保留输入事实并增加 assets.
            - held_out.emdb_ids: list[str], 当前 PDB 对应的全部 EMDB identities.
            - held_out.first_map_release: str | None, 首次 EMDB 发布时间.
            - held_out.quality: dict, map_resolution, cc_contour 和质量布尔值.
            - held_out.ligands: dict, occurrence 总数, 六类计数和严格 `(1, 100)` 过滤布尔值.
            - held_out.assets: dict, 使用 :func:`inspect_training_assets` 的资产审计字段契约.

    该顶层函数是 ProcessPoolExecutor worker. mmCIF 缺失或任意解析异常被转换为逐 PDB 序列状态; held-out 和暴露参考失败分别进入结果计数.
    """

    # str, Path 序列化值; 保证 ProcessPool worker 参数可直接 pickle.
    data_root_text, pdb_id, held_out_fact = argument
    # Path, A-G 正式数据根.
    data_root = Path(data_root_text)
    # Path, 当前 PDB 的冻结 RCSB mmCIF; 文件名使用小写 PDB identity.
    mmcif_path = data_root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"
    if not mmcif_path.is_file():
        # str, 未预期序列处理状态; held-out 和暴露参考分别计数.
        sequence_status = "missing_mmcif"
        # str, 人工定位所需的缺失来源路径.
        sequence_error = str(mmcif_path)
        # list[dict], 缺少 mmCIF 时没有可写入序列目录的 entity.
        entities: list[dict[str, Any]] = []
    else:
        try:
            entities = parse_mmcif_entities(mmcif_path, pdb_id)
            # str, mmCIF 语法, entity 序列和 chain 外键均已完成读取.
            sequence_status = "ok"
            # None, 成功记录没有错误文本.
            sequence_error = None
        except Exception as error:
            # list[dict], 解析失败不保留部分 entity, 避免残缺目录进入比对.
            entities = []
            # str, 任意逐 PDB 解析异常统一计为未预期失败, 供运行后人工验收.
            sequence_status = "parse_error"
            # str, 异常类型与文本; 不包含 traceback 以控制身份证体积.
            sequence_error = f"{type(error).__name__}: {error}"
    # dict, 当前 PDB 的完整序列状态和 entity 列表; held-out 时再附加基础事实.
    record: dict[str, Any] = {
        "pdb_id": pdb_id,
        "sequence_status": sequence_status,
        "sequence_error": sequence_error,
        "entities": entities,
    }
    if held_out_fact is not None:
        record["held_out"] = {
            **held_out_fact,
            "assets": inspect_training_assets(data_root, pdb_id),
        }
    return record


def parse_fasta_entities(text: str) -> dict[str, str]:
    """读取 RCSB per-entry FASTA, 并按 header 首字段返回 entity 序列.

    header 的第一个 `|` 前必须是 `<PDB_ID>_<entity_id>`; 返回键转为大写, 序列只去空白并大写.
    """

    # dict[str, str], 大写 `<PDB_ID>_<entity_id>` 到官方全长序列的映射.
    sequences: dict[str, str] = {}
    # str | None, 当前 FASTA 记录的 entity identity.
    current_id: str | None = None
    # list[str], 当前 entity 跨物理行的序列片段.
    fragments: list[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            if current_id is not None:
                sequences[current_id] = normalize_sequence("".join(fragments))
            current_id = line[1:].split("|", maxsplit=1)[0].strip().upper()
            fragments = []
        elif line.strip():
            if current_id is None:
                raise ValueError("FASTA sequence 出现在首个 header 之前.")
            fragments.append(line)
    if current_id is not None:
        sequences[current_id] = normalize_sequence("".join(fragments))
    return sequences


def compare_official_fasta(
    pdb_id: str,
    local_entities: Iterable[dict[str, Any]],
    official_fasta_text: str,
) -> dict[str, Any]:
    """逐 entity 比较本地 mmCIF 规范序列与 RCSB 官方 FASTA.

    输入参数:
        - pdb_id: str, 当前 RCSB PDB identity.
        - local_entities: Iterable[dict], 使用 :func:`parse_mmcif_entities` 契约的本地 entity.
        - official_fasta_text: str, RCSB per-entry FASTA 全文.

    返回字段:
        - pdb_id: str, 输入 PDB identity.
        - source_url: str, 当前 PDB 的 RCSB 官方 FASTA 下载地址.
        - passed: bool, 两侧 entity identity 集合和每条规范序列是否完全相同.
        - entities: list[dict], 按 sequence_id 排序的逐 entity 对照.
            - sequence_id: str, 大写 `<PDB_ID>_<entity_id>`.
            - local_sequence: str | None, 本地 mmCIF 规范序列; 本地缺失时为 None.
            - official_sequence: str | None, RCSB FASTA 序列; 官方缺失时为 None.
            - equal: bool, 两侧序列是否存在且逐字符相同.
    """

    # dict[str, str], 本地 mmCIF entity identity 到规范全长序列.
    local_sequences = {
        str(entity["sequence_id"]).upper(): str(entity["sequence"])
        for entity in local_entities
    }
    # dict[str, str], RCSB 官方下载文件中的 entity identity 到全长序列.
    official_sequences = parse_fasta_entities(official_fasta_text)
    # list[str], 两侧 identity 并集; 缺少任一侧都显式进入失败明细.
    all_sequence_ids = sorted(set(local_sequences).union(official_sequences))
    # list[dict], 每个 entity 的两侧序列与逐项相等布尔值.
    entity_results = [
        {
            "sequence_id": sequence_id,
            "local_sequence": local_sequences.get(sequence_id),
            "official_sequence": official_sequences.get(sequence_id),
            "equal": local_sequences.get(sequence_id) == official_sequences.get(sequence_id),
        }
        for sequence_id in all_sequence_ids
    ]
    return {
        "pdb_id": pdb_id,
        "source_url": RCSB_FASTA_URL.format(pdb_id=pdb_id.upper()),
        "passed": bool(entity_results) and all(result["equal"] for result in entity_results),
        "entities": entity_results,
    }


def _write_fasta(path: Path, entities: Iterable[dict[str, Any]], normalize_u_to_t: bool) -> None:
    """写出 entity FASTA; 核酸比对视图可显式把 U 替换为 T.

    每条 header 只包含无空白的 `sequence_id`, 序列每 80 个字符换行. `normalize_u_to_t=False` 的自然 FASTA 不修改 U.
    """

    # list[str], FASTA header 与 80 字符序列行; entity 顺序继承调用方稳定排序.
    lines: list[str] = []
    for entity in entities:
        # str (L,), 自然或派生比对序列; 只有派生核酸视图允许 U->T.
        sequence = str(entity["sequence"])
        if normalize_u_to_t:
            sequence = sequence.replace("U", "T")
        lines.append(f">{entity['sequence_id']}")
        lines.extend(sequence[index : index + 80] for index in range(0, len(sequence), 80))
    _write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def _select_official_smoke_pdbs(
    entities_by_pdb: dict[str, list[dict[str, Any]]],
    smoke_count: int,
) -> list[str]:
    """依次选择 protein 和核酸代表, 再按 PDB identity 补足.

    返回值最多含 `smoke_count` 个互异 PDB; 固定排序使同一冻结目录得到相同的真实 smoke 身份.
    """

    # list[str], 按序列类别依次选择且互异的 PDB identity.
    selected: list[str] = []
    # tuple[Callable, ...], protein 和核酸两个序列 smoke 角色.
    predicates = (
        lambda entity: entity["sequence_class"] == "protein",
        lambda entity: entity["sequence_class"] in {"rna", "dna", "hybrid"},
    )
    for predicate in predicates:
        for pdb_id in sorted(entities_by_pdb):
            if pdb_id not in selected and any(predicate(entity) for entity in entities_by_pdb[pdb_id]):
                selected.append(pdb_id)
                break
        if len(selected) >= smoke_count:
            return selected
    for pdb_id in sorted(entities_by_pdb):
        if pdb_id not in selected and entities_by_pdb[pdb_id]:
            selected.append(pdb_id)
        if len(selected) >= smoke_count:
            break
    return selected


# ================================================================================================


def run_catalog_shard(
    data_root: Path,
    pair_list_path: Path,
    held_out_split_path: Path,
    pdb_audit_path: Path,
    output_root: Path,
    shard_index: int,
    shard_count: int,
    workers: int,
) -> dict[str, Any]:
    """解析完整 PDB 目录的一个固定分片, 并对其中 held-out PDB 建立基础事实.

    输入参数:
        - data_root: Path, A-G 正式数据根.
        - pair_list_path: Path, 完整 PDB/EMDB JSONL.
        - held_out_split_path: Path, 2,497 个 PDB 的 occurrence 级 JSON.
        - pdb_audit_path: Path, 保存首次 EMDB 发布时间的 PDB 审计 JSONL.
        - output_root: Path, held-out 正式输出根.
        - shard_index: int, 当前目录数组下标.
        - shard_count: int, 目录数组分片总数.
        - workers: int, 当前数组元素内部的进程数.

    返回字段:
        - shard_index: int, 当前目录分片编号.
        - shard_count: int, 目录分片总数.
        - assigned_pdb_count: int, 当前分片负责的 PDB 数.
        - held_out_pdb_count: int, 当前分片中的 held-out PDB 数.
        - sequence_status_counts: dict[str, int], 当前分片各序列状态的 PDB 数.
        - workers: int, ProcessPoolExecutor 进程数.
        - output: str, 当前 catalog JSONL 路径.

    落盘产物:
        - `stage1/shards/catalog_<index>.jsonl`: JSONL; 每行使用 :func:`_process_pdb` 返回字段.
        - `stage1/shards/summary_<index>.json`: dict; 字段与函数返回值相同.

    分片规则是排序后的完整 PDB identity 列表取 `pdb_ids[shard_index::shard_count]`. 一个数组元素内部使用 ProcessPoolExecutor, 输出只写 `stage1/shards/catalog_<index>.jsonl` 和对应 summary.
    """

    # list[dict], 完整 PDB/EMDB 对照; 同一 PDB 可对应多个 EMDB.
    pair_records = _read_jsonl(pair_list_path)
    # list[str] (N_pdb,), 22,386 个去重, 排序的小写 PDB identity.
    all_pdb_ids = sorted({str(record["pdb_id"]).strip().lower() for record in pair_records})
    # dict[str, set[str]], 每个 PDB 对应的全部 EMDB identity.
    emdb_ids_by_pdb: dict[str, set[str]] = defaultdict(set)
    for record in pair_records:
        pdb_id = str(record["pdb_id"]).strip().lower()
        emdb_ids_by_pdb[pdb_id].add(str(record["emdb_id"]).strip().upper().replace("_", "-"))

    # list[dict] (N_occ,), held-out 的 81,922 条 occurrence 级质量与类型记录.
    held_out_rows = json.loads(held_out_split_path.read_text(encoding="utf-8"))
    # dict[str, list[dict]], held-out PDB 到全部 occurrence 的映射.
    occurrences_by_pdb: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in held_out_rows:
        occurrences_by_pdb[str(row["pdb_id"]).strip().lower()].append(row)
    # dict[str, dict], PDB 到首次 EMDB 发布时间和冻结状态的映射.
    audit_by_pdb = {
        str(record["pdb_id"]).strip().lower(): record for record in _read_jsonl(pdb_audit_path)
    }

    # dict[str, dict], 只供 held-out PDB 使用的日期, 质量和六类配体计数.
    held_out_facts: dict[str, dict[str, Any]] = {}
    for pdb_id, rows in occurrences_by_pdb.items():
        # dict, 同一密度图任一 occurrence 的图级质量字段; 图级字段在 PDB 内共享.
        first_row = rows[0]
        # Counter[str], 六类 type_tag 的 occurrence 数, ion 也计入总数.
        ligand_counts = Counter(str(row["type_tag"]) for row in rows)
        held_out_facts[pdb_id] = {
            "emdb_ids": sorted(emdb_ids_by_pdb[pdb_id]),
            "first_map_release": audit_by_pdb[pdb_id].get("first_map_release"),
            "quality": {
                "map_resolution": first_row.get("map_resolution"),
                "cc_contour": first_row.get("cc_contour"),
                "passed": (
                    first_row.get("map_resolution") is not None
                    and first_row.get("cc_contour") is not None
                    and float(first_row["map_resolution"]) < 4.0
                    and float(first_row["cc_contour"]) > 0.65
                ),
            },
            "ligands": {
                "total_count": len(rows),
                "type_counts": {name: int(ligand_counts.get(name, 0)) for name in LIGAND_TYPES},
                "strict_1_100_passed": 1 < len(rows) < 100,
            },
        }

    # list[str], 当前数组元素按稳定步长取得的 PDB identity.
    assigned_pdb_ids = all_pdb_ids[shard_index::shard_count]
    # list[tuple], ProcessPool 输入; 只有 held-out PDB 的第三项非空.
    worker_arguments = [
        (str(data_root), pdb_id, held_out_facts.get(pdb_id)) for pdb_id in assigned_pdb_ids
    ]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        # list[dict], 与 assigned_pdb_ids 同序的逐 PDB 目录分片结果.
        records = list(executor.map(_process_pdb, worker_arguments, chunksize=8))

    # Path, 当前数组所有目录分片和分片摘要的共享输出目录.
    shard_directory = output_root / "stage1" / "shards"
    # Path, 当前分片逐 PDB 序列与 held-out 基础事实的 JSONL.
    shard_path = shard_directory / f"catalog_{shard_index:03d}.jsonl"
    # Path, 当前分片输入规模与序列状态计数的 JSON.
    summary_path = shard_directory / f"summary_{shard_index:03d}.json"
    _write_jsonl(shard_path, records)
    # Counter[str], 当前分片的 ok/missing_mmcif/parse_error 数量.
    status_counts = Counter(str(record["sequence_status"]) for record in records)
    # dict, 当前分片身份, 输入数量, 状态计数, worker 数和结果路径.
    summary = {
        "shard_index": shard_index,
        "shard_count": shard_count,
        "assigned_pdb_count": len(assigned_pdb_ids),
        "held_out_pdb_count": sum("held_out" in record for record in records),
        "sequence_status_counts": dict(sorted(status_counts.items())),
        "workers": workers,
        "output": str(shard_path),
    }
    _write_json(summary_path, summary)
    return summary


def finalize_catalog(
    output_root: Path,
    pair_list_path: Path,
    train_pdb_path: Path,
    validation_pdb_path: Path,
    calibration_pdb_path: Path,
    held_out_pdb_path: Path,
    shard_count: int,
    alignment_shard_count: int,
    official_smoke_count: int,
    official_timeout_seconds: float,
) -> dict[str, Any]:
    """合并序列目录, 生成比对 FASTA, 并执行 RCSB 官方 FASTA smoke.

    输入参数:
        - output_root: Path, 全部正式产物的根目录.
        - pair_list_path: Path, 完整 PDB/EMDB JSONL, 用于独立核对分片身份.
        - train_pdb_path: Path, train 暴露参考 PDB JSON 列表.
        - validation_pdb_path: Path, validation 暴露参考 PDB JSON 列表.
        - calibration_pdb_path: Path, calibration 暴露参考 PDB JSON 列表.
        - held_out_pdb_path: Path, 冻结 held-out PDB JSON 列表.
        - shard_count: int, 要合并的目录分片数.
        - alignment_shard_count: int, 要派生的 MMseqs2 query FASTA 分片数.
        - official_smoke_count: int, 要下载并对照的真实 PDB 数.
        - official_timeout_seconds: float, 单次 RCSB FASTA HTTP 请求超时, 单位 s.

    返回值:
        - catalog_pdb_count: int, 完整序列目录中的 PDB 数.
        - catalog_entity_count: int, 完整序列目录中的 polymer entity 数.
        - reference_pdb_count: int, train/validation/calibration 暴露参考 PDB 并集大小.
        - reference_sequence_failure_count: int, 暴露参考中 missing_mmcif 或 parse_error 的 PDB 数.
        - held_out_pdb_count: int, 冻结 held-out PDB 数.
        - held_out_sequence_failure_count: int, held-out 中 missing_mmcif 或 parse_error 的 PDB 数.
        - sequence_status_counts: dict[str, int], 完整 PDB 目录中各序列状态的 PDB 数.
        - protein_target_entity_count: int, MMseqs2 protein target FASTA 的 entity 数.
        - nucleic_target_entity_count: int, MMseqs2 nucleic target FASTA 的 entity 数.
        - alignment_shard_count: int, MMseqs2 query FASTA 分片数.
        - official_fasta_smoke_passed: bool, 全部真实 RCSB FASTA 对照是否通过.

    落盘产物:
        - `sequence_catalog.jsonl`: 每行一个 :func:`parse_mmcif_entities` entity.
        - `pdb_sequence_status.jsonl`: JSONL; 每行一个完整目录 PDB 的序列处理状态.
            - pdb_id: str, 小写 PDB identity.
            - status: str, 取 ok, missing_mmcif 或 parse_error.
            - error: str | None, 成功时为 None; 失败时为来源路径或异常文本.
            - entity_count: int, 成功解析的 polymer entity 数; 失败时为 0.
        - `held_out_base.jsonl`: JSONL; 每行一个冻结 held-out PDB 的基础身份证.
            - pdb_id: str, 小写 held-out PDB identity.
            - emdb_ids: list[str], 当前 PDB 对应的全部 EMDB identities.
            - first_map_release: str | None, 首次 EMDB 发布时间.
            - quality: dict, 当前 PDB 的图级质量事实.
                - quality.map_resolution: float | None, 冷冻电镜图分辨率, 单位 Å; 来源缺失时为 None.
                - quality.cc_contour: float | None, 当前图的 contour 相关系数; 来源缺失时为 None.
                - quality.passed: bool, map_resolution `<4.0` 且 cc_contour `>0.65` 时为 True.
            - ligands: dict, 当前 PDB 的 occurrence 级配体统计.
                - ligands.total_count: int, 当前 PDB 的全部 occurrence 数, 包含 ion.
                - ligands.type_counts: dict[str, int], 固定含 ion, nucleotide_like, other, peptide_like, small_molecule, sugar 六类计数.
                - ligands.strict_1_100_passed: bool, `1 < total_count < 100` 时为 True.
            - assets: dict, 使用 :func:`inspect_training_assets` 的资产审计字段契约.
            - sequence: dict, 当前 PDB 的序列处理状态和 polymer 计数.
                - sequence.status: str, 取 ok, missing_mmcif 或 parse_error.
                - sequence.error: str | None, 成功时为 None; 失败时为来源路径或异常文本.
                - sequence.entity_count: int, 全部 polymer entity 数.
                - sequence.chain_count: int, 全部 label asym chain instance 数.
                - sequence.residue_count: int, 全部 chain instance 的沉积序列长度总和.
                - sequence.comparable_entity_count: int, 达到类别长度边界的 entity 数.
                - sequence.comparable_chain_count: int, 达到类别长度边界的 chain instance 数.
                - sequence.comparable_residue_count: int, comparable chain 的沉积序列长度总和.
                - sequence.by_class: dict[str, dict[str, int]], 使用 :func:`summarize_entities` 的五类子统计.
        - `fasta/natural/{protein,rna,dna,hybrid}.fasta`: FASTA; 保存对应类别的全部沉积规范序列, 包含短链.
        - `fasta/mmseqs/{protein,nucleic}_target.fasta`: FASTA; 保存参考与 held-out 的 comparable entity, nucleic 视图使用 U/T 等价.
        - `fasta/mmseqs/{protein,nucleic}_query_<shard>.fasta`: FASTA; 保存当前 held-out 分片的 comparable entity, nucleic 视图使用 U/T 等价.
        - `official_fasta_smoke.json`: dict; 真实 RCSB per-entry FASTA 对照报告.
            - requested_count: int, 请求对照的 PDB 数.
            - pdb_ids: list[str], 实际选择的 PDB identities.
            - passed: bool, 实际数量达到 requested_count 且全部逐 PDB 对照通过时为 True.
            - results: list[dict], 使用 :func:`compare_official_fasta` 返回字段的逐 PDB 报告.
        - `held_out_sequence_failures.jsonl`: JSONL; `held_out_base` 中 status 为 missing_mmcif 或 parse_error 的完整记录子集.
        - `stage1/summary.json`: dict; 字段与函数返回值相同.
        - `stage1/_COMPLETE`: 空文件; 本函数正常执行到末尾时写出, 不作为后续代码门控.

    held-out 和暴露参考的序列失败只进入结果统计, 不参与代码门控. `reference_redundant` 只表示成功进入序列目录的参考范围. 官方 FASTA smoke 是否通过也只进入报告, 由端到端验收人工判断.
    """

    # Path, 第一组产物的分片, summary 和完成标记目录.
    stage1_root = output_root / "stage1"
    # list[dict] (N_pdb,), 合并后的完整逐 PDB 序列记录.
    records: list[dict[str, Any]] = []
    for shard_index in range(shard_count):
        shard_path = stage1_root / "shards" / f"catalog_{shard_index:03d}.jsonl"
        records.extend(_read_jsonl(shard_path))
    records.sort(key=lambda record: str(record["pdb_id"]))
    if len(records) != len({str(record["pdb_id"]) for record in records}):
        raise ValueError("catalog shard 中存在重复 PDB identity.")

    # list[str], pair_list 再次独立得到的完整 PDB identity 基准.
    expected_pdb_ids = sorted(
        {
            str(record["pdb_id"]).strip().lower()
            for record in _read_jsonl(pair_list_path)
        }
    )
    # list[str], 分片合并结果中的 PDB identity, 应逐项等于 expected_pdb_ids.
    actual_pdb_ids = [str(record["pdb_id"]) for record in records]
    if actual_pdb_ids != expected_pdb_ids:
        raise ValueError("catalog shard 合并结果与 pair_list PDB identity 不一致.")

    # list[dict] (N_entity,), 完整目录中每个 polymer entity 一条记录.
    entities = [entity for record in records for entity in record["entities"]]
    entities.sort(key=lambda entity: (str(entity["pdb_id"]), str(entity["entity_id"])))
    # dict[str, list[dict]], 官方 FASTA smoke 与逐 PDB 汇总使用的 entity 索引.
    entities_by_pdb = {
        str(record["pdb_id"]): list(record["entities"]) for record in records
    }
    _write_jsonl(output_root / "sequence_catalog.jsonl", entities)
    _write_jsonl(
        output_root / "pdb_sequence_status.jsonl",
        (
            {
                "pdb_id": record["pdb_id"],
                "status": record["sequence_status"],
                "error": record["sequence_error"],
                "entity_count": len(record["entities"]),
            }
            for record in records
        ),
    )

    # list[str], 冻结日期留出的 2,497 个 PDB identity.
    held_out_ids = json.loads(held_out_pdb_path.read_text(encoding="utf-8"))
    # set[str], held-out 成员查询集合.
    held_out_id_set = {str(pdb_id).strip().lower() for pdb_id in held_out_ids}
    # set[str], train/validation/calibration 合并后的 14,017 个暴露参考 PDB.
    reference_id_set: set[str] = set()
    for path in (train_pdb_path, validation_pdb_path, calibration_pdb_path):
        reference_id_set.update(
            str(pdb_id).strip().lower()
            for pdb_id in json.loads(path.read_text(encoding="utf-8"))
        )
    if held_out_id_set.intersection(reference_id_set):
        raise ValueError("held-out 与暴露参考 PDB identity 不互斥.")
    # dict[str, dict] (N_pdb,), 完整目录的逐 PDB 状态索引; 用于证明暴露参考序列检查无遗漏.
    record_by_pdb = {str(record["pdb_id"]): record for record in records}
    if not reference_id_set.issubset(record_by_pdb):
        # list[str], split 中存在但完整目录中缺失的暴露参考 PDB identities.
        missing_reference_ids = sorted(reference_id_set.difference(record_by_pdb))
        raise ValueError(f"暴露参考 PDB 不在完整目录中: {missing_reference_ids[:10]}")

    # list[dict] (N_held_out,), 日期, 质量, 资产, 配体和序列统计的基础身份证; 正式 N_held_out=2497.
    held_out_base_records: list[dict[str, Any]] = []
    for record in records:
        pdb_id = str(record["pdb_id"])
        if pdb_id not in held_out_id_set:
            continue
        held_out_fact = record.get("held_out")
        if held_out_fact is None:
            raise ValueError(f"{pdb_id} 缺少 held-out 基础事实.")
        held_out_base_records.append(
            {
                "pdb_id": pdb_id,
                **held_out_fact,
                "sequence": {
                    "status": record["sequence_status"],
                    "error": record["sequence_error"],
                    **summarize_entities(record["entities"]),
                },
            }
        )
    held_out_base_records.sort(key=lambda record: str(record["pdb_id"]))
    # set[str], 实际生成基础身份证的 held-out PDB identity, 必须完整覆盖冻结集合.
    actual_held_out_ids = {str(record["pdb_id"]) for record in held_out_base_records}
    if actual_held_out_ids != held_out_id_set:
        raise ValueError("held_out_base 与冻结 held-out PDB identity 不一致.")
    _write_jsonl(output_root / "held_out_base.jsonl", held_out_base_records)

    # Path, 不改写自然序列的四类 entity FASTA 目录.
    natural_directory = output_root / "fasta" / "natural"
    for sequence_class in ("protein", "rna", "dna", "hybrid"):
        # list[dict], 当前自然序列类别的全部 entity, 包含短链.
        class_entities = [
            entity for entity in entities if entity["sequence_class"] == sequence_class
        ]
        _write_fasta(natural_directory / f"{sequence_class}.fasta", class_entities, False)

    # list[dict], 已应用 protein>=30 或 nucleic>=20 的 entity 比对子集.
    comparable_entities = [entity for entity in entities if bool(entity["comparable"])]
    # set[str], MMseqs2 target 只包含暴露参考与 held-out, 不包含其他历史 PDB.
    target_id_set = reference_id_set.union(held_out_id_set)
    # list[dict], protein target entity; 自然序列不做字符替换.
    protein_targets = [
        entity
        for entity in comparable_entities
        if entity["pdb_id"] in target_id_set and entity["sequence_class"] == "protein"
    ]
    # list[dict], RNA/DNA/hybrid target entity; 写 FASTA 时统一 U->T.
    nucleic_targets = [
        entity
        for entity in comparable_entities
        if entity["pdb_id"] in target_id_set
        and entity["sequence_class"] in {"rna", "dna", "hybrid"}
    ]
    # Path, protein/nucleic 的完整 target 和 alignment_shard_count 份 held-out query FASTA 目录.
    mmseqs_directory = output_root / "fasta" / "mmseqs"
    _write_fasta(mmseqs_directory / "protein_target.fasta", protein_targets, False)
    _write_fasta(mmseqs_directory / "nucleic_target.fasta", nucleic_targets, True)
    # list[str], query 分片使用的稳定 held-out PDB 顺序.
    sorted_held_out_ids = sorted(held_out_id_set)
    for shard_index in range(alignment_shard_count):
        # set[str], 当前 MMseqs2 query 分片负责的 held-out PDB.
        query_pdb_ids = set(sorted_held_out_ids[shard_index::alignment_shard_count])
        # list[dict], 当前分片满足长度边界的 protein entity.
        protein_queries = [
            entity
            for entity in comparable_entities
            if entity["pdb_id"] in query_pdb_ids and entity["sequence_class"] == "protein"
        ]
        # list[dict], 当前分片满足长度边界的 RNA/DNA/hybrid entity.
        nucleic_queries = [
            entity
            for entity in comparable_entities
            if entity["pdb_id"] in query_pdb_ids
            and entity["sequence_class"] in {"rna", "dna", "hybrid"}
        ]
        _write_fasta(
            mmseqs_directory / f"protein_query_{shard_index:03d}.fasta",
            protein_queries,
            False,
        )
        _write_fasta(
            mmseqs_directory / f"nucleic_query_{shard_index:03d}.fasta",
            nucleic_queries,
            True,
        )

    # list[str], 固定选择的少量真实 PDB, 优先覆盖 protein 和核酸序列.
    smoke_pdb_ids = _select_official_smoke_pdbs(entities_by_pdb, official_smoke_count)
    # list[dict], 本地 mmCIF 与 RCSB 官方 FASTA 的逐 PDB 对照结果.
    smoke_results: list[dict[str, Any]] = []
    for pdb_id in smoke_pdb_ids:
        # urllib.request.Request, 当前 PDB 的 RCSB per-entry FASTA 官方下载请求.
        request = urllib.request.Request(
            RCSB_FASTA_URL.format(pdb_id=pdb_id.upper()),
            headers={"User-Agent": RCSB_USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=official_timeout_seconds) as response:
            # str, RCSB 返回的 text/x-fasta 全文.
            official_text = response.read().decode("utf-8")
        smoke_results.append(compare_official_fasta(pdb_id, entities_by_pdb[pdb_id], official_text))
    # dict, N_smoke 个真实 PDB 的 entity identity 集合和序列逐项相等报告.
    smoke_report = {
        "requested_count": official_smoke_count,
        "pdb_ids": smoke_pdb_ids,
        "passed": len(smoke_results) == official_smoke_count
        and all(result["passed"] for result in smoke_results),
        "results": smoke_results,
    }
    _write_json(output_root / "official_fasta_smoke.json", smoke_report)

    # list[dict], 只包含 held-out 的 mmCIF 缺失或解析异常; 分母固定为 2,497.
    held_out_failures = [
        record
        for record in held_out_base_records
        if record["sequence"]["status"] in {"missing_mmcif", "parse_error"}
    ]
    _write_jsonl(output_root / "held_out_sequence_failures.jsonl", held_out_failures)
    # list[dict] (N_reference_failure,), 暴露参考中缺少 mmCIF 或解析异常的记录; 用于量化实际参考去冗余范围.
    reference_failures = [
        record_by_pdb[pdb_id]
        for pdb_id in sorted(reference_id_set)
        if record_by_pdb[pdb_id]["sequence_status"] in {"missing_mmcif", "parse_error"}
    ]
    # Counter[str], 完整 22,386 个 PDB 的序列处理状态分布.
    status_counts = Counter(str(record["sequence_status"]) for record in records)
    # dict, 第一组产物的目录规模, 失败计数, 比对输入规模和官方 smoke 结果.
    summary = {
        "catalog_pdb_count": len(records),
        "catalog_entity_count": len(entities),
        "reference_pdb_count": len(reference_id_set),
        "reference_sequence_failure_count": len(reference_failures),
        "held_out_pdb_count": len(held_out_id_set),
        "held_out_sequence_failure_count": len(held_out_failures),
        "sequence_status_counts": dict(sorted(status_counts.items())),
        "protein_target_entity_count": len(protein_targets),
        "nucleic_target_entity_count": len(nucleic_targets),
        "alignment_shard_count": alignment_shard_count,
        "official_fasta_smoke_passed": smoke_report["passed"],
    }
    _write_json(stage1_root / "summary.json", summary)
    _write_text(stage1_root / "_COMPLETE", "")
    return summary
