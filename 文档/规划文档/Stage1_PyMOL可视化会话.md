# Stage1 PyMOL 可视化会话

## 文档责任

本规格负责定义单个 PDB 的 Stage1 PyMOL 会话内容、输入寻址、坐标契约和验收边界。具体命令、对象名称和使用方法由 `可视化套件/Stage1/README.md` 说明；实施、服务器运行和验收证据由 `文档/exec_plan/Stage1_PyMOL可视化实施.md` 记录。本规格不改写 AdaLigand 数据契约或 Pocket Plus Stage1 推理契约。

## 目标

从 AdaLigand 数据与 Pocket Plus Stage1 推理产物生成一个自包含 `.pse`，使用者可在 PyMOL 中独立显示或隐藏实验密度、受体、任意 GT 配体实例和任意预测 blob。同一入口通过公共 Stage1 `blobs` 与 `evaluation` 产物适用于 `unet_c1` 和 `Find_*`。

## 冻结范围

- 密度层只包含完整实验密度 map 和由 `contour_canonical` 创建的 mesh。map 必须保留在会话中，以支持 `isolevel` 和围绕任意原子选区重建局部 mesh。
- 受体是一个独立分子对象，使用 `receptor_tokens.npz` 的原子、元素和化学键。因源产物不含作者编号，受体对象显式使用稳定的合成链号和残基号。
- 每个 GT ligand occurrence 是一个独立分子对象，使用沉积坐标、元素和化学键；不加载 GT 体素掩码。
- 每个 evaluation 候选是一个独立预测对象。所有候选均写入会话，只有 `candidate_selected=true` 的对象默认显示。预测对象以体素中心伪原子表示，不声称化学结构。
- 生成器只依赖输入文件的共同字段，不根据 producer 名称加入模型白名单或分支。
- 首版不加载 `sim`、`diff` 或 `posdiff`，但 `density` 组保留可增加命名密度层的结构。

## 坐标与对象契约

密度数组的轴顺序为 ZYX，PyMOL Brick 的轴顺序为 XYZ。AdaLigand `origin` 是体素边界下角，因此 Brick 的首个采样点与体素中心坐标均使用 `origin + 0.5 * voxel_size`。预测的全图 ZYX 索引先换轴为 XYZ，再与同一体素中心原点和体素尺寸换算。受体与 GT 已是世界 XYZ 坐标，不再旋转、缩放或平移。

会话顶层组为 `stage1`，其下保留 `density`、`receptor`、`ground_truth` 和 `predictions`。`ground_truth` 下每个 occurrence 可独立切换；`predictions` 下再按默认入选状态分组，每个 blob 仍可独立切换。

## 验收条件

1. 合成数据单元测试检查分组、默认可见性、受体坐标、GT 坐标、预测体素中心坐标、`isolevel` 和局部 `isomesh`。
2. 服务器独立 PyMOL Conda 环境用真实 `unet_c1` 产物生成一个 `.pse`，并保留正式 release、launch 和运行命令。
3. 同一个服务器环境用具备当前公共 blobs 与 evaluation 契约的真实 `Find_*` 产物生成一个 `.pse`，以证明入口未与 `unet_c1` 路径耦合。若服务器现有 `Find_*` 只保留旧版 `centered/components/probability` 文件，该验收等待相应模型生成公共契约产物，不在可视化层追加第二套旧版解析公式。
4. 服务器会话下载到 Windows 后，本机 PyMOL 能直接打开，且输入树不需随会话一起下载。

## 非目标

本轮不实现批量会话管理、PyMOL GUI 插件、配体身份解码、预测 blob 原子化、新的候选筛选规则，也不在密度缺失时自动切换到模拟密度。
