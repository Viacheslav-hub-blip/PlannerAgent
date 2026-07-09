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

USER_PROFILE_MEMORY_PATH = "/.deep_agent/memory/user_profile.md"


@dataclass(frozen=True)
class UserProfileMemory:
    """Хранит параметры памяти профиля пользователя.

    Args:
        login: Login пользователя.
        file_path: Физический путь к файлу памяти профиля.
        memory_source: Виртуальный путь файла памяти deepagents.

    Returns:
        Контейнер параметров памяти профиля пользователя.
    """

    login: str
    file_path: Path
    memory_source: str = USER_PROFILE_MEMORY_PATH

    @property
    def memory_path(self) -> str:
        """Возвращает путь файла памяти deepagents.

        Args:
            Отсутствуют.

        Returns:
            Путь файла памяти вида ``/.deep_agent/memory/user_profile.md``.
        """

        return self.memory_source


def build_user_profile_memory_reference(
    *,
    workspace_root: str | Path,
) -> UserProfileMemory:
    """Создает ссылку на память профиля без Spark-запроса.

    Args:
        workspace_root: Runtime workspace, из которого извлекается login.

    Returns:
        Параметры памяти профиля пользователя без чтения Spark-таблиц.
    """

    login = extract_login_from_path(workspace_root)
    file_path = Path(workspace_root).expanduser().resolve() / ".deep_agent" / "memory" / "user_profile.md"
    return UserProfileMemory(login=login, file_path=file_path)


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

    if profile.file_path.exists():
        content = profile.file_path.read_text(encoding="utf-8")
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
    profile.file_path.parent.mkdir(parents=True, exist_ok=True)
    profile.file_path.write_text(content, encoding="utf-8")
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

    resolved_path = Path(workspace_root).expanduser().resolve()
    for part in resolved_path.parts:
        lowered_part = part.lower()
        if any(marker in lowered_part for marker in ("omega", "sigma", "sbrf")):
            match = re.search(r"\d+", part)
            if match:
                return match.group()

    match = re.search(r"\d{4,}", str(resolved_path))
    if not match:
        raise ValueError(f"Не удалось найти login в пути: {workspace_root}")
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

## Facts
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
