"""Терминальный чат для проверки native DeepAgents аналитического агента."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool
from langchain_core.tools.structured import StructuredTool

from deep_agent_test.analytics_deep_agent import build_analytics_deep_agent
from deep_agent_test.settings import DeepAgentSettings, load_deep_agent_settings

EXIT_COMMANDS = {"exit", "quit", "q", "выход", "стоп"}
TEST_DATA_DIR = Path(__file__).resolve().parent / "data"
TOOL_ARGS_PREVIEW_CHARS = 2500
TOOL_RESULT_PREVIEW_CHARS = 3500
#DEFAULT_DEMO_QUERY = "Какой город по IP у сработки 3486d84b-4eba-4ba4-b044-94764fc9e7a4?"
DEFAULT_DEMO_QUERY = "найди все сработки связанные с образованием за январь 2026 года"


def build_chat_agent(settings: DeepAgentSettings | None = None, data_tools: list[BaseTool] | None = None) -> Any:
    from model import model as openrouter_model

    return build_analytics_deep_agent(
        openrouter_model,
        settings=settings,
        data_tools=data_tools,
    )


def build_test_data_tools(data_dir: Path = TEST_DATA_DIR) -> list[BaseTool]:
    from examples.fake_spark_tools import build_fake_spark_tools

    raw_tool = build_fake_spark_tools(delay_seconds=0.0, data_dir=data_dir)[0]

    def read_table_sync(**kwargs: Any) -> Any:
        return _format_read_table_output(asyncio.run(raw_tool.ainvoke(kwargs)))

    async def read_table_async(**kwargs: Any) -> Any:
        return _format_read_table_output(await raw_tool.ainvoke(kwargs))

    return [
        StructuredTool.from_function(
            func=read_table_sync,
            coroutine=read_table_async,
            name=raw_tool.name,
            description=raw_tool.description,
            args_schema=raw_tool.args_schema,
        )
    ]


def _format_read_table_output(value: Any) -> Any:
    if not hasattr(value, "to_dict") or not hasattr(value, "columns"):
        return value

    rows = [
        {column: _format_read_table_cell(column, item) for column, item in row.items()}
        for row in value.to_dict(orient="records")
    ]
    payload = {
        "status": "success",
        "table_name": value.attrs.get("spark_table_name"),
        "source_file": value.attrs.get("spark_source_file"),
        "total_rows": value.attrs.get("spark_total_rows"),
        "matched_rows": value.attrs.get("spark_matched_rows", len(rows)),
        "returned_rows": len(rows),
        "columns": list(value.columns),
        "rows": rows,
    }
    schema = value.attrs.get("spark_schema")
    if schema is not None:
        payload["schema"] = schema
    return json.dumps(payload, ensure_ascii=False, default=str)


def _format_read_table_cell(column: str, value: Any) -> Any:
    if value is None or value != value:
        return None
    normalized_column = column.lower()
    if (
        normalized_column.endswith("_id")
        or normalized_column in {"event_id", "epk_id", "user_id", "event_dt", "event_time", "operation_id"}
        or "transaction_id" in normalized_column
    ):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def make_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def run_chat(settings: DeepAgentSettings | None = None, data_tools: list[BaseTool] | None = None) -> None:
    settings = settings or load_deep_agent_settings()
    agent = build_chat_agent(settings=settings, data_tools=data_tools)
    config = make_config(settings.thread_id)
    loaded_skills_printed = False
    message_cursor = _initial_message_cursor(agent, config)

    print("Native Analytics DeepAgent. Команды выхода: exit, quit, q.")
    while True:
        user_message = input("Вы: ").strip()
        if user_message.lower() in EXIT_COMMANDS:
            return
        if not user_message:
            continue

        print("Агент: обрабатываю запрос...", flush=True)
        try:
            result = invoke_user_message(agent, config, user_message)
        except Exception as error:
            print()
            print(f"Ошибка выполнения агента: {error}")
            print()
            continue

        state = resolve_agent_state(agent, config, result)
        loaded_skills_printed = print_loaded_skills_once(state, already_printed=loaded_skills_printed)
        message_cursor = print_messages(state, start_index=message_cursor)


def invoke_user_message(agent: Any, config: dict[str, Any], message: str) -> Any:
    return agent.invoke({"messages": [{"role": "user", "content": message}]}, config=config)


def stream_user_message(agent: Any, config: dict[str, Any], message: str) -> Any:
    """Запускает agent.stream(stream_mode='updates') и печатает шаги по мере выполнения."""

    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
        stream_mode="updates",
    ):
        if not isinstance(chunk, dict):
            continue
        for node_name, update in chunk.items():
            print_stream_update(node_name, update)

    snapshot = agent.get_state(config)
    values = getattr(snapshot, "values", None)
    return resolve_agent_state(agent, config, values if isinstance(values, dict) else snapshot)


def run_stream_query(
    user_message: str,
    settings: DeepAgentSettings | None = None,
    data_tools: list[BaseTool] | None = None,
) -> Any:
    """Один запрос в stream-режиме: видны node-обновления, tool calls и ответы."""

    settings = settings or load_deep_agent_settings()
    agent = build_chat_agent(settings=settings, data_tools=data_tools)
    config = make_config(settings.thread_id)

    print(f"Запрос: {user_message}", flush=True)
    print("Агент: stream...", flush=True)
    state = stream_user_message(agent, config, user_message)
    print_loaded_skills_once(state, already_printed=False)
    return state


def print_stream_update(node_name: str, update: Any) -> None:
    """Печатает одно stream-обновление LangGraph (имя node + новые messages/todos/skills)."""

    print(f"\n[stream] {node_name}", flush=True)
    if update is None or not isinstance(update, dict):
        return

    skill_paths = update.get("preloaded_skill_paths")
    if isinstance(skill_paths, list) and skill_paths:
        print("  skills:", ", ".join(map(str, skill_paths)), flush=True)

    todos = update.get("todos")
    if isinstance(todos, list) and todos:
        print("  todos:", flush=True)
        print(_indent_text(format_todos_for_user(todos), prefix="    "), flush=True)

    messages = update.get("messages")
    if isinstance(messages, list) and messages:
        print_messages({"messages": messages}, start_index=0)


def print_loaded_skills_once(result: Any, *, already_printed: bool) -> bool:
    if already_printed or not isinstance(result, dict):
        return already_printed

    skill_paths = result.get("preloaded_skill_paths") or []
    if not skill_paths:
        return already_printed

    print()
    print("Агент:")
    print("Загруженные skills:")
    for index, skill_path in enumerate(skill_paths, start=1):
        print(f"{index}. {skill_path}")
    print()
    return True


def print_messages(state: Any, *, start_index: int = 0) -> int:
    """Печатает новые сообщения из state начиная с ``start_index``."""

    if not isinstance(state, dict):
        return start_index

    messages = state.get("messages") or []
    if not isinstance(messages, list) or start_index >= len(messages):
        return len(messages)

    printed = False
    for message in messages[start_index:]:
        if isinstance(message, HumanMessage):
            continue

        if isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", None) or []
            for tool_call in tool_calls:
                if not printed:
                    print()
                printed = True
                print(format_tool_call(str(tool_call.get("name") or "tool"), tool_call.get("args")))

            text = message_to_text(message).strip()
            if text:
                if not printed:
                    print()
                printed = True
                print("Агент:")
                print(text)
            continue

        if type(message).__name__ == "ToolMessage":
            if not printed:
                print()
            printed = True
            status = str(getattr(message, "status", "") or "success")
            print(
                format_tool_result(
                    str(getattr(message, "name", "") or "tool"),
                    message_to_text(message),
                    status=status,
                )
            )

    if printed:
        print()
    return len(messages)


def resolve_agent_state(agent: Any, config: dict[str, Any], result: Any) -> Any:
    get_state = getattr(agent, "get_state", None)
    if get_state is None:
        return result

    try:
        snapshot = get_state(config)
    except Exception:
        return result

    values = getattr(snapshot, "values", None)
    if isinstance(values, dict):
        return values
    if isinstance(snapshot, dict):
        snapshot_values = snapshot.get("values")
        if isinstance(snapshot_values, dict):
            return snapshot_values
    return result


def last_agent_response_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""

    messages = result.get("messages") or []
    if not messages:
        return ""
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        if getattr(message, "tool_calls", None):
            continue
        text = message_to_text(message).strip()
        if text:
            return text
    return ""


def format_todos_for_user(todos: list[dict[str, Any]]) -> str:
    if not todos:
        return "План не указан."

    status_labels = {
        "pending": "ожидает",
        "in_progress": "в работе",
        "completed": "готово",
    }
    lines = []
    for index, todo in enumerate(todos, start=1):
        content = str(todo.get("content") or "").strip() or "Без описания"
        status = status_labels.get(str(todo.get("status") or ""), str(todo.get("status") or ""))
        suffix = f" [{status}]" if status else ""
        lines.append(f"{index}. {content}{suffix}")
    return "\n".join(lines)


def message_to_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, list):
        return "\n".join(str(block) for block in content)
    if content is not None:
        return str(content)
    return str(message)


def iter_tool_calls(messages: Iterable[Any]) -> Iterable[tuple[str, Any]]:
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in getattr(message, "tool_calls", None) or []:
            yield str(tool_call.get("name") or ""), tool_call.get("args")


def _message_count(state: Any) -> int:
    if not isinstance(state, dict):
        return 0
    messages = state.get("messages")
    return len(messages) if isinstance(messages, list) else 0


def _initial_message_cursor(agent: Any, config: dict[str, Any]) -> int:
    get_state = getattr(agent, "get_state", None)
    if get_state is None:
        return 0
    try:
        snapshot = get_state(config)
    except Exception:
        return 0
    values = getattr(snapshot, "values", None)
    if isinstance(values, dict):
        return _message_count(values)
    return 0


def format_tool_call(tool_name: str, args: Any) -> str:
    lines = [f"[Tool call] {tool_name}"]
    if tool_name == "write_todos" and isinstance(args, dict):
        lines.append("План:")
        lines.append(format_todos_for_user(args.get("todos", [])))
        return "\n".join(lines)

    if tool_name == "task" and isinstance(args, dict):
        description = str(args.get("description") or args.get("task") or "").strip()
        subagent = str(args.get("subagent_type") or args.get("name") or "").strip()
        if subagent:
            lines.append(f"Subagent: {subagent}")
        if description:
            lines.append("Задание:")
            lines.append(_indent_text(description, prefix="  "))
        return "\n".join(lines)

    lines.append("Аргументы:")
    lines.append(_indent_text(_format_json_preview(args), prefix="  "))
    return "\n".join(lines)


def format_tool_result(tool_name: str, content: str, *, status: str = "success") -> str:
    lines = [f"[Tool result] {tool_name} [{status}]"]
    lines.append(_summarize_tool_result(tool_name, content))
    return "\n".join(lines)


def _summarize_tool_result(tool_name: str, content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return "  (пустой результат)"

    parsed = _try_parse_json(text)
    if parsed is None:
        return _indent_text(_truncate_text(text, TOOL_RESULT_PREVIEW_CHARS), prefix="  ")

    if tool_name == "read_table" or _looks_like_read_table_payload(parsed):
        return _indent_text(_format_read_table_result_summary(parsed), prefix="  ")

    if tool_name == "execute_python_code" or (
        isinstance(parsed, dict) and "success" in parsed and "generated_code" in parsed
    ):
        return _indent_text(_format_execute_python_result_summary(parsed), prefix="  ")

    if tool_name == "write_todos" and isinstance(parsed, dict):
        return _indent_text(format_todos_for_user(parsed.get("todos", [])), prefix="  ")

    if isinstance(parsed, dict) and parsed.get("format") == "pkl":
        return _indent_text(
            "\n".join(
                [
                    f"Сохранен pickle: {parsed.get('saved_file', parsed.get('file_path', ''))}",
                    f"Строк: {parsed.get('rows', '?')}",
                ]
            ),
            prefix="  ",
        )

    if "saved_file" in parsed or "pickle" in text.lower():
        return _indent_text(_format_spill_file_summary(parsed, text), prefix="  ")

    return _indent_text(_format_json_preview(parsed), prefix="  ")


def _format_read_table_result_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return _truncate_text(str(payload), TOOL_RESULT_PREVIEW_CHARS)

    lines = [
        f"status: {payload.get('status', 'unknown')}",
        f"table_name: {payload.get('table_name', '')}",
        f"returned_rows: {payload.get('returned_rows', payload.get('matched_rows', payload.get('rows_count', '?')))}",
    ]
    columns = payload.get("columns")
    if isinstance(columns, list) and columns:
        lines.append(f"columns: {', '.join(map(str, columns[:20]))}")

    rows = payload.get("rows")
    if isinstance(rows, list) and rows:
        preview = rows[:3]
        lines.append("preview:")
        lines.append(_indent_text(_format_json_preview(preview), prefix="    "))

    if payload.get("schema"):
        lines.append("schema: присутствует")

    missing = payload.get("missing_columns") or payload.get("unknown_columns")
    if missing:
        lines.append(f"missing_columns: {missing}")

    limitations = payload.get("limitations")
    if limitations:
        lines.append(f"limitations: {limitations}")

    return "\n".join(lines)


def _format_execute_python_result_summary(payload: dict[str, Any]) -> str:
    lines = [
        f"success: {payload.get('success')}",
        f"message: {payload.get('message', '')}",
    ]
    if payload.get("target_variable"):
        lines.append(f"target_variable: {payload.get('target_variable')}")
    if payload.get("error"):
        lines.append(f"error: {payload.get('error')}")
    if payload.get("traceback"):
        lines.append("traceback:")
        lines.append(_indent_text(_truncate_text(str(payload.get("traceback")), 1500), prefix="    "))
    if payload.get("execution_output"):
        lines.append("execution_output:")
        lines.append(
            _indent_text(_truncate_text(str(payload.get("execution_output")), 1200), prefix="    ")
        )
    if payload.get("variable_preview"):
        lines.append("variable_preview:")
        lines.append(
            _indent_text(_truncate_text(str(payload.get("variable_preview")), 1200), prefix="    ")
        )
    if payload.get("possible_causes"):
        lines.append(f"possible_causes: {payload.get('possible_causes')}")
    return "\n".join(lines)


def _format_spill_file_summary(parsed: dict[str, Any], raw_text: str) -> str:
    lines: list[str] = []
    for key in ("saved_file", "file_path", "format", "rows"):
        if key in parsed:
            lines.append(f"{key}: {parsed.get(key)}")
    if not lines:
        for line in raw_text.splitlines():
            if "Файл:" in line or "Путь:" in line or "Preview" in line:
                lines.append(line.strip())
    return "\n".join(lines) or _truncate_text(raw_text, TOOL_RESULT_PREVIEW_CHARS)


def _looks_like_read_table_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and (
        "table_name" in payload or "returned_rows" in payload or "rows" in payload
    )


def _try_parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _format_json_preview(value: Any) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        rendered = repr(value)
    return _truncate_text(rendered, TOOL_ARGS_PREVIEW_CHARS)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...[truncated {len(text) - max_chars} chars]"


def _indent_text(text: str, *, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" if line else prefix.rstrip() for line in text.splitlines())


def main() -> int:
    settings = load_deep_agent_settings()
    test_data_tools = build_test_data_tools(TEST_DATA_DIR)
    agent = build_chat_agent(settings=settings, data_tools=test_data_tools)
    config = make_config(settings.thread_id)

    user_message = DEFAULT_DEMO_QUERY
    print(f"Запрос: {user_message}", flush=True)
    print("Агент: обрабатываю запрос...", flush=True)

    result = invoke_user_message(agent, config, user_message)
    state = resolve_agent_state(agent, config, result)
    print_loaded_skills_once(state, already_printed=False)
    print_messages(state, start_index=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
