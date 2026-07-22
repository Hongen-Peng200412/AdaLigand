# UCSF Chimera 密度与 CC 命令的构造、执行和解析。
# 主要输入：标准化 mmCIF、MRC/map 文件、Chimera 命令参数与工作目录。
# 主要输出：Chimera 生成的模拟图、模型/地图几何信息、CC 数值与 stdout/stderr 证据。
# 关键边界：AdaLigand 负责命令、路径、退出码和输出验证；科学数值由 Chimera 计算。
"""Classic UCSF Chimera 的窄接口与可审计外部进程执行器。"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from adaligand_preprocessing.artifacts.failures import ExternalToolError, ToolFailureCode
from adaligand_preprocessing.artifacts.validation import cc_value_errors


_FATAL_LOG_PATTERNS = (
    re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE),
    re.compile(r"No such file", re.IGNORECASE),
    re.compile(r"open failed", re.IGNORECASE),
    re.compile(r"No atoms", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*(?:ERROR|Error)(?::|\s)", re.MULTILINE),
)
_BENIGN_MONITOR_TRIGGER_PATTERN = re.compile(
    r'^\s*Error processing trigger "monitor changes":\s*\r?\n'
    r"\s*KeyError: ['\"]\?['\"]\s*(?=\r?\n|$)",
    re.MULTILINE,
)
_NUMBER_PATTERN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


@dataclass(frozen=True)
class ToolRunResult:
    """一次无 shell 外部进程的可序列化执行摘要。"""

    argv: tuple[str, ...]
    returncode: int
    elapsed_seconds: float
    stdout_path: Path
    stderr_path: Path


def run_external_tool(
    argv: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
) -> ToolRunResult:
    """
    以参数列表、独立进程组运行外部工具，并统一检查超时、返回码和致命日志。

    不使用 ``shell=True``。超时时终止整个进程组，因为 MapQ CLI 内部还会启动 Chimera 子进程。
    """
    if not argv or not np_is_positive_finite(timeout_seconds):
        raise ExternalToolError(ToolFailureCode.CONFIG_INVALID, "invalid argv or timeout")
    cwd.mkdir(parents=True, exist_ok=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    popen_kwargs: dict = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "shell": False,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    started = time.monotonic()
    try:
        with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout_handle, stderr_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as stderr_handle:
            process = subprocess.Popen(
                argv,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                **popen_kwargs,
            )
            try:
                returncode = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _kill_process_group(process)
                process.wait()
                raise ExternalToolError(
                    ToolFailureCode.TIMEOUT,
                    f"external tool timed out after {timeout_seconds:.1f}s",
                ) from exc
    except ExternalToolError:
        raise
    except OSError as exc:
        raise ExternalToolError(ToolFailureCode.LAUNCH_FAILED, str(exc)) from exc

    elapsed = time.monotonic() - started
    result = ToolRunResult(
        argv=tuple(argv),
        returncode=returncode,
        elapsed_seconds=elapsed,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    if returncode != 0:
        raise ExternalToolError(
            ToolFailureCode.NONZERO_EXIT,
            f"external tool returned {returncode}; stdout={stdout_path}; stderr={stderr_path}",
        )
    combined_log = _read_logs(result)
    matched = _fatal_log_matches(combined_log)
    if matched:
        raise ExternalToolError(
            ToolFailureCode.FATAL_LOG,
            f"fatal external-tool log pattern {matched}; stdout={stdout_path}; stderr={stderr_path}",
        )
    return result


def _fatal_log_matches(log: str) -> list[str]:
    """
    返回外部工具日志中仍需阻断的致命模式。

    Classic Chimera 1.19 在处理部分金属配位 ``struct_conn`` 时，会在已经成功
    生成完整 MRC 后打印固定的 ``monitor changes``/``KeyError '?'`` 两行警告。
    这里只移除该精确序列；同一日志中的普通 ``Error``、Traceback、缺文件或
    无原子错误仍会继续触发 fail-fast，输出 artifact 也仍需后续完整 QC。

    输入参数:
        - log: str, 一次外部工具运行合并后的 stdout 与 stderr

    输出:
        - matched: list[str], 命中的致命正则表达式文本
    """
    actionable_log = _BENIGN_MONITOR_TRIGGER_PATTERN.sub("", log)
    return [
        pattern.pattern
        for pattern in _FATAL_LOG_PATTERNS
        if pattern.search(actionable_log)
    ]


class ChimeraRunner:
    """只公开 molmap-onGrid、四种 CC 和版本探测的 Classic Chimera 适配器。"""

    def __init__(self, command: list[str], *, timeout_seconds: float = 3600.0) -> None:
        if not command:
            raise ValueError("Chimera command cannot be empty")
        self.command = [str(item) for item in command]
        self.timeout_seconds = float(timeout_seconds)

    def probe(self, scratch_dir: Path) -> str:
        """运行 ``--version`` 并返回首个非空版本行。"""
        result = run_external_tool(
            [*self.command, "--version"],
            cwd=scratch_dir,
            stdout_path=scratch_dir / "probe.stdout.log",
            stderr_path=scratch_dir / "probe.stderr.log",
            timeout_seconds=min(self.timeout_seconds, 120.0),
        )
        lines = [line.strip() for line in _read_logs(result).splitlines() if line.strip()]
        if not lines:
            raise ExternalToolError(ToolFailureCode.OUTPUT_SCHEMA, "Chimera --version returned no text")
        return lines[0]

    def molmap_on_grid(
        self,
        model_cif: Path,
        canonical_mrc: Path,
        output_mrc: Path,
        *,
        resolution: float,
        scratch_dir: Path,
    ) -> ToolRunResult:
        """
        在 canonical map 的当前完整 step=1 网格上直接生成模拟密度。

        ``step 1`` 只表示使用每个现有网格点；1 Å 重采样必须已由 Stage E1 完成。
        """
        if not model_cif.is_file() or not canonical_mrc.is_file():
            raise ExternalToolError(ToolFailureCode.INPUT_CONTRACT, "molmap input file is missing")
        if not np_is_positive_finite(resolution):
            raise ExternalToolError(ToolFailureCode.INPUT_CONTRACT, "molmap resolution is invalid")
        scratch_dir.mkdir(parents=True, exist_ok=True)
        script_path = scratch_dir / "molmap.py"
        script_path.write_text(
            "\n".join(
                [
                    "from adaligand_preprocessing.external_tools.chimera import runCommand as rc",
                    f"rc('open {_chimera_open_path(model_cif)}')",
                    f"rc('open {_chimera_open_path(canonical_mrc)}')",
                    "rc('volume #1 region all step 1 limitVoxelCount false')",
                    f"rc('molmap #0 {float(resolution):.8g} onGrid #1 modelId #2 showDialog false')",
                    f"rc('volume #2 save {_chimera_quote(output_mrc)} saveStep 1 saveRegion all')",
                    "rc('stop now')",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        result = self._run_script(script_path, scratch_dir, "molmap")
        if not output_mrc.is_file() or output_mrc.stat().st_size == 0:
            raise ExternalToolError(
                ToolFailureCode.OUTPUT_MISSING,
                f"Chimera did not create non-empty simulated map: {output_mrc}",
            )
        return result

    def measure_correlations(
        self,
        experimental_mrc: Path,
        simulated_mrc: Path,
        *,
        contour: float | None,
        scratch_dir: Path,
    ) -> tuple[dict[str, float | None], ToolRunResult]:
        """
        以实验图为第一张图，测量 contour/nonzero mask 下普通与去均值 CC。

        四个原始量含义：
        - ``cc_contour``：实验图高于已映射到 canonical 幅值空间的 recommended contour 的相关系数；
        - ``cc_contour_about_mean``：同一 mask 内分别减两图均值后的相关系数；
        - ``cc_all``：Chimera ``aboveThreshold false``，即实验图非零 grid mask 上的相关系数；
        - ``cc_all_about_mean``：该非零 mask 内分别减均值后的相关系数。
        """
        if not experimental_mrc.is_file() or not simulated_mrc.is_file():
            raise ExternalToolError(ToolFailureCode.INPUT_CONTRACT, "correlation input file is missing")
        if contour is not None and not np_is_finite(contour):
            raise ExternalToolError(ToolFailureCode.INPUT_CONTRACT, "contour is non-finite")
        scratch_dir.mkdir(parents=True, exist_ok=True)
        script_path = scratch_dir / "correlation.py"
        commands = [
            "from adaligand_preprocessing.external_tools.chimera import runCommand as rc",
            "from adaligand_preprocessing.external_tools.chimera import openModels",
            "import FitMap",
            f"rc('open {_chimera_open_path(experimental_mrc)}')",
            f"rc('open {_chimera_open_path(simulated_mrc)}')",
            "rc('volume #0 region all step 1 limitVoxelCount false')",
            "rc('volume #1 region all step 1 limitVoxelCount false')",
            "experimental_map = openModels.list(id=0)[0]",
            "simulated_map = openModels.list(id=1)[0]",
        ]
        if contour is not None:
            commands.extend(
                [
                    # ``volume level`` 对 solid 表示要求额外 brightness 参数；直接设置
                    # surface_levels 才与 FitMap 的 aboveThreshold 读取契约一致。
                    (
                        "experimental_map.set_parameters("
                        f"surface_levels=[{float(contour):.9g}])"
                    ),
                    "print('ADALIGAND_CC_CONTOUR_BEGIN')",
                    (
                        "_, cc, cc_about_mean = FitMap.map_overlap_and_correlation("
                        "experimental_map, simulated_map, True)"
                    ),
                    (
                        "print('correlation = %.17g, correlation about mean = %.17g' "
                        "% (cc, cc_about_mean))"
                    ),
                    "print('ADALIGAND_CC_CONTOUR_END')",
                ]
            )
        commands.extend(
            [
                "print('ADALIGAND_CC_ALL_BEGIN')",
                (
                    "_, cc, cc_about_mean = FitMap.map_overlap_and_correlation("
                    "experimental_map, simulated_map, False)"
                ),
                (
                    "print('correlation = %.17g, correlation about mean = %.17g' "
                    "% (cc, cc_about_mean))"
                ),
                "print('ADALIGAND_CC_ALL_END')",
                "rc('stop now')",
                "",
            ]
        )
        script_path.write_text("\n".join(commands), encoding="utf-8", newline="\n")
        result = self._run_script(script_path, scratch_dir, "correlation")
        log = _read_logs(result)
        values: dict[str, float | None] = {
            "cc_contour": None,
            "cc_contour_about_mean": None,
            "cc_all": None,
            "cc_all_about_mean": None,
        }
        if contour is not None:
            normal, about_mean = _parse_correlation_section(log, "CONTOUR")
            values["cc_contour"] = normal
            values["cc_contour_about_mean"] = about_mean
        normal, about_mean = _parse_correlation_section(log, "ALL")
        values["cc_all"] = normal
        values["cc_all_about_mean"] = about_mean
        errors = cc_value_errors(values, contour_available=contour is not None)
        if errors:
            raise ExternalToolError(ToolFailureCode.CORRELATION_PARSE, str(errors))
        return values, result

    def _run_script(self, script_path: Path, scratch_dir: Path, stem: str) -> ToolRunResult:
        """用固定参数运行一个由适配器生成的 Chimera Python 脚本。"""
        return run_external_tool(
            [*self.command, "--nogui", "--silent", "--script", str(script_path)],
            cwd=scratch_dir,
            stdout_path=scratch_dir / f"{stem}.stdout.log",
            stderr_path=scratch_dir / f"{stem}.stderr.log",
            timeout_seconds=self.timeout_seconds,
        )


def _parse_correlation_section(log: str, section: str) -> tuple[float, float]:
    """在唯一 BEGIN/END marker 内解析恰好一对普通/去均值 correlation。"""
    begin = f"ADALIGAND_CC_{section}_BEGIN"
    end = f"ADALIGAND_CC_{section}_END"
    if log.count(begin) != 1 or log.count(end) != 1:
        raise ExternalToolError(
            ToolFailureCode.CORRELATION_PARSE,
            f"section {section} marker count is not exactly one",
        )
    start = log.index(begin) + len(begin)
    stop = log.index(end, start)
    body = log[start:stop]
    normal_matches = re.findall(rf"(?<!about mean )correlation\s*=\s*({_NUMBER_PATTERN})", body, re.I)
    mean_matches = re.findall(rf"correlation about mean\s*=\s*({_NUMBER_PATTERN})", body, re.I)
    if len(normal_matches) != 1 or len(mean_matches) != 1:
        raise ExternalToolError(
            ToolFailureCode.CORRELATION_PARSE,
            f"section {section} expected one correlation pair, got {normal_matches}/{mean_matches}",
        )
    return float(normal_matches[0]), float(mean_matches[0])


def _chimera_quote(path: Path) -> str:
    """为 Chimera command language 引用绝对 POSIX 风格路径。"""
    text = path.resolve().as_posix()
    if any(character in text for character in ('"', "\n", "\r")):
        raise ExternalToolError(ToolFailureCode.INPUT_CONTRACT, f"unsupported path: {text!r}")
    return f'"{text}"'


def _chimera_open_path(path: Path) -> str:
    """
    生成 classic Chimera ``open`` 命令可识别的绝对路径。

    classic Chimera 1.19 的 Midas ``doOpen`` 使用普通 ``str.split()``，不会移除
    shell 风格引号；给无空白路径加双引号反而会把引号当作文件名的一部分。正式
    服务器代码根和数据根均不含空白，因此这里显式拒绝空白路径并传裸路径。
    """
    text = path.resolve().as_posix()
    if any(character.isspace() for character in text) or any(
        character in text for character in ('"', "'", "\n", "\r")
    ):
        raise ExternalToolError(ToolFailureCode.INPUT_CONTRACT, f"unsupported Chimera open path: {text!r}")
    return text


def _read_logs(result: ToolRunResult) -> str:
    """读取一次工具运行的 stdout/stderr；日志本身保留在 scratch。"""
    return "\n".join(
        [
            result.stdout_path.read_text(encoding="utf-8", errors="replace"),
            result.stderr_path.read_text(encoding="utf-8", errors="replace"),
        ]
    )


def _kill_process_group(process: subprocess.Popen) -> None:
    """终止目标外部工具及其子进程。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)


def np_is_finite(value: float) -> bool:
    """避免给轻量外部工具层引入 NumPy，仅检查 Python float 有限性。"""
    return value == value and value not in (float("inf"), float("-inf"))


def np_is_positive_finite(value: float) -> bool:
    """检查正有限浮点参数。"""
    return np_is_finite(float(value)) and float(value) > 0
