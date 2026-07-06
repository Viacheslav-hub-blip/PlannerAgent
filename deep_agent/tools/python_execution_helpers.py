"""Вспомогательная обвязка результата Python tool.

Содержит:
- normalize_workspace_path_arguments: нормализация строковых workspace-путей в файловых вызовах.
- _WorkspacePathArgumentTransformer: AST-transformer строковых path-аргументов.
- _is_resolve_workspace_path_call: проверка уже нормализованного path-аргумента.
- _looks_like_workspace_tool_path: проверка строки на workspace tool-путь.
- artifact_preview: preview измененного artifact-файла.
- _text_file_preview: первые строки текстового artifact-файла.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from deep_agent.execution.python_sandbox import DeepAgentPythonSandbox

MAX_ARTIFACT_PREVIEW_LINES = 30
MAX_ARTIFACT_PREVIEW_CHARS = 8_000
PATH_ARGUMENT_CALL_NAMES = frozenset(
    {
        "open",
        "Path",
        "read_csv",
        "read_json",
        "read_excel",
        "read_parquet",
        "read_pickle",
        "read_table",
        "read_fwf",
        "read_html",
        "read_feather",
        "read_orc",
        "to_csv",
        "to_json",
        "to_excel",
        "to_parquet",
        "to_pickle",
        "to_html",
        "to_feather",
        "to_orc",
        "exists",
        "isfile",
        "isdir",
        "getsize",
        "listdir",
        "makedirs",
        "remove",
        "unlink",
        "rename",
        "replace",
        "copy",
        "copyfile",
        "move",
    }
)
TWO_PATH_ARGUMENT_CALL_NAMES = frozenset({"rename", "replace", "copy", "copyfile", "move"})
PATH_ARGUMENT_KEYWORDS = frozenset(
    {
        "path",
        "file",
        "file_path",
        "filepath",
        "filepath_or_buffer",
        "path_or_buf",
        "path_or_buffer",
        "fname",
        "excel_writer",
    }
)
LINUX_SYSTEM_ROOTS = frozenset(
    {
        "bin",
        "boot",
        "dev",
        "etc",
        "home",
        "lib",
        "lib64",
        "mnt",
        "opt",
        "proc",
        "root",
        "run",
        "sbin",
        "sys",
        "tmp",
        "usr",
        "var",
    }
)


def normalize_workspace_path_arguments(code: str, sandbox: DeepAgentPythonSandbox) -> str:
    """Подставляет ``resolve_workspace_path`` для строковых workspace-путей.

    Args:
        code: Python-код перед выполнением.
        sandbox: Sandbox с корнем workspace и helper ``resolve_workspace_path``.

    Returns:
        Исходный код или AST-пересобранный код с нормализованными path-аргументами.
    """

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return code

    transformer = _WorkspacePathArgumentTransformer(sandbox)
    transformed = transformer.visit(tree)
    if not transformer.changed:
        return code
    ast.fix_missing_locations(transformed)
    return ast.unparse(transformed)


class _WorkspacePathArgumentTransformer(ast.NodeTransformer):
    """Заменяет строковые workspace-пути в типичных файловых вызовах Python.

    Args:
        sandbox: Sandbox, относительно которого проверяются корни workspace.

    Returns:
        AST-transformer, который меняет только аргументы известных файловых API.
    """

    def __init__(self, sandbox: DeepAgentPythonSandbox) -> None:
        """Создаёт transformer для нормализации путей.

        Args:
            sandbox: Sandbox с рабочей директорией и readable roots.

        Returns:
            ``None``.
        """

        self.sandbox = sandbox
        self.changed = False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Нормализует строковые path-аргументы в вызове функции или метода.

        Args:
            node: Узел ``ast.Call``.

        Returns:
            Обновленный узел вызова.
        """

        self.generic_visit(node)
        if not self._is_path_call(node):
            return node

        positional_path_args = 2 if self._call_name(node) in TWO_PATH_ARGUMENT_CALL_NAMES else 1
        for index in range(min(positional_path_args, len(node.args))):
            node.args[index] = self._replace_path_literal(node.args[index])
        for keyword in node.keywords:
            if keyword.arg in PATH_ARGUMENT_KEYWORDS:
                keyword.value = self._replace_path_literal(keyword.value)
        return node

    def _is_path_call(self, node: ast.Call) -> bool:
        """Проверяет, относится ли вызов к известным файловым API.

        Args:
            node: Узел вызова Python.

        Returns:
            ``True``, если первый аргумент вызова вероятно является путем.
        """

        func = node.func
        if isinstance(func, ast.Name):
            return func.id in PATH_ARGUMENT_CALL_NAMES
        if isinstance(func, ast.Attribute):
            return func.attr in PATH_ARGUMENT_CALL_NAMES
        return False

    def _call_name(self, node: ast.Call) -> str:
        """Возвращает простое имя вызываемой функции или метода.

        Args:
            node: Узел вызова Python.

        Returns:
            Имя функции, метода или пустую строку.
        """

        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return ""

    def _replace_path_literal(self, node: ast.AST) -> ast.AST:
        """Заменяет строковый workspace-путь на вызов ``resolve_workspace_path``.

        Args:
            node: Узел аргумента вызова.

        Returns:
            Исходный или замененный AST-узел.
        """

        if _is_resolve_workspace_path_call(node):
            return node
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return node
        if not _looks_like_workspace_tool_path(node.value, self.sandbox):
            return node
        self.changed = True
        return ast.Call(
            func=ast.Name(id="resolve_workspace_path", ctx=ast.Load()),
            args=[node],
            keywords=[],
        )


def _is_resolve_workspace_path_call(node: ast.AST) -> bool:
    """Проверяет, что аргумент уже обернут в ``resolve_workspace_path``.

    Args:
        node: AST-узел аргумента.

    Returns:
        ``True``, если узел является вызовом helper ``resolve_workspace_path``.
    """

    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "resolve_workspace_path"
    )


def _looks_like_workspace_tool_path(value: str, sandbox: DeepAgentPythonSandbox) -> bool:
    """Проверяет, похожа ли строка на workspace tool-путь вида ``/file``.

    Args:
        value: Строковое значение из Python-кода.
        sandbox: Sandbox с реальными workspace-корнями.

    Returns:
        ``True``, если путь нужно преобразовать через ``resolve_workspace_path``.
    """

    normalized = str(value or "").strip().replace("\\", "/")
    if not normalized.startswith("/") or normalized == "/":
        return False
    if len(normalized) >= 4 and normalized[2:4] == ":/":
        return False

    readable_prefixes = [path.as_posix().rstrip("/") for path in sandbox.readable_roots]
    if any(normalized == prefix or normalized.startswith(f"{prefix}/") for prefix in readable_prefixes):
        return False

    first_segment = normalized.lstrip("/").split("/", 1)[0]
    if first_segment in LINUX_SYSTEM_ROOTS:
        return False
    return True


def artifact_preview(path: Path) -> dict[str, Any]:
    """Возвращает компактный preview измененного artifact-файла.

    Args:
        path: Реальный путь к artifact-файлу.

    Returns:
        Словарь с preview для текстовых форматов или причиной недоступности preview.
    """

    suffix = path.suffix.lower()
    if suffix in {".csv", ".json", ".jsonl", ".md", ".txt", ".py", ".html", ".log"}:
        return _text_file_preview(
            path,
            max_lines=MAX_ARTIFACT_PREVIEW_LINES,
            max_chars=MAX_ARTIFACT_PREVIEW_CHARS,
        )
    return {
        "available": False,
        "reason": "Preview не формируется для бинарного или нетекстового artifact.",
    }


def _text_file_preview(path: Path, *, max_lines: int, max_chars: int) -> dict[str, Any]:
    """Читает первые строки текстового artifact-файла.

    Args:
        path: Реальный путь к файлу.
        max_lines: Максимальное число строк preview.
        max_chars: Максимальное число символов preview.

    Returns:
        Словарь с первыми строками или ошибкой чтения.
    """

    lines: list[str] = []
    total_chars = 0
    truncated = False
    try:
        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if line_number > max(0, max_lines):
                    truncated = True
                    break
                clean_line = line.rstrip("\n\r")
                total_chars += len(clean_line)
                if total_chars > max_chars:
                    lines.append(clean_line[: max(0, len(clean_line) - (total_chars - max_chars))])
                    truncated = True
                    break
                lines.append(clean_line)
    except (OSError, UnicodeDecodeError) as error:
        return {
            "available": False,
            "error": f"{type(error).__name__}: {error}",
            "lines": [],
        }
    return {
        "available": True,
        "line_count": len(lines),
        "max_lines": max_lines,
        "truncated": truncated,
        "lines": lines,
    }


__all__ = [
    "artifact_preview",
    "normalize_workspace_path_arguments",
]
