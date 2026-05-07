"""
Модуль инициализации агента планировщика.

Содержит функции для загрузки контекста навыков из файловой системы
и инициализации начального состояния агента с предпросмотром переменных
и доступных навыков.
"""

from pathlib import Path
from typing import Any, Optional

import aiofiles
import pandas as pd
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from ..models import AgentState
from ..runtime.sandbox import PythonSandboxProtocol
from ..services.lineage_service import LineageService
from ..services.skills_service import SkillsService

# Константы конфигурации
DEFAULT_MAX_PREVIEW_CHARS = 1700
ALLOWED_SKILL_EXTENSIONS = {".txt", ".md"}
SKILL_SEPARATORS = ("\n---\n", "---")
FILE_ENCODINGS = ("utf-8", "utf-8-sig", "cp1251")
DEFAULT_FILESYSTEM_CONTEXT = {
    "workspace_root": ".",
    "sources_dir": ".",
    "contexts_dir": ".",
    "skills_dir": ".",
}
MAX_EMPTY_COLUMNS_IN_SCHEMA = 20


async def _read_text_with_fallback(path: Path) -> str:
    """
    Асинхронное чтение текстового файла с попыткой различных кодировок.

    Args:
        path: Путь к файлу для чтения

    Returns:
        Содержимое файла или пустая строка в случае ошибки
    """
    for encoding in FILE_ENCODINGS:
        try:
            async with aiofiles.open(path, mode="r", encoding=encoding) as f:
                return await f.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def _extract_preview(content: str, separators: tuple[str, ...] = SKILL_SEPARATORS) -> str:
    """
    Извлечение превью из содержимого файла до разделителя.

    Args:
        content: Полное содержимое файла
        separators: Кортеж разделителей для поиска (по приоритету)

    Returns:
        Извлеченное превью или полное содержимое, если разделитель не найден
    """
    normalized = content.replace("\r\n", "\n")

    for separator in separators:
        if separator in normalized:
            preview, _ = normalized.split(separator, maxsplit=1)
            return preview.strip()

    return normalized.strip()


async def _load_skill_previews(
        contexts_dir: str,
        max_chars: int = DEFAULT_MAX_PREVIEW_CHARS,
        allowed_extensions: set[str] = ALLOWED_SKILL_EXTENSIONS,
        skills_service: SkillsService | None = None,
) -> dict[str, str]:
    """
    Асинхронная загрузка превью навыков из директории skills.

    Args:
        contexts_dir: Путь к директории с skills или контекстами
        max_chars: Максимальное количество символов для превью
        allowed_extensions: Множество разрешенных расширений файлов
        skills_service: Сервис skills, если он уже создан фабрикой агента

    Returns:
        Словарь с именами файлов и их превью
    """
    if skills_service is not None:
        return skills_service.build_skill_previews()

    path = Path(contexts_dir)
    if not path.exists() or not path.is_dir():
        return {}

    if any(path.rglob("SKILL.md")):
        return SkillsService(path).build_skill_previews()

    previews: dict[str, str] = {}

    for item in sorted(path.iterdir()):
        if not item.is_file() or item.suffix.lower() not in allowed_extensions:
            continue

        content = await _read_text_with_fallback(item)
        if not content.strip():
            continue

        preview = _extract_preview(content)
        compact_preview = " ".join(preview.split())

        if len(compact_preview) > max_chars:
            compact_preview = f"{compact_preview[:max_chars]}..."

        previews[item.name] = compact_preview

    return previews


def _enhance_variable_previews_with_dataframe_quality(
        sandbox: PythonSandboxProtocol,
        previews: dict[str, str],
) -> dict[str, str]:
    globals_dict = getattr(sandbox, "globals", None)
    if not isinstance(globals_dict, dict):
        return previews

    enhanced = dict(previews)
    for name, value in globals_dict.items():
        if not isinstance(value, pd.DataFrame):
            continue
        quality = _dataframe_quality_summary(value)
        base = enhanced.get(name, "")
        enhanced[name] = f"{base}\n{quality}" if base else quality
    return enhanced


def _dataframe_quality_summary(df: pd.DataFrame) -> str:
    row_count, column_count = df.shape
    empty_counts = _dataframe_empty_counts(df)
    columns_with_empty = {
        str(column): int(count)
        for column, count in empty_counts.items()
        if int(count) > 0
    }
    total_empty = sum(columns_with_empty.values())
    if columns_with_empty:
        limited = dict(list(columns_with_empty.items())[:MAX_EMPTY_COLUMNS_IN_SCHEMA])
        omitted = max(0, len(columns_with_empty) - len(limited))
        columns_text = ", ".join(
            f"{column}={count}" for column, count in limited.items()
        )
        if omitted:
            columns_text += f", ... +{omitted} more columns"
    else:
        columns_text = "none"

    return (
        "DataFrame quality: "
        f"rows={row_count}; columns={column_count}; "
        f"empty_cells={total_empty}; "
        f"columns_with_empty={len(columns_with_empty)}; "
        f"empty_by_column={columns_text}"
    )


def _dataframe_empty_counts(df: pd.DataFrame) -> dict[Any, int]:
    counts: dict[Any, int] = {}
    for column in df.columns:
        series = df[column]
        null_count = int(series.isna().sum())
        empty_string_count = 0
        if series.dtype == "object" or pd.api.types.is_string_dtype(series):
            non_null = series.dropna()
            empty_string_count = int(
                non_null.astype(str).str.strip().eq("").sum()
            )
        counts[column] = null_count + empty_string_count
    return counts


async def initializer_node(
        state: AgentState,
        sandbox: PythonSandboxProtocol,
        filesystem_context: Optional[dict[str, str]] = None,
        lineage_service: Optional[LineageService] = None,
        skills_service: Optional[SkillsService] = None,
        max_preview_chars: int = DEFAULT_MAX_PREVIEW_CHARS,
) -> Command:
    """
    Узел инициализации агента планировщика.

    Загружает текущее состояние песочницы, контекст файловой системы
    и превью доступных навыков для передачи планировщику.

    Args:
        state: Текущее состояние агента
        sandbox: Экземпляр песочницы Python для выполнения кода
        filesystem_context: Опциональный контекст файловой системы (пути)
        lineage_service: Опциональный сервис для создания ResearchRun и стартовых nodes
        skills_service: Опциональный сервис skills для загрузки preview навыков
        max_preview_chars: Максимальная длина превью навыков

    Returns:
        Command для перехода к узлу планировщика с обновленным состоянием
    """
    current_vars = await sandbox.get_all_variable_previews()
    current_vars = _enhance_variable_previews_with_dataframe_quality(
        sandbox,
        current_vars,
    )
    global_keys = list(current_vars.keys())

    fs_context = DEFAULT_FILESYSTEM_CONTEXT.copy()
    if filesystem_context:
        fs_context.update(filesystem_context)

    skill_previews = await _load_skill_previews(
        contexts_dir=fs_context.get("skills_dir", fs_context["contexts_dir"]),
        max_chars=max_preview_chars,
        skills_service=skills_service,
    )

    lineage_update = _create_initial_lineage(
        state=state,
        filesystem_context=fs_context,
        data_schemas=current_vars,
        skill_previews=skill_previews,
        lineage_service=lineage_service,
    )

    return Command(
        goto="context_builder",
        update={
            **lineage_update,
            "data_schemas": current_vars,
            "global_vars": global_keys,
            "filesystem_context": fs_context,
            "skill_previews": skill_previews,
        },
    )


def _get_initial_user_query(state: AgentState) -> str:
    if state.initial_user_query:
        return state.initial_user_query

    first_human = next(
        (msg for msg in state.messages if isinstance(msg, HumanMessage)),
        None,
    )
    return str(first_human.content) if first_human else ""


def _create_initial_lineage(
        *,
        state: AgentState,
        filesystem_context: dict[str, str],
        data_schemas: dict[str, str],
        skill_previews: dict[str, str],
        lineage_service: Optional[LineageService],
) -> dict[str, object]:
    """Создает lineage для нового запуска или продолжает уже существующий run.

    Args:
        state: Текущее состояние агента перед context_builder.
        filesystem_context: Нормализованный контекст рабочих директорий.
        data_schemas: Preview доступных переменных и таблиц.
        skill_previews: Preview доступных навыков.
        lineage_service: Сервис lineage или ``None``.

    Returns:
        Update для LangGraph state с run_id, current_node_id, parent_node_ids и lineage_events.
    """

    if lineage_service is None:
        return {}

    initial_user_query = _get_initial_user_query(state)
    if state.run_id and lineage_service.get_run(state.run_id) is not None:
        return _create_existing_run_context_lineage(
            state=state,
            initial_user_query=initial_user_query,
            filesystem_context=filesystem_context,
            data_schemas=data_schemas,
            skill_previews=skill_previews,
            lineage_service=lineage_service,
        )

    return _create_new_run_lineage(
        state=state,
        initial_user_query=initial_user_query,
        filesystem_context=filesystem_context,
        data_schemas=data_schemas,
        skill_previews=skill_previews,
        lineage_service=lineage_service,
    )


def _create_existing_run_context_lineage(
        *,
        state: AgentState,
        initial_user_query: str,
        filesystem_context: dict[str, str],
        data_schemas: dict[str, str],
        skill_previews: dict[str, str],
        lineage_service: LineageService,
) -> dict[str, object]:
    """Добавляет context_snapshot в уже существующий ResearchRun.

    Args:
        state: Восстановленное состояние существующего запуска или ветки.
        initial_user_query: Текущий пользовательский запрос ветки/продолжения.
        filesystem_context: Нормализованный контекст рабочих директорий.
        data_schemas: Preview доступных переменных и таблиц.
        skill_previews: Preview доступных навыков.
        lineage_service: Сервис lineage.

    Returns:
        Update для LangGraph state без создания нового ResearchRun.
    """

    parent_ids = state.parent_node_ids or (
        [state.current_node_id] if state.current_node_id else []
    )
    snapshot = state.model_copy(
        update={
            "run_id": state.run_id,
            "initial_user_query": state.initial_user_query or initial_user_query,
            "data_schemas": data_schemas,
            "filesystem_context": filesystem_context,
            "skill_previews": skill_previews,
        },
        deep=True,
    )
    context_node = lineage_service.create_state_node(
        run_id=state.run_id,
        node_type="context_snapshot",
        title="Context snapshot",
        parent_ids=parent_ids,
        status="succeeded",
        summary=(
            f"Resumed run context. Loaded {len(data_schemas)} sandbox variable previews, "
            f"{len(skill_previews)} skill previews, and filesystem context."
        ),
        state=snapshot,
        created_by="system",
        metadata={
            "resumed_existing_run": True,
            "data_schema_count": len(data_schemas),
            "skill_preview_count": len(skill_previews),
            "filesystem_context": filesystem_context,
        },
    )

    return {
        "run_id": state.run_id,
        "current_node_id": context_node.node_id,
        "parent_node_ids": [context_node.node_id],
        "initial_user_query": state.initial_user_query or initial_user_query,
        "lineage_events": [context_node.model_dump(mode="json")],
    }


def _create_new_run_lineage(
        *,
        state: AgentState,
        initial_user_query: str,
        filesystem_context: dict[str, str],
        data_schemas: dict[str, str],
        skill_previews: dict[str, str],
        lineage_service: LineageService,
) -> dict[str, object]:
    """Создает новый ResearchRun и стартовые lineage nodes.

    Args:
        state: Текущее состояние агента без существующего run_id.
        initial_user_query: Исходный пользовательский запрос.
        filesystem_context: Нормализованный контекст рабочих директорий.
        data_schemas: Preview доступных переменных и таблиц.
        skill_previews: Preview доступных навыков.
        lineage_service: Сервис lineage.

    Returns:
        Update для LangGraph state с новым run_id и двумя стартовыми lineage nodes.
    """

    run = lineage_service.create_run(
        initial_user_query=initial_user_query,
        session_id=state.session_id,
        user_id=state.user_id,
    )

    snapshot = state.model_copy(
        update={
            "run_id": run.run_id,
            "initial_user_query": state.initial_user_query or initial_user_query,
            "data_schemas": data_schemas,
            "filesystem_context": filesystem_context,
            "skill_previews": skill_previews,
        },
        deep=True,
    )
    run_started_node = lineage_service.create_state_node(
        run_id=run.run_id,
        node_type="run_started",
        title="Run started",
        status="succeeded",
        summary=initial_user_query[:500],
        state=snapshot,
        created_by="system",
        metadata={
            "session_id": state.session_id,
            "user_id": state.user_id,
        },
    )
    context_snapshot = snapshot.model_copy(
        update={
            "current_node_id": run_started_node.node_id,
            "parent_node_ids": [run_started_node.node_id],
        },
        deep=True,
    )
    context_node = lineage_service.create_state_node(
        run_id=run.run_id,
        node_type="context_snapshot",
        title="Context snapshot",
        parent_ids=[run_started_node.node_id],
        status="succeeded",
        summary=(
            f"Loaded {len(data_schemas)} sandbox variable previews, "
            f"{len(skill_previews)} skill previews, and filesystem context."
        ),
        state=context_snapshot,
        created_by="system",
        metadata={
            "data_schema_count": len(data_schemas),
            "skill_preview_count": len(skill_previews),
            "filesystem_context": filesystem_context,
        },
    )

    return {
        "run_id": run.run_id,
        "current_node_id": context_node.node_id,
        "parent_node_ids": [context_node.node_id],
        "initial_user_query": state.initial_user_query or initial_user_query,
        "lineage_events": [
            run_started_node.model_dump(mode="json"),
            context_node.model_dump(mode="json"),
        ],
    }
