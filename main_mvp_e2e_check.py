"""End-to-end smoke test MVP архитектуры research-agent без внешнего LLM.

Содержит:
- DeterministicMvpGraph: предсказуемый graph, имитирующий успешный запуск агента.
- MvpE2EContext: контейнер сервисов и агента для сценария.
- _build_context: сборка сервисов, агента и API client.
- _run_standard_case: проверка обычного LangChain input строкой.
- _run_messages_case: проверка стандартного LangChain messages input.
- _run_branch_case: проверка branch_from node и повторного запуска из ветки.
- _run_dialog_context_case: проверка follow-up запуска с context_runs.
- _run_api_case: проверка API endpoints для UI.
- _print_run_summary: печать краткой сводки RunResult.
- _assert_condition: простая проверка инвариантов сценария.
- main: последовательный запуск всех MVP e2e проверок.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from planner_agent import ContextRunRef, ResearchAgent  # noqa: E402
from planner_agent.models import AgentState  # noqa: E402
from planner_agent.schemas.lineage import BranchRequest, StateNode  # noqa: E402
from planner_agent.services.artifact_service import ArtifactService  # noqa: E402
from planner_agent.services.dialog_context_service import DialogContextService  # noqa: E402
from planner_agent.services.lineage_service import LineageService  # noqa: E402
from planner_agent.services.run_inspection_service import (  # noqa: E402
    RunInspectionService,
    RunResult,
)
from planner_agent.http_api import ApiSettings, create_app  # noqa: E402
from planner_agent.http_api.config import ApiServices  # noqa: E402


RUNS_DIR = PROJECT_ROOT / "examples" / "runs_mvp_e2e"


class DeterministicMvpGraph:
    """Предсказуемый graph для проверки архитектуры без вызова внешней модели.

    Args:
        lineage_service: Сервис записи ResearchRun и StateNode.
        artifact_service: Сервис записи artifacts.

    Returns:
        Объект с методом ``ainvoke``, совместимый с ResearchAgent facade.
    """

    def __init__(
            self,
            lineage_service: LineageService,
            artifact_service: ArtifactService,
    ) -> None:
        """Сохраняет сервисы для записи lineage и artifacts.

        Args:
            lineage_service: Сервис lineage.
            artifact_service: Сервис artifacts.

        Returns:
            None.
        """

        self.lineage_service = lineage_service
        self.artifact_service = artifact_service

    async def ainvoke(
            self,
            state: AgentState,
            config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Имитирует полный исследовательский запуск.

        Args:
            state: Входное состояние агента.
            config: Неиспользуемый конфиг запуска.

        Returns:
            Словарь с финальным состоянием агента.
        """

        run_record = self.lineage_service.get_run(state.run_id) if state.run_id else None
        if run_record is None:
            run_record = self.lineage_service.create_run(
                initial_user_query=state.initial_user_query,
                session_id=state.session_id,
                user_id=state.user_id,
                title=f"MVP e2e: {state.initial_user_query[:60]}",
            )

        parent_ids = state.parent_node_ids or (
            [state.current_node_id] if state.current_node_id else []
        )
        context_node = self._append_context_node(run_record.run_id, state, parent_ids)
        plan_node = self._append_plan_node(run_record.run_id, state, context_node.node_id)
        task_node = self._append_task_node(run_record.run_id, state, plan_node.node_id)
        final_node, final_report = self._append_final_node(
            run_id=run_record.run_id,
            state=state,
            parent_node_id=task_node.node_id,
        )

        messages = list(state.messages or [])
        messages.append(AIMessage(content=final_report))
        artifact_index = {
            artifact.artifact_id: artifact.model_dump(mode="json")
            for artifact in self.artifact_service.list_artifacts(run_record.run_id)
        }
        return {
            **state.model_dump(),
            "run_id": run_record.run_id,
            "current_node_id": final_node.node_id,
            "parent_node_ids": [final_node.node_id],
            "artifact_index": artifact_index,
            "final_report": final_report,
            "messages": messages,
        }

    def _append_context_node(
            self,
            run_id: str,
            state: AgentState,
            parent_ids: list[str],
    ) -> StateNode:
        """Создает context_snapshot node.

        Args:
            run_id: Идентификатор ResearchRun.
            state: Текущее состояние агента.
            parent_ids: Родительские nodes для нового node.

        Returns:
            Созданный StateNode.
        """

        node = StateNode(
            run_id=run_id,
            parent_ids=parent_ids,
            node_type="context_snapshot",
            title="MVP context snapshot",
            status="succeeded",
            summary="Captured input, filesystem context and dialog context.",
        )
        return self.lineage_service.append_node(
            node,
            state={
                "run_id": run_id,
                "initial_user_query": state.initial_user_query,
                "filesystem_context": state.filesystem_context,
                "ephemeral_recalls": state.ephemeral_recalls,
            },
        )

    def _append_plan_node(
            self,
            run_id: str,
            state: AgentState,
            parent_node_id: str,
    ) -> StateNode:
        """Создает plan_created node.

        Args:
            run_id: Идентификатор ResearchRun.
            state: Текущее состояние агента.
            parent_node_id: Родительский node.

        Returns:
            Созданный StateNode.
        """

        node = StateNode(
            run_id=run_id,
            parent_ids=[parent_node_id],
            node_type="plan_created",
            title="MVP plan created",
            status="succeeded",
            summary="Created deterministic MVP plan with one analysis task.",
        )
        return self.lineage_service.append_node(
            node,
            state={
                "run_id": run_id,
                "objective": state.initial_user_query,
                "plan": {
                    "1": {
                        "description": "Inspect available context and produce a report.",
                        "status": "completed",
                    }
                },
            },
        )

    def _append_task_node(
            self,
            run_id: str,
            state: AgentState,
            parent_node_id: str,
    ) -> StateNode:
        """Создает task_completed node и dataset/tool_trace artifacts.

        Args:
            run_id: Идентификатор ResearchRun.
            state: Текущее состояние агента.
            parent_node_id: Родительский node.

        Returns:
            Созданный StateNode.
        """

        node = StateNode(
            run_id=run_id,
            parent_ids=[parent_node_id],
            node_type="task_completed",
            title="MVP task completed",
            status="succeeded",
            summary="Created deterministic dataset and tool trace artifacts.",
        )
        dataset = self.artifact_service.write_artifact(
            run_id=run_id,
            node_id=node.node_id,
            kind="dataset",
            filename=f"tasks/{node.node_id}/tool_results/context_summary.json",
            content=json.dumps(
                {
                    "query": state.initial_user_query,
                    "has_dialog_context": "dialog_context" in state.ephemeral_recalls,
                    "filesystem_context_keys": sorted(state.filesystem_context.keys()),
                    "message_count": len(state.messages),
                },
                ensure_ascii=False,
                indent=2,
            ),
            mime_type="application/json",
            summary="Deterministic context summary dataset.",
            metadata={"artifact_role": "captured_tool_result", "tool_name": "mvp_context_summary"},
        )
        trace = self.artifact_service.write_artifact(
            run_id=run_id,
            node_id=node.node_id,
            kind="tool_trace",
            filename=f"tasks/{node.node_id}/tool_calls/mvp_context_summary.txt",
            content="mvp_context_summary(query, filesystem_context, ephemeral_recalls)",
            mime_type="text/plain",
            summary="Deterministic tool trace.",
            metadata={"artifact_role": "tool_call_trace", "tool_name": "mvp_context_summary"},
        )
        node.artifact_refs = [dataset.artifact_id]
        node.tool_trace_refs = [trace.artifact_id]
        return self.lineage_service.append_node(
            node,
            state={
                "run_id": run_id,
                "task_result": "MVP task completed.",
                "artifact_refs": node.artifact_refs,
                "tool_trace_refs": node.tool_trace_refs,
            },
        )

    def _append_final_node(
            self,
            *,
            run_id: str,
            state: AgentState,
            parent_node_id: str,
    ) -> tuple[StateNode, str]:
        """Создает final_report node и report artifact.

        Args:
            run_id: Идентификатор ResearchRun.
            state: Текущее состояние агента.
            parent_node_id: Родительский node.

        Returns:
            Кортеж ``(StateNode, final_report)``.
        """

        dialog_note = (
            "Dialog context was available."
            if "dialog_context" in state.ephemeral_recalls
            else "No dialog context was provided."
        )
        final_report = (
            "# MVP E2E Report\n\n"
            f"Query: {state.initial_user_query}\n\n"
            f"Session: {state.session_id or 'none'}\n\n"
            f"{dialog_note}\n\n"
            "Artifacts and lineage were written successfully."
        )
        node = StateNode(
            run_id=run_id,
            parent_ids=[parent_node_id],
            node_type="final_report",
            title="MVP final report",
            status="succeeded",
            summary=final_report[:500],
        )
        report = self.artifact_service.write_artifact(
            run_id=run_id,
            node_id=node.node_id,
            kind="report",
            filename="final_report.md",
            content=final_report,
            mime_type="text/markdown",
            summary=final_report[:500],
            metadata={"node_type": "final_report"},
        )
        node.artifact_refs = [report.artifact_id]
        node = self.lineage_service.append_node(
            node,
            state={
                "run_id": run_id,
                "final_report": final_report,
                "messages": [
                    message.model_dump(mode="json")
                    for message in [*state.messages, AIMessage(content=final_report)]
                ],
                "ephemeral_recalls": state.ephemeral_recalls,
            },
        )
        return node, final_report


@dataclass
class MvpE2EContext:
    """Контейнер объектов полного MVP e2e сценария.

    Args:
        agent: ResearchAgent с deterministic graph.
        lineage_service: Сервис lineage.
        artifact_service: Сервис artifacts.
        inspection_service: Сервис inspection.
        api_client: TestClient для проверки UI API.

    Returns:
        Контейнер зависимостей e2e сценария.
    """

    agent: ResearchAgent
    lineage_service: LineageService
    artifact_service: ArtifactService
    inspection_service: RunInspectionService
    api_client: TestClient


def _build_context() -> MvpE2EContext:
    """Собирает сервисы, агента и API client для сценария.

    Returns:
        MvpE2EContext.
    """

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    lineage_service = LineageService(RUNS_DIR)
    artifact_service = ArtifactService(RUNS_DIR)
    inspection_service = RunInspectionService(lineage_service, artifact_service)
    agent = ResearchAgent(
        graph=DeterministicMvpGraph(lineage_service, artifact_service),
        lineage_service=lineage_service,
        artifact_service=artifact_service,
        runs_dir=str(RUNS_DIR),
    )
    api_services = ApiServices(
        lineage_service=lineage_service,
        artifact_service=artifact_service,
        inspection_service=inspection_service,
        dialog_context_service=DialogContextService(inspection_service),
        agent=agent,
    )
    api_client = TestClient(
        create_app(
            settings=ApiSettings(
                workspace_root=str(PROJECT_ROOT),
                runs_dir=str(RUNS_DIR),
            ),
            services=api_services,
        )
    )
    return MvpE2EContext(
        agent=agent,
        lineage_service=lineage_service,
        artifact_service=artifact_service,
        inspection_service=inspection_service,
        api_client=api_client,
    )


async def _run_standard_case(context: MvpE2EContext) -> str:
    """Проверяет обычный запуск агента от строкового LangChain input.

    Args:
        context: Контейнер e2e зависимостей.

    Returns:
        run_id созданного запуска.
    """

    print("\nCase 1: standard string input")
    messages = await context.agent.ainvoke(
        "Analyze client-42 behavior from available context",
        session_id="mvp-session",
        user_id="mvp-user",
    )
    _assert_condition(messages and isinstance(messages[-1], BaseMessage), "standard input returned messages")
    _assert_condition(context.agent.last_run_id != "", "standard input saved run_id")
    result = context.agent.get_run_result()
    _assert_condition(result is not None, "standard input has run result")
    assert result is not None
    _assert_condition(result.summary.node_count >= 4, "standard input wrote lineage nodes")
    _assert_condition(result.summary.artifact_count >= 3, "standard input wrote artifacts")
    _print_run_summary("standard", result)
    return result.run.run_id


async def _run_messages_case(context: MvpE2EContext) -> str:
    """Проверяет запуск агента от списка LangChain messages.

    Args:
        context: Контейнер e2e зависимостей.

    Returns:
        run_id созданного запуска.
    """

    print("\nCase 2: LangChain messages input")
    messages = await context.agent.ainvoke(
        [
            HumanMessage(content="Review previous analysis style"),
            AIMessage(content="Previous answer placeholder"),
            HumanMessage(content="Continue with a compact MVP check"),
        ],
        session_id="mvp-messages-session",
    )
    _assert_condition(messages[-1].content.startswith("# MVP E2E Report"), "messages input returned final report")
    result = context.agent.get_run_result()
    _assert_condition(result is not None, "messages input has run result")
    assert result is not None
    _print_run_summary("messages", result)
    return result.run.run_id


async def _run_branch_case(context: MvpE2EContext, source_run_id: str) -> str:
    """Проверяет создание и запуск ветки от final_report node.

    Args:
        context: Контейнер e2e зависимостей.
        source_run_id: Идентификатор базового запуска.

    Returns:
        run_id созданной ветки.
    """

    print("\nCase 3: branch from final node")
    graph = context.agent.get_run_graph(source_run_id)
    _assert_condition(graph is not None, "source graph exists")
    assert graph is not None
    source_node = next(node for node in reversed(graph.nodes) if node.node_type == "final_report")
    datasets = [
        artifact.artifact_id
        for artifact in context.agent.list_artifacts(source_run_id)
        if artifact.kind == "dataset"
    ]
    branch_messages = await context.agent.ainvoke_branch(
        BranchRequest(
            source_run_id=source_run_id,
            source_node_id=source_node.node_id,
            new_task="Check alternative hypothesis from saved state",
            branch_mode="what_if",
            artifact_refs=datasets,
        )
    )
    _assert_condition(branch_messages[-1].content.startswith("# MVP E2E Report"), "branch returned final report")
    branch_result = context.agent.get_run_result()
    _assert_condition(branch_result is not None, "branch has run result")
    assert branch_result is not None
    _assert_condition(branch_result.run.parent_run_id == source_run_id, "branch parent_run_id is linked")
    _print_run_summary("branch", branch_result)
    return branch_result.run.run_id


async def _run_dialog_context_case(
        context: MvpE2EContext,
        base_run_id: str,
        branch_run_id: str,
) -> str:
    """Проверяет follow-up запуск с явным context_runs.

    Args:
        context: Контейнер e2e зависимостей.
        base_run_id: Идентификатор базового run.
        branch_run_id: Идентификатор branch run.

    Returns:
        run_id dialog запуска.
    """

    print("\nCase 4: dialog over existing runs")
    messages = await context.agent.ainvoke(
        {
            "input": "Compare base run and branch run. Which one has stronger evidence?",
            "context_runs": [
                ContextRunRef(run_id=base_run_id, role="base").model_dump(),
                ContextRunRef(run_id=branch_run_id, role="branch").model_dump(),
            ],
        },
        session_id="mvp-dialog-session",
    )
    _assert_condition(messages[-1].content.startswith("# MVP E2E Report"), "dialog returned final report")
    _assert_condition(context.agent.last_state is not None, "dialog saved final state")
    assert context.agent.last_state is not None
    dialog_context = context.agent.last_state.ephemeral_recalls.get("dialog_context", "")
    _assert_condition(base_run_id in dialog_context, "dialog context includes base run")
    _assert_condition(branch_run_id in dialog_context, "dialog context includes branch run")
    result = context.agent.get_run_result()
    _assert_condition(result is not None, "dialog has run result")
    assert result is not None
    _print_run_summary("dialog", result)
    return result.run.run_id


def _run_api_case(
        context: MvpE2EContext,
        base_run_id: str,
        branch_run_id: str,
        dialog_run_id: str,
) -> None:
    """Проверяет основные API endpoints будущего UI.

    Args:
        context: Контейнер e2e зависимостей.
        base_run_id: Идентификатор базового run.
        branch_run_id: Идентификатор branch run.
        dialog_run_id: Идентификатор dialog run.

    Returns:
        None.
    """

    print("\nCase 5: UI API endpoints")
    client = context.api_client
    health = client.get("/api/v1/health")
    _assert_condition(health.status_code == 200, "API health is OK")

    graph = client.get(f"/api/v1/runs/{base_run_id}/graph")
    _assert_condition(graph.status_code == 200, "API graph endpoint is OK")
    graph_payload = graph.json()
    final_node_id = next(
        node["node_id"]
        for node in reversed(graph_payload["nodes"])
        if node["node_type"] == "final_report"
    )
    inspector = client.get(f"/api/v1/runs/{base_run_id}/nodes/{final_node_id}/inspector")
    _assert_condition(inspector.status_code == 200, "API node inspector endpoint is OK")
    _assert_condition(inspector.json()["node"]["node_id"] == final_node_id, "API inspector returns selected node")

    artifacts = client.get(f"/api/v1/runs/{base_run_id}/artifacts")
    _assert_condition(artifacts.status_code == 200, "API artifacts endpoint is OK")
    first_artifact_id = artifacts.json()[0]["artifact_id"]
    preview = client.get(f"/api/v1/runs/{base_run_id}/artifacts/{first_artifact_id}/preview")
    _assert_condition(preview.status_code == 200, "API artifact preview endpoint is OK")

    dialog_context = client.post(
        "/api/v1/dialog-context",
        json={
            "user_query": "Compare base and branch before running agent",
            "context_runs": [
                {"run_id": base_run_id, "role": "base"},
                {"run_id": branch_run_id, "role": "branch"},
                {"run_id": dialog_run_id, "role": "dialog"},
            ],
        },
    )
    _assert_condition(dialog_context.status_code == 200, "API dialog-context endpoint is OK")
    rendered = dialog_context.json()["context"]["rendered_context"]
    _assert_condition(base_run_id in rendered and branch_run_id in rendered, "API dialog context includes runs")

    invoke = client.post(
        "/api/v1/runs/invoke",
        json={
            "user_query": "Run from UI API",
            "session_id": "mvp-api-session",
            "context_runs": [{"run_id": base_run_id, "role": "base"}],
        },
    )
    _assert_condition(invoke.status_code == 200, "API run invoke endpoint is OK")
    _assert_condition(invoke.json()["run_id"], "API run invoke returned run_id")

    branch_invoke = client.post(
        "/api/v1/branches/invoke",
        json={
            "source_run_id": base_run_id,
            "source_node_id": final_node_id,
            "new_task": "Run branch from UI API",
            "branch_mode": "what_if",
        },
    )
    _assert_condition(branch_invoke.status_code == 200, "API branch invoke endpoint is OK")
    _assert_condition(
        branch_invoke.json()["result"]["run"]["parent_run_id"] == base_run_id,
        "API branch invoke linked parent_run_id",
    )
    print("API endpoints checked successfully.")


def _print_run_summary(label: str, result: RunResult) -> None:
    """Печатает краткую сводку запуска.

    Args:
        label: Человекочитаемая метка кейса.
        result: RunResult для печати.

    Returns:
        None.
    """

    print(
        f"{label}: run_id={result.run.run_id} | "
        f"nodes={result.summary.node_count} | "
        f"artifacts={result.summary.artifact_count} | "
        f"final_report_chars={len(result.final_report or '')}"
    )


def _assert_condition(condition: bool, message: str) -> None:
    """Проверяет условие и печатает статус.

    Args:
        condition: Проверяемое условие.
        message: Описание проверки.

    Returns:
        None.

    Raises:
        AssertionError: Если условие ложно.
    """

    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


async def main() -> None:
    """Запускает полный MVP e2e smoke test.

    Args:
        Отсутствуют.

    Returns:
        None.
    """

    print("Starting MVP e2e architecture check without external LLM.")
    print(f"runs_dir: {RUNS_DIR}")
    context = _build_context()
    base_run_id = await _run_standard_case(context)
    await _run_messages_case(context)
    branch_run_id = await _run_branch_case(context, base_run_id)
    dialog_run_id = await _run_dialog_context_case(context, base_run_id, branch_run_id)
    _run_api_case(context, base_run_id, branch_run_id, dialog_run_id)
    print("\nMVP e2e architecture check completed successfully.")
    print(f"base_run_id: {base_run_id}")
    print(f"branch_run_id: {branch_run_id}")
    print(f"dialog_run_id: {dialog_run_id}")


if __name__ == "__main__":
    asyncio.run(main())
