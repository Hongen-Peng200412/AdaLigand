# MapQ/Chimera 兼容必须绑定确定性上游写出行为

Type: gotcha
Date: 2026-07-17
Tags: AdaLigand, Stage F, MapQ, Chimera, deterministic serialization, identity validation

## Context

Stage F 的一次补算把 353 个样本记为 unknown。逐例审计证明它们全部属于固定外部工具的确定性写出语义与 AdaLigand 适配器预期不一致，而不是 CC、Q-score、坐标来源或样本科学有效性发生变化。对应实现修复为 Git commit `751c8b5`，并通过远端 369 项全套、8 样本 shadow smoke/replay、成功基线四 CC 零漂移和 7 样本 promotion。

## Memory

- MapQ 的坐标 writer 固定使用 `%.3f`。验证器必须比较同一三位小数序列化结果；不得要求输出恢复内部更高精度，也不得把该规则扩大为任意 epsilon 或最近邻匹配。
- `_atom_site.id` 只要求在同一个 occurrence 的投影内不重复。不同 occurrence 合法复用同一 id 时，仍须分别按各自 occurrence 的完整身份和坐标核验，不能使用全 PDB 全局唯一假设。
- MapQ 身份规范化保持严格，只接受可由固定 `ReadMol/WriteMol` 行为证明的两类变化：
  - `HETATM X/UNK/UNX` 的 `type_symbol` 写为 `LP`，其余身份字段不变；
  - 只有实际 author-residue-key 冲突时，component 才按首个冲突行的 author component 写出。
- 不得加入 PDB allowlist、任意 component 替换、模糊身份匹配或静默回退。
- classic Chimera 的 solid representation 不能用 Midas `volume ... level` 只传一个数值；contour 应通过 `experimental_map.set_parameters(surface_levels=[contour])` 设置。该接口修复不得改变 contour 数值、四种 CC 的 mask/去均值公式或 map 次序。
- 修改这些适配规则时，至少保留一个既有成功样本做新旧四 CC 零漂移对照，并为每种兼容类别保留真实失败代表；只有专项、全套、shadow smoke 和只读重放同时通过，才能用于正式重算。
- 运行级失败数量、run id、Job ID、try-lock 和 promotion 清单属于执行证据，不是长期科学契约；不要把它们写成未来样本的默认 allowlist。

## When To Use

修改或审查 `mapq.py`、`chimera.py`、`quality.py`、Stage F identity/coordinate validator、外部工具版本适配或真实 smoke 时使用。遇到大批同类 unknown 时，先按上游实际序列化和命令 API 聚类，不要先把样本降级为 known failure，也不要扩大容差。

## Related Files

- `Data_Preprocessing/Ori_Data/code/mapq.py`
- `Data_Preprocessing/Ori_Data/code/chimera.py`
- `Data_Preprocessing/Ori_Data/code/quality.py`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
