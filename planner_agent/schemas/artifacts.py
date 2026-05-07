"""Схемы artifacts для исследовательских запусков.

Содержит:
- ArtifactMetadata: нормализованные metadata artifact с возможностью доменных расширений.
- Artifact: запись artifact в хранилище запуска.
- normalize_artifact_metadata: приведение произвольных metadata к единому минимальному формату.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


ARTIFACT_METADATA_SCHEMA_VERSION = "artifact_metadata.v1"


class ArtifactMetadata(BaseModel):
    """Нормализованные metadata artifact с поддержкой произвольных дополнительных полей.

    Args:
        schema_version: Версия служебной схемы metadata.
        artifact_role: Роль artifact внутри запуска: результат tool, trace, отчет, context и так далее.
        producer: Компонент, который создал artifact.
        content_kind: Универсальный тип содержимого, обычно совпадает с ``Artifact.kind``.
        task_id: Идентификатор задачи worker, если artifact связан с задачей.
        tool_name: Имя LangChain tool, если artifact создан из результата tool.
        capture_reason: Причина сохранения результата как artifact.
        reusable: Можно ли повторно использовать artifact в последующих шагах или ветках.
        editable: Можно ли пользователю редактировать artifact перед продолжением работы.

    Returns:
        Pydantic-модель metadata. Неизвестные поля сохраняются как дополнительные ключи.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = Field(
        default=ARTIFACT_METADATA_SCHEMA_VERSION,
        description="Версия служебной схемы metadata artifact.",
    )
    artifact_role: str = Field(
        default="unspecified",
        description="Роль artifact в жизненном цикле запуска.",
    )
    producer: str = Field(
        default="agent",
        description="Компонент, создавший artifact.",
    )
    content_kind: str = Field(
        default="",
        description="Универсальный тип содержимого artifact.",
    )
    task_id: str | None = Field(
        default=None,
        description="Идентификатор задачи worker, если artifact связан с задачей.",
    )
    tool_name: str | None = Field(
        default=None,
        description="Имя LangChain tool, если artifact создан инструментом.",
    )
    capture_reason: str | None = Field(
        default=None,
        description="Причина сохранения результата как artifact.",
    )
    reusable: bool | None = Field(
        default=None,
        description="Можно ли повторно использовать artifact.",
    )
    editable: bool | None = Field(
        default=None,
        description="Можно ли редактировать artifact перед продолжением исследования.",
    )


class Artifact(BaseModel):
    """Описание сохраненного artifact внутри ResearchRun."""

    artifact_id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str
    node_id: str
    kind: str
    uri: str
    mime_type: str = "application/octet-stream"
    summary: str = ""
    checksum: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def normalize_artifact_metadata(
        metadata: dict[str, Any] | None,
        *,
        kind: str,
        producer: str = "agent",
        artifact_role: str = "unspecified",
) -> dict[str, Any]:
    """Нормализует произвольные metadata artifact без удаления пользовательских полей.

    Args:
        metadata: Исходные metadata от конкретного сервиса, tool wrapper или приложения.
        kind: Тип artifact, который будет продублирован в поле ``content_kind``.
        producer: Компонент, создающий artifact, если он не указан в metadata.
        artifact_role: Роль artifact по умолчанию, если она не указана в metadata.

    Returns:
        Плоский JSON-совместимый словарь metadata с обязательными служебными ключами и
        всеми исходными дополнительными полями.
    """

    payload = dict(metadata or {})
    payload.setdefault("schema_version", ARTIFACT_METADATA_SCHEMA_VERSION)
    payload.setdefault("artifact_role", artifact_role)
    payload.setdefault("producer", producer)
    payload.setdefault("content_kind", kind)
    return ArtifactMetadata.model_validate(payload).model_dump(
        mode="json",
        exclude_none=True,
    )


__all__ = [
    "ARTIFACT_METADATA_SCHEMA_VERSION",
    "Artifact",
    "ArtifactMetadata",
    "normalize_artifact_metadata",
]
