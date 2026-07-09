"""Инициализация памяти профиля пользователя.

Содержит:
- UserProfileMemory: параметры памяти профиля пользователя.
- build_user_profile_memory_reference: создает ссылку на память без Spark-запроса.
- ensure_user_profile_memory: создает файл памяти профиля, если его еще нет.
- extract_login_from_path: извлекает login из runtime workspace path.
- fetch_user_info: читает ФИО пользователя из Spark addressbook.
- _build_user_profile_memory_content: формирует markdown-файл памяти.
- _login_in_memory: проверяет наличие текущего login в файле памяти.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents.backends.utils import create_file_data

from deep_agent.memory.simple_file_store import SimpleFileStore

USER_PROFILE_MEMORY_PATH = "/memories/user_profile.md"
USER_PROFILE_STORE_KEY = "/user_profile.md"


@dataclass(frozen=True)
class UserProfileMemory:
    """Хранит параметры памяти профиля пользователя.

    Args:
        login: Login пользователя.
        namespace: Namespace LangGraph Store для изоляции памяти.
        store: Store с файлом памяти.
        memory_source: Виртуальный путь файла памяти deepagents.

    Returns:
        Контейнер параметров памяти профиля пользователя.
    """

    login: str
    namespace: tuple[str, ...]
    store: Any
    memory_source: str = USER_PROFILE_MEMORY_PATH

    @property
    def memory_path(self) -> str:
        """Возвращает путь файла памяти deepagents.

        Args:
            Отсутствуют.

        Returns:
            Путь файла памяти вида ``/memories/user_profile.md``.
        """

        return self.memory_source


def build_user_profile_memory_reference(
    *,
    workspace_root: str | Path,
    memory_root: str | Path,
) -> UserProfileMemory:
    """Создает ссылку на память профиля без Spark-запроса.

    Args:
        workspace_root: Runtime workspace, из которого извлекается login.
        memory_root: Директория JSON-файлов памяти.

    Returns:
        Параметры памяти профиля пользователя без чтения Spark-таблиц.
    """

    login = extract_login_from_path(workspace_root)
    namespace = ("user-profile", login)
    store = SimpleFileStore(root_dir=str(memory_root))
    return UserProfileMemory(login=login, namespace=namespace, store=store)


def ensure_user_profile_memory(
    *,
    profile: UserProfileMemory,
    spark_session_factory: Any,
) -> str | None:
    """Создает файл памяти профиля, если он отсутствует.

    Args:
        profile: Ссылка на память профиля пользователя.
        spark_session_factory: Фабрика SparkSession из инструмента ``load_data``.

    Returns:
        Содержимое файла памяти или ``None``.
    """

    existing_item = profile.store.get(profile.namespace, USER_PROFILE_STORE_KEY)
    if existing_item is not None:
        content = existing_item.value.get("content", "")
        if _login_in_memory(content, profile.login):
            return content

    spark = spark_session_factory()
    try:
        full_name = fetch_user_info(spark, profile.login)
    finally:
        stop = getattr(spark, "stop", None)
        if callable(stop):
            stop()

    if not full_name:
        return None

    content = _build_user_profile_memory_content(profile.login, full_name)
    profile.store.put(
        profile.namespace,
        USER_PROFILE_STORE_KEY,
        create_file_data(content),
    )
    return content


def extract_login_from_path(workspace_root: str | Path) -> str:
    """Извлекает числовой login из runtime workspace path.

    Args:
        workspace_root: Runtime workspace path агента.

    Returns:
        Первый числовой фрагмент из имени директории workspace.

    Raises:
        ValueError: Если числовой login не найден.
    """

    directory_name = Path(workspace_root).expanduser().resolve().name
    match = re.search(r"\d+", directory_name)
    if not match:
        raise ValueError(f"Не удалось найти логин в пути: {workspace_root}")
    return match.group()


def fetch_user_info(spark: Any, login: str) -> str | None:
    """Читает ФИО пользователя из Spark addressbook по sigma login.

    Args:
        spark: Активная SparkSession.
        login: Login пользователя без доменного префикса.

    Returns:
        ФИО пользователя или ``None``.
    """

    from pyspark.sql import functions as f

    sigma_login = "SIGMA\\" + login
    table = (
        spark.table("csp_addressbook_inc.base")
        .filter(f.col("domainloginsigma") == f.lit(sigma_login))
        .select("empfindstr", "domainloginomega", "domainloginsigma")
        .limit(1)
    )
    if table.count() == 0:
        return None

    user_info = table.toPandas()
    if user_info.empty or "empfindstr" not in user_info.columns:
        return None
    return user_info.iloc[0]["empfindstr"]


def _build_user_profile_memory_content(login: str, full_name: str) -> str:
    """Формирует markdown-содержимое файла памяти профиля пользователя.

    Args:
        login: Login пользователя.
        full_name: ФИО пользователя.

    Returns:
        Markdown-текст для Store.
    """

    return f"""# User profile

login: {login}
name: {full_name}
"""


def _login_in_memory(content: str, login: str) -> bool:
    """Проверяет, что файл памяти содержит текущий login.

    Args:
        content: Текст файла памяти.
        login: Текущий login пользователя.

    Returns:
        ``True``, если файл содержит текущий login.
    """

    return f"login: {login}" in content
