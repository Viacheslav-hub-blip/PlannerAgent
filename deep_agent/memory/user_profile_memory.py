"""User profile memory initialization.

Contains:
- UserProfileMemory: user profile memory parameters.
- build_user_profile_memory_reference: creates memory reference without Spark query.
- ensure_user_profile_memory: creates user profile memory file when missing.
- extract_login_from_path: extracts login from runtime workspace path.
- fetch_user_info: reads full name from Spark addressbook.
- _build_user_profile_memory_content: builds markdown memory file.
- _login_in_memory: checks whether memory file contains current login.
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
    """Stores user profile memory parameters.

    Args:
        login: User login.
        namespace: LangGraph Store namespace for isolated memory.
        store: Store with the memory file.
        full_name: User full name or ``None``.
        memory_source: DeepAgents virtual memory file path.

    Returns:
        User profile memory parameters container.
    """

    login: str
    namespace: tuple[str, ...]
    store: Any
    full_name: str | None = None
    memory_source: str = USER_PROFILE_MEMORY_PATH

    @property
    def memory_path(self) -> str:
        """Returns DeepAgents memory file path.

        Args:
            None.

        Returns:
            Memory file path like ``/memories/user_profile.md``.
        """

        return self.memory_source


def build_user_profile_memory_reference(
    *,
    workspace_root: str | Path,
    memory_root: str | Path,
) -> UserProfileMemory:
    """Creates user profile memory reference without Spark query.

    Args:
        workspace_root: Runtime workspace used to extract login.
        memory_root: Directory for JSON memory files.

    Returns:
        User profile memory parameters without reading Spark tables.
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
    """Creates user profile memory file when it is missing.

    Args:
        profile: User profile memory reference.
        spark_session_factory: SparkSession factory from ``load_data`` tool.

    Returns:
        Memory file content or ``None``.
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
    """Extracts numeric login from runtime workspace path.

    Args:
        workspace_root: Agent runtime workspace path.

    Returns:
        First numeric fragment from workspace directory name.

    Raises:
        ValueError: If numeric login is not found.
    """

    directory_name = Path(workspace_root).expanduser().resolve().name
    match = re.search(r"\d+", directory_name)
    if not match:
        raise ValueError(f"Не удалось найти логин в пути: {workspace_root}")
    return match.group()


def fetch_user_info(spark: Any, login: str) -> str | None:
    """Reads user full name from Spark addressbook by sigma login.

    Args:
        spark: Active SparkSession.
        login: User login without domain prefix.

    Returns:
        User full name or ``None``.
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
    """Builds markdown content for user profile memory file.

    Args:
        login: User login.
        full_name: User full name.

    Returns:
        Markdown text for Store.
    """

    return f"""# User profile

login: {login}
name: {full_name}
"""


def _login_in_memory(content: str, login: str) -> bool:
    """Checks that memory file contains current login.

    Args:
        content: Memory file text.
        login: Current user login.

    Returns:
        ``True`` when file contains current login.
    """

    return f"login: {login}" in content
