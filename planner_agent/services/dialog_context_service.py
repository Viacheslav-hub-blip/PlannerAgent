"""Сервис сборки контекста диалога поверх существующих ResearchRun.

Содержит:
- ContextRunRef: ссылка на run, который нужно добавить в follow-up контекст.
- ContextRunContext: собранные данные одного context run.
- DialogContext: итоговый пакет контекста для AgentState.
- DialogContextService: read-only сервис сборки dialog context.
- _truncate_text: безопасное ограничение текста по символам.
- _render_context: форматирование dialog context для prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from planner_agent.schemas.artifacts import Artifact
from planner_agent.schemas.lineage import ResearchRun, StateNode

from .run_inspection_service import RunInspectionService


class ContextRunRef(BaseModel):
    """Ссылка на существующий ResearchRun для follow-up запроса.

    Args:
        run_id: Идентификатор сохраненного ResearchRun.
        role: Роль run в диалоге, например ``base``, ``branch`` или ``context``.
        include_final_report: Добавлять ли финальный отчет run в dialog context.
        include_artifacts: Добавлять ли manifest artifacts.
        include_nodes: Добавлять ли краткий список lineage nodes.
        artifact_refs: Явный список artifact_id, которые нужно раскрыть preview.
        node_refs: Явный список node_id, которые нужно упомянуть отдельно.
        max_report_chars: Лимит символов финального отчета.
        max_artifact_preview_chars: Лимит preview для явно выбранных artifacts.

    Returns:
        Валидированная ссылка на context run.
    """

    run_id: str = Field(description="Идентификатор ResearchRun.")
    role: str = Field(default="context", description="Роль run в follow-up контексте.")
    include_final_report: bool = Field(
        default=True,
        description="Добавлять ли финальный отчет run.",
    )
    include_artifacts: bool = Field(
        default=True,
        description="Добавлять ли manifest artifacts run.",
    )
    include_nodes: bool = Field(
        default=False,
        description="Добавлять ли краткий список lineage nodes.",
    )
    artifact_refs: list[str] = Field(
        default_factory=list,
        description="Явно выбранные artifacts для preview.",
    )
    node_refs: list[str] = Field(
        default_factory=list,
        description="Явно выбранные nodes для дополнительного контекста.",
    )
    max_report_chars: int = Field(
        default=12_000,
        ge=0,
        description="Максимальное количество символов финального отчета.",
    )
    max_artifact_preview_chars: int = Field(
        default=2_000,
        ge=0,
        description="Максимальное количество символов preview artifact.",
    )


class ContextRunContext(BaseModel):
    """Собранный read-only контекст одного ResearchRun.

    Args:
        ref: Исходная ссылка на context run.
        run: Найденный ResearchRun или ``None``.
        final_report: Финальный отчет с учетом лимита или ``None``.
        final_report_truncated: Был ли финальный отчет обрезан.
        artifacts: Manifest artifacts выбранного run.
        artifact_previews: Preview явно выбранных artifacts.
        nodes: Краткий список nodes, если он был запрошен.
        selected_nodes: Явно выбранные nodes.
        warnings: Технические предупреждения по этому run.

    Returns:
        Контекст одного run для итогового DialogContext.
    """

    ref: ContextRunRef = Field(description="Исходная ссылка на context run.")
    run: ResearchRun | None = Field(default=None, description="Найденный ResearchRun.")
    final_report: str | None = Field(default=None, description="Финальный отчет run.")
    final_report_truncated: bool = Field(
        default=False,
        description="Был ли финальный отчет обрезан.",
    )
    artifacts: list[Artifact] = Field(
        default_factory=list,
        description="Manifest artifacts run.",
    )
    artifact_previews: dict[str, str] = Field(
        default_factory=dict,
        description="Preview явно выбранных artifacts по artifact_id.",
    )
    nodes: list[StateNode] = Field(
        default_factory=list,
        description="Краткий список lineage nodes.",
    )
    selected_nodes: list[StateNode] = Field(
        default_factory=list,
        description="Явно выбранные lineage nodes.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Технические предупреждения сборки контекста.",
    )


class DialogContext(BaseModel):
    """Итоговый контекст follow-up диалога поверх существующих runs.

    Args:
        context_runs: Собранные контексты отдельных runs.
        rendered_context: Текстовый блок, который можно добавить в AgentState.

    Returns:
        Пакет dialog context для planner/worker prompts.
    """

    context_runs: list[ContextRunContext] = Field(
        default_factory=list,
        description="Контексты отдельных ResearchRun.",
    )
    rendered_context: str = Field(
        default="",
        description="Готовый текстовый блок dialog context для prompt.",
    )


class DialogContextService:
    """Собирает context для чатового follow-up поверх существующих ResearchRun.

    Args:
        inspection_service: Read-only сервис доступа к runs, nodes и artifacts.

    Returns:
        Экземпляр сервиса сборки dialog context.
    """

    def __init__(self, inspection_service: RunInspectionService) -> None:
        self.inspection_service = inspection_service

    def build_context(self, refs: list[ContextRunRef]) -> DialogContext:
        """Собирает dialog context по списку context run ссылок.

        Args:
            refs: Список существующих runs, которые нужно сделать доступными агенту.

        Returns:
            DialogContext с машинно-читаемыми данными и текстовым представлением.
        """

        contexts = [self._build_run_context(ref) for ref in refs]
        return DialogContext(
            context_runs=contexts,
            rendered_context=_render_context(contexts),
        )

    def _build_run_context(self, ref: ContextRunRef) -> ContextRunContext:
        """Собирает контекст одного run.

        Args:
            ref: Ссылка на run и настройки включения данных.

        Returns:
            ContextRunContext для одного run.
        """

        warnings: list[str] = []
        run = self.inspection_service.get_run(ref.run_id)
        if run is None:
            return ContextRunContext(
                ref=ref,
                warnings=[f"run_not_found:{ref.run_id}"],
            )

        final_report: str | None = None
        final_report_truncated = False
        if ref.include_final_report:
            raw_report = self.inspection_service.get_final_report(ref.run_id)
            final_report, final_report_truncated = _truncate_text(
                raw_report,
                max_chars=ref.max_report_chars,
            )
            if raw_report is None:
                warnings.append("final_report_not_found")

        artifacts = (
            self.inspection_service.list_artifacts(ref.run_id)
            if ref.include_artifacts
            else []
        )
        artifact_previews: dict[str, str] = {}
        for artifact_id in ref.artifact_refs:
            details = self.inspection_service.get_artifact_details(
                ref.run_id,
                artifact_id,
                preview_chars=ref.max_artifact_preview_chars,
            )
            if details is None:
                warnings.append(f"artifact_not_found:{artifact_id}")
                continue
            artifact_previews[artifact_id] = details.preview.preview or ""

        nodes = (
            self.inspection_service.list_nodes(ref.run_id)
            if ref.include_nodes
            else []
        )
        selected_nodes: list[StateNode] = []
        for node_id in ref.node_refs:
            node = self.inspection_service.get_node(ref.run_id, node_id)
            if node is None:
                warnings.append(f"node_not_found:{node_id}")
                continue
            selected_nodes.append(node)

        return ContextRunContext(
            ref=ref,
            run=run,
            final_report=final_report,
            final_report_truncated=final_report_truncated,
            artifacts=artifacts,
            artifact_previews=artifact_previews,
            nodes=nodes,
            selected_nodes=selected_nodes,
            warnings=warnings,
        )


def _truncate_text(value: str | None, *, max_chars: int) -> tuple[str | None, bool]:
    """Обрезает текст по лимиту и сообщает факт обрезания.

    Args:
        value: Исходный текст или ``None``.
        max_chars: Максимальное количество символов.

    Returns:
        Кортеж ``(text, truncated)``.
    """

    if value is None:
        return None, False
    safe_limit = max(0, max_chars)
    return value[:safe_limit], len(value) > safe_limit


def _render_context(contexts: list[ContextRunContext]) -> str:
    """Форматирует context runs в текстовый блок для prompts.

    Args:
        contexts: Собранные контексты отдельных runs.

    Returns:
        Многострочный текст dialog context.
    """

    if not contexts:
        return ""

    blocks: list[str] = [
        "<dialog_context>",
        "Это явный контекст предыдущих ResearchRun для текущего follow-up запроса.",
        "Не проси пользователя повторно предоставить отчеты или artifacts, если они перечислены ниже.",
    ]
    for context in contexts:
        blocks.extend(_render_run_context(context))
    blocks.append("</dialog_context>")
    return "\n".join(blocks)


def _render_run_context(context: ContextRunContext) -> list[str]:
    """Форматирует один context run.

    Args:
        context: Собранный контекст одного run.

    Returns:
        Список строк для итогового dialog context.
    """

    ref = context.ref
    lines = [
        "",
        f"<context_run role=\"{ref.role}\" run_id=\"{ref.run_id}\">",
    ]
    if context.run is not None:
        lines.extend(
            [
                f"title: {context.run.title}",
                f"status: {context.run.status}",
                f"parent_run_id: {context.run.parent_run_id}",
                f"source_node_id: {context.run.source_node_id}",
            ]
        )
    if context.final_report is not None:
        suffix = "\n[final_report_truncated: true]" if context.final_report_truncated else ""
        lines.extend(["<final_report>", f"{context.final_report}{suffix}", "</final_report>"])
    if context.artifacts:
        lines.append("<artifacts>")
        for artifact in context.artifacts:
            lines.append(
                " | ".join(
                    [
                        f"artifact_id={artifact.artifact_id}",
                        f"kind={artifact.kind}",
                        f"summary={artifact.summary}",
                        f"uri={artifact.uri}",
                    ]
                )
            )
        lines.append("</artifacts>")
    if context.artifact_previews:
        lines.append("<selected_artifact_previews>")
        for artifact_id, preview in context.artifact_previews.items():
            lines.extend([f"<artifact_preview artifact_id=\"{artifact_id}\">", preview, "</artifact_preview>"])
        lines.append("</selected_artifact_previews>")
    if context.nodes:
        lines.append("<nodes>")
        for node in context.nodes:
            lines.append(
                f"node_id={node.node_id} | type={node.node_type} | status={node.status} | title={node.title}"
            )
        lines.append("</nodes>")
    if context.selected_nodes:
        lines.append("<selected_nodes>")
        for node in context.selected_nodes:
            lines.append(
                f"node_id={node.node_id} | type={node.node_type} | status={node.status} | summary={node.summary}"
            )
        lines.append("</selected_nodes>")
    if context.warnings:
        lines.extend(["<warnings>", *context.warnings, "</warnings>"])
    lines.append("</context_run>")
    return lines


__all__ = [
    "ContextRunContext",
    "ContextRunRef",
    "DialogContext",
    "DialogContextService",
]
