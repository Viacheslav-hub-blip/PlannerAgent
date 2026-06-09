"""Инструменты аналитического DeepAgent.

Содержит:
- build_spark_data_tools: сборка инструмента чтения данных из Spark.
- build_fake_spark_data_tools: сборка локального инструмента чтения тестовых CSV.
- build_execute_python_code_tool: выполнение безопасного Python-кода.
- build_load_skills_tool: пакетная загрузка SKILL.md в контекст.
- wrap_data_tools_with_query_code: добавление прозрачного описания запроса к data-tools.
"""

from deep_agent_test.tools.data_tools_wrapper import wrap_data_tools_with_query_code
from deep_agent_test.tools.execute_python_code import build_execute_python_code_tool
from deep_agent_test.tools.fake_spark_data import build_fake_spark_data_tools
from deep_agent_test.tools.load_skills import build_load_skills_tool
from deep_agent_test.tools.spark_data import build_spark_data_tools

__all__ = [
    "build_execute_python_code_tool",
    "build_fake_spark_data_tools",
    "build_load_skills_tool",
    "build_spark_data_tools",
    "wrap_data_tools_with_query_code",
]
