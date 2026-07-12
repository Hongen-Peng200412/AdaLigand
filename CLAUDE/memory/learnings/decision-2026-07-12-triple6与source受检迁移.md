# Triple=6 与当前 source 的受检迁移

Type: decision
Date: 2026-07-12
Tags: AdaLigand, Stage C, receptor, triple, source-dirty, migration

## Context

全量 run 的 ABC gate 暴露 7 个合法 receptor `TRIPLE` 键和 23 个当前 mmCIF 与旧 C 只在 `atom_name` 上不一致的样本。用户明确接受两项数据契约：追加三键编码，并接受当前 RCSB mmCIF，但必须严格审计后再迁移。

## Memory

- receptor `bond_type` 保持 `single=0,double=1,aromatic=2,backbone=3,disulfide=4,covale=5` 不变，只向后兼容追加 `triple=6`；其他未声明键型仍 fail-fast。
- “接受当前 source”不等于允许覆盖旧 C。先冻结 dirty IDs、数量和 SHA；全集合必须为 `exact/atom_name_only` 且零 blocked/failed 才能 apply。
- `atom_name_only` 只允许更新 `receptor_tokens.npz` 的 `atom_name/bond_index/bond_type/feat`；六个其余受体基础数组、occurrences、ligand_coords 与额外 provenance key 必须不变。
- `exact` 若旧 receptor 已是完整新 schema，还必须证明 `bond_index/bond_type/feat` 与当前 source 重建逐位一致；不能只看七个基础数组后保留陈旧派生键图。
- audit 冻结 mmCIF、旧 receptor、occurrences、ligand_coords、单样本 report、LigandObject/CCD cache 依赖闭包及 repair Python 实现；当前 atom name、CCD cache 身份和元素必须完整一致。
- 正式 run 的 C 状态只由无过滤全量 C 刷新；filtered smoke/repair 必须使用独立 run id。

## When To Use

恢复 Stage C、解释 bond_type 取值、处理未来 RCSB source revision 或判断能否迁移旧 C 时使用。不得把本决策简化成“当前 mmCIF 可无条件覆盖”。

## Related Files

- `文档/规划文档/数据处理_v2.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/c_source_repair.py`
- `Data_Preprocessing/Ori_Data/code/receptor.py`
- `Data_Preprocessing/Ori_Data/code/readme.md`
