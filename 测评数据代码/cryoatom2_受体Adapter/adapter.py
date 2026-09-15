"""把外部受体结构转换为 Pocket Plus Stage1 可直接读取的受体资产.

主要入口是 :func:`prepare_receptor_dataset`. 它读取一个有序 PDB 清单, 为每个
PDB 使用外部最终 mmCIF 重建 ``receptor_tokens.npz`` 并在既有实验密度网格上
生成 ``sim.npy``. 配体真值与实验密度不重新计算, 而是在目标 ``Ori_Data`` 中以
只读符号链接复用参考数据根的同名文件.

正式产物由 ``output_root`` 决定:
    - ``parse/<pdb_id>/receptor_tokens.npz``: NPZ, 保存十个受体原子数组.
    - ``density/<pdb_id>/sim.npy``: float32 NPY, ``(1, Z, Y, X)`` 模拟密度.
    - ``density/<pdb_id>/sim.npz``: NPZ, 保存 schema、网格几何和模拟参数.
    - ``受体适配记录.jsonl``: JSONL, 每行保存一个 PDB 的来源路径、规模和产物路径.

本模块不计算文件哈希. 输入与输出身份的哈希核对属于测试或一次性门控, 不属于
长期生产逻辑.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import gemmi
from joblib import Parallel, delayed
import numpy as np

from adaligand_preprocessing.external_tools.chimera import ChimeraRunner
from adaligand_preprocessing.external_tools.model_cif import write_normalized_model_cif
from adaligand_preprocessing.geometry.mrc import MapGrid, load_map, write_canonical_mrc
from adaligand_preprocessing.stages.stage_c.pipeline import (
    category_rows,
    optional_category_rows,
    selected_atom_rows,
    split_candidate_atoms,
)
from adaligand_preprocessing.stages.stage_c.receptor import build_receptor_arrays
from adaligand_preprocessing.stages.stage_e.common import MRC_GENERATED_ORIGIN_MODE
from adaligand_preprocessing.utils.io import atomic_replace, atomic_save_npz, write_jsonl


def _link_reference_asset(source: Path, target: Path) -> None:
    """建立一个不由适配器改写的参考资产符号链接.

    输入参数:
        - source: Path, AdaLigand 主 ``Ori_Data`` 中已经验收的普通文件或目录.
        - target: Path, 目标 ``Ori_Data`` 中保持相同相对语义的位置.

    副作用:
        - target: 符号链接; 已正确指向 source 时保持不变, 其他既有路径不会被覆盖.
    """
    source = source.resolve(strict=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() and target.resolve(strict=True) == source:
        return
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"目标路径已存在且不是预期符号链接: {target}")
    target.symlink_to(source, target_is_directory=source.is_dir())


def _prepare_one_receptor(
    pdb_id: str,
    source_cif: Path,
    pair_record: dict[str, Any],
    reference_root: Path,
    output_root: Path,
    scratch_root: Path,
    chimera_command: tuple[str, ...],
    chimera_version: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """生成一个 PDB 的 CryoAtom2 受体 token 与同网格模拟密度.

    输入参数:
        - pdb_id: str, 小写 PDB 标识, 如 ``6bgi``.
        - source_cif: Path, CryoAtom2 ``latest.json`` 指向的最终 mmCIF; 不使用 ``_raw.cif``.
        - pair_record: dict, 主 ``pair_list.jsonl`` 中当前 PDB 的记录; ``resolution`` 是模拟密度分辨率, 单位 Å.
        - reference_root: Path, 已验收 AdaLigand 主 ``Ori_Data`` 根.
        - output_root: Path, 当前 CryoAtom2 数据集的长期 ``Ori_Data`` 根.
        - scratch_root: Path, 当前正式运行的 Chimera 临时目录; 不属于科学产物.
        - chimera_command: tuple[str,...], UCSF Chimera 可执行命令及固定前置参数.
        - chimera_version: str, 本次实际探测到的 UCSF Chimera 版本文本.
        - timeout_seconds: float, 单个 Chimera 子进程的超时秒数.

    返回值:
        - record: dict, 写入 ``受体适配记录.jsonl`` 的一条记录.
            - pdb_id: str, 当前小写 PDB 标识, 如 ``6bgi``.
            - status: str, ``success`` 表示本次生成, ``skipped`` 表示复用完整三件套.
            - source_cif: str, CryoAtom2 最终 mmCIF 的绝对路径.
            - receptor_atom_count: int, ``receptor_tokens.npz`` 的受体重原子数.
            - sim_shape_zyx: list[int], 模拟密度的 Z、Y、X 三轴长度.
            - receptor_tokens: str, 相对 output_root 的受体 token 路径.
            - simulated_density: str, 相对 output_root 的 ``sim.npy`` 路径.
            - simulated_metadata: str, 相对 output_root 的 ``sim.npz`` 路径.

    落盘产物:
        - ``receptor_tokens.npz``: 原子轴长度为 N, 化学键轴长度为 E.
            - coords: float32 ``(N, 3)``, 受体重原子的世界 XYZ 坐标, 单位 Å.
            - element: uint8 ``(N,)``, 与 coords 逐原子对齐的原子序数.
            - res_type: uint8 ``(N,)``, 与 coords 逐原子对齐的 Stage C 29 类残基编号.
            - is_backbone: bool ``(N,)``, 与 coords 逐原子对齐的蛋白质或核酸主链标记.
            - atom_name: ``S4 (N,)``, 与 coords 逐原子对齐的 mmCIF 原子名.
            - res_index: int32 ``(N,)``, 同值表示同一链中的同一残基.
            - chain_index: int32 ``(N,)``, 同值表示同一条受体链.
            - bond_index: int32 ``(2, E)``, 第 0、1 轴保存每条无向键的两个 coords 原子索引.
            - bond_type: uint8 ``(E,)``, 与 bond_index 第二维对齐; 0–6 依次是 single、double、aromatic、backbone、disulfide、covale、triple.
            - feat: float32 ``(N, 49)``, 与 coords 逐原子对齐; 依次是元素 one-hot 6、残基 one-hot 25、理化性质 8、归一化质量 1 和局部原子数 9 维.
        - ``sim.npy``: float32 ``(1, Z, Y, X)``, 后三轴与同 PDB ``exp.npy`` 逐体素对齐.
        - ``sim.npz``: 模拟密度的网格和生成参数.
            - voxel_size: float32 ``(3,)``, 世界 XYZ 三轴体素尺寸, 单位 Å.
            - origin: float32 ``(3,)``, voxel-grid corner 的世界 XYZ 原点, 单位 Å.
            - schema_version: uint16 标量, Pocket Plus 密度元数据契约版本 2.
            - resolution: float32 标量, Chimera molmap 的当前 PDB 分辨率, 单位 Å.
            - resolution_info_json: 字符串标量, pair_list 分辨率来源对象的 JSON 文本.
            - chimera_version: 字符串标量, 本次实际探测的 UCSF Chimera 版本.
            - strict_hetatm_removed: bool 标量, True 表示模拟密度不包含 HETATM.
            - model_selection: 字符串标量, 首模型、规范异构位置、重原子和 ATOM-only 选择契约.
            - generated_mrc_origin_mode: 字符串标量, 临时 MRC 的原点字段约定.
            - normalized_model_n_atoms: int32 标量, 实际传给 Chimera 的受体重原子数.

    符号链接副作用:
        - 当前 PDB 的 CryoAtom2 最终 CIF 链接到 ``raw/rcsb_mmcif``.
        - 当前 PDB 的配体真值、实验密度和距离监督链接到参考 ``Ori_Data``; 本函数不改写链接目标.

    科学边界:
        - 含 ``_entity`` 的结构沿用 Stage C polymer 分类; 不含该类别的 CryoAtom2 结构把 ``group_PDB=ATOM`` 重原子作为受体.
        - 坐标保持 mmCIF 世界 XYZ 坐标和 Å 单位; 不执行拟合、平移、裁剪或补原子.
        - 模拟密度在参考 ``exp.npy`` 的完整网格上执行 Chimera ``molmap onGrid``.
    """
    # 两个目录 Path 依次承载当前 PDB 的 token 和密度资产.
    parse_directory = output_root / "parse" / pdb_id
    density_directory = output_root / "density" / pdb_id
    # 三个文件 Path 依次是新生成的受体 token、模拟密度网格和模拟密度元数据.
    receptor_path = parse_directory / "receptor_tokens.npz"
    sim_grid_path = density_directory / "sim.npy"
    sim_metadata_path = density_directory / "sim.npz"

    _link_reference_asset(source_cif, output_root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif")
    for name in ("occurrences.jsonl", "ligand_coords.npz"):
        _link_reference_asset(reference_root / "parse" / pdb_id / name, parse_directory / name)
    for name in (
        "exp.npy",
        "exp.npz",
        "ligand_area.npz",
        "union_mask.npy",
        "ligand_dist.npy",
        "ligand_dist.npz",
    ):
        _link_reference_asset(reference_root / "density" / pdb_id / name, density_directory / name)
    # tuple[bool,bool,bool], 依次表示 token、模拟密度网格和模拟密度元数据是否已存在.
    artifact_presence = tuple(path.is_file() for path in (receptor_path, sim_grid_path, sim_metadata_path))
    if all(artifact_presence):
        with np.load(receptor_path, allow_pickle=False) as receptor_archive:
            receptor_atom_count = int(receptor_archive["coords"].shape[0])
        sim_shape_zyx = list(np.load(sim_grid_path, mmap_mode="r", allow_pickle=False).shape[1:])
        return {
            "pdb_id": pdb_id,
            "status": "skipped",
            "source_cif": str(source_cif),
            "receptor_atom_count": receptor_atom_count,
            "sim_shape_zyx": sim_shape_zyx,
            "receptor_tokens": str(receptor_path.relative_to(output_root)),
            "simulated_density": str(sim_grid_path.relative_to(output_root)),
            "simulated_metadata": str(sim_metadata_path.relative_to(output_root)),
        }
    if any(artifact_presence):
        raise FileExistsError(f"受体三件套只存在部分文件, 禁止混合续写: {pdb_id}")

    # gemmi.cif.Block, CryoAtom2 最终受体的唯一 mmCIF 数据块.
    block = gemmi.cif.read(str(source_cif)).sole_block()
    # list[dict], 已选择首个模型、规范异构位置且去除 H/D 的 mmCIF 原子; 坐标字段为世界 XYZ Å.
    atom_rows = selected_atom_rows(category_rows(block, "_atom_site."))
    # dict[str,str], mmCIF entity 编号到 entity 类型的映射; CryoAtom2 最终 CIF 没有该类别时为空.
    entity_types = {
        str(row["id"]): str(row["type"]).lower()
        for row in optional_category_rows(block, "_entity.")
        if "id" in row and "type" in row
    }
    # list[dict], 两个分支均生成长度 N 的受体重原子记录, 每项含身份、世界 XYZ 坐标和残基归属.
    if entity_types:
        # 已有 _entity 时复用 Stage C 的 polymer 身份, 保持与真实受体完全同口径.
        _, receptor_atoms = split_candidate_atoms(atom_rows, entity_types)
    else:
        # CryoAtom2 不写 _entity; group_PDB=ATOM 是其受体原子身份, HETATM 不进入受体.
        receptor_atoms = [atom for atom in atom_rows if str(atom["group_PDB"]).upper() == "ATOM"]
    if not receptor_atoms:
        raise ValueError(f"最终受体 mmCIF 没有可用 ATOM 重原子: {source_cif}")
    # dict[str,np.ndarray], 十字段受体数组; 全部原子轴字段与 coords 第一维逐原子对齐.
    receptor_arrays = build_receptor_arrays(
        receptor_atoms,
        optional_category_rows(block, "_struct_conn."),
        reference_root / "raw" / "ccd_cache",
        allow_ccd_fetch=False,
    )
    atomic_save_npz(receptor_path, **receptor_arrays)

    exp_grid_path = reference_root / "density" / pdb_id / "exp.npy"
    exp_metadata_path = reference_root / "density" / pdb_id / "exp.npz"
    # float32 mmap, (1, Z, Y, X), 当前 PDB 的实验密度; 第一维是单通道轴.
    exp_grid = np.load(exp_grid_path, mmap_mode="r", allow_pickle=False)
    with np.load(exp_metadata_path, allow_pickle=False) as exp_archive:
        # float32, (3,), 实验网格沿世界 XYZ 轴的体素尺寸, 单位 Å.
        voxel_size_xyz = np.asarray(exp_archive["voxel_size"], dtype=np.float32)
        # float32, (3,), 实验网格 voxel-grid corner 的世界 XYZ 原点, 单位 Å.
        origin_xyz = np.asarray(exp_archive["origin"], dtype=np.float32)
    if exp_grid.ndim != 4 or exp_grid.shape[0] != 1:
        raise ValueError(f"实验密度必须为单通道 (1,Z,Y,X): {exp_grid_path}")

    # Path, 仅属于当前 PDB 的 Chimera 临时目录; 成功后只删除内部三个中间文件.
    pdb_scratch = scratch_root / pdb_id
    pdb_scratch.mkdir(parents=True, exist_ok=False)
    normalized_cif = pdb_scratch / "receptor_atom_only.cif"
    # dict, n_atoms 是传入 Chimera 的 ATOM-only 受体重原子数, 其余字段记录 ATOM/HETATM 计数和首模型编号.
    model_statistics = write_normalized_model_cif(source_cif, normalized_cif, atom_only=True)
    canonical_mrc = pdb_scratch / "canonical_exp.mrc"
    write_canonical_mrc(
        canonical_mrc,
        MapGrid(grid=np.asarray(exp_grid[0]), voxel_size=voxel_size_xyz, origin=origin_xyz),
    )
    simulated_mrc = pdb_scratch / "sim.mrc"
    runner = ChimeraRunner(list(chimera_command), timeout_seconds=timeout_seconds)
    runner.molmap_on_grid(
        normalized_cif,
        canonical_mrc,
        simulated_mrc,
        resolution=float(pair_record["resolution"]),
        scratch_dir=pdb_scratch,
    )
    # MapGrid, grid 为 float32 ``(Z, Y, X)``, voxel_size 与 origin 为世界 XYZ ``(3,)`` 数组.
    simulated = load_map(simulated_mrc, multiply_global_origin=False)
    # float32, (1, Z, Y, X), CryoAtom2 受体模拟密度; 空间轴和物理几何与 exp 逐体素对齐.
    sim_grid = simulated.grid[None].astype(np.float32, copy=False)
    # bool, Chimera 输出的 XYZ 体素尺寸和原点与实验网格在 MRC float32 精度内一致.
    geometry_matches = np.allclose(simulated.voxel_size, voxel_size_xyz, rtol=0.0, atol=1e-5) and np.allclose(
        simulated.origin, origin_xyz, rtol=0.0, atol=1e-5
    )
    if sim_grid.shape != exp_grid.shape or not geometry_matches:
        raise ValueError(f"模拟密度与实验密度网格不一致: {pdb_id}")

    density_directory.mkdir(parents=True, exist_ok=True)
    temporary_grid_path = sim_grid_path.with_name(f".{sim_grid_path.name}.tmp.{os.getpid()}.npy")
    np.save(temporary_grid_path, sim_grid, allow_pickle=False)
    atomic_replace(temporary_grid_path, sim_grid_path)
    atomic_save_npz(
        sim_metadata_path,
        voxel_size=voxel_size_xyz,
        origin=origin_xyz,
        schema_version=np.asarray(2, dtype=np.uint16),
        resolution=np.asarray(float(pair_record["resolution"]), dtype=np.float32),
        resolution_info_json=np.asarray(json.dumps(pair_record.get("resolution_info", {}), ensure_ascii=False, sort_keys=True)),
        chimera_version=np.asarray(chimera_version),
        strict_hetatm_removed=np.asarray(True, dtype=bool),
        model_selection=np.asarray("first_model_stage_c_altloc_heavy_group_PDB_ATOM"),
        generated_mrc_origin_mode=np.asarray(MRC_GENERATED_ORIGIN_MODE),
        normalized_model_n_atoms=np.asarray(model_statistics["n_atoms"], dtype=np.int32),
    )
    canonical_mrc.unlink()
    simulated_mrc.unlink()
    normalized_cif.unlink()
    return {
        "pdb_id": pdb_id,
        "status": "success",
        "source_cif": str(source_cif),
        "receptor_atom_count": int(receptor_arrays["coords"].shape[0]),
        "sim_shape_zyx": list(sim_grid.shape[1:]),
        "receptor_tokens": str(receptor_path.relative_to(output_root)),
        "simulated_density": str(sim_grid_path.relative_to(output_root)),
        "simulated_metadata": str(sim_metadata_path.relative_to(output_root)),
    }


# ================================================================================================


def prepare_receptor_dataset(
    split_file: Path,
    cryoatom2_root: Path,
    reference_root: Path,
    output_root: Path,
    scratch_root: Path,
    chimera_command: tuple[str, ...],
    workers: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """按冻结 PDB 顺序生成一个 CryoAtom2 数据集的受体适配资产.

    输入参数:
        - split_file: Path, 顶层为 PDB 字符串列表或含 ``pdb_ids`` 的 JSON object.
        - cryoatom2_root: Path, 含 ``运行日志与统计/pdb/<pdb_id>/latest.json`` 和最终 CIF 的 CryoAtom2 实验根.
        - reference_root: Path, 提供实验密度、配体真值、CCD 缓存及分辨率的 AdaLigand 主 ``Ori_Data``.
        - output_root: Path, 当前 CryoAtom2 划分长期使用的目标 ``Ori_Data``.
        - scratch_root: Path, 当前运行专属的 Chimera 工作目录.
        - chimera_command: tuple[str,...], UCSF Chimera 可执行命令及固定前置参数.
        - workers: int, 同时处理的 PDB 数; 每个 worker 启动一个 Chimera 子进程.
        - timeout_seconds: float, 每个 Chimera 子进程的超时秒数.

    返回值:
        - records: list[dict], 按 split_file 顺序排列的逐 PDB 适配记录.
            - pdb_id: str, 小写 PDB 标识.
            - status: str, ``success`` 表示本次生成, ``skipped`` 表示复用完整三件套.
            - source_cif: str, CryoAtom2 最终 mmCIF 绝对路径.
            - receptor_atom_count: int, 受体重原子数 N.
            - sim_shape_zyx: list[int], 模拟密度的 ``[Z, Y, X]`` 空间尺寸.
            - receptor_tokens: str, 相对 output_root 的 token 路径.
            - simulated_density: str, 相对 output_root 的 ``sim.npy`` 路径.
            - simulated_metadata: str, 相对 output_root 的 ``sim.npz`` 路径.

    顶层落盘范围:
        - 每个 PDB 新生成 ``receptor_tokens.npz``、``sim.npy`` 和 ``sim.npz``; 有序记录写入 ``受体适配记录.jsonl``.
        - 顶层 ``pair_list.jsonl``、``ccd_cache``、``ligand_objects``、``ligand_descriptors`` 及逐 PDB 的配体真值和实验密度均以符号链接复用参考根, 不改写参考文件.
        - 受体原子轴标签不能复用, 因此目标根不创建 ``labels/<pdb_id>``.

    共享链接:
        - ``raw/pair_list.jsonl``、``raw/ccd_cache``、``ligand_objects``、``ligand_descriptors``: 指向 reference_root 的只读符号链接.
        - 每个 PDB 的实验密度、配体真值和原有 parse 辅助文件: 保持主 ``Ori_Data`` 的相对路径并只读复用.
    """
    # list 或 dict, 顶层是 PDB 列表, 或以 pdb_ids 字段保存该列表.
    payload = json.loads(split_file.read_text(encoding="utf-8"))
    # list[str], 当前划分的有序小写 PDB 轴; 不排序、不抽样且不改变 test_0/test_1 父子关系.
    pdb_ids = [str(value).lower() for value in (payload if isinstance(payload, list) else payload["pdb_ids"])]
    if len(pdb_ids) != len(set(pdb_ids)):
        raise ValueError(f"PDB 清单含重复成员: {split_file}")

    _link_reference_asset(reference_root / "raw" / "pair_list.jsonl", output_root / "raw" / "pair_list.jsonl")
    _link_reference_asset(reference_root / "raw" / "ccd_cache", output_root / "raw" / "ccd_cache")
    _link_reference_asset(reference_root / "ligand_objects", output_root / "ligand_objects")
    _link_reference_asset(reference_root / "ligand_descriptors", output_root / "ligand_descriptors")

    # dict[str,dict], 以小写 PDB 标识索引主 pair_list 的实验图和分辨率记录.
    pair_records: dict[str, dict[str, Any]] = {}
    with (reference_root / "raw" / "pair_list.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            pdb_id = str(record["pdb_id"]).lower()
            if pdb_id in pdb_ids:
                if pdb_id in pair_records:
                    raise ValueError(f"pair_list 对同一 PDB 存在多条记录: {pdb_id}")
                pair_records[pdb_id] = record
    if set(pair_records) != set(pdb_ids):
        raise ValueError(f"pair_list 缺少清单成员: {sorted(set(pdb_ids) - set(pair_records))}")

    # dict[str,Path], 以 PDB 标识索引 CryoAtom2 已验收的最终 CIF; latest.json 必须为 success.
    source_cifs: dict[str, Path] = {}
    for pdb_id in pdb_ids:
        latest_path = cryoatom2_root / "运行日志与统计" / "pdb" / pdb_id / "latest.json"
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if latest["status"] != "success" or str(latest["pdb_id"]).lower() != pdb_id:
            raise ValueError(f"CryoAtom2 latest.json 不是当前 PDB 的成功终态: {latest_path}")
        source_cif = Path(str(latest["final_cif"]))
        if source_cif.name.endswith("_raw.cif") or not source_cif.is_file():
            raise ValueError(f"CryoAtom2 最终 CIF 路径无效: {source_cif}")
        source_cifs[pdb_id] = source_cif

    scratch_root.mkdir(parents=True, exist_ok=False)
    # ChimeraRunner, 只执行一次版本探测; 所有 PDB 的 sim.npz 记录同一文本.
    probe_runner = ChimeraRunner(list(chimera_command), timeout_seconds=timeout_seconds)
    chimera_version = probe_runner.probe(scratch_root / "_probe")
    # list[dict], 长度等于 pdb_ids; joblib 返回顺序与提交顺序相同.
    records = Parallel(n_jobs=workers, backend="loky", verbose=10)(
        delayed(_prepare_one_receptor)(
            pdb_id,
            source_cifs[pdb_id],
            pair_records[pdb_id],
            reference_root,
            output_root,
            scratch_root,
            chimera_command,
            chimera_version,
            timeout_seconds,
        )
        for pdb_id in pdb_ids
    )
    write_jsonl(output_root / "受体适配记录.jsonl", records)
    return records
