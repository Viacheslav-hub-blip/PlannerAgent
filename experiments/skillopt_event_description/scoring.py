"""Метрики для одноразового эксперимента SkillOpt по поиску сработок.

Функции файла:
- load_jsonl: читает JSONL-корзину тестовых примеров.
- extract_trace_signals: извлекает из trace признаки выбора skill и вызова инструментов.
- score_case: считает hard/soft метрику для одного запуска агента.
- build_llm_judge_messages: готовит сообщения для LLM-as-a-judge без вызова модели.
- judge_answer_with_llm: выполняет LLM-as-a-judge через переданную модель.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TraceSignals:
    """Сигналы, извлеченные из trace одного запуска агента.

    Args:
        skill_was_selected: Был ли загружен целевой skill.
        called_data_retrieval_agent: Был ли вызван subagent ``data-retrieval-agent``.
        called_load_data: Был ли вызван инструмент ``load_data``.
        load_data_queries: Список текстов запросов, найденных в вызовах ``load_data``.
        called_tools: Список имен инструментов, найденных в trace.

    Returns:
        Объект с нормализованными признаками для расчета метрик.
    """

    skill_was_selected: bool
    called_data_retrieval_agent: bool
    called_load_data: bool
    load_data_queries: list[str]
    called_tools: list[str]


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Читает JSONL-файл с тестовой корзиной.

    Args:
        path: Путь к JSONL-файлу.

    Returns:
        Список словарей с тестовыми примерами.
    """

    items: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            items.append(json.loads(stripped))
    return items


def extract_trace_signals(trace_text: str, target_skill_id: str) -> TraceSignals:
    """Извлекает минимальные признаки из текстового trace DeepAgent.

    Args:
        trace_text: Полный текст trace-файла одного запуска.
        target_skill_id: Идентификатор skill, который должен быть выбран.

    Returns:
        Объект ``TraceSignals`` с признаками выбора skill и вызовов инструментов.
    """

    normalized = trace_text.lower()
    skill_markers = [
        target_skill_id.lower(),
        f"skill_id: {target_skill_id}".lower(),
        f"/skills/{target_skill_id}/skill.md".lower(),
    ]
    called_tools = re.findall(r"name:\s*([a-zA-Z0-9_\-]+)", trace_text)
    load_data_queries = _extract_load_data_queries(trace_text)
    return TraceSignals(
        skill_was_selected=any(marker in normalized for marker in skill_markers),
        called_data_retrieval_agent="data-retrieval-agent" in normalized,
        called_load_data=any(tool == "load_data" for tool in called_tools) or "name: load_data" in normalized,
        load_data_queries=load_data_queries,
        called_tools=called_tools,
    )


def score_case(case: dict[str, Any], answer: str, trace_text: str) -> dict[str, Any]:
    """Считает hard и soft метрику для одного тестового примера.

    Args:
        case: Тестовый пример из JSONL-корзины.
        answer: Финальный ответ агента.
        trace_text: Полный trace запуска агента.

    Returns:
        Словарь с ``hard``, ``soft``, деталями проверок и диагностикой для SkillOpt.
    """

    signals = extract_trace_signals(trace_text, str(case["target_skill_id"]))
    checks = {
        "skill_was_selected": signals.skill_was_selected,
        "called_data_retrieval_agent": signals.called_data_retrieval_agent,
        "called_load_data": signals.called_load_data,
        "period_is_correct": _period_is_correct(signals.load_data_queries, case["expected_result"]),
        "required_tool_queries_present": _required_tool_queries_present(signals.load_data_queries, case),
        "answer_has_expected_values": _answer_has_expected_values(answer, case),
        "answer_mentions_expected_descriptions": _answer_mentions_expected_descriptions(answer, case),
    }

    hard_keys = _hard_check_keys(case)
    if case.get("workflow_checks", {}).get("must_select_skill", True) and not checks["skill_was_selected"]:
        hard = 0
        soft = min(_weighted_soft(checks), 0.4)
        failure_type = "preview_failure"
    else:
        hard = int(all(checks[key] for key in hard_keys))
        soft = _weighted_soft(checks)
        failure_type = "passed" if hard else _failure_type(checks)

    return {
        "id": case["id"],
        "hard": hard,
        "soft": round(float(soft), 4),
        "failure_type": failure_type,
        "checks": checks,
        "called_tools": signals.called_tools,
        "load_data_queries": signals.load_data_queries,
    }


def build_llm_judge_messages(case: dict[str, Any], answer: str) -> list[dict[str, str]]:
    """Готовит prompt для простой LLM-as-a-judge проверки ответа.

    Args:
        case: Тестовый пример с эталонными значениями.
        answer: Финальный ответ агента.

    Returns:
        Список сообщений для chat-модели. Функция не вызывает модель и не использует API-ключи.
    """

    expected = json.dumps(case["expected_result"], ensure_ascii=False, indent=2)
    return [
        {
            "role": "system",
            "content": (
                "Ты проверяешь ответ аналитического агента. Верни только JSON с полями "
                "answer_is_correct, values_are_present, answer_is_grounded, explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Вопрос пользователя:\n{case['user_prompt']}\n\n"
                f"Эталонные значения:\n{expected}\n\n"
                f"Ответ агента:\n{answer}\n\n"
                "Проверь, содержит ли ответ нужные значения и не противоречит ли эталону."
            ),
        },
    ]


def judge_answer_with_llm(model: Any, case: dict[str, Any], answer: str) -> dict[str, Any]:
    """Запускает LLM-as-a-judge через явно переданную модель.

    Args:
        model: Chat-модель LangChain или совместимый объект с методом ``invoke``.
        case: Тестовый пример с эталонными значениями.
        answer: Финальный ответ агента.

    Returns:
        Словарь с результатом judge. Если модель вернула не JSON, сырой текст кладется в ``raw``.
    """

    messages = build_llm_judge_messages(case, answer)
    response = model.invoke(messages)
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "\n".join(str(item) for item in content)
    text = str(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _extract_load_data_queries(trace_text: str) -> list[str]:
    """Находит в trace текстовые запросы, переданные в ``load_data``.

    Args:
        trace_text: Полный trace запуска агента.

    Returns:
        Список найденных SQL-подобных запросов.
    """

    queries: list[str] = []
    blocks = re.split(r"\n={10,}|\n-+", trace_text)
    for block in blocks:
        if "name: load_data" not in block:
            continue
        match = re.search(r'"query"\s*:\s*"(?P<query>(?:\\.|[^"])*)"', block, flags=re.DOTALL)
        if match:
            queries.append(bytes(match.group("query"), "utf-8").decode("unicode_escape"))
            continue
        fallback = re.search(r"query:\s*(?P<query>LOAD .*?)(?:\n\n|$)", block, flags=re.DOTALL)
        if fallback:
            queries.append(fallback.group("query").strip())
    return queries


def _period_is_correct(queries: list[str], expected: dict[str, Any]) -> bool:
    """Проверяет наличие правильного периода хотя бы в одном запросе.

    Args:
        queries: Список запросов ``load_data``.
        expected: Эталонный блок ``expected_result``.

    Returns:
        ``True``, если найден правильный ``PERIOD event_dt``.
    """

    needle = f"PERIOD event_dt FROM '{expected['period_from']}' TO '{expected['period_to']}'"
    return any(needle in query for query in queries)


def _required_tool_queries_present(queries: list[str], case: dict[str, Any]) -> bool:
    """Проверяет обязательные фрагменты запросов из ``required_tools``.

    Args:
        queries: Список запросов ``load_data``.
        case: Тестовый пример.

    Returns:
        ``True``, если каждый обязательный набор фрагментов найден хотя бы в одном запросе.
    """

    required = [tool for tool in case.get("required_tools", []) if tool.get("name") == "load_data"]
    for tool in required:
        fragments = tool.get("query_must_contain", [])
        if not any(all(fragment in query for fragment in fragments) for query in queries):
            return False
    return True


def _answer_has_expected_values(answer: str, case: dict[str, Any]) -> bool:
    """Проверяет наличие ключевых числовых значений в ответе.

    Args:
        answer: Финальный ответ агента.
        case: Тестовый пример.

    Returns:
        ``True``, если ответ содержит ожидаемое количество и, при наличии, сумму.
    """

    expected = case["expected_result"]
    normalized = _digits_only(answer)
    count_ok = str(expected["events_count"]) in normalized
    amount = expected.get("amount_rub")
    if amount is None or not case.get("answer_requires_amount", False):
        return count_ok
    amount_int = str(int(round(float(amount))))
    amount_compact = str(amount).replace(".", "").replace(",", "")
    return count_ok and (amount_int in normalized or amount_compact in normalized)


def _answer_mentions_expected_descriptions(answer: str, case: dict[str, Any]) -> bool:
    """Проверяет, что ответ упоминает ожидаемые точные описания событий.

    Args:
        answer: Финальный ответ агента.
        case: Тестовый пример.

    Returns:
        ``True``, если в ответе есть хотя бы одно ожидаемое описание, либо список описаний пуст.
    """

    descriptions = case["expected_result"].get("matching_event_descriptions", [])
    if not descriptions:
        return True
    lowered = answer.lower()
    return any(description.lower() in lowered for description in descriptions)


def _weighted_soft(checks: dict[str, bool]) -> float:
    """Считает простую взвешенную soft-метрику.

    Args:
        checks: Словарь булевых проверок.

    Returns:
        Число от ``0.0`` до ``1.0``.
    """

    weights = {
        "skill_was_selected": 0.25,
        "called_data_retrieval_agent": 0.20,
        "called_load_data": 0.15,
        "period_is_correct": 0.15,
        "required_tool_queries_present": 0.15,
        "answer_has_expected_values": 0.07,
        "answer_mentions_expected_descriptions": 0.03,
    }
    return sum(weight for key, weight in weights.items() if checks.get(key))


def _hard_check_keys(case: dict[str, Any]) -> list[str]:
    """Возвращает список проверок, обязательных для ``hard = 1``.

    Args:
        case: Тестовый пример.

    Returns:
        Список ключей из словаря ``checks``.
    """

    keys = [
        "skill_was_selected",
        "called_data_retrieval_agent",
        "called_load_data",
        "period_is_correct",
        "required_tool_queries_present",
        "answer_has_expected_values",
    ]
    if case.get("test_type") == "skill_content":
        keys.append("answer_mentions_expected_descriptions")
    return keys


def _failure_type(checks: dict[str, bool]) -> str:
    """Определяет главный тип ошибки для передачи в SkillOpt extras.

    Args:
        checks: Словарь булевых проверок.

    Returns:
        Короткая строка с типом ошибки.
    """

    if all(checks.values()):
        return "passed"
    if not checks["skill_was_selected"]:
        return "preview_failure"
    if not checks["called_data_retrieval_agent"] or not checks["called_load_data"]:
        return "workflow_failure"
    if not checks["period_is_correct"] or not checks["required_tool_queries_present"]:
        return "query_failure"
    return "answer_failure"


def _digits_only(value: str) -> str:
    """Оставляет в строке только цифры.

    Args:
        value: Исходная строка.

    Returns:
        Строка из цифр без пробелов и разделителей.
    """

    return re.sub(r"\D+", "", value)
