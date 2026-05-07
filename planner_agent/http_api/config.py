"""Настройки и сборка сервисов HTTP API.

Содержит:
- ApiSettings: конфигурация путей для API приложения.
- ApiServices: контейнер сервисов чтения runs и artifacts.
- build_api_services: создание сервисов из настроек.
- _resolve_path: нормализация путей относительно workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from planner_agent.services.artifact_service import ArtifactService
from planner_agent.services.dialog_context_service import DialogContextService
from planner_agent.services.lineage_service import LineageService
from planner_agent.services.run_inspection_service import RunInspectionService
from planner_agent.services.skills_service import SkillsService


class ApiSettings(BaseModel):
    """Настройки API слоя research-agent.

    Args:
        workspace_root: Корневая директория проекта или окружения, относительно
            которой разрешаются относительные пути.
        runs_dir: Директория сохраненных ResearchRun. Может быть абсолютной или
            относительной к ``workspace_root``.
        api_prefix: Префикс HTTP маршрутов API.

    Returns:
        Валидированная конфигурация API приложения.
    """

    workspace_root: str = Field(
        default=".",
        description="Корневая директория workspace.",
    )
    runs_dir: str = Field(
        default="runs",
        description="Директория сохраненных ResearchRun.",
    )
    api_prefix: str = Field(
        default="/api/v1",
        description="Префикс HTTP маршрутов API.",
    )


class ApiServices(BaseModel):
    """Контейнер сервисов, используемых API приложением.

    Args:
        lineage_service: Сервис чтения и записи lineage graph.
        artifact_service: Сервис чтения и регистрации artifacts.
        inspection_service: Сервис read-only инспекции runs, nodes и artifacts.
        dialog_context_service: Сервис сборки follow-up context поверх существующих runs.
        skills_service: Опциональный сервис skills для HTTP endpoints.
        agent: Опциональный ResearchAgent-compatible объект для запуска агента.

    Returns:
        Контейнер зависимостей API приложения.
    """

    lineage_service: LineageService = Field(description="Сервис lineage.")
    artifact_service: ArtifactService = Field(description="Сервис artifacts.")
    inspection_service: RunInspectionService = Field(description="Сервис inspection.")
    dialog_context_service: DialogContextService | None = Field(
        default=None,
        description="Сервис dialog context.",
    )
    skills_service: SkillsService | None = Field(
        default=None,
        description="Сервис управления skills.",
    )
    agent: Any | None = Field(
        default=None,
        description="Опциональный агент с методами ainvoke и ainvoke_branch.",
    )

    model_config = {"arbitrary_types_allowed": True}


def build_api_services(settings: ApiSettings) -> ApiServices:
    """Создает сервисы API слоя из настроек.

    Args:
        settings: Настройки API приложения.

    Returns:
        ApiServices с общими экземплярами LineageService, ArtifactService и
        RunInspectionService.
    """

    workspace_root = Path(settings.workspace_root).resolve()
    runs_dir = _resolve_path(workspace_root, settings.runs_dir)
    lineage_service = LineageService(runs_dir)
    artifact_service = ArtifactService(runs_dir)
    inspection_service = RunInspectionService(
        lineage_service=lineage_service,
        artifact_service=artifact_service,
    )
    return ApiServices(
        lineage_service=lineage_service,
        artifact_service=artifact_service,
        inspection_service=inspection_service,
        dialog_context_service=DialogContextService(inspection_service),
    )


def _resolve_path(workspace_root: Path, value: str) -> Path:
    """Нормализует путь относительно workspace.

    Args:
        workspace_root: Абсолютный путь к workspace.
        value: Абсолютный или относительный путь.

    Returns:
        Абсолютный путь.
    """

    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (workspace_root / path).resolve()


__all__ = ["ApiServices", "ApiSettings", "build_api_services"]
