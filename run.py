"""Минимальный запуск аналитического DeepAgent на локальных CSV.

Содержит:
- main: инициализация fake-инструмента чтения данных, trace-логгера, агента и один invoke.
- main_stream: запуск агента со стримингом человекочитаемых промежуточных шагов.
- _print_v3_progress: вывод typed-событий ``stream_events(version="v3")``.
- _print_tool_call_progress: вывод статуса одного tool call.
- _subagent_status: форматирование статуса subagent-а.
- _tool_call_status: форматирование статуса вызова инструмента.
- _compact_args_preview: компактное представление аргументов инструмента.
- _last_message_text: извлечение текста последнего ответа агента.
- _configure_openrouter_runtime: настройка OpenRouter для локального CLI-запуска.
"""

from __future__ import annotations

import json
import os
from typing import Any

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_TEMPERATURE = "0.2"
OPENROUTER_TIMEOUT_SECONDS = "120"
OPENROUTER_MAX_RETRIES = "0"

# .\.venv\Scripts\Activate.ps1
# $env:OPENAI_API_KEY = "<OPENROUTER_API_KEY>"
# python run.py


def _configure_openrouter_runtime() -> None:
    """Настраивает OpenRouter как OpenAI-compatible провайдер для запуска из этого файла.

    Args:
        Отсутствуют. Функция использует константы модуля и переменные окружения.

    Returns:
        ``None``. В окружение процесса добавляются только отсутствующие настройки модели.
    """

    os.environ.setdefault("DEEP_AGENT_MODEL_PROVIDER", "openai")
    os.environ.setdefault("OPENAI_BASE_URL", OPENROUTER_BASE_URL)
    os.environ.setdefault("DEEP_AGENT_MODEL", OPENROUTER_MODEL)
    os.environ.setdefault("DEEP_AGENT_TEMPERATURE", OPENROUTER_TEMPERATURE)
    os.environ.setdefault("DEEP_AGENT_TIMEOUT", OPENROUTER_TIMEOUT_SECONDS)
    os.environ.setdefault("DEEP_AGENT_MAX_RETRIES", OPENROUTER_MAX_RETRIES)


_configure_openrouter_runtime()

from deep_agent.agent import build_analytics_deep_agent
from deep_agent.settings import load_deep_agent_settings
from deep_agent.runtime.tracing import FileTraceCallbackHandler, build_trace_file_path
from tests.support.fake_spark_data import build_fake_spark_data_tools
from model import model

USER_MESSAGE_2 = (
    "Сколько сработок правила «DENY оплата обучения после смены устройства» было с 24 января "
    "по 6 февраля 2026 года включительно? "
)
USER_MESSAGE_1 = (
    "Сколько уникальных клиентов имели сработку правила «DENY нетипичная сумма оплаты курсов» "
    "с 24 января по 6 февраля 2026 года включительно? "
)
USER_MESSAGE = (
   "найди  в моих файлах где находится prompt запрос для coding agent"
)
USER_MESSAGE_4 = (
    "Какова общая сумма в рублях по сработкам клиента epk_id = 2099007770421995000001 "
    "с 24 января по 20 февраля 2026 года включительно?"
)
USER_MESSAGE_5 = (
    "Какова средняя сумма операции в рублях для сработок правила «CARD_DENY крупная покупка "
    "образовательных услуг после cash-in» с 24 января по 20 февраля 2026 года включительно? "
)
USER_MESSAGE_6 = (
    "Какова максимальная сумма операции в рублях среди сработок канала MOBILE с 24 января "
    "по 6 февраля 2026 года включительно? "
)
USER_MESSAGE_7 = (
    "Какой процент сработок имел has_claim = true с 24 января по 6 февраля 2026 года включительно? "
    "В знаменателе используй все сработки периода."
)
USER_MESSAGE_8 = (
    "Какой процент сработок с непустым признаком is_save имел is_save = true с 24 января "
    "по 20 февраля 2026 года включительно? Строки с пустым is_save исключи из знаменателя. "
)
USER_MESSAGE_9 = (
    "Какой канал событий был самым частым среди сработок с 24 января по 6 февраля 2026 года "
    "включительно? Верни канал и количество. При равенстве выбери канал, который раньше по алфавиту."
)
USER_MESSAGE_10 = (
    "Сколько уникальных непустых значений event_description было среди сработок с 24 января "
    "по 20 февраля 2026 года включительно? Какие они были? Сохрани в виде таблицы "
)
USER_MESSAGE_11 = (
    "Сколько сработок с описанием, относящимся к оплате образования, было с 24 января "
    "по 6 февраля 2026 года включительно? "
)
USER_MESSAGE_12 = (
    "Сколько разных значений rule_category содержится внутри JSON-поля main_rule у сработок "
    "с 24 января по 6 февраля 2026 года включительно? "
)
USER_MESSAGE_13 = (
    "Сколько raw-событий есть в cards у клиента epk_id = 2099007770421995000001 "
    "с 24 января по 6 февраля 2026 года включительно? "
)
USER_MESSAGE_14 = (
    "Сколько уникальных непустых atm_merchant_name встречается в cards с 24 января "
    "по 6 февраля 2026 года включительно? "
)
USER_MESSAGE_15 = (
    "Сколько уникальных непустых hardware_id было у клиента epk_id = 2099007770421993000001 "
    "в uko с 24 января по 6 февраля 2026 года включительно?"
)
USER_MESSAGE_16 = (
    "Для сработки event_id = ae107b8e-4788-4073-9bb4-4f209a6e02aa найди все транзакции клиента за день сработки, верни кол-во транзакций "
)
USER_MESSAGE_17 = (
    "Какие типы и подтипы событий были у клиента в день сработки "
    "event_id = 3486d84b-4eba-4ba4-b044-94764fc9e7a4? Покажи тип, подтип и количество."
)
USER_MESSAGE_18 = (
    "Сколько транзакций совершил клиент в день сработки "
    "event_id = ae107b8e-4788-4073-9bb4-4f209a6e02aa и на какую общую сумму?"
)
USER_MESSAGE_19 = (
    "Сколько транзакций совершил клиент в день сработки "
    "event_id = 3486d84b-4eba-4ba4-b044-94764fc9e7a4 и на какую общую сумму?"
)
USER_MESSAGE_20 = (
    "Какие типы и подтипы событий встречались у сработок, связанных с образовательными услугами, "
    "с 24 января по 6 февраля 2026 года включительно? Покажи тип, подтип и количество."
)
USER_MESSAGE_21 = (
    "Покажи топ-3 мерчанта по количеству карточных сработок, связанных "
    "с образовательными услугами, с 24 января по 6 февраля 2026 года включительно."
)
USER_MESSAGE_22 = (
    "Покажи топ-3 банка получателя по количеству  сработок, связанных с образовательными "
    "услугами, с 24 января по 6 февраля 2026 года включительно."
)
USER_MESSAGE_23 = (
    "Покажи взаимосвязь между правилом сработки и категорией мерчанта для  "
    "сработок с 24 января по 6 февраля 2026 года включительно. Формат: правило, категория, количество."
)
USER_MESSAGE_24 = (
    "Покажи взаимосвязь между правилом сработки и типом операции для сработок "
    "с 24 января по 6 февраля 2026 года включительно. Формат: правило, тип операции, количество."
)
USER_MESSAGE_25 = (
    "Какие типы и подтипы событий были у клиентов по сработкам с 24 января "
    "по 20 февраля 2026 года включительно? Покажи продукт, тип, подтип и количество."
)
USER_MESSAGE_26 = (
    "Покажи топ-5 банков получателя по количеству сработок, связанных с оплатой "
    "образовательных услуг, с 24 января по 20 февраля 2026 года включительно."
)
USER_MESSAGE_27 = (
    "Какие типы операций совершал клиент в день сработки "
    "event_id = ae107b8e-4788-4073-9bb4-4f209a6e02aa? Покажи количество по каждой комбинации."
)
USER_MESSAGE_28 = (
    "У какого торгового предприятия было больше всего карточных сработок, отмеченных как save, "
    "с 24 января по 20 февраля 2026 года включительно? Верни название и количество сработок."
)
USER_MESSAGE_29 = (
    "Сравни по каждому продукту количество транзакций, совершённых клиентами в дни сработок, "
    "за периоды с 24 января по 6 февраля и с 7 по 20 февраля 2026 года. Покажи количество за каждый "
    "период, изменение в штуках и процентах."
)
USER_MESSAGE_30 = (
    "Покажи по каждой поверхности количество транзакций, совершённых клиентами в дни сработок, "
    "и среднее количество транзакций на один клиентский день с 24 января по 20 февраля 2026 года "
    "включительно."
)

TOOL_STATUS_LABELS = {
    "write_todos": "Составляю план",
    "load_skills": "Читаю skills",
    "task": "Запускаю subagent",
    "load_data": "Читаю данные",
    "execute_python_code": "Анализирую данные",
}


def main() -> int:
    """Запускает один запрос к агенту.

    Args:
        Отсутствуют. Скрипт не принимает параметры командной строки.

    Returns:
        Код завершения процесса: ``0`` при успешном invoke.
    """

    settings = load_deep_agent_settings()
    data_tools = build_fake_spark_data_tools(query_parser_model=model)
    agent = build_analytics_deep_agent(model=model, settings=settings, data_tools=data_tools)
    trace_file_path = build_trace_file_path(settings.trace_log_dir)
    trace_handler = FileTraceCallbackHandler(trace_file_path)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": USER_MESSAGE}]},
        config={
            "callbacks": [trace_handler],
            "configurable": {"thread_id": settings.thread_id},
            "recursion_limit": settings.graph_recursion_limit,
        },
    )
    print(_last_message_text(result))
    print(f"Trace log: {trace_file_path}")
    return 0


def main_stream() -> int:
    """Запускает один запрос к агенту и печатает промежуточные шаги.

    Args:
        Отсутствуют. Скрипт не принимает параметры командной строки.

    Returns:
        Код завершения процесса: ``0`` при успешном stream-запуске.
    """

    settings = load_deep_agent_settings()
    data_tools = build_fake_spark_data_tools(query_parser_model=model)
    agent = build_analytics_deep_agent(model=model, settings=settings, data_tools=data_tools)
    trace_file_path = build_trace_file_path(settings.trace_log_dir)
    trace_handler = FileTraceCallbackHandler(trace_file_path)
    config = {
        "callbacks": [trace_handler],
        "configurable": {"thread_id": settings.thread_id},
        "recursion_limit": settings.graph_recursion_limit,
    }

    print("Запускаю агента...")
    final_result = None
    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": USER_MESSAGE}]},
        config=config,
        version="v3",
    )
    _print_v3_progress(stream)
    final_result = stream.output

    if final_result is not None:
        print("\nИтоговый ответ:")
        print(_last_message_text(final_result))
    print(f"Trace log: {trace_file_path}")
    return 0


def _print_v3_progress(stream: Any, *, prefix: str = "") -> None:
    """Печатает промежуточные шаги из typed stream-проекций v3.

    Args:
        stream: ``GraphRunStream`` или ``SubagentRunStream`` из ``stream_events(version="v3")``.
        prefix: Префикс для вложенных subagent-сообщений.

    Returns:
        ``None``. Функция печатает статусы по мере прихода событий.
    """

    for channel_name, item in stream.interleave("tool_calls", "subagents", "lifecycle"):
        if channel_name == "tool_calls":
            _print_tool_call_progress(item, prefix=prefix)
        elif channel_name == "subagents":
            status = _subagent_status(item)
            print(f"{prefix}{status}")
            _print_v3_progress(item, prefix=f"{prefix}[{item.name or 'subagent'}] ")
        elif channel_name == "lifecycle":
            if item.get("event") == "started" and item.get("graph_name"):
                print(f"{prefix}Запускаю graph: {item['graph_name']}")


def _print_tool_call_progress(tool_call: Any, *, prefix: str = "") -> None:
    """Печатает старт и завершение одного вызова инструмента.

    Args:
        tool_call: ``ToolCallStream`` из v3-проекции ``tool_calls``.
        prefix: Префикс для вложенных subagent-сообщений.

    Returns:
        ``None``. Функция печатает статусы и дожидается завершения tool call.
    """

    tool_name = str(getattr(tool_call, "tool_name", "") or "")
    if tool_name == "task":
        return
    print(f"{prefix}{_tool_call_status(tool_name, getattr(tool_call, 'input', None))}")
    for _ in tool_call.output_deltas:
        pass
    label = TOOL_STATUS_LABELS.get(tool_name, f"Инструмент {tool_name}")
    if getattr(tool_call, "error", None):
        print(f"{prefix}{label}: ошибка - {tool_call.error}")
    else:
        print(f"{prefix}{label}: завершено")


def _subagent_status(subagent: Any) -> str:
    """Формирует статус запуска subagent-а.

    Args:
        subagent: ``SubagentRunStream`` из v3-проекции ``subagents``.

    Returns:
        Текст статуса с именем subagent-а и кратким описанием задачи.
    """

    name = getattr(subagent, "name", None) or "subagent"
    task_input = _compact_args_preview(getattr(subagent, "task_input", None))
    return f"Запускаю subagent {name}: {task_input}" if task_input else f"Запускаю subagent {name}"


def _tool_call_status(tool_name: str, args: Any) -> str:
    """Формирует статус старта инструмента.

    Args:
        tool_name: Имя инструмента из события LangChain.
        args: Аргументы вызова инструмента.

    Returns:
        Строка статуса с компактным preview аргументов.
    """

    label = TOOL_STATUS_LABELS.get(tool_name, f"Вызываю инструмент {tool_name}")
    preview = _compact_args_preview(args)
    return f"{label}: {preview}" if preview else label


def _compact_args_preview(args: Any, *, max_chars: int = 300) -> str:
    """Возвращает короткое JSON-представление аргументов инструмента.

    Args:
        args: Любые аргументы tool call.
        max_chars: Максимальная длина строки preview.

    Returns:
        Компактная строка без переносов или пустая строка, если аргументов нет.
    """

    if args in (None, "", {}, []):
        return ""
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except TypeError:
        text = str(args)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


def _last_message_text(result: Any) -> str:
    """Достает текст последнего сообщения агента из результата invoke.

    Args:
        result: Словарь состояния, который вернул ``agent.invoke``.

    Returns:
        Текст последнего сообщения или строковое представление результата.
    """

    if not isinstance(result, dict):
        return str(result)
    messages = result.get("messages") or []
    if not messages:
        return str(result)
    last_message = messages[-1]
    text = getattr(last_message, "text", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(last_message, "content", None)
    if isinstance(content, str):
        return content
    return str(last_message)


if __name__ == "__main__":
    raise SystemExit(main_stream())
# создать план для выполнения взаимоисключабщими агентами, чьи результаты в дальнейшем будут синтезированы в один ответ
