"""Профиль harness аналитического DeepAgent.

Содержит:
- build_analytics_harness_profile: создание профиля без general-purpose subagent и generic execute.
- register_analytics_harness_profile: регистрация профиля для заданного provider/model key.
"""

from __future__ import annotations

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)


def build_analytics_harness_profile() -> HarnessProfile:
    """Создаёт профиль harness для аналитического агента.

    Returns:
        Профиль DeepAgents, который отключает автоматически добавляемый
        ``general-purpose`` subagent и скрывает generic tool ``execute``.
    """

    return HarnessProfile(
        excluded_tools=frozenset({"execute"}),
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
