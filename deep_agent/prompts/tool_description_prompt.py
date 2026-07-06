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
Создает и поддерживает актуальный checklist текущей задачи.

Вход:
- список задач с названием, статусом и описанием

Выход:
- обновленный план, доступный агенту на следующих шагах выполнения.

Используй когда:
- задачу нужно разбить на несколько проверяемых шагов;
- статус уже запланированных шагов изменился.
- все задачи выполнены, необходимо завершить выполнение
""".strip()

TASK_TOOL_DESCRIPTION = """
task
---
Описание:
Запускает одного subagent и возвращает его отчет.

Доступные subagents:
{available_agents}

Вход:
- `subagent_type`: имя subagent из списка доступных subagents.
- `description`: задача subagent с входными данными, ожидаемым результатом , подробным описанием задачи со всеми необходимыми для выполнения данными

Выход:
- текстовый отчет subagent о выполненной работе, найденных фактах, созданных artifacts, проверках и ограничениях.

Используй когда:
- изолированный атомарный этап должен быть выполнен в отдельном контексте;
- задача по code/workspace требует цепочки поиска, чтения, редактирования, проверки или просмотра проекта, а не
  проверки одного известного файла.

Не используй когда:
- нужно делегировать микрошаг вроде "прочитай один файл", "проверь один путь" или "исправь одну строку" без завершенного
  результата;
- следующий шаг зависит от ответа subagent и проще выполнить его сразу текущими инструментами.

Правило размера задачи:
- делегируй не отдельные движения, а законченный крупный кусок работы: исследование -> правка/выгрузка -> проверка -> отчет;
- в `description` всегда указывай цель, границы файлов/данных, входные факты, ожидаемые artifacts/evidence,
  ограничения и условие остановки;
- если задача большая, разделяй её только на независимые атомарные части с непересекающимися файлами или источниками.

Плохой пример:
```text
task(subagent_type="<subagent-name>", description="Fix paths")
```

Хороший пример:
```text
task(
  subagent_type="<subagent-name>",
  description="
Цель: исправить некорректную обработку workspace-путей (пути).
Границы: /deep_agent/tools/python_execution_tool.py и связанные prompt-описания.
Ожидаемый результат: код изменен, проверка запущена, отчет содержит changed files, checks, limitations.
Условие остановки: правка внесена и подтверждена проверкой или найден blocker с evidence.
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
Возвращает список файлов одной директории.

Вход:
- `path`: абсолютный путь директории в файловом namespace tools.
- Используй канонические POSIX workspace paths, например `/` или `/deep_agent/`; не передавай Windows paths.

Выход:
- список файлов и поддиректорий или сообщение об ошибке для недоступного/отсутствующего пути.

Используй когда:
- нужно посмотреть содержимое известной директории;
- нужна проверка существования директории.
""".strip(),
    "read_file": """
read_file
---
Описание:
Читает текстовый файл.

Вход:
- `file_path`: абсолютный путь файла в файловом namespace tools.
- `offset`: первая строка для чтения при pagination.
- `limit`: максимальное число строк.
- Используй канонические POSIX workspace paths, например `/report.md`; не передавай Windows paths.

Выход:
- запрошенный текстовый фрагмент и metadata о прочитанном диапазоне.
- content может отображаться с номерами строк или служебными notices; эти prefixes не являются частью file content.

Формат вызова:
- передавай path через `file_path`;
- если file прочитан не полностью, запроси next fragment с новым `offset`.

Пример:
```text
read_file(file_path="/deep_agent/prompts/supervisor.py", offset=1, limit=120)
```

Используй когда:
- нужен исходный код, configuration, documentation или другой текстовый artifact.

Ограничения:
- tool не предназначен для binary files;
- при переносе текста в `edit_file` убирай отображаемые только в ответе номера строк, tabs и pagination notices из fragment.
""".strip(),
    "write_file": """
write_file
---
Описание:
Записывает файл.

Вход:
- целевой путь файла;
- полный новый текстовый content для file.
Выход:
- результат записи или сообщение об ошибке; после успешной записи результат дополняется
  `file_operation_verification` с проверенным путем, размером и preview первых строк.

Используй когда:
- результат должен быть сохранен как текстовый файл;
- нужно создать или обновить `.ipynb`: передай Python/percent-script, где `# %% [markdown]`
  и верхнеуровневые `#`-блоки станут markdown-ячейками, а остальной текст станет code-ячейками;
- нужно создать или обновить `.py` файл: сначала прочитай текущий файл, затем передай в `content` полное обновленное содержимое с минимально необходимыми изменениями;
- полный content существующего text file нужно намеренно заменить;
- задача называет точный output file и финальный результат должен быть записан именно туда.

Пример:
```text
write_file(file_path="/summary.md", content="<complete markdown report>")
```

Ограничения:
- tool работает с text files;
- tool перезаписывает существующий файл по тому же пути; не создавай duplicate filenames с suffixes вроде `_final`,
  `_final_final` или `_new` после успешной записи;
- если создаешь новый пользовательский файл и видишь риск совпадения имени, сначала проверь существование файла
  через `read_file`/`ls` или выбери явно согласованный другой путь;
- не записывай helper script вместо requested output file; scripts - только intermediate tools;
- не оставляй requested output files empty или placeholders, если пользователь явно не просил это;
- `/` - настроенный корень workspace пользователя;
- `/artifacts` предназначен для data exports, offloaded table results и intermediate transformation outputs; не сохраняй
  туда каждый user-facing file по умолчанию;
- `/deep_agent/` - директория реализации агента, а не output folder;
- не записывай в `/deep_agent/`, если задача явно не меняет agent code, prompts, tests или skills;
- для `.py` файлов используй `write_file` даже при точечных изменениях: сохраняй остальной текст файла без необоснованных правок.
""".strip(),
    "edit_file": """
edit_file
---
Описание:
Редактирует существующий текстовый файл, заменяя точный текстовый fragment.

Вход:
- `file_path`: целевой путь файла;
- `old_string`: точный текстовый fragment для замены;
- `new_string`: replacement text fragment;
- `replace_all`: заменить все вхождения вместо одного уникального.
- Используй канонические POSIX workspace paths, например `/deep_agent/prompts/coding.py`; не передавай Windows paths.

Выход:
- результат замены или сообщение об ошибке.

Используй когда:
- существующему текстовому файлу нужно локальное изменение.

Пример:
```text
edit_file(
  file_path="/deep_agent/prompts/coding.py",
  old_string="exact existing fragment without line-number prefixes",
  new_string="replacement fragment"
)
```

Ограничения:
- fragment для замены должен однозначно находиться в файле;
- убирай display-only префиксы номеров строк, скопированные из `read_file`, перед заполнением `old_string` или `new_string`;
- если tool сообщает, что строка не найдена, измени fragment по проверенному content файла вместо повтора той же ошибки;
- `/deep_agent/` - директория реализации агента, редактируй ее только для явных изменений agent code, prompt,
  test или skill;
- tool не предназначен для binary files или generated files, которые должен обновлять generator.
""".strip(),
    "glob": """
glob
---
Описание:
Находит files по glob pattern.

Вход:
- `pattern`: glob pattern, например `**/*.md`;
- `path`: базовая директория поиска.
- Используй канонические POSIX workspace paths, например `/` или `/deep_agent/`; не передавай Windows paths.

Выход:
- список путей, соответствующих pattern.

Используй когда:
- files нужно найти по имени, extension или структуре директорий.
""".strip(),
    "grep": """
grep
---
Описание:
Ищет текст в файлах.

Вход:
- `pattern`: текст для поиска;
- `path`: директория поиска;
- `glob`: фильтр файлов;
- `output_mode`: режим вывода, например `files_with_matches`, `content` или `count`.
- Используй канонические POSIX workspace paths, например `/` или `/deep_agent/`; не передавай Windows paths.

Выход:
- найденный content, files with matches или число совпадений в зависимости от `output_mode`.

Формат вызова:
- передавай search text через `pattern`;
- `path` указывает на директорию;
- имя одного файла можно передать через `glob`;
- передавай одну search phrase за call; если нужно несколько альтернатив, сделай отдельные calls или используй Python scan.

Используй когда:
- нужно найти symbol, call, configuration key, text или упоминание artifact.

Ограничения:
- `pattern` считается plain text, если реализация tool не объявляет другой режим поиска;
- если повторные поиски не дают полезных совпадений, измени `path`/`glob` по проверенному контексту или смени стратегию
  вместо повторения эквивалентных поисков.
""".strip(),
    "execute": """
execute
---
Описание:
Запускает неинтерактивную shell command в рабочей директории tool.

Вход:
- команда для запуска;
- если runtime поддерживает: timeout, working directory и дополнительные параметры выполнения.
- Workspace-absolute paths, возвращенные filesystem tools, например `/DEMO PRES.ipynb`, отображаются в реальные shell paths.
  Заключай пути с пробелами в кавычки.

Выход:
- exit code команды, stdout и stderr.

Используй когда:
- нужно запустить tests, linter, formatter, type checker, build, generator или diagnostic command;
- command output нужен как проверяемое наблюдение;
- нужны filesystem operations вроде copy, move, remove или создания директории.

Не используй когда:
- нужно только прочитать/отредактировать text file;
- `python` лучше подходит для расчетов по existing artifact;
- command требует API keys, secrets, interactive input или long-running services.

Пример:
```text
execute(command="python scripts/check_project_quality.py")
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
- command не должна требовать interactive input;
- tool нельзя использовать для команд, требующих secrets или API keys;
- используй filesystem tools для обычных операций чтения/записи/редактирования текста; shell используй для tests,
  builds, diagnostics, package commands и copy/move operations;
- не используй shell-конвертацию notebook в файл с фиксированным именем, если target может существовать; для notebook
  используй `convert_jupyter_notebook`, где перезапись запрещена по умолчанию;
- не вставляй multi-line content внутрь shell-строки в двойных кавычках;
- избегай сложных `python -c` one-liners с loops, branches, functions, classes или context managers после точки с
  запятой; для data/intermediate transformations запиши небольшой script в `/artifacts`, иначе используй подходящий
  путь repository/workspace или single-quoted heredoc.
""".strip(),
}
