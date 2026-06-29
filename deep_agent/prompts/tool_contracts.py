"""Описания публичных контрактов инструментов DeepAgent.

Содержит:
- WRITE_TODOS_TOOL_DESCRIPTION: описание инструмента ведения списка задач.
- TASK_TOOL_DESCRIPTION: описание инструмента запуска subagent.
- TOOL_DESCRIPTION_OVERRIDES: таблица переопределений описаний встроенных tools.
"""

from __future__ import annotations

WRITE_TODOS_TOOL_DESCRIPTION = """
write_todos
---
Описание:
Поддерживает актуальный checklist текущей задачи.

Вход:
- список задач с коротким названием, статусом и необязательным expected result.

Выход:
- обновленный план, доступный агенту на следующих шагах выполнения.

Используй когда:
- задачу нужно разбить на несколько проверяемых шагов;
- статус уже запланированных шагов изменился.
""".strip()

TASK_TOOL_DESCRIPTION = """
task
---
Описание:
Запускает одного subagent и возвращает его финальный report.

Доступные subagents:
{available_agents}

Вход:
- `subagent_type`: имя subagent из списка available subagents.
- `description`: задача subagent с inputs, constraints, expected result и stopping condition.

Выход:
- текстовый report от subagent о выполненной работе, найденных фактах, созданных artifacts, checks и limitations.

Используй когда:
- изолированная задача должна быть выполнена в отдельном context;
- результат subagent нужен как compact report;
- code/workspace task требует цепочки search, reading, editing, validation или project inspection, а не проверки
  одного known file.

Не используй когда:
- next action - один маленький direct tool call вне code/workspace investigation или modification chain;
- у текущего agent уже достаточно verified evidence для ответа;
- delegation только повторит known context.

Плохой пример:
```text
task(subagent_type="<subagent-name>", description="Fix paths")
```

Хороший пример:
```text
task(
  subagent_type="<subagent-name>",
  description="
Objective: fix incorrect workspace path handling.
Scope: /deep_agent/runtime/python_sandbox.py and tests.
Constraints: no broad rewrite, preserve existing API except documented python tool contract.
Expected report: changed files, commands run, test results, limitations.
Stopping condition: focused tests pass or blocker with evidence.
"
)
```
""".strip()

TOOL_DESCRIPTION_OVERRIDES = {
    "write_todos": WRITE_TODOS_TOOL_DESCRIPTION,
    "task": TASK_TOOL_DESCRIPTION,
    "ls": """
ls
---
Описание:
Показывает содержимое одной директории.

Вход:
- `path`: абсолютный path директории в файловом namespace tools.
- Используй canonical POSIX workspace paths, например `/` или `/deep_agent/`; не передавай Windows paths.

Выход:
- список files и subdirectories или error message для inaccessible/missing path.

Используй когда:
- нужно inspect contents известной directory;
- нужна проверка существования directory.
""".strip(),
    "read_file": """
read_file
---
Описание:
Читает text file.

Вход:
- `file_path`: абсолютный file path в файловом namespace tools.
- `offset`: первая строка для чтения при pagination.
- `limit`: maximum number of lines.
- Используй canonical POSIX workspace paths, например `/report.md`; не передавай Windows paths.

Выход:
- requested text fragment и metadata о прочитанном диапазоне.
- content может отображаться с line numbers или service notices; эти prefixes не являются частью file content.

Формат вызова:
- передавай path через `file_path`;
- если file прочитан не полностью, запроси next fragment с новым `offset`.

Пример:
```text
read_file(file_path="/deep_agent/prompts/supervisor.py", offset=1, limit=120)
```

Используй когда:
- нужен source code, configuration, documentation или другой text artifact.

Ограничения:
- tool не предназначен для binary files;
- при переносе текста в `edit_file` убирай display-only line numbers, tabs и pagination notices из fragment.
""".strip(),
    "write_file": """
write_file
---
Описание:
Записывает text file.

Вход:
- target file path;
- complete new text content для file.
- Используй canonical POSIX workspace paths, например `/report.md`; не передавай Windows paths.

Выход:
- write result plus verification notice или error message, если file cannot be read back after writing.

Используй когда:
- result должен быть сохранен как text file;
- нужно создать или обновить `.py` файл: сначала прочитай текущий файл, затем передай в `content` полное обновленное содержимое с минимально необходимыми изменениями;
- complete content existing text file должен быть intentionally replaced;
- task names an exact output file и final deliverable must be written to that exact file.

Пример:
```text
write_file(file_path="/summary.md", content="<complete markdown report>")
```

Ограничения:
- tool работает с text files;
- tool overwrites existing file at the same path; не создавай duplicate filenames с suffixes вроде `_final`,
  `_final_final` или `_new` после successful write;
- не записывай helper script вместо requested output file; scripts - только intermediate tools;
- не оставляй requested output files empty или placeholders, если user explicitly не просил это;
- `/` - configured user workspace root;
- `/artifacts` reserved for data exports, offloaded table results и intermediate transformation outputs; не сохраняй
  every user-facing file there by default;
- `/deep_agent/` - agent implementation directory, not output folder;
- не write under `/deep_agent/`, если task explicitly не changes agent code, prompts, tests или skills;
- для `.py` файлов используй `write_file` даже при точечных изменениях: сохраняй остальной текст файла без необоснованных правок.
""".strip(),
    "edit_file": """
edit_file
---
Описание:
Редактирует existing text file, заменяя exact text fragment.

Вход:
- `file_path`: target file path;
- `old_string`: exact text fragment to replace;
- `new_string`: replacement text fragment;
- `replace_all`: replace every occurrence instead of one unique occurrence.
- Используй canonical POSIX workspace paths, например `/deep_agent/prompts/coding.py`; не передавай Windows paths.

Выход:
- replacement result plus verification notice или error message, если file cannot be read back after editing.

Используй когда:
- existing text file needs a local change.

Пример:
```text
edit_file(
  file_path="/deep_agent/prompts/coding.py",
  old_string="exact existing fragment without line-number prefixes",
  new_string="replacement fragment"
)
```

Ограничения:
- fragment to replace must be found unambiguously in the file;
- strip display-only line-number prefixes copied from `read_file` before filling `old_string` или `new_string`;
- если tool reports string not found, измени fragment using verified file content instead of repeating same failed edit;
- `/deep_agent/` is the agent implementation directory and should be edited only for explicit agent code, prompt,
  test или skill changes;
- tool не предназначен для binary files или generated files, которые should be updated by a generator.
""".strip(),
    "glob": """
glob
---
Описание:
Находит files по glob pattern.

Вход:
- `pattern`: glob pattern, например `**/*.md`;
- `path`: base search directory.
- Используй canonical POSIX workspace paths, например `/` или `/deep_agent/`; не передавай Windows paths.

Выход:
- list of paths matching the pattern.

Используй когда:
- files нужно найти по name, extension или directory structure.
""".strip(),
    "grep": """
grep
---
Описание:
Ищет text in files.

Вход:
- `pattern`: text to search for;
- `path`: search directory;
- `glob`: file filter;
- `output_mode`: output mode, например `files_with_matches`, `content` или `count`.
- Используй canonical POSIX workspace paths, например `/` или `/deep_agent/`; не передавай Windows paths.

Выход:
- matching content, files with matches или match counts depending on `output_mode`.

Формат вызова:
- передавай search text через `pattern`;
- `path` points to a directory;
- single file name can be passed through `glob`;
- передавай одну search phrase за call; если нужно several alternatives, make separate calls или use Python scan.

Используй когда:
- нужно найти symbol, call, configuration key, text или artifact mention.

Ограничения:
- `pattern` treated as plain text, unless tool implementation declares another search mode;
- если repeated searches не дают useful matches, измени `path`/`glob` from verified context или switch strategy
  instead of retrying equivalent searches.
""".strip(),
    "execute": """
execute
---
Описание:
Запускает non-interactive shell command в tool working directory.

Вход:
- command to run;
- when supported by runtime: timeout, working directory и additional execution parameters.
- Workspace-absolute paths returned by filesystem tools, например `/VLM PRES.ipynb`, mapped to real shell paths.
  Quote paths that contain spaces.

Выход:
- command exit code, stdout и stderr.

Используй когда:
- нужно run tests, linter, formatter, type checker, build, generator или diagnostic command;
- command output нужен как verifiable observation;
- нужны filesystem operations вроде copy, move, remove или directory creation.

Не используй когда:
- нужно только read/edit text file;
- `python` лучше подходит для data calculation over existing artifact;
- command requires API keys, secrets, interactive input или long-running services.

Пример:
```text
execute(command="python -m pytest tests/test_filesystem_path_contract.py -q")
execute(command="jupyter nbconvert --to script \"/VLM PRES.ipynb\" --output \"/VLM_PRES.py\"")
```

Плохой пример:
```text
execute(command="type deep_agent\\agent.py")
```

Хороший пример:
```text
read_file(file_path="/deep_agent/agent.py", offset=1, limit=120)
```

Ограничения:
- command must not require interactive input;
- tool must not be used for commands requiring secrets или API keys;
- use filesystem tools for ordinary text read/write/edit operations; use shell for tests, builds, diagnostics,
  package commands и copy/move operations;
- не embed multi-line content inside a double-quoted shell string;
- avoid complex `python -c` one-liners with loops, branches, functions, classes или context managers after semicolons;
  for data/intermediate transformations write a small script under `/artifacts`, otherwise use an appropriate
  repository/workspace path или single-quoted heredoc.
""".strip(),
}
