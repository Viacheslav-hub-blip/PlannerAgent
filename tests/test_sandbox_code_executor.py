"""Тесты интеграции генератора кода с локальной Python-песочницей.

Содержит:
- FakeCodeGeneratorInput: схема аргументов тестового генератора кода.
- fake_generate_python_code: тестовый LangChain tool, возвращающий Python-код.
- SandboxCodeExecutorTests: проверки wrapper-а и factory-подготовки tools.
"""

from __future__ import annotations

import json
import unittest

import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from planner_agent.factory import _prepare_worker_tools
from sandbox import BaseCodeExecutorTool, ClientPythonSandbox


class FakeCodeGeneratorInput(BaseModel):
    """Аргументы тестового инструмента, который имитирует MCP-генератор кода."""

    instruction: str = Field(description="Текстовая инструкция для генерации кода.")
    target_variable: str = Field(
        default="result",
        description="Имя переменной, которую должен создать сгенерированный код.",
    )


def fake_generate_python_code(
        instruction: str,
        target_variable: str = "result",
) -> str:
    """Возвращает Python-код для проверки выполнения в песочнице.

    Args:
        instruction: Текстовая инструкция. В тесте не используется напрямую.
        target_variable: Имя переменной результата, которую должен создать код.

    Returns:
        Строка Python-кода, создающего агрегированный DataFrame.
    """

    return (
        f"{target_variable} = "
        "df_current.groupby('segment', dropna=False).size().reset_index(name='count')"
    )


class SandboxCodeExecutorTests(unittest.IsolatedAsyncioTestCase):
    """Проверяет исполнение кода через BaseCodeExecutorTool и ClientPythonSandbox."""

    async def test_code_generator_tool_executes_code_in_sandbox(self) -> None:
        """Проверяет, что генератор кода создает переменную в песочнице."""

        df = pd.DataFrame(
            {
                "segment": ["a", "a", "b", None],
                "amount": [10, 20, 30, 40],
            }
        )
        sandbox = ClientPythonSandbox(
            initial_globals={"df_current": df},
            allowed_libraries={"pd": pd},
        )
        generator_tool = StructuredTool.from_function(
            func=fake_generate_python_code,
            name="generate_python_code",
            description="Генерирует Python-код для анализа DataFrame.",
            args_schema=FakeCodeGeneratorInput,
        )
        executor_tool = BaseCodeExecutorTool(
            name="generate_python_code",
            description="Генерирует и исполняет Python-код.",
            mcp_tool=generator_tool,
            sandbox=sandbox,
        )

        raw_result = await executor_tool.ainvoke(
            {
                "instruction": "Посчитай количество строк по segment.",
                "target_variable": "segment_counts",
            }
        )

        result = json.loads(raw_result)
        created_value = await sandbox.get_variable("segment_counts")
        previews = await sandbox.get_all_variable_previews()

        self.assertTrue(result["success"])
        self.assertEqual(result["target_variable"], "segment_counts")
        self.assertIsNotNone(created_value)
        self.assertEqual(sandbox.last_target_variable, "segment_counts")
        self.assertEqual(sandbox.last_dataframe_variable, "segment_counts")
        self.assertIn("segment_counts", previews)
        self.assertIn("df_current", previews)
        self.assertIn("pd", sandbox.globals)

    async def test_factory_wraps_named_code_generator_tool(self) -> None:
        """Проверяет, что factory заменяет указанный генератор кода на executor tool."""

        sandbox = ClientPythonSandbox(initial_globals={"df_current": pd.DataFrame()})
        generator_tool = StructuredTool.from_function(
            func=fake_generate_python_code,
            name="generate_python_code",
            description="Генерирует Python-код для анализа DataFrame.",
            args_schema=FakeCodeGeneratorInput,
        )

        prepared_tools = _prepare_worker_tools(
            tools=[generator_tool],
            sandbox=sandbox,
            code_generator_tool_names={"generate_python_code"},
        )

        self.assertEqual(len(prepared_tools), 1)
        self.assertIsInstance(prepared_tools[0], BaseCodeExecutorTool)
        self.assertEqual(prepared_tools[0].name, "generate_python_code")

    async def test_code_generator_task_receives_grounded_data_contract(self) -> None:
        """Проверяет добавление контракта работы с реальными данными."""

        sandbox = ClientPythonSandbox(initial_globals={"df_current": pd.DataFrame()})
        generator_tool = StructuredTool.from_function(
            func=fake_generate_python_code,
            name="generate_python_code",
            description="Генерирует Python-код для анализа DataFrame.",
            args_schema=FakeCodeGeneratorInput,
        )
        executor_tool = BaseCodeExecutorTool(
            name="generate_python_code",
            description="Генерирует и исполняет Python-код.",
            mcp_tool=generator_tool,
            sandbox=sandbox,
        )

        args = executor_tool._prepare_mcp_args(
            instruction="Посчитай количество строк по segment.",
            target_variable="segment_counts",
        )

        self.assertIn("Контракт работы с данными", args["instruction"])
        self.assertIn("Не создавай демонстрационные", args["instruction"])


if __name__ == "__main__":
    unittest.main()
