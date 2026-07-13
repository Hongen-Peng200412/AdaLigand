# Model-map 坐标帧完全分离作为稳定已知失败

Type: decision
Date: 2026-07-13
Tags: stage-e, stage-f, world-coordinates, known-failure, qc

## Context

权威 mmCIF 模型与 EMDB map 通常共享世界坐标帧，但不能把这一点当成无条件假设。正式 Stage E 发现过合法模型与合法 map 的 XYZ 包围盒完全分离，且 source 没有提供可证实的坐标变换。

## Memory

E/F 共用同一个确定性 preflight。map 边界为：

    map_lower_xyz = origin_xyz
    map_upper_xyz = origin_xyz + (shape_zyx[::-1] - 1) * voxel_size_xyz

受体边界是 Stage C polymer receptor token 坐标 `receptor_tokens.coords` 的 XYZ 逐轴最小/最大值。它是 E/F 共用 frame anchor，不等同于 E2 严格 ATOM-only Chimera 模型或 F 完整 ATOM+HETATM 模型。只有 map 与受体输入合法、有限、非空，且任一轴在 `1e-5 Å` 容差后仍完全分离时，才记 `known_failed:model_map_frame_mismatch`。E 在生成/reuse receptor-only sim 前检查，F 在质量产物 reuse 或 Chimera/MapQ 前检查。

该策略不包含 PDB allowlist、猜测平移、`fitmap` 或坐标改写。空坐标、NaN/Inf、错 dtype/shape/voxel/origin、密度全零、外部工具失败或其他几何不一致仍是 unknown failure，不得借此降级。run-scoped detail 应保存 map/model 包围盒、XYZ/ZYX 轴序、容差和 `no_transform_or_fitmap` 策略。G 排除该样本，但它不阻断其他样本。

## When To Use

- 新增或审查 Stage E/F model-map 几何检查时。
- 遇到模型落在 map 世界边界之外、但 source 无权威变换时。
- 审查 known failure 是否被过度使用、从而掩盖工程或数值错误时。

## Related Files

- `Data_Preprocessing/Ori_Data/code/failures.py`
- `Data_Preprocessing/Ori_Data/code/qc.py`
- `Data_Preprocessing/Ori_Data/code/density.py`
- `Data_Preprocessing/Ori_Data/code/quality.py`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `文档/规划文档/数据处理_v2.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
