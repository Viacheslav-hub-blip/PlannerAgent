"""Статические проверки структуры Python-проекта.

Содержит функции:
- iter_python_files: поиск собственных Python-файлов;
- validate_file: проверка размера и docstring одного файла;
- main: запуск проверок и печать краткого отчета.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_LINES = 1000
EXCLUDED_PARTS = {
    ".git",
    ".idea",
    ".langgraph_api",
    ".pytest_cache",
    ".runtime",
    ".venv",
    "__pycache__",
    "runs",
}


def iter_python_files(root: Path) -> list[Path]:
    """Находит собственные Python-файлы проекта.

    Args:
        root: Корень проверяемого проекта.

    Returns:
        Отсортированный список Python-файлов без generated и cache-каталогов.
    """

    return sorted(
        path
        for path in root.rglob("*.py")
        if not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts)
    )


def validate_file(path: Path) -> list[str]:
    """Проверяет размер, синтаксис и docstring Python-файла.

    Args:
        path: Путь к проверяемому Python-файлу.

    Returns:
        Список найденных нарушений; пустой список означает успешную проверку.
    """

    source = path.read_text(encoding="utf-8-sig")
    relative_path = path.relative_to(PROJECT_ROOT)
    issues: list[str] = []
    line_count = len(source.splitlines())
    if line_count > MAX_FILE_LINES:
        issues.append(
            f"{relative_path}: {line_count} строк, допустимо не более {MAX_FILE_LINES}"
        )

    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        issues.append(f"{relative_path}:{error.lineno}: синтаксическая ошибка: {error.msg}")
        return issues

    if not ast.get_docstring(tree):
        issues.append(f"{relative_path}: отсутствует docstring файла")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not ast.get_docstring(node):
                issues.append(
                    f"{relative_path}:{node.lineno}: отсутствует docstring у {node.name}"
                )
    return issues


def main() -> int:
    """Запускает проверки качества проекта.

    Returns:
        ``0`` при отсутствии нарушений, иначе ``1``.
    """

    issues = [
        issue
        for path in iter_python_files(PROJECT_ROOT)
        for issue in validate_file(path)
    ]
    if issues:
        print("\n".join(issues))
        return 1
    print("Проверка структуры, лимита строк и docstring пройдена.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
