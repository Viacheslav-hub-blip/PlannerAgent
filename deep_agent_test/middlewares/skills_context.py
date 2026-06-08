"""Middleware предзагрузки domain context из локальных skills.

Содержит:
- SelectedSkillPaths: structured schema выбора релевантных skills.
- SkillSelectionOutcome: технический результат выбора skills.
- PreloadedSkillsSelection: загруженный контекст и метаданные выбора.
- PreloadedSkillsContextMiddleware: middleware чтения skills и добавления context в prompt.
- PreloadedSkillsContextMiddleware.before_agent: чтение skills и запись context в state.
- PreloadedSkillsContextMiddleware.wrap_model_call: добавление skills context в system prompt.
- build_preloaded_skills_context: автосканирование папки skills и сборка compact context.
- select_relevant_skill_paths_with_llm: выбор релевантных skills по index через LLM.
- _invoke_skill_selector: один structured-output вызов selector.
- _validate_selected_paths: техническая валидация выбранных путей.
- _compact_selection_error: сокращение диагностического текста selector.
- discover_skill_context_files: поиск файлов SKILL.md для предзагрузки.
- build_skills_index: построение компактного index skills.
- _read_context_file: чтение одного context-файла с ограничением размера.
- _latest_user_query: получение последнего пользовательского запроса из state.
- _parse_skill_index_entry: извлечение имени и описания skill.
- _virtual_skill_path: построение виртуального пути skills для найденного файла.
- _normalize_virtual_dir: нормализация виртуальной папки skills.
- _truncate_text: ограничение длины текста skill.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from deepagents.middleware._utils import append_to_system_message

from deep_agent_test.core.state import AnalyticsAgentState
from deep_agent_test.core.prompts import (
    PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
)


class SelectedSkillPaths(BaseModel):
    """Результат выбора релевантных skills перед запуском агента.

    Attributes:
        paths: Виртуальные пути выбранных файлов ``SKILL.md``.
        selection_reason: Краткое объяснение выбора skills.
    """

    paths: list[str] = Field(
        default_factory=list,
        description=(
            "Список виртуальных путей выбранных skill-файлов. "
            "Допустим пустой список или любое необходимое число существующих путей."
        ),
    )
    selection_reason: str = Field(
        default="",
        description="Кратко объясни, почему выбран этот набор skills или почему skills не нужны.",
    )


class SkillSelectionOutcome(BaseModel):
    """Технический результат LLM-выбора skills.

    Attributes:
        selection_status: ``success`` или ``selection_failed``.
        selected_paths: Проверенные пути из переданного index.
        selection_reason: Объяснение selector или причина отсутствия skills.
        validation_errors: Ошибки формата, неизвестные пути или дубли.
        retry_performed: Выполнялась ли корректирующая попытка.
        error: Краткая финальная диагностика при неуспехе.
    """

    selection_status: Literal["success", "selection_failed"]
    selected_paths: list[str] = Field(default_factory=list)
    selection_reason: str = ""
    validation_errors: list[str] = Field(default_factory=list)
    retry_performed: bool = False
    error: str = ""


@dataclass(frozen=True)
class PreloadedSkillsSelection:
    """Контекст и метаданные предварительного выбора skills.

    Attributes:
        context: Объединённый текст выбранных ``SKILL.md``.
        paths: Фактически загруженные виртуальные пути.
        outcome: Технический результат selector.
    """

    context: str
    paths: list[str]
    outcome: SkillSelectionOutcome


@dataclass(frozen=True)
class PreloadedSkillsContextMiddleware(AgentMiddleware[AnalyticsAgentState]):
    """Автоматически загружает файлы ``SKILL.md`` до первого рассуждения модели.

    Используется в двух режимах, которые делят один кэш через ``shared_selection``:

    - ``select_skills=True`` (supervisor): выбирает релевантные skills через LLM один раз
      на пользовательский запрос и кладёт результат в общий кэш.
    - ``select_skills=False`` (subagent): не вызывает LLM, а переиспользует выбор
      supervisor-а из общего кэша, чтобы в субагентов попадали те же skills.

    Args:
        skills_root: Локальная папка проекта, которую нужно рекурсивно просканировать.
        skills_virtual_dir: Виртуальная папка skills внутри DeepAgents backend.
        max_chars_per_file: Максимальная длина текста одного ``SKILL.md`` в context.
        model: Chat model для выбора релевантных skills по index. Если ``None``,
            выбор завершается со статусом ``selection_failed``.
        select_skills: Режим выбора. ``True`` — выбирать и кэшировать (supervisor),
            ``False`` — только переиспользовать кэш supervisor-а (subagent).
        shared_selection: Общий мутируемый кэш выбора skills. Один и тот же словарь нужно
            передать supervisor- и subagent-экземплярам, чтобы они делили выбор.
        prompt_template: Шаблон системного блока с ``{context}``, соответствующий tools
            текущего агента.

    Returns:
        Middleware, который добавляет compact domain context в state и system message.
    """

    skills_root: Path
    skills_virtual_dir: str = "/skills/"
    max_chars_per_file: int = 18000
    model: Any | None = None
    select_skills: bool = True
    shared_selection: dict[str, Any] = field(default_factory=dict, compare=False)
    prompt_template: str = PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE

    state_schema = AnalyticsAgentState

    def before_agent(
        self,
        state: AnalyticsAgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Читает skills и сохраняет context в state перед запуском агента.

        Args:
            state: Текущий state агента.
            runtime: Runtime LangGraph текущего запуска.

        Returns:
            Обновление state с context и списком прочитанных skill-файлов.
        """

        user_query = _latest_user_query(state)
        if state.get("skills_context_loaded") and state.get("preloaded_skills_selection_user_key") == user_query:
            return None

        selection = self._resolve_selection(user_query)
        if selection is None:
            return None

        outcome = selection.outcome
        return {
            "skills_context_loaded": True,
            "preloaded_skills_selection_user_key": user_query,
            "preloaded_skill_paths": selection.paths,
            "preloaded_skills_context": selection.context,
            "preloaded_skills_selection_status": outcome.selection_status,
            "preloaded_skills_selection_reason": outcome.selection_reason,
            "preloaded_skills_selection_error": outcome.error,
            "preloaded_skills_selection_retry": outcome.retry_performed,
            "preloaded_skills_selection_validation_errors": outcome.validation_errors,
        }

    def _resolve_selection(
        self,
        user_query: str,
    ) -> PreloadedSkillsSelection | None:
        """Возвращает выбор skills из кэша или вычисляет его (только для supervisor).

        Args:
            user_query: Последний пользовательский запрос текущего агента.

        Returns:
            Результат предзагрузки или ``None``, если выбор
            недоступен (субагент без кэша supervisor-а).
        """

        cached = self.shared_selection.get("entry")

        if not self.select_skills:
            if cached is None:
                return None
            return cached

        if cached is not None and self.shared_selection.get("user_query") == user_query:
            return cached

        selection = build_preloaded_skills_context(
            skills_root=self.skills_root,
            skills_virtual_dir=self.skills_virtual_dir,
            max_chars_per_file=self.max_chars_per_file,
            model=self.model,
            user_query=user_query,
        )
        self.shared_selection["user_query"] = user_query
        self.shared_selection["entry"] = selection
        return selection

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Any,
    ) -> ModelResponse:
        """Добавляет предзагруженный domain context в system message.

        Args:
            request: Запрос модели с текущим state.
            handler: Функция реального вызова модели.

        Returns:
            Ответ модели без изменений.
        """

        context = request.state.get("preloaded_skills_context")
        selection_status = request.state.get("preloaded_skills_selection_status")
        selection_error = request.state.get("preloaded_skills_selection_error")
        if not context and selection_status != "selection_failed":
            return handler(request)

        system_message = request.system_message
        if selection_status == "selection_failed":
            system_message = append_to_system_message(
                system_message,
                (
                    "## Ошибка выбора domain context\n\n"
                    "Автоматический selector не смог корректно выбрать skills после одной "
                    "исправляющей попытки. Skills не загружены автоматически. "
                    f"Диагностика: {selection_error or 'неизвестная ошибка selector'}."
                ),
            )
        if context:
            system_message = append_to_system_message(
                system_message,
                self.prompt_template.format(context=context),
            )
        return handler(request.override(system_message=system_message))


def build_preloaded_skills_context(
    skills_root: Path,
    skills_virtual_dir: str,
    max_chars_per_file: int,
    model: Any | None = None,
    user_query: str = "",
) -> PreloadedSkillsSelection:
    """Сканирует папку skills и собирает compact context из файлов ``SKILL.md``.

    Args:
        skills_root: Локальная папка проекта ``skills`` или другая переданная папка.
        skills_virtual_dir: Виртуальная папка, через которую DeepAgents видит skills.
        max_chars_per_file: Максимальная длина текста одного ``SKILL.md``.
        model: Chat model для LLM-выбора skills по index.
        user_query: Последний пользовательский запрос для выбора skills.

    Returns:
        Контекст, загруженные пути и технический результат selector.
    """

    skill_files = discover_skill_context_files(skills_root)
    outcome = select_relevant_skill_paths_with_llm(
        model=model,
        user_query=user_query,
        skill_files=skill_files,
        skills_root=skills_root,
        skills_virtual_dir=skills_virtual_dir,
    )
    selected_path_set = set(outcome.selected_paths)
    blocks: list[str] = []
    loaded_paths: list[str] = []
    for skill_path in skill_files:
        virtual_path = _virtual_skill_path(skills_root, skill_path, skills_virtual_dir)
        if virtual_path not in selected_path_set:
            continue
        content = _read_context_file(skill_path, max_chars_per_file)
        if content is None:
            continue
        loaded_paths.append(virtual_path)
        blocks.append(f"### {virtual_path}\n\n{content}")
    return PreloadedSkillsSelection(
        context="\n\n".join(blocks),
        paths=loaded_paths,
        outcome=outcome,
    )


def select_relevant_skill_paths_with_llm(
    *,
    model: Any | None,
    user_query: str,
    skill_files: list[Path],
    skills_root: Path,
    skills_virtual_dir: str,
) -> SkillSelectionOutcome:
    """Выбирает релевантные skills через LLM по компактному index.

    Args:
        model: Chat model с поддержкой ``with_structured_output``.
        user_query: Последний пользовательский запрос.
        skill_files: Найденные файлы ``SKILL.md``.
        skills_root: Корневая папка локальных skills.
        skills_virtual_dir: Виртуальная папка skills внутри DeepAgents.

    Returns:
        Технический результат выбора. Пустой выбор является успешным результатом.
        При ошибке выполняется не более одной корректирующей попытки; fallback на
        полный список skills не используется.
    """

    index = build_skills_index(
        skill_files=skill_files,
        skills_root=skills_root,
        skills_virtual_dir=skills_virtual_dir,
    )
    if not index:
        return SkillSelectionOutcome(
            selection_status="success",
            selected_paths=[],
            selection_reason="Skills Index пуст.",
        )
    if model is None:
        return SkillSelectionOutcome(
            selection_status="selection_failed",
            error="Модель selector не настроена.",
        )
    if not user_query.strip():
        return SkillSelectionOutcome(
            selection_status="selection_failed",
            error="Пользовательский запрос для selector пуст.",
        )

    try:
        try:
            structured_model = model.with_structured_output(
                SelectedSkillPaths,
                method="function_calling",
            )
        except TypeError:
            structured_model = model.with_structured_output(SelectedSkillPaths)
    except Exception as exc:
        return SkillSelectionOutcome(
            selection_status="selection_failed",
            error=_compact_selection_error(exc),
        )

    validation_errors: list[str] = []
    previous_error = ""
    for attempt in range(2):
        try:
            result = _invoke_skill_selector(
                structured_model=structured_model,
                user_query=user_query,
                index=index,
                previous_error=previous_error,
            )
            current_errors = _validate_selected_paths(result.paths, index)
            if not current_errors:
                return SkillSelectionOutcome(
                    selection_status="success",
                    selected_paths=list(result.paths),
                    selection_reason=result.selection_reason.strip(),
                    validation_errors=validation_errors,
                    retry_performed=attempt == 1,
                )
            previous_error = "; ".join(current_errors)
            validation_errors.extend(current_errors)
        except Exception as exc:
            previous_error = _compact_selection_error(exc)
            validation_errors.append(previous_error)

    return SkillSelectionOutcome(
        selection_status="selection_failed",
        selected_paths=[],
        validation_errors=validation_errors,
        retry_performed=True,
        error=previous_error or "Selector вернул некорректный structured output.",
    )


def _invoke_skill_selector(
    *,
    structured_model: Any,
    user_query: str,
    index: list[dict[str, str]],
    previous_error: str = "",
) -> SelectedSkillPaths:
    """Выполняет один structured-output вызов selector.

    Args:
        structured_model: Модель после ``with_structured_output``.
        user_query: Исходный запрос пользователя.
        index: Полный компактный Skills Index.
        previous_error: Ошибка первой попытки для корректирующего вызова.

    Returns:
        Валидированный Pydantic-результат selector.
    """

    correction = ""
    if previous_error:
        correction = (
            "Предыдущий ответ нарушил технический контракт: "
            f"{previous_error}. Исправь формат, не добавляй выдуманные пути и не повторяй пути."
        )
    raw_result = structured_model.invoke(
        [
            SystemMessage(
                content=(
                    "Выбери достаточный набор domain skills для запроса пользователя. "
                    "Можно выбрать от нуля до любого необходимого числа skills. "
                    "Используй только точные пути из переданного index, без дублей. "
                    "Если domain skills не нужны, верни пустой paths и объясни причину. "
                    f"{correction}"
                )
            ),
            HumanMessage(
                content=json.dumps(
                    {
                        "user_query": user_query,
                        "skills_index": index,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            ),
        ]
    )
    return (
        raw_result
        if isinstance(raw_result, SelectedSkillPaths)
        else SelectedSkillPaths.model_validate(raw_result)
    )


def _validate_selected_paths(
    selected_paths: list[str],
    index: list[dict[str, str]],
) -> list[str]:
    """Проверяет только технический контракт выбранных путей.

    Args:
        selected_paths: Пути, возвращённые selector.
        index: Skills Index, переданный selector.

    Returns:
        Список ошибок по неизвестным путям и дублям.
    """

    errors: list[str] = []
    allowed = {item["path"] for item in index}
    unknown = [path for path in selected_paths if path not in allowed]
    if unknown:
        errors.append("Неизвестные пути: " + ", ".join(unknown))

    duplicates = sorted({path for path in selected_paths if selected_paths.count(path) > 1})
    if duplicates:
        errors.append("Дубли путей: " + ", ".join(duplicates))
    return errors


def _compact_selection_error(error: Exception) -> str:
    """Возвращает короткую диагностику ошибки selector.

    Args:
        error: Исключение structured-output вызова.

    Returns:
        Строка с типом исключения и сообщением длиной не более 500 символов.
    """

    message = " ".join(str(error).split())
    compact = f"{type(error).__name__}: {message}" if message else type(error).__name__
    return compact[:500]


def build_skills_index(
    *,
    skill_files: list[Path],
    skills_root: Path,
    skills_virtual_dir: str,
) -> list[dict[str, str]]:
    """Строит компактный index skills для LLM-выбора.

    Args:
        skill_files: Найденные файлы ``SKILL.md``.
        skills_root: Корневая папка локальных skills.
        skills_virtual_dir: Виртуальная папка skills внутри DeepAgents.

    Returns:
        Список словарей с путем, именем и описанием skill.
    """

    index: list[dict[str, str]] = []
    for skill_path in skill_files:
        content = _read_context_file(skill_path, max_chars=4000) or ""
        parsed = _parse_skill_index_entry(content)
        index.append(
            {
                "path": _virtual_skill_path(skills_root, skill_path, skills_virtual_dir),
                "name": parsed.get("name") or skill_path.parent.name,
                "description": parsed.get("description") or "",
                "keywords": parsed.get("keywords") or "",
            }
        )
    return index


def discover_skill_context_files(skills_root: Path) -> list[Path]:
    """Находит файлы ``SKILL.md`` для автоматической предзагрузки.

    Args:
        skills_root: Папка skills, которую нужно просканировать рекурсивно.

    Returns:
        Список файлов ``SKILL.md`` из skill-папок, отсортированный по пути.
    """

    if not skills_root.exists():
        return []
    skill_files = [path for path in skills_root.rglob("SKILL.md") if path.is_file()]
    return sorted(
        skill_files,
        key=lambda path: path.relative_to(skills_root).as_posix().lower(),
    )


def _read_context_file(path: Path, max_chars: int) -> str | None:
    """Читает один context-файл skills и ограничивает его длину.

    Args:
        path: Абсолютный путь к файлу.
        max_chars: Максимальное количество символов для возврата.

    Returns:
        Текст файла или ``None``, если файл не найден.
    """

    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    return _truncate_text(content, max_chars)


def _latest_user_query(state: AnalyticsAgentState) -> str:
    """Извлекает последний пользовательский запрос из state.

    Args:
        state: Текущий state агента.

    Returns:
        Текст последнего HumanMessage или пустая строка.
    """

    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)
        if getattr(message, "type", None) == "human":
            return str(getattr(message, "content", ""))
    return ""


def _parse_skill_index_entry(content: str) -> dict[str, str]:
    """Извлекает имя и описание skill из front matter.

    Args:
        content: Текст ``SKILL.md``.

    Returns:
        Словарь с ключами ``name``, ``description`` и ``keywords`` при наличии данных.
    """

    result: dict[str, str] = {}
    for line in content.splitlines()[:20]:
        if line.startswith("name:"):
            result["name"] = line.split(":", 1)[1].strip().strip('"')
        if line.startswith("description:"):
            result["description"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("keywords:"):
            result["keywords"] = line.split(":", 1)[1].strip().strip('"')
    return result


def _virtual_skill_path(skills_root: Path, path: Path, skills_virtual_dir: str) -> str:
    """Строит виртуальный путь skills для найденного файла.

    Args:
        skills_root: Локальная папка skills.
        path: Найденный markdown-файл внутри ``skills_root``.
        skills_virtual_dir: Виртуальная папка skills внутри DeepAgents backend.

    Returns:
        Виртуальный путь файла для prompt context и логов.
    """

    try:
        relative_path = path.relative_to(skills_root).as_posix()
    except ValueError:
        relative_path = path.name
    return f"{_normalize_virtual_dir(skills_virtual_dir)}{relative_path}"


def _normalize_virtual_dir(value: str) -> str:
    """Нормализует виртуальную папку skills к виду ``/name/``.

    Args:
        value: Виртуальный путь из настроек.

    Returns:
        Виртуальная папка с ведущим и завершающим слешем.
    """

    stripped = value.strip() or "/skills/"
    if not stripped.startswith("/"):
        stripped = f"/{stripped}"
    if not stripped.endswith("/"):
        stripped = f"{stripped}/"
    return stripped


def _truncate_text(text: str, max_chars: int) -> str:
    """Обрезает текст до заданного количества символов.

    Args:
        text: Исходный текст.
        max_chars: Максимальное количество символов.

    Returns:
        Исходный или обрезанный текст с пометкой о сокращении.
    """

    if max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n...[truncated {omitted} chars]"


__all__ = [
    "PreloadedSkillsContextMiddleware",
    "PreloadedSkillsSelection",
    "SelectedSkillPaths",
    "SkillSelectionOutcome",
    "build_preloaded_skills_context",
    "build_skills_index",
    "discover_skill_context_files",
    "select_relevant_skill_paths_with_llm",
]
