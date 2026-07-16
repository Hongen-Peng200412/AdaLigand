# 学习导航：功能分区=外部工具与格式适配；生命周期=正式主路径 Stage F 工具适配。
# 主要输入：标准化 mmCIF、实验/模拟 MRC、sigma=0.4、np=8 与 atom_site 映射。
# 主要输出：MapQ 原子 Q-score、工具日志和严格 atom_site.id 对齐后的 occurrence 数组。
# 关键边界：MapQ 计算数值；AdaLigand 负责命令、身份 join、缺失/重复 ID 与 provenance 校验。
"""MapQ 2.9.7 的固定参数命令适配器与严格 atom_site.id 输出校验。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gemmi
import numpy as np

from chimera import ToolRunResult, run_external_tool
from failures import ExternalToolError, ToolFailureCode
from parse import category_rows, clean_value


MAPQ_PACKAGE_NAME = "mapq_v2.9.7.zip"
MAPQ_COMMIT = "c3bdf305677f5f9fc4b69aa404b834d9d3a75937"
MAPQ_ZIP_SHA256 = "ee004e19f0ca2bf1f439365d64b8463d2e8bd18c8827c28e9b2ccfe3a538fe55"
MAPQ_SIGMA = 0.4
MAPQ_NP = 8
MAPQ_CIF_OPENMODELS_PATCH = "mapq_cmd_cif_readmol_openmodels_v1"
_IDENTITY_FIELDS = (
    "group_PDB",
    "type_symbol",
    "label_atom_id",
    "label_alt_id",
    "label_comp_id",
    "label_asym_id",
    "label_entity_id",
    "label_seq_id",
    "pdbx_PDB_ins_code",
    "auth_atom_id",
    "auth_comp_id",
    "auth_asym_id",
    "auth_seq_id",
    "pdbx_PDB_model_num",
)
_COORD_FIELDS = ("Cartn_x", "Cartn_y", "Cartn_z")


@dataclass(frozen=True)
class MapQRunResult:
    """一次 MapQ 成功运行的逐 atom_site.id Q 值与 provenance。"""

    q_by_atom_site_id: dict[str, float]
    tool_result: ToolRunResult
    output_cif: Path
    cli_banner: str
    compatibility_cli: Path
    adapter_patch: str


class MapQRunner:
    """固定 sigma=0.4、np=8 的 MapQ 命令行适配器。"""

    def __init__(
        self,
        python_command: list[str],
        mapq_cmd_path: Path,
        chimera_root: Path,
        *,
        timeout_seconds: float = 7200.0,
    ) -> None:
        if not python_command:
            raise ValueError("python_command cannot be empty")
        self.python_command = [str(item) for item in python_command]
        self.mapq_cmd_path = mapq_cmd_path
        self.chimera_root = chimera_root
        self.timeout_seconds = float(timeout_seconds)

    def run(
        self,
        native_mrc: Path,
        normalized_full_cif: Path,
        *,
        resolution: float,
        scratch_dir: Path,
    ) -> MapQRunResult:
        """
        在 fresh per-PDB scratch 中运行 MapQ，并验证输出身份集合和逐原子 Q。

        MapQ CLI 即使参数错误也可能返回 0，且内部 ``os.system`` 不传播 Chimera 返回码；
        因此返回码之后仍强制检查预期文件、``_atom_site.Q-score``、id 集合和完整身份。
        """
        if not self.mapq_cmd_path.is_file() or not self.chimera_root.is_dir():
            raise ExternalToolError(ToolFailureCode.CONFIG_INVALID, "MapQ/Chimera path is invalid")
        if not native_mrc.is_file() or not normalized_full_cif.is_file():
            raise ExternalToolError(ToolFailureCode.INPUT_CONTRACT, "MapQ input is missing")
        if not np.isfinite(resolution) or resolution <= 0:
            raise ExternalToolError(ToolFailureCode.INPUT_CONTRACT, "MapQ resolution is invalid")
        if native_mrc.parent.resolve() != scratch_dir.resolve():
            raise ExternalToolError(
                ToolFailureCode.INPUT_CONTRACT,
                "native map must live in fresh scratch because MapQ writes _mapqScript.py beside it",
            )
        scratch_dir.mkdir(parents=True, exist_ok=True)
        # 上游 CLI 会按 basename 识别并跳过 argv[0]；副本必须仍名为 mapq_cmd.py。
        compatibility_cli = scratch_dir / "mapq_compat" / "mapq_cmd.py"
        _write_mapq_compatibility_cli(self.mapq_cmd_path, compatibility_cli)
        argv = [
            *self.python_command,
            str(compatibility_cli),
            str(self.chimera_root),
            f"map={native_mrc}",
            f"cif={normalized_full_cif}",
            f"sigma={MAPQ_SIGMA}",
            f"res={float(resolution):.8g}",
            f"np={MAPQ_NP}",
        ]
        tool_result = run_external_tool(
            argv,
            cwd=scratch_dir,
            stdout_path=scratch_dir / "mapq.stdout.log",
            stderr_path=scratch_dir / "mapq.stderr.log",
            timeout_seconds=self.timeout_seconds,
        )
        output_cif = Path(f"{normalized_full_cif}__Q__{native_mrc.name}.cif")
        if not output_cif.is_file() or output_cif.stat().st_size == 0:
            raise ExternalToolError(
                ToolFailureCode.OUTPUT_MISSING,
                f"MapQ returned 0 but expected output is missing: {output_cif}",
            )
        q_by_id = parse_mapq_output(normalized_full_cif, output_cif)
        combined_log = "\n".join(
            [
                tool_result.stdout_path.read_text(encoding="utf-8", errors="replace"),
                tool_result.stderr_path.read_text(encoding="utf-8", errors="replace"),
            ]
        )
        banner = next(
            (line.strip() for line in combined_log.splitlines() if "mapq" in line.lower()),
            "not_reported",
        )
        return MapQRunResult(
            q_by_id,
            tool_result,
            output_cif,
            banner,
            compatibility_cli,
            MAPQ_CIF_OPENMODELS_PATCH,
        )


def _write_mapq_compatibility_cli(source_path: Path, output_path: Path) -> None:
    """
    为 MapQ 2.9.7 的 CIF 分支生成一次性兼容副本。

    上游 ``mapq_cmd.py`` 用 ``mmcif.ReadMol`` 构造 Molecule，却没有把它加入
    ``chimera.openModels``；随后 Q-score 内核访问 ``mol.openState`` 时会在真实
    Chimera 1.19 中报 ``ValueError: unopen model``。固定包校验通过后，仅在
    per-PDB scratch 副本中插入一行 ``openModels.add``，不修改安装目录。
    """
    try:
        lines = source_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ExternalToolError(ToolFailureCode.CONFIG_INVALID, str(exc)) from exc
    matches = [
        index
        for index, line in enumerate(lines)
        if "fp.write" in line and "mol = mmcif.ReadMol" in line
    ]
    if len(matches) != 1:
        raise ExternalToolError(
            ToolFailureCode.CONFIG_INVALID,
            f"MapQ CIF compatibility anchor count is {len(matches)}, expected 1",
        )
    index = matches[0]
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    injected = indent + 'fp.write ( "chimera.openModels.add ( [mol], noprefs = True )\\n" )'
    lines.insert(index + 1, injected)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def parse_mapq_output(input_cif: Path, output_cif: Path) -> dict[str, float]:
    """
    以 atom_site.id 为主键读取 Q-score，并逐 id 复核完整身份与坐标。

    输出行可任意重排；重复/缺失/额外 id、身份交换、坐标交换、非有限或越界 Q 都失败。
    """
    input_rows = _read_atom_rows(input_cif)
    output_rows = _read_atom_rows(output_cif)
    input_by_id = _unique_rows_by_id(input_rows, "input")
    output_by_id = _unique_rows_by_id(output_rows, "output")
    if set(input_by_id) != set(output_by_id):
        missing = sorted(set(input_by_id).difference(output_by_id))
        extra = sorted(set(output_by_id).difference(input_by_id))
        raise ExternalToolError(
            ToolFailureCode.OUTPUT_SCHEMA,
            f"MapQ atom_site.id set mismatch: missing={missing[:10]}, extra={extra[:10]}",
        )

    q_by_id: dict[str, float] = {}
    for atom_id, input_row in input_by_id.items():
        output_row = output_by_id[atom_id]
        input_identity = tuple(_identity_value(input_row, key) for key in _IDENTITY_FIELDS)
        output_identity = tuple(_identity_value(output_row, key) for key in _IDENTITY_FIELDS)
        if input_identity != output_identity:
            changed_fields = [
                key
                for key, before, after in zip(
                    _IDENTITY_FIELDS,
                    input_identity,
                    output_identity,
                    strict=True,
                )
                if before != after
            ]
            if not _is_expected_mapq_identity_normalization(
                input_rows,
                input_row,
                output_row,
                changed_fields,
            ):
                raise ExternalToolError(
                    ToolFailureCode.ATOM_MAPPING,
                    f"MapQ identity changed for atom_site.id={atom_id}: {changed_fields}",
                )
        try:
            input_coord = np.asarray([float(input_row[key]) for key in _COORD_FIELDS])
            output_coord = np.asarray([float(output_row[key]) for key in _COORD_FIELDS])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalToolError(
                ToolFailureCode.OUTPUT_SCHEMA,
                f"MapQ coordinate schema is invalid for atom_site.id={atom_id}",
            ) from exc
        expected_output_coord = _mapq_serialized_coordinates(input_coord)
        if not np.array_equal(output_coord, expected_output_coord):
            raise ExternalToolError(
                ToolFailureCode.ATOM_MAPPING,
                "MapQ coordinates changed beyond its documented three-decimal "
                f"mmCIF serialization for atom_site.id={atom_id}",
            )
        if "Q-score" not in output_row:
            raise ExternalToolError(ToolFailureCode.OUTPUT_SCHEMA, "missing _atom_site.Q-score")
        try:
            q_score = float(output_row["Q-score"])
        except (TypeError, ValueError) as exc:
            raise ExternalToolError(
                ToolFailureCode.OUTPUT_SCHEMA,
                f"invalid Q-score for atom_site.id={atom_id}",
            ) from exc
        if not np.isfinite(q_score) or q_score < -1.0 - 1e-6 or q_score > 1.0 + 1e-6:
            raise ExternalToolError(
                ToolFailureCode.OUTPUT_SCHEMA,
                f"out-of-range Q-score for atom_site.id={atom_id}: {q_score}",
            )
        q_by_id[atom_id] = q_score
    return q_by_id


def _mapq_serialized_coordinates(coordinates: np.ndarray) -> np.ndarray:
    """按 MapQ 祖传 ``%.3f`` 写出规则构造唯一允许的输出坐标。"""
    if coordinates.shape != (3,) or not np.all(np.isfinite(coordinates)):
        raise ExternalToolError(
            ToolFailureCode.OUTPUT_SCHEMA,
            "MapQ input coordinates must be three finite values",
        )
    return np.asarray([float("%.3f" % value) for value in coordinates], dtype=np.float64)


def _is_expected_mapq_identity_normalization(
    input_rows: list[dict[str, Any]],
    input_row: dict[str, Any],
    output_row: dict[str, Any],
    changed_fields: list[str],
) -> bool:
    """仅接受 MapQ 祖传 ReadMol/WriteMol 可由输入唯一推导的身份规范化。"""
    if changed_fields == ["type_symbol"]:
        return (
            _identity_value(input_row, "group_PDB") == "HETATM"
            and _identity_value(input_row, "type_symbol") == "X"
            and _identity_value(input_row, "label_atom_id") == "UNK"
            and _identity_value(input_row, "auth_atom_id") == "UNK"
            and _identity_value(input_row, "label_comp_id") == "UNX"
            and _identity_value(input_row, "auth_comp_id") == "UNX"
            # Chimera 1.19 将未知元素 X 确定写回为其 lone-pair 名称 LP。
            and _identity_value(output_row, "type_symbol") == "LP"
        )

    if changed_fields != ["label_comp_id", "auth_comp_id"]:
        return False
    input_label_comp = _identity_value(input_row, "label_comp_id")
    input_auth_comp = _identity_value(input_row, "auth_comp_id")
    output_label_comp = _identity_value(output_row, "label_comp_id")
    output_auth_comp = _identity_value(output_row, "auth_comp_id")
    if not input_label_comp or input_label_comp != input_auth_comp:
        return False
    if not output_label_comp or output_label_comp != output_auth_comp:
        return False

    author_key = _mapq_author_residue_key(input_row)
    collision_rows = [row for row in input_rows if _mapq_author_residue_key(row) == author_key]
    collision_components = {
        _identity_value(row, "auth_comp_id") for row in collision_rows
    }
    if author_key is None or len(collision_components) < 2:
        return False
    # ReadMol 按输入顺序首次创建 author residue；WriteMol 随后把该首个
    # auth_comp_id 同时写到 label/auth comp 字段。
    expected_component = _identity_value(collision_rows[0], "auth_comp_id")
    return bool(expected_component) and output_label_comp == expected_component


def _mapq_author_residue_key(row: dict[str, Any]) -> tuple[str, str, int, str] | None:
    """复现 MapQ ReadMol 的 model 内 author residue 合并主键。"""
    try:
        auth_seq_id = int(_identity_value(row, "auth_seq_id"))
    except ValueError:
        return None
    return (
        _identity_value(row, "pdbx_PDB_model_num"),
        _identity_value(row, "auth_asym_id"),
        auth_seq_id,
        _identity_value(row, "pdbx_PDB_ins_code"),
    )


def _identity_value(row: dict[str, Any], key: str) -> str:
    """规范化身份字段；元素符号大小写不同不代表化学身份改变。"""
    value = clean_value(row.get(key, ""))
    return value.upper() if key == "type_symbol" else value


def _read_atom_rows(path: Path) -> list[dict[str, str]]:
    """读取 mmCIF atom_site，解析错误统一归为外部输出 schema 失败。"""
    try:
        block = gemmi.cif.read(str(path)).sole_block()
        rows = category_rows(block, "_atom_site.")
    except (RuntimeError, ValueError) as exc:
        raise ExternalToolError(ToolFailureCode.OUTPUT_SCHEMA, f"cannot parse mmCIF: {path}") from exc
    if not rows:
        raise ExternalToolError(ToolFailureCode.OUTPUT_SCHEMA, f"empty _atom_site: {path}")
    return rows


def _unique_rows_by_id(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    """把 atom_site 行变为唯一 id 字典。"""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        atom_id = clean_value(str(row.get("id", "")))
        if not atom_id or atom_id in result:
            raise ExternalToolError(
                ToolFailureCode.OUTPUT_SCHEMA,
                f"{label} atom_site.id is missing or duplicated: {atom_id!r}",
            )
        result[atom_id] = row
    return result
