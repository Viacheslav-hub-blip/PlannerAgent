"""Контракт supervisor-а и subagent data-retrieval аналитического DeepAgent."""

from __future__ import annotations

from pydantic import BaseModel, Field

DATA_RETRIEVAL_AGENT_NAME = "data-retrieval-agent"
DATA_RETRIEVAL_CRITIC_AGENT_NAME = "data-retrieval-critic"


class DataRetrievalCriticVerdict(BaseModel):
    """Structured output внутреннего critic-а для data-retrieval-agent.

    Args:
        approved: Можно ли считать результат чтения данных достаточным.
        reasoning: Краткое обоснование решения critic-а.
        issues: Проблемы одной строкой через точку с запятой.
        revision_instructions: Инструкция по исправлению, если результат не принят.
        checks_performed: Выполненные проверки одной строкой через точку с запятой.

    Returns:
        Валидированный вердикт critic-а для supervisor-а.
    """

    approved: bool = Field(
        description="Можно ли считать шаг чтения данных завершённым и отдать результат supervisor-у.",
    )
    reasoning: str = Field(
        description="Краткое обоснование с опорой на проверенные факты и tool output.",
    )
    issues: str = Field(
        default="",
        description="Выявленные проблемы одной строкой через точку с запятой.",
    )
    revision_instructions: str = Field(
        default="",
        description="Что data-retrieval-agent должен сделать следующим, если approved=false.",
    )
    checks_performed: str = Field(
        default="",
        description="Какие проверки или tools critic выполнил, одной строкой через точку с запятой.",
    )


__all__ = [
    "DATA_RETRIEVAL_AGENT_NAME",
    "DATA_RETRIEVAL_CRITIC_AGENT_NAME",
    "DataRetrievalCriticVerdict",
]
