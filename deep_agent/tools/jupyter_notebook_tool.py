"""Инструмент конвертации Jupyter Notebook для coding-agent.

Содержит:
- CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME: имя LangChain tool.
- CONVERT_JUPYTER_NOTEBOOK_DESCRIPTION: описание tool для модели.
- ConvertJupyterNotebookInput: схема аргументов tool ``convert_jupyter_notebook``.
- ConvertJupyterNotebookTool: LangChain tool конвертации ``.py`` percent-script и ``.ipynb``.
- build_convert_jupyter_notebook_tool: фабрика tool ``convert_jupyter_notebook``.
- convert_jupyter_notebook_file: конвертация файла notebook или percent-script.
- build_notebook_from_python_text: сборка notebook из текстового Python/percent-script.
- _py_to_ipynb: преобразование ``.py`` percent-script в структуру notebook.
- _ipynb_to_py: преобразование структуры notebook в ``.py`` percent-script.
- _parse_percent_script: разбор ``# %%`` ячеек в Python-файле.
- _parse_write_file_notebook_script: разбор текста write_file для создания notebook.
- _split_comment_markdown_blocks: перенос ``#``-блоков из code-ячеек в markdown.
- _split_unmarked_code_from_markdown_cell: перенос хвоста markdown-ячейки без ``#`` в code-ячейку.
- _normalize_notebook_source: нормализация содержимого ячейки notebook.
- _format_code_cell_lines: форматирование Python-кода одной code-ячейки.
- _format_python_text_with_external_formatter: форматирование Python-кода внешним formatter.
- _normalize_python_spacing: резервная нормализация пробелов и разделителей Python-кода.
- _strip_trailing_whitespace: удаление хвостовых пробелов в строках Python-кода.
- _starts_top_level_block: определение top-level ``def``/``class`` блоков.
- _has_significant_line: проверка наличия непустой строки.
- _trailing_blank_lines: получение хвостовых пустых строк.
- _ensure_trailing_blank_lines: установка нужного числа хвостовых пустых строк.
- _format_markdown_cell_lines: форматирование markdown-ячейки в читаемые строки.
- _is_markdown_fence: проверка fence-маркера markdown.
- _is_structural_markdown_line: проверка структурной markdown-строки.
- _flush_markdown_paragraph: перенос накопленного markdown-абзаца в выходные строки.
- _append_single_blank_line: добавление одиночной пустой строки.
- _lines_to_text: преобразование строк notebook в текст.
- _text_to_notebook_lines: преобразование текста ячейки notebook в строки.
- _markdown_lines_from_percent_cell: преобразование markdown-комментариев в текст ячейки.
- _percent_lines_from_markdown_cell: преобразование markdown-ячейки в comment-блок.
- _resolve_workspace_file_path: разрешение workspace-пути в локальный файл.
- _assert_inside_workspace: проверка принадлежности пути workspace.
- _assert_converted_filename_preserved: проверка сохранения имени файла при конвертации.
- _json_payload: сериализация результата tool в JSON.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Callable, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from deep_agent.agent_settings import (
    load_agent_settings,
    strip_workspace_tool_prefix,
    workspace_tool_path,
)

CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME = "convert_jupyter_notebook"
PYTHON_FORMATTER_TIMEOUT_SECONDS = 10
MARKDOWN_WRAP_WIDTH = 88
CONVERT_JUPYTER_NOTEBOOK_DESCRIPTION = """
convert_jupyter_notebook
---
Конвертирует и пересобирает Jupyter notebook между `.py` percent-script и `.ipynb`.

Каждый выходной файл нормализуется перед записью. Инструмент всегда форматирует Python code-ячейки,
форматирует markdown/text-ячейки, сохраняет markdown как реальные notebook markdown-ячейки и очищает
outputs/execution_count при пересборке из `.ipynb`.

Правила:
- Для `py_to_ipynb` исходный файл должен иметь расширение `.py`, целевой файл `.ipynb`.
- Для `ipynb_to_py` исходный файл должен иметь расширение `.ipynb`, целевой файл `.py`.
- Имя файла без расширения менять нельзя: `output_path` может отличаться директорией и расширением, но не stem.
- Инструмент только конвертирует файлы и не выполняет код notebook.
- При `ipynb_to_py` outputs и execution_count игнорируются.
- Markdown/text-ячейки создаются только из percent-ячеек, помеченных ровно как `# %% [markdown]`.
- Не добавляй отдельный шаг форматирования: этот tool всегда форматирует содержимое notebook перед записью файла.

""".strip()


class ConvertJupyterNotebookInput(BaseModel):
    """Аргументы tool ``convert_jupyter_notebook`` для конвертации notebook-файлов.

    Attributes:
        mode: Направление конвертации: из ``.py`` percent-script в ``.ipynb`` или обратно.
        source_path: Исходный путь внутри workspace.
        output_path: Целевой путь внутри workspace.
        kernel_name: Имя Python kernel, записываемое в metadata при создании ``.ipynb``.
        overwrite: Разрешение перезаписи существующего целевого файла.
    """

    mode: Literal["py_to_ipynb", "ipynb_to_py"] = Field(
        description="Направление конвертации: `py_to_ipynb` или `ipynb_to_py`.",
    )
    source_path: str = Field(
        description="Исходный файл внутри workspace. Можно передать абсолютный путь ОС или workspace-путь tools.",
    )
    output_path: str = Field(
        description=(
            "Целевой файл внутри workspace. Для `py_to_ipynb` это `.ipynb`, "
            "для `ipynb_to_py` это `.py`. Имя файла без расширения должно "
            "совпадать с исходным файлом."
        ),
    )
    kernel_name: str = Field(
        default="python3",
        description="Имя kernel для metadata создаваемого `.ipynb`; обычно `python3`.",
    )
    overwrite: bool = Field(
        default=True,
        description="Если `False`, существующий целевой файл не перезаписывается.",
    )


class ConvertJupyterNotebookTool(BaseTool):
    """LangChain tool конвертации Jupyter Notebook без выполнения кода.

    Args:
        workspace_root: Корень workspace для разрешения относительных и workspace-путей.

    Returns:
        ``None``. Результат работы возвращается методом ``_run`` в виде JSON-строки.
    """

    name: str = CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME
    description: str = CONVERT_JUPYTER_NOTEBOOK_DESCRIPTION
    args_schema: type[BaseModel] = ConvertJupyterNotebookInput

    _workspace_root: Path = PrivateAttr()

    def __init__(self, *, workspace_root: str | Path | None = None) -> None:
        """Создает tool конвертации notebook-файлов.

        Args:
            workspace_root: Корень workspace. Если ``None``, берется из настроек агента.

        Returns:
            ``None``.
        """

        super().__init__()
        resolved_workspace_root = workspace_root or load_agent_settings().workspace_root
        self._workspace_root = Path(resolved_workspace_root).expanduser().resolve()

    def _run(
        self,
        mode: Literal["py_to_ipynb", "ipynb_to_py"],
        source_path: str,
        output_path: str,
        kernel_name: str = "python3",
        overwrite: bool = True,
        **_: Any,
    ) -> str:
        """Выполняет синхронную конвертацию notebook-файла.

        Args:
            mode: Направление конвертации.
            source_path: Исходный путь внутри workspace.
            output_path: Целевой путь внутри workspace.
            kernel_name: Имя kernel для ``.ipynb``.
            overwrite: Разрешение перезаписи целевого файла.
            **_: Дополнительные аргументы LangChain, которые игнорируются.

        Returns:
            JSON-строка с результатом конвертации.
        """

        return convert_jupyter_notebook_file(
            mode=mode,
            source_path=source_path,
            output_path=output_path,
            workspace_root=self._workspace_root,
            kernel_name=kernel_name,
            overwrite=overwrite,
        )

    async def _arun(
        self,
        mode: Literal["py_to_ipynb", "ipynb_to_py"],
        source_path: str,
        output_path: str,
        kernel_name: str = "python3",
        overwrite: bool = True,
        **kwargs: Any,
    ) -> str:
        """Выполняет асинхронную конвертацию notebook-файла через синхронную реализацию.

        Args:
            mode: Направление конвертации.
            source_path: Исходный путь внутри workspace.
            output_path: Целевой путь внутри workspace.
            kernel_name: Имя kernel для ``.ipynb``.
            overwrite: Разрешение перезаписи целевого файла.
            **kwargs: Дополнительные аргументы LangChain.

        Returns:
            JSON-строка с результатом конвертации.
        """

        return self._run(
            mode=mode,
            source_path=source_path,
            output_path=output_path,
            kernel_name=kernel_name,
            overwrite=overwrite,
            **kwargs,
        )


def build_convert_jupyter_notebook_tool(
    *,
    workspace_root: str | Path | None = None,
) -> ConvertJupyterNotebookTool:
    """Собирает tool ``convert_jupyter_notebook``.

    Args:
        workspace_root: Корень workspace для ограничения файловых операций.

    Returns:
        Экземпляр ``ConvertJupyterNotebookTool``.
    """

    return ConvertJupyterNotebookTool(workspace_root=workspace_root)


def convert_jupyter_notebook_file(
    *,
    mode: Literal["py_to_ipynb", "ipynb_to_py"],
    source_path: str,
    output_path: str,
    workspace_root: str | Path,
    kernel_name: str = "python3",
    overwrite: bool = True,
) -> str:
    """Конвертирует файл между ``.py`` percent-script и ``.ipynb``.

    Args:
        mode: Направление конвертации.
        source_path: Исходный путь внутри workspace.
        output_path: Целевой путь внутри workspace.
        workspace_root: Корень workspace для разрешения путей.
        kernel_name: Имя kernel для создаваемого ``.ipynb``.
        overwrite: Разрешение перезаписи целевого файла.

    Returns:
        JSON-строка с успешным результатом конвертации.

    Raises:
        FileNotFoundError: Исходный файл не найден.
        FileExistsError: Целевой файл существует при ``overwrite=False``.
        ValueError: Путь вне workspace, неверное расширение или неподдерживаемый режим.
    """

    resolved_workspace_root = Path(workspace_root).expanduser().resolve()
    source_file = _resolve_workspace_file_path(source_path, resolved_workspace_root)
    output_file = _resolve_workspace_file_path(output_path, resolved_workspace_root)

    if not source_file.is_file():
        raise FileNotFoundError(f"Исходный файл не найден: {source_path}")
    if output_file.exists() and not overwrite:
        raise FileExistsError(f"Целевой файл уже существует: {output_path}")

    if mode == "py_to_ipynb":
        if source_file.suffix.lower() != ".py" or output_file.suffix.lower() != ".ipynb":
            raise ValueError("Для `py_to_ipynb` нужен исходный `.py` и целевой `.ipynb`.")
        _assert_converted_filename_preserved(source_file, output_file)
        source_text = source_file.read_text(encoding="utf-8")
        notebook = _py_to_ipynb(source_text, kernel_name=kernel_name)
        cells_count = len(notebook["cells"])
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(notebook, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif mode == "ipynb_to_py":
        if source_file.suffix.lower() != ".ipynb" or output_file.suffix.lower() != ".py":
            raise ValueError("Для `ipynb_to_py` нужен исходный `.ipynb` и целевой `.py`.")
        _assert_converted_filename_preserved(source_file, output_file)
        notebook = json.loads(source_file.read_text(encoding="utf-8"))
        cells_count = len(notebook.get("cells", []))
        script_text = _ipynb_to_py(notebook)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(script_text, encoding="utf-8")
    else:
        raise ValueError(f"Неподдерживаемый режим конвертации: {mode}")

    return _json_payload(
        {
            "success": True,
            "mode": mode,
            "source_path": workspace_tool_path(source_file, resolved_workspace_root),
            "output_path": workspace_tool_path(output_file, resolved_workspace_root),
            "cells_count": cells_count,
            "message": "Файл успешно сконвертирован.",
        }
    )


def build_notebook_from_python_text(
    source_text: str,
    *,
    kernel_name: str = "python3",
    split_comment_markdown: bool = False,
) -> dict[str, Any]:
    """Собирает notebook из текста Python/percent-script.
    Args:
        source_text: Исходный текст для ячеек notebook.
        kernel_name: Имя kernel в metadata.
        split_comment_markdown: Нужно ли превращать ``#``-блоки в markdown.
    Returns:
        Словарь notebook v4.
    """

    parser = _parse_write_file_notebook_script if split_comment_markdown else _parse_percent_script
    return _py_to_ipynb(
        source_text,
        kernel_name=kernel_name,
        parse_cells=parser,
    )


def _py_to_ipynb(
    source_text: str,
    *,
    kernel_name: str,
    parse_cells: Callable[[str], list[tuple[Literal["code", "markdown"], list[str]]]] | None = None,
) -> dict[str, Any]:
    """Преобразует ``.py`` percent-script в JSON-структуру Jupyter Notebook.

    Args:
        source_text: Текст Python-файла с маркерами ``# %%``.
        kernel_name: Имя kernel для metadata notebook.
        parse_cells: Функция разбиения исходного текста на пары ``(тип, строки)``.

    Returns:
        Словарь notebook формата nbformat v4.
    """

    cells = []
    resolved_parse_cells = parse_cells or _parse_percent_script
    for cell_type, source_lines in resolved_parse_cells(source_text):
        if cell_type == "markdown":
            cells.append(
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": _format_markdown_cell_lines(
                        _markdown_lines_from_percent_cell(source_lines)
                    ),
                }
            )
        else:
            cells.append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": _format_code_cell_lines(source_lines),
                }
            )

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": kernel_name,
                "language": "python",
                "name": kernel_name,
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _ipynb_to_py(notebook: dict[str, Any]) -> str:
    """Преобразует JSON-структуру Jupyter Notebook в ``.py`` percent-script.

    Args:
        notebook: Словарь notebook, загруженный из ``.ipynb``.

    Returns:
        Текст Python-файла с маркерами ``# %%``.
    """

    output_lines: list[str] = []
    for cell in notebook.get("cells", []):
        cell_type = str(cell.get("cell_type", "code"))
        source_lines = _normalize_notebook_source(cell.get("source", []))
        if cell_type == "markdown":
            output_lines.append("# %% [markdown]\n")
            output_lines.extend(
                _percent_lines_from_markdown_cell(_format_markdown_cell_lines(source_lines))
            )
        else:
            output_lines.append("# %%\n")
            output_lines.extend(_format_code_cell_lines(source_lines))
        if output_lines and not output_lines[-1].endswith("\n"):
            output_lines[-1] += "\n"
        output_lines.append("\n")

    return "".join(output_lines).rstrip() + "\n"


def _parse_percent_script(source_text: str) -> list[tuple[Literal["code", "markdown"], list[str]]]:
    """Разбирает Python percent-script на ячейки.

    Args:
        source_text: Текст Python-файла с опциональными маркерами ``# %%``.

    Returns:
        Список пар ``(тип_ячейки, строки_исходника)``.
    """

    cells: list[tuple[Literal["code", "markdown"], list[str]]] = []
    current_type: Literal["code", "markdown"] = "code"
    current_lines: list[str] = []
    has_current_cell = False

    def flush_current_cell() -> None:
        """Добавляет накопленную percent-ячейку в итоговый список.

        Args:
            Отсутствуют.

        Returns:
            ``None``.
        """

        if current_type == "markdown":
            cells.extend(_split_unmarked_code_from_markdown_cell(current_lines))
            return
        cells.append((current_type, current_lines.copy()))

    for line in source_text.splitlines(keepends=True):
        stripped_line = line.strip()
        if stripped_line.startswith("# %%"):
            if has_current_cell or current_lines:
                flush_current_cell()
            current_type = "markdown" if "[markdown]" in stripped_line.lower() else "code"
            current_lines = []
            has_current_cell = True
            continue
        current_lines.append(line)

    if has_current_cell or current_lines:
        flush_current_cell()
    if not cells:
        cells.append(("code", []))
    return cells


def _parse_write_file_notebook_script(
    source_text: str,
) -> list[tuple[Literal["code", "markdown"], list[str]]]:
    """Разбирает текст ``write_file`` для прямой сборки ``.ipynb``.

    Args:
        source_text: Текст Python/percent-script из ``write_file``.

    Returns:
        Пары ``(тип_ячейки, строки)`` с markdown из ``# %%`` и ``#``-блоков.
    """

    cells: list[tuple[Literal["code", "markdown"], list[str]]] = []
    for cell_type, source_lines in _parse_percent_script(source_text):
        if cell_type == "markdown":
            cells.append((cell_type, source_lines))
            continue
        cells.extend(_split_comment_markdown_blocks(source_lines))
    if not cells:
        cells.append(("code", []))
    return cells


def _split_comment_markdown_blocks(
    source_lines: list[str],
) -> list[tuple[Literal["code", "markdown"], list[str]]]:
    """Выносит верхнеуровневые ``#``-блоки из code-ячейки в markdown.

    Args:
        source_lines: Строки code-ячейки после разбора ``# %%``.

    Returns:
        Code- и markdown-ячейки в исходном порядке.
    """

    cells: list[tuple[Literal["code", "markdown"], list[str]]] = []
    current_type: Literal["code", "markdown"] = "code"
    current_lines: list[str] = []

    def flush_current_cell() -> None:
        """Добавляет непустую накопленную ячейку в ``cells``.

        Args:
            Отсутствуют.

        Returns:
            ``None``.
        """

        if any(line.strip() for line in current_lines):
            cells.append((current_type, current_lines.copy()))
        current_lines.clear()

    for line in source_lines:
        next_type: Literal["code", "markdown"] = (
            "markdown" if line.startswith("#") else "code"
        )
        if next_type != current_type:
            flush_current_cell()
            current_type = next_type
        current_lines.append(line)

    flush_current_cell()
    return cells


def _split_unmarked_code_from_markdown_cell(
    source_lines: list[str],
) -> list[tuple[Literal["code", "markdown"], list[str]]]:
    """Отделяет code-хвост из markdown-ячейки с comment-markdown строками.

    Args:
        source_lines: Строки markdown-ячейки после маркера ``# %% [markdown]``.

    Returns:
        Список из markdown-ячейки и, при наличии, следующей code-ячейки.
    """

    cells: list[tuple[Literal["code", "markdown"], list[str]]] = []
    markdown_lines: list[str] = []
    code_lines: list[str] = []
    pending_blank_lines: list[str] = []
    seen_comment_markdown = False
    is_code_tail = False

    for line in source_lines:
        if is_code_tail:
            code_lines.append(line)
            continue

        if not line.strip():
            pending_blank_lines.append(line)
            continue

        if line.startswith("#"):
            markdown_lines.extend(pending_blank_lines)
            pending_blank_lines.clear()
            markdown_lines.append(line)
            seen_comment_markdown = True
            continue

        if seen_comment_markdown:
            markdown_lines.extend(pending_blank_lines)
            pending_blank_lines.clear()
            code_lines.append(line)
            is_code_tail = True
            continue

        markdown_lines.extend(pending_blank_lines)
        pending_blank_lines.clear()
        markdown_lines.append(line)

    if not is_code_tail:
        markdown_lines.extend(pending_blank_lines)

    if any(line.strip() for line in markdown_lines):
        cells.append(("markdown", markdown_lines))
    if any(line.strip() for line in code_lines):
        cells.append(("code", code_lines))
    if not cells:
        cells.append(("markdown", source_lines.copy()))
    return cells


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


def _resolve_workspace_file_path(raw_path: str, workspace_root: Path) -> Path:
    """Разрешает путь tool или ОС в локальный путь внутри workspace.

    Args:
        raw_path: Относительный путь, абсолютный путь ОС или workspace-путь tools.
        workspace_root: Корень workspace.

    Returns:
        Абсолютный локальный путь внутри workspace.

    Raises:
        ValueError: Путь пустой или выходит за пределы workspace.
    """

    normalized_path = str(raw_path).strip().replace("\\", "/")
    if not normalized_path:
        raise ValueError("Путь не может быть пустым.")

    relative_path = strip_workspace_tool_prefix(normalized_path, workspace_root)
    if relative_path is not None:
        candidate = (
            workspace_root.joinpath(*Path(relative_path).parts)
            if relative_path
            else workspace_root
        )
    else:
        candidate_path = Path(raw_path)
        candidate = (
            candidate_path
            if candidate_path.is_absolute()
            else workspace_root / candidate_path
        )

    resolved_path = candidate.expanduser().resolve()
    _assert_inside_workspace(resolved_path, workspace_root)
    return resolved_path


def _assert_inside_workspace(path: Path, workspace_root: Path) -> None:
    """Проверяет, что путь находится внутри workspace.

    Args:
        path: Проверяемый путь.
        workspace_root: Корень workspace.

    Returns:
        ``None``.

    Raises:
        ValueError: Путь находится вне workspace.
    """

    try:
        path.relative_to(workspace_root)
    except ValueError:
        raise ValueError(f"Путь должен быть внутри workspace: {path}") from None


def _assert_converted_filename_preserved(source_file: Path, output_file: Path) -> None:
    """Проверяет, что конвертация не переименовывает файл.

    Args:
        source_file: Разрешенный путь исходного файла внутри workspace.
        output_file: Разрешенный путь целевого файла внутри workspace.

    Returns:
        ``None``.

    Raises:
        ValueError: Имя целевого файла без расширения отличается от исходного.
    """

    if source_file.stem != output_file.stem:
        raise ValueError(
            "При конвертации Jupyter Notebook нельзя менять имя файла: "
            f"ожидался stem `{source_file.stem}`, получен `{output_file.stem}`."
        )


def _json_payload(payload: dict[str, Any]) -> str:
    """Сериализует payload tool в JSON-строку.

    Args:
        payload: Словарь результата tool.

    Returns:
        JSON-строка с ``ensure_ascii=False``.
    """

    return json.dumps(payload, ensure_ascii=False)


__all__ = [
    "CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME",
    "ConvertJupyterNotebookInput",
    "ConvertJupyterNotebookTool",
    "build_convert_jupyter_notebook_tool",
    "build_notebook_from_python_text",
    "convert_jupyter_notebook_file",
]
