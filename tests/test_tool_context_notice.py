"""Тесты уведомлений и ошибок tool context middleware.

Содержит:
- ToolContextNoticeTests: проверки подсказок для неуспешных tool calls.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from deep_agent.middleware.tool_context_notice import (
    ToolContextNoticeMiddleware,
    build_tool_error_recovery_hint,
)


class ToolContextNoticeTests(unittest.TestCase):
    """Проверяет возврат ошибок инструментов агенту."""

    def test_tool_error_message_gets_recovery_hint(self) -> None:
        """Неуспешный tool result должен вернуться агенту с подсказкой восстановления.

        Returns:
            ``None``.
        """

        middleware = ToolContextNoticeMiddleware()
        request = SimpleNamespace(
            tool_call={"id": "call-error", "name": "write_file"}
        )
        result = middleware.wrap_tool_call(
            request,
            lambda _: ToolMessage(
                content="Error writing file: path already exists",
                tool_call_id="call-error",
                name="write_file",
                status="error",
            ),
        )

        self.assertEqual(result.status, "error")
        self.assertIn("Error writing file", result.content)
        self.assertIn(build_tool_error_recovery_hint(), result.content)

    def test_tool_exception_is_returned_to_agent_as_error_message(self) -> None:
        """Исключение tool handler должно попасть обратно агенту как ToolMessage.

        Returns:
            ``None``.
        """

        middleware = ToolContextNoticeMiddleware()
        request = SimpleNamespace(
            tool_call={"id": "call-boom", "name": "custom_tool"}
        )

        def raise_error(_: object) -> ToolMessage:
            """Выбрасывает тестовую ошибку инструмента.

            Args:
                _: Неиспользуемый запрос tool call.

            Returns:
                Не возвращает значение, потому что всегда выбрасывает исключение.

            Raises:
                ValueError: Всегда для проверки middleware.
            """

            raise ValueError("bad args")

        result = middleware.wrap_tool_call(request, raise_error)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.tool_call_id, "call-boom")
        self.assertEqual(result.name, "custom_tool")
        self.assertIn("ValueError: bad args", result.content)
        self.assertIn(build_tool_error_recovery_hint(), result.content)


if __name__ == "__main__":
    unittest.main()
