# Stage E3 体素中心必须直接复用 Pocket Plus 祖传实现

日期：2026-07-16

## 用户冻结的信任边界

Pocket Plus 已经过训练、验证与测试，其祖传数值实现是当前项目的权威基线。只要 Pocket Plus 已经提供相应实现，AdaLigand 就不得由 Agent 另写一个“看起来等价”或“更稳健”的替代算法；有疑问时应先删除自研替代，直接 vendoring 原函数，再用很薄、可枚举、可测试的接口适配连接 Ada 数据契约。

这一规则既适用于已经冻结的 MRC 六函数，也适用于 Stage E3 使用的体素中心构造。不得把 Ada 自有的稀疏存储、occurrence 身份或逐元素半径差异误写成对 Pocket 数值几何的修改授权。

## 当前实现决定

- `Data_Preprocessing/Ori_Data/code/mrc.py` 继续只调用零差异 vendoring 的 Pocket `load_map` 与 `make_model_grid`；本次 E3 修复没有改动这两个函数。
- `Data_Preprocessing/Ori_Data/code/voxel_gt_pocket_legacy.py` 原样 vendoring Pocket Plus `_build_voxel_center_coords_xyz`，来源与源码/AST 哈希记录在同目录 `voxel_gt_pocket_legacy.source.json`。
- E3 的世界坐标体素中心直接由上述祖传函数产生，语义为网格下角点 `origin` 与 `origin_xyz + (index_xyz + 0.5) * voxel_size_xyz`。
- AdaLigand 只在祖传中心坐标之上做稀疏索引选择；不得重新推导、近似或另写中心公式。稀疏结果必须用祖传完整网格作为 oracle 做逐元素回归。
- 不能机械复制 Pocket 最终标签函数中与本项目科学契约不同的部分：Pocket 的统一半径、严格小于、类别过滤和 first-writer-wins 实例标签不替代 Ada 已冻结的逐元素范德华半径、独立 occurrence mask、重叠允许、排序稀疏坐标与 union mask。任何此类差异必须被明确列出，不能隐藏在“兼容”代码里。

## 可审计证据

- Git checkpoint：`75d8f42 fix(stage-e3): align ligand masks with Pocket voxel centers`。
- vendored 函数源码与 Pocket 祖先逐字节/AST 对照测试已加入；LF 行尾由 `.gitattributes` 固定。
- 300 组随机各向异性、非零及极大 origin 的完整 Pocket 网格 oracle 对照为零差异。
- 本地专项测试与全套测试通过；截至该 checkpoint，全套为 `309 passed, 10 skipped`，跳过项均为 Windows 平台条件项。

## 后续 Agent 的操作纪律

1. 先查 Pocket Plus 是否已有实现，再决定是否写代码。
2. 已有祖传实现时，默认原样 vendoring；薄适配必须逐条写入 ExecPlan、README、mapping 和测试。
3. 不得用合成极端输入的现象评价或改写祖传算法；测试的作用是确认 Ada 适配没有偏离祖传结果。
4. 若真实 Pocket 端到端对照出现差异，先区分“几何中心漂移”和“双方已冻结的标签科学契约差异”；前者阻断放行，后者完整报告并按用户授权处理。
5. 在用户不能亲自复核代码时，可阅读的近零 diff 与来源哈希优先于 Agent 自行设计的实现。
6. 对祖传实现本身的疑点，至少分别独立审计上下游衔接、祖传方法本身和修复前后产物差异。小瑕疵只记录，不得借机重写；若证据显示可能是广泛硬伤，也只能先冻结影响清单并报告用户，取得明确批准前不得修改祖传函数或生产适配。
