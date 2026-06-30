# Tools

Папка содержит LangChain tools ядра:

- `load_data_spark_tool.py` — сборка production `load_data` поверх Spark.
- `python_execution_tool.py` — persistent Python tool для расчетов и работы с artifacts.
- `skill_loader_tool.py` — загрузка выбранных `SKILL.md` и связанных markdown-файлов.
- `project_structure_tool.py` — краткая карта структуры проекта без содержимого skills.
- `jupyter_notebook_tool.py` — конвертация notebook/script formats.
- `refactor_review_tool.py` — локальная проверка результата refactor-задач.

Схемы, parser и вспомогательная логика `load_data` находятся в `deep_agent/data_processing/`.
