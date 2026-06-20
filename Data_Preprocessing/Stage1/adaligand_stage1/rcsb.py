"""RCSB、PDBe 与 EMDB 元数据访问。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import requests

RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_ENTRY_URL = "https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
PDB_CIF_URL = "https://files.rcsb.org/download/{pdb_id}.cif"
EMDB_META_URL = "https://www.ebi.ac.uk/emdb/api/entry/{emdb_id}"
EMDB_MAP_URL = (
    "https://ftp.ebi.ac.uk/pub/databases/emdb/structures/EMD-{emdb_num}/map/"
    "emd_{emdb_num}.map.gz"
)


def search_em_ligand_entries() -> list[str]:
    """
    查询含 EMDB 且带非聚合物或 branched entity 的 EM 结构。

    输出:
        - pdb_ids: list[str], 小写 PDB id 列表
    """
    query = {
        "query": {
            "type": "group",
            "logical_operator": "and",
            "nodes": [
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "exptl.method",
                        "operator": "exact_match",
                        "value": "ELECTRON MICROSCOPY",
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_container_identifiers.emdb_ids",
                        "operator": "exists",
                    },
                },
                {
                    "type": "group",
                    "logical_operator": "or",
                    "nodes": [
                        {
                            "type": "terminal",
                            "service": "text",
                            "parameters": {
                                "attribute": "rcsb_entry_info.nonpolymer_entity_count",
                                "operator": "greater",
                                "value": 0,
                            },
                        },
                        {
                            "type": "terminal",
                            "service": "text",
                            "parameters": {
                                "attribute": "rcsb_entry_info.branched_entity_count",
                                "operator": "greater",
                                "value": 0,
                            },
                        },
                    ],
                },
            ],
        },
        "return_type": "entry",
        "request_options": {"return_all_hits": True},
    }
    response = requests.post(RCSB_SEARCH_URL, json=query, timeout=60)
    response.raise_for_status()
    data = response.json()
    result_set = data.get("result_set", [])
    return [str(item["identifier"]).lower() for item in result_set]


def fetch_entry_metadata(pdb_id: str) -> dict[str, Any]:
    """
    读取 RCSB entry metadata。

    输入参数:
        - pdb_id: str, PDB id, 大小写均可

    输出:
        - metadata: dict[str, Any], RCSB Data API 返回对象
    """
    response = requests.get(RCSB_ENTRY_URL.format(pdb_id=pdb_id.upper()), timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_emdb_metadata(emdb_id: str) -> dict[str, Any]:
    """
    读取 PDBe EMDB 元数据。

    输入参数:
        - emdb_id: str, 形如 `EMD-30556`

    输出:
        - metadata: dict[str, Any], PDBe REST API 返回对象
    """
    response = requests.get(EMDB_META_URL.format(emdb_id=emdb_id), timeout=30)
    response.raise_for_status()
    return response.json()


def choose_emdb_id(pdb_id: str, entry_metadata: dict[str, Any]) -> str:
    """
    从 RCSB entry metadata 中选择主 EMDB id。

    输入参数:
        - pdb_id: str, 小写 PDB id
        - entry_metadata: dict[str, Any], RCSB entry metadata

    输出:
        - emdb_id: str, 形如 `EMD-30556`
    """
    identifiers = entry_metadata["rcsb_entry_container_identifiers"]
    emdb_ids = [str(item).upper() for item in identifiers["emdb_ids"]]
    if len(emdb_ids) == 1:
        return emdb_ids[0]

    matched_emdb_ids: list[str] = []
    for emdb_id in emdb_ids:
        try:
            meta = fetch_emdb_metadata(emdb_id)
        except requests.RequestException:
            continue
        if emdb_references_pdb(meta, pdb_id):
            matched_emdb_ids.append(emdb_id)
    if matched_emdb_ids:
        return matched_emdb_ids[0]
    return emdb_ids[0]


def emdb_references_pdb(emdb_metadata: dict[str, Any], pdb_id: str) -> bool:
    """
    判断 EMDB metadata 是否明确引用当前 PDB。

    输入参数:
        - emdb_metadata: dict[str, Any], EMDB API `/entry/{emdb_id}` 返回对象
        - pdb_id: str, PDB id, 大小写均可

    输出:
        - is_referenced: bool, `crossreferences.pdb_list.pdb_reference` 中含该 PDB 时为 True
    """
    pdb_references = (
        emdb_metadata.get("crossreferences", {})
        .get("pdb_list", {})
        .get("pdb_reference", [])
    )
    if isinstance(pdb_references, dict):
        pdb_references = [pdb_references]
    expected = pdb_id.lower()
    return any(str(item.get("pdb_id", "")).lower() == expected for item in pdb_references)


def extract_resolution(*objects: dict[str, Any]) -> float | None:
    """
    从 RCSB/PDBe 元数据中提取第一个可用分辨率。

    输入参数:
        - objects: dict[str, Any], 一个或多个 metadata 对象

    输出:
        - resolution: float 或 None, 单位 Å; 缺失时为 None
    """
    for obj in objects:
        direct = _extract_resolution_from_object(obj)
        if direct is not None:
            return direct
    return None


def _extract_resolution_from_object(obj: Any) -> float | None:
    """
    从嵌套对象中寻找 resolution 数值。

    输入参数:
        - obj: Any, JSON 可表示对象

    输出:
        - resolution: float 或 None
    """
    if isinstance(obj, dict):
        for key in ("resolution_combined", "resolution", "map_resolution"):
            if key in obj:
                value = obj[key]
                if isinstance(value, list) and value:
                    value = value[0]
                if isinstance(value, int | float):
                    return float(value)
                if isinstance(value, str):
                    try:
                        return float(value)
                    except ValueError:
                        pass
        for value in obj.values():
            nested = _extract_resolution_from_object(value)
            if nested is not None:
                return nested
    elif isinstance(obj, list):
        for value in obj:
            nested = _extract_resolution_from_object(value)
            if nested is not None:
                return nested
    return None


def build_pair_records(pdb_ids: Iterable[str], limit: int | None) -> list[dict[str, Any]]:
    """
    为 PDB id 列表构造 pair_list 记录。

    输入参数:
        - pdb_ids: Iterable[str], PDB id 序列
        - limit: int 或 None, 最多输出记录数; None 表示不截断

    输出:
        - records: list[dict[str, Any]], 每项含 emdb_id、pdb_id、resolution
    """
    records: list[dict[str, Any]] = []
    for pdb_id in pdb_ids:
        entry_meta = fetch_entry_metadata(pdb_id)
        emdb_id = choose_emdb_id(pdb_id, entry_meta)
        try:
            emdb_meta = fetch_emdb_metadata(emdb_id)
        except requests.RequestException:
            emdb_meta = {}
        records.append(
            {
                "emdb_id": emdb_id,
                "pdb_id": pdb_id.lower(),
                "resolution": extract_resolution(entry_meta, emdb_meta),
            }
        )
        if limit is not None and len(records) >= limit:
            break
    return records


def emdb_map_url(emdb_id: str) -> str:
    """
    构造 EMDB map.gz 下载 URL。

    输入参数:
        - emdb_id: str, 形如 `EMD-30556`

    输出:
        - url: str, 官方 FTP/HTTPS map.gz 地址
    """
    emdb_num = emdb_id.upper().replace("EMD-", "")
    return EMDB_MAP_URL.format(emdb_num=emdb_num)
