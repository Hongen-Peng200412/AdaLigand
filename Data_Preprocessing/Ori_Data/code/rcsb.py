# 学习导航：功能分区=外部工具与格式适配；生命周期=正式主路径 Stage A 元数据适配。
# 主要输入：PDB/EMDB 查询条件、RCSB/EMDB HTTP 响应和重试配置。
# 主要输出：pair_list 所需 PDB↔EMDB、分辨率、URL 与 provenance 字段。
# 关键边界：网络元数据只建立候选宇宙；A guard 冻结后，后续阶段不得隐式改写样本集合。
"""Stage A 的 RCSB / EMDB 元数据访问与分辨率 provenance。

- search_em_ligand_entries：一次 RCSB Search 查询，列出"EM + 有 EMDB + 含配体"的全部 PDB（全局，不分片）。
- fetch_entry_metadata / fetch_emdb_metadata / choose_emdb_id：取条目元数据、为多 EMDB 选主 EMDB。
- extract_resolution_info / build_resolution_summary：从 EMDB final reconstruction（优先）与 RCSB
  resolution_combined（fallback）显式收集分辨率候选，给出选定值、来源、状态与本批统计。
- 网络请求带少量重试。供 a_enumerate 写 pair_list / resolution_summary。
"""

from __future__ import annotations

from collections.abc import Iterable
import time
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
REQUEST_RETRIES = 3
REQUEST_RETRY_SLEEP_SECONDS = 2.0


def _request_with_retries(method: str, url: str, **kwargs: Any) -> requests.Response:
    """
    带少量重试地访问外部 metadata API。

    输入参数:
        - method: str, `requests.request` 支持的 HTTP 方法
        - url: str, 目标 URL
        - kwargs: Any, 传给 `requests.request` 的关键字参数

    输出:
        - response: requests.Response, 成功返回的 HTTP 响应对象
    """
    last_exc: requests.RequestException | None = None
    for attempt in range(REQUEST_RETRIES):
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt + 1 == REQUEST_RETRIES:
                break
            time.sleep(REQUEST_RETRY_SLEEP_SECONDS * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def search_em_ligand_entries() -> list[str]:
    """
    查询含 EMDB 且带 ligand-like entity 的 EM 结构。

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
    response = _request_with_retries("post", RCSB_SEARCH_URL, json=query, timeout=60)
    data = response.json()
    result_set = data.get("result_set", [])
    return [str(item["identifier"]).lower() for item in result_set]


def fetch_entry_metadata(pdb_id: str) -> dict[str, Any]:
    """
    读取 RCSB entry metadata。

    输入参数:
        - pdb_id: str, PDB id, 大小写不敏感

    输出:
        - metadata: dict[str, Any], RCSB Data API 返回对象
    """
    response = _request_with_retries(
        "get", RCSB_ENTRY_URL.format(pdb_id=pdb_id.upper()), timeout=30
    )
    return response.json()


def fetch_emdb_metadata(emdb_id: str) -> dict[str, Any]:
    """
    读取 PDBe EMDB metadata。

    输入参数:
        - emdb_id: str, 形如 `EMD-30556`

    输出:
        - metadata: dict[str, Any], PDBe REST API 返回对象
    """
    response = _request_with_retries(
        "get", EMDB_META_URL.format(emdb_id=emdb_id), timeout=30
    )
    return response.json()


def choose_emdb_id(pdb_id: str, entry_metadata: dict[str, Any]) -> str:
    """
    从 RCSB entry metadata 中选择一个 EMDB id。

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
    判断 EMDB metadata 是否明确引用当前 PDB id。

    输入参数:
        - emdb_metadata: dict[str, Any], EMDB API `/entry/{emdb_id}` 返回对象
        - pdb_id: str, PDB id, 大小写不敏感

    输出:
        - is_referenced: bool, `pdb_reference` 包含该 PDB id 时为 True
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


def extract_resolution_info(
    entry_metadata: dict[str, Any],
    emdb_metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    从明确的 RCSB/EMDB 字段收集并选择 map 分辨率。

    输入参数:
        - entry_metadata: dict[str, Any], RCSB entry metadata
        - emdb_metadata: dict[str, Any], PDBe EMDB metadata

    输出:
        - info: dict[str, Any], 包含:
            - selected: float 或 None, 最终选择的分辨率
            - status: str, 选择状态
            - selected_source: str 或 None, 被选中候选的来源
            - selection_rule: str, 当前记录使用的选择规则
            - n_candidates: int, 收集到的候选数量
            - n_unique_values: int, 候选唯一数值数量
            - rcsb_disagree: bool, RCSB 候选是否与最终选择不同
            - candidates: list[dict[str, Any]], 每项含 source/value/units/method/path
    """
    candidates = [
        *_collect_emdb_resolution_candidates(emdb_metadata),
        *_collect_rcsb_resolution_candidates(entry_metadata),
    ]
    emdb_candidates = [
        item for item in candidates if item["source"] == "emdb.final_reconstruction"
    ]
    rcsb_candidates = [
        item for item in candidates if item["source"] == "rcsb.resolution_combined"
    ]

    if emdb_candidates:
        selected_candidate = emdb_candidates[0]
        selected = selected_candidate["value"]
        emdb_unique = _unique_resolution_values(emdb_candidates)
        all_unique = _unique_resolution_values(candidates)
        if len(emdb_unique) > 1:
            status = "ambiguous_emdb"
            selection_rule = "first_emdb_final_reconstruction_due_to_multiple_values"
        elif len(candidates) > 1 and len(all_unique) == 1:
            status = "multi_candidate_consistent"
            selection_rule = "emdb_unique_preferred"
        elif _rcsb_disagrees(selected, rcsb_candidates):
            status = "rcsb_disagree"
            selection_rule = "emdb_unique_preferred_rcsb_disagrees"
        else:
            status = "single_unique"
            selection_rule = "emdb_unique_preferred"
    elif rcsb_candidates:
        selected_candidate = rcsb_candidates[0]
        selected = selected_candidate["value"]
        status = "fallback_rcsb"
        selection_rule = "rcsb_resolution_combined_fallback"
    else:
        selected_candidate = None
        selected = None
        status = "missing"
        selection_rule = "no_explicit_resolution_candidate"

    return {
        "selected": selected,
        "status": status,
        "selected_source": None if selected_candidate is None else selected_candidate["source"],
        "selection_rule": selection_rule,
        "n_candidates": len(candidates),
        "n_unique_values": len(_unique_resolution_values(candidates)),
        "rcsb_disagree": False if selected is None else _rcsb_disagrees(selected, rcsb_candidates),
        "candidates": candidates,
    }


def extract_resolution(
    entry_metadata: dict[str, Any],
    emdb_metadata: dict[str, Any],
) -> float | None:
    """
    返回明确选择后的分辨率数值。

    输入参数:
        - entry_metadata: dict[str, Any], RCSB entry metadata
        - emdb_metadata: dict[str, Any], PDBe EMDB metadata

    输出:
        - resolution: float 或 None, 单位 Angstrom; 缺失时为 None
    """
    return extract_resolution_info(entry_metadata, emdb_metadata)["selected"]


def _collect_emdb_resolution_candidates(emdb_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """
    收集 EMDB final reconstruction 的显式分辨率候选。

    输入参数:
        - emdb_metadata: dict[str, Any], PDBe EMDB metadata

    输出:
        - candidates: list[dict[str, Any]], 每项含 source/value/units/method/path
    """
    candidates: list[dict[str, Any]] = []
    determinations = _as_list(
        emdb_metadata.get("structure_determination_list", {}).get(
            "structure_determination", []
        )
    )
    for det_idx, determination in enumerate(determinations):
        if not isinstance(determination, dict):
            continue
        image_processing = _as_list(determination.get("image_processing", []))
        for proc_idx, processing in enumerate(image_processing):
            if not isinstance(processing, dict):
                continue
            reconstructions = _as_list(processing.get("final_reconstruction", []))
            for rec_idx, reconstruction in enumerate(reconstructions):
                if not isinstance(reconstruction, dict):
                    continue
                resolution = reconstruction.get("resolution")
                path = (
                    "structure_determination_list.structure_determination"
                    f"[{det_idx}].image_processing[{proc_idx}]"
                    f".final_reconstruction[{rec_idx}].resolution"
                )
                value, units = _resolution_value_and_units(resolution)
                if value is None:
                    continue
                candidates.append(
                    {
                        "source": "emdb.final_reconstruction",
                        "value": value,
                        "units": units,
                        "method": reconstruction.get("resolution_method"),
                        "path": f"{path}.valueOf_" if isinstance(resolution, dict) else path,
                    }
                )
    return candidates


def _collect_rcsb_resolution_candidates(entry_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """
    收集 RCSB `rcsb_entry_info.resolution_combined` 分辨率候选。

    输入参数:
        - entry_metadata: dict[str, Any], RCSB entry metadata

    输出:
        - candidates: list[dict[str, Any]], 每项含 source/value/units/method/path
    """
    values = _as_list(
        entry_metadata.get("rcsb_entry_info", {}).get("resolution_combined", [])
    )
    candidates: list[dict[str, Any]] = []
    for idx, raw_value in enumerate(values):
        value = _to_float(raw_value)
        if value is None:
            continue
        candidates.append(
            {
                "source": "rcsb.resolution_combined",
                "value": value,
                "units": "A",
                "method": None,
                "path": f"rcsb_entry_info.resolution_combined[{idx}]",
            }
        )
    return candidates


def _resolution_value_and_units(resolution: Any) -> tuple[float | None, str | None]:
    """
    解析 EMDB resolution 字段中的数值和单位。

    输入参数:
        - resolution: Any, `final_reconstruction.resolution` 字段

    输出:
        - result: tuple[float | None, str | None], 分辨率数值与单位
    """
    if isinstance(resolution, dict):
        return _to_float(resolution.get("valueOf_")), resolution.get("units")
    return _to_float(resolution), None


def _as_list(value: Any) -> list[Any]:
    """
    将可能为单对象或列表的 metadata 字段统一为列表。

    输入参数:
        - value: Any, metadata 字段值

    输出:
        - values: list[Any], 列表形式字段值
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_float(value: Any) -> float | None:
    """
    将 metadata 数值字段转为 float。

    输入参数:
        - value: Any, 可能为 int、float 或字符串

    输出:
        - result: float 或 None, 无法解析时为 None
    """
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _unique_resolution_values(candidates: list[dict[str, Any]]) -> list[float]:
    """
    返回分辨率候选中的唯一数值。

    输入参数:
        - candidates: list[dict[str, Any]], 分辨率候选列表

    输出:
        - values: list[float], 按首次出现顺序去重后的数值
    """
    values: list[float] = []
    for candidate in candidates:
        value = candidate["value"]
        if not any(abs(value - seen) < 1e-6 for seen in values):
            values.append(value)
    return values


def _rcsb_disagrees(selected: float, rcsb_candidates: list[dict[str, Any]]) -> bool:
    """
    判断是否存在与最终选择值不同的 RCSB 候选。

    输入参数:
        - selected: float, 最终选择的分辨率
        - rcsb_candidates: list[dict[str, Any]], RCSB 候选列表

    输出:
        - disagrees: bool, 存在不同 RCSB 值时为 True
    """
    return any(abs(candidate["value"] - selected) >= 1e-6 for candidate in rcsb_candidates)


def build_resolution_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    汇总 pair_list 中 `resolution_info` 的状态分布。

    输入参数:
        - records: list[dict[str, Any]], Stage A 输出记录

    输出:
        - summary: dict[str, Any], 包含总数、状态计数和少量示例
    """
    status_keys = [
        "single_unique",
        "multi_candidate_consistent",
        "ambiguous_emdb",
        "fallback_rcsb",
        "rcsb_disagree",
        "missing",
    ]
    summary: dict[str, Any] = {
        "total_records": len(records),
        **{key: 0 for key in status_keys},
        "emdb_metadata_error": 0,
        "examples": {
            "ambiguous_emdb": [],
            "rcsb_disagree": [],
            "missing": [],
            "emdb_metadata_error": [],
        },
    }
    for record in records:
        info = record.get("resolution_info", {})
        status = info.get("status", "missing")
        if status in summary:
            summary[status] += 1
        if info.get("rcsb_disagree") and status != "rcsb_disagree":
            summary["rcsb_disagree"] += 1
        if info.get("emdb_metadata_error"):
            summary["emdb_metadata_error"] += 1
            if len(summary["examples"]["emdb_metadata_error"]) < 10:
                summary["examples"]["emdb_metadata_error"].append(
                    _resolution_example(record)
                )
        if status in summary["examples"] and len(summary["examples"][status]) < 10:
            summary["examples"][status].append(_resolution_example(record))
        elif info.get("rcsb_disagree") and len(summary["examples"]["rcsb_disagree"]) < 10:
            summary["examples"]["rcsb_disagree"].append(_resolution_example(record))
    return summary


def _resolution_example(record: dict[str, Any]) -> dict[str, Any]:
    """
    构造用于人工审查 resolution 的短示例。

    输入参数:
        - record: dict[str, Any], pair_list 单条记录

    输出:
        - example: dict[str, Any], 包含 pdb_id、emdb_id、selected、status 和 values
    """
    info = record.get("resolution_info", {})
    values = [item["value"] for item in info.get("candidates", [])]
    return {
        "pdb_id": record.get("pdb_id"),
        "emdb_id": record.get("emdb_id"),
        "selected": info.get("selected"),
        "status": info.get("status"),
        "values": values,
    }


def format_resolution_summary(summary: dict[str, Any]) -> str:
    """
    将 resolution summary 格式化为终端摘要。

    输入参数:
        - summary: dict[str, Any], `build_resolution_summary` 返回值

    输出:
        - text: str, 多行终端文本
    """
    lines = [
        "Resolution summary:",
        f"  total_records: {summary['total_records']}",
        f"  single_unique: {summary['single_unique']}",
        f"  multi_candidate_consistent: {summary['multi_candidate_consistent']}",
        f"  ambiguous_emdb: {summary['ambiguous_emdb']}",
        f"  fallback_rcsb: {summary['fallback_rcsb']}",
        f"  rcsb_disagree: {summary['rcsb_disagree']}",
        f"  emdb_metadata_error: {summary['emdb_metadata_error']}",
        f"  missing: {summary['missing']}",
    ]
    return "\n".join(lines)


def build_pair_records(pdb_ids: Iterable[str], limit: int | None) -> list[dict[str, Any]]:
    """
    为 PDB id 列表构造 pair_list 记录。

    输入参数:
        - pdb_ids: Iterable[str], PDB id 序列
        - limit: int 或 None, 最多输出记录数; None 表示不截断

    输出:
        - records: list[dict[str, Any]], 每项含 emdb_id、pdb_id、resolution 和 resolution_info
    """
    records: list[dict[str, Any]] = []
    for pdb_id in pdb_ids:
        entry_meta = fetch_entry_metadata(pdb_id)
        emdb_id = choose_emdb_id(pdb_id, entry_meta)
        emdb_metadata_error = None
        try:
            emdb_meta = fetch_emdb_metadata(emdb_id)
        except requests.RequestException as exc:
            emdb_meta = {}
            emdb_metadata_error = f"{type(exc).__name__}: {exc}"
        resolution_info = extract_resolution_info(entry_meta, emdb_meta)
        if emdb_metadata_error is not None:
            resolution_info["emdb_metadata_error"] = emdb_metadata_error
        records.append(
            {
                "emdb_id": emdb_id,
                "pdb_id": pdb_id.lower(),
                "resolution": resolution_info["selected"],
                "resolution_info": resolution_info,
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
        - url: str, 官方 FTP/HTTPS map.gz URL
    """
    emdb_num = emdb_id.upper().replace("EMD-", "")
    return EMDB_MAP_URL.format(emdb_num=emdb_num)
