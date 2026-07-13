"""Adapter запуска DeepAgent через LangGraph Agent Server.

Содержит:
- KITAI_MODEL_CONFIG: явные параметры KitAI-модели для локального запуска.
- build_ui_agent_settings: сборка путей UI с workspace на уровень выше проекта.
- create_spark_session: фабрика SparkSession для пользовательского Spark-конфига.
- build_langgraph_agent_server_agent: сборка агента для LangGraph Agent Server.
- agent: экспортируемый граф, который читает ``local_ui/langgraph.json``.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from deep_agent.agent import build_agent
from deep_agent._request_log_config import build_default_agent_request_logger
from deep_agent.agent_settings import AgentSettings, load_agent_settings
from deep_agent.gigachat_kitai_model import build_gigachat_kitai_model
from deep_agent.tools.load_data_spark_tool import build_spark_data_tools

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
ARTIFACTS_VIRTUAL_DIR = "/artifacts/"
KITAI_MODEL_CONFIG = {
    "kitai_host_sdk": "",
    "cert_file": "",
    "key_file": "",
    "model": "GigaChat-2-Max",
    "verify_ssl": False,
    "system_name": "lab",
    "module_name": "lab_antifraud_edge",
    "polling_retries": 500,
    "polling_delay_in_sec": 2,
    "polling_start_delay_in_sec": 2,
    "polling_timeout_in_sec": 180,
    "temperature": 0.05,
    "profanity_check": False,
    "verbose": True,
}


def _diagnostic_log(message: str) -> None:
    """Печатает диагностическое сообщение adapter в общий stdout-лог backend.

    Args:
        message: Текст диагностического сообщения.

    Returns:
        ``None``.
    """

    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"[{timestamp}] [agent-adapter] {message}", flush=True)


def _path_exists(value: Any) -> bool:
    """Проверяет существование пути без вывода самого содержимого файла.

    Args:
        value: Значение пути из конфигурации.

    Returns:
        ``True``, если путь непустой и существует на файловой системе.
    """

    return bool(value) and Path(str(value)).exists()


def build_ui_agent_settings() -> AgentSettings:
    """Собирает настройки UI с файловым workspace на уровень выше проекта.

    Args:
        Отсутствуют. Пути берутся из ``PROJECT_ROOT`` и ``WORKSPACE_ROOT``.

    Returns:
        ``AgentSettings``, где виртуальный ``/`` указывает на ``WORKSPACE_ROOT``,
        а ``AGENTS.md``, ``skills`` и ``artifacts`` остаются внутри ``PROJECT_ROOT``.
    """

    project_relative_agents_file = (
        PROJECT_ROOT.relative_to(WORKSPACE_ROOT) / "AGENTS.md"
    ).as_posix()
    settings = load_agent_settings(WORKSPACE_ROOT)
    return replace(
        settings,
        agents_file_name=project_relative_agents_file,
        skills_root=PROJECT_ROOT / "skills",
        tool_outputs_dir=PROJECT_ROOT / "artifacts",
    )


def create_spark_session() -> Any:
    """Создает SparkSession для инструмента ``load_data``.

    Args:
        Отсутствуют. Все параметры Spark задаются внутри этой функции через
        ``SparkSession.builder.config(...)``.

    Returns:
        Настроенный ``pyspark.sql.SparkSession`` для чтения рабочих таблиц.
    """

    spark_python_paths = (
        "/home/23111424_omega-sbrf-ru/python311/lib/python3.11/site-packages",
        "/usr/sdp/current/spark3-client/python",
        "/usr/sdp/current/spark3-client/python/lib/py4j-0.10.9.3-src.zip",
    )
    for path in spark_python_paths:
        if path not in sys.path:
            sys.path.insert(0, path)

    from pyspark.sql import SparkSession

    driver_cores = "8"
    driver_memory = "10G"
    executor_cores = "10"
    executor_memory = "7G"
    min_executors = "12"
    init_executors = "12"
    spark_max_exec = "32"
    job_name = "csi_2_report"

    hadoop_file_systems = (
        "hdfs://lab-antifraud-sdp,"
        "hdfs://sdp-datastore:8020/,"
        "hdfs://sdp-datastore-fs:8020/"
    )

    return (
        SparkSession.builder.master("yarn")
        .appName(job_name)
        .config("spark.dynamicAllocation.enabled", "true")
        .config("spark.dynamicAllocation.minExecutors", min_executors)
        .config("spark.dynamicAllocation.initialExecutors", init_executors)
        .config("spark.dynamicAllocation.maxExecutors", spark_max_exec)
        .config("spark.executor.cores", executor_cores)
        .config("spark.executor.memory", executor_memory)
        .config("spark.driver.memory", driver_memory)
        .config("spark.driver.cores", driver_cores)
        .config("spark.driver.maxResultSize", "4G")
        .config("spark.default.parallelism", "400")
        .config("spark.executor.extraJavaOptions", "-XX:+UseG1GC")
        .config("spark.memory.fraction", "0.7")
        .config("spark.memory.storageFraction", "0.3")
        .config("spark.network.timeout", "14400s")
        .config("spark.rpc.message.maxSize", "512")
        .config("spark.shuffle.service.enabled", "true")
        .config("spark.shuffle.compress", "true")
        .config("spark.shuffle.spill.compress", "true")
        .config("spark.sql.broadcastTimeout", "1200")
        .config("spark.sql.autoBroadcastJoinThreshold", "-1")
        .config("spark.yarn.driver.memory.overhead", "4G")
        .config("spark.yarn.executor.memory.overhead", "3G")
        .config("spark.kryoserializer.buffer.max", "1024m")
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config("spark.sql.shuffle.partitions", "200")
        .config("spark.sql.hive.convertMetastoreParquet", "false")
        .config("spark.sql.parquet.int96RebaseModeInRead", "CORRECTED")
        .config("spark.sql.parquet.int96RebaseModeInWrite", "CORRECTED")
        .config("spark.sql.parquet.datetimeRebaseModeInRead", "CORRECTED")
        .config("spark.sql.parquet.datetimeRebaseModeInWrite", "CORRECTED")
        .config("spark.kerberos.access.hadoopFileSystems", hadoop_file_systems)
        .getOrCreate()
    )


def build_langgraph_agent_server_agent() -> Any:
    """Собирает DeepAgent для LangGraph Agent Server.

    Args:
        Отсутствуют. Adapter использует Python-настройки проекта и подключает
        ``load_data`` через пользовательскую фабрику SparkSession.

    Returns:
        Скомпилированный граф без пользовательского checkpointer. Persistence,
        threads и streaming предоставляет LangGraph Agent Server.
    """

    last_step = "agent_build.start"
    try:
        _diagnostic_log(last_step)
        _diagnostic_log(f"project_root={PROJECT_ROOT}")
        _diagnostic_log(f"workspace_root={WORKSPACE_ROOT}")
        _diagnostic_log(
            "model_config "
            f"host_set={bool(KITAI_MODEL_CONFIG.get('kitai_host_sdk'))} "
            f"model={KITAI_MODEL_CONFIG.get('model')} "
            f"cert_exists={_path_exists(KITAI_MODEL_CONFIG.get('cert_file'))} "
            f"key_exists={_path_exists(KITAI_MODEL_CONFIG.get('key_file'))}"
        )

        last_step = "settings.loaded"
        settings = build_ui_agent_settings()
        _diagnostic_log(
            f"{last_step} workspace_root={settings.workspace_root} "
            f"skills_root={settings.skills_root} "
            f"tool_outputs_dir={settings.tool_outputs_dir}"
        )

        last_step = "request_logger.created"
        request_logger = build_default_agent_request_logger()
        if request_logger is None:
            _diagnostic_log(f"{last_step} enabled=False")
        else:
            request_logger.initialize()
            _diagnostic_log(
                f"{last_step} enabled=True "
                f"schema={request_logger.schema_name} "
                f"table={request_logger.table_name}"
            )

        last_step = "model.created"
        model = build_gigachat_kitai_model(**KITAI_MODEL_CONFIG)
        _diagnostic_log(f"{last_step} type={type(model).__name__}")

        last_step = "data_tools.created"
        data_tools = build_spark_data_tools(
            spark_session_factory=create_spark_session,
            query_parser_model=model,
            output_dir=settings.tool_outputs_dir,
            workspace_root=settings.workspace_root,
        )
        _diagnostic_log(f"{last_step} count={len(data_tools)} names={[tool.name for tool in data_tools]}")

        last_step = "graph.created"
        agent_graph = build_agent(
            model=model,
            settings=settings,
            data_tools=data_tools,
            checkpointer=None,
            state_artifacts_virtual_dir=ARTIFACTS_VIRTUAL_DIR,
            request_logger=request_logger,
        )
        _diagnostic_log(f"{last_step} type={type(agent_graph).__name__}")
        return agent_graph
    except Exception as error:
        _diagnostic_log(f"agent_build.failed last_step={last_step} error={type(error).__name__}: {error}")
        print(traceback.format_exc(), flush=True)
        raise


agent = build_langgraph_agent_server_agent()


