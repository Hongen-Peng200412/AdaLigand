# Current source 新增 occurrence 可能首次引入 descriptor 依赖

Type: gotcha
Date: 2026-07-12
Tags: AdaLigand, Stage C, source rebuild, ligand descriptor, dependency supplement

## Context

本轮 14-PDB `CCD:5GP` 完整 C rebuild audit 在 CCD cache 已补齐后仍 14/14 fail-closed。原因不是迁移算法，而是当前 source 让 20 个旧 `resolve_failed` occurrence 首次成为合法项；旧正式 C 因从未消费这些 occurrence，没有物化 `ligand_descriptors/CCD_5GP.npz`。

## Memory

- full rebuild 的只读 staging 仍可能依赖此前从未物化的去重配体 descriptor；“LigandObject 已存在”不等于“descriptor 一定存在”。
- 不应在 rebuild audit 内隐式生成该文件。应在最终 audit 冻结前，用独立 run id 与冻结 object-key 清单显式补足，固定清单、源 LigandObject、实现和最终 descriptor 的 SHA-256。
- 补足必须调用既有 materializer 且 `overwrite=False`，随后重新验证 descriptor schema 与源对象哈希；成功证据复用时也要再次核对当前文件，不能仅凭 summary 存在早退。
- failed/partial evidence 不覆盖，换新 run id；本轮保留 `csrc_v2` 失败证据，正式恢复使用 `csrc_v3`。
- 该补足只满足既有 Stage C descriptor 契约，不授予额外 source migration、不改变 occurrence 科学语义，也不把 run-scoped manifest 提升为长期契约。

## Related Files

- `Data_Preprocessing/Ori_Data/code/c_descriptor_prefetch.py`
- `Data_Preprocessing/Ori_Data/scripts/c_descriptor_prefetch.py`
- `Data_Preprocessing/Ori_Data/code/c_source_rebuild.py`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
