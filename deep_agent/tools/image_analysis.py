"""Инструмент анализа изображений через VLM.

Содержит:
- AnalyzeImageInput: схема аргументов инструмента ``analyze_image``.
- AnalyzeImageTool: LangChain tool анализа локальных изображений.
- build_analyze_image_tool: фабрика инструмента анализа изображений.
- _build_default_qwen_vlm_client: ленивый импорт фабрики Qwen VLM.
- _resolve_image_path: преобразование workspace-пути в локальный путь.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from deep_agent.models.vlm import QwenVLMClient
from deep_agent.settings import (
    load_deep_agent_settings,
    strip_workspace_tool_prefix,
)

ANALYZE_IMAGE_TOOL_NAME = "analyze_image"
ANALYZE_IMAGE_SYSTEM_PROMPT = (
    "Ты визуальная модель для анализа изображений, скриншотов, слайдов и документов. "
    "Отвечай на русском языке. Полностью извлекай видимый текст, описывай важные "
    "визуальные элементы и явно отделяй уверенно распознанное от предположений."
)


class AnalyzeImageInput(BaseModel):
    """Аргументы tool ``analyze_image`` для анализа локального изображения.

    Attributes:
        image_path: Абсолютный локальный путь или workspace-путь к изображению.
        query: Запрос к VLM о том, что нужно извлечь или описать.
    """

    image_path: str = Field(
        description=(
            "Путь к изображению. Можно передать абсолютный путь ОС или workspace-путь "
            "вида `/reports/slide.png`, который будет разрешён "
            "относительно настроенного workspace_root."
        ),
    )
    query: str = Field(
        description="Что нужно сделать с изображением: распознать текст, описать слайд или ответить на вопрос.",
    )


class AnalyzeImageTool(BaseTool):
    """LangChain tool анализа изображения через Qwen VLM.

    Args:
        workspace_root: Корень workspace для разрешения виртуальных путей.
        client_factory: Фабрика клиента VLM. Вызывается лениво при первом запросе.
    """

    name: str = ANALYZE_IMAGE_TOOL_NAME
    description: str = """
analyze_image
---
Анализирует локальное изображение через VLM.

Parameters:
- `image_path`: абсолютный путь ОС или workspace-путь к изображению;
- `query`: конкретный запрос, что нужно распознать или описать.

Use when:
- нужно извлечь текст со скриншота, изображения, слайда или документа;
- нужно описать визуальное содержимое изображения;
- пользователь просит ответить на вопрос по картинке.

Do not use:
- для текстовых файлов, таблиц и PDF без предварительного изображения страницы;
- без существующего локального пути к изображению;
- для сетевых URL.

Result:
Возвращает текст VLM. Файл изображения прочитан, визуальный контекст получен и передан агенту.
""".strip()
    args_schema: type[BaseModel] = AnalyzeImageInput

    _workspace_root: Path = PrivateAttr()
    _client_factory: Callable[[], QwenVLMClient] = PrivateAttr()
    _client: QwenVLMClient | None = PrivateAttr(default=None)

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        client_factory: Callable[[], QwenVLMClient] | None = None,
    ) -> None:
        """Создаёт tool анализа изображений.

        Args:
            workspace_root: Корень workspace для виртуальных путей. Если ``None``,
                используется ``workspace_root`` из настроек.
            client_factory: Фабрика клиента VLM.

        Returns:
            ``None``.
        """

        super().__init__()
        resolved_workspace_root = workspace_root or load_deep_agent_settings().workspace_root
        self._workspace_root = Path(resolved_workspace_root).expanduser().resolve()
        self._client_factory = client_factory or _build_default_qwen_vlm_client

    def _get_client(self) -> QwenVLMClient:
        """Возвращает лениво созданный клиент VLM.

        Returns:
            Экземпляр ``QwenVLMClient``.
        """

        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def _run(self, image_path: str, query: str, **_: Any) -> str:
        """Синхронно анализирует изображение через VLM.

        Args:
            image_path: Абсолютный локальный путь или workspace-путь к изображению.
            query: Запрос к VLM.
            **_: Служебные аргументы LangChain, не используются.

        Returns:
            Текстовый ответ VLM или понятное сообщение об ошибке.
        """

        resolved_path = _resolve_image_path(image_path, self._workspace_root)
        if not resolved_path.exists():
            return f"ImageAnalysisError: файл изображения не найден: {resolved_path}"
        if not resolved_path.is_file():
            return f"ImageAnalysisError: путь не является файлом: {resolved_path}"
        return self._get_client().generate_from_image(
            image_path=resolved_path,
            system_prompt=ANALYZE_IMAGE_SYSTEM_PROMPT,
            user_prompt=query,
        )

    async def _arun(self, image_path: str, query: str, **_: Any) -> str:
        """Асинхронно анализирует изображение через VLM.

        Args:
            image_path: Абсолютный локальный путь или workspace-путь к изображению.
            query: Запрос к VLM.
            **_: Служебные аргументы LangChain, не используются.

        Returns:
            Текстовый ответ VLM или понятное сообщение об ошибке.
        """

        resolved_path = _resolve_image_path(image_path, self._workspace_root)
        if not resolved_path.exists():
            return f"ImageAnalysisError: файл изображения не найден: {resolved_path}"
        if not resolved_path.is_file():
            return f"ImageAnalysisError: путь не является файлом: {resolved_path}"
        return await self._get_client().agenerate_from_image(
            image_path=resolved_path,
            system_prompt=ANALYZE_IMAGE_SYSTEM_PROMPT,
            user_prompt=query,
        )


def build_analyze_image_tool(
    *,
    workspace_root: str | Path | None = None,
    client_factory: Callable[[], QwenVLMClient] | None = None,
) -> AnalyzeImageTool:
    """Создаёт tool ``analyze_image``.

    Args:
        workspace_root: Корень workspace для виртуальных путей. Если ``None``,
            используется ``workspace_root`` из настроек.
        client_factory: Фабрика клиента VLM.

    Returns:
        Готовый ``AnalyzeImageTool``.
    """

    return AnalyzeImageTool(
        workspace_root=workspace_root,
        client_factory=client_factory or _build_default_qwen_vlm_client,
    )


def _build_default_qwen_vlm_client() -> QwenVLMClient:
    """Лениво импортирует общую фабрику Qwen VLM клиента.

    Returns:
        Готовый ``QwenVLMClient`` из центральной конфигурации моделей.
    """

    from deep_agent.models.instances import build_qwen_vlm_client

    return build_qwen_vlm_client()


def _resolve_image_path(image_path: str, workspace_root: Path) -> Path:
    """Преобразует абсолютный или workspace-путь изображения в локальный путь.

    Args:
        image_path: Путь из аргументов tool.
        workspace_root: Корень workspace.

    Returns:
        Абсолютный локальный путь.
    """

    raw_path = str(image_path or "").strip()
    relative_path = strip_workspace_tool_prefix(raw_path, workspace_root)
    if relative_path is not None:
        return (
            (workspace_root / relative_path).resolve()
            if relative_path
            else workspace_root.resolve()
        )

    path = Path(raw_path)
    if path.is_absolute() and not raw_path.startswith("/"):
        return path.expanduser().resolve()
    if raw_path.startswith("/") and ":" not in raw_path:
        return (workspace_root / raw_path.lstrip("/")).resolve()
    return (workspace_root / path).resolve()


__all__ = [
    "ANALYZE_IMAGE_TOOL_NAME",
    "AnalyzeImageInput",
    "AnalyzeImageTool",
    "build_analyze_image_tool",
]
