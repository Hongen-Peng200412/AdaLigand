# Source 更新可能在坐标不变时重排 candidate_id

Type: gotcha
Date: 2026-07-12
Tags: AdaLigand, Stage C, source revision, candidate_id, occurrence

## Context

对 2,156 个刷新 mmCIF 做全集 audit 时，14 个 PDB 的 `CCD:5GP` 从旧 `resolve_failed` 变为当前可解析。当前 source 新增 20 个 occurrence、删除 0 个；所有匹配 occurrence 的 `coords/present` 均逐位不变，但 mmCIF atom serial 排序变化使 1,995 个既有 occurrence 的 `candidate_id` 改变。

## Memory

- `candidate_id` 是 PDB 内按当前 source 排序派生的局部身份，不是跨 source revision 永久不变的 accession。
- 即使 object/component 身份和坐标完全不变，atom serial 或候选排序变化也会重排 candidate_id。
- source migration audit 不能只比较 object_key 集或坐标；必须显式报告新增/删除 occurrence、candidate_id 迁移映射和下游是否已生成。
- 本轮 D–G 和任何下游训练尚未启动，所以迁移成本最低。用户已对冻结的 14-PDB 集合单独授权完整 C 重建；这不构成未来 source revision 的自动迁移许可。
- before/after 主键 manifest 只应保存在对应 repair run 的诊断目录，不能被提升为 Stage C 主产物、训练字段或跨 source 稳定身份。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/parse.py`
- `Data_Preprocessing/Ori_Data/code/c_source_repair.py`
- `Data_Preprocessing/Ori_Data/code/c_source_rebuild.py`
