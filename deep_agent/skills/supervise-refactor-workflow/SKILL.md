---
name: supervise-refactor-workflow
description: "Используй только supervisor-ом для управления задачами рефакторинга, правки существующего кода и notebook: делегировать изменение coding-agent, проверить существование файлов, запустить вторую validation-делегацию coding-agent, проверить markdown-ячейки, комментарии, docstring, сохранение логики и подготовить финальный отчет с фрагментами было/стало."
---

# Supervisor workflow для рефакторинга

Этот skill задает порядок приемки результата рефакторинга. Он предназначен для
`supervisor`. `coding-agent` использует этот skill только как критерии приемки, а
реализацию выполняет по `refactor-files`, `jupyter-notebook` и другим профильным
skills.

## Когда применять

Применяй workflow, когда пользователь просит:

- отрефакторить существующий код, prompt, skill, config или notebook;
- улучшить структуру, docstring, type hints, комментарии или markdown-ячейки;
- исправить код с сохранением текущей логики;
- показать, что изменилось в формате "было/стало".

## Обязательный цикл

1. Загрузить или использовать уже выбранные профильные skills:
   - `refactor-files` для требований к рефакторингу;
   - `jupyter-notebook` для `.ipynb` и percent-script;
   - `code-workspace` для работы с файлами workspace.
2. Делегировать основное изменение `coding-agent`.
3. Дождаться ответа от `coding-agent` 
4. Проверить существование каждого измененного файла через filesystem tools.
5. Делегировать `coding-agent` отдельную validation-задачу по уже измененным файлам.
6. Если validation вернула `FAIL`, делегировать исправление только найденных проблем и
   повторить validation один раз.
7. Финальный ответ дать на русском языке и включить:
   - список измененных файлов;
   - краткое описание изменений;
   - короткие фрагменты "было/стало";
   - результат validation;
   - проверки, которые были или не были выполнены.

## Делегация основного рефакторинга

Все примеры ниже показывают синтаксис tools из обвязки. Не считай paths, имена
файлов и команды из примеров подтвержденными фактами. Перед вызовом проверь, что
tool доступен текущему агенту, а path найден через runtime context, skills index,
tool output или явно указан пользователем.

Если нужный workflow не загружен, сначала загрузи skills через штатный tool:

```text
load_skills(
  skill_names="/deep_agent/skills/supervise-refactor-workflow/SKILL.md, /deep_agent/skills/refactor-files/SKILL.md",
  already_loaded=""
)
```

Для многошагового рефакторинга веди checklist:

```text
write_todos([
  {"content": "Делегировать рефакторинг coding-agent", "status": "pending"},
  {"content": "Проверить существование измененных файлов", "status": "pending"},
  {"content": "Делегировать validation-проход", "status": "pending"},
  {"content": "Собрать отчет было/стало", "status": "pending"}
])
```

Пример формы вызова `task` из обвязки:

```text
task(
  subagent_type="coding-agent",
  description="
Objective: отрефакторить существующий notebook без изменения аналитической логики.
Scope: /reports/client_analysis.ipynb
Skills: /deep_agent/skills/refactor-files/SKILL.md, /deep_agent/skills/jupyter-notebook/SKILL.md.
Constraints:
- сохранить исходную последовательность вычислений;
- markdown должен быть реальными markdown-ячейками, а не комментариями внутри code cells;
- неочевидная измененная логика должна быть пояснена короткими комментариями через #.
Expected artifacts:
- обновленный /reports/client_analysis.ipynb;
- промежуточный percent-script только если он нужен для конвертации.
"
)
```

## Проверка существования файлов

После report от `coding-agent` supervisor обязан проверить файлы сам. Для одного
известного файла достаточно `read_file` или `ls` родительской директории.

Примеры формы filesystem-вызовов:

```text
ls(path="/reports")
```

```text
read_file(file_path="/deep_agent/skills/refactor-files/SKILL.md", offset=1, limit=80)
```

Если изменен `.ipynb`, не читай большой JSON полностью без необходимости. Проверь
существование через `ls`, а содержательную проверку делегируй `coding-agent`.

## Делегация validation-прохода

Validation должна быть отдельной задачей. Не проси того же subagent "просто
продолжить"; передай ему чеклист приемки и запрети новые широкие правки.

Пример validation-вызова:

```text
task(
  subagent_type="coding-agent",
  description="
Objective: проверить качество уже измененного файла после рефакторинга.
Scope: /reports/client_analysis.ipynb
Skills: /deep_agent/skills/refactor-files/SKILL.md, /deep_agent/skills/jupyter-notebook/SKILL.md.
Do not make broad refactoring. Read the changed artifact and validate it.
Checklist:
- файл существует и читается;
- для notebook есть markdown-ячейки, а не '# Markdown:' внутри code cells;
- при редактировании notebook использован convert_jupyter_notebook;
- код не склеен в одну ячейку;
- исходная логика и важные вычисления не потеряны;
- неочевидная измененная логика пояснена короткими комментариями через #;
- новые или измененные функции и классы имеют русские docstring;
- type hints добавлены там, где изменялись функции или классы;
- выполнена доступная проверка: ruff, compileall, pytest или обоснованное объяснение,
  почему проверка неприменима.
Expected report format:
PASS/FAIL.
Evidence: files checked, commands run, relevant counts or fragments.
Problems: concrete missing comments, missing markdown cells, lost logic or failed checks.
If FAIL: propose minimal fix scope only.
Stopping condition: checklist completed with PASS/FAIL and evidence.
"
)
```

## Примеры команд для coding-agent

Supervisor не обязан выполнять эти команды сам, но может включать их в delegated
task как ожидаемые инструменты или checks.

Конвертация notebook в percent-script:

```text
convert_jupyter_notebook(
  mode="ipynb_to_py",
  source_path="/reports/client_analysis.ipynb",
  output_path="/reports/client_analysis.py"
)
```

Конвертация percent-script обратно в notebook:

```text
convert_jupyter_notebook(
  mode="py_to_ipynb",
  source_path="/reports/client_analysis.py",
  output_path="/reports/client_analysis.ipynb"
)
```

Запись обновленного `.py` percent-script:

```text
write_file(file_path="/reports/client_analysis.py", content="<complete updated percent-script>")
```

Проверки через shell wrapper:

```text
execute(command="python -m compileall -q deep_agent/prompts/coding.py")
execute(command="python -m pytest tests/test_coding_prompt.py -q")
execute(command="python -m ruff check deep_agent/prompts/coding.py")
```

Если `ruff` не установлен, это не blocker само по себе. Report должен явно сказать,
какой interpreter использовался и какую ошибку вернул tool.

## Acceptance checklist

Считай результат готовым только если:

- измененные файлы существуют;
- validation-задача вернула `PASS` или дала исправленный после одного retry результат;
- для notebook сохранены markdown/code cells и использован `convert_jupyter_notebook`;
- комментарии и docstring соответствуют правилам `refactor-files`;
- финальный ответ содержит не только "готово", но и фрагменты "было/стало";

## Финальный ответ

Форматируй финальный ответ кратко:

```text
Изменено:
1. /path/to/file.py
   Было:
   <короткий фрагмент>
   Стало:
   <короткий фрагмент>
```
