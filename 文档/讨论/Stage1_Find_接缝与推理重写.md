# Stage1（Find）接缝与推理重写：转正指针

本讨论稿的已确认内容已经整理为当前正式计划：

- `文档/规划文档/Stage1训练与多阈值推理.md`

正式计划自包含地定义了 Stage1 基础训练、整图概率组装、micro-$F_\alpha$ 阈值标定、26-连通组件森林、候选谱系组（CLG）枚举、Group-parent 局部特征物化、Global Proposal 候选选择器、反链优化、可选 selected-final 精修，以及供 Stage1/Stage2/Stage3 共用的轻量密度 U-Net 调制接口。

盘上字段与 ragged 关系继续由 `文档/讨论/BOX-level数据契约.md` 维护。实现与计划的对应关系见 `文档/mapping/计划执行映射.md`。

本文件不再承载并行的设计正文，避免同一事实在讨论稿和正式计划之间漂移。
