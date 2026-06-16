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
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from deepagents.middleware.memory import MemoryMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from deep_agent.agent import (
    _agents_memory_path,
    _build_file_edit_interrupts,
    _build_native_runtime_middleware,
    build_conversation_checkpointer,
    build_skills_backend,
    build_supervisor_backend,
)
from deep_agent.capabilities import (
    BASE_SUPERVISOR_TOOL_NAMES,
    CODE_WORKSPACE_SKILL_PATH,
    CODE_WORKSPACE_TOOL_NAMES,
    DATA_RETRIEVAL_TOOL_NAMES,
    GENERAL_PURPOSE_BASE_TOOL_NAMES,
    IMAGE_ANALYSIS_SKILL_PATH,
    IMAGE_ANALYSIS_TOOL_NAMES,
    MCP_TOOLS_SKILL_PATH,
    SUPERVISOR_SKILL_TOOL_GRANTS,
)
from deep_agent.runtime.harness import build_analytics_harness_profile
from deep_agent.prompts.coding import CODING_AGENT_PROMPT
from deep_agent.prompts.data_retrieval import DATA_RETRIEVAL_PROMPT
from deep_agent.prompts.skills import (
    DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
)
from deep_agent.prompts.supervisor import SYSTEM_PROMPT
from deep_agent.prompts.tool_contracts import (
    TASK_TOOL_DESCRIPTION,
    TOOL_DESCRIPTION_OVERRIDES,
)
from deep_agent.settings import load_deep_agent_settings, workspace_tool_path
from deep_agent.runtime.filesystem import Utf8FilesystemBackend, Utf8LocalShellBackend
from deep_agent.middleware.tool_output_file import ToolOutputFileMiddleware
from deep_agent.subagents.coding import (
    CODING_AGENT_DESCRIPTION,
    build_coding_subagent_spec,
)
from deep_agent.subagents.data_retrieval import (
    DATA_RETRIEVAL_AGENT_DESCRIPTION,
    build_data_retrieval_subagent_spec,
)
from deep_agent.subagents.registry import build_subagent_specs
from deep_agent.middleware.skills_context import (
    SelectedSkillPaths,
    build_preloaded_skills_context,
    discover_skill_context_files,
    select_relevant_skill_paths_with_llm,
)
from deep_agent.middleware.tool_loop_guard import (
    _count_trailing_identical_tool_calls,
)
from deep_agent.middleware.tool_visibility import (
    ToolVisibilityMiddleware,
    filter_system_message_by_tools,
    filter_tools_by_name,
    resolve_allowed_tools,
)
from deep_agent.middleware.tool_context_notice import (
    ToolContextNoticeMiddleware,
    build_tool_context_notice,
)
from deep_agent.data.query_schema import FilterCondition, ParsedDataQuery
from deep_agent.tools.skill_loader import LOAD_SKILLS_DESCRIPTION
from deep_agent.data.query_parser import _parsed_query_to_read_args


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
                skills_workspace_dir="/deep_agent/skills/",
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
                        paths=["/deep_agent/skills/missing/SKILL.md"],
                        selection_reason="Ошибочный путь.",
                    ),
                    SelectedSkillPaths(
                        paths=["/deep_agent/skills/hit-table/SKILL.md"],
                        selection_reason="Нужна карточка hits.",
                    ),
                ]
            )

            outcome = select_relevant_skill_paths_with_llm(
                model=FakeSelectorModel(structured_model),
                user_query="Покажи сработки.",
                skill_files=skill_files,
                skills_root=skills_root,
                skills_workspace_dir="/deep_agent/skills/",
            )

        self.assertEqual(outcome.selection_status, "success")
        self.assertEqual(
            outcome.selected_paths,
            ["/deep_agent/skills/hit-table/SKILL.md"],
        )
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
                skills_workspace_dir="/deep_agent/skills/",
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

    def test_harness_profile_keeps_default_general_purpose_subagent(self) -> None:
        """HarnessProfile должен сохранять execute и штатный general-purpose."""

        profile = build_analytics_harness_profile()

        self.assertNotIn("execute", profile.excluded_tools)
        self.assertIsNotNone(profile.general_purpose_subagent)
        self.assertTrue(profile.general_purpose_subagent.enabled)

    def test_harness_profile_can_disable_nested_general_purpose_subagent(self) -> None:
        """Compiled subagents не должны получать вложенный general-purpose."""

        profile = build_analytics_harness_profile(enable_general_purpose=False)

        self.assertIsNotNone(profile.general_purpose_subagent)
        self.assertFalse(profile.general_purpose_subagent.enabled)

    def test_subagent_specs_include_coding_and_data_agents(self) -> None:
        """Сборка должна явно добавлять coding-agent и data-retrieval-agent."""

        coding_agent = object()
        data_retrieval_agent = object()
        specs = build_subagent_specs(
            coding_agent=coding_agent,
            data_retrieval_agent=data_retrieval_agent,
        )

        self.assertEqual(
            [spec["name"] for spec in specs],
            ["coding-agent", "data-retrieval-agent"],
        )
        self.assertIs(specs[0]["runnable"], coding_agent)
        self.assertIs(specs[1]["runnable"], data_retrieval_agent)
        self.assertEqual(specs[0]["description"], CODING_AGENT_DESCRIPTION)
        self.assertEqual(
            specs[1]["description"],
            DATA_RETRIEVAL_AGENT_DESCRIPTION,
        )

    def test_subagent_builders_return_create_deep_agent_kwargs(self) -> None:
        """Builder-ы должны возвращать независимые kwargs без registry-описания."""

        model = object()
        tool = object()
        middleware = object()
        skill_source = "/deep_agent/skills/"

        coding_spec = build_coding_subagent_spec(
            model=model,
            tools=[tool],
            common_middleware=[middleware],
            skill_sources=[skill_source],
        )
        data_spec = build_data_retrieval_subagent_spec(
            model=model,
            data_tools=[tool],
            common_middleware=[middleware],
            skill_sources=[skill_source],
        )

        self.assertNotIn("description", coding_spec)
        self.assertNotIn("description", data_spec)
        signature(create_deep_agent).bind_partial(**coding_spec)
        signature(create_deep_agent).bind_partial(**data_spec)
        self.assertIs(coding_spec["model"], model)
        self.assertIs(data_spec["model"], model)
        self.assertEqual(coding_spec["tools"], [tool])
        self.assertEqual(data_spec["tools"], [tool])
        self.assertEqual(coding_spec["middleware"], [middleware])
        self.assertEqual(data_spec["middleware"], [middleware])
        self.assertEqual(coding_spec["skills"], [skill_source])
        self.assertEqual(data_spec["skills"], [skill_source])

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

    def test_image_and_mcp_skills_grant_external_tools(self) -> None:
        """Skills image-analysis и mcp-tools должны открывать внешние tools."""

        grants = {
            **SUPERVISOR_SKILL_TOOL_GRANTS,
            MCP_TOOLS_SKILL_PATH: frozenset({"search_presentations"}),
        }

        without_skill = resolve_allowed_tools(
            base_allowed_tools=BASE_SUPERVISOR_TOOL_NAMES,
            skill_tool_grants=grants,
            state={},
        )
        with_image_skill = resolve_allowed_tools(
            base_allowed_tools=BASE_SUPERVISOR_TOOL_NAMES,
            skill_tool_grants=grants,
            state={"preloaded_skill_paths": [IMAGE_ANALYSIS_SKILL_PATH]},
        )
        with_mcp_skill = resolve_allowed_tools(
            base_allowed_tools=BASE_SUPERVISOR_TOOL_NAMES,
            skill_tool_grants=grants,
            state={"materialized_skill_paths": [MCP_TOOLS_SKILL_PATH]},
        )

        self.assertTrue(IMAGE_ANALYSIS_TOOL_NAMES.isdisjoint(without_skill))
        self.assertNotIn("search_presentations", without_skill)
        self.assertTrue(IMAGE_ANALYSIS_TOOL_NAMES.issubset(with_image_skill))
        self.assertIn("search_presentations", with_mcp_skill)

    def test_workspace_backend_uses_local_shell_and_sanitized_environment(self) -> None:
        """Backend должен выполнять команды из workspace без API-ключей в env."""

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "AGENTS.md").write_text("# Test memory\n", encoding="utf-8")
            settings = replace(
                load_deep_agent_settings(),
                workspace_root=workspace,
                skills_root=workspace / "deep_agent" / "skills",
                tool_outputs_dir=workspace / "tool_outputs",
            )

            backend = build_skills_backend(settings)

        self.assertIsInstance(backend.default, Utf8LocalShellBackend)
        self.assertEqual(backend.default.cwd, workspace.resolve())
        self.assertNotIn("OPENAI_API_KEY", backend.default._env)

    def test_backends_use_one_workspace_namespace_and_access_all_directories(self) -> None:
        """Проверяет единый корень и доступ к произвольным папкам workspace.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            arbitrary_file = workspace / "nested" / "folder" / "value.txt"
            arbitrary_file.parent.mkdir(parents=True)
            arbitrary_file.write_text("value", encoding="utf-8")
            skills_root = workspace / "deep_agent" / "skills"
            skills_root.mkdir(parents=True)
            settings = replace(
                load_deep_agent_settings(),
                workspace_root=workspace,
                skills_root=skills_root,
                tool_outputs_dir=workspace / "runs",
            )

            coding_backend = build_skills_backend(settings)
            supervisor_backend = build_supervisor_backend(settings)

            self.assertIsInstance(coding_backend.default, Utf8LocalShellBackend)
            self.assertIsInstance(supervisor_backend.default, Utf8FilesystemBackend)
            self.assertEqual(coding_backend.routes, {})
            self.assertEqual(supervisor_backend.routes, {})
            self.assertEqual(
                workspace_tool_path(skills_root, workspace, directory=True),
                "/deep_agent/skills/",
            )
            self.assertEqual(
                supervisor_backend.read("/nested/folder/value.txt").file_data[
                    "content"
                ],
                "value",
            )

            write_result = supervisor_backend.write(
                "/deep_agent/skills/generated/SKILL.md",
                "# Generated\n",
            )

            self.assertIsNone(write_result.error)
            self.assertEqual(
                (skills_root / "generated" / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "# Generated\n",
            )

    def test_runtime_uses_native_langchain_limits_and_retries(self) -> None:
        """Проверяет встроенные retry и execution limits LangChain.

        Returns:
            ``None``.
        """

        settings = load_deep_agent_settings()
        middleware = _build_native_runtime_middleware(
            settings,
            ToolOutputFileMiddleware(
                output_dir=settings.tool_outputs_dir,
                workspace_root=settings.workspace_root,
            ),
            limit_model_calls=True,
        )

        self.assertTrue(any(isinstance(item, ModelRetryMiddleware) for item in middleware))
        self.assertTrue(any(isinstance(item, ToolCallLimitMiddleware) for item in middleware))
        self.assertTrue(any(isinstance(item, ModelCallLimitMiddleware) for item in middleware))
        self.assertTrue(any(isinstance(item, ToolContextNoticeMiddleware) for item in middleware))

    def test_file_edit_approval_does_not_interrupt_terminal(self) -> None:
        """HITL должен применяться только к write_file и edit_file."""

        settings = replace(load_deep_agent_settings(), enable_interrupts=True)
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

    def test_native_memory_middleware_loads_agents_file_into_prompt(self) -> None:
        """Нативный MemoryMiddleware должен читать AGENTS.md и добавлять его в system prompt."""

        settings = load_deep_agent_settings()
        backend = build_skills_backend(settings)
        memory_path = _agents_memory_path(settings.agents_file_name)
        memory = MemoryMiddleware(backend=backend, sources=[memory_path])

        update = memory.before_agent({}, None, {})
        request = SimpleNamespace(
            state=dict(update or {}),
            system_message=SystemMessage(content="BASE"),
            model=None,
            override=lambda **kwargs: SimpleNamespace(**kwargs),
        )

        modified = memory.modify_request(request)
        prompt_text = "\n".join(
            str(block.get("text") or "")
            for block in modified.system_message.content_blocks
            if isinstance(block, dict)
        )

        self.assertIn("<agent_memory>", prompt_text)
        self.assertIn("/AGENTS.md", prompt_text)
        self.assertIn("# AGENTS.md", prompt_text)
        self.assertIn("task(data-retrieval-agent)", prompt_text)

    def test_filesystem_tool_descriptions_define_correct_arguments_and_paging(self) -> None:
        """Описания filesystem tools должны предотвращать ошибочные аргументы и неполное чтение."""

        read_file_description = TOOL_DESCRIPTION_OVERRIDES["read_file"]
        grep_description = TOOL_DESCRIPTION_OVERRIDES["grep"]

        self.assertIn("путь через `file_path`, не через `path`", read_file_description)
        self.assertIn("продолжай со следующим `offset`", read_file_description)
        self.assertIn("через `pattern`, не через `query`", grep_description)
        self.assertIn("`path` должен быть директорией", grep_description)
        self.assertIn('"glob": "settings.yaml"', grep_description)
        self.assertIn('"pattern": "build_client"', grep_description)
        self.assertIn(
            "aliases `/skills`, `/tool_outputs` и `/project_memory` не используются",
            TOOL_DESCRIPTION_OVERRIDES["execute"],
        )
        self.assertIn(
            "например `deep_agent/skills/...`",
            TOOL_DESCRIPTION_OVERRIDES["execute"],
        )

    def test_load_skills_description_rejects_auxiliary_files(self) -> None:
        """Описание load_skills должно запрещать загрузку fields.md как skill."""

        self.assertIn("loads only `SKILL.md` files", LOAD_SKILLS_DESCRIPTION)
        self.assertIn(
            "Do not pass paths like `/deep_agent/skills/name/fields.md`",
            LOAD_SKILLS_DESCRIPTION,
        )

    def test_tool_rules_are_kept_in_descriptions_not_system_prompts(self) -> None:
        """Правила tools должны находиться в descriptions, а не в system prompts."""

        self.assertIn("генерации тестов", TASK_TOOL_DESCRIPTION)
        self.assertIn("для coding-задачи", TASK_TOOL_DESCRIPTION)
        self.assertIn("пустой отчёт", TASK_TOOL_DESCRIPTION)
        self.assertNotIn("load_data", SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE)
        self.assertNotIn("load_skills", SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE)
        self.assertNotIn("read_file", DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE)
        self.assertNotIn("load_skills", DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE)
        self.assertNotIn("инструмент", SYSTEM_PROMPT.lower())
        self.assertIn("Do not repeat the same delegation", SYSTEM_PROMPT)
        self.assertIn("report without factual evidence", SYSTEM_PROMPT)
        self.assertIn("Create a plan before executing every non-trivial task", SYSTEM_PROMPT)
        self.assertIn("Use delegation as the default execution strategy", SYSTEM_PROMPT)
        self.assertIn(
            "may call a non-delegation tool directly only for a very small atomic action",
            SYSTEM_PROMPT,
        )
        self.assertIn("Never expose private chain-of-thought", SYSTEM_PROMPT)
        self.assertIn("delegate it to `coding-agent`", SYSTEM_PROMPT)
        self.assertIn(
            "When creating or updating a skill under `/deep_agent/skills`",
            CODING_AGENT_PROMPT,
        )
        self.assertIn(
            "maps directly to `workspace_root/deep_agent/skills/...`",
            CODING_AGENT_PROMPT,
        )
        self.assertIn("для чтения и проверки табличных данных", TASK_TOOL_DESCRIPTION)
        self.assertIn("более чем двух последовательных чтений", TASK_TOOL_DESCRIPTION)
        self.assertIn("не повторяй один и тот же tool call", TASK_TOOL_DESCRIPTION)
        self.assertIn("material parameters", DATA_RETRIEVAL_PROMPT)
        self.assertIn("observed results", DATA_RETRIEVAL_PROMPT)
        self.assertIn("material parameters", CODING_AGENT_PROMPT)
        self.assertIn("observed result", CODING_AGENT_PROMPT)

    def test_tool_context_notice_text_is_human_readable(self) -> None:
        """Tool notice должен явно сообщать о переданном контексте."""

        self.assertIn("Файл прочитан", build_tool_context_notice("read_file"))
        self.assertIn("визуальный контекст", build_tool_context_notice("analyze_image"))

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
