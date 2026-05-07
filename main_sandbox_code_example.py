"""Пример запуска агента с tool-генератором Python-кода и локальной sandbox.

Содержит:
- CodeGeneratorInput: схема аргументов демо-инструмента генерации кода.
- generate_python_code: локальный демо-инструмент, имитирующий MCP code generator.
- build_code_agent: сборка ResearchAgent с ClientPythonSandbox.
- main: ручной пример запуска агента через LangChain ainvoke.

Файл не запускается тестами автоматически. Он нужен как шаблон подключения
реального MCP-инструмента `generate_python_code` или `generate_plotly_python_code`.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pandas as pd
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from model import model as llm
from planner_agent import ResearchAgent
from sandbox import ClientPythonSandbox


PROJECT_ROOT = Path(__file__).resolve().parent


class CodeGeneratorInput(BaseModel):
    """Аргументы инструмента, который генерирует Python-код для исполнения."""

    instruction: str = Field(
        description="Задача на генерацию Python-кода для анализа данных.",
    )
    target_variable: str = Field(
        default="result",
        description="Имя переменной результата, которую должен создать код.",
    )


def generate_python_code(
        instruction: str,
        target_variable: str = "result",
) -> str:
    """Имитирует внешний MCP-инструмент генерации Python-кода.

    Args:
        instruction: Инструкция агента на генерацию кода.
        target_variable: Имя переменной, которую должен создать сгенерированный код.

    Returns:
        Python-код. В реальном запуске вместо этой функции можно передать MCP tool
        с таким же именем, а агент сам обернет его в executor.
    """

    return f"""
{target_variable} = (
    df_current
    .groupby("event_type", dropna=False)
    .agg(
        rows=("event_type", "size"),
        total_amount=("transaction_amount", "sum"),
        avg_amount=("transaction_amount", "mean"),
    )
    .reset_index()
    .sort_values("rows", ascending=False)
)
"""


def build_code_agent() -> tuple[ResearchAgent, ClientPythonSandbox]:
    """Собирает агента с песочницей и tool генерации кода.

    Args:
        Отсутствуют. Демо-данные берутся из `examples/data/cspfs_repo_features3.hits_extra_info_129372427_view.csv`.

    Returns:
        Кортеж `(agent, sandbox)`, где agent совместим с LangChain Runnable API,
        а sandbox хранит исходный DataFrame и переменные, созданные кодом.
    """

    data_path = PROJECT_ROOT / "examples" / "data" / "cspfs_repo_features3.hits_extra_info_129372427_view.csv"
    df = pd.read_csv(data_path)
    sandbox = ClientPythonSandbox(
        initial_globals={"df_current": df},
        allowed_libraries={"pd": pd},
    )
    sandbox.last_dataframe_variable = "df_current"

    code_tool = StructuredTool.from_function(
        func=generate_python_code,
        name="generate_python_code",
        description=(
            "Генерирует Python-код для анализа текущего DataFrame. "
            "Всегда создает переменную target_variable."
        ),
        args_schema=CodeGeneratorInput,
    )

    agent = ResearchAgent(
        model=llm,
        sandbox=sandbox,
        tools=[code_tool],
        code_generator_tool_names={"generate_python_code"},
        workspace_root=str(PROJECT_ROOT / "examples"),
        runs_dir=str(PROJECT_ROOT / "examples" / "runs"),
        memory_dir=str(PROJECT_ROOT / "examples" / "memory"),
        skills_dir=str(PROJECT_ROOT / "examples" / "skills"),
    )
    return agent, sandbox


async def main() -> None:
    """Запускает ручной пример анализа через агента.

    Args:
        Отсутствуют.

    Returns:
        None. Печатает финальное сообщение агента и переменные песочницы.
    """

    agent, sandbox = build_code_agent()
    messages = await agent.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Посчитай метрики по event_type через generate_python_code. "
                        "Сохрани результат в переменную event_type_metrics и объясни вывод."
                    )
                )
            ],
        }
    )
    previews = await sandbox.get_all_variable_previews()
    print("\nFinal message:")
    print(messages[-1].content)
    print("\nSandbox variables:")
    for name, preview in previews.items():
        print(f"\n{name}\n{preview}")


if __name__ == "__main__":
    started_at = time.perf_counter()
    asyncio.run(main())
    print(f"\nElapsed seconds: {time.perf_counter() - started_at:.2f}")
