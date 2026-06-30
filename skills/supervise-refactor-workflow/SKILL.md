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

Если нужный workflow не загружен, сначала загрузи skills через штатный tool:

```text
load_skills(
  skill_names="/skill_1/SKILL.md, /skill_2/SKILL.md",
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

Пример реального вызова `task` из обвязки:

```text
task(
  subagent_type="coding-agent",
  description="
Objective: отрефакторить существующий notebook без изменения аналитической логики.
Scope: /file_1.ipynb
Skills: /skill_1/SKILL.md, /skill_2/SKILL.md.
Constraints:
- сохранить исходную последовательность вычислений;
- markdown должен быть реальными markdown-ячейками, а не комментариями внутри code cells;
- над измененными строками должны быть короткие комментарии через #.
Expected artifacts:
- обновленный /file_1.ipynb;
- промежуточный percent-script только если он нужен для конвертации.
"
)
```

## Проверка существования файлов

После report от `coding-agent` supervisor обязан проверить файлы сам. Для одного
известного файла достаточно `read_file` или `ls` родительской директории.

Примеры реальных filesystem-вызовов:

```text
ls(path="/dir_1")
```

```text
read_file(file_path="/file_1.py", offset=1, limit=80)
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
Scope: /file_1.ipynb
Skills: /skill_1/SKILL.md, /skill_2/SKILL.md.
Do not make broad refactoring. Read the changed artifact and validate it.
Checklist:
- файл существует и читается;
- для notebook есть markdown-ячейки, а не '# Markdown:' внутри code cells;
- при редактировании notebook использован convert_jupyter_notebook;
- код не склеен в одну ячейку;
- исходная логика и важные вычисления не потеряны;
- измененные строки снабжены короткими комментариями через #;
- новые или измененные функции и классы имеют русские docstring;
- type hints добавлены там, где изменялись функции или классы;
- выполнена доступная проверка: compileall или scripts/check_project_quality.py или обоснованное объяснение,
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
  source_path="/file_1.ipynb",
  output_path="/file_1.py"
)
```

Конвертация percent-script обратно в notebook:

```text
convert_jupyter_notebook(
  mode="py_to_ipynb",
  source_path="/file_1.py",
  output_path="/file_1.ipynb"
)
```

Запись обновленного `.py` percent-script:

```text
write_file(file_path="/file_1.py", content="<complete updated percent-script>")
```

Точечное редактирование существующего text artifact:

```text
edit_file(
  file_path="/file_2.md",
  old_string="<verified exact fragment>",
  new_string="<updated fragment>"
)
```

Проверки через shell wrapper:

```text
execute(command="python -m compileall -q file_1.py")
execute(command="python scripts/check_project_quality.py")
execute(command="python -m ruff check file_1.py")
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

