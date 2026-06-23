"""Тесты надёжного выполнения без вызовов внешней LLM.

Содержит:
- SequencedStructuredModel: детерминированные ответы structured selector.
- FakeSelectorModel: тестовая модель с ``with_structured_output``.
- ReliableExecutionTests: проверки skill routing, tool loop и harness profile.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages import ToolMessage
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from deepagents.middleware.memory import MemoryMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from deep_agent.agent import (
    _agents_memory_path,
    _build_native_runtime_middleware,
    _build_runtime_context_prompt,
    build_conversation_checkpointer,
    build_skills_backend,
    build_supervisor_backend,
    create_session_tool_outputs_dir,
)
from deep_agent.runtime.harness import build_analytics_harness_profile
from deep_agent.prompts.coding import CODING_AGENT_PROMPT
from deep_agent.prompts.data_retrieval import DATA_RETRIEVAL_PROMPT
from deep_agent.prompts.gigachat import GIGACHAT_AGENT_PRACTICES_PROMPT
from deep_agent.prompts.skills import (
    DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
)
from deep_agent.prompts.supervisor import SYSTEM_PROMPT
from deep_agent.prompts.tool_contracts import (
    TASK_TOOL_DESCRIPTION,
    TOOL_DESCRIPTION_OVERRIDES,
)
from deep_agent.tools.spark_data import READ_TABLE_DESCRIPTION
from deep_agent.settings import (
    DEFAULT_CONFIG_PATH,
    DeepAgentSettings,
    load_deep_agent_settings,
    workspace_tool_path,
)
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
from deep_agent.middleware.tool_context_notice import (
    ToolContextNoticeMiddleware,
    build_tool_context_notice,
)
from deep_agent.middleware.gigachat_runtime import (
    LoopBreakerMiddleware,
    ShellSafetyMiddleware,
    ThinkToolMiddleware,
)
from deep_agent.middleware.tool_descriptions import PromptToolDescriptionsMiddleware
from deep_agent.data.query_schema import FilterCondition, ParsedDataQuery
from deep_agent.tools.skill_loader import LOAD_SKILLS_DESCRIPTION, build_load_skills_tool
from deep_agent.tools.image_analysis import build_analyze_image_tool
from deep_agent.tools.project_structure import build_get_project_structure_tool
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
            workspace = Path(temp_dir)
            skills_root = _create_test_skills(workspace)
            skills_workspace_dir = workspace_tool_path(
                skills_root,
                workspace,
                directory=True,
            )
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
                skills_workspace_dir=skills_workspace_dir,
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
            workspace = Path(temp_dir)
            skills_root = _create_test_skills(workspace)
            skills_workspace_dir = workspace_tool_path(
                skills_root,
                workspace,
                directory=True,
            )
            hit_skill_path = f"{skills_workspace_dir}hit-table/SKILL.md"
            skill_files = discover_skill_context_files(skills_root)
            structured_model = SequencedStructuredModel(
                [
                    SelectedSkillPaths(
                        paths=[f"{skills_workspace_dir}missing/SKILL.md"],
                        selection_reason="Ошибочный путь.",
                    ),
                    SelectedSkillPaths(
                        paths=[hit_skill_path],
                        selection_reason="Нужна карточка hits.",
                    ),
                ]
            )

            outcome = select_relevant_skill_paths_with_llm(
                model=FakeSelectorModel(structured_model),
                user_query="Покажи сработки.",
                skill_files=skill_files,
                skills_root=skills_root,
                skills_workspace_dir=skills_workspace_dir,
            )

        self.assertEqual(outcome.selection_status, "success")
        self.assertEqual(
            outcome.selected_paths,
            [hit_skill_path],
        )
        self.assertTrue(outcome.retry_performed)
        self.assertEqual(structured_model.calls, 2)
        self.assertIn("Неизвестные пути", outcome.validation_errors[0])

    def test_two_selector_failures_do_not_fallback_to_all_skills(self) -> None:
        """После двух ошибок selector должен вернуть пустой failed-результат."""

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            skills_root = _create_test_skills(workspace)
            skill_files = discover_skill_context_files(skills_root)
            structured_model = SequencedStructuredModel(
                [ValueError("bad format"), ValueError("bad format again")]
            )

            outcome = select_relevant_skill_paths_with_llm(
                model=FakeSelectorModel(structured_model),
                user_query="Покажи сработки.",
                skill_files=skill_files,
                skills_root=skills_root,
                skills_workspace_dir=workspace_tool_path(
                    skills_root,
                    workspace,
                    directory=True,
                ),
            )

        self.assertEqual(outcome.selection_status, "selection_failed")
        self.assertEqual(outcome.selected_paths, [])
        self.assertTrue(outcome.retry_performed)
        self.assertEqual(structured_model.calls, 2)

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
        self.assertIn("refactor existing code", CODING_AGENT_DESCRIPTION)
        self.assertIn("edit or create source files", CODING_AGENT_DESCRIPTION)
        self.assertIn("convert files between supported formats", CODING_AGENT_DESCRIPTION)
        self.assertIn("run validation commands", CODING_AGENT_DESCRIPTION)
        self.assertIn("Do not use for table data retrieval", CODING_AGENT_DESCRIPTION)
        self.assertIn("Use only for bounded table data retrieval with load_data", DATA_RETRIEVAL_AGENT_DESCRIPTION)
        self.assertIn("fetch unique values of one column", DATA_RETRIEVAL_AGENT_DESCRIPTION)
        self.assertIn("retrieve rows matching exact identifiers", DATA_RETRIEVAL_AGENT_DESCRIPTION)
        self.assertIn("Provide a precise retrieval objective", DATA_RETRIEVAL_AGENT_DESCRIPTION)
        self.assertIn("Do not use for calculations", DATA_RETRIEVAL_AGENT_DESCRIPTION)
        self.assertIn("semantic classification decisions", DATA_RETRIEVAL_AGENT_DESCRIPTION)
        self.assertIn("Bad tasks: calculate totals or averages", DATA_RETRIEVAL_AGENT_DESCRIPTION)
        self.assertIn("delegate those follow-up tasks to coding-agent", DATA_RETRIEVAL_AGENT_DESCRIPTION)

    def test_subagent_builders_return_create_deep_agent_kwargs(self) -> None:
        """Builder-ы должны возвращать независимые kwargs без registry-описания."""

        model = object()
        tool = object()
        middleware = object()
        skill_source = "/home/user_123456/deep_agent/skills/"

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

    def test_agent_builder_gives_shell_backend_to_supervisor_only(self) -> None:
        """Проверяет wiring backend-ов без запуска внешней модели.

        Returns:
            ``None``. Тест фиксирует, что supervisor получает shell-capable backend,
            а data-agent остаётся на filesystem-only backend.
        """

        source = (Path(__file__).parents[1] / "deep_agent" / "agent.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("data_backend = build_supervisor_backend(", source)
        self.assertIn("supervisor_backend = build_skills_backend(", source)
        self.assertIn("backend=data_backend", source)
        self.assertIn("backend=supervisor_backend", source)

    def test_settings_derive_paths_from_workspace_root(self) -> None:
        """Проверяет, что path-настройки выводятся из ``workspace_root``.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            payload = {
                "harness_profile_key": "openai",
                "thread_id": "test-thread",
                "workspace_root": str(workspace),
                "terminal_timeout": 120,
                "terminal_max_output_bytes": 100000,
                "data_tools_factory": None,
                "data_tools_factory_kwargs": {},
                "tool_output_min_rows_to_save": 30,
                "tool_output_min_content_chars_to_save": 60000,
                "tool_output_preview_rows": 30,
                "tool_output_inline_original_chars": 10000,
                "context_edit_trigger_tokens": 100000,
                "context_edit_keep_tool_results": 3,
                "read_file_default_limit": 500,
                "max_model_retries": 5,
                "max_tool_calls_per_run": 40,
                "max_subagent_model_calls": 19,
                "graph_recursion_limit": 100,
            }

            settings = DeepAgentSettings.from_mapping(payload)

        self.assertEqual(settings.agents_file_name, "AGENTS.md")
        self.assertEqual(settings.skills_root, workspace / "deep_agent" / "skills")
        self.assertEqual(
            settings.tool_outputs_dir,
            workspace / "artifacts",
        )
        self.assertEqual(
            settings.trace_log_dir,
            workspace / "artifacts",
        )

    def test_settings_reject_external_tool_outputs_dir(self) -> None:
        """Проверяет, что tool outputs остаются внутри workspace.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            external_outputs = root / "runs" / "deep_agent_tool_outputs"
            workspace.mkdir()
            payload = {
                "harness_profile_key": "openai",
                "thread_id": "test-thread",
                "workspace_root": str(workspace),
                "terminal_timeout": 120,
                "terminal_max_output_bytes": 100000,
                "data_tools_factory": None,
                "data_tools_factory_kwargs": {},
                "tool_outputs_dir": str(external_outputs),
                "tool_output_min_rows_to_save": 30,
                "tool_output_min_content_chars_to_save": 60000,
                "tool_output_preview_rows": 30,
                "tool_output_inline_original_chars": 10000,
                "context_edit_trigger_tokens": 100000,
                "context_edit_keep_tool_results": 3,
                "read_file_default_limit": 500,
                "max_model_retries": 5,
                "max_tool_calls_per_run": 40,
                "max_subagent_model_calls": 19,
                "graph_recursion_limit": 100,
            }

            with self.assertRaisesRegex(ValueError, "workspace_root"):
                DeepAgentSettings.from_mapping(payload)

    def test_default_config_keeps_only_workspace_root_as_path_setting(self) -> None:
        """Проверяет, что базовый config не хранит производные path-настройки.

        Returns:
            ``None``.
        """

        payload = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))

        self.assertIn("workspace_root", payload)
        self.assertNotIn("agents_file_name", payload)
        self.assertNotIn("skills_root", payload)
        self.assertNotIn("tool_outputs_dir", payload)
        self.assertNotIn("trace_log_dir", payload)

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
                workspace_tool_path(
                    workspace / "deep_agent" / "skills",
                    workspace,
                    directory=True,
                ),
            )
            arbitrary_workspace_path = workspace_tool_path(arbitrary_file, workspace)
            self.assertEqual(
                supervisor_backend.read(arbitrary_workspace_path).file_data[
                    "content"
                ],
                "value",
            )

            generated_skill_path = workspace_tool_path(
                skills_root / "generated" / "SKILL.md",
                workspace,
            )
            write_result = supervisor_backend.write(
                generated_skill_path,
                "# Generated\n",
            )

            self.assertIsNone(write_result.error)
            self.assertEqual(
                (skills_root / "generated" / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "# Generated\n",
            )

    def test_load_skills_uses_runtime_workspace_paths(self) -> None:
        """Проверяет, что load_skills использует фактический workspace текущего запуска.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as runtime_dir:
            source_workspace = Path(source_dir)
            runtime_workspace = Path(runtime_dir)
            runtime_skills = runtime_workspace / "runtime_skills"
            skill_dir = runtime_skills / "custom-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: custom-skill\n"
                'description: "Runtime skill."\n'
                "---\n"
                "# Runtime Skill\n",
                encoding="utf-8",
            )
            settings = replace(
                load_deep_agent_settings(),
                workspace_root=source_workspace,
                skills_root=source_workspace / "missing_skills",
                tool_outputs_dir=source_workspace / "outputs",
            )

            tool = build_load_skills_tool(
                settings,
                skills_root=runtime_skills,
                workspace_root=runtime_workspace,
            )
            skill_workspace_path = workspace_tool_path(
                skill_dir / "SKILL.md",
                runtime_workspace,
            )
            result = tool.invoke(
                {
                    "type": "tool_call",
                    "name": "load_skills",
                    "id": "call-load-skills",
                    "args": {"skill_names": skill_workspace_path},
                }
            )
            message = result.update["messages"][0]

        self.assertIn(skill_workspace_path, message.content)
        self.assertIn("# Runtime Skill", message.content)

    def test_get_project_structure_tool_returns_agent_tree_without_skill_contents(self) -> None:
        """Проверяет tool структуры агента без содержимого skills.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            skills_root = workspace / "deep_agent" / "skills"
            skill_dir = skills_root / "demo"
            skill_dir.mkdir(parents=True)
            (workspace / "deep_agent").mkdir(exist_ok=True)
            (workspace / "deep_agent" / "agent.py").write_text("# agent\n", encoding="utf-8")
            (workspace / "AGENTS.md").write_text("# Memory\n", encoding="utf-8")
            (workspace / "README.md").write_text("# Readme\n", encoding="utf-8")
            (workspace / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (workspace / "tests").mkdir()
            (workspace / "tests" / "test_sample.py").write_text("# test\n", encoding="utf-8")
            (workspace / "scripts").mkdir()
            (workspace / "scripts" / "script.py").write_text("# script\n", encoding="utf-8")
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n# Demo\n",
                encoding="utf-8",
            )
            tool = build_get_project_structure_tool(
                workspace_root=workspace,
            )

            report = tool.invoke({"max_entries": 20})

        self.assertEqual(tool.name, "get_project_structure")
        self.assertIn(workspace_tool_path(workspace, workspace, directory=True), report)
        self.assertIn(workspace_tool_path(skills_root, workspace, directory=True), report)
        self.assertIn("agent.py", report)
        self.assertNotIn(workspace_tool_path(skill_path, workspace), report)
        self.assertNotIn("## Skills", report)
        self.assertNotIn("Demo skill", report)
        self.assertNotIn("AGENTS.md", report)
        self.assertNotIn("README.md", report)
        self.assertNotIn("pyproject.toml", report)
        self.assertNotIn("test_sample.py", report)
        self.assertNotIn("script.py", report)

    def test_analyze_image_default_root_comes_from_settings(self) -> None:
        """Проверяет, что analyze_image без аргумента использует workspace_root настроек.

        Returns:
            ``None``.
        """

        settings = load_deep_agent_settings()
        tool = build_analyze_image_tool(client_factory=lambda: self.fail("Client must be lazy."))

        self.assertEqual(tool._workspace_root, settings.workspace_root.resolve())

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
        self.assertTrue(any(isinstance(item, PromptToolDescriptionsMiddleware) for item in middleware))
        self.assertTrue(any(isinstance(item, ThinkToolMiddleware) for item in middleware))
        self.assertTrue(any(isinstance(item, ShellSafetyMiddleware) for item in middleware))
        self.assertTrue(any(isinstance(item, LoopBreakerMiddleware) for item in middleware))

    def test_shell_safety_blocks_unsafe_python_one_liner(self) -> None:
        """Проверяет блокировку небезопасного ``python -c`` до запуска shell.

        Returns:
            ``None``.
        """

        middleware = ShellSafetyMiddleware()
        request = SimpleNamespace(
            tool_call={
                "id": "call-1",
                "name": "execute",
                "args": {"command": 'python -c "x=0; for value in [1]: x += value"'},
            }
        )

        def handler(_request: Any) -> ToolMessage:
            raise AssertionError("unsafe command should be blocked")

        result = middleware.wrap_tool_call(request, handler)

        self.assertEqual(result.name, "execute")
        self.assertEqual(result.status, "error")
        self.assertIn("[SHELL-SAFETY]", result.content)
        self.assertIn("Do not retry", result.content)

    def test_loop_breaker_injects_human_nudge_for_repeated_tool_errors(self) -> None:
        """Проверяет подсказку сменить стратегию после серии повторяющихся ошибок.

        Returns:
            ``None``.
        """

        messages: list[Any] = []
        for index in range(3):
            call_id = f"call-{index}"
            messages.append(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": call_id,
                            "name": "execute",
                            "args": {"command": 'python -c "x=0; for value in [1]: x += value"'},
                        }
                    ],
                )
            )
            messages.append(
                ToolMessage(
                    content="SyntaxError: invalid syntax",
                    tool_call_id=call_id,
                    name="execute",
                    status="error",
                )
            )

        update = LoopBreakerMiddleware().before_model({"messages": messages}, None)

        self.assertIsNotNone(update)
        assert update is not None
        self.assertIsInstance(update["messages"][0], HumanMessage)
        self.assertIn("[LOOP-BREAKER]", update["messages"][0].content)
        self.assertIn("/artifacts/run.py", update["messages"][0].content)

    def test_gigachat_practices_prompt_keeps_project_path_contract(self) -> None:
        """Проверяет, что GigaChat prompt-довесок сохраняет namespace workspace ``/``.

        Returns:
            ``None``.
        """

        self.assertIn("supplement the project", GIGACHAT_AGENT_PRACTICES_PROMPT)
        self.assertIn("The workspace root is ``/``", GIGACHAT_AGENT_PRACTICES_PROMPT)
        self.assertIn("/artifacts/run.py", GIGACHAT_AGENT_PRACTICES_PROMPT)
        self.assertNotIn("MEMORY.md", GIGACHAT_AGENT_PRACTICES_PROMPT)

    def test_tool_output_summary_includes_workspace_artifact_path(self) -> None:
        """Offload summary должен показывать workspace-путь для pandas pickle.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            outputs_dir = workspace / "artifacts"
            middleware = ToolOutputFileMiddleware(
                output_dir=outputs_dir,
                workspace_root=workspace,
                min_rows_to_save=1,
            )
            result = middleware._process_tool_message(
                result=ToolMessage(
                    content="[]",
                    artifact=[{"event_id": "1"}, {"event_id": "2"}],
                    tool_call_id="call-1",
                    name="load_data",
                ),
                tool_name="load_data",
            )
            absolute_file_exists = Path(result.artifact["absolute_file"]).exists()

        self.assertIn("artifact_path:", result.content)
        self.assertIn("pandas_read_pickle: rows = pd.read_pickle(resolve_workspace_path", result.content)
        self.assertIn("read_pickle_file: read_pickle_file", result.content)
        self.assertIn("/artifacts/", result.content)
        self.assertEqual(result.artifact["workspace_file"].split("/")[1], "artifacts")
        self.assertTrue(absolute_file_exists)

    def test_create_session_tool_outputs_dir_uses_single_artifacts_folder(self) -> None:
        """Проверяет, что session outputs не создают дополнительный подкаталог.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir) / "artifacts"
            result = create_session_tool_outputs_dir(artifacts_dir)

            self.assertEqual(result, artifacts_dir.resolve())
            self.assertTrue(artifacts_dir.exists())

    def test_agent_builder_does_not_add_permissions_or_interrupt_fallback(self) -> None:
        """Сборка агента не должна содержать permission rules или HITL fallback.

        Returns:
            ``None``.
        """

        source = (Path(__file__).parents[1] / "deep_agent" / "agent.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("permissions=", source)
        self.assertNotIn("interrupt_on=", source)
        self.assertNotIn("FilesystemPermission", source)

    def test_runtime_context_prompt_defines_current_date_and_artifact_paths(self) -> None:
        """Runtime prompt должен явно фиксировать дату и реальные пути артефактов.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            outputs_dir = workspace / "artifacts"
            outputs_dir.mkdir(parents=True)
            prompt = _build_runtime_context_prompt(workspace, outputs_dir)

        self.assertIn("Current date:", prompt)
        self.assertIn("Workspace root:", prompt)
        self.assertIn("Artifacts directory:", prompt)
        self.assertIn("last 2 days", prompt)
        self.assertIn("Never take", prompt)
        self.assertIn("examples", prompt)
        self.assertIn("demo data", prompt)
        self.assertIn("single artifacts directory", prompt)

    def test_agent_builder_keeps_session_tool_outputs_persistent(self) -> None:
        """Сборка агента не должна удалять session tool outputs при закрытии графа.

        Returns:
            ``None``.
        """

        source = (Path(__file__).parents[1] / "deep_agent" / "agent.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("\n    register_session_tool_outputs_cleanup(agent", source)

    def test_agents_memory_and_conversation_checkpointer_use_native_runtime(self) -> None:
        """Project memory и краткосрочная память должны использовать DeepAgents/LangGraph."""

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.assertEqual(
                _agents_memory_path("AGENTS.md", workspace),
                workspace_tool_path(workspace / "AGENTS.md", workspace),
            )
            self.assertEqual(
                _agents_memory_path("config\\AGENTS.md", workspace),
                workspace_tool_path(workspace / "config" / "AGENTS.md", workspace),
            )
        with self.assertRaisesRegex(ValueError, "workspace"):
            _agents_memory_path("../AGENTS.md", Path(tempfile.gettempdir()))
        self.assertIsInstance(build_conversation_checkpointer(), InMemorySaver)

    def test_native_memory_middleware_loads_agents_file_into_prompt(self) -> None:
        """Нативный MemoryMiddleware должен читать AGENTS.md и добавлять его в system prompt."""

        settings = load_deep_agent_settings()
        backend = build_skills_backend(settings)
        memory_path = _agents_memory_path(
            settings.agents_file_name,
            settings.workspace_root,
        )
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
        self.assertIn(memory_path, prompt_text)
        self.assertIn("## Role", prompt_text)
        self.assertIn("data-retrieval-agent", prompt_text)

    def test_filesystem_tool_descriptions_define_public_call_contract(self) -> None:
        """Описания filesystem tools должны фиксировать публичный контракт вызова."""

        read_file_description = TOOL_DESCRIPTION_OVERRIDES["read_file"]
        grep_description = TOOL_DESCRIPTION_OVERRIDES["grep"]
        write_file_description = TOOL_DESCRIPTION_OVERRIDES["write_file"]
        edit_file_description = TOOL_DESCRIPTION_OVERRIDES["edit_file"]

        self.assertIn("pass the path through `file_path`", read_file_description)
        self.assertIn("request the next fragment with a new `offset`", read_file_description)
        self.assertIn("pass the search text through `pattern`", grep_description)
        self.assertIn("`path` points to a directory", grep_description)
        self.assertIn("single file name can be passed through `glob`", grep_description)
        self.assertIn("exit code, stdout, and stderr", TOOL_DESCRIPTION_OVERRIDES["execute"])
        self.assertIn("`/` is the configured user workspace root", write_file_description)
        self.assertIn("overwrites an existing file at the same path", write_file_description)
        self.assertIn("_final_final", write_file_description)
        self.assertIn("do not write under `/deep_agent/`", write_file_description)
        self.assertIn("should be edited only for explicit agent code", edit_file_description)

    def test_load_skills_description_rejects_auxiliary_files(self) -> None:
        """Описание load_skills должно запрещать загрузку fields.md как skill."""

        self.assertIn("loads only `SKILL.md` files", LOAD_SKILLS_DESCRIPTION)
        self.assertIn(
            "Do not pass paths like `/deep_agent/skills/name/fields.md`",
            LOAD_SKILLS_DESCRIPTION,
        )

    def test_tool_descriptions_are_separate_from_agent_workflow_rules(self) -> None:
        """Описания tools не должны содержать внутренние workflow-правила агента."""

        self.assertIn("Runs one subagent", TASK_TOOL_DESCRIPTION)
        self.assertIn("`subagent_type`", TASK_TOOL_DESCRIPTION)
        self.assertIn("`description`", TASK_TOOL_DESCRIPTION)
        self.assertNotIn("coding-agent", TASK_TOOL_DESCRIPTION)
        self.assertNotIn("data-retrieval-agent", TASK_TOOL_DESCRIPTION)
        self.assertNotIn("supervisor", TASK_TOOL_DESCRIPTION)
        self.assertNotIn("не повторяй один и тот же tool call", TASK_TOOL_DESCRIPTION)
        self.assertNotIn("пустой отчёт", TASK_TOOL_DESCRIPTION)
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
        self.assertIn("do not call tools in a loop after a successful result", SYSTEM_PROMPT)
        self.assertIn("Treat `/` in filesystem tools as the configured user workspace root", SYSTEM_PROMPT)
        self.assertIn("Do not use `/deep_agent/` as a default", SYSTEM_PROMPT)
        self.assertIn("среди этих", SYSTEM_PROMPT)
        self.assertIn("pd.read_pickle(resolve_workspace_path(artifact_path))", SYSTEM_PROMPT)
        self.assertIn("read_pickle_file(artifact_path)", SYSTEM_PROMPT)
        self.assertIn("Do not delegate a new `load_data`", SYSTEM_PROMPT)
        self.assertIn("good plan for analytics over retrieved data", SYSTEM_PROMPT)
        self.assertIn("retrieve raw trigger rows for the last calendar month", SYSTEM_PROMPT)
        self.assertIn("retrieve raw trigger rows for the previous calendar month", SYSTEM_PROMPT)
        self.assertIn("calculate absolute change and percentage", SYSTEM_PROMPT)
        self.assertIn("handling of zero previous-month counts", SYSTEM_PROMPT)
        self.assertIn("Before accepting a subagent result", SYSTEM_PROMPT)
        self.assertIn("two-step operation such as rename, move, convert", SYSTEM_PROMPT)
        self.assertIn("intermediate artifact is not enough", SYSTEM_PROMPT)
        self.assertIn("bounded code and workspace tasks", CODING_AGENT_PROMPT)
        self.assertIn("Do not access table data", CODING_AGENT_PROMPT)
        self.assertIn("`/deep_agent/` is the agent implementation directory", CODING_AGENT_PROMPT)
        self.assertIn("Treat the requested deliverable as strict", CODING_AGENT_PROMPT)
        self.assertIn("For two-step operations, complete both halves", CODING_AGENT_PROMPT)
        self.assertIn("For policy/action JSON tasks", CODING_AGENT_PROMPT)
        self.assertIn("For merge or conflict-resolution tasks", CODING_AGENT_PROMPT)
        self.assertIn("material parameters", DATA_RETRIEVAL_PROMPT)
        self.assertIn("observed results", DATA_RETRIEVAL_PROMPT)
        self.assertIn("Preserve exact names and values from verified sources", DATA_RETRIEVAL_PROMPT)
        self.assertIn("every exact value, field, period label, and artifact path", DATA_RETRIEVAL_PROMPT)
        self.assertIn("material parameters", CODING_AGENT_PROMPT)
        self.assertIn("observed result", CODING_AGENT_PROMPT)
        self.assertIn("Do not add row limits on behalf of the user", SYSTEM_PROMPT)
        self.assertIn("Do not add `LIMIT` unless the original user request", DATA_RETRIEVAL_PROMPT)
        self.assertIn('Path(ARTIFACTS_DIR) / "file.csv"', DATA_RETRIEVAL_PROMPT)
        self.assertIn("workspace path under the single `/artifacts` directory", DATA_RETRIEVAL_PROMPT)
        self.assertIn("pd.read_pickle(resolve_workspace_path", DATA_RETRIEVAL_PROMPT)
        self.assertIn("Comparison and change requests require separate comparable populations", DATA_RETRIEVAL_PROMPT)
        self.assertIn("two adjacent 7-day windows", DATA_RETRIEVAL_PROMPT)
        self.assertIn("do not replace them with one 20260601-20260614 aggregate", DATA_RETRIEVAL_PROMPT)
        self.assertIn("A mandatory calls section with one item per tool invocation", DATA_RETRIEVAL_PROMPT)
        self.assertIn("exact tool name", DATA_RETRIEVAL_PROMPT)
        self.assertIn("exact material parameters / input parameters", DATA_RETRIEVAL_PROMPT)
        self.assertIn("## Вызовы инструментов", DATA_RETRIEVAL_PROMPT)
        self.assertIn('Do not add a separate "Ограничения" / limitations section by default', DATA_RETRIEVAL_PROMPT)

    def test_load_data_description_makes_limit_user_explicit_only(self) -> None:
        """Описание ``load_data`` должно запрещать неявный LIMIT.

        Returns:
            ``None``.
        """

        self.assertIn("LIMIT не является обязательным", READ_TABLE_DESCRIPTION)
        self.assertIn("Не добавляй LIMIT самостоятельно", READ_TABLE_DESCRIPTION)
        self.assertIn("LIMIT запрещён", READ_TABLE_DESCRIPTION)

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

    def test_text_column_semantic_filter_skill_is_not_event_description_only(self) -> None:
        """Skill смысловой фильтрации должен работать с любой текстовой колонкой."""

        skill_path = (
            Path(__file__).resolve().parents[1]
            / "deep_agent"
            / "skills"
            / "poisk-zapisey-po-opisaniyu"
            / "SKILL.md"
        )

        content = skill_path.read_text(encoding="utf-8")

        self.assertIn("name: text-column-semantic-filter", content)
        self.assertIn("text_column", content)
        self.assertIn("unique_values", content)
        self.assertIn("exact_candidates", content)
        self.assertIn("atm_merchant_name", content)
        self.assertIn("Загрузи полный список `unique_values` в контекст анализа", content)
        self.assertIn("Не переходи к итоговому списку, пока не проверены все батчи", content)
        self.assertIn("Не привязывай workflow к `event_description`", content)
        self.assertIn("Не используй `LIKE` или `CONTAINS`", content)
        self.assertIn("Не добавляй логику финальной выборки строк в этот skill", content)
        self.assertNotIn("result_fields", content)
        self.assertNotIn("final_artifact", content)


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
