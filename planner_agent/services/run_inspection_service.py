"""Сервис чтения сохраненных исследовательских запусков.

Содержит:
- ArtifactContentPreview: безопасное preview содержимого artifact.
- ArtifactDetails: подробности artifact, связанный node и preview.
- NodeDetails: подробности lineage node, snapshot и связанных artifacts.
- SnapshotSection: top-level секция snapshot для Node Inspector.
- NodeStateDiff: top-level diff snapshot текущего node с родителем.
- NodeInspectorView: полная read-only модель Node Inspector для UI.
- RunGraph: сохраненный граф запуска.
- RunResult: полный результат запуска для backend/API слоя.
- RunSummary: краткая сводка по одному ResearchRun.
- RunInspectionService: facade для чтения run, lineage nodes, snapshots и artifacts.
- _find_parent_nodes: поиск родительских nodes для инспектора.
- _find_child_nodes: поиск дочерних nodes для инспектора.
- _build_snapshot_sections: подготовка top-level секций snapshot для UI.
- _build_snapshot_diff: подготовка top-level diff snapshot с родителем.
- _deduplicate_artifact_details: удаление дублей ArtifactDetails.
- _item_count: подсчет элементов контейнера snapshot.
- _preview_value: компактное текстовое preview значения snapshot.
- _build_artifact_preview: сбор preview и технических сведений о файле artifact.
- _is_text_mime_type: проверка, можно ли читать artifact как текст.
- _read_text_file: безопасное чтение текстового artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from planner_agent.schemas.artifacts import Artifact
from planner_agent.schemas.lineage import ResearchRun, StateNode

from .artifact_service import ArtifactService
from .lineage_service import LineageService


class ArtifactContentPreview(BaseModel):
    """Безопасное preview содержимого artifact для UI/API слоя."""

    artifact_id: str = Field(description="Идентификатор artifact.")
    uri: str = Field(description="URI или локальный путь artifact.")
    exists: bool = Field(description="Существует ли файл artifact в доступной файловой системе.")
    is_text: bool = Field(description="Можно ли прочитать artifact как UTF-8 текст.")
    size_bytes: int | None = Field(
        default=None,
        description="Размер файла artifact в байтах, если файл доступен.",
    )
    total_chars: int | None = Field(
        default=None,
        description="Полный размер текстового содержимого в символах, если artifact текстовый.",
    )
    preview: str | None = Field(
        default=None,
        description="Текстовое preview artifact или ``None`` для бинарных/недоступных artifacts.",
    )
    preview_chars: int = Field(description="Запрошенный лимит preview в символах.")
    truncated: bool = Field(description="Было ли preview обрезано по лимиту.")
    error: str | None = Field(
        default=None,
        description="Код ошибки чтения, если preview недоступно.",
    )


class ArtifactDetails(BaseModel):
    """Подробности artifact для backend/API слоя без загрузки всего содержимого."""

    artifact: Artifact = Field(description="Основная запись Artifact из индекса запуска.")
    node: StateNode | None = Field(
        default=None,
        description="Lineage node, который создал artifact, если node найден.",
    )
    preview: ArtifactContentPreview = Field(
        description="Безопасное preview содержимого artifact и технические сведения о файле.",
    )


class NodeDetails(BaseModel):
    """Подробности одного lineage node для backend/API слоя."""

    node: StateNode = Field(description="Lineage node.")
    snapshot: dict[str, Any] | None = Field(
        default=None,
        description="Снимок AgentState или служебного состояния на момент node.",
    )
    artifacts: list[Artifact] = Field(
        default_factory=list,
        description="Artifacts, явно связанные с node.",
    )


class SnapshotSection(BaseModel):
    """Секция snapshot, подготовленная для отображения в Node Inspector.

    Модель не интерпретирует доменную логику состояния. Она раскладывает
    top-level поля snapshot на секции, чтобы UI мог показывать состояние без
    знания внутренних Pydantic/TypedDict моделей агента.
    """

    name: str = Field(description="Имя top-level поля snapshot.")
    value: Any = Field(description="Исходное JSON-совместимое значение секции.")
    value_type: str = Field(description="Технический тип значения: dict, list, str и т.д.")
    item_count: int | None = Field(
        default=None,
        description="Количество элементов для list/dict/set или ``None`` для скаляров.",
    )
    preview: str = Field(description="Короткое текстовое preview значения для компактного UI.")
    truncated: bool = Field(description="Было ли preview обрезано по лимиту символов.")


class NodeStateDiff(BaseModel):
    """Top-level diff snapshot текущего node относительно одного родительского node."""

    parent_node_id: str | None = Field(
        default=None,
        description="Идентификатор parent node, snapshot которого использовался для сравнения.",
    )
    added_keys: list[str] = Field(
        default_factory=list,
        description="Top-level ключи, которые появились в текущем snapshot.",
    )
    removed_keys: list[str] = Field(
        default_factory=list,
        description="Top-level ключи, которые были у parent snapshot, но отсутствуют в текущем.",
    )
    changed_keys: list[str] = Field(
        default_factory=list,
        description="Top-level ключи, значения которых отличаются от parent snapshot.",
    )
    unchanged_keys: list[str] = Field(
        default_factory=list,
        description="Top-level ключи, значения которых совпадают с parent snapshot.",
    )


class NodeInspectorView(BaseModel):
    """Полная read-only модель Node Inspector для UI.

    Эта модель собирает вокруг одного lineage node всю информацию, нужную для
    экрана просмотра: сам node, связи с графом, snapshot, artifacts, tool traces
    и простой diff с родителем. Она не запускает агента и не меняет состояние.
    """

    run: ResearchRun = Field(description="ResearchRun, которому принадлежит node.")
    node: StateNode = Field(description="Текущий lineage node, открытый в инспекторе.")
    parent_nodes: list[StateNode] = Field(
        default_factory=list,
        description="Родительские nodes из lineage graph.",
    )
    child_nodes: list[StateNode] = Field(
        default_factory=list,
        description="Дочерние nodes, которые ссылаются на текущий node.",
    )
    snapshot: dict[str, Any] | None = Field(
        default=None,
        description="Полный snapshot текущего node, если он доступен и был запрошен.",
    )
    snapshot_sections: list[SnapshotSection] = Field(
        default_factory=list,
        description="Top-level секции snapshot с preview для UI.",
    )
    diff_with_parent: NodeStateDiff | None = Field(
        default=None,
        description="Top-level diff с первым доступным parent snapshot.",
    )
    artifacts: list[ArtifactDetails] = Field(
        default_factory=list,
        description="Artifacts текущего node, кроме tool traces.",
    )
    tool_traces: list[ArtifactDetails] = Field(
        default_factory=list,
        description="Tool trace artifacts текущего node.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Технические предупреждения инспектора: отсутствующий snapshot, artifact и т.д.",
    )


class RunGraph(BaseModel):
    """Граф сохраненного ResearchRun без загрузки тяжелых snapshot payloads."""

    run: ResearchRun = Field(description="Основная запись ResearchRun.")
    nodes: list[StateNode] = Field(description="Lineage nodes запуска в порядке записи.")


class RunSummary(BaseModel):
    """Краткая сводка исследовательского запуска для backend/API слоя."""

    run: ResearchRun = Field(description="Основная запись ResearchRun.")
    node_count: int = Field(description="Количество lineage nodes в запуске.")
    artifact_count: int = Field(description="Количество artifacts в запуске.")
    final_report: str | None = Field(
        default=None,
        description="Финальный отчет, если он уже был создан.",
    )
    final_report_node_id: str | None = Field(
        default=None,
        description="Идентификатор final_report node, если он найден.",
    )
    final_report_artifact_id: str | None = Field(
        default=None,
        description="Идентификатор artifact с финальным отчетом, если он найден.",
    )


class RunResult(BaseModel):
    """Полный read-only результат ResearchRun для интеграций без UI."""

    run: ResearchRun = Field(description="Основная запись ResearchRun.")
    summary: RunSummary = Field(description="Краткая сводка запуска.")
    final_report: str | None = Field(
        default=None,
        description="Финальный markdown-отчет запуска, если он был создан.",
    )
    final_state: dict[str, Any] | None = Field(
        default=None,
        description="Snapshot final_report node или последнего node, если final_report node отсутствует.",
    )
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Сериализованные LangChain messages из final_state, если они есть в snapshot.",
    )
    nodes: list[StateNode] = Field(
        default_factory=list,
        description="Lineage nodes запуска.",
    )
    artifacts: list[Artifact] = Field(
        default_factory=list,
        description="Artifacts запуска.",
    )


class RunInspectionService:
    """Читает сохраненные runs, lineage snapshots и artifacts без зависимости от UI.

    Args:
        lineage_service: Сервис lineage-хранилища, из которого читаются runs и nodes.
        artifact_service: Сервис artifact-хранилища, из которого читается индекс artifacts.

    Returns:
        Экземпляр сервиса для программной инспекции результатов агента.
    """

    def __init__(
            self,
            lineage_service: LineageService,
            artifact_service: ArtifactService,
    ) -> None:
        self.lineage_service = lineage_service
        self.artifact_service = artifact_service

    def list_runs(self) -> list[ResearchRun]:
        """Возвращает список всех сохраненных ResearchRun.

        Returns:
            Список запусков, отсортированный от новых к старым.
        """

        return self.lineage_service.list_runs()

    def list_run_summaries(self) -> list[RunSummary]:
        """Возвращает краткие сводки всех сохраненных запусков.

        Returns:
            Список RunSummary, отсортированный от новых запусков к старым.
        """

        summaries: list[RunSummary] = []
        for run in self.list_runs():
            summary = self.get_run_summary(run.run_id)
            if summary is not None:
                summaries.append(summary)
        return summaries

    def get_run(self, run_id: str) -> ResearchRun | None:
        """Возвращает один ResearchRun по идентификатору.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            ResearchRun или ``None``, если запуск не найден.
        """

        return self.lineage_service.get_run(run_id)

    def list_nodes(self, run_id: str) -> list[StateNode]:
        """Возвращает lineage nodes выбранного запуска.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            Список StateNode в порядке записи в lineage.
        """

        return self.lineage_service.get_nodes(run_id)

    def get_run_graph(self, run_id: str) -> RunGraph | None:
        """Возвращает сохраненный граф запуска.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            RunGraph или ``None``, если запуск не найден.
        """

        run = self.get_run(run_id)
        if run is None:
            return None
        return RunGraph(run=run, nodes=self.list_nodes(run_id))

    def get_node(self, run_id: str, node_id: str) -> StateNode | None:
        """Возвращает lineage node по идентификатору.

        Args:
            run_id: Идентификатор исследовательского запуска.
            node_id: Идентификатор lineage node.

        Returns:
            StateNode или ``None``, если node не найден.
        """

        return self.lineage_service.get_node(run_id, node_id)

    def load_node_snapshot(self, run_id: str, node_id: str) -> dict[str, Any]:
        """Загружает сохраненный snapshot состояния для конкретного node.

        Args:
            run_id: Идентификатор исследовательского запуска.
            node_id: Идентификатор lineage node.

        Returns:
            JSON-совместимый словарь snapshot.

        Raises:
            FileNotFoundError: Если node или snapshot не найден.
        """

        return self.lineage_service.load_snapshot(run_id, node_id)

    def get_node_details(
            self,
            run_id: str,
            node_id: str,
            *,
            include_snapshot: bool = True,
    ) -> NodeDetails | None:
        """Возвращает node вместе со snapshot и связанными artifacts.

        Args:
            run_id: Идентификатор исследовательского запуска.
            node_id: Идентификатор lineage node.
            include_snapshot: Загружать ли snapshot node.

        Returns:
            NodeDetails или ``None``, если node не найден.
        """

        node = self.get_node(run_id, node_id)
        if node is None:
            return None

        snapshot: dict[str, Any] | None = None
        if include_snapshot:
            try:
                snapshot = self.load_node_snapshot(run_id, node_id)
            except FileNotFoundError:
                snapshot = None

        node_artifacts = self._get_node_artifacts(run_id=run_id, node=node)
        return NodeDetails(
            node=node,
            snapshot=snapshot,
            artifacts=node_artifacts,
        )

    def get_node_inspector_view(
            self,
            run_id: str,
            node_id: str,
            *,
            include_snapshot: bool = True,
            preview_chars: int = 4_000,
            snapshot_preview_chars: int = 1_000,
    ) -> NodeInspectorView | None:
        """Собирает read-only модель Node Inspector для UI.

        Args:
            run_id: Идентификатор исследовательского запуска.
            node_id: Идентификатор lineage node, который нужно открыть в инспекторе.
            include_snapshot: Загружать ли полный snapshot текущего node.
            preview_chars: Максимальный размер preview для связанных artifacts.
            snapshot_preview_chars: Максимальный размер preview для каждой top-level
                секции snapshot.

        Returns:
            NodeInspectorView или ``None``, если run/node не найдены.
        """

        run = self.get_run(run_id)
        node = self.get_node(run_id, node_id)
        if run is None or node is None:
            return None

        warnings: list[str] = []
        nodes = self.list_nodes(run_id)
        parent_nodes = _find_parent_nodes(nodes=nodes, node=node)
        child_nodes = _find_child_nodes(nodes=nodes, node=node)

        snapshot: dict[str, Any] | None = None
        if include_snapshot:
            try:
                snapshot = self.load_node_snapshot(run_id, node_id)
            except FileNotFoundError:
                warnings.append("node_snapshot_not_found")

        parent_snapshot: dict[str, Any] | None = None
        parent_snapshot_node_id: str | None = None
        for parent_node in parent_nodes:
            try:
                parent_snapshot = self.load_node_snapshot(run_id, parent_node.node_id)
                parent_snapshot_node_id = parent_node.node_id
                break
            except FileNotFoundError:
                continue

        if parent_nodes and parent_snapshot is None:
            warnings.append("parent_snapshot_not_found")

        node_artifacts = self._get_node_artifacts(run_id=run_id, node=node)
        for artifact_id in node.tool_trace_refs:
            artifact = self.get_artifact(run_id, artifact_id)
            if artifact is None:
                warnings.append(f"tool_trace_not_found:{artifact_id}")
                continue
            node_artifacts.append(artifact)

        raw_artifact_details: list[ArtifactDetails] = []
        for artifact in node_artifacts:
            details = self.get_artifact_details(
                run_id,
                artifact.artifact_id,
                preview_chars=preview_chars,
            )
            if details is not None:
                raw_artifact_details.append(details)
        artifact_details = _deduplicate_artifact_details(details=raw_artifact_details)
        tool_trace_ids = set(node.tool_trace_refs)
        tool_traces = [
            details
            for details in artifact_details
            if details.artifact.kind == "tool_trace"
            or details.artifact.artifact_id in tool_trace_ids
        ]
        artifacts = [
            details
            for details in artifact_details
            if details.artifact.kind != "tool_trace"
            and details.artifact.artifact_id not in tool_trace_ids
        ]

        return NodeInspectorView(
            run=run,
            node=node,
            parent_nodes=parent_nodes,
            child_nodes=child_nodes,
            snapshot=snapshot,
            snapshot_sections=_build_snapshot_sections(
                snapshot,
                max_preview_chars=snapshot_preview_chars,
            ),
            diff_with_parent=_build_snapshot_diff(
                snapshot=snapshot,
                parent_snapshot=parent_snapshot,
                parent_node_id=parent_snapshot_node_id,
            ),
            artifacts=artifacts,
            tool_traces=tool_traces,
            warnings=warnings,
        )

    def list_artifacts(self, run_id: str) -> list[Artifact]:
        """Возвращает artifacts выбранного запуска.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            Список artifacts из индекса запуска.
        """

        return self.artifact_service.list_artifacts(run_id)

    def get_artifact(self, run_id: str, artifact_id: str) -> Artifact | None:
        """Возвращает artifact по идентификатору.

        Args:
            run_id: Идентификатор исследовательского запуска.
            artifact_id: Идентификатор artifact.

        Returns:
            Artifact или ``None``, если artifact не найден.
        """

        return self.artifact_service.get_artifact(run_id, artifact_id)

    def get_artifact_details(
            self,
            run_id: str,
            artifact_id: str,
            *,
            preview_chars: int = 4_000,
    ) -> ArtifactDetails | None:
        """Возвращает подробности artifact, связанный lineage node и безопасное preview.

        Args:
            run_id: Идентификатор исследовательского запуска.
            artifact_id: Идентификатор artifact.
            preview_chars: Максимальное количество символов preview для текстовых artifacts.

        Returns:
            ArtifactDetails или ``None``, если artifact не найден.
        """

        artifact = self.get_artifact(run_id, artifact_id)
        if artifact is None:
            return None

        return ArtifactDetails(
            artifact=artifact,
            node=self.get_node(run_id, artifact.node_id),
            preview=_build_artifact_preview(
                artifact=artifact,
                preview_chars=preview_chars,
            ),
        )

    def preview_artifact(
            self,
            run_id: str,
            artifact_id: str,
            *,
            preview_chars: int = 4_000,
    ) -> ArtifactContentPreview | None:
        """Возвращает только preview содержимого artifact.

        Args:
            run_id: Идентификатор исследовательского запуска.
            artifact_id: Идентификатор artifact.
            preview_chars: Максимальное количество символов preview для текстовых artifacts.

        Returns:
            ArtifactContentPreview или ``None``, если artifact не найден.
        """

        details = self.get_artifact_details(
            run_id,
            artifact_id,
            preview_chars=preview_chars,
        )
        return details.preview if details is not None else None

    def artifact_download_path(self, run_id: str, artifact_id: str) -> Path | None:
        """Возвращает путь к файлу artifact для отдачи как вложение, если путь безопасен.

        Args:
            run_id: Идентификатор исследовательского запуска.
            artifact_id: Идентификатор artifact.

        Returns:
            ``Path`` к существующему файлу внутри ``runs_dir/{run_id}/artifacts`` или ``None``.
        """

        artifact = self.get_artifact(run_id, artifact_id)
        if artifact is None or artifact.run_id != run_id:
            return None

        path = Path(artifact.uri).resolve()
        base = (self.artifact_service.runs_dir / run_id / "artifacts").resolve()
        try:
            path.relative_to(base)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return path

    def read_artifact_text(
            self,
            run_id: str,
            artifact_id: str,
            *,
            max_chars: int | None = None,
    ) -> str | None:
        """Читает текстовое содержимое artifact, если оно доступно как файл.

        Args:
            run_id: Идентификатор исследовательского запуска.
            artifact_id: Идентификатор artifact.
            max_chars: Опциональный лимит символов для превью.

        Returns:
            Текст artifact или ``None``, если artifact не найден или файл недоступен.
        """

        artifact = self.get_artifact(run_id, artifact_id)
        if artifact is None:
            return None
        return _read_text_file(artifact.uri, max_chars=max_chars)

    def get_final_report(self, run_id: str) -> str | None:
        """Возвращает финальный отчет запуска.

        Сначала ищет ``final_report`` в snapshot последнего final_report node.
        Если snapshot недоступен, читает report artifact.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            Markdown-текст финального отчета или ``None``.
        """

        final_node = self._get_latest_final_report_node(run_id)
        if final_node is not None:
            try:
                snapshot = self.load_node_snapshot(run_id, final_node.node_id)
                report = snapshot.get("final_report")
                if isinstance(report, str) and report:
                    return report
            except FileNotFoundError:
                pass

            for artifact_id in final_node.artifact_refs:
                text = self.read_artifact_text(run_id, artifact_id)
                if text:
                    return text

        report_artifact = self._get_latest_report_artifact(run_id)
        if report_artifact is None:
            return None
        return _read_text_file(report_artifact.uri)

    def get_run_result(
            self,
            run_id: str,
            *,
            include_nodes: bool = True,
            include_artifacts: bool = True,
            include_final_state: bool = True,
    ) -> RunResult | None:
        """Возвращает полный результат запуска для backend/API интеграций.

        Args:
            run_id: Идентификатор исследовательского запуска.
            include_nodes: Включать ли lineage nodes в ответ.
            include_artifacts: Включать ли artifacts в ответ.
            include_final_state: Загружать ли snapshot финального или последнего node.

        Returns:
            RunResult или ``None``, если запуск не найден.
        """

        summary = self.get_run_summary(run_id)
        if summary is None:
            return None

        nodes = self.list_nodes(run_id) if include_nodes else []
        artifacts = self.list_artifacts(run_id) if include_artifacts else []
        final_state = (
            self._load_final_or_latest_snapshot(run_id)
            if include_final_state
            else None
        )
        return RunResult(
            run=summary.run,
            summary=summary,
            final_report=summary.final_report,
            final_state=final_state,
            messages=_messages_from_snapshot(final_state),
            nodes=nodes,
            artifacts=artifacts,
        )

    def get_run_summary(self, run_id: str) -> RunSummary | None:
        """Собирает компактную сводку запуска для API или chat-backend слоя.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            RunSummary или ``None``, если запуск не найден.
        """

        run = self.get_run(run_id)
        if run is None:
            return None

        nodes = self.list_nodes(run_id)
        artifacts = self.list_artifacts(run_id)
        final_node = self._get_latest_final_report_node(run_id)
        final_artifact = self._get_latest_report_artifact(run_id)
        return RunSummary(
            run=run,
            node_count=len(nodes),
            artifact_count=len(artifacts),
            final_report=self.get_final_report(run_id),
            final_report_node_id=final_node.node_id if final_node else None,
            final_report_artifact_id=(
                final_artifact.artifact_id if final_artifact else None
            ),
        )

    def _get_latest_final_report_node(self, run_id: str) -> StateNode | None:
        """Находит последний final_report node в запуске.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            Последний StateNode типа ``final_report`` или ``None``.
        """

        nodes = self.list_nodes(run_id)
        return next(
            (node for node in reversed(nodes) if node.node_type == "final_report"),
            None,
        )

    def _get_latest_report_artifact(self, run_id: str) -> Artifact | None:
        """Находит последний artifact отчета в запуске.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            Последний Artifact с ``kind == "report"`` или ``None``.
        """

        artifacts = self.list_artifacts(run_id)
        return next(
            (artifact for artifact in reversed(artifacts) if artifact.kind == "report"),
            None,
        )

    def _get_node_artifacts(self, *, run_id: str, node: StateNode) -> list[Artifact]:
        """Собирает artifacts, связанные с node по refs и node_id.

        Args:
            run_id: Идентификатор исследовательского запуска.
            node: Lineage node.

        Returns:
            Список Artifact без дублей.
        """

        by_id: dict[str, Artifact] = {}
        for artifact in self.artifact_service.list_node_artifacts(run_id, node.node_id):
            by_id[artifact.artifact_id] = artifact
        for artifact_id in node.artifact_refs:
            artifact = self.get_artifact(run_id, artifact_id)
            if artifact is not None:
                by_id[artifact.artifact_id] = artifact
        return list(by_id.values())

    def _load_final_or_latest_snapshot(self, run_id: str) -> dict[str, Any] | None:
        """Загружает snapshot final_report node или последнего node запуска.

        Args:
            run_id: Идентификатор исследовательского запуска.

        Returns:
            Snapshot или ``None``, если snapshot отсутствует.
        """

        nodes = self.list_nodes(run_id)
        if not nodes:
            return None

        preferred = self._get_latest_final_report_node(run_id) or nodes[-1]
        try:
            return self.load_node_snapshot(run_id, preferred.node_id)
        except FileNotFoundError:
            return None


def _find_parent_nodes(*, nodes: list[StateNode], node: StateNode) -> list[StateNode]:
    """Находит родительские nodes для Node Inspector.

    Args:
        nodes: Все nodes выбранного запуска.
        node: Node, для которого строится инспектор.

    Returns:
        Список parent nodes в порядке ``node.parent_ids``.
    """

    by_id = {candidate.node_id: candidate for candidate in nodes}
    return [
        by_id[parent_id]
        for parent_id in node.parent_ids
        if parent_id in by_id
    ]


def _find_child_nodes(*, nodes: list[StateNode], node: StateNode) -> list[StateNode]:
    """Находит дочерние nodes для Node Inspector.

    Args:
        nodes: Все nodes выбранного запуска.
        node: Node, для которого строится инспектор.

    Returns:
        Список nodes, которые ссылаются на текущий node как на parent.
    """

    return [
        candidate
        for candidate in nodes
        if node.node_id in candidate.parent_ids
    ]


def _build_snapshot_sections(
        snapshot: dict[str, Any] | None,
        *,
        max_preview_chars: int,
) -> list[SnapshotSection]:
    """Преобразует snapshot в top-level секции для UI.

    Args:
        snapshot: Snapshot node или ``None``.
        max_preview_chars: Максимальный размер preview одной секции.

    Returns:
        Список SnapshotSection в порядке ключей snapshot.
    """

    if not isinstance(snapshot, dict):
        return []

    sections: list[SnapshotSection] = []
    for key, value in snapshot.items():
        preview, truncated = _preview_value(value, max_chars=max_preview_chars)
        sections.append(
            SnapshotSection(
                name=key,
                value=value,
                value_type=type(value).__name__,
                item_count=_item_count(value),
                preview=preview,
                truncated=truncated,
            )
        )
    return sections


def _build_snapshot_diff(
        *,
        snapshot: dict[str, Any] | None,
        parent_snapshot: dict[str, Any] | None,
        parent_node_id: str | None,
) -> NodeStateDiff | None:
    """Строит top-level diff текущего snapshot с parent snapshot.

    Args:
        snapshot: Snapshot текущего node.
        parent_snapshot: Snapshot parent node.
        parent_node_id: Идентификатор parent node, использованный для сравнения.

    Returns:
        NodeStateDiff или ``None``, если один из snapshot недоступен.
    """

    if not isinstance(snapshot, dict) or not isinstance(parent_snapshot, dict):
        return None

    current_keys = set(snapshot)
    parent_keys = set(parent_snapshot)
    shared_keys = current_keys & parent_keys
    return NodeStateDiff(
        parent_node_id=parent_node_id,
        added_keys=sorted(current_keys - parent_keys),
        removed_keys=sorted(parent_keys - current_keys),
        changed_keys=sorted(
            key
            for key in shared_keys
            if snapshot.get(key) != parent_snapshot.get(key)
        ),
        unchanged_keys=sorted(
            key
            for key in shared_keys
            if snapshot.get(key) == parent_snapshot.get(key)
        ),
    )


def _deduplicate_artifact_details(details: list[ArtifactDetails]) -> list[ArtifactDetails]:
    """Удаляет дубли ArtifactDetails с сохранением порядка.

    Args:
        details: Список деталей artifacts, собранных разными способами.

    Returns:
        Список ArtifactDetails без повторяющихся ``artifact_id``.
    """

    result: list[ArtifactDetails] = []
    seen: set[str] = set()
    for item in details:
        artifact_id = item.artifact.artifact_id
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        result.append(item)
    return result


def _item_count(value: Any) -> int | None:
    """Возвращает количество элементов для контейнеров snapshot.

    Args:
        value: Значение секции snapshot.

    Returns:
        Количество элементов для dict/list/tuple/set или ``None`` для скаляров.
    """

    if isinstance(value, (dict, list, tuple, set)):
        return len(value)
    return None


def _preview_value(value: Any, *, max_chars: int) -> tuple[str, bool]:
    """Создает компактное текстовое preview произвольного JSON-значения.

    Args:
        value: Значение snapshot-секции.
        max_chars: Максимальный размер preview.

    Returns:
        Кортеж ``(preview, truncated)``.
    """

    try:
        rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        rendered = str(value)
    safe_limit = max(0, max_chars)
    return rendered[:safe_limit], len(rendered) > safe_limit


def _messages_from_snapshot(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Извлекает сериализованные messages из snapshot.

    Args:
        snapshot: Snapshot AgentState или ``None``.

    Returns:
        Список JSON-совместимых сообщений.
    """

    if not isinstance(snapshot, dict):
        return []
    messages = snapshot.get("messages")
    if not isinstance(messages, list):
        return []
    return [message for message in messages if isinstance(message, dict)]


def _build_artifact_preview(
        *,
        artifact: Artifact,
        preview_chars: int,
) -> ArtifactContentPreview:
    """Собирает безопасное preview artifact без доменных предположений о содержимом.

    Args:
        artifact: Artifact, который нужно прочитать.
        preview_chars: Максимальное количество символов preview для текстовых файлов.

    Returns:
        ArtifactContentPreview с техническими признаками файла, preview и ошибкой чтения.
    """

    path = Path(artifact.uri)
    exists = path.exists() and path.is_file()
    is_text = _is_text_mime_type(artifact.mime_type)
    size_bytes = path.stat().st_size if exists else None
    if not exists:
        return ArtifactContentPreview(
            artifact_id=artifact.artifact_id,
            uri=artifact.uri,
            exists=False,
            is_text=is_text,
            size_bytes=None,
            preview=None,
            preview_chars=preview_chars,
            truncated=False,
            error="artifact_file_not_found",
        )
    if not is_text:
        return ArtifactContentPreview(
            artifact_id=artifact.artifact_id,
            uri=artifact.uri,
            exists=True,
            is_text=False,
            size_bytes=size_bytes,
            preview=None,
            preview_chars=preview_chars,
            truncated=False,
            error="artifact_is_not_text",
        )

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ArtifactContentPreview(
            artifact_id=artifact.artifact_id,
            uri=artifact.uri,
            exists=True,
            is_text=True,
            size_bytes=size_bytes,
            preview=None,
            preview_chars=preview_chars,
            truncated=False,
            error="artifact_decode_failed",
        )

    safe_limit = max(0, preview_chars)
    preview = content[:safe_limit]
    return ArtifactContentPreview(
        artifact_id=artifact.artifact_id,
        uri=artifact.uri,
        exists=True,
        is_text=True,
        size_bytes=size_bytes,
        total_chars=len(content),
        preview=preview,
        preview_chars=preview_chars,
        truncated=len(content) > len(preview),
        error=None,
    )


def _is_text_mime_type(mime_type: str) -> bool:
    """Проверяет, можно ли MIME-тип безопасно читать как UTF-8 текст.

    Args:
        mime_type: MIME-тип artifact.

    Returns:
        ``True`` для текстовых, JSON, JSONL и CSV artifacts.
    """

    normalized = (mime_type or "").lower()
    return (
        normalized.startswith("text/")
        or normalized in {
            "application/json",
            "application/x-jsonlines",
            "application/jsonl",
            "text/csv",
        }
    )


def _read_text_file(uri: str, *, max_chars: int | None = None) -> str | None:
    """Читает текстовый файл по URI/path.

    Args:
        uri: Путь к локальному файлу artifact.
        max_chars: Опциональный лимит символов.

    Returns:
        Текст файла или ``None``, если файл отсутствует либо не читается как UTF-8.
    """

    path = Path(uri)
    if not path.exists() or not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    if max_chars is None:
        return content
    return content[:max_chars]


__all__ = [
    "ArtifactContentPreview",
    "ArtifactDetails",
    "NodeDetails",
    "NodeInspectorView",
    "NodeStateDiff",
    "RunGraph",
    "RunInspectionService",
    "RunResult",
    "RunSummary",
    "SnapshotSection",
]
