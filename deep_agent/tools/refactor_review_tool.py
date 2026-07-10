"""Внутренний инструмент ревью изменений файлов.

Содержит:
- REVIEW_REFACTOR_TOOL_NAME: имя tool внутреннего ревью.
- REVIEW_REFACTOR_TOOL_DESCRIPTION: описание tool ``review_refactor``.
- ReviewRefactorInput: схема аргументов tool ``review_refactor``.
- ReviewRefactorTool: tool запуска внутреннего review-agent.
- build_review_refactor_tool: фабрика tool ``review_refactor``.
- _resolve_review_file_path: разрешение workspace-пути редактируемого файла.
- _last_message_text: извлечение финального текста review-agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import FilesystemPermission, create_deep_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from deep_agent.middleware.gigachat_runtime_middleware import ThinkToolMiddleware
from deep_agent.middleware.prompt_logging_middleware import PromptLoggingMiddleware
from deep_agent.middleware.tool_description_middleware import PromptToolFilterMiddleware
from deep_agent.execution.filesystem_backend import (
    Utf8FilesystemBackend,
    review_snapshot_path_for_file,
)
from deep_agent.agent_settings import (
    load_agent_settings,
    strip_workspace_tool_prefix,
    workspace_tool_path,
)
from deep_agent.prompts.refactor_review_prompt import (
    REVIEW_REFACTOR_AGENT_PROMPT,
    build_refactor_review_prompt,
)

REVIEW_REFACTOR_TOOL_NAME = "review_refactor"
REVIEW_REFACTOR_TOOL_DESCRIPTION = (
    "Проведи внутреннее ревью изменения существующего файла по сохраненному snapshot. "
    "Ревью возвращает короткий текст с ошибками, замечаниями и рекомендациями; "
    "файлы не изменяются."
)


class ReviewRefactorInput(BaseModel):
    """Аргументы tool ``review_refactor`` для внутреннего ревью изменения файла.

    Attributes:
        user_request: Исходная задача пользователя, относительно которой проверяется правка.
        edited_path: Путь измененного файла внутри workspace.
    """

    user_request: str = Field(
        description="Исходная задача пользователя, относительно которой нужно проверить изменение.",
    )
    edited_path: str = Field(
        description="Путь измененного файла внутри workspace.",
    )


class ReviewRefactorTool(BaseTool):
    """Запускает read-only review-agent для сравнения snapshot и текущего файла.

    Args:
        model: Chat model LangChain для внутреннего review-agent.
        workspace_root: Корень workspace, где находятся файлы и snapshot.

    Returns:
        ``None``. Результат ревью возвращается методом ``_run`` обычным текстом.
    """

    name: str = REVIEW_REFACTOR_TOOL_NAME
    description: str = REVIEW_REFACTOR_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ReviewRefactorInput

    _model: Any = PrivateAttr()
    _workspace_root: Path = PrivateAttr()
    _review_agent: Any = PrivateAttr(default=None)

    def __init__(self, *, model: Any, workspace_root: str | Path | None = None) -> None:
        """Создает tool внутреннего ревью.

        Args:
            model: Chat model LangChain, используемая review-agent.
            workspace_root: Корень workspace. Если ``None``, берется из настроек.

        Returns:
            ``None``.
        """

        super().__init__()
        resolved_workspace_root = workspace_root or load_agent_settings().workspace_root
        self._model = model
        self._workspace_root = Path(resolved_workspace_root).expanduser().resolve()

    def _run(self, user_request: str, edited_path: str, **_: Any) -> str:
        """Выполняет ревью измененного файла относительно сохраненного snapshot.

        Args:
            user_request: Исходная задача пользователя.
            edited_path: Путь измененного файла внутри workspace.
            **_: Дополнительные аргументы LangChain, которые игнорируются.

        Returns:
            Текст ревью или сообщение, почему ревью не было выполнено.
        """

        try:
            edited_file = _resolve_review_file_path(edited_path, self._workspace_root)
            snapshot_file = review_snapshot_path_for_file(edited_file, self._workspace_root)
        except ValueError as error:
            return f"Ревью не выполнено: {error}"

        if not snapshot_file.exists():
            return (
                "Ревью не выполнено: исходный snapshot для файла не найден. "
                "Если файл новый, сравнение с исходной версией не требуется."
            )
        if not edited_file.exists():
            return "Ревью не выполнено: измененный файл не найден."

        original_path = workspace_tool_path(snapshot_file, self._workspace_root)
        current_path = workspace_tool_path(edited_file, self._workspace_root)
        prompt = build_refactor_review_prompt(
            user_request=user_request,
            original_path=original_path,
            current_path=current_path,
        )
        result = self._get_review_agent().invoke({"messages": [HumanMessage(content=prompt)]})
        return _last_message_text(result)

    async def _arun(self, user_request: str, edited_path: str, **kwargs: Any) -> str:
        """Выполняет асинхронное ревью через синхронную реализацию.

        Args:
            user_request: Исходная задача пользователя.
            edited_path: Путь измененного файла внутри workspace.
            **kwargs: Дополнительные аргументы LangChain.

        Returns:
            Текст ревью.
        """

        return self._run(user_request=user_request, edited_path=edited_path, **kwargs)

    def _get_review_agent(self) -> Any:
        """Возвращает лениво созданный compiled review-agent.

        Returns:
            Скомпилированный read-only DeepAgent для внутреннего ревью.
        """

        if self._review_agent is None:
            review_backend = Utf8FilesystemBackend(
                root_dir=self._workspace_root,
                virtual_mode=True,
            )
            self._review_agent = create_deep_agent(
                model=self._model,
                tools=[],
                system_prompt=REVIEW_REFACTOR_AGENT_PROMPT,
                backend=review_backend,
                middleware=[
                    ThinkToolMiddleware(),
                    PromptToolFilterMiddleware(
                        (
                            "ls",
                            "write_file",
                            "edit_file",
                            "glob",
                            "grep",
                            "execute",
                            "write_todos",
                            "task",
                        )
                    ),
                    PromptLoggingMiddleware(
                        log_dir=Path("debug_prompts"),
                        agent_name="review-refactor-agent",
                    ),
                ],
                permissions=[
                    FilesystemPermission(
                        operations=["write"],
                        paths=["/**"],
                        mode="deny",
                    )
                ],
                subagents=[],
                checkpointer=False,
            )
        return self._review_agent


def build_review_refactor_tool(
    *,
    model: Any,
    workspace_root: str | Path | None = None,
) -> ReviewRefactorTool:
    """Собирает tool ``review_refactor``.

    Args:
        model: Chat model LangChain для внутреннего review-agent.
        workspace_root: Корень workspace для чтения файлов и snapshot.

    Returns:
        Экземпляр ``ReviewRefactorTool``.
    """

    return ReviewRefactorTool(model=model, workspace_root=workspace_root)


def _resolve_review_file_path(raw_path: str, workspace_root: Path) -> Path:
    """Разрешает workspace-путь измененного файла в реальный путь.

    Args:
        raw_path: Путь из tool-вызова.
        workspace_root: Корень workspace.

    Returns:
        Реальный путь внутри workspace.

    Raises:
        ValueError: Путь пустой или выходит за пределы workspace.
    """

    normalized_path = str(raw_path or "").strip().replace("\\", "/")
    if not normalized_path:
        raise ValueError("путь измененного файла пустой")

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
    try:
        resolved_path.relative_to(workspace_root.resolve())
    except ValueError:
        raise ValueError(f"путь находится вне workspace: {resolved_path}") from None
    return resolved_path


def _last_message_text(result: Any) -> str:
    """Извлекает текст последнего сообщения из результата review-agent.

    Args:
        result: Результат ``invoke`` compiled DeepAgent.

    Returns:
        Текст последнего сообщения или строковое представление результата.
    """

    messages = result.get("messages") if isinstance(result, dict) else None
    if messages:
        content = getattr(messages[-1], "content", "")
        return content if isinstance(content, str) else str(content)
    return str(result)


__all__ = [
    "REVIEW_REFACTOR_TOOL_NAME",
    "REVIEW_REFACTOR_TOOL_DESCRIPTION",
    "ReviewRefactorInput",
    "ReviewRefactorTool",
    "build_review_refactor_tool",
]
