"""Форматирование ячеек Jupyter Notebook для convert_jupyter_notebook.

Содержит функции:
- _normalize_notebook_source: нормализация source notebook-ячейки;
- _format_code_cell_lines: форматирование Python-кода code-ячейки;
- _format_python_text_with_external_formatter: запуск внешнего formatter для Python-кода;
- _normalize_python_spacing: резервная нормализация пробелов Python-кода;
- _strip_trailing_whitespace: удаление хвостовых пробелов;
- _starts_top_level_block: проверка top-level def/class/decorator блока;
- _has_significant_line: проверка наличия непустой строки;
- _trailing_blank_lines: получение хвостовых пустых строк;
- _ensure_trailing_blank_lines: установка числа хвостовых пустых строк;
- _format_markdown_cell_lines: форматирование markdown-ячейки;
- _is_markdown_fence: проверка fenced code block;
- _is_structural_markdown_line: проверка структурной markdown-строки;
- _flush_markdown_paragraph: перенос накопленного markdown-абзаца;
- _append_single_blank_line: добавление одиночной пустой строки;
- _lines_to_text: преобразование строк notebook в текст;
- _text_to_notebook_lines: преобразование текста в строки notebook;
- _markdown_lines_from_percent_cell: преобразование percent markdown-комментариев в notebook markdown;
- _percent_lines_from_markdown_cell: преобразование notebook markdown в percent comments.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from typing import Any

PYTHON_FORMATTER_TIMEOUT_SECONDS = 10
MARKDOWN_WRAP_WIDTH = 88

def _normalize_notebook_source(source: Any) -> list[str]:
    """Нормализует ``source`` ячейки notebook к списку строк.

    Args:
        source: Значение ``cell["source"]`` из notebook: строка, список строк или другой объект.

    Returns:
        Список строк с сохраненными переводами строк.
    """

    if isinstance(source, list):
        return [str(line) for line in source]
    if isinstance(source, str):
        return source.splitlines(keepends=True)
    return [str(source)]


def _format_code_cell_lines(source_lines: list[str]) -> list[str]:
    """Форматирует Python-код ячейки notebook без изменения смысла кода.

    Args:
        source_lines: Строки исходного кода одной code-ячейки.

    Returns:
        Список строк отформатированной code-ячейки с сохранёнными переводами строк.
    """

    source_text = _lines_to_text(source_lines)
    if not source_text.strip():
        return []

    formatted_text = _format_python_text_with_external_formatter(source_text)
    if formatted_text is None:
        formatted_text = _normalize_python_spacing(source_text)

    return _text_to_notebook_lines(formatted_text)


def _format_python_text_with_external_formatter(source_text: str) -> str | None:
    """Форматирует Python-код через установленный formatter, если он доступен.

    Args:
        source_text: Текст Python-кода одной ячейки.

    Returns:
        Отформатированный текст или ``None``, если внешний formatter недоступен или не смог разобрать ячейку.
    """

    formatter_commands = (
        ("ruff", ["ruff", "format", "--stdin-filename", "notebook_cell.py", "-"]),
        ("black", ["black", "--quiet", "-"]),
    )
    for executable_name, command in formatter_commands:
        if shutil.which(executable_name) is None:
            continue
        try:
            result = subprocess.run(
                command,
                input=source_text,
                capture_output=True,
                check=False,
                encoding="utf-8",
                timeout=PYTHON_FORMATTER_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return None


def _normalize_python_spacing(source_text: str) -> str:
    """Нормализует пробелы и разделители Python-кода при отсутствии внешнего formatter.

    Args:
        source_text: Текст Python-кода одной ячейки.

    Returns:
        Текст с удалёнными хвостовыми пробелами и двумя пустыми строками перед top-level ``def``/``class``.
    """

    normalized_lines = _strip_trailing_whitespace(source_text)
    output_lines: list[str] = []

    for line_index, line in enumerate(normalized_lines):
        if not line.strip():
            if output_lines and output_lines[-1].strip():
                output_lines.append("\n")
            elif output_lines and len(_trailing_blank_lines(output_lines)) < 2:
                output_lines.append("\n")
            continue

        if _starts_top_level_block(normalized_lines, line_index) and _has_significant_line(output_lines):
            _ensure_trailing_blank_lines(output_lines, expected_count=2)

        output_lines.append(line)

    while output_lines and not output_lines[-1].strip():
        output_lines.pop()

    return "".join(output_lines).rstrip() + "\n"


def _strip_trailing_whitespace(source_text: str) -> list[str]:
    """Удаляет хвостовые пробелы в строках Python-кода.

    Args:
        source_text: Текст Python-кода одной ячейки.

    Returns:
        Список строк с сохранёнными переводами строк.
    """

    lines = source_text.splitlines(keepends=True)
    stripped_lines = []
    for line in lines:
        line_without_newline = line.rstrip("\r\n")
        newline = line[len(line_without_newline) :]
        newline_value = newline or "\n"
        stripped_lines.append(f"{line_without_newline.rstrip()}{newline_value}")
    return stripped_lines


def _starts_top_level_block(lines: list[str], line_index: int) -> bool:
    """Проверяет, начинает ли строка top-level функцию, класс или их декоратор.

    Args:
        lines: Все строки code-ячейки.
        line_index: Индекс проверяемой строки.

    Returns:
        ``True``, если строка должна быть отделена двумя пустыми строками от предыдущего top-level блока.
    """

    stripped_line = lines[line_index].lstrip()
    if lines[line_index] != stripped_line:
        return False
    if stripped_line.startswith(("def ", "async def ", "class ")):
        return True
    if not stripped_line.startswith("@"):
        return False
    next_index = line_index + 1
    while next_index < len(lines):
        next_line = lines[next_index]
        next_stripped_line = next_line.lstrip()
        if next_line != next_stripped_line:
            return False
        if not next_stripped_line.strip():
            next_index += 1
            continue
        if next_stripped_line.startswith("@"):
            next_index += 1
            continue
        return next_stripped_line.startswith(("def ", "async def ", "class "))
    return False


def _has_significant_line(lines: list[str]) -> bool:
    """Проверяет наличие непустой строки в уже сформированном блоке кода.

    Args:
        lines: Уже накопленные строки code-ячейки.

    Returns:
        ``True``, если в списке есть строка с содержимым.
    """

    return any(line.strip() for line in lines)


def _trailing_blank_lines(lines: list[str]) -> list[str]:
    """Возвращает хвостовые пустые строки.

    Args:
        lines: Список строк.

    Returns:
        Список пустых строк в конце входного списка.
    """

    blank_lines = []
    for line in reversed(lines):
        if line.strip():
            break
        blank_lines.append(line)
    return blank_lines


def _ensure_trailing_blank_lines(lines: list[str], *, expected_count: int) -> None:
    """Обеспечивает точное число пустых строк в конце списка.

    Args:
        lines: Изменяемый список строк.
        expected_count: Требуемое число пустых строк в конце списка.

    Returns:
        ``None``. Список ``lines`` изменяется на месте.
    """

    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend("\n" for _ in range(expected_count))


def _format_markdown_cell_lines(source_lines: list[str]) -> list[str]:
    """Форматирует markdown-ячейку notebook в читаемые строки.

    Args:
        source_lines: Строки markdown-ячейки.

    Returns:
        Список строк markdown-ячейки с переносами строк.
    """

    source_text = _lines_to_text(source_lines)
    if not source_text.strip():
        return []

    output_lines: list[str] = []
    paragraph_lines: list[str] = []
    inside_fence = False

    for raw_line in source_text.splitlines():
        line = raw_line.rstrip()
        stripped_line = line.strip()

        if _is_markdown_fence(stripped_line):
            _flush_markdown_paragraph(paragraph_lines, output_lines)
            output_lines.append(f"{line}\n")
            inside_fence = not inside_fence
            continue

        if inside_fence:
            output_lines.append(f"{line}\n")
            continue

        if not stripped_line:
            _flush_markdown_paragraph(paragraph_lines, output_lines)
            _append_single_blank_line(output_lines)
            continue

        if _is_structural_markdown_line(stripped_line):
            _flush_markdown_paragraph(paragraph_lines, output_lines)
            output_lines.append(f"{line}\n")
            continue

        paragraph_lines.append(stripped_line)

    _flush_markdown_paragraph(paragraph_lines, output_lines)
    while output_lines and not output_lines[-1].strip():
        output_lines.pop()
    return output_lines


def _is_markdown_fence(stripped_line: str) -> bool:
    """Проверяет начало или конец fenced code block в markdown.

    Args:
        stripped_line: Markdown-строка без внешних пробелов.

    Returns:
        ``True``, если строка является fence-маркером.
    """

    return stripped_line.startswith(("```", "~~~"))


def _is_structural_markdown_line(stripped_line: str) -> bool:
    """Проверяет markdown-строки, которые нельзя переносить как обычный абзац.

    Args:
        stripped_line: Markdown-строка без внешних пробелов.

    Returns:
        ``True`` для заголовков, списков, таблиц, цитат, горизонтальных правил и HTML-блоков.
    """

    if stripped_line.startswith(("#", ">", "|", "<")):
        return True
    if stripped_line.startswith(("- ", "* ", "+ ")):
        return True
    if stripped_line[:3] in {"---", "***", "___"}:
        return True
    marker, _, rest = stripped_line.partition(". ")
    return marker.isdigit() and bool(rest)


def _flush_markdown_paragraph(paragraph_lines: list[str], output_lines: list[str]) -> None:
    """Переносит накопленный markdown-абзац в выходной список строк.

    Args:
        paragraph_lines: Накопленные строки одного абзаца.
        output_lines: Изменяемый список выходных строк.

    Returns:
        ``None``. Списки изменяются на месте.
    """

    if not paragraph_lines:
        return
    paragraph_text = " ".join(paragraph_lines)
    wrapped_lines = textwrap.wrap(
        paragraph_text,
        width=MARKDOWN_WRAP_WIDTH,
        break_long_words=False,
        break_on_hyphens=False,
    )
    output_lines.extend(f"{line}\n" for line in wrapped_lines)
    paragraph_lines.clear()


def _append_single_blank_line(output_lines: list[str]) -> None:
    """Добавляет одну пустую строку, если предыдущая строка не пустая.

    Args:
        output_lines: Изменяемый список markdown-строк.

    Returns:
        ``None``. Список ``output_lines`` изменяется на месте.
    """

    if output_lines and output_lines[-1].strip():
        output_lines.append("\n")


def _lines_to_text(source_lines: list[str]) -> str:
    """Преобразует список строк notebook в единый текст.

    Args:
        source_lines: Строки ячейки notebook.

    Returns:
        Текст ячейки.
    """

    return "".join(source_lines)


def _text_to_notebook_lines(source_text: str) -> list[str]:
    """Преобразует текст ячейки notebook в список строк.

    Args:
        source_text: Текст ячейки notebook.

    Returns:
        Список строк с сохранёнными переводами строк.
    """

    return f"{source_text.rstrip()}\n".splitlines(keepends=True)


def _markdown_lines_from_percent_cell(source_lines: list[str]) -> list[str]:
    """Преобразует закомментированные markdown-строки percent-script в текст notebook.

    Args:
        source_lines: Строки markdown-ячейки из ``.py`` файла.

    Returns:
        Строки markdown-ячейки для ``.ipynb``.
    """

    markdown_lines = []
    for line in source_lines:
        if line.startswith("# "):
            markdown_lines.append(line[2:])
        elif line.startswith("#\n") or line == "#":
            markdown_lines.append(line[1:])
        else:
            markdown_lines.append(line)
    return markdown_lines


def _percent_lines_from_markdown_cell(source_lines: list[str]) -> list[str]:
    """Преобразует markdown-строки notebook в comment-блок percent-script.

    Args:
        source_lines: Строки markdown-ячейки notebook.

    Returns:
        Строки ``.py`` файла с префиксом ``#``.
    """

    percent_lines = []
    for line in source_lines:
        if line == "\n" or line == "":
            percent_lines.append("#\n")
        else:
            percent_lines.append(f"# {line}")
    return percent_lines
