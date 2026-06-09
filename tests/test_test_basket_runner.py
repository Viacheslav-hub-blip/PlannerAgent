"""Тесты локальной логики раннера тестовой корзины.

Содержит тесты:
- test_evaluate_answer_accepts_extra_text: дополнительный текст не ломает regex-проверку.
- test_evaluate_tool_calls_checks_name_arguments_and_errors: проверяются имя, параметры и ошибки tool.
- test_evaluate_case_result_combines_checks: сырой результат объединяется с regex-проверками.
- test_calculate_metrics_counts_failed_cases_in_denominator: ошибки остаются в знаменателе метрик.
- test_load_run_queries_reads_concatenated_constants: AST читает склеенные строковые константы.
- test_build_process_group_options_matches_platform: параметры процесса соответствуют ОС.
- test_print_progress_bar_writes_to_stderr: progress bar не загрязняет stdout.
"""

from pathlib import Path

from deep_agent_test.run_test_basket import (
    build_process_group_options,
    calculate_metrics,
    evaluate_answer,
    evaluate_case_result,
    evaluate_tool_calls,
    print_progress_bar,
)
from deep_agent_test.sync_test_queries import load_run_queries


def test_evaluate_answer_accepts_extra_text() -> None:
    """Проверяет ответ с пояснениями вокруг ожидаемых значений.

    Returns:
        ``None``.
    """

    success, missing = evaluate_answer(
        "Расчет завершен. Итоговая сумма: 458 116,99 рубля.",
        [r"458[\s ]?116[,.]99"],
    )

    assert success is True
    assert missing == []


def test_evaluate_tool_calls_checks_name_arguments_and_errors() -> None:
    """Проверяет сопоставление tool name, regex аргументов и статуса вызова.

    Returns:
        ``None``.
    """

    calls = [
        {
            "name": "load_data",
            "arguments": {
                "query": "SELECT event_id FROM hits h PERIOD 20260124 TO 20260206"
            },
            "error": "",
        },
        {
            "name": "load_data",
            "arguments": {"query": "SELECT event_id FROM cards c"},
            "error": "ValueError: invalid query",
        },
    ]

    success, failures = evaluate_tool_calls(
        calls,
        [{"tool": "load_data", "patterns": ["hits", "20260124", "20260206"]}],
    )
    failed_success, failed_expectations = evaluate_tool_calls(
        calls,
        [{"tool": "load_data", "patterns": ["cards"]}],
    )

    assert success is True
    assert failures == []
    assert failed_success is False
    assert failed_expectations[0]["matched_calls"] == 0


def test_evaluate_case_result_combines_checks() -> None:
    """Проверяет объединение проверок ответа и инструментов.

    Returns:
        ``None``.
    """

    result = evaluate_case_result(
        {
            "id": "1",
            "answer_patterns": [r"(?<!\d)7(?!\d)"],
            "tool_expectations": [{"tool": "load_data", "patterns": ["hits"]}],
        },
        {
            "status": "completed",
            "answer": "Ответ: 7 сработок.",
            "tool_calls": [
                {
                    "name": "load_data",
                    "arguments": {"query": "SELECT event_id FROM hits"},
                    "error": "",
                }
            ],
        },
    )

    assert result["tool_correct"] is True
    assert result["answer_correct"] is True


def test_calculate_metrics_counts_failed_cases_in_denominator() -> None:
    """Проверяет, что ошибочные кейсы не исключаются из процентов.

    Returns:
        ``None``.
    """

    metrics = calculate_metrics(
        [
            {"tool_correct": True, "answer_correct": True},
            {"tool_correct": False, "answer_correct": True},
            {"tool_correct": False, "answer_correct": False},
            {"tool_correct": True, "answer_correct": False},
        ]
    )

    assert metrics["tool_correctness_percent"] == 50.0
    assert metrics["answer_correctness_percent"] == 50.0


def test_load_run_queries_reads_concatenated_constants(tmp_path: Path) -> None:
    """Проверяет чтение многострочной конкатенации строк без импорта ``run.py``.

    Args:
        tmp_path: Временная директория pytest.

    Returns:
        ``None``.
    """

    run_path = tmp_path / "run.py"
    run_path.write_text(
        'USER_MESSAGE_1 = ("Первая " "часть")\n'
        'USER_MESSAGE_2 = "Второй запрос"\n'
        "USER_MESSAGE = USER_MESSAGE_1\n",
        encoding="utf-8",
    )

    assert load_run_queries(run_path) == {
        "1": "Первая часть",
        "2": "Второй запрос",
    }


def test_build_process_group_options_matches_platform() -> None:
    """Проверяет выбор параметров группы процессов для текущей ОС.

    Returns:
        ``None``.
    """

    options = build_process_group_options()

    assert set(options) in ({"creationflags"}, {"start_new_session"})


def test_print_progress_bar_writes_to_stderr(capsys: object) -> None:
    """Проверяет вывод завершенного progress bar в stderr.

    Args:
        capsys: Pytest fixture для перехвата stdout и stderr.

    Returns:
        ``None``.
    """

    print_progress_bar(3, 3, width=10)
    captured = capsys.readouterr()

    assert captured.out == ""
    assert "[##########] 3/3 (100.00%)" in captured.err
