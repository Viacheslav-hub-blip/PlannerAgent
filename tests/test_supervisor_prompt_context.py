"""Проверки prompt-блоков supervisor без импорта всего deep_agent_test пакета."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module(relative_path: str, module_name: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


prompts = _load_module("deep_agent_test/prompts.py", "prompts_under_test")


class SupervisorPromptContextTests(unittest.TestCase):
    """Проверяет состав prompt-блоков, на которых supervisor строит план."""

    def test_skill_front_matter_available_for_index(self) -> None:
        skills_root = ROOT / "deep_agent_test" / "skills"
        names: set[str] = set()
        for skill_path in skills_root.rglob("SKILL.md"):
            content = skill_path.read_text(encoding="utf-8")
            for line in content.splitlines()[:20]:
                if line.startswith("name:"):
                    names.add(line.split(":", 1)[1].strip().strip('"'))
        self.assertIn("hit-table", names)
        self.assertIn("cards-event-table", names)
        self.assertIn("uko-event-table", names)

    def test_planning_prompt_blocks_put_index_before_partial_preview(self) -> None:
        index_block = prompts.SKILLS_INDEX_CONTEXT_PROMPT_TEMPLATE.format(
            skills_index=json.dumps(
                [{"path": "/skills/hit-table/SKILL.md", "name": "hit-table", "description": "hits"}],
                ensure_ascii=False,
            )
        )
        preview_block = prompts.PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE.format(context="preview text")
        combined = f"{prompts.SYSTEM_PROMPT}\n\n{index_block}\n\n{preview_block}"

        self.assertIn("Skills Index", combined)
        self.assertIn("Partial Preloaded Skills Preview", combined)
        self.assertLess(combined.index("Skills Index"), combined.index("Partial Preloaded Skills Preview"))
        self.assertIn("read_file", combined)
        self.assertIn("write_todos", combined)
        self.assertIn("Skills Before Planning Policy", combined)


if __name__ == "__main__":
    unittest.main()
