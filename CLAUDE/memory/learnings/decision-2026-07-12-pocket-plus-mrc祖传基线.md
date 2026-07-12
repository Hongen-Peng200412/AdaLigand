# Pocket Plus MRC 祖传基线与 AdaLigand 适配边界

日期：2026-07-12

## 决定

Pocket Plus `processedPDB_EMDB_binder/utils/mrc_tools.py` 是 AdaLigand 当前 MRC 加载和重采样的可信祖传基线。它已经过 Pocket Plus 的训练、验证和测试工作流；在用户无法重新人工核验数值实现的阶段，可审计的近零 diff 优先于 Agent 自行设计的替代算法。

AdaLigand 必须原样保存以下六个函数：`load_map`、`make_cubic`、`normalize_voxel_size`、`rescale_real`、`rescale_fourier`、`make_model_grid`。来源和逐函数哈希由 `Data_Preprocessing/Ori_Data/code/mrc_pocket_legacy.source.json` 冻结，任何函数源码或 AST 漂移都应使测试失败。

## 允许的薄适配

- `Path` 与祖传字符串路径之间转换。
- 显式透传祖传已有的 `multiply_global_origin`：native EMDB 使用 `True`；AdaLigand/Chimera 写出的 `nstart=0`、Å 级 header.origin 图使用 `False`。
- 返回值封装为 `MapGrid`，网格实体化，artifact dtype 统一为 float32，并做 shape/finite/positive 接口验收。
- `make_canonical_grid` 只校验正 target、调用祖传 `make_model_grid`、封装/转 dtype；不得重写 shape、padding、Fourier、origin 或 voxel 算法。
- AdaLigand 自有标准 MRC writer、schema/provenance、实际 voxel 跨图 QC。
- 全量 22,274-EMDB header 审计只确认 EMD-11978/12465 两张 mixed-axis 边界：薄层可复用祖传已返回的补偶 grid，以祖传 `rescale_real` 同一函数体把条件从 `np.all` 窄改为 `np.any`，仍直接调用祖传 `rescale_fourier`；vendored 六函数继续零修改，模式必须显式落盘。
- Pocket canonical grid 的幅值保持祖传行为；EMDB native recommended contour 另存 `native`、`prod(even_input)/prod(actual_output)` 比例和 `canonical` 三值，F 只消费 canonical 值，并把人类可读 provenance 与当前 E1 三值、mode、path/source 逐项绑定。

每一项差异都必须同时进入 ExecPlan、代码近端 README 和回归测试。无法证明必要性的差异不做。

## actual voxel 契约

正式 target 是 1.0 Å，但祖传函数为保持输入物理长度并选择偶数输出 shape，会返回由 `输入物理长度 / 输出 shape` 决定的实际 XYZ voxel。E1 必须同时保存 target 和实际 voxel；E2/E3/F 必须消费实际 voxel，不得硬编码三轴精确等于 1.0。exp/sim 仍必须同 shape、同实际 voxel、同 origin。

旧 AdaLigand 的独立 `scipy.signal.resample` 实现及 schema v1 不得复用。E1/E2/E3 schema v2 和 E1 identity 必须使旧产物失效。

## 重要纠正

早期 45 Å 偏差来自把人工构造的 Å 级非零 `header.origin` 当作 Pocket native-map 输入契约，不足以否定 Pocket Plus。真实服务器 EMDB map 的核验显示 Pocket 与 Ada 在实际输入契约下一致。后续 Agent 不得引用该早期 fixture 作为修改祖传函数的授权。

## 放行门

合成测试之外，Stage E 放行前必须用真实 Chimera `molmap onGrid` 输出验证非单位 voxel、非零 origin、`nstart=0`、header.origin Å 语义和 exp/sim 几何完全一致。若失败，只修薄适配并重新验收；不得改祖传六函数体。

本轮正式证据已完成：header audit `adaligand_mrc_contract_audit_20260712T192000_v2` 为 all_diff=21,941、all_equal=326、mixed=2、缺图=5（均为 B known failure）；真实 smoke `adaligand_mrc_geometry_smoke_20260712T200227` 对 7b14/7nll 两张 mixed 图使用 Chimera 1.19，两个 generated MRC 均为标准轴、`nstart=0`，canonical/sim shape、actual voxel、非零 origin 完全一致且三维 QC 零错误。本地与服务器 Python 3.10 均为 172 tests passed。完整哈希和服务器路径见 `文档/exec_plan/A-G数据流水线实现与全量运行.md` 与 `Data_Preprocessing/Ori_Data/code/readme.md`。
