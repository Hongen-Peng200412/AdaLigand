# 冻结 14-PDB 完整 C 重建与额外资源授权

Type: decision
Date: 2026-07-12
Tags: AdaLigand, Stage C, source migration, audit, resource discipline

## Context

首轮 2,156-source audit 发现 14 个 `CCD:5GP` PDB 因当前 RCSB source 命名修订新增 20 个此前 `resolve_failed` 的 occurrence；删除 0 个，1,995 个既有 occurrence 的 `candidate_id` 因排序变化而重排，匹配项 `coords/present` 逐位不变。D–G 和下游训练尚未启动。

## Memory

- 用户授权仅对本轮冻结的 14-PDB ID 文件及其 SHA 执行完整 Stage C 重建，接受上述 20/0/1,995 迁移。
- before/after 主键 manifest 仅是本次 repair run 的阶段性审计证据，不是科学契约、Stage C 主产物、训练字段、stable occurrence id 或未来自动 rebuild 许可。
- 通用 source repair 仍只接受 `exact/atom_name_only`；14-PDB 走独立 audit/prepare、联合 2,156 零阻断 gate 和可恢复四件套事务。
- 当前 source 新增的 5GP occurrence 首次需要 `CCD:5GP` descriptor；可在最终 audit 前用冻结 object-key 清单从既有 LigandObject 以 `overwrite=False` 显式补足，并记录源/实现/产物哈希。这是依赖补足，不改变 descriptor schema、occurrence 科学语义或本次迁移授权。
- 用户将可用 CPU 从既有 96 核扩充为最多并行 96+48 核。额外 48 核只能用于独立测试、只读审计或最终 audit 冻结前的依赖补足；316114 的 96 核 allocation 是唯一正式 Stage C 写入者。

## When To Use

当恢复 `adaligand_ag_20260711T154658`、解释本轮 candidate 主键迁移、调度补充审计资源，或判断未来 source 漂移是否可自动接受时使用。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/c_source_rebuild.py`
- `Data_Preprocessing/Ori_Data/code/c_descriptor_prefetch.py`
- `Data_Preprocessing/Ori_Data/scripts/c_source_rebuild.py`
- `与服务器交互/other/readme.md`
