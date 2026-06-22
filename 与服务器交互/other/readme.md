# AdaLigand 服务器交互工具箱

本目录记录 AdaLigand 项目的服务器交互工具与使用纪律。工具随项目走，密码、本机依赖和 VS Code 用户设置不随项目走。

## 当前映射

- 本地同步源：`C:\Users\15919\Desktop\AdaLigand\Data_Preprocessing\Ori_Data`
- 远端目录：`/storage/penghongen/AdaLigand/Ori_Data`
- 服务器：`penghongen@10.102.33.220:10022`
- Stage A-C 专用环境：`/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310`

## 同步入口

- `run_sync.bat` / `sync_code.ps1`：安全同步，只上传本地 `Ori_Data`，不删除远端目录。
- `run_syncWithClean.bat` / `sync_codeWithClean.ps1`：删除式同步，人类手动专用；agent 不擅自运行。

同步脚本会排除本地环境、缓存、测试输出和旧小样本产物：

```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
tests_output/
mini-example/
mini-example-20/
mini-example-reorg/
resolution-check-30/
adaligand_stage1.egg-info/
```

## sbatch 草案位置

当前简单版 Stage A/B 调度脚本位于：

```text
Data_Preprocessing/Ori_Data/code/sbatch/a.sbatch
Data_Preprocessing/Ori_Data/code/sbatch/bc.sbatch
```

约定：

- A：单任务，不使用 array。
- B：`--array=0-5`，每个 array task 申请 8 核，传给 joblib-loky 的 `--n_jobs` 为 7。
- 数据根目录：`/storage/penghongen/AdaLigand/Ori_Data`

## AI helper 使用纪律

`other\Invoke-PasswordSsh.ps1` 用于轻量远端命令、只读探测或把本地 LF 行尾的 bash 脚本通过 stdin 送给远端 `bash -s`。

注意：

- 不把密码写入项目文件。
- 不用 helper 跑正式数据处理、模型训练或重型推理。
- 远端写入默认只允许在用户明确授权的位置进行。
- `-InputFile` 传给远端 bash 时必须使用 LF 行尾。
