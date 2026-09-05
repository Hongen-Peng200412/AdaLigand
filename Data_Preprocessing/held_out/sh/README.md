# Held-out 正式任务脚本

本目录只保存 `Data_Preprocessing/held_out` 数据链的五个 Slurm 任务脚本。提交时通过项目根的 `训练与运行/submit_task.sh` 传入当前脚本的项目相对路径；完整命令、输入、输出和科学契约见 [held-out 去冗余说明](../README.md)。

## 组织与阅读顺序

1. `held_out_catalog_array.sh`：并行解析 12 个 mmCIF 序列目录分片。
2. `held_out_catalog_finalize.sh`：合并序列目录、生成 FASTA，并执行 RCSB 官方 FASTA 抽样对照。
3. `held_out_mmseqs_array.sh`：并行运行 12 个 protein 与 nucleic MMseqs2 检索分片。
4. `held_out_finalize.sh`：合并 MMseqs2 结果并生成与 split 参数无关的共享 PDB 边证据。
5. `held_out_split_array.sh`：并行生成 `0.5/0.6 × chain/residue/or/and` 八组测试集。

五个脚本都是 `held_out_pipeline.cli` 的薄入口，不会自动串联前后步骤。脚本内的输出根、分片数、coverage 参数和随机种子与 [父目录 README](../README.md) 中的当前运行契约一致。
