"""Тесты middleware контракта путей filesystem tools.

Содержит:
- FakeBackend: тестовый backend проверочного чтения.
- FilesystemPathContractTests: проверки нормализации путей и подтверждения записи.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deep_agent.middleware.filesystem_path_contract import (
    FilesystemPathContractMiddleware,
    normalize_filesystem_tool_path,
)


class FakeBackend:
    """Тестовый backend для проверочного чтения файлов.

    Args:
        files: Словарь ``canonical path -> content``.

    Returns:
        Backend с методом ``read``, совместимым с проверкой middleware.
    """

    def __init__(self, files: dict[str, str] | None = None) -> None:
        """Сохраняет тестовые файлы.

        Args:
            files: Начальное содержимое виртуальных файлов.

        Returns:
            ``None``.
        """

        self.files = dict(files or {})

    def read(self, file_path: str, offset: int = 0, limit: int = 10_000) -> SimpleNamespace:
        """Возвращает содержимое файла или ошибку отсутствия.

        Args:
            file_path: Canonical POSIX-путь файла.
            offset: Смещение строк, не используется в тесте.
            limit: Максимум строк, не используется в тесте.

        Returns:
            ``SimpleNamespace`` с полями ``error`` и ``file_data``.
        """

        del offset, limit
        if file_path not in self.files:
            return SimpleNamespace(error="not found", file_data=None)
        return SimpleNamespace(error=None, file_data={"content": self.files[file_path]})


class FilesystemPathContractTests(unittest.TestCase):
    """Проверяет canonical path contract и подтверждение записи."""

    def test_normalizes_workspace_os_path_to_posix_tool_path(self) -> None:
        """Преобразует OS-путь внутри workspace в canonical ``/...`` путь.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            report_path = workspace / "artifacts" / "result.md"

            normalized = normalize_filesystem_tool_path(str(report_path), workspace)

        self.assertEqual(normalized, "/artifacts/result.md")

    def test_normalizes_relative_path_to_workspace_posix_path(self) -> None:
        """Преобразует относительный путь в путь от корня workspace.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()

            normalized = normalize_filesystem_tool_path("artifacts/result.md", workspace)

        self.assertEqual(normalized, "/artifacts/result.md")

    def test_write_file_result_is_verified_after_handler(self) -> None:
        """Добавляет подтверждение, если файл читается после записи.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            backend = FakeBackend()
            middleware = FilesystemPathContractMiddleware(
                workspace_root=workspace,
                backend=backend,
            )
            request = ToolCallRequest(
                tool_call={
                    "id": "call-write",
                    "name": "write_file",
                    "args": {
                        "file_path": "artifacts/result.md",
                        "content": "ok\n",
                    },
                },
                tool=None,
                state={},
                runtime=None,
            )

            def handler(call: ToolCallRequest) -> ToolMessage:
                """Имитирует успешную запись через filesystem tool.

                Args:
                    call: Нормализованный tool call.

                Returns:
                    Успешный ``ToolMessage``.
                """

                file_path = call.tool_call["args"]["file_path"]
                backend.files[file_path] = call.tool_call["args"]["content"]
                return ToolMessage(
                    content="written",
                    tool_call_id="call-write",
                    name="write_file",
                    status="success",
                )

            result = middleware.wrap_tool_call(request, handler)

        self.assertEqual(result.status, "success")
        self.assertIn("FilesystemVerification", result.content)
        self.assertIn("/artifacts/result.md", result.content)

    def test_write_file_result_becomes_error_when_readback_differs(self) -> None:
        """Возвращает ошибку, если проверочное чтение не совпало с записанным текстом.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            backend = FakeBackend({"/artifacts/result.md": "different\n"})
            middleware = FilesystemPathContractMiddleware(
                workspace_root=workspace,
                backend=backend,
            )
            request = ToolCallRequest(
                tool_call={
                    "id": "call-write",
                    "name": "write_file",
                    "args": {
                        "file_path": "/artifacts/result.md",
                        "content": "ok\n",
                    },
                },
                tool=None,
                state={},
                runtime=None,
            )

            result = middleware.wrap_tool_call(
                request,
                lambda _: ToolMessage(
                    content="written",
                    tool_call_id="call-write",
                    name="write_file",
                    status="success",
                ),
            )

        self.assertEqual(result.status, "error")
        self.assertIn("FilesystemVerificationError", result.content)

if __name__ == "__main__":
    unittest.main()
