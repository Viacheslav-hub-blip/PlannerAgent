"""Инструмент конвертации Jupyter Notebook для coding-agent.

Содержит:
- CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME: имя LangChain tool.
- CONVERT_JUPYTER_NOTEBOOK_DESCRIPTION: описание tool для модели.
- ConvertJupyterNotebookInput: схема аргументов tool ``convert_jupyter_notebook``.
- ConvertJupyterNotebookTool: LangChain tool конвертации ``.py`` percent-script и ``.ipynb``.
- build_convert_jupyter_notebook_tool: фабрика tool ``convert_jupyter_notebook``.
- convert_jupyter_notebook_file: конвертация файла notebook или percent-script.
- _py_to_ipynb: преобразование ``.py`` percent-script в структуру notebook.
- _ipynb_to_py: преобразование структуры notebook в ``.py`` percent-script.
- _parse_percent_script: разбор ``# %%`` ячеек в Python-файле.
- _normalize_notebook_source: нормализация содержимого ячейки notebook.
- _markdown_lines_from_percent_cell: преобразование markdown-комментариев в текст ячейки.
- _percent_lines_from_markdown_cell: преобразование markdown-ячейки в comment-блок.
- _resolve_workspace_file_path: разрешение workspace-пути в локальный файл.
- _assert_inside_workspace: проверка принадлежности пути workspace.
- _json_payload: сериализация результата tool в JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from deep_agent.settings import (
    load_deep_agent_settings,
    strip_workspace_tool_prefix,
    workspace_tool_path,
)

CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME = "convert_jupyter_notebook"
CONVERT_JUPYTER_NOTEBOOK_DESCRIPTION = """
convert_jupyter_notebook
---
Конвертирует Jupyter notebook между `.py` percent-script и `.ipynb`.

Use when:
- нужно создать `.ipynb` файл: сначала создай `.py` через `write_file` с ячейками `# %%` и `# %% [markdown]`, затем вызови `convert_jupyter_notebook` с `mode="py_to_ipynb"`;
- нужно изменить существующий notebook: сначала вызови `mode="ipynb_to_py"`, отредактируй полученный `.py`, затем вызови `mode="py_to_ipynb"`;
- нужно получить читаемый Python-файл из `.ipynb` без выполнения notebook.

Parameters:
- `mode`: `py_to_ipynb` или `ipynb_to_py`;
- `source_path`: исходный файл внутри workspace;
- `output_path`: целевой файл внутри workspace;
- `kernel_name`: имя kernel для `.ipynb`, обычно `python3`;
- `overwrite`: можно ли перезаписать существующий целевой файл.

Rules:
- Для `py_to_ipynb` исходный файл должен иметь расширение `.py`, целевой файл `.ipynb`.
- Для `ipynb_to_py` исходный файл должен иметь расширение `.ipynb`, целевой файл `.py`.
- Инструмент только конвертирует файлы и не выполняет код notebook.
- При `ipynb_to_py` outputs и execution_count игнорируются.

Result:
Возвращает JSON со статусом, режимом, workspace-путями созданных файлов и числом ячеек.
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
        description="Целевой файл внутри workspace. Для `py_to_ipynb` это `.ipynb`, для `ipynb_to_py` это `.py`.",
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
        resolved_workspace_root = workspace_root or load_deep_agent_settings().workspace_root
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


def _py_to_ipynb(source_text: str, *, kernel_name: str) -> dict[str, Any]:
    """Преобразует ``.py`` percent-script в JSON-структуру Jupyter Notebook.

    Args:
        source_text: Текст Python-файла с маркерами ``# %%``.
        kernel_name: Имя kernel для metadata notebook.

    Returns:
        Словарь notebook формата nbformat v4.
    """

    cells = []
    for cell_type, source_lines in _parse_percent_script(source_text):
        if cell_type == "markdown":
            cells.append(
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": _markdown_lines_from_percent_cell(source_lines),
                }
            )
        else:
            cells.append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": source_lines,
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
            output_lines.extend(_percent_lines_from_markdown_cell(source_lines))
        else:
            output_lines.append("# %%\n")
            output_lines.extend(source_lines)
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

    for line in source_text.splitlines(keepends=True):
        stripped_line = line.strip()
        if stripped_line.startswith("# %%"):
            if has_current_cell or current_lines:
                cells.append((current_type, current_lines))
            current_type = "markdown" if "[markdown]" in stripped_line.lower() else "code"
            current_lines = []
            has_current_cell = True
            continue
        current_lines.append(line)

    if has_current_cell or current_lines:
        cells.append((current_type, current_lines))
    if not cells:
        cells.append(("code", []))
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
    "convert_jupyter_notebook_file",
]
