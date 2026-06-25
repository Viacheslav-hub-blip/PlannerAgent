"""Тесты prompt-контракта coding-agent.

Содержит:
- CodingPromptTests: проверки правил итеративного редактирования кода.
"""

from __future__ import annotations

import unittest

from deep_agent.prompts.coding import CODING_AGENT_PROMPT


class CodingPromptTests(unittest.TestCase):
    """Проверяет ключевые правила prompt-а coding-agent."""

    def test_prompt_requires_iterative_editing_for_non_trivial_changes(self) -> None:
        """Проверяет контракт маленьких правок с промежуточной валидацией.

        Returns:
            ``None``.
        """

        self.assertIn("## Iterative Editing", CODING_AGENT_PROMPT)
        self.assertIn("small edit-and-check loop", CODING_AGENT_PROMPT)
        self.assertIn("Do not rewrite a whole existing source file", CODING_AGENT_PROMPT)
        self.assertIn("Apply one coherent `edit_file` change", CODING_AGENT_PROMPT)
        self.assertIn("Run the narrowest relevant check immediately", CODING_AGENT_PROMPT)
        self.assertIn("Use `python` as a scratch REPL", CODING_AGENT_PROMPT)
        self.assertIn("Do not use the REPL as a hidden source-file editor", CODING_AGENT_PROMPT)
        self.assertIn("For existing Jupyter notebooks, convert to percent-script", CODING_AGENT_PROMPT)


if __name__ == "__main__":
    unittest.main()
