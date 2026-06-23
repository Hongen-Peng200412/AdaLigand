"""AdaLigand 数据侧 Stage A–C（Ori_Data）的代码包。

把"枚举→下载→解析"三步共享的实现集中在本包：常量(constants)、文件 IO(io_utils)、
分片(parallel)、RCSB/EMDB 访问(rcsb)、下载(download)、CCD→LigandObject 物化(ligand_object)、
mmCIF 解析(parse)、失败/报告(reports)。脚本入口在同级 `scripts/`，由脚本把本目录加入 sys.path 后裸导入。
"""

