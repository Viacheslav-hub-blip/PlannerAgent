"""Автоматический запуск DeepAgent на тестовой корзине и расчет двух метрик.

Содержит классы и функции:
- ToolCallRecord: нормализованная запись вызова инструмента.
- RecordingCallbackHandler: callback для сбора вызовов и ошибок инструментов.
- load_basket: чтение и валидация JSON-корзины.
- run_case_worker: выполнение одного кейса внутри изолированного процесса.
- build_process_group_options: параметры отдельной группы процессов для Windows и POSIX.
- terminate_process_tree: завершение worker и его дочерних процессов.
- run_case_with_timeout: запуск worker-процесса с жестким таймаутом.
- evaluate_answer: regex-проверка итогового ответа.
- evaluate_tool_calls: regex-проверка имен и параметров инструментов.
- calculate_metrics: расчет процентов по завершенной серии.
- print_progress_bar: вывод прогресса обработки корзины в stderr.
- synchronize_queries: синхронизация запросов из ``run.py`` перед тестом.
- main: запуск всей корзины без параметров или внутреннего worker-режима.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASKET_PATH = Path(__file__).resolve().with_name("test_basket.json")
DEFAULT_REPORT_PATH = PROJECT_ROOT / "runs" / "test_basket_report.json"
DEFAULT_MARKDOWN_PATH = Path(__file__).resolve().with_name("TEST_CASES.md")
DEFAULT_RUN_PATH = PROJECT_ROOT / "run.py"
WORKER_CASE_ENV = "DEEP_AGENT_TEST_WORKER_CASE"
WORKER_RESULT_ENV = "DEEP_AGENT_TEST_WORKER_RESULT"


@dataclass(slots=True)
class ToolCallRecord:
    """Хранит один фактический вызов инструмента.

    Args:
        name: Имя вызванного инструмента.
        arguments: Аргументы вызова в JSON-совместимом виде.
        error: Текст ошибки инструмента или пустая строка при успехе.
    """

    name: str
    arguments: Any
    error: str = ""


class RecordingCallbackHandler(BaseCallbackHandler):
    """Собирает структурированные вызовы инструментов текущего запуска.

    Returns:
        Callback handler, записи которого доступны через атрибут ``calls``.
    """

    def __init__(self) -> None:
        """Создает пустой журнал вызовов.

        Returns:
            ``None``.
        """

        super().__init__()
        self.calls: list[ToolCallRecord] = []
        self._call_indexes: dict[str, int] = {}

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        inputs: dict[str, Any] | None = None,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Записывает имя и параметры начавшегося tool-вызова.

        Args:
            serialized: Метаданные LangChain с именем инструмента.
            input_str: Строковые аргументы, если структурированные не переданы.
            inputs: Структурированные аргументы инструмента.
            run_id: Идентификатор запуска для сопоставления ошибки.
            **kwargs: Неиспользуемые callback-параметры.

        Returns:
            ``None``.
        """

        del kwargs
        record = ToolCallRecord(
            name=str(serialized.get("name") or "(unknown)"),
            arguments=inputs if inputs is not None else input_str,
        )
        self.calls.append(record)
        if run_id is not None:
            self._call_indexes[str(run_id)] = len(self.calls) - 1

    def on_tool_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        """Добавляет ошибку к соответствующему tool-вызову.

        Args:
            error: Исключение, возникшее внутри инструмента.
            run_id: Идентификатор вызова инструмента.
            **kwargs: Неиспользуемые callback-параметры.

        Returns:
            ``None``.
        """

        del kwargs
        index = self._call_indexes.get(str(run_id))
        if index is not None:
            self.calls[index].error = f"{type(error).__name__}: {error}"


def load_basket(path: Path) -> dict[str, Any]:
    """Читает и минимально валидирует тестовую корзину.

    Args:
        path: Путь к JSON-файлу корзины.

    Returns:
        Словарь с настройками и списком тестовых кейсов.

    Raises:
        ValueError: Если обязательные поля корзины отсутствуют.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("cases"), list):
        raise ValueError("Поле cases должно быть списком.")
    for case in payload["cases"]:
        for field in ("id", "query", "answer_patterns", "tool_expectations"):
            if field not in case:
                raise ValueError(f"Кейс {case.get('id', '?')}: отсутствует поле {field}.")
    return payload


def _last_message_text(result: Any) -> str:
    """Извлекает текст последнего сообщения из результата агента.

    Args:
        result: Результат ``agent.invoke``.

    Returns:
        Текст финального сообщения или строковое представление результата.
    """

    if not isinstance(result, dict):
        return str(result)
    messages = result.get("messages") or []
    if not messages:
        return str(result)
    message = messages[-1]
    text = getattr(message, "text", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(message, "content", None)
    return content if isinstance(content, str) else str(message)


def run_case_worker(case: dict[str, Any], result_path: Path) -> int:
    """Выполняет один кейс и сохраняет сырой результат worker-процесса.

    Args:
        case: Описание тестового кейса из корзины.
        result_path: Путь для записи JSON-результата.

    Returns:
        Код процесса: ``0`` при штатном завершении invoke, иначе ``1``.
    """

    from deep_agent_test import build_analytics_deep_agent, load_deep_agent_settings
    from deep_agent_test.core.trace_logging import FileTraceCallbackHandler, build_trace_file_path
    from deep_agent_test.tools.fake_spark_data import build_fake_spark_data_tools
    from model import model

    settings = load_deep_agent_settings()
    trace_path = build_trace_file_path(
        settings.trace_log_dir,
        prefix=f"basket_case_{case['id']}",
    )
    recorder = RecordingCallbackHandler()
    trace_handler = FileTraceCallbackHandler(trace_path)
    started_at = time.monotonic()
    payload: dict[str, Any]

    try:
        data_tools = build_fake_spark_data_tools(query_parser_model=model)
        agent = build_analytics_deep_agent(model=model, settings=settings, data_tools=data_tools)
        result = agent.invoke(
            {"messages": [{"role": "user", "content": case["query"]}]},
            config={
                "callbacks": [recorder, trace_handler],
                "configurable": {
                    "thread_id": f"{settings.thread_id}-basket-{case['id']}-{uuid.uuid4().hex}",
                },
                "recursion_limit": settings.graph_recursion_limit,
            },
        )
        payload = {
            "status": "completed",
            "answer": _last_message_text(result),
            "tool_calls": [asdict(call) for call in recorder.calls],
            "duration_seconds": round(time.monotonic() - started_at, 3),
            "trace_path": str(trace_path),
            "error": "",
        }
        exit_code = 0
    except Exception as error:
        payload = {
            "status": "error",
            "answer": "",
            "tool_calls": [asdict(call) for call in recorder.calls],
            "duration_seconds": round(time.monotonic() - started_at, 3),
            "trace_path": str(trace_path),
            "error": f"{type(error).__name__}: {error}",
        }
        exit_code = 1

    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code


def build_process_group_options() -> dict[str, Any]:
    """Возвращает параметры запуска отдельной группы процессов.

    Returns:
        Для Windows - ``creationflags`` с новой группой процессов, для Linux и
        других POSIX-систем - ``start_new_session=True``.
    """

    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Завершает worker-процесс вместе с порожденными дочерними процессами.

    Args:
        process: Запущенный worker, который нужно остановить по таймауту.

    Returns:
        ``None``. После возврата worker завершен либо уже был завершен.
    """

    if process.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_case_with_timeout(
    case: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Запускает кейс в отдельном процессе и прерывает его по таймауту.

    Args:
        case: Описание тестового кейса.
        timeout_seconds: Максимальная длительность кейса в секундах.

    Returns:
        Сырой результат кейса со статусом ``completed``, ``error`` или ``timeout``.
    """

    with tempfile.TemporaryDirectory(prefix="deep_agent_case_") as temp_dir:
        result_path = Path(temp_dir) / "result.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
        ]
        worker_environment = os.environ.copy()
        worker_environment[WORKER_CASE_ENV] = str(case["id"])
        worker_environment[WORKER_RESULT_ENV] = str(result_path)
        started_at = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=worker_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **build_process_group_options(),
        )
        try:
            _, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            terminate_process_tree(process)
            _, stderr = process.communicate()
            return {
                "status": "timeout",
                "answer": "",
                "tool_calls": [],
                "duration_seconds": round(time.monotonic() - started_at, 3),
                "trace_path": "",
                "error": f"Кейс превысил таймаут {timeout_seconds:g} секунд.",
                "stderr": stderr.strip(),
            }

        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            result = {
                "status": "error",
                "answer": "",
                "tool_calls": [],
                "duration_seconds": round(time.monotonic() - started_at, 3),
                "trace_path": "",
                "error": f"Worker завершился с кодом {process.returncode} без result.json.",
            }
        result["stderr"] = stderr.strip()
        return result


def evaluate_answer(answer: str, patterns: list[str]) -> tuple[bool, list[str]]:
    """Проверяет свободный текст ответа набором обязательных regex.

    Args:
        answer: Финальный текст агента.
        patterns: Регулярные выражения, каждое из которых должно совпасть.

    Returns:
        Пара ``(успех, несовпавшие regex)``.
    """

    missing = [
        pattern
        for pattern in patterns
        if re.search(pattern, answer, flags=re.IGNORECASE | re.DOTALL) is None
    ]
    return not missing, missing


def evaluate_tool_calls(
    calls: list[dict[str, Any]],
    expectations: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]]]:
    """Проверяет вызовы инструментов по имени и regex аргументов.

    Args:
        calls: Фактические структурированные вызовы callback handler.
        expectations: Ожидания вида ``tool``, ``patterns`` и необязательного ``min_calls``.

    Returns:
        Пара ``(успех, невыполненные ожидания)``.
    """

    failures: list[dict[str, Any]] = []
    for expectation in expectations:
        tool_name = str(expectation["tool"])
        patterns = list(expectation.get("patterns") or [])
        min_calls = int(expectation.get("min_calls", 1))
        matched = 0
        for call in calls:
            if call.get("name") != tool_name or call.get("error"):
                continue
            arguments = json.dumps(call.get("arguments"), ensure_ascii=False, default=str)
            if all(
                re.search(pattern, arguments, flags=re.IGNORECASE | re.DOTALL)
                for pattern in patterns
            ):
                matched += 1
        if matched < min_calls:
            failures.append({**expectation, "matched_calls": matched})
    return not failures, failures


def calculate_metrics(results: list[dict[str, Any]]) -> dict[str, float | int]:
    """Рассчитывает две итоговые метрики по всем кейсам корзины.

    Args:
        results: Оцененные результаты тестовых кейсов.

    Returns:
        Количество кейсов и проценты tool correctness и правильных ответов.
    """

    total = len(results)
    tool_correct = sum(bool(result["tool_correct"]) for result in results)
    answer_correct = sum(bool(result["answer_correct"]) for result in results)
    return {
        "total_cases": total,
        "tool_correct_cases": tool_correct,
        "answer_correct_cases": answer_correct,
        "tool_correctness_percent": round(100 * tool_correct / total, 2) if total else 0.0,
        "answer_correctness_percent": round(100 * answer_correct / total, 2) if total else 0.0,
    }


def print_progress_bar(completed: int, total: int, *, width: int = 30) -> None:
    """Выводит однострочный progress bar выполнения тестовой корзины.

    Args:
        completed: Количество завершенных кейсов.
        total: Общее количество кейсов.
        width: Ширина полосы прогресса в символах.

    Returns:
        ``None``. Прогресс записывается в stderr, не смешиваясь с метриками stdout.
    """

    ratio = completed / total if total else 1.0
    filled = min(width, round(width * ratio))
    bar = "#" * filled + "-" * (width - filled)
    ending = "\n" if completed >= total else "\r"
    print(
        f"[{bar}] {completed}/{total} ({ratio * 100:6.2f}%)",
        end=ending,
        file=sys.stderr,
        flush=True,
    )


def _run_worker(case_id: str, result_path: Path) -> int:
    """Находит выбранный кейс и запускает внутренний worker.

    Args:
        case_id: Идентификатор кейса из переменной окружения.
        result_path: Путь к временному JSON-результату.

    Returns:
        Код завершения worker.
    """

    basket = load_basket(DEFAULT_BASKET_PATH)
    case = next(
        (item for item in basket["cases"] if str(item["id"]) == case_id),
        None,
    )
    if case is None:
        raise ValueError(f"Кейс {case_id} не найден.")
    return run_case_worker(case, result_path)


def synchronize_queries() -> int:
    """Синхронизирует запросы из ``run.py`` с корзиной и Markdown-файлом.

    Returns:
        Количество синхронизированных запросов.
    """

    from deep_agent_test.sync_test_queries import (
        load_run_queries,
        update_basket_queries,
        update_markdown_queries,
    )

    queries = load_run_queries(DEFAULT_RUN_PATH)
    update_basket_queries(DEFAULT_BASKET_PATH, queries)
    update_markdown_queries(DEFAULT_MARKDOWN_PATH, queries)
    return len(queries)


def main() -> int:
    """Запускает корзину без параметров и печатает только две метрики.

    Returns:
        Код завершения процесса: ``0`` после обработки всех кейсов.
    """

    worker_case_id = os.environ.get(WORKER_CASE_ENV)
    worker_result_path = os.environ.get(WORKER_RESULT_ENV)
    if worker_case_id and worker_result_path:
        return _run_worker(worker_case_id, Path(worker_result_path))

    synchronize_queries()
    basket = load_basket(DEFAULT_BASKET_PATH)
    timeout_seconds = float(basket.get("timeout_seconds", 1000))
    cases = basket["cases"][:3]
    evaluated_results: list[dict[str, Any]] = []
    print_progress_bar(0, len(cases))

    for index, case in enumerate(cases, start=1):
        raw_result = run_case_with_timeout(
            case,
            timeout_seconds=timeout_seconds,
        )
        answer_correct, missing_answer_patterns = evaluate_answer(
            raw_result.get("answer", ""),
            case["answer_patterns"],
        )
        tool_correct, failed_tool_expectations = evaluate_tool_calls(
            raw_result.get("tool_calls", []),
            case["tool_expectations"],
        )
        evaluated = {
            "id": str(case["id"]),
            "status": raw_result["status"],
            "tool_correct": tool_correct and raw_result["status"] == "completed",
            "answer_correct": answer_correct and raw_result["status"] == "completed",
            "missing_answer_patterns": missing_answer_patterns,
            "failed_tool_expectations": failed_tool_expectations,
            **raw_result,
        }
        evaluated_results.append(evaluated)
        print_progress_bar(index, len(cases))

    metrics = calculate_metrics(evaluated_results)
    report = {"metrics": metrics, "results": evaluated_results}
    DEFAULT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Tool correctness: {metrics['tool_correctness_percent']:.2f}%")
    print(f"Correct answers: {metrics['answer_correctness_percent']:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
