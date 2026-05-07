"""Узел перепланирования, переиспользующий общую логику planner_node.

Содержит:
- replanner_node: запускает planner_node в режиме force_replan.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.types import Command

from .planner_node import planner_node
from ..models import AgentState
from ..services.artifact_service import ArtifactService
from ..services.lineage_service import LineageService
from ..services.skills_service import SkillsService


async def replanner_node(
    state: AgentState,
    llm: BaseChatModel,
    tools: list[BaseTool],
    prompt: str,
    plan_review_prompt: str | None = None,
    lineage_service: LineageService | None = None,
    artifact_service: ArtifactService | None = None,
    skills_service: SkillsService | None = None,
) -> Command:
    """Перестраивает план с учетом результатов выполнения и critic feedback.

    Args:
        state: Текущее состояние агента.
        llm: Языковая модель для перепланирования.
        tools: Список доступных worker tools.
        prompt: Системный prompt replanner-а.
        plan_review_prompt: Опциональный prompt критика плана до исполнения.
        lineage_service: Опциональный сервис записи lineage.

    Returns:
        Команда LangGraph, возвращаемая общим ``planner_node``.
    """

    return await planner_node(
        state=state,
        llm=llm,
        tools=tools,
        prompt=prompt,
        plan_review_prompt=plan_review_prompt,
        force_replan=True,
        lineage_service=lineage_service,
        artifact_service=artifact_service,
        skills_service=skills_service,
    )
