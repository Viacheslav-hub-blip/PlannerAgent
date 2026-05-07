"""Публичные entrypoints пакета research-agent.

Содержит:
- ResearchAgent: LangChain Runnable facade агента.
- ResearchAgentInput: входная схема Runnable facade.
- ContextRunRef: необязательная ссылка на существующий run для follow-up контекста.
- ArtifactContentPreview: read-only preview содержимого artifact.
- ArtifactDetails: read-only детали artifact.
- NodeDetails: read-only детали lineage node.
- NodeInspectorView: read-only модель Node Inspector для UI.
- NodeStateDiff: top-level diff snapshot node с родителем.
- RunGraph: read-only граф запуска.
- RunResult: read-only результат запуска.
- RunSummary: краткая сводка запуска.
- SnapshotSection: секция snapshot для отображения в Node Inspector.
- planner_agent: lazy factory для прямой сборки LangGraph workflow.
"""

from __future__ import annotations

from typing import Any

from .research_agent import ResearchAgent, ResearchAgentInput
from .services.dialog_context_service import ContextRunRef
from .services.run_inspection_service import (
    ArtifactContentPreview,
    ArtifactDetails,
    NodeDetails,
    NodeInspectorView,
    NodeStateDiff,
    RunGraph,
    RunResult,
    RunSummary,
    SnapshotSection,
)


def planner_agent(*args: Any, **kwargs: Any) -> Any:
    """Лениво создает LangGraph workflow через существующую factory.

    Args:
        *args: Позиционные аргументы для ``factory.planner_agent``.
        **kwargs: Именованные аргументы для ``factory.planner_agent``.

    Returns:
        Скомпилированный LangGraph workflow.
    """

    from .factory import planner_agent as _planner_agent

    return _planner_agent(*args, **kwargs)


__all__ = [
    "ResearchAgent",
    "ResearchAgentInput",
    "ContextRunRef",
    "ArtifactContentPreview",
    "ArtifactDetails",
    "NodeDetails",
    "NodeInspectorView",
    "NodeStateDiff",
    "RunGraph",
    "RunResult",
    "RunSummary",
    "SnapshotSection",
    "planner_agent",
]
