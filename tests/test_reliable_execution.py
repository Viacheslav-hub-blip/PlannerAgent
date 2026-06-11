"""Тесты надёжного выполнения без вызовов внешней LLM.

Содержит:
- SequencedStructuredModel: детерминированные ответы structured selector.
- FakeSelectorModel: тестовая модель с ``with_structured_output``.
- ReliableExecutionTests: проверки skill routing, tool loop и harness profile.
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from deep_agent_test.core.analytics_deep_agent import (
    _agents_memory_path,
    _build_file_edit_interrupts,
    build_conversation_checkpointer,
    build_skills_backend,
)
from deep_agent_test.core.capabilities import (
    BASE_SUPERVISOR_TOOL_NAMES,
    CODE_WORKSPACE_SKILL_PATH,
    CODE_WORKSPACE_TOOL_NAMES,
    SUPERVISOR_SKILL_TOOL_GRANTS,
)
from deep_agent_test.core.harness_profile import build_analytics_harness_profile
from deep_agent_test.core.prompts import (
    BUILTIN_TOOLS_PROMPT_APPEND,
    DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    DATA_RETRIEVAL_PROMPT,
    DATA_RETRIEVAL_TOOLS_PROMPT_APPEND,
    SYSTEM_PROMPT,
    SUPERVISOR_TOOLS_PROMPT_APPEND,
    SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    TASK_TOOL_DESCRIPTION,
    TOOL_DESCRIPTION_OVERRIDES,
)
from deep_agent_test.core.settings import load_deep_agent_settings
from deep_agent_test.core.utf8_filesystem_backend import Utf8LocalShellBackend
from deep_agent_test.core.retrieval_subagents import build_analytics_subagent_specs
from deep_agent_test.middlewares.skills_context import (
    SelectedSkillPaths,
    build_preloaded_skills_context,
    discover_skill_context_files,
    select_relevant_skill_paths_with_llm,
)
from deep_agent_test.middlewares.tool_loop_guard import (
    _count_trailing_identical_tool_calls,
)
from deep_agent_test.middlewares.tool_visibility import (
    ToolVisibilityMiddleware,
    filter_system_message_by_tools,
    filter_tools_by_name,
    resolve_allowed_tools,
)
from deep_agent_test.tools.data_query_schema import FilterCondition, ParsedDataQuery
from deep_agent_test.tools.load_skills import LOAD_SKILLS_DESCRIPTION
from deep_agent_test.tools.spark_data import _parsed_query_to_read_args


class SequencedStructuredModel:
    """Возвращает заранее заданные ответы structured selector.

    Args:
        responses: Последовательность результатов или исключений.
    """

    def __init__(self, responses: list[Any]) -> None:
        """Сохраняет ответы и счётчик вызовов.

        Args:
            responses: Результаты, возвращаемые по порядку.

        Returns:
            ``None``.
        """

        self.responses = list(responses)
        self.calls = 0

    def invoke(self, messages: list[Any]) -> Any:
        """Возвращает следующий результат или выбрасывает исключение.

        Args:
            messages: Сообщения selector; содержимое не изменяется.

        Returns:
            Следующий тестовый structured result.

        Raises:
            Exception: Заранее заданное исключение текущего шага.
        """

        del messages
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSelectorModel:
    """Предоставляет тестовую реализацию ``with_structured_output``.

    Args:
        structured_model: Детерминированная structured-модель.
    """

    def __init__(self, structured_model: SequencedStructuredModel) -> None:
        """Сохраняет structured-модель.

        Args:
            structured_model: Объект, который обрабатывает ``invoke``.

        Returns:
            ``None``.
        """

        self.structured_model = structured_model

    def with_structured_output(
        self,
        schema: type[Any],
        **kwargs: Any,
    ) -> SequencedStructuredModel:
        """Возвращает тестовую structured-модель.

        Args:
            schema: Pydantic-схема ожидаемого результата.
            **kwargs: Настройки structured output, которые тестовая модель игнорирует.

        Returns:
            Детерминированная structured-модель.
        """

        self.schema = schema
        self.structured_output_kwargs = kwargs
        return self.structured_model


class ReliableExecutionTests(unittest.TestCase):
    """Проверяет локальные механические контракты этапа надёжности."""

    def test_empty_skill_selection_is_success_and_loads_nothing(self) -> None:
        """Пустой осознанный выбор не должен загружать все skills."""

        with tempfile.TemporaryDirectory() as temp_dir:
            skills_root = _create_test_skills(Path(temp_dir))
            structured_model = SequencedStructuredModel(
                [
                    SelectedSkillPaths(
                        paths=[],
                        selection_reason="Для общего вопроса domain skills не нужны.",
                    )
                ]
            )
            selector_model = FakeSelectorModel(structured_model)

            selection = build_preloaded_skills_context(
                skills_root=skills_root,
                skills_virtual_dir="/skills/",
                max_chars_per_file=1000,
                model=selector_model,
                user_query="Что такое медиана?",
            )

        self.assertEqual(selection.outcome.selection_status, "success")
        self.assertEqual(selection.paths, [])
        self.assertEqual(selection.context, "")
        self.assertEqual(structured_model.calls, 1)
        self.assertEqual(
            selector_model.structured_output_kwargs,
            {"method": "function_calling"},
        )

    def test_invalid_skill_path_gets_one_corrective_retry(self) -> None:
        """Выдуманный путь должен вызвать одну корректирующую попытку."""

        with tempfile.TemporaryDirectory() as temp_dir:
            skills_root = _create_test_skills(Path(temp_dir))
            skill_files = discover_skill_context_files(skills_root)
            structured_model = SequencedStructuredModel(
                [
                    SelectedSkillPaths(
                        paths=["/skills/missing/SKILL.md"],
                        selection_reason="Ошибочный путь.",
                    ),
                    SelectedSkillPaths(
                        paths=["/skills/hit-table/SKILL.md"],
                        selection_reason="Нужна карточка hits.",
                    ),
                ]
            )

            outcome = select_relevant_skill_paths_with_llm(
                model=FakeSelectorModel(structured_model),
                user_query="Покажи сработки.",
                skill_files=skill_files,
                skills_root=skills_root,
                skills_virtual_dir="/skills/",
            )

        self.assertEqual(outcome.selection_status, "success")
        self.assertEqual(outcome.selected_paths, ["/skills/hit-table/SKILL.md"])
        self.assertTrue(outcome.retry_performed)
        self.assertEqual(structured_model.calls, 2)
        self.assertIn("Неизвестные пути", outcome.validation_errors[0])

    def test_two_selector_failures_do_not_fallback_to_all_skills(self) -> None:
        """После двух ошибок selector должен вернуть пустой failed-результат."""

        with tempfile.TemporaryDirectory() as temp_dir:
            skills_root = _create_test_skills(Path(temp_dir))
            skill_files = discover_skill_context_files(skills_root)
            structured_model = SequencedStructuredModel(
                [ValueError("bad format"), ValueError("bad format again")]
            )

            outcome = select_relevant_skill_paths_with_llm(
                model=FakeSelectorModel(structured_model),
                user_query="Покажи сработки.",
                skill_files=skill_files,
                skills_root=skills_root,
                skills_virtual_dir="/skills/",
            )

        self.assertEqual(outcome.selection_status, "selection_failed")
        self.assertEqual(outcome.selected_paths, [])
        self.assertTrue(outcome.retry_performed)
        self.assertEqual(structured_model.calls, 2)

    def test_tool_loop_normalizes_args_and_allows_correction(self) -> None:
        """Одинаковые args должны считаться повтором, изменённые — новым вызовом."""

        first_call = {
            "id": "call-1",
            "name": "load_data",
            "args": {"query": "SELECT  *\nFROM hits"},
        }
        repeated_call = {
            "id": "call-2",
            "name": "load_data",
            "args": {"query": " SELECT * FROM   hits "},
        }
        corrected_call = {
            "id": "call-3",
            "name": "load_data",
            "args": {"query": "SELECT event_id FROM hits"},
        }
        state = {
            "messages": [
                HumanMessage(content="Покажи данные."),
                AIMessage(content="", tool_calls=[first_call]),
                AIMessage(content="", tool_calls=[repeated_call]),
                AIMessage(content="", tool_calls=[corrected_call]),
            ]
        }

        repeated_count = _count_trailing_identical_tool_calls(
            {"messages": state["messages"][:-1]},
            repeated_call,
        )
        corrected_count = _count_trailing_identical_tool_calls(state, corrected_call)

        self.assertEqual(repeated_count, 2)
        self.assertEqual(corrected_count, 1)

    def test_tool_visibility_uses_agent_specific_allowlist(self) -> None:
        """Supervisor allowlist должен удалять filesystem и generic execute."""

        tools = [
            {"name": "write_todos"},
            {"name": "task"},
            {"name": "execute"},
            {"name": "read_file"},
            {"name": "execute_python_code"},
            {"name": "load_skills"},
        ]
        allowed = frozenset(
            {"write_todos", "task", "execute_python_code", "load_skills"}
        )

        filtered = filter_tools_by_name(tools, allowed)

        self.assertEqual(
            [tool["name"] for tool in filtered],
            ["write_todos", "task", "execute_python_code", "load_skills"],
        )

    def test_tool_visibility_removes_unavailable_builtin_prompt_sections(self) -> None:
        """System prompt не должен описывать tools вне allowlist агента."""

        system_message = SystemMessage(
            content=[
                {"type": "text", "text": "Основная инструкция."},
                {
                    "type": "text",
                    "text": (
                        "## Filesystem Tools `ls`, `read_file`, `write_file`, "
                        "`edit_file`, `glob`, `grep`\n- grep: search"
                    ),
                },
                {"type": "text", "text": "## `task` (subagent spawner)\nTask docs"},
            ]
        )

        supervisor_message = filter_system_message_by_tools(
            system_message,
            frozenset({"task", "execute_python_code", "load_skills", "write_todos"}),
        )
        subagent_message = filter_system_message_by_tools(
            system_message,
            frozenset({"load_data", "read_file", "grep"}),
        )

        supervisor_text = "\n".join(
            str(block.get("text") or "") for block in supervisor_message.content_blocks
        )
        subagent_text = "\n".join(
            str(block.get("text") or "") for block in subagent_message.content_blocks
        )
        self.assertNotIn("Filesystem Tools", supervisor_text)
        self.assertIn("task", supervisor_text)
        self.assertIn("read_file", subagent_text)
        self.assertIn("grep", subagent_text)
        self.assertNotIn("subagent spawner", subagent_text)

    def test_tool_visibility_blocks_hidden_tool_execution(self) -> None:
        """Скрытый от модели tool не должен выполняться через tool node."""

        middleware = ToolVisibilityMiddleware(
            allowed_tools=frozenset({"task", "execute_python_code"})
        )
        request = SimpleNamespace(
            tool_call={
                "id": "call-hidden",
                "name": "grep",
                "args": {"pattern": "age_category"},
            }
        )

        result = middleware.wrap_tool_call(
            request,
            lambda _: self.fail("Hidden tool must not be executed."),
        )

        self.assertEqual(result.status, "error")
        self.assertIn("ToolUnavailableError", result.content)
        self.assertIn("task", result.content)

    def test_tool_visibility_executes_tool_after_skill_grant(self) -> None:
        """Загруженный code-workspace должен разрешать фактический tool call."""

        middleware = ToolVisibilityMiddleware(
            allowed_tools=BASE_SUPERVISOR_TOOL_NAMES,
            skill_tool_grants=SUPERVISOR_SKILL_TOOL_GRANTS,
        )
        request = SimpleNamespace(
            state={"materialized_skill_paths": [CODE_WORKSPACE_SKILL_PATH]},
            tool_call={
                "id": "call-edit",
                "name": "edit_file",
                "args": {"file_path": "/app.py"},
            },
        )

        result = middleware.wrap_tool_call(request, lambda _: "executed")

        self.assertEqual(result, "executed")

    def test_harness_profile_keeps_execute_for_explicit_coding_subagent(self) -> None:
        """HarnessProfile должен сохранять execute и отключать только auto subagent."""

        profile = build_analytics_harness_profile()

        self.assertNotIn("execute", profile.excluded_tools)
        self.assertIsNotNone(profile.general_purpose_subagent)
        self.assertFalse(profile.general_purpose_subagent.enabled)

    def test_subagent_specs_include_coding_and_data_agents(self) -> None:
        """Сборка должна явно добавлять general-purpose и data-retrieval-agent."""

        specs = build_analytics_subagent_specs(
            data_tools=[],
            data_retrieval_middleware=[],
            general_purpose_middleware=[],
            model=object(),
        )

        self.assertEqual(
            [spec["name"] for spec in specs],
            ["general-purpose", "data-retrieval-agent"],
        )

    def test_code_workspace_skill_grants_filesystem_and_terminal_tools(self) -> None:
        """Skill code-workspace должен динамически расширять allowlist supervisor."""

        without_skill = resolve_allowed_tools(
            base_allowed_tools=BASE_SUPERVISOR_TOOL_NAMES,
            skill_tool_grants=SUPERVISOR_SKILL_TOOL_GRANTS,
            state={},
        )
        with_skill = resolve_allowed_tools(
            base_allowed_tools=BASE_SUPERVISOR_TOOL_NAMES,
            skill_tool_grants=SUPERVISOR_SKILL_TOOL_GRANTS,
            state={"preloaded_skill_paths": [CODE_WORKSPACE_SKILL_PATH]},
        )
        materialized = resolve_allowed_tools(
            base_allowed_tools=BASE_SUPERVISOR_TOOL_NAMES,
            skill_tool_grants=SUPERVISOR_SKILL_TOOL_GRANTS,
            state={"materialized_skill_paths": [CODE_WORKSPACE_SKILL_PATH]},
        )

        self.assertTrue(CODE_WORKSPACE_TOOL_NAMES.isdisjoint(without_skill))
        self.assertTrue(CODE_WORKSPACE_TOOL_NAMES.issubset(with_skill))
        self.assertTrue(CODE_WORKSPACE_TOOL_NAMES.issubset(materialized))

    def test_workspace_backend_uses_local_shell_and_sanitized_environment(self) -> None:
        """Backend должен выполнять команды из workspace без API-ключей в env."""

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "AGENTS.md").write_text("# Test memory\n", encoding="utf-8")
            settings = replace(
                load_deep_agent_settings(),
                workspace_root=workspace,
                tool_outputs_dir=workspace / "tool_outputs",
            )

            backend = build_skills_backend(settings)

        self.assertIsInstance(backend.default, Utf8LocalShellBackend)
        self.assertEqual(backend.default.cwd, workspace.resolve())
        self.assertNotIn("OPENAI_API_KEY", backend.default._env)

    def test_file_edit_approval_does_not_interrupt_terminal(self) -> None:
        """HITL должен применяться только к write_file и edit_file."""

        settings = load_deep_agent_settings()
        interrupts = _build_file_edit_interrupts(settings)

        self.assertEqual(set(interrupts or {}), {"write_file", "edit_file"})
        self.assertNotIn("execute", interrupts or {})
        self.assertEqual(
            interrupts["edit_file"]["allowed_decisions"],
            ["approve", "edit", "reject"],
        )

    def test_enable_interrupts_false_disables_hitl(self) -> None:
        """Флаг enable_interrupts=false должен отключать interrupt_on."""

        settings = replace(load_deep_agent_settings(), enable_interrupts=False)
        self.assertIsNone(_build_file_edit_interrupts(settings))

    def test_agents_memory_and_conversation_checkpointer_use_native_runtime(self) -> None:
        """Project memory и краткосрочная память должны использовать DeepAgents/LangGraph."""

        self.assertEqual(_agents_memory_path("AGENTS.md"), "/AGENTS.md")
        self.assertEqual(
            _agents_memory_path("config\\AGENTS.md"),
            "/config/AGENTS.md",
        )
        with self.assertRaisesRegex(ValueError, "workspace"):
            _agents_memory_path("../AGENTS.md")
        self.assertIsInstance(build_conversation_checkpointer(), InMemorySaver)

    def test_filesystem_tool_descriptions_define_correct_arguments_and_paging(self) -> None:
        """Описания filesystem tools должны предотвращать ошибочные аргументы и неполное чтение."""

        read_file_description = TOOL_DESCRIPTION_OVERRIDES["read_file"]
        grep_description = TOOL_DESCRIPTION_OVERRIDES["grep"]

        self.assertIn("use `file_path`, never `path`", read_file_description)
        self.assertIn("continue with the next `offset`", read_file_description)
        self.assertIn("use `pattern`, never `query`", grep_description)
        self.assertIn("search directory, not a file path", grep_description)
        self.assertIn('"glob": "fields.md"', grep_description)
        self.assertIn('"pattern": "age_category"', grep_description)

    def test_load_skills_description_rejects_auxiliary_files(self) -> None:
        """Описание load_skills должно запрещать загрузку fields.md как skill."""

        self.assertIn("loads only `SKILL.md` files", LOAD_SKILLS_DESCRIPTION)
        self.assertIn("Do not pass paths like `/skills/name/fields.md`", LOAD_SKILLS_DESCRIPTION)

    def test_prompts_reject_empty_delegation_and_unsupported_results(self) -> None:
        """Supervisor и subagent не должны принимать пустой task за доказательство результата."""

        self.assertIn("Treat an empty `task` result as a failed delegation", BUILTIN_TOOLS_PROMPT_APPEND)
        self.assertIn("Never finish with an empty assistant message", BUILTIN_TOOLS_PROMPT_APPEND)
        self.assertIn("The supervisor always has", SUPERVISOR_TOOLS_PROMPT_APPEND)
        self.assertIn("code-workspace", SUPERVISOR_TOOLS_PROMPT_APPEND)
        self.assertNotIn("For `grep`", SUPERVISOR_TOOLS_PROMPT_APPEND)
        self.assertIn("The data-retrieval agent has only these tools", DATA_RETRIEVAL_TOOLS_PROMPT_APPEND)
        self.assertIn(
            "If table data is needed, delegate it to `data-retrieval-agent`",
            SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
        )
        self.assertNotIn(
            "Read auxiliary files",
            SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
        )
        self.assertIn(
            "Read auxiliary files",
            DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
        )
        self.assertIn("Treat an empty subagent report", SYSTEM_PROMPT)
        self.assertIn("The final assistant message must never be empty", SYSTEM_PROMPT)
        self.assertIn("delegate the table read/calculation", TASK_TOOL_DESCRIPTION)
        self.assertIn("an empty report", TASK_TOOL_DESCRIPTION)
        self.assertIn("Do not return an empty report", DATA_RETRIEVAL_PROMPT)
        self.assertIn("at least one successful data tool result", DATA_RETRIEVAL_PROMPT)

    def test_exact_event_id_lookup_does_not_require_period(self) -> None:
        """Точный event_id должен разрешать первичный lookup без event_dt."""

        parsed = ParsedDataQuery(
            status="ready",
            table_name="hits",
            select_columns=["event_id", "event_dt", "epk_id", "event_channel"],
            filters=[
                FilterCondition(
                    column="event_id",
                    operator="eq",
                    value="3486d84b-4eba-4ba4-b044-94764fc9e7a4",
                )
            ],
            max_rows=1,
        )

        result = _parsed_query_to_read_args(parsed)

        self.assertEqual(result["table_name"], "hits")
        self.assertEqual(result["filters"][0]["column"], "event_id")
        self.assertEqual(result["filters"][0]["operator"], "eq")

    def test_event_id_lookup_can_recover_from_parser_needs_more_input(self) -> None:
        """Ошибочный needs_more_input parser не должен блокировать exact event_id."""

        parsed = ParsedDataQuery(
            status="needs_more_input",
            table_name="hits",
            select_columns=["event_id", "event_dt", "epk_id"],
            filters=[
                FilterCondition(
                    column="event_id",
                    operator="eq",
                    value="3486d84b-4eba-4ba4-b044-94764fc9e7a4",
                )
            ],
            problem="Не указан период.",
            missing_inputs=["period"],
        )

        result = _parsed_query_to_read_args(parsed)

        self.assertEqual(result["select_columns"], ["event_id", "event_dt", "epk_id"])

    def test_non_event_id_lookup_still_requires_period(self) -> None:
        """Фильтр по клиенту без периода не должен обходить защиту широкого чтения."""

        parsed = ParsedDataQuery(
            status="ready",
            table_name="hits",
            select_columns=["event_id", "event_dt", "epk_id"],
            filters=[
                FilterCondition(
                    column="epk_id",
                    operator="eq",
                    value="2099007770421986000001",
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "временного интервала"):
            _parsed_query_to_read_args(parsed)


def _create_test_skills(root: Path) -> Path:
    """Создаёт минимальную тестовую папку skills.

    Args:
        root: Временная корневая директория.

    Returns:
        Путь к созданной папке skills.
    """

    skills_root = root / "skills"
    skill_dir = skills_root / "hit-table"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: hit-table\n"
        'description: "Карточка hits."\n'
        "---\n"
        "# Hits\n",
        encoding="utf-8",
    )
    return skills_root


if __name__ == "__main__":
    unittest.main()
