# 学习导航：功能分区=入口依赖的共享实现；生命周期=正式主路径基础设施。
# 主要输入：Stage A–C 脚本传入的路径、样本清单和运行配置。
# 主要输出：供 code/ 各模块裸导入的共享常量、IO、分片、访问与报告能力。
# 关键边界：本文件只建立包级导航，不承担样本科学计算或调度逻辑。
"""AdaLigand 数据侧 Stage A–C（Ori_Data）的代码包。

把"枚举→下载→解析"三步共享的实现集中在本包：常量(constants)、文件 IO(io_utils)、
分片(parallel)、RCSB/EMDB 访问(rcsb)、下载(download)、CCD→LigandObject 物化(ligand_object)、
mmCIF 解析(parse)、失败/报告(reports)。脚本入口在同级 `scripts/`，由脚本把本目录加入 sys.path 后裸导入。
"""
