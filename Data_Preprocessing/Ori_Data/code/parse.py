"""Stage C 核心：把一个 PDB 的 mmCIF 解析成 occurrence / 受体 token / 真实坐标。

parse_one_pdb 的主流程：gemmi 读 mmCIF → 选原子(首 model + altloc) → 分 HET/受体 →
并查集按共价(CCD 内部键 + struct_conn covale + branch_link)连出 occurrence →
物化去重 LigandObject → 按 (residue, atom_name) 对齐抽取沉积态真实坐标 →
落盘 occurrences.jsonl / ligand_coords.npz / receptor_tokens.npz 与单样本报告（resolve_failed 不入主产物）。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gemmi
import numpy as np
from rdkit import Chem

from constants import (
    JUNK_RESNAMES,
    METAL_ELEMENTS,
    NUCLEIC_BACKBONE,
    PROTEIN_BACKBONE,
)
from io_utils import atomic_save_npz, file_lock, safe_object_filename, write_jsonl
from ligand_descriptors import materialize_ligand_descriptor
from ligand_object import (
    Atom,
    get_ccd_mol,
    ligand_object_is_valid,
    materialize_ccd_ligand,
    process_branched_ligand,
)
from receptor import build_receptor_arrays, build_receptor_base_arrays
from reports import write_report

_MATERIALIZED_OBJECT_KEYS: set[tuple[str, str]] = set()


@dataclass
class StageCSourceView:
    """
    当前 mmCIF 在不落盘条件下重建出的 Stage C 核心视图。

    字段:
        - occurrences: list[dict[str,Any]], 当前成功 occurrence 列表
        - ligand_coords: dict[str,np.ndarray], `coords_{cid}`/`present_{cid}` 数组
        - receptor_atoms: list[dict[str,Any]], 已选择的受体重原子行
        - receptor_base: dict[str,np.ndarray], 七个受体基础数组
        - struct_conns: list[dict[str,str]], 当前 `_struct_conn` 行
        - ccd_ids: tuple[str,...], dry-build 与受体化学键依赖的 CCD 缓存键
        - object_keys: tuple[str,...], dry-build 读取的 LigandObject 键
        - report: dict[str,Any], 内存中的计数、warning 与 failed occurrence
    """

    occurrences: list[dict[str, Any]]
    ligand_coords: dict[str, np.ndarray]
    receptor_atoms: list[dict[str, Any]]
    receptor_base: dict[str, np.ndarray]
    struct_conns: list[dict[str, str]]
    ccd_ids: tuple[str, ...]
    object_keys: tuple[str, ...]
    report: dict[str, Any]


class UnionFind:
    """
    并查集。

    输入参数:
        - size: int, 元素总数
    """

    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        """
        查询元素根节点。

        输入参数:
            - item: int, 元素编号

        输出:
            - root: int, 当前集合根节点
        """
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        """
        合并两个元素所在集合。

        输入参数:
            - left: int, 第一个元素编号
            - right: int, 第二个元素编号

        输出:
            - None: 集合关系原地更新
        """
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def category_rows(block: gemmi.cif.Block, prefix: str) -> list[dict[str, str]]:
    """
    将 mmCIF category 转为字典行列表。

    输入参数:
        - block: gemmi.cif.Block, mmCIF 数据块
        - prefix: str, 形如 `_atom_site.` 的 category 前缀

    输出:
        - rows: list[dict[str, str]], 每行以短字段名为 key
    """
    table = block.find_mmcif_category(prefix)
    tags = [tag.replace(prefix, "") for tag in table.tags]
    rows: list[dict[str, str]] = []
    for row in table:
        rows.append({tag: str(value) for tag, value in zip(tags, row, strict=False)})
    return rows


def optional_category_rows(block: gemmi.cif.Block, prefix: str) -> list[dict[str, str]]:
    """
    读取可选 mmCIF category。

    输入参数:
        - block: gemmi.cif.Block, mmCIF 数据块
        - prefix: str, 形如 `_struct_conn.` 的 category 前缀

    输出:
        - rows: list[dict[str, str]], category 不存在时为空列表
    """
    return category_rows(block, prefix)


def clean_value(value: str) -> str:
    """
    规范化 mmCIF 空值。

    输入参数:
        - value: str, 原始字段值

    输出:
        - cleaned: str, `.` 和 `?` 转为空字符串
    """
    if value in {".", "?"}:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def selected_raw_atom_rows(
    atom_rows: list[dict[str, str]],
    *,
    include_hydrogen: bool = False,
) -> list[dict[str, str]]:
    """
    选择首 model 和规范 altloc，同时保留原始 atom_site 全字段。

    输入参数:
        - atom_rows: list[dict[str,str]], `_atom_site` 原始行
        - include_hydrogen: bool, 是否保留 H/D；Stage C 与 E/F 标准模型均传 False

    输出:
        - rows: list[dict[str,str]], 按原始 atom_site.id 排序的选中行

    该函数是 Stage C、E 和 F 唯一的 model/altloc 选择实现。E/F 需要原始 ``atom_site.id``
    和完整身份字段，不能先经过 Stage C 的简化字典再猜回去。
    """
    first_model = None
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in atom_rows:
        model_num = clean_value(row.get("pdbx_PDB_model_num", "1")) or "1"
        if first_model is None:
            first_model = model_num
        if model_num != first_model:
            continue
        element = clean_value(row.get("type_symbol", "")).upper()
        if not include_hydrogen and element in {"H", "D"}:
            continue
        key = (
            clean_value(row.get("label_asym_id", "")),
            clean_value(row.get("label_comp_id", "")),
            clean_value(row.get("label_seq_id", "")),
            clean_value(row.get("auth_seq_id", "")),
            clean_value(row.get("pdbx_PDB_ins_code", "")),
            clean_value(row.get("label_atom_id", "")),
        )
        grouped[key].append(row)

    selected = []
    for rows in grouped.values():
        rows.sort(key=_altloc_sort_key)
        selected.append(rows[0])
    selected.sort(key=lambda row: int(row["id"]))
    return selected


def selected_atom_rows(atom_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """
    从 atom_site 中选择第一个 model 和规范 altloc 的重原子行。

    输入参数:
        - atom_rows: list[dict[str, str]], `_atom_site` 原始行

    输出:
        - atoms: list[dict[str, Any]], 已清洗并选择 altloc 的原子行
    """
    atoms: list[dict[str, Any]] = []
    for row in selected_raw_atom_rows(atom_rows):
        atoms.append(
            {
                "atom_site_id": int(row["id"]),
                "group_PDB": clean_value(row.get("group_PDB", "")),
                "element": clean_value(row.get("type_symbol", "")).upper(),
                "label_atom_id": clean_value(row.get("label_atom_id", "")),
                "label_comp_id": clean_value(row.get("label_comp_id", "")).upper(),
                "label_asym_id": clean_value(row.get("label_asym_id", "")),
                "label_entity_id": clean_value(row.get("label_entity_id", "")),
                "label_seq_id": clean_value(row.get("label_seq_id", "")),
                "auth_atom_id": clean_value(row.get("auth_atom_id", "")),
                "auth_comp_id": clean_value(row.get("auth_comp_id", "")).upper(),
                "auth_asym_id": clean_value(row.get("auth_asym_id", "")),
                "auth_seq_id": clean_value(row.get("auth_seq_id", "")),
                "icode": clean_value(row.get("pdbx_PDB_ins_code", "")),
                "x": float(row["Cartn_x"]),
                "y": float(row["Cartn_y"]),
                "z": float(row["Cartn_z"]),
            }
        )
    return atoms


def _altloc_sort_key(row: dict[str, str]) -> tuple[int, float, int]:
    """
    构造 altloc 选择排序键。

    输入参数:
        - row: dict[str, str], `_atom_site` 行

    输出:
        - key: tuple[int, float, int], 空/A/1 优先, occupancy 高者优先, atom_site.id 小者优先
    """
    alt = clean_value(row.get("label_alt_id", ""))
    if alt == "":
        rank = 0
    elif alt in {"A", "1"}:
        rank = 1
    else:
        rank = 2
    occupancy = float(row.get("occupancy", "0") or 0)
    return (rank, -occupancy, int(row["id"]))


def residue_key(atom: dict[str, Any]) -> tuple[str, str, str, str]:
    """
    构造 residue 实例键。

    输入参数:
        - atom: dict[str, Any], 已选择的 atom_site 行

    输出:
        - key: tuple[str, str, str, str], `(label_asym_id, label_comp_id, seq_or_auth, icode)`
    """
    seq = atom["label_seq_id"] or atom["auth_seq_id"]
    return (atom["label_asym_id"], atom["label_comp_id"], str(seq), atom["icode"])


def build_stage_c_source_view(
    root: Path,
    pdb_id: str,
    materialize_objects: bool,
) -> StageCSourceView:
    """
    从当前 mmCIF 重建不含派生 receptor bond/feat 的 Stage C 核心视图。

    输入参数:
        - root: Path, Stage root，包含 raw、ligand_objects 与旧 parse 产物
        - pdb_id: str, PDB id，大小写不敏感
        - materialize_objects: bool, 正式解析时补齐 LigandObject；只读 source audit 时必须为 False

    输出:
        - view: StageCSourceView, occurrence、配体坐标、受体基础数组与内存报告
    """
    normalized_id = pdb_id.lower()
    cif_path = root / "raw" / "rcsb_mmcif" / f"{normalized_id}.cif"
    block = gemmi.cif.read(str(cif_path)).sole_block()
    atom_rows = selected_atom_rows(category_rows(block, "_atom_site."))
    entity_types = {row["id"]: row["type"].lower() for row in category_rows(block, "_entity.")}
    chem_comp_types = {
        row["id"].upper(): row["type"].upper()
        for row in optional_category_rows(block, "_chem_comp.")
        if "id" in row and "type" in row
    }
    branch_rows = optional_category_rows(block, "_pdbx_branch_scheme.")
    branch_links = optional_category_rows(block, "_pdbx_entity_branch_link.")
    struct_conns = optional_category_rows(block, "_struct_conn.")

    report: dict[str, Any] = {
        "pdb_id": normalized_id,
        "status": "ok",
        "counts": {},
        "warnings": [],
        "failed_occurrences": [],
    }

    het_atoms, receptor_atoms = split_candidate_atoms(atom_rows, entity_types)
    uf = UnionFind(len(het_atoms))
    residue_atoms, atom_lookup = build_het_indices(het_atoms)
    all_atom_lookup = build_all_atom_lookup(atom_rows)
    residue_covalent = set()
    inter_bond_candidates: set[
        tuple[tuple[str, str, str, str], str, tuple[str, str, str, str], str]
    ] = set()

    add_ccd_internal_edges(
        uf,
        residue_atoms,
        root / "raw" / "ccd_cache",
        report,
        allow_ccd_fetch=materialize_objects,
    )
    add_branch_edges(uf, branch_rows, branch_links, residue_atoms, inter_bond_candidates)
    add_struct_conn_edges(
        uf,
        struct_conns,
        atom_lookup,
        all_atom_lookup,
        het_atoms,
        residue_covalent,
        inter_bond_candidates,
        entity_types,
    )

    components = build_components(
        normalized_id,
        uf,
        het_atoms,
        residue_atoms,
        residue_covalent,
        inter_bond_candidates,
        entity_types,
        chem_comp_types,
    )
    components.sort(key=lambda item: item["sort_key"])
    for candidate_id, component in enumerate(components):
        component["candidate_id"] = candidate_id
        component.pop("sort_key")

    if materialize_objects:
        materialize_ligand_objects(root, components, overwrite=False)
    coords_arrays, kept_components = build_ligand_coords(
        root,
        components,
        het_atoms,
        residue_atoms,
        report,
    )
    report["counts"] = {
        "atoms": len(atom_rows),
        "het_atoms": len(het_atoms),
        "receptor_atoms": len(receptor_atoms),
        "occurrences": len(kept_components),
    }
    dependency_ccd_ids = {key[1] for key in residue_atoms}
    dependency_ccd_ids.update(atom["label_comp_id"] for atom in receptor_atoms)
    dependency_object_keys = {str(item["object_key"]) for item in components}
    return StageCSourceView(
        occurrences=kept_components,
        ligand_coords=coords_arrays,
        receptor_atoms=receptor_atoms,
        receptor_base=build_receptor_base_arrays(receptor_atoms),
        struct_conns=struct_conns,
        ccd_ids=tuple(sorted(dependency_ccd_ids)),
        object_keys=tuple(sorted(dependency_object_keys)),
        report=report,
    )


def parse_one_pdb(root: Path, pdb_id: str, overwrite: bool) -> dict[str, Any]:
    """
    解析一个 PDB 的 Stage C 产物。

    输入参数:
        - root: Path, Stage root, 内含 raw/rcsb_mmcif
        - pdb_id: str, 小写 PDB id
        - overwrite: bool, 是否覆盖已有 parse 产物

    输出:
        - report: dict[str, Any], 当前样本解析报告
    """
    pdb_id = pdb_id.lower()
    parse_dir = root / "parse" / pdb_id
    occurrence_path = parse_dir / "occurrences.jsonl"
    receptor_path = parse_dir / "receptor_tokens.npz"
    coords_path = parse_dir / "ligand_coords.npz"
    report_path = root / "reports" / f"{pdb_id}.json"
    if not overwrite:
        from contracts import CArtifactState, inspect_stage_c

        inspection = inspect_stage_c(root, pdb_id)
        if inspection.state == CArtifactState.COMPLETE:
            return {"pdb_id": pdb_id, "status": "skipped"}
        if inspection.state == CArtifactState.UPGRADE:
            from c_upgrade import upgrade_stage_c

            return upgrade_stage_c(root, pdb_id)

    # 样本级 overwrite 不再联动覆盖全局去重 LigandObject，避免并发最后写者胜。
    view = build_stage_c_source_view(root, pdb_id, materialize_objects=True)
    write_jsonl(occurrence_path, view.occurrences)
    atomic_save_npz(coords_path, **view.ligand_coords)
    write_receptor_tokens(
        receptor_path,
        view.receptor_atoms,
        view.struct_conns,
        root / "raw" / "ccd_cache",
    )
    for object_key in sorted({str(component["object_key"]) for component in view.occurrences}):
        materialize_ligand_descriptor(root, object_key, overwrite=False)

    write_report(report_path, view.report)
    return view.report


def split_candidate_atoms(
    atom_rows: list[dict[str, Any]],
    entity_types: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    划分候选 HET 原子和受体原子。

    输入参数:
        - atom_rows: list[dict[str, Any]], 已选择 altloc 的重原子
        - entity_types: dict[str, str], entity id 到类型的映射

    输出:
        - result: tuple[list[dict[str, Any]], list[dict[str, Any]]], 包含:
            - het_atoms: list[dict[str, Any]], 非 junk 候选 ligand 原子
            - receptor_atoms: list[dict[str, Any]], polymer 受体原子
    """
    het_atoms: list[dict[str, Any]] = []
    receptor_atoms: list[dict[str, Any]] = []
    for atom in atom_rows:
        entity_type = entity_types.get(atom["label_entity_id"], "")
        resname = atom["label_comp_id"]
        if entity_type == "polymer":
            receptor_atoms.append(atom)
        elif atom["group_PDB"] == "HETATM" or entity_type in {"non-polymer", "branched"}:
            if resname not in JUNK_RESNAMES:
                atom["het_index"] = len(het_atoms)
                het_atoms.append(atom)
    return het_atoms, receptor_atoms


def build_het_indices(
    het_atoms: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str, str], dict[str, int]], dict[tuple[str, ...], int]]:
    """
    构建 HET residue 和 atom 查找索引。

    输入参数:
        - het_atoms: list[dict[str, Any]], 候选 ligand 原子

    输出:
        - result: tuple[dict, dict], 包含:
            - residue_atoms: dict, residue_key 到 atom_name/atom_index 的映射
            - atom_lookup: dict, 多种 mmCIF partner key 到 atom_index 的映射
    """
    residue_atoms: dict[tuple[str, str, str, str], dict[str, int]] = defaultdict(dict)
    atom_lookup: dict[tuple[str, ...], int] = {}
    for atom in het_atoms:
        idx = atom["het_index"]
        rkey = residue_key(atom)
        residue_atoms[rkey][atom["label_atom_id"]] = idx
        if atom["label_seq_id"]:
            atom_lookup[("label", atom["label_asym_id"], atom["label_comp_id"], atom["label_seq_id"], atom["label_atom_id"])] = idx
        if atom["auth_seq_id"]:
            atom_lookup[("auth", atom["auth_asym_id"], atom["auth_comp_id"], atom["auth_seq_id"], atom["auth_atom_id"])] = idx
            atom_lookup[("label_authseq", atom["label_asym_id"], atom["label_comp_id"], atom["auth_seq_id"], atom["label_atom_id"])] = idx
    return residue_atoms, atom_lookup


def build_all_atom_lookup(atom_rows: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
    """
    构建全原子 struct_conn partner 查找索引。

    输入参数:
        - atom_rows: list[dict[str, Any]], 已选择 altloc 的全部重原子

    输出:
        - lookup: dict[tuple[str, ...], dict[str, Any]], partner key 到 atom_site 行的映射
    """
    lookup: dict[tuple[str, ...], dict[str, Any]] = {}
    for atom in atom_rows:
        if atom["label_seq_id"]:
            lookup[("label", atom["label_asym_id"], atom["label_comp_id"], atom["label_seq_id"], atom["label_atom_id"])] = atom
        if atom["auth_seq_id"]:
            lookup[("auth", atom["auth_asym_id"], atom["auth_comp_id"], atom["auth_seq_id"], atom["auth_atom_id"])] = atom
            lookup[("label_authseq", atom["label_asym_id"], atom["label_comp_id"], atom["auth_seq_id"], atom["label_atom_id"])] = atom
    return lookup


def add_ccd_internal_edges(
    uf: UnionFind,
    residue_atoms: dict[tuple[str, str, str, str], dict[str, int]],
    ccd_cache_dir: Path,
    report: dict[str, Any],
    *,
    allow_ccd_fetch: bool = True,
) -> None:
    """
    根据 CCD 模板添加 residue 内部键。

    输入参数:
        - uf: UnionFind, HET 原子并查集
        - residue_atoms: dict, residue 到 atom index 的映射
        - ccd_cache_dir: Path, CCD 缓存目录
        - report: dict[str, Any], 样本报告
        - allow_ccd_fetch: bool, 缓存缺失时是否允许访问 RCSB；source audit 为 False

    输出:
        - None: 并查集原地更新
    """
    for rkey, atom_by_name in residue_atoms.items():
        ccd_id = rkey[1]
        try:
            mol = Chem.RemoveHs(
                get_ccd_mol(ccd_id, ccd_cache_dir, allow_fetch=allow_ccd_fetch),
                sanitize=False,
            )
        except Exception as exc:
            report["warnings"].append({"type": "ccd_failed", "ccd_id": ccd_id, "error": str(exc)})
            continue
        for bond in mol.GetBonds():
            left = mol.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetProp("name")
            right = mol.GetAtomWithIdx(bond.GetEndAtomIdx()).GetProp("name")
            if left in atom_by_name and right in atom_by_name:
                uf.union(atom_by_name[left], atom_by_name[right])


def add_branch_edges(
    uf: UnionFind,
    branch_rows: list[dict[str, str]],
    branch_links: list[dict[str, str]],
    residue_atoms: dict[tuple[str, str, str, str], dict[str, int]],
    inter_bonds: set[tuple[tuple[str, str, str, str], str, tuple[str, str, str, str], str]],
) -> None:
    """
    根据 `_pdbx_entity_branch_link` 添加 branched residue 间键。

    输入参数:
        - uf: UnionFind, HET 原子并查集
        - branch_rows: list[dict[str, str]], branch_scheme 行
        - branch_links: list[dict[str, str]], entity_branch_link 行
        - residue_atoms: dict, residue 到 atom index 的映射
        - inter_bonds: set, 跨 residue 键集合

    输出:
        - None: 并查集和 inter_bonds 原地更新
    """
    by_entity_asym: dict[tuple[str, str], dict[str, tuple[str, str, str, str]]] = defaultdict(dict)
    for row in branch_rows:
        entity_id = clean_value(row.get("entity_id", ""))
        asym_id = clean_value(row.get("asym_id", ""))
        mon_id = clean_value(row.get("mon_id", "")).upper()
        num = clean_value(row.get("num", ""))
        pdb_seq_num = clean_value(row.get("pdb_seq_num", ""))
        rkey = (asym_id, mon_id, pdb_seq_num or num, "")
        if rkey in residue_atoms:
            by_entity_asym[(entity_id, asym_id)][num] = rkey

    for link in branch_links:
        entity_id = clean_value(link.get("entity_id", ""))
        num1 = clean_value(link.get("entity_branch_list_num_1", ""))
        num2 = clean_value(link.get("entity_branch_list_num_2", ""))
        atom1 = clean_value(link.get("atom_id_1", ""))
        atom2 = clean_value(link.get("atom_id_2", ""))
        for (link_entity_id, _asym_id), num_to_rkey in by_entity_asym.items():
            if link_entity_id != entity_id or num1 not in num_to_rkey or num2 not in num_to_rkey:
                continue
            rkey1 = num_to_rkey[num1]
            rkey2 = num_to_rkey[num2]
            if atom1 in residue_atoms[rkey1] and atom2 in residue_atoms[rkey2]:
                uf.union(residue_atoms[rkey1][atom1], residue_atoms[rkey2][atom2])
                add_inter_bond(inter_bonds, rkey1, atom1, rkey2, atom2)


def add_struct_conn_edges(
    uf: UnionFind,
    struct_conns: list[dict[str, str]],
    atom_lookup: dict[tuple[str, ...], int],
    all_atom_lookup: dict[tuple[str, ...], dict[str, Any]],
    het_atoms: list[dict[str, Any]],
    residue_covalent: set[tuple[str, str, str, str]],
    inter_bonds: set[tuple[tuple[str, str, str, str], str, tuple[str, str, str, str], str]],
    entity_types: dict[str, str],
) -> None:
    """
    根据 `_struct_conn.conn_type_id == covale` 添加记录连接。

    输入参数:
        - uf: UnionFind, HET 原子并查集
        - struct_conns: list[dict[str, str]], struct_conn 行
        - atom_lookup: dict, partner key 到 HET atom index
        - het_atoms: list[dict[str, Any]], HET 原子列表
        - residue_covalent: set, 与 polymer 共价连接的 ligand residue
        - inter_bonds: set, 跨 residue 键集合
        - entity_types: dict[str, str], entity id 到类型的映射

    输出:
        - None: 并查集、covalent 标记和 inter_bonds 原地更新
    """
    for row in struct_conns:
        if clean_value(row.get("conn_type_id", "")).lower() != "covale":
            continue
        left_idx = lookup_struct_conn_partner(row, "ptnr1_", atom_lookup)
        right_idx = lookup_struct_conn_partner(row, "ptnr2_", atom_lookup)
        if left_idx is not None and right_idx is not None:
            uf.union(left_idx, right_idx)
            left_key = residue_key(het_atoms[left_idx])
            right_key = residue_key(het_atoms[right_idx])
            if left_key != right_key:
                add_inter_bond(
                    inter_bonds,
                    left_key,
                    clean_value(row.get("ptnr1_label_atom_id", "")),
                    right_key,
                    clean_value(row.get("ptnr2_label_atom_id", "")),
                )
            continue
        if left_idx is not None and partner_is_polymer(row, "ptnr2_", all_atom_lookup, entity_types):
            residue_covalent.add(residue_key(het_atoms[left_idx]))
        if right_idx is not None and partner_is_polymer(row, "ptnr1_", all_atom_lookup, entity_types):
            residue_covalent.add(residue_key(het_atoms[right_idx]))


def lookup_struct_conn_partner(
    row: dict[str, str],
    prefix: str,
    atom_lookup: dict[tuple[str, ...], int],
) -> int | None:
    """
    在 HET atom lookup 中查找 struct_conn partner。

    输入参数:
        - row: dict[str, str], struct_conn 行
        - prefix: str, `ptnr1_` 或 `ptnr2_`
        - atom_lookup: dict, partner key 到 HET atom index

    输出:
        - atom_index: int 或 None, 找不到则为 None
    """
    label_key = (
        "label",
        clean_value(row.get(prefix + "label_asym_id", "")),
        clean_value(row.get(prefix + "label_comp_id", "")).upper(),
        clean_value(row.get(prefix + "label_seq_id", "")),
        clean_value(row.get(prefix + "label_atom_id", "")),
    )
    auth_key = (
        "auth",
        clean_value(row.get(prefix + "auth_asym_id", "")),
        clean_value(row.get(prefix + "auth_comp_id", "")).upper(),
        clean_value(row.get(prefix + "auth_seq_id", "")),
        clean_value(row.get(prefix + "auth_atom_id", "")),
    )
    label_authseq_key = (
        "label_authseq",
        clean_value(row.get(prefix + "label_asym_id", "")),
        clean_value(row.get(prefix + "label_comp_id", "")).upper(),
        clean_value(row.get(prefix + "auth_seq_id", "")),
        clean_value(row.get(prefix + "label_atom_id", "")),
    )
    for key in (label_key, auth_key, label_authseq_key):
        if key in atom_lookup:
            return atom_lookup[key]
    return None


def add_inter_bond(
    inter_bonds: set[tuple[tuple[str, str, str, str], str, tuple[str, str, str, str], str]],
    left_key: tuple[str, str, str, str],
    left_atom: str,
    right_key: tuple[str, str, str, str],
    right_atom: str,
) -> None:
    """
    规范化并记录一条跨 residue 键。

    输入参数:
        - inter_bonds: set, 跨 residue 键集合
        - left_key: tuple[str, str, str, str], 左侧 residue key
        - left_atom: str, 左侧 atom name
        - right_key: tuple[str, str, str, str], 右侧 residue key
        - right_atom: str, 右侧 atom name

    输出:
        - None: inter_bonds 原地更新
    """
    if (residue_sort_key(left_key), left_atom) <= (residue_sort_key(right_key), right_atom):
        inter_bonds.add((left_key, left_atom, right_key, right_atom))
    else:
        inter_bonds.add((right_key, right_atom, left_key, left_atom))


def partner_is_polymer(
    row: dict[str, str],
    prefix: str,
    all_atom_lookup: dict[tuple[str, ...], dict[str, Any]],
    entity_types: dict[str, str],
) -> bool:
    """
    判断 struct_conn partner 是否属于 polymer。

    输入参数:
        - row: dict[str, str], struct_conn 行
        - prefix: str, `ptnr1_` 或 `ptnr2_`
        - all_atom_lookup: dict, partner key 到 atom_site 行的映射
        - entity_types: dict[str, str], entity id 到类型的映射

    输出:
        - is_polymer: bool, partner entity 为 polymer 时为 True
    """
    label_key = (
        "label",
        clean_value(row.get(prefix + "label_asym_id", "")),
        clean_value(row.get(prefix + "label_comp_id", "")).upper(),
        clean_value(row.get(prefix + "label_seq_id", "")),
        clean_value(row.get(prefix + "label_atom_id", "")),
    )
    auth_key = (
        "auth",
        clean_value(row.get(prefix + "auth_asym_id", "")),
        clean_value(row.get(prefix + "auth_comp_id", "")).upper(),
        clean_value(row.get(prefix + "auth_seq_id", "")),
        clean_value(row.get(prefix + "auth_atom_id", "")),
    )
    label_authseq_key = (
        "label_authseq",
        clean_value(row.get(prefix + "label_asym_id", "")),
        clean_value(row.get(prefix + "label_comp_id", "")).upper(),
        clean_value(row.get(prefix + "auth_seq_id", "")),
        clean_value(row.get(prefix + "label_atom_id", "")),
    )
    atom = all_atom_lookup.get(label_key) or all_atom_lookup.get(auth_key) or all_atom_lookup.get(label_authseq_key)
    if atom is None:
        return False
    return entity_types.get(atom["label_entity_id"], "") == "polymer"


def build_components(
    pdb_id: str,
    uf: UnionFind,
    het_atoms: list[dict[str, Any]],
    residue_atoms: dict[tuple[str, str, str, str], dict[str, int]],
    residue_covalent: set[tuple[str, str, str, str]],
    inter_bonds: set[tuple[tuple[str, str, str, str], str, tuple[str, str, str, str], str]],
    entity_types: dict[str, str],
    chem_comp_types: dict[str, str],
) -> list[dict[str, Any]]:
    """
    从并查集分量构造 occurrence 记录。

    输入参数:
        - pdb_id: str, 小写 PDB id
        - uf: UnionFind, HET 原子并查集
        - het_atoms: list[dict[str, Any]], HET 原子
        - residue_atoms: dict, residue 到 atom index 的映射
        - residue_covalent: set, 与 polymer 共价连接的 residue
        - inter_bonds: set, 记录来源的跨 residue 键
        - entity_types: dict[str, str], entity id 到类型
        - chem_comp_types: dict[str, str], CCD id 到 chem_comp.type

    输出:
        - components: list[dict[str, Any]], occurrence 记录列表, candidate_id 尚未填入
    """
    root_to_atoms: dict[int, list[int]] = defaultdict(list)
    for atom in het_atoms:
        root_to_atoms[uf.find(atom["het_index"])].append(atom["het_index"])

    results: list[dict[str, Any]] = []
    for atom_indices in root_to_atoms.values():
        group_atoms = [het_atoms[idx] for idx in atom_indices]
        group_residues = sorted({residue_key(atom) for atom in group_atoms}, key=residue_sort_key)
        res_index = {rkey: idx + 1 for idx, rkey in enumerate(group_residues)}
        components = []
        for rkey in group_residues:
            sample_atom = het_atoms[next(iter(residue_atoms[rkey].values()))]
            components.append(
                {
                    "index": res_index[rkey],
                    "ccd_id": rkey[1],
                    "label_asym_id": rkey[0],
                    "label_seq_id": int(rkey[2]) if str(rkey[2]).isdigit() else None,
                    "auth_asym_id": sample_atom["auth_asym_id"],
                    "auth_seq_id": int(sample_atom["auth_seq_id"]) if str(sample_atom["auth_seq_id"]).isdigit() else sample_atom["auth_seq_id"],
                    "icode": rkey[3],
                }
            )

        occurrence_inter_bonds = []
        for left_key, left_atom, right_key, right_atom in sorted(inter_bonds):
            if left_key in res_index and right_key in res_index:
                occurrence_inter_bonds.append([res_index[left_key], left_atom, res_index[right_key], right_atom])

        kind = "BRANCHED" if len(group_residues) > 1 else "CCD"
        object_key = build_object_key(group_residues, occurrence_inter_bonds)
        type_tag = derive_type_tag(group_atoms, group_residues, entity_types, chem_comp_types)
        sort_key = (
            min(atom["label_asym_id"] for atom in group_atoms),
            min(residue_sort_key(residue_key(atom))[1] for atom in group_atoms),
            min(atom["atom_site_id"] for atom in group_atoms),
        )
        results.append(
            {
                "pdb_id": pdb_id,
                "candidate_id": -1,
                "kind": kind,
                "object_key": object_key,
                "type_tag": type_tag,
                "is_covalent": any(rkey in residue_covalent for rkey in group_residues),
                "polymer_length": len(group_residues),
                "n_heavy_atoms": len(group_atoms),
                "components": components,
                "inter_bonds": occurrence_inter_bonds,
                "sort_key": sort_key,
            }
        )
    return results


def residue_sort_key(rkey: tuple[str, str, str, str]) -> tuple[str, int, str]:
    """
    构造 residue 排序键。

    输入参数:
        - rkey: tuple[str, str, str, str], residue 实例键

    输出:
        - key: tuple[str, int, str], asym、序号、CCD 名称
    """
    seq = int(rkey[2]) if str(rkey[2]).isdigit() else 10**9
    return (rkey[0], seq, rkey[1])


def build_object_key(
    group_residues: list[tuple[str, str, str, str]],
    inter_bonds: list[list[Any]],
) -> str:
    """
    构造 LigandObject 去重键。

    输入参数:
        - group_residues: list[tuple[str, str, str, str]], occurrence residue 列表
        - inter_bonds: list[list[Any]], occurrence 内跨 residue 键

    输出:
        - object_key: str, CCD 或 BRANCHED 对象键
    """
    ccds = [rkey[1] for rkey in group_residues]
    if len(ccds) == 1:
        return f"CCD:{ccds[0]}"
    digest_source = json.dumps({"ccds": ccds, "bonds": sorted(inter_bonds)}, sort_keys=True)
    bond_hash = hashlib.md5(digest_source.encode("utf-8")).hexdigest()[:6]
    return f"BRANCHED:{'-'.join(ccds)}:{bond_hash}"


def derive_type_tag(
    group_atoms: list[dict[str, Any]],
    group_residues: list[tuple[str, str, str, str]],
    entity_types: dict[str, str],
    chem_comp_types: dict[str, str],
) -> str:
    """
    派生 occurrence 的 type_tag。

    输入参数:
        - group_atoms: list[dict[str, Any]], occurrence 原子
        - group_residues: list[tuple[str, str, str, str]], occurrence residue
        - entity_types: dict[str, str], entity id 到类型
        - chem_comp_types: dict[str, str], CCD id 到 chem_comp.type

    输出:
        - type_tag: str, small_molecule/sugar/peptide_like/nucleotide_like/ion/other
    """
    comp_types = [chem_comp_types.get(rkey[1], "").upper() for rkey in group_residues]
    if any(entity_types.get(atom["label_entity_id"], "") == "branched" for atom in group_atoms):
        return "sugar"
    if comp_types and all("SACCHARIDE" in comp_type for comp_type in comp_types):
        return "sugar"
    if any("PEPTIDE LINKING" in comp_type for comp_type in comp_types):
        return "peptide_like"
    if any("NA LINKING" in comp_type for comp_type in comp_types):
        return "nucleotide_like"
    if len(group_atoms) == 1 and group_atoms[0]["element"] in METAL_ELEMENTS:
        return "ion"
    if comp_types and all(comp_type == "NON-POLYMER" for comp_type in comp_types):
        return "small_molecule"
    return "other"


def materialize_ligand_objects(root: Path, components: list[dict[str, Any]], overwrite: bool) -> None:
    """
    为 occurrence 列表物化去重 LigandObject。

    输入参数:
        - root: Path, Stage root
        - components: list[dict[str, Any]], occurrence 记录列表
        - overwrite: bool, 是否覆盖已存在的 LigandObject 文件

    输出:
        - None: `ligand_objects` 目录中包含所需对象
    """
    ligands_dir = root / "ligand_objects"
    ccd_cache_dir = root / "raw" / "ccd_cache"
    for component in components:
        object_key = component["object_key"]
        materialized_key = (str(root.resolve()), object_key)
        output_path = ligands_dir / f"{safe_object_filename(object_key)}.npz"
        lock_path = root / "reports" / "locks" / "ligand_objects" / f"{safe_object_filename(object_key)}.lock"
        with file_lock(lock_path):
            if (
                ligand_object_is_valid(output_path, object_key)
                and (not overwrite or materialized_key in _MATERIALIZED_OBJECT_KEYS)
            ):
                continue
            if component["kind"] == "CCD":
                materialize_ccd_ligand(
                    component["components"][0]["ccd_id"],
                    object_key,
                    ligands_dir,
                    ccd_cache_dir,
                    overwrite=True,
                )
            else:
                branched_config = {
                    "residues": [f"{item['index']}. {item['ccd_id']}" for item in component["components"]],
                    "bonds": component["inter_bonds"],
                }
                process_branched_ligand(branched_config, object_key, ligands_dir, ccd_cache_dir, None)
            if not ligand_object_is_valid(output_path, object_key):
                raise ValueError(f"invalid LigandObject after materialization: {object_key}")
            _MATERIALIZED_OBJECT_KEYS.add(materialized_key)


def build_ligand_coords(
    root: Path,
    components: list[dict[str, Any]],
    het_atoms: list[dict[str, Any]],
    residue_atoms: dict[tuple[str, str, str, str], dict[str, int]],
    report: dict[str, Any],
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    """
    构造每个 occurrence 对齐 LigandObject 的真实坐标。

    输入参数:
        - root: Path, Stage root
        - components: list[dict[str, Any]], occurrence 记录
        - het_atoms: list[dict[str, Any]], HET 原子
        - residue_atoms: dict, residue 到 atom index 的映射
        - report: dict[str, Any], 样本报告

    输出:
        - result: tuple[dict[str, np.ndarray], list[dict[str, Any]]], 包含:
            - coords_arrays: dict[str, np.ndarray], `coords_{cid}` 和 `present_{cid}` 数组
            - kept_components: list[dict[str, Any]], 成功对齐的 occurrence
    """
    coords_arrays: dict[str, np.ndarray] = {}
    kept_components: list[dict[str, Any]] = []
    for component in components:
        object_path = root / "ligand_objects" / f"{safe_object_filename(component['object_key'])}.npz"
        with np.load(object_path, allow_pickle=True) as obj:
            atom_names = [str(item) for item in obj["atom_names"].tolist()]
            atoms = obj["atoms"]
        coords = np.full((len(atom_names), 3), np.nan, dtype=np.float32)
        present = np.zeros((len(atom_names),), dtype=bool)
        unmatched_deposited: list[str] = []

        component_residue_keys = []
        for item in component["components"]:
            seq = str(item["label_seq_id"] if item["label_seq_id"] is not None else item["auth_seq_id"])
            component_residue_keys.append((item["label_asym_id"], item["ccd_id"], seq, item["icode"]))

        ligand_slots: dict[tuple[int, str], int] = {}
        for atom_idx, atom_name in enumerate(atom_names):
            residue_id = int(atoms[atom_idx]["residue_id"])
            ligand_slots[(residue_id, atom_name)] = atom_idx

        for comp_idx, rkey in enumerate(component_residue_keys, start=1):
            for atom_name, het_idx in residue_atoms[rkey].items():
                slot = ligand_slots.get((comp_idx, atom_name))
                if slot is None:
                    unmatched_deposited.append(f"{comp_idx}:{atom_name}")
                    continue
                atom = het_atoms[het_idx]
                coords[slot] = (atom["x"], atom["y"], atom["z"])
                present[slot] = True

        if unmatched_deposited:
            report["failed_occurrences"].append(
                {
                    "candidate_id": component["candidate_id"],
                    "reason": "resolve_failed",
                    "unmatched_deposited": unmatched_deposited,
                }
            )
            continue

        cid = component["candidate_id"]
        coords_arrays[f"coords_{cid}"] = coords
        coords_arrays[f"present_{cid}"] = present
        coords_arrays[f"centroid_atom_{cid}"] = coords[present].mean(
            axis=0,
            dtype=np.float64,
        ).astype(np.float32)
        kept_components.append(component)
    return coords_arrays, kept_components


def write_receptor_tokens(
    path: Path,
    receptor_atoms: list[dict[str, Any]],
    struct_conns: list[dict[str, str]],
    ccd_cache_dir: Path,
) -> None:
    """
    保存 receptor token 表。

    输入参数:
        - path: Path, 输出 `receptor_tokens.npz`
        - receptor_atoms: list[dict[str,Any]], polymer 重原子
        - struct_conns: list[dict[str,str]], `_struct_conn` 行
        - ccd_cache_dir: Path, `raw/ccd_cache` 目录

    输出:
        - None: receptor token 文件写入完成
    """
    arrays = build_receptor_arrays(receptor_atoms, struct_conns, ccd_cache_dir)
    atomic_save_npz(path, **arrays)


def normalize_residue(resname: str) -> str:
    """
    将常见修饰残基映射到标准母体。

    输入参数:
        - resname: str, mmCIF residue/comp id

    输出:
        - normalized: str, RES_VOCAB 中的标准残基或原值
    """
    mapping = {
        "MSE": "MET",
        "SEP": "SER",
        "TPO": "THR",
        "PTR": "TYR",
        "HYP": "PRO",
        "SEC": "CYS",
        "PYL": "LYS",
        "HID": "HIS",
        "HIE": "HIS",
        "HIP": "HIS",
        "CYX": "CYS",
    }
    return mapping.get(resname.upper(), resname.upper())


def is_backbone_atom(atom: dict[str, Any]) -> bool:
    """
    判断受体原子是否为蛋白或核酸主链原子。

    输入参数:
        - atom: dict[str, Any], receptor atom 行

    输出:
        - is_backbone: bool, 主链原子为 True
    """
    resname = normalize_residue(atom["label_comp_id"])
    atom_name = atom["label_atom_id"]
    if resname in {"A", "C", "G", "U", "DA", "DC", "DG", "DT"}:
        return atom_name in NUCLEIC_BACKBONE
    return atom_name in PROTEIN_BACKBONE
