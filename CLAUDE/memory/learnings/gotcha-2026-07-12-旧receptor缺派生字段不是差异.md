# 旧 receptor 缺派生字段表示无比较基线，不等于派生差异

Type: gotcha
Date: 2026-07-12
Tags: AdaLigand, Stage C, source repair, schema migration, atom_name

## Context

`csrc_v3` 的 2,156 联合 gate 出现 41 条 blocked。逐条汇总证明它们的原因集合完全一致：`receptor_base_changed:atom_name` 与 `receptor_derived_delta:old_receptor_incomplete`；没有 occurrence、ligand 坐标或其他 receptor base 漂移。

## Memory

- `bond_index/bond_type/feat` 在旧 receptor 中不存在时，没有派生比较基线；不能把“缺失”伪装成“比较后发生差异”。
- 若唯一 base 差异是 atom name，ligand-side 与其余 base 全部逐位一致，当前 cache-only 完整重建也通过，则仍可分类为 `atom_name_only`；apply 一次性补齐/替换三项派生数组。
- 若旧 receptor 已完整，必须继续执行 `feat` 全局不变与未改名子图 bond 不变门禁。
- 旧 schema 不完整不能豁免 occurrence/ligand 漂移、coords/element/residue/index 等其他 base 漂移或当前重建无效。
- 改变这类分类逻辑会改变 audit implementation hash；任何既有成功 staging/gate 都不能跨实现复用，必须换新 repair run id 从依赖证据开始重审。本轮由失败的 `csrc_v3` 切换到 `csrc_v4`。

## Related Files

- `Data_Preprocessing/Ori_Data/code/c_source_repair.py`
- `Data_Preprocessing/Ori_Data/tests/test_c_source_repair.py`
- `文档/规划文档/数据处理_v2.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
