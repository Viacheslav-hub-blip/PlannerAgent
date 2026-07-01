"""Middleware для устойчивой работы GigaChat в DeepAgent runtime.

Содержит:
- _think: tool для глубоких промежуточных размышлений.
- ThinkToolMiddleware: добавление tool ``think`` в доступный runtime.
- ShellSafetyMiddleware: блокировка небезопасных форм ``execute`` до запуска shell.
- LoopBreakerMiddleware: обнаружение повторяющихся ошибочных tool-циклов и подсказка сменить стратегию.
- _messages_from_state: извлечение сообщений из state middleware.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import Field


@tool("think")
def _think(
    thought: str = Field(
        ...,
        description=(
            "Глубокие промежуточные размышления. Используй для продумывания правок, "
            "синхронизации типов, разбора гипотез и выбора минимального изменения."
        ),
    ),
) -> str:
    """Возвращает глубокое промежуточное размышление без побочных эффектов.

    Args:
        thought: Текст, который помогает агенту продумать правки, типы, гипотезы и следующий шаг.

    Returns:
        Та же строка ``thought``. Tool предназначен только для внутренней структуризации,
        а не для чтения данных, записи файлов или финального ответа.
    """

    return thought


class ThinkToolMiddleware(AgentMiddleware):
    """Добавляет tool ``think`` во все сборки агента.

    Returns:
        Middleware с одним дополнительным tool без доступа к файловой системе, shell,
        данным или внешним API.
    """

    tools = [_think]


class ShellSafetyMiddleware(AgentMiddleware):
    """Блокирует частые небезопасные формы shell-команд до выполнения ``execute``.

    Middleware не запускает команду самостоятельно. Если команда безопасна, управление
    передается следующему обработчику tool call; если нет, модель получает ``ToolMessage``
    с причиной блокировки и должна сменить форму команды.
    """

    name = "ShellSafetyMiddleware"

    @staticmethod
    def _unsafe_execute_reason(command: str) -> str | None:
        """Определяет причину блокировки shell-команды.

        Args:
            command: Команда, переданная в tool ``execute``.

        Returns:
            Текст причины блокировки или ``None``, если команда не попала под известные
            небезопасные паттерны.
        """

        if not command:
            return None
        if "\n" in command and "<<" not in command and any(x in command for x in ('"', "`", "$(")):
            return (
                "multi-line content is embedded in a shell string. Use a filesystem "
                "tool, a script file, or a single-quoted heredoc instead."
            )
        if re.search(r"\bpython3?\s+-c\s+(['\"]).*;\s*(for|if|while|def|class|with)\b", command, re.S):
            return (
                "python -c one-liner contains a statement after ';'. Write a script "
                "file or use a heredoc instead."
            )
        return None

    def wrap_tool_call(self, request: Any, handler: Any) -> ToolMessage:
        """Синхронно блокирует небезопасный ``execute`` или передает вызов дальше.

        Args:
            request: Запрос tool call от runtime.
            handler: Следующий обработчик tool call.

        Returns:
            Результат следующего обработчика или ``ToolMessage`` с ошибкой безопасности.
        """

        tool_call = getattr(request, "tool_call", {}) or {}
        tool_name = tool_call.get("name") or getattr(getattr(request, "tool", None), "name", "")
        if tool_name != "execute":
            return handler(request)
        args = tool_call.get("args", {}) or {}
        command = args.get("command", "")
        reason = self._unsafe_execute_reason(command if isinstance(command, str) else str(command))
        if not reason:
            return handler(request)
        return ToolMessage(
            content=(
                "[SHELL-SAFETY] blocked unsafe execute command: "
                f"{reason} Do not retry the same command shape."
            ),
            tool_call_id=tool_call.get("id", ""),
            name="execute",
            status="error",
        )

    async def awrap_tool_call(self, request: Any, handler: Any) -> ToolMessage:
        """Асинхронно блокирует небезопасный ``execute`` или передает вызов дальше.

        Args:
            request: Запрос tool call от runtime.
            handler: Следующий асинхронный обработчик tool call.

        Returns:
            Результат следующего обработчика или ``ToolMessage`` с ошибкой безопасности.
        """

        tool_call = getattr(request, "tool_call", {}) or {}
        tool_name = tool_call.get("name") or getattr(getattr(request, "tool", None), "name", "")
        if tool_name != "execute":
            return await handler(request)
        args = tool_call.get("args", {}) or {}
        command = args.get("command", "")
        reason = self._unsafe_execute_reason(command if isinstance(command, str) else str(command))
        if not reason:
            return await handler(request)
        return ToolMessage(
            content=(
                "[SHELL-SAFETY] blocked unsafe execute command: "
                f"{reason} Do not retry the same command shape."
            ),
            tool_call_id=tool_call.get("id", ""),
            name="execute",
            status="error",
        )


class LoopBreakerMiddleware(AgentMiddleware):
    """Добавляет подсказку сменить стратегию при повторяющихся ошибочных tool calls.

    Middleware анализирует хвост истории сообщений перед новым model call. Если видит
    повторяющиеся неуспешные вызовы, оно добавляет ``HumanMessage`` с конкретной
    коррекцией вместо mid-conversation ``SystemMessage``, который GigaChat может не
    принять.
    """

    name = "LoopBreakerMiddleware"

    def _last_n_tool_pairs(
        self,
        messages: list[Any],
        n: int,
    ) -> list[tuple[str, str, str]] | None:
        """Возвращает последние ``n`` пар tool call/result из хвоста истории.

        Args:
            messages: История сообщений агента.
            n: Требуемое число последовательных пар.

        Returns:
            Список кортежей ``(tool_name, args_json, result_text)`` или ``None``,
            если хвост истории не состоит из нужного числа пар.
        """

        pairs: list[tuple[str, str, str]] = []
        index = len(messages) - 1
        while index >= 0 and len(pairs) < n:
            message = messages[index]
            if isinstance(message, ToolMessage):
                if index == 0:
                    return None
                ai_message = messages[index - 1]
                if not isinstance(ai_message, AIMessage):
                    return None
                tool_calls = getattr(ai_message, "tool_calls", None) or []
                if not tool_calls:
                    return None
                tool_call = tool_calls[0]
                content = message.content if isinstance(message.content, str) else str(message.content)
                pairs.append(
                    (
                        tool_call.get("name", ""),
                        json.dumps(tool_call.get("args", {}), ensure_ascii=False, sort_keys=True),
                        content,
                    )
                )
                index -= 2
                continue
            if isinstance(message, AIMessage):
                index -= 1
                continue
            break
        return pairs if len(pairs) == n else None

    @staticmethod
    def _result_is_error(text: str) -> bool:
        """Проверяет, похож ли результат tool на ошибку.

        Args:
            text: Текст результата tool.

        Returns:
            ``True``, если результат содержит известные маркеры ошибки.
        """

        if not text:
            return False
        markers = (
            "Error:",
            "error:",
            "Cannot ",
            "cannot ",
            "Traceback",
            "[stderr]",
            "Exit code: 1",
            "Exit code: 2",
            "SyntaxError",
            "FileNotFoundError",
            "No such file",
            "String not found",
            "Read-only file system",
            "unrecognized arguments",
            "invalid choice",
            "unknown command",
            "command not found",
            "[SHELL-SAFETY]",
            "ValueError:",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _error_family(text: str) -> str | None:
        """Классифицирует повторяющуюся ошибку в укрупненное семейство.

        Args:
            text: Текст результата tool.

        Returns:
            Имя семейства ошибки или ``None``, если семейство не распознано.
        """

        lowered = text.lower()
        families = (
            ("invalid-cli-args", ("unrecognized arguments", "invalid choice", "unknown command")),
            ("shell-command-not-found", ("command not found",)),
            ("python-syntax", ("syntaxerror",)),
            ("missing-path", ("no such file", "read-only file system")),
            ("edit-miss", ("string not found",)),
            ("shell-safety", ("[shell-safety]",)),
            ("traceback", ("traceback",)),
            ("filesystem-contract", ("valueerror:", "filesystemverificationerror")),
        )
        for family, markers in families:
            if any(marker in lowered for marker in markers):
                return family
        return None

    @staticmethod
    def _count_tool_rounds(messages: list[Any]) -> int:
        """Считает число assistant-сообщений с tool calls.

        Args:
            messages: История сообщений агента.

        Returns:
            Количество раундов, где модель вызвала хотя бы один tool.
        """

        return sum(
            1
            for message in messages
            if isinstance(message, AIMessage) and (getattr(message, "tool_calls", None) or [])
        )

    @staticmethod
    def _grep_looks_empty(text: str) -> bool:
        """Проверяет, похож ли результат поиска на отсутствие совпадений.

        Args:
            text: Текст результата ``grep``.

        Returns:
            ``True``, если результат пустой или содержит маркеры отсутствия совпадений.
        """

        if not text or not text.strip():
            return True
        lowered = text.lower()
        return any(
            marker in lowered
            for marker in ("no matches", "0 matches", "not found", "no results", "0 results")
        )

    @staticmethod
    def _already_nudged(messages: list[Any], marker: str) -> bool:
        """Проверяет, была ли недавно добавлена подсказка с указанным маркером.

        Args:
            messages: История сообщений агента.
            marker: Маркер подсказки.

        Returns:
            ``True``, если маркер уже встречался после последнего assistant-шага.
        """

        for message in reversed(messages):
            content = getattr(message, "content", "") or ""
            if isinstance(content, str) and marker in content:
                return True
            if isinstance(message, AIMessage):
                break
        return False

    def _budget_nudge(self, tool_rounds: int) -> str:
        """Формирует подсказку при слишком большом числе tool calls.

        Args:
            tool_rounds: Текущее число tool-раундов.

        Returns:
            Текст подсказки для модели.
        """

        return (
            "[BUDGET-NUDGE] You have made "
            f"{tool_rounds} tool calls. Stop exploring and finish the current bounded step.\n"
            "- If a required output file is still missing, write it now.\n"
            "- If you already have enough evidence, produce the answer or subagent report.\n"
            "- Do not make more equivalent read/grep calls without a new concrete reason."
        )

    def _grep_empty_nudge(self) -> str:
        """Формирует подсказку при повторяющемся пустом ``grep``.

        Returns:
            Текст подсказки для модели.
        """

        return (
            "[LOOP-BREAKER] grep returned no useful matches twice. Do not grep again with the same idea.\n"
            "Change strategy: adjust `path`/`glob` from verified context, use `glob` for filenames, "
            "or write a small Python scan under `/artifacts/run.py` if the task needs counting across many files."
        )

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Добавляет корректирующую подсказку перед model call при признаках цикла.

        Args:
            state: State агента с историей сообщений.
            runtime: Runtime LangGraph. Аргумент не используется.

        Returns:
            ``{"messages": [HumanMessage(...)]}`` с подсказкой или ``None``.
        """

        messages = _messages_from_state(state)
        if not messages:
            return None

        tool_rounds = self._count_tool_rounds(messages)
        if tool_rounds >= 12 and not self._already_nudged(messages, "[BUDGET-NUDGE]"):
            return {"messages": [HumanMessage(content=self._budget_nudge(tool_rounds))]}

        grep_pairs = self._last_n_tool_pairs(messages, 2)
        if (
            grep_pairs
            and all(pair[0] == "grep" for pair in grep_pairs)
            and all(self._grep_looks_empty(pair[2]) for pair in grep_pairs)
            and not self._already_nudged(messages, "[LOOP-BREAKER]")
        ):
            return {"messages": [HumanMessage(content=self._grep_empty_nudge())]}

        pairs = self._last_n_tool_pairs(messages, 3)
        if not pairs:
            return None

        names = {pair[0] for pair in pairs}
        all_same_call = pairs[0] == pairs[1] == pairs[2]
        all_same_tool_errors = len(names) == 1 and all(self._result_is_error(pair[2]) for pair in pairs)
        families = [self._error_family(pair[2]) for pair in pairs]
        all_same_error_family = bool(families[0]) and families[0] == families[1] == families[2]
        if not (all_same_call or all_same_tool_errors or all_same_error_family):
            return None

        marker = "[LOOP-BREAKER]"
        if self._already_nudged(messages, marker):
            return None

        tool_name = pairs[0][0]
        last_result = pairs[0][2][:300]
        nudge = (
            f"{marker} You have called `{tool_name}` repeatedly and it keeps failing "
            f"(last error: {last_result!r}). Stop repeating this approach. Change strategy:\n"
            "- If `edit_file` says 'String not found', remove any display-only line-number prefix copied from "
            "`read_file`, include exact indentation, and use enough surrounding context.\n"
            "- If `python -c` gives SyntaxError, write a script such as `/artifacts/run.py` and run it with "
            "`execute(command=\"python /artifacts/run.py\")`.\n"
            "- If a filesystem path failed, use the canonical workspace namespace such as `/file.py`, "
            "`/deep_agent/module.py`, or `/artifacts/result.csv`; do not use Windows or host absolute paths.\n"
            "- If `grep`/`glob` returns nothing useful, change `path`/`glob` from verified context or use a Python "
            "scan for counting tasks.\n"
            "- If a CLI/runtime tool says 'invalid choice' or 'unrecognized arguments', stop inventing flags and use "
            "only the documented tool contract.\n"
            "- If shell safety blocked a command, use filesystem tools, a script file, or a single-quoted heredoc.\n"
            "Do something materially different on the next step."
        )
        return {"messages": [HumanMessage(content=nudge)]}


def _messages_from_state(state: Any) -> list[Any]:
    """Извлекает список сообщений из state middleware.

    Args:
        state: Mapping-like или object-like state агента.

    Returns:
        Список сообщений или пустой список, если сообщения недоступны.
    """

    if isinstance(state, dict):
        messages = state.get("messages")
    else:
        messages = getattr(state, "messages", None)
    return list(messages or [])


__all__ = [
    "LoopBreakerMiddleware",
    "ShellSafetyMiddleware",
    "ThinkToolMiddleware",
]
