"""Профиль harness гибридного аналитического coding-agent.

Содержит:
- build_analytics_harness_profile: создание профиля с explicit subagents и полным tool runtime.
- register_analytics_harness_profile: регистрация профиля для заданного provider/model key.
"""

from __future__ import annotations

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)

from deep_agent.prompts.tool_contracts import TOOL_DESCRIPTION_OVERRIDES


def build_analytics_harness_profile() -> HarnessProfile:
    """Создаёт профиль harness для аналитического coding-agent.

    Returns:
        Профиль DeepAgents, который сохраняет generic ``execute`` и отключает только
        автоматический ``general-purpose``: его capability-aware спецификация
        добавляется сборщиком агента явно.
    """

    return HarnessProfile(
        tool_description_overrides=TOOL_DESCRIPTION_OVERRIDES,
        excluded_tools=frozenset(),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    )


def register_analytics_harness_profile(profile_key: str) -> None:
    """Регистрирует аналитический профиль для provider или конкретной модели.

    Args:
        profile_key: Ключ реестра DeepAgents вида ``provider`` или
            ``provider:model``.

    Returns:
        ``None``. Профиль добавляется в глобальный реестр DeepAgents.

    Raises:
        ValueError: Если передан пустой ключ профиля.
    """

    normalized_key = profile_key.strip()
    if not normalized_key:
        raise ValueError("Ключ harness profile не может быть пустым.")
    register_harness_profile(normalized_key, build_analytics_harness_profile())


__all__ = [
    "build_analytics_harness_profile",
    "register_analytics_harness_profile",
]
