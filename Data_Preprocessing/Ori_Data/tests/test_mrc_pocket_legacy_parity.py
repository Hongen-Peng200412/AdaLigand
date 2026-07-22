"""Pocket Plus 祖传 MRC 原语的逐函数同源性测试。"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VENDORED_PATH = (
    PROJECT_ROOT
    / "Data_Preprocessing"
    / "Ori_Data"
    / "adaligand_preprocessing"
    / "geometry"
    / "legacy"
    / "mrc_pocket.py"
)
MANIFEST_PATH = VENDORED_PATH.with_suffix(".source.json")
ANCESTOR_PATH = (
    PROJECT_ROOT.parent
    / "Pocket_Plus"
    / "processedPDB_EMDB_binder"
    / "utils"
    / "mrc_tools.py"
)


def _sha256_bytes(content: bytes) -> str:
    """返回给定字节内容的 SHA256 十六进制摘要。"""
    return hashlib.sha256(content).hexdigest()


def _function_sources(path: Path) -> tuple[str, dict[str, tuple[ast.FunctionDef, str]]]:
    """
    读取 Python 文件并提取模块顶层函数的 AST 与原始源码片段。

    输入参数:
        - path: Path, 待解析的 Python 文件路径

    输出:
        - source: str, 完整 UTF-8 源码
        - functions: dict[str, tuple[ast.FunctionDef, str]], 函数名到 AST 节点及精确源码片段的映射
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: (node, ast.get_source_segment(source, node) or "")
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    return source, functions


def _portable_ast(value: object) -> object:
    """把 AST 规范为跨 Python 3.10+ 稳定的纯 JSON 结构。"""
    if isinstance(value, ast.AST):
        fields = []
        for field_name in value._fields:
            # Python 3.12 为 FunctionDef/ClassDef 新增 type_params；空列表不改变本项目函数语义。
            if field_name == "type_params":
                continue
            fields.append((field_name, _portable_ast(getattr(value, field_name))))
        return {"node": type(value).__name__, "fields": fields}
    if isinstance(value, list):
        return [_portable_ast(item) for item in value]
    return value


def _portable_ast_sha256(node: ast.AST) -> str:
    """返回忽略解释器新增非语义字段的稳定 AST SHA256。"""
    payload = json.dumps(
        _portable_ast(node),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(payload)


def test_vendored_functions_match_frozen_ancestor_hashes_exactly() -> None:
    """验证 vendored 文件及六个函数都与 manifest 中冻结的祖传哈希一致。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    vendored_bytes = VENDORED_PATH.read_bytes()
    vendored_source, vendored_functions = _function_sources(VENDORED_PATH)

    assert _sha256_bytes(vendored_bytes) == manifest["vendored"]["sha256"]
    assert len(vendored_bytes) == manifest["vendored"]["size_bytes"]
    assert manifest["function_body_deviations"] == []
    assert set(vendored_functions) == set(manifest["functions"])

    for function_name, frozen in manifest["functions"].items():
        node, exact_source = vendored_functions[function_name]
        assert _sha256_bytes(exact_source.encode("utf-8")) == frozen["exact_source_sha256"]
        assert _portable_ast_sha256(node) == frozen["portable_ast_sha256"]

    tree = ast.parse(vendored_source)
    imports = [
        (alias.name, alias.asname)
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert imports == [("mrcfile", "mrc"), ("numpy", "np")]
    assert not any(isinstance(node, ast.ImportFrom) for node in tree.body)


def test_direct_ancestor_parity_when_sibling_checkout_is_available() -> None:
    """本机存在 Pocket_Plus 同级仓库时，直接比较祖传源码与 vendored 函数。"""
    if not ANCESTOR_PATH.is_file():
        return

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    ancestor_bytes = ANCESTOR_PATH.read_bytes()
    _, ancestor_functions = _function_sources(ANCESTOR_PATH)
    _, vendored_functions = _function_sources(VENDORED_PATH)

    assert _sha256_bytes(ancestor_bytes) == manifest["ancestor"]["sha256"]
    assert len(ancestor_bytes) == manifest["ancestor"]["size_bytes"]
    for function_name in manifest["functions"]:
        ancestor_node, ancestor_source = ancestor_functions[function_name]
        vendored_node, vendored_source = vendored_functions[function_name]
        assert vendored_source == ancestor_source
        assert _portable_ast(vendored_node) == _portable_ast(ancestor_node)
