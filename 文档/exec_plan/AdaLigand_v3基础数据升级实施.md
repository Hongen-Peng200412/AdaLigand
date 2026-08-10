# AdaLigand v3 基础数据升级实施记录

> 对应计划：`talk/AdaLigand_v3基础数据升级计划.md`
> 当前状态：首轮本地实现与隔离测试已完成；尚未同步服务器，也未运行正式数据。
> 本记录范围：`all_valid.json`、`info.json` 的一次性初始化，以及 `ligand_area.npz` 六个类别掩码升级。受体序列、残基映射、语言模型和后续清单维护脚本不在本轮实现范围内。

## 1. 已实现内容

一次性初始化文件位于 `Data_Preprocessing/Ori_Data_upgrade/tmp/`：

- `initialize_data_catalog.py` 从当前 split JSON 文件计算排序、去重后的 PDB 并集，写出 `all_valid.json`；
- 同一入口以 `raw/pair_list.jsonl` 中的全部唯一 PDB 为键，合并八类现有产物检查与可靠历史原因，写出 `info.json`；
- `initial_info_reasons.json` 保存本地证据能够逐 PDB 对应的历史原因；
- `initialize_data_catalog.sh` 通过 `训练与运行` 完整模式调用初始化入口；
- 初始化扫描前只把 `5y6p`、`7n6g`、`7z8g`、`9hhl`、`9v7i` 的 `receptor_tokens.npz` 改名为 `receptor_tokens_old.npz`。历史排除清单中的其他 11 个编号没有对应的源产物证据，因此没有扩大改名范围。

正式掩码升级文件位于 `Data_Preprocessing/Ori_Data_upgrade/`：

- `upgrade_ligand_area_masks.py` 按 `occurrences.jsonl::type_tag` 合并已有 `mask_{candidate_id}`，追加六个 `bool (1,Z,Y,X)` 掩码；
- 入口必须显式选择 `--sample-scope all_valid|all_existing`，本轮正式运行选择 `all_existing`；
- 六字段完整时跳过，六字段部分存在时打印 `partial_existing_masks` 并保持文件不变，六字段全部不存在时才原子替换文件；
- 单个 PDB 的异常只进入普通日志，不更新 `info.json`，也不阻止其他 PDB 继续处理；
- `upgrade_ligand_area_masks.sh` 通过 `训练与运行` 完整模式调用正式入口。

现有 E3 校验器 `Data_Preprocessing/Ori_Data/adaligand_preprocessing/stages/stage_e/ligand_area.py` 已做最小兼容修改：旧文件合法，六字段完整文件合法，部分字段存在时报契约错误。代码旁 `Data_Preprocessing/Ori_Data/README.md` 同步说明了六个可选字段。

## 2. 名单与历史问题边界

本地资料表明：

- `pair_list.jsonl` 有 22,386 个唯一 PDB；
- 当前 split 并集有 18,288 个 PDB；
- split 外共有 4,098 个 PDB；
- 本地可靠证据能够逐 PDB 对应 140 个 PDB 的 142 条历史问题；
- 剩余 3,958 个 split 外 PDB 只记录 `unknown_issue`。虽然历史汇总可分为 2,190 个几何不匹配和 1,768 个质量筛选失败，但本地没有可靠的逐 PDB 对应关系，因此没有猜测分类。

`info.json` 中是否存在问题不自动决定 PDB 是否进入 `all_valid.json`。

## 3. 本地验证

- 正式掩码入口通过 Python 静态编译和 shell 语法检查；
- 隔离 fixture 已覆盖新增六字段、类别重叠、旧字段保持、完整字段跳过、部分字段不改写和两种样本范围；
- E3 隔离测试已覆盖旧文件、六字段完整文件、部分字段和错误数据类型；
- A–G 原有 `test_density_stage_e.py` 在当前 Windows 环境收集时缺少 RDKit，未进入测试函数；这是本地依赖缺失，不是测试断言失败；
- 初始化入口的静态编译、历史原因数量检查和隔离端到端测试通过。

## 4. 尚未执行

- 没有访问、同步或修改服务器；
- 没有提交 Slurm 任务；
- 没有生成服务器上的 `all_valid.json`、`info.json` 或新版 `ligand_area.npz`；
- 没有实现后续维护 `info.json` 与只缩小 `all_valid.json` 的扫描器；
- 没有实现受体序列、残基映射、50 维原子特征或语言模型产物。

下一步由用户先运行一次性初始化并检查结果，再以 `all_existing` 运行掩码升级。掩码运行结束后只读汇总普通日志；只有用户验收后，后续维护扫描器才进入新的实现授权。
