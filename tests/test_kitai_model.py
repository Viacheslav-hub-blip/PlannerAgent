"""Тесты нормализации сообщений для корпоративной KitAI-модели.

Содержит классы:
- KitaiMessageNormalizationTests: проверка строкового content и сохранения metadata.
"""

from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deep_agent.models.kitai import content_to_text, normalize_kitai_messages


class KitaiMessageNormalizationTests(unittest.TestCase):
    """Проверяет совместимость сообщений DeepAgents с KitAI SDK."""

    def test_converts_text_content_blocks_to_string(self) -> None:
        """Преобразует список текстовых блоков в обычную строку.

        Returns:
            ``None``.
        """

        message = SystemMessage(
            content=[
                {"type": "text", "text": "Первая часть"},
                {"type": "text", "text": "Вторая часть"},
            ]
        )

        normalized = normalize_kitai_messages([message])

        self.assertEqual(normalized[0].content, "Первая часть\nВторая часть")

    def test_preserves_ai_tool_calls_and_adds_functions_state_id(self) -> None:
        """Сохраняет tool calls при заполнении пустого AI content.

        Returns:
            ``None``.
        """

        tool_call = {
            "name": "load_data",
            "args": {"query": "test"},
            "id": "call-1",
            "type": "tool_call",
        }
        message = AIMessage(content="", tool_calls=[tool_call])

        normalized = normalize_kitai_messages(message)

        self.assertEqual(normalized.tool_calls, [tool_call])
        self.assertIn("functions_state_id", normalized.additional_kwargs)
        self.assertIsInstance(normalized.content, str)
        self.assertTrue(normalized.content)

    def test_keeps_plain_human_message_unchanged_in_value(self) -> None:
        """Сохраняет текст обычного пользовательского сообщения.

        Returns:
            ``None``.
        """

        message = HumanMessage(content="Привет")

        normalized = normalize_kitai_messages(message)

        self.assertEqual(normalized.content, "Привет")
        self.assertIsNot(normalized, message)

    def test_serializes_non_text_block_without_data_loss(self) -> None:
        """Сериализует неизвестный content block в JSON.

        Returns:
            ``None``.
        """

        content = {"type": "custom", "value": 42}

        self.assertEqual(
            content_to_text(content),
            '{"type": "custom", "value": 42}',
        )


if __name__ == "__main__":
    unittest.main()
