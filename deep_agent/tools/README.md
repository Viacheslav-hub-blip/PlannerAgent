# Tools

Папка содержит только реализации LangChain tools продукта:

- `load_data` через Spark или совместимую фабрику data tools;
- `python` для persistent REPL-расчётов по выгруженным артефактам;
- `load_skills` для загрузки `SKILL.md`;
- `analyze_image(image_path, query)` для анализа локальных изображений через Qwen VLM;
- `skill_loader.py` для materialized-загрузки skills.

Инфраструктура вокруг tools вынесена из этой папки:

- wrapper результатов data-tools находится в `deep_agent/data/result_wrapper.py`;
- MCP loader находится в `deep_agent/integrations/mcp.py`;
- fake Spark backend намеренно находится в `tests/support`.
