# 学习导航：功能分区=数据契约与质量验证；生命周期=正式主路径失败语义基础设施。
# 主要输入：解析、工具、schema 和数据适用性错误。
# 主要输出：稳定的 known_failed/unknown_failed 代码、detail 与 gate 传播语义。
# 关键边界：known 只能表示科学上可解释且允许排除；程序缺陷和无法解释输出必须阻塞。
"""样本级已知失败与未知失败的集中分类。

已知失败只表示“输入数据在当前科学契约下不适用”，可以继续处理其他样本，但必须从最终
``keep_list`` 排除。程序缺陷、schema 漂移和无法解释的外部工具输出不应在这里兜底，仍作为
未知失败阻塞 release gate。
"""

from __future__ import annotations

from enum import Enum


class KnownFailureCode(str, Enum):
    """当前允许继续分片的稳定样本级失败码。"""

    NO_OCCURRENCES = "no_occurrences"
    NO_PRESENT_LIGAND_ATOMS = "no_present_ligand_atoms"
    NO_POCKET_RECEPTOR_ATOMS = "no_pocket_receptor_atoms"
    MISSING_MAP = "missing_map"
    MISSING_META = "missing_meta"
    MISSING_RESOLUTION = "missing_resolution"
    MODEL_MAP_FRAME_MISMATCH = "model_map_frame_mismatch"
    RUN_POLICY_EXCLUDED = "run_policy_excluded"


class KnownSampleFailure(RuntimeError):
    """携带稳定失败码的预期样本级异常。"""

    def __init__(self, code: KnownFailureCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ToolFailureCode(str, Enum):
    """外部工具适配层的稳定故障码；默认都属于 unknown failure。"""

    CONFIG_INVALID = "config_invalid"
    INPUT_CONTRACT = "input_contract"
    LAUNCH_FAILED = "launch_failed"
    TIMEOUT = "timeout"
    NONZERO_EXIT = "nonzero_exit"
    FATAL_LOG = "fatal_log"
    OUTPUT_MISSING = "output_missing"
    OUTPUT_SCHEMA = "output_schema"
    CORRELATION_PARSE = "correlation_parse"
    ATOM_MAPPING = "atom_mapping"
    GEOMETRY_QC = "geometry_qc"


class ExternalToolError(RuntimeError):
    """Chimera/MapQ 运行或输出契约失败；不得自动降级为已知样本失败。"""

    def __init__(self, code: ToolFailureCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
