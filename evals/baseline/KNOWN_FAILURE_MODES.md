# Известные failure modes до изменений

1. Skill selector при исключении или пустом результате загружал все skills.
2. Пустой список выбранных skills невозможно было отличить от ошибки selector.
3. Полный оставшийся Skills Index добавлялся в каждый model call.
4. `ToolLoopGuard` сравнивал только имя tool и мог блокировать исправленные аргументы.
5. DeepAgents автоматически добавлял `general-purpose` subagent.
6. Одновременно присутствовали встроенные `glob/grep` и `glob_search/grep_search`.
7. Generic `execute` оставался видимым рядом с ограниченным `execute_python_code`.
8. Текущий txt trace не являлся типизированным append-only `trace.jsonl`.
9. Baseline-сценарии и количественный отчёт ранее не были зафиксированы в репозитории.
