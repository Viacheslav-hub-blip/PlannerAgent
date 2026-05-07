"""Тестовый запуск research-agent с моделью DeepSeek из ``model.py``.

Содержит:
- SmokeSandbox: минимальная in-memory песочница для dataframe-контекста агента.
- _load_example_dataframe: загрузка тестовой таблицы для стартового контекста.
- build_agent: сборка ResearchAgent с моделью из ``model.py`` и тестовыми tools.
- _format_message_content: подготовка содержимого LangChain message к печати.
- _find_latest_run_dir: поиск последнего каталога запуска.
- _read_jsonl_rows: чтение jsonl-файла с пропуском поврежденных строк.
- _print_progress_event: печать одного события lineage.
- _print_artifact_progress: печать новых artifacts.
- _monitor_run_progress: фоновая печать промежуточных шагов агента.
- _invoke_agent_with_timeout: запуск агента с ограничением времени ожидания.
- _print_run_result_api: печать результата через публичный API чтения ResearchRun.
- main: асинхронный smoke-test запуска агента через ``ainvoke``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from examples.fake_spark_tools import build_fake_spark_tools  # noqa: E402
from model import model as deepseek_model  # noqa: E402
from planner_agent import ResearchAgent  # noqa: E402


class SmokeSandbox:
    """Минимальная песочница для проверки агента на локальном dataframe.

    Args:
        dataframe: Стартовая таблица, которая будет доступна агенту как
            переменная ``df_current``.

    Returns:
        Экземпляр песочницы с методами, которые ожидают workspace tools агента.
    """

    def __init__(self, dataframe: pd.DataFrame) -> None:
        """Сохраняет стартовую таблицу в словарь переменных.

        Args:
            dataframe: Таблица pandas DataFrame для первичного контекста.

        Returns:
            None.
        """

        self.last_dataframe_variable = "df_current"
        self.globals: dict[str, Any] = {"df_current": dataframe}

    async def get_all_variable_previews(self) -> dict[str, str]:
        """Возвращает компактные описания всех переменных песочницы.

        Args:
            Отсутствуют.

        Returns:
            Словарь ``имя переменной -> текстовое описание``. Для DataFrame
            описание включает размерность, колонки, количество пустых значений
            и первые строки.
        """

        previews: dict[str, str] = {}
        for name, value in self.globals.items():
            if isinstance(value, pd.DataFrame):
                null_counts = value.isna().sum().to_dict()
                previews[name] = (
                    f"shape={value.shape}; "
                    f"columns={list(value.columns)}; "
                    f"null_counts={null_counts}; "
                    f"head={value.head(3).to_dict(orient='records')}"
                )
            else:
                previews[name] = str(value)[:1_000]
        return previews

    async def add_variable(self, name: str, value: object) -> None:
        """Добавляет или обновляет переменную в песочнице.

        Args:
            name: Имя переменной.
            value: Значение переменной.

        Returns:
            None.
        """

        self.globals[name] = value
        if isinstance(value, pd.DataFrame):
            self.last_dataframe_variable = name

    async def get_variable(self, name: str) -> object:
        """Возвращает переменную из песочницы по имени.

        Args:
            name: Имя переменной.

        Returns:
            Значение переменной или ``None``, если такой переменной нет.
        """

        return self.globals.get(name)


def _load_example_dataframe() -> pd.DataFrame:
    """Загружает тестовую таблицу для стартового контекста агента.

    Args:
        Отсутствуют.

    Returns:
        DataFrame из ``examples/data/cspfs_repo_features3.hits_extra_info_129372427_view.csv``. Если файл недоступен,
        возвращается маленькая встроенная таблица для smoke-test.
    """

    data_path = PROJECT_ROOT / "examples" / "data" / "cspfs_repo_features3.hits_extra_info_129372427_view.csv"
    if data_path.exists():
        return pd.read_csv(data_path)

    return pd.DataFrame(
        [
            {
                "client_id": "client-42",
                "event_date": "2025-01-03",
                "event_type": "payment",
                "amount": 1500.0,
                "merchant_name": "AutoPay Mobile",
                "recipient": "self_account",
            }
        ]
    )


def build_agent() -> ResearchAgent:
    """Собирает ResearchAgent для ручной проверки DeepSeek/OpenRouter.

    Args:
        Отсутствуют.

    Returns:
        Экземпляр ResearchAgent, совместимый с LangChain ``ainvoke``.
    """

    example_root = PROJECT_ROOT / "examples"
    sandbox = SmokeSandbox(_load_example_dataframe())
    spark_tools = build_fake_spark_tools(
        delay_seconds=0.5,
        transaction_count=120,
        day_event_count=40,
    )

    return ResearchAgent(
        model=deepseek_model,
        sandbox=sandbox,
        tools=spark_tools,
        enable_workspace_tools=True,
        workspace_root=str(PROJECT_ROOT),
        sources_dir=str(example_root / "data"),
        contexts_dir=str(example_root / "skills"),
        skills_dir=str(example_root / "skills"),
        memory_dir=str(example_root / "memory"),
        runs_dir=str(example_root / "runs"),
    )


def _format_message_content(content: object) -> str:
    """Преобразует содержимое LangChain message в строку для консоли.

    Args:
        content: Содержимое сообщения LangChain. Обычно это строка, но у
            некоторых моделей может быть список блоков.

    Returns:
        Строковое представление ответа.
    """

    if isinstance(content, str):
        return content
    return str(content)


def _find_latest_run_dir(runs_dir: Path, ignored_run_ids: set[str]) -> Path | None:
    """Находит самый свежий каталог ResearchRun, которого нет в ignored_run_ids.

    Args:
        runs_dir: Каталог, в котором research-agent хранит запуски.
        ignored_run_ids: Набор run_id, существовавших до текущего запуска.

    Returns:
        Путь к самому свежему новому каталогу запуска или ``None``.
    """

    candidates = [
        path
        for path in runs_dir.iterdir()
        if path.is_dir() and path.name not in ignored_run_ids
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    """Читает JSONL-файл и возвращает валидные строки как словари.

    Args:
        path: Путь к JSONL-файлу.

    Returns:
        Список словарей. Неполные или поврежденные строки пропускаются, чтобы
        монитор не падал во время параллельной записи файла агентом.
    """

    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _print_progress_event(node: dict[str, Any]) -> None:
    """Печатает одно lineage-событие в компактном виде.

    Args:
        node: JSON-представление StateNode.

    Returns:
        None.
    """

    node_type = node.get("node_type", "unknown")
    status = node.get("status", "unknown")
    title = node.get("title", "")
    summary = str(node.get("summary", "")).replace("\n", " ")[:220]
    created_at = node.get("created_at", "")
    print(
        f"[progress] {created_at} | {node_type} | {status} | {title} | {summary}",
        flush=True,
    )


def _print_artifact_progress(artifact: dict[str, Any]) -> None:
    """Печатает информацию о новом artifact.

    Args:
        artifact: JSON-представление Artifact.

    Returns:
        None.
    """

    artifact_id = artifact.get("artifact_id", "")
    kind = artifact.get("kind", "")
    uri = artifact.get("uri", "")
    print(f"[artifact] {artifact_id} | {kind} | {uri}", flush=True)


async def _monitor_run_progress(
        runs_dir: Path,
        ignored_run_ids: set[str],
        stop_event: asyncio.Event,
        poll_interval_seconds: float = 2.0,
) -> None:
    """Фоном печатает новые lineage nodes и artifacts текущего запуска.

    Args:
        runs_dir: Каталог ``runs``, куда агент пишет lineage и artifacts.
        ignored_run_ids: Запуски, которые существовали до старта текущего main.
        stop_event: Событие остановки фонового мониторинга.
        poll_interval_seconds: Пауза между проверками файлов.

    Returns:
        None.
    """

    printed_node_ids: set[str] = set()
    printed_artifact_ids: set[str] = set()
    active_run_dir: Path | None = None

    while not stop_event.is_set():
        active_run_dir = active_run_dir or _find_latest_run_dir(
            runs_dir=runs_dir,
            ignored_run_ids=ignored_run_ids,
        )
        if active_run_dir is not None:
            for node in _read_jsonl_rows(active_run_dir / "lineage.jsonl"):
                node_id = str(node.get("node_id") or "")
                if node_id and node_id not in printed_node_ids:
                    printed_node_ids.add(node_id)
                    _print_progress_event(node)

            for artifact in _read_jsonl_rows(active_run_dir / "artifacts.jsonl"):
                artifact_id = str(artifact.get("artifact_id") or "")
                if artifact_id and artifact_id not in printed_artifact_ids:
                    printed_artifact_ids.add(artifact_id)
                    _print_artifact_progress(artifact)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            continue


async def _invoke_agent_with_timeout(agent: ResearchAgent) -> list[Any]:
    """Запускает агента с ограничением времени для ручного smoke-test.

    Args:
        agent: Экземпляр ResearchAgent, который нужно проверить.

    Returns:
        Список LangChain messages из финального состояния агента.

    Raises:
        TimeoutError: Если тестовый запуск не завершился за заданное время.
    """

    runs_dir = PROJECT_ROOT / "examples" / "runs"
    ignored_run_ids = {path.name for path in runs_dir.iterdir() if path.is_dir()}
    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(
        _monitor_run_progress(
            runs_dir=runs_dir,
            ignored_run_ids=ignored_run_ids,
            stop_event=stop_event,
        )
    )

    return await asyncio.wait_for(
        _invoke_agent_and_stop_monitor(
            agent=agent,
            stop_event=stop_event,
            monitor_task=monitor_task,
        ),
        timeout=300,
    )


async def _invoke_agent_and_stop_monitor(
        *,
        agent: ResearchAgent,
        stop_event: asyncio.Event,
        monitor_task: asyncio.Task[None],
) -> list[Any]:
    """Запускает агента и гарантированно останавливает монитор прогресса.

    Args:
        agent: Экземпляр ResearchAgent.
        stop_event: Событие остановки мониторинга.
        monitor_task: Фоновая задача мониторинга.

    Returns:
        Список LangChain messages из финального состояния агента.
    """

    try:
        return await agent.ainvoke(
            {
                "user_query": (
                    "Проведи глубокий анализ клиента client-42. "
                ),
                "session_id": "deepseek-smoke-session",
                "user_id": "manual-tester",
            },
            config={"recursion_limit": 30},
        )
    finally:
        stop_event.set()
        await monitor_task


def _print_run_result_api(agent: ResearchAgent) -> None:
    """Печатает пример чтения результата работы через публичный API агента.

    Args:
        agent: Экземпляр ResearchAgent после завершенного запуска через ``ainvoke``.

    Returns:
        None. Сводка ResearchRun, граф, artifacts и детали финального node печатаются
        в консоль как пример интеграции без UI.
    """

    result = agent.get_run_result()

    print("\nRun result API\n==============")
    if result is None:
        print("Run result is unavailable.")
        return

    print(f"run_id: {result.run.run_id}")
    print(f"node_count: {result.summary.node_count}")
    print(f"artifact_count: {result.summary.artifact_count}")
    print(f"final_report_node_id: {result.summary.final_report_node_id}")
    print(f"final_report_artifact_id: {result.summary.final_report_artifact_id}")
    print(f"final_report_chars: {len(result.final_report or '')}")
    print(f"messages_from_final_state: {len(result.messages)}")

    if result.final_state is not None:
        print(f"final_state_keys: {sorted(result.final_state.keys())}")

    graph = agent.get_run_graph()
    print("\nGraph nodes")
    if graph is None:
        print("(graph unavailable)")
    else:
        for node in graph.nodes:
            print(f"- {node.node_type} | {node.status} | {node.title} | {node.node_id}")

    print("\nArtifacts")
    for artifact in agent.list_artifacts():
        role = artifact.metadata.get("artifact_role") or artifact.metadata.get("node_type") or ""
        tool_name = artifact.metadata.get("tool_name") or ""
        metadata_parts = [str(part) for part in (role, tool_name) if part]
        metadata_text = " | ".join(metadata_parts)
        if metadata_text:
            print(f"- {artifact.artifact_id}: {artifact.kind} | {metadata_text} | {artifact.uri}")
        else:
            print(f"- {artifact.artifact_id}: {artifact.kind} | {artifact.uri}")

    if result.summary.final_report_node_id is None:
        return

    details = agent.get_node_details(result.summary.final_report_node_id)
    print("\nFinal node details")
    if details is None:
        print("(final node details unavailable)")
        return

    snapshot_keys = sorted(details.snapshot.keys()) if details.snapshot else []
    print(f"node_type: {details.node.node_type}")
    print(f"linked_artifacts: {len(details.artifacts)}")
    print(f"snapshot_keys: {snapshot_keys}")


async def main() -> None:
    """Запускает ручной smoke-test агента с моделью из ``model.py``.

    Args:
        Отсутствуют.

    Returns:
        None. Результат печатается в консоль, а run/artifacts сохраняются в
        ``examples/runs``.
    """

    agent = build_agent()
    print("Starting DeepSeek smoke-test. Timeout: 300 seconds.")
    try:
        messages = await _invoke_agent_with_timeout(agent)
    except TimeoutError:
        print("\nRun failed: timeout after 300 seconds.")
        print("Check the last [progress] or [llm] line above to see where the run stopped.")
        return
    except Exception as exc:
        print("\nRun failed with error\n=====================")
        print(str(exc))
        print("\nCheck the last [progress] or [llm] line above to see where the run stopped.")
        return

    final_message = messages[-1] if messages else None
    print("\nFinal report\n============")
    print(_format_message_content(final_message.content) if final_message else "")

    _print_run_result_api(agent)


if __name__ == "__main__":
    asyncio.run(main())
